# Agent A Stage 05 handoff

```text
Stage: Agent A Stage 05 — Laptop Local RAG ingestion and persistent index
Status: done
Base: main @ c9d5106 (Stage 04 PR #7 and Agent B Stage 04 PR #6 merged)
Branch: codex/agentA-stage05-rag-index
Schema/OpenAPI version: 0.1.0 / OpenAPI 3.1.0 (unchanged)
Runtime host: Ryzen AI 9 laptop only
```

## Summary

- Added a versioned `data/rag/manifest.json` with source path, authorization
  status, license note, acquisition date, source version, and SHA-256.
- Added a strict source gate: only `license_status=approved` plus
  `approved_for_index=true` and a matching source hash can be opened. Pending
  or unknown-license sources are excluded before file access and reported in
  the build metadata.
- Added lesson-fixture, JSONL, text, and Markdown ingestion. Chunking preserves
  Hanji and 臺羅 text, emits entry/section/rule locators, normalizes broken
  UTF-8/control/whitespace noise, drops too-short content, and deduplicates
  normalized text without removing the original chunk text.
- Added the deterministic CPU `hashing-char-ngram-v1` multilingual baseline and
  an optional local `onnx-local` CPU adapter. No model is downloaded or
  committed. The adapter is intentionally not selected until an approved
  tokenizer/model is supplied.
- Added a SQLite persistent vector index with packed embeddings, provenance
  metadata, JSONL chunk inspection output, keyword fallback, and revision IDs.
- Added full and incremental rebuild modes. Incremental builds reuse vectors
  for unchanged chunk IDs; every build completes in a staging directory and
  switches `active.json` only after validation. A failed build leaves the
  previous active revision untouched.
- Connected the active index to Core health. `/api/health` reports the RAG
  service as `ready` with the index revision after a successful reindex, and
  remains explicitly degraded when no active index is present.

## Changed files

- `.gitignore`
- `apps/core-api/README.md`
- `apps/core-api/config/demo.env.example`
- `apps/core-api/config/development.env.example`
- `apps/core-api/config/test.env.example`
- `apps/core-api/core_api/app.py`
- `apps/core-api/core_api/config.py`
- `apps/core-api/core_api/health.py`
- `apps/core-api/core_api/rag/__init__.py`
- `apps/core-api/core_api/rag/models.py`
- `apps/core-api/core_api/rag/embeddings.py`
- `apps/core-api/core_api/rag/chunking.py`
- `apps/core-api/core_api/rag/index.py`
- `apps/core-api/tests/test_rag.py`
- `data/rag/README.md`
- `data/rag/manifest.json`
- `data/rag/smoke_queries.json`
- `data/rag/embedding-evaluation.json`
- `scripts/rag_reindex.py`
- `scripts/rag_smoke.py`
- `scripts/rag_evaluate_embeddings.py`
- `docs/handoffs/agent-a-stage05.md`

No canonical JSON Schema, OpenAPI document, contract fixture, migration,
Agent B frontend, Speech Gateway, ASR/TTS worker, MI300 service, student
recording, textbook photograph, model weight, runtime index, or database was
changed or committed.

## Schema/OpenAPI version

- Canonical JSON Schema: Draft 2020-12, `schema_version=0.1.0` unchanged.
- Canonical OpenAPI: 3.1.0, API version `0.1.0` unchanged.
- No frozen field was removed, renamed, or reinterpreted. No Agent B type
  regeneration is required.
- Runtime Core adds no new public endpoint in this Stage. The existing frozen
  `/api/admin/rag/reindex` reservation remains for a later API integration;
  the reproducible local command is supplied below.

## Corpus authorization and coverage

The formal Stage 05 manifest contains one approved, repository-owned demo
fixture (`repository-demo-market-lesson`) so the pipeline and smoke tests are
reproducible without importing copyrighted material. It is explicitly marked
demo-only and is not an official textbook or dictionary corpus. No external
official source was silently assumed to be licensed. An operator may add an
external source only after recording its license, authorization note, date,
version, and SHA-256 in the manifest; otherwise the source is excluded.

## How to run

From the repository root with native Windows Python 3.12:

```powershell
python -m venv apps/core-api/.venv
apps/core-api/.venv/Scripts/python.exe -m pip install -r apps/core-api/requirements.txt

# Build the active laptop index under %LOCALAPPDATA%\HearOurLanguage.
& apps/core-api/.venv/Scripts/python.exe scripts/rag_reindex.py --mode full

# Reuse unchanged chunk embeddings and atomically switch the new revision.
& apps/core-api/.venv/Scripts/python.exe scripts/rag_reindex.py --mode incremental

# Run the 20 representative retrieval queries without keeping a test index.
& apps/core-api/.venv/Scripts/python.exe scripts/rag_smoke.py

# Evaluate the selected CPU baseline and report ONNX availability.
& apps/core-api/.venv/Scripts/python.exe scripts/rag_evaluate_embeddings.py
```

Set `RAG_MANIFEST_PATH`, `RAG_INDEX_ROOT`, `RAG_EMBEDDING_BACKEND`, and
`RAG_EMBEDDING_DIMENSION` through the Core configuration when using a different
laptop runtime location. The default runtime path is outside the repository.

## Tests and results

Executed on 2026-09-18, Windows, Python 3.12.9 with the repository Core
virtual environment:

```text
Set-Location apps/core-api
& .\.venv\Scripts\python.exe -m unittest discover -s tests -v
Set-Location ../..
21 tests, OK

python -m unittest discover -s apps/core-api/tests -p test_rag.py -v
7 tests, OK

python scripts/test_contracts.py
PASS: 7 schemas; 3 OpenAPI documents/45 responses; 18 schema fixtures; 10 student-safe fixtures

python -m compileall -q apps/core-api/core_api scripts/rag_*.py
PASS

python scripts/rag_smoke.py
20 queries, 20 passed, no failures
```

The RAG tests cover source authorization/hash gates, UTF-8 cleaning, Hanji
and 臺羅 retention, locators, deduplication/short-chunk handling, persistence,
keyword fallback, full rebuild, incremental vector reuse, atomic switch
failure protection, Core health integration, and the full 20-query set.

## Embedding and resource results

- Selected backend: `hashing-char-ngram-v1:256d`, deterministic CPU-only,
  dependency-free, preserving Unicode code points for Hanji and 臺羅.
- 20-query evaluation: 20/20 passed; mean query latency 0.884 ms; p95 1.244
  ms in the recorded run. The report is in
  `data/rag/embedding-evaluation.json`.
- Optional `onnx-local` adapter: present but not evaluated because no approved
  local model/tokenizer or ONNX runtime was installed. No network download was
  attempted.
- Demo index: 9 chunks, 1 approved source, 256-dimensional vectors. Recorded
  full-build working set peak was 56.97 MiB, build time 49 ms, and cold start
  18 ms; a separate persistent-index measurement was 71,498 bytes (0.068 MiB).
  Later runs vary with Windows process state.
- Device budget used for planning: 31.12 GiB physical RAM, 7.78 GiB system
  reserve, 23.34 GiB post-reserve runtime capacity, and 4.0 GiB Core+SQLite+RAG
  planning cap. The device snapshot reported 582.66 GiB free on C: with a
  100 GiB operational floor. The Stage 05 demo index is far below these
  budgets and uses CPU; the iGPU remains reserved for display/browser/Camera.

## Known limits

- The current formal corpus is demo-only. Official dictionary, curriculum, and
  external textbook sources remain out of the index until their authorization
  is recorded; the pipeline reports no result rather than generating a
  replacement citation.
- The default hashing embedding is a lightweight lexical/character baseline,
  not a trained semantic model. It is appropriate for offline smoke coverage;
  a licensed multilingual ONNX encoder requires a later measured evaluation.
- Stage 05 exposes retrieval primitives and health, but Stage 06 still owns
  production citation assembly, reranking policy, language normalization, and
  evidence injection into teaching prompts. Lesson analysis continues to avoid
  fabricating evidence until that handoff is integrated.
- The reserved public reindex API is not implemented in this Stage; use the
  local command while the index remains laptop-only.

## Agent B can rely on

- No canonical schema/OpenAPI or generated frontend types changed.
- Core remains the only product API and MI300 remains stateless; the RAG
  manifest, embeddings, SQLite index, and retrieval all stay on the laptop.
- `GET /api/health` includes the existing `rag` service. It is `degraded` with
  `RAG_NO_RESULT` when no active index exists and `ready` with
  `model_revision=rag-<revision>` after a successful local reindex.
- Runtime index files are outside Git under `%LOCALAPPDATA%\HearOurLanguage\rag\indexes`.
- Retrieval results include `source_id`, title, SHA-256, license, language,
  locator, section, and active index revision for the Stage 06 citation layer.
- Unknown-license sources are never included by the supplied builder.

## Next action

1. Review this branch and PR against `main`; do not merge without explicit
   user/repository-owner authorization.
2. Agent A Stage 06 consumes `RagIndexManager.search()` for citation assembly,
   reranking, 臺羅/POJ normalization boundaries, and no-result behavior.
3. Add only explicitly authorized official corpus entries to the manifest after
   owner review; rerun hash verification, resource measurement, and all 20
   smoke queries.

## Git state

At handoff time the implementation is local on
`codex/agentA-stage05-rag-index`. It is not yet committed, pushed, or opened as
a PR; those states will be reported separately after the final diff check.
