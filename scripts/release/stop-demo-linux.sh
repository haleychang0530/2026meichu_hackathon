#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
state_path="$repo_root/apps/core-api/.runtime/stage10-demo/processes.json"

if [[ ! -f "$state_path" ]]; then
  echo "Stage 10 demo has no managed process state; no processes were stopped."
  exit 0
fi

REPO_ROOT="$repo_root" python3 - "$state_path" <<'PY'
import json, os, signal, sys, time
path = sys.argv[1]
with open(path, encoding="utf-8") as handle:
    state = json.load(handle)
try:
    boot_id = open("/proc/sys/kernel/random/boot_id", encoding="ascii").read().strip()
except OSError:
    boot_id = None
if not boot_id or state.get("boot_id") != boot_id:
    os.unlink(path)
    print("Discarded process state from an earlier boot; no processes were signalled.")
    raise SystemExit(0)
repo_root = os.environ["REPO_ROOT"].encode()
entries = list(reversed(state.get("processes", [])))
def is_managed(pid):
    try:
        command = open(f"/proc/{pid}/cmdline", "rb").read()
        cwd = os.readlink(f"/proc/{pid}/cwd").encode()
        return repo_root in command or cwd == repo_root
    except OSError:
        return False
for entry in entries:
    pid = int(entry["pid"])
    try:
        if not is_managed(pid):
            continue
        pgid = os.getpgid(pid)
    except (OSError, ProcessLookupError):
        continue
    print(f"Stopping {entry['role']} PID {pid}")
    try:
        os.killpg(pgid, signal.SIGTERM) if pgid == pid else os.kill(pid, signal.SIGTERM)
    except ProcessLookupError:
        pass
deadline = time.monotonic() + 5
while time.monotonic() < deadline:
    if not any(is_managed(int(item["pid"])) for item in entries):
        break
    time.sleep(0.1)
for entry in entries:
    pid = int(entry["pid"])
    try:
        if not is_managed(pid):
            continue
        pgid = os.getpgid(pid)
        os.killpg(pgid, signal.SIGKILL) if pgid == pid else os.kill(pid, signal.SIGKILL)
    except (OSError, ProcessLookupError):
        pass
os.unlink(path)
PY

echo "Stage 10 demo stopped. Logs and generated data were retained."
