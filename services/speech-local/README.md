# Local Speech Gateway

Owner: Agent B. Runtime: Ryzen AI 9 laptop. Stage: 05.

The gateway implements the frozen v0.1 boundary in
`packages/contracts/openapi/v0.1/speech-gateway.openapi.json` with a
localhost-only, half-duplex, CPU-first scheduler. The mock workers remain the
default for contract tests; Stage 05 adds an explicit Breeze-ASR-26 CPU path
using the pinned faster-whisper/CTranslate2 runtime.

The current MVP/release profile is CPU-only. AMD Ryzen AI Software, Conda,
VitisAI, NPU encoder caches, and `whisper.cpp` NPU binaries are optional
research dependencies and are not required to start this gateway. The web
client sends `device_preference=cpu` by default; `auto`/`npu` remain compatible
API values for a future explicitly enabled NPU profile.

## Run

From the repository root:

```powershell
python .\services\speech-local\gateway.py --host 127.0.0.1 --port 8200
```

The default `mock` backend does not download model weights. To install the
CPU runtime in the local speech environment:

```powershell
python -m venv services/speech-local/.venv
& services/speech-local/.venv/Scripts/python.exe -m pip install -r services/speech-local/requirements.txt
```

Start the pinned CPU Breeze backend explicitly. The first warmup/transcription
downloads the CT2 model revision `7bf9dadb2f7f2bb418e82b3f074549fda82f7f47`
unless `--asr-model-path` points at an already prepared local model:

```powershell
& services/speech-local/.venv/Scripts/python.exe services/speech-local/gateway.py `
  --asr-backend breeze --asr-cpu-threads 4 --port 8200
```

`BREEZE_ASR_MODEL_PATH`, `BREEZE_ASR_MODEL_REVISION`,
`BREEZE_ASR_LOCAL_FILES_ONLY`, and `BREEZE_ASR_CPU_THREADS` are available as
environment overrides. Model files and local runtime output are not tracked.

The server refuses non-local bind addresses. The browser may use the
development origins `http://127.0.0.1:5173`, `http://localhost:5173`,
`http://127.0.0.1:4173`, and `http://localhost:4173`; other origins are
rejected.

The service exposes:

- `GET /local/health`
- `POST /local/warmup`
- `POST /local/cancel`
- `POST /v1/audio/transcriptions` (multipart `file` + `language`)
- `POST /v1/audio/speech` (canonical v0.1 `utterance`, WAV only)

Every response carries `X-Request-ID`. Error responses use the shared v0.1
error envelope and never include worker exception text.

## Scheduling and privacy

`SpeechGatewayService` owns a bounded inference queue, a cooperative cancel
token, single-flight protection for duplicate ASR/TTS requests, a timeout, and
one CPU inference semaphore shared by ASR and TTS. Starting a new recording
cancels playback; starting playback cancels recording/transcription. Successful
ASR ends in `EVALUATING` so Core Backend can decide the next product action;
playback, cancellation, and failures return to `IDLE`.

The Breeze worker decodes browser audio in memory, converts it to 16 kHz mono
float32 PCM, applies bounded volume normalization, and optionally trims
silence with a deterministic energy VAD. It passes `language="zh"` to Breeze,
which emits Mandarin Chinese characters for Taigi input; `nan-TW` remains the
product/API language label for the caller. Raw bytes and transcripts are not
written by the Gateway.

Audio bytes are held in memory only for the transcription request and are
dropped after the queued worker completes. The Gateway emits no request body,
audio bytes, or utterance content in logs. Runtime diagnostics retain only
queue/state/memory metadata.
The canonical v0.1 health body remains unchanged; its two service entries
report device, model revision, queue depth, status, and recent stable errors.
The health response additionally exposes local-only metadata in the
`X-Speech-Runtime` header (and exposes that header to an allowed browser
origin); `SpeechGatewayService.runtime_diagnostics()` supplies the same RAM
snapshot to device checks without changing Agent A's frozen schema.

## Tests

```powershell
python -m unittest discover -s services/speech-local -p "test_*.py" -v
```

The Stage 05 benchmark requires an operator-supplied manifest with at least 20
authorized recordings. Start from
`services/speech-local/benchmarks/cpu-cases.example.json`, fill in the audio
paths and authorization metadata, then run:

```powershell
& services/speech-local/.venv/Scripts/python.exe scripts/benchmark_breeze_cpu.py `
  --manifest path\to\cpu-cases.json `
  --output services/speech-local/.runtime/breeze-cpu-benchmark.json
```

The report records model revision, load time, per-case latency, real-time
factor, RSS peak, VAD/preprocessing metrics, expected no-speech rejections,
unexpected failures, and transcript hashes.
Full raw/normalized transcripts are opt-in with
`--include-transcripts` and should only be used for an authorized non-student
test set.

The integration suite covers the HTTP routes and localhost CORS, playback ↔
recording cancellation, duplicate-click single-flight behavior, CPU fallback,
worker crash recovery, state recovery, and in-memory WAV output.

Raw student audio is never sent to MI300 and is not persisted by this service.
