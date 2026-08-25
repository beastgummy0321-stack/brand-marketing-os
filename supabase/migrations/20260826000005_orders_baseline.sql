-- supabase/migrations/20260826000005_orders_baseline.sql
-- Module: orders
-- Generated from app/orders/migrations 0001..0005 on 2026-08-26 (ADR 0027 rebaseline).
-- Rule: migration files only CREATE tables prefixed/owned by this module.
--
-- cycle_shopee_code.campaign_cycle_id: source SQL (0005_channel.sql) declares
-- `REFERENCES campaign_cycle(id)`, a cross-module FK (orders -> ads), which the container
-- contract forbids (0 cross-module FKs, maintain 0). Kept as plain text, no REFERENCES —
-- see .scratch/saas/tickets/02-2-type-decisions.md item 6.

CREATE TABLE customer (
    id TEXT PRIMARY KEY,               -- cus_*
    org_id text NOT NULL REFERENCES organisation(id),
    brand_id TEXT NOT NULL,
    identity_hash TEXT NOT NULL,
    identity_type TEXT NOT NULL,
    first_order_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX customer_org_id_idx ON customer(org_id);
CREATE UNIQUE INDEX idx_customer_brand_hash ON customer(brand_id, identity_hash);

CREATE TABLE order_record (
    id TEXT PRIMARY KEY,               -- ord_*
    org_id text NOT NULL REFERENCES organisation(id),
    brand_id TEXT NOT NULL,
    customer_id TEXT,
    order_number TEXT NOT NULL,
    order_date date,
    total_amount numeric(14,2),
    refunded_amount numeric(14,2),
    financial_status TEXT,
    fulfillment_status TEXT,
    order_status TEXT,
    voucher_code TEXT,
    currency TEXT,
    source TEXT NOT NULL,
    import_batch_id TEXT,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    attribution_override TEXT          -- 0002_attribution.sql; NULL | 'excluded'
);
CREATE INDEX order_record_org_id_idx ON order_record(org_id);
CREATE UNIQUE INDEX idx_order_brand_number ON order_record(brand_id, order_number);
CREATE INDEX idx_order_customer ON order_record(customer_id);
CREATE INDEX idx_order_brand_date ON order_record(brand_id, order_date);

CREATE TABLE order_item (
    id TEXT PRIMARY KEY,
    org_id text NOT NULL REFERENCES organisation(id),
    brand_id TEXT NOT NULL,
    order_id TEXT NOT NULL,
    sku TEXT,
    item_price numeric(14,2),
    quantity double precision,
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX order_item_org_id_idx ON order_item(org_id);
CREATE INDEX idx_order_item_order ON order_item(order_id);
CREATE INDEX idx_order_item_sku ON order_item(brand_id, sku);

CREATE TABLE sku_cost (
    id TEXT PRIMARY KEY,
    org_id text NOT NULL REFERENCES organisation(id),
    brand_id TEXT NOT NULL,
    sku TEXT NOT NULL,
    unit_cost numeric(14,2) NOT NULL,
    updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX sku_cost_org_id_idx ON sku_cost(org_id);
CREATE UNIQUE INDEX idx_sku_cost_brand_sku ON sku_cost(brand_id, sku);

-- ============================================================
-- 0003_sku_cost_version.sql
-- ============================================================
CREATE TABLE sku_cost_version (
    id TEXT PRIMARY KEY,                -- skv_*
    org_id text NOT NULL REFERENCES organisation(id),
    brand_id TEXT NOT NULL,
    sku TEXT NOT NULL,
    version INTEGER NOT NULL,
    unit_cost numeric(14,2) NOT NULL,
    valid_from date NOT NULL,   -- judgment call: type-decisions.md item 4
    valid_to date,              -- judgment call: type-decisions.md item 4
    created_by TEXT NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX sku_cost_version_org_id_idx ON sku_cost_version(org_id);
CREATE UNIQUE INDEX idx_skv_brand_sku_version ON sku_cost_version(brand_id, sku, version);
CREATE INDEX idx_skv_brand_sku_valid ON sku_cost_version(brand_id, sku, valid_to);

-- ============================================================
-- 0004_policy_change_log.sql
-- ============================================================
CREATE TABLE policy_change_log (
    id TEXT PRIMARY KEY,                -- pcl_*
    org_id text NOT NULL REFERENCES organisation(id),
    brand_id TEXT NOT NULL,
    policy_type TEXT NOT NULL,
    changed_at timestamptz NOT NULL,
    description TEXT NOT NULL,
    created_by TEXT NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX policy_change_log_org_id_idx ON policy_change_log(org_id);
CREATE INDEX idx_policy_change_brand_date ON policy_change_log(brand_id, changed_at);

-- ============================================================
-- 0005_channel.sql
-- ============================================================
CREATE TABLE shopee_report_row (
    id TEXT PRIMARY KEY,                -- shp_*
    org_id text NOT NULL REFERENCES organisation(id),
    brand_id TEXT NOT NULL,
    order_sn TEXT,
    order_date date,
    revenue numeric(14,2),
    voucher_code TEXT,
    source TEXT NOT NULL,
    import_batch_id TEXT,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX shopee_report_row_org_id_idx ON shopee_report_row(org_id);
CREATE INDEX idx_shopee_report_brand_date ON shopee_report_row(brand_id, order_date);
CREATE UNIQUE INDEX idx_shopee_report_brand_sn
    ON shopee_report_row(brand_id, order_sn) WHERE order_sn IS NOT NULL;

CREATE TABLE pharmacy_batch (
    id TEXT PRIMARY KEY,                -- phb_*
    org_id text NOT NULL REFERENCES organisation(id),
    brand_id TEXT NOT NULL,
    batch_date date NOT NULL,
    quantity double precision,
    note TEXT,
    created_by TEXT NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX pharmacy_batch_org_id_idx ON pharmacy_batch(org_id);
CREATE INDEX idx_pharmacy_batch_brand_date ON pharmacy_batch(brand_id, batch_date);

CREATE TABLE cycle_shopee_code (
    id TEXT PRIMARY KEY,                -- shc_*
    org_id text NOT NULL REFERENCES organisation(id),
    brand_id TEXT NOT NULL,
    campaign_cycle_id TEXT NOT NULL,    -- cross-module id, no FK (see file header note)
    code TEXT,
    redemption_count INTEGER,
    updated_by TEXT NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX cycle_shopee_code_org_id_idx ON cycle_shopee_code(org_id);
CREATE UNIQUE INDEX idx_shopee_code_cycle ON cycle_shopee_code(campaign_cycle_id);
