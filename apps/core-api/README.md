# Core Backend

Owner: Agent A. Runtime: Ryzen AI 9 laptop.

This directory will contain the FastAPI product API, orchestration, VLM client, Local RAG integration, Teaching Agent, SQLite migrations, session state, SSE, health aggregation, and fallback policy. The browser's product requests terminate here. The API contract is `packages/contracts/openapi/v0.1/core-api.openapi.json`.

The service must start and serve health/existing lessons when MI300 is offline. It must never store runtime databases, indexes, recordings, photos, or downloaded models in Git.
