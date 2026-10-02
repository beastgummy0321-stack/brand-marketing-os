# Handoff after drill 10 (2026-10-02)

Start here in the next session. A board, not an implementation authorization. Replaces `handoff-after-drill-9.md`'s "next" pointer.

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

## Next: dig and fix (report §9; the fixes themselves are not ruled yet)
1. Three blocking defects (report §4.1):
   - B1 break-even of a ×N sell-way / bundle uses the qty-1 sell-way's cost (wrong money) — root cause 5, quantity has no unit.
   - B2 review 「停掉這則」 creates no proposal and dead-ends — root cause 4, queue / proposal / review joined by URL only.
   - B3 a refused manual copy edit leaves the slot 「處理中」 forever — root cause 3, "waiting for you" and "system busy" are one state
     and only one path stores the refusal.
2. The learning channel (root cause 1) — the largest A-vs-B gap and the third time this class appears (drill 7 red, drill 9, drill 10
   dimension 4 = 3): one ruler for grades, bad-ad lines carry no cost, ads under the spend threshold never enter learning, no
   "keep the least-bad" rule, theme is not a coordinate, learnings have no owner-visible page, closeout offers no next step.
3. Planned coordinates vs what shipped (root cause 2); failure messages and background-job staleness (root causes 6–8);
   defaults shown but not stored (root cause 9); offer sentence / free shipping / calendar data (root cause 10).
4. Still open from drill 9: #4 「在投」 semantics, #5 no manual re-read, #6 calendar data, #9 per-sell-way free shipping,
   #10 cap and platform re-entered per campaign, #12 learnings not in 品牌智庫.
Fix root causes, not the individual symptoms in §4: each group in report §1 lists the defects that disappear together.

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
