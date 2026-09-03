---
id: 0052
decision: A logged-in request runs as role `authenticated` with an `app.org_id` claim; every org table gets a policy on it.
applies-to: [supabase/migrations/, app/core/db.py, app/shared/web.py, app/tests/test_rls_tenant_policy.py, app/tests/test_real_db_schema_drift.py]
supersedes: none
status: in-force
---

# The org travels on the connection, for logged-in requests

**Amends ADR 0027 decision 9**, which is not retired and stays in force for everything else it
says. Decision 9 reads "RLS enabled on every table, no policies; the backend connects as
`postgres`, which bypasses RLS, so RLS exists only to close anon/authenticated access through
PostgREST." From this ADR onward the second half is false: there are policies, and a logged-in
request does not run with the bypass. ADR 0027 carries a correction line pointing here.

2026-09-02, decided by the user in a /slice station ① interview.

## What was actually true before this (measured, not recalled)

Every number below was read off the running local Supabase (`postgres@127.0.0.1:54322`) on
2026-09-02. `BOARD.md` had three of them wrong in the pessimistic direction, which is why they
are written down here.

- `public` holds **47** base tables, not 99. (Ticket 3's migration dropped 44 ad tables.)
  Four procrastinate tables live next door in `public__queue` (ADR 0038).
- **RLS was already enabled on all 47.** `20260828000001_core_rls.sql` and six later files
  issue 95 `ALTER … ENABLE ROW LEVEL SECURITY` statements between them, and
  `app/tests/test_real_db_schema_drift.py::test_every_table_has_rls_enabled` has been holding
  that ratchet — for *every* table, not just new ones — the whole time.
- `pg_policies` in `public`: **0 rows.** That was the actual gap: a lock with no key rule.
- The backend's `postgres` role is **not** a superuser (`rolsuper = false`) but does carry
  `rolbypassrls = true`. Same effect, different attribute.
- Only `organisation` and `app_user` lack an `org_id` column, matching the exemption list in
  `app/tests/test_org_isolation_all_tables.py:20`.
- **`authenticated` holds no CRUD on `public` at all.** Its 47×3 = 141 grants are exactly
  `REFERENCES`, `TRIGGER` and `TRUNCATE`; `SELECT`, `INSERT`, `UPDATE` and `DELETE` are zero.
  (Found by the R1 reviewer after the first draft of this ADR asserted the opposite from a
  grant *count*. The count was right and the reading was wrong.) Two consequences: the sweep
  must grant CRUD explicitly, table by table, and the door that has actually been keeping anon
  and authenticated out of PostgREST is the missing grants, not the policy-less RLS.

## The decision

1. **The claim is a GUC, not a JWT.** Policies read `current_setting('app.org_id', true)`. The
   backend talks to Postgres directly, not through PostgREST, so nothing else would ever
   populate `request.jwt.claims`; inventing that shape would be decoration. An unset claim
   returns SQL NULL and an empty claim returns `''` — **both yield zero rows** (measured), so
   the failure direction is "sees nothing", never "sees everything".
2. **The role is Supabase's existing `authenticated`.** It already exists, is not a superuser,
   does not bypass RLS, cannot log in (so it is reachable only by `SET ROLE` from a connection
   that already authenticated), and `postgres` is a member of it — `SET ROLE authenticated`
   and `RESET ROLE` both verified working on the app's own connection. No new role is created.
3. **The switch happens after `require_actor()`, and only there.** `app/shared/web.py:249` is
   the single entry every one of the 133 authenticated routes passes through. Before it, the
   request has no org and reads as `postgres`; after it, the connection is scoped for the rest
   of the request.
4. **Scope is released when the connection returns to the pool**, via psycopg_pool's `reset=`
   callback (`psycopg_pool/pool.py:54`, version 3.3.1 — pinned in `uv.lock`). A pooled
   connection handed to the next request carrying the previous request's org would be the
   whole bug this ADR exists to prevent.
5. **`SET ROLE` is committed immediately, and re-asserted on rollback.** Measured: a `SET ROLE`
   issued inside a transaction that is then rolled back reverts to `postgres` with the claim
   cleared — RLS silently off, gates all green. A `SET ROLE` that has been committed survives a
   later error and rollback intact. So the switch commits at once, and `Conn.rollback()`
   re-applies the scope it holds. A test asserts the post-rollback state, because this is
   exactly the kind of hole that never shows up in a passing suite.
6. **No `FORCE ROW LEVEL SECURITY`.** Measured on a scratch schema: with `FORCE` on, `postgres`
   still read every row, because `BYPASSRLS` beats `FORCE` — `FORCE` only removes the table
   *owner's* exemption. Since the design never relies on `postgres` being constrained, `FORCE`
   would be a statement that changes nothing. `BOARD.md` asked for it; it is not written.
7. **The queue is untouched.** `background.enqueue()` opens its own connection through
   `SyncPsycopgConnector` (`app/background/__init__.py:159-172`), so the request's `SET ROLE`
   never reaches it. The four `public__queue` tables also have RLS off already. They need no
   policy, no grant, and no exemption list entry — the earlier worry about locking the worker
   out does not apply to this design.
8. **`organisation` and `app_user` get their own policies**, since they carry no `org_id`:
   `organisation` on `id = current_setting('app.org_id', true)`, `app_user` through
   `membership` (which does carry `org_id`), matching the reasoning already written at
   `app/tests/test_org_isolation_all_tables.py:8-13`.
9. **A ratchet, with no new tolerance list.** After the sweep, a table that has `org_id` and no
   `authenticated` policy is a red gate. The existing 47 are fixed in the same slice, so the
   gate ships with nothing frozen. T2–T6's ~25 new tables inherit it.

## The vault door, and the hole that pinning `search_path` does not close by itself

Switching a request to `authenticated` takes away the bypass that let it read Supabase Vault.
Measured: with the switch on, 22 of 708 tests failed and every one failed on `permission denied
for schema vault`. The user chose, on 2026-09-02, to open a door rather than to widen a grant or
to keep the credentials path outside the lock: three `SECURITY DEFINER` functions —
`core_vault_read_secret`, `core_vault_save_secret`, `core_vault_delete_secret` — that hand back a
secret only if it belongs to the caller's own org. They check ownership against the only two
places a secret id is stored, `app_setting` and `meta_credential`, and they skip the check when
no claim is set, so every path that still runs as `postgres` behaves exactly as before.
(Amended by ADR 0056 §4: `meta_credential` is replaced by `channel_credential`, and the
ownership check's second branch is repointed there in the same migration that drops the old
table — this pair, not this paragraph's prose, is what changed.)

**`SET search_path = <schema>, vault` on a `SECURITY DEFINER` function is not enough, and the
gap is invisible until someone attacks it.** PostgreSQL searches the temporary schema *first*
unless `pg_temp` appears in the path explicitly. So an `authenticated` caller can
`CREATE TEMP TABLE app_setting`, seed one row claiming it owns someone else's secret, and the
ownership check inside the definer function reads the attacker's table. Reproduced on this
machine against the real `public` schema: the attack returned another org's Meta token, 193
characters of it. The fix is to name `pg_temp` in the path, **last** — naming it at all stops the
implicit first-position search, and putting it last stops a temp object shadowing a real one.
Verified both directions: the same attack against the fixed functions raises
`insufficient_privilege`.

Checked at the same time, so the next person does not have to: `authenticated` holds no `CREATE`
on `public` and no `CREATE` or `USAGE` on `vault`, so `pg_temp` is the only schema in that path
it can write to. Schema-qualifying the two tables inside the functions would be defence in depth,
not a fix for a live hole.

The general form, worth more than this one instance: **a gate that has never been attacked is not
evidence.** Eight machine gates and 710 tests were green over the vulnerable version, because
nothing in the suite creates a temp table. What found it was one reviewer asked to try.

## What counts as a stale claim, and what does not

Nine places in the repo say some version of "RLS is on, there are no policies, and the backend
connects as `postgres`". Two kinds, handled differently:

- **In-force documents** — `app/tests/test_real_db_schema_drift.py` (corrected by R1), ADR 0027
  decision 9 (correction line added by R1), ADR 0038 and ADR 0043. These describe the system in
  the present tense and are read as current fact. They are corrected.
- **Applied migration files** — the header comments in `20260828000001_core_rls.sql`,
  `20260830000001_core_approval.sql` and `20260830000004_meta_entity_spend.sql`. An applied
  migration is a dated record of one change, not a claim about today; the project rule is that
  applied files are never edited, and rewriting their comments to match a later decision would
  make the history lie about what that migration did. They stay as written.

## Why this is a second lock, not the front door

Constitution 3: the frontend only talks to FastAPI. No untrusted client holds a database
connection, so RLS here is not the gate that keeps tenants apart — the query layer is, held by
`UnscopedTenantReadScanTest` (`app/tests/test_architecture_boundaries.py:257`) and by
`test_org_isolation_all_tables.py`. This is the layer that catches the day one of those is
wrong. It is deliberately ranked below them, and that ranking is why option "every path,
including background jobs" below was not taken.

## Considered and rejected

- **Every path bites, background workers included.** Each job would declare its own org and the
  worker would switch roles too. Strictly better isolation; rejected because procrastinate's
  connector owns its own connections, the startup and login paths have no org at all, and the
  cost roughly doubles for a layer that is already the second lock. What is given up is written
  down: a background job that writes to the wrong org is not stopped by the database.
- **Read-only policies first (SELECT only, writes stay bypassing).** Smaller blast radius;
  rejected because "org A writes into org B" is the expensive failure, and the 47 tables would
  have to be walked twice.
- **Defer the whole thing to 07-2, with the deployment batch.** This was `BOARD.md`'s original
  schedule. Rejected once the numbers came in: 47 tables not 99, RLS already on, and T2–T6
  about to add ~25 more tables that would each need retrofitting. Doing it before those tickets
  is strictly less work. The original reason for 07-2 — "do it while there is no real customer
  data" — is satisfied a fortnight earlier, not violated.
- **A new dedicated role (`app_tenant`).** Rejected under reuse-first: `authenticated` already
  exists with exactly the needed attributes — not a superuser, no `BYPASSRLS`, no login, and
  `postgres` is already a member of it. It brings no CRUD grants with it (see above), but
  neither would a new role, so that is not a reason to create one.

## What we looked at

Supabase's own documented RLS pattern (policies `TO authenticated`, claim read out of a
setting) is the shape copied here; what is *not* copied is `auth.uid()` / `auth.jwt()`, because
those read a JWT that PostgREST injects and nothing injects it on a direct psycopg connection.
The per-request `SET ROLE` plus session GUC, released by the pool's reset hook, is the standard
shape for a server-side pool talking to Postgres directly. No package was adopted: this is
three SQL statements and a pool callback, well under the bar for a dependency.
