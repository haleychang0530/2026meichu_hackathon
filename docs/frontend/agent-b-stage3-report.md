# Agent B Stage 03：Camera 擷取、影像品質與教材上傳

## 交接摘要

```text
Stage: Agent B Stage 03
Status: done
Branch: codex/agentB_stage03
Base: origin/main @ c9d5106 (Agent A 01–04 and Agent B Stage 04 merged)
Contract: Core API v0.1.0
```

前端 Camera／檔案備援、影像品質提示、方向校正、EXIF 清理、有界壓縮、
multipart adapter 與 Capture page 流程已完成，並已接上 Agent A Stage 04 的
`POST /api/lessons/analyze` runtime handler。Real adapter 會先以
`GET /api/health` 建立 capture 入口，保留 `X-Provider-Mode`，並在 Agent A
Stage 08 session API 尚未提供前停用建立 session 按鈕；前端沒有猜測或另造
API schema。

## Changed files

- `apps/web/src/capture/imageQuality.ts`：檔案格式、大小、解析度、模糊、曝光檢查與中文修正建議。
- `apps/web/src/capture/imageProcessing.ts`：orientation-aware decode、canvas crop、EXIF 清理、有界 JPEG 壓縮、quality metrics、video frame capture 與 object URL cleanup。
- `apps/web/src/capture/CameraCapture.tsx`：Camera 權限、預覽、切換裝置、拍照、檔案上傳、品質覆寫、重拍與鍵盤操作。
- `apps/web/src/pages/CapturePage.tsx`：送至 Core Backend、取消、30 秒逾時、重試與明確離線 fixture。
- `apps/web/src/adapters/adapter.ts`、`mockAdapter.ts`、`realAdapter.ts`：共用 analyze/fallback 介面、v0.1 multipart request、provider mode 與 Stage 04 capture entrypoint。
- `apps/web/src/types/viewModels.ts`、`apps/web/src/styles.css`、`apps/web/src/components/AppShell.tsx`、`apps/web/index.html`、`apps/web/README.md`。
- `apps/web/src/adapters/realAdapter.test.ts`、`apps/web/src/capture/*.test.ts`：API mapping、provider header、幾何與品質單元測試。

Canonical OpenAPI／JSON Schema 與 generated types 沒有修改；`analyzeLesson`
已由現有 `packages/contracts/openapi/v0.1/core-api.openapi.json` 產生的
`operations['analyzeLesson']` 使用。

## How to run

```powershell
cd apps/web
npm run test
npm run typecheck
npm run build
npm run dev
```

Mock mode 是預設值。要測試 Stage 03 real multipart adapter，先啟動 Core
demo，再以 `VITE_DATA_MODE=real` 與 `VITE_CORE_API_BASE_URL` 啟動前端：

```powershell
$env:CORE_PROFILE = 'demo'
$env:CORE_DATA_DIR = (Resolve-Path 'apps/core-api').Path + '\.runtime\demo'
Set-Location apps/core-api
& .\.venv\Scripts\python.exe -m core_api

$env:VITE_DATA_MODE = 'real'
$env:VITE_CORE_API_BASE_URL = 'http://127.0.0.1:8000'
npm --prefix apps/web run dev -- --host 127.0.0.1 --port 5173
```

在 `/capture` 使用相機或檔案備援即可送出 multipart；Stage 04 demo 會以
fixture 回傳並在頁面標示來源。Lesson confirmation/session creation 仍由
Agent A Stage 08 提供。

## Image limits and privacy

- Input decode upper bound：20 MiB。
- Compressed upload upper bound：8 MiB。
- Minimum accepted resolution：640×480。
- Long edge upper bound：4096 px；default crop is the complete page to avoid
  cutting off small 台羅 text.
- Camera／file bytes are not logged. The preview uses a short-lived object URL;
  stream tracks and object URLs are released on stop, replacement, error, or
  unmount. The backend remains responsible for post-analysis temporary-file
  deletion according to `docs/contracts/v0.1/data-retention.md`.

## Tests and results

Results on the pinned Node/npm toolchain:

- `npm run test`：pass，7 test files／18 tests。
- `npm run typecheck`：pass，TypeScript strict check。
- `npm run build`：pass，Vite production build。
- `npm run contracts:generate`：pass，generated Core API output unchanged。
- pinned `jsonschema[format]==4.17.3` contract suite：pass，7 schemas、3
  OpenAPI documents／45 responses、18 schema fixtures、10 student-safe
  fixtures。
- Core API `python -m unittest discover -s tests -v`：pass，14 tests。
- Synthetic JPEG HTTP smoke：`GET /api/health` 200、`POST /api/lessons/analyze` 200、
  `X-Provider-Mode: fixture`、request ID echoed，upload directory empty after request。
- Browser smoke on `http://127.0.0.1:5173/capture` with real adapter：Core health
  and Stage 04 pending-capture entry rendered; CORS passed on the contract port.
- `git diff --check`：pass；Git only reports the repository's normal LF／CRLF
  conversion warnings on Windows。

The global Python environment currently has `jsonschema 4.26.0`; running the
contract suite without the repository-pinned dependency fails on the existing
`$defs/familiarity` resolver compatibility issue. The pinned temporary test
environment passes. These automated tests do not claim real device permission
or backend latency. Camera permission/stream and actual file-picker smoke still
require the demo laptop's user gesture; synthetic HTTP and real-adapter
capture-entry checks are complete.

## Accessibility checks

- Native `button`, `label`, `select`, `input[type=file]`, `video`, and `img`
  elements are used; no positive `tabindex` was added.
- Camera status, processing status, upload status, quality warnings, and
  permission fallback are exposed with visible text and live regions.
- A denied camera permission leaves the file-upload control in the same flow.
- Warning overrides require an explicit checkbox; rejected quality states cannot
  be submitted from the UI.

## Agent A can rely on

- Real mode sends only `POST /api/lessons/analyze` to the Core Backend using
  `multipart/form-data`; the browser has no MI300 URL or direct VLM call.
- Form fields are `image` (JPEG Blob with safe filename), `language=nan-TW`, and
  `use_fixture_on_failure=true`.
- Frontend aborts the request after 30 seconds or when the user cancels; no
  second lesson is created by the UI after cancellation or timeout.
- `getCaptureFallback()` is explicitly labelled frontend fixture mode and does
  not claim to be a VLM result.
- Backend must repeat file type, resolution, size, and image-quality validation;
  the browser check is a UX and resource guard, not a trust boundary.

## Known limits and next action

- The default crop is the full page; the processing API accepts a normalized
  crop rectangle, while a mouse-drawn crop editor is intentionally deferred so
  the default path does not hide small text.
- The demo Core provider intentionally returns `fixture`; a live MI300 provider
  smoke remains dependent on the trusted VLM endpoint and is not claimed here.
- Agent A Stage 08 must add lesson/session runtime routes before the real-mode
  capture page can enable `確認教材並開始`.
