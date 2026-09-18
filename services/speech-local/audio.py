"""In-memory audio decoding and CPU-ASR preprocessing.

The Speech Gateway owns the request bytes and hands them to the ASR worker
only for the duration of one job.  This module deliberately has no file I/O:
it decodes common browser audio in memory, converts it to the model's
16-kHz/mono float32 representation, and optionally trims leading/trailing
silence with a small deterministic energy VAD.

The optional ``faster-whisper`` decoder is used when it is installed because
PyAV can decode browser formats such as WebM/Opus.  A standard-library WAV
decoder remains available for tests and minimal CPU installations.
"""

from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO
import math
from typing import Any
import wave


TARGET_SAMPLE_RATE = 16_000
DEFAULT_MIN_DURATION_MS = 120
DEFAULT_MAX_DURATION_S = 60.0
DEFAULT_VAD_FRAME_MS = 30
DEFAULT_VAD_PADDING_MS = 90
DEFAULT_VAD_MIN_SPEECH_MS = 60
DEFAULT_VAD_THRESHOLD_DB = -45.0
MAX_WAVE_CHANNELS = 8


class AudioPreprocessError(ValueError):
    """Safe, user-actionable audio input failure.

    ``reason`` is a stable diagnostic key.  It never contains a path, audio
    bytes, transcript, or exception text from a decoder.
    """

    def __init__(self, reason: str, message: str) -> None:
        super().__init__(message)
        self.reason = reason
        self.safe_message = message


@dataclass(frozen=True)
class PreparedAudio:
    """Canonical in-memory waveform and non-sensitive preprocessing metrics."""

    samples: Any
    sample_rate: int
    input_duration_s: float
    output_duration_s: float
    input_sample_count: int
    output_sample_count: int
    peak: float
    rms: float
    normalization_gain: float
    vad_enabled: bool
    speech_detected: bool


def prepare_audio(
    audio: bytes,
    *,
    target_sample_rate: int = TARGET_SAMPLE_RATE,
    vad_enabled: bool = True,
    min_duration_ms: int = DEFAULT_MIN_DURATION_MS,
    max_duration_s: float = DEFAULT_MAX_DURATION_S,
) -> PreparedAudio:
    """Decode and normalize one audio request without touching disk.

    The returned samples are contiguous NumPy ``float32`` values in the range
    ``[-1, 1]``.  ``faster-whisper`` accepts this representation directly.
    ``AudioPreprocessError`` is raised for malformed, silent, or too-short
    input so the gateway can return a clear keyboard-input fallback.
    """

    if not isinstance(audio, (bytes, bytearray, memoryview)) or not audio:
        raise AudioPreprocessError("empty_audio", "Audio input is empty.")
    if target_sample_rate <= 0:
        raise ValueError("target_sample_rate must be positive")
    if min_duration_ms < 0:
        raise ValueError("min_duration_ms must not be negative")
    if max_duration_s <= 0:
        raise ValueError("max_duration_s must be positive")

    np = _require_numpy()
    raw = bytes(audio)
    samples, source_rate = _decode_audio(raw, target_sample_rate=target_sample_rate)
    if source_rate <= 0 or samples.size == 0:
        raise AudioPreprocessError("empty_audio", "Audio contains no samples.")

    samples = np.asarray(samples, dtype=np.float32).reshape(-1)
    samples = _finite_samples(samples, np)
    input_sample_count = int(samples.size)
    input_duration_s = input_sample_count / float(target_sample_rate)
    if input_duration_s > max_duration_s:
        raise AudioPreprocessError(
            "too_long",
            f"Audio is longer than the {max_duration_s:g}-second local limit.",
        )

    # Remove a small DC offset before estimating speech energy.  Do not expose
    # the samples or any content-derived text in diagnostics.
    samples = samples - np.float32(samples.mean())
    peak_before = float(np.max(np.abs(samples))) if samples.size else 0.0
    if peak_before < 1e-5:
        raise AudioPreprocessError("no_speech", "No speech activity was detected.")

    speech_detected = True
    if vad_enabled:
        samples, speech_detected = _trim_silence(
            samples,
            sample_rate=target_sample_rate,
            np=np,
        )
        if not speech_detected or samples.size == 0:
            raise AudioPreprocessError("no_speech", "No speech activity was detected.")

    output_duration_s = int(samples.size) / float(target_sample_rate)
    if output_duration_s * 1000.0 < min_duration_ms:
        raise AudioPreprocessError(
            "too_short",
            f"Audio is shorter than the {min_duration_ms}-millisecond minimum.",
        )

    normalized, gain = _normalize_volume(samples, np=np)
    peak = float(np.max(np.abs(normalized))) if normalized.size else 0.0
    rms = float(np.sqrt(np.mean(np.square(normalized)))) if normalized.size else 0.0
    return PreparedAudio(
        samples=np.ascontiguousarray(normalized, dtype=np.float32),
        sample_rate=target_sample_rate,
        input_duration_s=input_duration_s,
        output_duration_s=output_duration_s,
        input_sample_count=input_sample_count,
        output_sample_count=int(normalized.size),
        peak=peak,
        rms=rms,
        normalization_gain=gain,
        vad_enabled=vad_enabled,
        speech_detected=speech_detected,
    )


def _require_numpy() -> Any:
    try:
        import numpy as np
    except ImportError as exc:  # pragma: no cover - depends on environment
        raise AudioPreprocessError(
            "runtime_missing",
            "CPU ASR requires the pinned NumPy runtime.",
        ) from exc
    return np


def _decode_audio(audio: bytes, *, target_sample_rate: int) -> tuple[Any, int]:
    """Decode browser formats with PyAV, then fall back to PCM WAV."""

    np = _require_numpy()
    try:
        from faster_whisper.audio import decode_audio
    except ImportError:
        decode_audio = None

    if decode_audio is not None:
        try:
            decoded = decode_audio(
                BytesIO(audio),
                sampling_rate=target_sample_rate,
            )
            array = np.asarray(decoded, dtype=np.float32).reshape(-1)
            if array.size:
                return array, target_sample_rate
        except Exception:
            # A malformed WebM/Opus payload should still get the deterministic
            # WAV validation below.  Decoder details are never returned.
            pass

    try:
        return _decode_pcm_wave(audio, np=np, target_sample_rate=target_sample_rate)
    except AudioPreprocessError:
        raise
    except Exception as exc:
        raise AudioPreprocessError(
            "unsupported_audio",
            "Audio must be a decodable PCM WAV or browser audio recording.",
        ) from exc


def _decode_pcm_wave(audio: bytes, *, np: Any, target_sample_rate: int) -> tuple[Any, int]:
    try:
        wav_file = wave.open(BytesIO(audio), "rb")
    except (EOFError, wave.Error, OSError) as exc:
        raise AudioPreprocessError(
            "unsupported_audio",
            "Audio must be a decodable PCM WAV or browser audio recording.",
        ) from exc

    with wav_file:
        channels = wav_file.getnchannels()
        sample_width = wav_file.getsampwidth()
        source_rate = wav_file.getframerate()
        frame_count = wav_file.getnframes()
        compression = wav_file.getcomptype()
        if channels < 1 or channels > MAX_WAVE_CHANNELS:
            raise AudioPreprocessError("unsupported_audio", "Audio channel count is unsupported.")
        if sample_width not in {1, 2, 3, 4} or compression != "NONE":
            raise AudioPreprocessError("unsupported_audio", "Audio must use uncompressed PCM.")
        if source_rate <= 0 or frame_count <= 0:
            raise AudioPreprocessError("empty_audio", "Audio contains no samples.")
        raw = wav_file.readframes(frame_count)

    expected_bytes = frame_count * channels * sample_width
    if len(raw) != expected_bytes:
        raise AudioPreprocessError("unsupported_audio", "Audio data is incomplete.")
    values = _pcm_to_float(raw, sample_width=sample_width, np=np)
    if channels > 1:
        values = values.reshape(-1, channels).mean(axis=1)
    values = values.astype(np.float32, copy=False)
    if source_rate != target_sample_rate:
        values = _resample_linear(values, source_rate, target_sample_rate, np=np)
    return values, target_sample_rate


def _pcm_to_float(raw: bytes, *, sample_width: int, np: Any) -> Any:
    if sample_width == 1:
        return (np.frombuffer(raw, dtype=np.uint8).astype(np.float32) - 128.0) / 128.0
    if sample_width == 2:
        return np.frombuffer(raw, dtype="<i2").astype(np.float32) / 32768.0
    if sample_width == 4:
        return np.frombuffer(raw, dtype="<i4").astype(np.float32) / 2147483648.0

    # NumPy has no native 24-bit PCM dtype; sign-extend little-endian samples.
    packed = np.frombuffer(raw, dtype=np.uint8).reshape(-1, 3)
    values = (
        packed[:, 0].astype(np.int32)
        | (packed[:, 1].astype(np.int32) << 8)
        | (packed[:, 2].astype(np.int32) << 16)
    )
    values = np.where(values & 0x800000, values - 0x1000000, values)
    return values.astype(np.float32) / 8388608.0


def _resample_linear(samples: Any, source_rate: int, target_rate: int, *, np: Any) -> Any:
    if samples.size == 0 or source_rate == target_rate:
        return samples
    target_length = max(1, int(round(samples.size * target_rate / source_rate)))
    source_positions = np.arange(samples.size, dtype=np.float64)
    target_positions = np.linspace(0, samples.size - 1, target_length, dtype=np.float64)
    return np.interp(target_positions, source_positions, samples).astype(np.float32)


def _finite_samples(samples: Any, np: Any) -> Any:
    if not bool(np.isfinite(samples).all()):
        raise AudioPreprocessError("unsupported_audio", "Audio contains invalid sample values.")
    return np.clip(samples, -1.0, 1.0)


def _trim_silence(samples: Any, *, sample_rate: int, np: Any) -> tuple[Any, bool]:
    frame_length = max(1, int(sample_rate * DEFAULT_VAD_FRAME_MS / 1000))
    if samples.size < frame_length:
        return samples, bool(np.max(np.abs(samples)) >= 10 ** (DEFAULT_VAD_THRESHOLD_DB / 20.0))

    frame_count = int(math.ceil(samples.size / frame_length))
    padded = np.pad(samples, (0, frame_count * frame_length - samples.size))
    frames = padded.reshape(frame_count, frame_length)
    energies = np.sqrt(np.mean(np.square(frames), axis=1))
    peak = float(np.max(np.abs(samples)))
    noise_floor = float(np.percentile(energies, 20))
    absolute_floor = 10 ** (DEFAULT_VAD_THRESHOLD_DB / 20.0)
    energy_span = float(np.max(energies) - np.min(energies))
    # A short recording may contain continuous speech (or a synthetic test
    # tone), so percentile-based noise estimation must not classify every
    # frame as silence when the frame energy is intentionally steady.
    threshold = max(absolute_floor, peak * 0.08)
    # Only raise the threshold when there is a clear low-energy floor.  This
    # keeps continuous speech from disappearing while still trimming quiet
    # leading/trailing frames around a normal utterance.
    if energy_span > max(float(np.max(energies)) * 0.15, 1e-6) and noise_floor < threshold * 0.5:
        threshold = max(threshold, noise_floor * 2.0)
    voiced = energies >= threshold
    if not bool(voiced.any()):
        return samples[:0], False

    first = int(np.argmax(voiced)) * frame_length
    last = (int(np.where(voiced)[0][-1]) + 1) * frame_length
    padding = int(sample_rate * DEFAULT_VAD_PADDING_MS / 1000)
    start = max(0, first - padding)
    end = min(samples.size, last + padding)
    trimmed = samples[start:end]
    speech_duration_ms = int(voiced.sum()) * DEFAULT_VAD_FRAME_MS
    return trimmed, speech_duration_ms >= DEFAULT_VAD_MIN_SPEECH_MS


def _normalize_volume(samples: Any, *, np: Any) -> tuple[Any, float]:
    if samples.size == 0:
        return samples, 1.0
    rms = float(np.sqrt(np.mean(np.square(samples))))
    peak = float(np.max(np.abs(samples)))
    if rms < 1e-6 or peak < 1e-6:
        return samples, 1.0
    target_rms = 0.08
    gain = min(4.0, target_rms / rms)
    if peak * gain > 0.98:
        gain = 0.98 / peak
    normalized = np.clip(samples * np.float32(gain), -0.98, 0.98)
    return normalized.astype(np.float32, copy=False), float(gain)
