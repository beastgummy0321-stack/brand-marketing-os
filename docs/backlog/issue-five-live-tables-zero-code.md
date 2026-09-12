# 5 張表活在資料庫裡，production 程式碼零引用

Status: 2026-09-12 查到（`grep -rlE "(INTO|FROM|UPDATE|JOIN) <table>\b" app --include=*.py`，
排除 `app/tests/`，對 `pg_tables` 的 59 張 public 表逐一數）。

零引用的五張：`decision`、`learning_ledger`、`strategy_hypothesis`、`campaign_period_budget_version`、
`brand_dismissed_calendar_category`。

成因：上一輪 ontology 的殘骸。同期建的 `campaign_cycle`／`marketing_goal`／`success_criterion`／
`task_card`／`publishing_package`／`recommendation`／`finding` 都已經 DROP，這五張漏了。
它們的害處不是空間，是誤導：`learning_ledger`／`decision` 這種名字會讓人以為「學習」「決策」
已經有落腳處，其實 Learning 現在住在 `period_node_result`，決策依據住在 `llm_task`。

做法（未裁決）：一支 `core_drop_dead_tables.sql`（`brand_dismissed_calendar_category` 前綴屬
brand_intelligence，要分兩檔）。刪前先 `grep -rn "REFERENCES <table>" supabase/migrations/`，
跑 `test_org_isolation_all_tables.py`／`test_brand_isolation_all_tables.py`／
`test_architecture_boundaries.py`。`campaign_period_budget_version` 要先確認結算的舊值是不是
本來打算存這裡（CONTEXT.md「結算」那條說舊值進稽核紀錄，所以應該是 `audit_log` 接了）。
