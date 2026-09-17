# Device health snapshot

- Status: **ready**
- Checked at (UTC): `2026-09-17T02:39:42.0539357Z`
- Schema: `device-health.v1`

## Inventory

- OS: Microsoft Windows 11 家用版, build 26200, 64 位元
- Platform: ASUSTeK COMPUTER INC. ASUS Vivobook S 16 M5606WA_M5606WA
- BIOS: M5606WA.314
- CPU: AMD Ryzen AI 9 HX 370 w/ Radeon 890M, 12 cores / 24 logical processors
- RAM: 31.12 GiB total; 13.09 GiB free at capture
- Storage: C: 582.66 GiB free of 952.16 GiB
- GPU: AMD Radeon(TM) 890M Graphics, driver 32.0.21025.10016, 3200x2000 @ 60 Hz
- NPU: NPU Compute Accelerator Device, PnP `OK`, driver 32.0.203.297; runtime benchmark **not yet run**
- Power: 平衡; battery 85%

## Resource budget

| Bucket | Planning value | Rule |
| --- | ---: | --- |
| Windows / browser / Camera reserve | 7.78 GiB | max(25% RAM, 6 GiB) |
| Runtime capacity after reserve | 23.34 GiB | physical RAM minus reserve |
| Core Backend + Local RAG cap | 4 GiB | single worker, lightweight embedding |
| ASR CPU cap | 4 GiB | must be measured again in Stage 05 |
| TTS CPU cap | 2 GiB | CPU default; do not overlap with CPU ASR |
| Frontend + Speech overhead cap | 1.5 GiB | browser and local gateway overhead |
| Unallocated capacity after reserve | 11.84 GiB | measurement headroom |

## Device checks

| Check | Status | Detail |
| --- | --- | --- |
| memory_reserve | pass | free=13.09 GiB; reserve=7.78 GiB |
| storage_floor | pass | free=582.66 GiB; floor=100 GiB |
| npu_pnp | pass | NPU Compute Accelerator Device: OK |
| camera_pnp | pass | 2 camera device(s) detected |
| audio_pnp | pass | 3 audio device(s) detected |
| browser_media | pass | camera=pass; microphone=pass; playback=pass; secure_context=True |

The browser media check reports metadata only; it does not persist camera frames or microphone bytes. A `degraded` browser result means at least one manual media capability still needs a user-run test or fallback.
