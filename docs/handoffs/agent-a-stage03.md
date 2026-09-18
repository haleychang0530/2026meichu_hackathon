# Agent A Stage 03 handoff

```text
Stage: Agent A Stage 03 — MI300 stateless VLM inference service
Status: done
Base: main @ e3a0a16b (Stage 02 PR #4 merged)
Branch: codex/agentA-stage03-vlm-service
Schema/OpenAPI version: 0.1.0 / OpenAPI 3.1.0
Previous Stage: Agent A Stage 02 — candidate evaluation (done; PR #4)
```

## Summary

- Added a FastAPI gateway that exposes only `GET /internal/health` and
  `POST /internal/vlm/generate` on the MI300 trusted LAN.
- Kept the gateway stateless with respect to product data: no RAG, SQLite,
  sessions, callbacks, student records, audio, image files, or payload logs.
  Only bounded operational counters and a sanitized last error remain in
  process memory.
- Added UUID request IDs, schema/model-revision checks, JPEG/PNG/WebP
  base64/container validation, in-memory metadata stripping, byte/pixel/
  dimension/prompt/schema/evidence/context limits, and structured v0.1 errors.
- Added a bounded queue and at most two worker sequences. Request deadlines,
  caller cancellation, upstream timeout/offline/429/5xx mapping, and clean
  shutdown cancel in-flight work without persisting request data.
- Added response metadata for raw output, schema-validated parsed candidate,
  token usage, finish reason, model revision, queue latency, inference
  latency, and total latency.
- Added lifecycle scripts, a standard-library client example, unit tests, and
  a metadata-only live evaluation runner.

## Locked model selection

Stage 02 is merged. The official model pair is fixed as follows:

- Primary: `Qwen/Qwen3-VL-30B-A3B-Instruct-FP8`, revision
  `d9748a51ae66354c4dad665aab2c71f26cf2c8cd`.
- Fallback: `Qwen/Qwen2.5-VL-7B-Instruct`, revision
  `cc594898137f460bfe9f0759e9844b3ce807cfb5`.
- Both are Apache-2.0, non-gated Hugging Face releases.

The `VLM_PRIMARY_MODEL(_REVISION)` and
`VLM_FALLBACK_MODEL(_REVISION)` variables are deployment/laptop selection
values. MI300 keeps one active checkpoint at a time through
`VLM_MODEL`/`VLM_MODEL_REVISION`; product fallback and conversation state stay
on the laptop. No alternate model is implicitly loaded by this gateway.

## Changed files

- `services/vlm-mi300/service.py`
- `services/vlm-mi300/README.md`
- `services/vlm-mi300/requirements-service.txt`
- `services/vlm-mi300/launch_service.sh`
- `services/vlm-mi300/stop_service.sh`
- `services/vlm-mi300/health_check.sh`
- `services/vlm-mi300/client_example.py`
- `services/vlm-mi300/run_live_eval.py`
- `services/vlm-mi300/test_service.py`
- `packages/contracts/openapi/v0.1/vlm-mi300.openapi.json`
- `docs/handoffs/agent-a-stage03.md`

No Agent B React component, Speech Gateway, ASR/TTS worker, RAG, SQLite,
session, or product API file was modified.

## Schema/OpenAPI version

- JSON Schema dialect: Draft 2020-12 for caller-supplied response schemas.
- Canonical `schema_version`: `0.1.0` (unchanged; the response contract
  extension is additive within the existing internal v0.1 API).
- OpenAPI: `3.1.0`, API info version `0.1.0`.
- The VLM response now documents required `raw_output`, `parsed_candidate`,
  `usage`, and `finish_reason`, plus `inference_ms`; all existing fields and
  request names remain unchanged.
- No migration is required. If a future change removes or renames a frozen
  field, create a new version directory and compatibility migration first.

## How to run

The upstream vLLM process must already serve the pinned 30B-A3B FP8 checkpoint
on MI300 port 8000. From a checkout on MI300, set the trusted source CIDR and
run:

```bash
export VLM_PYTHON=/usr/bin/python3.12
export VLM_SITE_PACKAGES=/mlsteam/workspace/qwen3-benchmark/qwen38-venv/lib/python3.12/site-packages
export VLM_UPSTREAM_URL=http://127.0.0.1:8000/v1
export VLM_PRIMARY_MODEL=Qwen/Qwen3-VL-30B-A3B-Instruct-FP8
export VLM_PRIMARY_MODEL_REVISION=d9748a51ae66354c4dad665aab2c71f26cf2c8cd
export VLM_FALLBACK_MODEL=Qwen/Qwen2.5-VL-7B-Instruct
export VLM_FALLBACK_MODEL_REVISION=cc594898137f460bfe9f0759e9844b3ce807cfb5
export VLM_MODEL="$VLM_PRIMARY_MODEL"
export VLM_MODEL_REVISION="$VLM_PRIMARY_MODEL_REVISION"
export VLM_MAX_CONTEXT_TOKENS=65536
export VLM_MAX_OUTPUT_TOKENS=8192
export VLM_ALLOWED_CIDRS=127.0.0.1/32,10.0.0.0/8,172.16.0.0/12,192.168.0.0/16
bash services/vlm-mi300/launch_service.sh
bash services/vlm-mi300/health_check.sh
```

The gateway listens on `0.0.0.0:8100` by default so Manta can forward it. Stop
it with `bash services/vlm-mi300/stop_service.sh`. Add the basic 8100/tcp
forwarding entry in Manta and use the assigned external port. For a controlled
deployment, narrow `VLM_ALLOWED_CIDRS` to the exact forwarding source network;
the service does not trust `X-Forwarded-For`.

The client example sends a fresh image plus prompt and JSON Schema per call:

```bash
python services/vlm-mi300/client_example.py textbook.png \
  --endpoint http://mi300.internal:8100/internal/vlm/generate \
  --prompt '請分析教材圖片並依 schema 回傳，不要輸出 markdown。'
```

## Tests and results

Local, dependency-free checks:

```text
python -m py_compile services/vlm-mi300/service.py services/vlm-mi300/test_service.py services/vlm-mi300/client_example.py services/vlm-mi300/run_live_eval.py  PASS
python scripts/test_contracts.py  PASS: 7 schemas; 3 OpenAPI documents/45 responses; 18 schema fixtures; 10 student-safe fixtures
git diff --check  PASS
```

The local Windows environment does not have the service `httpx` dependency,
so the local unittest import is not used as evidence. On MI300, with the
existing vLLM environment, `unittest discover` ran 7 tests in 0.559 s and
finished `OK`, covering image/MIME/schema validation, response parsing,
bounded queue rejection, timeout cancellation, and caller cancellation.

Live MI300 evidence (2026-09-17 UTC) used the ten Stage 02 student-safe PNG
fixtures twice, sequentially, with one fixed prompt/schema and the same
sampling settings (`temperature=0`, `top_p=1`, `max_tokens=8192`):

```text
20/20 HTTP 200
20/20 response_schema-valid candidates
finish_reason: stop for all 20
latency: min 573 ms, P50 975.5 ms, P95 1220 ms, max 1221 ms
total reported tokens: 42662
```

AMD-SMI JSON samples reported 196592 MB total, 158189 MB used, and 38403 MB
free both before and after the 20 calls (22 samples); no sustained VRAM growth
was observed. The MI300 runtime reported vLLM 0.18.0, ROCm 7.0.0, and
AMD-SMI 26.0.0+37d158ab. The live gateway PID after the final restart was 141351 and
health returned `status=ready`, `model_revision=d9748a51ae66354c4dad665aab2c71f26cf2c8cd`.
The 20-call run used that PID; after the structured-log formatter fix the
gateway was restarted as PID 151936, and a valid image smoke request plus
health check returned 200 with no new formatter errors.

Additional live checks:

- malformed base64 image: HTTP 400 `VALIDATION_ERROR`;
- delayed isolated upstream with 0.1 s gateway deadline: HTTP 504
  `VLM_TIMEOUT` (the in-flight operation was cancelled);
- stopped and restarted the production gateway: health failed while stopped
  and returned ready after restart, followed by successful calls;
- unavailable isolated upstream: health reported `offline` with
  `VLM_OFFLINE`/`cached_lesson`; generate returned HTTP 503
  `VLM_OFFLINE`/`cached_lesson`;
- the unit suite's cancellation and queue tests passed. No request payload or
  model output was saved in the `/tmp` evidence files.

Laptop-origin forwarding smoke (2026-09-18 UTC):

- Manta basic forwarding: `8100/tcp` → external port `46944` (existing
  `8000/tcp` → `45503`). The assigned external port is lab state and can
  change when the rule is recreated.
- From the laptop, `GET http://210.61.209.139:46944/internal/health` returned
  HTTP 200 with `status=ready` and primary revision
  `d9748a51ae66354c4dad665aab2c71f26cf2c8cd`.
- From the laptop, one synthetic 512×512 PNG plus prompt and Draft 2020-12
  schema returned HTTP 200 from `/internal/vlm/generate`; the candidate was
  schema-valid, `finish_reason=stop`, `inference_ms=997`, and usage was
  `288/43/331` prompt/completion/total tokens.
- The smoke image and prompt were held in memory on the laptop and were not
  committed or persistently logged.

## Fixtures

- `/tmp/stage02-eval/dataset/` on MI300: ten synthetic/student-safe PNGs,
  including frontal, tilted, glare, dense Tai-Lo, illustration, dialogue,
  low-contrast, two-column, reasoning, and mixed-annotation cases.
- `/tmp/stage02-eval/response_schema.json` was used as the fixed response
  schema source; the live runner records only safe metadata.
- No images, prompts, raw output, audio, weights, cache, or database are added
  to Git.

## Resource usage

- MI300 one-GPU vLLM process: `Qwen/Qwen3-VL-30B-A3B-Instruct-FP8`, tensor
  parallel 1, max model length 65536, GPU utilization target 0.80, upstream
  port 8000.
- Gateway: one uvicorn worker, queue max 8, concurrency max 2, request
  timeout 120 s, output cap 8192, estimated context cap 65536.
- Lifecycle defaults pin `VLM_PRIMARY_MODEL_REVISION` to
  `d9748a51ae66354c4dad665aab2c71f26cf2c8cd` and
  `VLM_FALLBACK_MODEL_REVISION` to
  `cc594898137f460bfe9f0759e9844b3ce807cfb5`; the active gateway uses the
  primary pair above.
- Live VRAM remained 158189 MB used of 196592 MB across the 20-request run.
- Runtime logs, PID files, and sanitized evidence were kept under MI300
  `/tmp/stage03-vlm-service`; they are ephemeral and not committed.

## Known limits

- MI300 loads one checkpoint at a time. The pinned 7B fallback is a deployment
  switch target, not a second concurrent worker; the laptop owns the product
  fallback decision and session state.
- Manta's external port is lab-assigned (`46944` at this handoff) and can
  change when the forwarding rule is recreated. Read the current port from
  Manta before using the sample client.
- The live service was started through the browser terminal with the same
  environment as the lifecycle scripts; the repository scripts were syntax
  checked by inspection and remain the reproducible lifecycle source.
- JSON Schema validation is intentionally caller-supplied and bounded; the
  gateway does not perform teaching, RAG, moderation, answer-key, or session
  policy.
- Health is an internal readiness probe and returns an HTTP response with a
  status field; the laptop Core Backend must translate `offline`/`degraded` to
  the product fallback policy.

## Agent B can rely on

- Only the two documented internal paths exist; the browser/student frontend
  must never call MI300 directly.
- Send a new request for each turn. The laptop owns conversation history,
  evidence selection, RAG, SQLite, session state, and product fallback.
- Include a UUID `request_id`, `schema_version=0.1.0`, the exact running model
  revision, one base64 image, a bounded prompt/evidence set, and a Draft
  2020-12 `response_schema`.
- On success, consume `output.parsed_candidate` (already validated), token
  usage, finish reason, and latency fields. On errors, use the v0.1 envelope's
  `code`, `retryable`, and `fallback`; do not retry validation errors blindly.
- Treat `VLM_TIMEOUT` as retryable with bounded backoff and
  `VLM_OFFLINE`/`VLM_INVALID_OUTPUT` as inputs to the laptop fallback policy.

## Next action

1. Keep the MI300 30B primary and gateway processes running for the current lab
   session; read Manta's current assigned external port before use.
2. Agent B may integrate the two internal routes through the laptop Core
   Backend using the pinned primary/fallback environment values above.
3. If the forwarding rule is recreated or the lab restarts, rerun the two
   laptop-origin smoke commands and record the new assigned port.
