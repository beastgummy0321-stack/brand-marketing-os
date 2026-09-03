---
id: 0056
decision: A channel's platform facts live in a catalogue file; only per-org state lives in `ad_channel`. The file always wins.
applies-to: [app/schedule/, app/meta/, app/methodology/, supabase/migrations/]
supersedes: none
status: in-force
---

# A channel catalogue is a file, its per-org state is a table

2026-09-03, T4 station ①. Four questions put to the user, four answers signed in one sitting.
This is the Gate A decision ADR 0055 §5 explicitly deferred to T4 ("the picker keeps reading
`platform_objectives.json` until T4 moves it").

## The problem this closes

"Which platforms exist" had two possible homes and no ruling:

- `app/schedule/platform_objectives.json` — three platforms, six Meta objectives, every row
  carrying `source_url` and `verified_date`. Read from four places
  (`state.py:153`, `routes.py:229`, `jobs.py:119`, `jobs.py:185`) and by the frontend picker.
- `ad_channel` — created by T3a, per organisation, rows created lazily, **0 rows today**.

ADR 0055 §5 named the danger ("two sources for which platforms exist would be one too many")
and stopped there. T4 was told to decide. Left undecided one more ticket, `ad_channel` would
have rows and the move would stop being free.

## 1. The line: catalogue vs state

**A platform's rules are a file. An organisation's situation on that platform is a table.**

| question | home |
|---|---|
| Which platforms does this *product* support? What are each one's objectives, level count, minimum daily budget, creative limits? | catalogue file |
| Has *this organisation* switched this channel on? What can its token do? What has it bound? | `ad_channel` and the tables pointing at it |

The catalogue is a file and not a table for a reason the constitution forces: rule 2 admits no
exception to `org_id NOT NULL`, and the `org_id` gate documents exactly two exempt tables which
may not be widened (`app/tests/test_org_isolation_all_tables.py:20`). Putting platform constants
in Postgres therefore means **one copy per organisation**. Meta changes a limit and the fix is a
sync job over every tenant plus a seed for every `supabase db reset` — a platform fact stored as
if it were user data.

The file keeps the `source_url` / `verified_date` convention it already has. That convention is
the reason the file wins: a catalogue row can say where it came from and when it was last
checked, and a per-tenant copy of it cannot.

It is renamed `app/schedule/channel_catalogue.json`. `platform_objectives.json` described the
file's whole content when objectives were all it held; from this ADR it also answers "which
channels exist" and "what can each one do", and a name that describes a third of a file is the
same disease as a document written in the present tense about something that no longer exists.
Four read sites and the frontend picker's comment move with it, all inside `app/schedule/`.

**Consequence, and it is the load-bearing half of this ADR: `ad_channel` loses `label`.**
A label is the platform's name, not the organisation's opinion of it, so it is read from the
catalogue by `channel_key`. The column is dropped in T4 while the table still has 0 rows.
`ad_channel` after T4 is `id` / `org_id` / `channel_key` / `enabled` / `created_at` — nothing
else. Anything a second organisation would answer identically does not belong in it.

## 2. Capability flags are derived from the loop, and they live in the catalogue

ADR 0050 and ADR 0055 both say "five capability flags". **Neither says which five, and nothing
else in the repo ever did** — verified 2026-09-03 by grep across `docs/`, `app/`, `frontend/`
and `.scratch/`. The number was invented in the writing and copied once. It is corrected here:
the flags are **derived from what the system actually does to a channel**, and the count is
whatever that derivation produces, not five.

The loop does four things to a channel — pull performance, create entities, upload creative,
match results back by name — so there are four flags, one per action. They are platform facts,
so by §1 they live in the catalogue.

Meta's values are filled from official documentation with `source_url` and `verified_date`.
**Google and TikTok are left blank, which reads as "not yet verified", never as `false`.** A
blank is honest; a guessed `false` would silently disable a channel nobody ever checked.

**A flag says what the platform permits, never what this product has built.** Meta's API can
create ads; this product does not, and constitution rule 8 says the manual path stays first
class regardless. The two facts have different lifetimes and different evidence — one is a
documentation link, the other is a `grep`. So **no screen may read a flag to decide whether to
show a control**: what we have implemented is code, and a data file that claims otherwise is a
lie with a `verified_date` on it. What the flags are for is the day a second channel is
considered: which of the four actions are even possible there, answered before any code.

## 3. `ad_channel_format_spec` is not built — this amends ADR 0050's table list

ADR 0050 lists the table and writes the rule it was meant to enforce: *"character limits come
from `ad_channel_format_spec`, never from a Python constant."* **That rule is already
satisfied.** `app/creative/format_specs.py` no longer exists; its data moved to
`app/methodology/meta-format-specs.md`, which carries ratios, field counts, character budgets
and per-objective media caps, each section ending in a Meta documentation link and a verified
date. The ADR's target was a Python constant, and there is no longer one.

So the table is not built. Nothing holds a foreign key to it, nothing reads a character limit
programmatically today, and no copy has ever been truncated in production. Building it would add
a per-tenant snapshot of data that already sits, sourced, in a file.

Known ceiling, stated rather than hidden: **nothing enforces the limits.** The methodology file
is a prompt part — the model is shown "title: 27 characters" and is trusted to obey. **The
trigger to revisit is either of: the first time copy is actually truncated in Meta, or the first
channel whose format rules differ from Meta's.** Whoever hits either builds the machine-readable
half then, with a measured failure in hand.

## 4. `channel_credential.account_scope` exists from day one and v1 writes only `*`

`channel_credential` replaces `meta_credential`, whose PRIMARY KEY is `org_id` — one token per
organisation, written into the schema. The replacement is keyed
`unique(org_id, channel_id, account_scope)`.

`account_scope` is the slice of the platform a token covers. **v1 writes the single literal
`'*'`** (org-wide), so behaviour is exactly today's: one token per organisation per channel.
Holding two tokens later is writing a different value into a column that already exists — the
switch constitution rule 3 requires, not the migration it forbids.

**The table belongs to schedule and the code that uses it stays in `app/meta/`, and that seam is
one-way.** The established import direction is schedule → meta (`app/schedule/binding.py:16`,
`period.py:17-18`, `state.py:19`, `tree_approval.py:13`), so `app/meta/` calling
`app/schedule/repository.ensure_meta_channel` would close a package cycle that
`ImportCycleScanTest` records. The meta module therefore carries its own copy of the three-line
lazy insert — container contract §5 permits duplication until the third caller, and this is the
second. The third caller extracts it to a shared accessor; that is the trigger, written down so
the copy is a decision rather than an oversight.

The old table is dropped, not migrated. The project has not shipped; `CLAUDE.md` records every
row as test data, and the previous real Meta binding was already lost to a `supabase db reset`
(0 rows, verified 2026-09-02). A backfill would carry nothing.

## 5. What T4 deliberately does not add

Named here so the next reader does not rediscover them as omissions:

- **`ad_channel.last_data_at`** — already derivable. `meta_ad_account.last_pull_at` exists
  (`20260829000004_meta_daily_spend.sql:11`) and `repository.last_pull_at()` takes the `min`
  across an organisation's accounts, deliberately, so the screen shows the *oldest* data rather
  than the newest. A channel-level column would be a second answer to a question that already
  has one. Add it for the first channel that has no per-account table to derive it from.
- **`ad_channel.data_lag_days`** — for Meta this number *is* the attribution window, and
  `daily_pull.py:57` already states that coupling in writing: the 7 is taken from `graph.py`'s
  `_ATTRIBUTION_WINDOWS` `7d_click`, "不是另外挑一個數字". Copying it into the catalogue would
  break exactly the coupling that comment exists to protect. Add it when a channel appears whose
  data lag is *not* its attribution window.
- **`ad_channel.spec`** — level count and minimum daily budget are platform facts, so by §1 they
  are catalogue fields, not a `jsonb` column on a per-org table.

## Considered and rejected

- **Everything into Postgres, the JSON file retired.** One home, and a future organisation could
  define its own channel. Rejected on the cost in §1: a per-tenant copy of every platform
  constant, a sync job to keep them current, and a seed for every `db reset`.
- **The table as truth with the file as a cache.** Same cost, plus a second writer.
- **Leaving the question to T5 or T6.** By then `ad_channel` has rows and the move needs a
  migration and a backfill. The same debt, on a more expensive day.
- **Naming five capability flags anyway, to match ADR 0050's wording.** The wording had no
  source; matching it would have meant inventing five to fit a number.
