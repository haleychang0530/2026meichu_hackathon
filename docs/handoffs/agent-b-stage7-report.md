# Agent B Stage 07 handoff

```text
Stage: Agent B Stage 07 — MMS-TTS, language routing, and audio cache
Status: partial
Branch: codex/agentB_stage07
Contract: v0.1.0 Speech Gateway OpenAPI unchanged
Runtime profile: CPU-only
Model: facebook/mms-tts-nan @ f28526a6caaf9dc55e030da83008c933f6a1978b
```

## Changed files

- `services/speech-local/tts.py`: pinned lazy MMS worker, POJ vocabulary gate,
  route planner, WAV writer/concatenation, bounded cache, and approved fallback
  manifest reader.
- `services/speech-local/workers.py`: explicit `create_tts_worker("mms")`
  factory while preserving Mock as the test-safe default.
- `services/speech-local/gateway.py`: explicit MMS CLI/env configuration,
  warmup wiring, model/cache/fallback settings, and safe TTS worker reasons.
- `apps/web/src/speech/gateway.ts`: ordered per-segment language routing;
  browser Web Speech for `zh-TW`, localhost gateway for `nan-TW`, and strict
  cancellation so speech sources do not overlap.
- `services/speech-local/test_tts.py`: offline tests for gates, cache hits,
  fallback hash checking, and ordered concatenation.
- `services/speech-local/fallback/prerecorded_manifest.json`: 30 planned
  fallback entries, all pending owner/consultant approval.
- `docs/device/mms-tts-nan.md`: runtime, license, and operator instructions.
- `docs/reports/agent-b-stage07-mms-tts-listening.md`: 30-sentence listening
  report with honest pending status.

## How to run

```powershell
python -m unittest discover -s services/speech-local -p "test_*.py" -v
npm --prefix apps/web run typecheck
npm --prefix apps/web test -- --run
```

For an explicitly provisioned local model:

```powershell
& services/speech-local/.venv/Scripts/python.exe services/speech-local/gateway.py `
  --asr-backend breeze --tts-backend mms --tts-local-files-only
```

## Tests and current limits

- Offline worker/router/cache tests do not download model weights.
- The formal 30-sentence human naturalness/intelligibility review is not
  claimed complete because no owner-authorized speech set or consultant
  ratings were supplied in this checkout.
- The speech venv currently has the Stage 05 CPU ASR packages but not Torch or
  Transformers; installing the pinned TTS runtime and provisioning the model
  remains an explicit device setup step.
- The model license is CC-BY-NC 4.0; public/commercial use requires a license
  review before enabling the MMS backend.

## Agent A can rely on

- MMS receives only `poj_citation` from `verified`/`converted` nan segments
  with `tts_provider=mms-tts-nan`.
- `needs_review`, unknown POJ characters, model/runtime failure, and missing
  approved recordings fail closed with `prerecorded_audio` in the existing
  error envelope.
- The frontend routes Chinese UI speech to Web Speech and waits for each
  segment; it never sends Hanji to the nan model.
- ASR and TTS still use the one Gateway CPU semaphore.
- No canonical schema, OpenAPI file, session state, or student-safe boundary
  was changed.

## Next action

Install/provision the pinned CPU runtime, run the 30-sentence listening review,
fill only owner-approved manifest entries with hashes, then rerun the full
Gateway/frontend regression before asking the repository owner whether to open
the PR.  Do not merge without explicit authorization.
