# Agent B Stage 02：前端骨架、Generated Types 與 Mock

## 交接摘要

```text
Stage: Agent B Stage 02
Status: partial | blocked on Agent A Stage 01 contract
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

## Changed files

- `agent.md`、`.gitignore`。
- `apps/web/`：Vite entry、React pages/components、view models、Mock／Real adapters、error envelope、routing、styles、tests 與 npm lockfile。
- `scripts/generate_contract_types.mjs`：canonical contract 存在時的 generated-type 入口。
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

預設為 Mock mode。用 `?health=degraded`、`?health=offline` 或 `?health=recoverable_error` 可驗證健康狀態畫面；`VITE_DATA_MODE=real` 會進入 Real adapter，但在 canonical contract 產生前會清楚回報 `CONTRACT_NOT_GENERATED`。

## Blocker

`origin/main` 目前只有 Agent B Stage 01 的 merge；尚未有 Agent A Stage 01 的 `packages/contracts/openapi.yaml`／JSON Schema、generated fixtures 或 OpenAPI version。Stage 02 要求「從 Agent A contract 自動產生 types/client」，而共同規範禁止 Agent B 手寫同名平行型別。因此：

1. Mock UI、路由、狀態、無障礙與 adapter 邊界可以先驗證。
2. `npm run contracts:generate` 目前會以 exit code 2 明確停止，避免生成假型別。
3. Real adapter 只完成 transport／error boundary；收到成功 payload 時會拒絕未經 schema 的 cast。
4. Agent A 需要提供 versioned OpenAPI／JSON Schema、student／observer fixtures 與錯誤 envelope 後，才能完成 generated `api.ts`、real mapping 與正式契約測試。

## Agent A can rely on

- Mock demo 不依賴 MI300、RAG 或 Speech model，可以先做前端／鍵盤／screen-reader review。
- Stage 01 的 `/lesson-images/*.svg` 已由 Vite `publicDir` 共用，沒有重複拷貝教材素材。
- Real adapter 不會偷偷把 unknown response 當 canonical Lesson／Session 使用。
- Student mock payload 沒有答案、信心或教師專用欄位；測試會檢查這項邊界。

## Tests and results

- `npm run test`：通過，3 個 test files、5 個 tests。
- `npm run typecheck`：通過。
- `npm run build`：通過，Vite production bundle 成功產出。
- Browser smoke：通過 `/setup` → `/capture` → `/session/demo-session/student` → `/session/demo-session/observer`；也驗證學生送出後進度更新、observer 摘要，以及 `?health=degraded` 狀態畫面。
- `npm run contracts:generate`：預期阻塞，因 `packages/contracts/openapi.yaml` 尚不存在。

Stage 02 完成前仍需通過生成型別的契約測試。若 contract 尚未 merge，Stage 狀態維持 `partial`，不能宣稱 `done`。

## Runtime / accessibility / measurements

- Runtime：Windows PowerShell、Node.js `v24.18.0`、npm `11.16.0`；前端依賴版本鎖在 `apps/web/package-lock.json`。
- Accessibility：瀏覽器 AX smoke 已確認主要 landmark、heading 層級、keyboard-visible buttons、`role=status`、`role=alert`、`aria-live` 與 progressbar；尚未接入 automated axe audit。
- Latency：目前只驗證 Mock UI state transition，沒有宣稱 backend／ASR latency；observer 顯示的 latency 是合成資料。RAM：未量測，因 canonical backend／硬體尚未接入。
- Known limits：Real adapter route 與 mapping 仍需 Agent A contract；Mock state 只存在 adapter instance 內，重新整理不保留 session；沒有真實 microphone、ASR、RAG 或 MI300 呼叫。

## Next action

Agent A merge canonical contract 後，在 `apps/web` 執行 `npm run contracts:generate`，再補 real adapter mapping、OpenAPI error fixtures 與契約測試；完成後重新跑整套 build／Mock flow，再通知使用者準備 PR。
