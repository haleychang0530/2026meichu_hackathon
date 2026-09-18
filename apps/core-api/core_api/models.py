from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


SCHEMA_VERSION = "0.1.0"


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ErrorCode(StrEnum):
    VALIDATION_ERROR = "VALIDATION_ERROR"
    IMAGE_QUALITY_LOW = "IMAGE_QUALITY_LOW"
    LESSON_NOT_FOUND = "LESSON_NOT_FOUND"
    SESSION_NOT_FOUND = "SESSION_NOT_FOUND"
    VLM_TIMEOUT = "VLM_TIMEOUT"
    VLM_OFFLINE = "VLM_OFFLINE"
    VLM_INVALID_OUTPUT = "VLM_INVALID_OUTPUT"
    RAG_NO_RESULT = "RAG_NO_RESULT"
    ASR_UNAVAILABLE = "ASR_UNAVAILABLE"
    ASR_FAILED = "ASR_FAILED"
    TTS_UNAVAILABLE = "TTS_UNAVAILABLE"
    TTS_FAILED = "TTS_FAILED"
    CIRCUIT_OPEN = "CIRCUIT_OPEN"
    INTERNAL_ERROR = "INTERNAL_ERROR"


Fallback = Literal[
    "cached_lesson",
    "fixture_mode",
    "manual_review",
    "retry_later",
    "keyboard_input",
    "app_narration",
    "prerecorded_audio",
]


class ErrorEnvelope(StrictModel):
    schema_version: Literal["0.1.0"] = SCHEMA_VERSION
    code: ErrorCode
    message: str = Field(min_length=1, max_length=500)
    retryable: bool
    fallback: Fallback | None
    request_id: str
    details: dict[str, Any] = Field(default_factory=dict)


class VocabularyItem(StrictModel):
    hanji: str = Field(min_length=1)
    tailo: str = Field(min_length=1)
    meaning: str = Field(min_length=1)
    audio_key: str | None


class EvidenceItem(StrictModel):
    source_id: str = Field(min_length=1)
    title: str = Field(min_length=1)
    excerpt: str = Field(min_length=1)
    locator: str = Field(min_length=1)


class Lesson(StrictModel):
    schema_version: Literal["0.1.0"]
    lesson_id: str = Field(pattern=r"^lesson_[A-Za-z0-9_-]+$")
    topic: str = Field(min_length=1, max_length=200)
    source_text: str = Field(min_length=1)
    vocabulary: list[VocabularyItem]
    scene: str = Field(min_length=1)
    original_activity: str = Field(min_length=1)
    learning_objective: str = Field(min_length=1)
    accessible_activity: str = Field(min_length=1)
    evidence: list[EvidenceItem]
    confidence: float = Field(ge=0, le=1)
    review_status: Literal["pending", "approved", "rejected"]
    vlm_model_revision: str | None
    rag_index_revision: str | None


class ServiceHealth(StrictModel):
    schema_version: Literal["0.1.0"] = SCHEMA_VERSION
    service: Literal["core-api", "rag", "vlm-mi300", "asr", "tts"]
    status: Literal["ready", "degraded", "offline"]
    device: str | None
    model_revision: str | None
    queue_depth: int = Field(ge=0)
    last_error: ErrorEnvelope | None
    checked_at: datetime


class HealthResponse(StrictModel):
    schema_version: Literal["0.1.0"] = SCHEMA_VERSION
    request_id: str
    status: Literal["ready", "degraded", "offline"]
    services: list[ServiceHealth]
