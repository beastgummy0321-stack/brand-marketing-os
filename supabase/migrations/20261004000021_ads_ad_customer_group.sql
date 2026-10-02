-- supabase/migrations/20261004000021_ads_ad_customer_group.sql
-- Module: ads (F46-I01, Contract A). The customer group is a planned ad's 8th coordinate: the
-- delivery-plan model names one 第 N 群 of the prompt's 【這個賣法的顧客】 per ad and the program
-- maps N to the group id (`app/ads/plan.py`). No FK: `product_customer_group` belongs to
-- brand_intelligence, and a deleted group simply reads as unknown. Nullable, no default:
-- hand-made ads, plans made when no group was listed, and rows from before this migration have
-- none. Readers: `assets._ad_set` (the copy brief's `request.customer_group`) and the closeout
-- learning rows.

ALTER TABLE ads_ad ADD COLUMN customer_group_id text;
