# Agent A Stage 02 handoff

Stage: Agent A Stage 02 — MI300 VLM candidate evaluation
Status: **done**
Base: `main` @ `fee99c4`
Branch: `codex/agentA-stage02-vlm-evaluation`
PR: #4 (open; not merged)
Previous Stage: Agent A Stage 01 (`codex/agentA-stage01-contract-baseline`, PR #2 merged)

## Summary

Stage 02 is complete with the model choice fixed as:

- **Primary:** `Qwen/Qwen3-VL-30B-A3B-Instruct-FP8`, revision/hash
  `d9748a51ae66354c4dad665aab2c71f26cf2c8cd`.
- **Fallback:** `Qwen/Qwen2.5-VL-7B-Instruct`, revision/hash
  `cc594898137f460bfe9f0759e9844b3ce807cfb5`.
- **Comparison-only:** `Qwen/Qwen3-VL-32B-Instruct-FP8`, revision/hash
  `4bf2c2f39c37c0fede78bede4056e1f18cdf8109`.

All three Hub metadata records reported `license=apache-2.0`, `gated=false`,
and `private=false`. The selected primary and fallback both completed the
fixed workload under the conservative equivalent-cap rerun.

## Changed files

- `services/vlm-mi300/evaluation/benchmark_config.json`
- `services/vlm-mi300/evaluation/launch_vllm.sh`
- `services/vlm-mi300/evaluation/README.md`
- `services/vlm-mi300/evaluation/RESULTS.md`
- `docs/handoffs/agent-a-stage02.md`

No canonical product JSON Schema, OpenAPI document, migration, backend state,
RAG, SQLite, session, or Agent B-owned frontend/Speech Gateway file changed.
Raw JSONL, logs, generated images, model weights, caches, and review working
files remain outside Git on Manta under `/tmp/stage02-eval`.

## Schema/OpenAPI version

- Evaluation output: `stage02-eval.v1`.
- Raw records: `stage02-raw-result.v1`.
- Product contracts unchanged: JSON Schema Draft 2020-12, canonical
  `schema_version=0.1.0`, OpenAPI 3.1.0, API version 0.1.0.

## How to run

From the evaluation directory on Manta, run one model at a time. The launcher
uses `/usr/bin/python3.12`, the existing vLLM site-packages, and cache roots
under `/tmp`:

```bash
export EVAL_ROOT=/tmp/stage02-eval
export VLLM_PYTHON=/usr/bin/python3.12
export VLLM_SITE_PACKAGES=/mlsteam/workspace/qwen3-benchmark/qwen38-venv/lib/python3.12/site-packages
export STAGE02_GPU_MEMORY_UTILIZATION=0.48
bash launch_vllm.sh Qwen/Qwen3-VL-30B-A3B-Instruct-FP8 \
  d9748a51ae66354c4dad665aab2c71f26cf2c8cd qwen3-vl-30b-a3b-fp8-96gb
```

Use the fallback model and revision above to repeat the same fixed workload.
The benchmark uses `prompt.txt`, `response_schema.json`, 1280x1600 images,
temperature 0, top_p 1, max_tokens 1024, one warm-up, three measured calls,
and concurrency 1. The launcher now accepts
`STAGE02_GPU_MEMORY_UTILIZATION` (default `0.80`) and records the expanded
command in `work/logs/<slug>.command.txt`.

## Tests and results

- 10 deterministic synthetic textbook pages covered frontal, tilt, glare,
  dense 臺羅, illustration question, dialogue bubbles, low contrast,
  two-column, picture reasoning, and mixed annotations.
- Primary equivalent-cap run: 30/30 HTTP 200, JSON parse 100%, schema shape
  100%; P50 3.21693 s, P95 4.65890 s, mean completion 113.972 tok/s.
- Fallback equivalent-cap run: 30/30 HTTP 200, JSON parse 100%, schema shape
  100%; P50 1.39998 s, P95 2.18110 s, mean completion 202.662 tok/s.
- Human blind review: 30 anonymized rows, scored before opening the key;
  primary OCR/臺羅/scene/objective/reconstruction = 2.000/1.200/1.200/2.000/1.700;
  fallback = 2.000/0.900/0.600/2.000/1.600; answer leak 0/10 for both.
- Representative failure cases and complete aggregate evidence are recorded in
  `services/vlm-mi300/evaluation/RESULTS.md`.

## Fixtures

The evaluation dataset is generated deterministically from the checked-in
generator and manifest contract; no textbook photographs or student data are
committed. Product contract fixtures remain unchanged from Stage 01.

## Resource usage

- Hardware: AMD Instinct MI300X OAM SR-IOV, exposed `TOTAL_VRAM=196592 MB`,
  ROCm 7.0.0, HIP 7.0.51831-a3e329ad, vLLM 0.18.0.
- Equivalent-cap (`gpu_memory_utilization=0.48`) VRAM: primary 95,037 MB after
  load (95,217 MB after workload); fallback 94,074 MB after load; idle after
  shutdown 284 MB.
- The original exposed-slice comparison was also retained for 32B and showed
  12.1562/19.1934 s P50/P95; 32B is comparison-only rather than fallback.

## Known limits

- The lab exposes a 196 GB SR-IOV slice. `0.48` is a conservative allocator cap
  approximately equivalent to 94 GB; it is not proof of an isolated physical
  96 GB partition.
- Human review is one pass over deterministic synthetic pages; real textbook
  photographs and inter-rater reliability remain unmeasured.
- Qwen3 logs transient optional quantization-import and ROCm GELU warnings,
  but startup and all measured requests succeeded.
- The MI300 kit is stateless and must not contain RAG, SQLite, session state,
  product logic, persistent images, or prompt logs.

## Agent B can rely on

- Use `Qwen3-VL-30B-A3B-Instruct-FP8` at the pinned revision as the official
  MI300 primary.
- On load/health/timeout failure, use `Qwen2.5-VL-7B-Instruct` at its pinned
  revision as the official fallback. Do not substitute 32B without a new
  decision.
- Keep the product API, RAG, SQLite, session, and all product state on the
  Ryzen AI 9 laptop; MI300 receives only stateless image/prompt/schema
  inference requests.
- Product schema/OpenAPI versions and fixtures are unchanged from Stage 01.

## Next action

Stage 03 may consume the pinned primary/fallback pair and the launch evidence.
It must implement the stateless MI300 service and network policy without
moving backend/RAG/session state onto the accelerator host. PR #4 remains open
for review and has not been merged.
