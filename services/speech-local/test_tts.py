"""Offline tests for Stage 07 TTS routing and cache behavior."""

from __future__ import annotations

from io import BytesIO
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
import wave

import numpy as np


SERVICE_DIR = Path(__file__).resolve().parent
if str(SERVICE_DIR) not in sys.path:
    sys.path.insert(0, str(SERVICE_DIR))

from tts import (  # noqa: E402
    AudioCache,
    LanguageRouter,
    MMSNanTTSWorker,
    MMS_TTS_MODEL_ID,
    MMS_TTS_MODEL_REVISION,
    PrerecordedFallbackManifest,
    RoutedSpeechTTSWorker,
    build_audio_cache_key,
    normalize_poj_text,
)
from workers import CancellationToken, SpeechWorkerError  # noqa: E402


def make_wav(*, frames: int = 160, value: int = 1000) -> bytes:
    output = BytesIO()
    with wave.open(output, "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(16_000)
        wav_file.writeframes((int(value).to_bytes(2, "little", signed=True)) * frames)
    return output.getvalue()


def utterance(*segments: dict[str, object], provider: str | None = "mms-tts-nan") -> dict[str, object]:
    return {
        "schema_version": "0.1.0",
        "id": "utt_stage07_test",
        "segments": list(segments),
        "tts_provider": provider,
        "audio_url": None,
        "audio_cache_key": None,
    }


def nan_segment(
    text: str = "chiah-peng",
    *,
    status: str = "verified",
) -> dict[str, object]:
    return {
        "lang": "nan-TW",
        "hanji": "食飯",
        "tailo_citation": "tsiah-png",
        "poj_citation": text,
        "zh_gloss": "吃飯",
        "source": "generated",
        "pronunciation_status": status,
    }


class TtsValidationTests(unittest.TestCase):
    def test_normalization_accepts_reviewed_poj_and_rejects_unknown_text(self) -> None:
        self.assertEqual(normalize_poj_text("  chiah-peng  "), "chiah-peng")
        with self.assertRaises(SpeechWorkerError) as raised:
            normalize_poj_text("chiah-peng!")
        self.assertEqual(raised.exception.reason, "unsupported_poj_character")

    def test_cache_key_changes_with_every_synthesis_dimension(self) -> None:
        base = build_audio_cache_key(
            provider="mms-tts-nan",
            revision=MMS_TTS_MODEL_REVISION,
            normalized_text="chiah-peng",
            speed=1.0,
        )
        self.assertEqual(len(base), 64)
        self.assertNotEqual(
            base,
            build_audio_cache_key(
                provider="mms-tts-nan",
                revision=MMS_TTS_MODEL_REVISION,
                normalized_text="chiah-peng",
                speed=1.1,
            ),
        )
        self.assertNotEqual(
            base,
            build_audio_cache_key(
                provider="mms-tts-nan",
                revision="different-revision",
                normalized_text="chiah-peng",
                speed=1.0,
            ),
        )


class MmsWorkerTests(unittest.TestCase):
    def test_model_is_not_called_on_cache_hit(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            cache = AudioCache(directory)
            calls: list[tuple[str, float]] = []

            def synthesize(text: str, _token: CancellationToken, speed: float) -> np.ndarray:
                calls.append((text, speed))
                return np.asarray([0.1, -0.1, 0.1], dtype=np.float32)

            worker = MMSNanTTSWorker(cache=cache, synthesizer=synthesize)
            first = worker.synthesize_poj("chiah-peng", token=CancellationToken())
            second = worker.synthesize_poj("chiah-peng", token=CancellationToken())
            self.assertEqual(first, second)
            self.assertEqual(calls, [("chiah-peng", 1.0)])
            self.assertEqual(worker.model_revision, f"mms-tts-nan-transformers+torch@{MMS_TTS_MODEL_REVISION[:12]}")

    def test_mms_worker_accepts_needs_review_when_poj_is_valid(self) -> None:
        worker = MMSNanTTSWorker(
            cache=AudioCache(tempfile.mkdtemp()),
            synthesizer=lambda _text, _token, _speed: np.asarray([0.1], dtype=np.float32),
        )
        audio = worker.synthesize(
            utterance=utterance(nan_segment(status="needs_review")),
            token=CancellationToken(),
        )
        self.assertTrue(audio.startswith(b"RIFF"))


class RoutingAndFallbackTests(unittest.TestCase):
    def test_router_preserves_order_and_routes_each_language(self) -> None:
        needs_review_without_poj = nan_segment(status="needs_review")
        needs_review_without_poj["poj_citation"] = None
        plan = LanguageRouter().plan(
            utterance(
                {
                    "lang": "zh-TW",
                    "hanji": "請跟我說",
                    "pronunciation_status": "needs_review",
                },
                nan_segment(),
                nan_segment(status="needs_review"),
                needs_review_without_poj,
            )
        )
        self.assertEqual([item.index for item in plan], [0, 1, 2, 3])
        self.assertEqual(
            [item.provider for item in plan],
            ["web-speech", "mms-tts-nan", "mms-tts-nan", "web-speech"],
        )
        self.assertEqual(plan[3].reason, "needs_review_zh_fallback")

    def test_approved_manifest_audio_is_read_only_and_hash_checked(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            audio = make_wav()
            (root / "approved.wav").write_bytes(audio)
            manifest = {
                "schema": "stage07-prerecorded-fallback.v1",
                "entries": [
                    {
                        "key": "utt_stage07_test:0",
                        "language": "nan-TW",
                        "path": "approved.wav",
                        "approved": True,
                        "review_status": "approved",
                        "sha256": hashlib.sha256(audio).hexdigest(),
                    }
                ],
            }
            manifest_path = root / "manifest.json"
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            loaded = PrerecordedFallbackManifest.load(manifest_path)
            self.assertEqual(loaded.audio_for("utt_stage07_test:0"), audio)
            (root / "approved.wav").write_bytes(make_wav(value=2000))
            self.assertIsNone(loaded.audio_for("utt_stage07_test:0"))

    def test_routed_worker_concatenates_nan_segments_in_order(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            calls: list[str] = []

            def synthesize(text: str, _token: CancellationToken, _speed: float) -> np.ndarray:
                calls.append(text)
                return np.asarray([0.1 if text == "chiah-peng" else 0.2], dtype=np.float32)

            worker = RoutedSpeechTTSWorker(
                mms_worker=MMSNanTTSWorker(
                    cache=AudioCache(directory),
                    synthesizer=synthesize,
                ),
                fallback_manifest=PrerecordedFallbackManifest(Path(directory), {}),
            )
            audio = worker.synthesize(
                utterance=utterance(nan_segment("chiah-peng"), nan_segment("tshia̍h")),
                token=CancellationToken(),
            )
            with wave.open(BytesIO(audio), "rb") as wav_file:
                self.assertEqual(wav_file.getnframes(), 2)
            self.assertEqual(calls, ["chiah-peng", "tshia̍h"])

    def test_routed_worker_uses_windows_voice_for_chinese_ui_text(self) -> None:
        calls: list[str] = []

        class FakeWindowsVoice:
            available = True

            def synthesize(self, text: str, _token: CancellationToken) -> bytes:
                calls.append(text)
                return make_wav()

        with tempfile.TemporaryDirectory() as directory:
            worker = RoutedSpeechTTSWorker(
                windows_tts=FakeWindowsVoice(),  # type: ignore[arg-type]
                fallback_manifest=PrerecordedFallbackManifest(Path(directory), {}),
            )
            audio = worker.synthesize(
                utterance=utterance(
                    {
                        "lang": "zh-TW",
                        "hanji": "請跟我說",
                        "tailo_citation": None,
                        "poj_citation": None,
                        "zh_gloss": "請跟我說",
                        "source": "generated",
                        "pronunciation_status": "verified",
                    },
                    provider="windows",
                ),
                token=CancellationToken(),
            )
        self.assertEqual(calls, ["請跟我說"])
        self.assertTrue(audio.startswith(b"RIFF"))


if __name__ == "__main__":
    unittest.main()
