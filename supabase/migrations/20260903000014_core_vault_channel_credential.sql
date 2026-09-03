-- supabase/migrations/20260903000014_core_vault_channel_credential.sql
-- Module: core (these three functions already belong to core, created in
-- 20260902000003_core_vault_org_scoped_access.sql -- CREATE OR REPLACE on an existing
-- function is not a new CREATE TABLE and is not subject to the ownership registry).
-- Ticket: T4 §5. Decision of record: ADR 0056 §4, user-approved 2026-09-03 as a permission
-- path change. Sorts after 20260903000012_schedule_channel_credential.sql, whose table this
-- file's function bodies reference by name.
--
-- 20260903000012 drops the module's earlier one-row-per-org credential table. Without this
-- file, the three SECURITY DEFINER Vault door functions (core_vault_read_secret /
-- core_vault_save_secret / core_vault_delete_secret) still name that dropped table in their
-- ownership check's second EXISTS branch and would raise UndefinedTable -- not the graceful
-- insufficient_privilege they are designed to raise -- on every authenticated call, including
-- /api/schedule/brands/{id}/tree/bind (routes.py -> binding.bind_tree() -> meta_repo.get_token()).
--
-- The applied file 20260902000003 is NOT edited (ADR 0049 / CLAUDE.md: an applied migration
-- is never touched; a correction is a new file). This file CREATE OR REPLACEs all three
-- functions, byte-for-byte identical to that file except the second EXISTS now reads
-- channel_credential instead of the table it replaced, joined the same way 20260903000012's
-- read path is: channel_credential.org_id = v_org AND secret_id = p_secret_id. The channel
-- does not need to be resolved here -- a secret id is unique across channels.
--
-- Three load-bearing details, copied from 20260902000003's own header rather than
-- re-derived:
--   1. The functions are built with EXECUTE format(...) inside a DO block, pinning %1$I from
--      current_schema(), because app/tests/conftest.py replays every migration into a
--      per-module t_<module>_<pid> schema and the schema name is not known at authoring time.
--   2. SET search_path = %1$I, vault, pg_temp -- pg_temp named LAST. Without it, an
--      authenticated caller can CREATE TEMP TABLE app_setting, seed a row claiming another
--      org's secret, and the ownership check reads the fake row. Reproduced twice against
--      public. Do not drop it as noise.
--   3. An unset app.org_id claim skips the check, per function, deliberately -- every path
--      that still runs as postgres with no claim behaves exactly as before.
--
-- One correction to 20260902000003's own header, verified by the T4 ticket's second dispatch:
-- that file's header says "R3c has not flipped the switch yet". It has since --
-- app/shared/web.py:262 and app/core/db.py set the role and claim on every logged-in request
-- today. The ownership branch this file edits is live on ordinary traffic, not dormant.

DO $do$
DECLARE
    sch text := current_schema();
BEGIN
    EXECUTE format($fn$
        CREATE OR REPLACE FUNCTION %1$I.core_vault_read_secret(p_secret_id uuid)
        RETURNS text
        LANGUAGE plpgsql
        SECURITY DEFINER
        -- pg_temp named last: stops the implicit first-position temp-schema search that let
        -- a caller shadow app_setting with a temp table (see 20260902000003's header).
        SET search_path = %1$I, vault, pg_temp
        AS $body$
        DECLARE
            v_org text := current_setting('app.org_id', true);
            v_secret text;
        BEGIN
            IF v_org IS NOT NULL AND v_org <> '' THEN
                IF NOT (
                    EXISTS (SELECT 1 FROM app_setting
                             WHERE org_id = v_org
                               AND key = 'anthropic_api_key_secret_id'
                               AND value = p_secret_id::text)
                    OR EXISTS (SELECT 1 FROM channel_credential
                                WHERE org_id = v_org
                                  AND secret_id = p_secret_id)
                ) THEN
                    RAISE insufficient_privilege
                        USING MESSAGE = 'secret does not belong to the caller''s organisation';
                END IF;
            END IF;

            SELECT decrypted_secret INTO v_secret FROM vault.decrypted_secrets WHERE id = p_secret_id;
            RETURN v_secret;
        END;
        $body$;
    $fn$, sch);
    EXECUTE format('REVOKE EXECUTE ON FUNCTION %I.core_vault_read_secret(uuid) FROM PUBLIC', sch);
    EXECUTE format('GRANT EXECUTE ON FUNCTION %I.core_vault_read_secret(uuid) TO authenticated', sch);

    EXECUTE format($fn$
        CREATE OR REPLACE FUNCTION %1$I.core_vault_save_secret(p_secret_id uuid, p_value text)
        RETURNS uuid
        LANGUAGE plpgsql
        SECURITY DEFINER
        -- pg_temp named last: stops the implicit first-position temp-schema search that let
        -- a caller shadow app_setting with a temp table (see 20260902000003's header).
        SET search_path = %1$I, vault, pg_temp
        AS $body$
        DECLARE
            v_org text := current_setting('app.org_id', true);
            v_new_id uuid;
        BEGIN
            IF p_secret_id IS NULL THEN
                SELECT vault.create_secret(p_value) INTO v_new_id;
                RETURN v_new_id;
            END IF;

            IF v_org IS NOT NULL AND v_org <> '' THEN
                IF NOT (
                    EXISTS (SELECT 1 FROM app_setting
                             WHERE org_id = v_org
                               AND key = 'anthropic_api_key_secret_id'
                               AND value = p_secret_id::text)
                    OR EXISTS (SELECT 1 FROM channel_credential
                                WHERE org_id = v_org
                                  AND secret_id = p_secret_id)
                ) THEN
                    RAISE insufficient_privilege
                        USING MESSAGE = 'secret does not belong to the caller''s organisation';
                END IF;
            END IF;

            PERFORM vault.update_secret(p_secret_id, p_value);
            RETURN p_secret_id;
        END;
        $body$;
    $fn$, sch);
    EXECUTE format('REVOKE EXECUTE ON FUNCTION %I.core_vault_save_secret(uuid, text) FROM PUBLIC', sch);
    EXECUTE format('GRANT EXECUTE ON FUNCTION %I.core_vault_save_secret(uuid, text) TO authenticated', sch);

    EXECUTE format($fn$
        CREATE OR REPLACE FUNCTION %1$I.core_vault_delete_secret(p_secret_id uuid)
        RETURNS void
        LANGUAGE plpgsql
        SECURITY DEFINER
        -- pg_temp named last: stops the implicit first-position temp-schema search that let
        -- a caller shadow app_setting with a temp table (see 20260902000003's header).
        SET search_path = %1$I, vault, pg_temp
        AS $body$
        DECLARE
            v_org text := current_setting('app.org_id', true);
        BEGIN
            IF v_org IS NOT NULL AND v_org <> '' THEN
                IF NOT (
                    EXISTS (SELECT 1 FROM app_setting
                             WHERE org_id = v_org
                               AND key = 'anthropic_api_key_secret_id'
                               AND value = p_secret_id::text)
                    OR EXISTS (SELECT 1 FROM channel_credential
                                WHERE org_id = v_org
                                  AND secret_id = p_secret_id)
                ) THEN
                    RAISE insufficient_privilege
                        USING MESSAGE = 'secret does not belong to the caller''s organisation';
                END IF;
            END IF;

            DELETE FROM vault.secrets WHERE id = p_secret_id;
        END;
        $body$;
    $fn$, sch);
    EXECUTE format('REVOKE EXECUTE ON FUNCTION %I.core_vault_delete_secret(uuid) FROM PUBLIC', sch);
    EXECUTE format('GRANT EXECUTE ON FUNCTION %I.core_vault_delete_secret(uuid) TO authenticated', sch);
END
$do$;
