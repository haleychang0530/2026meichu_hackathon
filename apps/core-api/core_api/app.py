from __future__ import annotations

import logging
import time
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, File, Form, Request, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from .analyzer import LessonAnalyzer
from .config import Settings
from .db import Database
from .errors import AppError
from .health import HealthAggregator
from .image_pipeline import ImagePreparer
from .models import ErrorCode, ErrorEnvelope, HealthResponse, Lesson, SCHEMA_VERSION
from .providers import FixtureProvider, LessonProvider, Mi300Client, load_lesson_schema
from .rag import EmbeddingError, RagIndexManager, create_embedding_backend


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
    analyzer = LessonAnalyzer(preparer, primary, fixture)
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
    health = HealthAggregator(settings, database, primary, rag_manager)

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
        application.state.rag = rag_manager
        application.state.health = health
        try:
            yield
        finally:
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
        allow_headers=["Accept", "Content-Type", "X-Request-ID"],
        expose_headers=["X-Request-ID", "X-Provider-Mode"],
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

    @app.get("/api/health", response_model=HealthResponse, operation_id="getHealth")
    async def get_health(request: Request) -> HealthResponse:
        return await health.snapshot(_request_id(request))

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
        finally:
            await image.close()
        return JSONResponse(
            content=result.lesson.model_dump(mode="json"),
            headers={"X-Provider-Mode": result.provider_mode},
        )

    return app


app = create_app()
