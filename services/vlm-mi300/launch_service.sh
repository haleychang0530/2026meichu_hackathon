#!/usr/bin/env bash
set -euo pipefail

service_root="$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
runtime_dir="${VLM_SERVICE_RUNTIME_DIR:-/tmp/vlm-mi300-service}"
python_bin="${VLM_PYTHON:-/usr/bin/python3.12}"
site_packages="${VLM_SITE_PACKAGES:-/mlsteam/workspace/qwen3-benchmark/qwen38-venv/lib/python3.12/site-packages}"
bind_host="${VLM_BIND_HOST:-0.0.0.0}"
port="${VLM_PORT:-8100}"
primary_model="${VLM_PRIMARY_MODEL:-Qwen/Qwen3-VL-30B-A3B-Instruct-FP8}"
primary_revision="${VLM_PRIMARY_MODEL_REVISION:-d9748a51ae66354c4dad665aab2c71f26cf2c8cd}"
fallback_model="${VLM_FALLBACK_MODEL:-Qwen/Qwen2.5-VL-7B-Instruct}"
fallback_revision="${VLM_FALLBACK_MODEL_REVISION:-cc594898137f460bfe9f0759e9844b3ce807cfb5}"
model="${VLM_MODEL:-$primary_model}"
model_revision="${VLM_MODEL_REVISION:-$primary_revision}"
log_file="$runtime_dir/server.log"
pid_file="$runtime_dir/server.pid"

mkdir -p "$runtime_dir"

if [[ -s "$pid_file" ]]; then
  existing_pid="$(cat "$pid_file")"
  if [[ "$existing_pid" =~ ^[0-9]+$ ]] && kill -0 "$existing_pid" 2>/dev/null; then
    existing_cmd="$(ps -o args= -p "$existing_pid" || true)"
    if [[ "$existing_cmd" == *"uvicorn"* && "$existing_cmd" == *"service:app"* ]]; then
      echo "already running pid=$existing_pid"
      exit 0
    fi
    echo "refusing to reuse pid file for unrelated process pid=$existing_pid" >&2
    exit 1
  fi
  rm -f "$pid_file"
fi

export VLM_BIND_HOST="$bind_host"
export VLM_PORT="$port"
export VLM_SERVICE_RUNTIME_DIR="$runtime_dir"
export VLM_PRIMARY_MODEL="$primary_model"
export VLM_PRIMARY_MODEL_REVISION="$primary_revision"
export VLM_FALLBACK_MODEL="$fallback_model"
export VLM_FALLBACK_MODEL_REVISION="$fallback_revision"
export VLM_MODEL="$model"
export VLM_MODEL_REVISION="$model_revision"
export PYTHONPATH="$site_packages${PYTHONPATH:+:$PYTHONPATH}"

command=(
  "$python_bin" -m uvicorn service:app
  --app-dir "$service_root"
  --host "$bind_host"
  --port "$port"
  --workers 1
  --no-access-log
)

printf 'PYTHONPATH=%q ' "$PYTHONPATH" > "$runtime_dir/command.txt"
printf '%q ' "${command[@]}" >> "$runtime_dir/command.txt"
printf '\n' >> "$runtime_dir/command.txt"

nohup "${command[@]}" > "$log_file" 2>&1 &
pid="$!"
printf '%s\n' "$pid" > "$pid_file"

for _ in $(seq 1 120); do
  if curl --max-time 2 -sS "http://127.0.0.1:${port}/internal/health" > "$runtime_dir/health.json"; then
    echo "ready pid=$pid endpoint=http://127.0.0.1:${port}"
    exit 0
  fi
  if ! kill -0 "$pid" 2>/dev/null; then
    echo "service exited before readiness; inspect $log_file" >&2
    exit 1
  fi
  sleep 1
done

echo "timed out waiting for service readiness; inspect $log_file" >&2
exit 1
