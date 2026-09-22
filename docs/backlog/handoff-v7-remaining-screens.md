# Handoff — v7 ads-centre screens: DONE 2026-09-22 (F19–F24); what is left is backend-gated placeholders

Status: every prototype screen is built and human-accepted (F22 pause flow, F23 review flow steps 1–3, F24 abnormal states + monthly review + header chip); F19 is the only feature still open (its acceptance item covers home / campaign card / target page). Original goal (user instruction 2026-09-22): finish the rest of `docs/design/ads/prototype-v7-ads-center.html` with the workflow
proven on F21. This file is context, not execution permission: show the plan once, then run the whole queue.

## State
- Branch `feature/ads-center-v7-home` (main tree, clean, nothing pushed). F20 and F21 are closed into it. **F19 is still
  open** (human acceptance pending; do not close it for the user).
- Built: home `#/`, campaign detail `#/camp/<id>`, target `#/target/<id>`, data connections `#/connections`; batch A (F22,
  2026-09-22): steps 4–6 + sheet for the `pause` kind (`docs/architecture/ads.md` §6.22–6.23). Screens 4–7 below are done for pause; batch B (F23, 2026-09-22): screens 1–3 + review sheet (§6.24), ladder = placeholder (A); batches C+D (F24, 2026-09-22): screens 8, 10, 11 + failed card (§6.26); screen 9's recover banner not built (no signal), the 「沒收到回應」 state lives in the copy page. Every prototype screen is now built; remaining grey placeholders need backends (ladder count, brand-learning tags/list, image/existing-asset directions, next-month suggestions, adoptPlatform).
- Decisions: `docs/architecture/ads.md` §6.17–6.21. Measurements and root causes: `discovery-creative-lifecycle-and-triage.md`
  §5d–5g. UI rules: `docs/design-system.md` §1.7 (order of work, self-check 1–11). CLAUDE.md: 「先根因、後表象」 and the carve rule.
- harness 3.0.9 is committed in the plugin source (`D:/0UserProfile/Desktop/Default/Planner`, `92ee408`, 85 tests green)
  but NOT installed (no `claude` CLI on this machine's PATH). Until it is, workers call the source CLI for `run` only:
  `node "D:/0UserProfile/Desktop/Default/Planner/bin/harness.mjs" run "<command>"`; everything else stays on the installed 3.0.8.

## Remaining screens (prototype hash → function)
| # | Screen | Hash | Notes known today |
|---|---|---|---|
| 1 | Six-step repair, step 1 看證據 | `q/<id>/review` → `review()` | has an async "AI 正在整理證據" state; existing backend: review/evidence flows under `components/ads/Review*` |
| 2 | step 2 選方向 | `q/<id>/prepare` → `prepare()` | ladder 改文案→換圖→退役 has no backend (§5c); decide placeholder vs. small backend |
| 3 | step 3 改文案 | `q/<id>/copy` → `copy()` | diff of old/new copy |
| 4 | step 4 確認變更 (also the 3-step "light" flow for pause/budget) | `q/<id>/confirm` → `confirmPage()` | change-set API exists (`adsChangeApi.ts`) |
| 5 | step 5 到平台完成 | `q/<id>/handoff` → `handoff()` | manual checklist; `ManualHandoffPanel` exists |
| 6 | step 6 核對結果 | `q/<id>/verify` → `verify()` | verification states exist in change control |
| 7 | 暫緩／無法判定 sheet | `sheet(kind)` inside the flow | |
| 8 | 資料不足，這個活動先不判斷 (waiting) and 暫時讀取不到 (failed) | `wait/<id>` → `waitPage()`; failed card on home | **no backend state today** (§5c): needs a backend decision first; buttons go to `/ads/connections` |
| 9 | 系統剛恢復 banner, 保存「沒收到回應」 state | demo toggles `demoRecover`, `demoLost` | cross-screen states; check what change control already reports |
| 10 | 每月回顧 | `month` → `month()` | data source unverified — probe before planning |
| 11 | Shell header 「最近同步・N 項待處理」 | top bar | no brand-level sync endpoint (§6.21) |
Queue ids and campaign ids for the hashes are the keys of `db.queue` / `CAMP` in the prototype script.

## Workflow to use (what F21 proved; do not re-derive)
Per screen, one issue. Baseline to beat: worker 15 min / ~105 calls, 0 visual mismatches, 0 returns.
1. **Carve, facts first.** `cd frontend && node scripts/ui-evidence.cjs --proto ../docs/design/ads/prototype-v7-ads-center.html --hash <hash> --name <n> --out <scratch>`
   (no leading `/` or `#/` in `--hash`/`--app`). Read `facts-reference-*.txt`: `pieces` (kit component per button/chip) and
   `prototype classes with no kit mapping`. Recurring unmapped classes seen across the remaining screens: `card`, `meter`+`cap`,
   `thumb`, `camp`/`o-*` (campaign chip), `todo`, `seg`, `dots`/`d`/`dl` (step indicator — `patterns/StepIndicator` exists),
   `hero`, `tag`, `pickc`, `fld`. For each: layout only, an existing component (check `home/`, `detail/`, `patterns/`), or a
   missing piece. **The lead adds missing pieces to `components/ads/patterns` (with `data-slot` + variant attribute and one
   mapping line in the script) BEFORE dispatch** — issues keep `patterns/**` in `do_not_touch`, which is what made workers
   hand-roll copies.
2. **Check every field exists** in the real `/api` responses (capture fixtures like `.harness/scratch/F21/capture.cjs`);
   verify any "missing" claim yourself — an Explore agent was wrong about orders in F21. Missing fields → one small backend
   issue first; never into a legacy module (`validate` refuses; legacy list in ARCHITECTURE.md).
3. **Write the field→state rules in the feature Decisions, then challenge them before dispatch** (Appendix B): `harness:challenger`,
   read-only, given only the plan, told to read the backend code that produces each field and find counter-examples (null,
   zero, never set, NULL ordering, archived/variant rows, pagination, timezone, failed request vs. header counts). 80 s in
   F21; found everything the post-build review found. Correct the rules, then dispatch.
4. **Worker prompt** = Appendix A; its parts: attach first → `env` → facts command →
   context pack (sibling page + test, `ads/index.ts`, `App.tsx`, the API helper files, `patterns/index.ts`, §1.7 block only)
   → order facts → STATIC screen until `diff-*.txt` shows no one-sided piece type → wiring → tests → final evidence with
   `--mocks`. Own server port 8731 + issue number; dev commands through `harness run`. Stop-and-report rule instead of repair loops.
5. **Lead after hand-in**: read `diff-*.txt` and the two side-by-side PNGs → `finish` → post-build review only of what the
   challenge could not see (effects, keyboard, links) → `review approve` → `merge`.
6. **Docs before `integrate`** (a later commit voids the receipt, 3 min each); notes discovered after integrate go in
   AFTER `close`, on the base branch.
7. User instruction in force: on any problem, pause, find the root cause (the condition that makes this class of error
   inevitable), report cause first and symptom as evidence; no patch-by-patch returns. The user reviews once per merged
   batch on the running app (http://localhost:8710/app/brands/brd_bughunt/ads/…) plus the side-by-side images.

## Suggested batches (agent proposal, not decided)
A. Steps 4–6 + sheet (backend exists; the "light" 3-step flow makes 停損／加預算 proposals usable end to end).
B. Steps 1–3 (needs the ladder decision and the async evidence state).
C. Abnormal states 8–9 (needs a backend state decision first — ask the user once, with options).
D. Monthly review, then the shell header chip (probe data sources first).

## Open questions for the user (ask one at a time, with a recommendation)
- Ladder 改文案→換圖→退役: grey placeholder or a small backend?
- 「資料不足／讀取不到」 campaign states: which backend facts define them?
- Monthly review: which numbers, from which source, for brands with several platforms (discovery §6)?

## Environment notes
Docker needs the two-folder rename before each start (memory `docker-stale-sockets-block-start`). Test account
`123@example.com`／`123456`. Restart the 8710 backend before human acceptance when backend code changed. Push is manual, by the user.

## Appendix A — worker prompt template (`harness:worker`, model sonnet; fill the <…>)
```
You are the harness worker for issue <ID> (<screen>, UI). You ASSEMBLE an approved prototype screen from kit pieces; you do not redesign or re-interpret it.
Worktree (work ONLY here, absolute paths, prefix every shell call with `cd "<WT>" &&`): <WT>
FIRST command, alone: cd "<WT>" && node "<CLI>" attach <ID>   — its output carries the issue (follow its Done steps IN ORDER: facts → static screen that matches → wiring → tests) and the feature context. Then `node "<CLI>" env` alone.
Run your own tests, builds and servers as: node "D:/0UserProfile/Desktop/Default/Planner/bin/harness.mjs" run "<command>" (the worktree has no .env files).
Bridge tool: frontend/scripts/ui-evidence.cjs (read its header; --hash/--app take no leading slash or "#/"; never write your own screenshot scripts). `pieces` names the kit component + variant of every prototype button/chip: Button = @/components/layout/ui/button, Chip and the others = frontend/src/components/ads/patterns. Use exactly those; never choose emphasis yourself.
Context pack — read these instead of exploring: <sibling page + its test>, frontend/src/components/ads/index.ts, frontend/src/App.tsx, <API helper files + line hints>, frontend/src/components/ads/patterns/index.ts, docs/design-system.md: only "Worker self-check before handing in a UI issue" items 1–11 and "Assemble the screen from the prototype".
Fixture (real responses): <paths>.
Serving for --app runs (port <8731+N>): npm run build, then from the worktree root start uvicorn app.main:app on that port in the background with BRAND_OS_LLM_PROVIDER unset; poll /app/ until 200; after a code change only rebuild; kill the server when done. Final run uses --mocks { "<glob>": <fixture json> }.
Checks before hand-in: issue tests, npx tsc --noEmit -p ., npm run depcruise, npm run lint, npm run build. Commit on the issue branch. Do NOT run finish/merge.
USER INSTRUCTION: if a check fails, the page does not match, a prototype element has no kit piece, or the plan looks wrong, and the fix is not an obvious one-step correction inside touch — STOP and report what you saw and the cause you suspect. No repair loops, no wider scope.
Final report (short): files changed; check results; final diff-<name>.txt; evidence paths; anything omitted; anything that slowed you down or forced a guess.
```
## Appendix B — pre-dispatch challenge prompt (`harness:challenger`)
```
Read-only. You review a PLAN before anything is built (do not open .harness/worktrees/** or the target component folder).
Plan: .work/features/<F>.md — the Decisions bullets that define which API field produces which state, number or text.
For each rule, read the BACKEND code that produces the field, the frontend helper type, and any existing page showing the same data; find real inputs where the rule yields a wrong or misleading state/number: null, empty, zero, never set, NULL ordering, archived/variant rows, pagination, timezone of "today/yesterday", a failed request versus header counts. Starting points: <files>. Real sample responses: <fixture paths>.
Report at most 8 rule defects, most severe first: rule, concrete input, wrong result, file:line proof, corrected rule in one line. Under 400 words. Say plainly when a rule is sound.
```
