# 目標：廣告排程越用越聰明——系統替自己記分，並替使用者算下一期的錢與日子

Status: 2026-09-07 規劃完成（三支 code 探針，非讀文件）。全部 blocked on data：有座標的花費今天仍 0 元，
`docs/issues/ad-loop/` ⑧⑨ 先有真數字，這裡才有東西可驗。這個目標落地後，廣告排程進最終收尾。
依據：`CONSTITUTION.md` 第 4、7、8、9 條；ADR 0053（檔期）、0057／0064（綁定）、0012（規則上限）；
`docs/contracts/schedule.md`。前提（使用者 2026-09-07 定）：**不堆規則、不堆分析、不把大資料包丟給外部 AI。**

## 現況（探針量到的，開票前不必再查）

- 單向閉環完整：方案→七維座標→綁定→花費回流→判讀→採用→下一期 prompt「【本期要測的】」。
- 斷在最後一公尺：採用時 `dimension`／`coordinate_key`／`direction`／`impact_spend` 被揉成純文字
  （`issue-adopted-suggestion-drops-its-coordinate.md`）。
- 錢：使用者在設定頁打 `schedule_budget.daily_budget`（`app/core/rule_cards.py:49-63`），出方案時凍進
  `campaign_period.daily_budget`（`routes.py:257`）；代理只給比例，`largest_remainder_allocation` 乘出每節點金額
  （`plan.py:85`、`tree.py:155`）。**沒有任何地方從數據算出建議金額。** 檔期起迄在排程頁手打（`ScheduleSetup.tsx:61-62`）。
- 期別：每期一棵全新的 `schedule_tree`，名字由 LLM 現寫（`tree.py:79-80`），綁定靠名稱完全相符（`binding.py:73-126`）；
  plan prompt 完全不知道上一期（`context_compiler.py` 零引用 `campaign_period`／`schedule_tree`）。
  同一個 Meta 活動可跨期重綁（ADR 0064 §2），但今天只在名字巧合時發生。`app/meta/` 唯讀，系統建不了活動、改不了預算。
- 排程管線已在：`app/meta/daily_pull.py:154-156` 的 procrastinate `periodic()`，每天 03:00。新週期工作照它掛。
- 兩種「期」並存未對齊：日曆月（`state.py:97-105`，performance／diagnosis 用）與 `campaign_period.start/end_date`。

## 形狀（四刀，順序＝依賴順序）

| # | 刀 | 形狀 | 路線 |
|---|---|---|---|
| 1 | 座標鍵存回去 | schedule 模組自己一張表掛在 `rule.id` 上：維度、座標鍵、方向、採用日、當下花費。判定結果依憲法第 7 條用日期區間列 | C（新表，站①＋ADR） |
| 2 | 記分 | 純算術：採用日前後同座標值的花費／ROAS 方向 → 對／反／沒資料。掛每日拉取之後，零 LLM、零錢 | C（同一票） |
| 3 | 分數回流 | 壓縮表多一欄「上次採用＋結果」；判定過的 experiment 規則退出 prompt（汰舊按結果不按新舊；ADR 0012 一併裁決留退）。plan prompt 多一段「上一期：節點名＋座標＋結果」——是一張小表，不是資料包 | B |
| 4 | 錢與日子 | 讀的時候算、不存、不新表（同 `period._advance_if_ended` 的慣例）：下一期起日＝上期迄日＋1、天數同上期；日預算＝上期核准額 × 步階（方向由保守 ROAS 對打平線決定）。預填進排程頁表單，使用者仍要按 | B |

第 4 刀之後使用者的工作剩：看一眼預填、按「出方案」、去 Meta 貼名字。**「基本不用操心」的最後一段（系統自己建活動、自己改預算）
要 Meta 寫入 API，是另一個目標，不在這裡**——憲法第 9 條「花錢要按」在那個目標才需要設計。

## 站①要裁決的（未裁決，不得由票填）

1. 記分的「期」：日曆月還是 `campaign_period`？（兩者今天未對齊）
2. 日預算步階的數字與來源。候選：Meta 自己的建議「單次調幅 ≤20% 免重進學習期」——站①查證原文再引；查不到就不寫數字，畫面只給方向。
3. 節點延續規則：上一期哪些節點名字原樣帶進下一期（記分「對」或「沒資料」的？），讓名稱綁定自動接回同一個 Meta 活動。
4. 自動跑 LLM 判讀：T6c 決定 10 否決；留開關預設關，開不開由使用者裁決。

## 排序

1. `issue-adopted-suggestion-drops-its-coordinate.md` — 第 1、2 刀。
2. `issue-next-period-does-not-know-the-last-one.md` — 第 3 刀。
3. `issue-budget-and-dates-are-hand-typed.md` — 第 4 刀。
