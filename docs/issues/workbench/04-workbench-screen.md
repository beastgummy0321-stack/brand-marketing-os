# 04 — the 素材工作檯 screen (brief list · brief detail · 新工單 panel)

route=C (new screen of a new module: the 15th route, a sidebar entry, a feature folder behind
`index.ts` — ADR 0060/0065 boundaries). Serves the board row 素材工作檯 (spec.md in this folder).
Tickets 02–03 landed the tables, jobs and `/api/workbench/*`; this ticket is the first thing the
user can click. The prototype step the spec listed is folded into this ticket: the API exists
first, so the walker and the user click the real screen with seed data (`brd_bughunt`).

**Design rules are `docs/design-system.md` only (ADR 0065).** Every control from §6, every colour
and size from `tokens.css`, page anatomy §4, copy §8, gates §9, the §10 checklist. This ticket
edits the design system in exactly three places (§4 below) and invents no rule.

## What

### 1. Route, nav, feature folder

- `frontend/src/App.tsx`: `<Route path="/brands/:brandId/workbench" element={<WorkbenchRoute />} />`
  beside the `library` route (`:62`), `WorkbenchRoute` shaped like `LibraryRoute` (`:232-239`),
  importing from `@/components/workbench` (the `index.ts`, never a file inside).
- `frontend/src/components/layout/Sidebar.tsx:29` `BRAND_NAV`: insert
  `{ label: "素材工作檯", suffix: "/workbench", icon: <a lucide-react 1.28 icon the implementer
  verifies exists in node_modules, e.g. Wand2 or Sparkles> }` **after 檔期規劃** so it falls in the
  品牌經營 group; the `slice(0, 3)` / `slice(3)` split at `:170,:181` becomes `slice(0, 4)` /
  `slice(4)` (design-system §3 shell diagram lists 品牌經營 as 經營概況 · 檔期規劃 · 訂單與顧客 — it
  gains 素材工作檯 between them).
- `frontend/src/components/workbench/index.ts` exports `WorkbenchPage` only. Files:
  `WorkbenchPage.tsx`, `BriefList.tsx`, `BriefDetail.tsx`, `NewBriefPanel.tsx`, `copy.ts`
  (the fixed UI strings below). Everything reads `@/lib/workbenchApi` (ticket 03), products from
  `@/lib/productsApi`, coordinates from `@/lib/coordinatesApi`, shared kit from
  `@/components/layout/*` only (dependency-cruiser).

### 2. `WorkbenchPage` — §5 workspace split

`PageHeader` title 「素材工作檯」, description = brand name + 「文案、圖片提示詞與腳本在這裡生成；投放時到檔期規劃複製」,
actions: `Button` 「新工單」 (the one primary action) opening `NewBriefPanel`.
Below: `.workspace-split` — left `.workspace-subnav` = `BriefList`, right `.workspace-content` =
`BriefDetail` of the selected brief (query string `?brief=<id>`; none selected → `EmptyState`
「選一張工單」 / 「左側清單是這個品牌的工單；還沒有就按右上角新工單」).

Data: `fetchBriefs(brandId, status)` on mount and after every action; while any listed brief is
`queued`/`running`, poll `fetchBrief` for the selected one every 2 s (the interval
`SchedulePage.tsx:186` uses) and the list every 10 s; stop when nothing runs. Loading → `Skeleton`
shaped like the list; error → `EmptyState` with 重新載入.

### 3. `BriefList`

Filter row (`PageTabs`-style segmented, in the subnav): 進行中 (default, `status=active`) · 已關閉 ·
全部. Rows newest first: kind label (文案／圖片提示詞／影片腳本／自由生成／排程節點), one line =
`source_ref.node_name` for schedule briefs or the first 30 字 of `request.free_text` or the product
name, status `Badge` (處理中 for queued/running · 完成 · 失敗 `destructive` · 已關閉 `secondary`),
`created_at` relative. Selected row highlighted. Empty filter → `EmptyState` 「沒有工單」 with why.

### 4. `BriefDetail`

Header: kind label + product name + style label + status badge; row actions (`ghost` buttons):
關閉／重新開啟, 刪除 (`ui/dialog` confirm: 「刪除這張工單會一起刪掉它的所有產出，無法復原。」),
and 到檔期規劃 link when `source_kind === "schedule_node"`.

`last_error` when status 失敗: one `role="alert"` line + `Button variant="outline"` 「重新產出」
(runs the failed part again).

Parts, each a `surface` card, shown only if the brief's kind allows the part (ticket 03 table):

**文案** (`part=copy`): round switcher when >1 round (「第 N 輪」 + 已採用 badge); `ui/tabs` 短版 ·
中版 · 長版; above each tab's list the fixed one-liner from `copy.ts`:
短 「折疊前一口氣講完，適合再行銷、已認識品牌的人」· 中 「痛點→證明→優惠，適合第一次看到你的人」·
長 「說故事，適合高單價、需要被說服的商品」; each variant = text + 字數 caption + `CopyIconButton`;
a ❌ validation line under a variant that missed its band (from `body_json.validation`, text
verbatim). Below the tabs: 標題 ×5 and 說明 ×5 lists, each with `CopyIconButton`, and a 「全部複製」
`outline` button that copies the selected length's variants + headlines + descriptions as plain
text separated by blank lines. Footer buttons: 採用這一輪 (disabled when already adopted),
再產一輪 (`runPart(copy)`), both disabled while running.

**圖片提示詞** (`part=image_prompt`): a numeric `Input` 「目標張數」 (1–10, required, no default
value — the field starts empty) beside the grey line **exactly**:
「AI 生圖有不確定性，建議多產幾條備用，建議目標張數的 1.5 倍」; a numeric `Input` 「要幾條提示詞」
(1–30, required, empty) and `Button` 「產提示詞」 → `runPart(image_prompt, count)`. For a manual
`image_prompt` brief the 「圖上文字」 the user typed at creation is listed read-only above. When
the brief has no copy output and no `on_image_texts`, the button is disabled with a tooltip
「先產文案，或在工單填圖上文字」 (mirrors the 409 from ticket 03). Rounds switcher as above. Each
rendered prompt (`body_json.rendered[i]`) in a `<pre>`-styled block with its 字數 caption and a
`CopyIconButton`; ❌ validation lines verbatim. Beside the block list, the product's reference
photo thumbnail when `fetchLibrary(brandId).assets` has an image for `product_id`
(`asset_kind` product photo, first by `created_at`), else one muted line 「尚無商品參考照，圖片工具
需要它才能保住商品外觀」 with a link to 品牌智庫 → 官方素材.

**影片腳本** / **自由** parts: render `body_json` as labelled text blocks with `CopyIconButton`
(no tabs); 再產一輪 button. (Their task files land in ticket 05; until then the run returns 失敗
with the FileNotFoundError text — shown, not hidden.)

### 5. `NewBriefPanel` — `SidePanel` (§6: writes happen in the right-hand panel)

Fields, `form-section` order: 種類 (native `select`: 文案 / 圖片提示詞 / 影片腳本 / 自由生成),
產品 (`select`, optional, from `fetchProducts`), 風格 (`select` from `fetchStyles()`, default
`ugc`), 視覺調性 (`select`: 不指定 / 暗調強對比 / 暖調生活), 切角 (`select`, optional, the brand's
`angle` coordinates from `fetchCoordinates`, label shown, stored into `coordinates.angle`),
畫面概念 (`Textarea`, optional), 需求說明 (`Textarea` → `request.free_text`), 帶品牌資料
(checkbox, default on → `request.use_brand_knowledge`), and — only when 種類 = 圖片提示詞 —
圖上文字 (1–5 `Input`s, ≤27 字 each → `request.on_image_texts`, required, with the hint
「圖上出現的字必須是你寫的，不讓模型自己編」) and 要幾條提示詞 (1–30 → `request.image_prompt_count`).
Submit `Button` 「建立工單」 → `createBrief` → panel closes, list refreshes, new brief selected.
API error → `role="alert"` line with `errorMessageFrom` text; 400 codes map to field-level text
(`style_unknown`, `product_unknown`, `on_image_texts_required`, `count_out_of_range`).

### 6. Design-system edits (`docs/design-system.md`), three places, nothing else

- §3 shell diagram line 品牌經營 → `經營概況 · 檔期規劃 · 素材工作檯 · 訂單與顧客`; the sentence
  「The 14 routes and the `/app` basename are fixed」 → 「The 15 routes (素材工作檯 added 2026-09-09,
  ADR 0068) and the `/app` basename are fixed」.
- §5.2 new row: `| 素材工作檯 | workspace split: brief list left (進行中／已關閉／全部), brief detail
  right — copy tabs 短／中／長 with one fixed line each, image prompts with the user's count and the
  1.5× grey line, rounds, 採用；新工單 in the side panel |`.
- §5.1 stage 素材準備 row unchanged (ticket 05 fills it).

### 7. Gates and e2e

- `frontend/e2e/width-overflow.spec.ts`: add `/brands/:brandId/workbench` to the walked routes
  (the header comment 「14 條路由…共測 13 條」 becomes 15／14); `smoke.spec.ts`: one step — open
  `/app/brands/<brandId>/workbench`, expect `h1` 「素材工作檯」 and the 新工單 button.
- No unit test for the screen (test-suite shape rule); the e2e smoke is the check.

### 8. Fixed UI strings (`copy.ts`)

The three one-liners above; status words 處理中 · 完成 · 失敗 · 已關閉; buttons 新工單 · 建立工單 ·
產提示詞 · 再產一輪 · 採用這一輪 · 全部複製 · 關閉 · 重新開啟 · 刪除 · 重新產出 · 到檔期規劃; the
1.5× grey line verbatim. No first-person, no colloquial question (design-system §8).

## How we know it's done

1. `cd frontend && npm run build && npm run lint && npm test` green (includes `designTokens.test.ts` and dependency-cruiser — name the script that runs depcruise in the report).
2. `cd frontend && npm run e2e` green with the two edits in §7 (the new route in width-overflow at 1280; the smoke step).
3. Backend gate unchanged: `uv run ruff check app`, `uv run pyright`, `uv run pytest app/tests/test_workbench.py app/tests/test_workbench_api.py -q` green (nothing in `app/` changes; run to prove it).
4. `git diff --name-only` ⊆ Shared files touched + the new folder.
5. WALK (by the acceptance walker, not the implementer) on a **restarted** 8720 backend and a fresh browser, `brd_bughunt`, at 1280 and 1920:
   1. Sidebar shows 素材工作檯 under 檔期規劃; click → `h1` 素材工作檯, empty state text visible.
   2. 新工單 → panel opens; 種類 文案, 產品 the seed product, 需求說明 「測試」→ 建立工單 → panel closes, list has one row 處理中, detail shows the brief.
   3. Wait (poll) until status 完成 or 失敗 (codex_cli local: ~60 s); if 完成: 文案 card shows three tabs, 5/3/2 variants with 字數 captions, five headlines, five descriptions, each with a copy icon; click one copy icon → clipboard holds that text (playwright `page.evaluate(navigator.clipboard.readText)`).
   4. 圖片提示詞 card: 目標張數 empty, grey line text exact; enter 目標張數 2, 要幾條提示詞 3 → 產提示詞 → 處理中 → 完成 → three 9-line blocks, each 字數 200–250 caption, copy icons.
   5. 採用這一輪 → badge 已採用; 關閉 → row moves out of 進行中 into 已關閉; 重新開啟 → back; 刪除 → dialog → confirm → row gone, `GET /api/workbench/brands/…/briefs/<id>` 404.
   6. 新工單 with 種類 圖片提示詞 and no 圖上文字 → field error text, no request sent; fill one text → created.
   Screenshot each step; the first ❌ is red.

## Shared files touched

Searched 2026-09-09 with `git grep -n -F` / `grep -n`; names that change meaning:

`BRAND_NAV` (gains a row; the slice split shifts):
```
frontend/src/components/layout/Sidebar.tsx:29:const BRAND_NAV = [
frontend/src/components/layout/Sidebar.tsx:170:              {BRAND_NAV.slice(0, 3).map((n) =>
frontend/src/components/layout/Sidebar.tsx:181:              {BRAND_NAV.slice(3).map((n) =>
```

「14 routes」 (becomes 15):
```
docs/design-system.md:166:- The 14 routes and the `/app` basename are fixed; all of the above is done with in-page tabs and layout.
frontend/e2e/width-overflow.spec.ts:3:/** 殼寬回歸閘門（票 u2-fluid-shell-to-1920，ADR 0051 rule 4／Consequences）：14 條路由
frontend/e2e/width-overflow.spec.ts:22: * 14 條路由（`App.tsx`）扣掉 `/accept-invite`，共測 13 條。 */
frontend/e2e/width-overflow.spec.ts:25:test("14 條路由（扣 /accept-invite）在 1280 寬不橫向溢出", async ({ page }) => {
```
(`docs/adr/retired/0051…:128` is retired and not edited.)

`LibraryRoute` (the sibling the new route copies; unchanged):
```
frontend/src/App.tsx:20, :62, :232, :236
```

Files edited: `frontend/src/App.tsx`, `frontend/src/components/layout/Sidebar.tsx`,
`frontend/e2e/width-overflow.spec.ts`, `frontend/e2e/smoke.spec.ts`, `docs/design-system.md`.
Files created: `frontend/src/components/workbench/{index.ts,WorkbenchPage.tsx,BriefList.tsx,BriefDetail.tsx,NewBriefPanel.tsx,copy.ts}`.
Not touched: anything under `app/`, `frontend/src/lib/*` (ticket 03's `workbenchApi.ts` is consumed as is — a missing field there is `blocked-upstream`, not a local patch).

## Contradiction check

- Done-check 5 step 4 (目標張數 field empty, required) vs step 3's auto-poll: an implementation
  that pre-fills 目標張數 with 6 to make the walk faster passes step 4's "three blocks" and fails
  the ADR 0068 §7 rule "no default is generated for them" — the walker checks the field is empty
  before typing.
- Done-check 1 (dependency-cruiser) vs §4's product photo: reading the library bundle through
  `@/lib/libraryApi` is allowed; importing anything from `@/components/library/*` is a
  cross-feature import and fails the cruiser — the tension shows on the first `import … from
  "@/components/library/tabs/AssetsTab"`.
- Cheapest wrong implementation that leaves every check green: rendering the copy variants from
  `body_json.short` etc. but the 字數 caption from `text.length` including line breaks (bands are
  measured without them) — the caption would disagree with the server's ❌ line by the number of
  breaks; the walker compares one caption to the validation text. Second: `全部複製` copying the
  JSON instead of plain text — step 3 reads the clipboard.
