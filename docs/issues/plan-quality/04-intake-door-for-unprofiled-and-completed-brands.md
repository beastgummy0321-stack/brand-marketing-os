# 04 — The intake page opens a research round for a brand that has never run one, and again for a brand that has finished one

Route B: behaviour change, frontend only; no schema, no module boundary, no money path, no permission path.
Staffing (user, 2026-09-08): Sonnet implements; main chat (Fable) reviews the diff; Opus reviewed the ticket list once
before dispatch. Board row: 方案品質 (`docs/issues/plan-quality/spec.md`, cause 一). User's wish, 2026-09-08:
「讓即便後面品牌已經建檔完還是能走一次建檔讓 AI 掃品牌資訊」.

Why: the backend already supports a new round for an existing brand — `POST /api/intake/brands/{brand_id}/restart`
(`app/intake/routes_api.py:108-125`, one active draft per brand held by the partial unique index
`idx_intake_draft_one_active`, `supabase/migrations/20260826000003_intake_baseline.sql:35`) and `StartStep` already
has a restart mode (`frontend/src/components/intake/steps/StartStep.tsx:18` `isRestart = brandId !== null`,
`:62-64` calls `submitIntakeRestart`). What is missing is the door: `IntakeWizard` renders `StartStep` with a
`brandId` only at step 1 of an **existing** draft (`IntakeWizard.tsx:93`), so

- a brand that never ran the wizard (`brd_bughunt`, product Beast Gummy — no `intake_draft` row, measured
  2026-09-08) gets `GET /api/intake/brands/{id}/draft` → 404 → the `找不到建檔進度` empty state
  (`IntakeWizard.tsx:61-63`) whose only action is 回到跨品牌總覽;
- a brand whose draft is completed gets `IntakeCompletedPage` (`IntakeWizard.tsx:70-72`) whose only action is
  前往品牌頁 (`IntakeCompletedPage.tsx:54`).

The only link into the page today is `library/tabs/ResearchReportsTab.tsx:107` (`/brands/:id/intake`).

## What

`frontend/src/components/intake/IntakeWizard.tsx`:

1. `state.status === "notfound"` renders the restart form instead of the empty state:
   `<TaskFlowShell steps={STEP_LABELS} current={1} …><StartStep brandId={brandId} onSubmitted={refresh} /></TaskFlowShell>`
   — the same shell the `!brandId` branch uses (`:50-54`), with `CostGauge draft={null}`. After submit,
   `refresh()` reloads the draft, which now exists at step ≥ 1, and the wizard continues as today. `StartStep`'s
   restart mode already labels the form 「重新調研：{brand name}」 and the button 「開始這一輪調研」 (`StartStep.tsx:90`,
   `:192`); for a brand with no previous draft `prevBrandName` resolves to `null` and the header shows 「重新調研：…」
   — change that fallback in `StartStep.tsx:90` to the brand name passed down: `IntakeWizard` does not have it, so
   `StartStep` keeps calling `fetchIntakeDraft` and, on the 404, shows the title 「品牌調研」 instead of
   「重新調研：…」. One ternary on the existing `prevBrandName === null` state; no new fetch.
2. `draft.completed` still renders `IntakeCompletedPage`, which gains a second action next to 前往品牌頁:
   a `Button variant="outline"` labelled **再跑一次調研** that calls a new prop `onRestart: () => void`. `IntakeWizard`
   passes `() => setState({ status: "notfound" })` — the completed page flips to the same restart form as item 1.
   No backend call until the user submits the form (the restart endpoint creates the draft; `already_running`
   handling in `StartStep.tsx:38`/`:78` stays as is).

Literal shape (the only contract that changes is a component prop):

```json
{"IntakeCompletedPage": {"props": {"brandId": "string", "onRestart": "() => void"}}}
```

Copy per `docs/design-system.md` §8: button labels are standard verbs / noun phrases (再跑一次調研, 前往品牌頁),
no first person, no question. Nothing else on the completed page moves.

Not this ticket: the handoff step's "skip" affordance (`docs/issues/ui/issue-intake-handoff-dead-end.md` stays
open); the sidebar; the library tab link; any backend change.

## How we know it's done

1. `cd frontend && npm run build && npm run lint && npm test` green. `npm test` includes a new vitest in
   `frontend/src/components/intake/IntakeWizard.test.tsx` (create it; follow the nearest existing `*.test.tsx`
   under `frontend/src/components/` for the render/mocking convention — `git ls-files 'frontend/src/components/**/*.test.tsx'`
   lists them): with `fetchIntakeDraft` mocked to reject with `Error("找不到建檔進度")`, rendering
   `<IntakeWizard brandId="brd_x" />` shows the button text 開始這一輪調研 and does **not** show 找不到建檔進度.
   Red proof: revert item 1 → the test fails on the missing button.
2. Same file, second case: `fetchIntakeDraft` resolves a draft with `completed: true` → the page shows 再跑一次調研;
   clicking it shows 開始這一輪調研.
3. `cd frontend && npm run e2e` green (start the backend on 8720 yourself, stop it after; `supabase start` first).
4. Acceptance walk (`WALK:` post, playwright-cli, login `123@example.com` / `123456`, fresh session, restarted
   backend): open `/app/brands/brd_bughunt/intake` → the form with 開始這一輪調研 is visible, 找不到建檔進度 is not.
   Do **not** submit the form (that would create a draft on the seed brand and start a paid scan). Screenshot.
   Then open the completed brand `/app/brands/brd_01M1Y3SJSGWDCJSGV6R27PR09C/intake` → 🎉 建檔完成 with both
   buttons; click 再跑一次調研 → the form appears. Screenshot. Do not submit.

## Shared files touched

`git grep -n "IntakeCompletedPage" -- . ':!graphify-out'` (2026-09-08) — the component whose props change:

```
frontend/src/components/intake/IntakeCompletedPage.tsx:16:export function IntakeCompletedPage({ brandId }: { brandId: string }) {
frontend/src/components/intake/IntakeWizard.tsx:10:import { IntakeCompletedPage } from "./IntakeCompletedPage";
frontend/src/components/intake/IntakeWizard.tsx:71:    return <IntakeCompletedPage brandId={brandId} />;
```

`git grep -n "找不到建檔進度" -- . ':!graphify-out'` — the string that stops being rendered in the notfound branch:

```
app/intake/routes_api.py:161:    不然完成畫面會變成 404「找不到建檔進度」（e2e-adflow finding 1）。"""
frontend/src/components/intake/IntakeWizard.tsx:62:    return <EmptyState title="找不到建檔進度" description="這個品牌目前沒有進行中或已完成的建檔草稿。" actionHref="/" actionLabel="回到跨品牌總覽" actionInternal />;
```

`git grep -n "notfound" -- . ':!graphify-out'`:

```
frontend/src/components/intake/IntakeWizard.tsx:19:type LoadState = { status: "loading" } | { status: "error"; message: string } | …
frontend/src/components/intake/IntakeWizard.tsx:40:        if (err instanceof Error && err.message.includes("找不到")) setState({ status: "notfound" });
frontend/src/components/intake/IntakeWizard.tsx:61:  if (state.status === "notfound") {
```

`git grep -n "submitIntakeRestart\|brand_restart" -- . ':!graphify-out'` (unchanged, listed because the ticket
relies on them):

```
app/intake/routes_api.py:109:async def brand_restart(request: Request, brand_id: str):
frontend/src/components/intake/steps/StartStep.tsx:3:import { fetchIntakeDraft, submitIntakeRestart, submitIntakeStart, uploadInta…
frontend/src/components/intake/steps/StartStep.tsx:63:      const res = await submitIntakeRestart(brandId, { description, urls: tr…
frontend/src/lib/intakeApi.ts:235:export function submitIntakeRestart(
```

Files this ticket edits: `frontend/src/components/intake/IntakeWizard.tsx` (107 lines),
`IntakeCompletedPage.tsx` (74), `steps/StartStep.tsx`, new `IntakeWizard.test.tsx`. All under one feature folder;
the feature's `index.ts` export list does not change (ADR 0060).

## Contradiction check

- Done-check 1 and the backend's `already_running` rule could contradict: a brand with an **active** draft never
  reaches `notfound` (the GET returns the draft), so the restart form is never shown over a running round. Input
  that would show a conflict: none — `notfound` is only produced by the 404 path. Check 2's flip on a completed
  draft is safe for the same reason: the restart endpoint refuses while a draft is active
  (`routes_api.py:113`), and `StartStep` already renders the `alreadyRunning` panel for that answer.
- Cheapest wrong implementation that leaves every check green: render the restart form on `notfound` but leave
  `IntakeCompletedPage` untouched and satisfy check 2 by making the completed page's existing 重新讀取 button set
  `notfound`. Check 2 names the label 再跑一次調研, and the walk (check 4) opens the completed brand and reads the
  button text — that rules it out.
