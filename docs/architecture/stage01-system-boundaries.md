# Stage 01 system boundaries and data flow

Status: implementation complete; contract v0.1 remains a draft until Agent B walkthrough and sign-off.

## Decisions

1. The Ryzen AI 9 laptop is the product host and the only owner of product state.
2. The MI300 host is a stateless VLM inference appliance. It has no product API, RAG index, database, session, speech worker, or callback into the laptop.
3. The browser calls only the laptop Core Backend and laptop Speech Gateway. It never calls MI300.
4. Canonical contracts are owned under `packages/contracts` by Agent A. Agent B generates TypeScript types from these files and does not fork field definitions in the frontend.
5. This is the initial contract version, so there is no database migration. Any later breaking change requires a new contract version and a documented migration/compatibility window.

## Runtime and trust boundaries

```text
Camera / Mic / Keyboard / Screen reader
                  |
                  v
+----------------------------------------------------------------+
| Ryzen AI 9 laptop (product host and trusted data boundary)     |
|                                                                |
|  apps/web ---> apps/core-api ---> SQLite                       |
|      |              |   |-----> Local RAG index                |
|      |              |   `-----> Teaching Agent / session / SSE |
|      `--------> services/speech-local (ASR/TTS/cache)           |
+--------------------------|-------------------------------------+
                           | outbound request only
                           | request_id + schema version
                           | finite timeout/retry + circuit breaker
                           v
+----------------------------------------------------------------+
| MI300 trusted-LAN host                                         |
| services/vlm-mi300: stateless structured VLM inference only    |
| request bytes exist only for the lifetime of one request        |
+----------------------------------------------------------------+
```

The MI300 service may receive an image with metadata removed, a prompt, a JSON Schema, and optional compact evidence already selected by laptop RAG. It returns structured output and inference metadata. It does not retrieve evidence and does not retain request content after returning or failing.

## Network boundary

| Caller | Callee | Binding | Allowed API | Rule |
| --- | --- | --- | --- | --- |
| Browser | Core Backend | laptop localhost | `/api/*` | Only product API entry point |
| Browser/Core | Speech Gateway | laptop localhost | `/local/*`, `/v1/audio/*` | Agent B-owned; never exposed publicly |
| Core Backend | MI300 | allowlisted trusted LAN | `/internal/health`, `/internal/vlm/generate` | One-way requests; MI300 cannot call back |
| MI300 | Laptop | none | none | Denied by design |

Demo services must not bind to a public interface. The MI300 ingress must restrict source IP to the laptop. TLS or an isolated network is required outside a physically controlled demo LAN.

## Primary data flows

### Lesson creation

```text
web capture
  -> Core validates quality, strips metadata, bounds image size
  -> Core sends one stateless request to MI300
  -> Core validates structured output against JSON Schema
  -> Core performs at most one traceable repair attempt
  -> laptop RAG retrieves local licensed evidence and citations
  -> laptop normalization and Teaching Agent create a draft Lesson
  -> teacher/parent review
  -> laptop SQLite stores approved structured data
```

### Teaching turn

```text
Core next prompt -> local TTS -> SPEAKING ends -> local ASR
  -> Core semantic match / Teaching Agent
  -> SQLite Turn update
  -> SSE update to student and observer views
```

The half-duplex state machine is `IDLE -> SPEAKING -> LISTENING -> TRANSCRIBING -> EVALUATING -> SPEAKING`. Every failure returns to `IDLE` or `RECOVERABLE_ERROR`.

### Student control and observer projection

- Student control intents use `POST /api/sessions/{session_id}/actions`; its enum never includes answer submission.
- A student answer uses `POST /api/sessions/{session_id}/turns` and always carries a non-empty transcript.
- Both action results and turn results are student-safe and exclude the full Lesson, evidence, confidence, review fields, answer keys, and teacher controls.
- Observer mode uses `GET /api/sessions/{session_id}/summary` for turn history, evaluation, feedback, progress, latency, fallbacks, hints, and familiarity. It resolves lesson title/details separately from the teacher-only Lesson endpoint.
- Student and observer responses require separate selectors/cache keys in the frontend; UI mode switching does not change the underlying laptop-owned session.

## Request identity

- Every response carries `X-Request-ID`; JSON error bodies also carry `request_id`.
- An incoming valid UUID is echoed end-to-end. Otherwise the first receiving laptop service generates a UUID.
- Core forwards the same value to Speech and MI300 and includes it in structured logs.
- Logs contain request ID, status, duration, error code, and model/index revision only. They must not contain full student speech, raw audio, images, or prompt history.
- Reusing a request ID makes a VLM request traceable but does not authorize persistent deduplication on MI300.

## Timeout, retry, and circuit breaker policy

| Call | Connect timeout | Total timeout | Automatic retry | Fallback |
| --- | ---: | ---: | --- | --- |
| Core -> MI300 health | 1 s | 2 s | 1 retry with 100–300 ms jitter | mark VLM offline |
| Core -> MI300 generate | 2 s | 15 s | 1 retry only for connect reset, 429, 502, 503, 504 | cached lesson, fixture, or manual review |
| Core -> Speech health | 250 ms | 1 s | 1 retry | mark component degraded |
| Core/browser -> ASR | 1 s | 4 s | none; user controls replay | keyboard input |
| Core/browser -> TTS | 1 s | 4 s | none; avoid duplicate playback | prerecorded audio or screen reader |

MI300's circuit breaker opens after 3 consecutive qualifying failures inside 60 seconds. It stays open for 30 seconds, rejects calls with `CIRCUIT_OPEN`, then permits one half-open probe. One successful probe closes it; one failure reopens it. Validation failures do not trip the circuit. Retry budgets are included in the total timeout and preserve the same request ID.

## Failure boundary and degradation

| Failure | What remains available | User-visible action |
| --- | --- | --- |
| MI300 offline/timeout | Core, existing lessons, RAG, session, Speech | use cached lesson or demo fixture; do not block an active session |
| RAG no result | VLM draft and teacher review | show that no reliable citation was found; never invent evidence |
| ASR unavailable/fails | lesson, session, TTS, keyboard | offer retry and keyboard input |
| TTS unavailable/fails | lesson, session, ASR, screen reader | use approved recording or text/screen reader |
| SQLite write failure | read-only cached data where safe | stop state-changing actions and surface a recoverable error |
| Invalid VLM output | all laptop services | one recorded repair attempt, then manual review/fixture |

Errors use `packages/contracts/schemas/v0.1/error.schema.json`. Error codes and fallbacks are stable within v0.1; messages may be localized.

## Storage boundary and deletion policy

All persistent product data lives beneath `%LOCALAPPDATA%\HearOurLanguage` on the laptop. See `docs/contracts/v0.1/data-retention.md`. MI300 persists none of it.

## Version and compatibility policy

- `schema_version` is required in every canonical model and fixture.
- `info.version` is required in every OpenAPI document.
- Additive optional fields may be introduced in a patch revision after both agents update tests.
- Removing, renaming, changing type/meaning, or making an optional field required is breaking and requires the next contract directory, migration notes, fixtures, and parallel compatibility support.
- `0.1.0` is a draft baseline, not a formally frozen contract, until Agent B records walkthrough acceptance.
