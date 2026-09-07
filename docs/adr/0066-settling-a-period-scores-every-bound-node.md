---
id: 0066
decision: Settling a period scores every bound ad-set and ad node against the break-even line; only a resettle changes a score.
applies-to: [supabase/migrations/, app/schedule/, frontend/src/components/schedule/]
supersedes: none
status: in-force
---

# Settling a period scores every bound node

2026-09-08, slice smart-loop 01 station ①. User ruling: the system must get better period over period
("越排越好"), and the first thing it lacks is memory of what each node did. ADR 0053 froze two brand-level
numbers at settle; this ADR adds the per-node reading beside them.

## Rulings

1. **When.** Scoring happens inside the same user press as settlement (ADR 0053 §3: the user presses, nothing
   settles by itself). A resettle rewrites the whole set of rows for that period; the brand-level snapshot's
   audit entry (ADR 0053 §3) is the record that a resettle happened. No background job scores anything.
2. **What is scored.** Every node of the period's tree (the tree named by the period's
   `period_node_membership.source_tree_task_id`, ADR 0064 §4) that has a `channel_entity_map` binding at
   depth 2 (ad set — carries the approved `share`) or depth 3 (ad — carries the seven coordinate keys, ADR 0057).
   Depth 1 is one campaign with neither and is not scored. Rows of different depths are never summed: the same
   money sits on both levels (the reason `period.node_level_spend()` is pinned to one level).
3. **Which money.** Spend and tracked revenue of the bound platform object on the period's own
   `[start_date, end_date]`, read through `meta_repo.daily_entity_spend()` at that node's level, aggregated with
   the same arithmetic as the coordinate chart (`performance._bucket()`, ADR 0057 §7): conservative ROAS =
   revenue ÷ all spend, optimistic ROAS = revenue ÷ spend on tracked days, coverage = tracked rows ÷ rows. The
   node row is a reading, not the money of record: `campaign_period.settled_spend` keeps the ownership split of
   ADR 0053 §4, the node row does not apply it.
4. **Verdict.** Three values, derived from "both ROAS values are true" (`docs/contracts/schedule.md`):
   `win` when conservative ROAS ≥ break-even; `lose` when optimistic ROAS < break-even; otherwise `unclear`
   (including no spend, no tracked revenue, or no break-even). No other constant. The break-even used is
   `diagnosis.breakeven_roas()` at settle time, stored with its source string so a reader can see when it came
   from an unfilled margin.
5. **Approved vs actual are stored side by side, nothing is inferred.** `approved_share` /
   `approved_daily_amount` come from the bound tree; `actual_spend` from the platform. Whether the platform's
   optimiser or the user moved the money (the CBO question, `docs/issues/plan-quality/issue-budget-level-mismatch-is-never-checked.md`)
   is visible in the gap and is not decided here.
6. **Who owns it.** The `schedule` module (ADR 0049); the table is one of its brand-delete child tables. Reads
   for prompts and screens go through `schedule_repo.period_node_results()`; the scoring code lives in
   `app/schedule/scoring.py`, called from `routes.py` after `period.settle()` and imported by neither `period.py`
   nor `state.py` (the in-package import direction on the contract page).

## Considered and rejected

- **Score daily from the pull job** (the 2026-09-07 smart-loop plan): a score that moves every day is not a
  memory; and the daily job would have to decide when a period is "done", which ADR 0053 gives to the user's
  press.
- **Only "next period reads last period" without a verdict**: nothing checkable; the model could change wording
  and call it learning. Rejected by the user 2026-09-08.
- **Full automation (the system edits budgets and creates campaigns)**: needs Meta write API and an amendment
  of constitution §9; deferred by the user to a later goal.
- **Depth 1 rows / three-level totals**: rejected at plan review — no share, no coordinates, and any total across
  levels counts the same money twice.

## What we looked at

Reuse-first §2: no open-source ad-ops tool keeps a per-period, per-node verdict ledger tied to an approval;
the closest shapes are experiment ledgers in growth tooling (winner/loser per variant per window), which is the
shape adopted here. Nothing installed.
