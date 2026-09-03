# Contract — schedule (ads & scheduling)

Five things and nothing else (container contract §7). Reasoning lives in the ADRs named below;
it is not repeated here, because a second copy goes stale.

## Entry path

`app/schedule/__init__.py`. Everything else in the package (`plan.py`, `tree.py`, `creative.py`,
`period.py`, `binding.py`, `repository.py`, `routes.py`, `jobs.py`) is private and imported by
nothing outside it.

The split inside the package is by job, not by size: `routes.py` takes HTTP requests, and the
others do the work. `binding.py` was carved out of `routes.py` on 2026-09-03 (user-approved) on
exactly that line — matching a tree node to a live platform entity is work, not routing.

## Exported shapes

```
register(app: FastAPI) -> None        # mounts /api/schedule/*
register_tasks() -> None              # idempotently registers the three generation
                                      # procrastinate tasks against the current
                                      # app.background.app()
```

Callers: `app/main.py`'s register loop (both), and `app/tests` (which call `register_tasks()`
again after building their own test `background.app()`).

## Error shapes

Route errors are `web.ApiError(status, code, message)` — a stable `code` string plus a
user-facing Chinese `message` (`app/schedule/routes.py:366` onward). Generation failures are not
raised: they are recorded on the `llm_task` row and read back through the task endpoints.

## Must not import or touch

- `app.main`.
- Any other module's tables. A column another module owns is written through that module's
  repository, and its migration file carries that module's prefix (ADR 0049).
- `procrastinate_*` internals. `app.background` is the only door.

Allowed dependencies: `app.core`, `app.llm`, `app.shared.web`,
`app.brand_intelligence.repository`, `app.meta`, `app.background`, and — added 2026-09-02 at T2
station ① — `app.orders.repository`, read-only, for `channel_revenue_summary()` when settling a
period. `app.orders` imports only `brand_intelligence`, `core` and `shared`, so this closes no
cycle, and `app.dashboard` already depends on it the same way.

## Decisions in force

- ADR 0047 — one visual direction per ad node, never a finished image prompt.
- ADR 0048 — `schedule_plan` runs with no web search.
- ADR 0049 — this module owns migrations; a migration file takes the prefix of the table's owner.
- ADR 0050 — the ad-loop data model of record (table list, ticket owners, open questions).
- ADR 0053 — the campaign period's life: born on the form, settled by hand, shorter period wins.
- ADR 0054 — the shared commerce calendar is a department data file, not a `holiday` table.
- ADR 0055 — a tree node is identified by a path-style `node_key` plus its channel.
- ADR 0042 — work the user waits for runs on the queue.
- ADR 0040 — approval is the money brake.

Module-local and reversible, decided here rather than in an ADR:

- The module now registers an `app.core.cleanup` function (ticket T1b): `app/schedule/repository.py`
  registers 「創意座標與素材候選」, covering the five tables this ticket added.
- **How a creative reply is matched to a tree node** (T3d, 2026-09-03, user-approved): the agent
  answers per node **name**, and names locate their nodes on their own — different names may
  arrive in any order and are reordered back to document order, which is behaviour this module
  has had and tested since ticket 09. Position is used **only inside a group of identically
  named leaves**: the Kth reply block carrying a name goes to the Kth leaf carrying that name, in
  document order. A count mismatch per name is the same failure it has always been, with the same
  message. T3d's ticket demanded a global positional zip instead, which is not implementable
  against this module's own reordering test; the reviewer returned `blocked-upstream` and this
  line is the corrected rule.
