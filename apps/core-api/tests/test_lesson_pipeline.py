from __future__ import annotations

import copy
import json
import tempfile
import unittest
from pathlib import Path

from core_api.errors import ProviderError
from core_api.image_pipeline import PreparedImage
from core_api.lesson_pipeline import LessonAnalysisPipeline, accessible_activity_issues
from core_api.providers import StructuredGeneration
from core_api.rag import EvidenceCitation, RetrievalBundle


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
FIXTURE_PATH = REPOSITORY_ROOT / "fixtures" / "lesson-analysis" / "stage07" / "01-market-picture.json"


class RecordingGenerator:
    def __init__(self, candidates: list[object]) -> None:
        self.candidates = list(candidates)
        self.calls: list[dict[str, object]] = []

    async def generate(self, image, request_id, *, prompt, response_schema, evidence=None):
        self.calls.append({
            "request_id": request_id,
            "prompt": prompt,
            "response_schema": response_schema,
            "evidence": evidence,
        })
        candidate = self.candidates.pop(0)
        return StructuredGeneration(
            candidate=candidate,
            model_revision="stage07-test-model",
            raw_output="{\"candidate\":\"kept in memory only\"}",
            latency_ms=5,
            queue_ms=1,
            inference_ms=4,
        )


class RecordingRetriever:
    def __init__(self) -> None:
        self.queries: list[str] = []
        self.citation = EvidenceCitation(
            source_id="repository-demo-market-lesson",
            title="Repository demo lesson",
            excerpt="市場 tshī-tiûnn；教材活動需由教師審查。",
            locator="lesson/vocabulary[0]",
            score=0.91,
            index_revision="rag-stage07-test",
        )

    def retrieve(self, query: str) -> RetrievalBundle:
        self.queries.append(query)
        return RetrievalBundle(
            query=query,
            evidence=(self.citation,),
            index_revision=self.citation.index_revision,
            context_chars=len(self.citation.excerpt),
        )


def _fixture_parts() -> tuple[dict[str, object], dict[str, object]]:
    payload = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    return payload["facts"], payload["activity"]


class LessonAnalysisPipelineTests(unittest.IsolatedAsyncioTestCase):
    async def _run(self, generator: RecordingGenerator) -> tuple[LessonAnalysisPipeline, RecordingRetriever, object]:
        retriever = RecordingRetriever()
        pipeline = LessonAnalysisPipeline(generator, retriever)
        with tempfile.TemporaryDirectory() as directory:
            image_path = Path(directory) / "normalized.jpg"
            image_path.write_bytes(b"normalized-image-placeholder")
            lesson = await pipeline.analyze(
                PreparedImage(image_path, "image/jpeg", 64, 64, image_path.stat().st_size),
                "00000000-0000-4000-8000-000000000007",
            )
        return pipeline, retriever, lesson

    async def test_two_step_pipeline_binds_local_citations_and_keeps_lesson_pending(self) -> None:
        facts, activity = _fixture_parts()
        generator = RecordingGenerator([facts, activity])
        pipeline, retriever, lesson = await self._run(generator)

        self.assertTrue(pipeline.supports_two_step_generation)
        self.assertEqual(len(generator.calls), 2)
        self.assertEqual(generator.calls[0]["response_schema"]["title"], "Stage07LessonPageFacts")
        self.assertEqual(generator.calls[1]["response_schema"]["title"], "Stage07AccessibleActivity")
        self.assertEqual(generator.calls[1]["evidence"][0]["source_id"], retriever.citation.source_id)
        self.assertEqual(lesson.review_status, "pending")
        self.assertTrue(lesson.answer_evidence)
        self.assertTrue(facts["source_text_complete"])
        self.assertEqual(lesson.source_text, facts["source_text"])
        self.assertEqual(lesson.rag_index_revision, "rag-stage07-test")
        self.assertEqual(lesson.evidence[0].locator, retriever.citation.locator)
        self.assertNotIn(facts["answer_evidence"][0], retriever.queries[0])
        self.assertEqual(
            accessible_activity_issues(
                lesson.accessible_activity,
                lesson.answer_evidence,
                {"answer_leak_free": True, "no_position_hint": True, "no_sighted_only_clue": True},
            ),
            (),
        )

    async def test_source_text_is_preserved_verbatim_through_lesson_assembly(self) -> None:
        facts, activity = _fixture_parts()
        source_text = "第一句保留標點。\n第二句也要完整保存？"
        facts = copy.deepcopy(facts)
        facts["source_text"] = source_text
        generator = RecordingGenerator([facts, activity])
        _, _, lesson = await self._run(generator)

        self.assertEqual(lesson.source_text, source_text)
        self.assertIn("第一句保留標點。", lesson.source_text)
        self.assertIn("第二句也要完整保存？", lesson.source_text)

    async def test_incomplete_source_text_is_repaired_once_then_requires_manual_review(self) -> None:
        facts, _ = _fixture_parts()
        incomplete = copy.deepcopy(facts)
        incomplete["source_text_complete"] = False
        generator = RecordingGenerator([incomplete, incomplete])
        pipeline = LessonAnalysisPipeline(generator, RecordingRetriever())
        with tempfile.TemporaryDirectory() as directory:
            image_path = Path(directory) / "normalized.jpg"
            image_path.write_bytes(b"normalized-image-placeholder")
            with self.assertRaises(ProviderError) as caught:
                await pipeline.analyze(
                    PreparedImage(image_path, "image/jpeg", 64, 64, image_path.stat().st_size),
                    "00000000-0000-4000-8000-000000000009",
                )

        self.assertEqual(caught.exception.code.value, "VLM_INVALID_OUTPUT")
        self.assertFalse(caught.exception.retryable)
        self.assertEqual(caught.exception.details["stage"], "facts")
        self.assertIn("source_text_incomplete", caught.exception.details["reasons"])
        self.assertEqual(len(generator.calls), 2)

    async def test_invalid_json_gets_exactly_one_traceable_repair(self) -> None:
        facts, activity = _fixture_parts()
        generator = RecordingGenerator([{}, facts, activity])
        pipeline, _, lesson = await self._run(generator)

        self.assertEqual(lesson.review_status, "pending")
        self.assertEqual(len(generator.calls), 3)
        self.assertIn("VALIDATION_REASONS", generator.calls[1]["prompt"])
        self.assertIn("PREVIOUS_CANDIDATE_IF_PARSEABLE", generator.calls[1]["prompt"])
        self.assertEqual(pipeline.last_trace[0].stage, "facts")
        self.assertEqual(pipeline.last_trace[0].attempts, 2)
        self.assertTrue(pipeline.last_trace[0].repair_attempted)
        self.assertEqual(pipeline.last_trace[1].attempts, 1)

    async def test_unsafe_activity_repair_failure_is_explicit_and_not_retried_again(self) -> None:
        facts, activity = _fixture_parts()
        unsafe = copy.deepcopy(activity)
        unsafe["accessible_activity"] = "請看圖左邊的答案並指出它。"
        generator = RecordingGenerator([facts, unsafe, unsafe])
        retriever = RecordingRetriever()
        pipeline = LessonAnalysisPipeline(generator, retriever)
        with tempfile.TemporaryDirectory() as directory:
            image_path = Path(directory) / "normalized.jpg"
            image_path.write_bytes(b"normalized-image-placeholder")
            with self.assertRaises(ProviderError) as caught:
                await pipeline.analyze(
                    PreparedImage(image_path, "image/jpeg", 64, 64, image_path.stat().st_size),
                    "00000000-0000-4000-8000-000000000008",
                )

        self.assertEqual(caught.exception.code.value, "VLM_INVALID_OUTPUT")
        self.assertFalse(caught.exception.retryable)
        self.assertEqual(caught.exception.details["stage"], "activity")
        self.assertTrue(caught.exception.details["repair_attempted"])
        self.assertEqual(len(generator.calls), 3)


if __name__ == "__main__":
    unittest.main()
