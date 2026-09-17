# Agent A Stage 02 handoff

Stage: Agent A Stage 02 — MI300 VLM candidate evaluation
Status: partial (provisional recommendation only)
Base: `main` @ `fee99c4`
Branch: `codex/agentA-stage02-vlm-evaluation`
Previous Stage: Agent A Stage 01 (`codex/agentA-stage01-contract-baseline`, PR #2 merged)

## Summary

- Added a reproducible, stateless MI300 evaluation kit covering a deterministic
  10-page, 1280x1600 synthetic textbook set with frontal, tilt, glare, dense
  臺羅, illustration, dialogue, low-contrast, two-column, picture-reasoning,
  and mixed-annotation cases.
- Exercised Qwen2.5-VL-7B-Instruct, Qwen3-VL-32B-Instruct-FP8, and
  Qwen3-VL-30B-A3B-Instruct-FP8 under one prompt, schema, image size, and
  sampling contract. All 30 measured requests per model returned HTTP 200,
  valid JSON, and the expected schema shape.
- Completed a human blind review before opening the model key. The exposed
  MI300X slice provisionally favors Qwen3-VL-30B-A3B-Instruct-FP8 as primary
  and Qwen3-VL-32B-Instruct-FP8 as fallback; this is not a final model gate.
- The device reports 196,592 MB VRAM rather than the Stage 02 96 GB target, so
  the result remains partial until an actual 96 GB allocation (or equivalent
  cap) is rerun.

## Changed files

- `services/vlm-mi300/evaluation/benchmark_config.json`
- `services/vlm-mi300/evaluation/prompt.txt`
- `services/vlm-mi300/evaluation/response_schema.json`
- `services/vlm-mi300/evaluation/generate_synthetic_dataset.py`
- `services/vlm-mi300/evaluation/launch_vllm.sh`
- `services/vlm-mi300/evaluation/run_benchmark.py`
- `services/vlm-mi300/evaluation/make_blind_review.py`
- `services/vlm-mi300/evaluation/README.md`
- `services/vlm-mi300/evaluation/RESULTS.md`
- `docs/handoffs/agent-a-stage02.md`

No canonical schema, OpenAPI document, fixture, backend state, RAG, SQLite,
session, or Agent B-owned frontend/Speech Gateway file was changed. Raw
JSONL, logs, images, model weights, caches, and review working files remain
outside Git on Manta under `/tmp/stage02-eval`.

## Schema/OpenAPI version

- Evaluation output: `stage02-eval.v1`; raw records: `stage02-raw-result.v1`.
- Product contracts unchanged: JSON Schema Draft 2020-12, canonical
  `schema_version` 0.1.0, OpenAPI 3.1.0, API version 0.1.0.

## How to run

From the repository root on Manta, generate the dataset with
`services/vlm-mi300/evaluation/generate_synthetic_dataset.py`, then launch one
model at a time with `launch_vllm.sh` and run the fixed workload described in
`services/vlm-mi300/evaluation/README.md`. The Stage run used
`/usr/bin/python3.12` plus the existing vLLM site-packages via `PYTHONPATH`;
the runner was invoked through `runpy` because direct script mode on that
image lacked `urllib`. Run `make_blind_review.py` after all raw JSONL files
are collected, and keep all evidence outside Git.

## Tests and results

- `python -m py_compile services/vlm-mi300/evaluation/*.py`: passed.
- `python scripts/test_contracts.py`: passed (`7` schemas, `3` OpenAPI
  documents/`45` responses, `18` schema fixtures, `10` student-safe fixtures).
- Manta workload: `30/30` measured HTTP, JSON, and schema successes for each
  of the three candidates; human blind review completed for all `30` rows.
- Candidate aggregate, latency, throughput, VRAM, load, license, and failure
  evidence is recorded in
  [`services/vlm-mi300/evaluation/RESULTS.md`](../../services/vlm-mi300/evaluation/RESULTS.md).

## Fixtures

The evaluation dataset is generated deterministically from the checked-in
generator and manifest contract; no textbook photographs or student data are
committed. Product contract fixtures remain unchanged from Stage 01.

## Resource usage

- Hardware: AMD Instinct MI300X OAM SR-IOV, exposed `TOTAL_VRAM=196592 MB`,
  ROCm 7.0.0, HIP 7.0.51831-a3e329ad, vLLM 0.18.0.
- Peak sampled VRAM: 158,830 MB (7B) and 157,906 MB (both Qwen3 candidates);
  idle after stop: 284 MB.
- Measured P50/P95: 1.4045/2.1865 s (7B), 12.1562/19.1934 s (32B), and
  3.2309/4.6548 s (30B-A3B). Detailed load/download timings are in RESULTS.

## Known limits

- The hardware allocation does not match the required 96 GB target; no final
  fit/selection claim is allowed.
- Review is one human pass over synthetic pages; inter-rater reliability and
  real textbook-photo performance are unmeasured.
- Both Qwen3 launches emitted transient optional quantization import errors,
  but reached application startup and passed the fixed workload. The first
  32B attempt also failed when NFS `.aiter` storage was full; the successful
  retry isolated caches under `/tmp`.

## Agent B can rely on

- The evaluation harness is stateless and does not move RAG, SQLite, session,
  or product logic onto MI300.
- Product API/schema versions and fixtures are unchanged and remain the
  Stage 01 source of truth.
- If an interim model choice is needed for exposed-slice experiments, use
  30B-A3B-FP8 as provisional primary and 32B-FP8 as provisional fallback,
  with the 96 GB limitation clearly surfaced.

## Next action

1. Re-run the same kit on a verified 96 GB MI300 allocation or an equivalent
   memory cap, preserving revisions and sampling conditions.
2. Reassess the blind failures and promote a model only after the 96 GB gate
   and any required real-photo validation pass.
