# Agent B Stage 03：Camera 擷取、影像品質與教材上傳

## 交接摘要

```text
Stage: Agent B Stage 03
Status: partial
Branch: codex/agentB_stage03
Base: origin/main (2026-09-18)
Contract: Core API v0.1.0
```

前端 Camera／檔案備援、影像品質提示、方向校正、EXIF 清理、有界壓縮、
multipart adapter 與 Capture page 流程已完成。Agent A Stage 04 的 Core
Backend runtime handler 尚未在目前 base 提供，因此真實 HTTP upload 與 MI300
端到端結果仍待接上後補測；前端沒有猜測或另造 API schema。

## Changed files

- `apps/web/src/capture/imageQuality.ts`：檔案格式、大小、解析度、模糊、曝光檢查與中文修正建議。
- `apps/web/src/capture/imageProcessing.ts`：orientation-aware decode、canvas crop、EXIF 清理、有界 JPEG 壓縮、quality metrics、video frame capture 與 object URL cleanup。
- `apps/web/src/capture/CameraCapture.tsx`：Camera 權限、預覽、切換裝置、拍照、檔案上傳、品質覆寫、重拍與鍵盤操作。
- `apps/web/src/pages/CapturePage.tsx`：送至 Core Backend、取消、30 秒逾時、重試與明確離線 fixture。
- `apps/web/src/adapters/adapter.ts`、`mockAdapter.ts`、`realAdapter.ts`：共用 analyze/fallback 介面與 v0.1 multipart request。
- `apps/web/src/types/viewModels.ts`、`apps/web/src/styles.css`、`apps/web/README.md`。
- `apps/web/src/capture/*.test.ts`：幾何與品質單元測試。

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

Mock mode 是預設值。要測試 multipart adapter，使用 `VITE_DATA_MODE=real`
啟動前端，並把 `VITE_CORE_API_BASE_URL` 指到筆電 Core Backend；Stage 04
handler 完成後，在 `/capture` 按「開始預覽」或使用檔案上傳即可進行實機 smoke。

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

- `npm run test`：pass，6 test files／14 tests。
- `npm run typecheck`：pass，TypeScript strict check。
- `npm run build`：pass，Vite production build。
- `npm run contracts:generate`：pass，generated Core API output unchanged。
- pinned `jsonschema[format]==4.17.3` contract suite：pass，7 schemas、3
  OpenAPI documents／45 responses、18 schema fixtures、10 student-safe
  fixtures。
- `git diff --check`：pass；Git only reports the repository's normal LF／CRLF
  conversion warnings on Windows。

The global Python environment currently has `jsonschema 4.26.0`; running the
contract suite without the repository-pinned dependency fails on the existing
`$defs/familiarity` resolver compatibility issue. The pinned temporary test
environment passes. These automated tests do not claim real device permission
or backend latency. Camera permission/stream smoke should be repeated in the
actual demo browser after the runtime handler is available.

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

- Agent A Stage 04 runtime handler is not on this branch, so real multipart HTTP
  smoke, backend request-id behavior, temporary upload deletion, and MI300
  offline responses remain pending.
- The default crop is the full page; the processing API accepts a normalized
  crop rectangle, while a mouse-drawn crop editor is intentionally deferred so
  the default path does not hide small text.
- Actual Edge/Chrome permission and camera-device switching should be manually
  verified on the demo laptop, followed by a backend end-to-end upload check.
