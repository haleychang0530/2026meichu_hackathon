from __future__ import annotations

from typing import Any

from .models import ErrorCode, Fallback


class AppError(Exception):
    def __init__(
        self,
        code: ErrorCode,
        message: str,
        *,
        status_code: int,
        retryable: bool = False,
        fallback: Fallback | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code
        self.retryable = retryable
        self.fallback = fallback
        self.details = details


class ProviderError(AppError):
    pass
