# Handoff after drill 9 (2026-10-01)

Start here in the next session. A board, not an implementation authorization. Replaces `handoff-after-f43.md`'s "next" pointer.

## State
- No open feature; queue empty. Drill 9 done: `docs/drills/drill-9/report.md` (B 1.06 → 1.51 on A's window, A 2.25).
- Nothing running: drill backend and worker stopped. Dev DB keeps the drill-9 org (`beast.drill9@example.com`, brand
  `brd_01M3TWE86JZ1238A9TX3EC9N4S`, campaigns `adc_01M3TXH5Q1WPNN8X5K6D9VW22Z` / `adc_01M3TZYVNCQRTHRZQGR5YB699S` /
  `adc_01M3V2144MNZEJ0VBJ25QMB2A4`) as evidence; the drill clock file still says 2026-10-17 (`scripts.drill.clock set` before reuse).

## Next: `/dig` drill-9 red #1＋#2 — ads carry no sell-way
Confirmed (code + DB, report §3 #1/#2): `ads_ad.product_id` is NULL; the sell-way lives only on `ads_campaign.context_json.product_ids`
and `workbench_brief.product_id`. Each step looks for offer evidence on its own:
- Planner (`app/ads/plan.py:63-67,225-258`, `app/ads/strategy.py:133-134`): menu prints `offer｜bundle｜組合加贈` only — no sentence,
  no list price; `app/departments/ads/delivery_plan.md` has no "use an available offer" rule → `offer_key` none 13/13.
- Copy generation (`app/workbench/jobs.py:711`): uses the brief's sell-way → wrote 「優惠價 999（原價 1,500）」 in 4 ads.
- Asset confirm (`app/ads/asset_suggestion_policy.py:57`): `validate_claims(..., None, copy)` → sell-way offer not counted → 「優惠」 flagged;
  `app/ads/slots.py:348` drops the pending result → slot shows 「處理中」 forever, no reason, no retry. The 4 stuck slots = the 4 offer ads.
- `bundle` label 「組合加贈」 is wrong for a multi-unit price (`app/core/vocab.py:48`, `app/schedule/repository.py:168`).

Open for the dig (none decided):
1. Who owns "which sell-way this ad sells": `ads_ad.product_id` filled at plan time, or the campaign's sell-way read everywhere?
2. What the planner gets per available offer (sentence + list price) and whether "at least one ad uses a true offer" is a prompt rule or a program gate.
3. How a refused slot shows its reason and what the user can do (edit copy / drop the word / retry).
4. Same-class callers to include: `app/ads/user_assets_routes.py:230`, `app/intake/product_onboarding.py:727`; other swallowed `pending_reasons`.
Proposed acceptance (from the report): rerun drill-9 P1 planning on the same data → ≥1 ad with a true offer, offer slots reach ready.

## Other drill-9 candidates (not planned; report §3)
- #3/#4 one owner for "period window and whether today counts" (perf page all rows vs overview rolling 14 days vs month incl. today);
  「在投」 counts unclosed platform objects.
- #5 no manual re-read when a day's data failed; launch approval blocks on 「餘額尚不確定」.
- #6 calendar data gaps (no Oct exam rows, no audience field, no look-ahead past end date); P2 had 國慶 but copy never used it.
- #7/#8 prefill content not checked against the page (refund policy read as 滿意保證; EU caffeine warning as expert_endorsement).
- #9 per-sell-way free shipping not expressible; #10 platform and per-sale cap re-entered every new campaign.
- Still open from `handoff-after-f43.md` 「Backlog candidates」.

## Drill tooling (for drill 10)
Reuse `docs/drills/drill-9/plan.md`, `.harness/scratch/drill9/dispatch_common.md`, `measure.py`, `ops.py`. AI prefill reads
`scripts/drill/site/` (frozen copy, three items stripped by user ruling). After moving the clock past a period end, run `ops.py sync`
before planning. Push stays manual.
