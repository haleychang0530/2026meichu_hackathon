# Agent A Stage 07 handoff

```text
Stage: Agent A Stage 07 — textbook analysis and accessible activity generation
Status: done
Base: main @ a9904c4 (Agent A Stage 06 PR #11 merged)
Branch: codex/agentA-stage07-lesson-analysis
Pull request: #12 — https://github.com/haleychang0530/2026meichu_hackathon/pull/12 (open)
Schema/OpenAPI version: 0.1.0 / OpenAPI 3.1.0 (additive answer_evidence)
Runtime host: Ryzen AI 9 laptop only
MI300 role: stateless page-facts/activity inference only
```

## Summary

- Connected the Stage 07 laptop pipeline: validated upload and short-lived
  normalized image, MI300 page-facts extraction, local schema validation,
  laptop Local RAG retrieval, accessible-activity generation, citation binding,
  SQLite persistence, and `pending` Lesson output.
- Split generation into two prompts and two schemas: facts first, then
  `learning_objective`/`accessible_activity`. The facts output carries
  teacher/parent-only `answer_evidence`; the activity output carries the three
  safety booleans.
- Added one bounded, traceable repair attempt. A second invalid or unsafe
  output returns `VLM_INVALID_OUTPUT`, `manual_review`, stage/reason metadata,
  and no raw model output; it is not retried again as an automatic repair.
- Added deterministic checks for answer leakage, copied answer evidence,
  position hints, and sighted-only instructions. Lesson review stays pending
  until the teacher/parent PATCH route approves it.
- Added the SQLite `lessons` migration and teacher/parent GET/PATCH handlers.
  Source images, raw VLM output, and student recordings are not persisted.

## Changed files

- `apps/core-api/core_api/{analyzer.py,app.py,db.py,lesson_pipeline.py,models.py,providers.py}`
- `apps/core-api/migrations/0002_lessons.sql`
- `apps/core-api/tests/{test_app.py,test_config_and_db.py,test_lesson_pipeline.py}`
- `apps/core-api/README.md`
- `prompts/lesson-analysis/{facts.prompt.txt,activity.prompt.txt,repair.prompt.txt,facts.schema.json,activity.schema.json}`
- `fixtures/lesson-analysis/stage07/{01-market-picture.json,02-family-greeting.json,03-weather-clothing.json,04-classroom-dialogue.json,05-food-order.json,error-cases.json}`
- `fixtures/contracts/v0.1/observer/{success.lesson.json,rag-no-result.lesson.json}`
- `packages/contracts/schemas/v0.1/lesson.schema.json`
- `packages/contracts/openapi/v0.1/core-api.openapi.json`
- `docs/contracts/v0.1/agent-a-b-integration-format.md`
- `docs/reports/stage07-fixture-review.md`
- `scripts/{stage07_fixture_review.py,test_contracts.py}`
- `data/rag/manifest.json` (hash updated after the teacher-only fixture field)

No Agent B React/Speech Gateway/ASR/TTS file, model weight, textbook photo,
student recording, cache, runtime index, or database is committed.

## Schema/OpenAPI version

- Canonical JSON Schema remains Draft 2020-12 with `schema_version=0.1.0`.
- Canonical OpenAPI remains 3.1.0 with API version `0.1.0`.
- `Lesson.answer_evidence` is an additive optional v0.1 field for backward
  readability of older lessons. Every Stage 07 generated/fallback Lesson
  populates it when facts contain visual-answer evidence. Student-safe fixtures
  forbid the field and the integration contract marks it teacher/parent-only.
- Existing reserved `GET /api/lessons/{lesson_id}` and
  `PATCH /api/lessons/{lesson_id}` paths are now implemented at runtime.
- SQLite migration `0002_lessons.sql` stores validated structured payloads and
  review status; it does not store media.
- Agent B should regenerate types from the canonical schema/OpenAPI and must
  keep `answer_evidence` out of student selectors, caches, DOM, and prompts.

## How to run

From the repository root with the existing Windows Python 3.12 environment:

```powershell
& apps/core-api/.venv/Scripts/python.exe scripts/test_contracts.py
& apps/core-api/.venv/Scripts/python.exe scripts/stage07_fixture_review.py

Set-Location apps/core-api
& .\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

For a real two-step run, use `CORE_PROFILE=development`,
`CORE_PROVIDER=real`, a trusted `VLM_BASE_URL`, and the configured
`VLM_MODEL_REVISION`. The browser still calls only Core at
`http://127.0.0.1:8000`; it never calls MI300 directly.

## Tests and results

Executed on 2026-09-18, Windows, Python 3.12.9, after the Stage 07 changes:

```text
Core unittest discovery: 39 tests, OK
Contract suite: PASS — 7 schemas; 3 OpenAPI documents/45 responses;
  19 schema fixtures; 10 student-safe fixtures
Stage 07 fixture review: PASS — 5/5 metadata-only fixtures; all safety checks
  passed; all expected review statuses pending
Stage 07 pipeline tests: two-step citation binding, one repair boundary,
  unresolved safety failure, pending persistence/review: PASS
```

The full Stage 06 regression commands remain required before PR update:
`scripts/language_golden.py` (38/38), `scripts/retrieval_citation_smoke.py`
(20/20 queries and citation replay), and `git diff --check`.

## Fixtures and error cases

- `01-market-picture.json`: visual question reconstructed as role/action
  auditory reasoning without answer leakage.
- `02-family-greeting.json`: dialogue turn-taking and oral response.
- `03-weather-clothing.json`: weather-to-clothing choice with an explicit
  quality warning.
- `04-classroom-dialogue.json`: object naming through heard descriptions.
- `05-food-order.json`: ordered restaurant dialogue and role play with an
  occlusion warning.
- `error-cases.json`: invalid facts JSON, direct answer leakage, position hint,
  and empty-RAG citation policy.
- `docs/reports/stage07-fixture-review.md`: reproducible review result.

Fixtures are synthetic metadata only; no original page image is required.

## Resource usage

- All orchestration, Local RAG, SQLite, validation, safety checks, and review
  state remain on the Ryzen AI 9 laptop.
- MI300 receives one bounded request for facts and one for activity in the
  normal path; the repair path adds at most one extra request for the failing
  stage. The client retains raw output only in memory and never logs it.
- The checked-in Local RAG corpus remains the small repository-owned demo
  fixture. No external textbook/dictionary corpus is added.
- This run used synthetic in-memory/test image bytes and no live MI300 call;
  live latency/resource numbers must be measured against the trusted gateway.

## Known limits

- Semantic safety checks are conservative deterministic heuristics plus the
  model-reported booleans; every generated Lesson remains pending for human
  review. The code does not claim to replace an accessibility specialist.
- Teacher/parent route authentication/authorization is outside this Stage's
  existing local API boundary; deployment must protect GET/PATCH review routes.
- Local RAG evidence is empty when no active reliable index exists. The
  pipeline never fabricates citations and still returns a pending lesson when
  the activity is otherwise valid.
- The formal corpus is demo-only until a licensed/authorized source is added
  with manifest hash and citation replay coverage.
- The five representative fixtures are metadata-only and do not evaluate live
  OCR/VLM visual quality. A trusted MI300 smoke and human review remain needed.

## Agent B can rely on

- Analyze through `POST /api/lessons/analyze` with `language=nan-TW`; the
  response is a full teacher-reviewable Lesson and always starts `pending`.
- Use `GET /api/lessons/{lesson_id}` and bounded `PATCH` only in observer/
  teacher flows. Approval is explicit through `review_status=approved`.
- Treat `answer_evidence`, `original_activity`, `learning_objective`,
  `accessible_activity`, `evidence`, confidence, and revisions as teacher-side
  fields. Never put them in student state or prompt selectors.
- Citation fields are `source_id`, `title`, `excerpt`, and `locator`; the
  active Local RAG revision is carried by `rag_index_revision`.
- MI300 remains stateless and private behind Core. Agent B does not need its
  URL, prompt files, or response repair logic.
- `VLM_INVALID_OUTPUT` after the single repair boundary means manual review or
  the explicitly requested fixture fallback; it is not a student retry signal.

## Next action

1. Regenerate Agent B types from the updated canonical schema/OpenAPI and keep
   `answer_evidence` outside student routes.
2. Repository owner reviews this Stage 07 PR and confirms the teacher/parent
   review boundary; do not merge without explicit authorization.
3. Before adding official textbook sources, record license/authorization/hash,
   rebuild Local RAG, and rerun citation and resource checks.

## Git state

- Local implementation: complete after final tests and diff review.
- Commits: `0ac6ff0`, `ef7cfa5`, `b7c2c2a`, `baf77ca`.
- Remote branch: pushed to `origin/codex/agentA-stage07-lesson-analysis`.
- Pull request: #12 is open against `main`; merge not performed and still
  requires explicit repository-owner authorization.
