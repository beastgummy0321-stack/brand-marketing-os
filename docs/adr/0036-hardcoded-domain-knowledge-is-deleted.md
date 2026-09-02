---
id: 0036
decision: Delete hardcoded domain knowledge; the agent looks it up in the prompt and the user vets the result.
applies-to: [app/brand_intelligence/, app/dashboard/, app/departments/]
supersedes: none
status: in-force
---

# Hardcoded domain knowledge is deleted; the agent looks it up and the user vets it

Three bodies of domain knowledge are written into this codebase as Python. All three are
deleted. The direction, in the user's words on 2026-08-29: **"abandon hardcoding, embrace the
agent with prompts and a frame. There are hundreds of industries; I cannot write rules for all
of them."**

| Deleted | Lines | What it encoded |
| --- | --- | --- |
| `app/brand_intelligence/compliance_wordlist.py` | 119 | Taiwan food-safety and health-food claim wordlist |
| `app/dashboard/campaign_calendar.py` + `campaign_calendar_data.json` | 224 + 12 rows | A fixed holiday calendar with lead-time tiers |
| `app/core/calendar_dismiss.py`, `app/core/campaign_skip.py` | 151 + 111 | Per-brand overrides for that calendar |
| `frontend/src/components/settings/CalendarSection.tsx` | 162 | Its settings screen |
| `INDUSTRIES` tuple + `brand.industry` column | — | Five industry codes, feeding only the calendar |
| Three test files | 544 | — |

About **1,300 lines and one column**, plus the scattered wiring in `guide_cards.py`,
`dashboard/repository.py`, `routes_brand_settings.py` and `routes_library.py`.

The calendar is the clearest case of the disease. Twelve rows of data were surrounded by more
than a thousand lines of code that decided which of them a brand should care about, and the
answer it could give was only ever as good as a five-value industry enum. A supplement brand
and a fashion brand got the same twelve holidays filtered by the same crude test. What actually
matters to a brand this season is a question with a fresh answer, not a constant.

## What replaces it

Before scheduling, the agent looks up what is coming that is relevant to this brand — the
brand's own confirmed facts describe it far more precisely than an industry code ever did.

Under SaaS this is the **server-side web search tool** (`web_search_20260209`), declared in
`tools` and executed on Anthropic's infrastructure. No crawler, no browser, no proxy, no
per-tenant scraping infrastructure. **$10 per 1,000 searches**, errors not billed; web fetch
(`web_fetch_20260209`) adds no charge beyond the tokens it returns. One scheduling run with
three searches costs roughly US$0.28 on Opus 5, about US$0.12 on Sonnet 5.

Two implementation rules that are not optional:

- **The lookup is not a precondition.** No results, or a failed search, means the run proceeds
  and schedules an ordinary period. Turning a network request into a single point of failure
  for the whole feature is worse than the calendar was.
- **Server-tool errors return HTTP 200, not an exception.** On success the result block's
  `content` is a *list*; on error it is an *object* carrying an `error_code`. Branch on that
  before indexing, or a failed search becomes a crash instead of the graceful path above.

## What this costs — stated once, with numbers

The compliance wordlist covered Food Safety Act §28 (medical-efficacy claims; administrative
fines of NT$600,000 to NT$5,000,000) and the Health Food Control Act §6/§21 (claiming any of
the 13 statutory health benefits without a licence; up to three years' imprisonment and a fine
up to NT$1,000,000). The user sells supplements, so this exposure is concrete rather than
theoretical.

The user's decision, recorded knowingly: **the program is an aid, the user vets what it
produces, and excessive constraints in the prompt interfere with the agent's creative range.**
A brand that wants a specific claim avoided writes it as a brand rule, which reaches every
prompt through `context_compiler`. (This sentence used to cite ADR 0037 for the one-button
version; 0037 was retired by ADR 0046 and the exclusion path is now ADR 0050's `feedback`
table. The brand-rule path itself is unchanged and still live.)

Deleting a check outright is beyond narrowing what a gate applies to, and the global rules
require an explicit written decision for that. This section is that decision.

## Consequences

- **Methodology files lose their legal sections too**, including `app/methodology/ads-health.md`
  in full. The user's ruling was "remove it completely — treat every agent as a blank sheet."
  This includes the Meta advertising-policy material, whose failure mode is different (a
  rejected ad rather than a fine) and which the user chose to delete anyway.
- **The intake wizard's seeded food rule** (`app/intake/script.py:399`) goes with them.
- **`brand.industry` is dropped and the intake wizard asks one question fewer.** Where the
  agent needs to know what a brand does, `brand_fact` says so in plain language.
- **`campaign_calendar_data.json` is not preserved anywhere.** If a fixed calendar is ever
  wanted again it is a department task file, not code.
