# Agent B Stage 04 handoff

```text
Stage: Agent B Stage 04
Status: done
Branch: codex/agentB_stage04
Contract: v0.1.0 Speech Gateway OpenAPI (unchanged)
Checked: 2026-09-18 (Asia/Taipei)
```

## Changed files

- `services/speech-local/gateway.py`: localhost HTTP server, request IDs,
  restricted CORS, bounded queue, timeout, cancellation, CPU semaphore,
  half-duplex coordination, health/error envelopes, multipart parsing and
  in-memory resource diagnostics.
- `services/speech-local/workers.py`: ASR/TTS worker protocols, cancellation
  token, deterministic mock Breeze/MMS-TTS workers and in-memory WAV fixture.
- `services/speech-local/test_gateway.py`: seven core/HTTP integration tests.
- `services/speech-local/README.md`: runbook, boundary, privacy and scheduling
  notes.
- `apps/web/src/generated/speech.ts`: generated TypeScript from the canonical
  Speech OpenAPI.
- `apps/web/src/speech/gateway.ts`: browser Speech Gateway client, Mock client,
  MediaRecorder/Audio ownership and half-duplex state subscription.
- `apps/web/src/speech/gateway.test.ts`: Mock flow and HTTP request-shape tests.
- `apps/web/src/pages/StudentPage.tsx`, `apps/web/src/styles.css`: student UI
  controls and accessible speech-state feedback.
- `apps/web/README.md`: Mock/real speech mode runbook.

No Agent A canonical schema or OpenAPI file was modified.

## How to run

```powershell
python .\services\speech-local\gateway.py --host 127.0.0.1 --port 8200
python -m unittest discover -s services/speech-local -p "test_*.py" -v
```

The server is standard-library-only on Python 3.12.10 and defaults to
`127.0.0.1:8200`. It rejects non-local bind addresses and accepts only the
documented localhost Vite origins.

## Tests and results

- `python -m py_compile services/speech-local/workers.py services/speech-local/gateway.py`: pass.
- `python -m unittest discover -s services/speech-local -p "test_*.py" -v`: pass, 7 tests.
- `npm --prefix apps/web run typecheck`: pass.
- `npm --prefix apps/web test -- --run`: pass, 5 files / 11 tests.
- `npm --prefix apps/web run build`: pass; Vite production bundle generated.
- Browser smoke on `http://127.0.0.1:5173/session/demo-session/student`: pass;
  Mock UI completed start recording → stop/transcribe → submit → idle and
  prompt playback, with the speech state visible in the accessibility tree.
- HTTP integration covers `/local/health`, `/v1/audio/speech`,
  `/v1/audio/transcriptions`, request IDs, runtime-memory headers and CORS
  rejection.
- Core integration covers playback→record cancellation, record→play
  cancellation, duplicate-click single-flight, `/local/cancel`, worker crash
  recovery and safe state recovery.
- No request body, audio bytes, utterance text or worker exception text is
  written to logs. The mock ASR receives only audio byte count.

## Runtime and resource measurements

Environment: Windows Python 3.12.10 on the Stage 01 Ryzen AI 9 laptop.
One deterministic mock run after warmup measured:

| Operation | elapsed |
| --- | ---: |
| ASR mock | 0.10 ms |
| TTS mock | 0.14 ms |
| warmup (ASR + TTS) | 0.15 ms |

These are scheduler/mock timings, not Breeze or MMS-TTS quality/latency
claims. The same run reported:

- process RSS: 35,856,384 bytes;
- physical RAM: 33,413,771,264 bytes;
- available RAM: 16,362,745,856 bytes;
- safe reserve: 8,353,442,816 bytes (`max(25%, 6 GiB)`);
- runtime capacity after reserve: 25,060,328,448 bytes;
- final state: `IDLE`, queue depth: `0`.

`runtime_diagnostics()` records these values for local checks without expanding
the frozen v0.1 health body. The canonical health response reports the two
service entries with device, model revision, queue depth, status and recent
stable error.

## Accessibility checks

The student controls remain native buttons with visible focus styles. Speech
state is exposed through a polite live status (`待機`／`播放提示中`／`聆聽中`／
`辨識中`／`等待回饋`), and errors use the existing alert component with stable
fallback text. The browser smoke verified the state changes in the
accessibility tree. Full Narrator/NVDA and App narration matrix remains Stage
09.

## Known limits

- ASR and TTS are deterministic mock workers. Breeze-ASR CPU implementation is
  the next Stage 05 task; MMS-TTS integration remains Stage 07.
- `device_preference: npu` is accepted for forward compatibility but currently
  returns the reliable `cpu` path; no NPU inference is claimed.
- The v0.1 canonical health schema has no RAM property. RAM is therefore kept
  in the local-only `X-Speech-Runtime` health header and
  `runtime_diagnostics()` rather than creating an Agent B parallel health
  schema.
- The mock worker is in-process behind a worker protocol. A real model adapter
  may move heavy inference to a child process without changing the gateway
  routes or cancellation contract.
- The default frontend mode is Mock and does not request microphone permission.
  Set `VITE_SPEECH_MODE=real` and run the local Gateway to exercise browser
  `MediaRecorder` and real HTTP routes. The current prompt adapter creates a
  generated zh-TW demo utterance; Agent A/Core utterance orchestration will
  provide verified lesson speech in Stage 08.

## Agent A can rely on

- `SpeechGatewayService.health_payload()` returns exactly two v0.1
  `ServiceHealth` entries in `asr`, `tts` order.
- Every HTTP response carries `X-Request-ID`; errors use the shared v0.1
  envelope and stable ASR/TTS/validation codes.
- The gateway never calls MI300 and never persists raw audio.
- ASR/TTS jobs share one bounded executor and CPU semaphore, so at most one
  local audio inference is active. Opposite-direction work cancels the current
  operation before it proceeds.
- A successful transcription leaves the gateway in `EVALUATING`; the next
  speech request enters `SPEAKING`. Cancellation and failures return to
  `IDLE`.
- `StudentPage` can complete the Mock recording → transcription → evaluation →
  playback flow without a microphone and can be switched to the localhost
  client through `VITE_SPEECH_MODE=real`.

## Next action

Replace `MockASRWorker` with the measured Breeze-ASR-26 CPU adapter in Stage 05,
keeping `ASRWorker` and the gateway scheduler unchanged. Before the PR is
opened, the user will review this branch and confirm the PR base is `main`.
