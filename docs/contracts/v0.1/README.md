# Contract v0.1 draft

Canonical sources:

- JSON Schema: `packages/contracts/schemas/v0.1`
- OpenAPI 3.1: `packages/contracts/openapi/v0.1`
- Fixtures: `fixtures/contracts/v0.1`

The draft contains `Lesson`, `Utterance`, `TurnResult`, `ServiceHealth`, and `Error`, plus Core Backend, internal MI300, and local Speech Gateway APIs. Every canonical object uses `schema_version: 0.1.0`. Every API response carries `X-Request-ID`; error JSON also carries `request_id`.

Run the contract checks:

```powershell
python -m pip install -r packages/contracts/requirements-contracts.txt
python scripts/test_contracts.py
```

Student fixtures live only under `fixtures/contracts/v0.1/student`. Tests reject answer keys, model confidence, evidence, review fields, source textbook text, original activities, and teacher controls in that directory.

## Consumer workflow

Agent B may generate TypeScript types from the canonical JSON/OpenAPI documents into `apps/web/src/generated`. Generated files must include the source contract version and be regenerated whenever Agent A changes a contract file. Until the walkthrough is signed, consumers should pin to this directory but treat it as `draft_pending_agent_b_walkthrough`.

## Change rule

Any breaking change must update the versioned schema and OpenAPI directory, fixtures, tests, migration/compatibility notes, and the Agent B handoff together. There is no migration for this initial version because no earlier canonical contract or SQLite schema exists.
