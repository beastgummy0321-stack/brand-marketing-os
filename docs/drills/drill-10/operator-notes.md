# Drill 10 — operator working notes (chronological, 2026-10-01)

Raw notes kept for the fix sessions: per-period measures, every read-only root-cause mapping table (file:line), audit tallies as they arrived.
Where this file and `report.md` disagree, `report.md` wins (later corrections: 「這個月關掉 0 則」 and the refused 「3 天後／7 天後」 are drill artefacts; control-audit C1 defects 4 and 15 were withdrawn; fault tally is 20 items / 6 passed).
Screenshots and raw audit files: `.harness/scratch/drill10/` (local, not in version control).

---

# Drill 10 working findings (operator notes; feeds report.md)

IDs: org org_01M3VMJSH3PH2YNC9Z18ZRZXCS, brand brd_01M3VMMJET4BP0ZVB7AQR9M04J, P1 campaign adc_01M3VNEQ8F371CAWYEQDV4WYJN.
阿虎 agent id ab960cd3ec527bc6f (resume with SendMessage). Clock: P1 10/03, P2 10/10, P3 10/17.

## Timing (real clock 2026-10-01)
- Prep 19:10–19:45. 阿虎 P1 19:45–20:18 (32 min) + readback 20:19–20:21. Judge P1 80 s. P2 started ~20:27.

## P1 measures (measure.py)
4 ads / 2 groups, all ready, 0 blocked. Offer 1/4 (bundle), registered sentence written 1/1, offer=none leak 0, plan refusals 0 (1 delivery-plan task), video 0, pain 4/4.
Fit mean 1.30, compliance all ok. Sim real window ROAS 0.99 (CPA 1,013, 10 sales); A-window 0.49 (CPA 2,022, 5 sales).
Sensitivity (each ad under its own audience key, split_plan.py): A-window 0.89, real window 0.60. Sales per period 5–10 → ±1–2 sales moves ROAS 0.1–0.2 (noise).
Tool artefact: export_plan gives the group the FIRST ad's audience_key and tw_sim reads only the group key (scripts/drill/export_plan.py:38-41,62; tw_sim.py:100). Same tool since drill 7, so headline stays comparable; report both.

## 阿虎 P1 station scores
註冊9 品牌1:8 2:8 3:9 4:8 5:10 6:7 7:9 商品1:8 2:7 3:7 4:6 5:9 Tshirt8 組合6 建活動1:6 2:7 3:7 4:7 5:5 6:5 7:8 8:6 9:5 10:4 → 25 stations.
繞路 7、出錯 5（都有出口，除了總覽「在投 0 則」）、卡住 0、停止條件 0。

## P1 defects mapped to code (two read-only agents, 2026-10-01)
| # | Defect | Level | Root cause | Code |
|---|---|---|---|---|
| D1 | 素材格「處理中・自動更新」其實在等使用者到工作檯選定文案＋核准整包 | 要繞路 | readiness() = in_progress whenever pack exists but not approved; no "waiting for you" state | app/ads/assets.py:245-250; app/ads/slots.py:235-242; frontend/src/components/ads/workspace/AssetsBody.tsx:46,169-182 |
| D2 | 「設定 N 月月預算 →」帶到首頁不是表單；無預設值 | 要繞路 | hard-coded budgetHref to ads home; form only opens from local state; panel starts empty | frontend/src/components/ads/publish/PublishList.tsx:124; flow/confirmParts.tsx:285-288; home/MonthMoney.tsx:65,86,90-95,211; MonthlyBudgetPanel.tsx:24-25,39,58; app/ads/month_budget.py:467,486-487; change_control_launch.py:159-186 |
| D3 | 像素清單讀不到（代碼 100） | 演練替身 | stand-in lacks adspixels edge | scripts/drill/fake_meta.py:210,314-324 |
| D4 | 平台「未設定 猜的」但建立頁下拉顯示 Meta | 要繞路 | form shows default platform but only sends it when changed; server stores none → source=system | frontend/src/components/ads/NewCampaignPage.tsx:195-197,213; app/ads/brief.py:24,448-450,523-524,566 |
| D5 | 每筆上限預設打平 559、只能在進階改；只問總額沒有每日 | 要繞路 | cap default = sell-way cap_per_sale else breakeven | app/ads/wizard_options.py:26,130-145; brief.py:548-549; NewCampaignPage.tsx:201-210,398,409 |
| D6 | 商品列表多五張「AI 讀到了，還沒確認」重複卡，無法關掉 | 要繞路 | candidates = scan products minus top-level product names (exact); sell-ways/bundles don't suppress; no dismiss | app/intake/product_onboarding.py:396,400,404-413; frontend/src/components/intake/product/ProductCard.tsx:164-176; ProductsPage.tsx:51-58,94-100 |
| D7 | 「查看策略依據」只有原始時間戳、無內容 | 外觀 | basis rows carry only {id,label,updated_at}; raw ISO printed | frontend/src/components/ads/StrategyTab.tsx:379-434; app/ads/strategy.py:78,140,545-546 |
| D8 | 讀回 26 項讀不到 | 演練替身（欄位）；矛盾句是產品 | mirror builds adsets/ads without settings/creative; nMatch excludes self_confirmed while title says 都核對過了 | scripts/drill/fake_meta.py:451-463; frontend/src/components/ads/publish/PublishVerify.tsx:69-70,78,85,87-90; patterns/SettingsPieces.tsx:47 |
| D9 | 總覽「在投 0 則」「下次同步 02:02」無日期；頂列「1 個活動讀取異常」沒原因（草稿／從沒同步也算異常） | 要繞路（在投 0 是替身建 PAUSED） | status_summary counts never/syncing as failing, returns only a count; next sync = job.updated_at + 6h printed HH:MM | app/ads/status_summary.py:23-29,40-44; app/ads/repository.py:490-534; app/ads/workspace_reads.py:183-186,234; frontend/src/components/ads/workspace/OverviewBody.tsx:46,285; components/layout/Topbar.tsx:44-46 |
| D10 | 選了帳戶還要另按「指定給這個品牌」 | 外觀 | separate bind button | frontend/src/components/intake/steps/MetaConnectPanel.tsx:151,159-165 |
| D11 | 只有照片的品牌仍必須選一個圖片提示詞才能完成素材組 | 要繞路 | pack builder always requires {copy:1,image_prompt:1} | app/ads/assets.py:113-120; app/workbench/repository.py:653-664,1470; frontend/src/components/workbench/SetStudioPage.tsx:420,435,534 |
| D12 | 4 則只有 1 則帶優惠（策略頁寫「這期會用」） | 設計如此 | gate = any(); prompt says others may be none | app/departments/ads/delivery_plan.md:21-24; app/ads/plan.py:127-128,314-317 |
| D13 | 優惠句把商品全名貼進句子；免運表達不了（drill 9 #9 未修） | 要繞路 | sentence template f"{name}優惠價…"; POLICY_TYPES only brand-wide shipping | app/brand_intelligence/repository.py:829-842,845-874; app/core/vocab.py:63-78 |
| D14 | 輪播格只放 1 張圖就「已確認」 | 擋路候選（上架清單寫輪播、實際單圖；未確認 publish builder） | no image-count rule for carousel | app/ads/slots.py:134-149,388-423,483-535; app/ads/assets.py:113-115 |
| D15 | 探索組（運動員）裡的廣告文案在講開會 | 要繞路 | copy prompt gets coordinates + scene, not the customer group; ads_ad has no customer-group column | app/ads/assets.py:98-150; app/workbench/prompts.py:35-79; app/ads/plan.py:161-168,332-347 |
| D16 | 預填「長時間駕車」不是編造（官網四個商品頁有寫）；創辦人故事當證據是設計（founder_voice） | 不是缺陷 | — | scripts/drill/site/products_*.txt:2; app/core/vocab.py:30-37; app/intake/ai.py:117,126 |
| D17 | 組合用「數量 1 的賣法」當單件價／成本（典藏組顯示單件 100・成本 25＝體驗包） | **擋路（金額錯，潛伏）**：成本都填時打平線會高估約 1,140 | qty means "× one unit" but the model cannot tell a 3-piece trial pack from a box | app/intake/product_onboarding.py:1114-1124,1153-1168,202-204; app/brand_intelligence/repository.py:1169-1184,1187-1227; app/ads/budget.py:36-51; frontend/src/components/intake/product/BundlePage.tsx:380-383 |
| D18 | 策略文字「及其他三群」、國慶句空話 | 外觀 | strategy validator checks shape only | app/ads/strategy.py:267-311 |
| D19 | 同一廣告組裡的廣告受眾 key 不同（cold_unaware／cold_problem_aware 混在一組） | 待判 | LLM picks audience per ad freely; no rule | app/departments/ads/delivery_plan.md:9,33-34,49-51; app/ads/plan.py:161-168,226; app/ads/launch_view.py:63-99 |
| D20 | AI 讀網站寫約 1 分鐘、實際約 3 分鐘；照片一次只能傳一張；T-shirt 售罄仍「可以投放」（庫存不在範圍） | 外觀 | — | — |

## P2 (clock 10/10; campaign adc_01M3VQ82SSHYBT6JSAFRZ0DVC0; 阿虎 20:23–20:52 = 29 min incl. one operator pause)
Operator: paused 3 ads in stand-in after 阿虎 approved cleanup (he pressed 我都做完了 before the friend acted → 尚未回報, score 3).
Measures: 6 ads / 2 groups, all ready, 0 blocked; offer 2/6; registered sentence written 1/2 (「通勤開會免配水補給組合」offer=bundle, copy has no offer sentence, still ready → F44 gap: coordinate says offer, copy omits it, nothing catches omission); none-leak 0; plan refusals 0; video 0; pain 6/6.
Station scores P2: 首頁7 成效6 清理提議7 核對3 核對續7 結案6 建活動7 理解7 策略7 結構6 素材5 上架清單7 (+ readback pending).
Numbers: P1 spend 10,132.36 / 10 sales / 1,013 / ROAS 0.99 equal on home, perf tab, overview, cleanup proposal (drill 9 #3 not reproduced). Only oddity: perf tab 「今天 10/01」「期間 0 天」 (browser date vs drill clock = drill artefact; check).
P2 new defects:
| D21 | 清理核對頁：朋友未關時「尚未回報」，按「下一件 →」到「第 1 件／共 2 件」「核准清理（關 0 則）」灰頁；關完後同一連結變「找不到這則廣告的停損提議」 | 要繞路 | to map |
| D22 | 結案說「在品牌智庫留一條學習」，品牌智庫找不到；學習只在下一期策略依據裡（drill 9 #12 仍在）；結案後沒說下一步是排下一期 | 要繞路 | to map |
| D23 | 學習把每筆 555（最好、帶優惠、剛好打平）與 1,643–1,769 一律標「太貴」；策略「所有座標都未划算、不沿用任何座標」→ 贏家沒被留下（drill 7 紅燈「結案學習不分好壞」同類） | 面向 4 主要扣分 | to map: verdict thresholds |
| D24 | 學習寫「格式：輪播」但實際只傳單圖（D14 同源） | — | D14 |
| D25 | 「通勤開會免配水補給組合」標組合優惠、文案無優惠句 | 要繞路（F44 規則只擋「寫了不該寫的」，不擋「該寫沒寫」） | to map: validate_claims offer_key |
| D26 | 第二期 6 則但只有 4 張照片；與被關的兩則主題幾乎相同（備考、訓練前）再排一次 | 面向 4 | plan gets learnings but no rule against re-running closed themes |
| D27 | 每筆上限 450、平台 兩期都要重填（D4/D5 重複；drill 9 #10 仍在） | 要繞路 | D4/D5 |
| D28 | 第二期上架寫「首次上架」 | 外觀 | to map |
| D29 | 策略說「資料沒有顯示假日會影響」，行事曆沒進文案（drill 9 #6 仍在） | 面向 1 | — |
| D30 | 「運動前快速入口補給」文案約 3 分鐘才生成（等待，無錯誤） | — | — |

## P2 sims / judge
Fit mean 1.02 (0.95–1.05), all ok; −0.15 fatigue laundering on all six; no week-specific hook (國慶、期中考). Sim real window 1.39 (CPA 720, 14 sales); A-window 0.69 (CPA 1,445, 7 sales); per-ad-audience sensitivity A-window 0.79.

## P2 defects mapped to code (read-only agent)
| Q | Defect | Root cause | Code |
|---|---|---|---|
| D23 | 學習不分遠近：555 與 1,769 同一桶「太貴」；模型拿到的壞廣告清單沒有每筆成本、偏貴的兩邊都不列、沒有「都沒划算時留最不差的」規則 | one rule vs cap only (划算 ≤T, 偏貴 ≤1.2T, 太貴 >1.2T); scoreboard bad lines carry label+coordinates only; both prompt rules key on a 划算 ad | app/ads/triage.py:49-57,407-419,426-446; frontend/src/components/ads/patterns/MoneyTag.tsx:9-15; app/ads/closeout.py:173,183; app/ads/coordinate_learning.py:160-220,287-291,349-353,295-316; app/ads/strategy.py:455-463; app/ads/plan.py:278,290; app/departments/ads/strategy.md:28-29; delivery_plan.md:14-16 |
| D24 | 學習的格式＝規劃的 format_key，不看實際上傳 | planned coordinates treated as fact | app/ads/live_creative.py:145-159,162-183; coordinate_learning.py:172,207; assets.py:113-115 |
| D22 | 結案視窗說「在品牌智庫留一條學習」但品牌智庫不顯示；getAdsLearnings 沒人呼叫；結案後沒有「排下一期」動作（進度條連到月回顧） | learning_ledger has no owner-visible view | frontend/src/components/ads/CloseCampaignDialog.tsx:150; lib/adsLearningsApi.ts:24-28; detail/PeriodStatusRow.tsx:96-99,124-125; app/ads/campaign_stage.py:23-24; workspace/WorkspaceHead.tsx:34 |
| D21 | 清理「下一件」指到空頁／關 0 則 | cleanup row + (inferred) insufficient_data row share triage=campaign_items[0]; nextOpenQueueItem has no branch for that kind → /propose/pause/<first ad>; ConfirmPage matches cleanup row by entity id → empty tick list. 「尚未回報」= pending covers both never-reported and platform-unchanged | app/ads/triage.py:698-705,769-776,855,868; frontend/src/components/ads/home/status.ts:211-232; flow/changeFlow.ts:261-283; flow/ConfirmPage.tsx:118-128,143-144,161,422-428,484-485,504,614; flow/CleanupVerifyRows.tsx:5-17; app/ads/change_control.py:463-468; change_control_verify.py:124-127 |
| — | 成效分頁「今天 10/01」「期間 0 天」 | 演練才有（前端用瀏覽器時鐘 orgToday，忽略 /me 的 org.today） | frontend/src/lib/orgClock.ts:55-58,73-80; detail/PeriodStatusRow.tsx:23-28 |
| D28 | 「首次上架」寫死，第二期也這樣叫 | hard-coded | frontend/src/components/ads/PublishPage.tsx:38; publish/PublishFlow.tsx:83 |
| D25 | 標了優惠的廣告文案沒寫優惠也放行 | only a prompt line (_OFFER_CARRY_LINE); validate_claims/asset confirmation only reject, no positive check; ads.md §6.48 "enforced" overstates | app/workbench/claims.py:108-109,124-126,148-180; app/ads/asset_suggestion_policy.py:73-105; docs/architecture/ads.md:1867-1870 |
| D26 | 規劃不知道有幾張照片；被關的廣告只以「太貴」座標進來，主題（scene／名稱）不是座標 → 換一個 hook 就能重排同主題 | prompt-only rule, no program gate | app/ads/plan.py:35-36,77-98,254-294; delivery_plan.md:14-16; coordinate_learning.py:349-353 |
| D31 | 首頁「照現在速度月底會超出」「估計少賺約 5,000」公式不在畫面上；推估假設整月持續花（活動 10/09 已結束） | earn = Σ(purchases×break_even − spend); projected = spent/data_days×days_in_month | app/ads/home_overview.py:86-94,237-242,321-323; frontend/src/components/ads/home/MonthMoney.tsx:110-112,132-135,182; patterns/PaceChart.tsx:40-43,57-59 |

## P3 so far (clock 10/17)
P2 numbers equal across home / perf tab / per-ad sum (10,081.04, 14, 720, 1.39); month 20,213.40 / 24 / 842 equals both periods summed.
D32 月回顧「這個月關掉 0 則」（上一期同頁寫 3 則）→ 數字前後不一（to map: month_summary closed count）。
D33 清理提議「每日 1,500 撐 1 則」卻留 3 關 3、「還多 2 則放不下」算不通（to map: cleanup capacity rule）。
D34 帶優惠那則列「資料不足」留著、沒寫賣幾筆。
Operator paused 3 P2 ads (3404146330015/14/16) at 阿虎's cleanup handoff (he waited this time).

## P3 (clock 10/17; campaign adc_01M3VRZ7BKY8GCW299E3PYYBK2; 阿虎 20:58–21:21 ≈ 22 min incl. pauses)
Measures: 6 ads, all ready, 0 blocked; offer 2/6, sentence written 2/2; none-leak 0; plan refusals 0; video 0; pain 6/6. Fit mean 1.11 all ok (5 of 6 −0.15 fatigue).
Three-period F44 totals: 16 ads, 5 with offer, 4 wrote the sentence, 1 omitted, 0 leaks, 0 blocked slots, 0 plan refusals.
Station scores P3: 首頁7 成效6 月回顧7 清理提議5 核對8 結案6 建活動7 理解7 策略7 結構7 素材5 上架清單7 勾建好6 讀回5 總覽4.
P3 learning: only 3 rows, all 太貴 (717/726/1,099); the 3 資料不足 ads (incl. the offer ad) never enter learning; P1's 555 winner gone. Reasons cite 717/726/1,099 and 720.07 = perf page. Budget split 65/35 → 70/30; six new names. Calendar: 「期間沒有登記的假日、考季」 (期中考 10/12–10/23 not in calendar data; drill 9 #6).
D35 月預算剩 786.6 只寫「放得下」，沒提醒下半月沒預算（外觀）。D36 重用照片時「同一張圖，文案不同／換一張」看不懂（外觀）。

## Sim totals (tw_sim; simulated, ranks two schedules only)
A:            0.81 / 2.00 / 4.27 → total ROAS 2.25, CPA 512 (56 sales, spend 28,673)
B real dates: 0.99 / 1.39 / 0.50 → total 0.96, CPA 1,044 (29 sales, spend 30,288)
B A-window:   0.49 / 0.69 / 1.00 → total 0.73, CPA 1,375 (22 sales)   ← headline, same tool as drills 7–9
B A-window, per-ad audience (split_plan.py): 0.89 / 0.79 / 1.19 → total 0.96, CPA 1,043 (29 sales)
B drill 9 A-window: 1.40 / 1.37 / 1.83 → 1.51, CPA 660 (37 sales, spend 24,417)
Why lower than drill 9 (hypotheses to state, not proven): (1) export gives each group the first ad's audience key → cold_unaware ×0.5 CVR on every group in all three periods; (2) fit dropped 1.30 → 1.02 → 1.11 on fatigue-laundering deductions; (3) 6 ads per period split the budget; (4) 5–14 sales per period = noise ±0.1–0.2 ROAS.

## Blind verdict (Sonnet judge, X=A, Y=B; docs/drills/drill-10/blind-verdict.md)
Dim 1: A 8 / B 5. Dim 2: A 7 / B 5. Dim 4: A 9 / B 3. Fit means A 1.313 (19 ads), B 1.122 (16 ads); all compliance ok.
Key evidence: B dropped P2's best ad 「備考時刻不打斷讀書」(CPA 290, ROAS 3.44 — it sat in 資料不足 and never entered learning); B re-ran the three themes it had just cut under new names; B never used 國慶/期中考 (「沒有登記的假日、考季」); B P2 one offer-labelled ad without offer copy; 「提神」 wording in B P2 title / P3 ad name. A planned 4 video ads though the brand only has photos and wrote a shipping promise not in the facts (「今天下單，連假後出貨就寄到」) → A dim 2 = 7.
Dim 3 (formula in plan): A total CPA 512 → 7–8, trend up +1 → 8. B total CPA 1,375 (headline) / 1,043 (per-ad audience) → 0–2 band, trend up +1 → 2.

## 阿虎 totals (parsed from run_1..3.md)
P1 24 stations avg 7.12 (min 4), P2 15 avg 6.00 (min 3), P3 18 avg 6.22 (min 4). ALL 57 stations avg 6.54; 4 stations < 5 (三次「活動總覽」4 分＋清理核對 3 分); five-question all-pass 43/56 = 77%.
Detours P1 7 / P2 3 / P3 3. Errors with exit: P1 5, P2 5, P3 4. Stalls: 1 (P2 cleanup verify before friend acted). Stop conditions hit: 0. Three closeouts done (third at clock 10/24). Operator never touched product data (friend role only: mirror ×3, pause ×6, clock ×3, sync ×3).
阿虎 time: P1 19:45–20:21 (34), P2 20:23–20:55 (~30), P3 20:58–21:29 (~27) ≈ 91 min total.
Worker log P1–P3: 672 jobs, all Success; 「找不到工單」0 次（16 組文案都生成）.
Numbers: every period's spend/sales/CPA/ROAS equal on home, perf tab, overview, cleanup proposal, month review; month total 30,287.66 / 29 / 1,044 = sum of periods. Mismatches: 月回顧「這個月關掉 0 則」(6 closed); home row 2,014 vs perf 2,015; learning 格式：輪播 vs single photo.
P3 closing: reject cleanup — 「暫緩」 cannot be saved (「7 天後」 looks selected but is not; 3 天後 also fails; only 拒絕 saves) → D37 (to map; maybe drill clock). After closeout no next action; learnings visible only in next plan's 策略依據.
Persona verdict: 「不敢全交，只敢交一小部分」.

## Phase 2 (started ~21:35): controls agents ctl-a/b/c1/c2 + fault agent fault10; backend+worker restarted (worker2.err); clock 10/24.
Operator still owes after they finish: meta_fail switch test (替身回錯誤), worker-kill ×3 (AI 預填／規劃／文案生成中), then stop everything.
Draft scores so far: dim1 A8/B5, dim2 A7/B5, dim3 A8/B2, dim4 A9/B3, dim5 B6, dim7 B6 (avg 6.54, 77%, 4 stations <5), dim8 pending bundle check, dim6/9 pending.

## P3 defects mapped to code (read-only agent)
| # | Verdict | Root cause | Code |
|---|---|---|---|
| D32 月回顧「關掉 0 則」 | **演練工具造成，不是產品缺陷**：fake_meta load-rows 把品牌所有物件設回 ACTIVE（含剛關的），下次同步就翻回、不再算「已關」 | count = entities whose status_changed_at in month AND still closed | app/ads/month_summary.py:205-217; app/ads/external_repository.py:74-90; scripts/drill/fake_meta.py:665-668 |
| D33 「每日 1,500 撐 1 則」卻留 3 則 | 產品（規則一致、句子漏講）：can_support = floor(日預算 ÷ (上限×2)) = 1；資料不足的不能關，所以留 3 則、「還多 2 則放不下」；畫面沒說資料不足的不關 | 外觀／看不懂 | app/ads/triage_capacity.py:47-49,152-154,262-285; frontend/src/components/ads/flow/CleanupProposal.tsx:82-90,133 |
| D38 資料不足的廣告永遠不進學習（P2 最好的一則 4 筆、每筆 290 被丟掉） | 產品：評級門檻＝花費 ≥3×上限(1,350) 或（≥7 天且 ≥10 筆）；沒過門檻就沒評級、結案不寫學習 | 面向 4 根因之一 | app/ads/triage.py:32-34,367-373,442; app/ads/period_grades.py:35; app/ads/coordinate_learning.py:16,42,177-181; frontend/src/components/ads/patterns/TargetRuler.tsx:175-187 |
| D37 暫緩存不了 | **演練才有**（前端用瀏覽器時鐘算 +3/+7 天，伺服器用演練時鐘比對）；「7 天後」預設是真的有選（程式無法取消選取）。產品脆弱點：日期在前端用瀏覽器時鐘算、後端驗 | — | frontend/src/components/ads/flow/ConfirmPage.tsx:99-101,348-385,652-657; app/ads/change_control.py:404-411 |
| D39 暫緩存檔失敗後留下草稿變更單，首頁變「等你核准」 | 產品（要繞路）：先 ensureWorkingSet 建草稿、再 decide；decide 失敗不回滾 | — | frontend/src/components/ads/flow/ConfirmPage.tsx:380,233-260; home/status.ts:159-161; home/QueueRow.tsx:15-18 |
| D40 首頁 2,014 vs 成效頁 2,015 | 產品（外觀）：首頁 Math.floor、成效頁 Math.round | — | frontend/src/components/ads/home/MonthMoney.tsx:21-24; home/CampaignRows.tsx:131; detail/PeriodStatusRow.tsx:92 |
| D9+ 上架後沒有「已上架，等平台開始投放」狀態 | 產品（要繞路）：總覽只有 草稿／資料缺口／投放中；沒有資料時印「未知」「沒有要決定的事」。「在投 0」本身真實使用也會看到（Meta 建好預設暫停） | — | app/ads/workspace_reads.py:183-186,226-233; app/ads/campaign_stage.py:20-33; frontend/src/components/ads/workspace/OverviewBody.tsx:60-65,280-288,368-377,408-410 |
| D14 修正 | 交接清單完全不寫格式（沒有「輪播」、沒有張數）→ 使用者照一張圖建成單圖，學習卻記「輪播」。**不是擋路**，是「規劃的座標沒核對實際」→ 學習失真（要繞路） | — | app/ads/launch_view.py:153-166; app/ads/change_control_launch.py:406-412; frontend/src/components/ads/publish/PublishPlatform.tsx:62-71 |
| D41 結案後沒有下一步；月回顧「沒有要給下個月的建議」 | 產品：建議只有 refresh/cleanup/no_target 三種，來自進行中的待辦；而且只認 origin='imported' 的活動，系統自建的活動永遠不產生建議；沒有任何東西讀評級或學習來給下月建議 | 要繞路 | app/ads/month_summary.py:56,137-150,224-275,278-283,401-407; app/ads/triage.py:580-592; frontend/src/components/ads/month/MonthReviewPage.tsx:155-161 |

## Controls 丙2 (ctl-c2, 21:31–22:25): 200 controls, pass 151, defects 13 (blocking 0, detour 4, cosmetic 9), unchecked 36. File .harness/scratch/drill10/controls/controls-c2.md
Detour: bid strategy 成本上限 has no amount field (app/ads/launch_settings.py:46-50); 儲存這組設定 → 核准上架清單 always 409 until manual reload (app/ads/change_control_launch.py:310-311) [2 controls]; 「已回報人工操作」 disabled without reason. Cosmetic: 8 複製 without feedback; stale red error after fixing URL; 「新增素材需求」 no reaction.
Unchecked: propose pause/budget/cleanup, changes confirm/handoff/verify (single-item), review ×5, blocked-slot buttons ×5 — queue empty (all three campaigns closed). Spare campaigns: A adc_01M3VTNN8TTN0BM5SC1VRXVACM (approved, steps 1–3 walked), B adc_01M3VWDW3QH2J1K4ESCBY89D8A. Month budget now 60,000 (auditor changed).
Plan: after other audits finish, seed spare campaign A with stand-in rows → follow-up audit of proposal/changes pages.

## Faults (fault10, 21:31–22:28; .harness/scratch/drill10/faults/faults.md, 66 PNG; brand brd_01M3VTMWR79RWZ3PBBHBRJ68TM, campaign adc_01M3VVQVHPCQ8DEHHMMWBCPDVS)
| F | Verdict | One line |
|---|---|---|
| F1 官網讀不到 | 要繞路 | 壞網址報「我讀完你的網站了／預填 0 項」不說讀不到；改網址不重讀（ScanStep.tsx 只在 status==="none" 讀） |
| F2 品牌照壞檔 | 要繞路 | empty.jpg／text.jpg 被收下成破圖無提示；huge、mp4 有清楚原因 |
| F3 建檔重整／上一頁 | 外觀 | 無未儲存提示；步 3 重整退回步 2；上一頁到空白建立品牌頁 |
| F4 權杖填錯 | 要繞路 | 「這把權杖沒有列出任何帳戶。權杖已存」不說無效；步 6 輸入框消失，要到設定頁換（MetaConnectPanel.tsx） |
| F5 商品頁讀不到 | 要繞路 | 原因清楚，但改網址按重試仍讀舊網址 |
| F6 商品照壞檔 | 要繞路 | 只顯示「上傳失敗（狀態碼 400）」（libraryApi.ts:371 丟掉伺服器原因）；text.jpg、32MB 被收下成破圖、無移除鈕 |
| F7 商品步 3 重整 | 外觀 | AI 整理的客群與修改消失 |
| F8 賣法邊界 | 通過 | 0／負數擋；原價<售價靜默收下（外觀） |
| F8b 組合／×12 賣法金額 | **擋路（金額錯，畫面實測）** | 成本留空的 ×12 顯示「打平 2,620」（用體驗包成本 25×12）；正確 1,480；建活動頁同樣 2,620；沒標推算 |
| F9 生成中重整 | (a)(b) 通過，(c) 未測到 | 可重跑不卡死 |
| F10 文案被拒 | (a)(c) 擋住有原因；(b)「買一送一」未被攔（只比對「優惠」等字）→ 防線漏洞；格子不顯示被拒原因只寫處理中；改文案入口藏在進階 | 要繞路（b 視同高風險） |
| F11 素材格壞檔 | 通過 | 假 mp4 → 20 秒後「卡住：媒體無法解碼」→「換一張」恢復 |
| F12 發佈重整 | 通過 | — |
| F13 連點 | 通過 | 只一筆請求 |
| F14 登入過期 | 外觀 | 不說過期；登入後不回原頁 |
Totals: 14 items, pass 6, defects 8 (blocking 1, detour 5, cosmetic 3).
Operator still owes: 替身回錯誤 (meta_fail), worker-kill ×3.

## Controls 丙1 (ctl-c1, 21:31–22:33): 314 controls, pass 200, defective controls 10 (15 defect lines: blocking 0, detour 8, cosmetic 7), unchecked 104. File controls/controls-c1.md
Detour: (1) 首頁預算卡存檔後不更新（上方仍「預算 0」「還能花 -30,287.66」，重整才對）; (3) 月總額 -5 默默存成 0、0 也能存; (4) 「加入既有活動」彈窗列出已在工作區的活動; (5) 已結案活動「改預算上限」仍可儲存（鎖定不一致）; (9) 系統理解頁改期間／預算無效時「完成」停用沒說原因; (12) 像素欄填 abc 存成功; (13) 頂列「3 個活動讀取異常」連到資料連線頁卻寫「✓ 正常」、無出口; (15) 投放組每日預算 0 → 400 無人話原因（待確認）.
Cosmetic: (2) 月總額 0 時折線圖 SVG NaN console errors; (6) 策略依據原始 ISO 時間＋英文 likely; (7) 今天 10/01（演練）; (8) 已結案仍寫在投 6 則＋「素材已備妥製作中」; (10) 平台未設定（=D4）; (11) /ads/new 每筆上限 0 可過、理解頁擋; (14) 一句話建立後活動名怪.
Unchecked 104: mutating controls on closed campaigns (~61), month settle steps 2–3 unreachable (redirects to step 1 — investigate), CSV download ×2 (needs explicit OK), 「納入並開啟」×3, upload-record checkboxes 22, structure tab ~5. 資料連線頁沒有重新讀取／補讀按鈕（drill 9 #5 仍在）.
Spare campaign c1: adc_01M3VVT0EMH18NWHZAQ4F13ZQM (at assets tab). Month budget left at 60,000.

## Controls 乙 (ctl-b, 21:31–22:34): 185 controls, pass 147, defect rows 25 (25 distinct defects: blocking 0, detour 15, cosmetic 10; 8 cosmetic ones sit on rows counted as pass), unchecked 13. File controls/controls-b.md
Detour: #1 建檔步 1–3「← 上一步」丟改動無提示; #2 成本／運費負數悄悄變空白、每筆上限 0 不警告; #3 已存賣法列沒有刪除鈕; #4 /products/new 下一步停用沒說要填名稱; #5 「讓 AI 整理」停用沒原因; #6 深入調研貼回亂字顯示綠色「貼回完成，新增 0 條」(ProductDetailPage.tsx:283); #7 「AI 再次調研」空網址按了沒反應; #8 經濟數字售價 0 存成「已確認 NT$0」、負數變 0 (EconomicsPanel.tsx); #9 運費「可填負數表示折抵」-20 存成 0 (EconomicsPanel.tsx:116); #13 組合沒有刪除／封存入口; #15 工作檯「查看全部 →」沒反應 (WorkbenchHomePage.tsx:300); #16 「下一步・圖片待選定」只到 pack 總覽; #17 「查看來源」不去來源活動 (WorkbenchHomePage.tsx:386); #18 「確定覆蓋」硬核准未完成的包 → 已完成卻 0/1、素材組永久鎖住無解鎖入口; #21 「關閉任務包」「封存」無確認、列表看不到已關閉 (PackPage.tsx:164).
Cosmetic: #10 折行; #11 確認人顯示 uuid; #12 組合落地頁錯誤出現兩次、儲存送兩個 PUT; #14 搜尋無結果兩句矛盾 (WorkbenchHomePage.tsx:149,305); #19 自由創作素材組沒有名字; #20 標頭顯示 single_image; #22 複製無回饋; #23 商品下拉混草稿; #24 多一個「：」; #25 產出數量無上限.
Running controls total (c2+c1+b): 699 controls, pass 498, unchecked 153.

## Controls 甲 (ctl-a, 21:31–22:35): 187 rows, pass 160, defect rows 21 (18 distinct: blocking 0, detour 8, cosmetic 10), unchecked 6. File controls/controls-a.md
Detour: 設定頁儲存失敗只顯示「儲存失敗（狀態碼 400）」（後端有人話；frontend/src/lib/settingsApi.ts:89,143）; 毛利率卡接受 7（700%）(app/core/rule_cards.py); 檔期方案數量下限 6 上限 3 可存; 建檔步 1 主按鈕停用沒說原因; 建檔步 3 改過內容按「← AI 讀網站」再回來被打回原文; 通路營收金額 -5／0 存成「未填」無提示; 通路營收／口徑紀錄建立後無修改刪除入口; 報告剛生成再按「重新生成」被限流、整頁「讀取失敗」蓋掉已有報告.
Cosmetic: 英文「Invalid login credentials」且切換模式後殘留; 複製邀請連結無回饋; 設定頁出現「票 09」與 hard/soft; 品牌卡同時「有警示待處理」「一切正常」; 收件匣內文截斷; 看板 1/3 寬數字被切＋橫向捲軸; 歷史頁儲存無提示、略過重整後復原; 確認人 uuid; 創意座標切換啟用後分類下拉重設.
Side effects: org renamed 「備用測試組織」(cannot rename back in UI); spare brand deleted (it had been given Beast Prime's ad account — CHECK Beast Prime binding still intact).
## Controls total after four areas: 886 controls, pass 658, defective controls 69 (blocking 0), unchecked 159.

## Faults round 2 (fault11, 22:38–23:02; faults/faults2.md)
W1 預填中停 worker | 要繞路 | 「正在讀商品頁…」3.5 分鐘無逾時、無原因、無出口（無聲）；重啟後 30 秒自己好，資料沒丟
W2 策略／結構生成 | 通過（不靠 worker，停了照樣完成）
W3 文案生成中停 worker | 要繞路 | 「處理中・自動更新」「文案（未生成）」「排隊中・前面還有 0 件」無提示無重試；重啟後 4–5 分鐘自己生出來
W3b | 要繞路 | 文案生完後素材格仍永遠「處理中・自動更新，不用重整」（其實在等使用者／等圖）frontend/src/components/ads/workspace/AssetsBody.tsx:182 （同 D1）
M1 平台讀不到 | 要繞路 | 連線頁「缺 4 天…讀不到」無原因無重試；發佈步 1 像素「代碼 2…請手動填」但已核准活動輸入框 disabled（app/ads/launch_settings.py:299）；讀回「代碼 2」，恢復後重載仍留舊錯誤，要再按重新讀回
M2 平台故障時換權杖 | 外觀偏要繞路 | 「Meta 拒絕了這個權杖（代碼 2）」把平台故障說成權杖問題（app/meta/routes.py:77）
Round 2: 5 items (W2 counted), pass 1, defects 4 (blocking 0).
Natural failures: 「找不到工單」1 次（phase 2, brief wbb_01M3VWJYMDXDVNY9R6WQA350AE, campaign B; copy later regenerated, last_error stays on a 'done' brief; P1–P3 0 次）; meta_backfill job error 「這項平台請求不符合唯讀範圍，未送出」(org drill10, when auditor assigned the ad account to the spare brand) — no on-screen notice seen (to map).
## Dim 9 tally: scripted 19 items → pass 7 (37%), defects 12 (blocking 1 = F8b money; detour 8–9; cosmetic 3). Silent failures: W1, W3. No data destroyed.
Phase 3 (23:05): follow-up audits ctl-c3 (proposals/changes/reviews on spare campaign A, seeded rows, clock 10/28) and ctl-c4 (mutating workspace controls on c1's spare campaign, settle, CSV, import, blocked-slot buttons). Worker PIDs 93676/65024 (started by fault agent via Start-Process; logs worker3.*).

## Fault-class defects mapped to code (read-only agent)
| T | Verdict | Root cause | Code |
|---|---|---|---|
| T1a 「買一送一」放行 | 產品（F42 設計）：買N送 屬於 bundle 家族，廣告座標是組合優惠 → 視為有依據；從不比對文案是否等於登記的句子 → 同家族任何說法都過 | app/workbench/claims.py:22-28,32-40,178-190; app/ads/asset_suggestion_policy.py:82-105 |
| T1c 完全沒被偵測的優惠字眼 | 產品：第二件半價／半價、特價、特惠、下殺、限時、原價、早鳥價、加購價、組合價、現折100、滿額／滿千送百、單獨的「送／再送／加送」、回饋、點數、抽獎 都不在 RISK | claims.py:22-28,32-40 |
| T1d 手動改文案被拒，格子只寫「處理中」 | 產品：confirm_manual 拒絕只回 pending_reasons 不存；格子的 blocked 只讀 blocked_reasons 欄（只有上傳路徑會寫） | app/ads/asset_suggestions.py:568-576,626-644; app/ads/slots.py:158-181,226-230,388-423; frontend/src/components/ads/UserAssetPlacements.tsx:135; workspace/AssetsBody.tsx:169,182 |
| T2 官網讀不到說「我讀完了」、改網址不重讀 | 產品：_read_pages 靜默丟掉讀不到的頁、不留哪頁失敗；存 URL 不清 prefill；前端只在 status none 時發掃描 | app/intake/ai.py:296-302,322-337,350; app/intake/onboarding.py:167-182,198-208,356-357; frontend/src/components/intake/steps/ScanStep.tsx:31,50-55,77,109-115 |
| T3 上傳檢查三套 | 產品：建檔照片只查副檔名與 >10MB；素材庫只擋 0 位元組、不看內容；只有活動素材格有內容嗅探 | app/intake/routes_api.py:45-54; app/intake/state.py:229-237; app/brand_web/routes_library.py:61,70-100,280-294; app/ads/user_assets.py:38-39; app/ads/media_probe.py:18-42 |
| T3 「上傳失敗／儲存失敗（狀態碼 400）」 | 產品：伺服器有回人話，前端沒讀 body | frontend/src/lib/libraryApi.ts:370-372; frontend/src/lib/settingsApi.ts:88-90,142-144 |
| T4 背景行程停掉無提示 | 產品：沒有任何「排隊超過 N 分鐘」偵測、沒有 worker 心跳；只有 /api/jobs/active 帶 waited_seconds，鈴鐺對排隊中的工作不顯示 | frontend/src/components/intake/product/ProductOnboarding.tsx:19,76-97,158-159; workspace/AssetsBody.tsx:46,419-422; app/background/__init__.py:340-390; app/dashboard/routes_jobs_api.py:87-125; frontend/src/components/layout/ActiveJobsBell.tsx:68-89,162-176 |
| T5 「找不到工單」競態仍在；last_error 永不清除、也沒有畫面顯示 | 產品 | app/workbench/repository.py:94-107,220-237,1506; app/workbench/jobs.py:682-685; frontend/src/components/workbench/SetStudioPage.tsx:205 |
| T6 meta_backfill 失敗 | **演練替身**（分頁 next 網址沒帶 cursor）；產品面：補讀失敗在畫面只剩鈴鐺的「失敗 N 件」 | scripts/drill/fake_meta.py:225-244; app/meta/read_policy.py:149-169; app/meta/routes.py:242-252 |
| T7 存廣告組設定後核准 409 | 產品：「儲存這組設定」沒有觸發重新讀核准 hash（接到 onCampaignSaved 而非 onSaved）；409 後頁面會重讀，按第二次可能就過（未驗） | frontend/src/components/ads/publish/PublishList.tsx:69-75,99-103,129-130; publish/LaunchSettingsCard.tsx:57-58,77,220; app/ads/change_control_launch.py:306-311 |
| T8 成本上限沒有金額欄 | 產品：整個系統沒有出價金額欄位 | app/ads/launch_settings.py:44-52,86,112,430 |
| T9a 平台故障說成權杖被拒 | 產品：只對 100／10／200–299 分類，其餘（含暫時性錯誤、限流）一律「Meta 拒絕了這個權杖」 | app/meta/routes.py:67-78 |
| T9b 像素欄停用卻叫人手動填 | 產品 | frontend/src/components/ads/publish/LaunchSettingsCard.tsx:139,199-200,234-241; app/ads/launch_settings.py:293-299 |
| T10 月預算存檔後首頁卡不更新；0 可存；負數靜默不動 | 產品 | frontend/src/components/ads/MonthlyBudgetPanel.tsx:42-53,86; home/MonthMoney.tsx:60-61,90-95; app/ads/month_budget.py:31-40,430-435 |
| T11 已結案仍可改預算上限 | 產品（2026-09-25 裁決刻意如此；與其他鎖定不一致）→ 不列缺陷，列「設計如此」 | app/ads/strategy.py:688-702; app/ads/repository.py:1006-1025 |
| T12 「確定覆蓋」核准後永久鎖住 | 產品：沒有任何取消核准／重開路徑（文件說沒人要過） | frontend/src/components/workbench/PackPage.tsx:212-245; app/workbench/repository.py:667-670,1067-1102,1509-1511 |

## Controls 丙3 follow-up (ctl-c3, 23:03–23:45): ~112 rows, pass ~98, defect rows 13 (12 defects: blocking 1, detour 3, cosmetic 8). Unchecked: single-ad pause/budget confirm pages (~10, no real proposal reachable), ~130 repeated controls on 準備素材頁 (sampled 12), ~57 複製 on publish step 2 (sampled 3). File controls/controls-c3.md
Blocking candidate C3-G: 覆盤選方向「停掉這則」→「建立暫停提議 →」200 → /propose/pause/<ad> 「找不到這則廣告的停損提議」; no queue item appears (c3-rev-01-stop-proposal-not-found.png; frontend PreparePage.tsx:46, ConfirmPage.tsx:427). TO MAP (may relate to D21 lookup by first active ad).
Detour: C3-J 準備素材頁「套用到 1 件待處理」三欄全空也能按、把原文案清成空白 (UserAssetPlacements.tsx:84); C3-B 清理暫緩後沒有畫面入口回來，頂列「1 項待處理」vs 首頁「今天沒有要決定的事」; C3-A 活動 10/24 開始卻把 09/30–10/23 當缺資料 → 4 則都「資料不足」，首頁不出現待決定（可能受演練時鐘影響；判讀規則本身把開始前的日子算缺）.
Cosmetic: C3-D 暫緩後不顯示重看日期; C3-C 自訂時選項擠成直排; C3-E 「回到確認／回到到平台完成」被導回原頁; C3-F 「建立變更清單」「調整月總額」點了沒反應; C3-H /wait 標題資料不足但七格全有資料色; C3-I 證據頁標題「變貴」但該則每筆 290 低於上限 (QueueRow.tsx:39); C3-K 關閉鈕名稱 Close; C3-L 發佈步 2「取消」字義不清、複製無回饋.
Passed: publish steps 2–3 controls, cleanup proposal incl. custom defer date, change flow handoff/verify before+after pause, review flow (看證據、選方向、改文案、無法判定、再請 AI 看一次).

## C3 defects mapped to code
| U | Verdict | Root cause | Code |
|---|---|---|---|
| C3-G 覆盤「停掉這則」死路 | **產品，擋路**（常見狀態下必死路；與演練時鐘無關）：「建立暫停提議」只更新覆盤回合（UPDATE ads_review_round），不建立任何提議；接著導到 /propose/pause/<ad>，那頁要找「進行中的待辦列」，F28-I02 之後後端只在 划算→偏貴／太貴 時才有逐則的列；已暫停的廣告、從成效頁進階開始的檢討、已在清理清單裡的廣告都必定找不到。VerifyPage 的「暫停舊廣告 →」同一條路。單則停掉沒有其他可用入口（進階的「建立變更清單」測試時點了沒反應） | frontend/src/components/ads/review/PreparePage.tsx:180-186; app/ads/review_rounds.py:289-326; frontend/src/components/ads/flow/ConfirmPage.tsx:118-127,261-269,422-433; app/ads/triage.py:780-782,803-851; flow/VerifyPage.tsx:487,526 |
| C3-J 空白套用清掉文案 | 產品（要繞路；資料被清空） | applyDraft ?? "" 蓋掉既有欄位；前後端都沒有空值檢查 | frontend/src/components/ads/UserAssetPlacements.tsx:74,78,84,100; app/ads/user_assets_routes.py:351-370; app/ads/user_assets_repository.py:195-205,351-357 |
| C3-B 暫緩後回不去 | 產品（要繞路） | 暫緩不關待辦；首頁把它放進「今天處理過」但那個晶片沒有連結；頂列 open_items 不過濾暫緩；變更時間軸排除 deferred | frontend/src/components/ads/home/status.ts:164-169; home/TodayDecisions.tsx:29-38,180-195; app/ads/status_summary.py:34-39; components/layout/Topbar.tsx:64-67; app/ads/workspace_reads.py:439 |
| C3-A 開始前的日子算缺資料 | 多半演練造成（只拉了 4 天）；潛在產品規則：缺日＝判讀窗減「最後一次同步涵蓋範圍」，不看活動開始日；每次同步會覆蓋而不是合併涵蓋範圍 | app/ads/triage.py:35,201-248,508-518; app/ads/external_sync.py:69,483-484 |
| C3-H /wait 標題寫死 | 產品（外觀） | frontend/src/components/ads/wait/WaitPage.tsx:260-261,270,304 |
| C3-I 「變貴」寫死在覆盤麵包屑 | 產品（外觀） | frontend/src/components/ads/review/ReviewEvidencePage.tsx:342 |
Blocking count now: 2 (F8b money; C3-G review stop dead-end).

## Controls 丙4 follow-up (ctl-c4, 23:03–23:48): 148 clicked, pass 140, defective controls 8; 10 defects (blocking 1, detour 4, cosmetic 5); unchecked ~31. File controls/controls-c4.md
Blocking c4-1: 手動改文案加「醫師推薦」存新版後，格子永遠「處理中・自動更新」，不變卡住、無原因、無按鈕；改回原文再確認（POST 200）也不恢復；頂列寫「沒有背景工作在跑」(c4-14-cell-stuck-processing-forever.png; app/ads/slots.py:232-234; 同 T1d 根因：手動路徑的拒絕不存 blocked_reasons).
Detour: 像素欄 abc 可存; 投放組自訂日期結束早於開始可存 (c4-04); 「在這一組新增廣告」停用沒說要選滿 7 個下拉; 「新增素材需求」沒反應（待確認）.
Cosmetic: 改回後紅字殘留; CSV 浮點尾巴 (3286.2400000000002); 加入既有活動彈窗原始 ISO＋ACTIVE、不標已納入; 同一活動三處狀態字不同（待發布／草稿／ACTIVE）; 工作檯包建好是空的要逐組按再生成.
Corrections to c1: defect 15 (每日預算 0 無原因) and defect 4 (納入重複) NOT valid; month settle steps 2–3 unreachable = by design (月未結束，畫面有說). CSV totals 40,638.90 / 38 = screen.
## FINAL controls tally (approx. where agents said 約): round 1 inventory 886 (clicked 727: pass 658, defective 69→67 after c1 corrections); follow-up clicked 259 (pass 238, defective 21). Clicked ≈ 986, passed ≈ 896 (≈91%), defective ≈ 88. Blocking found by audits: 2 (C3-G, c4-1). Still unchecked after follow-up ≈ 250, of which ≈190 are repeats of one component sampled (準備素材頁 ~130, 複製 ~57), rest: single-ad pause/budget confirm (~10), blocked-slot buttons 4, c4 ~27, a 6, b 13.
## BLOCKING total 3: F8b (money: ×N sell-way/bundle break-even from qty-1 sell-way cost), C3-G (review 停掉這則 dead-end), c4-1 (slot stuck forever after refused manual copy).
## FINAL scores: dim1 A8/B5; dim2 A7/B5; dim3 A8/B2; dim4 A9/B3; dim5 B6; dim6 B4; dim7 B6; dim8 B4; dim9 B3. Bar: FAIL (no B dimension ≥7; 3 blocking).
