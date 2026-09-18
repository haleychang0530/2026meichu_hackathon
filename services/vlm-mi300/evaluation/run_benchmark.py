#!/usr/bin/env python3
"""Run the fixed Stage 02 image/schema workload against an OpenAI-compatible VLM."""

from __future__ import annotations

import argparse
import base64
import http.client
import json
import statistics
import time
from pathlib import Path


def post_json(url: str, payload: dict, timeout: float) -> tuple[int, dict, float]:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    scheme, rest = url.split("://", 1)
    authority, separator, request_path = rest.partition("/")
    if ":" in authority:
        host, port_text = authority.rsplit(":", 1)
        port = int(port_text)
    else:
        host = authority
        port = 443 if scheme == "https" else 80
    connection_type = http.client.HTTPSConnection if scheme == "https" else http.client.HTTPConnection
    connection = connection_type(host, port, timeout=timeout)
    started = time.perf_counter()
    try:
        connection.request("POST", "/" + request_path if separator else "/", body=body,
                           headers={"Content-Type": "application/json"})
        response = connection.getresponse()
        raw = response.read()
        status = response.status
    except (OSError, http.client.HTTPException) as error:
        raw = json.dumps({"_transport_error": repr(error)}).encode("utf-8")
        status = 599
    finally:
        connection.close()
    elapsed = time.perf_counter() - started
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        parsed = {"_raw_body": raw.decode("utf-8", errors="replace")}
    return status, parsed, elapsed


def validate_shape(value: object, schema_version: str = "stage02-eval.v1") -> tuple[bool, list[str]]:
    if not isinstance(value, dict):
        return False, ["root_not_object"]
    required = {
        "schema_version", "topic", "source_text", "vocabulary", "scene", "original_activity",
        "learning_objective", "accessible_activity", "quality_warnings", "confidence",
    }
    errors = []
    if set(value) != required:
        errors.append(f"keys:{sorted(value)}")
    if value.get("schema_version") != schema_version:
        errors.append("schema_version")
    if not isinstance(value.get("vocabulary"), list):
        errors.append("vocabulary")
    if not isinstance(value.get("quality_warnings"), list):
        errors.append("quality_warnings")
    confidence = value.get("confidence")
    if not isinstance(confidence, (int, float)) or not 0 <= confidence <= 1:
        errors.append("confidence")
    return not errors, errors


def image_data_url(path: Path) -> str:
    return "data:image/png;base64," + base64.b64encode(path.read_bytes()).decode("ascii")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:8000/v1")
    parser.add_argument("--model", required=True)
    parser.add_argument("--revision", required=True)
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--prompt", type=Path, default=Path(__file__).with_name("prompt.txt"))
    parser.add_argument("--schema", type=Path, default=Path(__file__).with_name("response_schema.json"))
    parser.add_argument("--runs", type=int, default=3)
    parser.add_argument("--warmup", type=int, default=1)
    parser.add_argument("--timeout", type=float, default=180.0)
    parser.add_argument("--max-tokens", type=int, default=1024)
    args = parser.parse_args()

    manifest = json.loads((args.dataset / "manifest.json").read_text(encoding="utf-8"))
    prompt = args.prompt.read_text(encoding="utf-8")
    schema = json.loads(args.schema.read_text(encoding="utf-8"))
    args.output.mkdir(parents=True, exist_ok=True)
    records = []
    endpoint = args.base_url.rstrip("/") + "/chat/completions"

    for case in manifest["cases"]:
        image_url = image_data_url(args.dataset / case["file"])
        payload = {
            "model": args.model,
            "messages": [{"role": "user", "content": [
                {"type": "text", "text": prompt},
                {"type": "image_url", "image_url": {"url": image_url}},
            ]}],
            "response_format": {"type": "json_schema", "json_schema": {
                "name": "stage02_textbook_analysis", "schema": schema,
            }},
            "temperature": 0,
            "top_p": 1,
            "max_tokens": args.max_tokens,
            "stream": False,
        }
        for run in range(args.warmup + args.runs):
            status, response, elapsed = post_json(endpoint, payload, args.timeout)
            content = None
            parsed_content = None
            parse_error = None
            try:
                content = response["choices"][0]["message"]["content"]
                parsed_content = json.loads(content)
            except (KeyError, IndexError, TypeError, json.JSONDecodeError) as error:
                parse_error = repr(error)
            shape_ok, shape_errors = validate_shape(parsed_content)
            usage = response.get("usage", {}) if isinstance(response, dict) else {}
            records.append({
                "schema_version": "stage02-raw-result.v1",
                "model": args.model,
                "revision": args.revision,
                "case_id": case["id"],
                "condition": case["condition"],
                "run": run,
                "warmup": run < args.warmup,
                "http_status": status,
                "latency_seconds": elapsed,
                "prompt_tokens": usage.get("prompt_tokens"),
                "completion_tokens": usage.get("completion_tokens"),
                "total_tokens": usage.get("total_tokens"),
                "completion_tokens_per_second": (
                    usage.get("completion_tokens") / elapsed if usage.get("completion_tokens") else None
                ),
                "content": content,
                "parsed_content": parsed_content,
                "json_parse_ok": parsed_content is not None,
                "schema_shape_ok": shape_ok,
                "schema_shape_errors": shape_errors,
                "parse_error": parse_error,
                "full_response": response,
            })
            print(f"{case['id']} run={run} status={status} latency={elapsed:.3f}s json={parsed_content is not None} schema={shape_ok}", flush=True)

    target = args.output / "raw_results.jsonl"
    target.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in records), encoding="utf-8")
    measured = [row for row in records if not row["warmup"]]
    latencies = sorted(row["latency_seconds"] for row in measured)
    p95_index = max(0, min(len(latencies) - 1, int((len(latencies) - 1) * 0.95 + 0.5)))
    token_rates = [
        row["completion_tokens_per_second"]
        for row in measured
        if row["completion_tokens_per_second"] is not None
    ]
    summary = {
        "model": args.model,
        "revision": args.revision,
        "samples": len(measured),
        "p50_seconds": statistics.median(latencies),
        "p95_seconds": latencies[p95_index],
        "json_parse_rate": sum(row["json_parse_ok"] for row in measured) / len(measured),
        "schema_shape_rate": sum(row["schema_shape_ok"] for row in measured) / len(measured),
        "http_success_rate": sum(row["http_status"] == 200 for row in measured) / len(measured),
        "mean_completion_tokens_per_second": statistics.fmean(token_rates) if token_rates else None,
    }
    (args.output / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
