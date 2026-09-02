---
id: 0053
decision: A campaign period is created on the schedule form, settles only by the user's press, and a settled number never moves.
applies-to: [supabase/migrations/, app/schedule/, app/brand_intelligence/, app/core/interrupts.py, frontend/src/components/schedule/]
supersedes: none
status: in-force
---

# The campaign period is born on the form and settles by hand

2026-09-02, /slice station ① of ticket T2. ADR 0050 named the tables; it left the period's own
life unanswered, and listed seven questions under `docs/issues/t2-campaign-period/UNKNOWN.md`.
All seven were put to the user in one sitting. This file is their answers, so that the ticket
file can die with its board row without taking the decisions with it.

Two of the seven changed a document above the ticket. They are recorded here and the affected
ADRs carry a pointer back: ADR 0036 (the shared calendar, see ADR 0054) and ADR 0050's table
list (`campaign_period.cpa_basis`, deleted below).

## What existed before this ADR, verified 2026-09-02

- **No period object exists anywhere.** `app/schedule` stores plan / tree / creative as
  `llm_task` rows; the only budget input is the rule card `schedule_budget.daily_budget`
  (`app/schedule/routes.py:340`). **No start date and no end date are stored anywhere in the
  flow** — the screen already says 「這期要投放哪些產品」 while holding no notion of when 「這期」 is.
- `campaign_cycle` was dropped (`20260828000003_ads_drop_module_tables.sql`);
  `interrupt.campaign_cycle_id` still points at a table that no longer exists.
- `product_economics` is updated in place (`app/brand_intelligence/repository.py:738`). It
  already carries `effective_from` / `effective_to`, both unused, and the product screen already
  shows an 「生效日」 input (`EconomicsPanel.tsx:29`) that lands on the same overwritten row.
- `product_economics.cpa_roas_basis` is a free-text note (`EconomicsPanel.tsx:124`,
  「計算口徑（選填）」, placeholder 「以月結算，含平台抽成」). It is written and displayed and **read
  by no code and no prompt**.

## The seven decisions

### 1. The period is born when the schedule form is submitted

The existing schedule form gains two fields, start date and end date. Pressing 「出方案」 creates
the `campaign_period` row with `status = 'planning'` first; the plan, the tree and the creative
`llm_task` rows all hang off it through `llm_task.campaign_period_id`.

**One draft per brand.** Pressing 出方案 three times must not leave three periods behind: a brand
has at most one period in `planning`, and a second submission updates that row's dates rather
than inserting another. The period stops being a draft at **tree approval** — the one press in
this system that means 「這期真的要投」 (ADR 0040) — which moves `planning` → `running`. A draft
never approved simply stays a draft; nothing asks the user to settle it.

Rejected: birth at tree approval (the LLM spend before the approval would have no owner, and the
dates would be the system's guess rather than the user's); a separate period-list screen (a
second screen and a second click, and it turns a backend ticket into a backend-plus-screen one).

### 2. The end is automatic, the settlement is not

Past `end_date`, the period moves itself from `running` to `awaiting_data` — a date comparison
on read, not a background job. That state is shown to the user as **「已結束，需人工確認」 with a
red alert marker**, not as a passive 「等資料」; the user's wording, and the reason is that a
period sitting unsettled is an action item, not a status.

`settled` is only ever reached by the user pressing 「結算」, which writes `settled_spend`,
`settled_revenue` and `settled_at`. Rejected: settling automatically on `end_date` (Meta's
conversions arrive late, so the snapshot would be systematically low and it is that snapshot
which answers 「這期賺不賺」); never moving off `running` (ADR 0050 fixes four states, and the
screen could not tell 「還在跑」 from 「早就結束但你還沒結算」).

### 3. Seven days is advice, not a lock

The screen writes 「這期已結束。Meta 的成交回報最長 7 天才補齊，建議 M/D 之後再結算」. The button stays
pressable throughout.

**Where the 7 comes from**: `app/meta/graph.py:222` `_ATTRIBUTION_WINDOWS = ("7d_click",
"1d_view")` — the same constant `app/meta/daily_pull.py:54` already uses to decide how many days
to re-pull. It is Meta's number, so it is read from the same place, never retyped as a
`SETTLEMENT_WAIT_DAYS = 7` of its own. When T4 lands `ad_channel.data_lag_days`, the hint reads
that column instead and this ADR needs no amendment.

Rejected: greying the button out until `end_date + 7` — a period that is visibly a disaster must
be closeable the same day (constitution rule 8, the manual path is first class), and the 7 is
Meta's, wrong the moment a second channel exists.

After settlement, late money still lands in `meta_entity_spend` and `channel_revenue` as usual.
The snapshot does not move. The screen shows the difference — 「結算後又進來 X 元」 — and the user
may press 結算 again, which overwrites the snapshot and writes the previous values to
`audit_log`. Rejected: recomputing the snapshot automatically (constitution rule 7 — that is
answering "what was true then" with a current-state column, and it is the disease already found
in four other places in this codebase); sealing the period so late money is never shown (a large
late order would be invisible for ever).

### 4. Overlapping periods: the shorter one takes the day

`ad_set_period_membership` carries `from_date` / `to_date` and `allocation_weight`, and — per ADR
0050 — **never** a `unique(ad_set_id)`. For a given ad set on a given day:

- exactly one membership covers the day → it takes 100%, which is arithmetically identical to
  today's behaviour;
- more than one → the membership whose period has the **shorter `end_date - start_date`** takes
  100%; the longer periods take 0 for that day;
- equal length → split by `allocation_weight` normalised over that day's covering memberships
  (two rows at the default 1.0 give 50/50).

`allocation_weight` stays as the manual override for any case the rule gets wrong.

**Granularity, and what actually ships first.** Nothing writes `ad_set_period_membership` until
T3 binds ad sets (`channel_entity_map`); until then the table has no writer. So the rule ships
one level up, over the periods' own dates: **a day belongs to the shortest period covering it**,
and a period's spend is the spend on the days it owns. Same rule, same invariant, coarser
subject — and it needs no membership row to be correct while every period's ads are the whole
brand's ads. T3 refines the subject from "the brand's spend that day" to "this ad set's spend
that day"; the rule itself does not change.

This is the machine-checkable form of the user's rule, 「以大檔期為重，常態檔不擋路」: nothing in
the schema says which period is 「大」, and duration is the one signal already present — a 5-day
中秋檔 against a 30-day 常態檔. The invariant that matters is that **the sum over all periods
equals the money actually paid to Meta**; double counting (每期各算全額) breaks 「這個月到底燒了
多少」 permanently, and forbidding overlap contradicts ADR 0050 in writing.

### 5. A product cost change applies from today, never backwards

`product_economics_version` is append-only with a half-open interval `[effective_from,
effective_to)`. Saving on the product screen
closes the current version at today and opens a new one **from today, in the organisation's
timezone** (`app/core/settings.today_for_org`). Periods that already ran keep the version that
was in force on their days.

Consequence, deliberate: the 「生效日」 input on `EconomicsPanel.tsx` is removed, because after
this decision it can only lie. The column keeps its meaning and back-dating later is a screen
change, not a migration.

Rejected: a user-entered effective date (one more box to fill, and a date typed into an
already-settled period produces a snapshot the current arithmetic cannot reproduce).

**Amends ADR 0050 on one clause.** Its `product_economics_version` row specifies "EXCLUDE
constraint against overlap". With back-dating rejected, the only overlap reachable is two open
versions for one product, and that is held by a partial unique index on `(product_id) WHERE
effective_to IS NULL` — no `btree_gist`, which this database does not install today (the only
`CREATE EXTENSION` in `supabase/migrations/` is `plpgsql`, and
`20260829000001_background_baseline.sql:57` already documents that managed Postgres can refuse
one). If back-dating is ever opened, the EXCLUDE constraint comes back with it: that is the
migration this shortcut owes.

### 6. The shared holiday list is not a table — see ADR 0054

ADR 0050 put `holiday` in T2. T2 does not build it. The reasoning, and the amendment to ADR 0036
that the user ordered, are in ADR 0054. What lands in T2 from this question is one deletion:
`campaign_skip` (`20260826000001_core_baseline.sql:130`) is dropped. It has zero Python callers
and its `holiday_id` points at a table that has never existed.

### 7. `cpa_basis` is deleted from both places

`campaign_period.cpa_basis` is **not built**, and `product_economics.cpa_roas_basis` is dropped,
together with its API field (`app/brand_web/routes_products.py:110`, `:471`) and its screen input
(`EconomicsPanel.tsx:124`, `EconomicsTab.tsx:71`). It is a free-text note that no code and no
prompt reads; two copies of it would have been two sources of truth for a value nobody consults.

This amends ADR 0050's `campaign_period` row. Rejected: keeping it on the period and snapshotting
it at creation (correct under constitution rule 7, but rule 7 protects readers, and this field
has none); keeping only the product's copy (a period covers several products — the schedule form
is a multi-select — so one product's note cannot describe the period).

## Consequences

- `interrupt.campaign_cycle_id` becomes `campaign_period_id`, and every `dedupe_key` written for
  a period-scoped warning carries the period id — without it, two overlapping periods silently
  eat each other's warnings through `idx_interrupt_brand_dedupe_key`.
- `llm_task.campaign_period_id` gives LLM spend an owner. Breaking the "newest row is the truth"
  read (`app/schedule/routes.py:133-139`) stays a T5 job.
- The four-state machine is `planning` → `running` → `awaiting_data` → `settled`, plus
  `force_settled_at` / `reason` for a settlement made before the advice date.
