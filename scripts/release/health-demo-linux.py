#!/usr/bin/env python3
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import shutil
import time
from urllib.request import urlopen


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
RUNTIME_ROOT = REPOSITORY_ROOT / "apps" / "core-api" / ".runtime" / "stage10-demo"


def endpoint(name: str, url: str, *, parse_json: bool = False) -> dict[str, object]:
    started = time.monotonic()
    try:
        with urlopen(url, timeout=4) as response:
            body = response.read()
            status = response.status
        payload = json.loads(body) if parse_json else None
        result = "ready"
        error = None
    except Exception:
        status = None
        payload = None
        result = "offline"
        error = "服務未回應或回應無法解析"
    return {
        "endpoint": {
            "name": name,
            "status": result,
            "http_status": status,
            "latency_ms": round((time.monotonic() - started) * 1000, 2),
            "uri": url,
            "error": error,
        },
        "payload": payload,
    }


def memory_snapshot() -> dict[str, int | str | None]:
    values: dict[str, int] = {}
    try:
        for line in Path("/proc/meminfo").read_text(encoding="utf-8").splitlines():
            key, raw = line.split(":", 1)
            values[key] = int(raw.strip().split()[0]) * 1024
    except (OSError, ValueError):
        return {"status": "not_available", "physical_total_bytes": None, "available_bytes": None}
    return {"status": "ready", "physical_total_bytes": values.get("MemTotal"), "available_bytes": values.get("MemAvailable")}


def process_snapshot(state: dict[str, object]) -> list[dict[str, object]]:
    rows = []
    for entry in state.get("processes", []):
        pid = int(entry["pid"])
        proc = Path("/proc") / str(pid)
        rss = None
        try:
            for line in (proc / "status").read_text(encoding="utf-8").splitlines():
                if line.startswith("VmRSS:"):
                    rss = int(line.split()[1]) * 1024
                    break
        except (OSError, ValueError):
            pass
        rows.append({"role": entry["role"], "pid": pid, "alive": proc.exists(), "working_set_bytes": rss})
    return rows


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=RUNTIME_ROOT / "health.json")
    args = parser.parse_args()
    try:
        state = json.loads((RUNTIME_ROOT / "processes.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        state = {}
    endpoints = [
        endpoint("frontend", "http://127.0.0.1:5173/health"),
        endpoint("core-api", "http://127.0.0.1:8000/api/health", parse_json=True),
        endpoint("speech-gateway", "http://127.0.0.1:8200/local/health", parse_json=True),
    ]
    core = endpoints[1]["payload"] or {}
    services = [
        {
            "name": item.get("service"),
            "status": item.get("status"),
            "device": item.get("device"),
            "model_revision": item.get("model_revision"),
            "queue_depth": item.get("queue_depth"),
        }
        for item in core.get("services", [])
    ]
    overall = "ready"
    if any(item["endpoint"]["status"] == "offline" for item in endpoints):
        overall = "offline"
    elif any(item.get("status") != "ready" for item in services):
        overall = "degraded"
    disk = shutil.disk_usage(REPOSITORY_ROOT)
    report = {
        "schema_version": "stage10-health.v1-linux",
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "overall_status": overall,
        "profile": state.get("mode"),
        "cpu_only_profile": {"status": "ready", "npu": "disabled"},
        "endpoints": endpoints,
        "services": services,
        "resources": {
            "memory": memory_snapshot(),
            "storage": {"status": "ready", "total_bytes": disk.total, "free_bytes": disk.free},
            "temperature": {"status": "not_available", "celsius_max": None},
        },
        "processes": process_snapshot(state),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Stage 10 health: {overall}")
    for item in services:
        print(f"  {item['name']}: {item['status']} ({item['device']}, {item['model_revision']})")
    print(f"Health metadata: {args.output}")
    return 0 if overall != "offline" else 1


if __name__ == "__main__":
    raise SystemExit(main())
