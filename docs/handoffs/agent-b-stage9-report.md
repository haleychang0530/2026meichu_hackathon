# Agent B Stage 09 handoff

```text
Stage: Agent B Stage 09 — teacher/parent mode, App narration, and accessibility
Status: partial
Branch: codex/agentB_stage09
Base: 21bac37 (Agent B Stage 08 student teaching flow)
Schema/OpenAPI: v0.1.0 unchanged
Runtime profile: CPU-only
```

## Changed files

- `apps/web/src/pages/ObserverPage.tsx`: full teacher/parent dashboard with
  Lesson review form, vocabulary/臺羅, citations, goals, turn history, hint
  history, familiarity, latency/fallbacks, service health, controls, and
  session-preserving mode switch.
- `apps/web/src/types/viewModels.ts`: observer dashboard projections, Lesson
  review patch, and teacher action types; student-safe types remain separate.
- `apps/web/src/adapters/adapter.ts`: teacher review/control methods.
- `apps/web/src/adapters/realAdapter.ts`: canonical Lesson merge-patch mapping,
  full observer summary mapping, five-service health/device/model/queue
  mapping, revision-aware skip/redo actions, and explicit reset fallback.
- `apps/web/src/adapters/mockAdapter.ts`: deterministic full observer fixture,
  review controls, health matrix, and mock skip/redo/end/reset behavior.
- `apps/web/src/accessibility/narrator.ts`: testable Chinese Web Speech queue
  with priority, cancellation, pause/resume, replay, rate, and detail level.
- `apps/web/src/accessibility/NarrationProvider.tsx`: explicit persisted
  system-reader/App-narration choice and React context.
- `apps/web/src/components/AppShell.tsx`: narration controls, focus-name
  announcements, and first-use choice surface.
- `apps/web/src/components/StatusBanner.tsx`: readable device, model revision,
  queue depth, and degraded/offline messages.
- `apps/web/src/App.tsx` and page files: page-title focus targets and mode
  switch audio cancellation.
- `apps/web/src/styles.css`: responsive observer table/forms, danger controls,
  narration panel, and 200% reflow support.
- `apps/web/src/**/**.test.ts`: narrator, observer mock, and Lesson PATCH tests.

## How to run

```powershell
npm --prefix apps/web test -- --run
npm --prefix apps/web run typecheck
npm --prefix apps/web run build
npm --prefix apps/web run dev -- --host 127.0.0.1
```

Open `/setup`, explicitly choose system screen reader or App narration, then
walk `/session/demo-session/student` → `/session/demo-session/observer`. Use
browser zoom at 200%; the page keeps semantic headings, labels, live status,
native controls, and keyboard-visible focus.

## Tests and results

- Web tests: 9 files, 27 tests, PASS.
- TypeScript typecheck: PASS.
- Vite production build: PASS.
- Browser AX smoke: PASS for explicit narration choice, five-service health,
  observer fields, review controls, mode switch focus, system-reader switch,
  and 200% responsive layout.
- `git diff --check`: PASS; only CRLF normalization warnings remain on files
  touched by the Windows checkout.

## Accessibility checks

- System-reader mode is never inferred; App narration is disabled until the
  user explicitly selects it.
- App narration reads Chinese UI labels/statuses, cancels stale focus/status
  messages, and can be stopped before local lesson speech or microphone use.
- New page headings receive focus after route changes.
- Observer uses `main`, heading hierarchy, labelled forms, table caption and
  scopes, definition lists, `role=status`/`aria-live`, native buttons, and no
  positive `tabindex`.
- Browser accessibility tree smoke and 200% zoom were checked in the local
  in-app browser. Full hardware Narrator/NVDA traversal was not executed in
  this non-interactive test run.

## Known limits

- Canonical v0.1 has no separate observer `end` or `reset` endpoint. Real mode
  maps `end` to the safe `pause` action and returns an explicit
  `OBSERVER_RESET_UNSUPPORTED` fallback; Mock mode supports all four controls.
  Agent A should add a versioned observer control contract before claiming
  server-side end/reset in production.
- App narration depends on the browser/Windows Chinese Web Speech voice. If it
  is unavailable, complete visible text and system-reader mode remain intact.
- Full manual Narrator/NVDA and hardware microphone/TTS measurements remain a
  device acceptance step, not a claim made by this handoff.

## Agent A can rely on

- No canonical schema, OpenAPI document, Core session truth, RAG behavior, or
  MI300 boundary was changed.
- Student routes still consume only student-safe Session/Turn/Event
  projections; teacher-only Lesson and summary fields stay in observer state.
- Lesson edits go through `PATCH /api/lessons/{lesson_id}` and are accepted
  only when the Core Backend safety validation succeeds.
- Real observer skip/redo sends the existing revision and idempotency headers;
  health failures degrade to summary health instead of hiding the dashboard.

## Next action

1. Review the v0.1 end/reset gap with the repository owner and Agent A before
   adding any new observer-control schema.
2. Run a manual Windows Narrator/NVDA matrix and repeat the 20-switch session
   test on the target Ryzen AI 9 laptop.
3. If accepted, commit this Stage 09 change, push the branch, and ask the owner
   before opening the PR. Do not merge without explicit authorization.
