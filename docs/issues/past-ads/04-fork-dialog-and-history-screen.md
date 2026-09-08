# 04 — the fork dialog, the 「把過去的廣告帶進來」 screen, and the guide card

Route B (frontend, plus one pure guide-card rule and its facts line). Rulings: ADR 0067 §1.6, §1.7, §1.9.
Goal picture: `spec.md`. Requires tickets 02 and 03 shipped (`startMetaBackfill`, `fetchMetaBackfillStatus`,
`fetchHistory`, `tagHistoryAd`, `setAdvertisingHistory` exist in `frontend/src/lib/`; `imported_ad_count` is
exported by `app/schedule/__init__.py`). Appearance and wording: `docs/design-system.md` (ADR 0065) — §6 for
every control, §7 for every number, §8 for every label, §9 gates, §10 checklist. **No LLM call anywhere.**

## What

### 1. The fork dialog — `frontend/src/components/intake/AdvertisingHistoryDialog.tsx`

Built on `layout/ui/dialog` (`DialogContent`, `DialogTitle`, `DialogDescription`, `DialogFooter`). Opens the
moment `StartStep` reports a **new** brand (`IntakeWizard.tsx:52`, the `brandId === null` branch) and before
the navigate; not on `/brands/:id/intake` (a re-run). No close button, no overlay dismiss, no ESC: the only
way out is one of the two buttons (ADR 0067 §1.6 — a choice, not a form). Title 「這個品牌以前投放過廣告嗎？」,
description one sentence: 「兩種都能建檔；選了之後可以在品牌頁改。」 Two `Button`s, primary
「投放過廣告」 (`has_history`), outline 「完全沒投放過」 (`none`). Press → `setAdvertisingHistory(brandId, value)`
via `useFormSubmit` (the kit's submit hook, `MetaSection.tsx:12`), then the navigate the wizard would have
done. A failed save shows the error inside the dialog (its own error line, §6) and keeps both buttons enabled.

### 2. The button on 「建檔完成」 — `IntakeCompletedPage.tsx`

The page already reads the truth card and personas. When the brand's `advertising_history === 'has_history'`
(read through `fetchLibrary(brandId)`'s brand shape, extended by ticket 03) the button row gains a primary
`Link` 「把過去的廣告帶進來」 → `/brands/:id/intake/history`, placed first; 「前往品牌頁」 becomes outline.
Otherwise the row is unchanged.

### 3. The guide card — `app/dashboard/guide_cards.py` + `app/dashboard/repository.py`

Rule `past_ads_pending`, registered **first in `RULES`** (amended after the walk, see `## Rejected`: the
overview brand card shows exactly one `next_step`, the first card `build()` returns, and a fresh brand
always trips `conversion_goal_missing` — the owner who just pressed 「投放過廣告」 sees their own next
step first, the conversion-goal card the moment ads are in): fires when `facts["advertising_history"] == "has_history"` and
`facts["imported_ad_count"] == 0`; card `{"title": "你說這個品牌投放過廣告——把過去的廣告帶進來，方案才用得上",
"action_url": f"/app/brands/{brand_id}/intake/history"}`. Facts: `_guide_card_facts()` adds
`"advertising_history": brand["advertising_history"]` (already has `brand`) and
`"imported_ad_count": schedule.imported_ad_count(conn, org_id, brand_id)` (`from app import schedule` — the
module's entry file; `app.dashboard` sits above `app.schedule` in `LAYER_ORDER`, `test_architecture_boundaries.py:495-505`).
Facts contract in the file docstring gains the two lines.

### 4. The screen — `frontend/src/components/intake/HistoryPage.tsx`, route `/brands/:brandId/intake/history`

Route added in `App.tsx` next to `/brands/:brandId/intake`, wrapped like `IntakeRoute` with `PageHeader`
title 「把過去的廣告帶進來」, description 「數字是 Meta 的，座標和理由是你的；這裡沒有 AI 在猜。」.
`Breadcrumb` under the brand. Data: `fetchHistory(brandId)` on mount; states per §10.3:

- `connected === false` → `EmptyState` 「還沒接上 Meta 廣告帳戶」, description 「這一輪只能從 Meta 帶進來；接上以後隨時可以回來。」,
  action 「前往設定」 → `/settings`.
- connected, `backfill.ad_rows === 0` and not running → a card with the primary button 「開始拉 37 個月的數字」
  → `startMetaBackfill(brandId)`; then poll `fetchMetaBackfillStatus` every 5 s while `running`, re-fetch
  history when it turns false. Copy while running: 「正在從 Meta 拉數字，目前拉到 {earliest_spend_date}」
  (§7 date format). Running on first load (started elsewhere) → the same polling state.
- cards: one section per currency (currency named in the section header, §7). Above the cards one line:
  「這些是 Meta 現在還回得出的廣告，不一定是你投過的全部。」 and, when `breakeven` is null,
  「算不出打平線（{source}），所以只排序、不判贏輸。」. Each card (`§6` card, two columns at ≥1024,
  stacked below): left — image (`<img>` with `alt` = name; missing → a placeholder block with
  「Meta 現在回不出這則的素材」 when `creative === null`, or `creative_error` when set), name, 「投放期間
  {first}–{last}」, `why` as badges (top_spend 「花最多」, top_roas 「賺最多」, bottom_roas 「賠最多」), the
  numbers via `format.ts` (`formatCurrency`, `formatMetaRoas` ×2 with captions 保守／樂觀, `formatPercent`
  for coverage, CPA), verdict badge (win 「贏」 / lose 「輸」 / unclear 「看不出」, colours from tokens);
  right — seven `select`s labelled with `COORDINATE_DIMENSIONS` (`coordinatesApi.ts:12`), options = that
  dimension's coordinates from the reply (`label`, value `key`) plus 「不填」; a `textarea` 「這則為什麼贏／輸？」
  (`ui/textarea`); footer buttons 「儲存」 (primary, `tagHistoryAd`) and 「略過」 (outline, hides the card
  for this visit — nothing saved). A saved card shows 「已記錄」 with its `tagged_at` through `formatSyncTime` (`format.ts:54`, §7 — never
a raw ISO string) and stays editable.
  Cards already `tagged` on load render with their saved values.
- A card list longer than one screen is still one list (§5: "nothing scrolls past one screen of overview"
  applies to overview pages; this is a task flow — say so in a comment citing §5.1).

`index.ts` for `intake/` is not needed: `App.tsx` may import a component path directly
(`.dependency-cruiser.cjs:35`), and nothing outside `intake/` imports these files.

Literal examples of the three things this ticket sends or shows:

```json
{"dialog_press": {"request": "PUT /api/library/brands/brd_x/advertising-history", "body": {"value": "has_history"}},
 "guide_card": {"title": "你說這個品牌投放過廣告——把過去的廣告帶進來，方案才用得上", "action_url": "/app/brands/brd_x/intake/history"},
 "card_save": {"request": "PUT /api/schedule/brands/brd_x/history/120212345678901234",
               "body": {"coordinates": {"audience": "new_parents", "pain": null, "angle": "convenience", "hook": null, "proof": null, "offer": "first_order_discount", "format": "carousel"},
                        "owner_note": "媽媽群組轉貼最多，週末單量翻倍"}}}
```

### 5. e2e

`frontend/e2e/width-overflow.spec.ts` gains `/brands/:brandId/intake/history` (`assertNoOverflow`, same
pattern as `/brands/:brandId/intake` at `:68-70`); `smoke.spec.ts` visits it once and expects the
「還沒接上 Meta 廣告帳戶」 empty state (the e2e account has no Meta token).

## How we know it's done

1. **Machine gate** (§9): `cd frontend && npm run build && npm run lint && npm run depcruise && npm test` (no `typecheck` script; `build` is `tsc -b && vite build`)
   (`designTokens.test.ts` included) · `unset BRAND_OS_LLM_PROVIDER; uv run ruff check app; uv run pyright;
   uv run pytest app/tests/test_dashboard_guide_cards.py app/tests/test_dashboard_guide_cards_wiring.py app/tests/test_dashboard_guide_card_links.py app/tests/test_architecture_boundaries.py -q`
   · `cd frontend && npm run e2e` (own 8720 backend, `supabase start` first, shut it down after).
2. **Guide card rule is pure and ranked.** In `test_dashboard_guide_cards.py`: facts `has_history` + 0 → the
   card with that `action_url`; `has_history` + 3 → no card; `none` + 0 → no card; with `intake_draft` **and**
   a missing `conversion_goal` also set, the past-ads card comes **first** (amended, see `## Rejected`). `test_dashboard_guide_card_links.py` (every `action_url` resolves to a
   mounted route) stays green with the new URL.
3. **Walk (WALK subagent, playwright-cli, on a restarted 8720 backend, seeded account `123@example.com`/`123456`):**
   1. Open `/app/intake/new`, fill the brand name, submit → the dialog appears with the two buttons and no
      close control; ESC does nothing. Screenshot.
   2. Press 「投放過廣告」 → wizard step ② shows for the new brand. Screenshot.
   3. Open the overview `/app` → the new brand's card carries the `next_step` link
      「你說這個品牌投放過廣告——把過去的廣告帶進來，方案才用得上」 (the overview card is the only place a
      guide card surfaces, one per brand — amended after the walk); click → lands on
      `/app/brands/<id>/intake/history`. Screenshot.
   4. On `brd_bughunt` (bound to BP AD, rows present): `/app/brands/brd_bughunt/intake/history` → the TWD
      section, ≥1 card with name, spend, both ROAS captions, seven selects, textarea. Screenshot at 1024 and 1920.
   5. Pick one coordinate in one select, type a note, 「儲存」 → 「已記錄」 with a time; reload → the values
      persist. Screenshot.
   6. 「略過」 on another card → it disappears; reload → it is back (nothing saved).
   7. Press 「開始拉 37 個月的數字」 if shown → the running copy appears (the real pull may fail without a
      valid token; the failure text is the state to screenshot, not a red step).
   The first ❌ is red.
4. **Copy gate**: every user-visible string in the new files passes §8 (no banned words; the gate the U1 row
   names, `docs/issues/ui/issue-u1-banned-words-gate.md`, if it exists as a runnable check — run it; if it is
   only a list, read it once and say so).

## Shared files touched

Searched 2026-09-08, whole repo, unscoped (same exclusions as tickets 01–03):

```
grep -rn AdvertisingHistoryDialog .   → (no hits)
grep -rn HistoryPage .                → (no hits)
grep -rn past_ads_pending .           → (no hits)
grep -rn "intake/history" .           → (no hits)
```

Files this ticket edits:

```
frontend/src/components/intake/AdvertisingHistoryDialog.tsx   (new)
frontend/src/components/intake/HistoryPage.tsx                (new)
frontend/src/components/intake/IntakeWizard.tsx:52            (open the dialog on a new brand)
frontend/src/components/intake/IntakeCompletedPage.tsx        (the button)
frontend/src/App.tsx:56-72,173-200                            (route)
frontend/e2e/smoke.spec.ts, frontend/e2e/width-overflow.spec.ts
app/dashboard/guide_cards.py                                  (rule + docstring)
app/dashboard/repository.py:126-135                           (two facts)
app/tests/test_dashboard_guide_cards.py                       (rule tests)
app/tests/test_architecture_boundaries.py                     (KNOWN_MODULE_SIZES["app/dashboard"] 645, TEST_LINES_CEILING)
```

## Contradiction check

- **Done-check 3 step 1 (no way to dismiss the dialog) vs design-system §6 (dialogs confirm, forms go in the
  side panel).** ADR 0067 §1.6 settles it: two buttons, no fields, read as the Confirm pattern. An implementer
  who adds a close control to satisfy §6 fails step 1; one who adds fields fails §6. Input: press ESC.
- **Done-check 3 step 6 (略過 saves nothing) vs step 5 (儲存 persists).** Both hold only if 略過 is purely
  client-side; a 略過 that PUTs `not_applicable` would make step 6's reload show the card gone. Keep 略過
  local.
- **Cheapest wrong implementation that leaves every check green:** the guide card fires on `has_history`
  alone (ignoring the count) — check 2's `has_history + 3 → no card` case is what catches it; keep that case.

## Rejected

2026-09-08, walk round 2 (Meta stand-in, `scripts/drill/`): steps 1, 2, 4–8 ✅; **step 3 ❌**. The guide card
never surfaced: `app/dashboard/repository.py` hands the overview brand card only the first card `build()`
returns (`next_step`, one slot; the cockpit page renders no guide cards at all), and every fresh brand trips
`conversion_goal_missing` first, so `past_ads_pending` — registered second — was masked for exactly the brand
it exists for. The ticket's picture of the cards was wrong, not the implementation. Ruling (main chat):
`past_ads_pending` is registered first; the walk step reads the overview card. Also caught: 「已記錄・<raw ISO
string>」 — §7 says every number is formatted; use `formatSyncTime`. Round 2 = those two changes, the
ordering test in `test_dashboard_guide_cards.py` updated to the new priority (the `intake_draft` case now
expects the past-ads card first when both fire), then a re-walk of steps 3 and 5. Walk round 1 had run
against a database `supabase db reset` (ticket 01) had emptied of Meta data — environment, not code; the
stand-in seed lives in the session scratchpad (`walk04_seed.py`), never in the repo.
