# Contract — schedule (ads & scheduling)

Five things and nothing else (container contract §7). Reasoning lives in the ADRs named below;
it is not repeated here, because a second copy goes stale.

## Entry path

`app/schedule/__init__.py`. Everything else in the package (`plan.py`, `tree.py`, `creative.py`,
`period.py`, `binding.py`, `state.py`, `tree_approval.py`, `performance.py`, `diagnosis.py`,
`scoring.py`, `repository.py`, `period_repository.py`, `routes.py`, `jobs.py`, `history.py`) is
private and imported by nothing outside it.

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
`scoring` is called from `routes` only; `period`/`state` never import it (ADR 0066 rule 6).
`period_repository` imports nothing from the package and is imported by `period`, `routes`,
`binding`, `scoring` (ticket smart-loop 02 — split out of `repository.py` to hold the 800-line
cap; no behaviour change) and, since ticket smart-loop 03, `jobs` (`latest_settled_period()`).

## Exported shapes

```
register(app: FastAPI) -> None        # mounts /api/schedule/*
register_tasks() -> None              # idempotently registers the three generation
                                      # procrastinate tasks against the current
                                      # app.background.app()
imported_ad_count(conn, org_id, brand_id) -> int
                                      # ticket past-ads/03 (ADR 0067): how many old ads this
                                      # brand has tagged, for the cockpit guide card
```

Callers: `app/main.py`'s register loop (both), and `app/tests` (which call `register_tasks()`
again after building their own test `background.app()`). `imported_ad_count` — `app.dashboard`
(ticket 04).

`register()` also mounts three routes for the past-ads history screen (ticket past-ads/03,
ADR 0067): `GET /api/schedule/brands/{brand_id}/history` (`history.history_cards()` — connection
state, backfill progress, break-even, the per-currency ranked ad cards, and the brand's
coordinate vocabulary), `PUT /api/schedule/brands/{brand_id}/history/{external_id}` (body
`{"coordinates": {…the seven dimensions…}, "owner_note": string | null}` →
`history.tag_imported_ad()`; `ValueError("coordinate_unknown:<dimension>")` → 400
`coordinate_unknown`, `ValueError("imported_ad_unknown")` → 404 `imported_ad_unknown`), and —
added ticket past-ads/09, ADR 0067 §1.9 amendment — `POST
/api/schedule/brands/{brand_id}/history/creatives/refetch` (body `{"external_ids": [...]}`,
1-30 ids, else 400 `too_many_ids` → `history.clear_creative_cache()` → `{"cleared": <int>}`).

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
`app.brand_intelligence.repository`, `app.brand_intelligence.personas` (read-only, added 2026-09-08 by
plan-quality ticket 03 for `state._knowledge_gaps()` — the same read `context_compiler` makes; same
top-level package, no new layer edge), `app.meta`, `app.background`, and — added 2026-09-02 at T2
station ① — `app.orders.repository`, read-only, for `channel_revenue_summary()` when settling a
period. `app.orders` imports only `brand_intelligence`, `core` and `shared`, so this closes no
cycle, and `app.dashboard` already depends on it the same way. Ticket 01 (T6c) reads a second
function off the same already-allowed module, `sku_margins()`, to compute this month's actual
gross margin rate for the diagnosis break-even line (`app/schedule/diagnosis.py`) — same
read-only direction, no new edge in the layer graph. Ticket 05 (ADR 0068 §2) adds `app.workbench`
— entry point only (`submit_brief`, `briefs_for_source`, `adopted_output`), one-way: schedule
calls workbench, workbench never calls back. `LAYER_ORDER` already places `app.workbench` before
`app.schedule` (ticket workbench/02), so this closes no cycle.

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
- ADR 0064 — a binding belongs to the tree that made it; amends ADR 0055 §1/§4 and ADR 0057 §2.
- ADR 0066 — settling a period scores every bound ad-set and ad node against the break-even
  line; only a resettle changes a score.
- ADR 0067 — an ad the platform already ran enters coordinates as an `imported_ad` row its
  owner tags; no model infers why it worked. First reader/writer is ticket past-ads/03
  (`app/schedule/history.py`): `history_cards()` ranks and reads, `tag_imported_ad()` writes
  the owner's seven keys and note. No LLM call anywhere in that file.
- The `format` coordinate dimension carries a fourth value, `flexible`／「彈性格式」, since
  2026-09-09 (ticket workbench/06, ADR 0068's "Numbers and their sources" table): 1–10 images at
  one coordinate, under Meta's asset_feed_spec ≤10-image ceiling. `single_image` is not deleted.
  New brands get it from `_SEED_COORDINATES["format"]`; brands that already had `format` rows are
  back-filled once by a data migration (`ensure_coordinates_seeded` skips a dimension once any row
  of it exists).

Module-local and reversible, decided here rather than in an ADR:

- **`GET .../history` writes the creative cache rows (`coordinates_status='pending'`) — a read
  that seeds its own cache** (ticket past-ads/03, ADR 0067 §1.9). The only write a GET makes is
  the `imported_ad` upsert for cards whose creative hasn't been fetched yet (name/dates/creative
  fields, never the owner's seven `*_key` columns or `owner_note` — those are `PUT`'s alone,
  ADR 0067 rule 2). A `GraphError` from `fetch_ad_creatives` leaves that batch's cards
  `creative: null` with the error message and writes nothing.

- **A `None` creative answer is retried, never frozen forever** (ticket past-ads/09, ADR 0067
  §1.9 amendment 2026-09-08). `history.CREATIVE_RETRY_AFTER` (`timedelta(hours=24)`, stated once
  as a module constant with the ADR reference in its comment) is the only place the 24-hour
  number lives — `_needs_creative_fetch()` re-asks Meta once a row with both `creative_body` and
  `creative_image_url` NULL is that old; a row that already carries a body or an image is never
  re-asked, no matter its age. `POST .../history/creatives/refetch` clears the four
  creative-cache columns (`repository.reset_imported_ad_creatives()`) for the ids the caller
  names, so the next GET treats them as never-fetched; the route does not restrict the ids to
  ones whose `creative` is currently null — the frontend only ever sends those, but pressing the
  button against an ad that already has a good creative refetches it once and it comes back
  (ticket's own contradiction-check line).

- The module now registers an `app.core.cleanup` function (ticket T1b): `app/schedule/repository.py`
  registers 「創意座標與素材候選」, covering the five tables this ticket added.
- **The plan prompt carries this month's ad-level performance as its last section** (ticket 01,
  `docs/issues/plan-quality/`): `performance.ad_performance()` → `jobs._account_performance_text()`,
  same window as the brand page and the diagnosis (`state._current_month_window`).
- **Both generation prompts carry the latest settled period's node results as their last
  section** (ticket smart-loop 03): `period_repository.latest_settled_period()` →
  `jobs._last_period_text()`; absent when there is no settled period or it scored no nodes.
- **The tree prompt ends with 【延續】, naming last period's `win`/`unclear` nodes to keep
  verbatim and its `lose` nodes to replace** (ticket smart-loop 04): `jobs._continuity_text()`,
  appended after the 【上一期】 section. The keep block also names the settled tree's depth-1
  campaign(s), read from their bindings (`jobs._continuity_campaign_names()` →
  `repository.bindings_for_tree()`, ADR 0064) rather than `period_node_result` — depth 1 is
  never scored (ADR 0066 rule 2), and `binding.bind_tree()` matches top-down, so a renamed
  campaign strands every node under it (Amendment 2026-09-08). `binding.tree_with_bindings()`
  marks a tree node `continued_from_node_key` when its name and depth equal a scored node of
  the latest settled period — read-time, not stored, and independent of verdict (the overlay is
  name/depth matching only; which names *should* be kept is the prompt's job, not this
  overlay's).
- **Next-period suggestion is read-time** (ticket smart-loop 05): `period.next_period_suggestion()`
  — nothing stored, nothing new to migrate. Baseline is the settled period's own `daily_budget`
  (frozen at creation, ADR 0053), not the rule card's current value and not `approval.latest()`
  (per brand, not per period, and not joinable back to that settled tree without a join this
  module does not have). Direction is the depth-2 rows' spend-weighted verdict (ADR 0066 rule 4,
  reimplemented locally in `period.py` — not imported from `scoring.py`/`diagnosis.py`, which
  would close a cycle through `state.py`). Step is rule card `schedule_budget.step_rate` (default
  20, no official Meta figure — source: user ruling 2026-09-08, spec decision 3).
- **Budget placement is read live, never stored** (ticket plan-quality/05, user ruling
  2026-09-08). The tree keeps emitting shares for whichever level `budget_level` names; whether
  Meta actually holds the budget on that level or a different one is read from Meta twice —
  once in `_run_bind()`'s response (`binding.budget_placement_note()`), once when
  `schedule_diagnosis()` builds its prompt — no column, no migration, no caching between the two
  reads. When the levels disagree, the bind response's `tree.budget_note` carries one sentence
  and the diagnosis prompt carries the same fact plus the framing that this period's per-node
  spend split was Meta's optimiser choice, not the user's experiment (`ab-testing.md:72-75`);
  the section sits after `reminders`/`【上一期】` and before `role_text(lens)` — last still wins
  (the "Position in the prompt decides" measurement below).
- **Retired 2026-09-09 (ticket workbench/05)**: the matching problem below no longer exists —
  each schedule-node brief is submitted for exactly one node (`source_ref.node_key`), never a
  batch reply the shell has to zip back onto a tree. Left here as history, not as a rule anything
  reads today.
- **How a creative reply is matched to a tree node** — ticket T3d, settled by the user; **amended
  2026-09-04, again by the user** (overturning their own 2026-09-03 "leave it until it
  bites"; the ticket is gone, this line is the rule). The agent now also echoes
  **`node_key`**, and when the reply's multiset of `node_key`s equals the tree's leaf `node_key`s
  the match is made by key. T3d's stated reason for not asking — "the agent does not know the
  shell's internal position code" — was false: `jobs._creative_params_text()` `json.dumps`es the
  whole tree into the prompt and every node carries `node_key` (`tree.py:111`), so the agent is
  copying back a field it was already shown, not learning shell vocabulary. `node_key` stays
  **optional**: a missing or wrong key falls back, unchanged, to the name rule below — a paid
  agent call is not re-run over a field the model dropped.
  The name rule, still in force as the fallback: the agent answers per node **name**, and names
  locate their nodes on their own — different names may arrive in any order and are reordered back
  to document order, which is behaviour this module has had and tested since ticket 09. Position is
  used **only inside a group of identically named leaves**: the Kth reply block carrying a name goes
  to the Kth leaf carrying that name, in document order. A count mismatch per name is the same
  failure it has always been, with the same message, and that name check still runs **first**.
  T3d's ticket demanded a global positional zip instead, which is not implementable
  against this module's own reordering test; the reviewer returned `blocked-upstream` and this
  line is the corrected rule.
- **The plan prompt ends with 【投放史】 (ticket past-ads 05)**: `history.tagged_history()` →
  `jobs._history_text()`; absent when no imported ad is tagged.

## Diagnosis (T6c) — frozen shape

Settled 2026-09-06 at /slice station ①; tickets 01/02 shipped against it. Moved here 2026-09-07
when `docs/issues/ad-loop/` was retired, because the next ticket that touches diagnosis must follow
it and a ticket is not a place a rule survives.

Delivery shape: **show the readings, one "adopt" button per suggestion**, which turns that
suggestion into a brand rule card (reusing the existing "I don't like this plan" path). No new
table, no migration, nothing counts until the user presses it. Fully automatic feedback was
rejected: a wrong AI conclusion fed into the next round unintercepted cannot be traced back.

```
screen "run a diagnosis" -> program compresses (pure arithmetic) -> three LLM calls
(creative / audience / money) -> program converges (dedupe + rank by impact spend, top 5)
-> screen shows -> "adopt" per row -> one `rule` row -> next plan's prompt eats it
```

| # | decision | source |
|---|---|---|
| 1 | **Break-even line = 1 ÷ gross margin**, never a fixed 1.0. Gross margin in three tiers: (1) actual margin from this month's own-site orders -> (2) rule card `gross_margin` (default 0.70, editable in settings) -> (3) neither, so **draw no line** and say so on screen | `ads-commerce.md:13`, `ab-testing.md:72`; the tier order is the user's ruling |
| 1b | A new rule card is one more entry in `app/core/rule_cards.py`'s `CARDS`, not a migration | `rule_cards.py:1-18` |
| 1c | Per-product break-even is **not built this round but not closed off**: what is missing is "which SKU did this ad sell". Keep the columns and the fallback order | `orders/repository.py:204-241`, `schedule/period.py:202-241` |
| 2 | Convergence is the program's job, not an agent's: rank by impact spend, **take the top 5** | ADR 0057 §6 |
| 3 | **Three fixed agents split by judgement dimension** (creative / audience / money), never fanned out per ad | user's ruling 2026-08-31 (the 24-agent / 130-suggestion failure) |
| 4 | "Not enough sample" is never a threshold constant; the screen always says "a directional reading, not a statistically significant conclusion" | `ab-testing.md:73`, `:75` |
| 5/11 | ROAS reaching an agent or the screen is always **two values plus coverage**: conservative = revenue / all spend, optimistic = revenue / tracked spend. A single number is forbidden | "Both ROAS numbers are true", this page |
| 6 | Methodology uses the existing "performance reading / next-period draft" pairing; the wiring carries no methodology of its own | `app/methodology/README.md:36` |
| 7 | `task_type` reuses the existing `performance_reading` | `app/llm/providers.py:151` |
| 8 | Zero migration: the diagnosis result lives in `llm_task.rendered_output`; adopting writes the existing `rule` table with **`source_reference_id` left NULL** (an `llm_task.id` there violates the FK — proven by a plan review that ran it), and the provenance goes into `content` as text | `20260826000001_core_baseline.sql:49` |
| 9 | An adopted rule is always `severity='soft'`; `rule_type` only ever the existing `angle` / `audience` / `budget_split` | `app/schedule/routes.py` `SOFT_REJECT_RULE_TYPES` |
| 10 | The trigger is the user pressing a button, never automatic; the "this month" window is not re-opened — the AI must see the same numbers as the chart on screen | all three existing `llm_task`s are buttons |

Two rules the variance probe forced, both already implemented: **collinearity is flagged by the
program** (when every coordinate value under a dimension carries exactly one ad, and several
dimensions group identically, the compression layer must say "these dimensions cannot be told
apart"); and the **dedupe key is (dimension, coordinate value, direction)** — one row per key,
recording how many judges said it.

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
- `app/methodology/README.md` row 「期中檢查點」 still has **zero callers**. 「成效判讀／下期草案」
  and `providers.py:151`'s `performance_reading` task_type got their first caller from ticket 01
  (T6c, `app/schedule/diagnosis.py` / `jobs.schedule_diagnosis()`) — the review methodology was
  already written before that ticket; it wired it, it did not write it.
- Mind-map C (diagnosis), D (market), E (audience), P (weekly/monthly report): summaries kept, no
  tickets until the loop has run.
- **The plan-quality noise floor, the ruler for any "the prompt got better" claim** (2026-09-08,
  moved here when `docs/issues/plan-quality/` closed). Same input (`input_context_hash`), local
  codex, `jobs.schedule_plan()` called 5 times: shape is stable (3 plans 5/5, first plan 廣泛 0.7 +
  測試 0.3 5/5), wording is noise (36 direction labels, none repeated across runs; summary opener
  different every time), and before ticket 01 no number came from the account (0/5). After ticket 01,
  3/3 runs named live ads and quoted spend / ROAS / coverage against the 1.00x line — but the plan
  count went 3, 3, 1 on a 3-plan request, which three runs cannot tell apart from noise. **Next
  measurement**: 3 more `schedule_plan()` calls on the same hash; if a 1 recurs, the account section
  is displacing the plan-count instruction (position, per the rule above). Never compare wording;
  count account numbers cited and check the ratio vector against performance.
- **Cause 一 of watery plans was data, not code** (2026-09-08): `brd_bughunt` (Beast Gummy) had never
  run the intake wizard (0 `intake_draft`, 0 brand_fact / persona / claim); the doumygo brand that
  completed it (12 / 4 / 2) got a plan citing brand-specific facts from the same code. Tickets 03/04
  made the gap visible and opened the door; the profile itself is the user's 30 minutes.
- **`visual_tone` is not a grouped dimension.** `brand_creative_performance()` groups by
  `creative.COORDINATE_KEYS` (`app/schedule/creative.py:68`: audience / pain / angle / hook / proof /
  offer / format); `creative_candidate.visual_tone` (ADR 0047) is stored per candidate but never
  bucketed, so "warm vs dark, which earns" cannot be drawn yet. Hanging an image on an ad node was
  judged **no** on 2026-09-04 (re-judged after the user hand-generated and uploaded one): the
  diagnosis needs the visual direction, which `visual_tone` + `visual_concept` already carry per
  candidate; `creative_candidate.provider` / `provider_job_id` / `provider_status` exist (all NULL)
  for the day generation is wired. The open axis is the grouping, to be judged together with the
  first round that has spend on tagged coordinates — not before.
- Milestone stage one was walked end to end on a real account on 2026-08-29 (晨光咖啡 + BP AD) and
  again on 2026-09-04 (Beast Prime + BP AD). This round stands on that, it does not replace it.
