-- supabase/migrations/20260903000012_schedule_channel_credential.sql
-- Module: schedule (ADR 0050 assigns this table to schedule; a new CREATE, so the ownership
-- registry -- test_migration_ownership.py -- records it under this file's prefix).
-- Ticket: T4. Decision of record: ADR 0056 §4.
--
-- Replaces the module's earlier one-row-per-org credential table, whose PRIMARY KEY was
-- org_id -- one token per organisation, hard coded into the schema (dropped at the bottom of
-- this file). channel_credential is keyed unique(org_id, channel_id,
-- account_scope): v1 writes only the literal '*' (org-wide), so today's behaviour is
-- unchanged. Holding two tokens later is writing a different value into a column that
-- already exists -- the switch constitution rule 3 requires, not the migration it forbids.
--
-- Composite FK (channel_id, org_id) -> ad_channel(id, org_id), copied from
-- channel_entity_map (20260903000006_schedule_channel_entity_map.sql): a single-column FK
-- would let org A reference org B's channel row.
--
-- The table belongs to schedule; the code that reads and writes it stays in app/meta/ (ADR
-- 0056 §4) because there is still only one channel. The write path
-- (app/meta/repository.py:save_token) carries its own copy of the lazy ad_channel insert --
-- app/meta/ cannot import app/schedule/ (schedule -> meta is the established direction; the
-- reverse would close a package cycle ImportCycleScanTest records) -- container contract §5
-- permits the duplication until a third caller.
--
-- Vault logic is unchanged: core_vault_save_secret / core_vault_read_secret, the token never
-- touching this table. The three Vault door functions' ownership check follows this table to
-- channel_credential in the next migration (20260903000014_core_vault_channel_credential.sql,
-- which must sort after this file -- it CREATE OR REPLACEs functions that reference this
-- table by name).
--
-- No backfill: the project has not shipped (CLAUDE.md -- every row is test data), and the
-- old table's last real row was already lost to a `supabase db reset` (0 rows, verified
-- on the live local DB immediately before writing this file).
CREATE TABLE channel_credential (
    id              TEXT PRIMARY KEY,                     -- new_id("chcr")
    org_id          text NOT NULL REFERENCES organisation(id),
    channel_id      TEXT NOT NULL,
    account_scope   TEXT NOT NULL,                         -- v1 writes only '*' (ADR 0056 §4)
    secret_id       uuid NOT NULL,                         -- vault.secrets.id, never the token
    token_tail      text NOT NULL,
    scopes          text[],                                -- nullable: what the token may do
    expires_at      timestamptz,                           -- nullable: unknown != never
    last_error_code text,                                  -- nullable
    updated_at      timestamptz NOT NULL DEFAULT now(),
    UNIQUE (org_id, channel_id, account_scope),
    FOREIGN KEY (channel_id, org_id) REFERENCES ad_channel(id, org_id)
);
CREATE INDEX channel_credential_org_id_idx ON channel_credential(org_id);

-- RLS + grants + org_isolation policy, same shape as ad_channel's own in
-- 20260903000006_schedule_channel_entity_map.sql -- copied, not invented.
ALTER TABLE channel_credential ENABLE ROW LEVEL SECURITY;
GRANT SELECT, INSERT, UPDATE, DELETE ON channel_credential TO authenticated;
DROP POLICY IF EXISTS channel_credential_org_isolation ON channel_credential;
CREATE POLICY channel_credential_org_isolation ON channel_credential
    FOR ALL TO authenticated
    USING (org_id = current_setting('app.org_id', true))
    WITH CHECK (org_id = current_setting('app.org_id', true));

-- The old table is replaced, not migrated -- see header. Verified 0 rows on the live local
-- DB immediately before writing this file.
DROP TABLE meta_credential;
