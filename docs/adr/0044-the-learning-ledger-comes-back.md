# The learning ledger comes back, because this time something writes to it

Ticket S0b, 2026-08-30. **This overturns a user ruling recorded earlier the same day.** Ticket 04
of the dead-code sweep found `learning_ledger` and `strategy_hypothesis` queried on every prompt
with no production writer left — two sections permanently empty that could never fill again — and
the user ruled **"Ruling: delete both sides."**
(`.scratch/dead-code-sweep/issues/04-rules-stop-expiring-and-two-tables-go-offline.md:53`). That
ticket's Ceiling named the obvious replacement and refused it: *"Do not build a replacement
「新增一條學習」 input — the user was offered that and chose deletion."* (`:82-83`).

**The observation half comes back. `learning_ledger` is written again — by a reading agent and a
human tick, never by a hand-entry form — and read back into the planner's prompt.** The user
re-ruled on 2026-08-30 (`.scratch/adloop/GRILL.md:188`, `.scratch/adloop/SPEC.md:285-290`).

## What the ruling actually deleted: Python, not data

The table was never touched. `learning_ledger` stands at
`supabase/migrations/20260826000002_brand_intelligence_baseline.sql:267` with every column this
pass needs already in it — `applicability_scope`, `sample_size`, `confidence`,
`needs_revalidation`, `expired`, `source_track` (`:268-285`) — three indexes (`:287-289`), and RLS
enabled (`supabase/migrations/20260828000001_core_rls.sql:52`). No policy follows it, and that is
the intended state rather than a gap: that file's own header says why — *"Backend connects as
postgres (bypasses RLS); this closes anon/authenticated access via PostgREST"* (`:2`). No later
migration changes a column or drops it; the ads-module drop explicitly excludes it as
brand-permanent (`supabase/migrations/20260828000003_ads_drop_module_tables.sql:17-18`), and
ticket 04's Ceiling parked the DROP as route C, "boarded separately".

What went was the code around it. From `app/brand_intelligence/repository.py`:
`create_learning_ledger_entry`, `list_learning_ledger`, `list_learnings_for_prompt`,
`deactivate_learning_ledger_entry`, `mark_learning_ledger_needs_revalidation`, plus
`unlink_learning_ledger_reading` and `unlink_learning_ledger_cycle` in the same ruling. All of
`app/brand_intelligence/repository_learning_text.py` went with them, and so did the
【已驗證的學習】 prompt section, whose removal is recorded at `app/llm/context_compiler.py:17-21`.

## The premise that moved

The deletion was right the day it was made. Nothing wrote to the table, so the reader could only
ever return an empty set: keeping it meant maintaining code that could never run, under a prompt
heading that could never have anything beneath it. The premise was *no writer exists*, and it was
true.

This pass supplies one. The onboarding read points reading agents at 91 continuous days of the
user's own real account across 35 ads (`.scratch/adloop/SPEC.md:312-313`); the end-of-period
review produces the same shape from a period this system ran itself. Neither writes the ledger by
itself — each produces conclusions a human then ticks, and the tick is the write. Both write
through `app.brand_intelligence.repository`; `app/schedule` and `app/meta` never write another
module's table directly, and `app/tests/test_architecture_boundaries.py` already gates that.

That is the entire difference.

## ADR 0026's mechanism does not come back

Three pieces of ADR 0026 stay dead: exposing the longest raw `learning_text` in a converged group
(`docs/adr/0026-one-learning-is-one-conclusion-in-one-scope.md:58-63`), substring-matching angle
names inside that text to decide which cells were winners, and computing the sample size as the
summed conversions of only the cells a sentence named (`:69-77`). All three are judgement compiled
into Python — the user's own diagnosis of why the previous module died, and the thing ADR 0030
retired twelve ADRs at once to be rid of. ADR 0030 states the cure as relocation, not deletion:
*"Their subject matter is not gone — it moves out of Python and into `rules.md` and the ad
department's task files"* (`docs/adr/0030-ads-era-decisions-retire-with-the-module.md:28-29`).

So convergence is not computed at all. It is replaced by one sentence in the prompt section, whose
content this ADR fixes and whose Chinese wording lands with the section itself: *these are
observations with confidence and sample size; the same conclusion may appear more than once, and
that means it was observed more than once.* Zero code: no dedupe, no merge, no winner detection,
no scoring.

ADR 0026 and ADR 0016 keep their `Status: retired by ADR 0030` lines
(`docs/adr/0026-one-learning-is-one-conclusion-in-one-scope.md:3`,
`docs/adr/0016-qa-checklist-self-report-reminder-not-gate.md:3`), and this ADR resurrects neither.
0026's code is genuinely gone: the winner-detection and sample-sum half went with `app/ads/`, and
the convergence half — `_LEARNING_ASIDE_RE` and `collapse_learnings()` in
`repository_learning_text.py` — went with ticket 04 itself, the very ruling overturned here. What
is overturned is the 2026-08-30 ruling about the table, not the 2026-08-25 decision about the
algorithm.

## Orders go to `rule`; observations go to `learning_ledger`

`rule` holds the things the user said once — ADR 0037 made it exactly that — and it has no
`confidence` column and no `sample_size` column
(`supabase/migrations/20260826000002_brand_intelligence_baseline.sql:141-153`). Nothing in a rule
row says how sure anyone is, because a person said it and that is the whole warrant. An
observation is the other thing: "commuters convert better" may be five rainy days, so it carries a
confidence and a sample size, and next period may overturn it. Those two columns are why an
observation belongs in the ledger rather than flattened into a rule, and the direction this ADR
does not touch is the other one: no ledger row, however confident, edits or overturns a rule the
user wrote.

## The writer is a reading agent plus a tick

A conclusion is not a ledger row when it is generated. The review's output is already an `llm_task`
row — that row is the record for every generation the shell makes
(`docs/adr/0032-the-agent-cli-is-a-provider-and-it-returns-text.md:34`) — and an unaccepted
conclusion stays there and is read from there. **Accepting is the only thing that writes a
`learning_ledger` row**, and the table gains no "pending" state, which would put an approval
workflow into a table meant for settled observations. What the tick looks like on screen is
settled in the spec and owned by the onboarding-read slice (`.scratch/adloop/SPEC.md:506-524`),
not here.

## What we looked at

The plan review's alternative, recorded so it is not re-proposed next month: the user reads Ads
Manager and types one conclusion into a rule card. Zero code, zero migration, and constitution
rule 6 makes the manual path first-class. **It is true today** — the card exists, the prompt
already reads it, and a person doing this by hand closes the loop this afternoon. It was rejected
because the user ruled against it twice in the 2026-08-30 session, asking for the opposite:
「我需要的就是一個可以媲美行銷公司在幫品牌做網路投放的完整流程」
(`.scratch/adloop/SPEC.md:352-357`).

Be precise about the scope of that rejection. It rejects **hand-written conclusions** — routing
the user to a minimum they type themselves. It does not reject hand-*run* analysis and does not
demote the manual path, which stays first-class under rule 6. The strongest evidence this design
works is itself hand-run: on 2026-08-30, before any of it was built, the four-segment prompt was
assembled by hand (92,858 characters, one call through the local codex CLI) and returned four
conclusions whose cited spend and cost-per-visit figures all recompute exactly from the raw CSV.
One number is wrong — a `view_content` count, 344 against an actual 342, a 0.6% slip in a sum of
eight daily values — and it changes no conclusion (`.scratch/adloop/SPEC.md:425-429`).

## What this does not authorise

- **No migration, no new column, no sweep.** The table is used as it stands; accept state is not
  stored on it, and `expired` and `needs_revalidation` are columns, not a schedule.
- **No 「新增一條學習」 hand-entry form.** That half of ticket 04's Ceiling survives intact: the
  user was offered a manual entry input and chose deletion. The writer is a reading agent plus a
  tick, never a form.
- **`strategy_hypothesis` stays on the deleted side.** Ticket 04 deleted both; only the
  `learning_ledger` half is overturned. 【尚未驗證的猜想】 does not return, and no 待確認 screen
  is authorised.
- **No direct SQL, on either side.** Writers go through `app.brand_intelligence.repository`, and
  so does the reader: `app/llm/context_compiler.py` calls a repository function and never touches
  the table — that is the A3 fix recorded at `app/tests/test_architecture_boundaries.py:11-12`,
  with `learning_ledger` listed in `BRAND_PERMANENT_TABLES` at `:47-51`. That gate stays as it is.
- **No values named here.** `source_track` has no production writer today and its column default
  is `'ads'` (`...brand_intelligence_baseline.sql:285`); which value marks an imported row against
  an earned one is the onboarding-read ticket's to state.

## Consequences

- The loop closes. Without the reader in the planner's prompt there is a report, not a loop; the
  【已驗證的學習】 section returning to `app/llm/context_compiler.py` is the interface that closes
  it.
- The onboarding read and the end-of-period review own the writer and are unblocked. The
  onboarding read is the earlier of the two, so the writer stops being a promise before any period
  has completed.
- Tenant cleanup needs nothing new: both delete cascades already name the table
  (`app/brand_intelligence/repository.py:213` and `:363`), and the raw `INSERT` those tests use
  because no writer existed (`app/tests/test_brand_delete.py:61-67`) can go back through the
  repository once one does.
- A ledger filling with noise is the real cost, and the accept tick is the only brake on it. If it
  fills with noise anyway, the thing to revisit is the accept step, not the table.
- The overturned ruling survives here, quoted. `.scratch/` is disposable by CLAUDE.md's 資料狀態
  section, so this file — not that ticket — is its record.
