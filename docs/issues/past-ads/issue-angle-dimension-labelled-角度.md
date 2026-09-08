# The angle dimension is labelled 「角度」 on screen and in prompt text; the glossary says 「切角」

Status: open (seen on the history screen at walk round 2, 2026-09-08; pre-existing, not introduced by past-ads).

Cause: `frontend/src/lib/coordinatesApi.ts:12` `COORDINATE_DIMENSIONS` maps `angle` → 「角度」, and
`app/schedule/diagnosis.py` `DIMENSION_LABELS["angle"]` is 「角度」 too. `CONTEXT.md` 「廣告素材」 names
**切角** as the canonical word and lists 角度 under _Avoid_. Every screen that renders the seven dimensions
(coordinate library tab, creative performance table, the new history cards) and every prompt section
built from `DIMENSION_LABELS` shows the avoided word. Ticket past-ads/05 wrote 切角 as a literal in the
【投放史】 table header for that reason, so the plan prompt now carries both words for one dimension.

Impact: wording only; no number is wrong. It is a `docs/design-system.md` §8 defect (interface vocabulary)
and a CONTEXT.md _Avoid_ hit in code.

Fix shape: change the two label sources to 切角 (one string each), then grep `角度` across
`frontend/src` and `app/` for stragglers; the U1 banned-words gate (`docs/issues/ui/issue-u1-banned-words-gate.md`)
is the place this would have been caught automatically.
