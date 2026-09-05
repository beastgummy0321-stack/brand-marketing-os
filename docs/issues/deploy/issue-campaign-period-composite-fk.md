# `campaign_period` 的八條 FK 升成複合鍵

Status: before-cloud——2026-09-05 從 `docs/tech-debt.md` §七認領進上雲目標（使用者裁決：上雲前全清）。
路線：route C（schema＋租戶隔離）。

**`campaign_period` 的 FK 沒用複合鍵（T6a 審查量出）**：`channel_entity_map`／`period_node_membership`／
`channel_credential` 用 `FOREIGN KEY (channel_id, org_id) REFERENCES ad_channel(id, org_id)` 在資料庫層擋跨組織；
但指向 `campaign_period` 的八條 FK（`decision`／`interrupt`／`llm_task`／`feedback`／`period_node_membership`／
`campaign_period_budget_version`／`channel_revenue`＋自己的 `source_period_id`）與六條自參照全是單欄。
升成 `(id, org_id)` 唯一鍵＋八條複合 FK 是一張獨立 route C 票，不是順手做的事。
