# Agent A Stage 04 handoff

```text
Stage: Agent A Stage 04 — Ryzen AI 9 Core Backend and VLM client
Status: done
Base: main @ 8a2475c (Stage 03 PR #5 merged)
Branch: codex/agentA-stage04-core-backend
Schema/OpenAPI version: 0.1.0 / OpenAPI 3.1.0 (unchanged)
Previous dependencies: Agent A Stage 01 and Stage 03 — done and merged
```

## Summary

- Added the laptop-only FastAPI Core Backend with `development`, `demo`, and
  `test` configuration layers. The frontend sees only the Core base URL; the
  MI300 URL remains a server-side environment value.
- Added request-ID propagation/generation, canonical errors, CORS for Agent B
  Vite port 5173, metadata-only request logs, and runtime `/openapi.json`.
- Added the real MI300 client with separate connect/read timeouts, two-attempt
  default retry, exponential backoff, and a three-failure circuit breaker with
  recovery probe behavior.
- Added the `/api/lessons/analyze` Stage 04 pipeline: streaming byte limit,
  JPEG/PNG/WebP container/dimension/pixel validation, EXIF transpose,
  metadata-free bounded JPEG normalization, canonical Lesson validation, and
  cleanup on success, error, cancellation, and startup TTL janitor.
- Added a fixture provider using the same `Lesson` response model. Fixture and
  fallback responses are explicit through `X-Provider-Mode` and
  `vlm_model_revision=fixture:v0.1`.
- Enforced the laptop trust boundary: gateway model revision is authoritative;
  before Stage 05 Local RAG exists, Core replaces any VLM-authored evidence
  with `evidence=[]` and `rag_index_revision=null`.
- Added SQLite migration tracking and a first runtime metadata migration, but
  no session/turn domain tables (those remain Stage 08).
- Added `/api/health` aggregation for Core+SQLite, RAG placeholder, MI300, ASR,
  and TTS. MI300-offline and fixture mode keep Core available and return
  explicit degraded/offline dependency states.

## Changed files

- `.gitignore`
- `apps/core-api/README.md`
- `apps/core-api/requirements.txt`
- `apps/core-api/config/*.env.example`
- `apps/core-api/core_api/*.py`
- `apps/core-api/migrations/0001_runtime_metadata.sql`
- `apps/core-api/tests/*.py`
- `docs/handoffs/agent-a-stage04.md`

No Agent B React component, generated TypeScript type, Speech Gateway,
ASR/TTS worker, canonical schema, canonical OpenAPI, or fixture file changed.

## Schema/OpenAPI version

- Canonical JSON Schema: Draft 2020-12, `schema_version=0.1.0` (unchanged).
- Canonical OpenAPI: 3.1.0, API version `0.1.0` (unchanged).
- Runtime FastAPI OpenAPI documents the two Stage 04 handlers now available:
  `GET /api/health` and `POST /api/lessons/analyze`. The canonical document
  remains the source for Agent B generated types and includes later-stage
  paths that are not yet runtime handlers.
- SQLite migration baseline: `0001_runtime_metadata.sql`; idempotent migration
  records live in `schema_migrations`.
- No frozen field was removed, renamed, or reinterpreted, so no contract
  migration or Agent B type regeneration is required.

## How to run

From the repository root with native Windows Python 3.12:

```powershell
python -m venv apps/core-api/.venv
apps/core-api/.venv/Scripts/python.exe -m pip install -r apps/core-api/requirements.txt

$env:CORE_PROFILE = 'demo'
$env:CORE_DATA_DIR = (Resolve-Path 'apps/core-api').Path + '\.runtime\demo'
Set-Location apps/core-api
& .\.venv\Scripts\python.exe -m core_api
```

Use `CORE_PROFILE=development`, `CORE_PROVIDER=real`, `VLM_BASE_URL`, and the
pinned `VLM_MODEL_REVISION` for the real provider. Full variables and request
examples are in `apps/core-api/README.md`.

Agent B Core base URL:

```text
http://127.0.0.1:8000
```

## Tests and results

Final local results on 2026-09-18 (Windows, Python 3.12.14):

```text
python -m unittest discover -s tests -v
14 tests, OK

python scripts/test_contracts.py
PASS: 7 schemas; 3 OpenAPI documents/45 responses; 18 schema fixtures; 10 student-safe fixtures

npm run test
4 test files, 8 tests passed

npm run typecheck
PASS

npm run build
PASS; Vite production bundle built
```

The Backend suite covers profile overrides, migration idempotence, request ID,
CORS, canonical errors and health, image validation, success/error/cancel cleanup,
TTL janitor, provider schema parity, authoritative metadata normalization,
finite retry, timeout mapping, circuit breaker, runtime OpenAPI, MI300-offline
startup, and fixture fallback.

Process smokes:

- Demo fixture: Core startup PASS; health HTTP 200 degraded; analyze HTTP 200;
  runtime OpenAPI HTTP 200 with no MI300 URL; upload directory empty after the
  request.
- MI300 offline: Core startup PASS; health HTTP 200 with VLM offline; fallback
  analyze HTTP 200; disabled fallback returned canonical timeout/offline error;
  upload directory empty.
- Live trusted MI300: health ready; one synthetic 512×512 JPEG analyze HTTP
  200 in 1,992 ms through Core; canonical Lesson fields present; provider
  `real`; pinned revision
  `d9748a51ae66354c4dad665aab2c71f26cf2c8cd`; no RAG evidence fabricated;
  upload directory empty. Only synthetic image bytes were used and no prompt,
  raw output, or image was persisted.

## Fixtures

- Runtime fixture source remains the frozen
  `fixtures/contracts/v0.1/observer/success.lesson.json`.
- Fixture responses are revalidated as canonical `Lesson` and marked
  `fixture:v0.1`; no duplicate or changed contract fixture was added.
- Unit tests generate in-memory white JPEGs. No original textbook photo,
  student recording, VLM raw output, or generated media is committed.

## Resource usage

- Core uses one uvicorn worker and CPU image normalization on the Ryzen laptop.
- Demo smoke after health/analyze/OpenAPI: working set 60.05 MiB, private
  memory 44.41 MiB, 6 threads. This is well below Agent B's preliminary
  4.0 GiB Core+SQLite+RAG cap; Stage 05 must remeasure after embedding/index.
- Default accepted upload is at most 10 MiB, 20 megapixels, and 8192 pixels per
  side; normalized output is at most 4096 pixels per side.
- SQLite and temporary media remain below `CORE_DATA_DIR` on the laptop.

## Known limits

- Only health and lesson analysis have runtime handlers in Stage 04. Lesson
  storage/review, normalization, sessions, turns, SSE, summaries, and RAG
  reindex remain in later Agent A stages even though the frozen canonical
  OpenAPI already reserves their paths.
- RAG intentionally reports degraded and returns no evidence until Stage 05.
- Speech health reports offline when Agent B's localhost port 8200 is absent;
  this does not stop Core startup or lesson analysis.
- Fixture analyze uses the existing market lesson regardless of input image;
  the provider marker prevents it from being mistaken for real inference.
- Core currently returns a synchronous analyze response. The live synthetic
  call was below the 20-second target; job/progress handling remains a later
  resilience option for slow network/model conditions.
- Real model content is teacher-review pending. This stage validates structure
  and provenance boundaries, not textbook semantic quality or RAG citations.

## Agent B can rely on

- Core listens on `http://127.0.0.1:8000`; Vite can use
  `VITE_CORE_API_BASE_URL=http://127.0.0.1:8000`.
- Browser code never needs or receives `VLM_BASE_URL`.
- `GET /api/health` always responds while MI300 is unavailable if Core and
  SQLite can start, with dependency states and canonical request IDs.
- `POST /api/lessons/analyze` accepts multipart `image`, `language=nan-TW`,
  and `use_fixture_on_failure`; successful real and fixture paths both return
  canonical `Lesson 0.1.0`.
- `X-Provider-Mode` is `real`, `fixture`, or `fixture-fallback`; CORS exposes
  it and `X-Request-ID` to the browser.
- All error bodies contain `code`, `message`, `retryable`, `fallback`, and
  `request_id`; response headers echo the same request ID.
- Canonical schema/OpenAPI files are unchanged, so current generated TypeScript
  types remain valid.

## Next action

1. Agent B runs a Real adapter HTTP smoke against port 8000 and decides where
   capture/upload UI should call `/api/lessons/analyze` in its owned files.
2. Agent A Stage 05 adds Local RAG ingestion/indexing and replaces the explicit
   RAG placeholder without moving index state off the laptop.
3. Keep PR unmerged until user/repository-owner review; do not delete the
   feature branch after merge without authorization.
