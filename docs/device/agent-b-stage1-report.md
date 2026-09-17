# Agent B Stage 01：筆電環境、資源預算與裝置盤點

## 交接摘要

```text
Stage: Agent B Stage 01
Status: done
Checked: 2026-09-17 (Asia/Taipei)
Branch: codex/agentB_stage1
```

本 Stage 建立可重跑的 Windows 裝置盤點、RAM／CPU／磁碟預算、Camera／Mic／播放 smoke test、共用 health-check 欄位與不含個資的測試素材。這份報告是一次量測快照；會變動的 RAM free、CPU load、電池與磁碟數值應以重新執行腳本的結果為準。

## 實測裝置與軟體

| 項目 | 實測結果 | 證據／限制 |
| --- | --- | --- |
| OS | Windows 11 Home, build 26200, 64-bit, zh-TW | `Win32_OperatingSystem` |
| 筆電 | ASUS Vivobook S 16 M5606WA | `Win32_ComputerSystem` |
| BIOS | M5606WA.314 | 未記錄 BIOS serial |
| CPU | AMD Ryzen AI 9 HX 370 with Radeon 890M；12 cores / 24 logical processors | `Win32_Processor` |
| 實體 RAM | 31.12 GiB；本次快照可用 13.09 GiB | `Win32_ComputerSystem` + `Win32_OperatingSystem` |
| SSD | C: NTFS，952.16 GiB total，582.66 GiB free | 操作下限設為 100 GiB free |
| iGPU | AMD Radeon 890M；driver 32.0.21025.10016；3200×2000 @ 60 Hz | 保留給顯示、瀏覽器與 Camera，不列為必要推論裝置 |
| NPU | `NPU Compute Accelerator Device`，PnP `OK`；AMD driver 32.0.203.297 | 這是 Windows／driver 證據；尚未做實際 NPU workload benchmark |
| Camera | `USB2.0 FHD UVC WebCam`、`USB2.0 IR UVC WebCam`，均 `OK` | 另外的 DFU／Studio Effects 元件不列為實體 camera |
| 音訊 | Realtek、AMD High Definition Audio 與 Windows streaming endpoint 均 `OK` | Bluetooth／A2DP 裝置不納入預設規劃 |
| Node / npm | Node v24.18.0 / npm 11.16.0 | `device-health.json` 同步保存路徑與版本 |
| Python / PowerShell | Python 3.12.10 / PowerShell 7.6.5 | Python 來源為 WindowsApps shim；Python workload 尚未納入產品啟動器 |
| 瀏覽器 | Microsoft Edge 153.0.4234.32、Google Chrome 152.0.7977.84 已安裝 | browser smoke test 以 Codex Chromium localhost page 完成 |
| 電源 | 平衡；本次快照電池 85% | 壓測與 ASR baseline 應固定電源條件 |

完整去個資快照：[`runtime/device-health.json`](runtime/device-health.json)；可讀版：[`runtime/device-health.md`](runtime/device-health.md)。

## 資源預算

安全保留遵循共同規範：`max(physical RAM × 25%, 6 GiB)`。31.12 GiB RAM 的安全保留為 7.78 GiB，保留後 runtime capacity 為 23.34 GiB。

| 資源桶 | 規劃上限 | 執行策略 |
| --- | ---: | --- |
| Windows／瀏覽器／Camera／顯示保留 | 7.78 GiB | 不可被模型 worker 吃掉 |
| Core Backend + SQLite + Local RAG | 4.0 GiB | 單 worker、輕量 CPU embedding；需由 Agent A 實測修正 |
| Breeze-ASR CPU | 4.0 GiB | Stage 05 量測前的 cap；CPU 路徑必須可靠 |
| MMS-TTS CPU | 2.0 GiB | 預設 CPU；不與 CPU ASR 同時推論 |
| Frontend + Speech Gateway overhead | 1.5 GiB | 瀏覽器、Camera、音訊 buffer 與本機 gateway |
| 保留後未配置 headroom | 11.84 GiB | 用於模型載入峰值、檢查與異常波動 |

其他資源規則：890M 只支援顯示與瀏覽器；MI300 VLM 不占用筆電 GPU／RAM；C: free 低於 100 GiB 時暫停模型／RAG index 下載；ASR 回到 CPU 時使用 semaphore 序列化。

## Camera／Mic／播放實測

測試頁：`http://127.0.0.1:8765/`（只綁定 localhost）。本次結果保存於 [`runtime/browser-check-result.json`](runtime/browser-check-result.json)。

| 測試 | 結果 | 證據 |
| --- | --- | --- |
| Secure localhost context | pass | `secure_context=true` |
| Camera permission + stream | pass | 1280×720；瀏覽器頁面顯示串流成功 |
| Camera photo capture | pass | 1280×720；canvas 擷取後未保存 |
| Microphone permission + recording | pass | `audio/webm;codecs=opus`，29,290 bytes；只留在頁面記憶體 |
| Audio playback | pass | `synthetic-prompt.wav` 播放成功 |
| 教材圖載入 | pass | 三張 SVG 都在 browser accessibility tree 出現，且有中文 alt text |

頁面只把狀態、尺寸、錄音 blob 大小與 fixture 名稱 POST 回本機檢查 server；不傳送相片或錄音 bytes，也不永久保存 media。

## 測試素材

[`fixtures/device/manifest.json`](../../fixtures/device/manifest.json) 保存 SHA-256 與用途：

- `synthetic-prompt.wav`、`synthetic-response.wav`、`synthetic-fallback.wav`：確定性 PCM 播放／傳輸 fixture，不是 ASR 語意 goldens。
- `lesson-shapes.svg`、`lesson-market.svg`、`lesson-weather.svg`：無人物的幾何／水果攤／天氣教材圖，不含姓名、臉孔或可識別資料。

## 共用健康檢查欄位

`device-health.v1` 固定記錄 OS、firmware（不含 serial）、CPU、RAM、SSD、GPU、NPU PnP／driver、Camera、audio、runtime、power 與每項 check status。NPU 的 `pnp_status=OK` 不等於 runtime 可推論，故另保留 `runtime_status=not_benchmarked`，交由 Stage 06 做 Go／No-Go。

## How to run

```powershell
pwsh -NoProfile -File .\scripts\generate_device_fixtures.ps1
pwsh -NoProfile -File .\scripts\device_health_check.ps1
node .\scripts\serve_browser_device_check.mjs
```

執行瀏覽器頁面上的 Camera、拍照、Mic 錄音與播放按鈕後，再執行一次 `device_health_check.ps1`，即可把 browser metadata 納入 `browser_media` check。

## Agent A 可依賴

- 筆電可依據 7.78 GiB system reserve 與 23.34 GiB runtime capacity 做 Backend／RAG worker 上限規劃。
- NPU 可被 Windows PnP 偵測且 AMD driver 已安裝；MVP 仍必須以 CPU ASR 為可靠 fallback。
- 兩個實體 UVC camera、Realtek／AMD audio 與本機 localhost browser media path 已通過 smoke test。
- `device-health.v1`、三段合成音訊與三張教材圖可直接供 Stage 02／Stage 03 使用。

## Tests and results

- `pwsh -NoProfile -File scripts/generate_device_fixtures.ps1`：pass；manifest checksum 產生完成。
- `pwsh -NoProfile -File scripts/device_health_check.ps1`：pass；overall `ready`。
- `node scripts/serve_browser_device_check.mjs 8765`：pass；localhost server 可服務 HTML、WAV、SVG 與 metadata endpoint。
- Browser smoke test：pass；Camera 1280×720、拍照、Mic 29,290-byte recording、WAV playback、三張教材圖載入。
- `node --check scripts/serve_browser_device_check.mjs`：pass；Stage 交付不包含第三方套件。

## Accessibility checks

測試頁使用單一 `h1`、分區 `h2`、原生 `button`、`role=status`／`aria-live`、video／canvas／audio 的 label，以及三張教材圖的替代文字；沒有正數 `tabindex`。本次用瀏覽器 accessibility tree 驗證文字與控制項可見；Windows Narrator／NVDA 的完整人工巡覽留到 Agent B Stage 09。

## Known limits and next action

- CPU load、free RAM、battery 與 free SSD 是取樣值，不是壓測結論。
- NPU 只有 PnP／driver 證據；不得在 Stage 02 宣稱 ASR 已可走 NPU。
- 合成 WAV 只測試 transport／playback；Stage 05 需另建經人工審核的 ASR speech set。
- 本次瀏覽器實測是在 Codex Chromium localhost context；Edge／Chrome 的安裝版本已盤點，但若展示機改用原生瀏覽器，需在該瀏覽器重新確認 permission profile。
- 下一步：Agent B Stage 02 建立 React／Vite／TypeScript 骨架，沿用本報告的 health snapshot 與 fixtures；Agent A 提供 canonical schema／OpenAPI 後再生成 TypeScript types。
