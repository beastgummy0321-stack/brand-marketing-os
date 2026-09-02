-- supabase/seed.sql
-- Dev organisation only (ticket 02-2, user approval D2a). Runs after every `supabase db reset`.
INSERT INTO organisation (id, name, kind) VALUES ('org_dev', 'Dev', 'personal');

-- Dev user + owner membership (ticket 03-1): backs the IDENTITY_DEV_TOKEN bypass.
INSERT INTO app_user (id, email) VALUES ('00000000-0000-0000-0000-000000000001', 'dev@local');
INSERT INTO membership (org_id, user_id, role)
  VALUES ('org_dev', '00000000-0000-0000-0000-000000000001', 'owner');

-- ---------------------------------------------------------------------------
-- Bug-hunting account (user request, 2026-09-02). LOCAL ONLY, PRE-LAUNCH ONLY.
--
-- Why it is here and not created by hand: the user needs one account that survives
-- `supabase db reset`, so that resetting the database while chasing a bug does not also
-- destroy the thing being used to chase it. `supabase/seed.sql` is run by the local CLI's
-- `db reset` and by nothing else — `supabase db push` does not run seed files — so this
-- account cannot reach a hosted project by this path.
--
-- It is still a known email with a six-character password committed to a public-capable repo.
-- BOARD.md carries the row that deletes this block before anything is deployed.
--
--   email    123@example.com
--   password 123456          (supabase/config.toml minimum_password_length = 6)
--
-- The app rows below are the ones a first login would otherwise create
-- (`app/identity/__init__.py:77-81`). They are pre-seeded with fixed ids so the organisation
-- and the brand survive a reset too — `_first_login` only creates an organisation when its
-- `create_user` actually inserted, so a pre-existing `app_user` row makes it a no-op.
-- ---------------------------------------------------------------------------
-- `auth.users` and `auth.identities` live in the `auth` schema, which is NOT part of the
-- per-module schema `app/tests/conftest.py` builds and drops — so these two inserts run again
-- for every test module that seeds. They carry ON CONFLICT DO NOTHING for that reason; the
-- public-schema rows below do not need it, because that schema is fresh each time.
-- The four token columns are written as '' on purpose: they have no DEFAULT, and GoTrue scans
-- them into non-nullable Go strings, so leaving them NULL makes every login fail with
-- "Database error querying schema" — a 500 that says nothing about the real cause. Measured
-- 2026-09-02: the first version of this seed omitted them and login returned exactly that.
INSERT INTO auth.users (
    instance_id, id, aud, role, email, encrypted_password, email_confirmed_at,
    confirmation_token, recovery_token, email_change_token_new, email_change,
    raw_app_meta_data, raw_user_meta_data, created_at, updated_at
) VALUES (
    '00000000-0000-0000-0000-000000000000',
    'b0a57eef-0000-4000-8000-000000000123',
    'authenticated', 'authenticated', '123@example.com',
    extensions.crypt('123456', extensions.gen_salt('bf')),
    now(),
    '', '', '', '',
    '{"provider": "email", "providers": ["email"]}'::jsonb,
    '{}'::jsonb, now(), now()
) ON CONFLICT DO NOTHING;

INSERT INTO auth.identities (
    provider_id, user_id, identity_data, provider, last_sign_in_at, created_at, updated_at
) VALUES (
    'b0a57eef-0000-4000-8000-000000000123',
    'b0a57eef-0000-4000-8000-000000000123',
    '{"sub": "b0a57eef-0000-4000-8000-000000000123", "email": "123@example.com", "email_verified": true, "phone_verified": false}'::jsonb,
    'email', now(), now(), now()
) ON CONFLICT DO NOTHING;

INSERT INTO app_user (id, email)
  VALUES ('b0a57eef-0000-4000-8000-000000000123', '123@example.com');
INSERT INTO organisation (id, name, kind)
  VALUES ('org_bughunt', 'Beast 排查用', 'personal');
INSERT INTO membership (org_id, user_id, role)
  VALUES ('org_bughunt', 'b0a57eef-0000-4000-8000-000000000123', 'owner');
INSERT INTO brand (id, org_id, name, status)
  VALUES ('brd_bughunt', 'org_bughunt', 'Beast Prime 野獸至尊', 'active');
