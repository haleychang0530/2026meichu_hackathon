# Stage 10 故障速查表

所有錯誤先在健康頁呈現，再給出可操作 fallback。fallback 不宣稱即時 MI300
分析，也不把 fixture 結果冒充 live model。

| 情境 | 健康／錯誤訊號 | 展示 fallback | 驗證方式 |
| --- | --- | --- | --- |
| 正常 mock／fixture | Core、RAG、Speech、Web ready；VLM 標示 fixture degraded | 使用核可 fixture lesson，照 Student → Observer 流程 | `Start-Demo.ps1 -Mode mock` + 50-cycle gate |
| MI300 離線／timeout | Core health 的 `vlm-mi300` 為 `degraded/offline`，保留 `VLM_OFFLINE` 或 timeout code | 使用 cached lesson／fixture，明說不是即時分析；可繼續既有 session | 在有可信任 MI300 位址的雙機環境以 `-Mode real` 執行；本機未宣稱 live 成功 |
| RAG 無可靠結果 | citation 缺失或 Core 回報 `rag-no-result` | 顯示 manual review，不能編造 citation；使用人工核准教材 | `fixtures/contracts/v0.1/errors/rag-no-result.error.json` |
| ASR 失敗 | Speech health／turn error 顯示 ASR failure | 改用鍵盤文字輸入或預錄 response | `fixtures/contracts/v0.1/student/asr-failure.json` |
| TTS 失敗 | TTS failure 或無法播放 | 使用 App 旁白、螢幕閱讀器或 `fixtures/device/audio` 預錄音檔 | `fixtures/contracts/v0.1/student/tts-failure.json` |
| Camera／Mic 被拒絕 | 健康頁 browser media 顯示 `degraded/offline` | 檔案上傳、鍵盤、預錄音訊；不重複請求權限 | 操作者在 `/health` 按檢查並自行選擇拒絕／允許 |
| 瀏覽器重整／模式切換 | 新頁標題接收 focus；同一 `demo-session` 可重新載入 | 回到 Student 或 Observer，不重建 session | 20 次 student／observer 路由切換 smoke |
| NPU 不可用 | CPU-only profile 明確顯示 NPU `disabled` | 由 CPU ASR/TTS 及鍵盤／預錄素材完成流程 | `Start-Demo.ps1 -SpeechProfile cpu`；不以 NPU 作 gate |
| 啟動器中的單一服務退出 | `/health` endpoint 為 offline，process report 可定位 role/PID | 執行 Stop → Start；展示期間改播備援錄影 | `Health-Demo.ps1` 與保留的 `.runtime/stage10-demo/logs` |

## 演練原則

1. 先讓操作者讀到狀態，再按 fallback；不要把錯誤藏在 console。
2. 不用真實學生影像、錄音、姓名或帳號做故障演練。
3. 每次演練結束保留 metadata 與錯誤碼即可；不要把原始 media 放入 report。
4. MI300 離線演練只改 `VLM_BASE_URL`／啟動設定，不修改前端或 schema。
