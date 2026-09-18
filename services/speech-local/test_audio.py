"""CPU ASR audio preprocessing tests; no model weights or audio files required."""

from __future__ import annotations

from io import BytesIO
import sys
from pathlib import Path
import unittest
import wave

import numpy as np


SERVICE_DIR = Path(__file__).resolve().parent
if str(SERVICE_DIR) not in sys.path:
    sys.path.insert(0, str(SERVICE_DIR))

from audio import AudioPreprocessError, prepare_audio  # noqa: E402


def make_wav(
    *,
    duration_ms: int = 1200,
    sample_rate: int = 8000,
    channels: int = 1,
    tone_start_ms: int = 200,
    tone_end_ms: int = 1000,
) -> bytes:
    frame_count = int(sample_rate * duration_ms / 1000)
    samples = np.zeros(frame_count, dtype=np.float32)
    start = int(sample_rate * tone_start_ms / 1000)
    end = min(frame_count, int(sample_rate * tone_end_ms / 1000))
    if end > start:
        time_axis = np.arange(end - start, dtype=np.float32) / sample_rate
        samples[start:end] = 0.2 * np.sin(2 * np.pi * 440 * time_axis)
    if channels > 1:
        samples = np.repeat(samples[:, None], channels, axis=1).reshape(-1)
    pcm = np.clip(samples * 32767.0, -32768, 32767).astype("<i2")
    output = BytesIO()
    with wave.open(output, "wb") as wav_file:
        wav_file.setnchannels(channels)
        wav_file.setsampwidth(2)
        wav_file.setframerate(sample_rate)
        wav_file.writeframes(pcm.tobytes())
    return output.getvalue()


class AudioPreprocessTests(unittest.TestCase):
    def test_resamples_downmixes_and_trims_silence(self) -> None:
        prepared = prepare_audio(make_wav(channels=2, sample_rate=8000))
        self.assertEqual(prepared.sample_rate, 16000)
        self.assertEqual(prepared.samples.dtype, np.float32)
        self.assertEqual(prepared.samples.ndim, 1)
        self.assertEqual(prepared.input_sample_count, 19200)
        self.assertLess(prepared.output_sample_count, prepared.input_sample_count)
        self.assertGreater(prepared.output_duration_s, 0.1)
        self.assertTrue(prepared.speech_detected)
        self.assertGreater(prepared.normalization_gain, 0)

    def test_vad_can_be_disabled_for_benchmark_comparison(self) -> None:
        prepared = prepare_audio(make_wav(), vad_enabled=False)
        self.assertEqual(prepared.input_sample_count, prepared.output_sample_count)
        self.assertFalse(prepared.vad_enabled)

    def test_silence_is_rejected_with_stable_reason(self) -> None:
        with self.assertRaises(AudioPreprocessError) as raised:
            prepare_audio(make_wav(tone_start_ms=0, tone_end_ms=0))
        self.assertEqual(raised.exception.reason, "no_speech")
        self.assertEqual(raised.exception.safe_message, "No speech activity was detected.")

    def test_short_audio_is_rejected_with_stable_reason(self) -> None:
        with self.assertRaises(AudioPreprocessError) as raised:
            prepare_audio(make_wav(duration_ms=50, tone_start_ms=0, tone_end_ms=50))
        self.assertEqual(raised.exception.reason, "too_short")

    def test_malformed_audio_is_rejected_without_decoder_details(self) -> None:
        with self.assertRaises(AudioPreprocessError) as raised:
            prepare_audio(b"not-audio")
        self.assertEqual(raised.exception.reason, "unsupported_audio")
        self.assertNotIn("not-audio", raised.exception.safe_message)


if __name__ == "__main__":
    unittest.main()
