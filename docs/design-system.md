# Design system — 行銷駕駛艙

> 2026-09-10: ADR numbers below are git history (`docs/adr/` was removed with the skeleton-slice workflow); the constitution is gone, this document is the frontend rule on its own.

**Status: in force since 2026-09-07. This is the only frontend rule document.**
Decision record: ADR 0065. Reference image: `docs/design-system.png` (the dashboard the user approved
2026-09-07; its numbers are sample data, its look is the standard). Token source of truth:
`frontend/src/styles/tokens.css`. Component kit: `frontend/src/components/layout/` (shared, ADR 0060)
and `frontend/src/components/layout/ui/` (shadcn/ui, new-york, Radix).

Current user-authorized scope → this document → ticket details. Apply established patterns directly; ask only when a material product/design choice is unresolved. Update this document when an authorized change alters a shared rule.
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
3. **Honest empties.** Missing/untracked data is never silently `0` or an empty card; explain why.
   A documented not-applicable placeholder may use `—`; do not confuse it with measured zero. Use labels
   (「本月還沒有訂單」「未追蹤」「累積中」). Sample data on screen always carries the 示意資料 badge.
4. **Two readings, both shown.** Where the system has two calculation bases (conservative / optimistic
   ROAS) both are drawn; the interface never hides uncertainty to look simpler.
5. **Calm surface.** Cool grey ground, white cards, one violet accent, one typeface family, restrained
   motion. Nothing decorative that does not carry information.
6. 照顧新手與老手，一個頁面預設顯示簡單化面，進階配置才給熟手。預設版面配置永遠乾淨簡潔，
   照顧新手使用者優先，新手可以基本輕鬆上手，AI 丟數個建議讓使用者參考，使用者看完沒問題基本
   只管點下一步就可以無壓力排程廣告；老手也可以針對 AI 給的建議去做細部調整（但都是預設在
   原始頁面下，不點開是不會看到），不要把版面做的像是另外一個 meta 後台／google 後台。
   進階設定一律是同一頁裡的收合區塊（`Disclosure`），不是模式切換、不是第二頁、不是第二份資料模型。

### 1.7 UIUX acceptance goal (user ruling 2026-09-20)

Passing functional tests does not mean the UI is accepted. A screen is accepted only when a first-time,
non-technical user can answer these from the screen alone, without an AI, the docs or the source code:
**where am I · what does this step do · what happens when I press the main button · where are next, back,
accept, reject and exit.** 使用者原話：「不是越簡單越好，也不是越豐富越好」「絕對不是用新手指南或說明書教使用者」。

- The layout carries the guidance: hierarchy, position, grouping, one dominant primary action, visible step
  position. Explanatory paragraphs, stacked disclaimers, tutorial overlays and "how to use" text are a design
  failure, not a fix. If a screen needs a sentence to explain a control, redesign the control.
- Not a wizard that hides decisions: the user still sees the evidence and makes the choice. Simplify the
  path, not the judgement. Honest unknowns (principle 4, F12) stay; say each once, where the number is.
- New UI work starts from the information hierarchy and the reference image (`預覽圖/`, `docs/design/ads/`),
  then wires data. Re-skinning an existing page by adding notes, status lines and forms to it is not a redesign.
- Every UI issue states its reference image and ends with a side-by-side screenshot review against it plus
  this five-question check, recorded as evidence. Flow, data and test evidence cannot substitute for it.
- Prefer visual encodings over prose where they are truthful: before/after, deltas, status chips, progress,
  thumbnails. Text budget per step: one title, one line of purpose, labels; everything else is folded or cut.

**Worker self-check before handing in a UI issue** (the defect classes review kept finding in F19):
1. Numeric edges: 0, negative, `null`/unknown are rejected or shown as unknown — never saved or printed as a real value.
2. No fake success: do not navigate away or show "saved" until the server confirmed and nothing stays unresolved.
3. A value the system derived is never persisted as the user's choice unless the user changed it.
4. Money and ratios go through the kit formatter (at most two decimals); no raw floats such as `346.667`.
5. At 1024 and 1920 with the longest real names: nothing truncates a control, arrow or count; chips do not squeeze the title.
6. Keyboard: tab order follows reading order and the focus ring is fully visible (not clipped by overflow).
7. Reviewed behaviour of other issues stays as it is; never change product code to make a test easier — report it.
8. Your own preview/e2e server uses port 8731 + issue number (I03 → 8734); 8720 belongs to harness merge/integrate.

**The HTML prototype is the spec (user ruling 2026-09-21, restated 2026-09-22).** A UI issue names the prototype file,
the screen's function and its route; the worker opens that HTML in a browser and reads its markup, states and
interactions — that is the primary source. Screenshots of it at 1024 and 1920 are only the left half of the side-by-side
evidence, never a substitute for the HTML. The issue adds the API calls that feed the screen and nothing else about the
layout — no prose re-description of the screen. Workers develop from minute one against the realistic
fixture (longest real names, drafts, no-target, decimal costs, imported campaigns), not against tidy sample data. A worker
hands in side-by-side images (reference | built) at both widths; the lead compares them first and returns anything that
does not match before any review. The user reviews once, after the whole batch is merged, on one side-by-side page per
screen, and answers pass / what is wrong; the fixes run as one round. Agents never stop mid-batch to ask for acceptance.

---

## F12. 一般流程與同頁進階（已驗收結案）

本節記錄 F12 已落地的介面規則；功能整合驗證通過，使用者於 2026-09-18 確認結案。沿用既有逐步流程；Full auto 另案。一般層顯示當前結果／建議、必要摘要、主要下一步；「查看詳情」只讀原因與紀錄，「進階設定」修改現有支持的參數。兩者同頁收合，不是兩套資料或全站模式切換。

- 預算、期間、商品、目標、必要缺漏、未上線、未追蹤及影響判讀的未知直接可見。保守／樂觀口徑仍同時呈現；簡化不能省略不確定性。
- 收起不儲存、不取消、不丟未存輸入。已展開的表單保留草稿，隱藏內容不能取得鍵盤焦點；未展開的昂貴內容不預先執行。離開 dirty 編輯有保護，重新讀取不能靜默覆蓋。草稿不得跨品牌／活動。
- 收起後可見生效摘要、已自訂、未儲存及作用範圍。恢復按明確範圍執行；既有整卡恢復就標明整卡，不假裝逐項恢復。僅新比較參數接口要求逐項還原，其他 legacy API 不因本輪擴寫。
- 必填資料若在收合內，一般層顯示缺漏及直達操作，展開並定位欄位。不能只留灰按鈕。所有純圖示操作有具體可存取名稱。
- 成效摘要先於選用比較；模擬工具不進普通品牌流程。素材必要複製、人工上架與現階段連接設定仍為一般操作，不能在替代能力尚未存在時藏掉。
- 設定從「品牌 AI 費用上限」開始，保留組織本月 AI 費用摘要，避免與廣告預算混淆。技術設定與智庫研究／座標在本頁進階入口；既有 URL 深連結仍有效並展開目的內容，不改全站路由架構。通知沿既有 resolved 語意使用「標記已處理」，不藉文案宣稱自動修復。
- 本輪不增加 LLM 呼叫。數據整理、計算、顯示文案與欄位映射由程式完成；平台名稱及能力由既有資料／公開接口取得。不得新增指定某平台、品牌、產業的預設。未知能力如實顯示不可用。
- 客觀驗收按 docs/verification.md：鍵盤、1024／1920、loading／empty／error；此處窄版指 §3 既有桌面下限 1024，不擴充手機或平板支援。不丟草稿、設定生效、可選功能不擋主流程。沿用 kit 與模組入口，不建立通用設定引擎。

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
│   ├── 品牌經營:  經營概況 · 投放中心 · 素材工作檯 · 訂單與顧客
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
- Route definitions in `frontend/src/App.tsx` are authoritative: `/brands/:id/schedule` (檔期規劃) is retired, replaced
  by `/brands/:id/ads` and its two sibling routes (投放中心 清單頁／建立 Campaign／Campaign 工作區).
  The `/app` basename is fixed; all of the above is done with in-page tabs and layout.

---

## 4. Page anatomy

Every routed screen, top to bottom:

1. **`PageHeader`** — `h1` noun phrase (經營概況、投放中心、產品), muted subtitle (brand name +
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

### 5.1 投放中心：清單頁 ＋ Campaign 工作區

投放中心：首頁 ＋ 清單頁 ＋ Campaign 工作區（五個分頁：總覽／策略/投放結構/素材/成效，分頁狀態在查詢字串）。
`/brands/:id/ads` 是首頁（v7 決定佇列＋月預算＋活動卡，見下方「F19 現況」，不是清單頁），
`/brands/:id/ads/campaigns` 才是清單頁（Campaign 清單 + 建立 Campaign），`/brands/:id/ads/campaigns/:id` 是工作區。
同樣的規則沿用自舊版的 staged workspace：

- 發布、配對、核准、撤回、結算 live in the tab they belong to and are enabled by **backend state**, never
  by which tab the frontend is on.
- 核准 keeps its meaning: the button must not look like it publishes an ad.
- Background work shows what is being processed, success or failure, and a retry; leaving and returning
  restores it. No percentage bar without real progress data.

F19 現況（取代舊版 F04 首頁四塊）：首頁改照 v7 原型（`docs/design/ads/prototype-v7-ads-center.html`
`home()`）——`PageHeader`「今天需要你決定的事」＋開著幾件／都處理完了，右側「每月回顧」是灰階
不可互動的 chip（`ReservedSlotCard` 同一條規則：連 disabled 假按鈕都不做，一個元素裡印
「接上後開放」）、加入既有活動、建立投放計畫；`需要你決定的事`（`ChangeAttention`）只在真的有
待確認清單時才佔版面，沒有時整塊不算——它自己一次請求決定，首頁不另外打第二次同一支 API 判斷
要不要顯示。下面 `1.9fr/1fr` 格線，左 `DecisionQueue`（品牌層停損／變差決定佇列；只印分類 chip、
廣告名稱與連結，沒有 `action_url` 的列不給連結，也不印任何金額——那些數字要等 F19-I06 的
`result_label` 才有依據，是 I03 的範圍）、右 `BudgetCard`（月可新增承諾大數字＋已花／預留／可用
分段長條，header／`調整` 對齊跟其他卡一致，調整沿用既有 `MonthlyBudgetPanel` 編輯，不重刻一份）；
再下方「活動」＋「查看全部活動 →」連到清單頁＋`CampaignCards`（沿用 `CampaignTile`，只列未結案的
Campaign，含既有平台活動；已結案的從清單頁找）。三支元件都在 `components/ads/home/`；`DecisionQueue`
／`BudgetCard`／`CampaignCards` 各自獨立打自己的 API、各自的 loading／error＋重試殼——三塊裡一塊
讀取失敗不會拖累另外兩塊。I02 定版面與骨架，佇列列與活動卡各自的細節（目標、五分類條）留給
I03／I04，設定目標頁是 I05。清單頁、「理解如下」確認畫面、策略頁按鈕、工作區總覽不在這次範圍內，
沿用既有寫法。判斷帶／時間軸／建檔檢查表元件檔仍在，但首頁不再引用。

### 5.2 Screen assignments

| Screen | Layout |
|---|---|
| 經營概況 (approved) | KPI row 廣告花費・曝光・點擊・點擊率・ROAS; middle: 活動花費分布 + 素材成效比較; bottom: 活動概況 table + 待處理; views switchable, 自訂版面 picks metrics and drags cards. Future brand metrics (粉絲、長粉、Reels／貼文觀看) join the same card system as new views, only once their data source exists |
| 品牌總覽 (跨品牌) | one brand: its own layout; many brands: health, revenue and next step compared; brand entry and task entry separated |
| 收件匣 | compact list + detail pane; 待處理／已處理 toggle; brand and severity legible at a glance |
| 品牌智庫 | workspace split: vertical categories with counts, list in the middle, detail on the right; never two rows of horizontal tabs. 官方素材 browses thumbnails; 事實／規則／宣稱 are lists |
| 投放中心 | 首頁（v7，F19）：`PageHeader`「今天需要你決定的事」＋件數；`1.9fr/1fr` 格線左 `DecisionQueue`（品牌層停損／變差佇列）右 `BudgetCard`（月可新增承諾大數字＋分段長條）；下方「活動」＋`CampaignCards`（`CampaignTile` 卡片，含既有平台活動）; 清單頁：`.table-surface` of Campaign（name, status pill, dates, objective, budget, spend so far）; 建立 Campaign 先過「理解如下」確認畫面（`StepIndicator`＋`FieldCard`）才花第二次模型錢; 工作區：五個 `PageTabs`（總覽／策略/投放結構/素材/成效），分頁狀態在查詢字串，策略頁按鈕真的會動 |
| 素材工作檯 | four screens, one IA: 入口（pack card grid／list, search ＋ status pills ＋ 最近使用 ＋ 快速開始） → 任務包（meta strip・摘要・完成條件・素材組 table） → 素材組 studio（tabs per 產物類型, versions as history, 生成設定） → 自由創作（AI 解析 free text → editable sets, two-click flow）. The pack rail and set rail are pack-local／set-local, not the OS sidebar, not a new shared kit component |
| 產品清單 | comparison table; product name, 待確認 count and cost status emphasised |
| 產品詳情 | product title + the same `PageTabs`; 再次調研 behind an explicit action |
| 訂單與顧客 | tabs 概況・訂單・商品毛利・通路營收・口徑紀錄 |
| 設定 | grouped subnav: 組織・AI 與費用・廣告連線・品牌參數 |
| 建檔精靈 | resumable steps; in-system research and confirmed facts per `docs/architecture/intake.md` |
| 顧問分析報告 | reading and print layout, plus a section index, data version and stale state |
| 登入／接受邀請 | auth split; return to the invitation after login |

### 5.3 投放中心的版面樣式

視覺真相是 `docs/design/ads/*.png`；原型與圖不一致時以圖為準。首頁例外（F19 起）：
`01-home.png` 已由 `docs/design/ads/prototype-v7-ads-center.html` 的 `home()` 取代，
首頁版面與圖不一致時以這支原型為準；表列「01-home」的樣式仍在其他畫面（如 Campaign 卡）有效，
只是首頁本身不再照 png 的舊四塊排版。

| 樣式 | 元件 | 形狀 | 出現在哪一張參考圖 |
|---|---|---|---|
| 判斷帶 | `JudgmentBand` | 整寬 tinted band，左圖示圓盤、右一句判斷＋一行事實 | 01-home, 05-strategy, 06-workspace-overview |
| 決定卡 | `DecisionCard` | `surface`，header 帶件數 badge，每列圖示＋標題＋理由＋三顆按鈕 | 01-home, 06-workspace-overview |
| Campaign 卡 | `CampaignTile` | `surface` 可點，名稱／狀態、花費進度條、底部 tinted 判斷區塊 | 01-home, 02-campaign-list |
| 數字條 | `KpiStrip` | 一張 `surface` 裡 3–5 等寬格，格間 1px 直線 | 05-strategy, 06-workspace-overview |
| 時間軸 | `ActionTimeline` | 垂直線＋小圓點，每筆時間／標題／說明 | 01-home, 06-workspace-overview |
| 佔位卡 | `ReservedSlotCard` | `surface` 全灰階、不可點、右上 tag badge | 01-home, 06-workspace-overview, 10-strategy-advanced |
| 步驟指示 | `StepIndicator` | 水平三步，圓圈＋連接線 | 04-understood |
| 摘要欄位卡 | `FieldCard` | `surface` 一格，圖示＋label＋value＋編輯鈕 | 04-understood |

`Disclosure`（進階收合）不是版面樣式而是規則載體：R9「不點開是不會看到」的機器實作，見上方
§1 第 6 條。

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
  except the approved bar gradient, no chart junk. ECharts 用於座標象限與投放中心的成效趨勢圖，其餘一律
  HTML/CSS。
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

## 9. Verification

Use `docs/verification.md` for commands, stage coverage and browser procedure. Token tests run as part of frontend tests; do not repeat the same test separately. Shared shell/kit layout changes cover 經營概況、投放中心、品牌智庫 at 1024/1920 in empty/normal/heavy states. Local changes check their affected screen and relevant states. Preserve accessibility, truthful data display and overflow checks (`#root.scrollWidth`, not `documentElement`).

## 10. New screen checklist

1. `PageHeader` + `PageTabs` first; content in a §5 pattern; nothing scrolls past one screen of
   overview — split into tabs.
2. Every control from §6; every colour, size and radius from `tokens.css`.
3. Every number formatted and captioned per §7; every empty state says why.
4. Every label passes §8.
5. Use §9 evidence once; reuse current-tree browser checks rather than repeating them for this checklist.
