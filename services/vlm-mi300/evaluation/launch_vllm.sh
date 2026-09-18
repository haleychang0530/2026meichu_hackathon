#!/usr/bin/env bash
set -euo pipefail

if [[ $# -ne 3 ]]; then
  echo "usage: $0 MODEL REVISION SLUG" >&2
  exit 2
fi

model="$1"
revision="$2"
slug="$3"
eval_root="${EVAL_ROOT:-/tmp/stage02-eval}"
python_bin="${VLLM_PYTHON:-/usr/bin/python3.12}"
venv_site="${VLLM_SITE_PACKAGES:-/mlsteam/workspace/qwen3-benchmark/qwen38-venv/lib/python3.12/site-packages}"
log_dir="$eval_root/work/logs"
cache_root="${STAGE02_CACHE_ROOT:-/tmp/stage02}"
stage_home="${STAGE02_HOME:-${cache_root}-home-${slug}}"
hf_home="${STAGE02_HF_HOME:-${cache_root}-hf-${slug}}"
xdg_home="${STAGE02_XDG_CACHE_HOME:-${cache_root}-xdg-${slug}}"
vllm_cache="${STAGE02_VLLM_CACHE_ROOT:-${cache_root}-vllm-cache-${slug}}"
triton_cache="${STAGE02_TRITON_CACHE_DIR:-${cache_root}-triton-${slug}}"
gpu_memory_utilization="${STAGE02_GPU_MEMORY_UTILIZATION:-0.80}"

mkdir -p "$log_dir" "$stage_home" "$hf_home" "$xdg_home" "$vllm_cache" "$triton_cache"
start_epoch="$(date +%s)"
printf '%s\n' "$start_epoch" > "$log_dir/$slug.start_epoch"
amd-smi metric --gpu 0 > "$log_dir/$slug.vram_before.txt"

command=(
  "$python_bin" -m vllm.entrypoints.openai.api_server
  --model "$model"
  --revision "$revision"
  --served-model-name "$model"
  --host 127.0.0.1
  --port 8000
  --tensor-parallel-size 1
  --max-model-len 8192
  --gpu-memory-utilization "$gpu_memory_utilization"
)
printf 'HOME=%q PYTHONPATH=%q HF_HOME=%q XDG_CACHE_HOME=%q VLLM_CACHE_ROOT=%q TRITON_CACHE_DIR=%q ' \
  "$stage_home" "$venv_site" "$hf_home" "$xdg_home" "$vllm_cache" "$triton_cache" \
  > "$log_dir/$slug.command.txt"
printf '%q ' "${command[@]}" >> "$log_dir/$slug.command.txt"
printf '\n' >> "$log_dir/$slug.command.txt"

HOME="$stage_home" \
PYTHONPATH="$venv_site" \
HF_HOME="$hf_home" \
XDG_CACHE_HOME="$xdg_home" \
VLLM_CACHE_ROOT="$vllm_cache" \
TRITON_CACHE_DIR="$triton_cache" \
DO_NOT_TRACK=1 \
HF_HUB_DISABLE_TELEMETRY=1 \
VLLM_NO_USAGE_STATS=1 \
TOKENIZERS_PARALLELISM=false \
nohup "${command[@]}" > "$log_dir/$slug.server.log" 2>&1 &
pid=$!
printf '%s\n' "$pid" > "$log_dir/$slug.pid"

for _ in $(seq 1 360); do
  if curl --max-time 2 -sf http://127.0.0.1:8000/v1/models > "$log_dir/$slug.models.json"; then
    ready_epoch="$(date +%s)"
    printf '%s\n' "$ready_epoch" > "$log_dir/$slug.ready_epoch"
    printf '%s\n' "$((ready_epoch - start_epoch))" > "$log_dir/$slug.load_seconds"
    amd-smi metric --gpu 0 > "$log_dir/$slug.vram_after_load.txt"
    echo "ready pid=$pid load_seconds=$((ready_epoch - start_epoch))"
    exit 0
  fi
  if ! kill -0 "$pid" 2>/dev/null; then
    echo "vLLM exited before readiness; inspect $log_dir/$slug.server.log" >&2
    exit 1
  fi
  sleep 5
done

echo "timed out waiting for vLLM readiness" >&2
exit 1
