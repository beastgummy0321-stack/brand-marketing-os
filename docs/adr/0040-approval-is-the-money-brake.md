---
id: 0040
decision: Approval is the money brake: it is recorded in its own table at the gate, not yet wired to any spending.
applies-to: [app/core/approval.py, app/schedule/routes.py]
supersedes: none
status: in-force
---

# Approval is the money brake, recorded now, not connected to a wheel yet

Ticket: `.scratch/approval-slice/issues/01-approval-is-the-money-brake.md`. New table
`approval`, new module `app/core/approval.py`, two endpoints on `app/schedule/routes.py`.

## 核准 is one of exactly four user gates

`docs/adr/0018-agency-model.md` §1 fixes the ceiling: at most four places a user must act
—開戶訪談／提案書核可／上線授權／週提案核可——and a gate survives only if it answers either
「這是平台限制」or「這是花錢煞車」. 核准 (approval) is the money-brake one. `CONTEXT.md:214`
lists it as one of exactly three business words the shell itself is allowed to know
(檔期／核准／預算上限). This ticket is the first place that word gets a table.

## The brake is not connected to a wheel yet, and that is said out loud on screen

`app/meta/graph.py` is read-only today (`list_ad_accounts`, `list_campaigns`,
`list_campaign_insights`, no POST anywhere). Nothing in this system can spend money by
itself, so approving a tree cannot actually gate a publish — there is no publish path to
gate. The screen says 「已核准」, never 「已解鎖」or 「可以投放了」, and carries a line
saying publishing is still done by hand in the platform's own interface. Faking a lock
that isn't real would be worse than admitting the brake has no wheel yet.

## Why build the table now anyway

The user ruled on 2026-08-30: **the system will eventually publish ads itself, on every
platform, not only Meta.** That makes the approval record a money-path data model
decision, not a UI decision — and `workflow.md` requires irreversible data-model decisions
to be settled before coding, not deferred with "refactor later" once a second platform
shows up. So the record's shape has to be platform-neutral from the first row, even while
the only thing reading it today is a comparison screen.

This was contested once. The plan reviewer's verdict on the first draft was `do_not_build`,
proposing instead "ship only the overspend line, no table, route B." That alternative was
put to the user, who ruled against it on 2026-08-30 for the reason above. This ADR is the
record of that ruling, so it is not re-proposed cold next month.

## The shape: platform-neutral by construction

`scope_type` + `scope_ref` + `approved_by`/`approved_at` + `note`, reused deliberately from
the deleted `activation_authorization` table
(`supabase/migrations/20260826000004_ads_baseline.sql:322`, dropped with `app/ads/`), which
already had the right platform-neutral shape for "a human signed off on something scoped by
type+ref." What it lacked, and what this ticket adds:

- **`approved_amount`** — without a signed number, an executor could never know what it may
  spend. Computed server-side from the tree's `daily_amount` sum at approval time; never
  accepted from the request body (a client-supplied money figure is a tamper path).
- **`content_hash`** — without it, a re-expanded tree could silently inherit an old
  signature. A SHA-256 digest of the tree body the user actually saw (`levels`/
  `budget_level`/`nodes`, with the fields the shell layers on afterward —
  `bound_external_id`/`spend`/`roas`/`task_id`/`created_at`/`failure`/`running`/
  `bind_failure`/`narrative` — stripped out first, so binding a campaign or spend arriving
  cannot invalidate a signature that never changed).
- **Revocation** (`revoked_by`/`revoked_at`, row kept) — a brake that cannot be released is
  worse than none. Re-approving never rewrites a row; it inserts a new one.

**No platform column, ever.** Which platform a tree's spend goes to is already frozen in
that tree's own `context_scope_json.platform`. Adding a platform column here would be
adding data, not columns (ADR 0035's principle) — and would leak a platform name into a
core-module table that's supposed to survive every platform this system ever writes to.

## `scope_ref` answers "which one did I sign", `content_hash` answers "is it still that one"

These are two different questions and they were briefly collapsed into one, so the reasoning is
recorded here rather than left to be rediscovered.

Implementing `scope_ref` literally as the ticket's draft SQL sketch described it — the approved
tree's `llm_task` id — and then *looking approvals up by it* breaks the feature. Re-expanding a
tree always creates a brand-new `llm_task` row with a new id, so a lookup pinned to the current
tree's id finds nothing after every re-expansion. `approval` would go straight to `null`, the
screen would read "never approved" instead of "approved, but the tree has changed", and
`content_hash` would never get the chance to fire.

The first implementation solved that by storing `brand_id` in `scope_ref`. That works, and it was
shipped and reviewed that way, but it pays for the fix with the column's only job: with `brand_id`
in it, `scope_ref` carries nothing the neighbouring `brand_id` column does not, and the question
"which tree did I sign on the 30th" can then only be answered by hashing every tree until one
matches. For a money-path record whose whole justification is that a future executor and a future
audit will read it, that is the wrong half to give up.

So the lookup moved instead of the stored value. `app/core/approval.py:latest()` filters on
`org_id + brand_id + scope_type` and takes the newest non-revoked row; `content_hash` decides
whether that row still describes the tree on screen. `scope_ref` keeps the approved tree's
`llm_task` id and stays a real answer to a real question.

The consequence, stated plainly: `latest()` assumes one live subject per brand per `scope_type`.
That is true today (there is exactly one live schedule tree per brand, and `_latest_task_row`
already treats it that way). The day a second concurrent subject of the same type exists, this
lookup needs a subject key — and `scope_ref` will already be holding the right value for it.

## What we looked at

An external "approval workflow" library was not evaluated. This is a nine-column table with
three functions (`approve`/`latest`/`revoke`) behind a single caller — a framework buys
nothing here that eighty lines of native SQL does not already have, and rule 8 (fewest
dependencies, no unbuilt queues/pools/frameworks) rules it out on size alone. The in-repo
prior art (`activation_authorization`, `app/core/interrupts.py`'s tenant-boundary handling
in `resolve()`) was reused instead.

## Ceiling

No executor, no platform write path, no per-platform code of any kind. No multi-approver,
no roles, no approval levels, no amount tiers — there is one user. No approval of anything
other than a schedule tree; a second `scope_type` is added when a second caller genuinely
exists. No threshold on the overspend comparison — the screen shows both numbers and their
difference and lets the user judge; a threshold would be a guessed number, and this repo
forbids guessed numbers in code.

## Consequences

- **`app/core/approval.py` gains a table and stays platform-agnostic.** It never imports
  `app/schedule` and never learns what a "tree" looks like — hashing and amount math are
  `app/schedule/routes.py`'s business knowledge, passed in as plain arguments.
- **The screen tells the truth about what core does not exist yet.** No unlock language,
  a visible line that publishing is still manual.
- **When a platform write path is built, this table does not move.** The executor becomes
  a second caller that checks `latest()` before it spends and calls `revoke()`/`approve()`
  the same way `app/schedule/routes.py` does today — no migration, no reshaping.
