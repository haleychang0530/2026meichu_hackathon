"""Breeze worker tests with a fake model; no network or model weights required."""

from __future__ import annotations

from io import BytesIO
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import patch
import wave

import numpy as np


SERVICE_DIR = Path(__file__).resolve().parent
if str(SERVICE_DIR) not in sys.path:
    sys.path.insert(0, str(SERVICE_DIR))

from workers import (  # noqa: E402
    BREEZE_ASR_MODEL_REVISION,
    BreezeASR26CPUWorker,
    CancellationToken,
    SpeechWorkerError,
    create_asr_worker,
)


def make_tone_wav() -> bytes:
    sample_rate = 16000
    time_axis = np.arange(sample_rate, dtype=np.float32) / sample_rate
    samples = (0.2 * np.sin(2 * np.pi * 440 * time_axis) * 32767).astype("<i2")
    output = BytesIO()
    with wave.open(output, "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(sample_rate)
        wav_file.writeframes(samples.tobytes())
    return output.getvalue()


class FakeModel:
    instances: list["FakeModel"] = []

    def __init__(self, model_ref: str, **kwargs: object) -> None:
        self.model_ref = model_ref
        self.kwargs = kwargs
        self.transcribe_calls: list[tuple[np.ndarray, dict[str, object]]] = []
        self.__class__.instances.append(self)

    def transcribe(self, samples: np.ndarray, **kwargs: object):
        self.transcribe_calls.append((samples, kwargs))
        segment = types.SimpleNamespace(text=" 測試回答 ")
        return iter([segment]), types.SimpleNamespace(language="zh")


class BreezeWorkerTests(unittest.TestCase):
    def setUp(self) -> None:
        FakeModel.instances.clear()
        fake_module = types.ModuleType("faster_whisper")
        fake_module.WhisperModel = FakeModel
        self.fake_module = fake_module

    def test_worker_is_lazy_and_forces_zh_cpu_int8_path(self) -> None:
        worker = BreezeASR26CPUWorker(
            model_path="C:/not-present-in-test",
            cpu_threads=3,
            beam_size=2,
            vad_enabled=False,
        )
        self.assertEqual(FakeModel.instances, [])
        with patch.dict(sys.modules, {"faster_whisper": self.fake_module}):
            worker.warmup(CancellationToken())
            transcript = worker.transcribe(
                audio=make_tone_wav(),
                audio_size=1,
                language="nan-TW",
                device="cpu",
                token=CancellationToken(),
            )
        self.assertEqual(transcript, "測試回答")
        self.assertEqual(len(FakeModel.instances), 1)
        model = FakeModel.instances[0]
        self.assertEqual(model.kwargs["device"], "cpu")
        self.assertEqual(model.kwargs["compute_type"], "int8")
        self.assertEqual(model.kwargs["cpu_threads"], 3)
        self.assertEqual(model.kwargs["revision"], BREEZE_ASR_MODEL_REVISION)
        samples, options = model.transcribe_calls[0]
        self.assertEqual(samples.dtype, np.float32)
        self.assertEqual(samples.ndim, 1)
        self.assertEqual(options["language"], "zh")
        self.assertEqual(options["device"] if "device" in options else "cpu", "cpu")
        self.assertFalse(options["vad_filter"])

    def test_preprocessing_failure_does_not_load_model(self) -> None:
        worker = BreezeASR26CPUWorker(model_path="C:/not-present-in-test")
        silent = BytesIO()
        with wave.open(silent, "wb") as wav_file:
            wav_file.setnchannels(1)
            wav_file.setsampwidth(2)
            wav_file.setframerate(16000)
            wav_file.writeframes(b"\x00\x00" * 16000)
        with patch.dict(sys.modules, {"faster_whisper": self.fake_module}):
            with self.assertRaises(SpeechWorkerError) as raised:
                worker.transcribe(
                    audio=silent.getvalue(),
                    audio_size=1,
                    language="zh-TW",
                    device="cpu",
                    token=CancellationToken(),
                )
        self.assertEqual(raised.exception.reason, "no_speech")
        self.assertEqual(FakeModel.instances, [])

    def test_factory_keeps_mock_default_and_exposes_breeze_backend(self) -> None:
        self.assertEqual(create_asr_worker("mock").model_revision, "mock-breeze-asr-v0.1")
        worker = create_asr_worker("breeze", model_path="C:/not-present-in-test")
        self.assertIsInstance(worker, BreezeASR26CPUWorker)


if __name__ == "__main__":
    unittest.main()
