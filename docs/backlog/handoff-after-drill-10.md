# Handoff after drill 10 (2026-10-02)

Start here in the next session. A board, not an implementation authorization. Replaces `handoff-after-drill-9.md`'s "next" pointer.

> **Superseded 2026-10-03:** drill 11 ran; start from `handoff-after-drill-11.md` and `../drills/drill-11/report.md`.

## Resume here (handoff 2026-10-03)
- Done: F45 / F46 / F47 (all drill-10 fixes) accepted by the user and merged to master (HEAD e19eaa2d, **not pushed**; push is
  manual). No open feature, no queue, no worker or backend running from that session. Main tree on `master`, clean.
- **Next = drill 11. The user has NOT said 「開跑」.** First message of the new session: show the plan below (short, Chinese,
  plain words) and wait for the go-ahead. Do not start any drill process before that.
- Plan already shown to the user once (unchanged): same question, nine dimensions, anchors and bar as `docs/drills/drill-10/plan.md`;
  new account + new org, three periods, three closeouts, A vs B. Drill-specific changes:
  1. `python -m scripts.drill.fake_meta reset` first (state files mirrored before 420ad723 lack the launch-pending mark).
  2. Dimension 3: `tw_sim` default = per-ad audience; also run `--audience group` and report both (drill-10-comparable).
  3. Control audit: each auditor gets its own account and spare objects (drill 10 left 159 controls unchecked; auditors collided).
  4. Provoked failures: same 20, separate fault account.
  5. Agents pick 「自訂」 dates (frontend "today" = browser clock, drill clock is ahead).
  Estimate 5–5.5 h (drill 10 measured ≈ 5 h). Output `docs/drills/drill-11/report.md` with drill-10 scores side by side and each
  drill-10 defect marked gone / still there / new.
- Leftover test data in the dev DB from acceptance (safe to keep or delete; test data): org `org_01M3Y1BN12NV2ZZTC95A1P79X7`
  (`acc.f45f47@example.com`), F47 worker brands `brd_01M3XYVV3Z07GH1RND84S2BFCA`, `brd_01M3XZS54S7WW9PDEF522H95JM`; brd_bughunt
  Oct budget set to 45,000. `.scratch/drill/meta_state.json` has an extra stand-in account `900000000004547` (backup
  `.harness/scratch/acceptance-f45-f47/meta_state.before.json`) — `fake_meta reset` clears it.
- Known accepted limits (not drill-11 blockers): readback keeps the timestamped old error until 重新讀回 after an outage; per-sale
  amounts show whole yuan everywhere (also small per-lead costs); O3 strategy text check, carousel-in-planning, calendar audience
  field not done (see "Fixes built" below).

## State
- Drill 10 (final battle-readiness drill, nine dimensions) ran 2026-10-01. **Bar not met** (bar = every dimension ≥ 7 and zero
  blocking defects): B scored 5 / 5 / 2 / 3 / 6 / 4 / 6 / 4 / 3, A scored 8 / 7 / 8 / 9 on the four shared dimensions; 3 blocking defects.
- What held: signup → three closeouts completes without the operator touching product data; F44 works (offers on 5 of 16 ads,
  drill 9 was 0 of 13; 0 blocked slots; 0 plan refusals; no offer leak on `none` ads); money numbers agree on every screen in all
  three periods; 「找不到工單」 0 times in the persona run (once during the control audit, recovered).
- Nothing running: drill backend and worker stopped. Dev DB keeps the drill-10 org (`beast.drill10@example.com`, brand
  `brd_01M3VMMJET4BP0ZVB7AQR9M04J`, three closed campaigns plus audit spares; org renamed 「備用測試組織」 by the control audit) and the
  fault org (`beast.drill10f@example.com`). Drill clock file says 2026-10-28 (`scripts.drill.clock set` before reuse).
- Not committed when this was written: `docs/drills/drill-10/`, this file, the pointer line in `handoff-after-drill-9.md`, and one
  drill-tool change (`scripts/drill/fake_meta.py`: outage switch `.scratch/drill/meta_fail`). No product code changed. Push stays manual.

## Drill 10 files (read what the task needs, not all of it)
| File | What it holds |
|---|---|
| `docs/drills/drill-10/report.md` | The result: score table (§0), ten root-cause groups (§1), A-vs-B evidence (§2), F44 measures (§3), defect list by level with screenshot and code location (§4), control-audit tally (§5), provoked failures (§6), drill artefacts and limits (§8), suggested order (§9). **Start here.** |
| `docs/drills/drill-10/plan.md` | Scoring anchors per dimension (what 10 / 7 / 5 / 3 / 0 mean), defect levels, control-audit page list, failure list. The re-run uses the same anchors. |
| `docs/drills/drill-10/operator-notes.md` | Every read-only root-cause mapping table (file:line per defect), per-period measures, tallies. Use when digging a specific defect; `report.md` wins on any disagreement. |
| `docs/drills/drill-10/controls.md` | Control audit, one row per control clicked (six areas). |
| `docs/drills/drill-10/faults.md` | The 20 provoked failures, each with on-screen wording, exit, verdict. |
| `docs/drills/drill-10/blind-verdict.md` | Independent judge's evidence for dimensions 1 / 2 / 4. |
| `docs/drills/drill-10/plans/` | Persona run logs `run_1..3.md`, exported plans, judge fit files, simulator reports. |
| `.harness/scratch/drill10/` (local, untracked) | Screenshots (`B/`, `controls/`, `faults/`), dispatch files, `measure.py`, `split_plan.py`, `build_blind.py`, simulator rows. |

## User rulings (2026-10-01 / 10-02)
- Scoring: nine dimensions 0–10, bar = every dimension ≥ 7 and zero blocking; an average alone does not pass.
- Unregistered same-family offer wording passing the guard (「買一送一」 typed by the user on a bundle-offer ad) = **needs a detour**, not
  blocking. Blocking count is final at 3.
- Order: dig and fix in a separate session, **then run the drill again** (see "After the fixes").

## Fixes built: F45, F46, F47 (2026-10-02)
Accepted by the user (「通過」, side-by-side pages `.harness/scratch/prototype/F4{5,6,7}-side-by-side.html`) and merged to master
2026-10-02 (not pushed). Lead runtime acceptance: `.harness/scratch/acceptance-f45-f47/report.md` (40 checks, the one failure fixed
after). Drill tools fixed for drill 11 in 420ad723 (`fake_meta reset` before reuse; `tw_sim --audience group` reproduces drill 10). Rulings and as-built: `docs/architecture/ads.md` §6.49 (F45), §6.49.1 (F46),
§6.49.2 (F47); `docs/architecture/intake.md` 「F45」, 「F47」; `docs/architecture/workbench.md` (F46 offer backing, F47 Q7 and
commit-before-enqueue); `docs/design-system.md` §6 (F47 feedback pieces). By report §1 root-cause group:
- Blocking B1 / B2 / B3 — done (F45).
- 1 learning channel — done (F46: ranked 留下／換掉 rows, planners build on them with a program gate, 品牌智庫 「投放學到的」,
  closeout exits, month review next step, strategy basis). The theme gap is covered by the customer group (8th coordinate) and the (group, angle) gate.
- 2 planned vs shipped — done (F46: actual format, offer sentence refused when missing, photo count, one customer group per ad
  set). Open: should the planner stop offering carousel while a slot holds one file.
- 3 waiting vs busy — done (F45 B3, S1, S2; F47 S3 delivery 「已上架，等平台開始投放」).
- 4 queue / proposal / review — done (F45 B2; F47 Q1–Q8: one done-ness owner, 暫緩 re-entry, top bar = connections count).
- 5 quantity without a unit — done (F45 base / composed sell-ways).
- 6 checks on one path only — done (F47 store-time input rules, one failure sentence, copy feedback, disabled reasons).
- 7 background staleness — done (F47 worker liveness notice; workbench commit-before-enqueue).
- 8 unreadable reported as read — done (F47 read reasons, one Meta classifier, connections 重新讀取).
- 9 defaults shown, not stored — done (F46 create defaults 沿用上一期 / 打平線, shown = stored).
- 10 offer and calendar data — done for O1 (F45 nameless offer sentence, per-sell-way free shipping) and October exam rows (F46);
  **open**: O3 (strategy text content check).
- Drill 9: #4, #5 done (F47); #6 October exam rows done (F46; audience field and look-ahead past the end date still open);
  #9 done (F45); #10, #12 done (F46).
- Left out on purpose (F47 Evidence): delete / edit entries for channel revenue, 口徑紀錄, bundles and saved sell-ways; C3-A days
  before campaign start counted as missing (likely drill clock); home 「月底會超出」 formula (needs a wording decision). Not built
  from F46: the strategy tab's per-ad provenance card, a monthly-budget default amount, daily budget on create.

## After the fixes: run the drill again (drill 11)
Same question (can it be used for real), same nine dimensions, same anchors and bar as `docs/drills/drill-10/plan.md`, so the two runs
compare directly. Show the user a short plan (what changed since drill 10, time estimate) and wait for the go-ahead before running.
- Reuse: `docs/drills/drill-10/plan.md` (anchors, page list, failure list), `.harness/scratch/drill10/dispatch_common.md` (persona),
  `controls_common.md` (control audit), `faults_dispatch.md` (provoked failures), `measure.py`, `build_blind.py`, `split_plan.py`; A side,
  judge rubric, `tw_sim`, Meta stand-in and site copy as in drill 9 / 10. New account, new org, three periods, three closeouts.
- Fix the drill tools first (they distorted drill 10):
  - `fake_meta load-rows` sets every entity of the brand ACTIVE, reopening ads the persona had closed
    (`scripts/drill/fake_meta.py:665-668`) → 「這個月關掉 0 則」 was this, not a product defect.
  - `export_plan` gives a group the first ad's `audience_key` and `tw_sim` reads only the group key
    (`scripts/drill/export_plan.py:38-41,62`, `scripts/drill/tw_sim.py:100`); report both the old and the per-ad figure so drill 10 stays comparable.
  - The stand-in lacks `adspixels`, adset settings / ad creative on mirrored entities, and a cursor in `paging.next`
    (readback 「26／34 項讀不到」, pixel 「代碼 100」 and the failed `meta_backfill` job were these).
- Known drill-only effects to tell the agents: the frontend takes "today" from the browser clock, so with the drill clock ahead
  「3 天後／7 天後」 are refused and the performance tab shows 「期間 0 天」 — use 「自訂」 dates.
- Control audit: give every auditor its own spare objects and tell them to click mutating controls on those (drill 10's first pass
  left 159 controls unchecked and auditors changed each other's data); one account per auditor if the page set allows.
- Simulator noise: 5–14 sales per period; differences under ~0.3 ROAS between B variants are not signal. Dimension 3 is simulated and
  only ranks two schedules; never write that a real campaign must run.
- Measured time for drill 10: about 5 hours (persona three periods ≈ 91 min; four parallel control audits ≈ 64 min; faults 57 + 24 min;
  follow-up audits 45 min).
- Report as `docs/drills/drill-11/report.md` with the drill-10 scores beside the new ones, and which drill-10 defects are gone,
  still there, or new.
