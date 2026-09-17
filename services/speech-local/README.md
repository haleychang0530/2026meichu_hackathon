# Local Speech Gateway boundary

Owner: Agent B. Runtime: Ryzen AI 9 laptop.

Agent A defines only the API boundary in `packages/contracts/openapi/v0.1/speech-gateway.openapi.json`; ASR/TTS workers and device integration remain Agent B-owned. The gateway is localhost-only, half-duplex, and provides CPU fallback when NPU inference is unavailable.

Raw student audio is deleted after transcription and is never sent to MI300.
