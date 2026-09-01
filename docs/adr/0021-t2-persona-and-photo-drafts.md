---
id: 0021
decision: Personas get their own brand-layer table; photo product cards stay inside the intake draft JSON.
applies-to: [app/brand_intelligence/personas.py, app/intake/]
supersedes: none
status: in-force
---

# 0021：人物誌獨立持久化，照片卡沿用草稿 JSON

T2 只新增品牌層 `persona` 小表；照片產品卡與每張讀取狀態沿用 `intake_draft.scan_products_json` 的向後相容包裝，不另加欄位。真相卡整批確認仍逐列走 `intake.repository.resolve_item()`，全部落檔後才背景產生 2–4 張人物誌；生成失敗保留舊人物誌，並以工作狀態、`llm_task` 與通知誠實揭露。

## 2026-08-15 追加：人物誌人工修改

人工修改只更新既有一張人物誌的五欄，不新增資料表或 migration；資料異動與前後內容審計在
`app.brand_intelligence.personas` 同一個交易完成。使用者確認重新產生後，才允許新一批人物誌
取代手動修改內容。
