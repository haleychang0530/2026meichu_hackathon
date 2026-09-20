from __future__ import annotations

import json
import tempfile
import unittest
import uuid
from dataclasses import replace
from pathlib import Path

import httpx

from core_api.config import Settings
from core_api.errors import ProviderError
from core_api.image_pipeline import PreparedImage
from core_api.models import ErrorCode
from core_api.providers import Mi300Client, load_lesson_schema
from tests.support import REPOSITORY_ROOT, lesson_payload


class Mi300ClientTests(unittest.IsolatedAsyncioTestCase):
    async def test_generate_skips_candidate_schema_validation_when_disabled(self) -> None:
        revision = "stage07-test-revision"
        stage_schema = json.loads(
            (REPOSITORY_ROOT / "prompts" / "lesson-analysis" / "facts.schema.json").read_text(
                encoding="utf-8"
            )
        )

        def handler(request: httpx.Request) -> httpx.Response:
            body = json.loads(request.content)
            self.assertEqual(body["response_schema"]["title"], "Stage07LessonPageFacts")
            return httpx.Response(
                200,
                json={
                    "schema_version": "0.1.0",
                    "request_id": body["request_id"],
                    "output": {"raw_output": "{}", "parsed_candidate": {}},
                    "model_revision": revision,
                },
            )

        with tempfile.TemporaryDirectory() as directory:
            image_path = Path(directory) / "image.jpg"
            image_path.write_bytes(b"jpeg")
            settings = replace(
                Settings.from_env("test"),
                provider_mode="real",
                vlm_model_revision=revision,
                vlm_output_validation_enabled=False,
            )
            client = Mi300Client(
                settings,
                load_lesson_schema(REPOSITORY_ROOT),
                transport=httpx.MockTransport(handler),
            )

            generation = await client.generate(
                PreparedImage(image_path, "image/jpeg", 1, 1, 4),
                str(uuid.uuid4()),
                prompt="facts prompt",
                response_schema=stage_schema,
            )

            self.assertEqual(generation.candidate, {})
            await client.close()

    async def test_generate_uses_stage_schema_and_does_not_retry_invalid_json(self) -> None:
        calls = 0
        revision = "stage07-test-revision"
        stage_schema = json.loads(
            (REPOSITORY_ROOT / "prompts" / "lesson-analysis" / "facts.schema.json").read_text(
                encoding="utf-8"
            )
        )

        def handler(request: httpx.Request) -> httpx.Response:
            nonlocal calls
            calls += 1
            body = json.loads(request.content)
            self.assertEqual(body["response_schema"]["title"], "Stage07LessonPageFacts")
            self.assertEqual(body["prompt"], "facts prompt")
            return httpx.Response(
                200,
                json={
                    "schema_version": "0.1.0",
                    "request_id": body["request_id"],
                    "output": {"raw_output": "{}", "parsed_candidate": {}},
                    "model_revision": revision,
                },
            )

        with tempfile.TemporaryDirectory() as directory:
            image_path = Path(directory) / "image.jpg"
            image_path.write_bytes(b"jpeg")
            settings = replace(
                Settings.from_env("test"),
                provider_mode="real",
                vlm_model_revision=revision,
                vlm_output_validation_enabled=True,
                max_attempts=3,
                retry_backoff_seconds=0,
            )
            client = Mi300Client(
                settings,
                load_lesson_schema(REPOSITORY_ROOT),
                transport=httpx.MockTransport(handler),
            )
            with self.assertRaises(ProviderError) as caught:
                await client.generate(
                    PreparedImage(image_path, "image/jpeg", 1, 1, 4),
                    str(uuid.uuid4()),
                    prompt="facts prompt",
                    response_schema=stage_schema,
                )
            self.assertEqual(caught.exception.code, ErrorCode.VLM_INVALID_OUTPUT)
            self.assertFalse(caught.exception.retryable)
            self.assertEqual(calls, 1)
            await client.close()

    async def test_timeout_is_bounded_and_retryable(self) -> None:
        calls = 0

        def handler(request: httpx.Request) -> httpx.Response:
            nonlocal calls
            calls += 1
            raise httpx.ReadTimeout("late", request=request)

        with tempfile.TemporaryDirectory() as directory:
            image_path = Path(directory) / "image.jpg"
            image_path.write_bytes(b"jpeg")
            settings = replace(
                Settings.from_env("test"),
                provider_mode="real",
                max_attempts=2,
                retry_backoff_seconds=0,
                circuit_failure_threshold=3,
            )
            client = Mi300Client(
                settings,
                load_lesson_schema(REPOSITORY_ROOT),
                transport=httpx.MockTransport(handler),
            )
            with self.assertRaises(ProviderError) as caught:
                await client.analyze(
                    PreparedImage(image_path, "image/jpeg", 1, 1, 4),
                    str(uuid.uuid4()),
                )
            self.assertEqual(caught.exception.code, ErrorCode.VLM_TIMEOUT)
            self.assertTrue(caught.exception.retryable)
            self.assertEqual(calls, 2)
            await client.close()

    async def test_retries_then_opens_circuit(self) -> None:
        calls = 0

        def handler(request: httpx.Request) -> httpx.Response:
            nonlocal calls
            calls += 1
            return httpx.Response(503, json={"code": "VLM_OFFLINE", "message": "offline", "retryable": True})

        with tempfile.TemporaryDirectory() as directory:
            image_path = Path(directory) / "image.jpg"
            image_path.write_bytes(b"jpeg")
            settings = replace(
                Settings.from_env("test"),
                provider_mode="real",
                max_attempts=2,
                retry_backoff_seconds=0,
                circuit_failure_threshold=1,
            )
            client = Mi300Client(
                settings,
                load_lesson_schema(REPOSITORY_ROOT),
                transport=httpx.MockTransport(handler),
            )
            image = PreparedImage(image_path, "image/jpeg", 1, 1, 4)
            with self.assertRaises(ProviderError) as first:
                await client.analyze(image, str(uuid.uuid4()))
            self.assertEqual(first.exception.code, ErrorCode.VLM_OFFLINE)
            self.assertEqual(calls, 2)
            with self.assertRaises(ProviderError) as second:
                await client.analyze(image, str(uuid.uuid4()))
            self.assertEqual(second.exception.code, ErrorCode.CIRCUIT_OPEN)
            self.assertEqual(calls, 2)
            await client.close()

    async def test_success_validates_request_and_response(self) -> None:
        revision = "test-revision"

        def handler(request: httpx.Request) -> httpx.Response:
            body = json.loads(request.content)
            self.assertEqual(body["schema_version"], "0.1.0")
            self.assertEqual(request.headers["X-Request-ID"], body["request_id"])
            candidate = lesson_payload("model-authored-revision")
            candidate["rag_index_revision"] = "invented-index"
            return httpx.Response(
                200,
                json={
                    "schema_version": "0.1.0",
                    "request_id": body["request_id"],
                    "output": {
                        "raw_output": "{}",
                        "parsed_candidate": candidate,
                        "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
                        "finish_reason": "stop",
                    },
                    "model_revision": revision,
                    "latency_ms": 2,
                    "queue_ms": 0,
                    "inference_ms": 2,
                },
            )

        with tempfile.TemporaryDirectory() as directory:
            image_path = Path(directory) / "image.jpg"
            image_path.write_bytes(b"jpeg")
            settings = replace(
                Settings.from_env("test"),
                provider_mode="real",
                vlm_model_revision=revision,
            )
            client = Mi300Client(
                settings,
                load_lesson_schema(REPOSITORY_ROOT),
                transport=httpx.MockTransport(handler),
            )
            lesson = await client.analyze(
                PreparedImage(image_path, "image/jpeg", 1, 1, 4),
                str(uuid.uuid4()),
            )
            self.assertEqual(lesson.vlm_model_revision, revision)
            self.assertIsNone(lesson.rag_index_revision)
            self.assertEqual(lesson.evidence, [])
            self.assertEqual(lesson.review_status, "pending")
            await client.close()


if __name__ == "__main__":
    unittest.main()
