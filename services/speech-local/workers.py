"""Worker protocols and deterministic workers for the local Speech Gateway.

The gateway owns scheduling and half-duplex coordination.  The mock ASR only
uses request metadata, while the real CPU worker receives one in-memory audio
buffer, converts it to canonical PCM, and releases it after inference.  No
worker writes audio or transcript content to disk.
"""

from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO
import os
from pathlib import Path
import threading
import time
from typing import Any, Protocol
import wave

from audio import AudioPreprocessError, prepare_audio


class WorkerCancelled(RuntimeError):
    """Raised when a worker notices the gateway cancellation token."""


class SpeechWorkerError(RuntimeError):
    """Expected worker failure that should be mapped to a stable API error."""

    def __init__(self, message: str, *, reason: str = "worker_error") -> None:
        super().__init__(message)
        self.safe_message = message[:500]
        self.reason = reason


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
        audio: bytes | None = None,
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
        audio: bytes | None = None,
    ) -> str:
        del audio, audio_size, device
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


BREEZE_ASR_MODEL_ID = "paulpengtw/faster-whisper-Breeze-ASR-26"
# Pinned Hub revision for the CT2 conversion.  Model files stay outside Git;
# this value makes a fresh machine resolve the same artifact every time.
BREEZE_ASR_MODEL_REVISION = "7bf9dadb2f7f2bb418e82b3f074549fda82f7f47"
BREEZE_ASR_COMPUTE_TYPE = "int8"
BREEZE_ASR_DEFAULT_CPU_THREADS = 4


class BreezeASR26CPUWorker:
    """CPU-only Breeze-ASR-26 adapter using faster-whisper/CTranslate2.

    The worker is lazy: importing ``workers`` and starting the mock gateway do
    not load a multi-gigabyte model.  The first explicit warmup or
    transcription loads the pinned CT2 model.  Audio is decoded and prepared
    in memory, and only the resulting float32 waveform is handed to the model.
    """

    device = "cpu"

    def __init__(
        self,
        *,
        model_path: str | None = None,
        model_id: str = BREEZE_ASR_MODEL_ID,
        revision: str = BREEZE_ASR_MODEL_REVISION,
        compute_type: str = BREEZE_ASR_COMPUTE_TYPE,
        cpu_threads: int = BREEZE_ASR_DEFAULT_CPU_THREADS,
        beam_size: int = 5,
        vad_enabled: bool = True,
        min_duration_ms: int = 120,
        max_duration_s: float = 60.0,
        local_files_only: bool = False,
    ) -> None:
        if cpu_threads < 1:
            raise ValueError("cpu_threads must be positive")
        if beam_size < 1:
            raise ValueError("beam_size must be positive")
        if not revision:
            raise ValueError("revision must be pinned")
        if not model_id and not model_path:
            raise ValueError("model_id or model_path is required")
        self.model_path = model_path
        self.model_id = model_id
        self.revision = revision
        self.compute_type = compute_type
        self.cpu_threads = cpu_threads
        self.beam_size = beam_size
        self.vad_enabled = vad_enabled
        self.min_duration_ms = min_duration_ms
        self.max_duration_s = max_duration_s
        self.local_files_only = local_files_only
        self.model_revision = f"breeze-asr-26-ct2-{compute_type}@{revision[:12]}"
        self._model: Any | None = None
        self._load_lock = threading.Lock()
        self._metrics_lock = threading.Lock()
        self._last_metrics: dict[str, Any] | None = None

    @property
    def last_metrics(self) -> dict[str, Any] | None:
        """Return preprocessing-only metrics; never returns audio or text."""

        with self._metrics_lock:
            return dict(self._last_metrics) if self._last_metrics else None

    def warmup(self, token: CancellationToken) -> None:
        token.checkpoint()
        self._ensure_model(token)
        token.checkpoint()

    def transcribe(
        self,
        *,
        audio_size: int,
        language: str,
        device: str,
        token: CancellationToken,
        audio: bytes | None = None,
    ) -> str:
        del audio_size, language
        if device != self.device:
            raise SpeechWorkerError("Breeze CPU worker received an unsupported device.")
        token.checkpoint()
        with self._metrics_lock:
            self._last_metrics = None
        try:
            prepared = prepare_audio(
                audio,
                vad_enabled=self.vad_enabled,
                min_duration_ms=self.min_duration_ms,
                max_duration_s=self.max_duration_s,
            )
        except AudioPreprocessError as exc:
            raise SpeechWorkerError(exc.safe_message, reason=exc.reason) from exc
        with self._metrics_lock:
            self._last_metrics = {
                "input_duration_s": round(prepared.input_duration_s, 3),
                "output_duration_s": round(prepared.output_duration_s, 3),
                "input_sample_count": prepared.input_sample_count,
                "output_sample_count": prepared.output_sample_count,
                "sample_rate": prepared.sample_rate,
                "peak": round(prepared.peak, 6),
                "rms": round(prepared.rms, 6),
                "normalization_gain": round(prepared.normalization_gain, 6),
                "vad_enabled": prepared.vad_enabled,
                "speech_detected": prepared.speech_detected,
            }

        model = self._ensure_model(token)
        token.checkpoint()
        try:
            # Breeze-ASR-26 follows Whisper's ``zh`` decoding path and emits
            # Mandarin Chinese characters even for Taigi input.  Explicit
            # language selection avoids language detection overhead.
            segments, _info = model.transcribe(
                prepared.samples,
                language="zh",
                task="transcribe",
                beam_size=self.beam_size,
                best_of=self.beam_size,
                temperature=0.0,
                condition_on_previous_text=False,
                vad_filter=False,
            )
            parts: list[str] = []
            for segment in segments:
                token.checkpoint()
                text = getattr(segment, "text", "")
                if isinstance(text, str):
                    parts.append(text)
            transcript = "".join(parts).strip()
        except WorkerCancelled:
            raise
        except SpeechWorkerError:
            raise
        except Exception as exc:
            raise SpeechWorkerError("Breeze CPU ASR inference failed.") from exc
        token.checkpoint()
        if not transcript:
            raise SpeechWorkerError("Breeze CPU ASR returned no transcript.")
        return transcript

    def close(self) -> None:
        with self._load_lock:
            self._model = None

    def _ensure_model(self, token: CancellationToken) -> Any:
        with self._load_lock:
            if self._model is not None:
                return self._model
            token.checkpoint()
            try:
                # Fresh Windows installations commonly lack the privilege
                # needed for Hugging Face's cache symlinks.  Force ordinary
                # copies so the pinned model can be cached without requiring
                # Administrator mode or Developer Mode.
                if os.name == "nt":
                    os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS", "1")
                    os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")
                from faster_whisper import WhisperModel
            except ImportError as exc:
                raise SpeechWorkerError(
                    "Breeze CPU ASR runtime is not installed; run the speech setup command."
                ) from exc

            model_ref = self.model_path or self.model_id
            kwargs: dict[str, Any] = {
                "device": "cpu",
                "compute_type": self.compute_type,
                "cpu_threads": self.cpu_threads,
                "num_workers": 1,
                "local_files_only": self.local_files_only,
            }
            if not _is_local_model_path(model_ref):
                kwargs["revision"] = self.revision
            try:
                self._model = WhisperModel(model_ref, **kwargs)
            except Exception as exc:
                raise SpeechWorkerError(
                    "Breeze CPU ASR model could not be loaded."
                ) from exc
            return self._model


def create_asr_worker(
    backend: str = "mock",
    *,
    model_path: str | None = None,
    model_id: str = BREEZE_ASR_MODEL_ID,
    revision: str = BREEZE_ASR_MODEL_REVISION,
    compute_type: str = BREEZE_ASR_COMPUTE_TYPE,
    cpu_threads: int = BREEZE_ASR_DEFAULT_CPU_THREADS,
    beam_size: int = 5,
    vad_enabled: bool = True,
    local_files_only: bool = False,
) -> ASRWorker:
    """Build the explicitly selected gateway backend.

    The default remains ``mock`` so contract tests and development do not
    accidentally download model weights.  Production/demo startup should use
    ``backend="breeze"`` after the pinned runtime and model are installed.
    """

    selected = backend.strip().lower()
    if selected == "mock":
        return MockASRWorker()
    if selected in {"breeze", "breeze-cpu", "cpu"}:
        return BreezeASR26CPUWorker(
            model_path=model_path,
            model_id=model_id,
            revision=revision,
            compute_type=compute_type,
            cpu_threads=cpu_threads,
            beam_size=beam_size,
            vad_enabled=vad_enabled,
            local_files_only=local_files_only,
        )
    raise ValueError("backend must be mock or breeze")


def _is_local_model_path(model_ref: str) -> bool:
    if not model_ref:
        return False
    try:
        return Path(model_ref).expanduser().is_dir()
    except OSError:
        return False


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
