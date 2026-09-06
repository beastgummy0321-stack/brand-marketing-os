# 沒有選產品的活動樹按「產素材」，工作在 0.02 秒內死掉，畫面卻什麼都不說

Status: 2026-09-06 slice-10 驗收走查撞到（步驟 4）。**不是這次改出來的**：
`git show 7143a16:app/schedule/jobs.py` 裡那一行一字不差，這個 session 之前就在。
slice-10 不修它——那張票的四個 done-check 沒有一條碰得到這條路徑。

成因：`_compile_brand_context()`（`app/schedule/jobs.py:57-76`）用 `brand_version = None` 起手，
只有在 `for product_id in product_ids:` 這個迴圈裡才會被賦值。產品清單是空的時候，迴圈一次都
不跑，`brand_version` 保持 `None`，一路傳進 `gateway.TaskContext(brand_version=None)`，
`app/llm/gateway.py:126` 的 `_insert_running_row()` 拿它去寫 `llm_task.brand_version`——
那一欄是 NOT NULL，於是 `psycopg.errors.NotNullViolation`。

`product_ids` 從哪裡來（`jobs.py:281-285`）：活動樹那一列的 `context_scope_json.source_plan_task_id`
→ 那一列方案的 `context_scope_json.product_ids`。**找不到方案那一列、或那一列沒有產品，就是空清單。**
`app/tools/simulate_meta_spend.py` 種出來的樹正是這種（直接種樹，沒有方案列），所以任何人用
模擬資料開發成效這條線、順手按一下「產素材」，都會撞到。

使用者看到的：按鈕閃一下就恢復成「產素材」，右上角「生成進度」寫「目前沒有進行中的背景工作」。
**兩個地方都沒有錯誤訊息**——工作在 0.019 秒內就爆掉，快到畫面來不及顯示任何進行中的狀態。
（旁證：這不是 issue-jobs-bell-blind-to-schedule-jobs 沒修好。那條已經修了，鈴鐺現在看得到
三個排程 kind；這裡是那個工作根本沒活到可以被看見。）

影響：真的用畫面走完「出方案→展開→產素材」的人碰不到（出方案那一步一定選過產品）。碰得到的是
兩種情況：模擬資料種出來的樹，以及任何日後讓「不選產品也能出方案」的路徑。
`app/schedule/routes.py:84` 的 `product_ids: list[str] = []` 預設值讓後者只差一個前端改動。

`file:line`：`app/schedule/jobs.py:63`（`brand_version = None` 起手）、
`app/schedule/jobs.py:286-288`（唯一的呼叫端，產素材）、`app/llm/gateway.py:126`（NOT NULL 那一寫）。

做法（未裁決，兩條都很小）：
- A：`_compile_brand_context()` 沒有產品時回品牌自己的 `knowledge_version`（
  `bi_repo.get_brand(conn, brand_id)["knowledge_version"]`）——`app/schedule/jobs.py` 的判讀那支
  （`schedule_diagnosis`，2026-09-06 寫的）已經是這個寫法，抄過來就好，形狀一致。
- B：`gateway.TaskContext` 收到 `brand_version=None` 就當場報錯，讓錯誤出現在呼叫端而不是 SQL 層。
兩條可以一起做。真正要裁決的是第三件事：**背景工作在寫下 running 那一列之前就死掉時，畫面要
怎麼知道**——今天的答案是「不知道」，而這條路徑上的每一個未來錯誤都會長成同一個樣子。
