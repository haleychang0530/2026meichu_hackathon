from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping


RAG_MANIFEST_SCHEMA = "rag-manifest.v1"
RAG_INDEX_FORMAT = "rag-index.v1"


class ManifestError(ValueError):
    """Raised when a corpus manifest is unsafe or cannot be interpreted."""


@dataclass(frozen=True, slots=True)
class RagSource:
    source_id: str
    title: str
    content_path: str
    source_type: str
    language: str
    license_name: str
    license_status: str
    approved_for_index: bool
    authorization_note: str
    acquired_at: str | None
    source_version: str
    content_sha256: str | None
    url: str | None = None

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "RagSource":
        required = (
            "source_id",
            "title",
            "content_path",
            "source_type",
            "language",
            "license",
            "license_status",
            "approved_for_index",
            "authorization_note",
            "source_version",
        )
        missing = [key for key in required if key not in value]
        if missing:
            raise ManifestError(f"source is missing manifest fields: {', '.join(missing)}")
        source_id = str(value["source_id"]).strip()
        title = str(value["title"]).strip()
        content_path = str(value["content_path"]).strip()
        if not source_id or not title or not content_path:
            raise ManifestError("source_id, title, and content_path must be non-empty")
        content_sha256 = value.get("content_sha256")
        if content_sha256 is not None:
            content_sha256 = str(content_sha256).strip().lower()
            if len(content_sha256) != 64 or any(char not in "0123456789abcdef" for char in content_sha256):
                raise ManifestError(f"invalid SHA-256 for source {source_id}")
        return cls(
            source_id=source_id,
            title=title,
            content_path=content_path,
            source_type=str(value["source_type"]).strip(),
            language=str(value["language"]).strip(),
            license_name=str(value["license"]).strip(),
            license_status=str(value["license_status"]).strip(),
            approved_for_index=bool(value["approved_for_index"]),
            authorization_note=str(value["authorization_note"]).strip(),
            acquired_at=(str(value["acquired_at"]).strip() if value.get("acquired_at") else None),
            source_version=str(value["source_version"]).strip(),
            content_sha256=content_sha256,
            url=(str(value["url"]).strip() if value.get("url") else None),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_id": self.source_id,
            "title": self.title,
            "content_path": self.content_path,
            "source_type": self.source_type,
            "language": self.language,
            "license": self.license_name,
            "license_status": self.license_status,
            "approved_for_index": self.approved_for_index,
            "authorization_note": self.authorization_note,
            "acquired_at": self.acquired_at,
            "source_version": self.source_version,
            "content_sha256": self.content_sha256,
            "url": self.url,
        }

@dataclass(frozen=True, slots=True)
class RagManifest:
    manifest_id: str
    version: str
    sources: tuple[RagSource, ...]
    min_chunk_chars: int = 2
    max_chunk_chars: int = 480
    overlap_chars: int = 40

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": RAG_MANIFEST_SCHEMA,
            "manifest_id": self.manifest_id,
            "version": self.version,
            "chunking": {
                "min_chunk_chars": self.min_chunk_chars,
                "max_chunk_chars": self.max_chunk_chars,
                "overlap_chars": self.overlap_chars,
            },
            "sources": [source.to_dict() for source in self.sources],
        }


@dataclass(frozen=True, slots=True)
class RagChunk:
    chunk_id: str
    text: str
    normalized_text: str
    source_id: str
    source_title: str
    source_type: str
    source_version: str
    source_sha256: str
    source_license: str
    acquired_at: str | None
    language: str
    locator: str
    section: str | None

    def metadata(self, index_revision: str | None = None) -> dict[str, Any]:
        return {
            "chunk_id": self.chunk_id,
            "source_id": self.source_id,
            "title": self.source_title,
            "source_type": self.source_type,
            "source_version": self.source_version,
            "source_sha256": self.source_sha256,
            "license": self.source_license,
            "acquired_at": self.acquired_at,
            "language": self.language,
            "locator": self.locator,
            "section": self.section,
            "index_revision": index_revision,
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            **self.metadata(),
            "text": self.text,
            "normalized_text": self.normalized_text,
        }


@dataclass(frozen=True, slots=True)
class RetrievalResult:
    chunk_id: str
    text: str
    score: float
    match_kind: str
    metadata: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "chunk_id": self.chunk_id,
            "text": self.text,
            "score": round(self.score, 6),
            "match_kind": self.match_kind,
            "metadata": self.metadata,
        }
