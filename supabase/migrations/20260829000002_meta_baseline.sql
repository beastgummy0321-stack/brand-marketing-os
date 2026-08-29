-- supabase/migrations/20260829000002_meta_baseline.sql
-- Module: meta (ticket 04, .scratch/schedule-module/issues/04-design-approved.md)
-- Rule: migration files only CREATE tables prefixed/owned by this module.
--
-- The Meta access token itself never lives in any of these tables — it lives in
-- Supabase Vault (`vault.secrets`), pointed at by `meta_credential.secret_id`. See
-- app/meta/repository.py for the vault.create_secret / vault.update_secret /
-- vault.decrypted_secrets round-trip.

CREATE TABLE meta_credential (
  org_id     text PRIMARY KEY REFERENCES organisation(id),
  secret_id  uuid NOT NULL,            -- vault.secrets.id — the pointer, never the token
  token_tail text NOT NULL,            -- last 4 characters, so the screen can say which token
  updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE meta_ad_account (
  id           text PRIMARY KEY,       -- new_id("mad")
  org_id       text NOT NULL REFERENCES organisation(id),
  account_id   text NOT NULL,          -- Graph API account_id, digits only, no act_ prefix
  name         text NOT NULL,
  currency     text NOT NULL,
  connected_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX meta_ad_account_org_id_idx ON meta_ad_account(org_id);
CREATE UNIQUE INDEX meta_ad_account_org_account_idx ON meta_ad_account(org_id, account_id);

-- Two tables, not one: an account bound to two brands must not store its name twice.
CREATE TABLE brand_meta_ad_account (
  org_id        text NOT NULL REFERENCES organisation(id),
  brand_id      text NOT NULL REFERENCES brand(id),
  ad_account_id text NOT NULL REFERENCES meta_ad_account(id) ON DELETE CASCADE,
  created_at    timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (org_id, brand_id, ad_account_id)
);
CREATE INDEX brand_meta_ad_account_brand_idx ON brand_meta_ad_account(brand_id);

ALTER TABLE meta_credential ENABLE ROW LEVEL SECURITY;
ALTER TABLE meta_ad_account ENABLE ROW LEVEL SECURITY;
ALTER TABLE brand_meta_ad_account ENABLE ROW LEVEL SECURITY;
