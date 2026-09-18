from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping

from .embeddings import normalize_for_embedding
from .models import ManifestError, RagChunk, RagManifest, RagSource, RAG_MANIFEST_SCHEMA


class SourceContentError(ValueError):
    """Raised when an approved source is missing, corrupt, or changed."""


@dataclass(frozen=True, slots=True)
class IngestReport:
    chunks: tuple[RagChunk, ...]
    skipped_sources: tuple[dict[str, str], ...]
    dropped_short: int
    dropped_duplicate: int


def load_manifest(path: Path) -> RagManifest:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ManifestError(f"cannot read RAG manifest {path}: {exc}") from exc
    if payload.get("schema_version") != RAG_MANIFEST_SCHEMA:
        raise ManifestError(f"unsupported RAG manifest schema in {path}")
    sources_raw = payload.get("sources")
    if not isinstance(sources_raw, list):
        raise ManifestError("RAG manifest sources must be an array")
    sources = tuple(RagSource.from_mapping(value) for value in sources_raw)
    source_ids = [source.source_id for source in sources]
    if len(source_ids) != len(set(source_ids)):
        raise ManifestError("RAG manifest source_id values must be unique")
    chunking = payload.get("chunking") or {}
    min_chunk_chars = int(chunking.get("min_chunk_chars", 2))
    max_chunk_chars = int(chunking.get("max_chunk_chars", 480))
    overlap_chars = int(chunking.get("overlap_chars", 40))
    if min_chunk_chars < 1 or max_chunk_chars < min_chunk_chars or overlap_chars >= max_chunk_chars:
        raise ManifestError("invalid chunking limits in RAG manifest")
    return RagManifest(
        manifest_id=str(payload.get("manifest_id", "")).strip(),
        version=str(payload.get("version", "")).strip(),
        sources=sources,
        min_chunk_chars=min_chunk_chars,
        max_chunk_chars=max_chunk_chars,
        overlap_chars=overlap_chars,
    )


def clean_text(value: str) -> str:
    """Normalize encoding noise without transliterating Hanji or 臺羅."""

    normalized = unicodedata.normalize("NFKC", value.replace("\r\n", "\n").replace("\r", "\n"))
    cleaned_lines: list[str] = []
    for raw_line in normalized.split("\n"):
        chars = [char for char in raw_line if char in "\t" or not unicodedata.category(char).startswith("C")]
        line = re.sub(r"[ \t]+", " ", "".join(chars)).strip()
        cleaned_lines.append(line)
    cleaned = "\n".join(cleaned_lines)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned.strip()


def _meaningful_length(value: str) -> int:
    return sum(1 for char in normalize_for_embedding(value) if char.isalnum())


def _source_path(source: RagSource, content_root: Path) -> Path:
    candidate = Path(source.content_path)
    if not candidate.is_absolute():
        candidate = content_root / candidate
    return candidate.resolve()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as handle:
            for block in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(block)
    except OSError as exc:
        raise SourceContentError(f"cannot read approved source {path}: {exc}") from exc
    return digest.hexdigest()


def _split_long_text(text: str, max_chars: int, overlap_chars: int) -> Iterable[tuple[str, int]]:
    if len(text) <= max_chars:
        yield text, 0
        return
    boundaries = [match.end() for match in re.finditer(r"(?<=[。！？.!?；;])\s+|\n+", text)]
    pieces: list[str] = []
    cursor = 0
    for boundary in boundaries + [len(text)]:
        piece = text[cursor:boundary].strip()
        if piece:
            pieces.append(piece)
        cursor = boundary
    if not pieces:
        pieces = [text]
    buffer = ""
    piece_number = 0
    for piece in pieces:
        candidate = f"{buffer} {piece}".strip() if buffer else piece
        if buffer and len(candidate) > max_chars:
            yield buffer, piece_number
            piece_number += 1
            buffer = f"{buffer[-overlap_chars:]} {piece}".strip() if overlap_chars else piece
        else:
            buffer = candidate
        while len(buffer) > max_chars:
            yield buffer[:max_chars].strip(), piece_number
            piece_number += 1
            buffer = buffer[max_chars - overlap_chars :].strip() if overlap_chars else buffer[max_chars:].strip()
    if buffer:
        yield buffer, piece_number


def _chunk(
    *,
    source: RagSource,
    source_sha256: str,
    text: str,
    locator: str,
    section: str | None,
    language: str,
) -> RagChunk:
    cleaned = clean_text(text)
    normalized = normalize_for_embedding(cleaned)
    identity = f"{source.source_id}\n{locator}\n{normalized}\n{language}".encode("utf-8")
    chunk_id = f"chunk_{hashlib.sha256(identity).hexdigest()[:24]}"
    return RagChunk(
        chunk_id=chunk_id,
        text=cleaned,
        normalized_text=normalized,
        source_id=source.source_id,
        source_title=source.title,
        source_type=source.source_type,
        source_version=source.source_version,
        source_sha256=source_sha256,
        source_license=source.license_name,
        acquired_at=source.acquired_at,
        language=language,
        locator=locator,
        section=section,
    )


def _lesson_fixture_chunks(
    payload: Mapping[str, Any], source: RagSource, source_sha256: str, manifest: RagManifest
) -> Iterable[RagChunk]:
    field_labels = {
        "topic": "主題",
        "source_text": "課文",
        "scene": "情境",
        "original_activity": "原始活動",
        "learning_objective": "教學目標",
        "accessible_activity": "無障礙活動",
    }
    for field, label in field_labels.items():
        value = payload.get(field)
        if isinstance(value, str) and value.strip():
            for piece, number in _split_long_text(value, manifest.max_chunk_chars, manifest.overlap_chars):
                yield _chunk(
                    source=source,
                    source_sha256=source_sha256,
                    text=f"{label}：{piece}",
                    locator=f"lesson/{field}/{number}",
                    section=label,
                    language=source.language,
                )
    vocabulary = payload.get("vocabulary")
    if isinstance(vocabulary, list):
        for index, item in enumerate(vocabulary):
            if not isinstance(item, Mapping):
                continue
            parts = [
                str(item.get("hanji", "")).strip(),
                str(item.get("tailo", "")).strip(),
                str(item.get("meaning", "")).strip(),
            ]
            text = "；".join(part for part in parts if part)
            if text:
                yield _chunk(
                    source=source,
                    source_sha256=source_sha256,
                    text=f"詞條：{text}",
                    locator=f"lesson/vocabulary[{index}]",
                    section="詞條",
                    language=source.language,
                )
    evidence = payload.get("evidence")
    if isinstance(evidence, list):
        for index, item in enumerate(evidence):
            if not isinstance(item, Mapping):
                continue
            excerpt = str(item.get("excerpt", "")).strip()
            if excerpt:
                yield _chunk(
                    source=source,
                    source_sha256=source_sha256,
                    text=f"依據摘錄：{excerpt}",
                    locator=f"lesson/evidence[{index}]/{item.get('locator', 'excerpt')}",
                    section="依據摘錄",
                    language=source.language,
                )


def _text_chunks(text: str, source: RagSource, source_sha256: str, manifest: RagManifest) -> Iterable[RagChunk]:
    section: str | None = None
    paragraph: list[str] = []
    paragraph_number = 0

    def flush() -> Iterable[RagChunk]:
        nonlocal paragraph, paragraph_number
        value = clean_text("\n".join(paragraph))
        paragraph = []
        if not value:
            return ()
        results: list[RagChunk] = []
        for piece, number in _split_long_text(value, manifest.max_chunk_chars, manifest.overlap_chars):
            results.append(_chunk(
                source=source,
                source_sha256=source_sha256,
                text=piece,
                locator=f"section/{paragraph_number}/{number}",
                section=section,
                language=source.language,
            ))
        paragraph_number += 1
        return tuple(results)

    for line_number, line in enumerate(text.splitlines(), start=1):
        stripped = line.strip()
        if not stripped:
            yield from flush()
            continue
        if stripped.startswith("#"):
            yield from flush()
            section = stripped.lstrip("#").strip() or None
            continue
        paragraph.append(stripped)
    yield from flush()


def _jsonl_chunks(text: str, source: RagSource, source_sha256: str, manifest: RagManifest) -> Iterable[RagChunk]:
    for line_number, raw_line in enumerate(text.splitlines(), start=1):
        if not raw_line.strip():
            continue
        try:
            item = json.loads(raw_line)
        except json.JSONDecodeError as exc:
            raise SourceContentError(f"invalid JSONL at {source.source_id}:{line_number}: {exc}") from exc
        if not isinstance(item, Mapping) or not str(item.get("text", "")).strip():
            continue
        language = str(item.get("language") or source.language)
        locator = str(item.get("locator") or f"line/{line_number}")
        section = str(item.get("section")).strip() if item.get("section") else None
        for piece, number in _split_long_text(str(item["text"]), manifest.max_chunk_chars, manifest.overlap_chars):
            yield _chunk(
                source=source,
                source_sha256=source_sha256,
                text=piece,
                locator=f"{locator}/{number}",
                section=section,
                language=language,
            )


def source_chunks(source: RagSource, content_root: Path, manifest: RagManifest) -> tuple[RagChunk, ...]:
    if not source.approved_for_index or source.license_status != "approved":
        return ()
    if not source.content_sha256:
        raise SourceContentError(f"approved source {source.source_id} has no content_sha256")
    path = _source_path(source, content_root)
    if not path.is_file():
        raise SourceContentError(f"approved source {source.source_id} is missing: {path}")
    actual_sha256 = _sha256(path)
    if actual_sha256 != source.content_sha256:
        raise SourceContentError(
            f"source hash mismatch for {source.source_id}: manifest={source.content_sha256}, actual={actual_sha256}"
        )
    try:
        text = path.read_text(encoding="utf-8-sig")
    except (OSError, UnicodeDecodeError) as exc:
        raise SourceContentError(f"cannot decode approved source {path} as UTF-8: {exc}") from exc
    if source.source_type == "lesson_fixture":
        try:
            payload = json.loads(text)
        except json.JSONDecodeError as exc:
            raise SourceContentError(f"lesson fixture {source.source_id} is not valid JSON: {exc}") from exc
        if not isinstance(payload, Mapping):
            raise SourceContentError(f"lesson fixture {source.source_id} must contain an object")
        candidates = _lesson_fixture_chunks(payload, source, actual_sha256, manifest)
    elif source.source_type == "jsonl":
        candidates = _jsonl_chunks(text, source, actual_sha256, manifest)
    elif source.source_type in {"text", "markdown"}:
        candidates = _text_chunks(text, source, actual_sha256, manifest)
    else:
        raise SourceContentError(f"unsupported source_type for {source.source_id}: {source.source_type}")
    return tuple(candidates)


def ingest_manifest(manifest: RagManifest, content_root: Path) -> IngestReport:
    accepted: list[RagChunk] = []
    skipped: list[dict[str, str]] = []
    dropped_short = 0
    dropped_duplicate = 0
    seen: set[tuple[str, str]] = set()
    for source in manifest.sources:
        if not source.approved_for_index or source.license_status != "approved":
            skipped.append({
                "source_id": source.source_id,
                "reason": "license_not_approved",
                "license_status": source.license_status,
            })
            continue
        for chunk in source_chunks(source, content_root, manifest):
            if _meaningful_length(chunk.text) < manifest.min_chunk_chars:
                dropped_short += 1
                continue
            key = (chunk.language, chunk.normalized_text)
            if key in seen:
                dropped_duplicate += 1
                continue
            seen.add(key)
            accepted.append(chunk)
    accepted.sort(key=lambda item: item.chunk_id)
    return IngestReport(tuple(accepted), tuple(skipped), dropped_short, dropped_duplicate)
