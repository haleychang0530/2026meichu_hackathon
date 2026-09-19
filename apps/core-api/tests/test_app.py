from __future__ import annotations

import json
import tempfile
import unittest
import uuid
from dataclasses import replace
from pathlib import Path

import httpx
from jsonschema import Draft202012Validator, FormatChecker, RefResolver

from core_api.app import create_app
from core_api.config import Settings
from core_api.errors import ProviderError
from core_api.models import ErrorCode, ServiceHealth
from core_api.providers import FixtureProvider
from tests.support import FIXTURE_PATH, REPOSITORY_ROOT, jpeg_bytes


class OfflineProvider:
    mode = "real"

    async def analyze(self, image, request_id):
        raise ProviderError(
            ErrorCode.VLM_OFFLINE,
            "MI300 is offline",
            status_code=503,
            retryable=True,
            fallback="fixture_mode",
        )

    async def health(self, request_id):
        fixture = FixtureProvider(FIXTURE_PATH)
        health = await fixture.health(request_id)
        return ServiceHealth.model_validate(
            {**health.model_dump(mode="json"), "status": "offline", "model_revision": None}
        )

    async def close(self):
        return None


class AppTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.settings = replace(
            Settings.from_env("test"),
            data_dir=Path(self.temporary.name),
            fixture_path=FIXTURE_PATH,
            speech_base_url=None,
        )

    async def asyncTearDown(self) -> None:
        self.temporary.cleanup()

    async def _request(self, app, method: str, path: str, **kwargs):
        async with app.router.lifespan_context(app):
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app),
                base_url="http://testserver",
            ) as client:
                return await client.request(method, path, **kwargs)

    async def test_health_starts_without_mi300_and_is_explicitly_degraded(self) -> None:
        app = create_app(self.settings)
        request_id = str(uuid.uuid4())
        response = await self._request(app, "GET", "/api/health", headers={"X-Request-ID": request_id})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["X-Request-ID"], request_id)
        body = response.json()
        self.assertEqual(body["status"], "degraded")
        services = {item["service"]: item for item in body["services"]}
        self.assertEqual(services["core-api"]["status"], "ready")
        self.assertEqual(services["vlm-mi300"]["last_error"]["fallback"], "fixture_mode")
        self.assertEqual({*services}, {"core-api", "rag", "vlm-mi300", "asr", "tts"})
        schema_dir = REPOSITORY_ROOT / "packages" / "contracts" / "schemas" / "v0.1"
        service_schema = json.loads((schema_dir / "service-health.schema.json").read_text(encoding="utf-8"))
        error_schema = json.loads((schema_dir / "error.schema.json").read_text(encoding="utf-8"))
        resolver = RefResolver.from_schema(service_schema, store={error_schema["$id"]: error_schema})
        validator = Draft202012Validator(
            service_schema,
            resolver=resolver,
            format_checker=FormatChecker(),
        )
        for item in services.values():
            validator.validate(item)

    async def test_cors_allows_agent_b_vite_origin_and_exposes_headers(self) -> None:
        app = create_app(self.settings)
        response = await self._request(
            app,
            "OPTIONS",
            "/api/lessons/analyze",
            headers={
                "Origin": "http://127.0.0.1:5173",
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "X-Request-ID",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["Access-Control-Allow-Origin"], "http://127.0.0.1:5173")
        simple = await self._request(
            create_app(self.settings),
            "GET",
            "/api/health",
            headers={"Origin": "http://127.0.0.1:5173"},
        )
        exposed = simple.headers.get("Access-Control-Expose-Headers", "").lower()
        self.assertIn("x-request-id", exposed)
        self.assertIn("x-provider-mode", exposed)

    async def test_fixture_analysis_matches_canonical_lesson_and_cleans_upload(self) -> None:
        app = create_app(self.settings)
        response = await self._request(
            app,
            "POST",
            "/api/lessons/analyze",
            files={"image": ("page.jpg", jpeg_bytes(), "image/jpeg")},
            data={"language": "nan-TW", "use_fixture_on_failure": "true"},
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.headers["X-Provider-Mode"], "fixture")
        schema = REPOSITORY_ROOT / "packages" / "contracts" / "schemas" / "v0.1" / "lesson.schema.json"
        Draft202012Validator(json.loads(schema.read_text(encoding="utf-8"))).validate(response.json())
        self.assertEqual(response.json()["vlm_model_revision"], "fixture:v0.1")
        self.assertEqual(list(self.settings.upload_dir.glob("lesson-*")), [])

    async def test_lesson_stays_pending_until_teacher_review(self) -> None:
        app = create_app(self.settings)
        created = await self._request(
            app,
            "POST",
            "/api/lessons/analyze",
            files={"image": ("page.jpg", jpeg_bytes(), "image/jpeg")},
            data={"language": "nan-TW", "use_fixture_on_failure": "true"},
        )
        self.assertEqual(created.status_code, 200, created.text)
        lesson_id = created.json()["lesson_id"]
        self.assertEqual(created.json()["review_status"], "pending")
        self.assertTrue(created.json()["answer_evidence"])

        fetched = await self._request(app, "GET", f"/api/lessons/{lesson_id}")
        self.assertEqual(fetched.status_code, 200, fetched.text)
        self.assertEqual(fetched.json()["review_status"], "pending")
        self.assertEqual(fetched.json()["source_text"], created.json()["source_text"])

        approved = await self._request(
            app,
            "PATCH",
            f"/api/lessons/{lesson_id}",
            json={"review_status": "approved"},
        )
        self.assertEqual(approved.status_code, 200, approved.text)
        self.assertEqual(approved.json()["review_status"], "approved")

        unsafe = await self._request(
            app,
            "PATCH",
            f"/api/lessons/{lesson_id}",
            json={"accessible_activity": "請看圖左邊的答案"},
        )
        self.assertEqual(unsafe.status_code, 400, unsafe.text)
        self.assertEqual(unsafe.json()["code"], "VALIDATION_ERROR")

    async def test_offline_provider_falls_back_only_when_requested(self) -> None:
        app = create_app(self.settings, provider=OfflineProvider())
        fallback = await self._request(
            app,
            "POST",
            "/api/lessons/analyze",
            files={"image": ("page.jpg", jpeg_bytes(), "image/jpeg")},
            data={"language": "nan-TW", "use_fixture_on_failure": "true"},
        )
        self.assertEqual(fallback.status_code, 200)
        self.assertEqual(fallback.headers["X-Provider-Mode"], "fixture-fallback")

        app = create_app(self.settings, provider=OfflineProvider())
        error = await self._request(
            app,
            "POST",
            "/api/lessons/analyze",
            files={"image": ("page.jpg", jpeg_bytes(), "image/jpeg")},
            data={"language": "nan-TW", "use_fixture_on_failure": "false"},
        )
        self.assertEqual(error.status_code, 503)
        self.assertEqual(error.json()["code"], "VLM_OFFLINE")
        self.assertEqual(error.json()["request_id"], error.headers["X-Request-ID"])

    async def test_invalid_image_uses_common_error_contract(self) -> None:
        app = create_app(self.settings)
        response = await self._request(
            app,
            "POST",
            "/api/lessons/analyze",
            files={"image": ("page.jpg", b"not an image", "image/jpeg")},
            data={"language": "nan-TW"},
        )
        self.assertEqual(response.status_code, 400)
        schema_path = REPOSITORY_ROOT / "packages" / "contracts" / "schemas" / "v0.1" / "error.schema.json"
        Draft202012Validator(
            json.loads(schema_path.read_text(encoding="utf-8")),
            format_checker=Draft202012Validator.FORMAT_CHECKER,
        ).validate(response.json())
        self.assertEqual(response.json()["request_id"], response.headers["X-Request-ID"])
        self.assertEqual(list(self.settings.upload_dir.glob("lesson-*")), [])

    async def test_runtime_openapi_documents_only_laptop_routes(self) -> None:
        app = create_app(self.settings)
        response = await self._request(app, "GET", "/openapi.json")
        self.assertEqual(response.status_code, 200)
        document = response.json()
        self.assertIn("/api/health", document["paths"])
        self.assertIn("/api/lessons/analyze", document["paths"])
        self.assertIn("/api/utterances/normalize", document["paths"])
        self.assertNotIn("/internal/vlm/generate", document["paths"])
        self.assertNotIn(self.settings.vlm_base_url, response.text)
        responses = document["paths"]["/api/lessons/analyze"]["post"]["responses"]
        self.assertTrue({"200", "400", "503", "504"}.issubset(responses))
        normalize = document["paths"]["/api/utterances/normalize"]["post"]
        self.assertEqual(normalize["operationId"], "normalizeUtterance")
        request_schema = normalize["requestBody"]["content"]["application/json"]["schema"]
        if "$ref" in request_schema:
            request_schema = document["components"]["schemas"][request_schema["$ref"].rsplit("/", 1)[-1]]
        self.assertIn("schema_version", request_schema["required"])


if __name__ == "__main__":
    unittest.main()
