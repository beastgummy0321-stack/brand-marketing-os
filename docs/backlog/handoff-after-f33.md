# Handoff after F32／F33 (2026-09-27)

Start here in the next session. A board, not an implementation authorization: `/dig` the next group and re-verify each
claim in code first (file:line below are as of `3e16ba50`). Replaces `handoff-after-drill-6.md` (its audit corrections
are folded in here; the drill report and audits stay in `docs/drills/drill-6/`).

## State
- No open feature; queue empty. F32 and F33 closed on `master` (`3e16ba50`, **not pushed**; the user pushes manually).
- Working tree clean apart from this file. `.harness/` has no leases; the F32／F33 worktrees are removed.
- The user's backend and worker (`Marketing OS Server`／`Worker` windows, started 2026-09-27 00:00) run **pre-F33 code**
  from `master` at that time; restart with `啟動行銷系統.bat` after closing both windows before any browser check.
- Shared dev DB (54322) is test data. Drill brand `brd_01M3EJ4K14MDBQ4PMQD1EY1K45` (org `org_01M3EJ2P9F3P7GV3P8MX2TDJ38`)
  still holds three campaigns and spend rows 9/26–10/9. `supabase db reset` removes it.
- **Pending one-off backfill (user must run; the agent's `docker exec psql` UPDATE was denied by the permission
  classifier):** campaigns bound by readback BEFORE F32 keep `ready` because the live rule fires at bind time only:
  ```
  docker exec supabase_db_marketing psql -U postgres -c "UPDATE ads_campaign SET status='live' WHERE origin='internal' AND status='ready' AND local_state='bound';"
  ```
  (3 rows on 2026-09-27: the drill brand's P1／P2 and one `brd_bughunt` campaign.)

## Done since drill 6 (rules live in `docs/architecture/ads.md`)
- **F32** (§6.36) — drill gaps #11／#12／#14: readback binding the campaign node sets `ready→live`; the runtime health
  beat sets `live→ended` when the plan end date passed (never `closed`); settle wizard steps are `?step=` (old path
  redirects). Verified: tests + browser (redirect and page). Audit corrections: `jobs.py:22` is not the monitor
  (`runtime.dispatch` keys on `ads_external_entity`); the real blocker was `PerformanceTab.tsx:195` hiding 結案 for a
  `ready` campaign; a non-default settle candidate silently degraded to candidate 0.
- **F33** (§6.37) — drill gaps #10／#18／#7 (rulings 1A／2A): strategy prompt carries 【這個品牌的起點】 and 【可用角色】
  (`retarget` only with a source: `advertising_history = has_history`, 90-day external clicks／purchases, or closed-loop
  purchases > 0); `app/ads/calendar_tw.py` static 2026–2027 table (holidays／exams verified on dgpa／ceec／cap／tcte,
  conventions marked); 【投放期間內的行事曆】 in strategy and delivery-plan prompts; scripted e2e AI follows the prompt.
  Verified: tests + full integrate incl. e2e. **Browser acceptance not done** (needs the user's backend restarted):
  fresh brand → roles 新客／探索 only and 起點 facts in the rationale; Beast Gummy → 再行銷 allowed; a period over
  10/9–10/11 → 國慶日 in the reasons or unknowns.

## Next step (drill report §6 order; user ruling pending)
1. **#9 食安法禁語閘** — `/dig` first. Today: forbidden rules only injected into prompts (`context_compiler.py:154-158`);
   brand `forbidden` substring match on uploaded／suggested copy (`asset_suggestion_policy.py:52-63`,
   `review_policy.py:81-84`); workbench regex warnings never block (`workbench/claims.py:1-19`); generated copy never
   checked after generation. `docs/backlog/issue-u1-banned-words-gate.md` is UI wording, not ad compliance — do not reuse
   it as the ticket. Decisions needed: source of the statutory list (食安法 §28 + 衛福部 公告 wording list, program data
   like `calendar_tw.py`), block vs warn, where the gate sits (workbench output check + ads launch approval).
2. **#1 文案與廣告格兩條路** — approved workbench copy never fills an ad slot; 「只準備新文案」 is a dead end on a draft
   campaign (`change_control_launch.py:27`, `MaterialTaskEditor.tsx:72`). Design question, not a bug fix.
3. **#16 商品重複建立** — 「賣什麼與數字」 step creates a second product when no `product_id` (`routes_offerings_api.py:119,143`;
   `OfferingsStep.tsx:114` sends no variant id); scan checklist dedupes (`intake/state.py:303-331`), this step does not.
4. **#3 站內出圖** — still 「接上後開放」 (`workbench/image_port.py:14`); known P2, needs a provider decision.
5. **Yellow batch** (report §4, small fixes; one feature): #4 ask the per-sale target before showing 打平 559
   (`budget.py:36`, `CapBlock.tsx:117`); #2／#17 slot copy inline + 「套用到全部」 (`AssetsBody.tsx:237`,
   `UserAssetPlacements.tsx:73`); #13 one data source for connections／home／成效／review (`home_overview.py:97`,
   `routes.py:825`, `review_evidence.py:243`); #15 「照上一期」 ÷ days with spend, not ÷30 (`channels.py:113`); #8
   audience hint in the manual handoff list (`handoff_data.py:66`, `manual_settings.py:12`); #20 one 「今天」 source
   (`PreparePage.tsx:156`, `review_evidence.py:239`); #5 派工 wording (`WorkbenchHomePage.tsx:134`); #6 scan empty-message
   condition (`ScanStep.tsx:198`, `intake/ai.py:234`).

## Unverified / open
- Gap #19 (asset AI 「取得建議」 only fills 用途, never regenerates copy): seen by the persona, not yet checked in code.
- Whether readback 「讀不到」 26/27 items is only the drill stand-in (no creative fields mirrored).
- Judge leniency (Haiku scored A 1.3–1.35 across the board) — ranking holds, multipliers soft.
- `ads_action.sync_state='confirmed_manual'`: column exists, no writer, read once in `judgment.py:196` (dead path, left).
- F33 agent choices open to reversal: the retarget rule uses 90-day external purchases (not all-time); starting-point
  facts are not stored in `budget_basis_json.basis` (prompt only); 期中／期末／開學 rows are `kind: "exam"`.

## Rejected routes (with reasons)
- Deriving `ads_campaign.status` at read time from entities everywhere: touches list／judgment／jobs／PerformanceTab;
  one writer at bind time was smaller (F32).
- Keeping settle picks in browser storage: hides the AppShell pathname-key cause; `?step=` fixes it (F32).
- Letting the LLM decide role availability from facts only: the department example effect would repeat the drill (F33, 1A).
- Fetching holidays at runtime or asking the LLM: table is data, extended yearly (F33, 2A).
- Reading Meta custom audiences for the retarget rule: no existing read, new Graph scope; not needed for "> 0" sources.
- Using `brd_bughunt` for drill personas: real Meta binding pollutes triage; personas register a fresh org.

## Drill tooling to reuse (drill only, never product)
`scripts/drill/clock.py set|clear`, `tw_sim.py run … --prior …`, `export_plan.py <brand> --period N --campaign <id>`,
`fake_meta load-rows`, then `fake_meta pull <org> --since --until` and a hand-requested `external_sync.request_sync`
(the 6-hour throttle `runtime._due` uses the real clock). Browser dates do not move: tell personas to set review
windows explicitly. Launch config `drill-backend` in `.claude/launch.json` starts the stand-in server on 8710.

## Timing (from `.harness/runtime/metrics.jsonl`)
F32: 2 issues parallel, authorize→integrate 15 min (integrate 5 min 15 s). F33: 3 issues (2 parallel + 1 after),
authorize→integrate 30 min (integrate 4 min 12 s), two rescopes on I01 (touch miss on a test fixture; then the
"ads tests import only declared facades" checker).
