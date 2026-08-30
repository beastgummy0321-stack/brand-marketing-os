# The test gate counts lines, not a ratio

A gate whose only way to pass is to loosen itself is not a gate.

`TestRatioTest` froze `tests / production` at 0.858 on 2026-08-29 and said 只准往下. On
2026-08-30 it was raised twice in one day — 0.858 → 0.862 → 0.865 — and neither raise was caused
by anyone writing a test. Both were caused by **deleting dead production code**: ticket 04 removed
697 production lines against 322 test lines, ticket 05 removed 191 against 131. The denominator
shrank, so the ratio climbed, so the gate went red, so the number was moved.

That is the gate punishing the work this repo most wants done. The dead-code sweep that day
deleted eleven things that were provably unreachable — and each deletion pushed the project
closer to a red gate whose only remedy was to edit the gate. By the end there was 0.001 of
headroom and the next ticket to add a single test line would have gone red for a reason unrelated
to that ticket.

## The decision (user, 2026-08-30)

**The gate counts absolute test lines.** `TEST_LINES_CEILING`, frozen at the measured value, may
only go down — unless it is raised in that same line with a written reason a reviewer sees in the
diff. That is the mechanism `KNOWN_MODULE_SIZES` two blocks below has always used, and its comment
already states the principle: 「允許調高，但必須改這張表——重點不是禁止成長，是讓成長出現在
diff 裡有人看得到」.

Now the cause and the alarm line up:

- Deleting production code does not move test lines, so it cannot turn the gate red. Proven by
  measurement before this ADR was written: removing 37 production lines moved the ratio 0.866 →
  0.868 while the gate stayed green.
- Adding test lines turns it red. Proven the same way: adding 30 lines to a test file turns it
  red immediately.

The ratio has not been thrown away. It is computed and printed in the failure message, and the
0.7 target in `docs/workflow-diet.md` still stands. It is a north star, not a brake.

## What this does not license

This is not a widened tolerance. The global rule — never widen a tolerance list to turn a gate
red→green — stands, and it is exactly what the two raises on 2026-08-30 ran into. What changed
here is **what the gate applies to**, which that rule names as a different act requiring an
explicit written decision. This ADR is that decision.

Raising `TEST_LINES_CEILING` because a ticket genuinely needs a test remains a visible, reasoned
edit on that line. Raising it to make a red gate green without saying why is the thing that was
forbidden before and is still forbidden.

## What we looked at

Nothing external. The mechanism was copied from `KNOWN_MODULE_SIZES` in the same file, which has
worked for the thing this gate was failing at: making growth visible in the diff without making
shrinkage expensive.

## Consequences

- The frozen number moves with the repo's own measurements, and every move carries its reason in
  the line above it.
- A large new feature that genuinely needs tests raises the ceiling once, deliberately. A deletion
  sweep raises nothing.
- The number includes this file and `test_architecture_boundaries.py` itself, so rewriting the
  gate costs against the gate. The five lines this rewrite cost are recorded in that file's
  comment rather than hidden.
