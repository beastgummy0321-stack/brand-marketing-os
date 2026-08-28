-- supabase/migrations/20260828000002_identity_baseline.sql
-- Module: identity (ticket 03-1, ADR 0027 decisions 2/3)
-- Rule: migration files only CREATE tables prefixed/owned by this module.
-- app_user has no org_id by design (a user spans organisations) — Gate A
-- (test_org_isolation_all_tables.py) carries the explicit exception set
-- {"organisation", "app_user"}, documented there.

CREATE TABLE app_user (
  id uuid PRIMARY KEY,
  email text NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE membership (
  org_id text NOT NULL REFERENCES organisation(id),
  user_id uuid NOT NULL REFERENCES app_user(id),
  role text NOT NULL CHECK (role IN ('owner','member')),
  created_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (org_id, user_id)
);
CREATE INDEX membership_user_id_idx ON membership(user_id);

CREATE TABLE org_invite (
  id text PRIMARY KEY,
  org_id text NOT NULL REFERENCES organisation(id),
  email text NOT NULL,
  role text NOT NULL CHECK (role IN ('owner','member')),
  token text NOT NULL UNIQUE,
  expires_at timestamptz NOT NULL,
  accepted_at timestamptz,
  created_by uuid NOT NULL REFERENCES app_user(id),
  created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX org_invite_org_id_idx ON org_invite(org_id);

ALTER TABLE app_user ENABLE ROW LEVEL SECURITY;
ALTER TABLE membership ENABLE ROW LEVEL SECURITY;
ALTER TABLE org_invite ENABLE ROW LEVEL SECURITY;
