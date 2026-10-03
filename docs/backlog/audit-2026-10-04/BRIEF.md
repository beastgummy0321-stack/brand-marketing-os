# Whole-program audit brief (2026-10-03) — read before your cluster

## Why this audit exists
Drills 6–11 each found 40–60 defects through the UI; fixes landed; the next drill found a new batch.
The user ordered one final fix round that ends the loop. A list of 60 more symptoms would just be drill 12
on paper. Your job is different: find the **defect generators** — structural conditions in the code that make
a whole class of symptoms inevitable — so each can be removed once (one shared rule + one machine check that
fails if the pattern comes back).

Read `docs/backlog/handoff-after-drill-11.md` §1 (R1–R7) first. Those are the generators already known, with
file:line evidence. Do **not** re-report them. Do report their **siblings**: other code paths that share the same
generator and would produce the next drill's symptoms.

Project principles that apply (from CLAUDE.md): 程式整理、LLM 判斷 (program sorts/computes, LLM only judges);
multi-platform core (no Meta hierarchy/budget-position/metric hard-coded in shared code); one rule per
business fact; 先根因、後表象.

## Generator classes to hunt (report the class id with every finding)
- **G1 Two implementations of one rule.** The same business fact (readiness, a field's valid range, a claim
  guard, a date window, a budget total, "is this ad closed", "which ads enter learning") computed in two or more
  places with different logic. Evidence = both locations + the input on which they disagree.
- **G2 State collapse.** Distinct real states share one stored value or one displayed sentence
  (not-readable / not-read-yet / read-empty; ended vs closed vs active; waiting-on-you vs processing;
  failed vs partial vs succeeded; unknown vs zero). Evidence = the enum/field + the two states it conflates.
- **G3 Number without basis.** A money/count/rate shown or stored without its period, window, currency, cost
  basis or scale (0–1 vs 0–100), or a label that names a different basis than the computation.
- **G4 Dead end.** A page/state with no forward exit; a disabled control with no reason; a queue/task kind no
  "next" handler knows; a link that leaves the flow with no return target.
- **G5 Long work lives only in the browser.** Background/LLM work whose busy/refused/failed/empty outcome has
  no DB row a read endpoint returns; refusals with no reason code; `max_retries=0` without a user-visible
  outcome; errors written into a success payload.
- **G6 Platform assumption in shared core.** Meta-only hierarchy, budget position, status vocabulary or metric
  names hard-coded outside an adapter (`app/ads/adapters/`, `app/meta/`).
- **G7 LLM output becomes product fact unchecked.** Names, numbers, claims, counts or decisions taken from a
  model reply and stored/shown without a program check against the data they describe.
- **G8 Origin-dependent paths.** Code that works only for imported campaigns (`external_view`) or only for
  system-built ones (`destinations`/handoff), while the screen is open to both.
- **G9 Silent failure.** `except` that swallows, a failure that ends as success, a notification path that
  skips a failure kind, a frontend that drops a returned job id / error.
- **G10 Time.** "today" from the browser clock or `now()` without the org timezone; UTC vs local date math;
  windows anchored to today for ended/closed objects.

## Method (non-negotiable)
1. Read the whole files in your cluster, not excerpts. Trace flows end to end (route → service → repository →
   frontend reader) before deciding a finding is real.
2. For every finding, open both sides and quote the exact lines. No guessing from names. A finding you did not
   verify in code goes under "Unverified" at the end, clearly separated.
3. Prefer findings that explain several symptoms over single oddities. Skip style, naming, and anything the
   user would never see or that cannot change a decision.
4. Note any existing test that covers the rule (path), or "no test".

## Output
Write ONE markdown file at `.harness/scratch/audit-2026-10-03/<cluster>.md` with:

```
# <cluster> audit

## Findings (verified)
| # | Class | Where (file:line, both sides) | What disagrees / collapses | Screens affected | Shared rule should live at | Machine check that would catch recurrence | Existing test |

## Siblings of R1–R7
| Rn | Where | Note |

## Unverified
- ...

## Coverage
Files read fully: ...
Files skimmed/skipped and why: ...
```

Keep each row terse. Chinese or English, your choice; file:line mandatory. Do not edit any product file.
