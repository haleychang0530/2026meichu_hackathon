from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import sqlite3
import time
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterable, Sequence

from .chunking import IngestReport, ingest_manifest, load_manifest
from .embeddings import EmbeddingBackend, EmbeddingError, normalize_for_embedding, pack_vector, unpack_vector
from .models import RAG_INDEX_FORMAT, RagChunk, RagManifest, RetrievalResult


class IndexError(RuntimeError):
    """Raised when a persistent Local RAG index is invalid."""


def _working_set_bytes() -> int:
    if os.name == "nt":
        import ctypes
        from ctypes import wintypes

        class ProcessMemoryCounters(ctypes.Structure):
            _fields_ = [
                ("cb", wintypes.DWORD),
                ("PageFaultCount", wintypes.DWORD),
                ("PeakWorkingSetSize", ctypes.c_size_t),
                ("WorkingSetSize", ctypes.c_size_t),
                ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                ("PagefileUsage", ctypes.c_size_t),
                ("PeakPagefileUsage", ctypes.c_size_t),
            ]

        counters = ProcessMemoryCounters()
        counters.cb = ctypes.sizeof(counters)
        process = ctypes.windll.kernel32.GetCurrentProcess()
        get_info = ctypes.windll.psapi.GetProcessMemoryInfo
        get_info.argtypes = [wintypes.HANDLE, ctypes.POINTER(ProcessMemoryCounters), wintypes.DWORD]
        get_info.restype = wintypes.BOOL
        if get_info(process, ctypes.byref(counters), counters.cb):
            return int(counters.PeakWorkingSetSize)
        return 0
    try:
        import resource

        value = int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
        return value * (1024 if os.uname().sysname == "Linux" else 1)
    except (ImportError, AttributeError, OSError):
        return 0


def _dot(left: Sequence[float], right: Sequence[float]) -> float:
    return sum(a * b for a, b in zip(left, right, strict=True))


def _keyword_tokens(text: str) -> tuple[str, ...]:
    value = normalize_for_embedding(text)
    if not value:
        return ()
    tokens = list(re.findall(r"[^\W_]+(?:[-'’][^\W_]+)*", value, flags=re.UNICODE))
    # CJK words are not whitespace-delimited. Add single characters and
    # adjacent pairs so exact Hanji queries remain useful in the fallback.
    compact = "".join(char for char in value if not char.isspace())
    cjk = [char for char in compact if "\u3400" <= char <= "\u9fff"]
    tokens.extend(cjk)
    tokens.extend("".join(cjk[index : index + 2]) for index in range(max(0, len(cjk) - 1)))
    return tuple(dict.fromkeys(token for token in tokens if token))


@dataclass(frozen=True, slots=True)
class BuildReport:
    revision: str
    mode: str
    switched: bool
    changed: bool
    chunk_count: int
    source_count: int
    skipped_sources: tuple[dict[str, str], ...]
    dropped_short: int
    dropped_duplicate: int
    reused_chunks: int
    new_embeddings: int
    build_duration_ms: int
    peak_working_set_mib: float | None
    cold_start_ms: int | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "revision": self.revision,
            "mode": self.mode,
            "switched": self.switched,
            "changed": self.changed,
            "chunk_count": self.chunk_count,
            "source_count": self.source_count,
            "skipped_sources": list(self.skipped_sources),
            "dropped_short": self.dropped_short,
            "dropped_duplicate": self.dropped_duplicate,
            "reused_chunks": self.reused_chunks,
            "new_embeddings": self.new_embeddings,
            "build_duration_ms": self.build_duration_ms,
            "peak_working_set_mib": self.peak_working_set_mib,
            "cold_start_ms": self.cold_start_ms,
        }


class RagIndex:
    def __init__(self, directory: Path, backend: EmbeddingBackend) -> None:
        self.directory = directory.resolve()
        revision_path = self.directory / "revision.json"
        try:
            self.metadata = json.loads(revision_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise IndexError(f"cannot read index revision metadata: {revision_path}") from exc
        if self.metadata.get("format") != RAG_INDEX_FORMAT:
            raise IndexError(f"unsupported index format in {revision_path}")
        if self.metadata.get("embedding_backend") != backend.name:
            raise IndexError(
                f"index embedding backend {self.metadata.get('embedding_backend')} does not match {backend.name}"
            )
        if int(self.metadata.get("embedding_dimension", 0)) != backend.dimension:
            raise IndexError("index embedding dimension does not match configured backend")
        database_path = self.directory / "index.sqlite3"
        if not database_path.is_file():
            raise IndexError(f"index database is missing: {database_path}")
        try:
            self._connection = sqlite3.connect(
                f"file:{database_path.as_posix()}?mode=ro", uri=True, check_same_thread=False
            )
            self._connection.execute("PRAGMA query_only=ON")
        except sqlite3.Error as exc:
            raise IndexError(f"cannot open index database: {database_path}") from exc
        self.backend = backend
        self.revision = str(self.metadata["revision"])

    @classmethod
    def open_active(cls, index_root: Path, backend: EmbeddingBackend) -> "RagIndex | None":
        pointer = index_root / "active.json"
        if not pointer.is_file():
            return None
        try:
            active = json.loads(pointer.read_text(encoding="utf-8"))
            revision = str(active["revision"])
        except (OSError, UnicodeDecodeError, json.JSONDecodeError, KeyError) as exc:
            raise IndexError(f"invalid active index pointer: {pointer}") from exc
        if not re.fullmatch(r"rag-[0-9a-f]{16}", revision):
            raise IndexError(f"invalid active index revision: {revision}")
        return cls(index_root / revision, backend)

    def close(self) -> None:
        self._connection.close()

    def embedding_for(self, chunk_id: str) -> tuple[float, ...] | None:
        row = self._connection.execute(
            "SELECT embedding FROM chunks WHERE chunk_id = ?", (chunk_id,)
        ).fetchone()
        return unpack_vector(row[0], self.backend.dimension) if row else None

    def _row_to_result(self, row: sqlite3.Row, score: float, match_kind: str) -> RetrievalResult:
        return RetrievalResult(
            chunk_id=str(row[0]),
            text=str(row[1]),
            score=score,
            match_kind=match_kind,
            metadata={
                "chunk_id": str(row[0]),
                "source_id": str(row[2]),
                "title": str(row[3]),
                "source_type": str(row[4]),
                "source_version": str(row[5]),
                "source_sha256": str(row[6]),
                "license": str(row[7]),
                "acquired_at": row[8],
                "language": str(row[9]),
                "locator": str(row[10]),
                "section": row[11],
                "index_revision": self.revision,
            },
        )

    def _all_rows(self) -> Iterable[sqlite3.Row]:
        self._connection.row_factory = sqlite3.Row
        return self._connection.execute(
            "SELECT chunk_id, text, source_id, source_title, source_type, source_version, "
            "source_sha256, source_license, acquired_at, language, locator, section, embedding "
            "FROM chunks"
        )

    def _keyword_scores(self, query: str) -> dict[str, float]:
        tokens = _keyword_tokens(query)
        normalized_query = normalize_for_embedding(query)
        scores: dict[str, float] = {}
        self._connection.row_factory = sqlite3.Row
        if tokens:
            placeholders = ",".join("?" for _ in tokens)
            rows = self._connection.execute(
                f"SELECT chunk_id, COUNT(*) FROM keyword_tokens WHERE token IN ({placeholders}) GROUP BY chunk_id",
                tokens,
            )
            scores.update({str(row[0]): float(row[1]) for row in rows})
        if normalized_query:
            for row in self._connection.execute(
                "SELECT chunk_id FROM chunks WHERE normalized_text LIKE ?", (f"%{normalized_query}%",)
            ):
                scores[str(row[0])] = scores.get(str(row[0]), 0.0) + 3.0
        return scores

    def _fetch_rows(self, chunk_ids: Sequence[str]) -> dict[str, sqlite3.Row]:
        if not chunk_ids:
            return {}
        self._connection.row_factory = sqlite3.Row
        placeholders = ",".join("?" for _ in chunk_ids)
        rows = self._connection.execute(
            "SELECT chunk_id, text, source_id, source_title, source_type, source_version, "
            "source_sha256, source_license, acquired_at, language, locator, section, embedding "
            f"FROM chunks WHERE chunk_id IN ({placeholders})",
            list(chunk_ids),
        )
        return {str(row[0]): row for row in rows}

    def search(self, query: str, *, top_k: int = 5, min_vector_score: float = 0.34) -> list[RetrievalResult]:
        if top_k < 1:
            return []
        cleaned_query = query.strip()
        if not cleaned_query:
            return []
        vector = self.backend.embed(cleaned_query)
        vector_rows: list[tuple[float, sqlite3.Row]] = []
        for row in self._all_rows():
            score = _dot(vector, unpack_vector(row[12], self.backend.dimension))
            vector_rows.append((score, row))
        vector_rows.sort(key=lambda item: (item[0], str(item[1][0])), reverse=True)
        keywords = self._keyword_scores(cleaned_query)
        candidate_rows = self._fetch_rows([str(row[0]) for _, row in vector_rows[: max(top_k * 3, 10)]])
        candidate_rows.update(self._fetch_rows(list(keywords)))
        vector_by_id = {str(row[0]): score for score, row in vector_rows}
        ranked: list[tuple[float, str, str]] = []
        for chunk_id, row in candidate_rows.items():
            vector_score = vector_by_id.get(chunk_id, 0.0)
            keyword_score = keywords.get(chunk_id, 0.0)
            if vector_score < min_vector_score and keyword_score <= 0:
                continue
            combined = vector_score + min(keyword_score, 4.0) * 0.08
            if keyword_score >= 3:
                combined += 0.2
            match_kind = "hybrid" if vector_score >= min_vector_score and keyword_score > 0 else (
                "vector" if vector_score >= min_vector_score else "keyword"
            )
            ranked.append((combined, chunk_id, match_kind))
        ranked.sort(key=lambda item: (item[0], item[1]), reverse=True)
        return [
            self._row_to_result(candidate_rows[chunk_id], score, match_kind)
            for score, chunk_id, match_kind in ranked[:top_k]
        ]


class _IndexWriter:
    def __init__(self, directory: Path, backend: EmbeddingBackend) -> None:
        self.directory = directory
        self.backend = backend
        self.directory.mkdir(parents=True, exist_ok=False)
        self.connection = sqlite3.connect(self.directory / "index.sqlite3")
        self.connection.executescript(
            """
            PRAGMA journal_mode = DELETE;
            PRAGMA synchronous = FULL;
            CREATE TABLE chunks (
                chunk_id TEXT PRIMARY KEY,
                text TEXT NOT NULL,
                normalized_text TEXT NOT NULL,
                source_id TEXT NOT NULL,
                source_title TEXT NOT NULL,
                source_type TEXT NOT NULL,
                source_version TEXT NOT NULL,
                source_sha256 TEXT NOT NULL,
                source_license TEXT NOT NULL,
                acquired_at TEXT,
                language TEXT NOT NULL,
                locator TEXT NOT NULL,
                section TEXT,
                embedding BLOB NOT NULL
            );
            CREATE TABLE keyword_tokens (
                token TEXT NOT NULL,
                chunk_id TEXT NOT NULL,
                PRIMARY KEY(token, chunk_id),
                FOREIGN KEY(chunk_id) REFERENCES chunks(chunk_id)
            );
            CREATE INDEX keyword_tokens_token_idx ON keyword_tokens(token);
            """
        )

    def write(
        self,
        *,
        metadata: dict[str, Any],
        chunks: Sequence[RagChunk],
        vectors: Sequence[Sequence[float]],
    ) -> None:
        if len(chunks) != len(vectors):
            raise IndexError("chunk/vector count mismatch")
        rows = []
        keyword_rows = []
        for chunk, vector in zip(chunks, vectors, strict=True):
            if len(vector) != self.backend.dimension:
                raise IndexError(f"embedding dimension mismatch for {chunk.chunk_id}")
            rows.append((
                chunk.chunk_id,
                chunk.text,
                chunk.normalized_text,
                chunk.source_id,
                chunk.source_title,
                chunk.source_type,
                chunk.source_version,
                chunk.source_sha256,
                chunk.source_license,
                chunk.acquired_at,
                chunk.language,
                chunk.locator,
                chunk.section,
                pack_vector(vector),
            ))
            keyword_rows.extend((token, chunk.chunk_id) for token in _keyword_tokens(chunk.normalized_text))
        self.connection.executemany(
            "INSERT INTO chunks VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", rows
        )
        self.connection.executemany(
            "INSERT INTO keyword_tokens(token, chunk_id) VALUES (?, ?)", keyword_rows
        )
        self.connection.commit()
        self.connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        self.connection.commit()
        (self.directory / "revision.json").write_text(
            json.dumps(metadata, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        with (self.directory / "chunks.jsonl").open("w", encoding="utf-8", newline="\n") as handle:
            for chunk in chunks:
                handle.write(json.dumps(chunk.to_dict(), ensure_ascii=False, sort_keys=True) + "\n")

    def close(self) -> None:
        self.connection.close()


class RagIndexBuilder:
    def __init__(
        self,
        *,
        manifest_path: Path,
        content_root: Path,
        index_root: Path,
        backend: EmbeddingBackend,
    ) -> None:
        self.manifest_path = manifest_path.resolve()
        self.content_root = content_root.resolve()
        self.index_root = index_root.resolve()
        self.backend = backend

    def _revision(self, manifest: RagManifest, corpus: IngestReport) -> str:
        payload = {
            "manifest": manifest.to_dict(),
            "chunks": [
                {
                    "chunk_id": chunk.chunk_id,
                    "text": chunk.text,
                    "language": chunk.language,
                    "source_sha256": chunk.source_sha256,
                }
                for chunk in corpus.chunks
            ],
            "embedding_backend": self.backend.name,
            "embedding_dimension": self.backend.dimension,
        }
        digest = hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()
        return f"rag-{digest[:16]}"

    def build(self, *, mode: str = "full", switch: bool = True) -> BuildReport:
        if mode not in {"full", "incremental"}:
            raise ValueError("RAG build mode must be full or incremental")
        started = time.perf_counter()
        manifest = load_manifest(self.manifest_path)
        corpus = ingest_manifest(manifest, self.content_root)
        revision = self._revision(manifest, corpus)
        self.index_root.mkdir(parents=True, exist_ok=True)
        active: RagIndex | None = None
        try:
            active = RagIndex.open_active(self.index_root, self.backend)
        except IndexError:
            active = None
        if active and active.revision == revision and switch:
            cold_start = time.perf_counter()
            active.close()
            active = RagIndex.open_active(self.index_root, self.backend)
            cold_start_ms = int((time.perf_counter() - cold_start) * 1000)
            active.close()
            return BuildReport(
                revision=revision,
                mode=mode,
                switched=False,
                changed=False,
                chunk_count=len(corpus.chunks),
                source_count=len({chunk.source_id for chunk in corpus.chunks}),
                skipped_sources=corpus.skipped_sources,
                dropped_short=corpus.dropped_short,
                dropped_duplicate=corpus.dropped_duplicate,
                reused_chunks=len(corpus.chunks),
                new_embeddings=0,
                build_duration_ms=int((time.perf_counter() - started) * 1000),
                peak_working_set_mib=round(_working_set_bytes() / (1024 * 1024), 2) or None,
                cold_start_ms=cold_start_ms,
            )

        reuse: dict[str, tuple[float, ...]] = {}
        if mode == "incremental" and active is not None:
            for chunk in corpus.chunks:
                vector = active.embedding_for(chunk.chunk_id)
                if vector is not None:
                    reuse[chunk.chunk_id] = vector
        if active is not None:
            active.close()

        staging_root = self.index_root / ".staging"
        staging_root.mkdir(parents=True, exist_ok=True)
        staging = staging_root / f"{revision}-{uuid.uuid4().hex}"
        final = self.index_root / revision
        writer: _IndexWriter | None = None
        switched = False
        try:
            vectors: list[tuple[float, ...]] = []
            new_embeddings = 0
            for chunk in corpus.chunks:
                vector = reuse.get(chunk.chunk_id)
                if vector is None:
                    vector = self.backend.embed(chunk.text)
                    new_embeddings += 1
                vectors.append(vector)
            metadata = {
                "format": RAG_INDEX_FORMAT,
                "revision": revision,
                "manifest_id": manifest.manifest_id,
                "manifest_version": manifest.version,
                "manifest_sha256": hashlib.sha256(
                    json.dumps(manifest.to_dict(), ensure_ascii=False, sort_keys=True).encode("utf-8")
                ).hexdigest(),
                "embedding_backend": self.backend.name,
                "embedding_dimension": self.backend.dimension,
                "created_at": datetime.now(UTC).isoformat(),
                "chunk_count": len(corpus.chunks),
                "source_count": len({chunk.source_id for chunk in corpus.chunks}),
                "skipped_sources": list(corpus.skipped_sources),
                "dropped_short": corpus.dropped_short,
                "dropped_duplicate": corpus.dropped_duplicate,
                "reused_chunks": len(reuse),
                "new_embeddings": new_embeddings,
            }
            writer = _IndexWriter(staging, self.backend)
            writer.write(metadata=metadata, chunks=corpus.chunks, vectors=vectors)
            writer.close()
            writer = None
            if final.exists():
                shutil.rmtree(staging)
            else:
                staging.replace(final)
            if switch:
                pointer_tmp = self.index_root / f"active.{uuid.uuid4().hex}.tmp"
                pointer_tmp.write_text(
                    json.dumps({"format": RAG_INDEX_FORMAT, "revision": revision}, indent=2) + "\n",
                    encoding="utf-8",
                )
                with pointer_tmp.open("r+", encoding="utf-8") as handle:
                    handle.flush()
                    os.fsync(handle.fileno())
                os.replace(pointer_tmp, self.index_root / "active.json")
                switched = True
            cold_start = time.perf_counter()
            opened = RagIndex(final, self.backend)
            opened.close()
            cold_start_ms = int((time.perf_counter() - cold_start) * 1000)
            return BuildReport(
                revision=revision,
                mode=mode,
                switched=switched,
                changed=True,
                chunk_count=len(corpus.chunks),
                source_count=len({chunk.source_id for chunk in corpus.chunks}),
                skipped_sources=corpus.skipped_sources,
                dropped_short=corpus.dropped_short,
                dropped_duplicate=corpus.dropped_duplicate,
                reused_chunks=len(reuse),
                new_embeddings=new_embeddings,
                build_duration_ms=int((time.perf_counter() - started) * 1000),
                peak_working_set_mib=round(_working_set_bytes() / (1024 * 1024), 2) or None,
                cold_start_ms=cold_start_ms,
            )
        finally:
            if writer is not None:
                writer.close()
            if staging.exists():
                shutil.rmtree(staging, ignore_errors=True)


@dataclass(frozen=True, slots=True)
class RagHealth:
    status: str
    revision: str | None
    embedding_backend: str | None
    chunk_count: int
    cold_start_ms: int | None
    last_error: str | None


class RagIndexManager:
    def __init__(self, index_root: Path, backend: EmbeddingBackend) -> None:
        self.index_root = index_root.resolve()
        self.backend = backend
        self.index: RagIndex | None = None
        self.last_error: str | None = None
        self.cold_start_ms: int | None = None

    def open_active(self) -> RagHealth:
        self.close()
        started = time.perf_counter()
        try:
            self.index = RagIndex.open_active(self.index_root, self.backend)
            self.cold_start_ms = int((time.perf_counter() - started) * 1000)
            self.last_error = None
        except (IndexError, EmbeddingError, OSError, sqlite3.Error) as exc:
            self.index = None
            self.cold_start_ms = int((time.perf_counter() - started) * 1000)
            self.last_error = str(exc)
        return self.health()

    def refresh(self) -> RagHealth:
        return self.open_active()

    def health(self) -> RagHealth:
        if self.index is None:
            return RagHealth("degraded", None, self.backend.name, 0, self.cold_start_ms, self.last_error)
        return RagHealth(
            "ready",
            self.index.revision,
            self.backend.name,
            int(self.index.metadata.get("chunk_count", 0)),
            self.cold_start_ms,
            None,
        )

    def search(self, query: str, *, top_k: int = 5) -> list[RetrievalResult]:
        if self.index is None:
            self.open_active()
        return self.index.search(query, top_k=top_k) if self.index is not None else []

    def close(self) -> None:
        if self.index is not None:
            self.index.close()
            self.index = None
