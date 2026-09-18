# Agent B Stage 08 handoff

```text
Stage: Agent B Stage 08 — student mode and complete teaching round
Status: partial
Branch: codex/agentB_stage08
Base: origin/main @ 2c43726
Contract: v0.1.0 JSON Schema / OpenAPI 3.1.0 unchanged
Runtime profile: Ryzen AI 9 laptop; Core Backend is the session source of truth
```

## Changed files

- `apps/web/src/pages/StudentPage.tsx`: full student-safe round UI with large
  playback, voice/keyboard answer, editable student transcript, hint,
  pause/resume, next, recovery messaging, and mode switching that cancels
  active audio first.
- `apps/web/src/adapters/adapter.ts`: revision/idempotency request options and
  student-safe SSE subscription contract.
- `apps/web/src/adapters/realAdapter.ts`: session snapshot reads, stable
  mutation headers, student projection mapping, health degradation handling,
  durable SSE cursor parsing/reconnect with exponential backoff, and real
  lesson confirmation.
- `apps/web/src/adapters/sessionEvents.ts`: strict student-safe SSE frame
  parser with durable event-id validation.
- `apps/web/src/adapters/mockAdapter.ts`: revisioned Mock session and event
  stream for keyboard/recovery regression without a running backend.
- `apps/web/src/types/viewModels.ts`: session state/phase/revision/event
  cursor and student-only transcript/fallback fields.
- `apps/web/src/adapters/{realAdapter.test.ts,mockAdapter.test.ts,sessionEvents.test.ts}`:
  request-header, SSE replay, parser, and student projection coverage.
- `apps/web/src/{styles.css,components/AppShell.tsx,pages/CapturePage.tsx}`:
  student status/transcript styling and Stage 08 copy updates.

## Student safety and runtime behavior

- Student routes use only Session, StudentAction, TurnResult, and SessionEvent
  projections; no observer evidence, confidence, answer key, or teacher fields
  are copied into the student view.
- Every action/turn sends `X-Session-Revision` and a stable `Idempotency-Key`.
  A revision conflict refreshes `/snapshot`; a retry keeps the same turn key
  until the request succeeds or the draft changes.
- Each SSE event advances `Last-Event-ID`. Finite backend batches and network
  errors reconnect with bounded exponential backoff; the page refreshes the
  student snapshot after an event or stream error.
- TTS, browser speech, and recording are cancelled before every control or
  mode switch. Mic failure/ASR failure leaves the editable keyboard path.
- MI300, ASR CPU, and prerecorded fallback messages are surfaced as actionable
  student-safe notices.

## How to run

Mock student route:

```powershell
npm --prefix apps/web run dev -- --host 127.0.0.1
# open /session/demo-session/student
```

Real Core route:

```powershell
$env:CORE_PROFILE = 'demo'
$env:CORE_DATA_DIR = (Resolve-Path 'apps/core-api').Path + '\\.runtime\\stage08-manual'
Set-Location apps/core-api
& .\\.venv\\Scripts\\python.exe -m core_api

$env:VITE_DATA_MODE = 'real'
$env:VITE_CORE_API_BASE_URL = 'http://127.0.0.1:8000'
npm --prefix apps/web run dev -- --host 127.0.0.1
```

## Tests and results

- Frontend Vitest: 8 files / 22 tests passed.
- Frontend TypeScript strict check: passed.
- Frontend Vite production build: passed.
- Core API unittest discovery from `apps/core-api`: 45 tests passed.
- Contract suite: 9 schemas; 48 responses; 20 schema fixtures; 10
  student-safe fixtures passed.
- Speech-local regression: 22 tests passed.
- Core Python compileall: passed.
- Manual real Core + SQLite fixture session: keyboard fallback completed four
  consecutive UI turns (one retry plus three successful phase advances), and a
  full page reload restored the server-side prompt/phase/progress. Speech
  Gateway was intentionally offline, so the actionable keyboard fallback and
  degraded health state were exercised.

## Known limits

- The checked-in demo teaching graph reaches `complete` after three successful
  phase advances, so the requested ten-round manual run cannot be represented
  without an Agent A-owned longer lesson fixture or contract extension. This
  implementation does not weaken the student completion lock to fake ten
  rounds.
- Live microphone/TTS naturalness testing remains pending a running Speech
  Gateway and authorized audio review. The browser keyboard fallback and
  Mock speech flow are covered.
- App narration selection and full Narrator/NVDA audit remain Stage 09 scope;
  this Stage preserves semantic HTML, focus targets, live status regions, and
  the half-duplex cancellation boundary needed by that work.

## Agent A can rely on

- No canonical schema, OpenAPI, Core session state machine, RAG, or MI300
  implementation was modified.
- The student adapter never calls the MI300 URL; all session and snapshot
  reads go through the laptop Core Backend.
- The frontend exposes only the student's own transcript and fallback/status
  messages. Observer mode continues to use `/summary` separately.

## Next action

1. Agent A/repository owner supplies an authorized longer lesson fixture if a
   ten-round acceptance run is required before Stage 09.
2. Provision Speech Gateway and perform microphone/TTS half-duplex and audio
   review before demonstration freeze.
3. Review this branch and open the PR only after repository-owner confirmation.
   Do not merge without explicit authorization.
