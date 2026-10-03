# Drill 11 — operator working notes (chronological, 2026-10-03)

Raw notes; `report.md` wins on any disagreement. Screenshots and raw files: `.harness/scratch/drill11/` (local).

## Setup (03:40–03:58 computer clock)
- master 7c6cbdde (F45–F47 merged). Frontend rebuilt. `fake_meta reset`; clock 2026-10-03. Backend `scripts.drill.serve` :8710, worker `scripts.drill.worker` (separate processes, logs in scratch).
- Account `beast.drill11@example.com`. Org/brand: brand `brd_01M3Z37FBMHNWMWTTG6W3NNZHT`. P1 campaign `adc_01M3Z3SZ3REV263XS6YT6RTKK6`.

## P1 (clock 10/03; 阿虎 03:58–04:26 to handoff list)
Measures: 6 ads / 2 groups; offer 4/6 (discount 2, free_shipping 2), false 0; registered sentence written 4/4 (measure v1 said 2/4: free-shipping sentence 「免運」 has no digits — measure fixed); none-leak 0; plan tasks 2 (one 「AI 沒能整理出可用的投放結構」 retry, both succeeded); video 0; pain 6/6.
Blocked placements 2: 「文案寫了「特惠」，品牌資料裡沒有登記這個優惠或背書。」 — the word is part of the registered sell-way name 「超能特惠組」 (to map: claims guard vs sell-way name). 阿虎 renamed to 「三盒組」 to pass; workbench had already accepted the same copy (two guards disagree).
Persona station scores: 註冊9 品牌 7/9/9/7/10/8/9 商品 7/6/7/6/9 Tshirt7 組合6 建活動 8/9/7/6 工作檯6 上傳6 清單6 到平台8.
Detours ≈10 (cap 559→450 in advanced; total not daily; prefilled groups rewritten (「駕車」「高體力工作者」 not in facts); 「創辦人第一手」 evidence removed twice; monthly budget required before approval — went to ads home and found way back). Errors 2 (both with exit). Stalls 0.
Persona notes to map: strategy names three groups, structure has two ad sets (athletes missing); ad names 「咖啡因小錠」 (product is gummy) and 「不怕頻尿」 (persona marked 頻尿 as not-sayable); bundle form shows 「成本 —」; no way to delete a wrongly placed photo; strategy basis 「10/04 更新」 while today is 10/03.
P1 judge (Sonnet): fit mean 1.23 (1.2–1.3); compliance 4 ok / 2 review (「帶著清醒上班」, 「經由口腔微血管吸收」) / 0 reject; tags student×3, worker×3 (no athlete ads).
P1 sim (ROAS / CPA / sales): real dates per-ad 0.79 / 1,272 / 7; real dates group 0.68 / 1,473 / 6; A-window per-ad 1.25 / 798 / 11; **A-window group (drill-10 headline) 0.90 / 1,104 / 8** (drill 10: 0.49).
P1 tail (04:26–04:30): 勾建好 8 (nine separate ticks, no 「全部建好」); readback 5 — 「8 項讀不到」 for ad sets/ads (settings matched) even after 重新讀回; after 「全部標記」 two items 「核對期間來源已更新，保留較新的資料，請再核對」 with their buttons gone until 重新讀回; persona finally marked 「一樣」 himself (not a real match). Timestamp 「10/04 04:28」 at real 10/03 04:28. Overview 9 (「已上架，等平台開始投放」 — F47 S3 works) but 「在投 0 則」「每日預算未知」. Detours 0 in this tail.
Operator P1→P2: load-rows rows_B_1 (42 rows); clock 10/10; ops sync 10/03–10/09 succeeded. P1 mapping agent dispatched.

## P1 defects mapped to code (read-only agent)
| # | Defect | Verdict | Root cause | Code |
|---|---|---|---|---|
| E1 | 「特惠」 in sell-way name 超能特惠組 blocks slot copy; workbench only warns | product (要繞路) | one detector `claims.unsupported`, no exemption for registered sell-way/product names; F45 dropped the name from the offer sentence so nothing backs 特惠; workbench advisory vs slot blocking | app/workbench/claims.py:34,47,190-209,239-241; app/workbench/repository.py:1420; app/brand_intelligence/repository.py:838,849; app/ads/asset_suggestion_policy.py:82-90; app/ads/slots.py:486-496 |
| E2 | readback 「8 項讀不到」 | product by design (manual landing_url per ad set ×2 + material per ad ×6 are never readable; stand-in has every compared field) | readback asks the user to look in Meta for fields no reader proves; 重新讀回 can never clear them | app/ads/handoff_check.py:137-147; app/ads/manual_settings.py:33; app/ads/adapters/meta_read.py:809; app/ads/asset_binding.py:158-190 |
| E3 | 「核對期間來源已更新，保留較新的資料」 and per-item buttons vanish | product race (要繞路) | check() compares entity updated_at before/after; the runtime readback tick upserts the same rows each minute → own worker trips it; stored result drops the unreadable list | app/ads/handoff_check.py:353-355,390-405,423-426; app/ads/external_repository.py:88; app/ads/runtime.py:149-170,300-303; PublishVerify.tsx:128-137 |
| E4 | timestamps one day ahead (10/04 04:28) | **drill tool** | clock.patch_modules replaces the day on a UTC datetime: before 08:00 local every now_utc() stamp is +1 day | scripts/drill/clock.py:61-64 |
| E5 | 「在投 0 則」「每日預算未知」 right after switch-on | drill timing + product gap | count from stored native_status, written while stand-in was PAUSED; no "not re-read yet" wording | app/ads/workspace_reads.py:198-214; scripts/drill/fake_meta.py:550,561,1006-1011 |
| E6 | strategy says three groups, structure has two ad sets | product (面向 1) | only role coverage checked; ≤1 group per ad set, 2 roles → max 2 groups; strategy text unchecked (drill-10 O3 still open) | app/ads/plan.py:243,250-277,456-461; app/ads/strategy.py:298-306 |
| E7 | ad names 「咖啡因小錠」「不怕頻尿」 | product (要繞路／外觀) | plan prompt has no product form and no forbidden claims; names free text, no claims check; 頻尿 not a RISK word | app/ads/plan.py:216-221,400-409; app/intake/product_onboarding.py:984 |
| E8 | bundle rows 「成本 —」 | product (外觀) | products list sell-way brief carries no cost; cost only after server preview | app/intake/product_onboarding.py:376-385; BundlePage.tsx:68-69,104-133 |
| E9 | no delete for wrongly placed intake photos | product (要繞路) | slots replace-only; delete only in library Assets tab | steps/StartStep.tsx:173-236,398; product/WhatStep.tsx:131-190 |
| E10 | first campaign: total not daily; cap default 559 | product as designed; cap now in main section (not advanced) | capDefault prev → own cap → round(break_even) | NewCampaignPage.tsx:71-78,234-236,455-463 |
| E11 | monthly budget gate links to ads home, no way back (drill-10 D3 **still there**) | product (要繞路) | BudgetFitCard link `?budget=edit` with no return target | flow/confirmParts.tsx:325,336-340; MonthlyBudgetPanel.tsx:16,110; AdsHomePage.tsx:103-106 |

## P2 (clock 10/10; campaign adc_01M3Z55SR8M3R0AM0D87HY5FZD; 阿虎 04:31–04:47 to handoff list)
Measures: 5 ads / 2 groups; offer 2/5 (discount), false 0, sentence written 2/2; none-leak 0; blocked 1 (same 「特惠」 false positive, fixed by persona renaming); plan tasks 1; video 0; pain 5/5.
Station scores: 首頁6 成效頁5 停關5 結案8 智庫7 建活動 8/9/8/8 工作檯6 出錯4 上傳7 清單9 到平台9.
Detours 4 (perf advanced looking for per-ad sales; two strategy folds; two 進階：編輯這一組; refilled 「沿用上一期」 fields that looked empty). Errors 1. Stalls 0. Friend actions requested: none — system proposed no stop/pause/cleanup.
Learning: closeout ranks 留下 1 (考前專注 392/sale), 換掉 5 (600, 1,173, 2,212, two zero-sale). P2 strategy reasons cite 1,271.72 / students 6 sales / 392 / office 1 sale = closeout page. Shift: students main, office workers out, athletes test; 70/30.
Persona-found mismatches (to map): perf tab per-ad spend sum 8,095.67 ≠ total 8,902.05; 考前專注 1,005.6 (perf) vs 1,176 (library); three ads over 1,350 still 「資料不足」; home 「今天沒有要決定的事」 at 2.8× cap; home 「少賺約 5,000」 vs ~1,909; dates 10/03 on perf tab / library / publish list, 「觀察期間 09-26—10-02」 「現在結案等於提前結束」; strategy 「國高中第一次段考週」 (facts: university midterms); 「不再採用折扣特價角度」 but 2 discount ads; kept winner's headline rewritten.
P2 judge: fit mean 1.15 (1.05–1.30); kept winner 考前專注 −0.15 fatigue (same creative, near-identical name — rubric penalises reuse even when the system keeps a winner on purpose); compliance all ok; tags fitness×3, student×2.
P2 sim (ROAS / CPA / sales): real per-ad 0.99 / 1,004 / 10; real group 1.39 / 720 / 14; A-window per-ad 0.89 / 1,126 / 9; **A-window group 1.28 / 780 / 13** (drill 10: 0.69).
P2 tail (04:47–04:49): 勾建好 8; readback 6 — 「7 項讀不到」 (= E2 by design), 「全部標記」 passed, no vanishing-button race this time; overview 9. Still 「在投 0 則」「每日預算未知」 (E5); 「近 14 天花費」 09/26–10/09; home month block still shows P1 figures unlabeled; readback time 「10/03 04:47」 at drill 10/10.
Operator P2→P3: load-rows rows_B_2 (35 rows); clock 10/17; sync 10/10–10/16 succeeded 04:49.

## P2 issues mapped to code (read-only agent, replayed triage at 10/10)
**Drill-tool fault found (E4 root):** scripts/drill/clock.py swapped the drill date onto a UTC datetime; the drill ran 03:58–04:51 local (before 08:00), so now_utc() ran one day ahead → triage "last complete day" = drill day instead of the day before (app/ads/triage.py:334) → window 10/04–10/10 past the synced coverage 10/03–10/09 → every ad `needs_resync` = 「資料不足」 (triage.py:549-555), cleanup skipped (triage.py:790-792), no stop/cleanup proposal; perf-tab per-ad sums used 10/04–10/10 (8,095.67; the 10/03 ad spend is exactly 806.38). Drill 10 ran in the evening, so it never hit this. Closeout learning (period_grades over start–end) was NOT affected.
Fixed in the drill tool at 04:55 (swap the date in +08:00 local), backend+worker restarted. P1 and P2 results were read under the fault; 阿虎 had already closed P2 (04:51) and created P3 (adc_01M3Z67VYVQK8M1ZHMEPF0JF0Z) when it was fixed. P3 results (read at clock 10/24) are the first period read with a correct clock.
| # | Symptom | Verdict | Root cause | Code |
|---|---|---|---|---|
| G1 | per-ad spend 8,095.67 ≠ 8,902.05 | drill tool; product weakness: triage window never clipped to campaign start/end, so after day 1 the tab mixes period totals with a trailing window | CampaignDetailPage.tsx:242-252; triage.py:545-556; outcome.py:190-196 |
| G2 | three ads over 1,350 still 資料不足 | drill tool (correct window grades 沒賣出／沒賣出／太貴 2,212) | triage.py:463-483,549-555; external_sync.py:66-69 |
| G3 | 「今天沒有要決定的事」 at 2.8× cap | drill tool + 2 product gaps: home board never shows insufficient_data rows (status.ts:211); closed campaigns are never triaged, open rows auto-resolve at closeout (triage.py:617-622); missing_days counts 28 days before the cutoff, not from campaign start (triage.py:246,258-272) | — |
| G4 | 「今天 10/03」「期間 1 天」「觀察期間 09-26—10-02」「現在結案等於提前結束」 | browser clock (drill) | orgClock.ts:55-58; PerformanceTab.tsx:192,282; ReviewPanel.tsx:20-21; PeriodStatusRow.tsx:67,93,114 |
| G5 | 「10/03 結案」「核准・10/03」 | drill (DB now(), not patched) | closeout.py:195; change_control_launch.py:247 |
| G6 | 「少賺約 5,000」 | product (外觀): 7×559 − 8,902 = −4,989, deducts product cost but label says only 扣掉廣告費 (drill-10 外觀 still there) | home_overview.py:236-242; MonthMoney.tsx:126-146 |
| G7 | 「國高中第一次段考週」 | not a defect: product calendar has 國高中段考 10/12–10/23 (F46) and university midterms 11/09–11/22; only tw_sim assumes October university midterms | calendar_tw.py:58-59; tw_sim.py:57,61 |
| G8 | 「不再採用折扣特價」 but 2 discount ads; kept winner's copy rewritten | product (面向 1／4): strategy prose unenforced; gate covers (group, angle) only; plan refused when available offers go unused; no rule that a kept ad keeps its copy | plan.py:280-291,379-383,431; coordinate_learning.py:240-259; delivery_plan.md:15-16,30-33 |
| G9 | strategy covers 3 groups, structure 2 | product, = E6 | strategy.py:267-300; plan.py:196-204,275-276 |

## P3 (clock 10/17; campaign adc_01M3Z67VYVQK8M1ZHMEPF0JF0Z; 阿虎 04:50–05:04 to handoff list)
Measures: 5 ads / 2 groups; offer 1/5 (discount), false 0, sentence written 1/1; none-leak 0; blocked 0; plan tasks 1; video 0; pain 5/5.
Station scores: 首頁6 成效頁6 停關5 結案8 智庫8 月回顧8 建活動 8/9/7/8 出錯5 (素材頁 「Failed to fetch」 = operator restart, drill) 工作檯6 上傳8 清單9 到平台9.
Detours 3 (strategy folds, ad-set advanced for titles, refill 「沿用上一期」 fields). Stalls 0. Friend actions: none (no proposals — clock fault still affected the P2 read, triage ran 04:50 before the fix).
Closeout P2: 留下 1 (段考前一次備妥優惠價 588/sale), 換掉 4 (訓練前 993／1,004／1,008; 考前專注 3,512). Month review 「有效（只算划算）0 則」「太貴・沒賣出 5 則，花 12,390.24」; sums agree (12,390.24 + 6,554.42 = 18,944.66).
Persona mismatches: strategy 「第 2 群在上一期賣出 13 筆」 (13 = two periods; P2 students 7); strategy cites P1 考前專注 392 though it was 3,512 in P2 and was dropped; perf-tab per-ad 8,582.55 ≠ 10,042.61 (clock fault, G1); 「少賺約 9,000」 (G6); month review titled 「11 月建議」 while content is next period; kept ad copy rewritten every period (G8).
P3 judge: fit mean 1.12 (1.05–1.2); −0.15 fatigue on 段考前一次備妥優惠價 (kept winner) and 訓練前隨手攜帶免沖泡 (headline identical to P2); compliance 3 ok / 2 review (段考 may imply minors; 「補充提神物質」); tags fitness×3, student×2.
P3 sim (ROAS / CPA / sales): real per-ad 1.36 / 737 / 11; real group 1.49 / 670 / 12; A-window per-ad 1.97 / 507 / 16; **A-window group 2.35 / 426 / 19** (drill 10: 1.00).
Three-period sim totals (spend / sales / CPA / ROAS): real per-ad 27,047 / 28 / 966 / 1.03; real group 26,964 / 32 / 843 / 1.19; A-window per-ad 27,024 / 36 / 751 / 1.33; **A-window group 27,061 / 40 / 677 / 1.48** (drill 10 headline 1,375 / 0.73; drill 9 660 / 1.51; A 512 / 2.25).

## P3 closeout (clock 10/24, correct clock; 阿虎 05:08–)
Home now raises 「需要你決定 1 件 花錢沒效…關掉色帶裡紅色的 2 則，每天省約 730 元」 — first proposal of the drill (the clock fix made triage work). Scores: 首頁8 成效頁8 清理提議7 到平台完成（清理）8; detours/errors/stalls 0. Perf tab per-ad 8,102.20 = total (G1 gone with correct clock); per-ad cost per sale shown before closeout.
Persona doubts: proposal closes 段考前一次備妥優惠價 (kept winner two periods, 634/sale, most sales 4) while three 訓練前 ads (~1,000 spend each, 資料不足) stay; 「每日 1,500 撐 1 則」 unclear with 5 running; asking to switch off ads of a campaign that ended 10/23.
Operator (friend): paused 3403617230024, 3403617230025 in the stand-in.
P3 closeout done 05:14 (阿虎 total 03:58–05:14 ≈ 76 min incl. operator waits). Scores: 核對清理9 結案8 學到什麼8 月回顧8; detours/errors/stalls 0. Readback after the friend paused: real read 「已核對，已關閉」.
「下一件」 → 「資料不足，這個活動先不判斷」 page with only 「重新檢查 →」「← 投放中心」 (to map). Closeout P3: 留下 訓練前不用配水的補充方式 337; 換掉 499 / 634 / 1,009 / 2,550 — two of the three 「資料不足、先留」 ads turned out 337 and 499. Three-period: 28 sales, 27,046.86, 966/sale; athletes 9 @ 669, students 18 @ 871, office 1 @ 5,353. Month review sums agree (17,476.1 + 9,570.76 = 27,046.86); 「這個月關掉 2 則」 correct (drill-10 D32 load-rows artefact gone).
Persona verdict: 「敢交一部分，不敢全交」. Top three: (1) silent on stop-loss in P1/P2 — **caused by the drill clock fault (G2/G3), not the product**; P3 with correct clock proposed; (2) readback never reads ad sets/ads (E2, product by design); (3) 「留下」 keeps the name, not the winning copy (G8, product) + per-ad sums ≠ totals in P1/P2 (clock fault, G1) + dates (browser clock).

## 阿虎 totals (parsed from run_1..3.md, incl. error stations)
P1 28 stations avg 7.25 (min 4), P2 17 avg 7.18 (min 4), P3 26 avg 7.58 (min 5). ALL 71 avg **7.35** (drill 10: 6.54); stations < 5: **2** (P1 readback/structure-error 4, P2 「特惠」 block 4; drill 10: 4); five-question all-pass 52/70 = **74%** (drill 10: 77%).
Detours P1 ≈10 / P2 4 / P3 3 (drill 10: 7/3/3). Stalls 0. Operator never touched product data (friend: mirror ×3, pause ×2, clock ×3, sync ×3) — but restarted backend+worker once mid-P3 (drill-tool fix), which produced one 「Failed to fetch」.
Phase 2 started ~05:20: controls 甲 (own account ctl.a.drill11 + read-only on B), 乙, 丙1, 丙2 (B account, own 「<區>備用」 objects, org-level settings only 甲/丙1); faults round 1 (beast.drill11f, retry agent after the first stopped itself on a refused rm); blind judge. Owner-role invites for per-auditor accounts were refused by the permission classifier — not pursued.

## Blind verdict (Sonnet, X=A, Y=B; .harness/scratch/drill11/blind/verdict.md)
Dim 1: A 9 / B 5. Dim 2: A 9 / B 6. Dim 4: A 9 / B 5. Fit: A 1.313 (unchanged A files), B 1.233 / 1.150 / 1.120 = 1.172; B compliance review 4, reject 0.
Judge variance: A's files are identical to drill 10, yet A moved 8/7/9 → 9/9/9 (this judge did not deduct A's video-for-a-photo-only-brand again). Treat ±1–2 as judge noise; the B-vs-A gap is the comparable signal (drill 10 gaps 3/2/6 → drill 11 4/3/4).
Decisive B evidence: P3 reason continues 「考前專注…每筆 392」 though results_2 shows 3,512 and the ad is not in P3; 「上一期 13 筆」 = two periods summed; kept ad re-run with rewritten copy (fatigue laundering); 「小錠」 for a gummy.

## P3 cleanup / closeout mapped to code (read-only agent, triage replayed at cutoff 10/23)
| # | Defect | Verdict | Root cause | Code |
|---|---|---|---|---|
| H1 | cleanup closes 段考前 (634, 4 sales, last period's 留下) and keeps three 訓練前 ads (337/499/1,009) as 「剛開始」 | product (面向 4) | grade gate = spend ≥ 3×cap or (≥7 days and ≥10 sales); the explore ad set's 450/day split over 3 ads (~150/day each) can never reach 1,350 in 7 days → which ads close depends on budget split, not results; cleanup never reads the closeout 留下 | app/ads/triage.py:33-36,404-410,463-483,545-573; app/ads/triage_capacity.py:154,262-278 |
| H2 | 「每日 1,500 撐 1 則」 with 5 running | product (drill-10 M2 **still there**) | can_support = floor(1500/(450×2)) = 1; planner builds up to 3 ads per group and never checks can_support → every period mismatches | triage_capacity.py:49,276-285; CleanupProposal.tsx:84-92,139,177-184; plan.py:50,360,456-469 |
| H3 | proposal to switch off ads of an ended campaign, 「每天省約 730 元」 | product | triage classifies every non-closed campaign incl. ended; no end_date check; saving = trailing 7-day spend ÷ 7 | triage.py:617-622,771-816; triage_capacity.py:183,313; runtime.py:240-257 |
| H4 | 「下一件」 → 「資料不足，這個活動先不判斷」 dead end | product (drill-10 Q1 class **still there**) | nextOpenQueueItem scans all kinds; insufficient_data is never done and not a home DECISION_KIND → home says 1 件, 下一件 jumps to an uncounted row; page offers only 重新檢查 (a sync, cannot fix a sample gate) and ← 投放中心, no 結案 link for an ended campaign | changeFlow.ts:291-300; queue_done.py:10-11,21,42-52; home/status.ts:211; wait/WaitPage.tsx:44-47,100-121,284,322-327 |
| H5 | learning includes under-gate ads (drill-10 L3 fixed by F46) but disagrees with cleanup | by design, conflicting rulers | learning_rank has no sample gate (flags 樣本少); triage uses the gate → 留下 rests on 1–4 sales and flips each period | learning_rank.py:8-15,59-98; coordinate_learning.py:149,240-261 |
| H6 | kept winner's copy rewritten every period | product gap (面向 2／4) | 留下 keeps only coordinates; adopt_strategy creates new ads (name, coordinates, scene, group); new placement → copy regenerated; ranking prompt never sees the approved creative | plan.py:393-396,462-469; coordinate_learning.py:225-232; brief.py:565-567 |
DB: 留下 P1 考前專注 392 (3 sales) → P2 3,512; P2 段考前 588 (6 sales) → P3 634. insufficient_data row raised at every period end (P1, P2, P3).

## Faults round 1 (retry agent, 05:11–05:47; .harness/scratch/drill11/faults/faults.md, 44 PNG; brand brd_01M3Z7DHMMHGJYSF9FSJC4SQA7, campaign adc_01M3Z8BBG2B8DZM5S18AMKD7YM)
(First fault agent stopped itself after a refused recursive delete of a temp folder; nothing tested; account reused.)
| F | Verdict | One line | drill 10 |
|---|---|---|---|
| F1 官網讀不到 | 通過 | reason sentence; 「改網址再讀一次」 keeps data (nit: bad domain reported as 404) | 要繞路 → fixed |
| F2 品牌照壞檔 | 通過 | every bad file named with a reason; 32 MB blocked | 要繞路 → fixed |
| F3 建檔重整／上一頁 | 要繞路 | step-3 reload keeps edits; browser back lands on a blank 建立品牌 form; step-4 typed text cleared on reload | 外觀 |
| F4 權杖填錯 | 通過 | 「這把權杖讀不到任何廣告帳戶：可能填錯…」, correct token connects | 要繞路 → fixed |
| F5 商品頁讀不到 | 通過 | 重試／自己填; retry after fixing URL works | 要繞路 → fixed |
| F6 商品照壞檔 | 外觀 | bad files refused with reasons; 32 MB PNG accepted silently on product photos (brand photos block it) | 要繞路 |
| F7 商品步重整 | 通過 | ?step= in URL; reload/back/forward keep everything | 外觀 → fixed |
| F8 賣法邊界 | 外觀 | 0／negative blocked; 原價 < 售價 saved silently as 「沒有優惠」 | 通過（同一外觀） |
| F8b 組合金額 | **通過** | 「超能特惠組 ×4」 cost blank → 推算 1,440, 打平 1,480, campaign picker 1,480 (推算), cap 1,480 — drill-10 B1 gone | 擋路 → fixed |
| F9 生成中重整 | 要繞路 | reload during 展開結構: button re-enabled, no 「處理中」; tab 「還沒有投放結構」, pressing again → 「已經展開過…不能重新展開」; full reload consistent; no duplicate | 通過 |
| F10 文案被拒 | 要繞路 (incomplete) | no copy edit box found; (a)(b)(c) not done; saw the 「特惠」 false positive, exit 「改這句文案」→保存 recovers in ~4 s | 要繞路 |
| F11 素材格壞檔 | 外觀 | 「檔案超過 50 MiB 或沒有內容，請另建批次」 mixes two reasons (app/ads/user_assets.py:39); fake mp4 → 處理失敗 + 換一張 recovers | 通過 |
| F12 發佈重整 | 通過 | stays; approve disabled with reason + link when month budget unset | 通過 |
| F13 連點 | 通過 | no duplicates (approve needed a second click once) | 通過 |
| F14 登入過期 | 外觀 | no 「登入已過期」; returns to the page but the pressed action silently lost | 外觀 |
Round 1: 15 items (F8b separate): pass 8, defects 7 (blocking 0, detour 3, cosmetic 4). F10 retry requested.
F10 retry (third campaign adc_01M3Z9XAG8MVKFV0SJSJTX9S9Q): only edit entry is 「改這句文案」 on a blocked slot (SlotTiles.tsx BlockedSlot) and 「改文案」 on a waiting slot; confirmed slots cannot be edited → (a) not doable (要繞路). (b) 「買一送一」 on a discount slot (blocked for 「文案沒寫優惠」 — drill-10 P1 「該寫沒寫」 now caught) → 「卡住」 + 「文案寫了「買一送」…沒有登記」, exits 改這句文案／到工作檯換一版／再檢查一次 → 通過 (drill-10 P3 「買一送一放行」 gone). (c) 「治療失眠、提升專注力、醫師推薦」 → only 「醫師推薦」 caught; 治療失眠／提升專注力 not flagged although 食安法 is ticked → 要繞路. Recovery: fix copy → 保存 → 「文案已保存，這一格已確認」 5/5 within ~5 s, survives reload → **drill-10 B3 (slot stuck 處理中 forever) gone**.
F10 verdict: 要繞路 (therapeutic claims not flagged; no edit entry on confirmed slots).
Note on F10(c): 治療／提升專注 ARE in the F34 statutory list (app/workbench/statutory_tw.py:54-70), which by design only reminds (F34 ruling: remind, never block) on three screens; the slot's manual-edit path showed no reminder at all → the reminder does not cover the manual edit path (to confirm).

## Controls 乙 (ctl-b, 05:14–06:08): 215 controls, pass 194, defects 15 (blocking 0, detour 6, cosmetic 9), unchecked 6. File controls/controls-b.md
Detour: zero customer groups still 「可以投放」 (b-07); products list cards only go to onboarding, no screen entry to product detail (b-08); archived product's bundle still listed and 可以投放; detail 「產品經濟數字」 tab disconnected from sell-way prices (b-05); free-creation product dropdown lists a deleted sell-way (b-04); 「建立自由工作 →」 disabled without reason (b-10).
Cosmetic: evidence 「改」 has no save/cancel, Enter saves and jumps to step 4; price 0 no inline error until 完成; breadcrumb 「產品」 vs 「商品」; bundle 「成本 —」 (= E8) and stale red error; /bundles/preview 400 on every edit with console errors and invisible red text; preview-card 「更多操作」「繼續 →」 unclickable; auto-checked pack condition looks clickable; 產出數量 no upper bound (99).
Unchecked 6: 候選卡 「不用了」×5 (destroys shared candidates), AI 再次調研 / paste-back with text (model spend shown), others repeats.
Side effect: 「繼續建檔 →」 on the 典藏組 candidate card created a draft product prd_01M3Z8Z6DJ3PE2FHZP8FBQA5QQ (one click, no confirm).
drill-10 乙 detour items gone: 已存賣法 delete (now exists — a spare sell-way was deleted), 組合 delete/封存 (封存 exists), 查看全部／查看來源 not reported, 確定覆蓋 lock not reported.

## Controls 丙2 (ctl-c2, 05:14–06:10): 232 controls, pass 195, defective 3 (+2 found off-table; blocking 0, detour 4, cosmetic 1), unchecked 34. File controls/controls-c2.md
Detour: C2-01 「一句話建立 → 請 AI 依品牌資料建議」 creates the campaign but drops platform Meta and cap 450 already filled (c2-02); C2-02 budget 0 disables 完成／產生策略 with no reason; C2-03 「照上一期」 → POST plan 502 ×3 「AI 沒能整理出可用的投放結構」, llm_task succeeded but `_validate_reply` (app/ads/plan.py:419-427) rejects the whole reply, 「照預算上限」 works (c2-01); C2-04 publish list 「放不下」 suggests 「改這期總預算」 → saved 4,200 in strategy tab but list still daily 1,500 / 10,500 / 放不下, only per-ad-set budgets in 調整結構（進階） fix it (c2-03).
Cosmetic: unknown review id → 409 instead of 404 (c2-05).
Unchecked 34: whole review flow (no review exists; spare campaign not live), proposal screens only in empty state, change pages read-only. Spare A adc_01M3Z7NWFSAFN9JWSF1WME7NAY (approved, 7 built, not mirrored, daily 600), spare B adc_01M3Z84SFN1M2NK95QT94YRBXR. No rename control on campaigns.
→ Follow-up needed (as drill 10 c3/c4): mirror spare A, load rows, clock 10/28, sync → audit proposals, review flow incl. drill-10 B2 (覆盤「停掉這則」 dead end).

## Controls 丙1 (ctl-c1, 05:14–06:30): 256 rows, pass 222, defective 6 (15 defect lines; blocking 0), unchecked 28. File controls/controls-c1.md
Detour: ad-set custom period 10/20–11/30 saved outside campaign 10/24–10/30 (c1-08; drill-10 V5 class still there); four 複製 buttons no feedback (c1-10; drill-10 cosmetic, now counted detour); /wait 「重新檢查 →」 POST sync 200 but page still 「還沒同步過」, draft labelled 「平台照常投放」 (c1-12); 「改這句文案」 on a 折扣特價 slot still blocked for 「折扣」「限時」 (registered sentence is the only accepted wording — same family as E1); 「選一版文案」 lists every approved copy of the brand, not filtered by product; confirmed slot on a draft campaign has no 換一張／換一版 (c1-13); closed campaign 改預算上限 editor saves (drill-10 T11, by design 2026-09-25).
Cosmetic: home 「還沒有活動」 with three closed campaigns this month (c1-01); broken thumbnails example.invalid (drill stand-in data, no fallback); perf advanced 「這則廣告沒有成效資料」 next to 8,902; overview 「近 14 天花費 未知」 next to 已花費 8,902; 「所有 Campaign」「建立投放計畫」 wording; bid 0 / bad UTM warned but saved; unnamed date inputs; month budget 0 → 409 not 422.
Month budget restored 31,500. Month CSV 27,046.86 / 28 = screen. Unchecked 28: mutating controls on closed campaigns, repeats, settle steps 2–3 (October not over — by design), 結案 (needs a live campaign).

## Controls 甲 (ctl-a, 05:14–06:39; own account ctl.a.drill11 + read-only on B): 454 controls, pass 442, defective 11 (13 lines: blocking 0, detour 7, cosmetic 6), unchecked 1. File controls/controls-a.md, 72 PNG
Detour: AI key 「abc」 saved without format check (a-07); rule-card empty state 「先去建一個品牌」 links to / (RuleCardsSection.tsx:92); evidence card Enter jumps to step 5 (EvidenceStep.tsx:117-119; same as 乙); unit cost 0 accepted → margin 100% (routes_api.py:123-130); channel revenue quantity −2 saved (channel.py:192); history 「開始拉 37 個月的數字」 no feedback when nothing came back (a-66); archived brand has no 「已封存品牌」 list, restore only via URL (BrandProfilePanel.tsx:168).
Cosmetic: cold invite link → login says 「登入已過期」 (LoginPage.tsx:102); settings saves without feedback; margin rule card shows 「%」 but takes 0–1 (rule_cards.py:87); overview card 「一切正常」 while product and ad account missing (drill-10 「有警示待處理／一切正常」 class); channel revenue / 口徑紀錄 no edit/delete (drill-10 V9 still there); report 「稍後再試」 retries immediately and is refused again.
drill-10 甲 items gone: settings 「儲存失敗（狀態碼 400）」, 毛利率 7 accepted, 方案數量下限>上限, 建檔步 1 disabled without reason, 步 3 ← AI 讀網站 resets edits, English 「Invalid login credentials」, 票 09 / hard-soft, 看板 1/3 寬 cut, report regenerate wiping the page (now a red box, not a blank page).
All settings restored. 甲 org bound to stand-in account 900000000000003 (same token as the fault account).

## Controls tally (round 1, four areas)
甲 454/442/11/1, 乙 215/194/15/6, 丙1 256/222/6/28, 丙2 232/195/3/34 → **1,157 controls, pass 1,053, defective 35, unchecked 69**; clicked 1,088, pass rate of clicked **96.8%** (drill 10 round 1: 886 inventoried, 727 clicked, 658 pass = 90.5%, unchecked 159). Blocking 0 in round 1. Follow-up 丙3 running (proposals, review incl. drill-10 B2).

## Controls 丙3 follow-up (ctl-c3, 06:28–; spare campaign A adc_01M3Z7NWFSAFN9JWSF1WME7NAY mirrored, rows ×3 spend for 10/24–10/27, clock 10/28)
Operator (friend): paused 3403617230035, 3403617230036; edit-copy 3403617230036.
**drill-10 B2 gone:** review 「停掉這則」 → 「建立暫停提議 →」 → propose/pause?from=review → approve → handoff (works from 進階→開始本次檢討; review/:entityId opened by hand says 「找不到…檢討提議」 = expected, links exist only for live queue rows).
| # | Defect | Verdict | Root cause | Code |
|---|---|---|---|---|
| C3-D3 | review 「換一張圖」 → material 「建立新廣告提議 →」 always disabled 「找不到這則廣告目前所屬的投放組」 | product; **要繞路 with a blocking-candidate flag**: the review direction is a dead end for every system-built campaign; a detour exists (素材分頁 → 進階 → 素材安排與人工交接 → new ad) but carries no replace/review link, so the old ad is not proposed for pause | ad-set lookup only in campaign.external_view, null unless origin=imported; backend handoff_new_ad and handoffRead.destinations already have the data | MaterialStepPage.tsx:60-65,137,265,317; app/ads/repository.py:814-817; handoff_data.py:231-245 |
| C3-D1 | pause confirm reason always 「花到上限 3 倍的錢，還一筆都沒賣出」 (ad had 2 sales at 1,294) | product (要繞路: wrong reason stored) | buildPauseDraftItem default PAUSE_REASON for every pause entry; real grade in pauseView.triage | changeFlow.ts:144,168; ConfirmPage.tsx:310; confirmParts.tsx:75,79,91 |
| C3-D2 | review copy: clearing 新標題 passes; confirm/handoff/verify show 「—」 and 複製標題 copies "" | product (要繞路): approval keeps the title, but the screens tell the friend to blank it; verify would then flag deviated | CopyPage.tsx:253-261,475; change_control_data.py:250-259; confirmParts.tsx:190; HandoffPage.tsx:296,302 |
| C3-D6 | /wait paints 7 days with data, 「最近 7 天都有資料」, rows only 10/24–10/27 | product (要繞路) | coverage = requested sync range, not days with rows nor campaign dates; headline is a fixed string (same family as G3 missing_days) | WaitPage.tsx:118,271-272; external_sync.py:67-69,484; triage.py:258-284 |
Also: cosmetic D5 unnamed source-card buttons, D4 blank pause 主打 area 1–2 s, D8 deferred proposal still reachable by URL, D9 409 on re-save without saying what was chosen; overview 「沒有要決定的事」 while home says 1 件 until sync.
丙3 final (06:28–06:57): 74 rows, pass ~60, defects 5 (auditor rated D3 blocking; operator rates 要繞路 + blocking-candidate flag, see table), unchecked: propose/budget (no 划算 ad), approve cleanup, ~33 repeats on material page. After the friend acted: three verify pages succeed 「這則廣告已經關閉」「文案和你核准的一樣」; learning sentences written; home count 0; 「用現成素材 → 上傳素材 → 加入此活動」 works.

## Faults round 2 (fault11c; operator stopped the worker by PID ~06:58, restarted ~07:13)
W1 product prefill with worker stopped: 通過 — within 5 s red banner 「背景程式停了：這件工作還排著，已填的資料沒丟。重新啟動行銷系統後會自動接著做。」, top bar 「背景程式停了・工作還排著」, bell 「排隊 1 件｜讀取商品頁」, form still hand-fillable (drill-10 W1 silent → **fixed by F47 liveness notice**).
W2 strategy/structure: 通過 (not worker-bound; banner shown throughout).
W3 copy generation: 通過 with cosmetic — same banner + 「再檢查一次」; each cell still says 「自動更新，不用重整」 next to the 「停了」 banner (drill-10 W3 silent → fixed).
W recovery: W1 通過 (prefill completed, banner gone, no mention it had stopped); W3 通過 (banner gone, cells flip to 「等你：到工作檯選定一版文案 →」 within ~1 min without reload; nothing lost). Meta outage switch on (meta_fail='*').
M1-a connections during outage: 外觀 — 「讀取失敗｜平台無法讀取此資料（代碼 2）。；…等 4 天 讀不到」 with 重新讀取／查看連線 exits; internal code and 「。；」, no 「稍後再試」 (drill-10 R6 「沒有重新讀取按鈕」 → fixed).
M1-b pixel on publish step 1: 通過 — 「像素清單暫時讀不到…像素 ID 請手動填在下面」, input usable (drill-10 R5 disabled input → fixed); nit: no retry button.
M1-c readback on the fault account's built campaign: 要繞路, silent — 「更新平台候選」 → forever 「來源讀取已排入，稍後按「重新讀取」查看候選」; three retries show no error; bell 「失敗」 count unchanged (job counted done); only exit is finding 「進階：手填平台識別」 (to map).
M2 change token during outage: 通過 — 「Meta 暫時讀不到（代碼 2），這把權杖還沒驗證、沒有存。請稍後再試。」 (drill-10 R4 → fixed).
Outage switch cleared ~07:26 (meta_fail emptied).

## Last mapping (read-only agent)
| # | Defect | Verdict | Root cause | Code |
|---|---|---|---|---|
| M1-c | readback 「來源讀取已排入…」 forever | product (要繞路, silent) | frontend drops the returned job and shows a fixed sentence; worker writes read errors into task JSON so the job ends partial/succeeded (bell never counts 失敗); list task has no campaign_id so nothing campaign-scoped records it; "0 candidates" never shown | ManualHandoffPanel.tsx:116-122; external_routes.py:174-190; external_sync.py:542-595; background/__init__.py:417-421 |
| N1 | 「這期要花 6,000」 for a 10,500 period | product (數字沒標明, 面向 8) | October's share only (1,500 × 4 days to 10/31), label never says so | month_budget.py:217-227; change_control_launch.py:159-186; confirmParts.tsx:280,320 |
| N2 | closed campaign 「近 14 天花費 未知」 next to 已花費 8,902 | product (外觀) | window anchored to today, not the campaign's run; coverage gap → null | workspace_reads.py:95-121; home_overview.py:114-115 |
| N3 | home 「還沒有活動」 with three closed campaigns | product (外觀) | campaigns block skips every closed campaign, empty state cannot say "all closed" | home_overview.py:502-504; CampaignRows.tsx:82-84 |
Prefill check: 「駕車」「體力」 appear in all four product pages of the frozen site copy → not fabrication (as drill 10 D16).
Faults total: round 1 15 items (pass 8) + round 2 W1, W2, W3, M1 (a/b/c as one item → defect, 要繞路 because of M1-c), M2 → 20 items, pass 12 (60%), defects 8 (blocking 0, detour 4: F3, F9, F10, M1; cosmetic 4: F6, F8, F11, F14). Silent failure 1 (M1-c). No data destroyed.

## Post-drill mapping B (read-only agent, for the fix handoff)
| # | Defect | Root cause | Code |
|---|---|---|---|
| B1 | 一句話建立 drops platform/cap | form sends only changed values; server fills defaults only on the structured path (`checked is not None`) | NewCampaignPage.tsx:255-261,333-336; app/ads/brief.py:570-581 |
| B2 | 「改這期總預算」 saved, publish list unchanged | ad-set daily budgets computed once at 展開投放結構; select_scenario writes budget_planned only and does not refuse after expansion; month fit/approval read SUM(ad-set daily) (approval amount uses budget_total or daily — split again) | plan.py:360; strategy.py:568-621,645; change_control_launch.py:137,227; repository.py:1138 |
| B3 | 照上一期 → 502 ×3 | NOT scenario-specific; five rules raise the same `delivery_plan_failed`, no reason code, no log, max_retries=0, refusal never fed back; likely roles check | plan.py:243,289-291,420-441; routes.py:479 |
| B4 | reload during 展開結構／策略 | busy state only in React; llm_task 'running' row exists but no read returns it; adopt_strategy reads campaign without row lock | gateway.py:180,192; StrategyTab.tsx:151,159,198-201; plan.py:344-348 |
| B5 | confirmed slot has no copy edit; copy picker brand-wide | copy write refuses confirmed placements; ReadySlot has no copy action; material_options takes no sell-way | slots.py:656,689-690; SlotTiles.tsx:118-121; workbench/__init__.py:59 |
| B6 | 食安法 reminder missing on slot manual edit | statutory_note IS computed (asset_suggestions.py:353) but `notes` never stored nor returned to the slot | asset_suggestions.py:353,420,666 |
| B7 | /wait 重新檢查 on a draft | no native root → refreshes account listing only, campaign sync stays never; chip 「平台照常投放」 hard-coded | external_routes.py:174-190; repository.py:519-521; WaitPage.tsx:117,284 |
| B8 | 「Failed to fetch」 | apiFetch doesn't translate fetch TypeError; ~8 API files have their own copy | lib/http.ts:85; lib/useApiRead.ts:24-25 |
| B9 | 「11 月建議」 | heading = shown month + 1 | MonthReviewPage.tsx:160-161 |
| B10 | 「在投 0」「每日未知」 after switch-on | counts from stored native_status; nothing marks "switched on, not re-read" (reported_at exists) | workspace_reads.py:211-214; home_overview.py:414-421; handoff_data.py:255 |
| B11 | readback asks to check unreadable fields | no `readable` flag on manual settings / material | manual_settings.py:12-58; change_control_launch.py:22-24,119-125; handoff_check.py:137-147 |
| B12 | readback race | upsert always sets updated_at=now() even when nothing changed | external_repository.py:87-88; handoff_check.py:61-69 |
| B13 | 「特惠」 in sell-way name; 「折扣」「限時」 on a discount slot | product/sell-way names never passed to `unsupported`; offer word backed only by the exact word in the sentence | workbench/__init__.py:166-169; claims.py:47-54,190-209; asset_suggestion_policy.py:82-90 |
Nit: simplified 「补」 in app/ads/asset_suggestions.py:364.
