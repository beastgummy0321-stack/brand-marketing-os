# 06 — the two Meta name lookups verify the id they are handed

Route C (permission / tenant isolation). Graduated from
`issue-meta-name-lookup-tenant-asymmetry.md` (2026-09-05).
User's decision, 2026-09-05: **change the call chain (pass the already-verified value down), not
one more Meta API call.** The rejected option and why: the only endpoint in this repo that
returns a parent id is `list_entity_insights` (`app/meta/graph.py:370`, `act_{account_id}/insights`),
and `graph.py:293,330`'s own docstrings say insights silently omit entities that never spent —
which is the exact reason these functions stopped using it. A single-node read with
`fields=campaign_id` has no proven call in this repo, so taking that route would first cost an
official-doc check.

## What

Three sibling functions in `app/meta/repository.py`, two of which trust their caller:

| function | line | what it does with the parent id |
|---|---|---|
| `campaign_ids_by_exact_name(conn, org_id, ad_account_ids, name)` | 293 | **verifies**: `SELECT account_id FROM meta_ad_account WHERE org_id = %s AND id = ANY(%s)` (`:304-306`), then `graph.list_campaigns` (`:314`) |
| `ad_set_ids_by_exact_name(conn, org_id, campaign_id, name)` | 330 | uses `org_id` only to fetch the token (`:343`); sends `campaign_id` to `graph.list_ad_sets` untouched (`:346`) |
| `ad_ids_by_exact_name(conn, org_id, adset_id, name)` | 356 | uses `org_id` only to fetch the token (`:369`); sends `adset_id` to `graph.list_ads` untouched (`:372`) |

Nothing leaks today, and this ticket does not claim otherwise. The only callers are
`app/schedule/binding.py:116` and `:143`; every value they pass came either from
`campaign_ids_by_exact_name`'s own verified result (`binding.py:99-102`) or from
`bindings_by_node_key` (`app/schedule/repository.py:508-518`, whose SQL carries
`WHERE cem.org_id = %s AND cem.brand_id = %s`); and the route
(`app/schedule/routes.py:427-430`) takes no request body at all, so no request can construct a
foreign id. `docs/contracts/meta.md:41-49` already records this as "the caller guarantees it, the
function does not".

**What this ticket changes is where the guarantee lives.** After it, the two functions refuse a
parent id this organisation has not been shown to own, and they refuse it *before* any Meta call —
so a future second caller (a backfill script, an admin tool, a new route) cannot reintroduce the
hole by being shaped differently.

The mechanism inside `app/meta/` is the implementer's to choose — it is reversible and lives in
one module. Two shapes are known to work with the data that exists:

- verify the parent id against `channel_entity_map` for this `org_id` (the table
  `bindings_by_node_key` already reads), which covers every already-bound node; **and** let
  `binding.py` hand the freshly matched campaign id down as a value the function itself minted,
  so the one path that has no row yet is still covered by provenance rather than by trust; or
- give the two functions a parameter type that only `app/meta/repository.py` can produce, so a
  bare `str` from anywhere else does not type-check and does not run.

Whichever is chosen: **do not** add a Meta API call, **do not** change `graph.py`, **do not**
widen `docs/contracts/meta.md` — main chat updates the contract page at close, once the
implementer's shape is known.

The contract, by example. Given org A owns ad account `act_111` and its campaign `c_A`, and org B
owns `act_222` and campaign `c_B`:

```json
{"call": "ad_set_ids_by_exact_name", "org_id": "org_A", "campaign_id": "c_A", "name": "夏季主打"},
{"expected": "reaches Meta, returns the matching ad set ids"}
```
```json
{"call": "ad_set_ids_by_exact_name", "org_id": "org_A", "campaign_id": "c_B", "name": "夏季主打"},
{"expected": "refused before any HTTP call to Meta; no token for org_A is spent"}
```

Same two cases for `ad_ids_by_exact_name` with `adset_id`.

## How we know it's done

1. `uv run ruff check app` — clean. `uv run pyright` — 0 errors.
2. New test in `app/tests/test_meta_daily_spend.py`: build two organisations with their own ad
   accounts and bindings, call `ad_set_ids_by_exact_name(org_A, campaign_of_org_B, …)`, and
   assert **(a)** it refuses and **(b)** `graph.list_ad_sets` was never called (patch it and
   assert `call_count == 0`). The second half is the point: an implementation that lets the call
   go out and relies on Meta returning a permission error has not moved the guarantee into this
   function. Repeat once for `ad_ids_by_exact_name`.
   Proven red once: revert the verification, watch the bad id reach the patched `graph` call,
   restore.
3. The happy path still works: `uv run pytest app/tests/test_meta_daily_spend.py -q` — green,
   including the existing `AdSetMatchUnreachableTest` (`:987-1010`) and `AdMatchUnreachableTest`
   (`:1041-1057`), which assert the shape of the "cannot reach Meta" error and must not change.
4. `uv run pytest app/tests/test_schedule.py app/tests/test_org_isolation_all_tables.py app/tests/test_architecture_boundaries.py -q` — green.
5. `cd frontend && npm run e2e` — green. The bind flow (`POST /brands/{brand_id}/tree/bind`) must
   still bind: this ticket must not make the real, legitimate path harder.
6. `git diff --name-only` matches `## Shared files touched` exactly.

No migration, no new table, no new column.

## Shared files touched

Unscoped repo-wide search for `ad_set_ids_by_exact_name`, `ad_ids_by_exact_name`,
`campaign_ids_by_exact_name` (the three names whose meaning changes):

```
app/meta/repository.py:293,304-306,314,330,343,346,356,369,372
app/schedule/binding.py:99-102,116,143
app/schedule/repository.py:508-518          (bindings_by_node_key — the org-filtered source)
app/schedule/routes.py:427-430              (the only route that reaches this chain)
app/meta/graph.py:293,330,370               (list_ad_sets / list_ads / list_entity_insights — read only)
app/tests/test_meta_daily_spend.py:987-1010,1041-1057
docs/contracts/meta.md:41-49                (records today's asymmetry; main chat rewrites it at close)
```

Expected diff: `app/meta/repository.py`, `app/schedule/binding.py`,
`app/tests/test_meta_daily_spend.py`. `docs/contracts/meta.md` is main chat's, not the
implementer's. Anything else is `blocked-upstream`.

## Contradiction check

Done-check 2 (the foreign id is refused before Meta is called) and done-check 5 (the real bind
flow still binds) can contradict each other: the cheapest way to pass 2 is to require every
parent id to already exist in `channel_entity_map`, which refuses the **first** bind of a node —
exactly the case where no row exists yet — and check 5's e2e would go red only if it covers a
first-time bind. The input that shows it: a brand whose node has never been bound, matched by
name for the first time in the same request. That path must still succeed. If the implementer
cannot make both true, that is `blocked-upstream`, not a reason to weaken check 2.
