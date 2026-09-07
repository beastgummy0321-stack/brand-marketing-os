# 日預算與檔期起迄全靠使用者自己算好再去設定頁打，系統一個數字都不建議

Status: found 2026-09-07 by code probe. Blocked on data (同 spec.md)。
Related: `docs/issues/ui/issue-daily-budget-has-no-guide-card.md`（沒填會硬擋、卻沒提醒——那張修提醒，這張修「不必自己算」）。

## 成因（file:line）

- 日預算唯一來源＝規則卡 `schedule_budget.daily_budget`（`app/core/rule_cards.py:49-63`），設定頁通用表單改（`RuleCardsSection.tsx:135-137`）；
  出方案時讀出、為 0 就拒絕（`app/schedule/routes.py:247-249`），凍進 `campaign_period.daily_budget`（`:257`）。
- 代理只給比例，金額由程式乘（`plan.py:85`、`tree.py:155`）；核准額＝節點金額加總（`tree_approval.py:60`、`routes.py:377`），
  存 `approval.approved_amount`／`max_daily_amount`（`app/core/approval.py:38-42`）。
- 起迄日在排程頁手打（`ScheduleSetup.tsx:61-62`），後端只驗形狀（`period.py:35-46`）。
- 已有的數據：上期 `approval.max_daily_amount`、`spend_to_date`（`tree_approval._approval_overspend`）、保守／樂觀 ROAS 與打平線
  （`diagnosis.breakeven_roas`）、結算等待天數（`period.settlement_advice_days()` 讀 Meta 7d_click）。**沒有任何函式拿這些算下一期的錢。**

## 影響

使用者要自己看數字、自己決定加減、跑去設定頁改、再回排程頁；三個演練角色全部在這一段迷路（`issue-settings-detour-has-no-link.md`）。

## 最小一刀（未裁決，route B）

- 純函數 `period.next_period_suggestion(...)`：讀的時候算、不存、不新表（同 `_advance_if_ended` 慣例）。
  起日＝上期迄日＋1；天數＝上期天數；日預算＝上期 `max_daily_amount` × 步階，方向＝保守 ROAS 對打平線（高→加、低→減、沒打平線或沒資料→不動）。
- 排程頁表單預填這三格＋一行「為什麼」（用既有 ROAS 兩個值）；規則卡那格改成「上次用的值」的鏡像，不再是唯一入口。
- 使用者仍要按「出方案」與核准（憲法第 9 條）；改動不寫 Meta（`app/meta/` 唯讀）。

## 站①要裁的

步階數字與來源（spec 決定 2）；第一期沒有上期時預填什麼（規則卡值？空白硬擋？）。
