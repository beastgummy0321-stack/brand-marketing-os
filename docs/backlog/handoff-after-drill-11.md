# Handoff after drill 11 (2026-10-03)

Start here in the next session. A board, not an implementation authorization. Replaces `handoff-after-drill-10.md`'s pointer.

## Resume here
- **2026-10-06: resume from `.work/features/F51.md` 「# Handoff」** (F48–F51 queues complete; combined acceptance and drill 12 remain open).
- **2026-10-04 whole-program audit** (user order: this round is the final fix, end the simulate→find→fix loop):
  `audit-2026-10-04/README.md` groups R1–R7 plus ~110 new verified findings into 19 generator workstreams W1–W19 with the
  machine check each must install; decisions 10–14 there extend §2 below. Carve from that README, not from §1 here.
  R1, R2 (E1/B13/E7/B6) and R5 (B2/N1) are built: `../architecture/ads.md` §6.50 (F48); R3, R4 (incl. C1) and R2 B5/P4: §6.51 (F49).
- Drill 11 ran 2026-10-03 03:40–07:45. **Bar not met**: blocking 0 (drill 10's three all gone) but no B dimension reached 7.
  B 5 / 6 / 4 (drill-10 measure 6) / 5 / 6 / 6 / 6 / 6 / 5 (drill 10: 5 / 5 / 2 / 3 / 6 / 4 / 6 / 4 / 3). Result: `../drills/drill-11/report.md`.
- **User ruling 2026-10-03**: review 「換一張圖」 dead end on system-built campaigns (report §4.1 C1) = 要繞路, not blocking. Blocking count final at 0.
- **User instruction 2026-10-03: next session fixes everything below completely** (one feature or a short chain; root-cause fixes, not per-symptom patches).
  Start with `/dig` only on the decisions in §2 (each has a recommendation), then carve. Every claim here was mapped read-only to code during
  the drill; re-verify a line before relying on it (`board-causes-need-reverifying`).
- Not committed: `docs/drills/drill-11/`, this file, the pointer line in `handoff-after-drill-10.md`, and the drill-tool fix
  `scripts/drill/clock.py` (swap the drill date in +08:00 local time; before 08:00 Taipei it ran one day ahead). No product code changed. Push stays manual.
- Nothing running. Dev DB keeps drill-11 test orgs (`beast.drill11@example.com`, `beast.drill11f@example.com`, `ctl.a.drill11`, `ctl.a2.drill11`).
  Clock file 2026-10-28; `.scratch/drill/meta_fail` empty. Before drill 12: `fake_meta reset`, `clock set`, start in daytime or keep the fixed clock tool.
- Evidence with full file:line tables: `../drills/drill-11/operator-notes.md` (sections "P1/P2/P3 defects mapped", "丙3", "Last mapping",
  "Post-drill mapping B"; mapping A is folded into §1 R6/R7 below). Screenshots local in `.harness/scratch/drill11/`.

## 1. Root causes (condition first; symptoms are evidence). IDs = report §4 / operator-notes.

### R1 Learning and judgement use two rulers, and 「留下」 keeps coordinates, not the thing that won
Causal chain: closeout ranking (`app/ads/learning_rank.py:8-15,59-98`) has no sample gate (1–4 sales can be 留下) → triage grading
(`app/ads/triage.py:33-36,404-410,463-483,545-573`) needs spend ≥ 3×cap or 7 days and ≥ 10 sales → a 450/day ad set split over 3 ads
(~150/day each) can never be graded in a 7-day campaign → cleanup closes graded ads only (`triage_capacity.py:154,262-278`) and never reads the
previous 留下 → which ad is closed depends on budget split, not results (H1: closed 634/4 sales, kept 1,009/1 sale). Then the next plan
recreates ads from coordinates only (`app/ads/plan.py:393-396,462-469`, `coordinate_learning.py:225-232`, `brief.py:565-567`); the approved
creative never travels → winners lose their copy every period (P1 392 → 3,512; P2 588 → 634) and the judge marks the rewrite as fatigue laundering.
Strategy prose is free text nobody checks (`plan.py:243,250-291,379-383`; `strategy.py:267-306`): 「三群都投」 with two ad sets (one group per
role, two roles), 「不再採用折扣」 with two discount ads (plan is refused when available offers go unused, `plan.py:431`), reasons quoting a
stale 392 and 「上一期 13 筆」 (two periods summed). Capacity: planner builds up to 3 ads per group (`plan.py:50,360`) and never checks
`can_support = floor(daily/(cap×2))` (`triage_capacity.py:49,276-285`) → 「每日 1,500 撐 1 則」 every period (drill-10 M2 still there).
Pause reason hard-coded 「一筆都沒賣出」 for every pause entry (`frontend/src/components/ads/flow/changeFlow.ts:144,168`; `ConfirmPage.tsx:310`;
real grade in `pauseView.triage`, `app/ads/triage_pause.py:31-41`).
Symptoms: L1–L6, H1, H2, H5, H6, G8, G9/E6, C3-D1. Dimensions 1, 3, 4 and the persona's "敢不敢交".
Fix direction: one grading ruler shared by triage, cleanup and closeout (sample size shown, not used as a hidden gate that budget split decides);
「留下」 carries the ad's approved creative into the next plan (reuse the placement/copy, regenerate only on 換掉); a program check that the
strategy's claims (groups covered, offers used/dropped, numbers quoted) match the structure and the closeout rows — or the strategy text is
generated from those facts; the planner respects can_support; pause reason built from the triage grade.

### R2 Plan and copy checks lack product facts, and the two claim guards disagree
- E1/B13 「特惠」 in the registered sell-way name 「超能特惠組」 blocks slot copy: product/sell-way names never reach `claims.unsupported`
  (`app/workbench/__init__.py:166-169`; `claims.py:190-209`); F45 removed the name from the offer sentence (`brand_intelligence/repository.py:836-849`).
  Workbench warns, slot blocks the same result (`claims.py:239-241` vs `app/ads/asset_suggestion_policy.py:82-90`). Same rule: 「折扣」「限時」
  on a discount slot refused because only the exact word in 「優惠價 NT$999（原價 NT$1,500）」 backs it (`claims.py:47-54`).
  Fix: strip registered product/sell-way names before scanning (as approved statements already are); one verdict for workbench and slot.
- E7 ad names 「咖啡因小錠」 (product is a gummy), 「不怕頻尿」 (user marked 頻尿 not-sayable): plan prompt has no product form and no
  forbidden claims (`plan.py:400-409`; forbidden stored at `app/intake/product_onboarding.py:984`, never read); names unchecked (`plan.py:216-221`).
  Fix: give the planner the product facts + forbidden claims; run names through the same claims check.
- B6 食安法 reminder missing on the slot manual edit: `statutory_note` is computed (`app/ads/asset_suggestions.py:353`) but `notes` is only in the
  return value (`:420`), never stored or shown. Fix: store the note on the placement and show it on the tile (F34 ruling: remind, never block).
- B5/P4 confirmed slots have no copy edit (`app/ads/slots.py:689-690`; `SlotTiles.tsx:118-121`); copy picker is brand-wide (`slots.py:656`;
  `workbench/__init__.py:59` takes no sell-way). Fix: new revision for a confirmed draft placement (as `follow_revision` does); filter by sell-way.

### R3 "Not readable", "not read yet" and "read, nothing there" all look the same
- E2/B11 readback asks the user to check fields no reader can ever prove (landing_url per ad set, material per ad):
  `app/ads/handoff_check.py:137-147`; `manual_settings.py:12-58` has no readable flag; `change_control_launch.py:22-24,119-125`.
  Fix: declare `readable: False`; confirm those once at approval, never list them as 「讀不到，請到 Meta 看一眼」.
- E3/B12 readback race 「核對期間來源已更新，保留較新的資料」 and vanishing buttons: `upsert_entity` always sets `updated_at=now()`
  (`app/ads/external_repository.py:87-88`); the runtime readback tick upserts the same rows each minute (`runtime.py:149-170`;
  `handoff_check.py:61-69,353-358,390-405,423-426`). Fix: bump updated_at only when a column changed.
- M1-c 「來源讀取已排入，稍後按重新讀取」 forever, silent: frontend drops the returned job (`ManualHandoffPanel.tsx:116-122`); worker writes
  read errors into task JSON so the job ends succeeded/partial (`app/ads/external_sync.py:542-595`), bell counts only procrastinate failures
  (`app/background/__init__.py:417-421`); list task has no campaign_id; "0 candidates" never shown. Fix: page reads the job outcome
  (failed / empty / found) and says it.
- C3-D6/G3 coverage = requested sync range, not days with rows nor campaign dates (`external_sync.py:67-69,484`; `triage.py:246,258-284`):
  /wait paints days without data, fixed headline 「最近 7 天都有資料」 (`WaitPage.tsx:118,271-272`); every campaign < 28 days raises
  insufficient_data. Fix: coverage = days that have rows, clipped to the campaign's start/end.
- G1 perf-tab per-ad window never clipped to campaign dates (`CampaignDetailPage.tsx:242-252`; `triage.py:545-556`) vs whole-period totals.
- B7 /wait 「重新檢查」 on a draft only refreshes the account list (`external_routes.py:174-190`), chip 「平台照常投放」 hard-coded (`WaitPage.tsx:117,284`).
- E5/B10 「在投 0 則」「每日預算未知」 after switch-on: counts from stored native_status (`workspace_reads.py:198-214`;
  `home_overview.py:414-421`); `reported_at` exists (`handoff_data.py:255`). Fix: show 上次讀取 time; mark counts older than the switch-on report as stale.
- N2 closed campaign 「近 14 天花費 未知」 next to 已花費: window anchored to today (`workspace_reads.py:95-121`).
- M1-a outage sentence shows 「代碼 2」 and 「。；」 with no 「稍後再試」.

### R4 Queue rows have no owner for "the campaign ended", and some flows read data only imported campaigns have
- H3 ended campaigns still get stop/cleanup proposals and 「每天省約 730 元」: triage classifies every non-closed campaign
  (`triage.py:617-622,771-816`; saving `triage_capacity.py:183,313`; runtime only marks ended, `runtime.py:240-257`).
- G3 closed campaigns are never triaged; open rows auto-resolve at closeout; home board never shows insufficient_data rows (`home/status.ts:211`).
- H4/Q2 「下一件」 → 「資料不足，這個活動先不判斷」 dead end: `nextOpenQueueItem` scans all kinds (`changeFlow.ts:291-300`; `queue_done.py:10-11,21,42-52`);
  page offers only 重新檢查 (a sync, cannot fix a sample gate) and ← 投放中心, no 結案 (`wait/WaitPage.tsx:44-47,100-121,322-327`).
- C1 (ruled 要繞路) review 「換一張圖」 → 「建立新廣告提議」 always disabled on system-built campaigns: ad-set lookup only in
  `external_view`, null unless imported (`MaterialStepPage.tsx:60-65,137,265,317`; `app/ads/repository.py:814-817`); `handoffRead.destinations`
  already has the data (`handoff_data.py:231-245`). Other `external_view` readers are deliberately imported-only.
- C3-D2 review copy: clearing 新標題 passes, confirm/handoff/verify show 「—」 and 複製標題 copies "" (`CopyPage.tsx:253-261,475`;
  `change_control_data.py:250-259`; `confirmParts.tsx:190`; `HandoffPage.tsx:296,302`).
- E11/Q4 monthly-budget gate links to ads home with no way back (drill-10 D3 still there): `confirmParts.tsx:325,336-340`; `MonthlyBudgetPanel.tsx:16,110`; `AdsHomePage.tsx:103-106`.
Fix direction: "ended (not closed)" becomes a state the queue understands — no pause/cleanup proposals on it, a closeout prompt instead; one rule
for which queue kinds are user decisions (home count = 下一件 = decision kinds); every queue page has a forward exit; flows open to internal
campaigns read `destinations`, not `external_view`; inline monthly budget editor (or a return target) on the publish list.

### R5 A number's basis is not written next to the number
Built in F51 where scoped: `../architecture/ads.md` §6.53, `../architecture/intake.md` F51 and `../design-system.md` §§6–7. Earlier F48–F50 ownership remains as recorded above; drill 12 is the independent outcome check.
- N1 「這期要花 6,000」 = October's share only (1,500 × 4 days): `app/ads/month_budget.py:217-227`; `change_control_launch.py:159-186`; `confirmParts.tsx:280,320`.
- G6 「少賺約 NT$5,000」 deducts product cost, label says only 扣掉廣告費: `app/ads/home_overview.py:236-242`; `MonthMoney.tsx:126-146`.
- B2 「改這期總預算」 after expansion saves budget_planned only; ad-set daily budgets (what month fit and approval read) never change:
  `plan.py:360`; `strategy.py:568-621` (no status check; `set_allocation` refuses at `:645`); `change_control_launch.py:137,227`; `repository.py:1138`.
- N3 home 「還沒有活動」 with three closed campaigns: `home_overview.py:502-504`; `CampaignRows.tsx:82-84`.
- B9 month review heading 「11 月建議」 = shown month + 1 (`MonthReviewPage.tsx:160-161`).
Fix direction: every figure says what it covers (month portion, days, cost basis); one source for the period budget (after expansion, a new total
re-splits ad sets with `budget.split`, or the link goes to the structure tab).

### R6 Readiness and field rules are re-implemented per page instead of one rule (drill-10 root cause 6, remaining)
Built in F51 where scoped: `../architecture/ads.md` §6.53, `../architecture/intake.md` F51 and `../design-system.md` §§6–7. Earlier F48–F50 ownership remains as recorded above; drill 12 is the independent outcome check.
- A1 「可以投放」 = step counter, not content: zero customer groups still ready (`app/intake/product_onboarding.py:126,413,574-579,798-800`;
  `ProductDoneStep.tsx:139`; `WhoStep.tsx:40-45`). Fix: one content check used by complete() and the ready calculation; refuse empty groups.
- A2 archived product's bundle still ready: `product_onboarding.py:427` ignores status; correct rule in `app/ads/wizard_options.py:118-121`. Fix: derive from `sellable_products`.
- A3 detail 「產品經濟數字」 reads the root product row; money lives on sell-way rows since F43/F45 (`brand_intelligence/repository.py:429,1761-1762`; `app/brand_web/routes_products.py:137,360`).
- A4 old product list endpoint returns archived/half-built rows to pickers (`app/shared/web.py:92-93`; `repository.py:401`; `FreeJobPage.tsx:355-356`; `ads/strategy/CapBlock.tsx:258`).
- A5/A11 no screen links to product detail; archived products and brands have no list, restore only by URL (`ProductCard.tsx:120,129`; `BrandProfilePanel.tsx:168`; `app/dashboard/repository.py:162`).
- A6 candidate 「繼續建檔 →」 creates a product with no confirm (`ProductsPage.tsx:57-61`).
- A7 disabled without reason: `Button.disabledReason` exists but is opt-in (`layout/ui/button.tsx:40-57`); `FreeJobPage.tsx:246,497`; `ConfirmBriefPage.tsx:254,277,307,336`. Fix: derive disabled from the reason string.
- A8 evidence 「改」: Enter submits the step form and jumps (`steps/EvidenceStep.tsx:117-141`; `ProductEvidenceStep.tsx:151-173`).
- A9 store-time rules missing from `app/core/input_rules.py`: ad-set dates inside the campaign window (`plan.py:524-532`); channel quantity ≥ 0
  (`app/orders/channel.py:204`; `routes_api.py:166`); AI key format (`app/main.py:218-222`); one image size cap (brand 10 MB `app/intake/state.py:240`
  vs product 50 MB `routes_library.py:60,81,314`); list price vs price (`product_onboarding.py:325-350`; `repository.py:847,1285`); unit cost 0 vs unknown (`app/orders/repository.py:217`).
- B1 一句話建立 drops platform and cap: form sends only changed values (`NewCampaignPage.tsx:255-261,333-336`), defaults filled only on the structured path (`brief.py:570-581`).
- A14 settings saves show no 已儲存 (`lib/useFormSubmit.ts:19-41`; `settings/shared/SaveButton.tsx:22`); margin card 「%」 stored 0–1 vs step_rate 0–100 (`app/core/rule_cards.py:69-71,87-89`).
- Copy buttons without feedback (c1-10, assets tab / publish step 2): no code root cause found — shared `layout/CopyIconButton` and
  `ads/patterns/CopyField` both render 「已複製」; candidate: `CopyIconButton` shows nothing while `writeText` is pending (`CopyIconButton.tsx:77-78`). Reproduce in a browser first.
- F11 empty/oversize file share one sentence 「檔案超過 50 MiB 或沒有內容，請另建批次」 (`app/ads/user_assets.py:39`). Nit: simplified 「补」 at `app/ads/asset_suggestions.py:364`.

### R7 Long work and session state live only in the browser tab
Built in F51 where scoped: `../architecture/ads.md` §6.53, `../architecture/intake.md` F51 and `../design-system.md` §§6–7. Earlier F48–F50 ownership remains as recorded above; drill 12 is the independent outcome check.
- B3 plan refusals: five rules raise one `delivery_plan_failed`, no reason code, no log, `max_retries=0`, refusal never fed back (`plan.py:243,289-291,420-441`; `routes.py:479`). Same pattern in brief and strategy.
- B4 reload during 展開投放結構／策略: busy state only in React; the running `llm_task` row exists but no read returns it; `adopt_strategy` has no row lock (`app/llm/gateway.py:180,192`; `StrategyTab.tsx:151,159,198-201`; `plan.py:344-348`).
- A10 brand onboarding step lives in sessionStorage, not `?step=`; Back from step 3 → blank 建立品牌; steps 4–6 lose drafts on reload (`IntakeWizard.tsx:77,100,105-106`; only `IdentityStep` uses `useStepDraft`). Product onboarding is the model.
- A12 history 「開始拉 37 個月」 has no done-empty / failed outcome (`HistoryPage.tsx:84,96-97,142`; `app/meta/daily_pull.py:279-282`).
- A13 login: cold invite link says 「登入已過期」, a real expiry says nothing and loses the page (`lib/http.ts:82-95`; `App.tsx:175-176`; `LoginPage.tsx:100-102`).
- B8 raw 「Failed to fetch」: `apiFetch` doesn't translate fetch TypeError; ~8 API files each copy a translation (`lib/http.ts:85`; `lib/useApiRead.ts:24-25`).
- F14 action pressed before the login redirect is silently lost.

## 2. Decisions for `/dig` (each with a recommendation; everything else above is a straight fix)
1. One grading ruler — **recommend**: cleanup and closeout share learning_rank's ordering with sample size shown; drop the 3×cap gate as a hidden blocker for small ad sets (keep "too early" as a label, not as protection).
2. 「留下」 keeps the approved creative — **recommend**: reuse the placement and copy as is; only 換掉 regenerates.
3. Strategy claims — **recommend**: generate the strategy's group/offer/number sentences from the structure and closeout rows (program), LLM writes only the connecting prose.
4. Planner vs capacity — **recommend**: ads per campaign ≤ can_support + explore slots, or the strategy says up front why more.
5. Unreadable launch fields — **recommend**: `readable: False`, confirmed once at approval.
6. Ended campaign — **recommend**: no proposals after end_date; a closeout row instead; open rows stay visible until closeout.
7. Discount family — **recommend**: a registered discount sentence backs 折扣／特價 words, still not 限時 or 買一送一.
8. Budget after expansion — **recommend**: a new total re-splits ad sets with `budget.split` and says so.
9. Margin scale — **recommend**: store 0–100 like step_rate.
Still open from drill 10 (unchanged): carousel in planning while a slot holds one file, calendar audience field, F47 left-outs (channel revenue / 口徑紀錄 / bundle edit-delete).

## 3. After the fixes
Drill 12 with the same ruler (`../drills/drill-10/plan.md` anchors, `../drills/drill-11/plan.md` setup). Reuse `.harness/scratch/drill11/` dispatch files
(they now carry the "never delete files", spare-object and custom-date rules). Report beside drill 10 and 11. Measured time drill 11 ≈ 4 h.
