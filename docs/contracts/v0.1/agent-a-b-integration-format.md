# Agent A / Agent B v0.1 integration format

Status: `conditional walkthrough` — the v0.1 contract tests pass, but the
observer and student-action surfaces below still need an Agent A contract
decision before v0.1 can be frozen.

This document is the shared format handoff for both agents. Agent A remains the
owner of canonical schemas and OpenAPI. Agent B consumes generated types and
must not create a parallel canonical model in the frontend.

## 1. Canonical sources and generated types

The v0.1 sources are:

- Core product API: `packages/contracts/openapi/v0.1/core-api.openapi.json`
- Local Speech Gateway: `packages/contracts/openapi/v0.1/speech-gateway.openapi.json`
- MI300 internal API: `packages/contracts/openapi/v0.1/vlm-mi300.openapi.json`
- Shared JSON Schema: `packages/contracts/schemas/v0.1/*.schema.json`
- Fixtures and audience policy: `fixtures/contracts/v0.1/**`

The browser must call only the laptop Core API and, where explicitly needed,
the localhost Speech Gateway. It must never call the MI300 API.

From `apps/web`, generate the Core API types with:

```powershell
npm run contracts:generate
```

The default input is `packages/contracts/openapi/v0.1/core-api.openapi.json`
and the default output is `apps/web/src/generated/api.ts`. The generator adds a
source-contract and `0.1.0` header to the generated file. Do not hand-write
`Lesson`, `Utterance`, `TurnResult`, `ServiceHealth`, `Session`, or API response
types in `apps/web/src/generated`.

To generate another canonical document explicitly:

```powershell
npm run contracts:generate -- `
  packages/contracts/openapi/v0.1/speech-gateway.openapi.json `
  apps/web/src/generated/speech-gateway.ts
```

The generated output is valid only when the source contract and fixture tests
pass. A missing source contract is a blocking error, not a reason to create a
fallback hand-written type.

## 2. Request, response, and error envelope

All JSON requests that represent a canonical model include:

```json
{
  "schema_version": "0.1.0"
}
```

Callers may send a valid `X-Request-ID`; every service response must return the
same header or generate and return a UUID. JSON error responses use the
canonical shape:

```json
{
  "schema_version": "0.1.0",
  "code": "ASR_FAILED",
  "message": "localized or operator-readable message",
  "retryable": true,
  "fallback": "keyboard_input",
  "request_id": "00000000-0000-4000-8000-000000000001"
}
```

The server-side error `request_id` is a UUID. A browser-only transport error
may keep `request_id: null` internally, but it must not be presented as a
valid server error envelope.

## 3. Student and observer data boundary

Student routes may use the safe `Session` and `TurnResult` projections. They
must not receive, store, render, or place in DOM data from the full teacher
review `Lesson`, including:

- `source_text`, `original_activity`, `learning_objective`,
  `accessible_activity`;
- `evidence`, `confidence`, `review_status`;
- `vlm_model_revision`, `rag_index_revision`; or
- teacher notes, controls, answer keys, or internal review fields.

Observer/teacher routes may request the full Lesson and turn history. The
frontend must use different response selectors and cache keys for student and
observer data. Mock fixtures must follow the same visibility boundary as real
responses.

## 4. Observer summary — required change before freeze

The current `GET /api/sessions/{session_id}/summary` response only contains
`session_id`, `completed_turns`, and `concepts_to_review`. That is not enough for
the required observer experience or for the current `ObserverPage`, which needs
the latest transcript, evaluation, feedback, progress, latency, and fallbacks.

Recommended additive v0.1 shape for the existing teacher/parent-only summary
endpoint:

```json
{
  "schema_version": "0.1.0",
  "session_id": "session_demo_001",
  "lesson_id": "lesson_market_001",
  "state": "EVALUATING",
  "progress": 0.4,
  "completed_turns": 1,
  "turns": [
    {
      "schema_version": "0.1.0",
      "turn_id": "turn_001",
      "session_id": "session_demo_001",
      "transcript_raw": "市場",
      "transcript_normalized": "市場",
      "result": "correct",
      "matched_concepts": ["市場"],
      "feedback": "答對了。",
      "next_prompt": "請說：阿媽欲去市場。",
      "progress": 0.4,
      "latency_ms": { "asr": 820, "backend": 95, "vlm": null, "tts": 310, "total": 1225 },
      "asr_device": "cpu",
      "fallbacks": ["asr_cpu"]
    }
  ],
  "concepts_to_review": ["欲去"],
  "hint_history": [
    { "turn_id": "turn_001", "prompt": "請再說一次。", "feedback": "可補上動作。" }
  ],
  "familiarity": [
    { "concept": "市場", "status": "developing" }
  ]
}
```

Agent A may choose different names, but the accepted contract must provide the
same information or explicitly revise the Stage2 UI requirement. The change
must be made in one synchronized update to:

1. a versioned JSON Schema (prefer a reusable `observer-session-summary` schema);
2. `core-api.openapi.json` response `200` for `/summary`;
3. observer fixtures for no-turn, success, partial, and fallback cases; and
4. `scripts/test_contracts.py` plus any generated TypeScript output.

The existing `Lesson` endpoint can remain the source for teacher-only lesson
details. The summary need only carry `lesson_id`; the observer maps the lesson
topic/title separately and must never use the full Lesson in student mode.

## 5. Student action format — required change before freeze

`POST /api/sessions/{session_id}/turns` currently requires a JSON body with
`schema_version` and `transcript`, while the Stage2 adapter uses UI actions
(`listen`, `answer`, `hint`, `pause`) and currently sends a query parameter.
Query-string action dispatch is not part of the canonical contract.

Recommended normalization:

- Keep `/turns` for a submitted answer only. Its body is JSON with
  `schema_version`, required `transcript`, and optional `input_mode` and
  `asr_device`; it returns canonical `TurnResult`.
- Add a teacher/student-safe `POST /api/sessions/{session_id}/actions` for
  control actions. Its body is JSON with `schema_version`, required `action`,
  and optional `input_mode`:

```json
{
  "schema_version": "0.1.0",
  "action": "request_hint",
  "input_mode": "voice"
}
```

Use this action enum: `replay_prompt`, `start_answer`, `pause`, `resume`,
`request_hint`, and `next`. `submit_answer` belongs to `/turns` so a transcript
can never be accidentally omitted. Every action response must return a safe
`Session` projection plus any user-facing feedback/next prompt; it must not
return Lesson evidence, confidence, or answer keys.

The adapter mapping is:

| UI intent | Canonical request |
| --- | --- |
| 播放提示 | `POST /actions`, `action=replay_prompt` |
| 開始回答 | `POST /actions`, `action=start_answer` |
| 送出回答 | `POST /turns` with `transcript` |
| 取得提示 | `POST /actions`, `action=request_hint` |
| 暫停／繼續 | `POST /actions`, `action=pause` or `resume` |
| 下一步 | `POST /actions`, `action=next` |

If Agent A prefers one discriminated `/actions` endpoint instead, the same
fields and visibility rules apply; the contract must still distinguish an
answer submission from a control action and must include fixtures for both.

## 6. Walkthrough and sign-off record

Review performed against Agent A branch
`codex/agentA-stage01-contract-baseline`:

- Python contract tests: pass — 5 schemas, 3 OpenAPI documents, 10 schema
  fixtures, 6 student-safe fixtures.
- JSON/OpenAPI parsing: pass.
- Explicit `openapi-typescript` generation from the v0.1 Core API: pass.
- Canonical source path: accepted after Agent B generator fix in this branch.
- Observer summary: not accepted; required fields are missing.
- Student action format: not accepted; `/turns` and UI actions disagree.
- Contract status: `conditional`, not frozen.

Sign-off condition: Agent B can sign v0.1 after Agent A accepts Sections 4–5,
updates the canonical contract/fixtures/tests, and both agents rerun the
contract and frontend suites. Until then this document is a review record, not
an approval to label v0.1 frozen.

## 7. Ownership and change rule

Agent A owns the canonical schema, OpenAPI, and contract fixtures. Agent B owns
the generated frontend output, adapters, UI projections, and accessibility
tests. Any breaking change updates the version directory, schema, OpenAPI,
fixtures, contract tests, and this handoff together. No agent should silently
rename a field or reinterpret a response without recording the change here.
