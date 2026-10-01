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

Dig 2026-10-01 (re-verified against code; not yet carved):
- Root cause restated: no single reader for "which sell-way this ad sells". `ad.product_id or campaign product_ids[0]` is
  re-derived per call site (`app/ads/assets.py:96`, `app/ads/learning.py:67-70`, `app/ads/plan.py:225`,
  `app/ads/materials_in_hand.py:34`) and skipped in `asset_suggestion_policy.violations`. A NULL `ads_ad.product_id` is a symptom.
- User rulings:
  1. The offer coordinate decides the copy: `offer=none` → copy must not write the sell-way's offer price / list price; an
     offer key → copy writes that offer's registered sentence. (Drill 9: 4 ads had coordinate `none` but offer copy, so the
     scoreboard would credit `none`.)
  2. "At least one ad uses an available offer" = prompt rule + program gate that rejects the whole reply (same pattern as the
     scene rule in `plan._validate_reply`); only when the filtered menu has an offer other than `none`.
- Agent assumptions (reversible, not user rulings):
  - The campaign owns the sell-way (wizard Contract D: exactly one, `app/ads/brief.py:242`); one resolver in `app/ads` read by
    planner, pack dispatch, confirm and learning; `ads_ad.product_id` stays an optional override, not filled at plan time.
  - Planner prints `bi_repo.offer_sources` sentences (already carry price + list price) beside the offer menu; no new data.
  - Refused slot: `ads_asset_placement.pending_reason` already exists and the manual upload notice shows it; the auto-confirm
    path (`slots._confirm_if_ready`, 3 callers) drops it. Store it, add a blocked slot state with the reason and one exit
    (edit copy / replace file / retry), stop the 3 s poll. UI → prototype before work.
  - `bundle` label 「組合加贈」 → 「組合優惠」 (`app/core/vocab.py:48`, `app/schedule/repository.py:168`).
- Same-class check: `user_assets_routes.py:230`, `product_onboarding.py:727`, `asset_suggestion_policy.py:81` pass `None` but
  read only `statutory_*` (brand regime, product-independent) — not this bug. Real sibling: `asset_suggestion_policy.source_rows`
  (`:50`) drops product-level approved claims for AI-filled copy.
Proposed acceptance (from the report): rerun drill-9 P1 planning on the same data → ≥1 ad with a true offer, offer slots reach
ready; plus: no ad with coordinate `offer=none` carries an offer sentence, and a refused slot shows its reason.

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
