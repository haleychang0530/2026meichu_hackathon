#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
runtime_root="$repo_root/apps/core-api/.runtime/stage10-demo"
log_root="$runtime_root/logs"
state_path="$runtime_root/processes.json"
core_data_root="$runtime_root/core-data"
speech_cache_root="$runtime_root/audio-cache"
rag_index_root="$runtime_root/rag-indexes"
huggingface_home="$repo_root/.runtime/huggingface"
core_python="$repo_root/apps/core-api/.venv/bin/python"
speech_python="$repo_root/services/speech-local/.venv/bin/python"
node_root="$repo_root/.runtime/toolchain/node"

mode=mock
speech_profile=mock
mi300_base_url="${VLM_BASE_URL:-}"
skip_rag=0
skip_health=0

usage() {
  echo "Usage: $0 [--mode mock|real] [--speech-profile mock|cpu] [--mi300-base-url URL] [--skip-rag-reindex] [--skip-health-check]" >&2
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --mode) mode="${2:-}"; shift 2 ;;
    --speech-profile) speech_profile="${2:-}"; shift 2 ;;
    --mi300-base-url) mi300_base_url="${2:-}"; shift 2 ;;
    --skip-rag-reindex) skip_rag=1; shift ;;
    --skip-health-check) skip_health=1; shift ;;
    -h|--help) usage; exit 0 ;;
    *) usage; exit 2 ;;
  esac
done

[[ "$mode" == mock || "$mode" == real ]] || { usage; exit 2; }
[[ "$speech_profile" == mock || "$speech_profile" == cpu ]] || { usage; exit 2; }
[[ -x "$core_python" ]] || { echo "Core environment missing; run scripts/release/setup-linux.sh first." >&2; exit 1; }
[[ -x "$node_root/bin/node" && -x "$node_root/bin/npm" ]] || { echo "Node runtime missing; run scripts/release/setup-linux.sh first." >&2; exit 1; }
if [[ "$speech_profile" == cpu && ! -x "$speech_python" ]]; then
  echo "CPU speech environment missing; run scripts/release/setup-linux.sh --with-cpu-speech first." >&2
  exit 1
fi

if [[ "$mode" == real ]]; then
  "$core_python" - "$mi300_base_url" <<'PY'
import sys
from urllib.parse import urlsplit
value = sys.argv[1].strip().rstrip("/")
parsed = urlsplit(value)
if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password or parsed.path not in {"", "/"} or parsed.query or parsed.fragment:
    raise SystemExit("--mi300-base-url must be a credential-free HTTP(S) origin without a path")
PY
fi

mkdir -p "$runtime_root" "$log_root" "$core_data_root" "$speech_cache_root" "$rag_index_root" "$huggingface_home"

if [[ -f "$state_path" ]] && REPO_ROOT="$repo_root" "$core_python" - "$state_path" <<'PY'
import json, os, sys
try:
    state = json.load(open(sys.argv[1], encoding="utf-8"))
except Exception:
    raise SystemExit(1)
try:
    boot_id = open("/proc/sys/kernel/random/boot_id", encoding="ascii").read().strip()
except OSError:
    boot_id = None
if not boot_id or state.get("boot_id") != boot_id:
    raise SystemExit(1)
repo_root = os.environ["REPO_ROOT"].encode()
def is_managed(item):
    try:
        command = open(f"/proc/{int(item['pid'])}/cmdline", "rb").read()
    except OSError:
        return False
    return repo_root in command
raise SystemExit(0 if any(is_managed(item) for item in state.get("processes", [])) else 1)
PY
then
  echo "Demo is already running; use scripts/release/stop-demo-linux.sh first." >&2
  exit 1
fi

if [[ $skip_rag -eq 0 ]]; then
  "$core_python" "$repo_root/scripts/rag_reindex.py" --mode full \
    --manifest "$repo_root/data/rag/manifest.json" --index-root "$rag_index_root" \
    >"$log_root/rag-reindex.log" 2>&1
fi

pids=()
roles=()
cleanup_on_error() {
  status=$?
  if [[ $status -ne 0 ]]; then
    for pid in "${pids[@]:-}"; do
      if kill -0 "$pid" 2>/dev/null; then kill -TERM -- "-$pid" 2>/dev/null || kill -TERM "$pid" 2>/dev/null || true; fi
    done
  fi
  exit "$status"
}
trap cleanup_on_error EXIT

speech_executable=python3
speech_args=("$repo_root/services/speech-local/gateway.py" --host 127.0.0.1 --port 8200 --asr-backend mock --tts-backend mock --tts-cache-dir "$speech_cache_root" --tts-fallback-manifest "$repo_root/services/speech-local/fallback/prerecorded_manifest.json")
if [[ "$speech_profile" == cpu ]]; then
  asr_model_path="${BREEZE_ASR_MODEL_PATH:-$huggingface_home/hub/models--paulpengtw--faster-whisper-Breeze-ASR-26/snapshots/7bf9dadb2f7f2bb418e82b3f074549fda82f7f47}"
  tts_model_path="${MMS_TTS_MODEL_PATH:-$huggingface_home/hub/models--facebook--mms-tts-nan/snapshots/f28526a6caaf9dc55e030da83008c933f6a1978b}"
  [[ -d "$asr_model_path" ]] || {
    echo "Pinned Breeze ASR snapshot missing: $asr_model_path; run scripts/release/provision-speech-models-linux.sh first." >&2
    exit 1
  }
  [[ -d "$tts_model_path" ]] || {
    echo "Pinned MMS-TTS snapshot missing: $tts_model_path; run scripts/release/provision-speech-models-linux.sh first." >&2
    exit 1
  }
  speech_executable="$speech_python"
  speech_args=("$repo_root/services/speech-local/gateway.py" --host 127.0.0.1 --port 8200 --asr-backend breeze --asr-model-path "$asr_model_path" --tts-backend mms --tts-model-path "$tts_model_path" --asr-cpu-threads 4 --asr-local-files-only --tts-local-files-only --tts-cache-dir "$speech_cache_root" --tts-fallback-manifest "$repo_root/services/speech-local/fallback/prerecorded_manifest.json")
fi
(
  cd "$repo_root/services/speech-local"
  exec setsid env PYTHONUNBUFFERED=1 HF_HOME="$huggingface_home" MMS_TTS_CACHE_DIR="$speech_cache_root" "$speech_executable" "${speech_args[@]}"
) >"$log_root/speech.out.log" 2>"$log_root/speech.err.log" &
pids+=("$!"); roles+=(speech)

core_profile=demo
core_provider=fixture
[[ "$mode" == real ]] && { core_profile=development; core_provider=real; }
(
  cd "$repo_root/apps/core-api"
  vlm_output_validation_enabled="${VLM_OUTPUT_VALIDATION_ENABLED:-false}"
  core_env=(env PYTHONUNBUFFERED=1 CORE_PROFILE="$core_profile" CORE_PROVIDER="$core_provider" CORE_HOST=127.0.0.1 CORE_PORT=8000 CORE_DATA_DIR="$core_data_root" CORE_ALLOWED_ORIGINS=http://127.0.0.1:5173,http://localhost:5173 VLM_OUTPUT_VALIDATION_ENABLED="$vlm_output_validation_enabled" SPEECH_BASE_URL=http://127.0.0.1:8200 RAG_MANIFEST_PATH="$repo_root/data/rag/manifest.json" RAG_INDEX_ROOT="$rag_index_root" LANGUAGE_GOLDEN_PATH="$repo_root/data/language/normalization-golden.json")
  [[ -n "$mi300_base_url" ]] && core_env+=(VLM_BASE_URL="$mi300_base_url")
  exec setsid "${core_env[@]}" "$core_python" -m core_api
) >"$log_root/core.out.log" 2>"$log_root/core.err.log" &
pids+=("$!"); roles+=(core)

(
  cd "$repo_root"
  exec setsid env PATH="$node_root/bin:$PATH" VITE_DATA_MODE="$mode" VITE_CORE_API_BASE_URL=http://127.0.0.1:8000 VITE_SPEECH_MODE="$([[ "$speech_profile" == cpu ]] && echo real || echo mock)" VITE_SPEECH_GATEWAY_BASE_URL=http://127.0.0.1:8200 "$node_root/bin/npm" --prefix "$repo_root/apps/web" run dev -- --host 127.0.0.1
) >"$log_root/web.out.log" 2>"$log_root/web.err.log" &
pids+=("$!"); roles+=(web)

PIDS="${pids[*]}" ROLES="${roles[*]}" MODE="$mode" SPEECH_PROFILE="$speech_profile" RUNTIME_ROOT="$runtime_root" "$core_python" - "$state_path" <<'PY'
import json, os, sys
from datetime import datetime, timezone
pids = [int(value) for value in os.environ["PIDS"].split()]
roles = os.environ["ROLES"].split()
state = {
    "schema_version": "stage10-processes.v1",
    "started_at": datetime.now(timezone.utc).isoformat(),
    "mode": os.environ["MODE"],
    "speech_profile": os.environ["SPEECH_PROFILE"],
    "runtime_root": os.environ["RUNTIME_ROOT"],
    "boot_id": open("/proc/sys/kernel/random/boot_id", encoding="ascii").read().strip(),
    "processes": [{"role": role, "pid": pid} for role, pid in zip(roles, pids)],
}
with open(sys.argv[1], "w", encoding="utf-8") as handle:
    json.dump(state, handle, ensure_ascii=False, indent=2)
PY

wait_http() {
  local url=$1 name=$2
  for _ in $(seq 1 120); do
    if curl -fsS --max-time 3 "$url" >/dev/null 2>&1; then echo "$name ready: $url"; return 0; fi
    sleep 0.25
  done
  echo "$name did not become ready: $url" >&2
  return 1
}

wait_http http://127.0.0.1:8200/local/health "Speech Gateway"
curl -fsS --max-time 300 -X POST -H 'Content-Type: application/json' -d '{"services":["asr","tts"]}' http://127.0.0.1:8200/local/warmup >/dev/null || echo "Speech warmup degraded; see health page." >&2
wait_http http://127.0.0.1:8000/api/health "Core Backend"
wait_http http://127.0.0.1:5173/health "Web"

if [[ $skip_health -eq 0 ]]; then
  "$core_python" "$repo_root/scripts/release/health-demo-linux.py" --output "$runtime_root/health.json"
fi

trap - EXIT
echo "Stage 10 demo started in $mode mode ($speech_profile speech)."
echo "Health page: http://127.0.0.1:5173/health"
echo "Stop: scripts/release/stop-demo-linux.sh"
