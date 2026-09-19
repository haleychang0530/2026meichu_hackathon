# MI300 stateless VLM service

Owner: Agent A. Runtime: MI300 trusted-LAN host. The gateway is a thin
stateless wrapper around the local OpenAI-compatible vLLM process. It never
owns RAG, SQLite, sessions, student records, product APIs, or callbacks to the
laptop.

## Locked model selection (Stage 02)

Stage 02 is merged and its model decision is final:

- Primary: `Qwen/Qwen3-VL-30B-A3B-Instruct-FP8`, revision
  `d9748a51ae66354c4dad665aab2c71f26cf2c8cd`.
- Fallback: `Qwen/Qwen2.5-VL-7B-Instruct`, revision
  `cc594898137f460bfe9f0759e9844b3ce807cfb5`.
- Both checkpoints are Apache-2.0 releases from their Hugging Face model
  repositories (`gated=false`).

`VLM_PRIMARY_*` and `VLM_FALLBACK_*` below are the laptop/deployment selection
variables. The MI300 gateway is stateless and loads one active checkpoint at a
time; `VLM_MODEL`/`VLM_MODEL_REVISION` identify that active process. Switching
to the fallback therefore means stopping the active vLLM process, starting the
pinned fallback checkpoint on port 8000, and restarting the gateway. Product
fallback policy and conversation state remain on the laptop.

## Endpoints

Only these routes are exposed:

- `GET /internal/health`
- `POST /internal/vlm/generate`

The canonical contract is
`packages/contracts/openapi/v0.1/vlm-mi300.openapi.json` (OpenAPI 3.1.0,
`schema_version` `0.1.0`). Every response includes `X-Request-ID`; every error
body uses the shared v0.1 error envelope.

`POST /internal/vlm/generate` accepts one image, prompt, JSON Schema, optional
laptop-selected evidence, UUID `request_id`, `schema_version`, and the exact
running `model_revision`:

```json
{
  "schema_version": "0.1.0",
  "request_id": "00000000-0000-4000-8000-000000000001",
  "image": {"media_type": "image/png", "content_base64": "..."},
  "prompt": "依照指定 schema 回傳結果，不要輸出 markdown。",
  "response_schema": {
    "type": "object",
    "additionalProperties": false,
    "properties": {"answer": {"type": "string"}},
    "required": ["answer"]
  },
  "model_revision": "d9748a51ae66354c4dad665aab2c71f26cf2c8cd"
}
```

The service verifies base64, MIME/container, dimensions, pixels, prompt and
schema size, evidence size, context budget, and model revision before queuing
the request. Images are decoded, checked, and metadata-stripped in memory;
they are never written to a file. The default limits are 8 MiB image, 4096 px
per dimension, 16,777,216 pixels, 50,000 prompt characters, 20 evidence items,
65,536 estimated context tokens, and 8,192 output tokens.

The response keeps raw output and the schema-validated candidate together with
token usage and finish reason:

```json
{
  "schema_version": "0.1.0",
  "request_id": "00000000-0000-4000-8000-000000000001",
  "output": {
    "raw_output": "{\"answer\":\"...\"}",
    "parsed_candidate": {"answer": "..."},
    "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
    "finish_reason": "stop"
  },
  "model_revision": "d9748a51ae66354c4dad665aab2c71f26cf2c8cd",
  "latency_ms": 1200,
  "queue_ms": 4,
  "inference_ms": 1196
}
```

The queue is bounded (`VLM_QUEUE_MAX`, default 8) and has at most two worker
sequences (`VLM_CONCURRENCY`, default 2). Queue overflow returns retryable
`VLM_TIMEOUT`/429. A request timeout cancels an in-flight upstream operation
and returns `VLM_TIMEOUT`/504. Upstream connection failures return
`VLM_OFFLINE`/503; invalid model JSON or schema output returns
`VLM_INVALID_OUTPUT`/503 with no payload logging.

## MI300 lifecycle

The Manta project `qwen3-coder-fp8-bench` used for this service exposes a
Terminal Console for direct MI300 shell work. The image has a full
`/mlsteam/workspace` NFS volume.
Use `/usr/bin/python3.12` plus the existing vLLM site-packages and keep runtime
logs/PID files under `/tmp`:

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
bash services/vlm-mi300/stop_service.sh
```

The upstream vLLM model must already be ready on port 8000. The gateway listens
on `0.0.0.0:8100` by default so the Manta lab can forward that port. Add the
lab's 8100 forwarding entry, then use the assigned external port from the Manta
UI. The IP allowlist does not trust `X-Forwarded-For`; in a controlled
deployment set `VLM_ALLOWED_CIDRS` to the exact forwarding source CIDR.

To switch models, stop the gateway, stop the verified vLLM parent, launch either
the primary or the pinned 7B fallback checkpoint on port 8000, set
`VLM_MODEL`/`VLM_MODEL_REVISION` to the selected pair, then start the gateway
again. The revision mismatch check prevents a laptop from accidentally sending
a request for a different checkpoint.

## Example laptop client

`client_example.py` uses only Python's standard library and sends a data URL
equivalent request to the gateway:

```bash
python client_example.py textbook.png \
  --endpoint http://mi300.internal:8100/internal/vlm/generate \
  --prompt '請分析教材圖片並依 schema 回傳，不要輸出 markdown。'
```

For multi-turn teaching, the laptop owns history. Send a fresh request with
the intentionally retained text/evidence (and image again when needed); the
MI300 gateway does not retain conversations between calls.

## Tests

Run dependency-free syntax checks from the repository root:

```bash
python -m py_compile services/vlm-mi300/service.py services/vlm-mi300/test_service.py services/vlm-mi300/client_example.py
```

On MI300, with the existing vLLM runtime on `PYTHONPATH`, run the gateway unit
tests before the live smoke workload:

```bash
PYTHONPATH=/mlsteam/workspace/qwen3-benchmark/qwen38-venv/lib/python3.12/site-packages \
  /usr/bin/python3.12 -m unittest discover -s services/vlm-mi300 -p 'test_service.py' -v
```

Live evidence must record the exact model/revision, vLLM/ROCm versions, service
PID, health response, at least 20 sequential image requests, malformed image,
timeout, cancellation, restart, and offline/fallback behavior. Record only
metadata, latency and error codes under `/tmp`; do not commit images, prompts,
raw student audio, model weights, caches or databases.

The dependency-free runner used for the MI300 evidence is:

```bash
PYTHONPATH=/tmp/stage03-vlm-service/src:/mlsteam/workspace/qwen3-benchmark/qwen38-venv/lib/python3.12/site-packages \
  /usr/bin/python3.12 /tmp/stage03-vlm-service/src/run_live_eval.py \
  --dataset /tmp/stage02-eval/dataset \
  --output /tmp/stage03-vlm-service/evidence/20-results.jsonl \
  --repeat 2
```

The final restart verification used 10 student-safe fixtures twice (20
sequential calls): all 20 returned HTTP 200 and schema-valid candidates, with
P50 975.5 ms, P95 1,220 ms, minimum 573 ms and maximum 1,221 ms. The model
reported 42,662 total tokens and `stop` for every call. AMD-SMI JSON reported
196,592 MB total, 158,189 MB used and 38,403 MB free both before and after the
run (22 samples), so no sustained VRAM growth was observed. The run was on
vLLM 0.18.0 / ROCm 7.0.0 (AMD-SMI 26.0.0+37d158ab), service PID 141351, revision
`d9748a51ae66354c4dad665aab2c71f26cf2c8cd`.

The 20-call run used gateway PID 141351. After the structured-log formatter
fix, the gateway was restarted as PID 151936; health and a valid image smoke
request returned 200, and the fresh log contained no formatter errors.

The same run verified malformed base64 (HTTP 400 `VALIDATION_ERROR`), an
isolated delayed upstream (HTTP 504 `VLM_TIMEOUT`), restart and health recovery,
and an unavailable upstream (HTTP 503 `VLM_OFFLINE`, fallback
`cached_lesson`). Cancellation and bounded-queue behavior are covered by the
seven MI300 unit tests. Evidence remains in the MI300 `/tmp` tree and is not a
repository artifact.

### Laptop-origin forwarding smoke (2026-09-18 UTC)

Manta was configured with the basic `8100/tcp` forwarding entry; the UI assigned
external port `46944` for this lab (`8000/tcp` remained `45503`). From the
laptop, without using the MI300 terminal, the following requests succeeded:

- `GET http://210.61.209.139:46944/internal/health` → HTTP 200,
  `status=ready`, primary revision `d9748a51ae66354c4dad665aab2c71f26cf2c8cd`.
- `POST http://210.61.209.139:46944/internal/vlm/generate` with one in-memory
  synthetic 512×512 PNG, a fixed prompt, and a Draft 2020-12 response schema →
  HTTP 200, schema-valid `parsed_candidate`, `finish_reason=stop`,
  `inference_ms=997`, usage `288/43/331` prompt/completion/total tokens.

The image and prompt were not written to the repository or persistent logs.
The external port is lab-assigned and may change when forwarding is recreated;
read the current value from Manta **Settings → Port Forwarding** before using
the sample client. As reconfirmed on 2026-09-19, internal vLLM `8000/tcp` maps
to external `45503`, while the Core-facing gateway `8100/tcp` maps to external
`46944`. Product code must use the gateway mapping, never the vLLM mapping.
