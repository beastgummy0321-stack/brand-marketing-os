# 0021：人物誌獨立持久化，照片卡沿用草稿 JSON

T2 只新增品牌層 `persona` 小表；照片產品卡與每張讀取狀態沿用 `intake_draft.scan_products_json` 的向後相容包裝，不另加欄位。真相卡整批確認仍逐列走 `intake.repository.resolve_item()`，全部落檔後才背景產生 2–4 張人物誌；生成失敗保留舊人物誌，並以工作狀態、`llm_task` 與通知誠實揭露。
