-- core: R3b — one door into the vault, and it only opens on your own org's secrets
-- (docs/issues/r3b-vault-org-door/ticket.md, ADR 0052).
--
-- Measured on the live local DB, 2026-09-02: `authenticated` has no privilege on schema
-- `vault` (confirmed by flipping the switch as a throwaway probe and reverting it — 22 of
-- 708 tests failed on `permission denied for schema vault`). Granting `authenticated` direct
-- access to `vault.decrypted_secrets` was rejected (every org could read every other org's
-- API key); a second unscoped connection was rejected too (leaves the credential path
-- permanently outside the lock). What ships instead: three `SECURITY DEFINER` functions,
-- owned by `postgres` (which can already call `vault.create_secret`/`vault.update_secret`
-- today, so a function owned by `postgres` can too), `EXECUTE` revoked from `PUBLIC` and
-- granted only to `authenticated`. Each checks that the secret id belongs to the caller's
-- own org before touching it — the id lives in exactly two places, both org-scoped:
-- `app_setting(org_id, key = 'anthropic_api_key_secret_id', value)` and
-- `meta_credential(org_id, secret_id)`.
--
-- Unset claim = no check, same behaviour as the direct `vault.*` call this replaces: every
-- caller today runs as `postgres` with no `app.org_id` claim (R3c has not flipped the switch
-- yet), and if the check applied unconditionally every existing caller would fail. Written
-- explicitly per function, not left to fall out of the SQL by accident.
--
-- `SECURITY DEFINER` needs a pinned `search_path` (an unpinned one is a privilege
-- escalation) but the schema is not known at authoring time — `app/tests/conftest.py`
-- replays every migration into its own `t_<module>_<pid>` schema — so the three
-- `CREATE FUNCTION` statements are built with `EXECUTE format(...)` inside a `DO` block,
-- pinning `SET search_path = <that schema>, vault` from `current_schema()`, same pattern
-- 20260902000002 already uses for its per-schema loop.
--
-- Round 1 pinned `<schema>, vault` and stopped there — still a privilege escalation.
-- Postgres searches `pg_temp` first unless `pg_temp` is named explicitly in the path, so an
-- `authenticated` caller could `CREATE TEMP TABLE app_setting (...)`, seed a row claiming
-- ownership of another org's secret, and the ownership check below would read that fake row
-- instead of the real table. Reproduced live against `public`, twice (ticket's ## Blocked
-- section). `pg_temp` must be named, and named LAST: naming it at all stops the implicit
-- first-position search; naming it last (after the real schema and `vault`) means a session's
-- temp object never shadows a real one. Do not delete this as noise.
--
-- Not done here: flipping the switch itself (`require_actor()`, `app/core/db.py`, the
-- connection pool are untouched — R3c's job), and any change to who is allowed to call
-- `vault.create_secret`/`vault.update_secret` directly (only `postgres` ever has; that is
-- unchanged, these functions run as `postgres` too).

DO $do$
DECLARE
    sch text := current_schema();
BEGIN
    -- Read: raises `insufficient_privilege` if a claim is present and the secret isn't the
    -- caller's; returns NULL if the secret id doesn't exist (matches the direct-query
    -- behaviour it replaces, which also returned NULL on no row).
    EXECUTE format($fn$
        CREATE OR REPLACE FUNCTION %1$I.core_vault_read_secret(p_secret_id uuid)
        RETURNS text
        LANGUAGE plpgsql
        SECURITY DEFINER
        -- pg_temp named last: stops the implicit first-position temp-schema search that let
        -- a caller shadow app_setting with a temp table (see file header, round 1 -> round 2).
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
                    OR EXISTS (SELECT 1 FROM meta_credential
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

    -- Save: NULL id creates and returns the new id; a given id updates that secret (checked
    -- the same way as read) and returns it back unchanged. Merges the app's two former call
    -- shapes (`_vault_create_secret` / `_vault_update_secret`) into one door.
    EXECUTE format($fn$
        CREATE OR REPLACE FUNCTION %1$I.core_vault_save_secret(p_secret_id uuid, p_value text)
        RETURNS uuid
        LANGUAGE plpgsql
        SECURITY DEFINER
        -- pg_temp named last: stops the implicit first-position temp-schema search that let
        -- a caller shadow app_setting with a temp table (see file header, round 1 -> round 2).
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
                    OR EXISTS (SELECT 1 FROM meta_credential
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

    -- Delete: same ownership check, then removes the secret outright.
    EXECUTE format($fn$
        CREATE OR REPLACE FUNCTION %1$I.core_vault_delete_secret(p_secret_id uuid)
        RETURNS void
        LANGUAGE plpgsql
        SECURITY DEFINER
        -- pg_temp named last: stops the implicit first-position temp-schema search that let
        -- a caller shadow app_setting with a temp table (see file header, round 1 -> round 2).
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
                    OR EXISTS (SELECT 1 FROM meta_credential
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
