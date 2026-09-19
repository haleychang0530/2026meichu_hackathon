# Core Backend (Agent A Stage 08)

The FastAPI Core Backend is the browser's only product API and runs on the
Ryzen AI 9 laptop. It owns image validation, orchestration, product fallback,
SQLite readiness, and dependency health. The browser never receives or calls
the MI300 URL.

The Stage 04/05/06/07 baseline plus Stage 08 implements:

- `GET /api/health`
- `POST /api/lessons/analyze`
- `GET /api/lessons/{lesson_id}` for teacher/parent review
- `PATCH /api/lessons/{lesson_id}` for teacher/parent approval or bounded edits
- FastAPI `/openapi.json` and `/docs`
- development, demo, and test configuration profiles
- request IDs, canonical error envelopes, CORS, metadata-only request logs
- a bounded MI300 client with timeout, two-attempt default retry, exponential
  backoff, and circuit breaker
- JPEG/PNG/WebP validation, metadata-stripping JPEG normalization, and upload
  cleanup on success, error, cancellation, plus startup cleanup after 15 minutes
- canonical `Lesson` validation for both real and fixture providers
- SQLite migration tracking plus laptop-owned lessons, sessions, turns,
  mastery, durable events, and settings
- laptop-only Local RAG manifest validation, UTF-8 cleaning, chunking, and
  persistent vector/keyword index support
- bounded hybrid retrieval, reproducible evidence citations, and honest empty
  evidence below the reliability threshold
- `POST /api/utterances/normalize` with textbook-臺羅 precedence, reviewed
  Hanji candidates, deterministic MMS-compatible POJ, and `needs_review` gates
- two-step lesson analysis: page facts first, then teaching objective and
  accessible activity, with laptop-only Local RAG citation binding
- facts extraction requires an explicit complete-source-text confirmation;
  validated `source_text` is copied verbatim into the pending Lesson and
  persisted in laptop SQLite for the Teaching Agent
- one traceable JSON repair attempt per invalid facts/activity output; a second
  failure returns `VLM_INVALID_OUTPUT` with `manual_review` and no raw model
  output
- teacher/parent-only `answer_evidence`, deterministic checks for answer leaks,
  position hints, and sighted-only clues, and SQLite-backed `pending` lessons
- a laptop-owned Teaching Agent state machine for introduction, demonstration,
  read-aloud, comprehension, hint, review, and complete phases
- student-safe session create/get/action/turn/snapshot routes and an
  observer-only session summary route
- optimistic session revisions, request IDs, idempotency replay, and durable
  SSE event IDs with `Last-Event-ID` backfill and heartbeat recovery
- deterministic local concept matching for simple answers, with bounded MI300
  semantic judgement only for unmatched difficult responses

The full cross-agent contract remains
`packages/contracts/openapi/v0.1/core-api.openapi.json`. Student-mode adapters
must use safe projections rather than the full teacher/parent Lesson object.

## Install

Use a native Windows Python 3.12 interpreter, not an MSYS Python interpreter:

```powershell
python -m venv apps/core-api/.venv
apps/core-api/.venv/Scripts/python.exe -m pip install -r apps/core-api/requirements.txt
```

The repository ignores `.venv`, `.runtime`, `.env`, Python caches, and SQLite
runtime files.

## Profiles

`CORE_PROFILE` selects one settings layer. Environment variables override that
layer; no secret or MI300 address is hard-coded in frontend code.

| Profile | Default provider | Purpose |
| --- | --- | --- |
| `development` | `real` | Calls the configured MI300 gateway; health stays available when it is offline. |
| `demo` | `fixture` | Deterministic offline demo. Analyze responses set `X-Provider-Mode: fixture`. |
| `test` | `fixture` | Isolated tests with explicit temporary data paths. |

Safe examples are under `config/*.env.example`. PowerShell does not
automatically load them; set the required variables in the process or use the
equivalent values in the launcher.

Important variables:

- `CORE_HOST` / `CORE_PORT` (defaults `127.0.0.1:8000`)
- `CORE_DATA_DIR` (defaults `%LOCALAPPDATA%\HearOurLanguage`)
- `CORE_PROVIDER=real|fixture`
- `CORE_ALLOWED_ORIGINS` (defaults to the Agent B Vite origins on port 5173)
- `VLM_BASE_URL` and `VLM_MODEL_REVISION`
- `SPEECH_BASE_URL` (Agent B contract default `http://127.0.0.1:8200`)
- `RAG_MANIFEST_PATH`, `RAG_INDEX_ROOT`, `RAG_EMBEDDING_BACKEND`, and
  `RAG_EMBEDDING_DIMENSION`
- `RAG_ONNX_MODEL_PATH` and `RAG_ONNX_TOKENIZER_PATH` when using `onnx-local`
- `LANGUAGE_GOLDEN_PATH` for the reviewed Hanji/臺羅/POJ set
- `VLM_CONNECT_TIMEOUT_SECONDS`, `VLM_READ_TIMEOUT_SECONDS`,
  `VLM_SEMANTIC_TIMEOUT_SECONDS`,
  `VLM_MAX_ATTEMPTS`, `VLM_RETRY_BACKOFF_SECONDS`,
  `VLM_CIRCUIT_FAILURE_THRESHOLD`, and `VLM_CIRCUIT_RECOVERY_SECONDS`

## Start

Offline/fixture demo from the repository root:

```powershell
$env:CORE_PROFILE = 'demo'
$env:CORE_DATA_DIR = (Resolve-Path 'apps/core-api').Path + '\.runtime\demo'
Set-Location apps/core-api
& .\.venv\Scripts\python.exe -m core_api
```

Real MI300 provider through the current Manta gateway forwarding. On
2026-09-19, project `qwen3-coder-fp8-bench` maps gateway `8100/tcp` to
`http://210.61.209.139:46944`; this external port is dynamic, so re-check
Manta **Settings → Port Forwarding** whenever the rule is rebuilt:

```powershell
$env:CORE_PROFILE = 'development'
$env:CORE_PROVIDER = 'real'
$env:VLM_BASE_URL = 'http://210.61.209.139:46944'
$env:VLM_MODEL_REVISION = 'd9748a51ae66354c4dad665aab2c71f26cf2c8cd'
Set-Location apps/core-api
& .\.venv\Scripts\python.exe -m core_api
```

Before starting Core, an operator can verify the forwarding without exposing
the URL to the browser. The health-only probe persists no payload:

```powershell
pwsh -File .\scripts\release\Test-Mi300Forwarding.ps1 `
  -BaseUrl 'http://210.61.209.139:46944'
```

Add `-ImagePath .\path\to\synthetic-test.png` to exercise
`POST /internal/vlm/generate`. The probe prints only bounded metadata and the
schema-validated candidate; it does not print image bytes, prompt text, or raw
model output. Direct gateway calls are for operator diagnostics only—product
traffic still goes through Core.

The Core API remains on `http://127.0.0.1:8000`. Agent B can set
`VITE_CORE_API_BASE_URL=http://127.0.0.1:8000`; it must not set a MI300 URL.

## Requests and fallback

```powershell
Invoke-RestMethod http://127.0.0.1:8000/api/health

curl.exe -X POST http://127.0.0.1:8000/api/lessons/analyze `
  -H "X-Request-ID: 00000000-0000-4000-8000-000000000001" `
  -F "language=nan-TW" `
  -F "use_fixture_on_failure=true" `
  -F "image=@page.jpg;type=image/jpeg"

curl.exe -X POST http://127.0.0.1:8000/api/utterances/normalize `
  -H "Content-Type: application/json" `
  -d '{"schema_version":"0.1.0","text":"市場","lang":"nan-TW","tailo_citation":"tshī-tiûnn"}'
```

When the real provider is unavailable and `use_fixture_on_failure=true`, the
same canonical Lesson schema is returned with
`X-Provider-Mode: fixture-fallback` and
`vlm_model_revision=fixture:v0.1`. Set the flag to `false` to receive the
canonical `VLM_OFFLINE`, `VLM_TIMEOUT`, or `CIRCUIT_OPEN` error instead.

Health is deliberately `degraded` while no Local RAG index or Agent B Speech
service is ready. After a successful local reindex, the RAG health service
becomes `ready` and reports the active index revision. SQLite readiness is
represented by the `core-api` service because
the frozen v0.1 `ServiceHealth.service` enum does not include a separate
`sqlite` value.

## Stage 07 lesson analysis

With `CORE_PROVIDER=real`, the laptop owns the complete orchestration:

1. `ImagePreparer` validates and normalizes the uploaded page into a short-lived
   JPEG; the temporary file is deleted in `finally`.
2. `Mi300Client.generate` sends only the image, prompt, requested JSON Schema,
   and bounded Local RAG evidence to the stateless MI300 gateway.
3. `LessonAnalysisPipeline` validates the facts response, queries the laptop
   Local RAG index, and requests the accessible activity in a second call.
4. The laptop rejects facts that do not confirm a complete original
   `source_text`; after one repair attempt the unresolved case is returned as
   `VLM_INVALID_OUTPUT`/`manual_review`.
5. The laptop validates activity safety, binds citations from the active RAG
   revision, persists the structured Lesson, and always returns
   `review_status=pending`.

Prompts and stage schemas are versioned under
`prompts/lesson-analysis/`. The facts prompt keeps `answer_evidence` separate
from the student activity. The activity prompt forbids answer leakage, location
clues, and sighted-only instructions. The review endpoint may approve a lesson
or edit only bounded teacher-facing fields; it cannot edit `answer_evidence`.

Teacher/parent review example:

```powershell
curl.exe http://127.0.0.1:8000/api/lessons/lesson_<id>
curl.exe -X PATCH http://127.0.0.1:8000/api/lessons/lesson_<id> `
  -H "Content-Type: application/merge-patch+json" `
  -d '{"review_status":"approved"}'
```

## Stage 08 Teaching Agent and sessions

All session state remains on the Ryzen AI 9 laptop. The MI300 gateway is never
called by the browser and never owns SQLite, RAG, sessions, turns, mastery, or
business state. The migrations are applied in order:

```text
0001_runtime_metadata.sql
0002_lessons.sql
0003_sessions.sql
0004_turns.sql
0005_mastery.sql
0006_events.sql
0007_settings.sql
0008_stage08_source_read.sql
```

Only a teacher/parent-approved Lesson may create a student session. The
student flow is:

```text
introduction → demonstration (full source read) → read_aloud (follow-read)
             → comprehension → review → complete
                         ↘ hint ↗
```

The demonstration prompt reads the complete persisted `Lesson.source_text`
verbatim once before the student can enter follow-read. The follow-read prompt
uses the same persisted text; it is never reconstructed from RAG evidence or
`accessible_activity`. A `start_answer` action during introduction or the
source-read demonstration remains in `SPEAKING` until the full source read is
finished.

`POST /api/sessions/{session_id}/turns` accepts a transcript and returns only
the student-safe `TurnResult`. Local concept matching handles straightforward
answers. A difficult unmatched answer may use the laptop `Mi300Client` with
`VLM_SEMANTIC_TIMEOUT_SECONDS`; timeout, offline, or invalid upstream output
becomes a retry with `mi300_offline` fallback. `POST
/api/sessions/{session_id}/actions` is reserved for controls such as
`start_answer`, `request_hint`, `pause`, `resume`, and `next`.

Every mutating request can carry `Idempotency-Key` and
`X-Session-Revision`. Reusing a key replays the committed result without a
second turn/event; a stale revision returns `SESSION_REVISION_CONFLICT` and
the current state is recoverable from `GET /api/sessions/{session_id}/snapshot`.

`GET /api/sessions/{session_id}/events` is a replayable SSE stream. Each
durable event has a monotonic `id:` line and a JSON `SessionEvent` data
envelope. Send `Last-Event-ID` or `?after=` after reconnecting; an empty
backlog returns a heartbeat comment. Student selectors never include lesson
evidence, confidence, answer evidence, review status, or teacher controls.
`GET /api/sessions/{session_id}/summary` is the observer/teacher projection
and includes evidence, health, review metadata, turn history, hints, and
mastery familiarity.

The metadata-only end-to-end paths are in
`fixtures/session/stage08/{all-correct,partial-recovery,retry-recovery}.json`.

## Local RAG

The manifest at `data/rag/manifest.json` is the only checked-in source list.
An approved source must have `license_status=approved`,
`approved_for_index=true`, and a matching SHA-256 before it can enter an
index. Sources with unknown or pending authorization are reported as excluded;
the Stage 05 manifest intentionally contains only the repository-owned demo
fixture, not an external textbook or dictionary dump.

Build or rebuild the runtime index under the laptop data directory:

```powershell
Set-Location apps/core-api
python ..\..\scripts\rag_reindex.py --mode full
python ..\..\scripts\rag_reindex.py --mode incremental
python ..\..\scripts\rag_smoke.py
```

The builder writes a complete revision to a staging directory, verifies the
SQLite metadata/vector store, then atomically replaces `active.json`. A failed
build leaves the previous active revision untouched. Incremental builds reuse
vectors for unchanged chunk IDs; full builds recompute every vector. Runtime
files are below `%LOCALAPPDATA%\HearOurLanguage\rag\indexes` and are ignored
by Git.

The default `hashing-char-ngram-v1` backend is deterministic, dependency-free,
CPU-only, and preserves Hanji plus 臺羅 code points. An approved local
tokenizer/model may opt into the optional `onnx-local` CPU adapter; this
repository does not download or commit model weights.

Stage 06 adds a policy layer over the index: normalized exact match, keyword,
and vector scores are combined; optional metadata filters are applied before
ranking; results below the configured threshold are discarded; duplicate text
is removed; and excerpts are clipped to a total context character budget. Each
internal evidence item contains `source_id`, `title`, `excerpt`, `locator`,
`score`, and `index_revision`. The frozen Lesson response keeps score internal,
places provenance in `evidence[]`, and carries the revision once in
`rag_index_revision`.

## Language normalization

The laptop environment does not require a network Taibun/THOKIT service. The
fallback mandated by Stage 06 is implemented as a versioned, reviewed offline
lexicon plus deterministic rules. `data/language/normalization-golden.json`
contains 38 Hanji/臺羅/POJ/Chinese-gloss/example rows. The conversion target is
the official `facebook/mms-tts-nan` vocabulary profile, so `poj_citation` is
lower-case, punctuation-free, and uses `nn` instead of the unsupported `ⁿ`.

Run the traceable golden report from the repository root:

```powershell
& apps/core-api/.venv/Scripts/python.exe scripts/language_golden.py
```

The report records every row's input/output plus the lexicon, converter,
pipeline, and MMS vocabulary versions. OOV, multiple readings,
literary/colloquial readings, and textbook/dictionary conflicts return
`needs_review` with no POJ or TTS provider. See
`data/language/manual-review.json` for the human confirmation queue.

Stage 08 adds `LanguageNormalizer.normalize_labeled_segments(...)` for the
two-step lesson pipeline. MI300 returns only ordered `language_segments`
(`lang`=`zh-TW`/`nan-TW`, `content`=Hanji); the laptop verifies that the
segments cover the original text exactly, tokenizes Taiwanese spans with the
golden lexicon, and emits canonical `Utterance.segments[]`. MI300 never
returns the final Tailo/POJ used by MMS. Session responses retain their
natural `current_prompt`/`next_prompt` strings and additionally return
`current_utterance`, `next_utterance`, and `feedback_utterance` where
available. The student UI should use the utterance only for speech routing;
`needs_review` spans have no POJ and are spoken with the Chinese browser or
Windows fallback.

## Test

```powershell
Set-Location apps/core-api
& .\.venv\Scripts\python.exe -m unittest discover -s tests -v

Set-Location ../..
& apps/core-api/.venv/Scripts/python.exe scripts/test_contracts.py
& apps/core-api/.venv/Scripts/python.exe scripts/language_golden.py
& apps/core-api/.venv/Scripts/python.exe scripts/retrieval_citation_smoke.py
& apps/core-api/.venv/Scripts/python.exe scripts/stage07_fixture_review.py
& apps/core-api/.venv/Scripts/python.exe -m unittest tests.test_stage08_sessions -v
```

Tests cover profiles, idempotent migrations, structured lesson persistence,
request IDs, canonical errors, image validation, success/error/cancellation
cleanup, real/fixture schema parity, retry, circuit breaker, runtime OpenAPI,
MI300-offline startup, fixture fallback, teacher review/pending status,
manifest/license gates, chunk cleaning, incremental reuse, atomic switching,
persistent vector retrieval, keyword fallback, and the 20-query RAG smoke set.
Stage 06 adds golden normalization, textbook-priority, OOV/conflict review
gates, MMS vocabulary validation, hybrid ranking, metadata filtering, context
budgets, empty-evidence behavior, and citation replay. Stage 07 adds the
facts/activity two-step pipeline, complete-source-text gating, one-repair
boundary, safety checks, citation binding, and five metadata-only representative
fixture reviews. Stage 08 adds
SQLite session migrations, the complete teaching state machine, correct/
partial/retry fixtures, selector privacy checks, optimistic revision and
idempotency tests, SSE reconnect/backfill tests, restart persistence, and a
bounded MI300 semantic-timeout fallback test.

## Data and privacy

- SQLite and temporary uploads stay below `CORE_DATA_DIR` on the laptop.
- Normal operation never commits databases, model weights, recordings, or
  textbook images.
- Uploaded image bytes are normalized into a metadata-free bounded JPEG, sent
  only for the active request, and deleted in `finally`.
- Startup removes abandoned `lesson-*` temporary files older than 15 minutes.
- Logs contain request ID, route, status, and latency only; they do not contain
  image bytes, prompt text, raw VLM output, or student transcripts. Repair
  traces contain only stage, attempt count, model revision, and safe reason
  codes.
- `answer_evidence` is teacher/parent-only structured review data; it is not
  indexed into Local RAG and must not be exposed by student routes.
- RAG logs and reports contain revision, source IDs, locators, counts, and
  latency/RAM measurements only; they do not contain student data or raw
  textbook media.
