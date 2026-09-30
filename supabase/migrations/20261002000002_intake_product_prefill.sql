-- Module: intake. Ticket: F43-I01 (feature F43, decision "Storage": product prefill).
--
-- The product-onboarding AI read of a product page: a proposal per onboarding field shown on
-- each step, never a confirmed fact (confirmed values are written to the product through the
-- brand_intelligence facade when the user saves a step). One row per product; the row goes with
-- its product (ON DELETE CASCADE) and with its brand (intake's cleanup registration).
-- Writer: app.intake.repository.save_product_prefill (the product prefill job);
-- reader: app.intake.repository.get_product_prefill (product onboarding).
-- Requires 20261002000001_brand_intelligence_sell_way.sql only by order (no column of it is used).

CREATE TABLE intake_product_prefill (
    product_id text PRIMARY KEY REFERENCES product(id) ON DELETE CASCADE,
    org_id text NOT NULL REFERENCES organisation(id),
    brand_id text NOT NULL REFERENCES brand(id),
    status text NOT NULL,
    prefill_json jsonb,
    llm_task_id text,
    updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX intake_product_prefill_org_id_idx ON intake_product_prefill(org_id);
CREATE INDEX intake_product_prefill_brand_id_idx ON intake_product_prefill(brand_id);

ALTER TABLE intake_product_prefill ENABLE ROW LEVEL SECURITY;
GRANT SELECT, INSERT, UPDATE, DELETE ON intake_product_prefill TO authenticated;
DROP POLICY IF EXISTS intake_product_prefill_org_isolation ON intake_product_prefill;
CREATE POLICY intake_product_prefill_org_isolation ON intake_product_prefill
    FOR ALL TO authenticated
    USING (org_id = current_setting('app.org_id', true))
    WITH CHECK (org_id = current_setting('app.org_id', true));
