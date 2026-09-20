# Stage 10 Release 操作手冊

這份手冊給展示人員使用。所有產品入口仍在 Ryzen AI 9 筆電；瀏覽器只連
Core API 與本機 Speech Gateway，不能直接連 MI300。啟動器會把 demo runtime
放在 `apps/core-api/.runtime/stage10-demo`，該目錄已被 Git 忽略。

## 啟動前

- Windows PowerShell 7、Node.js、Core API `.venv` 與 `npm install` 已完成。
- 真實 CPU ASR/TTS 模式只使用本機已準備的模型檔；現場不得下載模型。
- MI300 位於 Manta project `qwen3-coder-fp8-bench`。需要 shell 時開啟該
  project 的 Terminal Console；需要 API 時使用 gateway `8100/tcp` 的 forwarding。
- 2026-09-19 觀察到 gateway forwarding 為 `http://210.61.209.139:46944`
  （vLLM `8000/tcp` 的 forwarding 為 `45503`，Core 不直接呼叫它）。Manta
  外部 port 是動態配置；forwarding 重建後先到 **Settings → Port Forwarding**
  取得新值。URL 只傳給 Core，不得寫入 `VITE_*` 或前端程式。
- 若模型尚未準備，先在有網路的維運環境執行
  `pwsh -File .\scripts\release\Provision-SpeechModels.ps1 -Model all`，並確認
  `services\speech-local\.venv` 已安裝 `requirements.txt`。
- 若要使用 MI300，先取得當天可信任的內網 forwarding URL，不要把 URL 寫進前端或提交到 Git。
- 第一次展示先以 mock profile 完成暖機，再視現場狀況切換 real profile。

## 一鍵啟動

在 repository root 執行：

```powershell
pwsh -File .\scripts\release\Start-Demo.ps1 -Mode mock -SpeechProfile mock
```

啟動器會依序建立 RAG index、啟動 Speech Gateway、Core API、Vite 前端，呼叫
ASR/TTS warmup，最後開啟 `http://127.0.0.1:5173/health`。mock frontend 會
明確標示「Mock adapter」，不把模擬狀態冒充 live MI300；同時可在產生的
`health.json` 看到 Core `/api/health` 的 `vlm-mi300: degraded / fixture`。

Ubuntu 24.04 可直接使用原生 Bash 啟動器，不需 PowerShell：

```bash
scripts/release/setup-linux.sh
scripts/release/start-demo-linux.sh --mode mock --speech-profile mock
```

停止服務使用 `scripts/release/stop-demo-linux.sh`。真實 CPU 語音環境依序執行
`scripts/release/setup-linux.sh --with-cpu-speech` 與
`scripts/release/provision-speech-models-linux.sh`，再以 `--speech-profile cpu` 啟動。
Linux runtime、logs、RAG index、模型 cache 與可攜式 Node toolchain 都位於 Git
忽略目錄。Linux process state 會記錄 kernel boot ID；若電腦斷電或重新啟動，
啟動器會忽略舊 PID，停止器也不會對新 boot 中碰巧重複使用的 PID 發送 signal。

CPU-only profile（不啟用 NPU）如下：

```powershell
pwsh -File .\scripts\release\Start-Demo.ps1 -Mode mock -SpeechProfile cpu
```

真實 Core／MI300 profile 使用當天的可信任位址：

```powershell
pwsh -File .\scripts\release\Start-Demo.ps1 `
  -Mode real -SpeechProfile cpu `
  -Mi300BaseUrl 'http://210.61.209.139:46944'
```

`Start-Demo.ps1` 會自動尋找固定 revision 的 Hugging Face snapshot；也可明確
指定 `-AsrModelPath` 與 `-TtsModelPath`。若任一模型或 Torch/Transformers runtime
缺少，啟動器會在啟動服務前停止並指出 provisioning 指令，不再讓健康頁顯示
難以診斷的 `worker failed`。

`-Mode real` 仍讓 Core API、RAG、SQLite、session、Speech 與前端留在筆電；只有
Core Backend 的內部 VLM client 會使用 `Mi300BaseUrl`。不要把該位址設定成
`VITE_*`，也不要從瀏覽器直接呼叫 MI300。real mode 現在會拒絕缺少、含
credentials 或含 endpoint path 的 `Mi300BaseUrl`，避免誤用過期 localhost
預設值或把 `/internal/health` 重複接到 request path。

啟動前可先做不保存 payload 的 gateway probe：

```powershell
pwsh -File .\scripts\release\Test-Mi300Forwarding.ps1 `
  -BaseUrl 'http://210.61.209.139:46944'
```

它呼叫 `GET /internal/health`；若要測試圖片推論，可另傳 synthetic
`-ImagePath`，腳本會呼叫 `POST /internal/vlm/generate`，但不輸出圖片、prompt
或 raw model output。

## 健康頁與展示入口

開啟 `/health` 後依序確認：

1. Core Backend、Local RAG、ASR、TTS 顯示 `就緒` 或明確的降級狀態。
2. CPU-only note 顯示 NPU `disabled／未啟用`。
3. 按「檢查相機與麥克風」才會請求瀏覽器權限；測試 stream 立即停止，
   不保存影像、錄音或 transcript。若現場拒絕權限，改用檔案、鍵盤或預錄素材。
4. 從健康頁進入 `/capture`、`/session/demo-session/student`，再切到
   `/session/demo-session/observer`。observer 只顯示教師／家長資訊，學生頁
   不顯示答案、信心或 teacher controls。

非開發者的五分鐘流程：

```text
啟動 Start-Demo → 看 /health → Capture 教材 → 確認 Lesson
→ Student 播放／回答 → Observer 查看回合與健康 → 必要時使用 fallback 話術
```

## 壓測與資源報告

啟動器完成後，用 Core venv 執行 50 回合 privacy-safe loop：

```powershell
& .\apps\core-api\.venv\Scripts\python.exe `
  .\scripts\stage10_release_gate.py `
  --speech-profile mock --rounds 50 --progress 10 `
  --output .\apps\core-api\.runtime\stage10-demo\release-gate.json
```

此 gate 產生的 WAV、transcript 與 lesson image 都在記憶體中，不開啟麥克風，
不寫入學生資料。`Health-Demo.ps1` 會記錄 endpoint latency、服務 process 的
working set／CPU seconds、系統 RAM、C: 磁碟與 Windows thermal zone；韌體不提供
溫度時標示 `not_available`，不會虛構數值。

```powershell
pwsh -File .\scripts\release\Health-Demo.ps1 `
  -OutputPath .\apps\core-api\.runtime\stage10-demo\health.json
```

## 停止與重設

停止只會依啟動器記錄的 PID 及其子程序停止服務，保留 logs 與 reports：

```powershell
pwsh -File .\scripts\release\Stop-Demo.ps1
```

要清除 demo SQLite、RAG index 與 audio cache 時：

```powershell
pwsh -File .\scripts\release\Reset-Demo.ps1
```

`Reset-Demo.ps1` 不會刪除 repository 其他資料，也不會刪除 logs、健康報告或
本手冊。若 process state 不存在，Stop 不會碰其他程序。

## 已知限制

- 目前 repository 的 canonical contract 仍是 v0.1.0；v1.0 freeze 要由 Agent A
  完成後再做正式雙機驗收。
- 本機可重現的 gate 使用 mock Speech 與 fixture Core；完整真實 Breeze/MMS
  冷啟動與 live MI300 延遲，需在指定雙機與已準備模型上另行執行。
- Camera/Mic 權限是操作者決定的瀏覽器狀態，PowerShell 不會代替操作者授權。
- NPU 不是 Stage 10 release gate；CPU-only profile 的 NPU `disabled` 是預期狀態。
