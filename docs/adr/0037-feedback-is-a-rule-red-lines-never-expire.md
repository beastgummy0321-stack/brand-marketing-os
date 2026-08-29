# Feedback is a rule: red lines never expire, preferences do

When the agent proposes something the user does not want, the user says so once and the agent
does not propose it again. That mechanism is not new code — it is a row in the `rule` table,
which `app/llm/context_compiler.py:compile()` already injects into every prompt for that brand.

The feedback button is a shortcut for typing a rule on the settings screen. Under ADR 0034 that
is its entire justification: the user no longer navigates away to write down what just went
wrong.

## Two severities, borrowed from a hospital

| | Red line — casualty | Preference — outpatient |
| --- | --- | --- |
| `rule.severity` | `hard` | `soft` |
| `rule.rule_type` | always `forbidden_word`; **no sub-category** | chosen from a list |
| Content | the word or claim itself | one short sentence |
| Against the 20-rule prompt cap | never squeezed out | may be, and overflow is listed |
| After the expiry window | **never expires** | returns to `pending_reconfirm` |

A casualty department does not triage by specialty — everything goes in. A red line is a red
line whether it is a legal claim, a platform rule or something the founder will not say, so
asking which kind it is buys nothing. An outpatient department does sort by cause, and a
preference is worth sorting because the category tells the agent which part of the output the
complaint is about.

**The dropdown may only ask about consequence, never about content.** "Red line or preference"
has two values and will never have more, because it decides expiry and prompt priority — a
technical question. A dropdown asking *which kind of hazard* — exaggerated efficacy, platform
policy, competitor comparison — would be industry knowledge compiled into the product, and
under ADR 0036 that is exactly what does not go in.

## Preference categories

`RULE_TYPES` in `app/core/vocab.py` already carries `tone`, `visual`, `forbidden_word`,
`asset_usage`, `platform_spec` and `policy`. Those cover the creative module. Four are added
for the scheduling module, whose output the existing list does not describe at all:

| Code | Label | The complaint |
| --- | --- | --- |
| `angle` | 切角 | wrong angle for this period |
| `audience` | 受眾 | aimed at the wrong people |
| `product_pick` | 商品選擇 | should not be pushing this product |
| `budget_split` | 預算分配 | money divided wrongly |

Plus **`other`** on both modules. Without an escape hatch a user with a real complaint forces
it into the nearest wrong category, and a mis-prefixed rule is worse than an unlabelled one.

Timing and pacing is deliberately **not** a category: it has not hurt yet, and most of it is
absorbed by `angle`. Adding it later edits a list.

## The mechanism already exists — and ADR 0012 was wrongly retired

ADR 0012 specified both halves of this and both are live:

- `app/brand_intelligence/rule_lifecycle.py` (99 lines) flips rules that have gone unconfirmed
  past the threshold to `pending_reconfirm` — out of the prompt, not deleted, restored by one
  click on the accumulated-knowledge screen without retyping.
- `context_compiler._select_rules_for_prompt` enforces the 20-rule cap, **keeps every `hard`
  rule**, orders `soft` rules newest-first, and exposes what did not fit via
  `list_overflow_rules()` rather than dropping it silently.

**ADR 0030 marked ADR 0012 as "retired — the code it governed was deleted." That is wrong.**
None of it was deleted; `rule_lifecycle.py`, both rule cards and the cap in `context_compiler`
are all in use. The status line is corrected as part of this decision. Anyone acting on the
retirement would have deleted the mechanism this ADR depends on.

Two changes to what exists:

1. **`sweep_expired_rules()` stops sweeping `hard` rules.** One condition in the `WHERE`
   clause. Legal and brand red lines do not stop being true because three months passed.
2. **The threshold's unit changes from cycles to days, default 90.** It is currently
   `reconfirm_cycles` (default 6) multiplied by a local `CYCLE_DAYS_APPROX = 14` whose comment
   cites `app/ads/budget.py` — a file that no longer exists. A number whose named source has
   been deleted is a number with no source, which the global rules forbid.

This answers the question the user raised directly: a preference recorded because the founder
disliked something that customers in fact respond to **expires on its own after 90 days**
unless renewed. No detection, no learning ledger, no performance attribution. Time does it.

## The form

One entry is one line. The user presses **+** to add another: a visual complaint and a tone
complaint are two entries, not one paragraph; two forbidden claims are two red lines.

Each entry is a severity dropdown, a category dropdown when the severity is `soft`, and a free
text field capped at **100 characters** with the hint *"one sentence — the system holds 20
rules, and a long one crowds out the others."* The limit is stated as the user's own interest,
because it is.

**Rejecting a whole set requires at least one entry first.** Re-running with identical input
produces near-identical output, and a user who sees that concludes the system is broken. The
forced entry is also what makes the loop improve rather than repeat.

Three gates keep this from growing without bound, and all three already exist: the 100
characters, the 20-rule cap with its honest overflow list, and the 90-day expiry. Nothing needs
adding.

## Consequences

- **No new table and no new column.** `severity`, `rule_type`, `content`, `product_id` and
  `status` are all present; `rule_type` is free-form text, so the four new categories are list
  entries, not a migration.
- **A rejection's feedback applies to its own re-run.** The rules are active before the re-run
  composes its prompt, so the loop closes with no extra plumbing.
- **The earlier distinction between one-shot rejection reasons and permanent rules is dropped.**
  It existed to stop the agent being narrowed a slice at a time by passing moods; the 90-day
  expiry and the cap already do that, and two paths where one works is the thing this repo
  keeps deleting.
