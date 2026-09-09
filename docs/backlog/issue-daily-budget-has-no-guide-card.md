# 檔期日預算沒填會硬擋排程，但指南卡引擎不提醒——每個新品牌都必然撞牆一次

Status: open——2026-09-07 追 [issue-settings-detour-has-no-link.md] 時查到，已核對三份原始檔。

`app/core/rule_cards.py:49-63` 的 `schedule_budget` 卡，`daily_budget` 預設 `0.0`。
**這個 0 是刻意的哨兵值，不是漏填**——卡片自己的說明寫得很清楚（`:52-54`）：

> 預設 0 代表「使用者還沒填」，不是「預算是零」：還沒填之前，排程一律拒絕，
> 不會拿 0 去跑出一個沒有意義的方案。

設計是對的。問題是**沒有任何東西在使用者撞牆之前告訴他要填**。

成因：`app/dashboard/guide_cards.py` 就是為這件事存在的引擎——「下一步指南卡」，
`build()` 依登記順序掃規則、取前 `MAX_CARDS = 3` 筆（`:37`, `:89-96`）。目前登記了三條（`:83-85`）：

| 規則 | 管什麼 | 自述的定位 |
| --- | --- | --- |
| `_rule_conversion_goal_missing` | 品牌沒設廣告目標 | 「資料正確性前提，優先度高於一般提醒」 |
| `_rule_intake_in_progress` | 建檔精靈有草稿 | 「『這個品牌能不能正常運作』的前提」 |
| `_rule_pending_facts` | 有待確認事實 | 一般提醒 |

**沒填檔期日預算跟前兩條是同一類**——它是「這個品牌能不能正常運作」的前提，而且比那兩條更硬：
沒設廣告目標只是文案會套錯預設寫法（還是產得出東西），沒填日預算是**排程直接拒絕**。
引擎裡卻沒有這條規則（`grep -rn "schedule_budget\|daily_budget" app/dashboard/` 零筆命中）。

對照組：同一個檔案的 `gross_margin` 卡預設 `0.70`（`:73`），說明寫「不填一個數字就沒有打平線可畫，
判讀會誠實顯示『算不出來』」——那是軟性降級。`schedule_budget` 是**全站唯一刻意讓功能不可用**
的哨兵值，卻是唯一沒有指南卡的。

影響：每個新建的品牌都必然走到排程頁才撞牆，然後看到那句沒有連結的提示
（[issue-settings-detour-has-no-link.md]，2026-09-06 演練 3/3 全部卡在那裡）。
那張票修的是「撞牆之後有沒有路走」，這張修的是「有沒有必要撞這面牆」。兩張都做才是完整的。

做法（未裁決）：在 `RULES` 裡登記第四條 `_rule_daily_budget_missing`，登記位置在
`conversion_goal_missing` 與 `intake_in_progress` 之間或之後（優先序要裁決），
`action_url` 指向設定頁那張卡並帶 brandId。`MAX_CARDS = 3` 不夠裝四條時誰讓位，也要一併裁決。
`facts` 目前有沒有帶日預算、要不要加一個查詢——實作時才知道，屬於 route B 範圍。

檔案：
- `app/core/rule_cards.py:49-63`（`schedule_budget` 卡與哨兵值的說明）、`:64-76`（`gross_margin` 對照組）
- `app/dashboard/guide_cards.py:37`（`MAX_CARDS`）、`:38-82`（三條現有規則）、`:83-85`（`RULES` 登記表）
- `frontend/src/components/schedule/ScheduleSetup.tsx:73`（撞牆時看到的那句話）
