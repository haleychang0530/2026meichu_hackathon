"""Localhost Speech Gateway for Agent B Stage 04.

This module intentionally uses only Python's standard library.  The HTTP
boundary follows ``packages/contracts/openapi/v0.1/speech-gateway.openapi.json``
and the worker interfaces are injectable so the mock path can be tested before
Breeze ASR and MMS-TTS are installed on the laptop.

The gateway is a scheduler, not a product-session owner.  It provides one
bounded inference queue, one CPU semaphore shared by ASR/TTS, cooperative
cancellation, and the half-duplex audio state transitions.  Audio request bytes
are copied only into memory for the duration of transcription and are never
written to disk or included in logs.
"""

from __future__ import annotations

import argparse
from collections import deque
from concurrent.futures import Future, TimeoutError as FutureTimeoutError
from dataclasses import dataclass
from datetime import datetime, timezone
from email import policy
from email.parser import BytesParser
from enum import Enum
import json
import os
import queue
import re
import threading
import time
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Callable, Mapping
from uuid import UUID, uuid4

from workers import (
    ASRWorker,
    CancellationToken,
    MockASRWorker,
    MockTTSWorker,
    TTSWorker,
    WorkerCancelled,
)


SCHEMA_VERSION = "0.1.0"
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8200
DEFAULT_TIMEOUT_S = 15.0
MAX_AUDIO_BYTES = 16 * 1024 * 1024
MAX_JSON_BYTES = 2 * 1024 * 1024
DEFAULT_MAX_PENDING = 4
ALLOWED_LANGUAGES = {"nan-TW", "zh-TW"}
ALLOWED_DEVICE_PREFERENCES = {"npu", "cpu", "auto"}
ALLOWED_ORIGINS = frozenset({
    "http://127.0.0.1:5173",
    "http://localhost:5173",
    "http://127.0.0.1:4173",
    "http://localhost:4173",
})


class HalfDuplexState(str, Enum):
    IDLE = "IDLE"
    SPEAKING = "SPEAKING"
    LISTENING = "LISTENING"
    TRANSCRIBING = "TRANSCRIBING"
    EVALUATING = "EVALUATING"


LEGAL_TRANSITIONS: dict[HalfDuplexState, set[HalfDuplexState]] = {
    HalfDuplexState.IDLE: {HalfDuplexState.SPEAKING, HalfDuplexState.LISTENING},
    HalfDuplexState.SPEAKING: {HalfDuplexState.IDLE, HalfDuplexState.LISTENING},
    HalfDuplexState.LISTENING: {
        HalfDuplexState.IDLE,
        HalfDuplexState.SPEAKING,
        HalfDuplexState.TRANSCRIBING,
    },
    HalfDuplexState.TRANSCRIBING: {HalfDuplexState.IDLE, HalfDuplexState.EVALUATING},
    HalfDuplexState.EVALUATING: {
        HalfDuplexState.IDLE,
        HalfDuplexState.SPEAKING,
        HalfDuplexState.LISTENING,
    },
}


ERROR_CODES = {
    "VALIDATION_ERROR",
    "ASR_UNAVAILABLE",
    "ASR_FAILED",
    "TTS_UNAVAILABLE",
    "TTS_FAILED",
    "INTERNAL_ERROR",
}


class GatewayError(Exception):
    """Stable error that can be returned at the HTTP boundary."""

    def __init__(
        self,
        *,
        code: str,
        message: str,
        retryable: bool,
        fallback: str | None,
        request_id: str,
        status_code: int = HTTPStatus.BAD_REQUEST,
        details: Mapping[str, Any] | None = None,
    ) -> None:
        if code not in ERROR_CODES:
            code = "INTERNAL_ERROR"
        super().__init__(message)
        self.code = code
        self.message = message[:500]
        self.retryable = retryable
        self.fallback = fallback
        self.request_id = request_id
        self.status_code = int(status_code)
        self.details = dict(details) if details else None

    def payload(self) -> dict[str, Any]:
        body: dict[str, Any] = {
            "schema_version": SCHEMA_VERSION,
            "code": self.code,
            "message": self.message,
            "retryable": self.retryable,
            "fallback": self.fallback,
            "request_id": self.request_id,
        }
        if self.details:
            body["details"] = self.details
        return body


class QueueFullError(RuntimeError):
    """Raised when the bounded inference queue has no capacity."""


@dataclass
class _Job:
    request_id: str
    kind: str
    function: Callable[[CancellationToken], Any]
    token: CancellationToken
    future: Future[Any]


class BoundedJobExecutor:
    """One worker thread and a bounded queue for all local inference jobs."""

    def __init__(self, *, max_pending: int = DEFAULT_MAX_PENDING) -> None:
        if max_pending < 1:
            raise ValueError("max_pending must be positive")
        self.max_pending = max_pending
        self._queue: queue.Queue[_Job | None] = queue.Queue(maxsize=max_pending)
        self._jobs: dict[str, _Job] = {}
        self._active: _Job | None = None
        self._lock = threading.RLock()
        self._stopping = False
        self._thread = threading.Thread(
            target=self._run,
            name="speech-gateway-inference",
            daemon=True,
        )
        self._thread.start()

    @property
    def queue_depth(self) -> int:
        with self._lock:
            return self._queue.qsize()

    @property
    def active_request_id(self) -> str | None:
        with self._lock:
            return self._active.request_id if self._active else None

    def submit(
        self,
        *,
        request_id: str,
        kind: str,
        function: Callable[[CancellationToken], Any],
    ) -> Future[Any]:
        with self._lock:
            if self._stopping:
                raise QueueFullError("executor stopped")
            if request_id in self._jobs:
                raise QueueFullError("duplicate request")
            if self._queue.full():
                raise QueueFullError("inference queue full")
            future: Future[Any] = Future()
            job = _Job(
                request_id=request_id,
                kind=kind,
                function=function,
                token=CancellationToken(),
                future=future,
            )
            self._jobs[request_id] = job
            try:
                self._queue.put_nowait(job)
            except queue.Full as exc:  # pragma: no cover - guarded by full()
                self._jobs.pop(request_id, None)
                raise QueueFullError("inference queue full") from exc
            return future

    def cancel(self, request_id: str) -> bool:
        with self._lock:
            job = self._jobs.get(request_id)
            if not job:
                return False
            job.token.cancel()
            return True

    def cancel_all(self) -> int:
        with self._lock:
            jobs = list(self._jobs.values())
            for job in jobs:
                job.token.cancel()
            return len(jobs)

    def shutdown(self) -> None:
        with self._lock:
            if self._stopping:
                return
            self._stopping = True
            for job in self._jobs.values():
                job.token.cancel()
            # A full queue can contain cancelled jobs.  Wait only for the
            # worker to consume one slot; every queued job is cooperative and
            # therefore finishes quickly without running model work.
            try:
                self._queue.put(None, timeout=2.0)
            except queue.Full:  # pragma: no cover - defensive shutdown path
                pass
        self._thread.join(timeout=2.0)

    def _run(self) -> None:
        while True:
            job = self._queue.get()
            if job is None:
                self._queue.task_done()
                return
            with self._lock:
                self._active = job
            try:
                if job.token.cancelled:
                    raise WorkerCancelled("cancelled")
                result = job.function(job.token)
                if not job.future.done():
                    job.future.set_result(result)
            except BaseException as exc:  # worker failures must not kill the loop
                if not job.future.done():
                    job.future.set_exception(exc)
            finally:
                with self._lock:
                    if self._active is job:
                        self._active = None
                    self._jobs.pop(job.request_id, None)
                self._queue.task_done()


@dataclass
class _WorkerHealth:
    service: str
    device: str
    model_revision: str
    status: str = "ready"
    last_error: dict[str, Any] | None = None

    def payload(self, *, queue_depth: int) -> dict[str, Any]:
        return {
            "schema_version": SCHEMA_VERSION,
            "service": self.service,
            "status": self.status,
            "device": self.device,
            "model_revision": self.model_revision,
            "queue_depth": queue_depth,
            "last_error": self.last_error,
            "checked_at": _utc_now(),
        }


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _memory_snapshot() -> dict[str, int | None]:
    """Return process/RAM metadata without adding a third-party dependency."""

    process_rss: int | None = None
    available: int | None = None
    total: int | None = None
    if os.name == "nt":
        try:
            import ctypes
            from ctypes import wintypes

            class _MemoryStatusEx(ctypes.Structure):
                _fields_ = [
                    ("dwLength", wintypes.DWORD),
                    ("dwMemoryLoad", wintypes.DWORD),
                    ("ullTotalPhys", ctypes.c_ulonglong),
                    ("ullAvailPhys", ctypes.c_ulonglong),
                    ("ullTotalPageFile", ctypes.c_ulonglong),
                    ("ullAvailPageFile", ctypes.c_ulonglong),
                    ("ullTotalVirtual", ctypes.c_ulonglong),
                    ("ullAvailVirtual", ctypes.c_ulonglong),
                    ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
                ]

            class _ProcessMemoryCounters(ctypes.Structure):
                _fields_ = [
                    ("cb", wintypes.DWORD),
                    ("PageFaultCount", wintypes.DWORD),
                    ("PeakWorkingSetSize", ctypes.c_size_t),
                    ("WorkingSetSize", ctypes.c_size_t),
                    ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                    ("QuotaPagedPoolUsage", ctypes.c_size_t),
                    ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                    ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                    ("PagefileUsage", ctypes.c_size_t),
                    ("PeakPagefileUsage", ctypes.c_size_t),
                ]

            status = _MemoryStatusEx()
            status.dwLength = ctypes.sizeof(_MemoryStatusEx)
            kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
            psapi = ctypes.WinDLL("psapi", use_last_error=True)
            global_memory_status = kernel32.GlobalMemoryStatusEx
            global_memory_status.argtypes = [ctypes.POINTER(_MemoryStatusEx)]
            global_memory_status.restype = wintypes.BOOL
            if global_memory_status(ctypes.byref(status)):
                total = int(status.ullTotalPhys)
                available = int(status.ullAvailPhys)

            counters = _ProcessMemoryCounters()
            counters.cb = ctypes.sizeof(_ProcessMemoryCounters)
            get_current_process = kernel32.GetCurrentProcess
            get_current_process.restype = wintypes.HANDLE
            get_process_memory_info = psapi.GetProcessMemoryInfo
            get_process_memory_info.argtypes = [
                wintypes.HANDLE,
                ctypes.POINTER(_ProcessMemoryCounters),
                wintypes.DWORD,
            ]
            get_process_memory_info.restype = wintypes.BOOL
            if get_process_memory_info(
                get_current_process(),
                ctypes.byref(counters),
                counters.cb,
            ):
                process_rss = int(counters.WorkingSetSize)
        except (AttributeError, OSError, TypeError):
            pass
    if process_rss is None:
        try:
            import resource

            process_rss = int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
            if os.name != "nt":
                process_rss *= 1024
        except (ImportError, OSError):
            pass
    reserve = max(int(total * 0.25), 6 * 1024**3) if total else None
    runtime_capacity = total - reserve if total is not None and reserve is not None else None
    return {
        "process_rss_bytes": process_rss,
        "available_memory_bytes": available,
        "physical_memory_bytes": total,
        "safe_reserve_bytes": reserve,
        "runtime_capacity_bytes": runtime_capacity,
    }


def _make_error(
    *,
    code: str,
    request_id: str,
    message: str,
    retryable: bool,
    fallback: str | None,
    status_code: int,
    details: Mapping[str, Any] | None = None,
) -> GatewayError:
    return GatewayError(
        code=code,
        request_id=request_id,
        message=message,
        retryable=retryable,
        fallback=fallback,
        status_code=status_code,
        details=details,
    )


class SpeechGatewayService:
    """In-process gateway core used by HTTP handlers and integration tests."""

    def __init__(
        self,
        *,
        asr_worker: ASRWorker | None = None,
        tts_worker: TTSWorker | None = None,
        max_pending: int = DEFAULT_MAX_PENDING,
        timeout_s: float = DEFAULT_TIMEOUT_S,
    ) -> None:
        self.asr_worker = asr_worker or MockASRWorker()
        self.tts_worker = tts_worker or MockTTSWorker()
        self.timeout_s = timeout_s
        self._executor = BoundedJobExecutor(max_pending=max_pending)
        # A real CPU Breeze and MMS-TTS worker must acquire this same semaphore.
        self.cpu_inference_semaphore = threading.Semaphore(1)
        self._lifecycle_lock = threading.RLock()
        self._state_lock = threading.RLock()
        self._health_lock = threading.RLock()
        self._state = HalfDuplexState.IDLE
        self._state_history: deque[HalfDuplexState] = deque(
            [HalfDuplexState.IDLE], maxlen=64
        )
        self._active_request_id: str | None = None
        self._active_kind: str | None = None
        self._health: dict[str, _WorkerHealth] = {
            "asr": _WorkerHealth(
                service="asr",
                device=self.asr_worker.device,
                model_revision=self.asr_worker.model_revision,
            ),
            "tts": _WorkerHealth(
                service="tts",
                device=self.tts_worker.device,
                model_revision=self.tts_worker.model_revision,
            ),
        }

    @property
    def state(self) -> HalfDuplexState:
        with self._state_lock:
            return self._state

    @property
    def state_history(self) -> tuple[HalfDuplexState, ...]:
        with self._state_lock:
            return tuple(self._state_history)

    @property
    def queue_depth(self) -> int:
        return self._executor.queue_depth

    def runtime_diagnostics(self) -> dict[str, Any]:
        """Non-contract diagnostics used by local checks and the handoff report."""

        with self._state_lock:
            state = self._state.value
            active = self._active_request_id is not None
        return {
            "schema_version": SCHEMA_VERSION,
            "state": state,
            "active": active,
            "queue_depth": self.queue_depth,
            "memory": _memory_snapshot(),
        }

    def health_payload(self, request_id: str) -> dict[str, Any]:
        with self._health_lock:
            return {
                "schema_version": SCHEMA_VERSION,
                "request_id": request_id,
                "services": [
                    self._health["asr"].payload(queue_depth=self.queue_depth),
                    self._health["tts"].payload(queue_depth=self.queue_depth),
                ],
            }

    def warmup(
        self,
        *,
        services: list[str] | None,
        request_id: str,
    ) -> dict[str, Any]:
        if services is not None and not isinstance(services, list):
            raise _make_error(
                code="VALIDATION_ERROR",
                request_id=request_id,
                message="services must be an array.",
                retryable=False,
                fallback=None,
                status_code=HTTPStatus.BAD_REQUEST,
            )
        selected = ["asr", "tts"] if services is None else list(services)
        if any(not isinstance(service, str) or service not in {"asr", "tts"} for service in selected):
            raise _make_error(
                code="VALIDATION_ERROR",
                request_id=request_id,
                message="services must contain only asr or tts.",
                retryable=False,
                fallback=None,
                status_code=HTTPStatus.BAD_REQUEST,
            )
        if len(set(selected)) != len(selected):
            raise _make_error(
                code="VALIDATION_ERROR",
                request_id=request_id,
                message="services must not contain duplicates.",
                retryable=False,
                fallback=None,
                status_code=HTTPStatus.BAD_REQUEST,
            )

        workers = {"asr": self.asr_worker, "tts": self.tts_worker}

        def job(token: CancellationToken) -> None:
            for service in selected:
                token.checkpoint()
                with self.cpu_inference_semaphore:
                    token.checkpoint()
                    workers[service].warmup(token)

        try:
            future = self._executor.submit(
                request_id=request_id,
                kind="warmup",
                function=job,
            )
        except QueueFullError as exc:
            raise _make_error(
                code="ASR_UNAVAILABLE" if "asr" in selected else "TTS_UNAVAILABLE",
                request_id=request_id,
                message="Speech worker queue is full; try again shortly.",
                retryable=True,
                fallback="retry_later",
                status_code=HTTPStatus.SERVICE_UNAVAILABLE,
                details={"queue_depth": self.queue_depth},
            ) from exc

        try:
            future.result(timeout=self.timeout_s)
        except FutureTimeoutError as exc:
            self._executor.cancel(request_id)
            raise _make_error(
                code="ASR_UNAVAILABLE" if "asr" in selected else "TTS_UNAVAILABLE",
                request_id=request_id,
                message="Speech worker warmup timed out.",
                retryable=True,
                fallback="retry_later",
                status_code=HTTPStatus.SERVICE_UNAVAILABLE,
            ) from exc
        except WorkerCancelled as exc:
            raise _make_error(
                code="ASR_UNAVAILABLE" if "asr" in selected else "TTS_UNAVAILABLE",
                request_id=request_id,
                message="Speech worker warmup was cancelled.",
                retryable=True,
                fallback="retry_later",
                status_code=HTTPStatus.SERVICE_UNAVAILABLE,
            ) from exc
        except Exception as exc:
            # The public envelope does not expose exception text, which could
            # contain model paths or user data supplied by a real worker.
            for service in selected:
                self._record_failure(
                    service=service,
                    request_id=request_id,
                    code="ASR_FAILED" if service == "asr" else "TTS_FAILED",
                )
            raise _make_error(
                code="ASR_UNAVAILABLE" if "asr" in selected else "TTS_UNAVAILABLE",
                request_id=request_id,
                message="Speech worker warmup failed.",
                retryable=True,
                fallback="retry_later",
                status_code=HTTPStatus.SERVICE_UNAVAILABLE,
            ) from exc
        else:
            for service in selected:
                self._record_success(service)
        return {
            "schema_version": SCHEMA_VERSION,
            "request_id": request_id,
            "status": "ready",
        }

    def cancel(self, *, request_id: str) -> dict[str, Any]:
        with self._lifecycle_lock:
            self._executor.cancel_all()
            with self._state_lock:
                self._active_request_id = None
                self._active_kind = None
                self._set_state_locked(HalfDuplexState.IDLE, force=True)
        return {
            "schema_version": SCHEMA_VERSION,
            "request_id": request_id,
            "status": "cancelled",
        }

    def transcribe(
        self,
        *,
        audio: bytes,
        language: str,
        device_preference: str,
        request_id: str,
    ) -> dict[str, Any]:
        if language not in ALLOWED_LANGUAGES:
            raise _make_error(
                code="VALIDATION_ERROR",
                request_id=request_id,
                message="language must be nan-TW or zh-TW.",
                retryable=False,
                fallback="keyboard_input",
                status_code=HTTPStatus.BAD_REQUEST,
            )
        if device_preference not in ALLOWED_DEVICE_PREFERENCES:
            raise _make_error(
                code="VALIDATION_ERROR",
                request_id=request_id,
                message="device_preference must be npu, cpu, or auto.",
                retryable=False,
                fallback="keyboard_input",
                status_code=HTTPStatus.BAD_REQUEST,
            )
        if not audio:
            raise _make_error(
                code="VALIDATION_ERROR",
                request_id=request_id,
                message="file must contain audio bytes.",
                retryable=False,
                fallback="keyboard_input",
                status_code=HTTPStatus.BAD_REQUEST,
            )
        if len(audio) > MAX_AUDIO_BYTES:
            raise _make_error(
                code="VALIDATION_ERROR",
                request_id=request_id,
                message="audio file exceeds the local size limit.",
                retryable=False,
                fallback="keyboard_input",
                status_code=HTTPStatus.BAD_REQUEST,
            )

        # The mock and the future real worker only need metadata at this
        # boundary.  Drop the bytes before creating the queued closure.
        audio_size = len(audio)
        del audio
        started_at = time.monotonic()
        device = "cpu"  # NPU is opt-in later; CPU is the reliable fallback.

        def job(token: CancellationToken) -> str:
            with self.cpu_inference_semaphore:
                token.checkpoint()
                return self.asr_worker.transcribe(
                    audio_size=audio_size,
                    language=language,
                    device=device,
                    token=token,
                )

        future = self._submit_operation(
            kind="asr",
            request_id=request_id,
            function=job,
        )
        try:
            text = future.result(timeout=self.timeout_s)
        except FutureTimeoutError as exc:
            self._abort_operation(request_id)
            raise self._operation_error(
                kind="asr",
                request_id=request_id,
                message="ASR worker timed out.",
            ) from exc
        except WorkerCancelled as exc:
            self._finish_operation(request_id, kind="asr", success=False)
            raise self._operation_error(
                kind="asr",
                request_id=request_id,
                message="ASR work was cancelled.",
            ) from exc
        except Exception as exc:
            self._finish_operation(request_id, kind="asr", success=False)
            self._record_failure(service="asr", request_id=request_id, code="ASR_FAILED")
            raise self._operation_error(
                kind="asr",
                request_id=request_id,
                message="ASR worker failed.",
            ) from exc
        else:
            self._finish_operation(request_id, kind="asr", success=True)
            self._record_success("asr")
            return {
                "schema_version": SCHEMA_VERSION,
                "request_id": request_id,
                "text": text,
                "language": language,
                "device": device,
                "latency_ms": max(0, round((time.monotonic() - started_at) * 1000)),
            }

    def synthesize(
        self,
        *,
        utterance: dict[str, Any],
        format_name: str,
        request_id: str,
    ) -> bytes:
        _validate_utterance(utterance, request_id=request_id)
        if format_name != "wav":
            raise _make_error(
                code="VALIDATION_ERROR",
                request_id=request_id,
                message="format must be wav.",
                retryable=False,
                fallback="prerecorded_audio",
                status_code=HTTPStatus.BAD_REQUEST,
            )

        def job(token: CancellationToken) -> bytes:
            with self.cpu_inference_semaphore:
                token.checkpoint()
                return self.tts_worker.synthesize(utterance=utterance, token=token)

        future = self._submit_operation(
            kind="tts",
            request_id=request_id,
            function=job,
        )
        try:
            audio = future.result(timeout=self.timeout_s)
        except FutureTimeoutError as exc:
            self._abort_operation(request_id)
            raise self._operation_error(
                kind="tts",
                request_id=request_id,
                message="TTS worker timed out.",
            ) from exc
        except WorkerCancelled as exc:
            self._finish_operation(request_id, kind="tts", success=False)
            raise self._operation_error(
                kind="tts",
                request_id=request_id,
                message="TTS work was cancelled.",
            ) from exc
        except Exception as exc:
            self._finish_operation(request_id, kind="tts", success=False)
            self._record_failure(service="tts", request_id=request_id, code="TTS_FAILED")
            raise self._operation_error(
                kind="tts",
                request_id=request_id,
                message="TTS worker failed.",
            ) from exc
        else:
            self._finish_operation(request_id, kind="tts", success=True)
            self._record_success("tts")
            return audio

    def close(self) -> None:
        self._executor.shutdown()

    def _submit_operation(
        self,
        *,
        kind: str,
        request_id: str,
        function: Callable[[CancellationToken], Any],
    ) -> Future[Any]:
        with self._lifecycle_lock:
            self._begin_operation(kind=kind, request_id=request_id)
            try:
                return self._executor.submit(
                    request_id=request_id,
                    kind=kind,
                    function=function,
                )
            except QueueFullError as exc:
                self._finish_operation(request_id, kind=kind, success=False)
                code = "ASR_UNAVAILABLE" if kind == "asr" else "TTS_UNAVAILABLE"
                raise _make_error(
                    code=code,
                    request_id=request_id,
                    message="Speech worker queue is full; try again shortly.",
                    retryable=True,
                    fallback="retry_later" if kind == "asr" else "prerecorded_audio",
                    status_code=HTTPStatus.SERVICE_UNAVAILABLE,
                    details={"queue_depth": self.queue_depth},
                ) from exc

    def _begin_operation(self, *, kind: str, request_id: str) -> None:
        with self._state_lock:
            if self._active_kind == kind and self._active_request_id:
                code = "ASR_FAILED" if kind == "asr" else "TTS_FAILED"
                raise _make_error(
                    code=code,
                    request_id=request_id,
                    message="The same speech operation is already active.",
                    retryable=True,
                    fallback="keyboard_input" if kind == "asr" else "prerecorded_audio",
                    status_code=HTTPStatus.SERVICE_UNAVAILABLE,
                )
            if self._active_request_id:
                self._executor.cancel(self._active_request_id)
                self._set_state_locked(HalfDuplexState.IDLE, force=True)
            self._active_request_id = request_id
            self._active_kind = kind
            if kind == "asr":
                # The browser starts listening before it uploads.  The gateway
                # records both phases even though upload is already complete.
                self._set_state_locked(HalfDuplexState.LISTENING, force=True)
                self._set_state_locked(HalfDuplexState.TRANSCRIBING)
            else:
                # This transition releases any browser microphone ownership in
                # the paired frontend controller before playback begins.
                self._set_state_locked(HalfDuplexState.SPEAKING, force=True)

    def _abort_operation(self, request_id: str) -> None:
        with self._lifecycle_lock:
            self._executor.cancel(request_id)
            self._finish_operation(request_id, kind=None, success=False)

    def _finish_operation(
        self,
        request_id: str,
        *,
        kind: str | None,
        success: bool,
    ) -> None:
        with self._lifecycle_lock:
            with self._state_lock:
                if self._active_request_id != request_id:
                    return
                current_kind = self._active_kind
                self._active_request_id = None
                self._active_kind = None
                if not success:
                    self._set_state_locked(HalfDuplexState.IDLE, force=True)
                elif (kind or current_kind) == "asr":
                    self._set_state_locked(HalfDuplexState.EVALUATING)
                else:
                    self._set_state_locked(HalfDuplexState.IDLE, force=True)

    def _set_state_locked(self, state: HalfDuplexState, *, force: bool = False) -> None:
        if state == self._state:
            return
        if not force and state not in LEGAL_TRANSITIONS[self._state]:
            raise RuntimeError(f"illegal half-duplex transition: {self._state}->{state}")
        self._state = state
        self._state_history.append(state)

    def _operation_error(
        self,
        *,
        kind: str,
        request_id: str,
        message: str,
    ) -> GatewayError:
        if kind == "asr":
            return _make_error(
                code="ASR_FAILED",
                request_id=request_id,
                message=message,
                retryable=True,
                fallback="keyboard_input",
                status_code=HTTPStatus.SERVICE_UNAVAILABLE,
            )
        return _make_error(
            code="TTS_FAILED",
            request_id=request_id,
            message=message,
            retryable=True,
            fallback="prerecorded_audio",
            status_code=HTTPStatus.SERVICE_UNAVAILABLE,
        )

    def _record_failure(self, *, service: str, request_id: str, code: str) -> None:
        with self._health_lock:
            worker = self._health[service]
            worker.status = "degraded"
            worker.last_error = {
                "schema_version": SCHEMA_VERSION,
                "code": code,
                "message": f"{service.upper()} worker failed.",
                "retryable": True,
                "fallback": "keyboard_input" if service == "asr" else "prerecorded_audio",
                "request_id": request_id,
            }

    def _record_success(self, service: str) -> None:
        with self._health_lock:
            worker = self._health[service]
            worker.status = "ready"
            worker.last_error = None


def _validate_utterance(utterance: Any, *, request_id: str) -> None:
    if not isinstance(utterance, dict):
        raise _make_error(
            code="VALIDATION_ERROR",
            request_id=request_id,
            message="utterance must be an object.",
            retryable=False,
            fallback="prerecorded_audio",
            status_code=HTTPStatus.BAD_REQUEST,
        )
    required = {"schema_version", "id", "segments", "tts_provider", "audio_url", "audio_cache_key"}
    if set(utterance) != required or utterance.get("schema_version") != SCHEMA_VERSION:
        raise _make_error(
            code="VALIDATION_ERROR",
            request_id=request_id,
            message="utterance does not match contract v0.1.0.",
            retryable=False,
            fallback="prerecorded_audio",
            status_code=HTTPStatus.BAD_REQUEST,
        )
    if not isinstance(utterance.get("id"), str) or not re.fullmatch(
        r"utt_[A-Za-z0-9_-]+",
        utterance["id"],
    ):
        raise _make_error(
            code="VALIDATION_ERROR",
            request_id=request_id,
            message="utterance.id is invalid.",
            retryable=False,
            fallback="prerecorded_audio",
            status_code=HTTPStatus.BAD_REQUEST,
        )
    provider = utterance["tts_provider"]
    if provider is not None and (
        not isinstance(provider, str)
        or provider not in {"mms-tts-nan", "windows", "prerecorded"}
    ):
        raise _make_error(
            code="VALIDATION_ERROR",
            request_id=request_id,
            message="utterance.tts_provider is invalid.",
            retryable=False,
            fallback="prerecorded_audio",
            status_code=HTTPStatus.BAD_REQUEST,
        )
    for field in ("audio_url", "audio_cache_key"):
        if utterance[field] is not None and not isinstance(utterance[field], str):
            raise _make_error(
                code="VALIDATION_ERROR",
                request_id=request_id,
                message=f"utterance.{field} is invalid.",
                retryable=False,
                fallback="prerecorded_audio",
                status_code=HTTPStatus.BAD_REQUEST,
            )
    segments = utterance.get("segments")
    if not isinstance(segments, list) or not segments:
        raise _make_error(
            code="VALIDATION_ERROR",
            request_id=request_id,
            message="utterance.segments must not be empty.",
            retryable=False,
            fallback="prerecorded_audio",
            status_code=HTTPStatus.BAD_REQUEST,
        )
    segment_required = {
        "lang",
        "hanji",
        "tailo_citation",
        "poj_citation",
        "zh_gloss",
        "source",
        "pronunciation_status",
    }
    for segment in segments:
        if not isinstance(segment, dict) or set(segment) != segment_required:
            raise _make_error(
                code="VALIDATION_ERROR",
                request_id=request_id,
                message="utterance segment does not match contract v0.1.0.",
                retryable=False,
                fallback="prerecorded_audio",
                status_code=HTTPStatus.BAD_REQUEST,
            )
        if (
            not isinstance(segment["lang"], str)
            or segment["lang"] not in ALLOWED_LANGUAGES
            or not isinstance(segment["hanji"], str)
            or not segment["hanji"]
        ):
            raise _make_error(
                code="VALIDATION_ERROR",
                request_id=request_id,
                message="utterance segment language or text is invalid.",
                retryable=False,
                fallback="prerecorded_audio",
                status_code=HTTPStatus.BAD_REQUEST,
            )
        if not isinstance(segment["source"], str) or segment["source"] not in {
            "textbook",
            "dictionary",
            "generated",
        }:
            raise _make_error(
                code="VALIDATION_ERROR",
                request_id=request_id,
                message="utterance segment source is invalid.",
                retryable=False,
                fallback="prerecorded_audio",
                status_code=HTTPStatus.BAD_REQUEST,
            )
        if (
            not isinstance(segment["pronunciation_status"], str)
            or segment["pronunciation_status"] not in {"verified", "converted", "needs_review"}
        ):
            raise _make_error(
                code="VALIDATION_ERROR",
                request_id=request_id,
                message="utterance segment pronunciation status is invalid.",
                retryable=False,
                fallback="prerecorded_audio",
                status_code=HTTPStatus.BAD_REQUEST,
            )
        for field in ("tailo_citation", "poj_citation", "zh_gloss"):
            if segment[field] is not None and not isinstance(segment[field], str):
                raise _make_error(
                    code="VALIDATION_ERROR",
                    request_id=request_id,
                    message=f"utterance segment {field} is invalid.",
                    retryable=False,
                    fallback="prerecorded_audio",
                    status_code=HTTPStatus.BAD_REQUEST,
                )


class SpeechGatewayRequestHandler(BaseHTTPRequestHandler):
    """HTTP adapter for ``SpeechGatewayService``."""

    gateway: SpeechGatewayService
    allowed_origins = ALLOWED_ORIGINS
    protocol_version = "HTTP/1.1"

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A002
        # Do not emit request paths, filenames, or worker exception text into
        # logs.  The gateway is intentionally quiet by default.
        del format, args

    def do_OPTIONS(self) -> None:  # noqa: N802
        request_id, request_error = self._request_id()
        if request_error:
            self._send_error(request_error)
            return
        if not self._origin_allowed():
            self._send_error(
                _make_error(
                    code="VALIDATION_ERROR",
                    request_id=request_id,
                    message="Origin is not allowed for the localhost gateway.",
                    retryable=False,
                    fallback=None,
                    status_code=HTTPStatus.FORBIDDEN,
                )
            )
            return
        self.send_response(HTTPStatus.NO_CONTENT)
        self._write_common_headers(request_id=request_id)
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, X-Request-ID")
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_GET(self) -> None:  # noqa: N802
        request_id, request_error = self._request_id()
        if request_error:
            self._send_error(request_error)
            return
        if not self._origin_allowed():
            self._send_error(self._origin_error(request_id))
            return
        if self.path != "/local/health":
            self._send_error(
                _make_error(
                    code="VALIDATION_ERROR",
                    request_id=request_id,
                    message="Unknown Speech Gateway route.",
                    retryable=False,
                    fallback=None,
                    status_code=HTTPStatus.NOT_FOUND,
                )
            )
            return
        self._send_json(
            HTTPStatus.OK,
            self.gateway.health_payload(request_id),
            request_id=request_id,
            include_runtime=True,
        )

    def do_POST(self) -> None:  # noqa: N802
        request_id, request_error = self._request_id()
        if request_error:
            self._send_error(request_error)
            return
        if not self._origin_allowed():
            self._send_error(self._origin_error(request_id))
            return
        try:
            if self.path == "/local/warmup":
                payload = self._read_json(allow_empty=True, request_id=request_id)
                if set(payload) - {"services"}:
                    raise _make_error(
                        code="VALIDATION_ERROR",
                        request_id=request_id,
                        message="warmup accepts only the services field.",
                        retryable=False,
                        fallback=None,
                        status_code=HTTPStatus.BAD_REQUEST,
                    )
                services = payload.get("services")
                if services is not None and not isinstance(services, list):
                    raise _make_error(
                        code="VALIDATION_ERROR",
                        request_id=request_id,
                        message="services must be an array.",
                        retryable=False,
                        fallback=None,
                        status_code=HTTPStatus.BAD_REQUEST,
                    )
                response = self.gateway.warmup(services=services, request_id=request_id)
                self._send_json(HTTPStatus.OK, response, request_id=request_id)
                return
            if self.path == "/local/cancel":
                self._discard_body()
                response = self.gateway.cancel(request_id=request_id)
                self._send_json(HTTPStatus.OK, response, request_id=request_id)
                return
            if self.path == "/v1/audio/transcriptions":
                fields = self._read_multipart(request_id=request_id)
                if set(fields) - {"file", "language", "device_preference"}:
                    raise _make_error(
                        code="VALIDATION_ERROR",
                        request_id=request_id,
                        message="transcriptions contains an unsupported field.",
                        retryable=False,
                        fallback="keyboard_input",
                        status_code=HTTPStatus.BAD_REQUEST,
                    )
                response = self.gateway.transcribe(
                    audio=fields["file"],
                    language=fields["language"],
                    device_preference=fields.get("device_preference", "auto"),
                    request_id=request_id,
                )
                self._send_json(HTTPStatus.OK, response, request_id=request_id)
                return
            if self.path == "/v1/audio/speech":
                payload = self._read_json(request_id=request_id)
                if set(payload) != {"schema_version", "utterance", "format"}:
                    raise _make_error(
                        code="VALIDATION_ERROR",
                        request_id=request_id,
                        message="speech body does not match contract v0.1.0.",
                        retryable=False,
                        fallback="prerecorded_audio",
                        status_code=HTTPStatus.BAD_REQUEST,
                    )
                utterance = payload.get("utterance")
                format_name = payload.get("format")
                if payload.get("schema_version") != SCHEMA_VERSION:
                    raise _make_error(
                        code="VALIDATION_ERROR",
                        request_id=request_id,
                        message="schema_version must be 0.1.0.",
                        retryable=False,
                        fallback="prerecorded_audio",
                        status_code=HTTPStatus.BAD_REQUEST,
                    )
                audio = self.gateway.synthesize(
                    utterance=utterance,
                    format_name=format_name,
                    request_id=request_id,
                )
                self._send_audio(audio, request_id=request_id)
                return
            raise _make_error(
                code="VALIDATION_ERROR",
                request_id=request_id,
                message="Unknown Speech Gateway route.",
                retryable=False,
                fallback=None,
                status_code=HTTPStatus.NOT_FOUND,
            )
        except GatewayError as exc:
            self._send_error(exc)
        except (ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
            del exc
            self._send_error(
                _make_error(
                    code="VALIDATION_ERROR",
                    request_id=request_id,
                    message="Request body does not match the Speech Gateway contract.",
                    retryable=False,
                    fallback=None,
                    status_code=HTTPStatus.BAD_REQUEST,
                )
            )
        except Exception as exc:  # pragma: no cover - defensive HTTP boundary
            del exc
            self._send_error(
                _make_error(
                    code="INTERNAL_ERROR",
                    request_id=request_id,
                    message="Speech Gateway request failed.",
                    retryable=True,
                    fallback="retry_later",
                    status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
                )
            )

    def _request_id(self) -> tuple[str, GatewayError | None]:
        candidate = self.headers.get("X-Request-ID")
        generated = str(uuid4())
        if not candidate:
            return generated, None
        try:
            parsed = UUID(candidate)
        except (ValueError, AttributeError):
            return generated, _make_error(
                code="VALIDATION_ERROR",
                request_id=generated,
                message="X-Request-ID must be a UUID.",
                retryable=False,
                fallback=None,
                status_code=HTTPStatus.BAD_REQUEST,
            )
        return str(parsed), None

    def _origin_allowed(self) -> bool:
        origin = self.headers.get("Origin")
        return not origin or origin in self.allowed_origins

    def _origin_error(self, request_id: str) -> GatewayError:
        return _make_error(
            code="VALIDATION_ERROR",
            request_id=request_id,
            message="Origin is not allowed for the localhost gateway.",
            retryable=False,
            fallback=None,
            status_code=HTTPStatus.FORBIDDEN,
        )

    def _read_json(self, *, allow_empty: bool = False, request_id: str) -> dict[str, Any]:
        body = self._read_body(max_bytes=MAX_JSON_BYTES, request_id=request_id)
        if not body and allow_empty:
            return {}
        parsed = json.loads(body.decode("utf-8"))
        if not isinstance(parsed, dict):
            raise ValueError("JSON object required")
        return parsed

    def _read_multipart(self, *, request_id: str) -> dict[str, Any]:
        content_type = self.headers.get("Content-Type", "")
        if not content_type.lower().startswith("multipart/form-data"):
            raise _make_error(
                code="VALIDATION_ERROR",
                request_id=request_id,
                message="transcriptions requires multipart/form-data.",
                retryable=False,
                fallback="keyboard_input",
                status_code=HTTPStatus.BAD_REQUEST,
            )
        body = self._read_body(
            max_bytes=MAX_AUDIO_BYTES + 1024 * 1024,
            request_id=request_id,
        )
        envelope = (
            f"Content-Type: {content_type}\r\nMIME-Version: 1.0\r\n\r\n".encode("utf-8")
            + body
        )
        message = BytesParser(policy=policy.default).parsebytes(envelope)
        fields: dict[str, Any] = {}
        for part in message.iter_parts():
            name = part.get_param("name", header="content-disposition")
            if not name:
                continue
            data = part.get_payload(decode=True) or b""
            if name == "file":
                fields[name] = data
            else:
                fields[name] = data.decode("utf-8").strip()
        if "file" not in fields or "language" not in fields:
            raise _make_error(
                code="VALIDATION_ERROR",
                request_id=request_id,
                message="transcriptions requires file and language fields.",
                retryable=False,
                fallback="keyboard_input",
                status_code=HTTPStatus.BAD_REQUEST,
            )
        return fields

    def _read_body(self, *, max_bytes: int, request_id: str) -> bytes:
        raw_length = self.headers.get("Content-Length")
        if raw_length is None:
            raise ValueError("Content-Length required")
        try:
            length = int(raw_length)
        except ValueError as exc:
            raise ValueError("invalid content length") from exc
        if length < 0 or length > max_bytes:
            raise _make_error(
                code="VALIDATION_ERROR",
                request_id=request_id,
                message="request body exceeds the local size limit.",
                retryable=False,
                fallback="keyboard_input",
                status_code=HTTPStatus.REQUEST_ENTITY_TOO_LARGE,
            )
        body = self.rfile.read(length)
        if len(body) != length:
            raise ValueError("incomplete body")
        return body

    def _discard_body(self) -> None:
        raw_length = self.headers.get("Content-Length")
        if not raw_length:
            return
        try:
            length = int(raw_length)
        except ValueError:
            return
        if 0 < length <= MAX_JSON_BYTES:
            self.rfile.read(length)

    def _write_common_headers(self, *, request_id: str) -> None:
        self.send_header("X-Request-ID", request_id)
        origin = self.headers.get("Origin")
        if origin and origin in self.allowed_origins:
            self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Vary", "Origin")

    def _send_json(
        self,
        status: int,
        payload: Mapping[str, Any],
        *,
        request_id: str,
        include_runtime: bool = False,
    ) -> None:
        body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        self.send_response(status)
        self._write_common_headers(request_id=request_id)
        if include_runtime:
            runtime = json.dumps(
                self.gateway.runtime_diagnostics(),
                ensure_ascii=False,
                separators=(",", ":"),
            )
            self.send_header("X-Speech-Runtime", runtime)
            if self.headers.get("Origin") in self.allowed_origins:
                self.send_header(
                    "Access-Control-Expose-Headers",
                    "X-Request-ID, X-Speech-Runtime",
                )
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_audio(self, body: bytes, *, request_id: str) -> None:
        self.send_response(HTTPStatus.OK)
        self._write_common_headers(request_id=request_id)
        self.send_header("Content-Type", "audio/wav")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_error(self, error: GatewayError) -> None:
        self._send_json(error.status_code, error.payload(), request_id=error.request_id)


def build_server(
    service: SpeechGatewayService,
    *,
    host: str = DEFAULT_HOST,
    port: int = DEFAULT_PORT,
) -> ThreadingHTTPServer:
    """Build an injectable server; port 0 is useful for integration tests."""

    class _Handler(SpeechGatewayRequestHandler):
        gateway = service

    return ThreadingHTTPServer((host, port), _Handler)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the localhost Speech Gateway")
    parser.add_argument("--host", default=DEFAULT_HOST)
    parser.add_argument("--port", default=DEFAULT_PORT, type=int)
    parser.add_argument("--timeout", default=DEFAULT_TIMEOUT_S, type=float)
    args = parser.parse_args(argv)
    if args.host not in {"127.0.0.1", "localhost", "::1"}:
        parser.error("Speech Gateway must bind to localhost")
    service = SpeechGatewayService(timeout_s=args.timeout)
    server = build_server(service, host=args.host, port=args.port)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        return 0
    finally:
        server.shutdown()
        server.server_close()
        service.close()
    return 0


if __name__ == "__main__":  # pragma: no cover - exercised by the run command
    raise SystemExit(main())
