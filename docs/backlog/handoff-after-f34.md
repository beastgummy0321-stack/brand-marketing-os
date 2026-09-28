# Handoff after F34 (2026-09-28)

Start here in the next session. A board, not an implementation authorization: `/dig` the next item and re-verify each
claim in code first (file:line below are as of `c4409a20`). Replaces `handoff-after-f33.md`.

## State
- No open feature; queue empty. F34 closed on `master` (`c4409a20`, **not pushed**; the user pushes manually).
- Working tree clean. `.harness/` has no leases; the F34 worktrees are removed.
- The user's backend and worker (`Marketing OS Server`／`Worker` windows) run **pre-F33 code**; restart with
  `啟動行銷系統.bat` after closing both windows before any browser check. F34's migration
  (`20260927000001_brand_intelligence_regulatory_regime.sql`) is already applied to the shared dev DB (54322).
- Shared dev DB is test data. Drill brand `brd_01M3EJ4K14MDBQ4PMQD1EY1K45` (org `org_01M3EJ2P9F3P7GV3P8MX2TDJ38`) still
  holds three campaigns and spend rows 9/26–10/9. `brd_bughunt.regulatory_regime` is NULL (never set for real).
- **Still pending one-off backfill (user must run; 3 rows on 2026-09-28):** campaigns bound by readback BEFORE F32
  keep `ready` because the live rule fires at bind time only:
  ```
  docker exec supabase_db_marketing psql -U postgres -c "UPDATE ads_campaign SET status='live' WHERE origin='internal' AND status='ready' AND local_state='bound';"
  ```

## Done since drill 6 (rules live in `docs/architecture/ads.md`)
- **F32** (§6.36) — gaps #11／#12／#14: readback binding sets `ready→live`; health beat sets `live→ended`; settle steps `?step=`.
- **F33** (§6.37) — gaps #10／#18／#7: strategy prompt carries 【這個品牌的起點】 and 【可用角色】 (retarget only with a
  source); `app/ads/calendar_tw.py` static 2026–2027 table; 【投放期間內的行事曆】 in strategy and delivery-plan prompts.
  Browser acceptance of F33 was folded into the user's F34 acceptance (frontend tests + prototype comparison).
- **F34** (§6.38) — gap #9, **soft reminder, never a gate** (user rulings 1A／2B + "no extra prompt limits"):
  `brand.regulatory_regime` (`'food_tw'`／NULL) set in the intake start step or the brand profile page;
  `app/workbench/statutory_tw.py` (curated patterns per 認定準則 §4／§5 + 健康食品管理法 §6, 附件一 27 phrases as allow-list)
  behind `workbench.validate_claims` (`statutory_hits`／`statutory_warning` = `{terms:[{term,tier_label}], sentence, href}`);
  surfaces: workbench version list, ads placement list (`GET …/placements`), 補文案 `notes`. Prototype = UI spec:
  `.harness/scratch/prototype/f34-statutory/index.html` (one hash per screen; not in Git — `.harness/` is ignored; the
  shots are in `shots/`). Not modelled: 附件二 nutrient phrases; `review_policy` recommendation copy is not checked;
  launch approval ignores it by design.
- **Workflow that held for F34** (memory `f34-statutory-reminder-2026-09-28`): user approves an HTML prototype before any
  frontend ticket; tickets cite the hash; the lead compares reference|built side-by-sides before merge. 3 issues, 0
  returns, one rescope (a required type field rippled into `LibraryPage.test.tsx` — list every fixture that builds a
  changed type). Authorize→last merge ≈ 45 min, integrate ≈ 5 min.

## Drill-6 progress (report §3 table, 21 rows; #21 is a drill limitation, not a fix)
Done 9／20: #1 #2 #7 #9 #10 #11 #12 #14 #18 — the whole red group of report §6 (1–3) plus #1／#2 (F35). Remaining 10 + #16 (re-verified: design, not a bug; one guard item in the yellow batch): #3 #4
#5 #6 #8 #13 #15 #17 #20 and #19 (unverified in code).

## Next step (recommended order)
1. **#1 文案與廣告格兩條路 — built in F35, user accepted 2026-09-28** (rules in ads.md §6.39). Slot = 圖｜文案 with
   `copy_only`／`image_only` states; a slot upload carries the ad's selected workbench copy, fills the purpose and confirms
   in one call; 「選一版文案」 on image-only slots; drafts hide 「只準備新文案」; 「開始做素材 →」 is the bar's primary on
   投放結構. #2 (upload falling into 進階) is dissolved by the same change; #17 (「套用到全部」) remains for uploads through
   the 自帶素材 fold only.
2. **#16 商品重複建立 — re-verified 2026-09-28: not a bug** (user agreed). The "two rows per product" are the designed
   parent + sell-way pair (ARCHITECTURE §8: economics hang on the sell-way; `budget.py:66` picks the first sell-way for a
   parent; `wizard_options._sellable` never lists both). The dev DB has no same-name parent anywhere; step 3 pre-fills
   every existing parent with its `product_id`. Remaining latent gap → one small yellow-batch item: `create_product` has 9
   callers and only the two scan paths dedupe by name; add a partial unique index on `(brand_id, name)` for parents and
   make `create_product` return the existing active parent on a name match.
3. **Yellow batch — carved as F36 on 2026-09-28** (rules in ads.md §6.40; queue `.work/ready/F36-I01…I10`; #13 only its step A, #16 as the guard item). Original list: #4 ask the per-sale target before showing 打平 559
   (`budget.py:36`, `CapBlock.tsx:117`); #17 「套用到全部」 in the 自帶素材 fold (#2 done in F35;
   `UserAssetPlacements.tsx:73`); #13 one data source for connections／home／成效／review (`home_overview.py:97`,
   `routes.py:825`, `review_evidence.py:243`); #15 「照上一期」 ÷ days with spend (`channels.py:113`); #8 audience hint
   in the manual handoff list (`handoff_data.py:66`, `manual_settings.py:12`); #20 one 「今天」 source
   (`PreparePage.tsx:156`, `review_evidence.py:239`); #5 派工 wording (`WorkbenchHomePage.tsx:134`); #6 scan
   empty-message condition (`ScanStep.tsx:198`, `intake/ai.py:234`).
4. **#3 站內出圖** — still 「接上後開放」 (`workbench/image_port.py:14`); known P2, needs a provider decision first.

## Unverified / open
- Gap #19 (asset AI 「取得建議」 only fills 用途, never regenerates copy): seen by the persona, not yet checked in code.
- Whether readback 「讀不到」 26/27 items is only the drill stand-in (no creative fields mirrored).
- Judge leniency (Haiku scored A 1.3–1.35 across the board) — ranking holds, multipliers soft.
- `ads_action.sync_state='confirmed_manual'`: column exists, no writer, read once in `judgment.py:196` (dead path, left).
- F33 agent choices open to reversal: retarget rule uses 90-day external purchases; starting-point facts are prompt-only;
  期中／期末／開學 rows are `kind: "exam"`.
- F34 agent choices open to reversal: conditional 改善／預防 rule fires only within 6 chars before a symptom word;
  the seed pattern list in `statutory_tw.py` is curated (edit freely, keep `basis`); the existing 「健康類法規」
  methodology switch (`compute_methodology_switches`) is unrelated to the new flag.

## Rejected routes (with reasons)
- Deriving `ads_campaign.status` at read time everywhere: one writer at bind time was smaller (F32).
- Keeping settle picks in browser storage: `?step=` fixes the AppShell pathname-key cause (F32).
- Letting the LLM decide role availability or holidays: program data instead (F33 1A／2A).
- Reading Meta custom audiences for the retarget rule: new Graph scope, not needed for "> 0" sources.
- Using `brd_bughunt` for drill personas: real Meta binding pollutes triage; personas register a fresh org.
- F34: blocking or re-asking on statutory hits; injecting the word list into prompts; a brand-wide 台灣食品 default;
  deriving the regime from `fact_type='regulatory'` facts (LLM-extracted, regime-less).

## Drill tooling to reuse (drill only, never product)
`scripts/drill/clock.py set|clear`, `tw_sim.py run … --prior …`, `export_plan.py <brand> --period N --campaign <id>`,
`fake_meta load-rows`, then `fake_meta pull <org> --since --until` and a hand-requested `external_sync.request_sync`
(the 6-hour throttle `runtime._due` uses the real clock). Browser dates do not move: tell personas to set review
windows explicitly. Launch configs in `.claude/launch.json`: `drill-backend` (stand-in server on 8710), `prototype`
(static server for `.harness/scratch/prototype` on 8741).
