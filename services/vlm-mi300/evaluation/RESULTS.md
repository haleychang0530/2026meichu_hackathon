# Stage 02 MI300 VLM evaluation results

Status: **done**

The Stage 02 model decision is fixed. `Qwen/Qwen3-VL-30B-A3B-Instruct-FP8`
is the primary and `Qwen/Qwen2.5-VL-7B-Instruct` is the fallback. The
Qwen3-VL-32B-FP8 run remains comparison evidence only and is not used as the
fallback for the target deployment.

The fit gate was rerun with the same workload on the available MI300X
SR-IOV slice using `--gpu-memory-utilization 0.48`. The device exposes
196,592 MB, so this is a conservative approximately 94 GB allocator cap and
not an isolated physical 96 GB partition. Both selected models booted and
completed the complete workload under that cap; the allocation caveat remains
explicit below.

## Locked candidates and provenance

| role | model | immutable revision/hash | license source |
|---|---|---|---|
| primary | `Qwen/Qwen3-VL-30B-A3B-Instruct-FP8` | `d9748a51ae66354c4dad665aab2c71f26cf2c8cd` | Hugging Face model metadata: `apache-2.0`, `gated=false` |
| fallback | `Qwen/Qwen2.5-VL-7B-Instruct` | `cc594898137f460bfe9f0759e9844b3ce807cfb5` | Hugging Face model metadata: `apache-2.0`, `gated=false` |
| comparison-only | `Qwen/Qwen3-VL-32B-Instruct-FP8` | `4bf2c2f39c37c0fede78bede4056e1f18cdf8109` | Hugging Face model metadata: `apache-2.0`, `gated=false` |

The revision values are the exact Hub commit hashes recorded by the
authenticated MI300 run. No model weights, tokens, or cache directories are
committed.

## Fixed evaluation contract

- Dataset: `stage02-dataset.v1` / `synthetic-textbook-v1`, 10 deterministic
  synthetic pages at 1280x1600.
- Cases: frontal market, tilted school scene, glare, dense 臺羅 fruit, an
  illustration question, dialogue bubbles, low contrast, two-column text,
  picture reasoning, and mixed annotations.
- Prompt: `prompt.txt`; output schema: `response_schema.json`.
- Sampling: temperature 0, top_p 1, `max_tokens=1024`, stream false,
  concurrency 1; one warm-up and three measured requests per page.
- Evaluation/raw schemas: `stage02-eval.v1` and `stage02-raw-result.v1`.
  Product contracts were unchanged: JSON Schema Draft 2020-12,
  `schema_version=0.1.0`, OpenAPI 3.1.0, API 0.1.0.

## Equivalent-cap performance evidence

The following summaries are from the same 10-page workload, with 30 measured
requests per model. All requests returned HTTP 200, valid JSON, and the
expected schema shape.

| role/model | cap run | samples | HTTP/JSON/schema | P50 (s) | P95 (s) | mean completion tok/s | VRAM after load (MB) |
|---|---|---:|---|---:|---:|---:|---:|
| primary, Qwen3-VL-30B-A3B-FP8 | `gpu_memory_utilization=0.48` | 30 | 30/30/30 | 3.21693 | 4.65890 | 113.972 | 95,037 (95,217 after workload) |
| fallback, Qwen2.5-VL-7B-Instruct | `gpu_memory_utilization=0.48` | 30 | 30/30/30 | 1.39998 | 2.18110 | 202.662 | 94,074 |

`amd-smi` reported 196,592 MB total and 284 MB after process shutdown. No
out-of-memory event occurred in either cap run. The original exposed-slice
comparison, retained for context, measured P50/P95 of 3.2309/4.6548 s for
30B, 1.4045/2.1865 s for 7B, and 12.1562/19.1934 s for 32B at 0.80
utilization.

## Human blind review

`make_blind_review.py` selected run 1 for each page, shuffled model labels, and
created 30 rows. I scored every row against `dataset/manifest.json` before
opening the key. Scores are 0 (incorrect/missing), 1 (usable with correction),
or 2 (faithful); model confidence was not used.

| model | n | OCR | 臺羅 | scene | objective | reconstruction | answer leak |
|---|---:|---:|---:|---:|---:|---:|---:|
| Qwen2.5-VL-7B-Instruct (fallback) | 10 | 2.000 | 0.900 | 0.600 | 2.000 | 1.600 | 0/10 |
| Qwen3-VL-32B-Instruct-FP8 (comparison-only) | 10 | 2.000 | 1.400 | 0.700 | 2.000 | 2.000 | 0/10 |
| Qwen3-VL-30B-A3B-Instruct-FP8 (primary) | 10 | 2.000 | 1.200 | 1.200 | 2.000 | 1.700 | 0/10 |

Representative failure samples were retained in the aggregate review notes:

- **7B fallback:** dense 臺羅 returned one vocabulary item; glare returned two
  words; picture-reasoning and low-contrast scenes were generic or incorrect;
  dialogue vocabulary was word-level only.
- **30B primary:** glare used the wrong people and lost a tone mark; tilt
  omitted the school-gate detail; dense-fruit described the wrong figures;
  market was an English paraphrase that omitted the child; two-column was
  generic with partial 臺羅.
- **32B comparison-only:** two-column and mixed-annotation scenes were
  generic; low-contrast omitted sweeping/wiping actions; glare described the
  wrong scene; one dialogue 臺羅 token was misread.

The primary is selected because it provides the strongest scene understanding
of the two deployable choices while remaining much faster than 32B. The 7B
fallback has materially lower latency and boot evidence under the same cap,
with lower blind scene/臺羅 scores but complete structured-output behavior.

## Launch parameters and reproducible commands

The evaluation launcher runs one model at a time with:

```text
--host 127.0.0.1 --port 8000 --tensor-parallel-size 1
--max-model-len 8192 --gpu-memory-utilization ${STAGE02_GPU_MEMORY_UTILIZATION:-0.80}
--served-model-name <model> --revision <hash>
```

For the completed equivalent-cap gate on Manta:

```bash
export EVAL_ROOT=/tmp/stage02-eval
export VLLM_PYTHON=/usr/bin/python3.12
export VLLM_SITE_PACKAGES=/mlsteam/workspace/qwen3-benchmark/qwen38-venv/lib/python3.12/site-packages
export STAGE02_GPU_MEMORY_UTILIZATION=0.48
bash launch_vllm.sh Qwen/Qwen3-VL-30B-A3B-Instruct-FP8 \
  d9748a51ae66354c4dad665aab2c71f26cf2c8cd qwen3-vl-30b-a3b-fp8-96gb
```

Repeat the command with the fallback model and revision from the provenance
table. The fixed workload is:

```bash
/usr/bin/python3.12 -c "import sys; sys.argv=['run_benchmark.py', '--base-url', 'http://127.0.0.1:8000/v1', '--model', 'Qwen/Qwen3-VL-30B-A3B-Instruct-FP8', '--revision', 'd9748a51ae66354c4dad665aab2c71f26cf2c8cd', '--dataset', 'dataset', '--output', 'work/results/qwen3-vl-30b-a3b-fp8-96gb', '--prompt', 'prompt.txt', '--schema', 'response_schema.json', '--runs', '3', '--warmup', '1', '--timeout', '300', '--max-tokens', '1024']; __file__='run_benchmark.py'; exec(compile(open('run_benchmark.py','rb').read(), 'run_benchmark.py', 'exec'))"
```

The `__file__` wrapper is required only on the Manta image when direct script
execution selects the remote interpreter path; it does not change the
payload, schema, or sampling conditions. Keep JSONL, server logs, VRAM traces,
and generated images under `/tmp/stage02-eval` and out of Git.

## Runtime and known limits

- Hardware: AMD Instinct MI300X OAM SR-IOV, driver 6.16.13; exposed
  `TOTAL_VRAM=196592 MB`.
- Software: vLLM 0.18.0; torch 2.9.1+git8907517; HIP
  7.0.51831-a3e329ad; ROCm 7.0.0; AMD SMI 26.0.0.
- The Qwen3 service logs transient optional quantization-import and ROCm GELU
  warnings but reached application startup and passed all measured requests.
- The cap is a conservative allocator cap on a 196 GB SR-IOV slice, not proof
  of behavior on an isolated physical 96 GB partition.
- Review is one human pass over deterministic synthetic pages; real textbook
  photographs, inter-rater reliability, and student data were not evaluated.
- MI300 remains stateless: no RAG, SQLite, session, product API, or persistent
  image/prompt logging is part of this evaluation kit.
