#!/usr/bin/env python3
"""Run a bounded, metadata-only live evaluation against the MI300 gateway.

The script intentionally never writes prompts, image bytes, or model text. It
records only safe request metadata and a boolean schema-validation result.
"""

from __future__ import annotations

import argparse
import base64
import json
import subprocess
import time
import uuid
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


SCHEMA_VERSION = "0.1.0"
MODEL_REVISION = "d9748a51ae66354c4dad665aab2c71f26cf2c8cd"
PROMPT = (
    "請只回傳 JSON，answer 用繁體中文描述圖片中的主要教材情境，"
    "不要輸出 JSON 以外文字。"
)
RESPONSE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {"answer": {"type": "string"}},
    "required": ["answer"],
    "additionalProperties": False,
}


def _vram_sample() -> dict[str, Any]:
    """Return numeric AMD-SMI memory fields without retaining raw output."""

    try:
        result = subprocess.run(
            ["amd-smi", "monitor", "-v", "-g", "0", "--json"],
            check=False,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"error": type(exc).__name__}
    sample: dict[str, Any] = {"returncode": result.returncode}
    try:
        payload = json.loads(result.stdout)
        item = payload[0] if isinstance(payload, list) and payload else payload
        for source, target in (
            ("vram_total", "total_mb"),
            ("vram_used", "used_mb"),
            ("vram_free", "free_mb"),
        ):
            value = item.get(source, {}).get("value") if isinstance(item, dict) else None
            if isinstance(value, (int, float)):
                sample[target] = value
    except (json.JSONDecodeError, TypeError, AttributeError, IndexError):
        sample["parse_error"] = True
    return sample


def _request(endpoint: str, image_path: Path) -> dict[str, Any]:
    body = {
        "schema_version": SCHEMA_VERSION,
        "request_id": str(uuid.uuid4()),
        "image": {
            "media_type": "image/png",
            "content_base64": base64.b64encode(image_path.read_bytes()).decode("ascii"),
        },
        "prompt": PROMPT,
        "response_schema": RESPONSE_SCHEMA,
        "model_revision": MODEL_REVISION,
    }
    started = time.perf_counter()
    request = Request(
        endpoint,
        data=json.dumps(body, ensure_ascii=False, separators=(",", ":")).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urlopen(request, timeout=180) as response:
            status = response.status
            payload = json.load(response)
    except HTTPError as exc:
        try:
            error_payload = json.load(exc)
        except Exception:
            error_payload = {}
        return {
            "http_status": exc.code,
            "elapsed_ms": int((time.perf_counter() - started) * 1000),
            "error_code": error_payload.get("error", {}).get("code"),
        }
    except (URLError, TimeoutError) as exc:
        return {
            "http_status": None,
            "elapsed_ms": int((time.perf_counter() - started) * 1000),
            "error_code": type(exc).__name__,
        }
    output = payload.get("output", {})
    candidate = output.get("parsed_candidate")
    schema_valid = (
        isinstance(candidate, dict)
        and set(candidate) == {"answer"}
        and isinstance(candidate.get("answer"), str)
    )
    usage = output.get("usage") if isinstance(output.get("usage"), dict) else {}
    return {
        "http_status": status,
        "request_id": payload.get("request_id"),
        "latency_ms": payload.get("latency_ms"),
        "queue_ms": payload.get("queue_ms"),
        "inference_ms": payload.get("inference_ms"),
        "prompt_tokens": usage.get("prompt_tokens"),
        "completion_tokens": usage.get("completion_tokens"),
        "total_tokens": usage.get("total_tokens"),
        "finish_reason": output.get("finish_reason"),
        "parsed_candidate_type": type(candidate).__name__,
        "schema_valid": schema_valid,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--endpoint", default="http://127.0.0.1:8100/internal/vlm/generate")
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--repeat", type=int, default=2)
    args = parser.parse_args()
    images = sorted(args.dataset.glob("*.png"))
    if len(images) < 10:
        raise SystemExit(f"expected at least 10 PNG fixtures, found {len(images)}")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    vram_path = args.output.with_name("vram-samples.jsonl")
    before = _vram_sample()
    results: list[dict[str, Any]] = []
    with args.output.open("w", encoding="utf-8") as result_file, vram_path.open(
        "w", encoding="utf-8"
    ) as vram_file:
        vram_file.write(json.dumps({"phase": "before", **before}) + "\n")
        for index in range(args.repeat):
            for image_path in images[:10]:
                metadata = _request(args.endpoint, image_path)
                record = {
                    "index": len(results) + 1,
                    "fixture": image_path.name,
                    **metadata,
                }
                results.append(record)
                result_file.write(json.dumps(record, ensure_ascii=False) + "\n")
                result_file.flush()
                vram_file.write(
                    json.dumps({"index": len(results), **_vram_sample()}) + "\n"
                )
                vram_file.flush()
                print(
                    record.get("index"),
                    record.get("fixture"),
                    record.get("http_status"),
                    record.get("latency_ms", record.get("elapsed_ms")),
                    record.get("error_code", "ok"),
                    flush=True,
                )
        after = _vram_sample()
        vram_file.write(json.dumps({"phase": "after", **after}) + "\n")
    successes = sum(item.get("http_status") == 200 for item in results)
    valid = sum(item.get("schema_valid") is True for item in results)
    print(json.dumps({"requests": len(results), "successes": successes, "schema_valid": valid}))
    return 0 if successes == len(results) and valid == len(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
