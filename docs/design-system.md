# Design system — 行銷駕駛艙

**Status: in force since 2026-09-07. This is the only frontend rule document.**
Decision record: ADR 0065. Reference image: `docs/design-system.png` (the dashboard the user approved
2026-09-07; its numbers are sample data, its look is the standard). Token source of truth:
`frontend/src/styles/tokens.css`. Component kit: `frontend/src/components/layout/` (shared, ADR 0060)
and `frontend/src/components/layout/ui/` (shadcn/ui, new-york, Radix).

Precedence: `CONSTITUTION.md` rule 12 → this document → a ticket. A ticket that asks for a look this
document does not describe is `blocked-upstream`; change this document first (ADR-level, ask the user).
Every retired frontend rule (ADR 0051, the ui-reset handoff's "red lines", the U3 font/palette issue)
is folded in here — nothing else governs how a screen looks or reads.

---

## 0. Why this system exists

The 2026-09-07 redesign brief (the user's words: 清爽、有秩序、資訊精緻、操作明確，看起來是一套成熟的
商業產品) diagnosed five gaps in the previous interface. Every rule below closes one of them:

| Gap | Rule that closes it |
|---|---|
| No hierarchy: the cockpit stacked overview, table, verdict card and chart; the user assembled the conclusion | §4 page anatomy, §5 dashboard grid: overview first, one primary block, detail behind tabs |
| Whitespace out of balance: content in one corner, narrow tables inside very wide cards | §5 width caps and full-cell data cards |
| Type and controls inconsistent: mixed CJK/Latin faces, headings, tabs and buttons with no shared language | §2.2 one family, §6 one kit |
| Navigation did not show the brand context: a row of disabled items before a brand, no clear brand overview after | §3 工作區 → 品牌 → 功能, separate org and brand switchers |
| Complex flows expressed as longer pages (schedule most of all) | §1.1, §5.1 staged workspace |

What the brief called "proportion and level" is the thing to copy from the reference: stable positions
for sidebar, toolbar, number cards and charts; neutral almost everywhere; violet, blue and aqua only
where attention belongs.

## 1. Principles

1. **Dashboard, not document.** A screen is read at a glance: overview first, detail behind a tab or a
   disclosure. Nothing is one long scroll. The single exception is `/brands/:id/report`, which is a
   printable document by design.
2. **Numbers over sentences.** Anything that can be a number, a bar, or a status pill is not prose.
3. **Honest empties.** No data is never `0`, `—` or an empty card; it is one line saying why
   (「本月還沒有訂單」「未追蹤」「累積中」). Sample data on screen always carries the 示意資料 badge.
4. **Two readings, both shown.** Where the system has two calculation bases (conservative / optimistic
   ROAS) both are drawn; the interface never hides uncertainty to look simpler.
5. **Calm surface.** Cool grey ground, white cards, one violet accent, one typeface family, restrained
   motion. Nothing decorative that does not carry information.

---

## 2. Foundations

All values live in `tokens.css` `@theme`; components use the token, never the literal.
Raw hex is allowed in exactly two files: `tokens.css` and `frontend/src/lib/chartColors.ts`
(canvas charts cannot read CSS variables). A vitest gate enforces this (§9).

### 2.1 Colour

| Role | Token | Value | Use |
|---|---|---|---|
| Page ground | `--color-background` | `#f6f7fb` | body, table header fill |
| Card | `--color-card` | `#ffffff` | every surface, sidebar, topbar |
| Text | `--color-foreground` | `#202237` | body text, numbers |
| Muted text | `--color-muted-foreground` | `#626b80` | captions, labels, table headers |
| Muted fill | `--color-muted` | `#f0f2f7` | hover fill, count chips |
| Border | `--color-border` | `#e3e6ef` | 1px hairlines everywhere |
| Input border | `--color-input` | `#dce0ea` | form controls |
| Primary | `--color-primary` | `#7055d8` | the one accent: primary button, active tab text, links, KPI icon, main bar |
| Accent tint | `--color-accent` / `-foreground` | `#f1edfc` / `#6348c5` | active nav item, selected subnav, KPI icon disc |
| Secondary | `--color-secondary` / `-foreground` | `#f0edf9` / `#5945aa` | secondary button, 示意資料 badge, auth aside |
| Success | `--color-success` | `#238169` | connected / done pill (Meta Ads dot) |
| Warning | `--color-warning` | `#a96711` | breakeven line, attention |
| Danger / destructive | `--color-danger`, `--color-destructive` | `#c53945` | errors, loss zone, destructive button |
| Irreversible | `--color-alert-irreversible` | `#ba591c` | confirm step of an action that cannot be undone |
| Chart 1 | `--color-chart-revenue` | `#7055d8` | first series, conservative ROAS dot |
| Chart 2 | `--color-chart-spend` | `#397cda` | second series |
| Chart 3 | `--color-chart-aqua` | `#2ea7af` | third series |
| Chart 4 | `--color-chart-soft` | `#a397e9` | fourth series, optimistic ROAS (hollow) |
| Chart 5 | `--color-chart-rest` | `#8892a8` | fifth series / "other" |

Series order in a chart is always 1→5 above. Status colours are never used as series colours.
Light only: `color-scheme: light`; there is no dark theme and no ticket may add one without an ADR.

### 2.2 Typography

- Family: `"Inter Variable", "Noto Sans TC Variable", "Microsoft JhengHei", sans-serif` for
  everything (`--font-sans` = `--font-display`). Decided 2026-09-07 by approving the reference image;
  the U3 font question is closed. No other family, no icon font.
- Base 14px. Numbers always `font-variant-numeric: tabular-nums` (`.numeric`, tables inherit).
- Contrast is higher than the reference mock's pale captions: muted text is `#626b80` on white
  (≥ 4.5:1), because a Chinese interface is read for hours, not glanced at.

| Element | Size / weight | Where |
|---|---|---|
| Page title `h1` | 26px / 650, tracking −.025em | `PageHeader` |
| Page subtitle | 14px / 400 muted | under h1: brand name + tagline |
| Card title `h2` | 15px / 600 | `.surface-header` |
| Card subtitle | 12–13px muted | under card title (「依活動比較」) |
| KPI number | `clamp(22px, 1.8vw, 32px)` / 600, tracking −.035em | `.metric-number` |
| KPI label | 14px / 500 | beside the icon disc |
| KPI caption | 12px muted | 「本月累計」「平台回報」 |
| Body / table cell | 14px / 400 | |
| Table header | 12px / 500 muted, background fill | `th` |
| Nav item | 14px / 500 | `.nav-item` |
| Nav group label | 11px / 500 muted | 工作區・品牌經營・品牌資料 |
| Badge / pill | 12px / 500 | |

### 2.3 Space, radius, line, shadow

- Spacing on a 4px grid: 4 · 8 · 12 · 16 · 20 · 24 · 28. Main padding 28 (22 below 1280).
  Card header `20px 22px 14px`, card body `0 22px 20px`. Grid gaps: KPI row 16, dashboard grid 20.
- Radius: card / surface 12px, table surface 10px, tabs group 8px, tab 5px, nav item 7px,
  buttons `--radius-md` .5rem, pills fully round. Tokens: `--radius-sm/md/lg/xl`.
- Lines: 1px `--color-border` everywhere. Cards are bordered, **not** shadowed at rest;
  `--shadow-card` is near-invisible, `--shadow-card-hover` only on hover of a clickable card.
- Focus: `2px solid --color-ring` outline, offset 3px, on `:focus-visible` only.

### 2.4 Icons

lucide-react only. Nav 19px stroke 1.7; inline with text 16px (`size-4`); KPI tile icon 18px inside a
36px disc filled `--color-accent`, stroke `--color-primary`. Icons never replace a label.

### 2.5 Motion

Colour / border / shadow transitions 150ms. State changes fade or expand/collapse; bars and charts grow
in on first paint; nothing snaps and nothing bounces. `prefers-reduced-motion` turns it all off
(already in `tokens.css`).

### 2.6 Viewport

Desktop only, fluid: shell `max-width` 1920px, usable down to 1024px; breakpoints at 1279 and 1100
shrink paddings and the sidebar (`--width-sidebar` 232 → 208). Grids that can gain a column use
`auto-fit`; fixed-count grids (the 5-tile KPI row, the 12-column dashboard) stay fixed by design.
Tablet and phone are out of scope; do not add media queries below 1024.

---

## 3. Shell

```
.app-shell (flex, max 1920, centred)
├── .app-sidebar  232px (collapsed 76px), white, right hairline, sticky 100dvh
│   ├── Logo + 行銷駕駛艙 wordmark
│   ├── Brand switcher card: avatar initials · brand name · 目前品牌 · chevron
│   ├── 工作區:    品牌總覽 · 收件匣 (count badge)
│   ├── 品牌經營:  經營概況 · 檔期規劃 · 素材工作檯 · 訂單與顧客
│   ├── 品牌資料:  產品 · 品牌智庫 · 顧問分析報告
│   └── footer:    設定 · user card (avatar · role · chevron → org menu)
└── .app-workspace
    ├── .app-topbar 64px: breadcrumb「品牌 / 頁面」 ｜ 背景工作 pill+count · bell · avatar
    └── .app-main  padding 28
```

Navigation reads 工作區 → 品牌 → 功能:

- **Organisation and brand are different levels and have separate switchers.** The organisation is the
  team and its data permission (org menu, in the footer/user card); the brand is what is being worked on
  right now (brand switcher card at the top: 目前品牌 · 其他品牌 · 新增品牌).
- **Switching brand keeps the function.** Product list of A → product list of B. A screen with no
  counterpart (a product detail) falls back to the new brand's list.
- Brand-scoped nav items are disabled (muted, tooltip 「請先選擇品牌」) until a brand is chosen;
  never a link that looks live and does nothing.
- **Features not yet shipped are out of the main nav** (內容與曝光, 顧客與口碑). They return when they
  exist; the workspace stays focused on daily work.
- The shell mounts once; route changes swap `.app-main` only (`WorkspaceContext`). Data fetching goes
  through TanStack Query with cache keys that include org and brand, so a switch never shows the previous
  object's data.
- Breadcrumb inside the page (`nav[aria-label="麵包屑"]`) is hidden; the topbar carries 當前位置.
- The 15 routes (素材工作檯 added 2026-09-09, ADR 0068) and the `/app` basename are fixed; all of the above is done with in-page tabs and layout.

---

## 4. Page anatomy

Every routed screen, top to bottom:

1. **`PageHeader`** — `h1` noun phrase (經營概況、檔期規劃、產品), muted subtitle (brand name +
   tagline or one-line purpose), right-aligned actions (`Button variant="outline"` with icon,
   optional 示意資料 `Badge variant="secondary"`).
2. **`PageTabs`** — segmented control, left; the same row's right side holds context
   (period 「2026 年 9 月」, channel pill 「● Meta Ads」). A view that lets the user add tabs ends the
   group with 「＋ 新增檢視」. Tab state lives in the query string (`?tab=facts`) so it can be shared.
3. **Content** in one of the layout patterns below. Nothing after the last pattern; if more is
   needed it is another tab.

Answer on first sight: *what is this page for, what can I do right now*. The most important
block is first, and the same ordering applies inside tabs.

---

## 5. Layout patterns

| Pattern | Class / component | Shape | Used by |
|---|---|---|---|
| KPI row | `.dashboard-metrics` | 5 tiles: icon disc · label / number / caption | 經營概況 |
| Dashboard grid | `.dashboard-grid` + `.dashboard-widget[data-width]` | 12 columns; widget `narrow` 4 · default 6 · `wide` 8 · `full` 12; widgets have a drag handle and a `…` menu; layout saved per user/org/brand in the browser (`dashboardLayout.ts`) | 經營概況 |
| Surface | `.surface` > `.surface-header` + `.surface-body` | the card every widget, form and list sits in | everywhere |
| Workspace split | `.workspace-split` = `.workspace-subnav` 188px + `.workspace-content` | left vertical sub-navigation, sticky; right content | 品牌智庫 (8 tabs), 設定, 產品詳情 |
| Table surface | `.table-surface` | bordered 10px, `overflow-x:auto`; header fill, 13/16 cell padding, numbers right-aligned tabular, row hover tint | 活動概況, 訂單, 產品清單 |
| Task list | `InboxWidget` rows | icon disc · title / count line · chevron; footer link 「開啟收件匣 →」 | 待處理, 收件匣 |
| Form section | `.form-section` (max 760) | label above control, `Input`/`Textarea`/`select`, 儲存 at the end | 設定, 產品 |
| Intake workspace | `.intake-workspace` (max 1240) | step rail + one step at a time | 建檔精靈 |
| Auth split | `.auth-layout` / `.auth-aside` | left tinted aside, right form | 登入, 接受邀請 |
| Prose | `--width-prose` 68ch | continuous reading only | 顧問分析報告 |

Width caps are readability caps, not bugs: a 68ch paragraph or a 760px form beside white space is
correct. Cards that carry data use the full grid cell.

### 5.1 Staged workspace (檔期規劃)

A long flow is a sequence of stages, each one screen, never one page that grows:

基本設定 → 方案比較 → 投放結構 → 素材準備

| Stage | Left / main | Right |
|---|---|---|
| 基本設定 | product, goal, dates | pinned budget and settings summary |
| 方案比較 | plan summaries as a list | the selected plan, readable; side-by-side only when structured fields exist |
| 投放結構 | collapsible hierarchy tree | the selected node's budget and content (replaces nested cards) |
| 素材準備 | creative list | content, coordinates, copy actions |

- 配對、核准、撤回、結算 live in the stage they belong to and are enabled by **backend state**, never by
  the stage number the frontend is on.
- 核准 keeps its meaning: the button must not look like it publishes an ad (`CONSTITUTION.md` rule 9).
- Background work shows the stage being processed, success or failure, and a retry; leaving and returning
  restores it. No percentage bar without real progress data.

### 5.2 Screen assignments

| Screen | Layout |
|---|---|
| 經營概況 (approved) | KPI row 廣告花費・曝光・點擊・點擊率・ROAS; middle: 活動花費分布 + 素材成效比較; bottom: 活動概況 table + 待處理; views switchable, 自訂版面 picks metrics and drags cards. Future brand metrics (粉絲、長粉、Reels／貼文觀看) join the same card system as new views, only once their data source exists |
| 品牌總覽 (跨品牌) | one brand: its own layout; many brands: health, revenue and next step compared; brand entry and task entry separated |
| 收件匣 | compact list + detail pane; 待處理／已處理 toggle; brand and severity legible at a glance |
| 品牌智庫 | workspace split: vertical categories with counts, list in the middle, detail on the right; never two rows of horizontal tabs. 官方素材 browses thumbnails; 事實／規則／宣稱 are lists |
| 素材工作檯 | workspace split: brief list left (進行中／已關閉／全部), brief detail right — copy tabs 短／中／長 with one fixed line each, image prompts with the user's count and the 1.5× grey line, rounds, 採用；新工單 in the side panel |
| 產品清單 | comparison table; product name, 待確認 count and cost status emphasised |
| 產品詳情 | product title + the same `PageTabs`; 再次調研 behind an explicit action |
| 訂單與顧客 | tabs 概況・訂單・商品毛利・通路營收・口徑紀錄 |
| 設定 | grouped subnav: 組織・AI 與費用・廣告連線・品牌參數 |
| 建檔精靈 | resumable steps; external AI research as 複製交接內容 → 等待結果 → 貼回驗證 |
| 顧問分析報告 | reading and print layout, plus a section index, data version and stale state |
| 登入／接受邀請 | auth split; return to the invitation after login |

---

## 6. Components

Use what exists; do not hand-roll a control that the kit has. Adding a kit component is a layout
change (ADR 0060: `layout/` is the shared kit) and needs the shadcn generator, not a copy.

| Need | Use | Notes |
|---|---|---|
| Button | `ui/button` | `default` = the one primary action on screen; `outline` = secondary; `ghost` = icon / row actions; `destructive` only for delete; `link` inline. Sizes `sm` in table rows, `default` elsewhere. |
| Pill / status | `ui/badge` | `secondary` for 示意資料 and counts; status dot + text for connection state; `destructive` for failed |
| Tabs (in-card) | `ui/tabs` | inside a surface; page-level switching uses `PageTabs` |
| Write / edit | `SidePanel` (`ui/sheet`) | **writes happen in the right-hand panel**, default 28rem, wider when the content needs it; ESC closes, focus trapped; no modal forms. A few fields may be edited in place; a full flow uses the main workspace (§5.1) |
| Confirm | `ui/dialog` | only to confirm an irreversible or money-moving action; copy states the consequence |
| Explanation | `ui/tooltip` on a `?` affordance | one per genuinely complex thing; says what it *is*, not how to think |
| Menu | `ui/dropdown-menu` | org menu, widget `…`, row overflow |
| Inputs | `ui/input`, `ui/textarea`, native `select` | native `<input type=date>` for dates |
| Loading | `Skeleton` | shaped like the content it replaces |
| Empty / error | `EmptyState` | title · why · one next-step button (`actionHref` or `onAction` 重新載入) |
| Paging | `Pager` | client-side slices, default page size in `usePagination.ts` |
| Copy value | `CopyIconButton` | any id / key the user might paste elsewhere |
| Header / tabs | `PageHeader`, `PageTabs` | §4 |

Retired (deleted 2026-09-07, old look, zero importers): `FluidCard`, `StatBig`, `ProgressRing`,
`TrendSparkline`, `StatusLight`. Do not bring them back; build KPI tiles with `.dashboard-metrics`.

---

## 7. Data display

- **Formats**: money `NT$ 28,860` (no decimals, thousands separator, space after `NT$`) for the
  system's own TWD figures (budgets, own-site orders); **money that came from a platform row carries
  that row's currency** — `28,860 TWD`, `1,250 USD` (`formatMoney(value, currency)`, ticket past-ads 07,
  2026-09-08) — because one brand may bind accounts in two currencies (ADR 0057 §4) and `NT$` on a USD
  row is a wrong label; counts `1,332,500`; rate `1.91%`; ROAS `3.21x`; every number tabular. Format in
  one place (`number()` in `DashboardWidgets.tsx`, `format.ts`); do not re-implement per screen.
- **Caption every number**: what window (本月累計), what source (平台回報), what basis (保守／樂觀).
- **Two-basis ROAS** is drawn as a dumbbell: filled dot conservative (chart 1), hollow dot optimistic
  (chart 4), joined by a line; a dashed vertical breakeven line in `--color-warning` labelled
  「打平線 1.43x」; legend below; footnote 「兩種計算口徑，非統計信賴區間」. Never collapse it to one number.
- **Distribution bars** (`.chart-bar` 9px, radius 3): label left, value right, bars in series order,
  total row separated by a hairline, footnote states the sort and the cap (「依花費排序，最多顯示 5 個活動」).
- **Charts** answer one question each and exist for glance-legibility, not as filler; an information-dense
  overview may carry many. Axis labels and legends use muted text; no 3D, no gradients on data marks
  except the approved bar gradient, no chart junk. ECharts only for the coordinate quadrant; everything
  else is HTML/CSS.
- **Empty and partial**: 「未追蹤」 for a channel not connected, 「累積中」 for a window not closed,
  「成本還沒登記，算不出毛利（3 個 SKU）」 for a blocked derivation. Never fabricate a date range,
  organic metric or profit figure the API does not return.

Three product truths every data screen must respect:

1. **營收、毛利、淨利 are three different numbers.** Revenue is all channels; gross margin comes from
   website item costs; nothing is ever labelled 「本月淨賺多少」.
2. **Conservative and optimistic ROAS are both visible**, with tracking coverage beside them
   (the dumbbell above). Two calculation bases, never a confidence interval.
3. **Insufficient data is its own state.** 「沒有警示」 and 「資料足夠、表現正常」 are different states
   and look different. Missing cost shows *how many* items and a 補登 entry point, not a paragraph
   inside the KPI tile.

A trend chart or a date-range filter appears only after the API returns a daily series and accepts the
range; appearance is never added ahead of data.

---

## 8. Copy

- Interface text is standard UI vocabulary: 生成、下一步、接受、拒絕、儲存、匯入、產生報表、查看成效、
  自訂版面、新增檢視. Page and card titles are noun phrases.
- Never a colloquial question or first person as a control label
  (banned shape: 「看這期賺了多少」「我不喜歡，下一步」).
- Terms keep their industry name (ROAS, 曝光, 點擊率); the one-line analogy for a beginner lives in
  the `?` tooltip, not in the label. Beginner-friendly means the conventional word, not a sentence
  explaining the button.
- Status words: 處理中 · 完成 · 失敗 · 未追蹤 · 累積中 · 待補登 · 待裁決 · 待產出. Sample data: 示意資料.
- Traditional Chinese throughout; Latin only for units and product names (Meta Ads, ROAS, NT$).

---

## 9. Gates (every frontend ticket)

1. `npm run build` (tsc + vite) · `npm run lint` · `npm test`.
2. `frontend/src/designTokens.test.ts` — no raw hex outside `tokens.css` / `chartColors.ts`,
   no `font-family` outside `tokens.css`.
3. `npm run e2e`: `smoke`, `width-overflow` (at 1280, `#root.scrollWidth <= innerWidth` on every
   route — the `documentElement` formula is green no matter what and must not be reused),
   `dashboard-layout`.
4. Real-browser acceptance on a **fresh browser session and a restarted backend**; a cached bundle
   shows old code. Check 1024 and 1920, and the loading / empty / error states, not only the happy path.
5. A new gate is proven red once before it counts.
6. The three representative screens — 經營概況 (data), 檔期規劃 (flow), 品牌智庫 (data management) —
   are the acceptance set for any change to the kit or the shell, each in **empty, normal and heavy
   data**. Empty screenshots alone never prove a layout.

---

## 10. New screen checklist

1. `PageHeader` + `PageTabs` first; content in a §5 pattern; nothing scrolls past one screen of
   overview — split into tabs.
2. Every control from §6; every colour, size and radius from `tokens.css`.
3. Every number formatted and captioned per §7; every empty state says why.
4. Every label passes §8.
5. Gates §9, then look at it in a browser at 1024 and 1920.
