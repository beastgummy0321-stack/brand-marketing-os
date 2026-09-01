---
id: 0038
decision: Procrastinate's tables live in their own Postgres schema and must never gain an org_id column.
applies-to: [supabase/migrations/, app/background/, app/tests/test_org_isolation_all_tables.py]
supersedes: none
status: in-force
---

# The queue lives in its own schema, because it is not in the data model

Procrastinate's four tables — `procrastinate_workers`, `procrastinate_jobs`,
`procrastinate_periodic_defers`, `procrastinate_events` — carry no `org_id`, which collides with
the constitution's rule 2: every table has an `org_id`.

**They go in their own Postgres schema. They are not exempted from anything, and they must not
gain an `org_id` column.**

## The gate, stated accurately

`app/tests/test_org_isolation_all_tables.py` (Gate A, ticket 02-5, amended 03-1) requires every
base table **in the module's schema** to have a NOT NULL `org_id` with a foreign key to
`organisation(id)`. Its exempt set is exactly `{organisation, app_user}`, and a **second test**,
`test_exempt_set_is_exactly_the_two_documented_tables`, asserts the set is exactly those two —
a deliberate lock against quiet widening, written by ticket 03-1.

So there are only three ways forward, and two of them are bad:

- **Add `org_id` to the four tables.** Procrastinate owns that schema — 599 lines, four tables,
  three types, eighteen SQL functions. The column can be added, but `defer()` will not populate
  it and the fetch and locking SQL will not filter on it. A column no code writes and no query
  filters on is not isolation; it is decoration that reads as a safety property, and the next
  person to see it will assume the queue is tenant-isolated. Keeping it honest means forking the
  library's SQL and re-forking at every upgrade.
- **Add them to `EXEMPT_TABLES` and edit the lock.** This is sanctioned in principle — narrowing
  what a gate applies to is allowed with an explicit written decision, which this ADR could be.
  It is still wrong: the lock exists precisely to make this moment expensive, and spending it on
  a queue destroys the guard for the case it was built for, which is a *product* table sneaking
  through without a tenant column.
- **Put them somewhere Gate A does not scan.** Gate A scans `current_schema()`. A queue in its
  own schema is not in the product's data model, so the gate is not being narrowed, avoided or
  argued with — the tables were never in its subject.

The third is the honest one, because it matches what is actually true: **rule 2 describes the
three-layer data model (organisation → user → brand), and a job queue is not part of it.**

## Where the isolation actually lives

Rule 5 already answered this: *background work runs on procrastinate; a handler is re-runnable
and touches only its own organisation.* The tenant travels **in the job's arguments** —
`pull_meta_spend(org_id=..., brand_id=...)` — and the handler is what must respect it. Rule 2
governs the data model; rule 5 governs background work; the queue serves rule 5.

## Implementation

Procrastinate's schema SQL uses unqualified table names, so applying it under `SET search_path TO
procrastinate` creates the tables there, and connections that use the queue carry the same
`search_path`. No fork, no patched SQL.

**This is a design direction, not a tested result.** Three things must be verified end to end
before the ticket is done: the schema applies into its own namespace, `defer()` reaches it, and
a worker fetches from it. If any of the three does not hold, come back to this ADR rather than
falling through to the exempt-list route on your own.

The brand-isolation gate (`test_brand_isolation_all_tables.py`) scans the same way, so its
`BRAND_AGNOSTIC_EXCEPTIONS` needs no entry either. An entry added there before this decision
should be removed: not being scanned is better than being excused.

RLS is unaffected in substance — the queue is reachable only by the backend's `postgres`
connection and is never exposed through PostgREST, which is what RLS on `public` exists to
close. If the drift gate's RLS check reaches the new schema, enable RLS on the four tables with
no policies, exactly as every other table does.

## The gate this ADR owes

A limit in prose is not a limit. Rule 5's "touches only its own organisation" has never had a
machine check, and this ADR is the one leaning on it, so it adds one:

**Every registered procrastinate task takes a required `org_id` parameter.** Inspect the task
registry and assert each task's signature. About ten lines; it passes vacuously until ticket 05
registers the first real handler, and it is armed before that handler is written rather than
after. Prove it red once — register a task without `org_id`, see the failure, remove it.

No static check can prove a handler *uses* the argument correctly. This removes the failure mode
where a handler never had the organisation available to respect at all, which is the one that
produces a silent cross-tenant read.

## Consequences

- **Rule 2 is not amended and gains no exception.** Its subject is the product's data model.
  Third-party infrastructure whose schema we do not own lives outside that model, and outside
  its schema.
- **Both isolation gates keep their locks intact.** Gate A's exempt set stays at two;
  `BRAND_AGNOSTIC_EXCEPTIONS` gains nothing.
- **Ticket 01 gains the schema separation and the task-signature gate**, and neither is optional.
- **A correction for the record:** an earlier answer in this session said rule 2 had no machine
  gate. It does — `test_org_isolation_all_tables.py` — and it has two, counting the lock.
