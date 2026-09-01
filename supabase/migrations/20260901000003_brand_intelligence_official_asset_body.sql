-- supabase/migrations/20260901000003_brand_intelligence_official_asset_body.sql
-- Module: brand_intelligence (ADR 0049 rule 2 -- a migration file takes the prefix of the
-- module that owns the table it creates/alters, never the ticket that wanted the change).
-- Ticket: T1b. ADR 0050's `official_asset` row: an asset can now carry its body inline
-- (body_text / body_json) instead of a Storage object, and can be a derivative of another
-- asset (parent_asset_id).

ALTER TABLE official_asset ALTER COLUMN storage_key DROP NOT NULL;
ALTER TABLE official_asset
    ADD COLUMN body_text TEXT,
    ADD COLUMN body_json jsonb,
    ADD COLUMN parent_asset_id TEXT REFERENCES official_asset(id),
    ADD COLUMN platform TEXT,
    ADD COLUMN aspect_ratio TEXT,
    ADD COLUMN superseded_by_asset_id TEXT REFERENCES official_asset(id),
    ADD COLUMN usable_until date,
    ADD COLUMN provider TEXT,
    ADD COLUMN no_derivative boolean NOT NULL DEFAULT false,
    ADD COLUMN content_hash TEXT,
    ADD CONSTRAINT official_asset_id_brand_id_key UNIQUE (id, brand_id),
    ADD CONSTRAINT official_asset_has_body CHECK (
        storage_key IS NOT NULL OR body_text IS NOT NULL OR body_json IS NOT NULL);
CREATE INDEX idx_official_asset_parent_asset_id ON official_asset(parent_asset_id);
