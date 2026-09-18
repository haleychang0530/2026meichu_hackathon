# Agent B Stage 10 handoff

```text
Stage: Agent B Stage 10 — laptop integration gate, release health, and fallback
Status: partial
Branch: codex/agentB_stage10
Base: 1607380 (origin/main, Agent B Stage 09 merge)
Schema/OpenAPI: v0.1.0 unchanged
Runtime profile: mock Speech + fixture Core; CPU-only policy documented
```

## Changed files

- `apps/web/src/pages/HealthPage.tsx`: Stage 10 release gate with Core/RAG/VLM/
  ASR/TTS health, CPU-only/NPU-disabled statement, browser media check, entry points,
  and readable fallback talk track.
- `apps/web/src/health/deviceReadiness.ts` and its test: explicit camera/mic check;
  test stream is stopped immediately and no raw media is retained.
- `apps/web/src/App.tsx`, `apps/web/src/app/routing.ts`,
  `apps/web/src/components/AppShell.tsx`, `apps/web/src/pages/SetupPage.tsx`,
  `apps/web/src/styles.css`: `/health` route, navigation, setup CTA, and responsive
  health styles.
- `scripts/release/Start-Demo.ps1`: one-click mock/real launcher, RAG reindex,
  Speech warmup, Core/Web readiness, managed PID state, and optional browser open.
- `scripts/release/Stop-Demo.ps1`, `Reset-Demo.ps1`, `Health-Demo.ps1`: exact-process
  shutdown, scoped runtime reset, endpoint/service health, CPU/RAM/disk/temperature
  metadata, privacy status, and retained logs.
- `scripts/stage10_release_gate.py`: 50-cycle in-memory TTS → synthetic recording →
  ASR → Core judge loop with latency, process memory, failure, and privacy output.
- `docs/release/stage10-operator-runbook.md`, `stage10-fault-matrix.md`,
  `stage10-rehearsal-scripts.md`: operator instructions, fault matrix, three rehearsal
  cards, and backup material map.
- `docs/reports/agent-b-stage10-release-gate.json`: sanitized measured gate result.

## How to run

```powershell
pwsh -File .\scripts\release\Start-Demo.ps1 -Mode mock -SpeechProfile mock
& .\apps\core-api\.venv\Scripts\python.exe .\scripts\stage10_release_gate.py `
  --speech-profile mock --rounds 50 --progress 10 `
  --output .\apps\core-api\.runtime\stage10-demo\release-gate.json
pwsh -File .\scripts\release\Health-Demo.ps1 `
  -OutputPath .\apps\core-api\.runtime\stage10-demo\health.json
pwsh -File .\scripts\release\Stop-Demo.ps1
```

For a clean demo reset, run `Reset-Demo.ps1` after stopping. For real dual-machine
mode, pass the current trusted MI300 URL to `Start-Demo.ps1 -Mode real`; the browser
still uses only `http://127.0.0.1:8000` and `http://127.0.0.1:8200`.

## Tests and results

- `npm --prefix apps/web run typecheck`: PASS.
- `npm --prefix apps/web test -- --run`: PASS, 10 files / 28 tests before the
  release documentation-only additions.
- `npm --prefix apps/web run build`: PASS.
- PowerShell parser check for all `scripts/release/*.ps1`: PASS.
- `python -m py_compile scripts/stage10_release_gate.py`: PASS.
- 50-cycle gate: 50/50 success, failure count 0, p50 419.63 ms, p95 518.61 ms,
  max 618.99 ms; no audio or transcript persistence.
- Peak launcher-managed working set total: 60,231,680 bytes; end-to-start delta:
  +344,064 bytes (~0.33 MiB) across the 50-cycle run.
- Browser mode smoke: 20 student/observer route transitions completed; a keyboard
  answer was submitted before switching, and observer showed the same
  `demo-session` with 1 turn, revision 2, and 53% progress.
- `git diff --check`: PASS; Windows checkout may report normal CRLF normalization
  warnings on touched files.

## Accessibility and privacy checks

- `/health` uses semantic headings, labelled sections, live status, native buttons,
  keyboard focus targets, and readable status text.
- Media permission is only requested by an explicit button; tracks are stopped and
  device counts/status are retained as metadata only.
- Student/observer route switch returns focus to the page title; student projection
  remains separate from observer-only fields.
- The 50-cycle gate uses a generated in-memory WAV and synthetic JPEG; it does not
  access a microphone, store student audio, or store transcripts.
- Full manual Windows Narrator/NVDA traversal and an operator-granted camera/mic
  permission check remain hardware acceptance steps.

## Known limits

- The target MI300 runtime and the v1.0 contract were not available in this local
  checkout. The live VLM path was therefore not claimed as passed; fixture health
  deliberately reports MI300 as degraded and says it is not being called.
- The measured 50-cycle run used deterministic mock Speech. CPU Breeze/MMS local-file
  cold start must be repeated on the target laptop with model weights already cached;
  the launcher never downloads them.
- Real MI300-offline, RAG-empty, ASR-failure, and TTS-failure drills are documented
  and mapped to contract fixtures; only the local mock/fixture release gate was run in
  this session.

## Agent A can rely on

- No canonical schema, OpenAPI document, Core session truth, RAG implementation, or
  MI300 client was changed.
- The browser still calls Core and local Speech only; the MI300 URL is launcher/Core
  configuration and is never embedded in frontend code.
- CPU-only is the declared release profile; NPU is explicitly disabled and is not a
  release blocker.
- The launcher reindexes laptop RAG, keeps SQLite/session state in its scoped runtime,
  warms Speech, reports health before opening the demo, and can stop/reset exact managed
  processes without touching unrelated user files.

## Next action

1. Agent A reviews this branch and runs the real-profile health/MI300 contract check on
   the designated dual-machine network.
2. Jointly repeat CPU local-file warmup, the three rehearsal cards, manual Narrator/
   NVDA traversal, and operator camera/mic permission check.
3. Confirm v1.0 schema/OpenAPI freeze and update this report with the live acceptance
   evidence before release.
4. After owner review, open the PR; do not merge without explicit owner authorization.
