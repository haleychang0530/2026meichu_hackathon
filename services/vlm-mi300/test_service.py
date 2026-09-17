"""Unit tests for the stateless MI300 gateway without loading a model."""

from __future__ import annotations

import asyncio
import base64
import io
import unittest
import uuid

import httpx
from PIL import Image

import service


def make_png() -> str:
    image = Image.new("RGB", (32, 24), "white")
    output = io.BytesIO()
    image.save(output, format="PNG")
    return base64.b64encode(output.getvalue()).decode("ascii")


def make_settings(**overrides) -> service.Settings:
    values = {
        "upstream_url": "http://127.0.0.1:8000/v1",
        "model": "test-model",
        "model_revision": "test-revision",
        "allowed_cidrs_text": "127.0.0.1/32",
        "max_request_bytes": 2 * 1024 * 1024,
        "max_image_bytes": 512 * 1024,
        "max_image_pixels": 1_000_000,
        "max_image_dimension": 2048,
        "max_prompt_chars": 50_000,
        "max_schema_bytes": 64 * 1024,
        "max_evidence_items": 20,
        "max_evidence_bytes": 64 * 1024,
        "max_context_tokens": 4096,
        "max_output_tokens": 512,
        "image_token_budget": 128,
        "queue_max": 1,
        "concurrency": 1,
        "request_timeout_seconds": 1.0,
        "upstream_connect_timeout_seconds": 0.2,
        "health_timeout_seconds": 0.2,
    }
    values.update(overrides)
    return service.Settings(**values)


def make_request(settings: service.Settings, *, media_type: str = "image/png", prompt: str = "answer") -> service.GenerateRequest:
    return service.GenerateRequest(
        schema_version="0.1.0",
        request_id=uuid.uuid4(),
        image={"media_type": media_type, "content_base64": make_png()},
        prompt=prompt,
        response_schema={
            "type": "object",
            "additionalProperties": False,
            "properties": {"answer": {"type": "string"}},
            "required": ["answer"],
        },
        model_revision=settings.model_revision,
    )


class SlowTransport(httpx.AsyncBaseTransport):
    def __init__(self, delay: float) -> None:
        self.delay = delay

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        await asyncio.sleep(self.delay)
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": '{"answer":"ok"}'}, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 3, "completion_tokens": 2, "total_tokens": 5},
            },
            request=request,
        )


class GatewayTests(unittest.TestCase):
    def test_image_and_schema_validation_normalizes_metadata(self) -> None:
        settings = make_settings()
        request = make_request(settings)
        image, validator, estimated = service.validate_request_limits(request, settings)
        self.assertEqual(image.media_type, "image/png")
        self.assertEqual((image.width, image.height), (32, 24))
        self.assertIsInstance(validator, service.Draft202012Validator)
        self.assertGreater(estimated, 0)

    def test_mime_mismatch_is_rejected(self) -> None:
        settings = make_settings()
        with self.assertRaises(service.ServiceError) as raised:
            service.validate_request_limits(make_request(settings, media_type="image/jpeg"), settings)
        self.assertEqual(raised.exception.code, "VALIDATION_ERROR")

    def test_invalid_schema_is_rejected(self) -> None:
        settings = make_settings()
        request = make_request(settings)
        request.response_schema = {"type": "not-a-json-schema-type"}
        with self.assertRaises(service.ServiceError) as raised:
            service.validate_request_limits(request, settings)
        self.assertEqual(raised.exception.code, "VALIDATION_ERROR")

    def test_parse_upstream_response_returns_raw_and_candidate(self) -> None:
        settings = make_settings()
        request = make_request(settings)
        image, _validator, _estimated = service.validate_request_limits(request, settings)
        loop = asyncio.new_event_loop()
        try:
            gateway = service.InferenceService(settings)
            future = loop.create_future()
            job = service.InferenceJob(request, image, 0.0, future)
            result = gateway._parse_upstream_response(
                job,
                {
                    "choices": [{"message": {"content": '{"answer":"ok"}'}, "finish_reason": "stop"}],
                    "usage": {"prompt_tokens": 3, "completion_tokens": 2, "total_tokens": 5},
                },
                4,
                8,
            )
        finally:
            loop.close()
        self.assertEqual(result["output"]["raw_output"], '{"answer":"ok"}')
        self.assertEqual(result["output"]["parsed_candidate"], {"answer": "ok"})
        self.assertEqual(result["output"]["usage"]["total_tokens"], 5)
        self.assertEqual(result["output"]["finish_reason"], "stop")
        self.assertEqual(result["latency_ms"], 12)


class QueueTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.settings = make_settings()
        self.gateway = service.InferenceService(self.settings)
        await self.gateway.start()
        await self.gateway.client.aclose()
        self.gateway.client = httpx.AsyncClient(transport=SlowTransport(0.25))

    async def asyncTearDown(self) -> None:
        await self.gateway.stop()

    async def test_timeout_cancels_inflight_upstream(self) -> None:
        self.gateway.settings = make_settings(request_timeout_seconds=0.05)
        request = make_request(self.gateway.settings)
        image, _validator, _estimated = service.validate_request_limits(request, self.gateway.settings)
        with self.assertRaises(service.ServiceError) as raised:
            await self.gateway.submit(request, image)
        self.assertEqual(raised.exception.code, "VLM_TIMEOUT")
        self.assertGreaterEqual(self.gateway.cancelled_requests, 1)

    async def test_caller_cancellation_is_propagated(self) -> None:
        request = make_request(self.settings)
        image, _validator, _estimated = service.validate_request_limits(request, self.settings)
        task = asyncio.create_task(self.gateway.submit(request, image))
        await asyncio.sleep(0.02)
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        await asyncio.sleep(0.02)
        self.assertEqual(len(self.gateway.workers), 1)

    async def test_bounded_queue_rejects_excess_work(self) -> None:
        requests = [make_request(self.settings) for _ in range(3)]
        images = [service.validate_request_limits(item, self.settings)[0] for item in requests]
        tasks = [asyncio.create_task(self.gateway.submit(item, image)) for item, image in zip(requests, images)]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        errors = [item for item in results if isinstance(item, service.ServiceError)]
        self.assertTrue(any(item.status_code == 429 for item in errors))


if __name__ == "__main__":
    unittest.main()
