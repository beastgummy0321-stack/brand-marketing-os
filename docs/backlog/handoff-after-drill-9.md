# Handoff after drill 9 (2026-10-01)

Start here in the next session. A board, not an implementation authorization. Replaces `handoff-after-f43.md`'s "next" pointer.

## State
- No open feature; queue empty. Drill 9 done: `docs/drills/drill-9/report.md` (B 1.06 → 1.51 on A's window, A 2.25).
- Nothing running: drill backend and worker stopped. Dev DB keeps the drill-9 org (`beast.drill9@example.com`, brand
  `brd_01M3TWE86JZ1238A9TX3EC9N4S`, campaigns `adc_01M3TXH5Q1WPNN8X5K6D9VW22Z` / `adc_01M3TZYVNCQRTHRZQGR5YB699S` /
  `adc_01M3V2144MNZEJ0VBJ25QMB2A4`) as evidence; the drill clock file still says 2026-10-17 (`scripts.drill.clock set` before reuse).

## Done: drill-9 red #1＋#2 — ads carry the sell-way (F44)
Built as `docs/architecture/ads.md` §6.48 (rulings: the offer coordinate decides the copy; an available offer must be used by at
least one ad). Next candidates below.

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
