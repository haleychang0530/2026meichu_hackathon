# Error codes and fallback behavior v0.1

| Code | Retryable default | Fallback |
| --- | --- | --- |
| `VALIDATION_ERROR` | no | correct input |
| `IMAGE_QUALITY_LOW` | yes, user action | retake/upload |
| `LESSON_NOT_FOUND` | no | choose a lesson |
| `SESSION_NOT_FOUND` | no | start a session |
| `VLM_TIMEOUT` | yes, bounded by policy | cached lesson/fixture/manual review |
| `VLM_OFFLINE` | yes, bounded by policy | cached lesson or fixture |
| `VLM_INVALID_OUTPUT` | no after one repair | manual review or fixture |
| `RAG_NO_RESULT` | no | manual review; no fabricated citation |
| `ASR_UNAVAILABLE` | yes | keyboard input |
| `ASR_FAILED` | yes, user-controlled | retry or keyboard input |
| `TTS_UNAVAILABLE` | yes | screen reader or prerecorded audio |
| `TTS_FAILED` | yes, user-controlled | screen reader or prerecorded audio |
| `CIRCUIT_OPEN` | yes after cool-down | cached/fixture path |
| `INTERNAL_ERROR` | no automatic retry | safe recoverable state |

The machine-readable list is authoritative in `error.schema.json`. `retryable` describes whether a later attempt can succeed; it does not itself authorize an automatic retry. The service policy in the architecture decision controls automatic retries.
