---
id: 0051
decision: The interface is a dashboard read at a glance, not a document read top to bottom; the shell is fluid up to 1920px.
applies-to: [frontend/]
supersedes: decision-0038-desktop-only-1440 (no file in repo; was cited by ADR 0003 and three code comments)
status: in-force
---

# The interface is a dashboard, not a document

2026-09-02, dictated by the user in an interview. Until today **nothing in this repo decided
what the product looks like.** Three things did, none of them a decision:

1. `frontend/src/styles/tokens.css:1-5` — a header comment records the whole palette and type
   scale as the output of one tool query: `marketing operations dashboard cockpit professional
   light b2b saas`. Ticket 01 typed that string, used whatever came back, and every ticket since
   inherited it. That string is where the office-software look comes from.
2. `frontend/src/components/layout/AppShell.tsx:10` plus `tokens.css:79` (`overflow: hidden`) —
   the page cannot scroll, only the middle pane can. That is the Excel/Outlook/VS Code frame.
3. `tokens.css:66` — `--width-shell: 1440px`, consumed as a fixed width.

Every rule that should have governed this is gone: ADR 0019 (icons first, no chart piles) and
ADR 0017 (one thing at a time) are in `docs/adr/retired/`; `docs/ui-migration-contract.md` was
deleted; "decision 0038" has no file in the repo. This ADR replaces all of them.

**Scope: these rules are acceptance conditions for T2 and every frontend build after it.**
They do not authorise a frontend rewrite. The mainline is still the ad-scheduling loop.
Broad, not deep — one line per rule, covering every screen.

## Rules

**Layout**

1. A module's landing screen is a dashboard: overview first (number cards and charts), detail
   below it or behind a tab.
2. Any screen answers "what is this page for, and what can I do right now" on first sight;
   what matters most comes first, and the same ordering applies inside tabs and sub-tabs.
3. Dense information is split by tabs, sub-tabs, or disclosure — never a single long page the
   user scrolls to the bottom of.
4. The shell is fluid: `max-width` 1920px, usable down to 1024px, grids gain a column when
   there is room (`auto-fit`, not a hardcoded column count). Tablet and phone are out of scope.

**Density**

5. Anything expressible as a number, a chart, or a status pill is not written as a sentence.
   Prose is the last resort.
6. A clean screen wins: no annotation by default. Something genuinely complex earns one `?`
   affordance that reveals its explanation on hover.
7. An explanation says what a thing *is*. It does not tell the user how to think about it.
8. Charts exist so the overview is legible at a glance, not as page filler; each chart on a
   screen answers one question of its own. A genuinely information-dense overview may carry
   many charts — the limit is clutter, not count.

**Copy**

9. Buttons and labels use standard UI vocabulary: 生成、下一步、接受、拒絕、儲存、匯入、產生報表.
10. A function's name is never rewritten as a colloquial question or in the first person.
    Banned in the shape of: 「看這期賺了多少」, 「我不喜歡，下一步」, 「我喜歡，接受」.
11. "Plain language" governs how the assistant talks *to* the user in chat. It does not govern
    interface text. Beginner-friendly means the conventional UI word (生成, 下一步), not a
    sentence that explains the button to someone assumed not to read.

**Finish**

12. Motion is present and restrained: fade in/out and expand/collapse for state; charts, icons,
    pie and line charts get a simple grow, unfold, rotate, or move on entry. Nothing snaps.
13. Palette and typography are a separate ticket. This ADR does not change `tokens.css` colours
    or fonts.

## What was measured, and what was not

At 1280x800 today, the fixed 1440px shell puts real controls in a dead zone the window cannot
reach — not cramped, unclickable: the topbar's 回到舊版介面, org menu and bell across all 19
screen states, plus 新增品牌, 排這期的檔期, 新增產品, 新增/匯入訂單檔, 列印・存成 PDF, and the
per-tab buttons in 品牌智庫.

The probe changed `AppShell.tsx:10` from `w-[var(--width-shell)]` to
`w-full max-w-[var(--width-shell)]` and re-measured 19 screen states at 1280x800 and 1024x768:
zero overflow, zero broken layout, zero screens needing re-layout. The estimate of "10 tables
and 17 grids to fix" was wrong; none needed it. The probe was reverted.

**The caveat that must not be lost:** `products`, `orders`, `report` and `schedule` were
measured empty — a centred narrow card cannot overflow. **A full order table at 1024 has never
been measured.** Only the creative-coordinate tab had real data (35 rows, two columns) and it
passed. Seed those tables before calling rule 4 verified.

1920 is untested at any width above 1440.

## Consequences

- ADR 0003's consequence "決策 0038（純桌機 1440px）繼續有效，React 版不做響應式" no longer
  holds and now points here. ADR 0003's own decision (React rewrite) stays in force.
- Three code comments cite the dead decision and must be corrected when touched:
  `AppShell.tsx:6`, `lib/useEchart.ts:5`, `styles/tokens.css:65`.
- `BOARD.md`'s U1 row cites the deleted `ui-migration-contract.md` ("契約鐵則 11–12 驗收") and
  cannot be executed as written; it is re-pointed here.
- Rules 1-4 need a machine gate or they drift back. The gate: across the 15 routes at 1280,
  `document.documentElement.scrollWidth <= window.innerWidth`. It must be proven red once.
- Verifying any of this in a browser requires a fresh browser session — a cached JS bundle made
  the probe's first measurement identical to the unmodified build. This is the browser-side
  twin of the "restart the backend or you verify old code" rule in CLAUDE.md.
