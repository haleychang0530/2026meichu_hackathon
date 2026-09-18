from __future__ import annotations

import argparse
import json
import statistics
import sys
import tempfile
import time
from datetime import UTC, datetime
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPOSITORY_ROOT / "apps" / "core-api"))

from core_api.rag import EmbeddingError, RagIndexBuilder, RagIndexManager, create_embedding_backend  # noqa: E402


def _evaluate_hashing(queries: list[dict[str, object]]) -> dict[str, object]:
    backend = create_embedding_backend("hashing-char-ngram-v1")
    with tempfile.TemporaryDirectory(prefix="hol-rag-eval-") as directory:
        index_root = Path(directory) / "indexes"
        report = RagIndexBuilder(
            manifest_path=REPOSITORY_ROOT / "data/rag/manifest.json",
            content_root=REPOSITORY_ROOT,
            index_root=index_root,
            backend=backend,
        ).build(mode="full")
        manager = RagIndexManager(index_root, backend)
        health = manager.open_active()
        timings: list[float] = []
        passed = 0
        for item in queries:
            started = time.perf_counter()
            results = manager.search(str(item["query"]), top_k=3)
            timings.append((time.perf_counter() - started) * 1000)
            if item["expect"] == "no_result":
                ok = not results
            else:
                ok = bool(results) and results[0].metadata["source_id"] == item["source_id"]
            passed += int(ok)
        manager.close()
        return {
            "backend": backend.name,
            "status": "selected",
            "device": "CPU",
            "dimension": backend.dimension,
            "query_count": len(queries),
            "passed_queries": passed,
            "accuracy": round(passed / len(queries), 4) if queries else 0.0,
            "mean_query_ms": round(statistics.mean(timings), 3) if timings else 0.0,
            "p95_query_ms": round(sorted(timings)[max(0, int(len(timings) * 0.95) - 1)], 3) if timings else 0.0,
            "index_revision": health.revision,
            "cold_start_ms": health.cold_start_ms,
            "build": report.to_dict(),
        }


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="Evaluate approved local CPU embedding backends")
    parser.add_argument("--queries", default="data/rag/smoke_queries.json")
    args = parser.parse_args()
    queries = json.loads((REPOSITORY_ROOT / args.queries).read_text(encoding="utf-8"))
    candidates: list[dict[str, object]] = [_evaluate_hashing(queries)]
    try:
        create_embedding_backend("onnx-local")
    except EmbeddingError as exc:
        candidates.append({
            "backend": "onnx-local",
            "status": "not_evaluated",
            "device": "CPUExecutionProvider",
            "reason": str(exc),
        })
    print(json.dumps({
        "schema_version": "rag-embedding-evaluation.v1",
        "evaluated_at": datetime.now(UTC).isoformat(),
        "method": "20-query retrieval smoke; no external model download",
        "selected_backend": "hashing-char-ngram-v1",
        "candidates": candidates,
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
