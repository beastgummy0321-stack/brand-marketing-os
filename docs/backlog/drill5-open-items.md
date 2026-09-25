# Drill 5 交接：待裁決的 10 題（2026-09-23）

## Handoff (2026-09-25): start here in the next session
- **State:** F28 and F29 are closed and merged to master (F29 = `b00722e8`), **not pushed** (the user pushes manually). No open feature; the queue is empty. Rules: `docs/architecture/ads.md` §6.32 (F28) and §6.33 (F29).
- **Next step (2026-09-26):** F30 closed the UI batch and item 4; start from `docs/backlog/handoff-after-f30.md`.
- **Status of the original "待裁決" list:** 1, 2, 3 and 8 are done in F28, and 10's 「目標調高撐得起更少」 is shown on the strategy tab. Still open: 4 (worse flow with no manual exit when the fact check blocks), 5, 6, 7 and 9 (month review). Items 5, 6, 7 and 9 were built in F29; only item 4 remains.
- **Confirmed constraints to keep:**
  - The UI is graphics-first with linear flows and no text walls (§1.7).
  - Every UI change is prototyped first and validated with a cold novice persona on screenshots before the user sees it.
  - One cap per campaign, cost per result only; the screen word is 上限. Grades are 划算/偏貴/太貴/沒賣出 (白花 renamed in v10, ads.md §6.33).
  - No platform writes: reversing that needs its own product ruling against ads.md §6.4.
  - Never ask the user to run real Meta ads.
- **Next UI batch:** the remaining v9/v10 screens: the new-campaign wizard, assets (incl. the v10 素材需求 card), the full publish page, connections, and the workspace lifecycle rail and tabs. The month review was rebuilt in F29.
- **Environment:** start with `啟動行銷系統.bat`. It now brings Docker and Supabase up and clears Docker's stale socket folders itself (`scripts/ensure_database.ps1`). Test login: see CLAUDE.md.

三人實機演練（阿明／Vivian／小杰）＋原型落地複查後的未決事項。原始逐站紀錄在
`.scratch/drill5/{aming,vivian,jay}/run.md` 與 `.scratch/drill5/synthesis.md`（拋棄式，重灌會消失）。

## 現況（做完、不必重做）

- F25／F26／F27 已合併 master；投放中心原型（v7＋v8）落地複查 5 個問題已修。
- 演練中修掉 10 個產品 Bug，每個都有測試守住：新品牌缺座標詞彙（投放結構永遠失敗）、
  清理把停損那則算成留下、檢討不認「調整目標」頁的目標、發布失敗訊息被藏在收合區、
  新品牌從不讀 Meta 帳戶月花費（第一次發布永遠被擋）、配對候選只讀匯入活動、
  計畫列序不固定導致核對被判失效、投放目標中英文硬比對、核准失敗訊息隨跳頁消失、
  連線頁測試寫死日期。
- 後端 2223、前端 677 測試全綠。**尚未 push**（依規矩由使用者手動推）。
- 演練替身（`scripts/drill/fake_meta.py`）已補：分頁、純數字物件編號、鏡射帶目標／日期／預算。

## 待裁決（依嚴重度；每條：現象 → 建議）

1. **清理依花費挑廣告**（Vivian、小杰）：會關掉 4 則每筆購買成本 50 的贏家、留下成本約 400 的。
   → 改依每筆購買成本排序；核准前標明規模（8 則關 7 則）。
2. **一個活動兩套目標**（Vivian、小杰）：策略頁 450 vs 詳情頁預設近 30 天實際 126.5，兩處都可編輯。
   → 只留一個目標入口，其餘唯讀引用。
3. **成功條件存錯指標**（Vivian）：視窗顯示「每次購買成本」，不動下拉直接填 450 會存成 ROAS 450。
   → 送出前以畫面顯示的指標為準，或強制選擇。
4. **變差被事實檢查擋下後沒有出路**（Vivian）：畫面說「請人工判讀」，卻鎖住選方向／改文案，也沒有重試。
   → 開放手動改文案路徑＋重試。
5. **背景 AI 工作沒有進度**（阿明 25 分鐘、Vivian 5 分鐘）：畫面不說要等多久，甚至寫「沒有進行中的背景工作」。
   → 顯示第幾件／共幾件；同時檢討 worker 一次只做一件的併發上限。
6. **同一畫面三種說法**（Vivian、小杰）：上方有花費數字、中間全「尚待確認」、結尾寫「沒有成效資料」。
7. **非同步先給確定的空狀態**（小杰、Vivian）：首頁先說「都處理完了」，重整才出現待辦；件數與卡片數不符。
8. **核准失效後沒有重新核准的出口**（阿明）：計畫被判定變更後，11 項全部唯讀鎖死，只能由後台解。
9. **每月回顧不可信**（Vivian）：「有效 0 則」與詳情頁對不上；8 月素材區是 9 月內容；下月建議把已拒絕的清理再推一次。
10. **購買數顯示小數（273.429）與「目標調高反而撐得起更少」無解釋**（Vivian、小杰）。

## 能力缺口（票裡沒規定，做不做由使用者決定）

- A/B 測試：沒有「這是一場測試」的設定、沒有到期比較與留贏家規則。
- 匯出報表：沒有任何下載／分享入口。
- 投放進階設定：受眾、版位、出價、優化事件、歸因、像素、UTM 在上架清單皆「尚未填寫」。
- 站內出圖：只有文字提示詞（保留席位），素材因此接不回廣告。
- 主動加預算：好廣告只標「持平」，無提議也無手動入口。
- 素材需求只能綁整個活動，不能綁指定廣告；清理不能自選則數。

## 環境備忘

- 演練用後端：`scripts.drill.serve --port 8710` ＋ 裝了替身的 worker；目前已切回正常模式。
- worker 重啟會留下狀態 `doing` 的工作不會自己恢復，需手動改回 `todo`（schema `public__queue`）。

## Probe results (2026-09-23, code-read only, services were down)

Root causes behind the 10 items above, with evidence:

- **R1 Judgement is not anchored to the target.** `triage.py:320-334` classifies each ad only against its own previous window (±20%). So cleanup falls back to spend order (`triage_capacity.py:176,182`), scale-up needs the whole budget unit stable (`triage_scale.py:111-128`), and the month review counts only "better" as effective. Two target stores feed it: `success_metric/success_target` (strategy tab, read by `closeout.py:51`) vs `target_cost/target_basis` (detail page, read by `targets.resolve`, which falls back to the 30-day actual at `targets.py:113-118`). A metric that fails to parse defaults to `roas` (`brief.py:45`). → items 1, 2, 3, 9, 10.
- **R2 `stale` has no way out.** `handoff_check.py:281-290` marks an item stale, and after that the UI disables readback/review (`ManualHandoffPanel.tsx:170-171`) while `approve` accepts only draft or deferred sets (`change_control.py:229-233`). Nothing re-freezes the set against the current plan. → item 8.
- **R3 Stuck jobs never recover.** `background/recovery.py:15-27` re-queues only 8 read-only kinds. Every other kind stays in `doing` forever. Worker concurrency is 1 (`worker.py:131`).
- **R4 Progress is read from `llm_task`, not from the queue.** `dashboard/routes_jobs_api.py:57-60` sees running rows only and no `ads_*` kinds; there is no position API. → item 5.
- **R5 Each section decides "has data" on its own.** The detail page has three sources (`PerformanceTab.tsx:191,378`, `ReviewEvidence.tsx:43`). The home count and the cards come from separate reads, and failed reads turn into an empty list in 4 places. → items 6, 7.
- **R6 No budget cap check.** `budget.py:97-155` never reads `constraints_json.budget`, and the UI preselects "recommended" (`StrategyTab.tsx:139,157`).
- **R7 The learning loop is closed on real data.** Learning is written only on a manual closeout of an internally created campaign (`closeout.py:78`) or on a verified pause of an ad with an angle tag (`change_control_verify.py:263`). Period settle writes only a budget direction. Experiments refuse any data that is not simulated (`experiments.py:386`).
- **R8 No platform writes.** The only network call is `httpx.get` in `meta/graph.py:87`, and `auto_meta` is a reserved seat. This follows the decision in ads.md §6.4, so changing it is a product ruling, not a bug. The image port is a reserved seat (`workbench/image_port.py:14`).

## Deferred to a later /dig (user ruling 2026-09-23: fix R1, R2, R3 and R6 first)

Numbered as in the ranking shown to the user. **Status 2026-09-25:** 4, 5, 7, 8, 9 (inbox only) and 10 are ruled in ads.md §6.33 and planned as F29; 6 and the other channels of 9 stay deferred (see the end). The proposals below are the original starting points.
4. **Learning and A/B are closed on real data** (R7). Proposal: period settle writes learnings for ongoing campaigns (stable winners too, not only "angle failed"). Experiments judge real data behind a minimum-sample gate. Add a test definition (variable, equal budget, end date, winner rule).
5. **The screen contradicts itself** (R4, R5). Proposal: jobs progress reads the procrastinate queue (queued position, N of M) and covers `ads_*` kinds. One shared "has data / why not" state per campaign that every section reads. A failed read never shows as empty. Raise worker concurrency.
6. **No in-app image generation** (the image port is a reserved seat). Proposal: decide on a provider before any design work.
7. **A material request binds only to a campaign.** Proposal: let it target a specific ad, and let cleanup choose how many ads.
8. **No export or share.** Proposal: CSV for the period and month review first.
9. **No proactive notification.** Proposal: a daily digest (email or LINE) of the triage queue.
10. **Launch settings are free text** (audience, placement, bid, optimization event, pixel, UTM). Proposal: structured fields that readback can verify. Platform writes (R8) need a separate product ruling that reverses ads.md §6.4.

## Rulings for R1/R2/R3/R6 (/dig 2026-09-23)

Moved to `docs/architecture/ads.md` §6.32 (the rule) and `.work/features/F28.md` (contract names, being built). The prototype-before-code step is done: `prototype-v9-ads-center.html`.

## UI overhaul ruling (2026-09-23)

The user rejected the text-heavy UI, including the prototypes, and wants a graphics-first overhaul where the layout itself tells the user what to do next. Scope is the whole ads-centre loop, in ONE single-file prototype that becomes the final look: `docs/design/ads/prototype-v9-ads-center.html`. It absorbs v7, v8 and the drill-5 rulings above. Visual tokens stay unchanged: violet, Inter + Noto Sans TC, and the palette in design-system §2. The 4 open prototype details follow the recommendations:
- Cleanup never closes on-target ads; it proposes a budget increase instead.
- When the recommended budget is over the cap, the "推薦" tag moves to 照上限.
- Re-approve keeps the items already verified, and reverting needs one confirm.
- With no product cost, the screen also links to entering the product cost.

## Ads-centre entry page rethink (2026-09-23, done in F28)

The user says the v9 home is a to-do centre, not an operations view, and still feels like a cockpit. Question to answer first: why does the user come here, and what must they know on arrival? Three concepts are being drawn on a design canvas and checked by a cold novice persona before the user reviews them.
- Canvas: https://claude.ai/artifact/4zuu6yz76DTXt8arpSb3Dh. It holds three boards: A shows the month's pace, B shows where the money went, and C is a morning brief (recommended).
- Why the user comes here, in order: (1) is ad money being wasted, i.e. profit after ad spend; (2) the month's pace; (3) which campaign works and which is broken; (4) what to do today, at most 3 items. v9 answered only (4).
- A cold novice persona (a 42-year-old shop owner, screenshot only) tested two rounds. Round 1 root causes: marketing jargon instead of money, buttons that do not say what happens, colour without names. After the fixes, calm went from 3 to 4 on every version, but clarity stayed at 3. What is left: each number must say whether it is good or bad news, and who set the cap.
- Fixture caveat: in v9, break-even 380 is below target 450, which means a CPA at target loses money. The canvas assumes a profitable target and says "上限" instead of "目標". Fix the fixture before any real build.
- **Approved 2026-09-23:** home = board D (Fused) on the canvas. It is being ported into `prototype-v9-ads-center.html`, and the vocabulary follows it across all screens:
  - grades are 划算 / 偏貴 / 太貴 / 白花;
  - the target is shown as 上限;
  - stop-loss and cleanup merge into one decision;
  - the fixture break-even becomes 520.

## Deferred from F28 planning (user 2026-09-25: save for a later /dig, F28 uses the defaults)
Both are ruled in ads.md §6.33 (settle writes the 沒賣出 learning; 變貴 = a 划算 → 偏貴/太貴 move) and planned as F29.
1. **白花 closes through cleanup, so its brand learning is lost.** The cleanup flow has no 「這則主打什麼？」 step (F27 Contract D), so closing a 白花 ad no longer writes a learning. F28 accepts this. Restore it in the learning-loop /dig (item 4 above).
2. **變貴 (`worse`) rows are still triggered by the trend vs the previous window**, although the ruling makes trend a note only. F28 keeps them. Decide in the next feature, which owns the worse/stop decision flows, whether 變貴 should instead mean "moved from 划算 to 偏貴/太貴 against the cap".

## Left open after F28 (2026-09-25)
The first three are ruled in ads.md §6.33 and planned as F29; the fourth is test data only.
- **Pending handoffs are not on the home page.** Home D dropped the ChangeAttention card: approved lists waiting for 到平台完成 or 核對 show only on the campaign's 變更與核對 tab. The next feature should decide how home surfaces them, e.g. a campaign-row state.
- **暫用打平 lacks the product cost field.** The cap view has no `cost`, so the screen shows 售價 and ROAS 參考 but not the prototype's formula 「售價 − 成本含運 = 打平」.
- **No cap means no visible 推薦.** Without a budget cap, the 推薦 scenario can be a row whose amount is unknown, so the tag is not visible.
- **Old open cleanup rows keep the informational severity** until their daily key rolls over. This is test data only.

## Rulings for items 4–10 (/dig 2026-09-25)
Built in F29; the rule and its known gaps are in `docs/architecture/ads.md` §6.33. The prototype-before-code step is done: `prototype-v10-ads-center.html`.

Still deferred, not in F29:
- **In-app image generation** (item 6): the seat stays reserved and is never shown as a refusal. Decide on a provider before any design work.
- **More notification channels** (item 9): a per-user 「通知」 section in `/settings`, then LINE Official Account and email, one sender each behind the F29 digest builder. LINE Notify ended in March 2025.
- **Platform writes** (R8): still off; reversing ads.md §6.4 needs its own product ruling.
- **Month-review suggestion history** for past months (not stored), and the **full publish-page rebuild** (F29 changed only its settings blocks) — next UI batch.
