# Contract — brand_intelligence (brand & product facts)

Five things and nothing else (container contract §7). Reasoning lives in the ADRs named below;
it is not repeated here, because a second copy goes stale.

Written 2026-09-02, ahead of the T2 slice, because a route C ticket touching a module registers
that module first. It records what `app/brand_intelligence/` **is**, not what it should be.

## Entry path

Like `core`, this package has **no single entry file**: callers import the one module they need.
`__init__.py` holds a comment plus one import of `personas`, present only so that the personas
cleanup registers itself when the package loads.

| file | what it is the door to |
|---|---|
| `repository.py` | the brand / product / fact / rule / claim / economics tables — the main door, and the only writer of them |
| `repository_channels.py` | owned channels and channel facts |
| `personas.py` | persona rows and their cleanup registration |
| `customer_voice.py` | verbatim customer quotes |
| `product_ai.py` | prompt assembly for product research (pure; the LLM call is the caller's) |
| `report.py` | the consultant report document |
| `background_job.py` | the in-memory job dict + thread the four AI features share, and its `interrupt` write |
| `advertising_history.py` | the sole writer of `brand.advertising_history` (ticket past-ads/03, ADR 0067 rule 6) |

## Exported shapes

The surface other modules actually import, not the whole file:

```
repository.get_product(conn, brand_id, product_id) -> dict | None
repository.get_product_economics(conn, brand_id, product_id) -> dict | None
repository.save_product_economics(conn, brand_id, product_id, *, actor, ...) -> dict
repository.create_rule(conn, brand_id, *, actor, severity, rule_type, content) -> dict
repository.brand_facts(...) / confirmed facts, claims, sources        # read by context_compiler
personas.list_for_brand(conn, brand_id) -> list[dict]
background_job.start(...) / status(...)                               # dict + thread, not the queue
advertising_history.set_advertising_history(conn, brand_id, value, *, actor) -> dict
```

Callers: `brand_web` (every route file), `intake`, `dashboard`, `llm.context_compiler`,
`llm.gateway`, `schedule.routes`.

## Error shapes

This module **raises**; it does not build HTTP envelopes. `_require(...)` raises `ValueError`
with a Chinese message for a missing required field; psycopg errors propagate unwrapped.
Turning either into a response is `app/shared/web.py`'s job at the route layer.

## Must not import or touch

- `app.main`, `app.brand_web`, and any other feature module. Dependency direction is one-way:
  feature modules import this one, never the reverse.
- Another module's tables. This module owns `brand`, `product`, `product_economics`,
  `brand_fact`, `rule`, `claim`, `source_reference`, `persona`, `customer_voice`,
  `learning_ledger`, `official_asset`; it writes no one else's rows, and its migrations carry
  the `brand_intelligence` prefix (ADR 0049).
- `procrastinate_*` internals. `app.background` is the only door — noting that
  `background_job.py` predates that rule and uses a thread instead (BOARD.md carries the debt).

## Decisions in force

- ADR 0027 — multi-tenant cloud SaaS on Supabase; every table carries `org_id`.
- ADR 0036 — hardcoded domain knowledge is deleted; the agent looks it up and the user vets it.
- ADR 0043 — one bucket, and the `org_id` is the first folder.
- ADR 0049 — a migration file takes the prefix of the table's owner.
- ADR 0050 — the ad-loop data model of record.
- ADR 0053 — product cost is versioned from today, never rewritten backwards.
- ADR 0067 — `brand.advertising_history` (`has_history`/`none`, NULL = not yet answered) is a
  column this module owns. First writer is `advertising_history.set_advertising_history()`
  (ticket past-ads/03), reached from `app/brand_web/routes_library_write.py`'s
  `PUT /api/library/brands/{brand_id}/advertising-history`.
