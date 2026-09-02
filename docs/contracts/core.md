# Contract — core (shared infrastructure)

Five things and nothing else (container contract §7). Reasoning lives in the ADRs named below;
it is not repeated here, because a second copy goes stale.

Written 2026-09-02, ahead of the R3 slice, because a route C ticket touching a module registers
that module first. It records what `app/core/` **is**, not what it should be.

## Entry path

`app/core/` has **no single entry file, by design and by history**: it is infrastructure, and
callers import the one file they need — `from app.core import db`, `from app.core.db import
Conn`, `from app.core.audit import write_audit`. Each file below is its own entry point.
`app/core/__init__.py` holds a comment and nothing else. A ticket may not "fix" this by
inventing a facade; that would be a module-boundary change and needs its own decision.

| file | what it is the door to |
|---|---|
| `db.py` | the Postgres connection pool, the per-request/per-job bound connection, id generation, JSON encoding |
| `audit.py` | append-only `audit_log` writes |
| `approval.py` | the money brake (ADR 0040) |
| `interrupts.py` | the single outbox for anything a human must see |
| `settings.py` | org-level settings and LLM spend caps |
| `cleanup.py` | the registry brands use to delete their own rows |
| `retention.py` | expiry of large `llm_task` payloads |
| `rule_cards.py`, `vocab.py`, `net.py` | rule cards, UI vocabulary, outbound HTTP helper |

## Exported shapes

Only the ones another module is allowed to depend on. `db.py` is the one this contract exists
for:

```
db.dsn() -> str                          # the connection string; DATABASE_URL or local default
db.pool() -> ConnectionPool              # module-level singleton, lazily opened
db.connection() -> ContextManager[Conn]  # borrow one, bind it to this request/job, return it
db.current() -> Conn                     # the connection bound to this request/job
db.ConnProxy                             # a Conn-shaped handle that resolves current() per call
db.new_id(prefix) -> str                 # sortable, type-tagged id
db.jsonb(value) / db.now_utc() / db.now_iso()
```

`Conn` exposes exactly `execute`, `executemany`, `commit`, `rollback`, `close` — the surface the
callers actually use, not psycopg's whole connection.

Callers: every module. `app/main.py`'s HTTP middleware is the only caller of `db.connection()`
on the request path; `app/background` and the two brand-intelligence background threads open
their own.

## Error shapes

`core` raises, it does not return error envelopes — turning an exception into an HTTP response
is `app/shared/web.py`'s job. `db.current()` outside a `db.connection()` block raises
`RuntimeError`; psycopg errors propagate unwrapped.

## Must not import or touch

- `app.main`, and any feature module (`schedule`, `intake`, `meta`, `brand_web`, …). Dependency
  direction is one-way: everything imports `core`, `core` imports nothing of ours except
  `app.shared.logging`.
- Another module's tables. `core` owns `organisation`, `app_setting`, `audit_log`, `approval`,
  `interrupt` and the RLS/grant migrations; it does not write anyone else's rows.
- `procrastinate_*` internals — `app.background` is the only door.

## Decisions in force

- ADR 0027 — multi-tenant cloud SaaS on Supabase; every table carries `org_id`.
- ADR 0040 — approval is the money brake.
- ADR 0042 — work the user waits for runs on the queue.
- ADR 0052 — a logged-in request runs as role `authenticated` with an `app.org_id` claim.
- ADR 0053 — an `interrupt` raised for a campaign period carries the period id in its
  `dedupe_key`; `campaign_cycle_id` becomes `campaign_period_id`.

Module-local and reversible, decided here rather than in an ADR:

- The pool is a lazily-built module singleton keyed on `dsn()`; the test harness swaps the DSN
  and rebuilds it per test module rather than sharing one pool with a `configure=` hook
  (`app/tests/conftest.py` header explains why).
