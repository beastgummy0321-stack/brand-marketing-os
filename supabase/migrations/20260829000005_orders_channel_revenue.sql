-- supabase/migrations/20260829000005_orders_channel_revenue.sql
-- Module: orders (ticket 12, .scratch/schedule-module/issues/12-generic-channel-table.md,
-- ADR 0035 -- channels are data, and there is one offline channel).
-- Rule: migration files only CREATE tables prefixed/owned by this module.
--
-- One channel-revenue table replaces three channel-specific ones. `channel` values come
-- from app.core.vocab.CHANNEL_TYPES (website / marketplace / physical_store), validated in
-- Python, not re-declared as a DB constraint here.
--
-- revenue NULL means "unknown" (an offline shipment with no money figure), never 0. The
-- partial unique index on (brand_id, channel, external_id) is the re-import-safety
-- mechanism, the same role the unique index plays in meta_campaign_spend.

CREATE TABLE channel_revenue (
    id              text PRIMARY KEY,               -- chr_*
    org_id          text NOT NULL REFERENCES organisation(id),
    brand_id        text NOT NULL,
    channel         text NOT NULL,
    entry_date      date NOT NULL,
    external_id     text,
    revenue         numeric(14,2),
    quantity        double precision,
    note            text,
    source          text NOT NULL,
    import_batch_id text,
    created_at      timestamptz NOT NULL DEFAULT now(),
    updated_at      timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX channel_revenue_org_id_idx ON channel_revenue(org_id);
CREATE INDEX idx_channel_revenue_brand_date ON channel_revenue(brand_id, entry_date);
CREATE UNIQUE INDEX idx_channel_revenue_brand_channel_external
    ON channel_revenue(brand_id, channel, external_id) WHERE external_id IS NOT NULL;
ALTER TABLE channel_revenue ENABLE ROW LEVEL SECURITY;

-- Backfill: marketplace (Shopee report rows). No quantity/note concept on the old table.
INSERT INTO channel_revenue (id, org_id, brand_id, channel, entry_date, external_id, revenue,
    quantity, note, source, import_batch_id, created_at, updated_at)
SELECT 'chr_' || replace(gen_random_uuid()::text, '-', ''), org_id, brand_id, 'marketplace',
    order_date, order_sn, revenue, NULL, NULL, source, import_batch_id, created_at, updated_at
FROM shopee_report_row
WHERE order_date IS NOT NULL;

-- Backfill: physical_store (pharmacy shipment batches -- a shipment, not a sale, so revenue
-- is left NULL / unknown; quantity and note are the only figures the old table ever had).
INSERT INTO channel_revenue (id, org_id, brand_id, channel, entry_date, external_id, revenue,
    quantity, note, source, import_batch_id, created_at, updated_at)
SELECT 'chr_' || replace(gen_random_uuid()::text, '-', ''), org_id, brand_id, 'physical_store',
    batch_date, NULL, NULL, quantity, note, 'manual', NULL, created_at, created_at
FROM pharmacy_batch;

-- Backfill: website (own-site orders). A voided order earned zero, which is a known number,
-- not an unknown one -- so it gets revenue = 0, not NULL. Statuses match
-- app.orders.repository.VOIDED_ORDER_STATUSES.
INSERT INTO channel_revenue (id, org_id, brand_id, channel, entry_date, external_id, revenue,
    quantity, note, source, import_batch_id, created_at, updated_at)
SELECT 'chr_' || replace(gen_random_uuid()::text, '-', ''), org_id, brand_id, 'website',
    order_date, order_number,
    CASE WHEN lower(order_status) IN ('cancelled', 'canceled', 'voided', 'void') THEN 0
         ELSE COALESCE(total_amount, 0) - COALESCE(refunded_amount, 0) END,
    NULL, NULL, source, import_batch_id, created_at, updated_at
FROM order_record
WHERE order_date IS NOT NULL;

-- The three tables this module owned for channel-specific data are superseded by the row
-- above; cycle_shopee_code's only FK (campaign_cycle) was already dropped with the ads module
-- (see 20260826000005_orders_baseline.sql header) and nothing reads or writes it.
DROP TABLE shopee_report_row;
DROP TABLE pharmacy_batch;
DROP TABLE cycle_shopee_code;
