# ARCHITECTURE.md 沒有「這個系統要證明什麼、失效長什麼樣」那一節

Status: 2026-09-12 拿「MarketingOS 實作 Agent 系統級自我檢查」文件對照 repo 診斷出來的；
文件全文在使用者手上，不進 repo。這條是它的落地方式＋當天的診斷結論，給下一次 /dig 用。

成因：`ARCHITECTURE.md` 只有模組地圖與定案，沒有一段講「閉環要證明什麼、什麼訊號代表 OS
架構在失效」。規劃師每次判斷「這張票是在建 OS 還是在堆功能」都得從頭猜。

**裁決（2026-09-12）**：不另開 SYSTEM_SELF_CHECK.md（真相檔只有三處，第四份檔就是那份文件自己
§17 罵的 Markdown-first）；不做閘門（沒有一條能被機器判紅，0 次觸發＝裝飾）；不放 78／35／85
那種信心分數（數字進文件就過期）。只做兩件事：ARCHITECTURE.md 加 §0（40 行以內，草稿在最下面），
feature 收尾的整合審查多問一句 §0 最後那句話。

## 當天診斷結論（下一次 /dig 直接拿這個對，不用重讀 repo）

一句話：閉環骨架已接通、每一環在 DB 裡追得回去（結構 PASS）；目標客群走一遍撞三面牆，
且「AI 為什麼這樣建議」只在 DB、畫面看不到（體感未 PASS）。

七個核心物件：Brand／Offering／Artifact／Outcome 都有且可回溯；Campaign（`campaign_period`）沒有
「為什麼做」「成功怎麼判」欄位，成功只隱含在 ROAS 對打平線；Action 沒有這個物件——Meta 零寫入
（`app/meta/graph.py` 只有 list／fetch），手動建廣告再「綁定」對回來；Learning＝`period_node_result`
逐節點判決，下一期樹的 prompt 讀【上一期】，只記得一期、沒有跨期歸納。

三面牆（三場演練都撞到，都已有 backlog）：
1. `issue-intake-handoff-dead-end.md`——品牌事實填不進去，方案裡沒有一個數字來自這個帳戶。
2. `issue-daily-budget-has-no-guide-card.md`——每個新品牌必撞一次。
3. `issue-period-page-has-no-history.md`——上一期從畫面消失，Trust Layer 的「依據什麼」使用者看不到
   （`llm_task` 其實存了 `knowledge_item_ids_json`／`input_context_hash`）。

停損訊號命中三條：使用者 Copy／Paste（投放包→Meta 是「手動一級公民」的裁決，可接受；調研包→外部
AI 是第 1 面牆）；使用者要懂模組名稱（入口是側欄七個模組，演練者搜「歷史」「切換」零結果）；
功能增加但完整工作走不完。其餘沒中。

Autonomy 現在是 Level 2（AI 建議、人執行）；`approval.max_daily_amount` 是 Level 3 的煞車先造好、
車還沒有。沒搶跑，不用動。

Scope Explosion 已發生過一次且砍掉了：migration 史建過約 120 張表，活著 59 張；
`campaign_cycle`／`experiment_cell`／`marketing_goal`／`success_criterion`／`task_card`／
`publishing_package`／`recommendation`／`finding` 都是建了又刪。殘骸見 `issue-five-live-tables-zero-code.md`。

排序（前三條是既有 backlog，第 4 條新，第 5 條等前三條做完再談）：
1. 建檔精靈第 4 步加「先跳過，之後隨時回來」。半天。
2. 指南卡加「日預算未填」規則。半天。
3. 檔期歷史畫面，切到舊期鎖寫入按鈕。新畫面，先 /demo。
4. 刪 5 張死表。
5. 「你現在想完成什麼」的 goal-first 入口——唯一真的新東西，指南卡引擎是它的雛形。

要裁決的一題：要不要給「系統幫我跑調研（花錢）」這條路（第 1 面牆的第二刀）。

## §0 草稿（英文，貼進 ARCHITECTURE.md §1 前面）

```
## 0. What this system is for, and what failure looks like

MarketingOS owns one thing: the brand's decision flow —
goal → context → decision → strategy → artifact → action → outcome → learning → next goal.
Success is whether that chain closes for one brand, not how many modules exist.

Before cutting any issue the planner answers five questions:
1. Which link of the chain does this serve? No answer = an isolated feature.
2. Where does its input come from? Existing brand / product / period / history rows — never re-asking the user.
3. Where does its output go? Into the next link as structured data, not a screen the user copies from.
4. What trace does it leave? Why, what, which data, who approved, what happened.
5. If removed, does the OS still hold? Yes = pluggable module. No = core.

Golden path (prove this before any new module): brand → offering → goal → plan → tree → pack →
artifacts → 投放包 → approval → run (manual or simulated) → outcome → verdict → next-period
suggestion → the next tree reads the verdict.

Stop signals — any one means stop adding features and re-check the architecture:
- a module keeps its own copy of brand data · one product fact lives in two places
- the user copies between screens · a step cannot see what the previous step did
- an outcome cannot find its period · a learning cannot show its evidence · a suggestion cannot say why
- one feature touches many modules · every feature adds system prompt · the user must know module
  names to finish a simple job · features grow but the full job still does not complete

Autonomy is earned: observe → recommend → act with approval → bounded autonomy. Today: recommend,
manual execution, zero writes to Meta. Learning keeps its uncertainty: 「看不出」 is a valid verdict
and a correlation is never reported as a cause.

Every feature close answers one sentence: did this make the OS better at understanding, deciding,
executing, learning and handing over — or did it add a feature?
```
