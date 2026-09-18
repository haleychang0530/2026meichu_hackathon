from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from typing import Mapping

from .index import RagIndexManager


@dataclass(frozen=True, slots=True)
class HybridRetrievalConfig:
    top_k: int = 5
    candidate_multiplier: int = 3
    min_vector_score: float = 0.34
    min_score: float = 0.40
    context_budget_chars: int = 1600


@dataclass(frozen=True, slots=True)
class EvidenceCitation:
    source_id: str
    title: str
    excerpt: str
    locator: str
    score: float
    index_revision: str

    def to_dict(self) -> dict[str, str | float]:
        return {
            "source_id": self.source_id,
            "title": self.title,
            "excerpt": self.excerpt,
            "locator": self.locator,
            "score": round(self.score, 6),
            "index_revision": self.index_revision,
        }


@dataclass(frozen=True, slots=True)
class RetrievalBundle:
    query: str
    evidence: tuple[EvidenceCitation, ...]
    index_revision: str | None
    context_chars: int


def _dedupe_key(text: str) -> str:
    value = unicodedata.normalize("NFKC", text).casefold()
    return re.sub(r"\s+", " ", value).strip()


class HybridRetriever:
    """Policy layer for trustworthy, bounded Local RAG evidence."""

    def __init__(self, manager: RagIndexManager, config: HybridRetrievalConfig | None = None) -> None:
        self.manager = manager
        self.config = config or HybridRetrievalConfig()

    def retrieve(
        self,
        query: str,
        *,
        top_k: int | None = None,
        context_budget_chars: int | None = None,
        metadata_filter: Mapping[str, str] | None = None,
    ) -> RetrievalBundle:
        requested_top_k = self.config.top_k if top_k is None else max(top_k, 0)
        budget = self.config.context_budget_chars if context_budget_chars is None else max(
            context_budget_chars, 0
        )
        if requested_top_k == 0 or budget == 0 or not query.strip():
            return RetrievalBundle(query, (), None, 0)
        candidates = self.manager.search(
            query,
            top_k=max(requested_top_k * self.config.candidate_multiplier, requested_top_k),
            min_vector_score=self.config.min_vector_score,
            min_score=self.config.min_score,
            metadata_filter=metadata_filter,
        )
        evidence: list[EvidenceCitation] = []
        seen: set[str] = set()
        used = 0
        revision: str | None = None
        for result in candidates:
            key = _dedupe_key(result.text)
            if not key or key in seen:
                continue
            remaining = budget - used
            if remaining <= 0:
                break
            excerpt = result.text if len(result.text) <= remaining else result.text[:remaining].rstrip()
            if not excerpt:
                break
            index_revision = str(result.metadata["index_revision"])
            evidence.append(EvidenceCitation(
                source_id=str(result.metadata["source_id"]),
                title=str(result.metadata["title"]),
                excerpt=excerpt,
                locator=str(result.metadata["locator"]),
                score=result.score,
                index_revision=index_revision,
            ))
            seen.add(key)
            used += len(excerpt)
            revision = index_revision
            if len(evidence) >= requested_top_k:
                break
        return RetrievalBundle(query, tuple(evidence), revision, used)

    def reproduce(self, citation: EvidenceCitation) -> bool:
        result = self.manager.resolve(
            source_id=citation.source_id,
            locator=citation.locator,
            revision=citation.index_revision,
        )
        return result is not None and result.text.startswith(citation.excerpt)
