# Agent A / Agent B v0.1 integration format

Status: `walkthrough accepted on integration branch` — the v0.1 contract,
generated types, frontend mappings, and boundary tests pass on
`codex/agentB_stage2`. Formal freeze remains pending user review and merge to
`main`; runtime API handlers are a later-stage dependency.

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

## 4. Observer summary — accepted v0.1 shape

The v0.1 update to `GET /api/sessions/{session_id}/summary` now provides the
observer fields required by `ObserverPage`: latest turn transcript/result,
feedback, progress, latency, fallbacks, hint history, review concepts, and
familiarity. The endpoint remains teacher/parent-only.

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

The accepted Agent A contract uses this information set in one synchronized
update to:

1. a versioned JSON Schema (prefer a reusable `observer-session-summary` schema);
2. `core-api.openapi.json` response `200` for `/summary`;
3. observer fixtures for no-turn, success, partial, and fallback cases; and
4. `scripts/test_contracts.py` plus any generated TypeScript output.

The existing `Lesson` endpoint can remain the source for teacher-only lesson
details. The summary need only carry `lesson_id`; the observer maps the lesson
topic/title separately and must never use the full Lesson in student mode.

## 5. Student action format — accepted v0.1 shape

`POST /api/sessions/{session_id}/turns` remains the transcript-bearing answer
route. Control intents are sent to the JSON `POST
/api/sessions/{session_id}/actions` route; query-string action dispatch is not
part of the canonical contract.

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
`codex/agentA-stage01-contract-baseline`, then integrated into Agent B branch
`codex/agentB_stage2` with merge commit `27f20f1`:

- Python contract tests: pass with the pinned `jsonschema 4.17.3` — 7
  schemas, 3 OpenAPI documents/45 responses, 18 schema fixtures, 10
  student-safe fixtures.
- JSON/OpenAPI parsing: pass.
- Explicit `openapi-typescript` generation from the v0.1 Core API: pass; output
  is `apps/web/src/generated/api.ts`.
- Canonical source path: accepted after Agent B generator fix in this branch.
- Observer summary: accepted; Agent B observer mapping and teacher-only
  projection test pass.
- Student action format: accepted; `/actions` is used for controls and
  `/turns` is used for transcript submissions, with no query-string action.
- Frontend verification: `npm run test` 4 files/8 tests, `npm run typecheck`,
  and `npm run build` pass.
- Contract status: `walkthrough_accepted_pending_main_merge`.

Sign-off: Agent B accepts Sections 4–5 for the v0.1 frontend integration on
this branch. This is not a claim that the later Core API runtime is deployed;
the runtime HTTP smoke remains a follow-up once handlers exist. The repository
may label the contract walkthrough accepted, while formal main-branch freeze
waits for user review and merge.

## 7. Ownership and change rule

Agent A owns the canonical schema, OpenAPI, and contract fixtures. Agent B owns
the generated frontend output, adapters, UI projections, and accessibility
tests. Any breaking change updates the version directory, schema, OpenAPI,
fixtures, contract tests, and this handoff together. No agent should silently
rename a field or reinterpret a response without recording the change here.

## 8. Stage 06 utterance normalization profile

`POST /api/utterances/normalize` now implements the already-reserved v0.1
operation. The request and response fields are unchanged. Agent B may pass a
`nan-TW` segment's `poj_citation` directly to `facebook/mms-tts-nan` only when
`pronunciation_status` is `verified` or `converted` and `tts_provider` is
`mms-tts-nan`. A `needs_review` segment always has `poj_citation: null` and no
TTS provider.

The MMS-facing POJ profile is lower-case, punctuation-free, and uses `nn` for
nasalization because the pinned official model vocabulary contains `n` but not
the superscript nasal marker. The scholarly/source 臺羅 remains unchanged in
`tailo_citation`; the MMS-compatible representation belongs only in
`poj_citation`.

Hanji-only input uses the versioned, manually reviewed repository lexicon.
Textbook-provided 臺羅 always takes precedence, but a disagreement with the
reviewed candidate is blocked as `needs_review`. OOV, multiple readings, and
literary/colloquial conflicts are likewise blocked. Internal audit records keep
the version and input/output of Unicode normalization, Hanji lookup, 臺羅→POJ,
and MMS vocabulary validation without adding private/internal trace fields to
the frozen public Utterance response.

No JSON Schema or OpenAPI version bump is required: Stage 06 fills the frozen
v0.1 endpoint and corrects the POJ fixture value without adding, removing, or
reinterpreting a field. Agent B should regenerate types as a regression check;
the generated type shape is expected to remain unchanged.
