from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, File, Form, Request, Response, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from .analyzer import LessonAnalyzer
from .config import Settings
from .db import Database
from .errors import AppError
from .gimbal import GimbalController, GimbalError, GimbalResult
from .health import HealthAggregator
from .image_pipeline import ImagePreparer
from .lesson_pipeline import LessonAnalysisPipeline, accessible_activity_issues
from .language import LanguageNormalizer
from .models import (
    ErrorCode,
    ErrorEnvelope,
    HealthResponse,
    Lesson,
    LessonPatch,
    NormalizeUtteranceRequest,
    ObserverSessionSummary,
    SCHEMA_VERSION,
    SessionCreateRequest,
    StudentActionRequest,
    StudentActionResult,
    SessionView,
    TurnResult,
    TurnSubmission,
    Utterance,
)
from .providers import FixtureProvider, LessonProvider, Mi300Client, load_lesson_schema
from .rag import (
    EmbeddingError,
    HybridRetrievalConfig,
    HybridRetriever,
    RagIndexManager,
    create_embedding_backend,
)
from .session_service import SessionService
from .teaching_agent import TeachingAgent


LOGGER = logging.getLogger("hear_our_language.core_api")
REPOSITORY_ROOT = Path(__file__).resolve().parents[3]


def _request_id(request: Request) -> str:
    value = getattr(request.state, "request_id", None)
    if value:
        return value
    try:
        return str(uuid.UUID(request.headers.get("X-Request-ID", "")))
    except ValueError:
        return str(uuid.uuid4())


def _error_response(error: AppError, request_id: str) -> JSONResponse:
    body = ErrorEnvelope(
        schema_version=SCHEMA_VERSION,
        code=error.code,
        message=error.message,
        retryable=error.retryable,
        fallback=error.fallback,
        request_id=request_id,
        details=error.details or {},
    )
    return JSONResponse(
        status_code=error.status_code,
        content=body.model_dump(mode="json"),
        headers={"X-Request-ID": request_id},
    )


def create_app(settings: Settings | None = None, provider: LessonProvider | None = None) -> FastAPI:
    settings = settings or Settings.from_env()
    lesson_schema = load_lesson_schema(REPOSITORY_ROOT)
    fixture_path = settings.fixture_path
    if not fixture_path.is_absolute():
        fixture_path = REPOSITORY_ROOT / fixture_path
    fixture = FixtureProvider(fixture_path)
    primary: LessonProvider = provider or (
        fixture if settings.provider_mode == "fixture" else Mi300Client(settings, lesson_schema)
    )
    database = Database(settings.database_path, settings.migration_dir)
    preparer = ImagePreparer(settings)
    language_golden_path = settings.language_golden_path
    if not language_golden_path.is_absolute():
        language_golden_path = REPOSITORY_ROOT / language_golden_path
    normalizer = LanguageNormalizer(language_golden_path)
    try:
        embedding_backend = create_embedding_backend(
            settings.rag_embedding_backend,
            dimension=settings.rag_embedding_dimension,
            onnx_model_path=settings.rag_onnx_model_path,
            onnx_tokenizer_path=settings.rag_onnx_tokenizer_path,
        )
        rag_manager = RagIndexManager(settings.rag_index_root, embedding_backend)
    except EmbeddingError as exc:
        # A missing optional ONNX runtime/model must not prevent the laptop
        # Core API from starting. Health stays degraded until the operator
        # installs an approved backend or uses the CPU fallback explicitly.
        fallback_backend = create_embedding_backend("hashing-char-ngram-v1")
        rag_manager = RagIndexManager(settings.rag_index_root, fallback_backend)
        rag_manager.last_error = str(exc)
    retriever = HybridRetriever(
        rag_manager,
        HybridRetrievalConfig(
            top_k=settings.rag_top_k,
            min_score=settings.rag_min_score,
            context_budget_chars=settings.rag_context_budget_chars,
        ),
    )
    pipeline = LessonAnalysisPipeline(
        primary if hasattr(primary, "generate") else None,
        retriever,
        language_normalizer=normalizer,
        validate_model_output=settings.vlm_output_validation_enabled,
    )
    analyzer = LessonAnalyzer(preparer, primary, fixture, pipeline=pipeline)
    gimbal = GimbalController(settings.gimbal_port, settings.gimbal_baud, settings.gimbal_model_path)
    health = HealthAggregator(settings, database, primary, rag_manager)
    semantic_judge = primary if callable(getattr(primary, "judge_answer", None)) else None
    sessions = SessionService(
        database,
        TeachingAgent(
            semantic_judge,
            semantic_timeout_seconds=settings.semantic_timeout_seconds,
            normalizer=normalizer,
        ),
        health,
    )

    @asynccontextmanager
    async def lifespan(application: FastAPI):
        database.migrate()
        removed = preparer.cleanup_stale()
        if removed:
            LOGGER.info("removed stale uploads", extra={"removed_count": removed})
        rag_manager.open_active()
        application.state.settings = settings
        application.state.database = database
        application.state.analyzer = analyzer
        application.state.language_normalizer = normalizer
        application.state.rag = rag_manager
        application.state.retriever = retriever
        application.state.health = health
        application.state.sessions = sessions
        try:
            yield
        finally:
            try:
                await asyncio.to_thread(gimbal.stop)
            except GimbalError:
                LOGGER.warning("gimbal did not acknowledge shutdown")
            rag_manager.close()
            await health.close()
            await primary.close()
            if primary is not fixture:
                await fixture.close()

    app = FastAPI(
        title="Hear Our Language Core Backend API",
        version=SCHEMA_VERSION,
        description=(
            "Ryzen AI 9 laptop product API. The browser never receives or calls the MI300 internal URL. "
            "Canonical cross-agent contract: packages/contracts/openapi/v0.1/core-api.openapi.json."
        ),
        lifespan=lifespan,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(settings.allowed_origins),
        allow_credentials=False,
        allow_methods=["GET", "POST", "PATCH", "OPTIONS"],
        allow_headers=[
            "Accept",
            "Content-Type",
            "Idempotency-Key",
            "If-Match",
            "Last-Event-ID",
            "X-Request-ID",
            "X-Session-Revision",
        ],
        expose_headers=[
            "X-Request-ID",
            "X-Provider-Mode",
            "X-Session-Revision",
            "X-Event-ID",
            "X-Idempotency-Replayed",
        ],
    )

    @app.middleware("http")
    async def request_context(request: Request, call_next):
        started = time.perf_counter()
        request_id = _request_id(request)
        request.state.request_id = request_id
        try:
            response = await call_next(request)
        except Exception:
            LOGGER.exception("unhandled request error", extra={"request_id": request_id})
            response = _error_response(
                AppError(
                    ErrorCode.INTERNAL_ERROR,
                    "internal server error",
                    status_code=500,
                    retryable=False,
                ),
                request_id,
            )
        response.headers["X-Request-ID"] = request_id
        LOGGER.info(
            "request completed",
            extra={
                "request_id": request_id,
                "method": request.method,
                "path": request.url.path,
                "status_code": response.status_code,
                "duration_ms": round((time.perf_counter() - started) * 1000),
            },
        )
        return response

    @app.exception_handler(AppError)
    async def app_error_handler(request: Request, error: AppError):
        return _error_response(error, _request_id(request))

    @app.exception_handler(GimbalError)
    async def gimbal_error_handler(request: Request, error: GimbalError):
        return _error_response(
            AppError(ErrorCode.GIMBAL_UNAVAILABLE, str(error), status_code=503, retryable=True),
            _request_id(request),
        )

    @app.exception_handler(RequestValidationError)
    async def validation_error_handler(request: Request, error: RequestValidationError):
        fields = [".".join(str(part) for part in item.get("loc", ()))[:200] for item in error.errors()[:20]]
        return _error_response(
            AppError(
                ErrorCode.VALIDATION_ERROR,
                "request validation failed",
                status_code=400,
                details={"fields": fields},
            ),
            _request_id(request),
        )

    @app.exception_handler(StarletteHTTPException)
    async def http_error_handler(request: Request, error: StarletteHTTPException):
        return _error_response(
            AppError(
                ErrorCode.VALIDATION_ERROR,
                "route or method is not available" if error.status_code in {404, 405} else "request failed",
                status_code=error.status_code,
            ),
            _request_id(request),
        )

    error_responses = {
        400: {"model": ErrorEnvelope, "description": "Invalid or low-quality image."},
        503: {"model": ErrorEnvelope, "description": "MI300 unavailable or circuit open."},
        504: {"model": ErrorEnvelope, "description": "MI300 request timed out."},
    }

    def idempotency_key(request: Request) -> str:
        value = (request.headers.get("Idempotency-Key") or _request_id(request)).strip()
        if not value or len(value) > 128:
            raise AppError(
                ErrorCode.VALIDATION_ERROR,
                "Idempotency-Key must be between 1 and 128 characters",
                status_code=400,
                fallback="retry_later",
            )
        return value

    def expected_revision(request: Request, body_value: int | None = None) -> int | None:
        header_value = request.headers.get("X-Session-Revision") or request.headers.get("If-Match")
        if header_value is None or header_value.strip() == "*":
            return body_value
        raw = header_value.strip().strip('"')
        try:
            parsed = int(raw)
        except ValueError as exc:
            raise AppError(
                ErrorCode.VALIDATION_ERROR,
                "session revision must be a non-negative integer",
                status_code=400,
                fallback="retry_later",
            ) from exc
        if parsed < 0 or (body_value is not None and body_value != parsed):
            raise AppError(
                ErrorCode.VALIDATION_ERROR,
                "session revision values do not agree",
                status_code=400,
                fallback="retry_later",
            )
        return parsed

    def session_headers(response: Response, revision: int, event_id: int, replayed: bool = False) -> None:
        response.headers["X-Session-Revision"] = str(revision)
        response.headers["X-Event-ID"] = str(event_id)
        response.headers["X-Idempotency-Replayed"] = "true" if replayed else "false"

    @app.get("/api/health", response_model=HealthResponse, operation_id="getHealth")
    async def get_health(request: Request) -> HealthResponse:
        return await health.snapshot(_request_id(request))

    @app.post("/api/gimbal/start", response_model=GimbalResult, operation_id="startGimbal")
    async def start_gimbal() -> GimbalResult:
        return await asyncio.to_thread(gimbal.start)

    @app.post("/api/gimbal/observe", response_model=GimbalResult, operation_id="observeGimbal")
    async def observe_gimbal(image: UploadFile = File(...)) -> GimbalResult:
        data = await image.read(1_000_001)
        try:
            return await asyncio.to_thread(gimbal.observe, data)
        except ValueError as exc:
            raise AppError(ErrorCode.VALIDATION_ERROR, str(exc), status_code=400) from exc

    @app.post("/api/gimbal/test", response_model=GimbalResult, operation_id="testGimbal")
    async def test_gimbal() -> GimbalResult:
        return await asyncio.to_thread(gimbal.test)

    @app.post("/api/gimbal/stop", response_model=GimbalResult, operation_id="stopGimbal")
    async def stop_gimbal() -> GimbalResult:
        return await asyncio.to_thread(gimbal.stop)

    @app.post(
        "/api/lessons/analyze",
        response_model=Lesson,
        responses=error_responses,
        operation_id="analyzeLesson",
    )
    async def analyze_lesson(
        request: Request,
        image: UploadFile = File(...),
        language: Literal["nan-TW"] = Form(...),
        use_fixture_on_failure: bool = Form(True),
    ) -> JSONResponse:
        del language
        try:
            result = await analyzer.analyze(
                image,
                _request_id(request),
                use_fixture_on_failure=use_fixture_on_failure,
            )
            try:
                await asyncio.to_thread(database.save_lesson, result.lesson)
            except Exception as exc:  # pragma: no cover - defensive storage boundary
                LOGGER.exception("lesson persistence failed", extra={"request_id": _request_id(request)})
                raise AppError(
                    ErrorCode.INTERNAL_ERROR,
                    "lesson draft could not be stored",
                    status_code=500,
                    retryable=True,
                    fallback="manual_review",
                ) from exc
        finally:
            await image.close()
        return JSONResponse(
            content=result.lesson.model_dump(mode="json"),
            headers={"X-Provider-Mode": result.provider_mode},
        )

    @app.get(
        "/api/lessons/{lesson_id}",
        response_model=Lesson,
        responses={404: {"model": ErrorEnvelope, "description": "Lesson was not found."}},
        operation_id="getLesson",
    )
    async def get_lesson(lesson_id: str) -> Lesson:
        lesson = await asyncio.to_thread(database.get_lesson, lesson_id)
        if lesson is None:
            raise AppError(
                ErrorCode.LESSON_NOT_FOUND,
                "lesson was not found",
                status_code=404,
                fallback="manual_review",
            )
        return lesson

    @app.patch(
        "/api/lessons/{lesson_id}",
        response_model=Lesson,
        responses={
            400: {"model": ErrorEnvelope, "description": "Invalid teacher review update."},
            404: {"model": ErrorEnvelope, "description": "Lesson was not found."},
        },
        operation_id="reviewLesson",
    )
    async def review_lesson(lesson_id: str, body: LessonPatch) -> Lesson:
        current = await asyncio.to_thread(database.get_lesson, lesson_id)
        if current is None:
            raise AppError(
                ErrorCode.LESSON_NOT_FOUND,
                "lesson was not found",
                status_code=404,
                fallback="manual_review",
            )
        patch = body.model_dump(exclude_none=True)
        candidate = current.model_copy(update=patch)
        if "source_text" in patch:
            patch["source_utterance"] = normalizer.normalize_labeled_segments(
                text=candidate.source_text,
                segments=[{"lang": "nan-TW", "content": candidate.source_text}],
                utterance_id=f"utt_{lesson_id}_source",
            ).utterance.model_dump(mode="json")
        if "accessible_activity" in patch:
            # A teacher-edited activity has no MI300 language labels. Keep a
            # conservative Chinese playback contract until a new analysis
            # supplies explicit Taiwanese spans.
            patch["accessible_activity_utterance"] = normalizer.normalize_labeled_segments(
                text=candidate.accessible_activity,
                segments=[{"lang": "zh-TW", "content": candidate.accessible_activity}],
                utterance_id=f"utt_{lesson_id}_activity",
            ).utterance.model_dump(mode="json")
            candidate = current.model_copy(update=patch)
        safety_reasons = (
            accessible_activity_issues(
                candidate.accessible_activity,
                candidate.answer_evidence,
                {"answer_leak_free": True, "no_position_hint": True, "no_sighted_only_clue": True},
            )
            if settings.vlm_output_validation_enabled
            else ()
        )
        if safety_reasons:
            raise AppError(
                ErrorCode.VALIDATION_ERROR,
                "accessible activity failed the safety checks",
                status_code=400,
                fallback="manual_review",
                details={"reasons": list(safety_reasons)},
            )
        updated = await asyncio.to_thread(database.update_lesson, lesson_id, patch)
        if updated is None:  # pragma: no cover - guarded by the read above
            raise AppError(
                ErrorCode.LESSON_NOT_FOUND,
                "lesson was not found",
                status_code=404,
                fallback="manual_review",
            )
        return updated

    @app.post(
        "/api/utterances/normalize",
        response_model=Utterance,
        responses={400: {"model": ErrorEnvelope, "description": "Invalid normalization input."}},
        operation_id="normalizeUtterance",
    )
    async def normalize_utterance(
        request: Request,
        body: NormalizeUtteranceRequest,
    ) -> Utterance:
        del request
        try:
            result = normalizer.normalize(
                text=body.text,
                lang=body.lang,
                tailo_citation=body.tailo_citation,
            )
        except ValueError as exc:
            raise AppError(
                ErrorCode.VALIDATION_ERROR,
                str(exc),
                status_code=400,
                fallback="manual_review",
            ) from exc
        return result.utterance

    @app.post(
        "/api/sessions",
        response_model=SessionView,
        status_code=201,
        responses={
            400: {"model": ErrorEnvelope, "description": "Invalid session request."},
            404: {"model": ErrorEnvelope, "description": "Lesson was not found."},
            409: {"model": ErrorEnvelope, "description": "Lesson approval or idempotency conflict."},
        },
        operation_id="createSession",
    )
    async def create_session(
        request: Request,
        response: Response,
        body: SessionCreateRequest,
    ) -> SessionView:
        command = await sessions.create_session(
            body.lesson_id,
            _request_id(request),
            idempotency_key(request),
        )
        session_headers(
            response,
            command.response.revision,
            command.event.event_id,
            command.replayed,
        )
        return command.response

    @app.get(
        "/api/sessions/{session_id}",
        response_model=SessionView,
        responses={404: {"model": ErrorEnvelope, "description": "Session was not found."}},
        operation_id="getSession",
    )
    async def get_session(request: Request, response: Response, session_id: str) -> SessionView:
        del request
        view = await sessions.get_student_session(session_id)
        session_headers(response, view.revision, view.last_event_id)
        return view

    @app.get(
        "/api/sessions/{session_id}/snapshot",
        response_model=SessionView,
        responses={404: {"model": ErrorEnvelope, "description": "Session was not found."}},
        operation_id="getSessionSnapshot",
    )
    async def get_session_snapshot(request: Request, response: Response, session_id: str) -> SessionView:
        del request
        view = await sessions.get_student_session(session_id)
        session_headers(response, view.revision, view.last_event_id)
        return view

    @app.post(
        "/api/sessions/{session_id}/actions",
        response_model=StudentActionResult,
        responses={
            400: {"model": ErrorEnvelope, "description": "Invalid student action."},
            404: {"model": ErrorEnvelope, "description": "Session was not found."},
            409: {"model": ErrorEnvelope, "description": "Revision or idempotency conflict."},
        },
        operation_id="submitStudentAction",
    )
    async def submit_student_action(
        request: Request,
        response: Response,
        session_id: str,
        body: StudentActionRequest,
    ) -> StudentActionResult:
        command = await sessions.submit_action(
            session_id,
            body.action,
            _request_id(request),
            idempotency_key(request),
            expected_revision(request, body.expected_revision),
        )
        session_headers(
            response,
            command.response.revision,
            command.event.event_id,
            command.replayed,
        )
        return command.response

    @app.post(
        "/api/sessions/{session_id}/turns",
        response_model=TurnResult,
        responses={
            400: {"model": ErrorEnvelope, "description": "Invalid answer submission."},
            404: {"model": ErrorEnvelope, "description": "Session was not found."},
            409: {"model": ErrorEnvelope, "description": "Session state, revision, or idempotency conflict."},
        },
        operation_id="submitTurn",
    )
    async def submit_turn(
        request: Request,
        response: Response,
        session_id: str,
        body: TurnSubmission,
    ) -> TurnResult:
        command = await sessions.submit_turn(
            session_id,
            body,
            _request_id(request),
            idempotency_key(request),
            expected_revision(request, body.expected_revision),
        )
        session_headers(
            response,
            command.response.revision,
            command.event.event_id,
            command.replayed,
        )
        return command.response

    @app.get(
        "/api/sessions/{session_id}/events",
        response_class=StreamingResponse,
        responses={404: {"model": ErrorEnvelope, "description": "Session was not found."}},
        operation_id="streamSessionEvents",
    )
    async def stream_session_events(
        request: Request,
        session_id: str,
        after: int | None = None,
    ) -> StreamingResponse:
        last_event_header = request.headers.get("Last-Event-ID")
        if after is None and last_event_header:
            try:
                after = int(last_event_header)
            except ValueError as exc:
                raise AppError(
                    ErrorCode.VALIDATION_ERROR,
                    "Last-Event-ID must be a non-negative integer",
                    status_code=400,
                    fallback="retry_later",
                ) from exc
        if after is None:
            after = 0
        if after < 0:
            raise AppError(
                ErrorCode.VALIDATION_ERROR,
                "Last-Event-ID must be a non-negative integer",
                status_code=400,
                fallback="retry_later",
            )
        snapshot = await sessions.get_student_session(session_id)
        events = await sessions.get_events(session_id, after)

        async def event_body():
            if not events:
                yield ": heartbeat\n\n"
                return
            for event in events:
                payload = json.dumps(event.model_dump(mode="json"), ensure_ascii=False, separators=(",", ":"))
                yield f"id: {event.event_id}\nevent: {event.event}\ndata: {payload}\n\n"

        return StreamingResponse(
            event_body(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Session-Revision": str(snapshot.revision),
                "X-Event-ID": str(snapshot.last_event_id),
            },
        )

    @app.get(
        "/api/sessions/{session_id}/summary",
        response_model=ObserverSessionSummary,
        responses={404: {"model": ErrorEnvelope, "description": "Session was not found."}},
        operation_id="getSessionSummary",
    )
    async def get_session_summary(request: Request, response: Response, session_id: str) -> ObserverSessionSummary:
        summary = await sessions.get_summary(session_id, _request_id(request))
        session_headers(response, summary.revision, summary.last_event_id)
        return summary

    return app


app = create_app()
