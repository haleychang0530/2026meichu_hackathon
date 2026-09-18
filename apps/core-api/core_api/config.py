from __future__ import annotations

import os
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Literal


Profile = Literal["development", "demo", "test"]
ProviderMode = Literal["real", "fixture"]


def _bool_env(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _int_env(name: str, default: int, minimum: int = 0) -> int:
    raw = os.getenv(name)
    if raw is None:
        return default
    value = int(raw)
    if value < minimum:
        raise ValueError(f"{name} must be >= {minimum}")
    return value


def _float_env(name: str, default: float, minimum: float = 0.0) -> float:
    raw = os.getenv(name)
    if raw is None:
        return default
    value = float(raw)
    if value < minimum:
        raise ValueError(f"{name} must be >= {minimum}")
    return value


def _default_data_dir() -> Path:
    root = os.getenv("LOCALAPPDATA")
    if root:
        return Path(root) / "HearOurLanguage"
    return Path.home() / ".local" / "share" / "HearOurLanguage"


@dataclass(frozen=True, slots=True)
class Settings:
    profile: Profile = "development"
    host: str = "127.0.0.1"
    port: int = 8000
    provider_mode: ProviderMode = "real"
    data_dir: Path = _default_data_dir()
    allowed_origins: tuple[str, ...] = ("http://127.0.0.1:5173", "http://localhost:5173")
    vlm_base_url: str = "http://127.0.0.1:8100"
    vlm_model_revision: str = "d9748a51ae66354c4dad665aab2c71f26cf2c8cd"
    speech_base_url: str | None = "http://127.0.0.1:8200"
    connect_timeout_seconds: float = 2.0
    read_timeout_seconds: float = 120.0
    health_timeout_seconds: float = 1.0
    max_attempts: int = 2
    retry_backoff_seconds: float = 0.25
    circuit_failure_threshold: int = 3
    circuit_recovery_seconds: float = 30.0
    max_image_bytes: int = 10 * 1024 * 1024
    max_image_pixels: int = 20_000_000
    max_image_dimension: int = 8192
    normalized_image_dimension: int = 4096
    upload_ttl_seconds: int = 15 * 60
    fixture_path: Path = Path("fixtures/contracts/v0.1/observer/success.lesson.json")
    rag_manifest_path: Path = Path("data/rag/manifest.json")
    rag_index_root_override: Path | None = None
    rag_embedding_backend: str = "hashing-char-ngram-v1"
    rag_embedding_dimension: int = 256
    rag_onnx_model_path: Path | None = None
    rag_onnx_tokenizer_path: Path | None = None
    rag_top_k: int = 5
    rag_min_score: float = 0.40
    rag_context_budget_chars: int = 1600
    language_golden_path: Path = Path("data/language/normalization-golden.json")

    @property
    def database_path(self) -> Path:
        return self.data_dir / "db" / "app.sqlite3"

    @property
    def upload_dir(self) -> Path:
        return self.data_dir / "tmp" / "uploads"

    @property
    def migration_dir(self) -> Path:
        return Path(__file__).resolve().parents[1] / "migrations"

    @property
    def rag_index_root(self) -> Path:
        return self.rag_index_root_override or (self.data_dir / "rag" / "indexes")

    @classmethod
    def from_env(cls, profile: str | None = None) -> "Settings":
        selected = (profile or os.getenv("CORE_PROFILE", "development")).strip().lower()
        if selected not in {"development", "demo", "test"}:
            raise ValueError("CORE_PROFILE must be development, demo, or test")

        defaults = cls(profile=selected)  # type: ignore[arg-type]
        if selected in {"demo", "test"}:
            defaults = replace(defaults, provider_mode="fixture")

        origins = tuple(
            item.strip()
            for item in os.getenv("CORE_ALLOWED_ORIGINS", ",".join(defaults.allowed_origins)).split(",")
            if item.strip()
        )
        provider = os.getenv("CORE_PROVIDER", defaults.provider_mode).strip().lower()
        if provider not in {"real", "fixture"}:
            raise ValueError("CORE_PROVIDER must be real or fixture")
        speech_url = os.getenv("SPEECH_BASE_URL", defaults.speech_base_url or "").strip() or None
        data_dir = Path(os.getenv("CORE_DATA_DIR", str(defaults.data_dir))).expanduser()
        embedding_backend = os.getenv("RAG_EMBEDDING_BACKEND", defaults.rag_embedding_backend).strip()
        if embedding_backend not in {"hashing-char-ngram-v1", "onnx-local"}:
            raise ValueError("RAG_EMBEDDING_BACKEND must be hashing-char-ngram-v1 or onnx-local")
        index_root = os.getenv("RAG_INDEX_ROOT", "").strip()
        model_path = os.getenv("RAG_ONNX_MODEL_PATH", "").strip()
        tokenizer_path = os.getenv("RAG_ONNX_TOKENIZER_PATH", "").strip()
        rag_min_score = _float_env("RAG_MIN_SCORE", defaults.rag_min_score, 0.0)
        if rag_min_score > 1.0:
            raise ValueError("RAG_MIN_SCORE must be <= 1.0")

        return replace(
            defaults,
            host=os.getenv("CORE_HOST", defaults.host),
            port=_int_env("CORE_PORT", defaults.port, 1),
            provider_mode=provider,  # type: ignore[arg-type]
            data_dir=data_dir,
            allowed_origins=origins,
            vlm_base_url=os.getenv("VLM_BASE_URL", defaults.vlm_base_url).rstrip("/"),
            vlm_model_revision=os.getenv("VLM_MODEL_REVISION", defaults.vlm_model_revision),
            speech_base_url=speech_url.rstrip("/") if speech_url else None,
            connect_timeout_seconds=_float_env(
                "VLM_CONNECT_TIMEOUT_SECONDS", defaults.connect_timeout_seconds, 0.01
            ),
            read_timeout_seconds=_float_env("VLM_READ_TIMEOUT_SECONDS", defaults.read_timeout_seconds, 0.01),
            health_timeout_seconds=_float_env(
                "DEPENDENCY_HEALTH_TIMEOUT_SECONDS", defaults.health_timeout_seconds, 0.01
            ),
            max_attempts=_int_env("VLM_MAX_ATTEMPTS", defaults.max_attempts, 1),
            retry_backoff_seconds=_float_env(
                "VLM_RETRY_BACKOFF_SECONDS", defaults.retry_backoff_seconds, 0.0
            ),
            circuit_failure_threshold=_int_env(
                "VLM_CIRCUIT_FAILURE_THRESHOLD", defaults.circuit_failure_threshold, 1
            ),
            circuit_recovery_seconds=_float_env(
                "VLM_CIRCUIT_RECOVERY_SECONDS", defaults.circuit_recovery_seconds, 0.01
            ),
            max_image_bytes=_int_env("CORE_MAX_IMAGE_BYTES", defaults.max_image_bytes, 1),
            fixture_path=Path(os.getenv("CORE_FIXTURE_PATH", str(defaults.fixture_path))),
            rag_manifest_path=Path(
                os.getenv("RAG_MANIFEST_PATH", str(defaults.rag_manifest_path))
            ).expanduser(),
            rag_index_root_override=Path(index_root).expanduser() if index_root else None,
            rag_embedding_backend=embedding_backend,
            rag_embedding_dimension=_int_env("RAG_EMBEDDING_DIMENSION", defaults.rag_embedding_dimension, 32),
            rag_onnx_model_path=Path(model_path).expanduser() if model_path else None,
            rag_onnx_tokenizer_path=Path(tokenizer_path).expanduser() if tokenizer_path else None,
            rag_top_k=_int_env("RAG_TOP_K", defaults.rag_top_k, 1),
            rag_min_score=rag_min_score,
            rag_context_budget_chars=_int_env(
                "RAG_CONTEXT_BUDGET_CHARS", defaults.rag_context_budget_chars, 1
            ),
            language_golden_path=Path(
                os.getenv("LANGUAGE_GOLDEN_PATH", str(defaults.language_golden_path))
            ).expanduser(),
        )
