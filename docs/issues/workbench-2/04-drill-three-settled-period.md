# 04 — drill 3: a first period that actually settles, and the loop's proof (adopt → next offer) on real rows

route=B (acceptance only; no code unless the drill finds a defect, which then becomes an issue file).
Serves the board row 工作檯消融與閉環修正 (spec.md). Runs after tickets 01–03 ship. Drill 2 (2026-09-09)
never reached 結算 or 下一期: every period was still running, so the second diagnosis and the
next-period suggestion were never seen with data.

## What

1. Stand-in Meta on the drill server (`scripts/drill/serve.py --port 8710`, `docs/drills/README.md`):
   `fake_meta reset` → `mirror` a tree for one brand → `spend` dated inside the period **and past its
   `end_date`** → `pull`. The period must reach `awaiting_data` by itself (`_advance_if_ended`).
2. One persona (Haiku, playwright-cli headed, relay batons of ≤4 steps, `run.md` as the baton, no time
   limit, screenshot every step): 素材準備 → adopt the copy of two nodes, leave the rest → 經營概況 →
   判讀 (records which coordinates it names) → 檔期面板 → 結算這期 → 建議下一期 → 採用預算 → 出方案 →
   record whether the new offer's coordinates repeat the adopted nodes' winning coordinates.
3. Opus aggregates into `.scratch/drill3/summary.md`; every number the persona reports is
   recomputed from the DB by main chat before it is believed (drill 2 lesson: the screen said 91.6%,
   the DB said 91.9%).
4. One observation line, not an experiment: with the humanizer rule file in the copy task, count the
   fix-call failed lines for this drill's copy outputs; compare with drill 2's 322→104. No
   with/without run (Opus plan review 2026-09-09: nothing measured supports a controlled comparison yet).

## How we know it's done

1. `.scratch/drill3/summary.md` exists with: the settled period's spend/revenue as the screen shows
   them and as `SELECT` returns them (equal); the diagnosis text with ≥1 coordinate named; the
   next-period suggestion's dates and budget; the new offer's node coordinates against the adopted
   nodes' coordinates (a yes/no per dimension).
2. Untagged spend share on the diagnosis is 0% (ticket 01's rule) — the on-screen number and the SQL.
3. Every defect found is a `docs/issues/<goal>/issue-<name>.md` (cause, impact, `file:line`, `Status:`);
   none is fixed inside this ticket.
4. The persona's screenshots are real page captures (check `file` type; drill 2 had 12 of 42 as the
   playwright-cli upgrade banner).

## Shared files touched

None edited. Read: `scripts/drill/*`, `docs/drills/README.md`, `app/schedule/period.py:339`
(`next_period_suggestion`), `app/schedule/performance.py:88` (`_slot_for_spend`).

## Contradiction check

- Done-check 2 (0% untagged) vs a persona who adopts only two nodes: ticket 01 syncs the latest
  round for the other nodes, so every bound ad still carries coordinates; if the number is not 0%,
  ticket 01 is wrong, not this drill.
- §2 「採用預算 → 出方案」 vs ADR 0053 (settle by hand): the drill settles by pressing the button
  after the end date, never by writing the period row directly.
