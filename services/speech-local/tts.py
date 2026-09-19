"""MMS-TTS, language routing, and local audio fallback support.

The public Speech Gateway owns scheduling and half-duplex state.  This module
owns only TTS concerns: validating the Agent A pronunciation gate, loading the
pinned CPU MMS checkpoint lazily, caching generated WAV bytes, and routing
Chinese UI speech away from the Min Nan model.

The real model dependencies are imported only when the MMS worker is warmed or
used.  Contract tests therefore remain offline and the default Mock gateway
never downloads model weights.
"""

from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO
import base64
import hashlib
import json
import math
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import threading
import time
from typing import Any, Callable, Iterable, Mapping, Sequence
import unicodedata
import wave
from uuid import uuid4

from workers import CancellationToken, SpeechWorkerError, TTSWorker


SCHEMA_VERSION = "0.1.0"

# These values are intentionally pinned.  The revision is the current Hub
# commit for facebook/mms-tts-nan, not a mutable ``main`` alias at runtime.
MMS_TTS_MODEL_ID = "facebook/mms-tts-nan"
MMS_TTS_MODEL_REVISION = "f28526a6caaf9dc55e030da83008c933f6a1978b"
MMS_TTS_LICENSE = "CC-BY-NC-4.0"
MMS_TTS_FRAMEWORK = "transformers+torch"
MMS_TTS_SAMPLE_RATE = 16_000
MMS_TTS_FORMAT = "wav"
MMS_TTS_DEVICE = "cpu"
MMS_TTS_DEFAULT_SPEED = 1.0
MMS_TTS_DEFAULT_SEED = 555
MMS_TTS_WARMUP_TEXT = "chiah-peng"
MMS_TTS_MAX_TEXT_LENGTH = 512
WINDOWS_SAPI_SAMPLE_RATE = 16_000
WINDOWS_SAPI_MAX_TEXT_LENGTH = 4_096

DEFAULT_CACHE_MAX_BYTES = 256 * 1024 * 1024
DEFAULT_CACHE_MAX_ENTRIES = 500
DEFAULT_CACHE_TTL_SECONDS = 14 * 24 * 60 * 60

# This is the complete vocabulary shipped by the pinned nan checkpoint.  It is
# deliberately explicit: VitsTokenizer can normalize punctuation, but the
# product contract requires an approved POJ citation and must reject unknown
# input before it reaches the model.
MMS_TTS_VOCABULARY = frozenset(
    " '-abcdefghijklmnopqrstuvwxyz"
    "àáâèéêìíîòóôùúûāēīńōūǹḿ"
    "̂̄̍͘"
)


def _default_cache_dir() -> Path:
    configured = os.environ.get("MMS_TTS_CACHE_DIR")
    if configured:
        return Path(configured).expanduser()
    return Path(__file__).resolve().parent / ".runtime" / "audio-cache"


def _default_manifest_path() -> Path:
    configured = os.environ.get("MMS_TTS_FALLBACK_MANIFEST")
    if configured:
        return Path(configured).expanduser()
    return Path(__file__).resolve().parent / "fallback" / "prerecorded_manifest.json"


def normalize_poj_text(text: str) -> str:
    """Normalize a reviewed POJ citation without inventing pronunciation.

    Unicode NFC and whitespace normalization are deterministic formatting
    operations.  Case folding is intentionally not applied: the MMS contract
    requires lower-case, punctuation-free POJ, so upper-case or unsupported
    characters fail closed instead of silently changing a citation.
    """

    if not isinstance(text, str):
        raise SpeechWorkerError(
            "MMS-TTS requires a POJ citation string.",
            reason="missing_poj_citation",
        )
    normalized = unicodedata.normalize("NFC", text).strip()
    normalized = " ".join(normalized.split())
    if not normalized:
        raise SpeechWorkerError(
            "MMS-TTS requires a non-empty POJ citation.",
            reason="missing_poj_citation",
        )
    if len(normalized) > MMS_TTS_MAX_TEXT_LENGTH:
        raise SpeechWorkerError(
            "The POJ citation is too long for local TTS.",
            reason="text_too_long",
        )
    unsupported = sorted({char for char in normalized if char not in MMS_TTS_VOCABULARY})
    if unsupported:
        raise SpeechWorkerError(
            "The POJ citation contains an unsupported MMS character.",
            reason="unsupported_poj_character",
        )
    return normalized


def build_audio_cache_key(
    *,
    provider: str,
    revision: str,
    normalized_text: str,
    speed: float,
) -> str:
    """Build a content-addressed key from the complete synthesis profile."""

    if not provider or not revision:
        raise ValueError("provider and revision are required for an audio key")
    speed_value = float(speed)
    if not math.isfinite(speed_value) or speed_value <= 0:
        raise ValueError("speed must be a positive finite number")
    canonical = json.dumps(
        [provider, revision, normalized_text, f"{speed_value:.6f}"],
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _is_valid_wav(audio: bytes, *, sample_rate: int = MMS_TTS_SAMPLE_RATE) -> bool:
    try:
        with wave.open(BytesIO(audio), "rb") as wav_file:
            return (
                wav_file.getnchannels() == 1
                and wav_file.getsampwidth() == 2
                and wav_file.getframerate() == sample_rate
                and wav_file.getnframes() > 0
                and wav_file.getcomptype() == "NONE"
            )
    except (EOFError, OSError, wave.Error, ValueError):
        return False


class AudioCache:
    """Small bounded on-disk WAV cache.

    Only content-addressed ``*.wav`` files are created.  Writes are atomic,
    stale files are removed on access/prune, and the cache is placed below the
    ignored local runtime directory by default.
    """

    def __init__(
        self,
        root: str | os.PathLike[str] | None = None,
        *,
        max_bytes: int = DEFAULT_CACHE_MAX_BYTES,
        max_entries: int = DEFAULT_CACHE_MAX_ENTRIES,
        ttl_seconds: float = DEFAULT_CACHE_TTL_SECONDS,
    ) -> None:
        if max_bytes <= 0 or max_entries <= 0 or ttl_seconds <= 0:
            raise ValueError("audio cache limits must be positive")
        self.root = Path(root or _default_cache_dir()).expanduser()
        self.max_bytes = int(max_bytes)
        self.max_entries = int(max_entries)
        self.ttl_seconds = float(ttl_seconds)
        self._lock = threading.RLock()
        self.root.mkdir(parents=True, exist_ok=True)
        self.prune()

    def path_for(self, key: str) -> Path:
        if not re.fullmatch(r"[0-9a-f]{64}", key):
            raise ValueError("audio cache keys must be SHA-256 hex strings")
        return self.root / f"{key}.wav"

    def get(self, key: str) -> bytes | None:
        path = self.path_for(key)
        with self._lock:
            try:
                stat = path.stat()
                if time.time() - stat.st_mtime > self.ttl_seconds:
                    path.unlink(missing_ok=True)
                    return None
                audio = path.read_bytes()
            except (FileNotFoundError, OSError):
                return None
            if not _is_valid_wav(audio):
                try:
                    path.unlink(missing_ok=True)
                except OSError:
                    pass
                return None
            # Touching the file makes the retention policy LRU-like while the
            # actual bytes remain immutable and content addressed.
            try:
                os.utime(path, None)
            except OSError:
                pass
            return audio

    def put(self, key: str, audio: bytes) -> None:
        if not _is_valid_wav(audio):
            raise ValueError("audio cache accepts only mono 16 kHz PCM WAV")
        target = self.path_for(key)
        with self._lock:
            self.root.mkdir(parents=True, exist_ok=True)
            temporary = self.root / f".{key}.{uuid4().hex}.tmp"
            try:
                temporary.write_bytes(bytes(audio))
                os.replace(temporary, target)
            finally:
                try:
                    temporary.unlink(missing_ok=True)
                except OSError:
                    pass
            self.prune()

    def prune(self) -> None:
        with self._lock:
            try:
                paths = list(self.root.glob("*.wav"))
            except OSError:
                return
            now = time.time()
            live: list[tuple[Path, int, float]] = []
            for path in paths:
                try:
                    stat = path.stat()
                except OSError:
                    continue
                if now - stat.st_mtime > self.ttl_seconds:
                    try:
                        path.unlink(missing_ok=True)
                    except OSError:
                        pass
                    continue
                live.append((path, int(stat.st_size), stat.st_mtime))
            live.sort(key=lambda item: item[2], reverse=True)
            total = 0
            for index, (path, size, _mtime) in enumerate(live):
                keep = index < self.max_entries and total + size <= self.max_bytes
                if keep:
                    total += size
                    continue
                try:
                    path.unlink(missing_ok=True)
                except OSError:
                    pass

    def clear(self) -> None:
        """Remove only cache WAVs; leave unrelated runtime files untouched."""

        with self._lock:
            for path in self.root.glob("*.wav"):
                try:
                    path.unlink(missing_ok=True)
                except OSError:
                    pass


@dataclass(frozen=True)
class FallbackEntry:
    key: str
    language: str
    path: str | None
    approved: bool
    review_status: str
    sha256: str | None = None


class PrerecordedFallbackManifest:
    """Read-only manifest for owner-approved emergency audio."""

    SCHEMA = "stage07-prerecorded-fallback.v1"

    def __init__(self, manifest_path: Path, entries: Mapping[str, FallbackEntry]) -> None:
        self.manifest_path = manifest_path
        self.entries = dict(entries)

    @classmethod
    def load(cls, path: str | os.PathLike[str] | None = None) -> "PrerecordedFallbackManifest":
        manifest_path = Path(path or _default_manifest_path()).expanduser()
        try:
            raw = json.loads(manifest_path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return cls(manifest_path, {})
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise SpeechWorkerError(
                "The prerecorded fallback manifest could not be read.",
                reason="fallback_manifest_invalid",
            ) from exc
        if not isinstance(raw, dict) or raw.get("schema") != cls.SCHEMA:
            raise SpeechWorkerError(
                "The prerecorded fallback manifest has an unsupported schema.",
                reason="fallback_manifest_invalid",
            )
        raw_entries = raw.get("entries")
        if not isinstance(raw_entries, list):
            raise SpeechWorkerError(
                "The prerecorded fallback manifest has no entries array.",
                reason="fallback_manifest_invalid",
            )
        entries: dict[str, FallbackEntry] = {}
        for item in raw_entries:
            if not isinstance(item, dict) or not isinstance(item.get("key"), str):
                raise SpeechWorkerError(
                    "The prerecorded fallback manifest contains an invalid entry.",
                    reason="fallback_manifest_invalid",
                )
            key = item["key"]
            if key in entries:
                raise SpeechWorkerError(
                    "The prerecorded fallback manifest contains duplicate keys.",
                    reason="fallback_manifest_invalid",
                )
            language = item.get("language")
            path_value = item.get("path")
            approved = item.get("approved") is True
            review_status = item.get("review_status", "pending_owner_review")
            if language not in {"nan-TW", "zh-TW"}:
                raise SpeechWorkerError(
                    "The prerecorded fallback manifest contains an invalid language.",
                    reason="fallback_manifest_invalid",
                )
            if path_value is not None and not isinstance(path_value, str):
                raise SpeechWorkerError(
                    "The prerecorded fallback manifest contains an invalid path.",
                    reason="fallback_manifest_invalid",
                )
            entries[key] = FallbackEntry(
                key=key,
                language=language,
                path=path_value,
                approved=approved and review_status == "approved",
                review_status=str(review_status),
                sha256=item.get("sha256") if isinstance(item.get("sha256"), str) else None,
            )
        return cls(manifest_path, entries)

    def audio_for(self, *keys: str) -> bytes | None:
        """Return bytes only for an approved, present, hash-matching entry."""

        for key in keys:
            entry = self.entries.get(key)
            if entry is None or not entry.approved or not entry.path:
                continue
            path = (self.manifest_path.parent / entry.path).resolve()
            try:
                # A manifest may point to a fixture or an owner-managed audio
                # directory, but never to a path that escapes its own parent.
                path.relative_to(self.manifest_path.parent.resolve())
                audio = path.read_bytes()
            except (OSError, ValueError):
                continue
            if entry.sha256 and hashlib.sha256(audio).hexdigest() != entry.sha256:
                continue
            if _is_valid_wav(audio):
                return audio
        return None


class WindowsSapiTTSWorker:
    """Synthesize Chinese UI text with the local Windows zh-TW voice.

    MMS-TTS-nan intentionally accepts only reviewed Taiwanese POJ.  The
    student prompt, however, is often Chinese UI/scaffolding text.  Browsers
    normally provide that voice through Web Speech, but the embedded browser
    used by the demo has no ``speechSynthesis`` implementation.  Windows SAPI
    is a local-only fallback for that environment; it never sends prompt text
    over the network.
    """

    _SCRIPT = r'''
Add-Type -AssemblyName System.Speech
$output = [Environment]::GetEnvironmentVariable("MEICHU_TTS_OUTPUT")
$text = [Environment]::GetEnvironmentVariable("MEICHU_TTS_TEXT")
if ([string]::IsNullOrWhiteSpace($output) -or [string]::IsNullOrWhiteSpace($text)) {
  throw "Windows SAPI output path or text is missing."
}
$synth = New-Object System.Speech.Synthesis.SpeechSynthesizer
try {
  $voice = $synth.GetInstalledVoices() |
    Where-Object { $_.VoiceInfo.Culture.Name -eq "zh-TW" } |
    Select-Object -First 1
  if (-not $voice) { throw "No installed zh-TW Windows voice was found." }
  $synth.SelectVoice($voice.VoiceInfo.Name)
  $format = New-Object System.Speech.AudioFormat.SpeechAudioFormatInfo(
    16000,
    [System.Speech.AudioFormat.AudioBitsPerSample]::Sixteen,
    [System.Speech.AudioFormat.AudioChannel]::Mono
  )
  $synth.SetOutputToWaveFile($output, $format)
  $synth.Speak($text)
} finally {
  $synth.Dispose()
}
'''

    def __init__(
        self,
        *,
        executable: str | None = None,
        runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
        timeout_s: float = 30.0,
    ) -> None:
        self.executable = executable or shutil.which("powershell.exe")
        self.runner = runner
        self.timeout_s = timeout_s

    @property
    def available(self) -> bool:
        return bool(self.executable)

    def synthesize(self, text: str, token: CancellationToken) -> bytes:
        token.checkpoint()
        if not self.executable:
            raise SpeechWorkerError(
                "Windows SAPI is unavailable on this device.",
                reason="windows_sapi_unavailable",
            )
        normalized = unicodedata.normalize("NFC", text).strip()
        if not normalized:
            raise SpeechWorkerError(
                "Windows SAPI requires non-empty Chinese text.",
                reason="missing_zh_text",
            )
        if len(normalized) > WINDOWS_SAPI_MAX_TEXT_LENGTH:
            raise SpeechWorkerError(
                "Chinese UI text is too long for local Windows SAPI.",
                reason="text_too_long",
            )

        with tempfile.TemporaryDirectory(prefix="meichu-sapi-") as directory:
            output = Path(directory) / "speech.wav"
            environment = os.environ.copy()
            environment["MEICHU_TTS_OUTPUT"] = str(output)
            environment["MEICHU_TTS_TEXT"] = normalized
            encoded_script = base64.b64encode(
                self._SCRIPT.encode("utf-16le"),
            ).decode("ascii")
            try:
                completed = self.runner(
                    [
                        self.executable,
                        "-NoProfile",
                        "-NonInteractive",
                        "-EncodedCommand",
                        encoded_script,
                    ],
                    capture_output=True,
                    text=True,
                    check=False,
                    timeout=self.timeout_s,
                    env=environment,
                )
            except subprocess.TimeoutExpired as exc:
                raise SpeechWorkerError(
                    "Windows SAPI timed out while generating Chinese audio.",
                    reason="windows_sapi_timeout",
                ) from exc
            except OSError as exc:
                raise SpeechWorkerError(
                    "Windows SAPI could not be started.",
                    reason="windows_sapi_failed",
                ) from exc
            token.checkpoint()
            if completed.returncode != 0 or not output.is_file():
                raise SpeechWorkerError(
                    "Windows SAPI failed to generate Chinese audio.",
                    reason="windows_sapi_failed",
                )
            try:
                audio = output.read_bytes()
            except OSError as exc:
                raise SpeechWorkerError(
                    "Windows SAPI audio could not be read.",
                    reason="windows_sapi_failed",
                ) from exc
            if not _is_valid_wav(audio, sample_rate=WINDOWS_SAPI_SAMPLE_RATE):
                raise SpeechWorkerError(
                    "Windows SAPI returned an unsupported WAV format.",
                    reason="windows_sapi_invalid_audio",
                )
            return audio


@dataclass(frozen=True)
class SpeechRoute:
    index: int
    language: str
    provider: str
    text: str
    reason: str | None = None


class LanguageRouter:
    """Create an ordered, non-overlapping playback plan for an Utterance."""

    def plan(self, utterance: Mapping[str, Any]) -> tuple[SpeechRoute, ...]:
        segments = utterance.get("segments")
        if not isinstance(segments, list) or not segments:
            raise SpeechWorkerError("Utterance has no speech segments.", reason="empty_utterance")
        utterance_provider = utterance.get("tts_provider")
        routes: list[SpeechRoute] = []
        for index, segment in enumerate(segments):
            if not isinstance(segment, dict):
                raise SpeechWorkerError("Utterance segment is invalid.", reason="invalid_segment")
            language = segment.get("lang")
            if language == "zh-TW":
                text = segment.get("hanji")
                if not isinstance(text, str) or not text.strip():
                    raise SpeechWorkerError("Chinese speech text is missing.", reason="missing_zh_text")
                # Chinese UI/skeleton speech belongs to Windows/Web Speech.  A
                # server worker can only use an approved recording as a last
                # resort; it must never send Hanji to the nan checkpoint.
                routes.append(SpeechRoute(index, language, "web-speech", text.strip()))
                continue
            if language != "nan-TW":
                raise SpeechWorkerError("Unsupported utterance language.", reason="unsupported_language")

            if utterance_provider != "mms-tts-nan":
                routes.append(
                    SpeechRoute(
                        index,
                        language,
                        "prerecorded",
                        str(segment.get("hanji") or "").strip(),
                        "provider_not_mms",
                    ),
                )
                continue
            if segment.get("pronunciation_status") not in {"verified", "converted"}:
                routes.append(
                    SpeechRoute(
                        index,
                        language,
                        "prerecorded",
                        str(segment.get("hanji") or "").strip(),
                        "needs_review",
                    ),
                )
                continue
            poj = segment.get("poj_citation")
            try:
                normalized = normalize_poj_text(poj)
            except SpeechWorkerError as exc:
                routes.append(
                    SpeechRoute(
                        index,
                        language,
                        "prerecorded",
                        str(segment.get("hanji") or "").strip(),
                        exc.reason,
                    )
                )
            else:
                routes.append(SpeechRoute(index, language, "mms-tts-nan", normalized))
        return tuple(routes)


def waveform_to_wav(
    waveform: Any,
    *,
    sample_rate: int = MMS_TTS_SAMPLE_RATE,
) -> bytes:
    """Convert a model waveform to the fixed mono PCM contract."""

    if sample_rate != MMS_TTS_SAMPLE_RATE:
        raise SpeechWorkerError(
            "MMS-TTS returned an unsupported sample rate.",
            reason="unsupported_sample_rate",
        )
    value = waveform
    if hasattr(value, "detach"):
        value = value.detach()
    if hasattr(value, "cpu"):
        value = value.cpu()
    if hasattr(value, "numpy"):
        value = value.numpy()
    try:
        import numpy as np

        array = np.asarray(value, dtype=np.float32)
        if array.ndim == 0:
            array = array.reshape(1)
        if array.ndim > 1:
            array = array.reshape(array.shape[0], -1)[0]
        if array.size == 0 or not bool(np.isfinite(array).all()):
            raise ValueError("waveform is empty or non-finite")
        array = np.clip(array, -1.0, 1.0)
        pcm = (array * 32767.0).astype("<i2").tobytes()
    except ImportError:
        try:
            values = list(value)
            if values and isinstance(values[0], (list, tuple)):
                values = list(values[0])
            if not values:
                raise ValueError("waveform is empty")
            pcm = b"".join(
                int(max(-1.0, min(1.0, float(sample))) * 32767).to_bytes(
                    2, "little", signed=True
                )
                for sample in values
            )
        except (TypeError, ValueError, OverflowError) as exc:
            raise SpeechWorkerError(
                "MMS-TTS returned an invalid waveform.",
                reason="invalid_waveform",
            ) from exc
    except (TypeError, ValueError, OverflowError) as exc:
        raise SpeechWorkerError(
            "MMS-TTS returned an invalid waveform.",
            reason="invalid_waveform",
        ) from exc
    output = BytesIO()
    with wave.open(output, "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(MMS_TTS_SAMPLE_RATE)
        wav_file.writeframes(pcm)
    return output.getvalue()


def concatenate_wavs(chunks: Iterable[bytes]) -> bytes:
    """Concatenate fixed-format WAVs in input order without overlap."""

    frames: list[bytes] = []
    for audio in chunks:
        try:
            with wave.open(BytesIO(audio), "rb") as wav_file:
                if (
                    wav_file.getnchannels() != 1
                    or wav_file.getsampwidth() != 2
                    or wav_file.getframerate() != MMS_TTS_SAMPLE_RATE
                    or wav_file.getcomptype() != "NONE"
                ):
                    raise ValueError("unsupported audio format")
                frames.append(wav_file.readframes(wav_file.getnframes()))
        except (EOFError, OSError, wave.Error, ValueError) as exc:
            raise SpeechWorkerError(
                "A TTS audio segment has an unsupported format.",
                reason="invalid_audio_segment",
            ) from exc
    if not frames:
        raise SpeechWorkerError("TTS produced no audio.", reason="empty_audio")
    output = BytesIO()
    with wave.open(output, "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(MMS_TTS_SAMPLE_RATE)
        for frame_data in frames:
            wav_file.writeframes(frame_data)
    return output.getvalue()


class MMSNanTTSWorker:
    """Lazy CPU worker for the pinned ``facebook/mms-tts-nan`` checkpoint."""

    device = MMS_TTS_DEVICE

    def __init__(
        self,
        *,
        model_path: str | None = None,
        model_id: str = MMS_TTS_MODEL_ID,
        revision: str = MMS_TTS_MODEL_REVISION,
        speed: float = MMS_TTS_DEFAULT_SPEED,
        seed: int = MMS_TTS_DEFAULT_SEED,
        local_files_only: bool = False,
        cache: AudioCache | None = None,
        synthesizer: Callable[[str, CancellationToken, float], Any] | None = None,
    ) -> None:
        if not revision:
            raise ValueError("MMS-TTS revision must be pinned")
        if not model_id and not model_path:
            raise ValueError("MMS-TTS model_id or model_path is required")
        if not math.isfinite(float(speed)) or float(speed) <= 0:
            raise ValueError("MMS-TTS speed must be a positive finite number")
        self.model_path = model_path
        self.model_id = model_id
        self.revision = revision
        self.speed = float(speed)
        self.seed = int(seed)
        self.local_files_only = local_files_only
        self.cache = cache or AudioCache()
        self.model_revision = f"mms-tts-nan-{MMS_TTS_FRAMEWORK}@{revision[:12]}"
        self._model: Any | None = None
        self._tokenizer: Any | None = None
        self._torch: Any | None = None
        self._load_lock = threading.Lock()
        # Tests and future alternate runtimes can inject a pure-Python
        # synthesizer without importing torch or downloading the checkpoint.
        self._injected_synthesizer = synthesizer

    def warmup(self, token: CancellationToken) -> None:
        token.checkpoint()
        self._ensure_model(token)
        # Run one short, approved inference so the first student request does
        # not absorb tokenizer/model graph initialization latency.
        self.synthesize_poj(MMS_TTS_WARMUP_TEXT, token=token)
        token.checkpoint()

    def synthesize(
        self,
        *,
        utterance: dict[str, Any],
        token: CancellationToken,
    ) -> bytes:
        segments = utterance.get("segments")
        if not isinstance(segments, list) or not segments:
            raise SpeechWorkerError("Utterance has no speech segments.", reason="empty_utterance")
        chunks: list[bytes] = []
        provider = utterance.get("tts_provider")
        for segment in segments:
            token.checkpoint()
            if not isinstance(segment, dict) or segment.get("lang") != "nan-TW":
                raise SpeechWorkerError(
                    "MMS-TTS nan worker accepts only nan-TW segments.",
                    reason="language_not_supported",
                )
            if provider != "mms-tts-nan":
                raise SpeechWorkerError(
                    "MMS-TTS requires the approved mms-tts-nan provider.",
                    reason="provider_not_approved",
                )
            if segment.get("pronunciation_status") not in {"verified", "converted"}:
                raise SpeechWorkerError(
                    "This pronunciation requires language review before TTS.",
                    reason="needs_review",
                )
            normalized = normalize_poj_text(segment.get("poj_citation"))
            chunks.append(self.synthesize_poj(normalized, token=token))
        return concatenate_wavs(chunks)

    def synthesize_poj(
        self,
        text: str,
        *,
        token: CancellationToken,
        speed: float | None = None,
    ) -> bytes:
        normalized = normalize_poj_text(text)
        selected_speed = self.speed if speed is None else float(speed)
        cache_key = build_audio_cache_key(
            provider="mms-tts-nan",
            revision=self.revision,
            normalized_text=normalized,
            speed=selected_speed,
        )
        cached = self.cache.get(cache_key)
        if cached is not None:
            token.checkpoint()
            return cached
        token.checkpoint()
        try:
            if self._injected_synthesizer is not None:
                waveform = self._injected_synthesizer(normalized, token, selected_speed)
                if isinstance(waveform, tuple) and len(waveform) == 2:
                    audio = waveform_to_wav(waveform[0], sample_rate=int(waveform[1]))
                else:
                    audio = waveform_to_wav(waveform)
            else:
                model, tokenizer, torch = self._ensure_model(token)
                if hasattr(model, "speaking_rate"):
                    model.speaking_rate = selected_speed
                torch.manual_seed(self.seed)
                inputs = tokenizer(text=normalized, return_tensors="pt")
                if hasattr(inputs, "to"):
                    inputs = inputs.to(MMS_TTS_DEVICE)
                with torch.no_grad():
                    output = model(**inputs)
                sample_rate = int(getattr(getattr(model, "config", None), "sampling_rate", 0))
                audio = waveform_to_wav(output.waveform, sample_rate=sample_rate)
        except SpeechWorkerError:
            raise
        except Exception as exc:
            raise SpeechWorkerError(
                "MMS-TTS inference failed.",
                reason="mms_inference_failed",
            ) from exc
        token.checkpoint()
        self.cache.put(cache_key, audio)
        return audio

    def close(self) -> None:
        with self._load_lock:
            self._model = None
            self._tokenizer = None
            self._torch = None

    def _ensure_model(self, token: CancellationToken) -> tuple[Any, Any, Any]:
        if self._injected_synthesizer is not None:
            return None, None, None
        with self._load_lock:
            if self._model is not None and self._tokenizer is not None and self._torch is not None:
                return self._model, self._tokenizer, self._torch
            token.checkpoint()
            try:
                import torch
                from transformers import AutoTokenizer, VitsModel
            except ImportError as exc:
                raise SpeechWorkerError(
                    "MMS-TTS runtime is not installed; run the speech setup command.",
                    reason="runtime_missing",
                ) from exc
            if os.name == "nt":
                os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS", "1")
                os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")
            model_ref = self.model_path or self.model_id
            kwargs: dict[str, Any] = {"local_files_only": self.local_files_only}
            if not _is_local_model_path(model_ref):
                kwargs["revision"] = self.revision
            try:
                tokenizer = AutoTokenizer.from_pretrained(model_ref, **kwargs)
                model = VitsModel.from_pretrained(model_ref, **kwargs)
                model.to(MMS_TTS_DEVICE)
                model.eval()
                sample_rate = int(getattr(getattr(model, "config", None), "sampling_rate", 0))
                if sample_rate != MMS_TTS_SAMPLE_RATE:
                    raise ValueError("checkpoint sampling rate is not 16 kHz")
            except SpeechWorkerError:
                raise
            except Exception as exc:
                raise SpeechWorkerError(
                    "MMS-TTS model could not be loaded.",
                    reason="model_unavailable",
                ) from exc
            self._torch = torch
            self._tokenizer = tokenizer
            self._model = model
            return model, tokenizer, torch


class RoutedSpeechTTSWorker:
    """Route nan-TW to MMS and Chinese UI text to local/browser speech."""

    device = MMS_TTS_DEVICE

    def __init__(
        self,
        *,
        mms_worker: MMSNanTTSWorker | None = None,
        fallback_manifest: PrerecordedFallbackManifest | None = None,
        manifest_path: str | os.PathLike[str] | None = None,
        windows_tts: WindowsSapiTTSWorker | None = None,
    ) -> None:
        self.mms_worker = mms_worker or MMSNanTTSWorker()
        self.fallback_manifest = fallback_manifest or PrerecordedFallbackManifest.load(manifest_path)
        self.router = LanguageRouter()
        self.model_revision = self.mms_worker.model_revision
        self.windows_tts = windows_tts if windows_tts is not None else WindowsSapiTTSWorker()

    def warmup(self, token: CancellationToken) -> None:
        self.mms_worker.warmup(token)

    def synthesize(
        self,
        *,
        utterance: dict[str, Any],
        token: CancellationToken,
    ) -> bytes:
        routes = self.router.plan(utterance)
        chunks: list[bytes] = []
        utterance_id = str(utterance.get("id", ""))
        for route in routes:
            token.checkpoint()
            if route.provider == "mms-tts-nan":
                chunks.append(self.mms_worker.synthesize_poj(route.text, token=token))
                continue
            fallback = self.fallback_manifest.audio_for(
                f"{utterance_id}:{route.index}",
                f"{route.language}:{route.text}",
            )
            if fallback is not None:
                chunks.append(fallback)
                continue
            if route.provider == "web-speech":
                if self.windows_tts.available:
                    chunks.append(self.windows_tts.synthesize(route.text, token))
                    continue
                raise SpeechWorkerError(
                    "Chinese UI speech requires a browser Web Speech voice, Windows zh-TW voice, or approved recording.",
                    reason="browser_tts_required",
                )
            raise SpeechWorkerError(
                "No approved prerecorded audio is available for this pronunciation.",
                reason=route.reason or "fallback_unavailable",
            )
        return concatenate_wavs(chunks)

    def close(self) -> None:
        self.mms_worker.close()


def _is_local_model_path(model_ref: str) -> bool:
    if not model_ref:
        return False
    try:
        return Path(model_ref).expanduser().is_dir()
    except OSError:
        return False


__all__ = [
    "AudioCache",
    "FallbackEntry",
    "LanguageRouter",
    "MMSNanTTSWorker",
    "MMS_TTS_DEFAULT_SEED",
    "MMS_TTS_DEFAULT_SPEED",
    "MMS_TTS_DEVICE",
    "MMS_TTS_FORMAT",
    "MMS_TTS_FRAMEWORK",
    "MMS_TTS_LICENSE",
    "MMS_TTS_MODEL_ID",
    "MMS_TTS_MODEL_REVISION",
    "MMS_TTS_SAMPLE_RATE",
    "MMS_TTS_VOCABULARY",
    "MMS_TTS_WARMUP_TEXT",
    "WindowsSapiTTSWorker",
    "PrerecordedFallbackManifest",
    "RoutedSpeechTTSWorker",
    "SpeechRoute",
    "build_audio_cache_key",
    "concatenate_wavs",
    "normalize_poj_text",
    "waveform_to_wav",
]
