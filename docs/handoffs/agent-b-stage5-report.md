# Agent B Stage 05 handoff

```text
Stage: Agent B Stage 05 — Breeze-ASR-26 CPU baseline
Status: partial
Branch: codex/agentB_stage05
Base: main @ 59f8237
Contract: v0.1.0 / Speech Gateway OpenAPI unchanged
Checked: 2026-09-18 (Asia/Taipei)
```

## Why the status is partial

The CPU worker, preprocessing path, Gateway wiring, pinned runtime, and local
smoke measurement are implemented. The required quality/performance report
over at least 20 representative recordings is not claimed complete because
this checkout contains no authorized Mandarin, Mandarin–Taigi mixed, or child
speech recordings. The benchmark harness rejects fewer than 20 cases and
requires the six Stage 05 categories instead of filling the report with
synthetic tones or invented CER/RTF values.

## Changed files

- `services/speech-local/audio.py`: in-memory browser/WAV decode, 16 kHz mono
  float32 conversion, resampling, bounded volume normalization, deterministic
  energy VAD, and stable empty/short/invalid input reasons.
- `services/speech-local/workers.py`: lazy `BreezeASR26CPUWorker`, pinned CT2
  revision, CPU INT8 settings, explicit `language="zh"`, preprocessing
  metrics, cancellation checkpoints, and backend factory.
- `services/speech-local/gateway.py`: passes audio only in memory to the worker,
  preserves the existing HTTP contract, returns safe preprocessing reasons,
  exposes explicit `--asr-backend breeze` configuration, and handles Windows
  Hugging Face cache permissions without requiring symlinks.
- `services/speech-local/requirements.txt`: tested Python 3.12 Windows lock
  including `faster-whisper==1.2.1`, `ctranslate2==4.8.2`, and `numpy==2.3.5`.
- `services/speech-local/test_audio.py`, `test_workers.py`: 8 preprocessing
  and worker tests without model downloads.
- `scripts/benchmark_breeze_cpu.py`: authorized 20-case benchmark runner that
  records timings, RTF, RSS, preprocessing metrics, expected no-speech
  rejections, unexpected failures, and transcript hashes; full transcript
  output is opt-in.
- `services/speech-local/benchmarks/cpu-cases.example.json`: six-category,
  20-case manifest template.
- `services/speech-local/README.md`, `.gitignore`: setup, runbook, privacy,
  and local-runtime guidance.

No canonical schema, OpenAPI document, frontend code, student audio, model
weights, or model cache was added to Git. Existing untracked research/PDF/tmp
files were left untouched.

## Model and input baseline

- CT2 model: `paulpengtw/faster-whisper-Breeze-ASR-26`
- Revision: `7bf9dadb2f7f2bb418e82b3f074549fda82f7f47`
- Compute: CTranslate2 `int8`, CPU, 4 threads, beam size 5, one worker.
- Runtime: `faster-whisper==1.2.1`, `ctranslate2==4.8.2`, `av==18.1.0`,
  `numpy==2.3.5`, Python 3.12.10.
- The model card and CT2 conversion identify Apache 2.0 licensing. Model
  weights are cached outside the repository.
- Input is decoded in memory and converted to 16 kHz, mono, float32. The
  Gateway retains the API language label (`nan-TW`/`zh-TW`), while the model is
  explicitly decoded with `language="zh"` because its documented output is
  Mandarin Chinese characters for Taigi input.
- A single request is limited to 16 MiB by the Gateway and 60 seconds by the
  CPU worker. VAD rejects no-speech input and the worker reports a keyboard
  fallback for invalid/too-short audio.

## How to run

```powershell
python -m unittest discover -s services/speech-local -p "test_*.py" -v

& services/speech-local/.venv/Scripts/python.exe services/speech-local/gateway.py `
  --asr-backend breeze --asr-local-files-only --asr-cpu-threads 4 --port 8200

& services/speech-local/.venv/Scripts/python.exe scripts/benchmark_breeze_cpu.py `
  --manifest path\to\authorized-cpu-cases.json `
  --output services/speech-local/.runtime/breeze-cpu-benchmark.json
```

The first non-local run downloads the pinned model revision. Use
`--asr-model-path` with a pre-provisioned model directory for offline startup.

## Tests and measured smoke results

- Standard-library Python tests plus the Breeze fake-model tests: **15 tests,
  OK**.
- `py_compile` for Gateway, workers, preprocessing, tests, and benchmark:
  **pass**.
- `git diff --check`: **pass**.
- Cached real model warmup: **6.170 s** on the Ryzen AI 9 laptop.
- Two-second in-memory PCM tone smoke: **6.799 s** inference, approximately
  **3.400 RTF**. This is a pipeline smoke measurement only; a tone is not a
  speech-quality sample and its transcript is intentionally not recorded.
- Real Breeze worker through the localhost multipart Gateway: **HTTP 200**,
  `device=cpu`, caller language label preserved as `nan-TW`, request ID header
  matched the JSON response, and no transcript content was printed. The
  cached-process run took **9,906 ms** end to end.
- Resource snapshot during the same process:

  - physical RAM: `33,413,771,264` bytes;
  - required reserve: `8,353,442,816` bytes (`max(25%, 6 GiB)`);
  - post-reserve runtime capacity: `25,060,328,448` bytes;
  - RSS after model load: `1,704,075,264` bytes;
  - RSS after the smoke inference: `2,196,971,520` bytes;
  - available RAM after smoke inference: `12,857,667,584` bytes.

The six-category 20-case measurement remains pending the authorized audio
manifest. Run output is designed to retain raw/normalized transcript pairs
only when `--include-transcripts` is explicitly supplied for a non-student
test set; otherwise it keeps hashes and lengths.

## Accessibility checks

No frontend or accessibility surface changed in this Stage. The Stage 04
student speech-state live region and native controls remain covered by the
previous handoff; this Stage only replaces the injected ASR worker path.

## Known limits

- The CTranslate2 call can only observe cancellation before and after native
  inference; a cancellation token cannot interrupt a currently running native
  decode. The Gateway still returns timeout/cancel safely and the shared CPU
  semaphore prevents overlapping ASR/TTS work.
- NPU inference is not implemented or claimed; Stage 06 owns the time-boxed
  NPU Go/No-Go decision.
- Actual CER, child-speech robustness, mixed-language quality, and real
  classroom RTF require the missing authorized 20-case manifest.
- Default Gateway startup remains Mock so development and contract tests never
  download model weights implicitly. Demo startup must opt into `breeze`.

## Agent A can rely on

- The public Speech Gateway routes and v0.1 response shape are unchanged.
- A real CPU request goes through the same bounded queue, timeout, half-duplex
  transitions, cancellation token, and ASR/TTS CPU semaphore as the Mock path.
- Raw audio is never written to disk or sent to MI300. The worker exposes only
  non-sensitive preprocessing metrics for local benchmark tooling.
- Successful real ASR returns the model's Chinese-character transcript with
  the caller's original `language` label and `device="cpu"`.
- No RAG, session, Teaching Agent, canonical schema, or generated type was
  changed.

## Next action

Provide or place an owner-authorized 20-case audio set, fill
`services/speech-local/benchmarks/cpu-cases.example.json`, run the benchmark,
and attach the generated report metadata before treating Stage 05 as `done`.
After review, open the PR against `main`; do not merge without explicit user
authorization.
