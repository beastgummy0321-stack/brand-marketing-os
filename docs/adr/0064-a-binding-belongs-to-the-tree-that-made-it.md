---
id: 0064
decision: A binding belongs to the tree that made it; spend meets the binding that was live on that spend's own date.
applies-to: [supabase/migrations/, app/schedule/, frontend/src/components/cockpit/]
supersedes: none
status: in-force
---

# A binding belongs to the tree that made it

2026-09-06, slice-10 station ①. Amends **ADR 0055 §1/§4** (the identity of a *binding*, not of a
node) and **ADR 0057 §2** (which tree answers "whose creative is this ad"). Schema change:
the user approved this plan on 2026-09-06 before any code was written, per constitution rule 2.

## The problem this closes

Measured 2026-09-06 in the usability drill (`docs/drills/`): **three roles in three
organisations, 3/3**. Plan the next period and the money the previous period spent loses its
coordinates — permanently.

| moment | dimensions with values | untagged |
|---|---|---|
| before period 2 was planned | 7 of 7, `angle` from 0.7 to 3.4 | 0 |
| after period 2 was planned (period 2 had spent nothing) | **0 of 7** | **5,180 (100%)** |
| after period 2 started spending | period 2's are back | period 1's 5,180 stays untagged forever |

Two independent halves produce it, and only fixing both closes it:

1. **The read asks the wrong tree.** `_vetted_depth_three_bindings()`
   (`app/schedule/performance.py:57-79`) reads `state._display_task_row(...)` — the *newest*
   `schedule_tree` row — and keeps a binding only if `node_name_at_bind` still equals the name
   at the same `node_key` in that tree. A new period is a new tree, so every binding made
   against the old tree fails a vote it was never a candidate in.
2. **The row itself is overwritten.** `channel_entity_map` is `UNIQUE (org_id, brand_id,
   channel_id, node_key)` and `upsert_binding()` (`app/schedule/repository.py:540-566`)
   `ON CONFLICT ... DO UPDATE`s that key. Node `1.1.1` of period 2 replaces node `1.1.1` of
   period 1, including its `source_tree_task_id`. After period 2 binds, period 1's ad → slot
   link does not exist anywhere in the database. That is where "permanently" comes from.

A third defect rides along: the untagged bucket's copy on screen says the excluded money is
"手動建的廣告" — ads the user built by hand. It is not; those ads came out of this system. The
bucket has one hard-coded explanation for what is really several causes.

## 1. The unique key gains the source tree — this amends ADR 0055 §1/§4

ADR 0055 §1 settles how a **node** is identified: `node_key` plus channel. That stands. What
this ADR changes is the identity of a **binding**: a binding is a fact about one tree, so its
key is `(org_id, brand_id, channel_id, node_key, source_tree_task_id)`, declared
`UNIQUE NULLS NOT DISTINCT` so that the rows written before `source_tree_task_id` existed
(all `NULL`) still collide with each other exactly as they do today.

ADR 0055 §4's sentence "re-binding overwrites, and keeps no history" narrows to: re-binding
**the same node of the same tree** overwrites. Binding the same position in a *different* tree
is a different fact and gets its own row.

## 2. Spend meets the binding that was live on that spend's own date

An entity can be bound in two trees — the same campaign reused across two periods. Its daily
spend rows are then split by date: a row for day D belongs to the binding for that entity with
the **latest `created_at` date not after D**; a row earlier than every binding belongs to the
earliest one. No new column: `created_at` is already on every row, and the bind press is what
makes the fact true.

This is the answer to "who owns the overlap" that both drill issues asked for. It needs no
period join, and it is the same shape `period.node_level_spend()` already uses for membership:
the day decides.

## 3. The screen keeps showing what it shows today

`tree_with_bindings()` (display) keeps answering "is this position bound?" with the **newest**
row for that `node_key` whose `node_name_at_bind` still matches — unchanged behaviour, so
re-expanding a plan does not make bound nodes look unbound.

`bind_tree()` asks a different question — "does *this* tree have a row for this node?" — and so
reads rows scoped to `tree_row["id"]`. Without this split, a node that displays as bound
(inherited from the previous tree's row) would be skipped by the binder, and the new tree's ads
would never get a row of their own. Two readers, two questions, one table.

## 4. Settlement joins on the tree too

`period_node_memberships_for_brand()` joins `period_node_membership` to `channel_entity_map` on
`node_key` alone. With more than one row per node that join fans out and
`period.node_level_spend()` counts one ad set's money once per tree. `period_node_membership`
therefore carries `source_tree_task_id` as well, written at the same moment by the same binder,
and the join uses it. This is a money path; it is the reason this slice is route C rather than a
read-time patch.

## 5. The untagged bucket stops naming a cause it does not know

`CoordinateQuadrantChart.tsx` and `CockpitPage.tsx` say the untagged money is manually built
ads. The bucket cannot know that. It says what it does know: this spend has no coordinate —
either the ad was not made by this system, or its binding predates coordinates. Copy only; no
logic hangs on it.

## 6. Considered and rejected

- **Read-time fix only** (vet each binding against its own tree, leave the schema alone).
  Recovers period 1 until period 2's bind overwrites the row, then loses it again — it does not
  close the word in the issue's title. Rejected by the user, 2026-09-06.
- **Snapshot the coordinates onto the spend rows.** A second copy of a fact that already has a
  home; `meta_entity_spend` belongs to `app/meta` and would start carrying schedule's data
  (container charter §1).
- **Keep one row and version it in a history table.** A second table to answer a question the
  first table can answer once its key is right.

## 7. What we looked at (reuse-first §2)

Nothing external: this is a uniqueness key on our own table, not a capability. The two products
whose model was checked for the same problem in ADR 0055 §12 (Meta's own ad hierarchy, and
Google Ads' resource names) both key a link row by the *pair* of the platform entity and the
campaign version that produced it, which is the same shape as this decision.

## 8. What this does not close

The campaign-period screen still shows only the current period; the previous period's dates,
plan text and tree are not reachable from any screen. That is a screen, not an attribution bug,
and it is recorded as `docs/issues/ui/issue-period-page-has-no-history.md`.
