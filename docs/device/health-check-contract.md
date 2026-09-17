# Device health check contract

版本：`device-health.v1`

這份契約是 Agent A 與 Agent B 共用的「主機能力快照」格式。它描述裝置和資源，不取代 Core Backend 的 `/api/health` 或 Speech Gateway 的 `/local/health`。

## 必要欄位

| 欄位 | 意義 |
| --- | --- |
| `schema_version` | 快照版本；目前為 `device-health.v1`。 |
| `checked_at` | ISO 8601 本機量測時間。 |
| `os` | Windows 版本、build 與架構。 |
| `firmware` | BIOS 版本；不包含序號。 |
| `cpu` | 型號、核心數、thread 數與目前系統負載。 |
| `memory` | 實體總量、目前可用量、保留量與保留後可用上限。 |
| `storage` | `C:` 容量、可用量與運作下限。 |
| `gpu` | 顯示 GPU 與 driver；890M 僅供瀏覽器、Camera 與顯示。 |
| `npu` | PnP 狀態與 driver；只有偵測到裝置不代表 ASR runtime 已可推論。 |
| `camera` | 目前可見的 Camera 裝置名稱與狀態，不含 instance id。 |
| `audio` | 目前可見的音訊裝置名稱與狀態，不含錄音內容。 |
| `runtimes` | Node、npm、Python、PowerShell 與瀏覽器版本。 |
| `power` | 電源配置與電池快照。 |
| `checks` | 每個檢查的 `status: pass | fail | not_run | degraded` 與說明。 |

## 資源預算規則

```text
safe_reserve_gib = max(physical_ram_gib * 0.25, 6)
runtime_capacity_after_reserve_gib = physical_ram_gib - safe_reserve_gib
```

預算是上限而非保證的模型工作集：

- Windows、瀏覽器、Camera 與顯示先保留 `safe_reserve_gib`。
- Core Backend、SQLite、Local RAG 先以單 worker 和輕量 embedding 估算。
- ASR CPU 路徑與 TTS 不同時啟動；ASR 回到 CPU 時由 semaphore 序列化。
- 890M 不列入必要推論容量；MI300 推論不占用筆電 RAM／GPU 預算。
- SSD 運作下限先以 100 GiB 設定；低於下限時停止下載模型或建立新 RAG index。

## 健康判定

- `ready`：NPU、Camera、audio、RAM reserve、SSD floor 均通過；瀏覽器測試若未執行則另標 `browser_media: not_run`。
- `degraded`：裝置存在但 driver／runtime 或資源不足，仍可使用 CPU／檔案上傳等 fallback。
- `offline`：裝置不存在或系統回報錯誤。
- `not_run`：需要使用者在瀏覽器操作，尚未取得實測結果。

## 隱私界線

快照不得保存：電腦名稱、Windows 使用者、BIOS／硬體序號、PnP instance id、原始照片、原始錄音、完整學生語音或裝置 bytes。瀏覽器 smoke test 只上傳到本機檢查 server 的測試結果 metadata。
