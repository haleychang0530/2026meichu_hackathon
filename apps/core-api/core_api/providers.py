from __future__ import annotations

import asyncio
import base64
import copy
import json
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

import httpx
from jsonschema import Draft202012Validator, SchemaError, ValidationError

from .config import Settings
from .errors import ProviderError
from .image_pipeline import PreparedImage
from .models import ErrorCode, Lesson, SCHEMA_VERSION, ServiceHealth


class LessonProvider(Protocol):
    mode: str

    async def analyze(self, image: PreparedImage, request_id: str) -> Lesson: ...

    async def health(self, request_id: str) -> ServiceHealth: ...

    async def close(self) -> None: ...


class CircuitBreaker:
    def __init__(self, failure_threshold: int, recovery_seconds: float) -> None:
        self.failure_threshold = failure_threshold
        self.recovery_seconds = recovery_seconds
        self.failures = 0
        self.opened_at: float | None = None
        self._half_open_in_flight = False
        self._lock = asyncio.Lock()

    async def allow(self) -> bool:
        async with self._lock:
            if self.opened_at is None:
                return True
            if time.monotonic() - self.opened_at < self.recovery_seconds:
                return False
            if self._half_open_in_flight:
                return False
            self._half_open_in_flight = True
            return True

    async def success(self) -> None:
        async with self._lock:
            self.failures = 0
            self.opened_at = None
            self._half_open_in_flight = False

    async def failure(self) -> None:
        async with self._lock:
            self.failures += 1
            self._half_open_in_flight = False
            if self.failures >= self.failure_threshold:
                self.opened_at = time.monotonic()

    @property
    def state(self) -> str:
        if self.opened_at is None:
            return "closed"
        if time.monotonic() - self.opened_at >= self.recovery_seconds:
            return "half-open"
        return "open"


@dataclass(slots=True)
class StructuredGeneration:
    candidate: Any
    model_revision: str
    raw_output: str
    latency_ms: int
    queue_ms: int
    inference_ms: int


@dataclass(slots=True)
class VlmResponse:
    lesson: Lesson
    model_revision: str


class Mi300Client:
    mode = "real"

    def __init__(
        self,
        settings: Settings,
        lesson_schema: dict[str, Any],
        *,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.settings = settings
        self.lesson_schema = lesson_schema
        self.validator = Draft202012Validator(lesson_schema)
        self.breaker = CircuitBreaker(
            settings.circuit_failure_threshold,
            settings.circuit_recovery_seconds,
        )
        timeout = httpx.Timeout(
            connect=settings.connect_timeout_seconds,
            read=settings.read_timeout_seconds,
            write=settings.connect_timeout_seconds,
            pool=settings.connect_timeout_seconds,
        )
        self.client = httpx.AsyncClient(base_url=settings.vlm_base_url, timeout=timeout, transport=transport)

    async def generate(
        self,
        image: PreparedImage,
        request_id: str,
        *,
        prompt: str,
        response_schema: dict[str, Any],
        evidence: list[dict[str, Any]] | None = None,
    ) -> StructuredGeneration:
        """Run one bounded, stateless structured inference request.

        Stage 07 composes two calls from this primitive. The client validates
        the gateway result again so a caller cannot accidentally trust an
        unvalidated candidate even when a compatible gateway is replaced.
        """

        if not await self.breaker.allow():
            raise ProviderError(
                ErrorCode.CIRCUIT_OPEN,
                "MI300 circuit breaker is open",
                status_code=503,
                retryable=True,
                fallback="fixture_mode",
                details={"circuit_state": self.breaker.state},
            )

        payload = {
            "schema_version": SCHEMA_VERSION,
            "request_id": request_id,
            "image": {
                "media_type": image.media_type,
                "content_base64": base64.b64encode(image.path.read_bytes()).decode("ascii"),
            },
            "prompt": prompt,
            "response_schema": response_schema,
            "model_revision": self.settings.vlm_model_revision,
        }
        if evidence:
            payload["evidence"] = evidence

        last_error: ProviderError | None = None
        for attempt in range(1, self.settings.max_attempts + 1):
            try:
                response = await self.client.post(
                    "/internal/vlm/generate",
                    json=payload,
                    headers={"X-Request-ID": request_id},
                )
                if response.status_code == 200:
                    generation = self._parse_structured_response(
                        response,
                        request_id,
                        response_schema,
                    )
                    await self.breaker.success()
                    return generation
                last_error = self._map_http_error(response, request_id)
                if (
                    response.status_code not in {429, 500, 502, 503, 504}
                    or not last_error.retryable
                ):
                    break
            except httpx.TimeoutException as exc:
                last_error = ProviderError(
                    ErrorCode.VLM_TIMEOUT,
                    "MI300 inference timed out",
                    status_code=504,
                    retryable=True,
                    fallback="fixture_mode",
                    details={"attempt": attempt},
                )
                last_error.__cause__ = exc
            except httpx.TransportError as exc:
                last_error = ProviderError(
                    ErrorCode.VLM_OFFLINE,
                    "MI300 VLM is unreachable",
                    status_code=503,
                    retryable=True,
                    fallback="fixture_mode",
                    details={"attempt": attempt},
                )
                last_error.__cause__ = exc

            if attempt < self.settings.max_attempts:
                await asyncio.sleep(self.settings.retry_backoff_seconds * (2 ** (attempt - 1)))

        await self.breaker.failure()
        raise last_error or ProviderError(
            ErrorCode.VLM_OFFLINE,
            "MI300 VLM request failed",
            status_code=503,
            retryable=True,
            fallback="fixture_mode",
        )

    async def analyze(self, image: PreparedImage, request_id: str) -> Lesson:
        """Backward-compatible one-step Lesson provider.

        Stage 07 uses ``generate`` through the laptop orchestration pipeline;
        this method keeps the Stage 04 provider contract useful for callers
        and existing offline/provider tests.
        """

        generation = await self.generate(
            image,
            request_id,
            prompt=(
                "分析這一頁臺灣台語教材，依 JSON Schema 回傳可供教師審查的 Lesson。"
                "不得輸出 Markdown；看圖活動不可直接洩漏答案；尚無 RAG 依據時 evidence 必須是空陣列。"
            ),
            response_schema=self.lesson_schema,
        )
        try:
            normalized = dict(generation.candidate)
            # Gateway metadata is authoritative. Local RAG binding happens in
            # the laptop pipeline, never in the MI300 service.
            normalized["vlm_model_revision"] = generation.model_revision
            normalized["rag_index_revision"] = None
            normalized["evidence"] = []
            normalized["review_status"] = "pending"
            return Lesson.model_validate(normalized)
        except (TypeError, ValueError) as exc:
            raise ProviderError(
                ErrorCode.VLM_INVALID_OUTPUT,
                "MI300 returned an invalid Lesson candidate",
                status_code=503,
                retryable=False,
                fallback="manual_review",
            ) from exc

    def _parse_structured_response(
        self,
        response: httpx.Response,
        request_id: str,
        response_schema: dict[str, Any],
    ) -> StructuredGeneration:
        try:
            body = response.json()
            if not isinstance(body, dict):
                raise ValueError("response body must be an object")
            if body.get("request_id") != request_id:
                raise ValueError("request_id mismatch")
            if body.get("model_revision") != self.settings.vlm_model_revision:
                raise ValueError("model revision mismatch")
            candidate = body["output"]["parsed_candidate"]
            Draft202012Validator.check_schema(response_schema)
            validator = Draft202012Validator(response_schema)
            errors = sorted(validator.iter_errors(candidate), key=lambda error: list(error.path))
            if errors:
                details = {
                    "validation_errors": [
                        {
                            "path": ".".join(str(part) for part in error.path)[:200],
                            "validator": str(error.validator)[:100],
                        }
                        for error in errors[:10]
                    ]
                }
                raise ProviderError(
                    ErrorCode.VLM_INVALID_OUTPUT,
                    "MI300 returned JSON that does not match the requested schema",
                    status_code=503,
                    retryable=False,
                    fallback="manual_review",
                    details=details,
                )
            output = body["output"]
            if not isinstance(output, dict):
                raise ValueError("output must be an object")
            return StructuredGeneration(
                candidate=candidate,
                model_revision=str(body["model_revision"]),
                raw_output=str(output.get("raw_output") or ""),
                latency_ms=int(body.get("latency_ms", 0)),
                queue_ms=int(body.get("queue_ms", 0)),
                inference_ms=int(body.get("inference_ms", 0)),
            )
        except ProviderError:
            raise
        except (KeyError, TypeError, ValueError, json.JSONDecodeError, SchemaError, ValidationError) as exc:
            raise ProviderError(
                ErrorCode.VLM_INVALID_OUTPUT,
                "MI300 returned an invalid structured candidate",
                status_code=503,
                retryable=False,
                fallback="manual_review",
            ) from exc

    @staticmethod
    def _map_http_error(response: httpx.Response, request_id: str) -> ProviderError:
        default_code = ErrorCode.VLM_TIMEOUT if response.status_code in {429, 504} else ErrorCode.VLM_OFFLINE
        default_status = 504 if default_code == ErrorCode.VLM_TIMEOUT else 503
        try:
            body = response.json()
            if not isinstance(body, dict):
                raise ValueError("error body must be an object")
            code = ErrorCode(body.get("code", default_code))
            message = str(body.get("message") or "MI300 request failed")
            retryable = bool(body.get("retryable", response.status_code >= 500 or response.status_code == 429))
        except (ValueError, TypeError):
            code = default_code
            message = "MI300 request failed"
            retryable = response.status_code >= 500 or response.status_code == 429
        if code not in {ErrorCode.VLM_TIMEOUT, ErrorCode.VLM_OFFLINE, ErrorCode.VLM_INVALID_OUTPUT}:
            code = default_code
        return ProviderError(
            code,
            message[:500],
            status_code=default_status,
            retryable=retryable,
            fallback="fixture_mode" if code != ErrorCode.VLM_INVALID_OUTPUT else "manual_review",
            details={"upstream_status": response.status_code, "request_id": request_id},
        )

    async def health(self, request_id: str) -> ServiceHealth:
        if self.breaker.state == "open":
            return _dependency_health(
                "vlm-mi300",
                "offline",
                request_id,
                code=ErrorCode.CIRCUIT_OPEN,
                message="MI300 circuit breaker is open",
                fallback="fixture_mode",
                device="MI300 96GB",
                model_revision=self.settings.vlm_model_revision,
            )
        try:
            response = await self.client.get(
                "/internal/health",
                headers={"X-Request-ID": request_id},
                timeout=self.settings.health_timeout_seconds,
            )
            response.raise_for_status()
            body = response.json()
            return ServiceHealth.model_validate(body)
        except (httpx.HTTPError, ValueError, TypeError):
            return _dependency_health(
                "vlm-mi300",
                "offline",
                request_id,
                code=ErrorCode.VLM_OFFLINE,
                message="MI300 health probe failed",
                fallback="fixture_mode",
                device="MI300 96GB",
                model_revision=self.settings.vlm_model_revision,
            )

    async def close(self) -> None:
        await self.client.aclose()


class FixtureProvider:
    mode = "fixture"

    def __init__(self, fixture_path: Path) -> None:
        self.fixture_path = fixture_path
        self._fixture = Lesson.model_validate(json.loads(fixture_path.read_text(encoding="utf-8")))

    async def analyze(self, image: PreparedImage, request_id: str) -> Lesson:
        payload = copy.deepcopy(self._fixture.model_dump(mode="json"))
        payload["vlm_model_revision"] = "fixture:v0.1"
        payload["rag_index_revision"] = None
        return Lesson.model_validate(payload)

    async def health(self, request_id: str) -> ServiceHealth:
        return _dependency_health(
            "vlm-mi300",
            "degraded",
            request_id,
            code=ErrorCode.VLM_OFFLINE,
            message="Fixture provider is active; MI300 is not being called",
            fallback="fixture_mode",
            device="Ryzen AI 9 laptop fixture",
            model_revision="fixture:v0.1",
        )

    async def close(self) -> None:
        return None


def _dependency_health(
    service: str,
    status: str,
    request_id: str,
    *,
    code: ErrorCode,
    message: str,
    fallback: str,
    device: str | None,
    model_revision: str | None,
) -> ServiceHealth:
    from datetime import UTC, datetime

    return ServiceHealth.model_validate(
        {
            "schema_version": SCHEMA_VERSION,
            "service": service,
            "status": status,
            "device": device,
            "model_revision": model_revision,
            "queue_depth": 0,
            "last_error": {
                "schema_version": SCHEMA_VERSION,
                "code": code,
                "message": message,
                "retryable": True,
                "fallback": fallback,
                "request_id": request_id,
            },
            "checked_at": datetime.now(UTC),
        }
    )


def load_lesson_schema(repository_root: Path) -> dict[str, Any]:
    path = repository_root / "packages" / "contracts" / "schemas" / "v0.1" / "lesson.schema.json"
    return json.loads(path.read_text(encoding="utf-8"))
