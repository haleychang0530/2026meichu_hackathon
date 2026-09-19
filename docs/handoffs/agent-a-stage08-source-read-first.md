# Agent A Stage 08 handoff — source read before follow-read

```text
Stage: Agent A Stage 08 — source read first, Teaching Agent and session gate
Status: done — implementation and local regression complete; PR pending
Base: codex/agentA-stage07-source-text-integrity @ 6711ad0 (Stage 07 PR #23 open)
Branch: codex/agentA-stage08-source-read-first
Pull request: pending creation; merge not performed
Schema/OpenAPI version: public JSON Schema 0.1.0 / OpenAPI 3.1.0
Runtime host: Ryzen AI 9 laptop only
MI300 role: bounded stateless semantic judgement only for difficult unmatched answers
```

## Summary

- Kept the public v0.1 teaching phase enum compatible with Agent B and made the
  existing `demonstration` phase the full teacher-read phase.
- The demonstration prompt now reads the persisted `Lesson.source_text`
  verbatim once. The following `read_aloud` prompt uses the same text for
  student follow-read. No RAG evidence, accessible activity, or second model
  call reconstructs the original lesson.
- A student cannot enter `LISTENING` or submit a transcript during the
  introduction or full-source demonstration. The action remains `SPEAKING`
  and asks the client to finish listening first; a direct `/turns` call is
  rejected with the existing `VALIDATION_ERROR` state detail.
- Session creation now requires `review_status=approved`. Pending or rejected
  lessons return `LESSON_NOT_APPROVED` with the current review status and do
  not create a session or event. The approval gate uses the existing laptop
  SQLite lesson record and does not add a student-visible field.
- Added migration `0008_stage08_source_read.sql` to version the Teaching Agent
  behavior as `stage08-v2-source-read` without changing the database schema.

## Changed files

- `apps/core-api/core_api/teaching_agent.py`
- `apps/core-api/core_api/session_service.py`
- `apps/core-api/core_api/models.py`
- `apps/core-api/core_api/app.py`
- `apps/core-api/migrations/0008_stage08_source_read.sql`
- `apps/core-api/tests/test_stage08_sessions.py`
- `apps/core-api/tests/test_config_and_db.py`
- `apps/core-api/README.md`
- `packages/contracts/schemas/v0.1/error.schema.json`
- `packages/contracts/openapi/v0.1/core-api.openapi.json`
- `fixtures/contracts/v0.1/errors/lesson-not-approved.error.json`
- `fixtures/contracts/v0.1/manifest.json`
- `docs/contracts/v0.1/error-codes.md`
- `docs/contracts/v0.1/agent-a-b-integration-format.md`
- `docs/handoffs/agent-a-stage08-source-read-first.md`

No Agent B React, Speech Gateway, ASR, TTS worker, model weight, textbook
photo, student recording, cache, runtime index, or database is committed.

## Schema/OpenAPI version

- Canonical JSON Schema remains Draft 2020-12 with `schema_version=0.1.0`.
- Canonical Core OpenAPI remains 3.1.0 with API version `0.1.0`.
- The existing phase enum is unchanged: `demonstration` is the source-read
  phase and `read_aloud` is the follow-read phase.
- Added the additive `LESSON_NOT_APPROVED` error code to the v0.1 error schema
  and documented the `409` response on `POST /api/sessions`.

## How to run

From the repository root:

```powershell
& apps/core-api/.venv/Scripts/python.exe scripts/test_contracts.py
& apps/core-api/.venv/Scripts/python.exe scripts/stage07_fixture_review.py

Set-Location apps/core-api
& .\.venv\Scripts\python.exe -m unittest discover -s tests -v
& .\.venv\Scripts\python.exe -m unittest discover -s tests -p 'test_stage08_sessions.py' -v
```

The normal product flow is:

1. `POST /api/lessons/analyze` returns a complete but pending Lesson.
2. Teacher/parent review calls `PATCH /api/lessons/{lesson_id}` with
   `{"review_status":"approved"}`.
3. `POST /api/sessions` creates the student-safe session.
4. The client plays the introduction, then the full-source demonstration
   prompt, then the follow-read prompt. TTS playback remains Agent B's
   Speech/UI responsibility.

## Tests and results

Executed on 2026-09-19, Windows, Python 3.12:

```text
Core unittest discovery: PASS — 53 tests, OK
Stage 08 session suite: PASS — 10 tests, OK
Migration/config tests: PASS — 7 tests, OK
Contract suite: PASS — 9 schemas; 3 OpenAPI documents/49 responses;
  21 schema fixtures; 10 student-safe fixtures
Stage 07 fixture review: PASS — 5/5 metadata-only fixtures
Language golden: PASS — 38/38
Retrieval/citation smoke: PASS — 20/20 queries; 40 citation replays
Python compileall: PASS
git diff --check: PASS before commit
```

The Stage 08 tests cover approval gating, exact source-text inclusion in both
read phases, the pre-follow-read answer guard, the three fixed teaching paths,
selectors, idempotency, optimistic revisions, SSE reconnect/heartbeat,
restart recovery, and MI300 semantic timeout fallback.

## Fixtures

- `fixtures/session/stage08/all-correct.json`
- `fixtures/session/stage08/partial-recovery.json`
- `fixtures/session/stage08/retry-recovery.json`
- `fixtures/contracts/v0.1/errors/lesson-not-approved.error.json`

All fixtures are metadata-only. The source text is read from the validated
Lesson fixture and no source-text completeness marker is exposed publicly.

## Resource usage

- SQLite, Lesson approval state, Teaching Agent state, SSE, and all product
  orchestration remain on the Ryzen AI 9 laptop.
- A normal source-read/follow-read path makes no MI300 semantic request.
- Only a difficult unmatched answer may call the bounded stateless MI300
  semantic judge; timeout/offline remains a safe retry fallback.
- Tests use temporary directories and synthetic image bytes. No live MI300 call,
  original media, student audio, model weight, cache, or runtime index was
  added.

## Known limits

- `source_text_complete` is enforced by the Stage 07 laptop pipeline but is an
  internal facts field; live OCR/VLM completeness still needs a trusted MI300
  smoke test and human review on real textbook images.
- Teacher/parent authentication and authorization remain outside this local
  API boundary; `GET/PATCH /api/lessons/{id}` and `/summary` need deployment
  protection.
- Agent B must trigger TTS playback when `current_prompt` or a phase transition
  changes. This branch does not modify Speech Gateway or frontend code.
- The test harness verifies finite SSE backlog/heartbeat responses; production
  ASGI/proxy keep-alive configuration still needs deployment validation.

## Agent B can rely on

- Use only the laptop Core API and regenerate no new TypeScript phase type; the
  phase enum is unchanged.
- Do not call `POST /api/sessions` until the Lesson is explicitly approved.
  Handle `409` with `code=LESSON_NOT_APPROVED` by returning to teacher review;
  `details.review_status` is the current status.
- After session creation, play `current_prompt` in `introduction`. The next
  action exposes `phase=demonstration` and a prompt containing the complete
  persisted original source text for teacher read. The following action
  exposes `phase=read_aloud` and the same text for follow-read.
- Do not add the internal `source_text_complete` field to student state,
  caches, DOM, or Speech payloads. Student selectors still exclude evidence,
  confidence, review fields, answer evidence, and teacher controls.
- Use `X-Session-Revision`, `Idempotency-Key`, and SSE `Last-Event-ID` exactly
  as documented in the existing v0.1 Core OpenAPI.

## Next action

1. Review and merge the Stage 07 source-text PR #23, then retarget or merge
   this stacked Stage 08 PR according to the repository owner's chosen order.
2. Agent B wires automatic TTS playback for the demonstration and follow-read
   prompts and validates the real Speech Gateway path.
3. Run a trusted live MI300 semantic-judgement smoke test and measure
   end-to-end TTS/ASR/Teaching-Agent latency before deployment.

## Git state

- Local implementation: complete and tested.
- Branch: `codex/agentA-stage08-source-read-first` created from the pushed Stage
  07 source-text branch.
- Stage 07 dependency branch and PR #23 remain unmerged; this Stage 08 branch
  does not modify them.
- Commit, push, and PR URL will be recorded here after the final diff audit.
- Merge: not performed; explicit repository-owner authorization is required.
