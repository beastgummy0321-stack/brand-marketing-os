---
id: 0058
decision: A stored UTC timestamp becomes a date in the org's timezone before any money comparison against `today_for_org()`.
applies-to: [app/core/settings.py, app/schedule/tree_approval.py]
supersedes: none
status: in-force
---

# A stored UTC timestamp becomes a date in the organisation's timezone

2026-09-04, ticket M1. Money path: the user approved the plan before any code was written
(BOARD.md level 1, item 1). ADR 0040 owns the money brake itself; this ADR owns only the
question of *which calendar* the brake counts days on.

## The problem this closes

`_approval_overspend()` (`app/schedule/tree_approval.py:60-92`) subtracts two dates that are
measured on two different calendars:

| value | calendar | source |
|---|---|---|
| `approval_date` | **UTC** | `approval_row["approved_at"].date()` — column is `timestamptz`, psycopg hands it back in UTC |
| `today` | **the organisation's timezone** | `coresettings.today_for_org()` (票 04-1b) |

For eight hours of every day — Taipei 00:00–08:00, when UTC is still on the previous date —
the two disagree by one day and `days_elapsed = (today - window_start).days + 1` counts one
day too many.

`expected_to_date = approved_amount × days_elapsed`, so an inflated `days_elapsed` inflates
"you should have spent this much by now", which makes real spending look **less** overspent
than it is. ADR 0040 is a brake; a brake that errs is allowed to err towards stopping, never
towards letting go.

**Measured, not reasoned.** `app/tests/test_approval.py::ApprovalApiContractTest` asserts
`days_elapsed == 1` on the approval's own day. Run at 2026-09-04 01:22 Taipei (2026-09-03
17:22 UTC): `1 failed, 2 passed`. The same file was green on every daytime run, including
every CI run — a test that is only red for a third of the day is a test that reports the
bug to nobody.

## The ruling

**`today_for_org()` is not the only place the organisation's calendar is needed.** Any stored
UTC instant that is about to be compared against it is first moved onto that same calendar.

Concretely, `app/core/settings.py` grows one function beside `today_for_org()`:

```python
def org_timezone(conn, *, org_id: str) -> ZoneInfo   # the org's tzinfo, same fallback rules
def today_for_org(conn, *, org_id: str) -> date      # == datetime.now(org_timezone(...)).date()
```

`today_for_org()` is re-expressed in terms of `org_timezone()` and its observable behaviour
does not change — including the two fallbacks its docstring promises (a malformed IANA name
logs a warning and falls back to `Asia/Taipei`; a missing IANA database is allowed to raise,
because silently falling back to UTC is exactly the bug this ADR closes).

`_approval_overspend()` then reads:

```python
approval_date = approved_at.astimezone(org_timezone(conn, org_id=org_id)).date()
```

## Why a shared helper and not one `astimezone()` at the call site

Because the call site is not the only one. `app/orders/repository.py:55, 344, 426` also turn
stored timestamps into dates and compare or render them, and `app/brand_web/routes.py:61`,
`app/intake/repository.py:374` and `app/main.py:115` mint dates from `datetime.now(UTC)`.
**None of those is on the money path and none is in this ticket's scope** — but a private
`_to_org_date()` inside `tree_approval.py` would guarantee the next one is written wrong too.
One named function in `app/core/settings.py`, next to the function it is the sibling of, is
where a future reader looks.

## What was considered and rejected

- **Store `approved_at` as a date in the org's timezone.** Rejected: `approved_at` is an audit
  timestamp of an event, and 票 04-1b already ruled those stay UTC
  (`app/core/settings.py:282-283`). Changing the column would also be a migration on the money
  path for a display concern.
- **Make the test deterministic and leave the code.** Rejected: certifying current behaviour is
  forbidden by the global rules, and the behaviour is wrong in the direction that loses money.
- **Fix every `.date()` site in the repo in this ticket.** Rejected: the four route C classes
  do not cover orders rendering, and a money ticket that also rewrites three unrelated modules
  is a diff nobody can review against a done-check. Recorded here so the next reader of those
  lines has the ruling to apply.

## How this can be seen red again

Set the machine clock (or the org's `org_timezone` setting) so the organisation's date is
ahead of UTC's, approve a tree, and read `days_elapsed`. Before the fix it is 2 on the day of
approval; after, it is 1. `app/tests/test_approval.py` carries a clock-independent version of
this so it no longer depends on what time of day the gate runs.
