-- supabase/seed.sql
-- Dev organisation only (ticket 02-2, user approval D2a). Runs after every `supabase db reset`.
INSERT INTO organisation (id, name, kind) VALUES ('org_dev', 'Dev', 'personal');

-- Dev user + owner membership (ticket 03-1): backs the IDENTITY_DEV_TOKEN bypass.
INSERT INTO app_user (id, email) VALUES ('00000000-0000-0000-0000-000000000001', 'dev@local');
INSERT INTO membership (org_id, user_id, role)
  VALUES ('org_dev', '00000000-0000-0000-0000-000000000001', 'owner');
