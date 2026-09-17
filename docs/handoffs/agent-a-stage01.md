# Agent A Stage 01 handoff

```text
Stage: Agent A Stage 01 — architecture, repository, and contract baseline
Status: done (implementation); v0.1 draft pending Agent B walkthrough/sign-off
Base: main @ ee5cbc1
Branch: codex/agentA-stage01-contract-baseline
Schema/OpenAPI version: 0.1.0 / OpenAPI 3.1.0
Previous Stage: none (Stage 01 has no dependency)
```

## Summary

- Declared the Ryzen AI 9 laptop as the product host for Core Backend, Local RAG, SQLite, Teaching Agent, session/SSE, Speech Gateway, web, and all product state.
- Restricted MI300 to two stateless internal VLM endpoints with one-way laptop-originated calls and no retained request data.
- Defined runtime, network, storage, failure, timeout, retry, circuit-breaker, request-ID, versioning, and deletion boundaries.
- Added versioned canonical `Lesson`, `Utterance`, `TurnResult`, `ServiceHealth`, and `Error` JSON Schemas.
- Added OpenAPI v0.1 drafts for Core Backend, internal MI300 VLM, and local Speech Gateway.
- Added observer/shared fixtures plus six student-safe scenarios: success, partial success, MI300 offline, RAG no result, ASR failure, and TTS failure.
- Added automated contract tests that validate Draft 2020-12 schemas, every typed fixture, OpenAPI paths/refs/response request IDs, fixture manifest completeness, and forbidden student fields.

## Changed files

- `apps/core-api/README.md`
- `apps/web/README.md`
- `services/vlm-mi300/README.md`
- `services/speech-local/README.md`
- `data/rag/README.md`
- `packages/contracts/schemas/v0.1/*.schema.json`
- `packages/contracts/openapi/v0.1/*.openapi.json`
- `packages/contracts/requirements-contracts.txt`
- `fixtures/contracts/v0.1/**`
- `scripts/test_contracts.py`
- `docs/architecture/*.md`
- `docs/contracts/v0.1/*.md`
- `docs/handoffs/agent-a-stage01.md`

No Agent B React component, adapter, ASR/TTS worker, device fixture, or device report was modified.

## Schema/OpenAPI version

- JSON Schema dialect: 2020-12
- Canonical `schema_version`: `0.1.0`
- OpenAPI: `3.1.0`, API info version `0.1.0`
- Contract status: `draft_pending_agent_b_walkthrough`
- Migration: none; this is the first canonical contract. Breaking changes require a new version directory and migration/compatibility notes.

## How to run

From the repository root:

```powershell
python -m pip install -r packages/contracts/requirements-contracts.txt
python scripts/test_contracts.py
```

## Tests and results

Run on 2026-09-17:

```text
PASS: 5 schemas; 3 OpenAPI documents/41 responses; 10 schema fixtures; 6 student-safe fixtures
```

The test suite also asserts that MI300 exposes exactly `/internal/health` and `/internal/vlm/generate`, and that every OpenAPI response declares `X-Request-ID`.

## Fixtures

- Observer: canonical Lesson success/RAG-empty, Utterance success, TurnResult success/partial, and MI300-offline ServiceHealth.
- Shared errors: MI300 offline, RAG no result, ASR failed, TTS failed.
- Student: six view fixtures under `fixtures/contracts/v0.1/student` with a deny-list test for answer keys, `confidence`, evidence, review fields, source text, original/accessible activity, model/index revision, and teacher controls.

## Resource usage

- Stage 01 adds text-only contracts, fixtures, tests, and documentation; no model, database, media, corpus, or runtime index is added.
- Agent B Stage 01 measured 31.12 GiB physical RAM, a 7.78 GiB system reserve, and a 23.34 GiB post-reserve runtime capacity.
- The preliminary Core Backend + SQLite + Local RAG cap remains 4.0 GiB, single worker, until later Agent A measurement.
- Contract testing uses a small Python process and the pinned `jsonschema` development dependency only.

## Known limits

- v0.1 is not formally frozen until Agent B completes the contract walkthrough and signs off.
- OpenAPI files are design contracts; runtime handlers arrive in later stages.
- Student/observer separation is a response-shaping rule for the demo, not formal authorization. The full Lesson endpoint is observer/teacher-only and must not be called from student mode.
- Timeout and memory values are baseline budgets pending later integration measurements.
- No SQLite migration exists yet because Stage 01 introduces no runtime database schema.

## Agent B can rely on

- Canonical field names, enums, error envelope, and request-ID behavior in `packages/contracts` for mock adapters and generated TypeScript types.
- Six student-safe fixtures that do not require MI300, RAG, ASR, or TTS to be running.
- MI300 remaining stateless and unreachable directly from the browser.
- Core Backend owning all lesson/session/RAG/SQLite behavior and aggregating health/fallback states.
- Speech Gateway remaining Agent B-owned on laptop localhost with the v0.1 draft endpoint shapes.

## Next action

1. Agent B performs a walkthrough against the Stage 02 mock adapter and records accepted questions or requested changes.
2. Agent B regenerates TypeScript types from the accepted canonical contracts.
3. Agent A incorporates agreed additive corrections with synchronized schema, OpenAPI, fixtures, version notes, and tests.
4. Only after both agents record acceptance may the repository label v0.1 as formally frozen.
