# 目標：越排越好——結算就是記分，下一期讀上一期，系統推薦下期的錢與日子

Status: 2026-09-08 使用者裁決撿回（同日早上曾封存），並把骨幹定為「**結算＝記分、下期讀上期、贏家延續、
系統推薦下期預算與日期**」（前提檢查的選項 1＋3 改版；全自動改預算／建活動不在這一輪，仍要 Meta 寫入 API 與修憲）。
前身規劃（2026-09-07 三支 code 探針）的現況段全部沿用，下面只重列 2026-09-08 重量過的數字。
依據：`CONSTITUTION.md` 第 4、7、8、9 條；ADR 0053（檔期）、0055（node_key）、0057／0064（綁定與花費）、0012（規則上限）；
`docs/contracts/schedule.md`。前提（使用者 2026-09-07 定）：不堆規則、不堆分析、不把大資料包丟給外部 AI。

## 一句話定義（驗收就驗這句）

**下一期出方案時，prompt 裡有上一期每個節點的「核准了多少／實際花了多少／ROAS 對打平線／判決」，方案文字引用它們；
判決不是輸的節點名字原樣延續、綁定自動接回同一個 Meta 物件；排程頁預填下一期的日期與建議日預算，使用者仍要按。**

## 現況（2026-09-08 量到，開票前不必再查）

- `campaign_period` 只存品牌層 `settled_spend`／`settled_revenue`（`period.settle()`，`period.py:298`）；
  **沒有任何一張表存節點層的結果**。`period_node_membership` 3 列（深度 2，綁定時寫，`binding.py:147`）；
  `channel_entity_map` 深度 1／2／3 各 1／3／7 列；`creative_candidate` 7 則 `tagged`（七維座標齊）。
- 本機資料：檔期 `cpd_01M1Y012…`（09-07～09-14）`running` 未結算，另一列 `planning`（09-08～09-15，走查時開的草稿）。
  結算可以提前按（`settle()` 的 `force_early`），驗收不必等到 09-14。
- 出方案 prompt 已有本月成效（plan-quality 票 01，2026-09-08）；活動樹 prompt 沒有；**兩者都不知道上一期**
  （`context_compiler.py` 零引用 `campaign_period`／`schedule_tree`）。
- 節點名字由 LLM 現寫（`tree.py:79-80`），綁定靠名稱完全相符（`binding.py:73-126`）；同一個 Meta 活動可跨期重綁（ADR 0064 §2）。
- 日預算唯一來源＝規則卡 `schedule_budget.daily_budget`；起迄日在排程頁手打（`ScheduleSetup.tsx`）；
  `_advance_if_ended`／`settlement_advice_days()` 是「讀的時候算、不存」的既有慣例。
- 打平線：`diagnosis.breakeven_roas()` 三層 fallback；兩個 ROAS＋覆蓋率是契約（schedule.md 決定 5/11）。
- 兩條棘輪在票 01 之後都是「量到的值＝常數」（零餘裕）；每張票要明寫授權調高。

## 形狀（四刀，順序＝依賴順序）

| # | 刀 | 形狀 | 路線 |
|---|---|---|---|
| 1 | 結算＝記分 | 新表 `period_node_result`（schedule 模組）。`settle()` 對這期的樹（`period_node_membership.source_tree_task_id`）每個**已綁定**節點（深度 1～3）寫一列：`node_key`、`depth`、`name`、`external_id`、`approved_share`、`approved_daily_amount`（核准那棵樹的值）、`actual_spend`（這期日期區間、該實體、該層的花費）、`revenue_tracked`、`roas_conservative`、`roas_optimistic`、`roas_coverage`、`breakeven_roas`（結算當下）、`verdict`、`coordinates_json`（深度 3 從 `creative_candidate` 七個 `*_key`）。**判決**：保守 ROAS ≥ 打平線 → `win`；樂觀 ROAS < 打平線 → `lose`；其餘（含沒資料、算不出打平線）→ `unclear`。重新結算覆寫同期同節點那一列。**不推斷是誰分的錢**：核准比例與實花比例並列，CBO 底下的差異自己會顯出來 | C（schema＋ADR） |
| 2 | 下期讀上期 | 出方案 prompt 與活動樹 prompt 各加一段【上一期】：期名、日期、日預算、結算花費／營收、判決分佈，逐節點一列（名稱｜深度｜座標｜核准比例｜實花｜實花佔比｜保守／樂觀 ROAS｜判決）。來源＝最近一期**已結算**的 `period_node_result`；沒有 → 這段不出現。位置：在本月成效那段之後、prompt 最後 | B |
| 3 | 贏家延續 | 活動樹 prompt 末段指令：判決 `win`／`unclear` 的節點**名字原樣沿用**（逐一列出），`lose` 的換座標、換名字。樹讀回時每個節點多 `continued_from_node_key`（名字＝上期同深度節點名時填上，讀的時候算、不存）；畫面樹上標「延續」；綁定頁只要求去 Meta 建「新」的 | B |
| 4 | 錢與日子 | `period.next_period_suggestion()`：讀的時候算、不存、不新表。起日＝上期迄日＋1；天數同上期；日預算＝上期核准 `max_daily_amount` × 步階，方向由上期**期層**判決決定（用結算的花費／營收對打平線，同第 1 刀的三值）；`why` 一句話帶兩個 ROAS。排程頁預填日期＋「建議日預算」卡（數字＋為什麼）＋「採用」按鈕寫進規則卡（既有 `saveRuleCard`），使用者仍要按出方案與核准（憲法第 9 條） | B |

第 4 刀之後使用者的工作剩：看一眼預填、按「出方案」、去 Meta 貼「新」節點的名字。系統自己建活動、自己改預算要 Meta 寫入 API，
是另一個目標（憲法第 9 條「花錢要按」在那裡才需要重新設計）。

## 站①裁決（主聊天提案，2026-09-08 一次問使用者）

1. 判決三值與門檻：由契約「兩個 ROAS 都是真的」推出（保守過線＝贏、樂觀都不過＝輸、其餘看不出），**不另設常數**。
2. 延續規則：`win`／`unclear` 延續、`lose` 換。理由：`unclear` 多半是樣本不夠，換掉等於永遠測不出來。
3. 日預算步階：**Meta 官方沒有數字**（2026-09-08 查證）。Meta「Significant edits and learning phase」
   （https://www.facebook.com/business/help/316478108955072）原文：「A change to … Budget amount … may or may not be
   significant, depending on the magnitude of the change … $100 to $101 … isn't likely … $100 to $1000 … may reenter the
   learning phase.」「20% 以內免重進學習期」是業界口耳相傳，不在任何 Meta 自家頁面。學習期長度：「usually … about 50 results
   in the week after the ad set's last significant edit」（https://www.facebook.com/business/help/112167992830700）。
   所以步階數字**沒有可引的來源**。**使用者裁決 2026-09-08：開規則卡 `schedule_budget.step_rate`，預設 20%**（來源＝使用者本人，
   卡片說明寫明「Meta 沒有官方數字，20% 是業界慣例」）。建議額＝上期核准 `max_daily_amount` ×（1 ± 步階），方向由上期記分決定。
4. 第一期沒有上一期：【上一期】段落不出現；預填＝今天、規則卡值，卡片說明「這是第一期」。
5. CBO（`plan-quality/issue-budget-level-mismatch-is-never-checked.md`）：**不是前置**。記分表存核准與實花兩欄，差異可見；
   要不要去讀 Meta 的 `daily_budget` 欄位是之後的事。
6. 自動跑 LLM 判讀：維持手動（schedule.md 決定 10）。
7. 記分的「期」＝`campaign_period`（結算就是記分，所以跟結算同一個期），日曆月那套只留給畫面的本月成效。

## Plan review（Opus，2026-09-08，一輪）量到的，已折進上面

- **綁定的 Meta 物件零花費**：`channel_entity_map` 10 個 `external_id` 對 `meta_entity_spend` JOIN 出 0 列（系統綁的那條活動暫停中，
  真花費全在使用者手建的廣告）。所以今天結算＝10 列全部 `actual_spend 0`、判決全「看不出」；第 3 刀在今天的資料上等於「全部延續」。
  這是帳戶資料的現況，記在這裡當事實；不是缺陷、不是待辦、不是任何一張票的前置（BOARD 第 5 行的裁決）。
  驗收用測試資料證明賺／賠三種判決，真資料只證明「結算會寫列、畫面會顯示」。
- **打平線 1.0 來自毛利率 100%**（產品成本填 1.05 元）：記分列多存 `breakeven_source` 原文，不另設門檻；成本是資料，請使用者填。
- **深度 1／3 沒有 `share`**（`tree.py:89-99` 只有 `budget_level`=2 那層有），三層花費相加會重複算同一筆錢：記分表只做深度 2（有核准比例）
  與深度 3（有七維座標），**永不跨層相加**，深度 1 不記。
- **期層營收 0**（`channel_revenue` 0 列，沒匯訂單）：第 4 刀的方向**不用** `settled_revenue`，改用記分表深度 2 列的花費加權保守 ROAS 對打平線；
  沒有任何追蹤到的營收 → 只回日期、不回金額方向。
- **本機有兩列重疊的 `planning` 檔期**：第 4 刀的預填從「最近一期**已結算**」算，跟現有未結算檔期重疊時畫面要說，不能默默 +1。
- **棘輪零餘裕、`repository.py` 731／800**：每張票明寫授權；票 01 的三支 repo 函式要塞進 69 行，塞不進就 blocked-upstream。
- 它建議的「更懶版」（只存深度 2 三欄、第 3／4 刀先不做）沒採用：使用者這一輪的目標就是四刀落地；第 3／4 刀在今天資料上是 no-op 這件事寫進驗收，不是不做的理由。

## 排序（票）

1. `01-period-node-result.md` — 第 1 刀（C）。前身 `issue-adopted-suggestion-drops-its-coordinate.md`。
2. `02-last-period-in-prompts.md` — 第 2 刀（B）。前身 `issue-next-period-does-not-know-the-last-one.md`。
3. `03-winners-keep-their-names.md` — 第 3 刀（B）。
4. `04-next-period-money-and-dates.md` — 第 4 刀（B）。前身 `issue-budget-and-dates-are-hand-typed.md`。

驗收（整條）：在重啟過的後端上，把 09-07～09-14 那期提前結算 → 記分表有列、畫面看得到判決 → 出方案＋展開活動樹 →
方案與樹的文字引用上一期節點與數字、贏家名字原樣出現 → 綁定自動接回 → 排程頁預填了日期與建議預算。

畫面那一半在 `docs/issues/ui/`，跟著這一行走：`issue-adopt-has-no-echo.md`、`issue-period-page-has-no-history.md`。
`plan-quality/issue-coordinate-guard-only-blocks-unknown-labels.md` 不擋路。
