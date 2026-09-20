#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
core_python="$repo_root/apps/core-api/.venv/bin/python"
speech_python="$repo_root/services/speech-local/.venv/bin/python"
node_root="$repo_root/.runtime/toolchain/node"

with_cpu_speech=0
if [[ "${1:-}" == "--with-cpu-speech" ]]; then
  with_cpu_speech=1
elif [[ $# -gt 0 ]]; then
  echo "Usage: $0 [--with-cpu-speech]" >&2
  exit 2
fi

mkdir -p "$repo_root/.runtime/toolchain"

if [[ ! -x "$node_root/bin/node" ]]; then
  if command -v node >/dev/null 2>&1 && node -e 'const [major, minor] = process.versions.node.split(".").map(Number); process.exit(major > 22 || (major === 22 && minor >= 12) || (major === 20 && minor >= 19) ? 0 : 1)'; then
    system_node="$(command -v node)"
    system_node_root="$(cd "$(dirname "$system_node")/.." && pwd)"
    ln -s "$system_node_root" "$node_root"
  elif [[ -x /usr/lib/chatgpt/resources/cua_node/bin/node ]]; then
    cp -a /usr/lib/chatgpt/resources/cua_node "$node_root"
  else
    echo "Node.js ^20.19 or >=22.12 is required. Set up Node and rerun this script." >&2
    exit 1
  fi
fi

python3 -m venv "$repo_root/apps/core-api/.venv"
"$core_python" -m pip install --index-url https://pypi.org/simple --timeout 120 --retries 10 --upgrade pip
"$core_python" -m pip install --index-url https://pypi.org/simple --timeout 120 --retries 10 -r "$repo_root/apps/core-api/requirements.txt"

PATH="$node_root/bin:$PATH" npm --prefix "$repo_root/apps/web" ci --no-audit --no-fund \
  --fetch-retries=10 --fetch-retry-mintimeout=2000 --fetch-retry-maxtimeout=120000 --fetch-timeout=120000

if [[ $with_cpu_speech -eq 1 ]]; then
  python3 -m venv "$repo_root/services/speech-local/.venv"
  "$speech_python" -m pip install --index-url https://pypi.org/simple --timeout 120 --retries 10 --upgrade pip
  # PyPI's Linux Torch wheel pulls CUDA libraries even for this CPU-only
  # release profile.  Install the matching CPU wheel first so the pinned
  # requirements resolve without several gigabytes of unused NVIDIA wheels.
  "$speech_python" -m pip install --index-url https://download.pytorch.org/whl/cpu --timeout 120 --retries 10 'torch==2.8.0'
  "$speech_python" -m pip install --index-url https://pypi.org/simple --timeout 120 --retries 10 -r "$repo_root/services/speech-local/requirements.txt"
fi

echo "Linux dependencies are ready."
echo "Node: $($node_root/bin/node --version)"
echo "Core Python: $($core_python --version)"
if [[ $with_cpu_speech -eq 1 ]]; then
  echo "CPU speech Python: $($speech_python --version)"
fi
