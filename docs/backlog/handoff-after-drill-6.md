# Handoff after drill 6 (2026-09-26)

Start here in the next session. A board, not an implementation authorization: `/dig` the first red group, re-verify each claim first (file:line in the audits are as of `b17cd61e` + this drill's uncommitted tree).

## State
- No open feature; queue empty. F31 closed on `master` (`b17cd61e`, not pushed). The user pushes manually.
- **Uncommitted working tree** (drill tooling + docs only, no product code): `scripts/drill/{clock.py,export_plan.py,tw_sim.py,worker.py}` new; `scripts/drill/{fake_meta.py,serve.py}` modified (drill account `900000000000006`, `load-rows`, clock install); `docs/drills/README.md` (Drill 6 section); `docs/drills/drill-6/` (report, contract, rubric, audits, plans, persona runs). Commit as `docs+drill: drill 6 …` before starting the feature so the audits are on master.
- Drill processes are stopped, drill clock cleared (`.scratch/drill/today` removed). The user's normal backend/worker were killed before the drill: run `啟動行銷系統.bat` to use the product. Stand-in state `.scratch/drill/meta_state.json` still holds the drill brand's mirrored entities (harmless; `fake_meta reset` before the next drill).
- Drill brand in the shared dev DB: org `org_01M3EJ2P9F3P7GV3P8MX2TDJ38`, brand `brd_01M3EJ4K14MDBQ4PMQD1EY1K45` (test data; three campaigns, spend rows for 9/26–10/9). `supabase db reset` removes it.
- No background agents or jobs alive. Persona account credentials are in `.harness/scratch/drill6/B/account.md` (scratch, not committed).

## Outcome (one line)
Outside advertiser (Opus, blind) vs the product (Sonnet persona) over three simulated weeks: A ROAS 0.81→2.00→4.27, B 0.25→0.30→0.88. Full report `docs/drills/drill-6/report.md`; 21 gaps cited to code in `audit_p1.md` / `audit_p2.md`. Simulated numbers are relative only (`tw_sim.py` rules), never proof of real delivery.

## Next step (user ruling pending: order below is the drill's recommendation)
1. ~~Red group 1~~ carved as **F32** (2026-09-26, ruling A): `live` at readback bind, `ended` on the runtime beat, settle
   steps as `?step=`. Corrections to the audit: `jobs.py:22` is not the monitor (`runtime.dispatch` keys on
   `ads_external_entity`), and the real blocker was `PerformanceTab.tsx:195` hiding 結案 for a `ready` campaign; a
   non-default settle candidate also silently degraded to candidate 0. Rules in ads.md §6.36. F32 closed 2026-09-27
   (tests + browser: old settle path redirects to `?step=`). Campaigns bound BEFORE F32 keep `ready` (the rule fires at
   bind time only); on the dev DB run once:
   `UPDATE ads_campaign SET status='live' WHERE origin='internal' AND status='ready' AND local_state='bound';` (3 rows on
   2026-09-27: the drill brand's P1/P2 and one `brd_bughunt` campaign). `supabase db reset` makes this moot.
2. ~~Red group 2~~ carved as **F33** (2026-09-27, rulings 1A/2A; rules in ads.md §6.37). Original claim, verified: strategy blind to history: prompt omits `advertising_history`, pixel/audience size (`strategy.py:296-334`, `strategy.md:23-27` always splits 新客／再行銷／探索; `plan.py:69` validates vocabulary only). Plus a minimal TW calendar (holidays + exam weeks) as program rules, not LLM.
3. Red 3 — 食安法 banned-words gate after generation (today only prompt injection + brand `forbidden` substring on uploads; `claims.py` warnings never block). `docs/backlog/issue-u1-banned-words-gate.md` is UI wording, not ad compliance — do not reuse it as the ticket.
4. Yellow (report §4): ask the per-sale target before showing 打平 559 (`budget.py:36`, `CapBlock.tsx:117`); slot copy 「套用到全部」 (`UserAssetPlacements.tsx:73`); one data source for connections/home/成效/review (`home_overview.py:97`, `routes.py:825`, `review_evidence.py:243`); 「照上一期」 ÷ days with spend, not ÷30 (`channels.py:113`); duplicate products from 「賣什麼與數字」 (`routes_offerings_api.py:119,143`).

## Unverified / open
- Gap #19 (asset AI 「取得建議」 only fills 用途, never regenerates copy) was seen by the persona but not yet checked in code.
- Judge (Haiku) scored A 1.3–1.35 across the board; leniency does not change the ranking but the multipliers are soft.
- P3 for side B was simulated but not paired/pulled back into the product (final period, no feedback by design).
- Whether the readback 「讀不到」 26/27 items is only the stand-in (no creative fields mirrored) — real-account workload unknown.

## Rejected routes (with reasons)
- Using `brd_bughunt` for the persona: real Meta binding + six old campaigns would pollute triage; the persona registered a fresh org instead.
- `supabase db reset` before the drill: unnecessary once the persona has its own org; kept the user's data.
- Patching module-level `date`/`datetime` classes for the drill clock: broke `isinstance` in `app/core/db._json_default`; replaced with a `now_utc` wrapper (see `scripts/drill/clock.py`).
- Fixing product defects mid-drill: forbidden by `docs/drills/README.md`; every blocker was worked around by the operator and recorded in report §1.

## Drill tooling to reuse (drill only, never product)
`scripts/drill/clock.py set|clear`, `tw_sim.py run … --prior …`, `export_plan.py <brand> --period N --campaign <id>`, `fake_meta load-rows`, then `fake_meta pull <org> --since --until` and a hand-requested `external_sync.request_sync` (the 6-hour throttle `runtime._due` uses the real clock). Browser dates do not move: tell personas to set review windows explicitly.
