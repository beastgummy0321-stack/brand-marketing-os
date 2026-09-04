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
   files are private to it. **Anything** may import it **only** through
   `frontend/src/components/<feature>/index.ts` — another feature, `src/lib/`, a test, a
   directory that does not exist yet. "Private" that only holds against files in one directory
   is not private; see the amendment below for what it cost to learn that.
3. A feature gets an `index.ts` **only when something outside it actually imports it**. Eleven
   of the twelve folders need none today; writing them anyway is scaffolding for later.
4. The shell may compose features (`layout/Topbar.tsx` renders `auth`'s org menu). That makes
   `layout` and `auth` mutually dependent **at folder level**; at file level there is no cycle,
   and the alternative — threading the org menu as a prop through every `AppShell` caller — buys
   nothing. Recorded here so the next reader does not mistake it for an oversight.

5. **`frontend/src/App.tsx` is the composition root** — the one file entitled to know every
   feature by name, because routing is exactly that job (thirteen such imports today, all in
   that file). Nothing else outside `src/components/` may reach a feature's internals, and
   **only `src/main.tsx` may import `App.tsx`**, so the exception cannot itself be used as a way
   in. One privileged file, and it is a dead end.

Held by three rules in `frontend/.dependency-cruiser.cjs`, which CI runs on every push
(`.github/workflows/ci.yml:88`): `feature-internals-are-private`,
`outsiders-use-the-front-door-too`, `only-main-imports-the-app-shell`. All three are wildcard
matches, not lists of folder names: a folder added next month is governed the day it appears,
with no edit to the config.

## Amendment, 2026-09-04, same day: the first version of this ADR overclaimed

Point 5 and the second and third rules were not in the signed version. The independent review of
ticket 01 attacked the gate the ADR had just been written to describe, and got through:

    frontend/src/lib/_launder.ts              export { ApiKeySection } from "@/components/settings/ApiKeySection";
    frontend/src/components/cockpit/_use.tsx  import { ApiKeySection } from "@/lib/_launder";

    ✔ no dependency violations found (153 modules, 566 dependencies cruised)

`settings/` had no front door, `ApiKeySection.tsx` was internal, `cockpit` read it anyway, and
the command CI runs reported nothing. The cause was structural, not a typo: the first rule
anchors **both** its `from` and its `to` to `^src/components/`, so any file outside that prefix
is invisible to it and one line of re-export launders the whole boundary.

The first fix was itself too narrow, twice. Main chat then found the same laundering working from
`src/components/_bare.ts` (a file directly under `components/`, in neither rule's `from`), and
again from `_side/_launder.ts` (a file outside `src/` entirely). Three instances of one shape.

**The root cause is the shape of `from`, not the list of places it forgot.** A boundary rule whose
`from` is a prefix protects only against files that happen to live under that prefix, and a
laundering hop can live anywhere. The `from` of both rules is therefore **unanchored** — every
module is a potential source — with the privileged sources spelled out as an explicit `pathNot`
exception list: `src/components/<feature>/` (governed by the first rule instead), `src/App.tsx`
(the composition root), and `node_modules/` (not ours). Privilege is enumerated; everything else
is suspect. Measured with that shape: zero violations in the repo, and all three laundering
routes red.

Three lessons, in the order they matter:

1. **A gate's claim is worth what someone tried to break.** This rule had been proved red two
   ways before it shipped — a real violation, and a folder that did not exist when the rule was
   written. Both proofs were about the rule *firing*; neither was about the rule being *evaded*.
   Proving red and proving unbypassable are different exercises, and only the second one is what
   the word "private" in this ADR was promising.
2. **Fixing the instance is not fixing the hole.** The first patch closed `src/lib/`; the same
   attack then worked from one directory up, and again from outside `src/`. Each patch passed its
   own proof-red and left the boundary open. A gate patched per-instance is a gate that will be
   patched again.
3. **None of it cost anything.** Measured before asking: zero violations in the repo as it
   stands, zero source files changed, gate red on every attack. The expensive part was never the
   fix; it was that the ADR asserted the protection before anyone had tried to walk around it.

The user signed this amendment on 2026-09-04, the same day as the original.

## Two measured facts about the finished gate

**What it does not cover, on purpose.** The final review reached a feature's internals by hand-
planting a package under `frontend/node_modules/` that re-exports them, and both `npm run
depcruise` and `npm run build` stayed green — `options.doNotFollow: { path: "node_modules" }`
stops the crawl before that edge is built. It is not a shippable route: `node_modules/` is
gitignored, so it appears in no diff and no review, and `npm ci` does not recreate a hand-placed
folder on anyone else's machine or in CI. Recorded because it is the honest edge of this gate, and
because a future supply-chain concern would start exactly here. Every other route the review tried
— dynamic `import()`, `require()` from `.cjs`, type-only import, a `.d.ts` / `.stories.tsx` /
`e2e/` hop, a hop through `layout/`, a hop through another feature's own `index.ts`, and a
`tsconfig` path alias pointing straight at an internal file — is red. A vite-only alias blinds
depcruise alone but fails `tsc`, so it cannot pass the full gate either.

**Pull-out test, 2026-09-04.** Deleting `src/components/report/` plus its registration in
`App.tsx` leaves `npm run build` green and both e2e specs passing — no hidden coupling. Deleting
`src/components/products/` does **not** build, for one reason and it is a declared one:
`intake/steps/ScanStep.tsx` imports `@/components/products`. That is the dependency this ADR's
"considered and rejected" section is about; the front door makes it visible in the dependency
graph rather than hiding it, which is the whole point. A declared cross-feature dependency
failing a pull-out is not the hidden coupling that test hunts for, and it is not "fixed" by
deleting the sharing.

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
