"""Run the reproducible Breeze-ASR-26 CPU baseline benchmark.

The benchmark consumes an operator-supplied, authorized audio manifest.  It
does not copy audio into the report.  By default it records only timing,
resource, status, and transcript hashes; ``--include-transcripts`` is an
explicit opt-in for a non-student test set.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from importlib import metadata
from pathlib import Path
import statistics
import sys
import time
import unicodedata
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
SERVICE_DIR = REPO_ROOT / "services" / "speech-local"
if str(SERVICE_DIR) not in sys.path:
    sys.path.insert(0, str(SERVICE_DIR))

from gateway import _memory_snapshot  # noqa: E402
from workers import (  # noqa: E402
    BREEZE_ASR_COMPUTE_TYPE,
    BREEZE_ASR_DEFAULT_CPU_THREADS,
    BREEZE_ASR_MODEL_ID,
    BREEZE_ASR_MODEL_REVISION,
    BreezeASR26CPUWorker,
    CancellationToken,
    SpeechWorkerError,
)


REQUIRED_CATEGORIES = {
    "mandarin",
    "mixed",
    "child_slow",
    "noise",
    "silence",
    "too_short",
}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--manifest",
        type=Path,
        required=True,
        help="JSON manifest with at least 20 authorized audio cases.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=SERVICE_DIR / ".runtime" / "breeze-cpu-benchmark.json",
    )
    parser.add_argument("--model-path", default=None)
    parser.add_argument("--model-id", default=BREEZE_ASR_MODEL_ID)
    parser.add_argument("--model-revision", default=BREEZE_ASR_MODEL_REVISION)
    parser.add_argument("--compute-type", default=BREEZE_ASR_COMPUTE_TYPE)
    parser.add_argument("--cpu-threads", default=BREEZE_ASR_DEFAULT_CPU_THREADS, type=int)
    parser.add_argument("--beam-size", default=5, type=int)
    parser.add_argument("--local-files-only", action="store_true")
    parser.add_argument("--no-vad", action="store_true")
    parser.add_argument(
        "--include-transcripts",
        action="store_true",
        help="Include raw/normalized text; use only with an authorized non-student set.",
    )
    args = parser.parse_args(argv)

    try:
        cases, manifest_meta = _load_manifest(args.manifest)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"benchmark manifest error: {exc}", file=sys.stderr)
        return 2

    missing = [case["id"] for case in cases if _resolve_audio(args.manifest, case["audio_path"]) is None]
    if missing:
        print(
            "benchmark audio files missing for: " + ", ".join(missing),
            file=sys.stderr,
        )
        return 2

    worker = BreezeASR26CPUWorker(
        model_path=args.model_path,
        model_id=args.model_id,
        revision=args.model_revision,
        compute_type=args.compute_type,
        cpu_threads=args.cpu_threads,
        beam_size=args.beam_size,
        vad_enabled=not args.no_vad,
        local_files_only=args.local_files_only,
    )
    rss_before = _memory_snapshot().get("process_rss_bytes")
    warmup_started = time.perf_counter()
    try:
        worker.warmup(CancellationToken())
    except SpeechWorkerError as exc:
        print(f"benchmark model error: {exc.safe_message}", file=sys.stderr)
        return 3
    warmup_ms = round((time.perf_counter() - warmup_started) * 1000.0, 3)

    results: list[dict[str, Any]] = []
    peak_rss = rss_before
    for case in cases:
        result = _run_case(
            worker,
            args.manifest,
            case,
            include_transcript=args.include_transcripts,
        )
        results.append(result)
        current_rss = _memory_snapshot().get("process_rss_bytes")
        if current_rss is not None:
            peak_rss = max(peak_rss or current_rss, current_rss)

    report = {
        "schema_version": "0.1.0",
        "benchmark": "agent-b-stage05-breeze-asr-26-cpu",
        "manifest": manifest_meta,
        "runtime": {
            "python": sys.version.split()[0],
            "faster_whisper": _package_version("faster-whisper"),
            "numpy": _package_version("numpy"),
            "model_id": args.model_id,
            "model_revision": args.model_revision,
            "compute_type": args.compute_type,
            "device": "cpu",
            "cpu_threads": args.cpu_threads,
            "beam_size": args.beam_size,
            "vad_enabled": not args.no_vad,
        },
        "resource": {
            "rss_before_bytes": rss_before,
            "rss_after_bytes": _memory_snapshot().get("process_rss_bytes"),
            "rss_peak_bytes": peak_rss,
            "memory_snapshot": _memory_snapshot(),
            "warmup_ms": warmup_ms,
        },
        "summary": _summarize(results),
        "cases": results,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(report["summary"], ensure_ascii=False, indent=2))
    print(f"report: {args.output}")
    worker.close()
    return 0 if report["summary"]["failed"] == 0 else 4


def _load_manifest(path: Path) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(payload, list):
        cases = payload
        meta: dict[str, Any] = {"path": path.name}
    elif isinstance(payload, dict):
        cases = payload.get("cases")
        meta = {
            "path": path.name,
            "dataset": payload.get("dataset"),
            "license": payload.get("license"),
            "authorization": payload.get("authorization"),
        }
    else:
        raise ValueError("manifest must be an array or an object with cases")
    if not isinstance(cases, list) or len(cases) < 20:
        raise ValueError("manifest must contain at least 20 cases")
    categories = {case.get("category") for case in cases if isinstance(case, dict)}
    missing_categories = sorted(REQUIRED_CATEGORIES - categories)
    if missing_categories:
        raise ValueError("manifest is missing categories: " + ", ".join(missing_categories))
    normalized: list[dict[str, Any]] = []
    ids: set[str] = set()
    for raw in cases:
        if not isinstance(raw, dict):
            raise ValueError("each case must be an object")
        case_id = raw.get("id")
        category = raw.get("category")
        audio_path = raw.get("audio_path")
        expected = raw.get("expected", "success")
        if not isinstance(case_id, str) or not case_id or case_id in ids:
            raise ValueError("case ids must be non-empty and unique")
        if not isinstance(category, str) or not category:
            raise ValueError(f"case {case_id} is missing category")
        if not isinstance(audio_path, str) or not audio_path:
            raise ValueError(f"case {case_id} is missing audio_path")
        if expected not in {"success", "rejection"}:
            raise ValueError(f"case {case_id} expected must be success or rejection")
        ids.add(case_id)
        normalized.append(
            {
                "id": case_id,
                "category": category,
                "audio_path": audio_path,
                "language": raw.get("language", "nan-TW"),
                "reference_text": raw.get("reference_text"),
                "expected": expected,
            }
        )
    return normalized, meta


def _resolve_audio(manifest: Path, audio_path: str) -> Path | None:
    candidate = Path(audio_path).expanduser()
    candidates = [candidate]
    if not candidate.is_absolute():
        candidates.extend([REPO_ROOT / candidate, manifest.parent / candidate])
    for item in candidates:
        try:
            if item.is_file():
                return item.resolve()
        except OSError:
            continue
    return None


def _run_case(
    worker: BreezeASR26CPUWorker,
    manifest: Path,
    case: dict[str, Any],
    *,
    include_transcript: bool,
) -> dict[str, Any]:
    audio_path = _resolve_audio(manifest, case["audio_path"])
    if audio_path is None:  # checked before model load; defensive only
        return {
            "id": case["id"],
            "category": case["category"],
            "expected": case["expected"],
            "status": "missing",
        }
    audio = audio_path.read_bytes()
    started = time.perf_counter()
    try:
        transcript = worker.transcribe(
            audio=audio,
            audio_size=len(audio),
            language=case["language"],
            device="cpu",
            token=CancellationToken(),
        )
        status = "success" if case["expected"] == "success" else "unexpected_success"
        failure: dict[str, Any] = {}
    except SpeechWorkerError as exc:
        transcript = ""
        status = "expected_rejection" if case["expected"] == "rejection" else "failed"
        failure = {"reason": exc.reason, "message": exc.safe_message}
    elapsed_ms = round((time.perf_counter() - started) * 1000.0, 3)
    metrics = worker.last_metrics or {}
    input_duration = metrics.get("input_duration_s") or 0.0
    output: dict[str, Any] = {
        "id": case["id"],
        "category": case["category"],
        "expected": case["expected"],
        "status": status,
        "audio_bytes": len(audio),
        "input_duration_s": input_duration,
        "elapsed_ms": elapsed_ms,
        "rtf": round(elapsed_ms / 1000.0 / input_duration, 4) if input_duration else None,
        "preprocess": metrics,
        "transcript_sha256": hashlib.sha256(transcript.encode("utf-8")).hexdigest(),
        "transcript_chars": len(transcript),
    }
    reference = case.get("reference_text")
    if isinstance(reference, str):
        output["cer"] = _cer(reference, transcript)
    if include_transcript:
        output["transcript_raw"] = transcript
        output["transcript_normalized"] = _normalize_transcript(transcript)
    if failure:
        output["error"] = failure
    return output


def _normalize_transcript(text: str) -> str:
    normalized = unicodedata.normalize("NFKC", text)
    return " ".join(normalized.split())


def _cer(reference: str, hypothesis: str) -> float:
    ref = list(_normalize_for_cer(reference))
    hyp = list(_normalize_for_cer(hypothesis))
    if not ref:
        return 0.0 if not hyp else 1.0
    previous = list(range(len(hyp) + 1))
    for index, ref_char in enumerate(ref, start=1):
        current = [index]
        for hyp_index, hyp_char in enumerate(hyp, start=1):
            current.append(
                min(
                    current[-1] + 1,
                    previous[hyp_index] + 1,
                    previous[hyp_index - 1] + (ref_char != hyp_char),
                )
            )
        previous = current
    return round(previous[-1] / len(ref), 4)


def _normalize_for_cer(text: str) -> str:
    return "".join(_normalize_transcript(text).split())


def _summarize(results: list[dict[str, Any]]) -> dict[str, Any]:
    successes = [item for item in results if item["status"] == "success"]
    expected_rejections = [item for item in results if item["status"] == "expected_rejection"]
    failures = [
        item
        for item in results
        if item["status"] in {"failed", "unexpected_success", "missing"}
    ]
    elapsed = sorted(float(item["elapsed_ms"]) for item in successes)
    rtfs = [float(item["rtf"]) for item in successes if item.get("rtf") is not None]
    return {
        "total": len(results),
        "success": len(successes),
        "expected_rejection": len(expected_rejections),
        "failed": len(failures),
        "passed": len(results) - len(failures),
        "mean_elapsed_ms": round(statistics.mean(elapsed), 3) if elapsed else None,
        "p95_elapsed_ms": round(_percentile(elapsed, 0.95), 3) if elapsed else None,
        "mean_rtf": round(statistics.mean(rtfs), 4) if rtfs else None,
        "p95_rtf": round(_percentile(rtfs, 0.95), 4) if rtfs else None,
        "categories": {
            category: sum(item["category"] == category for item in results)
            for category in sorted({item["category"] for item in results})
        },
    }


def _percentile(values: list[float], fraction: float) -> float:
    if len(values) == 1:
        return values[0]
    position = (len(values) - 1) * fraction
    lower = int(position)
    upper = min(lower + 1, len(values) - 1)
    weight = position - lower
    return values[lower] * (1 - weight) + values[upper] * weight


def _package_version(name: str) -> str | None:
    try:
        return metadata.version(name)
    except metadata.PackageNotFoundError:
        return None


if __name__ == "__main__":
    raise SystemExit(main())
