# AGENT_A Stage 08 handoff — language-aware prompt playback

Stage: 08 — 教學 session、語音與語言分段整合
Status: partial

## Summary

Implemented the additive language-segment pipeline for student prompts:

`MI300 facts/activity labels → exact coverage validation → laptop golden-dictionary longest-match normalization → canonical Utterance → pending Lesson/session response`.

The existing text fields remain in every public response. New clients can use the corresponding `Utterance` fields to control pronunciation without exposing JSON, Tailo, POJ, or language labels in the student UI.

## Changed files

- `prompts/lesson-analysis/{facts.prompt.txt,facts.schema.json,activity.prompt.txt,activity.schema.json,repair.prompt.txt}` — two-step MI300 output now requires ordered `language_segments` with `lang` and `content`; MI300 does not generate Tailo/POJ. Internal schemas are `stage07-facts.v3` and `stage07-activity.v2`.
- `apps/core-api/core_api/language/normalization.py` — exact concatenation check, longest-match golden dictionary tokenization, local Tailo→POJ conversion, audit trail, and needs-review routing metadata.
- `apps/core-api/core_api/{models.py,lesson_pipeline.py,teaching_agent.py,selectors.py,session_service.py,app.py}` — additive Lesson/session/turn utterances, source/activity binding, all prompt phases, teacher-edit regeneration, and durable event payloads.
- `packages/contracts/schemas/v0.1/{lesson,session,student-action,turn-result}.schema.json` — optional utterance fields with inline contract definitions to keep direct JSON Schema validation offline.
- `apps/web/src/{generated/api.ts,types/viewModels.ts,adapters/realAdapter.ts,adapters/mockAdapter.ts,pages/StudentPage.tsx,speech/gateway.ts}` — consume backend utterances; retain string fallback for legacy/mock responses; route `needs_review` spans to Chinese browser speech.
- `services/speech-local/{tts.py,test_tts.py,README.md}` — `needs_review` nan spans use `web-speech`/Windows Chinese fallback and never reach MMS.
- `data/rag/manifest.json` — refreshed the approved demo fixture SHA-256 after adding the additive utterance fixture fields.
- `fixtures/lesson-analysis/stage07/01..05-*.json` and `scripts/stage07_fixture_review.py` — five representative fixtures now carry exact language coverage.

## Schema/OpenAPI version

- Public wire/schema/OpenAPI version remains `0.1.0`; the change is additive and keeps `current_prompt`, `next_prompt`, and `source_text` compatibility fields.
- New optional fields: `Lesson.source_utterance`, `Lesson.accessible_activity_utterance`, `SessionView.current_utterance`, `StudentActionResult.current_utterance`, `StudentActionResult.feedback_utterance`, `StudentActionResult.next_utterance`, `TurnResult.feedback_utterance`, and `TurnResult.next_utterance`.
- Internal MI300 prompt schemas are `stage07-facts.v3` and `stage07-activity.v2`.
- No SQLite column migration is required: lessons and event payloads are JSON documents; the existing session row still stores the compatibility prompt string.

## How to run

From the repository root:

```powershell
$env:PYTHONPATH = (Resolve-Path 'apps/core-api').Path
& .\apps\core-api\.venv\Scripts\python.exe -m unittest discover -s apps/core-api/tests -v
& .\apps\core-api\.venv\Scripts\python.exe scripts/test_contracts.py
& .\apps\core-api\.venv\Scripts\python.exe scripts/stage07_fixture_review.py
Push-Location apps/web
npm run typecheck
npm test
Pop-Location
```

## Tests and results

- Core Backend: PASS — 57 tests.
- Contract checks: PASS — 9 schemas, 3 OpenAPI documents / 49 responses, 21 schema fixtures, 10 student-safe fixtures.
- Stage 07 fixture review: PASS — all 5 fixtures, pending status, answer evidence, exact language coverage, and privacy checks.
- Web: PASS — TypeScript typecheck and 29 Vitest tests.
- Speech direct routing smoke: PASS — an unverified nan segment routes to `web-speech` with reason `needs_review_zh_fallback`.
- Full `services/speech-local` unittest suite: not executable in this checkout because `services/speech-local/.venv` is absent and the available Core venv does not contain `numpy`; no dependency or model installation was performed.

## Fixtures

The five Stage 07 metadata-only fixtures now include `language_segments` for both the original source text and accessible activity. They contain no textbook photos, raw recordings, cache, model weights, or database files.

## Resource usage

- MI300 remains stateless: it only labels Hanji spans as `zh-TW`/`nan-TW` and returns facts/activity JSON.
- Golden dictionary lookup, Tailo→POJ conversion, RAG, SQLite, lesson state, and utterance assembly remain on the Ryzen AI 9 laptop.
- MMS receives only local `verified`/`converted` POJ. `needs_review` spans use browser/Windows Chinese fallback.

## Known limits

- The checked-in golden set does not yet contain human-reviewed pronunciations for the screenshot's night-market food terms. Those terms therefore remain `needs_review` until approved data is added; no pronunciation was invented in this change.
- Teacher-edited accessible activities conservatively receive an all-Chinese utterance until a new MI300 analysis supplies explicit language boundaries.
- Existing clients that ignore the additive utterance fields continue to display the natural blue prompt text and can use their old all-text fallback.
- Full speech worker tests still require the existing speech-local environment with `numpy` and its pinned dependencies.

## Agent B can rely on

- The student UI should display only `current_prompt`/`next_prompt` text and pass the additive `Utterance` object to the speech gateway.
- Do not expose `lang`, `tailo_citation`, `poj_citation`, or `pronunciation_status` as student-facing text.
- For each ordered segment: `zh-TW` uses browser/Windows speech; approved nan segments use MMS; `needs_review` uses Chinese browser/Windows fallback.
- Existing string fields remain populated for compatibility, and the generated TypeScript contract is in `apps/web/src/generated/api.ts`.
- Lessons are still `pending` after analysis and require teacher/parent approval before session creation.

## Next action

Review this feature branch, install/use the existing speech-local runtime to run its full tests, then add only human-reviewed golden entries for any target Taiwanese vocabulary before enabling MMS playback for those terms. Merge only after explicit owner approval.
