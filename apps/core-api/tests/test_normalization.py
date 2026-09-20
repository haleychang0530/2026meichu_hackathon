from __future__ import annotations

import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

import httpx
from jsonschema import Draft202012Validator

from core_api.app import create_app
from core_api.config import Settings
from core_api.language import LanguageNormalizer, tailo_to_mms_poj
from tests.support import FIXTURE_PATH, REPOSITORY_ROOT


GOLDEN_PATH = REPOSITORY_ROOT / "data/language/normalization-golden.json"


class LanguageNormalizationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.normalizer = LanguageNormalizer(GOLDEN_PATH)
        cls.document = json.loads(GOLDEN_PATH.read_text(encoding="utf-8"))

    def test_golden_set_has_at_least_thirty_complete_reproducible_entries(self) -> None:
        entries = self.document["entries"]
        self.assertGreaterEqual(len(entries), 30)
        for entry in entries:
            for key in ("hanji", "tailo", "poj", "zh_gloss", "example"):
                self.assertTrue(entry[key], f"{entry['id']} missing {key}")
            converted, unknown = tailo_to_mms_poj(entry["tailo"])
            self.assertEqual(converted, entry["poj"], entry["id"])
            self.assertEqual(unknown, (), entry["id"])

    def test_verified_hanji_uses_curated_tailo_and_mms_ready_poj(self) -> None:
        result = self.normalizer.normalize(text="市場", lang="nan-TW")
        segment = result.utterance.segments[0]
        self.assertEqual(segment.tailo_citation, "tshī-tiûnn")
        self.assertEqual(segment.poj_citation, "chhī-tiûnn")
        self.assertEqual(segment.pronunciation_status, "verified")
        self.assertEqual(result.utterance.tts_provider, "mms-tts-nan")
        self.assertFalse(result.audit.needs_review_reasons)

    def test_textbook_tailo_is_preserved_and_conflict_requires_review(self) -> None:
        result = self.normalizer.normalize(
            text="市場",
            lang="nan-TW",
            tailo_citation="khì",
        )
        segment = result.utterance.segments[0]
        self.assertEqual(segment.tailo_citation, "khì")
        self.assertEqual(segment.poj_citation, "khì")
        self.assertEqual(segment.source, "textbook")
        self.assertEqual(segment.pronunciation_status, "needs_review")
        self.assertEqual(result.utterance.tts_provider, "mms-tts-nan")
        self.assertIn("textbook_dictionary_conflict", result.audit.needs_review_reasons)

    def test_oov_and_multiple_readings_do_not_emit_tts_input(self) -> None:
        oov = self.normalizer.normalize(text="未收錄詞", lang="nan-TW")
        ambiguous = self.normalizer.normalize(text="行", lang="nan-TW")
        self.assertEqual(oov.audit.needs_review_reasons, ("oov",))
        self.assertGreaterEqual(len(ambiguous.audit.tailo_candidates), 2)
        oov_segment = oov.utterance.segments[0]
        self.assertEqual(oov_segment.pronunciation_status, "needs_review")
        self.assertIsNone(oov_segment.poj_citation)
        self.assertIsNone(oov.utterance.tts_provider)

        ambiguous_segment = ambiguous.utterance.segments[0]
        self.assertEqual(ambiguous_segment.pronunciation_status, "needs_review")
        self.assertEqual(ambiguous_segment.poj_citation, "kiânn")
        self.assertEqual(ambiguous.utterance.tts_provider, "mms-tts-nan")

    def test_unsupported_mms_character_requires_review(self) -> None:
        result = self.normalizer.normalize(
            text="教材字",
            lang="nan-TW",
            tailo_citation="ra",
        )
        self.assertIn("unsupported_mms_character", result.audit.needs_review_reasons)
        self.assertIsNone(result.utterance.segments[0].poj_citation)
        self.assertIsNone(result.utterance.tts_provider)

    def test_audit_records_tool_versions_and_each_step_io(self) -> None:
        result = self.normalizer.normalize(
            text="阿媽欲去市場買菜",
            lang="nan-TW",
        )
        self.assertEqual(
            [step.name for step in result.audit.steps],
            [
                "unicode_normalization",
                "hanji_to_tailo_candidates",
                "tailo_to_poj",
                "mms_vocabulary_gate",
            ],
        )
        for step in result.audit.steps:
            self.assertTrue(step.tool_version)
            self.assertIsInstance(step.input, dict)
            self.assertIsInstance(step.output, dict)

    def test_zh_tw_routes_to_windows_without_romanization(self) -> None:
        result = self.normalizer.normalize(text="先聽一次台語。", lang="zh-TW")
        segment = result.utterance.segments[0]
        self.assertIsNone(segment.tailo_citation)
        self.assertIsNone(segment.poj_citation)
        self.assertEqual(result.utterance.tts_provider, "windows")

    def test_labeled_prompt_uses_local_longest_match_and_keeps_mi300_without_poj(self) -> None:
        result = self.normalizer.normalize_labeled_segments(
            text="我會帶你讀學校",
            segments=[
                {"lang": "zh-TW", "content": "我會帶你讀"},
                {"lang": "nan-TW", "content": "學校"},
            ],
        )
        self.assertEqual([item.lang for item in result.utterance.segments], ["zh-TW", "nan-TW"])
        self.assertEqual(result.utterance.segments[1].tailo_citation, "ha̍k-hāu")
        self.assertEqual(result.utterance.segments[1].poj_citation, "ha̍k-hāu")
        self.assertEqual(result.utterance.tts_provider, "mms-tts-nan")
        self.assertIn("language_segment_concatenation", [step.name for step in result.audit.steps])

    def test_labeled_oov_is_explicit_review_and_has_no_poj(self) -> None:
        result = self.normalizer.normalize_labeled_segments(
            text="請說未收錄詞",
            segments=[{"lang": "nan-TW", "content": "請說未收錄詞"}],
        )
        self.assertTrue(any(item.pronunciation_status == "needs_review" for item in result.utterance.segments))
        self.assertIsNone(result.utterance.tts_provider)
        self.assertTrue(any(item.poj_citation is None for item in result.utterance.segments))

    def test_labeled_segments_must_concatenate_to_original_text(self) -> None:
        with self.assertRaisesRegex(ValueError, "do not concatenate"):
            self.normalizer.normalize_labeled_segments(
                text="我會帶你讀學校",
                segments=[{"lang": "zh-TW", "content": "我會帶你讀"}],
            )


class NormalizeApiTests(unittest.IsolatedAsyncioTestCase):
    async def test_normalize_endpoint_returns_canonical_utterance(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            settings = replace(
                Settings.from_env("test"),
                data_dir=Path(directory),
                fixture_path=FIXTURE_PATH,
                speech_base_url=None,
                language_golden_path=GOLDEN_PATH,
            )
            app = create_app(settings)
            async with app.router.lifespan_context(app):
                async with httpx.AsyncClient(
                    transport=httpx.ASGITransport(app=app),
                    base_url="http://testserver",
                ) as client:
                    response = await client.post(
                        "/api/utterances/normalize",
                        json={
                            "schema_version": "0.1.0",
                            "text": "市場",
                            "lang": "nan-TW",
                            "tailo_citation": "tshī-tiûnn",
                        },
                    )
            self.assertEqual(response.status_code, 200, response.text)
            schema = json.loads(
                (REPOSITORY_ROOT / "packages/contracts/schemas/v0.1/utterance.schema.json")
                .read_text(encoding="utf-8")
            )
            Draft202012Validator(schema).validate(response.json())
            segment = response.json()["segments"][0]
            self.assertEqual(segment["tailo_citation"], "tshī-tiûnn")
            self.assertEqual(segment["poj_citation"], "chhī-tiûnn")
            self.assertEqual(segment["pronunciation_status"], "converted")


if __name__ == "__main__":
    unittest.main()
