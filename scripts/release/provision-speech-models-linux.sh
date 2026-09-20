#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
speech_python="$repo_root/services/speech-local/.venv/bin/python"
huggingface_home="$repo_root/.runtime/huggingface"
log_root="$repo_root/services/speech-local/.runtime/provision"
port=8299

[[ -x "$speech_python" ]] || {
  echo "CPU speech environment missing; run scripts/release/setup-linux.sh --with-cpu-speech first." >&2
  exit 1
}
mkdir -p "$huggingface_home" "$log_root"

HF_HOME="$huggingface_home" HF_HUB_DISABLE_XET=1 HF_HUB_DOWNLOAD_TIMEOUT=600 "$speech_python" - <<'PY'
from huggingface_hub import snapshot_download

models = (
    ("paulpengtw/faster-whisper-Breeze-ASR-26", "7bf9dadb2f7f2bb418e82b3f074549fda82f7f47"),
    ("facebook/mms-tts-nan", "f28526a6caaf9dc55e030da83008c933f6a1978b"),
)
for model_id, revision in models:
    print(f"Provisioning {model_id}@{revision[:12]}...", flush=True)
    path = snapshot_download(repo_id=model_id, revision=revision, max_workers=2)
    print(f"Ready: {path}", flush=True)
PY

asr_model_path="${BREEZE_ASR_MODEL_PATH:-$huggingface_home/hub/models--paulpengtw--faster-whisper-Breeze-ASR-26/snapshots/7bf9dadb2f7f2bb418e82b3f074549fda82f7f47}"
tts_model_path="${MMS_TTS_MODEL_PATH:-$huggingface_home/hub/models--facebook--mms-tts-nan/snapshots/f28526a6caaf9dc55e030da83008c933f6a1978b}"
[[ -d "$asr_model_path" ]] || { echo "Breeze ASR snapshot missing: $asr_model_path" >&2; exit 1; }
[[ -d "$tts_model_path" ]] || { echo "MMS-TTS snapshot missing: $tts_model_path" >&2; exit 1; }

cleanup() {
  status=$?
  if [[ -n "${gateway_pid:-}" ]] && kill -0 "$gateway_pid" 2>/dev/null; then
    kill -TERM -- "-$gateway_pid" 2>/dev/null || kill -TERM "$gateway_pid" 2>/dev/null || true
  fi
  exit "$status"
}
trap cleanup EXIT

(
  cd "$repo_root/services/speech-local"
  exec setsid env HF_HOME="$huggingface_home" HF_HUB_DISABLE_XET=1 PYTHONUNBUFFERED=1 \
    BREEZE_ASR_MODEL_PATH="$asr_model_path" MMS_TTS_MODEL_PATH="$tts_model_path" "$speech_python" gateway.py \
    --host 127.0.0.1 --port "$port" --asr-backend breeze --tts-backend mms \
    --asr-cpu-threads 4 --asr-local-files-only --tts-local-files-only \
    --tts-cache-dir "$repo_root/services/speech-local/.runtime/audio-cache" \
    --tts-fallback-manifest "$repo_root/services/speech-local/fallback/prerecorded_manifest.json"
) >"$log_root/gateway.out.log" 2>"$log_root/gateway.err.log" &
gateway_pid=$!

for _ in $(seq 1 120); do
  curl -fsS --max-time 3 "http://127.0.0.1:$port/local/health" >/dev/null 2>&1 && break
  sleep 0.25
done
curl -fsS --max-time 1800 -X POST -H 'Content-Type: application/json' \
  -d '{"services":["asr","tts"]}' "http://127.0.0.1:$port/local/warmup" >/dev/null
curl -fsS --max-time 5 "http://127.0.0.1:$port/local/health"
echo
echo "Pinned Breeze ASR and MMS-TTS models are downloaded and pass local-only warmup."
