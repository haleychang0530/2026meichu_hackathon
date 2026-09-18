from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPOSITORY_ROOT / "apps" / "core-api"))

from core_api.rag import RagIndexBuilder, RagIndexManager, create_embedding_backend  # noqa: E402
from core_api.rag.chunking import load_manifest  # noqa: E402


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="Run the 20-query Local RAG smoke set")
    parser.add_argument("--index-root", help="reuse an existing runtime index instead of a temporary rebuild")
    parser.add_argument("--queries", default="data/rag/smoke_queries.json")
    parser.add_argument("--manifest", default="data/rag/manifest.json")
    args = parser.parse_args()
    queries = json.loads((REPOSITORY_ROOT / args.queries).read_text(encoding="utf-8"))

    with tempfile.TemporaryDirectory(prefix="hol-rag-smoke-") as temporary:
        index_root = Path(args.index_root).expanduser() if args.index_root else Path(temporary) / "indexes"
        backend = create_embedding_backend("hashing-char-ngram-v1")
        if not args.index_root:
            manifest = load_manifest(REPOSITORY_ROOT / args.manifest)
            report = RagIndexBuilder(
                manifest_path=REPOSITORY_ROOT / args.manifest,
                content_root=REPOSITORY_ROOT,
                index_root=index_root,
                backend=backend,
            ).build(mode="full")
        manager = RagIndexManager(index_root, backend)
        health = manager.open_active()
        if health.status != "ready":
            raise SystemExit(f"RAG smoke index is not ready: {health}")
        failures: list[dict[str, object]] = []
        for item in queries:
            results = manager.search(str(item["query"]), top_k=3)
            if item["expect"] == "no_result":
                passed = not results
            else:
                passed = bool(results)
                if passed and item.get("source_id"):
                    passed = results[0].metadata["source_id"] == item["source_id"]
                if passed:
                    passed = all(
                        any(term in result.text for term in item.get("contains", []))
                        for result in results[:1]
                    )
            if not passed:
                failures.append({"query": item["query"], "results": [result.to_dict() for result in results]})
        manager.close()
        print(json.dumps({
            "query_count": len(queries),
            "passed": not failures,
            "failures": failures,
            "index_revision": health.revision,
            "build": report.to_dict() if not args.index_root else None,
        }, ensure_ascii=False, indent=2))
        return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
