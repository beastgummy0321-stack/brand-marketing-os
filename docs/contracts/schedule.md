# Contract — schedule (ads & scheduling)

Five things and nothing else (container contract §7). Reasoning lives in the ADRs named below;
it is not repeated here, because a second copy goes stale.

## Entry path

`app/schedule/__init__.py`. Everything else in the package (`plan.py`, `tree.py`, `creative.py`,
`period.py`, `binding.py`, `state.py`, `tree_approval.py`, `performance.py`, `repository.py`,
`routes.py`, `jobs.py`) is private and imported by nothing outside it.

The split inside the package is by job, not by size: `routes.py` takes HTTP requests, and the
others do the work. Three files were carved out of `routes.py` on 2026-09-03 (user-approved) on
exactly that line, taking it from 768 lines to 502:

- `binding.py` — matching a tree node to a live platform entity is work, not routing.
- `state.py` — reading the `llm_task` rows and assembling the brand's screen shape.
- `tree_approval.py` — the money. Container contract §7: a function that computes money or an
  approval amount never lives in a routes file. `_tree_signature`, `_tree_content_hash`,
  `_sum_daily_amounts`, `_approval_overspend`, `_fill_approval`, `APPROVAL_SCOPE_TYPE`.

The rule those three share, and the one to apply next time: **a symbol earns a line in `routes.py`
only if it would have no reason to exist outside an HTTP endpoint.** A `@router` function, its
request shape, or a constant whose whole content is HTTP-facing wording. Anything that would still
be needed if this package were driven by a CLI is work.

Import direction inside the package is one-way into `routes.py`: `routes` imports `state` and
`tree_approval`, `state` imports `tree_approval`, and neither of those imports `routes`. `state.py`
did import `routes` for one line between those two tickets; that cycle is closed and must not come
back. Note that `ImportCycleScanTest` only records edges between top-level packages, so a cycle
*inside* `app/schedule/` is invisible to it — this paragraph is the only thing guarding it.

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
- ADR 0056 — a channel catalogue is a file; its per-org state is a table.
- ADR 0057 — ad-level spend meets the coordinate through the depth-3 binding, which freezes the
  tree that produced it.
- ADR 0058 — a stored UTC timestamp becomes a date in the org's timezone before any money
  comparison against `today_for_org()`.
- ADR 0059 — an approval signs the tree's shape plus a daily ceiling; a total that only shrinks
  under that ceiling keeps it valid.

Module-local and reversible, decided here rather than in an ADR:

- The module now registers an `app.core.cleanup` function (ticket T1b): `app/schedule/repository.py`
  registers 「創意座標與素材候選」, covering the five tables this ticket added.
- **How a creative reply is matched to a tree node** — ticket T3d, settled by the user: the agent
  answers per node **name**, and names locate their nodes on their own — different names may
  arrive in any order and are reordered back to document order, which is behaviour this module
  has had and tested since ticket 09. Position is used **only inside a group of identically
  named leaves**: the Kth reply block carrying a name goes to the Kth leaf carrying that name, in
  document order. A count mismatch per name is the same failure it has always been, with the same
  message. T3d's ticket demanded a global positional zip instead, which is not implementable
  against this module's own reordering test; the reviewer returned `blocked-upstream` and this
  line is the corrected rule.

## Measured (facts this module's next ticket must not re-discover)

Moved here from `BOARD.md` on 2026-09-04 (full text: `BOARD.md` @ `6574191`).

- **Position in the prompt decides whether an instruction runs; wording does not** (T8b acceptance,
  2026-09-04). Same model (`gpt-5.6-luna` via local codex), same seven-dimension vocabulary: a
  2,210-char prompt filled all seven; the 21,679-char production prompt filled only `angle`. Three
  rounds of rewording changed nothing. Moving the vocabulary section from the middle to the **last**
  paragraph (`jobs.py`'s join order) made all six creatives 7/7. Rule: an instruction of the kind
  "answer this after you have written" goes last, never before 8k chars of methodology plus 8k of
  tree. The next person who finds the agent skipping a step looks at where the instruction sits
  before touching its wording.
- **One coordinate has two ROAS values that are both true; drawing one is picking a lie**
  (2026-09-04 probe). The backend `roas` denominator is spend on the days that tracked a conversion,
  not all spend (ADR 0057 §7, deliberately). Real ad, four days: spend 3,570, tracked revenue
  2,737.8, coverage 75% → conservative ROAS 0.767 (losing), optimistic 1.029 (winning). The chart
  draws a segment from conservative to optimistic; crossing the break-even line means "not enough
  data". Arithmetic in `frontend/src/lib/quadrant.ts`, test `quadrant.test.ts` uses these numbers.
  **The next place that shows a ROAS asks which denominator first.**
- `compute_money()` (T3e, ADR 0055 §11) takes spend from `daily_entity_spend(level="adset")`, not
  `spend_summary(level="campaign")`: membership is per ad set, and a different level does not add up.
- `app/methodology/README.md` rows 「成效判讀／下期草案」 and 「期中檢查點」 have **zero callers**;
  `providers.py:154`'s `performance_reading` label is empty. The review methodology is already
  written; the step ⑨ ticket wires it, it does not write it.
- Mind-map C (diagnosis), D (market), E (audience), P (weekly/monthly report): summaries kept, no
  tickets until the loop has run.
- Milestone stage one was walked end to end on a real account on 2026-08-29 (晨光咖啡 + BP AD) and
  again on 2026-09-04 (Beast Prime + BP AD). This round stands on that, it does not replace it.
