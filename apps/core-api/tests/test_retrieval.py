from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from core_api.rag import (
    HybridRetrievalConfig,
    HybridRetriever,
    RagIndexBuilder,
    RagIndexManager,
    create_embedding_backend,
)


def _write_corpus(root: Path) -> tuple[Path, Path]:
    source = root / "source.jsonl"
    source.write_text(
        '{"text":"市場 tshī-tiûnn","locator":"entry/市場"}\n'
        '{"text":"欲 beh","locator":"entry/欲"}\n'
        '{"text":"菜 tshài","locator":"entry/菜"}\n',
        encoding="utf-8",
    )
    manifest = {
        "schema_version": "rag-manifest.v1",
        "manifest_id": "stage06-test",
        "version": "1",
        "chunking": {"min_chunk_chars": 2, "max_chunk_chars": 480, "overlap_chars": 40},
        "sources": [{
            "source_id": "approved-dictionary",
            "title": "Approved dictionary fixture",
            "content_path": "source.jsonl",
            "source_type": "jsonl",
            "language": "nan-TW",
            "license": "test-fixture",
            "license_status": "approved",
            "approved_for_index": True,
            "authorization_note": "Unit-test fixture",
            "acquired_at": "2026-09-18",
            "source_version": "1",
            "content_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
        }],
    }
    manifest_path = root / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")
    return manifest_path, source


class HybridRetrievalTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        root = Path(self.temporary.name)
        manifest_path, _ = _write_corpus(root)
        self.backend = create_embedding_backend("hashing-char-ngram-v1")
        self.index_root = root / "indexes"
        self.report = RagIndexBuilder(
            manifest_path=manifest_path,
            content_root=root,
            index_root=self.index_root,
            backend=self.backend,
        ).build(mode="full")
        self.manager = RagIndexManager(self.index_root, self.backend)
        self.manager.open_active()

    def tearDown(self) -> None:
        self.manager.close()
        self.temporary.cleanup()

    def test_exact_keyword_vector_and_metadata_filter(self) -> None:
        exact = self.manager.search("市場 tshī-tiûnn", top_k=1)
        self.assertEqual(exact[0].match_kind, "normalized_exact")
        self.assertEqual(exact[0].score, 1.0)
        filtered = self.manager.search(
            "市場",
            top_k=3,
            metadata_filter={"language": "nan-TW", "source_type": "jsonl"},
        )
        self.assertTrue(filtered)
        rejected = self.manager.search(
            "市場",
            top_k=3,
            metadata_filter={"language": "zh-TW"},
        )
        self.assertEqual(rejected, [])
        self.assertEqual(
            self.manager.search("%", top_k=3, min_vector_score=1.1, min_score=0.85),
            [],
        )

    def test_top_k_dedup_threshold_context_budget_and_empty_evidence(self) -> None:
        retriever = HybridRetriever(
            self.manager,
            HybridRetrievalConfig(top_k=2, min_score=0.40, context_budget_chars=12),
        )
        bundle = retriever.retrieve("市場")
        self.assertLessEqual(len(bundle.evidence), 2)
        self.assertLessEqual(bundle.context_chars, 12)
        self.assertEqual(bundle.index_revision, self.report.revision)
        self.assertEqual(retriever.retrieve("lunar rocket museum").evidence, ())

    def test_evidence_contains_required_fields_and_is_reproducible(self) -> None:
        retriever = HybridRetriever(self.manager)
        bundle = retriever.retrieve("tshī-tiûnn", top_k=1)
        self.assertEqual(len(bundle.evidence), 1)
        citation = bundle.evidence[0]
        self.assertEqual(
            set(citation.to_dict()),
            {"source_id", "title", "excerpt", "locator", "score", "index_revision"},
        )
        self.assertTrue(retriever.reproduce(citation))
        self.assertEqual(citation.index_revision, self.report.revision)


if __name__ == "__main__":
    unittest.main()
