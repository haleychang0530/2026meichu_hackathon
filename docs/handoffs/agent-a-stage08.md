# Agent A Stage 08 handoff

```text
Stage: Agent A Stage 08 — Teaching Agent, SQLite sessions, and SSE
Status: done
Base at branch creation: main @ dd5bc35e3ddefab9da125b668cbd1bd43ecc33b3
Branch: codex/agentA-stage08-session-sse
Pull request: #14 — https://github.com/haleychang0530/2026meichu_hackathon/pull/14 (open, not merged)
Schema/OpenAPI version: JSON Schema Draft 2020-12 / 0.1.0; OpenAPI 3.1.0 / 0.1.0
Runtime host: Ryzen AI 9 laptop only
MI300 role: bounded stateless semantic judgement only for difficult unmatched answers
```

## Summary

- Added ordered SQLite migrations for `lessons`, `sessions`, `turns`,
  `mastery`, durable `events`, and `settings`. Session and event writes use
  one transaction, SQLite WAL, and optimistic revisions.
- Added the laptop-owned Teaching Agent state machine:
  `introduction → demonstration → read_aloud → comprehension → review →
  complete`, with a recoverable `hint` layer and deterministic
  `correct`/`partial`/`retry` outcomes.
- Added local concept matching, hint level progression, language-ratio
  updates, mastery/familiarity updates, and bounded optional semantic
  judgement through the existing MI300 client. A semantic timeout/offline
  result is a safe retry with `mi300_offline` fallback.
- Added student-safe session create/get/action/turn/snapshot APIs and the
  observer-only summary API. Student selectors exclude answers, evidence,
  confidence, lesson source content, review fields, and teacher controls;
  observer summaries include evidence, health, review metadata, hints,
  history, and mastery familiarity.
- Added durable SSE event IDs, `Last-Event-ID`/`after` replay, heartbeat
  recovery, idempotency replay, and `SESSION_REVISION_CONFLICT` recovery.
- Corrected the checked-in demo RAG manifest hash after the Stage 07 lesson
  fixture gained teacher-only fields; the source remains a synthetic,
  repository-owned fixture.

## Changed files

- `apps/core-api/core_api/{app.py,config.py,db.py,models.py,providers.py}`
- `apps/core-api/core_api/{selectors.py,session_service.py,teaching_agent.py}`
- `apps/core-api/migrations/{0003_sessions.sql,0004_turns.sql,0005_mastery.sql,0006_events.sql,0007_settings.sql}`
- `apps/core-api/tests/{test_config_and_db.py,test_stage08_sessions.py}`
- `apps/core-api/README.md`
- `packages/contracts/schemas/v0.1/{error.schema.json,student-action.schema.json,turn-result.schema.json,observer-session-summary.schema.json,session.schema.json,session-event.schema.json}`
- `packages/contracts/openapi/v0.1/core-api.openapi.json`
- `fixtures/contracts/v0.1/{manifest.json,observer/*.json,student/*.json}`
- `fixtures/session/stage08/{all-correct.json,partial-recovery.json,retry-recovery.json}`
- `scripts/test_contracts.py`
- `data/rag/manifest.json`

## Schema/OpenAPI version

- Canonical JSON Schema remains Draft 2020-12 with `schema_version=0.1.0`.
- Canonical OpenAPI remains 3.1.0 with API version `0.1.0`.
- Added canonical student-safe `Session` and replayable `SessionEvent`
  schemas. Added `phase`, `revision`, and `last_event_id` to session/action/
  turn responses; request bodies accept optional `expected_revision`.
- Added additive observer summary evidence, health, review, confidence,
  answer-evidence, model/RAG revision, and session cursor fields. These fields
  are never selected by student routes.
- Added `GET /api/sessions/{session_id}/snapshot` and documented idempotency,
  optimistic revision, and SSE reconnect behavior in the Core OpenAPI.

## How to run

From the repository root:

```powershell
& apps/core-api/.venv/Scripts/python.exe scripts/test_contracts.py
& apps/core-api/.venv/Scripts/python.exe scripts/stage07_fixture_review.py

Set-Location apps/core-api
& .\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

For a fixture demo:

```powershell
$env:CORE_PROFILE = 'demo'
$env:CORE_DATA_DIR = (Resolve-Path 'apps/core-api').Path + '\.runtime\stage08'
& apps/core-api/.venv/Scripts/python.exe -m core_api
```

The browser calls only `http://127.0.0.1:8000`; it never calls the MI300
endpoint. Set `VLM_SEMANTIC_TIMEOUT_SECONDS` to tune the difficult-answer
timeout in a trusted deployment.

## Tests and results

Executed on 2026-09-18, Windows, Python 3.12.9, on the Stage 08 branch:

```text
Core unittest discovery: 45 tests, OK
Stage 08 session suite: 6 tests, OK
Contract suite: PASS — 9 schemas; 3 OpenAPI documents/48 responses;
  20 schema fixtures; 10 student-safe fixtures
Stage 07 fixture review: PASS — 5/5 metadata-only fixtures
Language golden set: PASS — 38/38
Retrieval citation smoke: PASS — 20/20 queries and citation replay
compileall: PASS
git diff --check: PASS
```

The Stage 08 tests cover the three fixed teaching paths, simple local answer
matching, partial/retry recovery, hint/language/mastery persistence, student
versus observer selectors, duplicate action/turn/create requests, stale
revisions and snapshot recovery, SSE backlog/reconnect/heartbeat behavior,
MI300 semantic timeout fallback, and persistence across app restart.

## Fixtures

- `fixtures/session/stage08/all-correct.json`: every activity answer is
  locally correct.
- `fixtures/session/stage08/partial-recovery.json`: partial read-aloud
  answer, hint request, recovery, and completion.
- `fixtures/session/stage08/retry-recovery.json`: unmatched retry fallback,
  recovery, and completion.
- `fixtures/contracts/v0.1/observer/session-created.session-event.json`:
  canonical SSE event envelope.
- Contract observer/student fixtures now carry the Stage 08 cursor and review
  fields while preserving the student forbidden-key checks.

All fixtures are metadata-only. No student audio, textbook photograph, model
weight, cache, database, or runtime RAG index is committed.

## Resource usage

- SQLite, Teaching Agent state, Local RAG, idempotency, and all product
  orchestration remain on the Ryzen AI 9 laptop.
- A normal simple answer uses no MI300 request. Only an unmatched response of
  sufficient length can invoke one bounded stateless semantic request, with a
  configured timeout and no raw upstream error copied to student data.
- Tests use temporary directories and synthetic one-pixel/test JPEG bytes; no
  live MI300 call or external corpus was used.

## Known limits

- Teacher/parent authentication and authorization for the observer summary and
  existing lesson review endpoints remain an outer deployment responsibility.
- The checked-in RAG source is still the small approved demo fixture; an
  official corpus requires license/authorization, manifest hash, and citation
  replay checks.
- Event payloads are student-safe but are retained in SQLite to support
  reconnect/backfill and observer history. Production retention/privacy policy
  is still required.
- Semantic judgement is intentionally conservative. MI300 model quality and
  live latency require a trusted gateway smoke test; timeout/offline behavior
  is covered locally.
- SSE responses are finite backlog/heartbeat responses in the ASGI test
  harness; production deployment still needs an ASGI server/proxy configuration
  that preserves streaming and keep-alive behavior.

## Agent B can rely on

- Use only the laptop Core API. Agent B must regenerate types from
  `packages/contracts/openapi/v0.1/core-api.openapi.json` and must not call or
  expose the MI300 URL.
- Use `POST /api/sessions` with `schema_version`, `lesson_id`, and a stable
  `Idempotency-Key`; use the returned `revision` and `last_event_id` for
  subsequent calls.
- Use `/actions` for controls and `/turns` for transcript-bearing answers.
  Send `X-Session-Revision` (or `If-Match`) for optimistic concurrency and
  refresh from `/snapshot` after `SESSION_REVISION_CONFLICT`.
- Connect to `/events` with `Last-Event-ID`; deduplicate by the durable SSE
  `id`/`event_id` before applying a payload.
- Student selectors may use Session, StudentActionResult, TurnResult, and
  SessionEvent only. Do not place observer `evidence`, `health`, `confidence`,
  `review_status`, `answer_evidence`, or model/RAG revisions in student state,
  caches, prompts, or DOM.
- Observer mode may use `/summary` for evidence, health, history, hints,
  familiarity, and review metadata. The endpoint is not an authorization
  boundary by itself.

## Next action

1. Regenerate Agent B TypeScript types and update its student/observer adapters
   against the additive Stage 08 contract.
2. Repository owner reviews this Stage 08 PR and confirms the auth/retention
   boundary; do not merge without explicit authorization.
3. Run a trusted MI300 semantic-judgement smoke test and measure live
   end-to-end latency/resource usage before deployment.

## Git state

- Local implementation: complete after final regression and diff review.
- Commits: `0431159` core implementation, `01d028f` contracts/fixtures,
  `5423711` tests/docs, followed by the handoff metadata update.
- Remote branch: pushed to `origin/codex/agentA-stage08-session-sse`.
- Pull request: #14 is open against `main`; merge not performed and requires
  explicit repository-owner authorization.
- After branch creation, `main` advanced to `2009d91622c2909abbe870391a06d92445631fd8`
  through Agent B PR #13. The four upstream files are under `apps/web` and
  `services/speech-local`; they do not overlap this Stage 08 diff. A final
  `git fetch --prune` confirmed the branch is four commits ahead of the
  recorded branch base after this metadata update, with no working-tree or
  whitespace conflicts.
