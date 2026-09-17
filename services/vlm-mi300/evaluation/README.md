# Stage 02 MI300 VLM evaluation

This directory is a reproducible evaluation kit, not a product service. It keeps the MI300 role stateless: images, prompt, and schema are sent to the already running OpenAI-compatible endpoint; RAG, sessions, SQLite, and product logic are not installed on MI300.

## Fixed conditions

- Dataset: 10 deterministic synthetic Taiwanese-language textbook pages at 1280x1600.
- Coverage: frontal, tilt, glare, dense Tailo, illustration question, dialogue bubbles, low contrast, two-column layout, picture reasoning, and mixed annotations.
- Sampling: temperature 0, top_p 1, max_tokens 1024, concurrency 1.
- One warm-up plus three measured requests per image and model.
- The same `prompt.txt` and `response_schema.json` are used for every model.
- Human review uses anonymized model labels. The model's self-reported confidence is never used as the quality score.

The synthetic pages are generated at runtime and are not committed as binaries. This prevents real textbook photos, student data, model weights, caches, and large artifacts from entering Git.

## Generate the dataset

Use a CJK font with Traditional Chinese glyph coverage:

```bash
python3 generate_synthetic_dataset.py \
  --font /path/to/NotoSansTC-Regular.ttf \
  --output work/dataset
```

## Run one model

The Manta project volume can be full even when the LAB overlay has capacity. The
launcher pins Hugging Face, vLLM, XDG, and Triton caches under `/tmp`, records the
exact command, PID, load time, and VRAM snapshots, and waits for `/v1/models`:

```bash
bash launch_vllm.sh \
  Qwen/Qwen2.5-VL-7B-Instruct \
  cc594898137f460bfe9f0759e9844b3ce807cfb5 \
  qwen25-vl-7b
```

With exactly one model running, execute the fixed workload:

```bash
python3 run_benchmark.py \
  --base-url http://127.0.0.1:8000/v1 \
  --model Qwen/Qwen2.5-VL-7B-Instruct \
  --revision cc594898137f460bfe9f0759e9844b3ce807cfb5 \
  --dataset work/dataset \
  --output work/results/qwen25-vl-7b
```

Repeat without changing dataset, prompt, schema, sampling, image size, or run count for the 32B dense FP8 and 30B-A3B FP8 candidates in `benchmark_config.json`.

On the Manta terminal used for this Stage, the project NFS was full and the
saved venv intermittently returned a remote-I/O error.  The reproducible
workaround was `/usr/bin/python3.12` with
`PYTHONPATH=/mlsteam/workspace/qwen3-benchmark/qwen38-venv/lib/python3.12/site-packages`;
keep `HOME`, `HF_HOME`, `XDG_CACHE_HOME`, `VLLM_CACHE_ROOT`, and
`TRITON_CACHE_DIR` under `/tmp` (the launcher does this automatically).  If
direct script execution is affected by the remote interpreter, invoke the
runner through `runpy`:

```bash
/usr/bin/python3.12 -c "import runpy,sys; sys.argv=['run_benchmark.py', '--base-url', 'http://127.0.0.1:8000/v1', '--model', 'Qwen/Qwen3-VL-30B-A3B-Instruct-FP8', '--revision', 'd9748a51ae66354c4dad665aab2c71f26cf2c8cd', '--dataset', 'work/dataset', '--output', 'work/results/qwen3-vl-30b-a3b-fp8', '--prompt', 'prompt.txt', '--schema', 'response_schema.json', '--runs', '3', '--warmup', '1', '--timeout', '300', '--max-tokens', '1024']; runpy.run_path('run_benchmark.py', run_name='__main__')"
```

## Blind review

```bash
python3 make_blind_review.py \
  --results work/results/*/raw_results.jsonl \
  --output work/blind-review
```

Score each field against `work/dataset/manifest.json`:

- `0`: incorrect/missing; `1`: materially usable with correction; `2`: faithful.
- `answer_leak_0_1`: `1` if the accessible reconstruction reveals the answer.
- Reviewers must not open `blind_key.json` until all rows are scored.

## Evidence requirements

Preserve the model ID, exact revision, license, full start command, service PID, vLLM/ROCm versions, load time, VRAM before/after/peak, raw JSONL, HTTP/schema failures, P50/P95, token throughput, and ROCm errors. A candidate cannot be selected when any required model or human blind score is missing; report the Stage as `partial` instead.
