---
id: 0028
decision: A department is a folder of prompt .md files, not a Python package; adding one changes no code.
applies-to: [app/departments/]
supersedes: none
status: in-force
---

# Departments are folders of prompts, not code

Terminology first, because this ADR nearly stole a word that was already taken. This repo's
`CLAUDE.md` #7 uses **模組 / module** for a Python package that owns its own migrations and its
own frontend feature folder, and does not touch another module's tables. The thing described
here is a different thing and is called a **部門 / department** — the user's own word for it.
`app/core` is a module. The ad department is a department.

(As first written this paragraph also cited ADR 0024 and defined a module by the `status()` the
orchestrator reads. ADR 0024 was retired by ADR 0046 and the orchestrator is deleted; the
module/department distinction stands without it.)

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
- **Superseded note (2026-09-02):** this bullet originally said "this does not touch ADR 0024 —
  modules still self-report `status()` and the orchestrator still dispatches Actions", and named
  `app/intake/dispatch.py` as the one surviving implementation. None of that is true any more:
  ADR 0024 was retired by ADR 0046, `app/core/orchestrator.py` and every `status()` /
  `register_module()` implementation are deleted, and `app/intake/dispatch.py` does not exist.
  **The decision above is unaffected** — it stands on "a department is a folder of prompts", not
  on the orchestrator. Nothing in force now depends on the dispatch layer.
