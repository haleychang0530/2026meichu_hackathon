# Agent B Stage 07 — MMS-TTS listening report

Status: `partial` — implementation and offline safety gates are complete;
human naturalness/intelligibility sign-off is pending an owner-authorized
recording review.

The table is the required 30-sentence listening set.  It is deliberately not
filled with invented ratings: synthetic transport tones are not speech and
must not be reported as model quality evidence.

| # | Hanji | MMS POJ | Naturalness | Intelligibility | Reviewer / date | Action |
|---:|---|---|---|---|---|---|
| 1 | 阿媽 | a-má | pending | pending | — | owner/consultant listen |
| 2 | 欲 | beh | pending | pending | — | owner/consultant listen |
| 3 | 去 | khì | pending | pending | — | owner/consultant listen |
| 4 | 市場 | chhī-tiûnn | pending | pending | — | owner/consultant listen |
| 5 | 買 | bé | pending | pending | — | owner/consultant listen |
| 6 | 菜 | chhài | pending | pending | — | owner/consultant listen |
| 7 | 阿媽欲去市場買菜 | a-má beh khì chhī-tiûnn bé chhài | pending | pending | — | owner/consultant listen |
| 8 | 囡仔 | gín-á | pending | pending | — | owner/consultant listen |
| 9 | 老師 | lāu-su | pending | pending | — | owner/consultant listen |
| 10 | 學校 | ha̍k-hāu | pending | pending | — | owner/consultant listen |
| 11 | 食飯 | chia̍h-pn̄g | pending | pending | — | owner/consultant listen |
| 12 | 啉水 | lim-chúi | pending | pending | — | owner/consultant listen |
| 13 | 朋友 | pêng-iú | pending | pending | — | owner/consultant listen |
| 14 | 厝 | chhù | pending | pending | — | owner/consultant listen |
| 15 | 門 | mn̂g | pending | pending | — | owner/consultant listen |
| 16 | 看 | khoànn | pending | pending | — | owner/consultant listen |
| 17 | 聽 | thiann | pending | pending | — | owner/consultant listen |
| 18 | 講 | kóng | pending | pending | — | owner/consultant listen |
| 19 | 好 | hó | pending | pending | — | owner/consultant listen |
| 20 | 真 | chin | pending | pending | — | owner/consultant listen |
| 21 | 歡喜 | hoann-hí | pending | pending | — | owner/consultant listen |
| 22 | 早起 | chá-khí | pending | pending | — | owner/consultant listen |
| 23 | 暗時 | àm-sî | pending | pending | — | owner/consultant listen |
| 24 | 今日 | kin-á-ji̍t | pending | pending | — | owner/consultant listen |
| 25 | 明仔載 | bîn-á-chài | pending | pending | — | owner/consultant listen |
| 26 | 逐家 | ta̍k-ke | pending | pending | — | owner/consultant listen |
| 27 | 多謝 | to-siā | pending | pending | — | owner/consultant listen |
| 28 | 拜拜 | pài-pài | pending | pending | — | owner/consultant listen |
| 29 | 佗位 | tó-ūi | pending | pending | — | owner/consultant listen |
| 30 | 台灣 | tâi-oân | pending | pending | — | owner/consultant listen |

The corresponding runtime manifest is
`services/speech-local/fallback/prerecorded_manifest.json`.  Each entry is
`approved: false` until the audio is supplied, listened to, and hash-recorded.
The critical demo sentence must be approved before a public demonstration; an
unapproved entry causes a transparent `TTS_FAILED`/`prerecorded_audio` fallback
instead of guessing a pronunciation.
