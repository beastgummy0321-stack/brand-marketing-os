---
id: 0069
decision: The tree owns an ad node's seven coordinates; a continued node keeps last period's; brief and candidate read them.
applies-to: [app/schedule/, app/departments/ads/, app/workbench/prompts.py, frontend/src/components/schedule/, docs/contracts/schedule.md, docs/contracts/workbench.md]
supersedes: none
status: in-force
---

# A node's coordinates are owned by the tree, and a continued node keeps them

2026-09-09, ruled by the user after drill 3, in their words: 「座標歸樹、沿用帶上一期。確認好這期結束後，
能夠把好的留下來繼續投，爛的替換掉即可。」 Module-boundary decision (constitution rule 2): it moves the
source of truth for a node's coordinates across the schedule → workbench boundary set by ADR 0068.

## What drill 3 measured (2026-09-09, MOVE Daily, `.scratch/drill3/summary.md`)

The next offer named the winners (延續 01A/01C/02B/03A/03C at 3.40x) and replaced the 0.70x losers —
the loop closed on the **name** axis. It did not close on the **coordinate** axis: the tree's leaves
carried no coordinate field, `app/schedule/jobs.py` handed every brief `"coordinates": None`, and
`creative_candidate` took the seven labels the copy model chose each time. The same 沿用 node 01A was
scored on (pain=effort, hook=outcome_led) in period 1 and (pain=experience, hook=pain_question) in
period 2. A diagnosis that compares coordinates therefore compared two different things under one
name.

## The decision

1. **The tree task returns coordinates for every third-layer node** — the seven dimensions
   `audience/pain/angle/hook/proof/offer/format` as labels from the brand's vocabulary, which the
   tree prompt receives last (the order ADR 0068 §6 uses for copy). Layers 1–2 carry none.
2. **A continued node keeps last period's coordinates, enforced by the program.** The prompt tells
   the model to copy them; the read-time overlay that already stamps `continued_from_node_key`
   (ADR 0064's tree read, `binding.tree_with_bindings`) overwrites a matched depth-3 node's
   coordinates with the scored row's (`period_node_result.coordinates_json` → labels). A replaced
   (「賠」) node must differ from the old one in at least one dimension; that rule lives in the prompt
   only — the program does not reject a tree for it.
3. **The brief snapshot is the tree's.** `submit_brief` carries the leaf's coordinates into
   `workbench_brief.coordinates_snapshot_json` (ADR 0068 §2 amended); the copy prompt states them as
   the coordinates to write for, not as a reference.
4. **`creative_candidate` reads the snapshot first.** Per dimension the snapshot wins; the copy
   model's `coordinates_json` fills only what the snapshot left empty (ADR 0068 §3 amended). A
   manual brief with no snapshot keeps the model's answer — the only place the model still decides.
5. **The screen shows the seven values on the node** (one line), so a person can see that 沿用 means
   the same coordinates, not only the same name.

## Considered and rejected

- **Coordinates as keys in the tree reply.** Rejected: the copy task and the vocabulary route speak
  labels; `persist_creative_result` already resolves labels → keys once. Two spellings in flight is
  the bug this ADR removes.
- **Prompt-only continuity (no program override).** Rejected: drill 3's local model altered a
  verbatim seed by one space; a coordinate tuple copied by a model is a coordinate tuple until it is
  not, and the diagnosis would never know.
- **Storing the enforced coordinates back into the tree JSON.** Rejected: the tree read is an
  overlay that never writes (ADR 0064); the tree JSON stays the model's answer, the enforcement is
  visible in every read path because every read path goes through the same overlay.
- **Populating `creative_slot.*_coordinate_id`.** Rejected for now: seven FK columns nobody reads
  (ablation 2026-09-09); the candidate row already carries the resolved keys.

## Consequences

- `app/departments/ads/campaign_tree.md` reply shape, `app/schedule/{tree,binding,jobs,state}.py`,
  `app/workbench/prompts.py`, the tree node type and card in `frontend/src/components/schedule/`,
  and the contract pages of schedule and workbench change in ticket workbench-2/05.
- Trees produced before this ADR have no coordinates: their nodes render 「—」 and their briefs keep
  an empty snapshot; nothing is backfilled.
- The proof the next drill must show: a 沿用 node's `creative_candidate` keys equal its last
  `period_node_result` keys.
