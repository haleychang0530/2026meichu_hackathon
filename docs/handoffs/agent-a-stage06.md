# Agent A Stage 06 handoff

```text
Stage: Agent A Stage 06 — Hybrid retrieval, citation, and language normalization
Status: done
Base: main @ 1233a43 (Agent A Stage 05 PR #8, Agent B Stage 03 PR #9, and Agent B Stage 05 PR #10 merged)
Branch: codex/agentA-stage06-retrieval-normalization
Pull request: #11 — https://github.com/haleychang0530/2026meichu_hackathon/pull/11
Schema/OpenAPI version: 0.1.0 / OpenAPI 3.1.0 (unchanged)
Runtime host: Ryzen AI 9 laptop only
```

## Summary

- Extended the Stage 05 local index with normalized exact, keyword, vector,
  and metadata-filtered retrieval. Ranking has a configurable reliability
  threshold, top-k, duplicate suppression, and total context character budget.
- Added an evidence policy layer that emits `source_id`, `title`, `excerpt`,
  `locator`, `score`, and `index_revision`; every citation can be replayed
  against the same local revision. Queries below the threshold return empty
  evidence.
- Implemented the frozen `POST /api/utterances/normalize` Core endpoint.
  Textbook 臺羅 is preserved first; Hanji-only input uses the reviewed offline
  candidate set; output POJ is gated against the official MMS Min Nan vocab.
- Added versioned audit steps for Unicode normalization, Hanji candidate lookup,
  臺羅→POJ conversion, and MMS vocabulary validation. Internal audit steps
  retain each tool version and input/output without adding private trace fields
  to the public Utterance response.
- OOV, multiple readings, literary/colloquial readings, unsupported MMS
  characters, and textbook/dictionary conflicts return `needs_review`, with
  `poj_citation=null` and `tts_provider=null` so Speech cannot synthesize an
  unapproved pronunciation.
- Added a 38-entry engineering golden set, an explicit manual-review queue,
  an MMS-ready success fixture, and a `needs_review` fixture.

## Changed files

- `apps/core-api/core_api/language/{__init__.py,normalization.py}`
- `apps/core-api/core_api/rag/{__init__.py,index.py,retrieval.py}`
- `apps/core-api/core_api/{app.py,config.py,models.py}`
- `apps/core-api/config/{development,demo,test}.env.example`
- `apps/core-api/tests/{test_app.py,test_config_and_db.py,test_normalization.py,test_retrieval.py}`
- `apps/core-api/README.md`
- `data/language/{README.md,normalization-golden.json,manual-review.json}`
- `fixtures/contracts/v0.1/{manifest.json,observer/success.utterance.json,observer/needs-review.utterance.json}`
- `scripts/{test_contracts.py,language_golden.py,retrieval_citation_smoke.py}`
- `docs/contracts/v0.1/agent-a-b-integration-format.md`
- `docs/handoffs/agent-a-stage06.md`

No frontend component, Speech Gateway/ASR/TTS worker, MI300 service, SQLite
migration, model weight, runtime index, database, textbook photograph, or
student recording is changed or committed.

## Schema/OpenAPI version

- Canonical JSON Schema remains Draft 2020-12 with
  `schema_version=0.1.0`.
- Canonical OpenAPI remains 3.1.0 with API version `0.1.0`.
- Stage 06 implements the already-reserved `/api/utterances/normalize` path;
  no field is added, removed, renamed, or reinterpreted.
- The success Utterance fixture's POJ value is corrected to the official MMS
  vocabulary profile (`nn`, lower-case, punctuation-free), and one additive
  `needs_review` fixture is added. Contract type generation produces the same
  TypeScript shape.
- No database migration or compatibility adapter is required.

## How to run

From the repository root with the existing Core Python 3.12 environment:

```powershell
& apps/core-api/.venv/Scripts/python.exe scripts/rag_reindex.py --mode full
& apps/core-api/.venv/Scripts/python.exe scripts/retrieval_citation_smoke.py
& apps/core-api/.venv/Scripts/python.exe scripts/language_golden.py

$env:CORE_PROFILE = 'demo'
$env:CORE_DATA_DIR = (Resolve-Path 'apps/core-api').Path + '\.runtime\demo'
Set-Location apps/core-api
& .\.venv\Scripts\python.exe -m core_api
```

Normalize a TTS-ready textbook citation:

```powershell
curl.exe -X POST http://127.0.0.1:8000/api/utterances/normalize `
  -H "Content-Type: application/json" `
  -d '{"schema_version":"0.1.0","text":"市場","lang":"nan-TW","tailo_citation":"tshī-tiûnn"}'
```

## Tests and results

Executed on 2026-09-18, Windows, Python 3.12.9 and the repository-pinned
Node/npm environment:

```text
Core unittest discovery: 33 tests, OK
Contract suite: PASS — 7 schemas; 3 OpenAPI documents/45 responses;
  19 schema fixtures; 10 student-safe fixtures
Golden normalization report: 38/38 passed; no failures
Hybrid retrieval/citation smoke: 20/20 queries passed; 40 citations replayed;
  no failures
Stage 05 RAG smoke regression: 20/20 passed
Python compileall: PASS
pip check: No broken requirements found
Frontend generated types: PASS; generated API shape unchanged
Frontend Vitest: 7 files / 18 tests passed
Frontend TypeScript strict check: PASS
Frontend Vite production build: PASS
git diff --check: PASS (Windows LF/CRLF conversion warnings only)
```

The Core count is recorded as 33 after the final configuration-boundary test.

## Fixtures

- `normalization-golden.json`: 38 Hanji/臺羅/POJ/Chinese-gloss/example rows.
- `manual-review.json`: multiple-reading, literary/colloquial, OOV,
  textbook-conflict, and critical-demo listening checks.
- `success.utterance.json`: Agent B TTS-ready `poj_citation` example.
- `needs-review.utterance.json`: explicit no-POJ/no-provider gate.
- Existing lesson fixture remains the only approved RAG corpus source. No
  external dictionary or copyrighted corpus was added.

## Resource usage

- CPU-only, dependency-free `hashing-char-ngram-v1:256d`; no new model is
  loaded and the iGPU/NPU remain untouched.
- Citation smoke on the nine-chunk demo index: 20 queries, 40 reproduced
  citations, mean 0.913 ms, p95 1.660 ms, top-k 5, threshold 0.40, context
  budget 1,600 characters.
- Stage 05 build regression remained 20/20 with a recorded process peak of
  approximately 57.01 MiB in this run. Language normalization adds only the
  38-row in-memory lexicon and deterministic string rules.

## Known limits

- The formal corpus is still the repository-owned demo fixture. Official
  dictionary, curriculum, and textbook sources remain excluded until explicit
  authorization and hashes are recorded. Missing reliable evidence therefore
  returns an empty list.
- Taibun, THOKIT, and 臺灣言語工具 are not installed in the laptop environment.
  This Stage uses the allowed offline fallback: a bounded reviewed lexicon and
  versioned rules. It does not claim complete Taiwanese lexical coverage.
- `verified` means deterministic approval inside this engineering golden set,
  not a substitute for an official dictionary or language specialist.
- The MMS checkpoint is not downloaded or synthesized in Stage 06. Agent B
  Stage 07 still owns model revision/license verification and the 30-sentence
  human listening test. The critical demo sentence remains on that checklist.
- Evidence score stays server-internal under the frozen v0.1 Lesson contract;
  observer evidence uses the canonical provenance fields and the Lesson-level
  `rag_index_revision`.

## Agent B can rely on

- Call only Core `POST /api/utterances/normalize`; never send Hanji or raw
  VLM romanization directly to MMS-TTS.
- For `nan-TW`, pass `poj_citation` to MMS only when status is `verified` or
  `converted` and provider is `mms-tts-nan`.
- `needs_review` always means `poj_citation=null`, no TTS provider, and a
  teacher/language-review action before synthesis.
- MMS-facing POJ is lower-case, punctuation-free, and uses `nn` for nasalized
  syllables because superscript `ⁿ` is absent from the official vocabulary.
- The frozen Utterance/OpenAPI type shape is unchanged; regeneration is a
  regression check, not a migration.
- Core/RAG/normalization stay on the Ryzen laptop. MI300 remains stateless and
  Speech ownership remains with Agent B.

## Next action

1. Agent B Stage 07 regenerates Core types, consumes `poj_citation` under the
   gates above, pins the MMS checkpoint/license, and completes the human audio
   listening report plus prerecorded fallback.
2. Repository owner reviews the Stage 06 PR; do not merge without explicit
   authorization.
3. Add official corpus sources only after license/authorization review, then
   rebuild and rerun retrieval, citation, and resource tests.

## Git state

- Local implementation: complete.
- Commits: implementation `082b61b`; initial handoff `99dda8c`.
- Remote branch: pushed to `origin/codex/agentA-stage06-retrieval-normalization`.
- Pull request: #11 is open against `main`.
- Merge: not performed; explicit user/repository-owner authorization is still
  required.
