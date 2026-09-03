---
id: 0057
decision: Ad-level spend meets the coordinate through the depth-3 binding, which freezes the tree that produced it.
applies-to: [supabase/migrations/, app/schedule/, app/meta/, frontend/src/components/cockpit/]
supersedes: none
status: in-force
---

# Performance meets the coordinate at the depth-3 binding

2026-09-03, T5 station ①. The user twice sent the previous round back: once for reasoning from
"my Meta account is only a test account" (constitution rule 1 forbids single-tenant premises),
and once for accepting the published diagram without re-verifying it.

## 0. What was measured today, before any of this was decided

Every number below came out of a command run on 2026-09-03, not from a document:

| fact | how |
|---|---|
| Real Meta data exists again: 1 credential, 4 ad accounts, `BP AD` bound to `brd_bughunt` | `select` on `channel_credential`, `meta_ad_account`, `brand_meta_ad_account` |
| `meta_entity_spend` went 0 → **166 rows** (9 ads, 15 days, **28,237.00 TWD**) | `python -m app.meta.daily_pull --since 2026-08-20` |
| ROAS is present on **46 of 121** ad-level rows (38%) | `count(roas)` grouped by `level` |
| campaign / adset / ad totals are **exactly equal**, every single day | `sum(spend)` grouped by `level`, and by `spend_date` |
| 6 `creative_candidate` rows, **all `coordinates_status = 'tagged'`**, at node keys `1.1.1`–`1.2.3` | `select` on `creative_candidate`, `creative_slot` |
| `published_ad_external_id` is non-null on **0 of 6** rows | `count(published_ad_external_id)` |
| `channel_entity_map`, `channel_revenue`, `learning_ledger`: **0 rows** | `count(*)` |
| **No query anywhere filters by `adset_id`** | `grep -rn "adset_id" app/ --include=*.py` piped to select/where/group |

**The intersection of the two sides is empty**: the 9 ads carrying all 28,237 TWD were built by
hand in Meta and carry no coordinate; the 6 coordinate-tagged creatives have never been built on
Meta. That is not a defect — it is the loop not having been walked yet — and it is why §5 below
refuses to hide the untagged money.

## 1. The join path, and why there is no new table

```
creative_candidate.{audience,pain,angle,hook,proof,offer,format}_key
  → creative_slot (brand_id, source_tree_task_id, node_key)          [unique index, T3d]
  → channel_entity_map (org_id, brand_id, channel_id, node_key), depth = 3
  → external_id
  → meta_entity_spend (level = 'ad', entity_id = external_id, spend_date in window)
```

Every link already exists. `channel_entity_map` is the single place a node is tied to a platform
entity (ADR 0055 §1), `depth` is generated from `node_key`, and ADR 0055 §7 left level 3 unbound
precisely because its only consumer is this decision. T5 opens it: **more rows, not a migration**,
exactly as rule 3 requires.

The join is **not** written as one SQL statement across both modules. `meta_entity_spend` belongs
to `app/meta`; `creative_candidate` and `channel_entity_map` belong to `app/schedule`. The
established shape is `period.compute_money()` — read `meta_repo.daily_entity_spend(level=...)`,
join in Python against the schedule module's own rows. T5 follows it. A cross-module SQL join
would put `app/schedule` inside another module's table (container contract §1).

## 2. The binding freezes which tree produced it

`channel_entity_map` gains `source_tree_task_id`, written at bind time from the tree row the bind
ran against, nullable (rows bound before this column exist, and levels 1–2 do not need it).

Without it, "which creative is this ad's?" can only be answered by picking the newest
`schedule_tree` row — the `_latest_task_row` shape. `creative_slot` is unique on
`(brand_id, source_tree_task_id, node_key)`, so re-expanding the tree gives node `1.2.3` a second
slot with a second candidate and a second set of coordinates. Reading the newest one would
re-attribute last month's spend to this month's creative: constitution rule 7, "never answer what
was true then with a current-state column".

**This is a narrowing of the board's "break `_latest_task_row`", not the whole of it.** The
general problem — plan, tree, reject and approve all read the newest row — is untouched here and
stays on the board. What T5 buys is that the one path where a stale read silently corrupts money
attribution is closed by a frozen column instead of by a convention.

A rebinding overwrites this column with the rest of the row, per ADR 0055 §4's "no history is
kept, and here is the named consumer test". The consumer test is unchanged: nothing reads "which
entity was this node bound to last month".

## 3. `creative_candidate.published_ad_external_id` is dropped

ADR 0055 §7 left the choice to T5: denormalised convenience, or gone. It is dropped.

Measured: 6 rows, 0 of them non-null, and a repo-wide unscoped sweep returns 4 hits — `BOARD.md`,
ADR 0050's table list, ADR 0055 §7, and the migration that created it. **No code reads or writes
it.** Keeping it would mean two places answer "which ad is this", one of them with no writer, and
the first person to write the convenience column without writing the map would produce a binding
the settlement path cannot see.

## 4. `meta_entity_spend.currency` is frozen on the row

Added `NOT NULL`, backfilled from `meta_ad_account.currency` (itself `NOT NULL`, sourced from
Graph's `/me/adaccounts` `currency` field), then set `NOT NULL`.

Not a convenience. `brand_meta_ad_account` is m:n, so one brand may bind accounts in two
currencies, and `SUM(spend)` across them is two kinds of money added together — wrong with no
error, which is the failure mode the published diagram's database stress test named and the one
`roas`'s NULL-is-never-0 rule exists to avoid. Resolving currency by joining to the account at
read time would answer "what currency was this spend in" with the account's *current* setting:
rule 7 again, on the money path.

**Every read that sums spend groups by currency and never adds across it.** With one currency in
play today that costs one `GROUP BY`; the day a tenant runs TWD and USD it is the difference
between a wrong number and two right ones.

## 5. Untagged spend is a bucket, never a hole

The coordinate view reports, for one brand and one date window:

- one row per coordinate **value** within each of the seven dimensions, over ads bound at depth 3
  whose candidate carries that key;
- one **`未標座標`** bucket holding every other ad-level row for the brand's bound accounts.

**Invariant: bucket + tagged == the brand's total ad-level spend for the window, per currency.**
It is the ticket's own done-check, and today it is checkable against real money: 28,237.00 TWD,
all of it in the bucket, none of it tagged.

Rejected: showing only tagged coordinates. On the day the loop is first walked, one generated ad
would sit next to a hand-built account and the screen would imply the brand spent NT$300. The
same reasoning as ADR 0055 §11's rejection of a separate "unassigned" figure, reaching the
opposite conclusion for the opposite reason: there, the number reconciled with nothing; here, the
bucket is exactly what makes the total reconcile.

An ad may carry more than one coordinate dimension, so a row appears once per dimension it has a
key for. Dimensions are reported independently — this is a per-dimension breakdown, not a
cross-tabulation. Combinations (`pain × proof → ROAS`) need more than one generated ad per cell
before they say anything; the data model already supports asking, so this is a reading choice,
not a schema one.

## 6. The arithmetic is the program's; the judgement is T6's

T5 computes spend, impressions, clicks, revenue (`spend × roas`, summed only over rows where
`roas IS NOT NULL`) and roas coverage per coordinate, and renders them as a table in the cockpit,
under the existing per-campaign spend table.

It does **not** run the three diagnosis agents, does not rank to a top 5, and does not draw the
four-quadrant bubble board. Those are T6. The seam is the user's own design, recorded on
2026-08-31: *the program compresses, the AI only judges*. T5 is the compression; a compression
step is verifiable against a total, which is what makes it a route C slice that can be signed off
with numbers instead of with taste.

Consequence, stated plainly: **the loop's last link closes at T6, not at T5.** The board row
saying "閉環在這裡合攏" moves with the diagnosis.

## 7. `roas` is reported with its coverage, never averaged into a lie

Measured today: 38% of ad-level rows carry a `roas`. `spend_summary`'s `bool_and(roas IS NOT
NULL)` (`app/meta/repository.py:424,437`) returns NULL for the whole group when any day is
missing one — the first of T6's five reasons the bubble board cannot be drawn.

The coordinate read does not reuse that rule. Revenue is `SUM(spend × roas)` over rows that have
a `roas`, and the coverage fraction (`rows with roas / rows`) is returned beside it, so a
coordinate backed by 2 of 15 days is visibly weaker evidence than one backed by 15 of 15. NULL
still means 未追蹤, never 0 (`20260830000004_meta_entity_spend.sql`). Fixing `spend_summary`
itself is T6's, named there.

## 8. The ad level's `effective_status` has twelve values, and one of them is a reading trap

Verified against the official reference on 2026-09-03
(developers.facebook.com/docs/marketing-api/reference/adgroup/): the Ad node's `effective_status`
is `enum {ACTIVE, PAUSED, DELETED, PENDING_REVIEW, DISAPPROVED, PREAPPROVED,
PENDING_BILLING_INFO, CAMPAIGN_PAUSED, ARCHIVED, ADSET_PAUSED, IN_PROCESS, WITH_ISSUES}` — six
more than the campaign level's list in ADR 0055 §4. The edge is `GET /{AD_SET_ID}/ads`, "The ads
under this ad set" (developers.facebook.com/docs/marketing-api/reference/ad-campaign/ads/), whose
Ad nodes carry `id`, `name`, `adset_id`, `campaign_id`, `status` and `effective_status`.

No schema change: `external_status` is `TEXT` with no CHECK and stores the platform's own word
verbatim (ADR 0055 §4), which is exactly why a level with six extra words costs nothing.

**The trap, written down so T6's diagnosis does not walk into it:** a `DISAPPROVED` or
`PENDING_REVIEW` ad spends nothing. On a coordinate table that reads "NT$0", it is
indistinguishable from an angle nobody wanted. T5 stores the status and does not interpret it;
any agent that judges a zero-spend coordinate must read it first.

## 9. What T5 does not do, and why — the ablation

Run at the user's instruction before any code, twice: once wrongly (leaning on "one account, one
currency, one manual test"), then again against constitution rules 1 and 3. Recorded so none of
it is re-proposed next month.

| dropped from the board's T5 row | why it is not here |
|---|---|
| index `(adset_id, spend_date)` | The query it was measured for no longer exists: ADR 0055 §6 replaced membership's `ad_set_external_id` with `node_key`, and the query that does exist (`daily_entity_spend`) filters `(ad_account_id, level, spend_date)` — covered by the existing unique index. Zero queries in the repo filter by `adset_id`. Install it when one does. |
| `channel_revenue` gains `spend`／`campaign_period_id`／`currency`／`ad_channel_id`／`source_row_hash` + unique key | Real, and a money bug at any scale — hand-entered rows do not deduplicate on re-import. But it is on the revenue-import path, not on the path from a coordinate to a number, and ADR 0055 §11 keeps revenue at brand level for exactly this round. It gets its own board row, not silence. |
| `learning_ledger` filled in "while it is still empty" | 0 rows, 0 readers, 0 writers, its read side deleted at `app/llm/context_compiler.py:17`. Columns on an empty unread table cost the same to add later as now, so **no door closes** (rule 3's test, applied literally). The published diagram's own conclusion was "treat it as a new table, or do not use it". |
| the three diagnosis agents and the top-5 ranking | §6. |
| coordinate-tagging the 9 hand-built ads | The user's own 2026-08-31 decision: legacy ads get coordinates later, and rule 3 is already satisfied — the seven keys are nullable with `coordinates_status`, so batch tagging is **inserting data**, not a migration. |
| `approval.max_daily_amount`, the `_approval_overspend()` UTC-vs-org-timezone bug | Money path, both explicitly awaiting a plan and approval. Not touched by T5, not "quietly fixed". **The timezone half is no longer deferred: it was approved and closed on 2026-09-04 by ticket M1, ruling recorded in ADR 0058.** `approval.max_daily_amount` is still deferred and still awaits its own plan. |

## 10. What we looked at (reuse-first §2)

- **The project's own published architecture diagram** (claude.ai/code/artifact/534811bd-7078-424c-b839-7493b2c73b25),
  re-verified line by line rather than trusted. Four of its claims no longer hold and are corrected
  above: the `adset_id` index (§9), the "0.7% systematic gap between campaign and ad totals" (§0 —
  the three levels are exactly equal on 15 days of real data), the rename-breaks-the-binding risk
  (closed by ADR 0055 §4 — the name comparison is against our own tree, never against Meta's
  current name), and `learning_ledger` (§9). Its currency finding **does** hold and is §4.
- **Nothing external found.** The search recorded in ADR 0055 §12 — no open-source project maps a
  generated ad plan onto a platform's live objects — was not repeated; nothing in this decision
  reaches past the boundary that search already covered.
