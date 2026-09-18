# Local Speech Gateway

Owner: Agent B. Runtime: Ryzen AI 9 laptop. Stage: 04.

The gateway implements the frozen v0.1 boundary in
`packages/contracts/openapi/v0.1/speech-gateway.openapi.json` with Python's
standard library. It is localhost-only, half-duplex, and CPU-first. The
mock workers stand in for the Stage 05 Breeze-ASR and Stage 07 MMS-TTS workers;
their protocols are the integration seam for those real implementations.

## Run

From the repository root:

```powershell
python .\services\speech-local\gateway.py --host 127.0.0.1 --port 8200
```

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

Audio bytes are held in memory only for the transcription request. The gateway
passes only the byte count to the mock ASR worker, drops the request bytes before
queueing the job, writes no recordings, and emits no request body or utterance
content in logs. Runtime diagnostics retain only queue/state/memory metadata.
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

The integration suite covers the HTTP routes and localhost CORS, playback ↔
recording cancellation, duplicate-click single-flight behavior, CPU fallback,
worker crash recovery, state recovery, and in-memory WAV output.

Raw student audio is never sent to MI300 and is not persisted by this service.
