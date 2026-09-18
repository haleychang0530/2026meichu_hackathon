# Stage 10 三套展示彩排腳本

這三套腳本共用同一個 `/health` release gate。正常、降級與 MI300 離線都要有
清楚的口頭話術；只有通過健康頁與 fallback 檢查後才開始展示。

## A. 正常／fixture 彩排

```text
1. 執行 Start-Demo.ps1 -Mode mock -SpeechProfile mock。
2. 在 /health 確認 Core、RAG、ASR、TTS 與前端就緒；說明 VLM 是 fixture。
3. 進入 /capture，選核可的無個資教材 fixture。
4. 建立 demo-session，進 Student 播放題目、開始回答、完成一個回合。
5. 切到 Observer，確認教材、citation、turn、熟悉度與 health metadata。
6. 回到 Student，再切回 Observer；確認頁面標題 focus 與 session id 不變。
```

預期話術：「目前展示使用筆電 CPU 與本機 fixture；MI300 欄位如需即時分析會
由 Core Backend 顯示明確狀態，不會由瀏覽器直連。」

## B. 一般降級彩排

```text
1. 先完成 A 的啟動與 health 檢查。
2. 開啟 /setup?health=degraded，或在真實環境停止一個可替換的 Speech worker。
3. 回到 /health，確認降級 banner、服務名稱與 fallback 話術可讀。
4. 以鍵盤完成 Student 回合；TTS 失敗時播放核可預錄音檔或使用 App 旁白。
5. 切回 Observer，確認錯誤碼／retryable metadata 沒有洩漏原始錄音。
6. 回復服務後重新檢查 health，再繼續展示，不手動修改程式。
```

預期話術：「語音服務暫時不可用，教材與 session 還在筆電；現在改用鍵盤／
預錄素材完成同一個教學目標。」

## C. MI300 離線彩排

```text
1. 使用當天可信任的 real profile 設定啟動；不要在前端填 MI300 位址。
2. 在雙機環境暫停或隔離 MI300，再從 /health 確認 vlm-mi300 為 offline/degraded。
3. 對教材分析選擇 cached lesson／fixture fallback，讓畫面標示 manual review。
4. 不宣稱即時 VLM 結果；繼續展示已核准 lesson、Student 回合與 Observer 摘要。
5. MI300 恢復後重新檢查 health；若未恢復，以備援錄影結束展示。
```

預期話術：「外部無狀態 VLM 目前離線；筆電仍持有 lesson、RAG、session 與
語音 fallback，因此展示不會遺失進度。」

## 備援素材包

- 教材圖：`fixtures/device/lesson-images/lesson-market.svg`。
- 預錄音訊：`fixtures/device/audio/synthetic-prompt.wav`、
  `synthetic-response.wav`、`synthetic-fallback.wav`。
- 成功／部分成功／錯誤 contract fixtures：
  `fixtures/contracts/v0.1/{observer,student,errors}`。
- 若整機展示被阻斷，保留可操作的 fixture web demo 與不含學生個資的錄影；
  不在現場臨時下載模型或更換 schema。

本次工作站已完成 A 的 mock 彩排與三項 release gate；B 的 UI 降級路徑可由
`?health=degraded` 重現，C 的 live MI300 斷線需在指定雙機環境依上述腳本執行。
