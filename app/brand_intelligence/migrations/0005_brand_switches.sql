-- 品牌條件開關（票 A：方法論依品牌條件挑選載入，讓 KOL／個人賣家／服務業等能跳過
-- 台灣保健食品 D2C 電商的預設方法論檔）。兩欄預設 NULL——既有品牌未設定時，
-- 方法論開關一律視為「不成立」，見 app/brand_intelligence/repository.py 的
-- compute_methodology_switches()；不倒填猜測值，缺資料就是缺資料。
--
-- market_region：ISO 3166-1 alpha-2 國碼。目前唯一有對應方法論內容的值是 'TW'
-- （app/methodology/ 現有內容全部是台灣市場，其他國碼先進資料庫、之後有內容再對應）。
--
-- conversion_goal：平台中立轉換目標，只收 purchase／lead／booking／awareness 四值
-- （app/brand_intelligence/repository.py 的 CONVERSION_GOALS 把關）。不得存 Meta 事件名——
-- Meta 專屬欄位名只能關在 app/ads/meta_api.py（決策 0016 硬性原則 1），這裡刻意存
-- 平台中立值，Meta 標準事件對照表另由 README 記錄（票 B 範圍）。
ALTER TABLE brand ADD COLUMN market_region TEXT;
ALTER TABLE brand ADD COLUMN conversion_goal TEXT;
