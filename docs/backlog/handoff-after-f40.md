# Handoff after F40 (2026-09-30)

Start here in the next session. A board, not an implementation authorization. Replaces `handoff-after-f37.md`'s "next" pointers.

## State
- No open feature; queue empty. F39 and F40 closed on `master` (`e985d59d`, **not pushed** — the user pushes manually).
- F39 (drill-7 red + backend yellows, ads.md §6.43): per-ad coordinate learnings at closeout, program scoreboard into both
  planners (prompt rule, no gate), scene per ad (`ads_ad.scene`), calendar → copy, starting point counts closed periods, one clock.
- F40 (drill-7 frontend batch, ads.md §6.44): status row + close on the 成效 tab, 在投 lines, home band states, approve-page
  budget block, assets polling / video slot / one photo → several ads (`ads_asset_placement.ad_id`), pack blocking reasons,
  readback confirm-all, new campaign copies the previous one, truth-card answers kept, regenerate label.
- Both migrations applied and registered on the dev DB (54322). The user's backend/worker windows must be restarted before
  any browser check.

## Next: drill 8
Rerun **B only** (same A rows/fit from drill-6), same script/judge/sim as drill 7 (`docs/drills/drill-7/plan.md`), on master
`e985d59d`. Measure: (1) does period-2/3 planning reuse the period-1 划算 combination and name it in `rationale` (F39 scoreboard
rule is prompt-only — if not followed, the fallback is a program gate in `plan._validate_reply`); (2) scenes differ per audience
and the copy follows them; (3) calendar shows up in hooks; (4) the F40 screens remove the drill-7 friction stations (§3 #7–#18).
Drill notes that held: plan dates later than the real date; worker as a separate process; register a fresh org; stand-in via
`scripts/drill`.

## Backlog candidates (not planned)
- Slots payload `role` counts so the assets tab can show 主力 N・探索 M (F40 skipped the chip).
- Per-part generation status in the set payload (regenerate label after a reload says 「另一個部分」).
- `campaignDraft.ts` persisting the four new-campaign fields between tabs; glossary Term for 整期合計; fold
  `LandingUrlField` into `WizardPieces`.
- Drill-7 #13b/#13c (conversion-goal radio / completion page) were not reproducible from code — probe at runtime in drill 8.
