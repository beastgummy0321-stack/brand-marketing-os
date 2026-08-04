-- issue #1 後續（grilling 2026-07-28）：初掃順便偵測產品名單，供「一鍵建立產品」使用。
-- 病因修正：調研發生前產品名單必須存在，交接包才能正確枚舉適用範圍（大賢生醫 20 產品情境）。
ALTER TABLE intake_draft ADD COLUMN scan_products_json TEXT;
