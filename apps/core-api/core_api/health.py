from __future__ import annotations

import asyncio
from datetime import UTC, datetime

import httpx

from .config import Settings
from .db import Database
from .models import ErrorCode, HealthResponse, SCHEMA_VERSION, ServiceHealth
from .providers import LessonProvider


def _health(
    service: str,
    status: str,
    request_id: str,
    *,
    device: str | None,
    model_revision: str | None = None,
    error_code: ErrorCode | None = None,
    message: str | None = None,
    fallback: str | None = None,
) -> ServiceHealth:
    last_error = None
    if error_code is not None and message is not None:
        last_error = {
            "schema_version": SCHEMA_VERSION,
            "code": error_code,
            "message": message,
            "retryable": status != "ready",
            "fallback": fallback,
            "request_id": request_id,
        }
    return ServiceHealth.model_validate(
        {
            "schema_version": SCHEMA_VERSION,
            "service": service,
            "status": status,
            "device": device,
            "model_revision": model_revision,
            "queue_depth": 0,
            "last_error": last_error,
            "checked_at": datetime.now(UTC),
        }
    )


class HealthAggregator:
    def __init__(self, settings: Settings, database: Database, provider: LessonProvider) -> None:
        self.settings = settings
        self.database = database
        self.provider = provider
        self.speech_client = httpx.AsyncClient(
            base_url=settings.speech_base_url or "http://127.0.0.1",
            timeout=settings.health_timeout_seconds,
        )

    async def snapshot(self, request_id: str) -> HealthResponse:
        database_ok, vlm, speech = await asyncio.gather(
            asyncio.to_thread(self.database.healthy),
            self.provider.health(request_id),
            self._speech_health(request_id),
        )
        core = _health(
            "core-api",
            "ready" if database_ok else "offline",
            request_id,
            device="Ryzen AI 9 laptop / SQLite",
            error_code=None if database_ok else ErrorCode.INTERNAL_ERROR,
            message=None if database_ok else "SQLite readiness check failed",
            fallback=None,
        )
        rag = _health(
            "rag",
            "degraded",
            request_id,
            device="Ryzen AI 9 laptop CPU",
            error_code=ErrorCode.RAG_NO_RESULT,
            message="Local RAG is a Stage 05 placeholder",
            fallback="manual_review",
        )
        services = [core, rag, vlm, *speech]
        overall = "offline" if core.status == "offline" else (
            "degraded" if any(item.status != "ready" for item in services) else "ready"
        )
        return HealthResponse(
            schema_version=SCHEMA_VERSION,
            request_id=request_id,
            status=overall,
            services=services,
        )

    async def _speech_health(self, request_id: str) -> list[ServiceHealth]:
        if not self.settings.speech_base_url:
            return self._speech_offline(request_id, "Speech Gateway URL is not configured")
        try:
            response = await self.speech_client.get(
                "/local/health",
                headers={"X-Request-ID": request_id},
            )
            response.raise_for_status()
            body = response.json()
            services = [ServiceHealth.model_validate(item) for item in body.get("services", [])]
            if {item.service for item in services} != {"asr", "tts"}:
                raise ValueError("speech health must contain ASR and TTS")
            return services
        except (httpx.HTTPError, ValueError, TypeError):
            return self._speech_offline(request_id, "Speech Gateway health probe failed")

    @staticmethod
    def _speech_offline(request_id: str, message: str) -> list[ServiceHealth]:
        return [
            _health(
                "asr",
                "offline",
                request_id,
                device="Ryzen AI 9 laptop",
                error_code=ErrorCode.ASR_UNAVAILABLE,
                message=message,
                fallback="keyboard_input",
            ),
            _health(
                "tts",
                "offline",
                request_id,
                device="Ryzen AI 9 laptop",
                error_code=ErrorCode.TTS_UNAVAILABLE,
                message=message,
                fallback="app_narration",
            ),
        ]

    async def close(self) -> None:
        await self.speech_client.aclose()
