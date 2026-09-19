# Agent A Stage 04 Manta forwarding follow-up handoff

```text
Stage: Agent A Stage 04 follow-up — direct Manta VLM Gateway forwarding
Status: done
Base: main @ 90516f8
Branch: codex/agentA-stage04-manta-forwarding
Schema/OpenAPI version: 0.1.0 / OpenAPI 3.1.0 (unchanged)
Previous dependencies: Agent A Stage 01, Stage 03, and Stage 04 — done and merged
```

## Summary

- Configured the Ryzen laptop Core Backend to call the current Manta VLM
  Gateway origin directly. On 2026-09-19 the gateway mapping is internal
  `8100/tcp` → external `http://210.61.209.139:46944`; Core does not call the
  raw vLLM mapping (`8000/tcp` → external `45503`).
- Kept the forwarding URL server-side. Browser code still calls only Core on
  `http://127.0.0.1:8000` and never receives the MI300 address.
- Added strict origin validation for `VLM_BASE_URL` and the release launcher's
  `Mi300BaseUrl`. Credentials, endpoint paths, query strings, fragments, and
  invalid ports are rejected before requests are sent.
- Changed release real mode to require an explicit current gateway origin
  instead of silently falling back to laptop localhost port 8100.
- Added an operator probe for direct `GET /internal/health` and optional
  `POST /internal/vlm/generate`. It does not output image bytes, prompt text,
  or raw model output.
- Documented the Manta project `qwen3-coder-fp8-bench`, Terminal Console path,
  current forwarding values, and the requirement to re-check Manta
  **Settings → Port Forwarding** after a forwarding rebuild.

## Changed files

- `apps/core-api/core_api/config.py`
- `apps/core-api/tests/test_config_and_db.py`
- `apps/core-api/config/development.env.example`
- `apps/core-api/README.md`
- `scripts/release/Start-Demo.ps1`
- `scripts/release/Test-Mi300Forwarding.ps1`
- `docs/release/stage10-operator-runbook.md`
- `services/vlm-mi300/README.md`
- `docs/handoffs/agent-a-stage04-manta-forwarding.md`

No Agent B React, Speech Gateway, ASR/TTS worker, canonical schema, canonical
OpenAPI, fixture, or SQLite migration file changed.

## Schema/OpenAPI version

- Canonical JSON Schema: Draft 2020-12, `schema_version=0.1.0` unchanged.
- Canonical OpenAPI: 3.1.0, API version `0.1.0` unchanged.
- Fixtures: unchanged.
- SQLite migrations: unchanged (`0001` through `0007`).
- No generated TypeScript regeneration or data migration is required.

## How to run

Health-only direct gateway probe from repository root:

```powershell
pwsh -File .\scripts\release\Test-Mi300Forwarding.ps1 `
  -BaseUrl 'http://210.61.209.139:46944'
```

Add a synthetic JPEG/PNG/WebP to exercise the generate route:

```powershell
pwsh -File .\scripts\release\Test-Mi300Forwarding.ps1 `
  -BaseUrl 'http://210.61.209.139:46944' `
  -ImagePath .\path\to\synthetic-test.jpg
```

Start the full laptop stack in real mode:

```powershell
pwsh -File .\scripts\release\Start-Demo.ps1 `
  -Mode real -SpeechProfile cpu `
  -Mi300BaseUrl 'http://210.61.209.139:46944'
```

## Tests and results

Run on 2026-09-19 from the Ryzen laptop:

```text
Core Backend unittest: 47 tests, OK
Contract tests: PASS — 9 schemas; 3 OpenAPI documents/48 responses;
                20 schema fixtures; 10 student-safe fixtures
Python compile: PASS
PowerShell parse (Start-Demo + Test-Mi300Forwarding): PASS
Start-Demo missing-origin guard: PASS
Start-Demo endpoint-path guard: PASS
git diff --check: PASS (line-ending conversion warnings only)
```

Live direct forwarding smoke:

```text
GET /internal/health: ready
service: vlm-mi300
model_revision: d9748a51ae66354c4dad665aab2c71f26cf2c8cd
queue_depth: 0

POST /internal/vlm/generate: success
synthetic input: one temporary 64×64 white JPEG
finish_reason: stop
queue_ms: 0
inference_ms: 218
candidate: schema-valid
```

The temporary image was removed after the request. No image bytes, prompt,
raw model output, model weights, database, or cache was committed.

## Fixtures

- Canonical contract fixtures are unchanged.
- Unit tests use existing in-memory synthetic images.
- The live smoke used a one-time synthetic white JPEG created under the system
  temp directory and deleted immediately afterward.

## Resource usage

- Configuration validation adds no persistent process or storage.
- The probe is a single PowerShell process and holds an optional image only for
  the request lifetime.
- Live generate reported `queue_ms=0` and `inference_ms=218`; this is one smoke
  sample, not a latency benchmark.
- Core, RAG, SQLite, Teaching Agent, session, and Speech remain on the Ryzen
  laptop. MI300 remains a stateless VLM service.

## Known limits

- Manta external port `46944` is dynamic. If the forwarding rule is rebuilt,
  the operator must read the new `8100/tcp` mapping in Manta Settings and pass
  it through `VLM_BASE_URL` or `-Mi300BaseUrl`.
- The repository does not scrape or auto-discover Manta Settings; this avoids
  storing Manta credentials or coupling runtime startup to browser automation.
- The current forwarding uses HTTP. Operators must keep the Manta forwarding
  access control/trusted network policy in place and must not expose the URL to
  browser code.
- Direct gateway calls are diagnostic only. Product image analysis continues
  through laptop Core so validation, RAG, SQLite, fallback, and cleanup remain
  enforced.

## Agent B can rely on

- Frontend base URL remains `http://127.0.0.1:8000`.
- No `VITE_*` variable or browser request contains the MI300 URL.
- Core still reports explicit degraded/offline VLM health and can start when
  MI300 is unavailable.
- Canonical schema, OpenAPI, fixtures, generated TypeScript, and Speech port
  `8200` are unchanged.

## Next action

1. Before each real demo, verify the current Manta `8100/tcp` forwarding with
   `Test-Mi300Forwarding.ps1`.
2. If Manta reallocates the port, update only the runtime value and dated
   operator documentation; do not add it to frontend configuration.
3. Review and merge the PR only with explicit user/repository-owner approval.
