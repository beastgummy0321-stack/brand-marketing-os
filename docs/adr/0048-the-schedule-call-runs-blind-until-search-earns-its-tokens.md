---
id: 0048
decision: schedule_plan runs with no web search; the mechanism stays, the call site is off until search returns visible sources and stops dumping whole pages into the prompt.
applies-to: [app/schedule/jobs.py, app/departments/ads/schedule.md]
supersedes: none
status: in-force
---

# The schedule call runs blind until search earns its tokens

2026-09-01. ADR 0005 enabled web search as an opt-in `tools` argument, off by default,
**decided per call site**. The two call sites it named (`app/ads/plan.py`,
`app/ads/creative.py`) were deleted with `app/ads/` (ADR 0030). `app/schedule/jobs.py`
`schedule_plan()` later switched search on without a written decision. This is that decision,
and it is: **off**.

## What the meter says

Three `llm_task` rows, same brand, same day (2026-09-01), same shell:

| task | input tokens | searches | `search_sources` |
| --- | --- | --- | --- |
| `schedule_plan` (`llm_01M1DVZMJSCP7ZK44Q2HP7S1ES`) | **159,444** | 2 | 0 |
| `schedule_tree` (`llm_01M1DW3R962V6APB679Y2DRFB5`) | 29,057 | 0 | 0 |
| `schedule_creative` (`llm_01M1DW6CPDDGY1S5WJ37H6EGMG`) | 30,117 | 0 | 0 |

The shell's own prompt is ~30k. Two searches added **~130,000 input tokens** — the documented
cost of `web_search_20250305`, which has no dynamic filtering and puts whole results into the
prompt (`app/llm/providers.py`, the comment above `WEB_SEARCH_TOOL`).

The recorded cost was $0.02, all of it the per-search fee, because the `codex_cli` route bills
zero per token (`app/llm/pricing.py`). That zero is a property of the route, not of the feature.
On the Anthropic route the same call carries 130k extra input tokens: **~$0.65 at Opus rates,
~$0.39 at Sonnet — thirty times the search fee itself.**

## What the user got for it: nothing visible

`AnthropicProvider.complete()` parses `web_search_tool_result` blocks into `search_sources`;
the `codex_cli` branch returns `search_sources=[]` unconditionally. `app/schedule/plan.py`
reads that field and `SchedulePage.tsx` renders `SourceList` from it, so on the current
provider **the source list never appears**. The row above confirms it: two searches, zero
sources. The user pays 130k tokens for a claim they cannot check.

The same branch sends only `-c tools.web_search=true`. `max_uses: 3` and
`user_location.country: TW` — both required by ADR 0005 — are never transmitted.

## The prompt changes with the code

`app/departments/ads/schedule.md` told the model to use "你手上的網路搜尋工具". A model told to
search with no tool attached does not report the absence; it writes a remembered holiday into
`reasoning` and it reads exactly like a real finding. So that section is replaced by an explicit
"you have no network, do not write dates from memory", and the `reasoning` bullet no longer asks
whether 時事 was used. **Leaving the instruction would have been worse than leaving the search on.**

## Turning it back on

`search_sources` plumbing (`plan.py`, `SourceList`) stays. Re-enabling is one argument at
`app/schedule/jobs.py` — no schema change, no migration. Both of these must be true first:

1. The active provider fills `search_sources`, so the sources reach the screen.
2. Results stop entering the prompt whole — either `web_search_20260209` (dynamic filtering)
   once the model menu drops pre-4.6 models, or a separate cheap call that searches and returns
   a short summary the schedule prompt consumes.

## Consequences

- Schedule plans no longer reference current events. That capability is deferred, not rejected.
- `schedule_plan` input tokens return to the ~30k of its sibling calls.
- ADR 0005's mechanism (`tools` on `complete()`, `WEB_SEARCH_TOOL`, its tests, per-search
  pricing) is untouched and has zero live call sites.
