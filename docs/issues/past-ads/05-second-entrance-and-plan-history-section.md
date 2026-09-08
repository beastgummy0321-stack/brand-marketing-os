# 05 — the coordinate chart's second entrance, and 【投放史】 in the plan prompt

Route B (behaviour inside `app/schedule`; no schema, no boundary, no money path, no permission change).
Rulings: ADR 0067 §1.3 and §1.10. Requires ticket 03 shipped (`imported_ads_for_brand`, `history.py`).
**No LLM call is added; the plan prompt gains one program-built section.**

## What

### 1. `app/schedule/performance.py` — `brand_creative_performance()` falls back to `imported_ad`

After `row_candidate` is built from the depth-3 bindings (`performance.py:216-221`), every `(entity_id,
spend_date)` whose candidate does not reach any dimension (`_reaches_any` false) is looked up in
`schedule_repo.imported_ads_for_brand(conn, org_id, brand_id)` filtered to `coordinates_status == 'tagged'`,
keyed by `external_id`; a hit becomes that row's candidate (the imported row already carries the seven
`*_key` columns, so `_currency_view` needs no change). A binding that reaches any dimension wins over an
imported row for the same entity (ADR 0067 §1.3). `_untagged_bucket` and the invariant "tagged + 未標座標 ==
total" are untouched.

### 2. `app/schedule/history.py` — `tagged_history(conn, org_id, brand_id) -> list[dict]`

No Graph call. The brand's `tagged` imported rows, each joined in Python to its own numbers:
`meta_repo.daily_entity_spend(..., level="ad")` over `[min first_seen_date, max last_seen_date + 1 day)`
of the tagged rows, grouped by `entity_id`, aggregated with `performance._bucket`; each item is
`{"name", "first_seen_date", "last_seen_date", "currency", **_bucket, "coordinates": {dimension: key},
"owner_note"}`, ordered by `spend` descending, per currency (never summed across). Empty when no row is tagged.

### 3. `app/schedule/jobs.py` — `_history_text(items, labels, breakeven) -> str` and its place

Shaped after `_account_performance_text()` (`jobs.py:164-215`), reusing `diagnosis_mod._roas_text`,
`diagnosis_mod._pct`, `diagnosis_mod.DIRECTIONAL_ONLY_NOTE` and `_coordinate_cell`'s label lookup
(`performance_mod._coordinate_labels`). Empty list → `""` (the section is skipped by the existing
`if section` join). Otherwise:

```
【投放史】（系統接手之前，這個帳戶自己投過、老闆親自標了座標的廣告；{first}–{last}）
打平線 …（same line as 【這個帳戶目前的成效】）
{DIRECTIONAL_ONLY_NOTE}
# 幣別 TWD
| 廣告 | 投放期間 | 花費 | 保守 ROAS | 樂觀 ROAS | 追蹤覆蓋率 | 座標（受眾／痛點／切角／鉤子／證明／優惠／格式） | 老闆的話 |
|---|---|---|---|---|---|---|---|
| BP｜夏季｜輪播A | 2026-05-03–2026-08-31 | 3,570 | 0.77x | 1.03x | 75% | 新手爸媽／—／省時方便／—／—／首購折扣／輪播 | 媽媽群組轉貼最多，週末單量翻倍 |
投放史是起點，不是答案：說明這一期哪些座標值得再試、哪些不必重走，並指名是哪一則廣告的哪個數字讓你這樣判斷。
```

`owner_note` is printed verbatim (pipes `|` inside it replaced by `｜`, nothing else touched). Appended in
`schedule_plan()`'s join (`jobs.py:400-404`) **after** `last_period_text`, as the last section — ADR 0067
§1.10 and the contract page's "Position in the prompt decides". `schedule_tree()` and `schedule_creative()`
do not get it.

### 4. `docs/contracts/schedule.md`

Module-local decisions gain one line: "The plan prompt ends with 【投放史】 (ticket past-ads 05):
`history.tagged_history()` → `jobs._history_text()`; absent when no imported ad is tagged." Measured
section: nothing new.

## How we know it's done

1. **The second entrance, in `app/tests/test_schedule_performance.py`** (the file that already exercises
   `brand_creative_performance`): one ad with spend rows this month and a `tagged` imported row
   (`angle_key = 'convenience'`) and **no** binding → its spend appears under `angle` value `convenience`,
   the currency's `untagged.spend` excludes it, and `sum(values.spend) + untagged.spend == total_spend`
   (the existing invariant assertion, unchanged). Same fixture with a depth-3 binding whose candidate has
   `angle_key = 'proof_first'` → `proof_first` wins, `convenience` gets nothing. An imported row with
   `coordinates_status = 'pending'` → the spend stays in `untagged`.
2. **The section, in `app/tests/test_schedule.py`** (where `_account_performance_text` is tested):
   `_history_text([])` is `""`; with one item using the contract page's numbers (3,570 / 2,737.8 / 0.75) the
   text contains the ad name, `0.77x`, `1.03x`, `75%`, the coordinate labels in dimension order with `—` for
   the empty ones, and the note verbatim; a note containing `|` comes out with `｜`. `schedule_plan()`'s
   prompt (captured through the test's fake provider, as the existing last-period test does) ends with the
   【投放史】 block when a tagged row exists and does not contain 「投放史」 when none does.
3. **Nothing else moved**: `schedule_tree`'s prompt in the same test file does not contain 「投放史」.
4. **Machine gate**: `unset BRAND_OS_LLM_PROVIDER`; `uv run ruff check app` · `uv run pyright` ·
   `uv run pytest app/tests/test_schedule_performance.py app/tests/test_schedule.py app/tests/test_schedule_diagnosis.py app/tests/test_past_ads_history.py app/tests/test_architecture_boundaries.py -q`
   · `cd frontend && npm run typecheck && npm run build` · `cd frontend && npm run e2e` (own 8720 backend).
5. **Ratchets**: `KNOWN_MODULE_SIZES["app/schedule"]` and `TEST_LINES_CEILING` by measured amounts with reasons.

## Shared files touched

Searched 2026-09-08, whole repo, unscoped (same exclusions as tickets 01–04):

```
grep -rn tagged_history .     → (no hits)
grep -rn _history_text .      → (no hits)
grep -rn "投放史" .            → CONTEXT.md (glossary), docs/adr/0067-*.md, this folder — no code hit
```

Files this ticket edits:

```
app/schedule/performance.py:196-241         (fallback lookup)
app/schedule/history.py                     (tagged_history; created by ticket 03)
app/schedule/jobs.py:164-236,380-404        (_history_text, the join)
docs/contracts/schedule.md
app/tests/test_schedule_performance.py, app/tests/test_schedule.py
app/tests/test_architecture_boundaries.py   (ratchets)
```

## Contradiction check

- **Done-check 1 (binding wins) vs done-check 1's third case (pending imported row stays untagged).** Both
  hold only if the fallback is keyed on `coordinates_status == 'tagged'` *and* consulted only when the
  binding reaches nothing; a fallback that fires whenever a binding is absent would also pass the first
  case but would pull a `pending` row's `None` keys in — harmless for the numbers, but it makes `_reaches_any`
  the only thing standing between a pending row and the chart. Input: the pending-row fixture.
- **Done-check 2 (section last) vs the contract page's earlier measurement that the *vocabulary* section
  must be last for creatives.** Different prompt (`schedule_creative`), untouched here; the plan prompt's
  last section today is 【上一期】, which this ticket displaces to second-last. If plan quality drops (the
  noise-floor measurement on the contract page: count account numbers cited across 3 runs), the fix is
  position, not wording — record the count in the report.
- **Cheapest wrong implementation that leaves every check green:** computing `tagged_history` numbers over
  "this month" (`state._current_month_window`) instead of the rows' own seen window — an old ad with no
  spend this month would print zeros. Check 2's fixture must place the ad's spend outside the current month.
