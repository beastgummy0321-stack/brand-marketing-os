# `ad_set_ids_by_exact_name`／`ad_ids_by_exact_name` 不驗組織

Status: before-cloud——2026-09-05 從 `docs/tech-debt.md` §七認領進上雲目標（使用者裁決：上雲前全清）。
路線：route C（租戶隔離；要先裁決付哪種代價）。

**租戶防線不對稱（T3c 審查發現）**：`ad_set_ids_by_exact_name`／`ad_ids_by_exact_name`
（`app/meta/repository.py`）只拿 `org_id` 取權杖，`campaign_id`／`adset_id` 原封不動送 Meta、不驗屬於哪個組織；
姊妹函式 `campaign_ids_by_exact_name` 有驗。擋住跨組織的是呼叫端的形狀，審查逐條追過沒有任何請求構造得出
跨組織輸入。補法比「一次查詢」貴：這個資料庫沒有一張表存「campaign_id 屬於哪個組織」，要嘛多打一次
Meta API（先查官方文件核對回傳形狀），要嘛改呼叫鏈把 `binding.py` 驗過的結果往下傳（改簽章）。
是要不要付代價的設計題，留給使用者。`docs/contracts/meta.md` 已逐字記下這個不對稱。
