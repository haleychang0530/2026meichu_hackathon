#!/usr/bin/env bash
set -euo pipefail

port="${VLM_PORT:-8100}"
request_id="$(cat /proc/sys/kernel/random/uuid 2>/dev/null || printf '%s' '00000000-0000-4000-8000-000000000000')"
curl --fail-with-body --max-time "${VLM_HEALTH_TIMEOUT_SECONDS:-5}" \
  -H "X-Request-ID: $request_id" \
  "http://127.0.0.1:${port}/internal/health"
printf '\n'
