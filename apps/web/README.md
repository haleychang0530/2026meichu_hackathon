# Web application boundary

Owner: Agent B. Runtime: Ryzen AI 9 laptop browser.

Agent A defines only the contract boundary here; React/Vite components, accessibility behavior, adapters, and generated TypeScript integration remain Agent B-owned. The web app calls the laptop Core Backend and local Speech Gateway only. It never calls MI300.

Student routes must not receive or retain answer keys, model confidence, teacher controls, evidence, or full teacher-review Lesson objects.

## Stage 03 camera and upload flow

`/capture` now provides a keyboard-operable camera preview, camera selection,
photo capture, and a file-upload fallback. Camera permission failure never
blocks the file path. Before a photo is accepted, the browser:

- corrects the decoded orientation by drawing through a canvas (which also
  removes EXIF metadata);
- crops to the selected bounded rectangle (full-page crop is the default);
- limits the long edge to 4096 px and compresses to JPEG no larger than 8 MiB;
- checks minimum 640×480 resolution, blur, underexposure, overexposure, and
  supported type; and
- keeps only a short-lived object URL for the local preview.

Blur and exposure are warnings that require an explicit user override. Invalid
type, low resolution, and over-size output are blocking checks; Core Backend
must repeat validation. The current v0.1 multipart contract is
`POST /api/lessons/analyze` with `image`, `language=nan-TW`, and
`use_fixture_on_failure=true`. Agent A Stage 04 now provides the runtime
handler. The real adapter uses the Stage 04 health endpoint as its capture
entrypoint, reports `X-Provider-Mode`, and keeps the Stage 08 session button
disabled until the session API exists.

Run the Stage 03 checks from the repository root:

```powershell
cd apps/web
npm run test
npm run typecheck
npm run build
```

To run the real Stage 03 upload path against the laptop Core Backend:

```powershell
$env:VITE_DATA_MODE = 'real'
$env:VITE_CORE_API_BASE_URL = 'http://127.0.0.1:8000'
npm run dev
```

Start Core in `demo` profile first. The capture page can upload and analyze a
prepared image now; lesson confirmation and session creation remain Agent A
Stage 08 runtime work.

## Stage 04 speech wiring

The student page now uses `SpeechGatewayClient` for the local half-duplex
boundary. The default `VITE_SPEECH_MODE=mock` path completes recording →
transcription → evaluation → playback without microphone permission, so the
frontend walkthrough is deterministic. To call the localhost Gateway instead:

```powershell
$env:VITE_SPEECH_MODE = 'real'
$env:VITE_SPEECH_GATEWAY_BASE_URL = 'http://127.0.0.1:8200'
npm run dev
```

The release profile is CPU-only: the web client sends
`device_preference=cpu` by default, so AMD Ryzen AI Software and Conda are not
required. A future NPU experiment may explicitly set
`VITE_SPEECH_ASR_DEVICE` to `auto` or `npu` after its runtime and model gates
are complete.

Start `services/speech-local/gateway.py` first for real mode. On the student
page, `開始回答` starts listening; the same control stops recording, sends the
multipart transcription request, and submits the returned transcript through
the existing adapter. `播放提示` requests WAV speech. Starting either
direction cancels the other, and `停止音訊／暫停` releases browser media.

The generated `src/generated/speech.ts` is derived from the canonical Speech
OpenAPI. Full Core session orchestration and the 10-round student flow remain
Stage 08; App narration and Narrator/NVDA integration remain Stage 09.
