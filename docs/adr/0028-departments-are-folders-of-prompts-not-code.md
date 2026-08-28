# Departments are folders of prompts, not code

Terminology first, because this ADR nearly stole a word that was already taken. This repo's
constitution (`CLAUDE.md` #7) and ADR 0024 use **模組 / module** for a Python package that owns
its own migrations, its own frontend feature folder, and a `status()` the orchestrator reads.
The thing described here is a different thing and is called a **部門 / department** — the
user's own word for it. `app/core` is a module. The ad department is a department. Departments
never implement `status()` and the orchestrator never dispatches to them.

Shell OS is a marketing OS with departments — ads first, then creative, content, SEO, website.
In this repo the ad department alone grew to 21,595 lines of Python encoding thresholds nobody
had ever validated against a real campaign. To stop that repeating, a department is a folder of
task `.md` files inside the workspace, not a Python package. Adding a department means adding a
folder; the shell's code does not change.

The shell therefore never knows what any department does. It packs a folder, runs the agent
CLI, reads the result back, and blocks the approve button when money is involved. Department
logic lives in Markdown maintained by the user and the agent, not in code maintained by a
reviewer.

## Consequences

- A department cannot have its own screen. Every department renders through the same feed and
  the same dashboard. The day one genuinely needs a bespoke screen, this decision has to be
  reopened — that is the price paid for it.
- There is no per-department table, migration, or test suite. `run` carries a `department` text
  column, and nothing else in the schema distinguishes one department from another.
- This does not touch ADR 0024. Modules still exist, still self-report `status()`, and the
  orchestrator still dispatches Actions to them. But **7 of the 8 `status()` implementations
  live in `app/ads/`** (auto_sync, diagnosis, health_lights, meta_mcp, proposal, theme_batch,
  weekly_proposals); only `app/intake/dispatch.py` survives the deletion. The orchestrator
  therefore keeps its code and loses almost all its inputs — see the open question in
  `HANDOFF-shell-slice.md` §4.
