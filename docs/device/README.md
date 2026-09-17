# Agent B Stage 01：筆電裝置盤點

本目錄保存 Agent B Stage 01 的裝置盤點、資源預算與瀏覽器 media 健康檢查結果。

## 可重跑的檢查

在 repository 根目錄執行：

```powershell
pwsh -NoProfile -File .\scripts\device_health_check.ps1
pwsh -NoProfile -File .\scripts\generate_device_fixtures.ps1
```

`device_health_check.ps1` 只輸出必要的裝置能力與版本，不寫入電腦名稱、Windows 使用者、BIOS 序號、PnP instance id 或任何 camera／microphone bytes。輸出會放在 `docs/device/runtime/`；該目錄內的檔案可作為一次量測快照。

瀏覽器 camera、microphone、拍照、錄音與播放測試使用本機頁面：

```powershell
node .\scripts\serve_browser_device_check.mjs
```

接著在目標瀏覽器開啟 `http://127.0.0.1:8765/`，依頁面順序執行測試。頁面會將只有測試 metadata 的結果寫到 `docs/device/runtime/browser-check-result.json`；影像與錄音只留在瀏覽器記憶體，停止測試後不保存。

## 產物

- `agent-b-stage1-report.md`：一次盤點的可讀報告與資源預算。
- `runtime/device-health.json`：去個資後的結構化健康檢查快照。
- `runtime/browser-check-result.json`：瀏覽器 media smoke test 的 metadata（完成瀏覽器測試後才會出現）。
- `health-check-contract.md`：供 Agent A／Agent B 共用的欄位、狀態與量測方法。

測試素材的 checksum 與用途見 [`fixtures/device/manifest.json`](../../fixtures/device/manifest.json)。素材是合成音訊與幾何圖形，不含姓名、臉孔或可識別個資。
