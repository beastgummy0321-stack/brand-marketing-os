-- supabase/migrations/20260908000002_schedule_imported_ad.sql
-- Module: schedule (ADR 0049). Ticket: past-ads 01
-- (docs/issues/past-ads/01-schema-imported-ad-and-advertising-history.md). ADR 0067.
--
-- An ad the platform already ran enters coordinates as an imported_ad row its owner tags;
-- no model infers why it worked (ADR 0067 rule 1). The row is channel-shaped from day one
-- (rule 2): performance stays in the channel's own spend table (meta_entity_spend today),
-- this table only carries identity, the platform's cached creative, the owner's seven
-- coordinate keys and their verbatim note. It is not a creative_candidate, not a
-- creative_slot, not a channel_entity_map row (rule 4) -- an old ad went through none of the
-- system's own generation/binding path, so it gets none of those rows.
--
-- The composite FK mirrors 20260908000001_schedule_period_node_result.sql /
-- 20260905000002_schedule_campaign_period_composite_fk.sql: a single-column
-- REFERENCES ad_channel(id) would let one organisation's brand tag an ad against another
-- organisation's channel row -- RLS still hides the other org's data, but the reference
-- dangles across a tenant boundary regardless. ad_channel(id, org_id) already carries the
-- matching UNIQUE constraint (20260903000006_schedule_channel_entity_map.sql), so the
-- composite FK costs nothing new on that side.
--
-- Dormant here (this ticket's done-check 6): the migration plus repository.py's cleanup
-- registration are the whole change. Nothing reads or writes a row yet -- ticket past-ads 03
-- is the first writer, per the literal example row in the ticket.
CREATE TABLE imported_ad (
    id TEXT PRIMARY KEY,                        -- iad_*, via db.new_id("iad")
    org_id TEXT NOT NULL REFERENCES organisation(id),
    brand_id TEXT NOT NULL REFERENCES brand(id),
    ad_channel_id TEXT NOT NULL,
    external_id TEXT NOT NULL,                  -- the platform's own id for this ad
    external_name TEXT NOT NULL,                -- the platform's name at import, verbatim
    first_seen_date date,                       -- earliest / latest spend_date on record at import
    last_seen_date date,
    creative_body TEXT,                         -- cache of what the platform returned; NULL = not
    creative_title TEXT,                        --   fetched or not returned, never "empty"
    creative_image_url TEXT,
    creative_fetched_at timestamptz,
    audience_key TEXT, pain_key TEXT, angle_key TEXT, hook_key TEXT,
    proof_key TEXT, offer_key TEXT, format_key TEXT,
    coordinates_status TEXT NOT NULL DEFAULT 'pending'
        CHECK (coordinates_status IN ('tagged','pending','not_applicable')),
    owner_note TEXT,                            -- the owner's line, verbatim
    tagged_at timestamptz,
    tagged_by TEXT,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    FOREIGN KEY (ad_channel_id, org_id) REFERENCES ad_channel(id, org_id),
    UNIQUE (org_id, brand_id, ad_channel_id, external_id)
);
CREATE INDEX imported_ad_org_id_idx ON imported_ad(org_id);
CREATE INDEX idx_imported_ad_brand_id ON imported_ad(brand_id);

-- RLS + grants + org-isolation policy, copied verbatim (per-table shape, ADR 0052) from
-- 20260908000001_schedule_period_node_result.sql:45-51 (itself copied from
-- 20260903000001_schedule_campaign_period.sql:82-88) -- every org_id table carries at least
-- one authenticated-scoped policy, no exemption list (app/tests/test_rls_tenant_policy.py::
-- test_every_org_table_has_an_authenticated_policy).
ALTER TABLE imported_ad ENABLE ROW LEVEL SECURITY;
GRANT SELECT, INSERT, UPDATE, DELETE ON imported_ad TO authenticated;
DROP POLICY IF EXISTS imported_ad_org_isolation ON imported_ad;
CREATE POLICY imported_ad_org_isolation ON imported_ad
    FOR ALL TO authenticated
    USING (org_id = current_setting('app.org_id', true))
    WITH CHECK (org_id = current_setting('app.org_id', true));
