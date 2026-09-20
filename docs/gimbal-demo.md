# 雲台拍照 demo

此功能只在「相機預覽 → 使用者拍照」之間運作。瀏覽器是 webcam 的唯一擁有者；它每次送一張縮小的預覽影格到本機 Core API。Core 用 YOLO11n 的 `book` 類別偵測課本；若沒有結果，會嘗試紙張四邊形輪廓。Core 每次只送一個小角度 `STEP` 給 ESP32，等待 `ACK`，再看下一張影格。只有最後使用者確認的照片會進入現有教材分析流程。

## 準備

1. 將 [esp32-gimbal-model.ino](../firmware/esp32-gimbal-model/esp32-gimbal-model.ino) 用 Arduino IDE 上傳至 ESP32。先前的 signal-test 韌體收到 STEP 只做一次四方向動作，無法跟隨模型結果。需要安裝 `ESP32Servo` 函式庫。GPIO25 接 Z 軸左右轉動 servo 的訊號，GPIO26 接仰角 servo 的訊號。Servo 應使用獨立的合適電源，並與 ESP32 共地。
2. 韌體開機會先寫入邏輯 Z 軸 0°、仰角 25°。請讓機構在此位置附近可安全活動。Z 軸邏輯限位 −180°～180°，仰角 0°～50°；不同 servo 的實際物理行程要依型號確認。Demo 的閉環只會在每次 PING 的起點附近移動 Z 軸最多 ±24°、仰角最多 ±5°；Z 軸每步最多 8°，仰角每步最多 2°。Z 軸步幅沿用已測通的四方向動作幅度，以減少 SG90 小步進時不轉動的情況。
3. 在 Core API 的 Python 環境安裝可選依賴：
   ```powershell
   cd apps/core-api
   .\.venv\Scripts\python.exe -m pip install --only-binary=:all: -r requirements-gimbal.txt
   ```
4. 首次使用前先在有網路的環境載入 `yolo11n.pt`，讓模型權重下載至 Core 的工作目錄；之後 demo 可離線使用：
   ```powershell
   .\.venv\Scripts\python.exe -c "from ultralytics import YOLO; YOLO('yolo11n.pt')"
   ```
5. 接上 ESP32，確認 Windows 裝置管理員中的 COM 埠。啟動 Core：
   ```powershell
   $env:CORE_PROFILE = 'demo'
   $env:GIMBAL_PORT = 'COM5' # 改成實際 COM 埠
   $env:GIMBAL_MODEL_PATH = 'yolo11n.pt'
   .\.venv\Scripts\python.exe -m uvicorn core_api.app:app --host 127.0.0.1 --port 8000
   ```
6. 另一個終端機啟動網頁：
   ```powershell
   cd apps/web
   $env:VITE_CORE_API_BASE_URL = 'http://127.0.0.1:8000'
   $env:VITE_DATA_MODE = 'real'
   npm run dev
   ```

## 操作與除錯

在 `/capture` 按「開始預覽」→「自動尋找紙張／課本」。Core 先送 `PING`，接著送一次 `TEST`，ESP 會上下左右各小幅移動並返回起點。隨後網頁依序送預覽影格；畫面顯示模型或輪廓來源、頁面框與 ESP 回報的角度。出現「頁面位置已穩定」後，按「拍照」。找不到頁面、達到小範圍邊界或本機服務失敗時，仍可手動拍照。

序列協定為每行一筆 ASCII 命令：`PING <seq>`、`TEST <seq>`、`STEP <seq> <pan_delta> <tilt_delta>`、`STOP <seq>`。成功回覆 `ACK <seq> <pan> <tilt>`，錯誤回覆 `ERR <seq> <reason>`。使用 Serial Monitor 手動測試時，先停止 Core，避免兩個程式同時占用 COM 埠；Serial Monitor 設為 115200 baud、換行結尾。

Core 的四個本機路由：`POST /api/gimbal/start`、`/observe`（multipart `image`）、`/test`、`/stop`。影格不寫入磁碟，不送到 MI300。若 `GIMBAL_PORT` 未設定或模型/Serial 無法啟動，路由回 `GIMBAL_UNAVAILABLE`，拍照頁顯示錯誤後允許手動拍照。

## 已知限制

- 預訓練 `book` 類別不保證辨識單張紙。四邊形輪廓只是受控展示場景的備援；若 demo 有固定紙張/背景，先用實景測試，必要時把同一個 nano 模型微調為「頁面」類別。
- ESP 的 `ACK` 只確認指令和目標角度，並不提供角度感測器回饋。鏡頭是否真的往紙張移動，由下一張影格判斷；若初始畫面完全看不到紙，有限搜索後會請使用者先手動將紙移近。
- ESP32 韌體和實際舵機尚需上板驗證。若 Z 軸或仰角動作與影像相反，控制器會在下一張影格誤差變大時反轉該軸的後續指令。

## Stage 12 handoff

- **Status:** software demo implementation complete; physical validation pending.
- **Changed files:** `apps/web/src/capture/CameraCapture.tsx`, `apps/web/src/capture/gimbalClient.ts`, `apps/core-api/core_api/gimbal.py`, Core routes/config/error code, Core OpenAPI and generated TypeScript, ESP32 firmware, setup documentation, tests.
- **How to run:** follow the preparation and operation steps above.
- **Runtime versions:** development checks used Python 3.12 and the repository's Node/Vite 8.3 toolchain. Target runtime is the user's PN54; actual environment versions must be recorded during on-device testing.
- **Tests and results:** web Vitest 40/40, TypeScript typecheck and production build passed. Six isolated Python controller/Serial tests passed using fake camera detections and fake Serial replies. Python syntax compilation, contract JSON parsing, and `git diff --check` passed. Full Core API test suite could not run in this workspace because the Python dependencies were absent and package installation did not complete. Arduino compilation and hardware movement have not run here.
- **Latency/RAM measurements:** not measured on PN54. Cold model load, per-frame inference, Serial acknowledgement, and full alignment time should be measured during the hardware walkthrough.
- **Accessibility checks:** buttons use native keyboard operation; progress/error text uses `role=status` and `aria-live`; the visual page box is decorative and hidden from assistive technology. No screen-reader walkthrough has been performed.
- **Known limits:** pretrained `book` detection and contour fallback are not validated on the actual demo paper/background; the servo's physical travel and direction are not validated; this is a single-user demo controller with one COM owner.
- **Agent A can rely on:** the four additive `/api/gimbal/*` routes and `GIMBAL_UNAVAILABLE` error are documented in the Core OpenAPI contract. They do not change the lesson/session data path. Agent A should review the additive contract because the Core canonical contract is Agent A-owned.
- **Next action:** install the optional model/Serial dependencies on PN54, flash the firmware, set `GIMBAL_PORT`, and run an end-to-end capture with a real page. Record inference latency, first-move direction, servo travel, and final photo quality.
