# Local RAG data boundary

Owner: Agent A. Runtime: Ryzen AI 9 laptop only.

Git may contain source/license manifests and deterministic ingestion configuration here. Do not commit corpus dumps, embeddings, vector indexes, caches, student data, or copyrighted textbook media. Runtime indexes belong under `%LOCALAPPDATA%\HearOurLanguage\rag\indexes`.

`manifest.json` is the Stage 05 source allowlist. A source enters the formal
index only when its license is explicitly approved, `approved_for_index` is
true, and the recorded SHA-256 matches at build time. A pending or unknown
license is reported and excluded before the source is opened. The checked-in
Stage 05 source is a repository-owned demo fixture only; it is not a claim
that an external textbook or dictionary corpus has been authorized.

The default indexer uses a deterministic Unicode character n-gram embedding on
the laptop CPU. An optional `onnx-local` adapter accepts an operator-supplied,
approved CPU model and tokenizer; no model download is performed by the
repository scripts.

MI300 never owns or queries this index. Core Backend may include a small, request-scoped evidence selection in a VLM prompt.
