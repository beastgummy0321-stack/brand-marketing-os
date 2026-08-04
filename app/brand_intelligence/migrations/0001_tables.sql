-- app/brand_intelligence/migrations/0001_tables.sql
-- brand、product、brand_fact、product_fact、product_economics、brand_performance_baseline、
-- rule、claim、source_reference、official_asset、strategy_hypothesis、owned_channel
-- —— 見 docs/design/03-data-model.md §3.2。同模組內表之間使用真外鍵（03 §1）。
-- 建表順序依外鍵相依關係排列：brand -> product -> source_reference -> 其餘引用表。

CREATE TABLE IF NOT EXISTS brand (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    client_name TEXT,
    status TEXT NOT NULL,
    knowledge_version INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS product (
    id TEXT PRIMARY KEY,
    brand_id TEXT NOT NULL REFERENCES brand(id),
    name TEXT NOT NULL,
    status TEXT NOT NULL,
    knowledge_version INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_product_brand_id ON product(brand_id);

CREATE TABLE IF NOT EXISTS source_reference (
    id TEXT PRIMARY KEY,
    brand_id TEXT NOT NULL REFERENCES brand(id),
    title TEXT NOT NULL,
    url TEXT,
    source_type TEXT NOT NULL,
    published_date TEXT,
    captured_date TEXT NOT NULL,
    locale TEXT,
    note TEXT,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_source_reference_brand_id ON source_reference(brand_id);

CREATE TABLE IF NOT EXISTS brand_fact (
    id TEXT PRIMARY KEY,
    brand_id TEXT NOT NULL REFERENCES brand(id),
    fact_type TEXT NOT NULL,
    label TEXT NOT NULL,
    value TEXT NOT NULL,
    status TEXT NOT NULL,
    source_reference_id TEXT REFERENCES source_reference(id),
    confidence TEXT,
    confirmed_by TEXT,
    confirmed_at TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_brand_fact_brand_id ON brand_fact(brand_id);
CREATE INDEX IF NOT EXISTS idx_brand_fact_source_reference_id ON brand_fact(source_reference_id);

CREATE TABLE IF NOT EXISTS product_fact (
    id TEXT PRIMARY KEY,
    product_id TEXT NOT NULL REFERENCES product(id),
    brand_id TEXT NOT NULL REFERENCES brand(id),
    fact_type TEXT NOT NULL,
    label TEXT NOT NULL,
    value TEXT NOT NULL,
    status TEXT NOT NULL,
    source_reference_id TEXT REFERENCES source_reference(id),
    confidence TEXT,
    confirmed_by TEXT,
    confirmed_at TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_product_fact_product_id ON product_fact(product_id);
CREATE INDEX IF NOT EXISTS idx_product_fact_brand_id ON product_fact(brand_id);
CREATE INDEX IF NOT EXISTS idx_product_fact_source_reference_id ON product_fact(source_reference_id);

CREATE TABLE IF NOT EXISTS product_economics (
    id TEXT PRIMARY KEY,
    product_id TEXT NOT NULL REFERENCES product(id),
    brand_id TEXT NOT NULL REFERENCES brand(id),
    selling_price REAL NOT NULL,
    fixed_cost REAL,
    unit_variable_cost REAL,
    shipping_cost REAL,
    currency TEXT NOT NULL,
    cpa_roas_basis TEXT,
    effective_from TEXT,
    effective_to TEXT,
    status TEXT NOT NULL,
    source_reference_id TEXT REFERENCES source_reference(id),
    confirmed_by TEXT,
    confirmed_at TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_product_economics_product_id ON product_economics(product_id);
CREATE INDEX IF NOT EXISTS idx_product_economics_brand_id ON product_economics(brand_id);

CREATE TABLE IF NOT EXISTS brand_performance_baseline (
    id TEXT PRIMARY KEY,
    brand_id TEXT NOT NULL REFERENCES brand(id),
    product_id TEXT REFERENCES product(id),
    metric TEXT NOT NULL,
    value REAL NOT NULL,
    unit TEXT,
    basis_note TEXT,
    source_cycle_id TEXT,
    sample_note TEXT,
    as_of_date TEXT NOT NULL,
    created_by TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_bpb_brand_id ON brand_performance_baseline(brand_id);
CREATE INDEX IF NOT EXISTS idx_bpb_product_id ON brand_performance_baseline(product_id);

CREATE TABLE IF NOT EXISTS rule (
    id TEXT PRIMARY KEY,
    brand_id TEXT NOT NULL REFERENCES brand(id),
    product_id TEXT REFERENCES product(id),
    rule_type TEXT NOT NULL,
    content TEXT NOT NULL,
    severity TEXT NOT NULL,
    status TEXT NOT NULL,
    source_reference_id TEXT REFERENCES source_reference(id),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_rule_brand_id ON rule(brand_id);
CREATE INDEX IF NOT EXISTS idx_rule_product_id ON rule(product_id);

CREATE TABLE IF NOT EXISTS claim (
    id TEXT PRIMARY KEY,
    brand_id TEXT NOT NULL REFERENCES brand(id),
    product_id TEXT REFERENCES product(id),
    claim_text TEXT NOT NULL,
    claim_type TEXT NOT NULL,
    evidence_source_reference_id TEXT REFERENCES source_reference(id),
    status TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_claim_brand_id ON claim(brand_id);
CREATE INDEX IF NOT EXISTS idx_claim_product_id ON claim(product_id);

CREATE TABLE IF NOT EXISTS official_asset (
    id TEXT PRIMARY KEY,
    brand_id TEXT NOT NULL REFERENCES brand(id),
    product_id TEXT REFERENCES product(id),
    asset_kind TEXT NOT NULL,
    file_path TEXT NOT NULL,
    title TEXT,
    usage_note TEXT,
    status TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_official_asset_brand_id ON official_asset(brand_id);
CREATE INDEX IF NOT EXISTS idx_official_asset_product_id ON official_asset(product_id);

CREATE TABLE IF NOT EXISTS strategy_hypothesis (
    id TEXT PRIMARY KEY,
    brand_id TEXT NOT NULL REFERENCES brand(id),
    product_id TEXT REFERENCES product(id),
    hypothesis_type TEXT NOT NULL,
    statement TEXT NOT NULL,
    status TEXT NOT NULL,
    source_cycle_id TEXT,
    created_by TEXT NOT NULL,
    expired_at TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_strategy_hypothesis_brand_id ON strategy_hypothesis(brand_id);
CREATE INDEX IF NOT EXISTS idx_strategy_hypothesis_product_id ON strategy_hypothesis(product_id);

CREATE TABLE IF NOT EXISTS owned_channel (
    id TEXT PRIMARY KEY,
    brand_id TEXT NOT NULL REFERENCES brand(id),
    channel_type TEXT NOT NULL,
    platform TEXT NOT NULL,
    name TEXT NOT NULL,
    identifier TEXT,
    status TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_owned_channel_brand_id ON owned_channel(brand_id);
