# 01 — schema: `imported_ad` and `brand.advertising_history`, frozen and dormant

Route C (schema). Rulings: ADR 0067 §1.2 and §1.6. Goal picture: `spec.md`. Vocabulary: `CONTEXT.md`
「舊廣告與投放史」. **Dormant**: after this ticket nothing reads or writes either object except the
brand-delete path; the existing suite staying green is the proof (workflow.md, "the structure it needs,
dormant, then the flip").

## What

Two migration files, one per owning module (ADR 0049), timestamps after `20260908000001`:

1. `supabase/migrations/20260908000002_schedule_imported_ad.sql` — `CREATE TABLE imported_ad`, shaped
   after `20260908000001_schedule_period_node_result.sql` (header comment naming module / ticket / ADR;
   RLS enabled, zero policies — the same policy shape as `period_node_result` and `meta_entity_spend`; the
   `authenticated` policy that ADR 0052 gives every org table, copied from the most recent migration
   that adds one):

   ```sql
   CREATE TABLE imported_ad (
       id TEXT PRIMARY KEY,                        -- iad_*, via db.new_id("iad")
       org_id TEXT NOT NULL REFERENCES organisation(id),
       brand_id TEXT NOT NULL REFERENCES brand(id),
       ad_channel_id TEXT NOT NULL,
       external_id TEXT NOT NULL,                  -- the platform's own id for this ad
       external_name TEXT NOT NULL,                -- the platform's name at import, verbatim
       first_seen_date date,                       -- earliest / latest spend_date on record at import
       last_seen_date date,
       creative_body TEXT,                         -- cache of what the platform returned; NULL = not
       creative_title TEXT,                        --   fetched or not returned, never "empty"
       creative_image_url TEXT,
       creative_fetched_at timestamptz,
       audience_key TEXT, pain_key TEXT, angle_key TEXT, hook_key TEXT,
       proof_key TEXT, offer_key TEXT, format_key TEXT,
       coordinates_status TEXT NOT NULL DEFAULT 'pending'
           CHECK (coordinates_status IN ('tagged','pending','not_applicable')),
       owner_note TEXT,                            -- the owner's line, verbatim
       tagged_at timestamptz,
       tagged_by TEXT,
       created_at timestamptz NOT NULL DEFAULT now(),
       updated_at timestamptz NOT NULL DEFAULT now(),
       FOREIGN KEY (ad_channel_id, org_id) REFERENCES ad_channel(id, org_id),
       UNIQUE (org_id, brand_id, ad_channel_id, external_id)
   );
   CREATE INDEX imported_ad_org_id_idx ON imported_ad(org_id);
   CREATE INDEX idx_imported_ad_brand_id ON imported_ad(brand_id);
   ```

   The seven `*_key` columns hold `brand_coordinate.key` values exactly as `creative_candidate` does
   (`20260901000002_schedule_creative_coordinates.sql:44-47`): keys, not FKs, same reason.

2. `supabase/migrations/20260908000003_brand_intelligence_advertising_history.sql`:

   ```sql
   ALTER TABLE brand ADD COLUMN advertising_history TEXT
       CHECK (advertising_history IN ('has_history','none'));   -- NULL = not yet answered
   ```

3. `app/schedule/repository.py` — `imported_ad` joins `_CHILD_TABLES` (label 「舊廣告」) and the
   `brand_tables` frozenset of the existing `cleanup.register("創意座標與素材候選", …)` call. No other
   code change. No new function. No reader, no writer.

4. `docs/contracts/schedule.md` — one line under "Decisions in force": ADR 0067; `docs/contracts/brand_intelligence.md`
   — `brand.advertising_history` named beside the brand switches (`market_region`, `conversion_goal`)
   as a column this module owns and nobody writes yet.

Literal example of the row this table will hold once ticket 03 writes it (nothing writes it in this ticket):

```json
{
  "id": "iad_01M2…", "org_id": "org_bughunt", "brand_id": "brd_bughunt",
  "ad_channel_id": "adch_…", "external_id": "120212345678901234",
  "external_name": "BP｜夏季｜輪播A", "first_seen_date": "2026-05-03", "last_seen_date": "2026-08-31",
  "creative_body": "…", "creative_title": "…", "creative_image_url": "https://…", "creative_fetched_at": "2026-09-08T09:00:00Z",
  "audience_key": "new_parents", "pain_key": null, "angle_key": "convenience", "hook_key": null,
  "proof_key": null, "offer_key": "first_order_discount", "format_key": "carousel",
  "coordinates_status": "tagged", "owner_note": "媽媽群組轉貼最多，週末單量翻倍",
  "tagged_at": "2026-09-08T09:05:00Z", "tagged_by": "usr_…"
}
```

## How we know it's done

1. **The migrations apply on a clean local database.** `export PATH="/c/Users/User/AppData/Local/Programs/DockerDesktop/resources/bin:/c/Users/User/scoop/shims:$PATH" && supabase db reset` exits 0. (Test data only; `CLAUDE.md` 「資料狀態」 — no backup, no confirmation.)
2. **Isolation and ownership gates are green**, unset `BRAND_OS_LLM_PROVIDER` first:
   `uv run pytest app/tests/test_org_isolation_all_tables.py app/tests/test_brand_isolation_all_tables.py app/tests/test_architecture_boundaries.py app/tests/test_migration_ownership.py app/tests/test_real_db_schema_drift.py app/tests/test_rls_tenant_policy.py -q`.
   `imported_ad` carries `NOT NULL brand_id`, so it enters **no** exception list in
   `test_brand_isolation_all_tables.py` (`BRAND_AGNOSTIC_EXCEPTIONS` is not widened).
3. **A row cannot point at another organisation's channel** — the composite FK is proven, not assumed.
   One new test file `app/tests/test_imported_ad_schema.py`, shaped after the nearest existing
   composite-FK test (grep `REFERENCES campaign_period(id, org_id)` and the test that exercises it): insert
   an `ad_channel` row for org A and an `imported_ad` row for org B naming that channel → the INSERT raises
   a foreign-key violation. Proven red once by running the assertion against a single-column FK in a
   throwaway edit, then restored — say so in the report.
4. **Brand delete wipes it — proven in the ticket's own test file, not in `test_brand_delete.py`**
   (amended after review, see `## Blocked`). In `app/tests/test_imported_ad_schema.py`: create an org,
   a brand and its Meta channel (`app.schedule.repository.ensure_meta_channel`), insert one `imported_ad`
   row for that brand and one for a second brand of the same org; call `app.core.cleanup.delete_all(conn,
   brand_id)` (the path `brand_intelligence.repository.delete_brand()` runs — `test_cleanup_registry.py:62-67`
   shows the protocol); assert the returned counts carry `("舊廣告", 1)`, `count(*) FROM imported_ad WHERE
   brand_id = <deleted>` is 0, and the second brand's row is still there. `uv run pytest
   app/tests/test_brand_delete.py app/tests/test_cleanup_registry.py -q` stays green; **`test_brand_delete.py`
   is not edited.**
5. **Machine gate**: `uv run ruff check app` · `uv run pyright` · `cd frontend && npm run build` (no `typecheck` script; `build` is `tsc -b && vite build`; nothing frontend changes, the command still runs) · `cd frontend && npm run e2e` (own 8720 backend, `supabase start` first, shut it down after).
6. **Dormant is provable**: `grep -rn "imported_ad\|advertising_history" app/ --include=*.py` returns only `app/schedule/repository.py` (the child-table entries) and the new test file. Paste the output.
7. **Ratchets**: `TEST_LINES_CEILING` in `test_architecture_boundaries.py` rises by exactly the new test file's lines plus the reason comment, in the file's existing chronological style; `KNOWN_MODULE_SIZES["app/schedule"]` (4740) rises by the lines added to `repository.py`, with its reason. Both numbers are measured (`wc -l`), never typed.

## Shared files touched

Every name this ticket introduces was searched across the whole repo (2026-09-08, unscoped by directory or
file type, excluding `node_modules`/`.git`/`.venv`/`.scratch`/`.worktrees`/`dist`/`graphify-out`/`__pycache__`;
hits inside ADR 0067, this folder and `CONTEXT.md` excluded). Nothing existing changes meaning; these are new names:

```
grep -rn imported_ad .            → (no hits)
grep -rn advertising_history .    → (no hits)
grep -rn iad_ .                   → (not searched — id prefix; ticket must confirm "iad" is unused in app/ before use: grep -rn '"iad"' app/)
```

Files this ticket edits, for the diff check:

```
supabase/migrations/20260908000002_schedule_imported_ad.sql                 (new)
supabase/migrations/20260908000003_brand_intelligence_advertising_history.sql (new)
app/schedule/repository.py:590-625                                           (_CHILD_TABLES, cleanup.register brand_tables)
app/tests/test_imported_ad_schema.py                                         (new)
app/tests/test_brand_delete.py:15                                            (only if ALL_TABLES needs the table, per done-check 4)
app/tests/test_architecture_boundaries.py:1316,1737                          (TEST_LINES_CEILING, KNOWN_MODULE_SIZES["app/schedule"])
app/tests/test_real_db_schema_drift.py                                       (only if its known-drift list must name the new objects; do not widen it to hide a diff)
docs/contracts/schedule.md, docs/contracts/brand_intelligence.md            (one line each)
```

## Contradiction check

- **Done-check 6 (dormant: only `repository.py` and the test mention the table) vs done-check 4 (brand
  delete wipes it).** They agree only because the delete path lives in `repository.py`; an implementer who
  puts the wipe anywhere else (a trigger, `app/core/cleanup.py`) turns check 6 red. Input that shows it:
  the grep in check 6.
- **Done-check 2 (brand isolation green with no exception added) vs the table's composite FK to
  `ad_channel`, which *is* on the exception list.** The isolation test asks whether `imported_ad` has
  `brand_id`, not whether its parents do; the row is brand-scoped while its channel is org-scoped, which
  is the same shape `channel_entity_map` already has. Input that would show a real conflict: a test that
  demanded every FK target also carry `brand_id` — none exists (grep `BRAND_AGNOSTIC_EXCEPTIONS` usage).
- **Cheapest wrong implementation that leaves every check green:** a single-column
  `REFERENCES ad_channel(id)` — checks 1, 2, 4–7 all pass, and org A's brand can silently reference org
  B's channel. Check 3 exists for exactly that; its red-once proof is the only thing that makes it count.

## Blocked

2026-09-08, review round 1 (Opus): `blocked-upstream`. Done-check 4 (edit `test_brand_delete.py::ALL_TABLES`)
and done-check 6 (the grep returns only `repository.py` and the new test file) could not both be green, and
the precedent check 4 cited (`period_node_result` in that file) never existed; with `test_brand_delete.py`
untouched, nothing in the suite proved brand delete wipes `imported_ad`. The tenant-isolation attacks all
held (cross-org channel FK, RLS read/insert/update/delete as `authenticated` with the other org's
`app.org_id`). Ruling (main chat): done-check 4 rewritten above — the wipe is proven through
`cleanup.delete_all()` inside `test_imported_ad_schema.py`; `test_brand_delete.py` stays untouched. Round 2
implements only that test. The edits to tickets 02–05 found in the same diff were main chat's, not the
implementer's.
