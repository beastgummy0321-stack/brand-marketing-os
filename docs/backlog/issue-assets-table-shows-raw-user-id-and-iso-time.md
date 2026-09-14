# 素材分頁表格印出使用者 UUID 與原始 ISO 時間

Status: 2026-09-14 F06-I03 截圖看到（F06 之前就存在，不屬於該票）。

事實：`frontend/src/components/ads/AssetsTab.tsx` 的「狀態」欄在徽章旁印 `{row.by} 於 {row.at}`，「最後同步」欄印
`row.at`；實際畫面是「b0a57eef-0000-4000-8000-000000000123 於 2026-09-14T09:58:31.184106+00:00」。
非工程使用者看不懂，也占掉整張表一半寬度。

待查／待定：
- `row.by` 是 user id；要顯示名稱或 email 得有人給名字（`AssetReadinessRow` 的產生處在 `app/ads/assets.py::readiness`），
  還是乾脆不顯示是誰勾的。
- 時間用 `frontend/src/lib/format.ts` 既有格式化函式（若有）轉成「9月14日 17:58」這種在地時間；
  「狀態」欄與「最後同步」欄重複印同一個時間，留一個即可。
