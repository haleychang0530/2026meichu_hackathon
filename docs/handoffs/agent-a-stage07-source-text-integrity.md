# Agent A Stage 07 follow-up handoff — original source text integrity

```text
Stage: Agent A Stage 07 follow-up — complete original source-text preservation
Status: done — committed and pushed; PR open, not merged
Base: origin/main @ e7dcd4c
Branch: codex/agentA-stage07-source-text-integrity
Pull request: #23 — https://github.com/haleychang0530/2026meichu_hackathon/pull/23
Schema/OpenAPI version: public JSON Schema 0.1.0 / OpenAPI 3.1.0 unchanged
Internal prompt schema: stage07-facts.v2
Runtime host: Ryzen AI 9 laptop only
MI300 role: stateless facts/activity inference only
```

## Summary

- Tightened the first Stage 07 facts prompt so `source_text` means the complete
  verbatim lesson text in page reading order, including dialogue turns,
  punctuation, and internal line breaks.
- Added internal `source_text_complete` confirmation to the facts schema. The
  laptop rejects `false` or missing confirmation, performs at most the existing
  one traceable repair, and returns `VLM_INVALID_OUTPUT` with
  `manual_review` if the text is still incomplete.
- Kept the public Lesson contract unchanged. After the gate passes, the laptop
  copies the validated source text into `Lesson.source_text` without rewriting
  internal line breaks or punctuation and persists it through the existing
  SQLite payload.
- Extended the five metadata-only fixture review and database/pipeline tests to
  cover complete-text confirmation, verbatim assembly, SQLite round-trip, and
  the incomplete-text error boundary.

## Changed files

- `apps/core-api/core_api/lesson_pipeline.py`
- `apps/core-api/tests/test_lesson_pipeline.py`
- `apps/core-api/tests/test_config_and_db.py`
- `apps/core-api/README.md`
- `prompts/lesson-analysis/facts.prompt.txt`
- `prompts/lesson-analysis/facts.schema.json`
- `prompts/lesson-analysis/repair.prompt.txt`
- `fixtures/lesson-analysis/stage07/{01-market-picture,02-family-greeting,03-weather-clothing,04-classroom-dialogue,05-food-order}.json`
- `fixtures/lesson-analysis/stage07/error-cases.json`
- `scripts/stage07_fixture_review.py`
- `docs/reports/stage07-fixture-review.md`
- `docs/contracts/v0.1/agent-a-b-integration-format.md`
- `docs/handoffs/agent-a-stage07-source-text-integrity.md`

No Agent B frontend/Speech Gateway/ASR/TTS file, public Lesson schema,
OpenAPI, SQLite migration, model weight, textbook photo, student recording,
cache, runtime index, or database is committed.

## Schema/OpenAPI version

- Public canonical JSON Schema remains Draft 2020-12, `schema_version=0.1.0`.
- Public canonical OpenAPI remains 3.1.0, API version `0.1.0`.
- No public field, response, migration, or generated TypeScript shape changed.
- Internal facts prompt schema changed from `stage07-facts.v1` to
  `stage07-facts.v2` and now requires `source_text_complete: boolean`.

## How to run

From the repository root with the existing Windows Python 3.12 environment:

```powershell
& apps/core-api/.venv/Scripts/python.exe scripts/stage07_fixture_review.py
& apps/core-api/.venv/Scripts/python.exe scripts/test_contracts.py
Set-Location apps/core-api
& .\.venv\Scripts\python.exe -m unittest discover -s tests -p 'test_lesson_pipeline.py' -v
& .\.venv\Scripts\python.exe -m unittest discover -s tests -p 'test_config_and_db.py' -v
```

The live pipeline still uses `CORE_PROVIDER=real` and the trusted
`VLM_BASE_URL`; the browser calls only Core. A pending Lesson must be reviewed
by a teacher/parent before it is used as a teaching lesson.

## Tests and results

Executed on 2026-09-19, Windows, Python 3.12:

```text
Stage 07 fixture review: PASS — 5/5; source_text_complete=true for all five;
  all activities safe; all expected review_status=pending
Stage 07 pipeline tests: PASS — 5 tests
SQLite/config tests: PASS — 7 tests; source_text round-trip asserted
Core unittest discovery: PASS — 50 tests
Contract suite: PASS — 9 schemas; 3 OpenAPI documents/48 responses;
  20 schema fixtures; 10 student-safe fixtures
Language golden: PASS — 38/38
Retrieval/citation smoke: PASS — 20/20 queries; 40 citation replays
Python compileall: PASS
git diff --check: PASS (Windows LF/CRLF conversion warnings only)
```

## Fixtures

- Five Stage 07 metadata-only facts/activity fixtures now use
  `stage07-facts.v2` and explicitly set `source_text_complete=true`.
- `error-cases.json` includes the incomplete-source-text repair/manual-review
  case.
- No original textbook image, student recording, generated media, model
  weight, runtime index, cache, or database is included.

## Resource usage

- All validation, orchestration, RAG, SQLite persistence, and source-text gate
  remain on the Ryzen AI 9 laptop.
- Normal real analysis still sends one facts request and one activity request
  to MI300; an invalid/incomplete facts result adds at most one repair request.
- The gate stores no additional media or model output and adds only an
  in-memory boolean/string validation step.

## Known limits

- `source_text_complete` is a model-reported visual completeness signal plus
  schema/pipeline enforcement; metadata fixtures do not prove live OCR quality
  against real textbook photographs.
- A teacher/parent must still review every generated Lesson while
  `review_status=pending`; this follow-up does not approve lessons
  automatically.
- Existing teacher/parent authentication remains an outer deployment concern.

## Agent B can rely on

- No frontend contract regeneration is required for this follow-up.
- `POST /api/lessons/analyze` still returns the canonical full Lesson with
  `review_status=pending`; successful results contain a complete
  `Lesson.source_text` copied from Stage 07 facts.
- Incomplete facts never become a Lesson and are not sent to Stage 08; Core
  returns the existing non-retryable `VLM_INVALID_OUTPUT`/`manual_review`
  boundary after one repair attempt.
- The internal `source_text_complete` field is not in Lesson/OpenAPI and must
  not be added to student state, caches, DOM, or Speech payloads.
- Stage 08 should read the persisted `Lesson.source_text` on the laptop and
  use it for the teacher-read and student-follow-read prompts; it must not
  reconstruct the lesson from `accessible_activity`, RAG evidence, or a
  second model call.

## Next action

1. Stage 08 updates its Teaching Agent ordering so the backend first exposes a
   full source-text read prompt, then a student follow-read prompt, while
   keeping the source text in backend Lesson/session logic only.
2. Stage 08 should require explicit teacher/parent approval before creating a
   student teaching session; this follow-up leaves the generated Lesson in
   `pending` as required.
3. Agent B handles automatic TTS playback of the backend `current_prompt` or
   phase transition in its Speech/UI-owned files; Agent A does not modify those
   files here.

## Git state

- Local implementation: complete and tested on the feature branch.
- Commits: `40a27f2` implementation/tests, `a0ffe90` docs/handoff, and
  `60464b1` pushed handoff/PR metadata.
- Remote branch: pushed to `origin/codex/agentA-stage07-source-text-integrity`.
- Pull request: #23 is open against `main`; review is pending.
- Merge: not performed; requires explicit user/repository-owner authorization.
