"""Integration tests for the Agent B Stage 04 Speech Gateway."""

from __future__ import annotations

import http.client
import json
from pathlib import Path
import sys
import threading
import unittest


SERVICE_DIR = Path(__file__).resolve().parent
if str(SERVICE_DIR) not in sys.path:
    sys.path.insert(0, str(SERVICE_DIR))

from gateway import (  # noqa: E402
    HalfDuplexState,
    SpeechGatewayService,
    build_server,
)
from workers import MockASRWorker, MockTTSWorker  # noqa: E402


UTTERANCE = {
    "schema_version": "0.1.0",
    "id": "utt_stage04",
    "segments": [
        {
            "lang": "nan-TW",
            "hanji": "食飯",
            "tailo_citation": "tsiah-png",
            "poj_citation": "chiah-peng",
            "zh_gloss": "吃飯",
            "source": "generated",
            "pronunciation_status": "verified",
        }
    ],
    "tts_provider": "mms-tts-nan",
    "audio_url": None,
    "audio_cache_key": None,
}


class SpeechGatewayCoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.asr = MockASRWorker()
        self.tts = MockTTSWorker()
        self.service = SpeechGatewayService(
            asr_worker=self.asr,
            tts_worker=self.tts,
            timeout_s=2.0,
            max_pending=2,
        )

    def tearDown(self) -> None:
        self.service.close()

    def test_health_contains_contract_services_and_runtime_diagnostics(self) -> None:
        payload = self.service.health_payload("00000000-0000-4000-8000-000000000001")
        self.assertEqual(payload["schema_version"], "0.1.0")
        self.assertEqual([item["service"] for item in payload["services"]], ["asr", "tts"])
        self.assertEqual(self.service.runtime_diagnostics()["state"], "IDLE")
        self.assertIn("memory", self.service.runtime_diagnostics())

    def test_playback_cancels_recording_before_tts(self) -> None:
        self.asr.delay_s = 0.5
        errors: list[Exception] = []

        def transcribe() -> None:
            try:
                self.service.transcribe(
                    audio=b"synthetic-audio",
                    language="nan-TW",
                    device_preference="auto",
                    request_id="00000000-0000-4000-8000-000000000002",
                )
            except Exception as exc:  # the cancelled operation is expected
                errors.append(exc)

        thread = threading.Thread(target=transcribe)
        thread.start()
        self.assertTrue(self.asr.started.wait(1.0))
        audio = self.service.synthesize(
            utterance=UTTERANCE,
            format_name="wav",
            request_id="00000000-0000-4000-8000-000000000003",
        )
        thread.join(1.0)
        self.assertTrue(audio.startswith(b"RIFF"))
        self.assertEqual(len(errors), 1)
        self.assertEqual(getattr(errors[0], "code", None), "ASR_FAILED")
        self.assertEqual(self.service.state, HalfDuplexState.IDLE)
        self.assertLessEqual(self.asr.stats.max_active, 1)
        self.assertLessEqual(self.tts.stats.max_active, 1)

    def test_recording_cancels_playback_and_returns_transcript(self) -> None:
        self.tts.delay_s = 0.5
        errors: list[Exception] = []

        def synthesize() -> None:
            try:
                self.service.synthesize(
                    utterance=UTTERANCE,
                    format_name="wav",
                    request_id="00000000-0000-4000-8000-000000000004",
                )
            except Exception as exc:  # the cancelled operation is expected
                errors.append(exc)

        thread = threading.Thread(target=synthesize)
        thread.start()
        self.assertTrue(self.tts.started.wait(1.0))
        response = self.service.transcribe(
            audio=b"synthetic-audio",
            language="zh-TW",
            device_preference="npu",
            request_id="00000000-0000-4000-8000-000000000005",
        )
        thread.join(1.0)
        self.assertEqual(response["device"], "cpu")
        self.assertEqual(response["language"], "zh-TW")
        self.assertEqual(self.service.state, HalfDuplexState.EVALUATING)
        self.assertEqual(len(errors), 1)
        self.assertEqual(getattr(errors[0], "code", None), "TTS_FAILED")

    def test_rapid_duplicate_playback_is_single_flight(self) -> None:
        self.tts.delay_s = 0.25
        errors: list[Exception] = []

        def first() -> None:
            try:
                self.service.synthesize(
                    utterance=UTTERANCE,
                    format_name="wav",
                    request_id="00000000-0000-4000-8000-000000000006",
                )
            except Exception as exc:
                errors.append(exc)

        thread = threading.Thread(target=first)
        thread.start()
        self.assertTrue(self.tts.started.wait(1.0))
        with self.assertRaisesRegex(Exception, "same speech operation") as raised:
            self.service.synthesize(
                utterance=UTTERANCE,
                format_name="wav",
                request_id="00000000-0000-4000-8000-000000000007",
            )
        self.assertEqual(getattr(raised.exception, "code", None), "TTS_FAILED")
        thread.join(1.0)
        self.assertEqual(errors, [])
        self.assertEqual(self.tts.stats.calls, 1)

    def test_cancel_returns_idle_and_worker_crash_recovers(self) -> None:
        self.tts.delay_s = 0.5
        errors: list[Exception] = []

        def synthesize() -> None:
            try:
                self.service.synthesize(
                    utterance=UTTERANCE,
                    format_name="wav",
                    request_id="00000000-0000-4000-8000-000000000008",
                )
            except Exception as exc:
                errors.append(exc)

        thread = threading.Thread(target=synthesize)
        thread.start()
        self.assertTrue(self.tts.started.wait(1.0))
        cancelled = self.service.cancel(request_id="00000000-0000-4000-8000-000000000009")
        thread.join(1.0)
        self.assertEqual(cancelled["status"], "cancelled")
        self.assertEqual(self.service.state, HalfDuplexState.IDLE)
        self.assertEqual(len(errors), 1)

        self.asr.crash_next = True
        with self.assertRaisesRegex(Exception, "ASR worker failed"):
            self.service.transcribe(
                audio=b"synthetic-audio",
                language="nan-TW",
                device_preference="cpu",
                request_id="00000000-0000-4000-8000-000000000010",
            )
        degraded = self.service.health_payload("00000000-0000-4000-8000-000000000011")
        self.assertEqual(degraded["services"][0]["status"], "degraded")
        recovered = self.service.transcribe(
            audio=b"synthetic-audio",
            language="nan-TW",
            device_preference="cpu",
            request_id="00000000-0000-4000-8000-000000000012",
        )
        self.assertTrue(recovered["text"])
        ready = self.service.health_payload("00000000-0000-4000-8000-000000000013")
        self.assertEqual(ready["services"][0]["status"], "ready")


class SpeechGatewayHttpTests(unittest.TestCase):
    def setUp(self) -> None:
        self.service = SpeechGatewayService(timeout_s=2.0)
        self.server = build_server(self.service, host="127.0.0.1", port=0)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.port = self.server.server_address[1]

    def tearDown(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.service.close()
        self.thread.join(1.0)

    def request(
        self,
        method: str,
        path: str,
        *,
        body: bytes | None = None,
        headers: dict[str, str] | None = None,
    ) -> tuple[int, dict[str, str], bytes]:
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=2.0)
        connection.request(method, path, body=body, headers=headers or {})
        response = connection.getresponse()
        payload = response.read()
        response_headers = {key.lower(): value for key, value in response.getheaders()}
        status = response.status
        connection.close()
        return status, response_headers, payload

    def test_health_speech_and_transcription_routes(self) -> None:
        status, headers, payload = self.request(
            "GET",
            "/local/health",
            headers={"Origin": "http://127.0.0.1:5173"},
        )
        self.assertEqual(status, 200)
        health = json.loads(payload)
        self.assertEqual(len(health["services"]), 2)
        self.assertEqual(headers["access-control-allow-origin"], "http://127.0.0.1:5173")
        self.assertGreater(json.loads(headers["x-speech-runtime"])["memory"]["safe_reserve_bytes"], 0)
        self.assertIn("x-speech-runtime", headers["access-control-expose-headers"].lower())
        self.assertEqual(headers["x-request-id"], health["request_id"])

        status, _, payload = self.request(
            "POST",
            "/local/warmup",
            body=json.dumps({"services": ["asr", "tts"]}).encode("utf-8"),
            headers={"Content-Type": "application/json"},
        )
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(payload)["status"], "ready")

        status, _, payload = self.request("POST", "/local/cancel")
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(payload)["status"], "cancelled")

        # The canonical speech request keeps format beside utterance.
        speech_body = json.dumps(
            {"schema_version": "0.1.0", "utterance": UTTERANCE, "format": "wav"}
        ).encode("utf-8")
        status, headers, payload = self.request(
            "POST",
            "/v1/audio/speech",
            body=speech_body,
            headers={"Content-Type": "application/json", "Origin": "http://localhost:5173"},
        )
        self.assertEqual(status, 200)
        self.assertEqual(headers["content-type"], "audio/wav")
        self.assertTrue(payload.startswith(b"RIFF"))

        boundary = "stage04-boundary"
        multipart = b"".join(
            [
                f"--{boundary}\r\n".encode(),
                b'Content-Disposition: form-data; name="language"\r\n\r\n',
                b"nan-TW\r\n",
                f"--{boundary}\r\n".encode(),
                b'Content-Disposition: form-data; name="device_preference"\r\n\r\n',
                b"auto\r\n",
                f"--{boundary}\r\n".encode(),
                b'Content-Disposition: form-data; name="file"; filename="recording.wav"\r\n',
                b"Content-Type: audio/wav\r\n\r\n",
                b"RIFFsynthetic-audio",
                b"\r\n",
                f"--{boundary}--\r\n".encode(),
            ]
        )
        status, headers, payload = self.request(
            "POST",
            "/v1/audio/transcriptions",
            body=multipart,
            headers={
                "Content-Type": f"multipart/form-data; boundary={boundary}",
                "Origin": "http://127.0.0.1:5173",
            },
        )
        self.assertEqual(status, 200)
        transcript = json.loads(payload)
        self.assertEqual(transcript["language"], "nan-TW")
        self.assertEqual(transcript["device"], "cpu")
        self.assertEqual(headers["x-request-id"], transcript["request_id"])

    def test_disallowed_origin_is_rejected(self) -> None:
        status, headers, payload = self.request(
            "GET",
            "/local/health",
            headers={"Origin": "https://example.invalid"},
        )
        self.assertEqual(status, 403)
        self.assertNotIn("access-control-allow-origin", headers)
        self.assertEqual(json.loads(payload)["code"], "VALIDATION_ERROR")

    def test_integration_web_origin_is_allowed(self) -> None:
        status, headers, payload = self.request(
            "GET",
            "/local/health",
            headers={"Origin": "http://127.0.0.1:5175"},
        )
        self.assertEqual(status, 200)
        self.assertEqual(headers["access-control-allow-origin"], "http://127.0.0.1:5175")
        self.assertEqual(json.loads(payload)["schema_version"], "0.1.0")


if __name__ == "__main__":
    unittest.main()
