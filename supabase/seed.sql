-- supabase/seed.sql
-- Dev organisation only (ticket 02-2, user approval D2a). Runs after every `supabase db reset`.
INSERT INTO organisation (id, name, kind) VALUES ('org_dev', 'Dev', 'personal');
