---
id: 0060
decision: A components/ feature imports another only via its index.ts; layout is the shared kit, open to all.
applies-to: [frontend/src/components/, frontend/.dependency-cruiser.cjs]
supersedes: none
status: in-force
---

# layout is the shared kit; features meet at their front doors

2026-09-04, board row 閘門, ticket `docs/issues/gates/01-frontend-module-boundary.md`.
Module boundary, so the user signed it before any code was written.

## The problem this closes

`frontend/src/components/` has twelve folders and no stated rule about which may import which.
The backend has had `LayerDirectionTest` and `ImportCycleScanTest` since 2026-08-07; the front
end has had nothing. The board row carried an issue asking for "cross-module imports only
through the entry point" — the rule was right, its cost estimate was not.

## What was measured before deciding

Cross-folder imports under `frontend/src/components/`, counted 2026-09-04:

    各功能 → layout            83
    layout/Topbar.tsx → auth/OrgMenu.tsx                    1
    intake/steps/ScanStep.tsx → products/panels/…Panel.tsx  1
    ------------------------------------------------------------
    總計                                                    85

`index.ts` files in those twelve folders: **0**.

So the rule as originally worded was unbuildable — there were no front doors to walk through —
and had it been built by adding twelve of them, 83 of the 85 imports it flagged would have been
a feature using the shared UI kit, which is the correct thing to do. A gate that reports 83
false alarms on the day it ships gets loosened within the month.

## The decision

1. `frontend/src/components/layout/` is **the shared kit and the app shell**, not a feature.
   Anyone may import any file in it directly. Barrel-free on purpose: `@/components/layout/Pager`
   tree-shakes and an `index.ts` re-exporting twenty-three modules does not.
2. Every other folder directly under `frontend/src/components/` is a **feature**. A feature's
   files are private to it. Another feature may import it **only** through
   `frontend/src/components/<feature>/index.ts`.
3. A feature gets an `index.ts` **only when something outside it actually imports it**. Eleven
   of the twelve folders need none today; writing them anyway is scaffolding for later.
4. The shell may compose features (`layout/Topbar.tsx` renders `auth`'s org menu). That makes
   `layout` and `auth` mutually dependent **at folder level**; at file level there is no cycle,
   and the alternative — threading the org menu as a prop through every `AppShell` caller — buys
   nothing. Recorded here so the next reader does not mistake it for an oversight.

Held by `feature-internals-are-private` in `frontend/.dependency-cruiser.cjs`, which CI runs on
every push (`.github/workflows/ci.yml:88`). The rule is a wildcard match, not a list of folder
names: a folder added next month is governed the day it appears, with no edit to the config.

## What we looked at

- **dependency-cruiser** (already a devDependency, already wired into CI and `npm run depcruise`).
  Its `$1` back-reference across `from.path` → `to.pathNot` expresses "any feature, not this one,
  not through its index" in one rule. Adopted.
- **oxlint `no-restricted-imports`** (the other linter already installed). Rejected: its patterns
  are per-file globs with no way to say "not the folder this file is already in", so the same
  rule would need one entry per feature folder — a list that goes stale the next time a folder
  is added, which is the failure this ADR is trying to avoid.
- **Twelve barrel files** (the ticket's original wording). Rejected: 85 import rewrites for two
  real violations, plus a standing tax on every new folder, plus barrels' known cost to Vite's
  tree-shaking.

## Considered and rejected

- **Features may not import each other at all.** Rejected because a legitimate cross-feature
  reuse already exists (`ProductNewPanel` is used by both the product list and the intake
  wizard). Under that rule the only escape is to push shared feature code into `layout`, which
  turns the kit into a junk drawer and empties the boundary of meaning.
- **Freeze the two violations in a known-debt list and change no code.** Rejected: two is small
  enough to simply fix, and a tolerance list that exists is a tolerance list that grows.
