# MMS-TTS nan CPU profile

Stage 07 pins `facebook/mms-tts-nan` to Hub revision
`f28526a6caaf9dc55e030da83008c933f6a1978b`.

- Framework: `transformers==5.17.0` + `torch==2.8.0`
- Device: CPU only
- Output: mono, signed 16-bit PCM WAV at 16,000 Hz
- Default speed: `1.0`
- Reproducibility seed: `555`
- License: CC-BY-NC 4.0

The model card documents the `VitsModel`/`AutoTokenizer` loading path, the
16 kHz output configuration, and the need for a fixed seed when repeatable
waveforms are required:

- [MMS-TTS nan model card](https://huggingface.co/facebook/mms-tts-nan)
- [Transformers MMS documentation](https://huggingface.co/docs/transformers/model_doc/mms)
- [CC-BY-NC 4.0 license](https://creativecommons.org/licenses/by-nc/4.0/)

The non-commercial license must be reviewed before any public or commercial
deployment.  Model weights are downloaded or provisioned outside Git and are
never committed.

## Runtime

The Mock backend remains the test-safe default.  An explicit local run uses:

```powershell
& services/speech-local/.venv/Scripts/python.exe services/speech-local/gateway.py `
  --asr-backend breeze `
  --tts-backend mms `
  --tts-local-files-only
```

The first provision step may download the pinned model.  After provisioning,
`--tts-local-files-only` makes an offline demo fail clearly instead of silently
using a different revision.  The worker is lazy, so importing the gateway does
not require Torch or Transformers.

## Routing and safety

- `nan-TW` reaches MMS when the utterance provider is `mms-tts-nan` and
  `poj_citation` passes the pinned model vocabulary gate; `needs_review` does
  not block a valid POJ citation.
- Hanji, raw 臺羅, missing/invalid POJ, punctuation, upper-case text, and
  unknown characters never reach MMS.
- `zh-TW` UI/scaffolding is routed to browser Web Speech (Windows voice when
  available).  The server only uses an owner-approved prerecorded entry when
  browser speech is unavailable.
- Mixed paragraphs are played in source order.  The frontend awaits each
  segment and the server concatenates PCM chunks without overlap.

Audio cache files are content-addressed by provider, revision, normalized POJ,
and speed.  The local cache is atomic, bounded to 256 MiB/500 entries, and
expires entries after 14 days.  It lives below `services/speech-local/.runtime`
unless `MMS_TTS_CACHE_DIR` is set.

## Fallback approval

`services/speech-local/fallback/prerecorded_manifest.json` contains the 30
planned demo sentences, but entries are intentionally `approved: false` until
the owner or language consultant supplies and approves recordings.  The
runtime refuses unapproved or hash-mismatched files.
