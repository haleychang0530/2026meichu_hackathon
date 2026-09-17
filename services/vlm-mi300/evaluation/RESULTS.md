# Stage 02 MI300 VLM evaluation results

Status: **partial (provisional recommendation only)**

The requested candidates were exercised end-to-end on the authenticated Manta
terminal. The run is reproducible for the exposed GPU slice, but the device
reports 196,592 MB VRAM (MI300X OAM SR-IOV), not the 96 GB target stated in the
Stage 02 gate. The measurements therefore do not prove that either candidate
fits a 96 GB partition. A final model gate requires one rerun on the actual
96 GB allocation (or an equivalent memory cap).

## Fixed evaluation contract

- Dataset: stage02-dataset.v1 / synthetic-textbook-v1, 10 deterministic
  synthetic pages, 1280x1600. Coverage is frontal, tilt, glare, dense Tailo,
  illustration question, dialogue bubbles, low contrast, two-column,
  picture reasoning, and mixed annotations.
- Prompt: prompt.txt; output schema: response_schema.json.
- Sampling: temperature 0, top_p 1, max_tokens 1024, stream false,
  concurrency 1; one warm-up and three measured requests per page.
- Raw record schema: stage02-raw-result.v1; contract/API versions were not
  changed (canonical JSON Schema 2020-12, schema_version 0.1.0, OpenAPI 3.1.0,
  API 0.1.0).
- All measured requests for all three models returned HTTP 200 with valid JSON
  and the expected schema shape: 30/30 per model.

## Candidate comparison

| model (revision/sha) | license | weights download / load evidence | P50 / P95 (s) | mean completion tok/s | peak VRAM (MB) | blind quality mean / 2 |
|---|---|---:|---:|---:|---:|---:|
| Qwen/Qwen2.5-VL-7B-Instruct (cc594898137f460bfe9f0759e9844b3ce807cfb5) | Apache-2.0 | weights 7.53 s; model load 8.543 s; graph 8 s | 1.4045 / 2.1865 | 202.17 | 158,830 | 1.420 |
| Qwen/Qwen3-VL-32B-Instruct-FP8 (4bf2c2f39c37c0fede78bede4056e1f18cdf8109) | Apache-2.0 | download 311.589862 s; weights 17.88 s; model load 331.610977 s; graph 34 s | 12.1562 / 19.1934 | 29.15 | 157,906 | 1.620 |
| Qwen/Qwen3-VL-30B-A3B-Instruct-FP8 (d9748a51ae66354c4dad665aab2c71f26cf2c8cd) | Apache-2.0 | download 282.108665 s; weights 639.41 s; model load 923.497976 s; graph 22 s; multimodal warmup 5.252 s | 3.2309 / 4.6548 | 113.99 | 157,906 | 1.680 |

The 7B row is the baseline. The 32B run had 30/30 measured HTTP 200, JSON
parse and schema-shape successes. The 30B-A3B run also had 30/30 for each
metric. VRAM peaks are sampled from amd-smi; the post-stop idle reading was
284 MB. The peak is about 80% of the exposed 196,592 MB slice, not evidence of
96 GB operation.

## Human blind review

make_blind_review.py selected run 1 for each page, shuffled model labels, and
created 30 rows. I scored the rows against dataset/manifest.json before
opening blind_key.json; model confidence was not used. Scores are 0
(incorrect/missing), 1 (usable with correction), or 2 (faithful). leak is
the count of accessible reconstructions that reveal the answer.

| model | n | OCR | Tailo | scene | objective | reconstruction | leak |
|---|---:|---:|---:|---:|---:|---:|---:|
| Qwen2.5-VL-7B-Instruct | 10 | 2.000 | 0.900 | 0.600 | 2.000 | 1.600 | 0/10 |
| Qwen3-VL-32B-Instruct-FP8 | 10 | 2.000 | 1.400 | 0.700 | 2.000 | 2.000 | 0/10 |
| Qwen3-VL-30B-A3B-Instruct-FP8 | 10 | 2.000 | 1.200 | 1.200 | 2.000 | 1.700 | 0/10 |

Representative failure samples (after scoring) were:

- 7B: dense Tailo returned only one vocabulary item; glare returned only two
  vocabulary words; picture-reasoning and low-contrast scenes were generic or
  incorrect; dialogue vocabulary was word-level only.
- 32B: two-column and mixed-season scenes were generic; low-contrast omitted
  the sweeping/wiping actions; glare described the wrong scene; one dialogue
  Tailo token was misread.
- 30B-A3B: glare used the wrong people and lost a tone mark; tilt omitted the
  school-gate detail; dense-fruit scene described the wrong figures; market
  scene was an English paraphrase that omitted the child; two-column scene was
  generic with partial Tailo.

## Provisional decision

For this exposed MI300X slice, **Qwen3-VL-30B-A3B-Instruct-FP8 is the
provisional primary**: it had the best blind quality mean (1.680) and much
lower P50/P95 than the dense 32B candidate. **Qwen3-VL-32B-Instruct-FP8 is the
provisional fallback**: it had stronger Tailo and reconstruction averages than
the 7B baseline and completed all requests, but its latency is high. Neither
should be treated as the final 96 GB model selection until the memory-target
rerun passes.

## MI300 evidence and known limits

- GPU: AMD Instinct MI300X OAM, AMD MI300X_HWSRIOV_CVS_1VF, driver 6.16.13,
  exposed TOTAL_VRAM=196592 MB.
- Software: vLLM 0.18.0; torch 2.9.1+git8907517; HIP
  7.0.51831-a3e329ad8; ROCm 7.0.0; AMD SMI 26.0.0.
- Hugging Face API metadata for all three IDs reported sha equal to the
  pinned revision, license=apache-2.0, private=false, and gated=false.
- The project volume /mlsteam/workspace was full (0 bytes free). The launcher
  now isolates HOME, Hugging Face, XDG, vLLM, and Triton caches under /tmp.
- The original venv interpreter produced a remote I/O error. The reproducible
  workaround was /usr/bin/python3.12 with
  PYTHONPATH=/mlsteam/workspace/qwen3-benchmark/qwen38-venv/lib/python3.12/site-packages.
  Direct script mode also lacked urllib; run_benchmark.py now uses
  http.client, and the recorded run invoked it through runpy.
- Both Qwen3 launches logged transient optional quantization import errors;
  the services reached Application startup complete and all measured calls
  passed. The first 32B launch additionally failed on NFS .aiter space before
  the /tmp HOME retry; both logs were preserved on the Manta run.
- Review was one human pass over deterministic synthetic pages; no real
  textbook photographs or student data were used. Inter-rater reliability and
  96 GB behavior remain unmeasured.

## Reproduction

From the evaluation directory on Manta (one model at a time):

    export EVAL_ROOT=/tmp/stage02-eval
    export VLLM_PYTHON=/usr/bin/python3.12
    export VLLM_SITE_PACKAGES=/mlsteam/workspace/qwen3-benchmark/qwen38-venv/lib/python3.12/site-packages
    bash launch_vllm.sh Qwen/Qwen3-VL-30B-A3B-Instruct-FP8 d9748a51ae66354c4dad665aab2c71f26cf2c8cd qwen3-vl-30b-a3b-fp8
    /usr/bin/python3.12 -c "import runpy,sys; sys.argv=['run_benchmark.py', '--base-url', 'http://127.0.0.1:8000/v1', '--model', 'Qwen/Qwen3-VL-30B-A3B-Instruct-FP8', '--revision', 'd9748a51ae66354c4dad665aab2c71f26cf2c8cd', '--dataset', 'dataset', '--output', 'work/results/qwen3-vl-30b-a3b-fp8', '--prompt', 'prompt.txt', '--schema', 'response_schema.json', '--runs', '3', '--warmup', '1', '--timeout', '300', '--max-tokens', '1024']; runpy.run_path('run_benchmark.py', run_name='__main__')"
    python3 make_blind_review.py --results work/results/*/raw_results.jsonl --output work/blind-review

Use the same command with the model/revision/output values in
benchmark_config.json for the other candidates. Keep the raw JSONL, server
logs, PID files, and VRAM traces outside Git; only this aggregate report and
the harness are committed.
