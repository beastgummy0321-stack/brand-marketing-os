---
id: 0059
decision: An approval signs the tree's shape plus a daily ceiling; a total that only shrinks under that ceiling keeps it valid.
applies-to: [app/core/approval.py, app/schedule/tree_approval.py, supabase/migrations/]
supersedes: none
status: in-force
---

# An approval signs a shape and a ceiling, not a number

2026-09-04, ticket M2. ADR 0040 owns the money brake; this ADR narrows *what the press signs*.
Money path: the user approved the ticket before it was written (BOARD.md level 1) and approved
this plan on 2026-09-04. Written before any code, per constitution rule 2.

## The problem this closes

`_tree_signature()` (`app/schedule/tree_approval.py:26-41`) puts every node's `daily_amount`
into `content_hash`. So **any** budget movement — including one the system makes to save
money — flips `matches_current_tree` to false and the screen tells the user their approval no
longer covers what is in front of them.

Today this bites nobody: `grep` finds no code that changes `daily_amount` on its own. But the
fuse is already installed — `campaign_period_budget_version` exists and its `change_type`
CHECK already carries the value `auto_decrease` (ADR 0050, built by T2a, **0 rows and no
writer**, verified 2026-09-04). The first ticket that gives that table a writer makes every
automatic budget cut demand a fresh human press.

That is a direct collision with **constitution rule 9**: *"the system spends nothing without
the user's press. **It may save money on its own**, and must be able to undo it."* A rule that
permits the system to save money on its own cannot coexist with a signature that voids itself
whenever the system saves money.

## The ruling

**What the user presses on is a shape and a ceiling.**

| what | where | what changing it means |
|---|---|---|
| the tree's structure — names, `fields`, `warnings`, `levels`, `budget_level`, children | stays in `content_hash` | a different plan. The approval is void; press again. |
| each node's **`share`** (the proportional split, 0–1, summing to 1.0 — `app/schedule/tree.py:86-94, 148-152`) | **stays in `content_hash`** | money moved *between* ad sets. That is a different plan too. Void. |
| each node's **`daily_amount`** (`share × total`, `app/schedule/tree.py:152`) | **leaves `content_hash`** | pure scale. Allowed to shrink. |
| the **total** daily amount | new column `approval.max_daily_amount` | above it, the approval does not cover today's spend. |

Because `daily_amount` is exactly `share × total`, dropping it and keeping `share` is not a
loosening — it separates the two things that were tangled in one hash. Moving budget between
nodes changes `share` and still voids the signature. Only scaling the whole tree down slips
through, which is the one movement rule 9 explicitly permits.

`max_daily_amount` is set **equal to** the approved total at press time. It is not a headroom
input and the user is never asked to "approve up to 120%" — that would be the system spending
more than what was pressed, which rule 9 forbids outright. The column exists as its own field
rather than being read off `approved_amount` because the two answer different questions and
will diverge the day a ticket lets a user raise a ceiling without re-approving the shape.

The screen gains one more answer beside `matches_current_tree`:

```json
{
  "matches_current_tree": true,
  "approved_amount": 1000.0,
  "max_daily_amount": 1000.0,
  "current_daily_amount": 850.0,
  "within_approved_ceiling": true
}
```

## `expected_to_date` stops using the approval's number

Second-order consequence, and it must not be skipped, because it is the same class of error
ADR 0058 just closed. `_approval_overspend()` computes
`expected_to_date = approved_amount × days_elapsed`. Once the total is allowed to shrink below
the ceiling, `approved_amount` is an **over**-estimate of what the system will actually spend,
so real spending looks *less* overspent than it is — the brake erring towards letting go,
exactly what ADR 0040 forbids.

So `expected_to_date` is computed from the tree's **current** total
(`_sum_daily_amounts(tree["nodes"])`), not from the approval row.

**Honest limit, written down rather than hidden**: if the budget changed part-way through the
window, neither the old nor the new total is right for the whole window — the exact answer
needs the per-day history in `campaign_period_budget_version`, which has no writer yet. The
current total is strictly closer than the ceiling in every case, including today's, and the
exact version-aware computation belongs to whichever ticket first writes that table.

## Why now, when nothing bites yet

Measured 2026-09-04: `SELECT count(*) FROM approval` → **0**, and
`campaign_period_budget_version` → **0**. Removing a key from `_tree_signature` rewrites the
`content_hash` of every approval ever signed; at zero rows that costs nothing. At the first
real customer it costs every live approval reading "the content has changed" on the same day.

This is constitution rule 3 applied to a semantic rather than a column: the expensive-to-change
thing is decided before the feature that needs it exists.

## What was considered and rejected

- **Leave `daily_amount` in the hash and let auto-decrease re-approve automatically.** Rejected:
  a system that re-signs on the user's behalf is not a press. Rule 9's press is the whole brake.
- **Ask the user for a ceiling above the total ("approve up to 120%").** Rejected: rule 9 permits
  the system to save money, never to spend more than was pressed on.
- **Read the ceiling off `approved_amount` and add no column.** Rejected under rule 3 — the two
  fields answer different questions, and merging them writes the schema shut against raising a
  ceiling without re-approving a shape.
- **Do M2 later, when something actually writes budgets.** Rejected on the measured numbers
  above: later is the expensive version of the same change.

## How this can be seen red

Approve a tree, then scale every node's budget down by 15% without changing any `share`.
Before: `matches_current_tree` false. After: true, `within_approved_ceiling` true, and
`expected_to_date` reflects the reduced total rather than the ceiling. Raise the total 1 unit
above the ceiling and `within_approved_ceiling` goes false.
