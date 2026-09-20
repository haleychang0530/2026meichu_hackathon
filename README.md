# hear tAIgi

> 讓世界，多一種被理解的方式

hear tAIgi is an accessibility-first learning prototype for Taiwanese-language lessons. It turns a photographed or uploaded lesson page into a listen-and-speak learning session, with separate learner and teacher/parent views.

The repository provides a deterministic offline demo by default. The real integration path is optional and adds Core API lesson analysis, local speech inference, Local RAG retrieval, and an external MI300 vision-language model (VLM).

## What the product includes

- Camera capture and file-upload fallback with image quality checks, orientation correction, cropping, and metadata removal.
- A React/Vite web application with setup, capture, learner, observer, and health routes.
- A FastAPI Core Backend that owns product APIs, validation, SQLite state, lesson orchestration, and dependency health.
- A laptop-only Local RAG index with an approved-source manifest, deterministic CPU embeddings, citations, and smoke tests.
- An optional localhost Speech Gateway for ASR and TTS. Mock speech is the default; pinned CPU models are available for a fuller local run.
- A stateless MI300 VLM gateway for real lesson analysis. The browser never calls the MI300 service directly.
- Keyboard-oriented flows, visible focus behavior, screen-reader support, and an optional in-app narration mode.

## Architecture

```text
Browser (React/Vite)
  ├── mock adapter                 deterministic offline walkthrough
  ├── Core Backend :8000           the only product API in real mode
  │     ├── SQLite                  laptop-owned lessons and sessions
  │     ├── Local RAG               laptop-only retrieval and citations
  │     └── MI300 VLM :8100         optional stateless image analysis
  └── Speech Gateway :8200         localhost-only ASR/TTS in real speech mode
```

Core owns product state and privacy boundaries. The MI300 gateway does not own SQLite, RAG, sessions, student records, or callbacks to the laptop. Runtime files, databases, model caches, and generated indexes are kept outside Git.

## Repository layout

| Path | Purpose |
| --- | --- |
| `apps/web` | React 19 and Vite frontend |
| `apps/core-api` | FastAPI Core Backend, migrations, tests, and configuration profiles |
| `services/speech-local` | Local ASR/TTS gateway and CPU worker implementations |
| `services/vlm-mi300` | Stateless MI300 VLM gateway and operator scripts |
| `packages/contracts` | Versioned v0.1 JSON Schemas and OpenAPI documents |
| `data/rag` | RAG manifest, smoke queries, and deterministic index configuration |
| `data/language` | Reviewed language-normalization data and manual-review metadata |
| `fixtures` | Contract, session, device, audio, and lesson fixtures |
| `scripts` | Contract, language, RAG, release, and validation utilities |
| `docs` | Architecture, device, frontend, contract, and release documentation |

## Prerequisites

The tested development runtime is:

- Python 3.12.
- Node.js 20.19+ on the 20.x line, or Node.js 22.12+.
- npm from the selected Node.js installation.
- Git.
- Linux: Bash, `curl`, and `setsid` for the POSIX demo launcher.
- Windows: PowerShell 7 for the release scripts.

The default mock walkthrough does not require an MI300, GPU, API key, ASR model, or TTS model. Network access is required to install Python/npm dependencies. CPU speech model provisioning additionally requires access to Hugging Face.

## Reproduce the offline demo on Linux

From a fresh checkout:

```bash
git clone https://github.com/haleychang0530/2026meichu_hackathon.git
cd 2026meichu_hackathon

bash scripts/release/setup-linux.sh
bash scripts/release/start-demo-linux.sh
```

The setup script creates `apps/core-api/.venv`, installs Core dependencies, and runs `npm ci` for the web app. The demo launcher builds an isolated Local RAG index and starts the web app, Core Backend, and mock Speech Gateway on localhost.

Open these URLs in a browser:

- <http://127.0.0.1:5173/setup> — product walkthrough entry point.
- <http://127.0.0.1:5173/health> — service and device health view.
- <http://127.0.0.1:8000/docs> — Core Backend OpenAPI documentation.

The mock adapter can be used without camera or microphone permissions. For a quick learner walkthrough, open `/setup` and choose the example lesson. To stop all processes started by the launcher:

```bash
bash scripts/release/stop-demo-linux.sh
```

The launcher stores logs, SQLite data, RAG indexes, and process metadata under `apps/core-api/.runtime/stage10-demo/`; this directory is ignored by Git.

### Linux CPU speech profile

CPU speech is optional. Install its environment, download the exact pinned model revisions, and start the demo with the CPU profile:

```bash
bash scripts/release/setup-linux.sh --with-cpu-speech
bash scripts/release/provision-speech-models-linux.sh
bash scripts/release/start-demo-linux.sh --speech-profile cpu
```

For real lesson analysis as well, provide the current MI300 gateway origin:

```bash
bash scripts/release/start-demo-linux.sh \
  --mode real \
  --speech-profile cpu \
  --mi300-base-url http://MI300_HOST:8100
```

The VLM service must already be running and reachable at the supplied origin. Do not put credentials, paths, or a browser-facing MI300 URL in frontend configuration. The MMS-TTS model is licensed under CC-BY-NC-4.0; review that license before any non-development deployment.

## Reproduce the demo on Windows

Install Python 3.12 and Node.js first, then run from PowerShell at the repository root:

```powershell
py -3.12 -m venv apps/core-api/.venv
& .\apps\core-api\.venv\Scripts\python.exe -m pip install -r .\apps\core-api\requirements.txt
npm --prefix .\apps\web ci

pwsh -NoProfile -File .\scripts\release\Start-Demo.ps1 -Mode mock -SpeechProfile mock
```

Open <http://127.0.0.1:5173/health>. Stop the managed processes with:

```powershell
pwsh -NoProfile -File .\scripts\release\Stop-Demo.ps1
```

To use the pinned CPU speech profile, install the additional speech environment and provision the models before starting:

```powershell
py -3.12 -m venv services\speech-local\.venv
& .\services\speech-local\.venv\Scripts\python.exe -m pip install -r .\services\speech-local\requirements.txt
pwsh -NoProfile -File .\scripts\release\Provision-SpeechModels.ps1 -Model all
pwsh -NoProfile -File .\scripts\release\Start-Demo.ps1 -Mode mock -SpeechProfile cpu
```

See [`apps/core-api/README.md`](apps/core-api/README.md), [`apps/web/README.md`](apps/web/README.md), and [`services/speech-local/README.md`](services/speech-local/README.md) for service-specific configuration.

## Frontend-only preview

The web app defaults to the deterministic mock adapter and can be previewed without starting the backend:

```bash
npm --prefix apps/web ci
npm --prefix apps/web run dev -- --host 127.0.0.1
```

Then open <http://127.0.0.1:5173/setup>. The app uses the real Core and Speech services only when the corresponding environment variables select real mode:

```bash
VITE_DATA_MODE=real \
VITE_CORE_API_BASE_URL=http://127.0.0.1:8000 \
VITE_SPEECH_MODE=real \
VITE_SPEECH_GATEWAY_BASE_URL=http://127.0.0.1:8200 \
npm --prefix apps/web run dev -- --host 127.0.0.1
```

## Profiles and important settings

| Setting | Values | Meaning |
| --- | --- | --- |
| `VITE_DATA_MODE` | `mock`, `real` | Selects the frontend adapter. Mock is deterministic and offline. |
| `VITE_SPEECH_MODE` | `mock`, `real` | Selects browser-only/mock speech or the localhost Speech Gateway. |
| `CORE_PROFILE` | `development`, `demo`, `test` | Selects Core Backend defaults. `demo` and `test` use fixture data. |
| `CORE_PROVIDER` | `fixture`, `real` | Selects deterministic fixture analysis or the configured MI300 provider. |
| `CORE_DATA_DIR` | filesystem path | Stores local SQLite and temporary runtime state. |
| `RAG_MANIFEST_PATH` | filesystem path | Selects the approved source manifest. |
| `RAG_INDEX_ROOT` | filesystem path | Selects the generated Local RAG index directory. |
| `VLM_BASE_URL` | HTTP(S) origin | Core-to-MI300 gateway origin; never expose this directly to the browser. |
| `SPEECH_BASE_URL` | HTTP origin | Core-to-local Speech Gateway origin. |

Safe examples are provided in [`apps/core-api/config`](apps/core-api/config). Environment variables override profile defaults. The checked-in RAG manifest excludes sources whose license is pending; only approved sources can enter a formal index.

## Main routes

| Route | Use |
| --- | --- |
| `/setup` | Select a lesson path and accessibility mode |
| `/capture` | Capture or upload a lesson page |
| `/session/<id>/student` | Learner session with listening and speaking interactions |
| `/session/<id>/observer` | Teacher/parent projection of the same server-side session |
| `/health` | Browser, Core, RAG, VLM, ASR, and TTS readiness view |

In real mode, a lesson must be reviewed before a student session is created. Student responses use safe projections; teacher evidence, answer evidence, confidence, and review metadata stay in the observer boundary.

## Verification

Run the following checks after installing the relevant environments. The commands below assume Linux/macOS shell syntax; use the equivalent `.venv\Scripts\python.exe` paths on Windows.

```bash
# Frontend
npm --prefix apps/web test -- --run
npm --prefix apps/web run typecheck
npm --prefix apps/web run build

# Core Backend and contracts
(cd apps/core-api && .venv/bin/python -m unittest discover -s tests -v)
apps/core-api/.venv/bin/python scripts/test_contracts.py
apps/core-api/.venv/bin/python scripts/language_golden.py
apps/core-api/.venv/bin/python scripts/retrieval_citation_smoke.py
apps/core-api/.venv/bin/python scripts/stage07_fixture_review.py
apps/core-api/.venv/bin/python scripts/rag_smoke.py

# Local Speech Gateway
services/speech-local/.venv/bin/python -m unittest discover \
  -s services/speech-local -p 'test_*.py' -v

# MI300 gateway syntax and dependency-backed unit checks that do not require a live model
apps/core-api/.venv/bin/python -m py_compile \
  services/vlm-mi300/service.py \
  services/vlm-mi300/test_service.py \
  services/vlm-mi300/client_example.py
apps/core-api/.venv/bin/python -m unittest discover \
  -s services/vlm-mi300 -p 'test_service.py' -v

# Patch hygiene
git diff --check
```

The web package also provides `npm run contracts:generate` for regenerating TypeScript types from the canonical Core OpenAPI document. Do not hand-edit generated contract types.

## Service documentation

- [Core Backend](apps/core-api/README.md)
- [Web application](apps/web/README.md)
- [Local Speech Gateway](services/speech-local/README.md)
- [MI300 VLM service](services/vlm-mi300/README.md)
- [Contract v0.1](docs/contracts/v0.1/README.md)
- [Release operator runbook](docs/release/stage10-operator-runbook.md)

## Data, privacy, and reproducibility boundaries

- Runtime databases, upload staging files, audio caches, model weights, and generated indexes are not repository artifacts.
- Core removes uploaded image metadata and deletes temporary upload files after each request.
- The Speech Gateway keeps audio bytes and transcripts in memory for the active request and does not write raw student audio.
- The MI300 gateway is stateless and receives only the bounded request payload selected by Core.
- Local RAG ingestion is controlled by `data/rag/manifest.json`; pending or unknown licenses are excluded.
- The repository fixtures are synthetic or contract-scoped. Do not add student photographs, recordings, credentials, private URLs, or unlicensed textbook dumps.

## Troubleshooting

- If a port is already in use, stop the managed demo before starting another one. The default ports are 5173 (web), 8000 (Core), and 8200 (Speech).
- If health reports degraded RAG, rerun the launcher or run `scripts/rag_reindex.py --mode full` with the intended manifest and index root.
- If camera or microphone permission is unavailable, use the file-upload and keyboard paths; the mock walkthrough does not require media permissions.
- If real mode reports an offline VLM, verify the MI300 gateway health endpoint and the configured origin. The browser should still use the Core API origin only.
- If the CPU speech profile cannot find a model, rerun the pinned provisioning script or pass explicit local model paths as documented by the speech service.

## Known limitations in this checkout

The RAG manifest currently contains five third-party reading sources marked `license_status=pending`. The index builder correctly excludes them and indexes the approved repository fixture. The existing Core test `test_manifest_and_chunks_preserve_tailo_locator_and_license` still expects zero skipped sources, so the full Core suite reports one pre-existing failure until that expectation is updated or the pending entries are removed. The contract, language, RAG smoke, fixture-review, frontend, Speech Gateway, and MI300 gateway checks pass.
