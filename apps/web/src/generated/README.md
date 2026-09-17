# Generated contract types

This directory is intentionally waiting for Agent A's versioned canonical contract. Run:

```powershell
npm run contracts:generate
```

from `apps/web` after `packages/contracts/openapi.yaml` (or an explicit OpenAPI/JSON Schema path) exists. The generator writes `api.ts` here using `openapi-typescript`.

Do not hand-write `Lesson`, `Utterance`, `TurnResult`, `ServiceHealth`, or API response types in this directory. Until the contract lands, the Mock adapter uses presentation-only view models and the Real adapter fails with `CONTRACT_NOT_GENERATED` instead of casting unknown payloads.
