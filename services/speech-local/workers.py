"""Worker protocols and deterministic workers for the local Speech Gateway.

The gateway owns scheduling and half-duplex coordination.  Workers deliberately
receive only metadata for mock ASR; audio bytes are never retained by this
module.  Real ASR/TTS implementations can satisfy the protocols without
changing the HTTP boundary.
"""

from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO
import threading
import time
from typing import Any, Protocol
import wave


class WorkerCancelled(RuntimeError):
    """Raised when a worker notices the gateway cancellation token."""


class SpeechWorkerError(RuntimeError):
    """Expected worker failure that should be mapped to a stable API error."""


class WorkerCrash(RuntimeError):
    """Unexpected worker failure used by integration tests and adapters."""


class CancellationToken:
    """Small cooperative cancellation token shared by one queued job."""

    def __init__(self) -> None:
        self._event = threading.Event()

    @property
    def cancelled(self) -> bool:
        return self._event.is_set()

    def cancel(self) -> None:
        self._event.set()

    def checkpoint(self) -> None:
        if self.cancelled:
            raise WorkerCancelled("cancelled")

    def wait(self, timeout: float) -> bool:
        """Wait for cancellation; return True if cancellation was requested."""

        return self._event.wait(timeout)


class ASRWorker(Protocol):
    """Protocol implemented by CPU/NPU ASR workers."""

    model_revision: str
    device: str

    def warmup(self, token: CancellationToken) -> None: ...

    def transcribe(
        self,
        *,
        audio_size: int,
        language: str,
        device: str,
        token: CancellationToken,
    ) -> str: ...


class TTSWorker(Protocol):
    """Protocol implemented by CPU TTS workers."""

    model_revision: str
    device: str

    def warmup(self, token: CancellationToken) -> None: ...

    def synthesize(
        self,
        *,
        utterance: dict[str, Any],
        token: CancellationToken,
    ) -> bytes: ...


def _interruptible_sleep(delay_s: float, token: CancellationToken) -> None:
    deadline = time.monotonic() + max(delay_s, 0.0)
    while True:
        token.checkpoint()
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return
        token.wait(min(remaining, 0.02))


@dataclass
class WorkerCallStats:
    calls: int = 0
    active: int = 0
    max_active: int = 0


class MockASRWorker:
    """Deterministic ASR worker used until the real Breeze worker is delivered."""

    model_revision = "mock-breeze-asr-v0.1"
    device = "cpu"

    def __init__(
        self,
        *,
        delay_s: float = 0.0,
        transcripts: dict[str, str] | None = None,
    ) -> None:
        self.delay_s = delay_s
        self.transcripts = transcripts or {
            "nan-TW": "這是一段測試語音。",
            "zh-TW": "這是一段測試語音。",
        }
        self.stats = WorkerCallStats()
        self.started = threading.Event()
        self.finished = threading.Event()
        self.fail_next = False
        self.crash_next = False
        self._lock = threading.Lock()

    def warmup(self, token: CancellationToken) -> None:
        token.checkpoint()
        _interruptible_sleep(self.delay_s, token)

    def transcribe(
        self,
        *,
        audio_size: int,
        language: str,
        device: str,
        token: CancellationToken,
    ) -> str:
        del audio_size, device
        with self._lock:
            self.stats.calls += 1
            self.stats.active += 1
            self.stats.max_active = max(self.stats.max_active, self.stats.active)
            fail = self.fail_next
            crash = self.crash_next
            self.fail_next = False
            self.crash_next = False
        self.started.set()
        try:
            token.checkpoint()
            _interruptible_sleep(self.delay_s, token)
            if crash:
                raise WorkerCrash("mock worker crash")
            if fail:
                raise SpeechWorkerError("mock ASR failure")
            return self.transcripts.get(language, self.transcripts["zh-TW"])
        finally:
            with self._lock:
                self.stats.active -= 1
            self.finished.set()


def make_synthetic_wav(*, duration_ms: int = 160, sample_rate: int = 8000) -> bytes:
    """Return a small in-memory PCM WAV fixture; no file is written."""

    frame_count = max(1, int(sample_rate * duration_ms / 1000))
    # Silence is deterministic and avoids putting utterance content in the
    # generated audio.  Real TTS workers replace this implementation.
    frames = b"\x00\x00" * frame_count
    output = BytesIO()
    with wave.open(output, "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(sample_rate)
        wav_file.writeframes(frames)
    return output.getvalue()


class MockTTSWorker:
    """Deterministic CPU TTS worker used until MMS-TTS is wired in."""

    model_revision = "mock-mms-tts-nan-v0.1"
    device = "cpu"

    def __init__(self, *, delay_s: float = 0.0) -> None:
        self.delay_s = delay_s
        self.stats = WorkerCallStats()
        self.started = threading.Event()
        self.finished = threading.Event()
        self.fail_next = False
        self.crash_next = False
        self._lock = threading.Lock()

    def warmup(self, token: CancellationToken) -> None:
        token.checkpoint()
        _interruptible_sleep(self.delay_s, token)

    def synthesize(
        self,
        *,
        utterance: dict[str, Any],
        token: CancellationToken,
    ) -> bytes:
        # The mock only checks that the gateway passed a canonical utterance;
        # it does not retain or log any text from it.
        del utterance
        with self._lock:
            self.stats.calls += 1
            self.stats.active += 1
            self.stats.max_active = max(self.stats.max_active, self.stats.active)
            fail = self.fail_next
            crash = self.crash_next
            self.fail_next = False
            self.crash_next = False
        self.started.set()
        try:
            token.checkpoint()
            _interruptible_sleep(self.delay_s, token)
            if crash:
                raise WorkerCrash("mock worker crash")
            if fail:
                raise SpeechWorkerError("mock TTS failure")
            return make_synthetic_wav()
        finally:
            with self._lock:
                self.stats.active -= 1
            self.finished.set()
