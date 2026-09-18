"""Stateless MI300 VLM gateway.

The gateway deliberately keeps the model process separate from the product
backend.  It accepts one request, validates and normalizes the image in
memory, forwards a single OpenAI-compatible request to the local vLLM
process, validates the returned candidate against the caller supplied JSON
Schema, and discards request bytes when the response is complete.

No request payload is written to disk or included in logs.  The only
long-lived state is bounded operational counters and the last sanitized error
used by the health endpoint.
"""

from __future__ import annotations

import asyncio
import base64
import binascii
import ipaddress
import json
import logging
import math
import os
import time
import uuid
import warnings
from asyncio import Future, Queue, QueueFull, Task
from dataclasses import dataclass, field
from io import BytesIO
from typing import Any, Literal

import httpx
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from jsonschema import Draft202012Validator, SchemaError, ValidationError
from PIL import Image, ImageFile, UnidentifiedImageError
from pydantic import BaseModel, ConfigDict, Field


LOGGER = logging.getLogger("vlm-mi300")
_STRUCTURED_LOG_FIELDS = ("request_id", "status", "duration_ms", "model_revision")


class _StructuredDefaults(logging.Filter):
    """Keep third-party records compatible with the structured formatter."""

    def filter(self, record: logging.LogRecord) -> bool:
        for field_name in _STRUCTURED_LOG_FIELDS:
            if not hasattr(record, field_name):
                setattr(record, field_name, "-")
        return True


_structured_filter = _StructuredDefaults()
logging.basicConfig(
    level=os.getenv("VLM_LOG_LEVEL", "INFO"),
    format="%(asctime)s %(levelname)s request_id=%(request_id)s status=%(status)s duration_ms=%(duration_ms)s model_revision=%(model_revision)s %(message)s",
)
for _handler in logging.getLogger().handlers:
    _handler.addFilter(_structured_filter)

# Pillow otherwise accepts truncated files in some configurations.  We never
# enable this globally for the host; the request validator sets it back after
# each image operation.
ImageFile.LOAD_TRUNCATED_IMAGES = False

SCHEMA_VERSION = "0.1.0"
ALLOWED_MEDIA_TYPES = ("image/jpeg", "image/png", "image/webp")
PIL_FORMAT_FOR_MEDIA_TYPE = {
    "image/jpeg": {"JPEG", "MPO"},
    "image/png": {"PNG"},
    "image/webp": {"WEBP"},
}


def _env_int(name: str, default: int, *, minimum: int = 0, maximum: int | None = None) -> int:
    value = os.getenv(name)
    if value is None or value == "":
        return default
    try:
        parsed = int(value)
    except ValueError as exc:
        raise RuntimeError(f"{name} must be an integer") from exc
    if parsed < minimum:
        raise RuntimeError(f"{name} must be >= {minimum}")
    if maximum is not None and parsed > maximum:
        raise RuntimeError(f"{name} must be <= {maximum}")
    return parsed


def _env_float(name: str, default: float, *, minimum: float = 0.0) -> float:
    value = os.getenv(name)
    if value is None or value == "":
        return default
    try:
        parsed = float(value)
    except ValueError as exc:
        raise RuntimeError(f"{name} must be a number") from exc
    if parsed < minimum:
        raise RuntimeError(f"{name} must be >= {minimum}")
    return parsed


def _parse_networks(value: str) -> tuple[ipaddress._BaseNetwork, ...]:
    networks: list[ipaddress._BaseNetwork] = []
    for raw in value.replace(";", ",").split(","):
        item = raw.strip()
        if not item:
            continue
        try:
            networks.append(ipaddress.ip_network(item, strict=False))
        except ValueError as exc:
            raise RuntimeError(f"VLM_ALLOWED_CIDRS contains an invalid network: {item!r}") from exc
    if not networks:
        raise RuntimeError("VLM_ALLOWED_CIDRS must contain at least one CIDR")
    return tuple(networks)


@dataclass(frozen=True)
class Settings:
    """Runtime limits and trust-boundary settings.

    Defaults are intentionally conservative.  The default allowlist covers
    loopback and RFC1918/RFC4193 trusted LAN ranges, never the public
    internet.  Operators should narrow it to the laptop's exact CIDR.
    """

    upstream_url: str = os.getenv("VLM_UPSTREAM_URL", "http://127.0.0.1:8000/v1")
    model: str = os.getenv("VLM_MODEL", "Qwen/Qwen3-VL-30B-A3B-Instruct-FP8")
    model_revision: str = os.getenv(
        "VLM_MODEL_REVISION", "d9748a51ae66354c4dad665aab2c71f26cf2c8cd"
    )
    device: str = os.getenv("VLM_DEVICE", "MI300X")
    bind_host: str = os.getenv("VLM_BIND_HOST", "0.0.0.0")
    port: int = _env_int("VLM_PORT", 8100, minimum=1)
    max_request_bytes: int = _env_int("VLM_MAX_REQUEST_BYTES", 12 * 1024 * 1024, minimum=1)
    max_image_bytes: int = _env_int("VLM_MAX_IMAGE_BYTES", 8 * 1024 * 1024, minimum=1)
    max_image_pixels: int = _env_int("VLM_MAX_IMAGE_PIXELS", 16_777_216, minimum=1)
    max_image_dimension: int = _env_int("VLM_MAX_IMAGE_DIMENSION", 4096, minimum=1)
    max_prompt_chars: int = _env_int("VLM_MAX_PROMPT_CHARS", 50_000, minimum=1)
    max_schema_bytes: int = _env_int("VLM_MAX_SCHEMA_BYTES", 128 * 1024, minimum=1)
    max_evidence_items: int = _env_int("VLM_MAX_EVIDENCE_ITEMS", 20, minimum=0)
    max_evidence_bytes: int = _env_int("VLM_MAX_EVIDENCE_BYTES", 128 * 1024, minimum=1)
    max_context_tokens: int = _env_int("VLM_MAX_CONTEXT_TOKENS", 65_536, minimum=1)
    max_output_tokens: int = _env_int("VLM_MAX_OUTPUT_TOKENS", 8_192, minimum=1)
    image_token_budget: int = _env_int("VLM_IMAGE_TOKEN_BUDGET", 4_096, minimum=0)
    queue_max: int = _env_int("VLM_QUEUE_MAX", 8, minimum=1)
    concurrency: int = _env_int("VLM_CONCURRENCY", 2, minimum=1, maximum=2)
    request_timeout_seconds: float = _env_float("VLM_REQUEST_TIMEOUT_SECONDS", 120.0, minimum=0.1)
    upstream_connect_timeout_seconds: float = _env_float(
        "VLM_UPSTREAM_CONNECT_TIMEOUT_SECONDS", 5.0, minimum=0.1
    )
    health_timeout_seconds: float = _env_float("VLM_HEALTH_TIMEOUT_SECONDS", 2.0, minimum=0.1)
    allowed_cidrs_text: str = os.getenv(
        "VLM_ALLOWED_CIDRS",
        "127.0.0.1/32,::1/128,10.0.0.0/8,172.16.0.0/12,192.168.0.0/16,fc00::/7",
    )

    @property
    def allowed_networks(self) -> tuple[ipaddress._BaseNetwork, ...]:
        return _parse_networks(self.allowed_cidrs_text)

    @property
    def upstream_base(self) -> str:
        return self.upstream_url.rstrip("/")

    @property
    def upstream_chat_url(self) -> str:
        if self.upstream_base.endswith("/chat/completions"):
            return self.upstream_base
        return self.upstream_base + "/chat/completions"

    @property
    def upstream_models_url(self) -> str:
        if self.upstream_base.endswith("/chat/completions"):
            return self.upstream_base[: -len("/chat/completions")] + "/models"
        return self.upstream_base + "/models"

    def allows(self, host: str | None) -> bool:
        if not host:
            return False
        try:
            address = ipaddress.ip_address(host)
        except ValueError:
            return False
        return any(address in network for network in self.allowed_networks)


class ImageInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    media_type: Literal["image/jpeg", "image/png", "image/webp"]
    content_base64: str = Field(min_length=1)


class GenerateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[SCHEMA_VERSION]
    request_id: uuid.UUID
    image: ImageInput
    prompt: str = Field(min_length=1, max_length=50_000)
    response_schema: dict[str, Any]
    evidence: list[dict[str, Any]] | None = Field(default=None, max_length=20)
    model_revision: str = Field(min_length=1, max_length=500)


@dataclass
class NormalizedImage:
    content: bytes
    media_type: Literal["image/jpeg", "image/png", "image/webp"]
    width: int
    height: int


class ServiceError(Exception):
    """Sanitized error that can be returned without exposing request bytes."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        status_code: int,
        retryable: bool,
        fallback: str | None,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code
        self.retryable = retryable
        self.fallback = fallback
        self.details = details or {}

    def payload(self, request_id: str) -> dict[str, Any]:
        result: dict[str, Any] = {
            "schema_version": SCHEMA_VERSION,
            "code": self.code,
            "message": self.message,
            "retryable": self.retryable,
            "fallback": self.fallback,
            "request_id": request_id,
        }
        if self.details:
            result["details"] = self.details
        return result


def _request_id_from_header(request: Request) -> str:
    value = request.headers.get("x-request-id")
    try:
        return str(uuid.UUID(value)) if value else str(uuid.uuid4())
    except (ValueError, AttributeError):
        return str(uuid.uuid4())


def _error_response(error: ServiceError, request_id: str) -> JSONResponse:
    return JSONResponse(
        status_code=error.status_code,
        content=error.payload(request_id),
        headers={"X-Request-ID": request_id},
    )


def _log(request_id: str, status: str, duration_ms: int | str, settings: Settings, message: str) -> None:
    LOGGER.info(
        message,
        extra={
            "request_id": request_id,
            "status": status,
            "duration_ms": duration_ms,
            "model_revision": settings.model_revision,
        },
    )


def _sanitize_schema_error(error: ValidationError | SchemaError) -> dict[str, str]:
    # jsonschema paths may contain user supplied property names, but never
    # include the actual prompt/image.  Limit output to keep the error bounded.
    path = ".".join(str(part) for part in getattr(error, "path", []))
    return {"path": path[:200], "validator": str(getattr(error, "validator", "schema"))[:100]}


def validate_response_schema(schema: Any, settings: Settings) -> Draft202012Validator:
    if not isinstance(schema, dict):
        raise ServiceError(
            "VALIDATION_ERROR",
            "response_schema must be a JSON object",
            status_code=400,
            retryable=False,
            fallback=None,
        )
    try:
        serialized = json.dumps(schema, ensure_ascii=False, separators=(",", ":"))
    except (TypeError, ValueError) as exc:
        raise ServiceError(
            "VALIDATION_ERROR",
            "response_schema is not JSON serializable",
            status_code=400,
            retryable=False,
            fallback=None,
        ) from exc
    if len(serialized.encode("utf-8")) > settings.max_schema_bytes:
        raise ServiceError(
            "VALIDATION_ERROR",
            "response_schema exceeds the size limit",
            status_code=400,
            retryable=False,
            fallback=None,
            details={"max_schema_bytes": settings.max_schema_bytes},
        )
    try:
        Draft202012Validator.check_schema(schema)
        return Draft202012Validator(schema)
    except SchemaError as exc:
        raise ServiceError(
            "VALIDATION_ERROR",
            "response_schema is not a valid Draft 2020-12 schema",
            status_code=400,
            retryable=False,
            fallback=None,
            details=_sanitize_schema_error(exc),
        ) from exc


def _normalize_image(image: ImageInput, settings: Settings) -> NormalizedImage:
    try:
        raw = base64.b64decode(image.content_base64, validate=True)
    except (ValueError, binascii.Error) as exc:
        raise ServiceError(
            "VALIDATION_ERROR",
            "image.content_base64 is not valid base64",
            status_code=400,
            retryable=False,
            fallback="correct input",
        ) from exc
    if len(raw) > settings.max_image_bytes:
        raise ServiceError(
            "VALIDATION_ERROR",
            "image exceeds the byte limit",
            status_code=400,
            retryable=False,
            fallback="correct input",
            details={"max_image_bytes": settings.max_image_bytes},
        )
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(BytesIO(raw)) as image_file:
                # verify() must run before load() so truncated/corrupt
                # containers are rejected by Pillow's parser.
                width, height = image_file.size
                image_format = (image_file.format or "").upper()
                image_file.verify()
        expected_formats = PIL_FORMAT_FOR_MEDIA_TYPE[image.media_type]
        if image_format not in expected_formats:
            raise ServiceError(
                "VALIDATION_ERROR",
                "image MIME type does not match its encoded format",
                status_code=400,
                retryable=False,
                fallback="correct input",
            )
        if width < 1 or height < 1 or width > settings.max_image_dimension or height > settings.max_image_dimension:
            raise ServiceError(
                "VALIDATION_ERROR",
                "image dimensions exceed the limit",
                status_code=400,
                retryable=False,
                fallback="correct input",
                details={"max_image_dimension": settings.max_image_dimension},
            )
        pixels = width * height
        if pixels > settings.max_image_pixels:
            raise ServiceError(
                "VALIDATION_ERROR",
                "image pixel count exceeds the limit",
                status_code=400,
                retryable=False,
                fallback="correct input",
                details={"max_image_pixels": settings.max_image_pixels},
            )

        # Re-encode in memory to remove EXIF/XMP and other container metadata.
        # PNG is lossless and accepted by Qwen3-VL; it also gives the upstream a
        # deterministic MIME independent of the original JPEG/WebP container.
        with Image.open(BytesIO(raw)) as image_file:
            image_file.load()
            if image_file.mode not in ("RGB", "RGBA"):
                image_file = image_file.convert("RGB")
            output = BytesIO()
            image_file.save(output, format="PNG", optimize=True)
            normalized = output.getvalue()
        if len(normalized) > settings.max_image_bytes:
            raise ServiceError(
                "VALIDATION_ERROR",
                "normalized image exceeds the byte limit",
                status_code=400,
                retryable=False,
                fallback="correct input",
                details={"max_image_bytes": settings.max_image_bytes},
            )
        return NormalizedImage(normalized, "image/png", width, height)
    except ServiceError:
        raise
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError, Image.DecompressionBombWarning) as exc:
        raise ServiceError(
            "VALIDATION_ERROR",
            "image is not a readable safe image",
            status_code=400,
            retryable=False,
            fallback="correct input",
        ) from exc


def validate_request_limits(request: GenerateRequest, settings: Settings) -> tuple[NormalizedImage, Draft202012Validator, int]:
    if request.schema_version != SCHEMA_VERSION:
        raise ServiceError(
            "VALIDATION_ERROR",
            "unsupported schema_version",
            status_code=400,
            retryable=False,
            fallback="correct input",
        )
    if request.model_revision != settings.model_revision:
        raise ServiceError(
            "VALIDATION_ERROR",
            "model_revision does not match the running service",
            status_code=400,
            retryable=False,
            fallback="manual_review",
        )
    if len(request.prompt) > settings.max_prompt_chars:
        raise ServiceError(
            "VALIDATION_ERROR",
            "prompt exceeds the size limit",
            status_code=400,
            retryable=False,
            fallback="correct input",
            details={"max_prompt_chars": settings.max_prompt_chars},
        )
    image = _normalize_image(request.image, settings)
    validator = validate_response_schema(request.response_schema, settings)
    evidence = request.evidence or []
    if len(evidence) > settings.max_evidence_items:
        raise ServiceError(
            "VALIDATION_ERROR",
            "evidence item count exceeds the limit",
            status_code=400,
            retryable=False,
            fallback="correct input",
            details={"max_evidence_items": settings.max_evidence_items},
        )
    try:
        evidence_bytes = len(json.dumps(evidence, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))
    except (TypeError, ValueError) as exc:
        raise ServiceError(
            "VALIDATION_ERROR",
            "evidence must be JSON serializable",
            status_code=400,
            retryable=False,
            fallback="correct input",
        ) from exc
    if evidence_bytes > settings.max_evidence_bytes:
        raise ServiceError(
            "VALIDATION_ERROR",
            "evidence exceeds the size limit",
            status_code=400,
            retryable=False,
            fallback="correct input",
            details={"max_evidence_bytes": settings.max_evidence_bytes},
        )
    prompt_chars = len(request.prompt)
    schema_chars = len(json.dumps(request.response_schema, ensure_ascii=False, separators=(",", ":")))
    # A conservative 4-character/token estimate prevents the upstream from
    # receiving a request that cannot fit once image tokens and output budget
    # are accounted for.  The exact tokenizer remains vLLM's authority.
    estimated_prompt_tokens = math.ceil((prompt_chars + schema_chars + evidence_bytes) / 4) + settings.image_token_budget
    if estimated_prompt_tokens + settings.max_output_tokens > settings.max_context_tokens:
        raise ServiceError(
            "VALIDATION_ERROR",
            "request exceeds the configured context budget",
            status_code=400,
            retryable=False,
            fallback="correct input",
            details={
                "estimated_prompt_tokens": estimated_prompt_tokens,
                "max_output_tokens": settings.max_output_tokens,
                "max_context_tokens": settings.max_context_tokens,
            },
        )
    return image, validator, estimated_prompt_tokens


@dataclass
class InferenceJob:
    request: GenerateRequest
    image: NormalizedImage
    enqueued_at: float
    future: Future[dict[str, Any]]
    cancelled: bool = False
    started_at: float | None = None
    operation_task: Task[Any] | None = None


class InferenceService:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.queue: Queue[InferenceJob] = Queue(maxsize=settings.queue_max)
        self.client: httpx.AsyncClient | None = None
        self.workers: list[Task[Any]] = []
        self.active = 0
        self.started_at = time.time()
        self.last_error: dict[str, Any] | None = None
        self.total_requests = 0
        self.successful_requests = 0
        self.failed_requests = 0
        self.cancelled_requests = 0
        self.rejected_requests = 0
        self._lock = asyncio.Lock()

    async def start(self) -> None:
        limits = httpx.Limits(max_connections=self.settings.concurrency + 2, max_keepalive_connections=self.settings.concurrency)
        timeout = httpx.Timeout(
            self.settings.request_timeout_seconds,
            connect=self.settings.upstream_connect_timeout_seconds,
        )
        self.client = httpx.AsyncClient(timeout=timeout, limits=limits)
        self.workers = [asyncio.create_task(self._worker(index), name=f"vlm-worker-{index}") for index in range(self.settings.concurrency)]

    async def stop(self) -> None:
        for worker in self.workers:
            worker.cancel()
        if self.workers:
            await asyncio.gather(*self.workers, return_exceptions=True)
        self.workers.clear()
        if self.client is not None:
            await self.client.aclose()
            self.client = None

    @property
    def queue_depth(self) -> int:
        return self.queue.qsize()

    async def _worker(self, index: int) -> None:
        while True:
            job = await self.queue.get()
            try:
                if job.cancelled:
                    continue
                job.started_at = time.perf_counter()
                self.active += 1
                job.operation_task = asyncio.create_task(self._run_job(job), name=f"vlm-request-{index}")
                try:
                    result = await job.operation_task
                    if not job.future.done():
                        job.future.set_result(result)
                except asyncio.CancelledError:
                    if not job.future.done():
                        job.future.set_exception(
                            ServiceError(
                                "VLM_TIMEOUT",
                                "inference was cancelled",
                                status_code=504,
                                retryable=True,
                                fallback="retry_later",
                            )
                        )
                except ServiceError as exc:
                    self.last_error = exc.payload(str(job.request.request_id))
                    if not job.future.done():
                        job.future.set_exception(exc)
                except Exception as exc:  # pragma: no cover - defensive guard
                    error = ServiceError(
                        "INTERNAL_ERROR",
                        "unexpected inference service failure",
                        status_code=500,
                        retryable=False,
                        fallback=None,
                    )
                    self.last_error = error.payload(str(job.request.request_id))
                    LOGGER.exception("worker failure", extra={"request_id": str(job.request.request_id), "status": "error", "duration_ms": "-", "model_revision": self.settings.model_revision})
                    if not job.future.done():
                        job.future.set_exception(error)
                finally:
                    self.active -= 1
            finally:
                self.queue.task_done()

    async def _run_job(self, job: InferenceJob) -> dict[str, Any]:
        queue_ms = int(max(0.0, (job.started_at or time.perf_counter()) - job.enqueued_at) * 1000)
        started = time.perf_counter()
        response = await self._call_upstream(job)
        upstream_ms = int(max(0.0, time.perf_counter() - started) * 1000)
        result = self._parse_upstream_response(job, response, queue_ms, upstream_ms)
        self.successful_requests += 1
        return result

    async def _call_upstream(self, job: InferenceJob) -> dict[str, Any]:
        if self.client is None:
            raise ServiceError(
                "VLM_OFFLINE",
                "vLLM upstream is not initialized",
                status_code=503,
                retryable=True,
                fallback="cached_lesson",
            )
        request = job.request
        encoded = base64.b64encode(job.image.content).decode("ascii")
        evidence = request.evidence or []
        prompt = request.prompt
        if evidence:
            prompt = prompt + "\n\nEvidence selected by the laptop (do not invent beyond it):\n" + json.dumps(evidence, ensure_ascii=False, separators=(",", ":"))
        payload = {
            "model": self.settings.model,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{encoded}"}},
                    ],
                }
            ],
            "response_format": {
                "type": "json_schema",
                "json_schema": {"name": "vlm_result", "schema": request.response_schema},
            },
            "temperature": 0,
            "top_p": 1,
            "max_tokens": self.settings.max_output_tokens,
            "stream": False,
        }
        try:
            response = await self.client.post(
                self.settings.upstream_chat_url,
                json=payload,
                headers={"X-Request-ID": str(request.request_id)},
            )
        except asyncio.CancelledError:
            raise
        except httpx.TimeoutException as exc:
            self.failed_requests += 1
            raise ServiceError(
                "VLM_TIMEOUT",
                "vLLM inference timed out",
                status_code=504,
                retryable=True,
                fallback="cached_lesson",
            ) from exc
        except httpx.HTTPError as exc:
            self.failed_requests += 1
            raise ServiceError(
                "VLM_OFFLINE",
                "vLLM upstream is unavailable",
                status_code=503,
                retryable=True,
                fallback="cached_lesson",
            ) from exc
        if response.status_code == 429:
            self.failed_requests += 1
            raise ServiceError(
                "VLM_TIMEOUT",
                "vLLM upstream queue is full",
                status_code=429,
                retryable=True,
                fallback="retry_later",
            )
        if response.status_code >= 500:
            self.failed_requests += 1
            raise ServiceError(
                "VLM_OFFLINE",
                "vLLM upstream returned a server error",
                status_code=503,
                retryable=True,
                fallback="cached_lesson",
                details={"upstream_status": response.status_code},
            )
        if response.status_code >= 400:
            self.failed_requests += 1
            raise ServiceError(
                "VLM_INVALID_OUTPUT",
                "vLLM upstream rejected the inference request",
                status_code=503,
                retryable=False,
                fallback="manual_review",
                details={"upstream_status": response.status_code},
            )
        try:
            return response.json()
        except (ValueError, json.JSONDecodeError) as exc:
            self.failed_requests += 1
            raise ServiceError(
                "VLM_INVALID_OUTPUT",
                "vLLM upstream returned non-JSON output",
                status_code=503,
                retryable=False,
                fallback="manual_review",
            ) from exc

    def _parse_upstream_response(
        self,
        job: InferenceJob,
        body: dict[str, Any],
        queue_ms: int,
        upstream_ms: int,
    ) -> dict[str, Any]:
        try:
            choice = body["choices"][0]
            message = choice["message"]
            raw_output = message["content"]
            finish_reason = choice.get("finish_reason")
        except (KeyError, IndexError, TypeError) as exc:
            self.failed_requests += 1
            raise ServiceError(
                "VLM_INVALID_OUTPUT",
                "vLLM response did not contain an assistant message",
                status_code=503,
                retryable=False,
                fallback="manual_review",
            ) from exc
        if not isinstance(raw_output, str):
            raw_output = json.dumps(raw_output, ensure_ascii=False, separators=(",", ":"))
        try:
            candidate = json.loads(raw_output)
        except (TypeError, ValueError) as exc:
            self.failed_requests += 1
            raise ServiceError(
                "VLM_INVALID_OUTPUT",
                "assistant output is not valid JSON",
                status_code=503,
                retryable=False,
                fallback="manual_review",
                details={"finish_reason": finish_reason},
            ) from exc
        validator = Draft202012Validator(job.request.response_schema)
        errors = sorted(validator.iter_errors(candidate), key=lambda item: list(item.path))
        if errors:
            self.failed_requests += 1
            raise ServiceError(
                "VLM_INVALID_OUTPUT",
                "assistant JSON does not match response_schema",
                status_code=503,
                retryable=False,
                fallback="manual_review",
                details={"validation_errors": [_sanitize_schema_error(error) for error in errors[:10]]},
            )
        usage = body.get("usage") if isinstance(body.get("usage"), dict) else {}
        latency_ms = queue_ms + upstream_ms
        return {
            "schema_version": SCHEMA_VERSION,
            "request_id": str(job.request.request_id),
            "output": {
                "raw_output": raw_output,
                "parsed_candidate": candidate,
                "usage": {
                    "prompt_tokens": usage.get("prompt_tokens"),
                    "completion_tokens": usage.get("completion_tokens"),
                    "total_tokens": usage.get("total_tokens"),
                },
                "finish_reason": finish_reason,
            },
            "model_revision": self.settings.model_revision,
            "latency_ms": latency_ms,
            "queue_ms": queue_ms,
            "inference_ms": upstream_ms,
        }

    async def submit(self, request: GenerateRequest, image: NormalizedImage) -> dict[str, Any]:
        loop = asyncio.get_running_loop()
        future: Future[dict[str, Any]] = loop.create_future()
        job = InferenceJob(request=request, image=image, enqueued_at=time.perf_counter(), future=future)
        self.total_requests += 1
        try:
            self.queue.put_nowait(job)
        except QueueFull as exc:
            self.rejected_requests += 1
            raise ServiceError(
                "VLM_TIMEOUT",
                "inference queue is full",
                status_code=429,
                retryable=True,
                fallback="retry_later",
                details={"queue_max": self.settings.queue_max},
            ) from exc
        try:
            return await asyncio.wait_for(asyncio.shield(future), timeout=self.settings.request_timeout_seconds)
        except asyncio.TimeoutError as exc:
            job.cancelled = True
            if job.operation_task is not None and not job.operation_task.done():
                job.operation_task.cancel()
            if not future.done():
                future.cancel()
            self.cancelled_requests += 1
            raise ServiceError(
                "VLM_TIMEOUT",
                "inference exceeded the request timeout",
                status_code=504,
                retryable=True,
                fallback="cached_lesson",
            ) from exc
        except asyncio.CancelledError:
            job.cancelled = True
            if job.operation_task is not None and not job.operation_task.done():
                job.operation_task.cancel()
            if not future.done():
                future.cancel()
            self.cancelled_requests += 1
            raise

    async def probe_upstream(self) -> bool:
        if self.client is None:
            return False
        try:
            response = await self.client.get(self.settings.upstream_models_url, timeout=self.settings.health_timeout_seconds)
            if response.status_code != 200:
                error = ServiceError(
                    "VLM_OFFLINE",
                    "vLLM health probe returned an error",
                    status_code=503,
                    retryable=True,
                    fallback="cached_lesson",
                    details={"upstream_status": response.status_code},
                )
                self.last_error = error.payload(str(uuid.uuid4()))
                return False
            body = response.json()
            model_ids = [item.get("id") for item in body.get("data", []) if isinstance(item, dict)]
            if self.settings.model not in model_ids:
                error = ServiceError(
                    "VLM_OFFLINE",
                    "configured model is not available upstream",
                    status_code=503,
                    retryable=True,
                    fallback="cached_lesson",
                )
                self.last_error = error.payload(str(uuid.uuid4()))
                return False
            self.last_error = None
            return True
        except (httpx.HTTPError, ValueError, TypeError):
            error = ServiceError(
                "VLM_OFFLINE",
                "vLLM health probe failed",
                status_code=503,
                retryable=True,
                fallback="cached_lesson",
            )
            self.last_error = error.payload(str(uuid.uuid4()))
            return False

    async def health(self, request_id: str) -> dict[str, Any]:
        upstream_ready = await self.probe_upstream()
        if upstream_ready:
            status = "ready"
        elif self.active or self.queue_depth:
            status = "degraded"
        else:
            status = "offline"
        return {
            "schema_version": SCHEMA_VERSION,
            "service": "vlm-mi300",
            "status": status,
            "device": self.settings.device,
            "model_revision": self.settings.model_revision,
            "queue_depth": self.queue_depth,
            "last_error": self.last_error,
            "checked_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }


settings = Settings()
service = InferenceService(settings)
app = FastAPI(
    title="Hear Our Language MI300 Internal VLM API",
    version=SCHEMA_VERSION,
    docs_url=None,
    redoc_url=None,
)


@app.on_event("startup")
async def startup() -> None:
    await service.start()
    _log("-", "starting", "-", settings, "stateless MI300 VLM gateway started")


@app.on_event("shutdown")
async def shutdown() -> None:
    await service.stop()
    _log("-", "stopped", "-", settings, "stateless MI300 VLM gateway stopped")


@app.middleware("http")
async def request_size_guard(request: Request, call_next):
    if request.method == "POST" and request.url.path == "/internal/vlm/generate":
        raw_length = request.headers.get("content-length")
        if raw_length:
            try:
                length = int(raw_length)
            except ValueError:
                length = settings.max_request_bytes + 1
            if length > settings.max_request_bytes:
                error = ServiceError(
                    "VALIDATION_ERROR",
                    "request body exceeds the size limit",
                    status_code=400,
                    retryable=False,
                    fallback="correct input",
                    details={"max_request_bytes": settings.max_request_bytes},
                )
                return _error_response(error, _request_id_from_header(request))
    return await call_next(request)


@app.exception_handler(ServiceError)
async def service_error_handler(request: Request, error: ServiceError):
    request_id = _request_id_from_header(request)
    _log(request_id, "error", "-", settings, error.code)
    return _error_response(error, request_id)


@app.exception_handler(RequestValidationError)
async def validation_error_handler(request: Request, error: RequestValidationError):
    details = {"fields": [".".join(str(part) for part in item.get("loc", ()))[:200] for item in error.errors()[:20]]}
    wrapped = ServiceError(
        "VALIDATION_ERROR",
        "request validation failed",
        status_code=400,
        retryable=False,
        fallback="correct input",
        details=details,
    )
    request_id = _request_id_from_header(request)
    _log(request_id, "error", "-", settings, wrapped.code)
    return _error_response(wrapped, request_id)


@app.get("/internal/health")
async def internal_health(request: Request):
    request_id = _request_id_from_header(request)
    if not settings.allows(request.client.host if request.client else None):
        error = ServiceError(
            "VALIDATION_ERROR",
            "caller is outside the trusted network",
            status_code=403,
            retryable=False,
            fallback=None,
        )
        return _error_response(error, request_id)
    payload = await service.health(request_id)
    return JSONResponse(content=payload, headers={"X-Request-ID": request_id})


@app.post("/internal/vlm/generate")
async def internal_generate(request: Request, body: GenerateRequest):
    request_id = str(body.request_id)
    if not settings.allows(request.client.host if request.client else None):
        error = ServiceError(
            "VALIDATION_ERROR",
            "caller is outside the trusted network",
            status_code=403,
            retryable=False,
            fallback=None,
        )
        return _error_response(error, request_id)
    image, _validator, _estimated_tokens = validate_request_limits(body, settings)
    started = time.perf_counter()
    try:
        payload = await service.submit(body, image)
    except ServiceError as error:
        duration_ms = int(max(0.0, time.perf_counter() - started) * 1000)
        _log(request_id, "error", duration_ms, settings, error.code)
        return _error_response(error, request_id)
    duration_ms = int(max(0.0, time.perf_counter() - started) * 1000)
    _log(request_id, "ok", duration_ms, settings, "inference complete")
    return JSONResponse(content=payload, headers={"X-Request-ID": request_id})


if __name__ == "__main__":  # pragma: no cover - convenience for Manta
    import uvicorn

    uvicorn.run(
        "service:app",
        host=settings.bind_host,
        port=settings.port,
        workers=1,
        access_log=False,
    )
