"""Run the privacy-safe Stage 10 speech/session release gate.

The default path talks only to the localhost Speech Gateway and Core API. It
uses a generated in-memory WAV as the recording source; it never opens a
microphone and never writes audio or transcripts. The default launcher profile
uses deterministic Mock ASR/TTS, while ``--speech-profile cpu`` can exercise
the pre-provisioned CPU workers without downloading model weights.
"""

from __future__ import annotations

import argparse
import base64
import ctypes
import io
import json
import math
import os
from pathlib import Path
import struct
import time
import uuid
import wave
from urllib import error, request


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SPEECH_URL = "http://127.0.0.1:8200"
DEFAULT_CORE_URL = "http://127.0.0.1:8000"
DEFAULT_PROCESS_STATE = REPOSITORY_ROOT / "apps" / "core-api" / ".runtime" / "stage10-demo" / "processes.json"
UTTERANCE_PATH = REPOSITORY_ROOT / "fixtures" / "contracts" / "v0.1" / "observer" / "success.utterance.json"


class GateError(RuntimeError):
    """Stable, privacy-safe gate failure."""


def percentile(values: list[float], percentile_value: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    rank = (len(ordered) - 1) * percentile_value / 100.0
    lower = math.floor(rank)
    upper = math.ceil(rank)
    if lower == upper:
        return ordered[lower]
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (rank - lower)


def make_recording_wav() -> bytes:
    """Create a short synthetic recording in memory for the loopback gate."""

    sample_rate = 16_000
    duration = 0.22
    frequency = 440.0
    samples = int(sample_rate * duration)
    output = io.BytesIO()
    with wave.open(output, "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(sample_rate)
        frames = b"".join(
            struct.pack("<h", int(0.15 * 32767 * math.sin(2 * math.pi * frequency * index / sample_rate)))
            for index in range(samples)
        )
        wav_file.writeframes(frames)
    return output.getvalue()


def make_demo_jpeg() -> bytes:
    try:
        from PIL import Image
    except ImportError as exc:  # pragma: no cover - only hit outside the Core venv
        raise GateError("Pillow is required for Core lesson provisioning; run with apps/core-api/.venv Python.") from exc
    image = Image.new("RGB", (640, 480), (235, 242, 248))
    output = io.BytesIO()
    image.save(output, format="JPEG", quality=88)
    return output.getvalue()


def multipart_body(image: bytes, *, boundary: str) -> bytes:
    chunks = [
        f"--{boundary}\r\n".encode(),
        b'Content-Disposition: form-data; name="image"; filename="stage10-synthetic.jpg"\r\n',
        b"Content-Type: image/jpeg\r\n\r\n",
        image,
        b"\r\n",
        f"--{boundary}\r\n".encode(),
        b'Content-Disposition: form-data; name="language"\r\n\r\n',
        b"nan-TW\r\n",
        f"--{boundary}\r\n".encode(),
        b'Content-Disposition: form-data; name="use_fixture_on_failure"\r\n\r\n',
        b"true\r\n",
        f"--{boundary}--\r\n".encode(),
    ]
    return b"".join(chunks)


def multipart_audio(audio: bytes, *, boundary: str) -> bytes:
    chunks = [
        f"--{boundary}\r\n".encode(),
        b'Content-Disposition: form-data; name="file"; filename="stage10-recording.wav"\r\n',
        b"Content-Type: audio/wav\r\n\r\n",
        audio,
        b"\r\n",
        f"--{boundary}\r\n".encode(),
        b'Content-Disposition: form-data; name="language"\r\n\r\n',
        b"nan-TW\r\n",
        f"--{boundary}\r\n".encode(),
        b'Content-Disposition: form-data; name="device_preference"\r\n\r\n',
        b"cpu\r\n",
        f"--{boundary}--\r\n".encode(),
    ]
    return b"".join(chunks)


def http_call(
    method: str,
    url: str,
    *,
    body: bytes | None = None,
    content_type: str | None = None,
    timeout: float = 15.0,
    headers: dict[str, str] | None = None,
) -> tuple[int, dict[str, str], bytes]:
    call_headers = {"User-Agent": "meichu-stage10-gate"}
    if headers:
        call_headers.update(headers)
    if content_type:
        call_headers["Content-Type"] = content_type
    try:
        with request.urlopen(request.Request(url, data=body, headers=call_headers, method=method), timeout=timeout) as response:
            return response.status, dict(response.headers.items()), response.read()
    except error.HTTPError as exc:
        return exc.code, dict(exc.headers.items()), exc.read()
    except (error.URLError, TimeoutError, OSError) as exc:
        raise GateError(f"endpoint_unreachable:{url.split('/', 3)[-1]}") from exc


def json_call(method: str, url: str, payload: dict[str, object], *, headers: dict[str, str] | None = None) -> dict[str, object]:
    status, _response_headers, body = http_call(
        method,
        url,
        body=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        content_type="application/json",
        headers=headers,
    )
    try:
        parsed = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise GateError(f"invalid_json_response:{status}") from exc
    if status >= 400:
        code = parsed.get("code") if isinstance(parsed, dict) else "http_error"
        raise GateError(f"{code}:{status}")
    if not isinstance(parsed, dict):
        raise GateError("json_object_required")
    return parsed


def random_headers(prefix: str, *, revision: int | None = None) -> dict[str, str]:
    headers = {
        "X-Request-ID": str(uuid.uuid4()),
        "Idempotency-Key": f"stage10-{prefix}-{uuid.uuid4()}",
    }
    if revision is not None:
        headers["X-Session-Revision"] = str(revision)
    return headers


def current_process_rss(pid: int) -> int | None:
    if os.name == "nt":
        process_query_limited_information = 0x1000
        handle = ctypes.windll.kernel32.OpenProcess(process_query_limited_information, False, pid)
        if not handle:
            return None
        class ProcessMemoryCounters(ctypes.Structure):
            _fields_ = [
                ("cb", ctypes.c_ulong),
                ("PageFaultCount", ctypes.c_ulong),
                ("PeakWorkingSetSize", ctypes.c_size_t),
                ("WorkingSetSize", ctypes.c_size_t),
                ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                ("PagefileUsage", ctypes.c_size_t),
                ("PeakPagefileUsage", ctypes.c_size_t),
            ]
        counters = ProcessMemoryCounters()
        counters.cb = ctypes.sizeof(counters)
        try:
            ok = ctypes.windll.psapi.GetProcessMemoryInfo(handle, ctypes.byref(counters), counters.cb)
            return int(counters.WorkingSetSize) if ok else None
        finally:
            ctypes.windll.kernel32.CloseHandle(handle)
    try:
        return int(Path(f"/proc/{pid}/status").read_text(encoding="utf-8").split("VmRSS:", 1)[1].split()[0]) * 1024
    except (FileNotFoundError, IndexError, ValueError):
        return None


def process_memory_snapshot(state_path: Path) -> dict[str, int]:
    if not state_path.exists():
        return {}
    try:
        state = json.loads(state_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    snapshot: dict[str, int] = {}
    for entry in state.get("processes", []):
        if not isinstance(entry, dict) or not isinstance(entry.get("pid"), int):
            continue
        rss = current_process_rss(entry["pid"])
        if rss is not None:
            snapshot[str(entry.get("role", entry["pid"]))] = rss
    return snapshot


def ensure_lesson(core_url: str, lesson_id: str | None) -> str:
    if lesson_id:
        return lesson_id
    boundary = f"stage10-{uuid.uuid4().hex}"
    status, _headers, body = http_call(
        "POST",
        f"{core_url}/api/lessons/analyze",
        body=multipart_body(make_demo_jpeg(), boundary=boundary),
        content_type=f"multipart/form-data; boundary={boundary}",
        headers={"X-Request-ID": str(uuid.uuid4())},
        timeout=30,
    )
    if status >= 400:
        raise GateError(f"lesson_provision_failed:{status}")
    try:
        payload = json.loads(body.decode("utf-8"))
        return str(payload["lesson_id"])
    except (UnicodeDecodeError, json.JSONDecodeError, KeyError, TypeError) as exc:
        raise GateError("lesson_provision_invalid") from exc


def create_session(core_url: str, lesson_id: str) -> tuple[str, int]:
    payload = json_call(
        "POST",
        f"{core_url}/api/sessions",
        {"schema_version": "0.1.0", "lesson_id": lesson_id},
        headers=random_headers("session-create"),
    )
    return str(payload["session_id"]), int(payload.get("revision", 0))


def session_action(core_url: str, session_id: str, action: str, revision: int) -> int:
    payload = json_call(
        "POST",
        f"{core_url}/api/sessions/{session_id}/actions",
        {"schema_version": "0.1.0", "action": action, "expected_revision": revision},
        headers=random_headers(f"action-{action}", revision=revision),
    )
    return int(payload.get("revision", revision + 1))


def judge_turn(core_url: str, lesson_id: str, transcript: str) -> str:
    session_id, revision = create_session(core_url, lesson_id)
    revision = session_action(core_url, session_id, "next", revision)
    revision = session_action(core_url, session_id, "next", revision)
    revision = session_action(core_url, session_id, "start_answer", revision)
    result = json_call(
        "POST",
        f"{core_url}/api/sessions/{session_id}/turns",
        {
            "schema_version": "0.1.0",
            "transcript": transcript,
            "input_mode": "voice",
            "asr_device": "cpu",
            "expected_revision": revision,
        },
        headers=random_headers("turn", revision=revision),
    )
    return str(result.get("result", "unknown"))


def speech_cycle(speech_url: str, utterance: dict[str, object], recording: bytes) -> str:
    tts_payload = {"schema_version": "0.1.0", "utterance": utterance, "format": "wav"}
    status, _headers, tts_audio = http_call(
        "POST",
        f"{speech_url}/v1/audio/speech",
        body=json.dumps(tts_payload, ensure_ascii=False).encode("utf-8"),
        content_type="application/json",
        headers={"X-Request-ID": str(uuid.uuid4())},
    )
    if status >= 400 or not tts_audio.startswith(b"RIFF"):
        raise GateError(f"tts_failed:{status}")
    boundary = f"stage10-audio-{uuid.uuid4().hex}"
    status, _headers, body = http_call(
        "POST",
        f"{speech_url}/v1/audio/transcriptions",
        body=multipart_audio(recording, boundary=boundary),
        content_type=f"multipart/form-data; boundary={boundary}",
        headers={"X-Request-ID": str(uuid.uuid4())},
    )
    if status >= 400:
        raise GateError(f"asr_failed:{status}")
    try:
        payload = json.loads(body.decode("utf-8"))
        transcript = str(payload["text"]).strip()
    except (UnicodeDecodeError, json.JSONDecodeError, KeyError, TypeError) as exc:
        raise GateError("asr_invalid_response") from exc
    if not transcript:
        raise GateError("asr_empty_transcript")
    return transcript


def run(args: argparse.Namespace) -> dict[str, object]:
    utterance = json.loads(UTTERANCE_PATH.read_text(encoding="utf-8"))
    if not isinstance(utterance, dict):
        raise GateError("utterance_fixture_invalid")
    recording = make_recording_wav()
    warmup_status, _headers, _body = http_call(
        "POST",
        f"{args.speech_url}/local/warmup",
        body=json.dumps({"services": ["asr", "tts"]}).encode("utf-8"),
        content_type="application/json",
        headers={"X-Request-ID": str(uuid.uuid4())},
    )
    warmup = "ready" if warmup_status < 400 else "degraded"
    lesson_id = None if args.skip_core else ensure_lesson(args.core_url, args.lesson_id)
    latencies: list[float] = []
    failures: list[str] = []
    judge_results: dict[str, int] = {}
    memory_samples: list[dict[str, int]] = []
    started = time.perf_counter()
    for index in range(args.rounds):
        cycle_start = time.perf_counter()
        try:
            transcript = speech_cycle(args.speech_url, utterance, recording)
            if args.skip_core:
                judge = "local_nonempty_transcript"
            else:
                judge = judge_turn(args.core_url, lesson_id or "", transcript)
            judge_results[judge] = judge_results.get(judge, 0) + 1
        except GateError as exc:
            failures.append(str(exc).split(":", 1)[0])
        latencies.append((time.perf_counter() - cycle_start) * 1000)
        memory_samples.append(process_memory_snapshot(args.process_state))
        if args.progress and ((index + 1) % args.progress == 0 or index + 1 == args.rounds):
            print(f"stage10 speech gate: {index + 1}/{args.rounds}")
    elapsed = (time.perf_counter() - started) * 1000
    all_memory = [value for sample in memory_samples for value in sample.values()]
    memory_by_role: dict[str, dict[str, int | None]] = {}
    for role in sorted({role for sample in memory_samples for role in sample}):
        values = [sample[role] for sample in memory_samples if role in sample]
        memory_by_role[role] = {
            "start_bytes": values[0] if values else None,
            "end_bytes": values[-1] if values else None,
            "peak_bytes": max(values) if values else None,
            "delta_bytes": values[-1] - values[0] if values else None,
        }
    return {
        "schema_version": "stage10-release-gate.v1",
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "speech_profile": args.speech_profile,
        "rounds_requested": args.rounds,
        "success_count": args.rounds - len(failures),
        "failure_count": len(failures),
        "failure_codes": {code: failures.count(code) for code in sorted(set(failures))},
        "warmup": {"status": warmup, "http_status": warmup_status},
        "judge": {"mode": "core-api" if not args.skip_core else "local_nonempty_transcript", "results": judge_results},
        "latency_ms": {
            "count": len(latencies),
            "mean": round(sum(latencies) / len(latencies), 2) if latencies else None,
            "p50": round(percentile(latencies, 50) or 0, 2) if latencies else None,
            "p95": round(percentile(latencies, 95) or 0, 2) if latencies else None,
            "max": round(max(latencies), 2) if latencies else None,
            "wall_clock": round(elapsed, 2),
        },
        "memory": {
            "source": "GetProcessMemoryInfo working set for launcher-managed processes",
            "sample_count": len(memory_samples),
            "roles": memory_by_role,
            "peak_total_bytes": max((sum(sample.values()) for sample in memory_samples), default=None),
            "delta_total_bytes": (sum(memory_samples[-1].values()) - sum(memory_samples[0].values())) if memory_samples and memory_samples[0] and memory_samples[-1] else None,
        },
        "privacy": {
            "status": "ready",
            "audio_persisted": False,
            "transcripts_persisted": False,
            "note": "Synthetic recording and transcript stay in memory; no microphone permission is requested by this gate.",
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Stage 10 privacy-safe 50-cycle speech/session gate")
    parser.add_argument("--speech-url", default=DEFAULT_SPEECH_URL)
    parser.add_argument("--core-url", default=DEFAULT_CORE_URL)
    parser.add_argument("--speech-profile", choices=("mock", "cpu"), default="mock")
    parser.add_argument("--rounds", type=int, default=50)
    parser.add_argument("--lesson-id")
    parser.add_argument("--skip-core", action="store_true", help="Run Speech loop only and use local transcript validation as judge.")
    parser.add_argument("--process-state", type=Path, default=DEFAULT_PROCESS_STATE)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--progress", type=int, default=10)
    args = parser.parse_args()
    if args.rounds < 1 or args.rounds > 500:
        parser.error("--rounds must be between 1 and 500")
    try:
        report = run(args)
    except (OSError, GateError) as exc:
        print(f"Stage 10 gate blocked: {exc}")
        return 2
    encoded = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(encoded, encoding="utf-8")
        print(f"Stage 10 gate report: {args.output}")
    print(
        f"Stage 10 gate: {report['success_count']}/{report['rounds_requested']} cycles; "
        f"p50={report['latency_ms']['p50']}ms p95={report['latency_ms']['p95']}ms"
    )
    return 0 if report["failure_count"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
