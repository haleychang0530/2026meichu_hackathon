#!/usr/bin/env bash
set -euo pipefail

runtime_dir="${VLM_SERVICE_RUNTIME_DIR:-/tmp/vlm-mi300-service}"
pid_file="$runtime_dir/server.pid"

if [[ ! -s "$pid_file" ]]; then
  echo "not running (no pid file)"
  exit 0
fi

pid="$(cat "$pid_file")"
if [[ ! "$pid" =~ ^[0-9]+$ ]]; then
  echo "invalid pid file: $pid_file" >&2
  exit 1
fi

if ! kill -0 "$pid" 2>/dev/null; then
  rm -f "$pid_file"
  echo "not running (stale pid file removed)"
  exit 0
fi

cmd="$(ps -o args= -p "$pid" || true)"
if [[ "$cmd" != *"uvicorn"* || "$cmd" != *"service:app"* ]]; then
  echo "refusing to stop unrelated process pid=$pid" >&2
  exit 1
fi

kill "$pid"
for _ in $(seq 1 30); do
  if ! kill -0 "$pid" 2>/dev/null; then
    rm -f "$pid_file"
    echo "stopped pid=$pid"
    exit 0
  fi
  sleep 1
done

echo "service did not stop after 30 seconds; pid=$pid" >&2
exit 1
