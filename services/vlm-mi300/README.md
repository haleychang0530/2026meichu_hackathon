# MI300 stateless VLM service

Owner: Agent A. Runtime: MI300 trusted-LAN host.

Only `/internal/health` and `/internal/vlm/generate` are permitted. The service accepts one image, prompt, response schema, optional compact laptop-selected evidence, request ID, and model revision. It returns structured inference output and metrics, then discards request data.

This service must not contain RAG ingestion/retrieval, SQLite, sessions, student records, SSE, speech, product APIs, or callbacks to the laptop. Contract: `packages/contracts/openapi/v0.1/vlm-mi300.openapi.json`.
