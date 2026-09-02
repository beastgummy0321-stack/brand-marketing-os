---
id: 0054
decision: The shared commerce calendar is a department data file read into the prompt, never a table and never filtering code.
applies-to: [app/departments/ads/, supabase/migrations/]
supersedes: none
status: in-force
---

# The shared commerce calendar comes back, as prompt data and nothing else

2026-09-02, /slice station ① of ticket T2, question 6. ADR 0050 listed a `holiday` table under
T2. Building it collides with **ADR 0036**, which four days earlier deleted a fixed holiday
calendar. This file records the user's ruling, and ADR 0036 carries a pointer to it.

## The user's ruling, in their words

> 「ADR 0036 我認為需要修改，產業有幾百種但重要節慶每個品牌非過不可，若產業特殊，我認為可以在
> 建檔部分或是品牌智庫裡面補即可。」

It survives scrutiny, and it does not reopen what ADR 0036 closed. What 0036 deleted was
**1,300 lines of code that filtered twelve rows of data through a five-value industry enum** —
its own words: "twelve rows of data were surrounded by more than a thousand lines of code that
decided which of them a brand should care about". The disease was the filter, not the twelve
rows. 雙11, 618, 黑五, 母親節, 年終慶 need no filtering: every brand that sells anything is in
them. ADR 0036 itself left this exact door open — "if a fixed calendar is ever wanted again it is
a **department task file, not code**."

## The decision

1. A section of shared commerce dates is written into the ads department task file
   (`app/departments/ads/`), the same file the shell already pastes into the prompt verbatim
   without parsing it (ADR 0028). Dates plus the usual lead-in weeks; no code reads it, no
   column stores it, no screen edits it.
2. **No `holiday` table**, in T2 or later, until something other than a prompt needs to query
   one. Adding a table later is a new migration on empty ground, not a rewrite — no door closes
   here.
3. Brand-specific occasions (a pet brand's own week) stay where brand facts already live:
   the intake wizard and brand intelligence. That path exists and needs no work.
4. `campaign_skip`, which references a `holiday_id` that has never had a table and has zero
   Python callers, is dropped in T2.

## Why a file and not a table — the hard reason

Constitution rule 2 and `app/tests/test_org_isolation_all_tables.py`: **every table carries a
NOT NULL `org_id` with an FK**. A calendar shared by all tenants has no `org_id`. A `holiday`
table therefore has exactly two shapes, and both are worse than a file: a named exemption from
the tenant-isolation ratchet, or a copy of the same twenty rows seeded into every organisation,
drifting apart from the day the second organisation signs up.

## What this costs, stated once

The lunar dates (春節, 端午, 中秋) move every year, as do Taiwan's make-up working days. The
file is one line per occasion and someone edits it once a year. The fixed-rule dates (雙11, 618,
黑五, 母親節) do not move. Nothing in the system fails if the file goes stale — the period's own
start and end dates come from the user, and a stale calendar costs a less-well-timed suggestion,
not a wrong number.
