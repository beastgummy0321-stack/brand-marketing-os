-- supabase/migrations/20260904000001_orders_channel_revenue_dedupe.sql
-- Module: orders (ADR 0049 -- migration files are prefixed/owned by the module that owns the
-- table; orders owns channel_revenue). Ticket T7 (docs/adr/0050-...:89 is the authoritative
-- column list): the manual channel-entry write path (record_channel_entry) has no dedup key at
-- all today, so pressing the manual form twice doubles revenue. The other two write paths
-- (_sync_website_channel_revenue, save_shopee_rows) already dedupe on external_id and are
-- untouched by this file.
--
-- Every new column is nullable (constitution rule 3: the column exists from day one even though
-- the feature does not, so opening it later is a switch, not a migration). `spend`,
-- `campaign_period_id` and `ad_channel_id` get no writer in this ticket -- they are T6's join
-- target. `source_row_hash` is written only by record_channel_entry (the write path with no
-- external_id); the other two paths leave it NULL so two genuinely different orders that happen
-- to hash identically are never refused by the new unique index.

ALTER TABLE channel_revenue
    ADD COLUMN spend              numeric(14,2),
    ADD COLUMN currency           text,
    ADD COLUMN campaign_period_id text REFERENCES campaign_period(id),
    ADD COLUMN ad_channel_id      text REFERENCES ad_channel(id),
    ADD COLUMN source_row_hash    text;

CREATE UNIQUE INDEX idx_channel_revenue_brand_channel_row_hash
    ON channel_revenue(brand_id, channel, source_row_hash)
    WHERE source_row_hash IS NOT NULL;
