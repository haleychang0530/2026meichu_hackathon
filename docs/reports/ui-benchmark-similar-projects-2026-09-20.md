# hear tAIgi 相近產品 UI 研究報告

日期：2026-09-20  
研究對象：目前 branch `codex/accessibility-demo-fix` 的 real-mode web app  
研究角度：視障／低視力、聽說學習、教材影像輸入、學生／教師雙角色

## 1. 結論先行

hear tAIgi 不是一般的語言學習 App，而是「一頁教材影像 → 可聽、可說的台語課程 → 教師／家長觀察」的 local-first learning tool。UI 的核心不應是堆疊更多 AI 功能，而是讓使用者在每一個階段只需要回答一個清楚的問題：

1. 這張教材要不要使用？
2. 現在要聽、跟讀、回答，還是取得提示？
3. 教師／家長需要介入哪一個狀態？

相近產品反覆出現的共同模式是：

- 把閱讀內容從複雜頁面中抽離，提供獨立的閱讀／朗讀工作區。
- 把音訊控制做成持續存在、可恢復的主操作，而不是藏在設定裡。
- 語音辨識失敗時，提供同等重要的鍵盤或文字路徑。
- 把「拍攝、辨識、確認」拆成清楚的階段，先讓人確認 AI 結果，再建立學習 session。
- 學生介面保持低資訊量；教師介面才顯示證據、信心、延遲、fallback 與歷程。
- 無障礙偏好要能被記住，但不能用第二套自動旁白和系統螢幕閱讀器互相搶話。

## 2. 本專案目前的產品形狀

目前程式已具備很好的產品骨架：

| 使用者 | 目前流程 | 已有 UI 基礎 |
|---|---|---|
| 首次使用者／視障使用者 | 選擇系統螢幕閱讀器或 App 旁白 | 首次選擇 dialog、focus trap、skip link、live status |
| 學生 | 看／聽教材、播放提示、語音回答、鍵盤回答、下一步 | phase-based student flow、語音與鍵盤 fallback、學生安全 projection |
| 教師／家長 | 檢視教材、citation、turn、健康狀態與控制 | observer projection、教材審查、危險操作確認 |
| 操作者 | 拍照或上傳教材、檢查品質、送出分析 | camera/upload fallback、圖片品質檢查、分析狀態與錯誤恢復 |

對應程式位置：

- 首頁與三步驟說明：`apps/web/src/pages/SetupPage.tsx`
- 拍攝／上傳／分析：`apps/web/src/pages/CapturePage.tsx`、`apps/web/src/capture/CameraCapture.tsx`
- 學生階段與回答：`apps/web/src/pages/StudentPage.tsx`
- 教師／家長觀察：`apps/web/src/pages/ObserverPage.tsx`
- 螢幕閱讀器／App 旁白選擇：`apps/web/src/components/AppShell.tsx`

因此，本次研究不是要把它改造成 Duolingo，而是要把現有的「教材處理器 + 有聲課程 + observer」變得更接近成熟的 accessible reading workflow。

## 3. 類似產品比較

### 3.1 Microsoft Immersive Reader：內容抽離與閱讀偏好

[Immersive Reader 官方總覽](https://learn.microsoft.com/en-us/azure/ai-services/immersive-reader/overview) 將內容放進獨立、低干擾的閱讀工作區，提供朗讀、圖片字典、詞性標示與翻譯。其 SDK 也公開文字大小、字型、文字間距、主題與朗讀速度等設定，並支援保存偏好（[偏好設定文件](https://learn.microsoft.com/en-us/azure/ai-services/immersive-reader/how-to-store-user-preferences)）。

值得借鑑：

- 學習內容應有一個「閱讀／聆聽 focus mode」，不要讓健康 metadata、模型 revision、教師工具和學生課文同時競爭注意力。
- 文字大小、行距、字距、背景與語速應是使用者可調整的 reading preferences。
- 圖片詞典、詞彙解釋與翻譯應以「目前詞／目前句」為單位漸進展開。

不要直接照抄：

- Immersive Reader 是長文閱讀器；hear tAIgi 還有拍攝、回答與 session 狀態，不能把所有流程塞進一個閱讀器 modal。
- 圖像或顏色標示只能是輔助，不能取代螢幕閱讀器可讀的文字結構。

### 3.2 Google Read Along：一個活動、一個回饋循環

[Read Along web 介紹](https://blog.google/products-and-platforms/products/education/read-along-web/) 以閱讀 buddy Diya 在學生朗讀時給予即時回饋；學生遇到困難時可以點選取得單字或句子協助。Google 也描述了離線運作、裝置端語音處理、家長多 profile 與閱讀進度追蹤。較新的 [Read Along in Classroom 介紹](https://blog.google/products-and-platforms/products/education/classroom-ai-features/) 顯示，教師可以區分朗讀、默讀、聆聽等模式，並看理解、速度與進度資料。

值得借鑑：

- Student page 只突出一個當下任務：播放／跟讀／回答／下一步，不要同時把所有 AI 能力變成同等權重的按鈕。
- 回饋應該短、正向、可再次嘗試；錯誤訊息不要把學生推回整個流程。
- 語音模式、鍵盤模式、聆聽模式是平行入口，不是「視障者只能使用的特殊模式」。
- Observer 應看「進度、正確性、需要提示的概念、最近一次狀態」，而非把所有 raw turn 資料平鋪在首屏。

不要直接照抄：

- 星星、徽章和遊戲化可作為低優先鼓勵，但不應讓台語發音、教材理解或視障使用者被迫依賴視覺獎勵。
- 即時語音 feedback 必須允許關閉、重播和改用文字，避免在螢幕閱讀器已朗讀時造成聲音衝突。

### 3.3 Microsoft Seeing AI：拍攝前指引、結果分層

[Seeing AI 官方介紹](https://blogs.microsoft.com/accessibility/seeing-ai-app-launches-on-android-including-new-and-updated-features-and-new-languages/) 將功能拆成 Short Text、Documents、Products、Scenes、People 等 channel。Documents channel 在拍攝印刷頁面時提供 audio guidance，拍攝後讀取內容；使用者還可以要求文件摘要或針對文件提問。

值得借鑑：

- `/capture` 應明確分成「拍攝前的聽覺／文字指引」「影像已取得」「教材分析結果」三個狀態。
- 拍攝前先告訴使用者：教材是否完整入鏡、是否需要移動裝置、何時可以按拍照；不要等到送出後才顯示錯誤。
- AI 結果分成摘要、可核對的教材文字、需要人工確認的欄位；不要用一大段生成文字包住所有結果。
- 可提供「再讀一次」「從目前句開始」「問這頁教材」等結果後操作，但必須有清楚的目前上下文。

不要直接照抄：

- Seeing AI 是通用視覺輔助工具；hear tAIgi 的成功條件是教材內容正確、語言發音適合課程，而不是描述越多越好。
- 不應讓 VLM 生成的說明直接變成學生答案或教師判定；目前專案的 student-safe／observer boundary 應維持。

### 3.4 Bookshare Reader／Dolphin EasyReader：可恢復的閱讀播放列

[Bookshare Reader](https://www.bookshare.org/bookshare-reader) 提供文字與朗讀、karaoke-style highlighting、速度、字型、顏色、背景、書籤與上次閱讀位置；[Bookshare／EasyReader 操作指南](https://www.bookshare.org/wp-content/uploads/2024/02/bookshare_and_easyreader_instructions.pdf) 也把播放、倒退 15 秒、前進 15 秒、timer、章節與書籤列為主要導航。

值得借鑑：

- Student page 應有穩定的 audio bar：播放／暫停、重播目前句、前後跳轉、語速與目前位置。
- 課程重新整理或中斷後，應顯示「繼續上次活動」而不是讓學生重新猜目前 phase。
- 句子或詞語同步標示可幫助低視力與讀寫困難者，但必須提供純文字與螢幕閱讀器可讀的目前句資訊。
- 書籤／收藏在本專案可轉成「標記這個詞彙／需要再練習」並同步到 observer。

不要直接照抄：

- 書籍閱讀器的底部播放列適合長內容；短課程可以保留簡潔，但播放狀態不能只藏在一個「聽完整課文」按鈕的瞬間回饋裡。

### 3.5 Learning Ally：同步音訊、詞彙與教師觀察

[Learning Ally Audiobook Solution](https://learningally.org/app/) 以 word-by-word highlighting、可調整文字／顏色、詞彙、書籤與筆記連結學生與教師；學生使用狀態也能同步到 educator portal。它的設計重點不是把障礙者放到另一套內容，而是讓學生接觸同等級課程內容。

值得借鑑：

- 台語漢字、臺羅、中文義、音檔 key 應形成一個可切換但互相對齊的 vocabulary unit。
- Observer 看到的不是只有「答對／答錯」，還要能看到學生在哪個詞、哪個 phase、哪種 fallback 卡住。
- 筆記／標記在 hear tAIgi 可簡化為「教師標記需複習概念」與「學生重播此句」。

不要直接照抄：

- Learning Ally 依賴較大型的內容庫；hear tAIgi 目前應先做好單頁教材的品質、語音與恢復，再擴充 library。

## 4. 從比較提煉出的 UI 原則

### A. 入口：先選使用方式，不要讓使用者先猜 UI

首次設定保留兩個清楚選項：

1. 使用系統螢幕閱讀器（推薦）
2. 使用內建網頁旁白（沒有系統螢幕閱讀器時的備援）

選定後應記住偏好，但每個 route 不要再次彈出設定。系統螢幕閱讀器模式不應再播放一套重複 UI 旁白；App narrator 則只朗讀頁面標題、focus label、狀態與操作結果。

### B. Capture：三階段、每階段一個主 CTA

建議保持現有 01／02／03，但把資訊架構收斂成：

1. **取得教材**：開始預覽／上傳現有教材。
2. **檢查教材**：完整入鏡、文字清楚、方向正確、是否需要裁切。
3. **確認建立課程**：顯示教材標題、語言、AI 分析狀態、可疑欄位與「重新拍攝／確認教材並開始」。

在視障流程中，每一步都要有可聽的狀態文字與可重播指引；相機權限被拒絕時，檔案上傳與鍵盤路徑必須留在同一個操作群組內。

### C. Student：把「課程狀態」和「操作按鈕」分開

推薦的 student card 順序：

1. 目前階段與一句 prompt。
2. 目前可播放的音訊狀態。
3. 唯一主操作：回答／繼續回答。
4. 次要操作：重播、鍵盤回答、提示、下一步。
5. 回饋與可重試選項。

每次狀態改變都要回答「發生什麼、現在可以做什麼、下一步是什麼」。`role=status` 可以承接狀態，但不要讓每一次 websocket 更新都打斷使用者正在聽的內容。

### D. Observer：從 raw dashboard 改成決策 dashboard

Observer 首屏只需要：

- session／lesson 目前狀態
- 學生目前 phase 與進度
- 最近一回合的結果與需要介入的原因
- 一個主要「回到學生模式」入口

其餘 citation、VLM/RAG revision、latency、fallback、turn history 放在可展開區塊。危險操作仍需明確確認，並在完成後用 status message 告訴教師結果。

### E. 語言：把漢字、臺羅、中文義和音訊當成同一個語言單位

每個可朗讀語言片段建議有明確的語言 metadata：

- 台語內容：`nan-TW`
- 中文 UI／說明：`zh-Hant-TW`
- 臺羅讀音：以可讀文字提供，不只放在圖片或音檔 key

這會直接影響系統螢幕閱讀器選 voice、App narrator 的語音切換、以及教師看見的可核對內容。

### F. 視覺：保留溫暖品牌，但把「可讀」優先於「可愛」

目前暖色視覺適合兒童與親子情境；下一步應建立少量 design tokens：背景、主要文字、focus ring、主 CTA、次 CTA、警告、錯誤、成功、live status。每個狀態同時使用文字與結構，不只使用顏色。

建議固定：

- 主要 CTA 只有一個高權重樣式。
- 所有 keyboard focus 使用雙層高對比 ring。
- 文字行寬、字體、行距與背景可在 student reading mode 調整。
- 動畫與語音都要能停止、暫停、重播；不要自動開始長音訊。

## 5. 建議 backlog 與優先順序

### P0：下一個 sprint 必做

1. **Student audio bar**：播放／暫停／重播目前句／語速，並可被螢幕閱讀器讀到目前句與播放狀態。
2. **Capture audio guidance**：拍攝前、拍攝中、分析中、需要確認四種狀態的短指引與重播按鈕。
3. **語言 metadata**：對台語、中文 UI、臺羅建立 segment-level language metadata 與測試。
4. **Student primary action hierarchy**：每個 phase 只保留一個主 CTA，鍵盤回答不降級成隱藏 fallback。
5. **真實 NVDA／VoiceOver journey test**：涵蓋首次選擇、capture、student 一回合、observer 切換與錯誤恢復。

### P1：完成核心 demo 後做

1. student reading preferences：文字大小、行距、字距、主題、語速，並保存到使用者裝置。
2. 句子級同步 highlighting；同時提供純文字目前句和停止 highlighting 的設定。
3. resume card：顯示上次 session、目前 phase、最後播放句與「繼續」入口。
4. observer decision summary：把 raw turn、citation、latency 收進可展開區，首屏只顯示需要介入的訊號。
5. vocabulary practice：從教材詞彙產生重播、跟讀、再試一次與待複習標記。

### P2：有餘裕再做

1. 低干擾的進度鼓勵與學習連續性，不以視覺徽章作為主要成就。
2. 多學生 profile 與教師指派教材。
3. 更完整的 offline lesson cache 與同步狀態。
4. 可讓教師調整提示詳細度，但不直接洩漏答案的 intervention templates。

## 6. 研究限制與判讀方式

本報告使用官方產品文件、產品介紹與操作指南做 UI pattern benchmark，不等同於對這些產品目前版本逐頁做 NVDA/VoiceOver usability test。產品功能可能因地區、帳戶、裝置與版本不同而變化；本報告引用的是官方公開的產品能力，不把它們當成每個版本都保證的完整無障礙結論。

本專案下一次 review 應邀請至少一位實際使用螢幕閱讀器的台語學習者，執行完整 journey，特別檢查：台語／中文／臺羅 voice 切換、相機拍攝回饋、語音錄音狀態、錯誤 recovery，以及 observer 是否會洩漏不該給學生的資訊。

## 7. 參考資料

- [Microsoft Immersive Reader overview](https://learn.microsoft.com/en-us/azure/ai-services/immersive-reader/overview)
- [Microsoft Immersive Reader user preferences](https://learn.microsoft.com/en-us/azure/ai-services/immersive-reader/how-to-store-user-preferences)
- [Google Read Along on the web](https://blog.google/products-and-platforms/products/education/read-along-web/)
- [Google Classroom AI features and Read Along modes](https://blog.google/products-and-platforms/products/education/classroom-ai-features/)
- [Microsoft Seeing AI on Android and feature channels](https://blogs.microsoft.com/accessibility/seeing-ai-app-launches-on-android-including-new-and-updated-features-and-new-languages/)
- [Bookshare Reader](https://www.bookshare.org/bookshare-reader)
- [Bookshare／Dolphin EasyReader instructions](https://www.bookshare.org/wp-content/uploads/2024/02/bookshare_and_easyreader_instructions.pdf)
- [Learning Ally Audiobook Solution](https://learningally.org/app/)
