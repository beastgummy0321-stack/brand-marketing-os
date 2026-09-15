# Ad coordinates edited after dispatch diverge from the image set

Status: not planned. Found in the F07 integration audit (2026-09-15).

- Dispatch snapshots the ad's coordinates into the set (`workbench_brief.coordinates_snapshot_json`,
  `app/ads/assets.py:39-42`); image rounds use that snapshot and store `round.audience_key`
  (`app/workbench/jobs.py:592-601`).
- The ad's coordinates stay editable after dispatch, with no pack check (`app/ads/plan.py:321-337`).
- Closeout visual learning groups ads by the ad's current `audience_key`
  (`app/ads/visual_learning.py:77-87`), so an ad whose audience changed after dispatch is compared
  and learned under the new audience while its images were written for the old one. No Decision
  says which one is right.
- Revisit: pick the source of truth (the snapshot the images were made for, or the audience the ad
  ran with), then either lock coordinates once a pack is dispatched or read `round.audience_key` at
  closeout.
