# Repository layout and ownership

The repository is a monorepo. Runtime implementations arrive in later stages; Stage 01 establishes boundaries and contract locations without moving another agent's code.

```text
apps/
  core-api/                    Agent A: laptop FastAPI product API
  web/                         Agent B: React/Vite UI
services/
  vlm-mi300/                   Agent A: stateless MI300 service
  speech-local/                Agent B: laptop ASR/TTS gateway
packages/
  contracts/
    schemas/v0.1/              Agent A canonical JSON Schema
    openapi/v0.1/              Agent A canonical OpenAPI 3.1
data/
  rag/                         Agent A corpus manifests/config only
fixtures/
  contracts/v0.1/             Agent A API/contract fixtures by audience
  device/                      Agent B device fixtures
docs/
  architecture/               cross-service decisions and diagrams
  contracts/v0.1/             version, errors, retention, usage
  device/                      Agent B device reports
  handoffs/                    stage handoffs
scripts/
  test_contracts.py            canonical schema/OpenAPI/fixture checks
```

## Guardrails

- Runtime SQLite files, RAG indexes, downloaded models, caches, photos, and recordings never belong in Git.
- `data/rag` contains only corpus manifests, source/license metadata, and deterministic ingestion configuration. Runtime indexes live under `%LOCALAPPDATA%`.
- `apps/web` and `services/speech-local` are Agent B-owned. Agent A may define their external contract but does not edit their core implementation.
- `apps/core-api`, `services/vlm-mi300`, Local RAG, SQLite, session, and Teaching Agent are Agent A-owned.
- MI300 has no directory for database, RAG, session, or product APIs.
- Generated frontend types belong under `apps/web/src/generated` and are outputs of canonical contracts, never an independent source of truth.
