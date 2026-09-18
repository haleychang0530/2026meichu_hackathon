from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
import uuid
from dataclasses import replace
from pathlib import Path

import httpx

from core_api.app import create_app
from core_api.config import Settings
from core_api.rag import RagIndexBuilder, RagIndexManager, create_embedding_backend
from core_api.rag.chunking import SourceContentError, ingest_manifest, load_manifest


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
MANIFEST_PATH = REPOSITORY_ROOT / "data" / "rag" / "manifest.json"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_manifest(root: Path, source_path: Path, *, source_id: str = "temp-source") -> Path:
    relative = source_path.relative_to(root)
    manifest = {
        "schema_version": "rag-manifest.v1",
        "manifest_id": "test-manifest",
        "version": "test-1",
        "chunking": {"min_chunk_chars": 2, "max_chunk_chars": 480, "overlap_chars": 40},
        "sources": [{
            "source_id": source_id,
            "title": "Approved test source",
            "content_path": str(relative),
            "source_type": "jsonl",
            "language": "nan-TW",
            "license": "test-fixture",
            "license_status": "approved",
            "approved_for_index": True,
            "authorization_note": "Unit-test fixture",
            "acquired_at": "2026-09-18",
            "source_version": "test-1",
            "content_sha256": _sha256(source_path),
        }],
    }
    path = root / "manifest.json"
    path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


class RagTests(unittest.TestCase):
    def test_manifest_and_chunks_preserve_tailo_locator_and_license(self) -> None:
        manifest = load_manifest(MANIFEST_PATH)
        report = ingest_manifest(manifest, REPOSITORY_ROOT)
        self.assertEqual(report.skipped_sources, ())
        self.assertTrue(report.chunks)
        tailo = next(
            chunk for chunk in report.chunks
            if "tshī-tiûnn" in chunk.text and chunk.locator.startswith("lesson/vocabulary")
        )
        self.assertEqual(tailo.language, "nan-TW")
        self.assertEqual(tailo.source_id, "repository-demo-market-lesson")
        self.assertEqual(tailo.source_license, "internal-demo-fixture")
        self.assertIn("lesson/vocabulary[0]", tailo.locator)
        self.assertIn("tshī-tiûnn", tailo.text)

    def test_unapproved_source_is_excluded_before_file_read(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            approved = root / "approved.jsonl"
            approved.write_text('{"text":"市場 tshī-tiûnn","locator":"entry/市場"}\n', encoding="utf-8")
            manifest = json.loads(_write_manifest(root, approved).read_text(encoding="utf-8"))
            manifest["sources"].append({
                "source_id": "unknown-license",
                "title": "Not allowed",
                "content_path": "does-not-exist.txt",
                "source_type": "text",
                "language": "nan-TW",
                "license": "unknown",
                "license_status": "pending_authorization",
                "approved_for_index": False,
                "authorization_note": "Do not index",
                "acquired_at": None,
                "source_version": "unknown",
                "content_sha256": None,
            })
            manifest_path = root / "manifest-with-pending.json"
            manifest_path.write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")
            report = ingest_manifest(load_manifest(manifest_path), root)
            self.assertEqual(len(report.chunks), 1)
            self.assertEqual(report.skipped_sources[0]["source_id"], "unknown-license")

    def test_persistent_index_keyword_fallback_and_incremental_reuse(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source.jsonl"
            source.write_text(
                '{"text":"市場 tshī-tiûnn","locator":"entry/市場"}\n'
                '{"text":"欲 beh","locator":"entry/欲"}\n',
                encoding="utf-8",
            )
            manifest_path = _write_manifest(root, source)
            index_root = root / "indexes"
            backend = create_embedding_backend("hashing-char-ngram-v1")
            builder = RagIndexBuilder(
                manifest_path=manifest_path,
                content_root=root,
                index_root=index_root,
                backend=backend,
            )
            first = builder.build(mode="full")
            self.assertTrue(first.switched)
            manager = RagIndexManager(index_root, backend)
            health = manager.open_active()
            self.assertEqual(health.status, "ready")
            result = manager.search("tshī-tiûnn", top_k=1)
            self.assertEqual(result[0].metadata["locator"], "entry/市場/0")
            self.assertEqual(result[0].metadata["index_revision"], first.revision)
            manager.close()

            second = builder.build(mode="incremental")
            self.assertFalse(second.changed)
            self.assertEqual(second.new_embeddings, 0)
            self.assertEqual(second.reused_chunks, 2)


class RagHealthIntegrationTests(unittest.IsolatedAsyncioTestCase):
    async def test_core_health_reports_active_index_revision(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            index_root = root / "rag" / "indexes"
            backend = create_embedding_backend("hashing-char-ngram-v1")
            report = RagIndexBuilder(
                manifest_path=MANIFEST_PATH,
                content_root=REPOSITORY_ROOT,
                index_root=index_root,
                backend=backend,
            ).build(mode="full")
            settings = replace(
                Settings.from_env("test"),
                data_dir=root,
                fixture_path=REPOSITORY_ROOT / "fixtures/contracts/v0.1/observer/success.lesson.json",
                speech_base_url=None,
            )
            app = create_app(settings)
            async with app.router.lifespan_context(app):
                async with httpx.AsyncClient(
                    transport=httpx.ASGITransport(app=app),
                    base_url="http://testserver",
                ) as client:
                    response = await client.get("/api/health", headers={"X-Request-ID": str(uuid.uuid4())})
            self.assertEqual(response.status_code, 200)
            services = {item["service"]: item for item in response.json()["services"]}
            self.assertEqual(services["rag"]["status"], "ready")
            self.assertEqual(services["rag"]["model_revision"], report.revision)

class RagIncrementalTests(unittest.TestCase):
    def test_incremental_rebuild_reuses_unchanged_chunk_after_source_change(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source.jsonl"
            source.write_text(
                '{"text":"市場 tshī-tiûnn","locator":"entry/市場"}\n'
                '{"text":"欲 beh","locator":"entry/欲"}\n',
                encoding="utf-8",
            )
            manifest_path = _write_manifest(root, source)
            index_root = root / "indexes"
            backend = create_embedding_backend("hashing-char-ngram-v1")
            builder = RagIndexBuilder(
                manifest_path=manifest_path,
                content_root=root,
                index_root=index_root,
                backend=backend,
            )
            builder.build(mode="full")
            source.write_text(
                '{"text":"市場 tshī-tiûnn","locator":"entry/市場"}\n'
                '{"text":"欲 beh","locator":"entry/欲"}\n'
                '{"text":"菜 tshài","locator":"entry/菜"}\n',
                encoding="utf-8",
            )
            manifest_path = _write_manifest(root, source)
            builder = RagIndexBuilder(
                manifest_path=manifest_path,
                content_root=root,
                index_root=index_root,
                backend=backend,
            )
            report = builder.build(mode="incremental")
            self.assertTrue(report.changed)
            self.assertEqual(report.reused_chunks, 2)
            self.assertEqual(report.new_embeddings, 1)

    def test_failed_build_does_not_switch_active_revision(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source.jsonl"
            source.write_text('{"text":"市場 tshī-tiûnn","locator":"entry/市場"}\n', encoding="utf-8")
            manifest_path = _write_manifest(root, source)
            index_root = root / "indexes"
            backend = create_embedding_backend("hashing-char-ngram-v1")
            builder = RagIndexBuilder(
                manifest_path=manifest_path,
                content_root=root,
                index_root=index_root,
                backend=backend,
            )
            first = builder.build(mode="full")
            active_before = json.loads((index_root / "active.json").read_text(encoding="utf-8"))["revision"]
            self.assertEqual(active_before, first.revision)
            source.unlink()
            with self.assertRaises(SourceContentError):
                builder.build(mode="full")
            active_after = json.loads((index_root / "active.json").read_text(encoding="utf-8"))["revision"]
            self.assertEqual(active_after, active_before)

    def test_twenty_query_smoke_set(self) -> None:
        queries = json.loads((REPOSITORY_ROOT / "data/rag/smoke_queries.json").read_text(encoding="utf-8"))
        self.assertEqual(len(queries), 20)
        with tempfile.TemporaryDirectory() as directory:
            index_root = Path(directory) / "indexes"
            backend = create_embedding_backend("hashing-char-ngram-v1")
            RagIndexBuilder(
                manifest_path=MANIFEST_PATH,
                content_root=REPOSITORY_ROOT,
                index_root=index_root,
                backend=backend,
            ).build(mode="full")
            manager = RagIndexManager(index_root, backend)
            self.assertEqual(manager.open_active().status, "ready")
            for item in queries:
                results = manager.search(item["query"], top_k=3)
                if item["expect"] == "no_result":
                    self.assertFalse(results, item["query"])
                else:
                    self.assertTrue(results, item["query"])
                    self.assertEqual(results[0].metadata["source_id"], item["source_id"])
                    self.assertTrue(
                        all(any(term in result.text for result in results[:1]) for term in item["contains"]),
                        item["query"],
                    )
            manager.close()


if __name__ == "__main__":
    unittest.main()
