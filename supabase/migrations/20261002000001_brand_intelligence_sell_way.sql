-- Module: brand_intelligence. Ticket: F43-I01 (feature F43, decisions "Storage" and "One resolver each").
--
-- Product = knowledge, sell-way = what a campaign sells:
--   * product.page_url -- the knowledge product's own product page. Writer: set_product_page_url;
--     readers: product onboarding, the landing default of its sell-ways.
--   * product.landing_url -- a sell-way's landing page; NULL = its first component's page_url.
--     Writer: save_sell_way; readers: product onboarding, the new-campaign defaults.
--   * product.onboarding_step -- NULL = product onboarding done, 1-5 = 建到一半 (such a product
--     and its sell-ways are not pickable). Writer: set_product_onboarding_step.
--   * product_economics / product_economics_version .list_price (NULL = derived from the
--     components' single prices) and .cap_per_sale (NULL = break-even). Writer:
--     save_product_economics; reader: get_product_economics (effective values) and its readers
--     (budget, targets, learning, wizard, offers).
--   * product_fact.fact_key -- the proof kind of a product proof fact, the same CHECK pair as
--     brand_fact (20260929000002_brand_intelligence_brand_fact_key.sql). Reader:
--     available_proof_keys.
--   * product_component -- the products a sell-way sells (sell_way_id -> the sell-way's product
--     row, product_id -> a knowledge product, qty). Every sell-way written by save_sell_way has
--     >= 1 row; F05 sell-ways written before F43 have none (resolvers fall back to parent_id).
--     Writer: save_sell_way; readers: knowledge_product_ids, get_product_economics,
--     available_offer_keys / offer_sources, list_sell_ways.
--   * product_customer_group -- 1-3 customer groups of a knowledge product. Writer:
--     save_customer_groups; readers: list_customer_groups (planner / strategy prompts).
--
-- Both new tables belong to brand_intelligence (the owner of `product`) and are written only
-- through app/brand_intelligence/repository.py.
--
-- `grep -rn "REFERENCES product" supabase/migrations/` before this migration (nothing is
-- re-pointed here; the two new tables add product FKs with ON DELETE CASCADE):
--   20260826000002_brand_intelligence_baseline.sql: product_fact, product_economics,
--     brand_performance_baseline, rule, claim, official_asset, strategy_hypothesis (dropped)
--   20260903000004_brand_intelligence_product_economics_version.sql: product_economics_version
--   20260909000001_workbench_baseline.sql / 20260911000002: workbench_brief (ON DELETE SET NULL)
--   20260913000001_ads_tables.sql / 20260927000007: ads_ad (ON DELETE SET NULL)
--   20260914000001_brand_intelligence_product_hierarchy_and_economics.sql: product.parent_id
--     (ON DELETE CASCADE)

ALTER TABLE product ADD COLUMN page_url text;
ALTER TABLE product ADD COLUMN landing_url text;
ALTER TABLE product ADD COLUMN onboarding_step smallint
    CHECK (onboarding_step BETWEEN 1 AND 5);

ALTER TABLE product_economics ADD COLUMN list_price numeric(14,2);
ALTER TABLE product_economics ADD COLUMN cap_per_sale numeric(14,2);
ALTER TABLE product_economics_version ADD COLUMN list_price numeric(14,2);
ALTER TABLE product_economics_version ADD COLUMN cap_per_sale numeric(14,2);

ALTER TABLE product_fact ADD COLUMN fact_key text;
ALTER TABLE product_fact ADD CONSTRAINT product_fact_proof_key_valid
    CHECK (fact_type <> 'proof' OR fact_key IN ('customer_review', 'expert_endorsement', 'lab_report',
                                                'sales_numbers', 'media_coverage', 'founder_voice'));
ALTER TABLE product_fact ADD CONSTRAINT product_fact_key_only_for_proof
    CHECK (fact_type = 'proof' OR fact_key IS NULL);

CREATE TABLE product_component (
    id text PRIMARY KEY,                                   -- pco_*
    org_id text NOT NULL REFERENCES organisation(id),
    brand_id text NOT NULL REFERENCES brand(id),
    sell_way_id text NOT NULL REFERENCES product(id) ON DELETE CASCADE,
    product_id text NOT NULL REFERENCES product(id) ON DELETE CASCADE,
    qty integer NOT NULL CHECK (qty > 0),
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (sell_way_id, product_id),
    CHECK (sell_way_id <> product_id)
);
CREATE INDEX product_component_org_id_idx ON product_component(org_id);
CREATE INDEX product_component_brand_id_idx ON product_component(brand_id);
CREATE INDEX product_component_product_id_idx ON product_component(product_id);

CREATE TABLE product_customer_group (
    id text PRIMARY KEY,                                   -- pcg_*
    org_id text NOT NULL REFERENCES organisation(id),
    brand_id text NOT NULL REFERENCES brand(id),
    product_id text NOT NULL REFERENCES product(id) ON DELETE CASCADE,
    position smallint NOT NULL CHECK (position BETWEEN 1 AND 3),
    who text NOT NULL,
    pain_keys text[] NOT NULL
        CHECK (cardinality(pain_keys) BETWEEN 1 AND 2
               AND pain_keys <@ ARRAY['cost', 'effort', 'uncertainty', 'availability',
                                      'experience', 'identity']::text[]),
    quote text,
    when_used text,
    source text NOT NULL CHECK (source IN ('ai', 'user', 'custom')),
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (product_id, position)
);
CREATE INDEX product_customer_group_org_id_idx ON product_customer_group(org_id);
CREATE INDEX product_customer_group_brand_id_idx ON product_customer_group(brand_id);

-- RLS + grants + org-isolation policy, per table (the same shape as
-- 20260903000004_brand_intelligence_product_economics_version.sql).
ALTER TABLE product_component ENABLE ROW LEVEL SECURITY;
GRANT SELECT, INSERT, UPDATE, DELETE ON product_component TO authenticated;
DROP POLICY IF EXISTS product_component_org_isolation ON product_component;
CREATE POLICY product_component_org_isolation ON product_component
    FOR ALL TO authenticated
    USING (org_id = current_setting('app.org_id', true))
    WITH CHECK (org_id = current_setting('app.org_id', true));

ALTER TABLE product_customer_group ENABLE ROW LEVEL SECURITY;
GRANT SELECT, INSERT, UPDATE, DELETE ON product_customer_group TO authenticated;
DROP POLICY IF EXISTS product_customer_group_org_isolation ON product_customer_group;
CREATE POLICY product_customer_group_org_isolation ON product_customer_group
    FOR ALL TO authenticated
    USING (org_id = current_setting('app.org_id', true))
    WITH CHECK (org_id = current_setting('app.org_id', true));
