# 4 張表活在資料庫裡，production 程式碼零引用

Status: 2026-09-12 查到（`grep -rlE "(INTO|FROM|UPDATE|JOIN) <table>\b" app --include=*.py`，
排除 `app/tests/`，對 `pg_tables` 的 59 張 public 表逐一數）。
2026-09-12 /carve F03 更新：原本五張裡的 **`learning_ledger` 已除名**——投放中心（Ads V2）
把它復活了，寫入端是 `app/brand_intelligence/repository.py` 的 `record_learning`／`list_learnings`
（ARCHITECTURE.md §3 的裁決：學習是品牌知識，留在 brand_intelligence，`ads` 不直接寫別人的表）。

零引用的四張：`decision`、`strategy_hypothesis`、`campaign_period_budget_version`、
`brand_dismissed_calendar_category`。

成因：上一輪 ontology 的殘骸。同期建的 `campaign_cycle`／`marketing_goal`／`success_criterion`／
`task_card`／`publishing_package`／`recommendation`／`finding` 都已經 DROP，這幾張漏了。
它們的害處不是空間，是誤導：`decision` 這種名字會讓人以為「決策」已經有落腳處，
其實決策依據住在 `llm_task`，Action 從 F03 起住在 `ads_action`。

`campaign_period_budget_version` 的角色已經由 `ads_action` 接走（ARCHITECTURE.md §6.5），
所以它不只是沒人用，是確定不會再有人用。

做法（未裁決）：一支 `core_drop_dead_tables.sql`（`brand_dismissed_calendar_category` 前綴屬
brand_intelligence，要分兩檔）。刪前先 `grep -rn "REFERENCES <table>" supabase/migrations/`，
跑 `test_org_isolation_all_tables.py`／`test_brand_isolation_all_tables.py`／
`test_architecture_boundaries.py`。F03 沒有做這件事：刪死表跟閉環無關，不值得混進大改版的 diff。
