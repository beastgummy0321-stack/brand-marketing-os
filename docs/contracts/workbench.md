# Contract — workbench (素材工作檯, the asset module)

Five things and nothing else (container contract §7). Reasoning lives in the ADRs named below;
it is not repeated here, because a second copy goes stale.

Written 2026-09-09 at Gate A (ADR 0068), before the module exists: a module is registered before
it is built. Ticket 02 landed `app/workbench/` on 2026-09-09; every shape below is now a
description of code, not only the contract tickets are cut against.

## Entry path

`app/workbench/__init__.py`. Everything else in the package (`repository.py`, `jobs.py`,
`routes.py`, `prompts.py`, `validate.py`) is private and imported by nothing outside it. The one
outside reader is `app.schedule`, and it reads only through the functions below.

## Exported shapes

```
register(app: FastAPI) -> None          # mounts /api/workbench/*
register_tasks() -> None                # idempotently registers the generation tasks
                                        # against the current app.background.app()
submit_brief(conn, org_id, brand_id, brief: dict, *, created_by: str) -> str
                                        # writes one workbench_brief row, enqueues the
                                        # parts brief["parts"] names (copy today), returns
                                        # the brief id. brief = {"kind", "source_kind",
                                        # "source_ref", "product_id", "coordinates",
                                        # "visual_tone", "visual_concept", "style_key",
                                        # "request"}; style_key defaults to "ugc"
briefs_for_source(conn, org_id, brand_id, source_kind: str, source_ref: dict) -> list[dict]
                                        # the briefs whose source_ref contains every key of
                                        # the given dict (e.g. {"source_tree_task_id": ...}),
                                        # each with status and per-part latest round summary
adopted_output(conn, org_id, brand_id, brief_id: str, part: str) -> dict | None
                                        # the adopted output of that part, else the latest
                                        # round, else None; shape = the row plus
                                        # "is_adopted": bool
```

Callers: `app/main.py`'s register loop (first two); `app.schedule.jobs` (`submit_brief`, once per
deepest node after a tree succeeds); `app.schedule.state` / `app.schedule.performance`
(`briefs_for_source`, `adopted_output`).

Routes (all under `/api/workbench/brands/{brand_id}`): `GET /briefs?status=` list; `POST /briefs`
manual brief; `GET /briefs/{id}` detail with all rounds; `POST /briefs/{id}/parts/{part}/run`
body `{"count": int}` for `image_prompt` (the user's count, no default), empty for others — enqueues
one round; `POST /briefs/{id}/outputs/{output_id}/adopt`; `POST /briefs/{id}/close` and
`/reopen`; `DELETE /briefs/{id}`.

## Error shapes

Route errors are `web.ApiError(status, code, message)`: `brief_unknown` 404, `part_unknown` 400,
`count_out_of_range` 400 (image prompts: 1–30), `brief_closed` 409 on run/adopt of a closed brief,
`round_running` 409 when that part already has a running round. Generation failures are not
raised: they land on the `llm_task` row and the output row's absence; the brief's `status` reads
`failed` with the task's error text.

## Must not import or touch

- `app.schedule`, `app.main`, `app.meta`, `app.dashboard`. The workbench knows no tree; a
  `source_ref` is stored and compared, never interpreted.
- Any other module's tables. `product` and `official_asset` are read through
  `app.brand_intelligence.repository`; brand context through `app.llm.context_compiler`.
- `procrastinate_*` internals. `app.background` is the only door.

Allowed dependencies: `app.core`, `app.background`, `app.llm`, `app.shared.web`, `app.identity`,
`app.brand_intelligence.repository` (read-only).

## Decisions in force

- ADR 0068 — the module, its two tables, the one-way schedule → workbench direction, copy made
  here and taken from the schedule page, JSON-only replies, fixed/variable prompt blocks, the
  user-owned prompt count, lengths and variant counts.
- ADR 0047 — the finished image prompt belongs here; schedule sends one visual direction.
- ADR 0042 — work the user waits for runs on the queue.
- ADR 0049 — migrations carry the `workbench_` prefix; another module's column is written
  through its owner.
- ADR 0028 / 0029 — task files under `app/departments/workbench/` are prompt parts the shell cats
  in and never parses.
- ADR 0032 — every LLM call goes through `gateway.run_task()`.

Module-local and reversible, decided here rather than in an ADR:

- **Capture styles live in `app/workbench/image_styles.json`** — `[{"key","label","capture_line",
  "authenticity_hint"}]`, default entry `ugc`; `GET /api/workbench/styles` returns it verbatim for
  the 新工單 form; `prompts.py` pastes the chosen entry into the 工單 text. Adding a style is one
  entry, no code (ADR 0068 §7).

- A closed brief is hidden from the default list and excluded from the schedule page's 投放包 only
  if it has no adopted copy; adoption survives closing.
- The "when to use" one-liners for the three lengths are frontend copy (design-system §8), not
  generated and not stored.
