-- F31-I01 Contract M: the offerings step's two choices (賣什麼 / 廣告帶來的是什麼) live on the
-- draft, because product_economics.close_rate cannot tell 先詢問 from 留資料 and a service sold
-- directly has no close_rate at all. Shape: {"sell_type": "product"|"service"|"both",
-- "ad_delivery": "direct"|"ask"|"lead"}; NULL = never saved (the screen infers as before).
ALTER TABLE intake_draft ADD COLUMN offerings_choice_json jsonb;
