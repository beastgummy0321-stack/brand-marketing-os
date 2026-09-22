-- supabase/migrations/20260922000001_ads_runtime_events.sql
-- Module: ads (F27-I00, Contract J + pre-dispatch correction 3). A durable trail of two kinds
-- of background-process evidence, read later by the recovery banner (Contract K, a later F27
-- issue):
--
-- `beat` -- written every minute by the existing per-minute ads periodic task (`jobs.py`'s
-- `ads_runtime` cron, wrapping `runtime.dispatch`) -- proves the whole ads background system is
-- alive, never any one brand's own worker. `org_id`/`brand_id` are always NULL on a beat row.
--
-- `queue_refresh` -- written by `triage.refresh_queue` for the ONE brand it just refreshed --
-- `org_id`/`brand_id` are always filled on this kind (correction 3: "queue_refresh rows carry
-- org_id and brand_id").
--
-- `org_id` is nullable (a beat has none) -- the RLS policy below is the same
-- org-isolation shape every other ads table uses, widened with `org_id IS NULL OR ...` so a beat
-- row (visible to every tenant, by design: it is not tenant data) still passes it. Rows are
-- pruned after 48h by `app/ads/runtime_events.py::prune()` (called from the same per-minute task,
-- once an hour) -- the index below is shaped for that scan plus the per-kind/per-brand reads
-- `list_since()` does.
--
-- `ads_external_entity.status_changed_at`: set by `external_repository.upsert_entity` whenever an
-- ad's own active/closed category (`ad_status.is_closed`) actually changes between the previously
-- stored and newly written `native_status` (both known) -- read later by Contract A's
-- `history`/`cost_before`/`cost_after` windows and Contract G's `closed_this_month`. NULL until
-- the first observed transition; a first insert never sets it (there is no "before" to compare).

CREATE TABLE ads_runtime_event (
    id text PRIMARY KEY,
    kind text NOT NULL CHECK (kind IN ('beat', 'queue_refresh')),
    org_id text REFERENCES organisation(id),
    brand_id text REFERENCES brand(id),
    at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX ads_runtime_event_kind_idx ON ads_runtime_event(kind, brand_id, at);

ALTER TABLE ads_runtime_event ENABLE ROW LEVEL SECURITY;
GRANT SELECT, INSERT, UPDATE, DELETE ON ads_runtime_event TO authenticated;
CREATE POLICY ads_runtime_event_org_isolation ON ads_runtime_event FOR ALL TO authenticated
    USING (org_id IS NULL OR org_id = current_setting('app.org_id', true))
    WITH CHECK (org_id IS NULL OR org_id = current_setting('app.org_id', true));

ALTER TABLE ads_external_entity ADD COLUMN status_changed_at timestamptz;
