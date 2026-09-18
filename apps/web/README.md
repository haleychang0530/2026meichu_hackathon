# Web application boundary

Owner: Agent B. Runtime: Ryzen AI 9 laptop browser.

Agent A defines only the contract boundary here; React/Vite components, accessibility behavior, adapters, and generated TypeScript integration remain Agent B-owned. The web app calls the laptop Core Backend and local Speech Gateway only. It never calls MI300.

Student routes must not receive or retain answer keys, model confidence, teacher controls, evidence, or full teacher-review Lesson objects.

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

Start `services/speech-local/gateway.py` first for real mode. On the student
page, `開始回答` starts listening; the same control stops recording, sends the
multipart transcription request, and submits the returned transcript through
the existing adapter. `播放提示` requests WAV speech. Starting either
direction cancels the other, and `停止音訊／暫停` releases browser media.

The generated `src/generated/speech.ts` is derived from the canonical Speech
OpenAPI. Full Core session orchestration and the 10-round student flow remain
Stage 08; App narration and Narrator/NVDA integration remain Stage 09.
