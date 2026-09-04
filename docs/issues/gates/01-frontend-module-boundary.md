# 01 frontend module boundary: features meet at their front doors

Route C (module boundary). Decision signed by the user 2026-09-04 and written up as
**ADR 0060** (`docs/adr/0060-layout-is-the-shared-kit-features-meet-at-their-front-doors.md`)
before this ticket. Read that ADR first; it is the authority, this ticket is only the work.

## What

Add one rule to `frontend/.dependency-cruiser.cjs` and make the repo satisfy it. The existing
`supabase-js-only-in-auth` rule stays exactly as it is — do not touch it, do not reword it.

The rule, verbatim, appended as the second entry of the `forbidden` array:

```json
{
  "name": "feature-internals-are-private",
  "severity": "error",
  "comment": "ADR 0060：src/components/<功能>/ 之間只准 import 對方的 index.ts；layout 是共用零件櫃，全站可直接拿。",
  "from": { "path": "^src/components/([^/]+)/" },
  "to": {
    "path": "^src/components/[^/]+/",
    "pathNot": [
      "^src/components/$1/",
      "^src/components/layout/",
      "^src/components/[^/]+/index\\.tsx?$"
    ]
  }
}
```

(The file is `.cjs`, so write it as a JavaScript object literal in the existing style — single
`module.exports`, same indentation, `$1` and `\\.` kept exactly as above. `$1` is
dependency-cruiser's back-reference to the group captured in `from.path`; it is what makes the
rule cover folders that do not exist yet, and it must survive into the shipped config.)

Measured 2026-09-04 by installing this rule and running `npm run depcruise`: it produces
**exactly two** violations, and no others.

```
  error feature-internals-are-private: src/components/layout/Topbar.tsx → src/components/auth/OrgMenu.tsx
  error feature-internals-are-private: src/components/intake/steps/ScanStep.tsx → src/components/products/panels/ProductNewPanel.tsx
x 2 dependency violations (2 errors, 0 warnings). 149 modules, 562 dependencies cruised.
```

Clear those two by opening two front doors — **not** by moving, renaming or rewriting any
component:

1. New file `frontend/src/components/auth/index.ts`, re-exporting `OrgMenu` from `./OrgMenu`.
2. New file `frontend/src/components/products/index.ts`, re-exporting `ProductNewPanel` from
   `./panels/ProductNewPanel`.
3. `frontend/src/components/layout/Topbar.tsx:3` — the import specifier becomes
   `@/components/auth`; the imported name `OrgMenu` and every line of JSX stay unchanged.
4. `frontend/src/components/intake/steps/ScanStep.tsx:19` — the import specifier becomes
   `@/components/products`; the imported name `ProductNewPanel` and its usage at line 241 stay
   unchanged.

Out of scope, named so the reviewer does not read their absence as an oversight:
no `no-circular` rule, no `index.ts` for the other ten folders, no barrel for `layout`,
no change to `ProductListPage.tsx:10` (`./panels/ProductNewPanel` is inside its own feature and
stays a direct path), no change to `frontend/src/lib/`.

## How we know it's done

Run from the repo root unless the step says otherwise. Every command must be green.

1. `cd frontend && npm run depcruise`
   → `✔ no dependency violations found`. Both rules present in the config; neither reports.
2. **Proved red, two different ways** (each: break it, see it fail, restore, see it pass):
   a. Put `frontend/src/components/layout/Topbar.tsx:3` back to
      `import { OrgMenu } from "@/components/auth/OrgMenu";` → `npm run depcruise` reports
      `error feature-internals-are-private: src/components/layout/Topbar.tsx → src/components/auth/OrgMenu.tsx`.
      Restore.
   b. Create a folder that did not exist when the rule was written —
      `frontend/src/components/_probe/Thing.tsx` (any trivial exported component) — and import it
      from `frontend/src/components/intake/steps/ScanStep.tsx` as
      `@/components/_probe/Thing` → `npm run depcruise` reports a
      `feature-internals-are-private` error naming `_probe`. Delete the probe folder and the
      import. This is the check that the rule is a wildcard, not a list of today's folder names;
      a rule that passes (a) but not (b) has not met this ticket.
   Paste both failing outputs into the completion report. A done-check claimed without its
   output is not done.
3. **No false positive on the front door**: with the shipped code in place, `ScanStep.tsx`
   importing `@/components/products` is green — this is covered by step 1 and needs no extra run,
   but say so explicitly in the report.
4. `cd frontend && npm run lint` → oxlint clean.
5. `cd frontend && npm run test` → vitest green, including
   `frontend/src/components/auth/OrgMenu.test.tsx` (it imports `./OrgMenu` directly, inside its
   own feature, and must keep working untouched) and
   `frontend/src/architectureBoundaries.test.ts`.
6. `cd frontend && npm run build` → `tsc -b` plus vite build, no errors.
7. `cd frontend && npm run e2e` → 2 passed. Requires `supabase start` already running. This is
   the step that catches a barrel file breaking a real page load.
8. `uv run ruff check app` and `uv run pyright` → unchanged and green. No backend file is
   touched by this ticket; if either goes red, stop and report rather than fixing it here.

## Shared files touched

Pasted from the searches below, run 2026-09-04 at the repo root, unscoped by directory and by
file type (`node_modules`, `.git`, `dist`, `storybook-static`, `.scratch` excluded as noise).

`grep -rn "OrgMenu" .`

```
frontend/src/components/auth/OrgMenu.test.tsx:1:/** frontend/src/components/auth/OrgMenu.test.tsx — 票 03-3 §4：`GET /api/identity/me`
frontend/src/components/auth/OrgMenu.test.tsx:19:import { OrgMenu } from "./OrgMenu";
frontend/src/components/auth/OrgMenu.test.tsx:32:describe("OrgMenu", () => {
frontend/src/components/auth/OrgMenu.test.tsx:45:    render(<OrgMenu />);
frontend/src/components/auth/OrgMenu.tsx:43:export function OrgMenu() {
frontend/src/components/layout/CopyIconButton.tsx:9: * 但這顆按鈕的最後一個呼叫端（`components/auth/OrgMenu.tsx` 的邀請連結）還在。
frontend/src/components/layout/Topbar.tsx:3:import { OrgMenu } from "@/components/auth/OrgMenu";
frontend/src/components/layout/Topbar.tsx:10:        <OrgMenu />
frontend/src/lib/http.ts:59:/** 使用者自己按登出時呼叫（`OrgMenu`）：把記住的路徑丟掉。刻意不塞進 `lib/auth.ts` 的
```

`grep -rn "ProductNewPanel" .`

```
frontend/src/components/intake/steps/ScanStep.tsx:19:import { ProductNewPanel } from "../../products/panels/ProductNewPanel";
frontend/src/components/intake/steps/ScanStep.tsx:241:        <ProductNewPanel
frontend/src/components/products/panels/ProductNewPanel.tsx:13:export function ProductNewPanel({
frontend/src/components/products/ProductListPage.tsx:10:import { ProductNewPanel } from "./panels/ProductNewPanel";
frontend/src/components/products/ProductListPage.tsx:140:        <ProductNewPanel
```

`grep -rn "dependency-cruiser\|depcruise" .` (package-lock.json excluded)

```
.github/workflows/ci.yml:88:      - run: npm run depcruise
BOARD.md:7:- [ ] 閘門 ｜ docs/issues/gates/ ｜ 檔案層環掃描已裝完，剩前端 depcruise 與七維 regex 天花板
docs/adr/0027-multi-tenant-cloud-saas-target.md:28:     前端 depcruise 擋 `supabase-js` 只准出現在登入模組。
docs/issues/gates/issue-07-1-depcruise-supabase-js.md:1:# 07-1 前端 depcruise：supabase-js 只准在登入模組 import
docs/issues/gates/issue-07-1-depcruise-supabase-js.md:6:剩下 depcruise 那一條規則：跨模組只准 import 進入點，`@supabase/supabase-js` 只准出現在身分模組。證紅再算數。
docs/issues/gates/spec.md:3:Status: 待做——剩兩份 issue（前端 depcruise、七維 regex 天花板）。檔案層 import 環掃描
frontend/package.json:10:    "depcruise": "depcruise src --config .dependency-cruiser.cjs",
frontend/package.json:41:    "dependency-cruiser": "^18.2.0",
frontend/src/lib/auth.ts:6: * dependency-cruiser 規則盯住「全站只有這支檔案准 import @supabase/supabase-js」——
frontend/src/lib/auth.ts:7: * 2026-09-04 這條規則已經接上（`frontend/.dependency-cruiser.cjs`、`npm run depcruise`、
```

Files this ticket writes: `frontend/.dependency-cruiser.cjs`,
`frontend/src/components/auth/index.ts` (new),
`frontend/src/components/products/index.ts` (new),
`frontend/src/components/layout/Topbar.tsx` (line 3 only),
`frontend/src/components/intake/steps/ScanStep.tsx` (line 19 only).
Nothing else. `git diff --name-only` is checked against this list.

`frontend/` has no `docs/contracts/<module>.md` obligation: the contract-page ratchet
(`app/tests/test_architecture_boundaries.py:1787`) lists backend `app/` modules only.

## Contradiction check

**Done-check 2b against the "out of scope" list in What.** 2b asks for a folder
(`_probe`) that the config's own rule has never seen, while What forbids adding `index.ts` to
any folder beyond the two named. These agree only because the probe is created and deleted
inside the check and never ships. An implementer who reads 2b as licence to leave `_probe`
behind, or who satisfies it by adding `_probe` to a list inside the config, has broken What.
The input that shows it: `git diff --name-only` after the work — any path containing `_probe`
means the two readings diverged.

**Done-check 1 against done-check 2b.** If the rule were written as a list of the twelve
folder names, check 1 would be green and check 2b red — the config would pass today and stop
working the first time someone adds a folder. That is the whole point of 2b; do not "fix" a red
2b by adding the probe folder to the config.

**Done-check 5 against What step 1.** `OrgMenu.test.tsx:19` imports `./OrgMenu`, not the new
`index.ts`. That is a same-feature import and must stay as it is. An implementer who "tidies" it
to `@/components/auth` creates `auth/index.ts → auth/OrgMenu.tsx → auth/index.ts` circularity
risk in the test and changes a file this ticket does not list. The input that shows it: the test
file appearing in `git diff --name-only`.
