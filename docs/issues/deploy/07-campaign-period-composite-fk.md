# 07 — every foreign key into `campaign_period` becomes `(id, org_id)`

Route C (schema/migration + tenant isolation). Graduated from
`issue-campaign-period-composite-fk.md` (2026-09-05).
**Needs the user's approval before dispatch** (constitution: migrations, tenant isolation).

## What

`ad_channel` already makes the database itself refuse a cross-organisation row: it carries
`ALTER TABLE ad_channel ADD CONSTRAINT ad_channel_id_org_id_key UNIQUE (id, org_id)`
(`supabase/migrations/20260903000006_schedule_channel_entity_map.sql:29`), and three tables point
at it with `FOREIGN KEY (channel_id, org_id) REFERENCES ad_channel(id, org_id)` — same file `:62`
and `:76-78`, plus `20260903000012_schedule_channel_credential.sql:45`. A row whose `org_id` does
not match the parent's cannot be inserted at all.

`campaign_period` has no such defence. Its `id` is a bare `TEXT PRIMARY KEY`
(`20260903000001_schedule_campaign_period.sql:10`) and every foreign key into it is single-column,
so the only thing stopping one organisation's row from pointing at another organisation's period
is application code. Copy the `ad_channel` shape.

**The issue file's count was wrong and this ticket corrects it: there are 8 foreign keys in
total, of which exactly 1 is a self-reference — not "8 plus another 6 self-references".** The
measured list (`grep -rn "REFERENCES campaign_period" supabase/migrations/` plus an unscoped DDL
search):

| # | table.column | declared at | nullable? |
|---|---|---|---|
| 1 | `campaign_period.source_period_id` (self) | `20260903000001_schedule_campaign_period.sql:27` | yes |
| 2 | `campaign_period_budget_version.campaign_period_id` | same file `:43` | **NOT NULL** |
| 3 | `period_node_membership.campaign_period_id` | same file `:66` | **NOT NULL** |
| 4 | `interrupt.campaign_period_id` | `20260903000002_core_interrupt_period.sql:9` | yes |
| 5 | `llm_task.campaign_period_id` | same file `:16` | yes |
| 6 | `feedback.campaign_period_id` | `20260903000005_schedule_feedback_period_fk.sql:8` | yes |
| 7 | `channel_revenue.campaign_period_id` | `20260904000001_orders_channel_revenue_dedupe.sql:19` | yes |
| 8 | `decision.campaign_period_id` | `20260904000005_core_decision_columns.sql:17` | yes |

All eight referencing tables already carry `org_id text NOT NULL REFERENCES organisation(id)`, so
no column has to be added: `decision` (`20260826000001_core_baseline.sql:161`), `interrupt`
(same `:108`), `llm_task` (same `:47`), `channel_revenue`
(`20260829000005_orders_channel_revenue.sql:16`), `feedback`
(`20260901000002_schedule_creative_coordinates.sql:87`), and `period_node_membership` /
`campaign_period_budget_version` / `campaign_period` itself
(`20260903000001_schedule_campaign_period.sql:11,41,64`).

None of the eight declares `ON DELETE CASCADE` or `ON DELETE SET NULL`; all are the default
`NO ACTION`. Rebuilt constraints keep that default — do not add a delete behaviour this ticket
did not measure.

Work, in one new migration file
`supabase/migrations/<timestamp>_schedule_campaign_period_composite_fk.sql` (prefix `schedule_`:
`campaign_period` is the schedule module's table — `app/tests/test_migration_ownership.py`):

1. `ALTER TABLE campaign_period ADD CONSTRAINT campaign_period_id_org_id_key UNIQUE (id, org_id);`
   This must come first; without it none of the eight composite keys can be created.
2. For each of the eight: drop the existing single-column constraint **by its real name, read out
   of the database rather than guessed** —
   `SELECT conname, conrelid::regclass FROM pg_constraint WHERE confrelid = 'campaign_period'::regclass;`
   — then add `FOREIGN KEY (campaign_period_id, org_id) REFERENCES campaign_period(id, org_id)`
   (for row #1: `(source_period_id, org_id)`).
3. Applied migration files are never edited. Everything lands in the new file.

Literal example — the insert that must start failing. Org A owns period `cp_A`; org B is a
different tenant:

```json
{"table": "decision", "row": {"id": "dec_1", "org_id": "org_B", "campaign_period_id": "cp_A"},
 "before this ticket": "inserts successfully — one org's decision hangs off another org's period",
 "after this ticket":  "rejected by the database: foreign key (campaign_period_id, org_id) has no match in campaign_period(id, org_id)"}
```

The same row with `"org_id": "org_A"` must still insert. That is the pair every done-check is
measured against.

Out of scope: adding `org_id` anywhere, changing nullability, adding delete behaviour, touching
`ad_channel`, touching any application code. If application code has to change for the migration
to apply, that is `blocked-upstream`, not a fix to make quietly.

## How we know it's done

1. `uv run ruff check app` — clean. `uv run pyright` — 0 errors.
2. `supabase db reset` completes with no error, and the new migration is listed as applied.
3. Count command, output pasted into the report:
   `psql "$DATABASE_URL" -c "SELECT count(*) FROM pg_constraint WHERE confrelid='campaign_period'::regclass AND array_length(conkey,1)=2;"`
   returns **8**, and the same query with `array_length(conkey,1)=1` returns **0**.
4. **The isolation itself, attacked, not merely declared.** New test in
   `app/tests/test_org_isolation_all_tables.py`: create two organisations, each with a
   `campaign_period`; attempt to insert a `decision` row whose `org_id` is org A's and whose
   `campaign_period_id` is org B's period, and assert the database raises a foreign-key
   violation. Repeat once for a NOT NULL table (`period_node_membership`) — the two nullability
   classes fail differently. Proven red once: drop the composite constraint on `decision`, watch
   the bad insert succeed (test red), restore.
5. `uv run pytest app/tests/test_org_isolation_all_tables.py app/tests/test_brand_isolation_all_tables.py app/tests/test_architecture_boundaries.py -q` — green.
6. `uv run pytest app/tests/test_schedule_period.py app/tests/test_schedule.py app/tests/test_core_interrupts.py app/tests/test_orders_channel.py -q` — green (behaviour over the eight tables).
7. `cd frontend && npm run e2e` — green.

Note for the implementer: **no test asserts FK shape today.**
`app/tests/test_org_isolation_all_tables.py:57-77` only asserts each table has `org_id NOT NULL`
with an FK to `organisation(id)`; nothing enumerates constraints. Checks 3 and 4 are new ground,
not a regression net — which is why check 4 must be proven red by hand.

## Shared files touched

`grep -rn "REFERENCES campaign_period" supabase/migrations/` plus an unscoped search for
`campaign_period` in DDL context (quoted identifiers, inline `REFERENCES`,
`ALTER TABLE ... ADD CONSTRAINT`, line-wrapped forms):

```
supabase/migrations/20260903000001_schedule_campaign_period.sql:10,11,27,41,43,64,66
supabase/migrations/20260903000002_core_interrupt_period.sql:8,9,16
supabase/migrations/20260903000005_schedule_feedback_period_fk.sql:8
supabase/migrations/20260904000001_orders_channel_revenue_dedupe.sql:19
supabase/migrations/20260904000005_core_decision_columns.sql:17
supabase/migrations/20260903000006_schedule_channel_entity_map.sql:12-20,29,62,76-78   (pattern to copy)
supabase/migrations/20260903000012_schedule_channel_credential.sql:45                  (pattern to copy)
supabase/migrations/20260826000001_core_baseline.sql:47,108,161                        (org_id: llm_task/interrupt/decision)
supabase/migrations/20260829000005_orders_channel_revenue.sql:16
supabase/migrations/20260901000002_schedule_creative_coordinates.sql:87
app/tests/test_org_isolation_all_tables.py:57-77
docs/adr/0050-the-ad-loop-data-model-is-one-table-list.md   (the table list of record)
docs/adr/0053-the-campaign-period-is-born-on-the-form-and-settles-by-hand.md
```

Expected diff: one new migration file plus `app/tests/test_org_isolation_all_tables.py`. Any
other path in `git diff --name-only` is `blocked-upstream`.

## Contradiction check

Done-check 3 (8 composite constraints, 0 single-column ones) and done-check 6 (behaviour tests
stay green) can contradict each other. The cheapest way to make 3 pass is to drop the
single-column constraints and add composite ones while some existing row's `org_id` disagrees
with its parent's; the migration then fails on **data** rather than on shape, and the tempting
repair is to widen the constraint or null the offending column. The input that shows it: a
`period_node_membership` row (NOT NULL, so it cannot be nulled away) whose `org_id` differs from
its period's. Required behaviour: the migration fails loudly and the implementer reports it.
Local data is disposable test data (`CLAUDE.md`), so a clean `supabase db reset` is the right
response — silently reconciling rows is not, and neither is loosening the constraint.
