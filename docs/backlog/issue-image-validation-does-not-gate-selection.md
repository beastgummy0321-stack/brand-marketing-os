# Failed image checks do not stop a version from being selected; prose drift is unchecked

Status: not planned. Found reviewing F07 (2026-09-15).

- A round re-asks failing items once, then writes every row with its ❌ lines
  (`app/workbench/jobs.py:572-583, 602-604`); selecting a version ignores validation
  (`app/workbench/repository.py:341-347`).
- Checks cover structure and the 「」 strings (length, jargon leaks, fact numbers), not whether the
  prompt prose still matches the set's audience, offer or proof (`app/workbench/validate.py:274-292`).
- Today the user has to avoid ❌ cards by eye.
- Revisit: block or warn when selecting a version with ❌; decide whether a model-free prose check
  against the set's coordinates is worth it.
