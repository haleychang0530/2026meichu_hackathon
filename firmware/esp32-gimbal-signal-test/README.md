# 網頁 → ESP32 訊號測試韌體

這份韌體只驗證通訊與兩顆 servo。它與正式
[閉環韌體](../esp32-gimbal/esp32-gimbal.ino) 分開放置，避免 Arduino IDE
把兩份 `setup()`／`loop()` 一起編譯。

- GPIO25：Z 軸左右 servo 訊號。
- GPIO26：鏡頭平台上下仰角 servo 訊號。
- 舵機請用合適的獨立電源，並讓電源 GND 與 ESP32 GND 共地。

以 Arduino IDE 安裝 ESP32 板卡與 `ESP32Servo` 函式庫，再開啟
[esp32-gimbal-signal-test.ino](esp32-gimbal-signal-test.ino) 燒錄。
韌體初始位置是 Z 軸 0°、仰角 25°；測試時左右各 8°、上下各 5°，
每個方向短暫停留後回原位。這些是邏輯角度，實際方向取決於安裝方式。

本機 Core API 只需安裝原本的 `requirements.txt` 與 `pyserial`，
這次訊號測試**不需視覺模型**。在 `apps/core-api` 啟動：

```powershell
python -m pip install -r requirements.txt pyserial
$env:CORE_PROFILE = 'demo'
$env:GIMBAL_PORT = 'COM5' # 改為實際 COM 埠
python -m uvicorn core_api.app:app --host 127.0.0.1 --port 8000
```

在網站 `/capture` 按「開始預覽」→「自動尋找紙張／課本」。
網頁會要求 Core 送出 `PING <seq>` 和 `TEST <seq>`。
收到 `TEST` 時韌體才會四方向移動一次，最後回覆
`ACK <seq> 0 25`；網頁應顯示 `ESP ACK #...`。
韌體也接受第一筆 `STEP` 作同樣的一次性測試。再次 `PING` 才會
重新武裝，不會因連續 `STEP` 反覆移動。

若未安裝視覺模型，四方向動作後網頁可能顯示模型載入失敗；這不影響
本次「網頁 → Core → Serial → ESP32」測試。Serial Monitor 和 Core
不能同時占用 COM 埠。要用 Serial Monitor 單獨檢查時，先關閉 Core，
設定 115200 baud 與換行結尾，依序傳 `PING 1`、`TEST 2`。
