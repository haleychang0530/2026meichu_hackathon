from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


SCHEMA_VERSION = "0.1.0"


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ErrorCode(StrEnum):
    VALIDATION_ERROR = "VALIDATION_ERROR"
    IMAGE_QUALITY_LOW = "IMAGE_QUALITY_LOW"
    LESSON_NOT_FOUND = "LESSON_NOT_FOUND"
    SESSION_NOT_FOUND = "SESSION_NOT_FOUND"
    SESSION_REVISION_CONFLICT = "SESSION_REVISION_CONFLICT"
    IDEMPOTENCY_CONFLICT = "IDEMPOTENCY_CONFLICT"
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
    # Teacher/parent-only visual answer basis. This is additive in v0.1 so
    # older lessons remain readable while Stage 07 always populates it.
    answer_evidence: list[str] = Field(default_factory=list)
    evidence: list[EvidenceItem]
    confidence: float = Field(ge=0, le=1)
    review_status: Literal["pending", "approved", "rejected"]
    vlm_model_revision: str | None
    rag_index_revision: str | None


class LessonPatch(StrictModel):
    topic: str | None = Field(default=None, min_length=1, max_length=200)
    source_text: str | None = Field(default=None, min_length=1)
    accessible_activity: str | None = Field(default=None, min_length=1)
    review_status: Literal["pending", "approved", "rejected"] | None = None

    @model_validator(mode="after")
    def require_one_value(self) -> "LessonPatch":
        if not any(value is not None for value in self.model_dump().values()):
            raise ValueError("at least one lesson field is required")
        return self


class NormalizeUtteranceRequest(StrictModel):
    schema_version: Literal["0.1.0"]
    text: str = Field(min_length=1)
    lang: Literal["nan-TW", "zh-TW"]
    tailo_citation: str | None = None


class UtteranceSegment(StrictModel):
    lang: Literal["nan-TW", "zh-TW"]
    hanji: str = Field(min_length=1)
    tailo_citation: str | None
    poj_citation: str | None
    zh_gloss: str | None
    source: Literal["textbook", "dictionary", "generated"]
    pronunciation_status: Literal["verified", "converted", "needs_review"]


class Utterance(StrictModel):
    schema_version: Literal["0.1.0"] = SCHEMA_VERSION
    id: str = Field(pattern=r"^utt_[A-Za-z0-9_-]+$")
    segments: list[UtteranceSegment] = Field(min_length=1)
    tts_provider: Literal["mms-tts-nan", "windows", "prerecorded"] | None
    audio_url: str | None = None
    audio_cache_key: str | None = None


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


SessionState = Literal[
    "IDLE",
    "SPEAKING",
    "LISTENING",
    "TRANSCRIBING",
    "EVALUATING",
    "RECOVERABLE_ERROR",
    "COMPLETE",
]
TeachingPhase = Literal[
    "introduction",
    "demonstration",
    "read_aloud",
    "comprehension",
    "hint",
    "review",
    "complete",
]
ControlAction = Literal[
    "replay_prompt",
    "start_answer",
    "pause",
    "resume",
    "request_hint",
    "next",
]
InputMode = Literal["voice", "keyboard", "pointer"]
TurnOutcome = Literal["correct", "partial", "retry"]
FamiliarityStatus = Literal["new", "developing", "familiar"]


class SessionCreateRequest(StrictModel):
    schema_version: Literal["0.1.0"]
    lesson_id: str = Field(pattern=r"^lesson_[A-Za-z0-9_-]+$")


class StudentActionRequest(StrictModel):
    schema_version: Literal["0.1.0"]
    action: ControlAction
    input_mode: InputMode | None = None
    # Optional body form for non-browser clients. Browser clients may use the
    # X-Session-Revision/If-Match header instead.
    expected_revision: int | None = Field(default=None, ge=0)


class TurnSubmission(StrictModel):
    schema_version: Literal["0.1.0"]
    transcript: str = Field(min_length=1)
    input_mode: InputMode | None = None
    asr_device: Literal["npu", "cpu"] | None = None
    expected_revision: int | None = Field(default=None, ge=0)


class SessionView(StrictModel):
    """Student-safe session projection.

    This projection intentionally contains no Lesson content, evidence,
    confidence, answer key, or teacher control fields.
    """

    schema_version: Literal["0.1.0"] = SCHEMA_VERSION
    session_id: str = Field(pattern=r"^session_[A-Za-z0-9_-]+$")
    lesson_id: str = Field(pattern=r"^lesson_[A-Za-z0-9_-]+$")
    state: SessionState
    phase: TeachingPhase = "introduction"
    progress: float = Field(ge=0, le=1)
    current_prompt: str | None
    can_answer: bool = False
    revision: int = Field(default=0, ge=0)
    last_event_id: int = Field(default=0, ge=0)


class LatencyMetrics(StrictModel):
    asr: int | None = Field(ge=0)
    backend: int = Field(ge=0)
    vlm: int | None = Field(ge=0)
    tts: int | None = Field(ge=0)
    total: int = Field(ge=0)


class TurnResult(StrictModel):
    schema_version: Literal["0.1.0"] = SCHEMA_VERSION
    turn_id: str = Field(pattern=r"^turn_[A-Za-z0-9_-]+$")
    session_id: str = Field(pattern=r"^session_[A-Za-z0-9_-]+$")
    transcript_raw: str
    transcript_normalized: str
    result: TurnOutcome
    matched_concepts: list[str]
    feedback: str = Field(min_length=1)
    next_prompt: str = Field(min_length=1)
    progress: float = Field(ge=0, le=1)
    latency_ms: LatencyMetrics
    asr_device: Literal["npu", "cpu"]
    fallbacks: list[Literal[
        "mi300_offline",
        "rag_no_result",
        "asr_cpu",
        "tts_prerecorded",
        "cached_lesson",
        "fixture_mode",
    ]]
    phase: TeachingPhase = "introduction"
    revision: int = Field(default=0, ge=0)
    last_event_id: int = Field(default=0, ge=0)


class StudentActionResult(StrictModel):
    schema_version: Literal["0.1.0"] = SCHEMA_VERSION
    session_id: str = Field(pattern=r"^session_[A-Za-z0-9_-]+$")
    lesson_id: str = Field(pattern=r"^lesson_[A-Za-z0-9_-]+$")
    state: SessionState
    progress: float = Field(ge=0, le=1)
    current_prompt: str | None
    action: ControlAction
    feedback: str | None
    next_prompt: str | None
    can_answer: bool
    phase: TeachingPhase = "introduction"
    revision: int = Field(default=0, ge=0)
    last_event_id: int = Field(default=0, ge=0)


class ObserverHint(StrictModel):
    turn_id: str = Field(pattern=r"^turn_[A-Za-z0-9_-]+$")
    prompt: str = Field(min_length=1)
    feedback: str = Field(min_length=1)


class Familiarity(StrictModel):
    concept: str = Field(min_length=1)
    status: FamiliarityStatus


class ObserverSessionSummary(StrictModel):
    """Teacher/parent projection; never return this from student routes."""

    schema_version: Literal["0.1.0"] = SCHEMA_VERSION
    session_id: str = Field(pattern=r"^session_[A-Za-z0-9_-]+$")
    lesson_id: str = Field(pattern=r"^lesson_[A-Za-z0-9_-]+$")
    state: SessionState
    progress: float = Field(ge=0, le=1)
    completed_turns: int = Field(ge=0)
    turns: list[TurnResult]
    concepts_to_review: list[str]
    hint_history: list[ObserverHint]
    familiarity: list[Familiarity]
    # These fields are additive teacher/parent review data. They are never
    # copied by the student selector.
    evidence: list[EvidenceItem] = Field(default_factory=list)
    health: list[ServiceHealth] = Field(default_factory=list)
    review_status: Literal["pending", "approved", "rejected"] | None = None
    confidence: float | None = Field(default=None, ge=0, le=1)
    answer_evidence: list[str] = Field(default_factory=list)
    vlm_model_revision: str | None = None
    rag_index_revision: str | None = None
    phase: TeachingPhase = "introduction"
    revision: int = Field(default=0, ge=0)
    last_event_id: int = Field(default=0, ge=0)


class SessionEvent(StrictModel):
    schema_version: Literal["0.1.0"] = SCHEMA_VERSION
    event_id: int = Field(ge=1)
    session_id: str = Field(pattern=r"^session_[A-Za-z0-9_-]+$")
    event: str = Field(min_length=1, max_length=80)
    request_id: str
    revision: int = Field(ge=0)
    payload: dict[str, Any]


class SemanticJudgement(StrictModel):
    """Internal MI300 result; never returned as a student response."""

    decision: TurnOutcome
    matched_concepts: list[str] = Field(default_factory=list)
    latency_ms: int | None = Field(default=None, ge=0)
