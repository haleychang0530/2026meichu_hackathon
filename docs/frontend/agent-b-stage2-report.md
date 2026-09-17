# Agent B Stage 02：前端骨架、Generated Types 與 Mock

## 交接摘要

```text
Stage: Agent B Stage 02
Status: ready_for_review | v0.1 walkthrough accepted on the integration branch; runtime backend pending
Branch: codex/agentB_stage2
```

## 已完成

- React + Vite + TypeScript frontend under `apps/web`。
- `agent.md` 與根目錄 `.gitignore` 已加入 local workflow／PR 規定與前端產物忽略規則。
- URL routes：`/setup`、`/capture`、`/session/{id}/student`、`/session/{id}/observer`。
- Mock adapter and Real adapter transport boundary with a shared `FrontendAdapter` interface。
- Loading、empty、degraded、offline、recoverable-error、error boundary 與 error envelope UI。
- Semantic HTML、keyboard-friendly controls、focus ring、responsive layout、ARIA live status 與 progress bar。
- Mock flow：選教材 → 確認 lesson → 學生操作 → 教師／家長查看同一個 mock session 摘要。
- Student view 不含 answer、confidence、teacher 欄位；observer view 使用另一個 selector。
- `scripts/generate_contract_types.mjs` 與 `npm run contracts:generate` 已準備好，會以 `openapi-typescript` 產生型別。
- `agent.md` 已建立，規定 branch、PR、review／merge、契約與阻塞回報流程。
- `docs/contracts/v0.1/agent-a-b-integration-format.md` 已建立，統一 generated types、error envelope、observer summary、student action 與 sign-off 格式。
- Agent A v0.1 contract 已整合到本 branch；`apps/web/src/generated/api.ts` 由 canonical Core OpenAPI 產生並被 adapter 使用。
- Real adapter 已完成 health、lesson、session、observer summary、control action 與 transcript answer 的 typed mapping；瀏覽器不會直接呼叫 MI300。
- Capture page 對 canonical Lesson 未提供圖片 reference 的情況有明確 empty state，不會假造圖片資料。

## Changed files

- `agent.md`、`.gitignore`。
- `apps/web/`：Vite entry、React pages/components、view models、Mock／Real adapters、error envelope、routing、styles、tests 與 npm lockfile。
- `apps/web/src/generated/api.ts`：由 `packages/contracts/openapi/v0.1/core-api.openapi.json` 產生的 v0.1 型別。
- `apps/web/src/adapters/realAdapter.test.ts`：Real adapter 的 action、answer、observer mapping 測試。
- `scripts/generate_contract_types.mjs`：canonical Core API contract 存在時的 generated-type 入口。
- `docs/contracts/v0.1/agent-a-b-integration-format.md`：Agent A／B 共享格式與 walkthrough 紀錄。
- `docs/frontend/agent-b-stage2-report.md`：本 handoff。

## How to run

```powershell
cd apps/web
npm install
npm run test
npm run typecheck
npm run build
npm run dev
```

預設為 Mock mode。用 `?health=degraded`、`?health=offline` 或 `?health=recoverable_error` 可驗證健康狀態畫面；設定 `VITE_DATA_MODE=real` 會進入 typed Real adapter，實際執行仍需要 Core API runtime handlers。

Contract checks:

```powershell
python -m pip install -r packages/contracts/requirements-contracts.txt
python scripts/test_contracts.py
```

## Blocker / boundary

目前沒有阻擋 v0.1 前端 walkthrough 的 contract blocker。Agent A 的 canonical schema、OpenAPI、fixtures 與 contract tests 已在本 branch 的 merge commit 整合，且 Real adapter 已依 generated types 完成 mapping。

仍有一個明確的 downstream boundary：本 repository 目前只有 OpenAPI design contract，沒有後續階段的 Core API runtime handlers，因此尚未做真實 HTTP backend end-to-end smoke。Real adapter 的 request path、request body、response projection 已用 mocked `fetch` 測試；接入 runtime 後仍需補一輪實機 smoke。

Contract test 必須使用 repository pin 的 `jsonschema==4.17.3`。目前全域環境的 `jsonschema 4.26.0` 對舊版 `RefResolver` 與 Draft 2020-12 external `$ref` 組合會失敗；這是測試環境相容性問題，不是 v0.1 schema 內容錯誤。依 requirements 安裝後，完整 contract suite 通過。

## Agent A can rely on

- Mock demo 不依賴 MI300、RAG 或 Speech model，可以先做前端／鍵盤／screen-reader review。
- Stage 01 的 `/lesson-images/*.svg` 已由 Vite `publicDir` 共用，沒有重複拷貝教材素材。
- Real adapter 不會偷偷把 unknown response 當 canonical Lesson／Session 使用。
- Student mock payload 沒有答案、信心或教師專用欄位；測試會檢查這項邊界。
- Real adapter 將 `/actions` 的控制操作與 `/turns` 的 transcript answer 分開送出，並只把安全 projection 傳給 Student view。

## Tests and results

- `npm run test`：通過，4 個 test files、8 個 tests。
- `npm run typecheck`：通過。
- `npm run build`：通過，Vite production bundle 成功產出。
- `npm run contracts:generate`：通過，輸出 `apps/web/src/generated/api.ts`，來源為 canonical Core OpenAPI。
- `python scripts/test_contracts.py`：使用 pinned `jsonschema 4.17.3` 通過，`7 schemas; 3 OpenAPI documents/45 responses; 18 schema fixtures; 10 student-safe fixtures`。
- Real adapter mapping tests：通過，涵蓋 control action、transcript answer 與 observer-only summary projection。
- Browser smoke：通過 `/setup` → `/capture` → `/session/demo-session/student` → `/session/demo-session/observer`；也驗證學生送出後進度更新、observer 摘要，以及 `?health=degraded` 狀態畫面。

Stage 02 的前端／契約整合已 ready for review；正式 runtime readiness 仍需 Core API handlers、Speech Gateway 與後續硬體整合，不能由本 branch 的 mocked fetch tests 代稱。

## Runtime / accessibility / measurements

- Runtime：Windows PowerShell、Node.js `v24.18.0`、npm `11.16.0`；前端依賴版本鎖在 `apps/web/package-lock.json`。
- Accessibility：瀏覽器 AX smoke 已確認主要 landmark、heading 層級、keyboard-visible buttons、`role=status`、`role=alert`、`aria-live` 與 progressbar；尚未接入 automated axe audit。
- Latency：目前只驗證 Mock UI state transition，沒有宣稱 backend／ASR latency；observer 顯示的 latency 是合成資料。RAM：未量測，因 canonical backend／硬體尚未接入。
- Known limits：Mock state 只存在 adapter instance 內，重新整理不保留 session；沒有真實 microphone、ASR、RAG 或 MI300 呼叫；Real adapter 尚未對接 runtime backend。

## Next action

下一步是將本 branch 推送供使用者 review；依 `agent.md` 規定，開 PR 前先通知使用者。使用者確認 diff 後再開 PR，並由使用者 review／merge。Core API runtime 完成後，另補 Real mode HTTP smoke 與實機 latency／fallback measurements。
