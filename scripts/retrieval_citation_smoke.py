"""Run Stage 06 hybrid retrieval and citation reproduction smoke checks."""

from __future__ import annotations

import json
import statistics
import sys
import tempfile
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CORE_APP = ROOT / "apps" / "core-api"
if str(CORE_APP) not in sys.path:
    sys.path.insert(0, str(CORE_APP))

from core_api.rag import (  # noqa: E402
    HybridRetriever,
    RagIndexBuilder,
    RagIndexManager,
    create_embedding_backend,
)


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    queries = json.loads((ROOT / "data/rag/smoke_queries.json").read_text(encoding="utf-8"))
    failures: list[dict[str, str]] = []
    latencies: list[float] = []
    citation_count = 0
    with tempfile.TemporaryDirectory() as directory:
        backend = create_embedding_backend("hashing-char-ngram-v1")
        index_root = Path(directory) / "indexes"
        build = RagIndexBuilder(
            manifest_path=ROOT / "data/rag/manifest.json",
            content_root=ROOT,
            index_root=index_root,
            backend=backend,
        ).build(mode="full")
        manager = RagIndexManager(index_root, backend)
        manager.open_active()
        retriever = HybridRetriever(manager)
        try:
            for item in queries:
                started = time.perf_counter()
                bundle = retriever.retrieve(item["query"])
                latencies.append((time.perf_counter() - started) * 1000)
                if item["expect"] == "no_result" and bundle.evidence:
                    failures.append({"query": item["query"], "reason": "unexpected_evidence"})
                    continue
                if item["expect"] == "hit" and not bundle.evidence:
                    failures.append({"query": item["query"], "reason": "missing_evidence"})
                    continue
                if bundle.context_chars > retriever.config.context_budget_chars:
                    failures.append({"query": item["query"], "reason": "context_budget_exceeded"})
                for citation in bundle.evidence:
                    citation_count += 1
                    if not retriever.reproduce(citation):
                        failures.append({"query": item["query"], "reason": "citation_not_reproducible"})
        finally:
            manager.close()
    ordered = sorted(latencies)
    p95 = ordered[max(0, int(len(ordered) * 0.95) - 1)] if ordered else 0.0
    report = {
        "passed": not failures,
        "query_count": len(queries),
        "citation_count": citation_count,
        "index_revision": build.revision,
        "mean_latency_ms": round(statistics.fmean(latencies), 3) if latencies else 0.0,
        "p95_latency_ms": round(p95, 3),
        "top_k": retriever.config.top_k,
        "min_score": retriever.config.min_score,
        "context_budget_chars": retriever.config.context_budget_chars,
        "failures": failures,
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
