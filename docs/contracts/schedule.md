# Contract — schedule (ads & scheduling)

Five things and nothing else (container contract §7). Reasoning lives in the ADRs named below;
it is not repeated here, because a second copy goes stale.

## Entry path

`app/schedule/__init__.py`. Everything else in the package (`plan.py`, `tree.py`, `creative.py`,
`routes.py`, `jobs.py`) is private and imported by nothing outside it.

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
