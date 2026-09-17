# 專案開發規定（Agent B local workflow）

這份檔案是本 repository 的協作規定，適用於 Agent B 與後續在本機進行的 Stage 開發。它不能覆蓋使用者最新指示、`overview.md`、已凍結的 API／JSON Schema 或系統安全規則。

## 開始工作前

1. 依序完整閱讀 `overview.md`、角色文件、目前 Stage、前一 Stage 交接與相關提案段落。
2. 先同步 `origin/main`，確認上一個 PR 已 merge，再從最新 `main` 開新分支。
3. 檢查 `git status`；既有未追蹤的研究資料、PDF、`tmp/` 或其他使用者檔案不得擅自加入 commit。
4. 確認 Agent A 的 canonical schema／OpenAPI 版本與檔案所有權；沒有契約時不得自行創造同名平行型別。

## 分支與 commit

- `main` 只接受已 review／merge 的內容，不直接開發、不 force-push。
- Agent B 分支格式：`codex/agentB_stageN`，例如 `codex/agentB_stage2`。
- 每個 Stage 從最新 `main` 開始；需要同步時使用可審查的 merge 或 rebase，保留使用者未提交檔案。
- commit 使用清楚的 Conventional Commit，例如 `feat(agent-b): add stage 2 mock frontend`。
- commit 前必須執行與 Stage 對應的 typecheck、test、build 或 smoke test，並確認 `git diff --check` 通過。
- 不提交 secrets、token、個資、原始學生錄音／照片、主機序號、PnP instance id 或未授權教材。

## 契約與責任邊界

- Agent B 只修改 Device／Speech／Frontend／Accessibility 所有範圍；不修改 Agent A 的 RAG、Teaching Agent、session 真相來源或 canonical schema。
- 前端只能透過 Core Backend 與 localhost Speech Gateway；不得直接呼叫 MI300。
- generated TypeScript types 必須由 Agent A 提供的 OpenAPI／JSON Schema 產生；契約變更要同步 schema、fixtures、契約測試與版本。
- Mock 與 Real adapter 必須共用同一個介面與錯誤 envelope；Mock 不得把答案、信心或教師欄位放入 student response。

## PR 規定

1. PR 前先通知使用者，列出分支、commit、base branch、變更摘要、測試結果與已知限制。
2. PR 一律以 `main` 為 base；標題與 body 要指出 Stage、契約版本、可重現指令與 fallback。
3. 沒有使用者 review／明確確認不得 merge、刪 branch 或改寫 `main` 歷史。
4. PR review 發現問題時，在同一 branch 補 commit並重新跑檢查；不要用 force-push 隱藏審查歷史。
5. merge 後重新 fetch `origin/main`，下一個 Stage 從 merge 後的 main 開始。

## 阻塞回報

若 Stage 依賴尚未交付的契約、硬體、模型或權限：

- 先完成不依賴阻塞項目的安全工作；
- 以「缺少什麼、由誰提供、造成哪個檢查點無法通過、已做哪些替代驗證」具體回報；
- 不用猜測的 schema、假 benchmark 或假成功狀態掩蓋阻塞；
- 可交付 `partial` 時，先交付可重現的部分與 unblock 指令，狀態標為 `partial`，而不是宣稱 `done`。

## Stage handoff

每個 Stage 必須留下：`Status`、Changed files、How to run、runtime versions、Tests and results、Latency/RAM measurements、Accessibility checks、Known limits、Agent A can rely on、Next action。瀏覽器或硬體測試若產生 media，預設只留 metadata，不保存原始內容。
