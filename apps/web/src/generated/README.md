# Generated contract types

Run this from `apps/web` after Agent A's versioned canonical contract is available:

```powershell
npm run contracts:generate
```

By default the command reads `packages/contracts/openapi/v0.1/core-api.openapi.json`
and writes `api.ts` here using `openapi-typescript`. The generated file includes
the source path and contract version header. Pass an explicit contract path and
output path when generating another canonical service document.

Do not hand-write `Lesson`, `Utterance`, `TurnResult`, `ServiceHealth`, or API response types in this directory. Until the contract lands, the Mock adapter uses presentation-only view models and the Real adapter fails with `CONTRACT_NOT_GENERATED` instead of casting unknown payloads.
