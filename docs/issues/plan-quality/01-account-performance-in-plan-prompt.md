# 01 — This month's ad performance goes into the plan prompt

Route B: behaviour change; no schema, no money path, no permission path. Staffing (user, 2026-09-08):
Sonnet implements; a different Sonnet agent reviews the diff; Opus reviewed this ticket once before dispatch.
Board row: 方案品質 (`docs/issues/plan-quality/spec.md`, cause 二 "出方案的時候看不到成效").

Why this cut first: the variance probe (spec §雜訊底線, 2026-09-08) showed 0/5 identical-input runs cite any
number from the account. The numbers exist in the DB: for `brd_bughunt` this month, 8 ads, 12,747 TWD,
conservative ROAS 1.77x / optimistic 2.81x / coverage 39% (computed 2026-09-08 with `performance._bucket()`
over `meta_repo.daily_entity_spend(level="ad")`). The plan prompt today carries none of it.

Not this ticket: the five empty context tables (cause 一); the coordinate table (`diagnosis.compress()`) — every
row of it is `不可讀` today because no spend is tagged, so it would add 1,100 chars of noise; any change to
`app/meta`.

## What

### 1. Data — `app/schedule/performance.py`

```
ad_performance(conn, org_id: str, brand_id: str) -> dict
```

- window = `state._current_month_window(conn, org_id)` (same window as the brand page and the diagnosis).
- rows = `meta_repo.daily_entity_spend(conn, org_id, account_ids, start, end, level="ad")` where
  `account_ids = meta_repo.bound_account_ids_for_brand(conn, org_id, brand_id)`.
- names and CPA: `meta_repo.spend_summary(conn, org_id, account_ids, start, end, level="ad",
  conversion_goal=brand["conversion_goal"])` — `brand` from `bi_repo.get_brand`. One dict `entity_id ->
  (entity_name, cpa)`. No new query in `app/meta`.
- per-ad and total aggregation = the existing `_bucket()` unchanged (conservative = revenue ÷ all spend,
  optimistic = revenue ÷ tracked spend, coverage = tracked rows ÷ rows).
- **one block per currency**, never summed across currencies (ADR 0057 §4, same as
  `brand_creative_performance()["currencies"]`): rows are grouped by `row["currency"]` first, then by ad.
  Plan review 2026-09-08 caught this: the DB holds only TWD today (73 rows), so no check would have gone red.
- `window.end_date` is **inclusive**: `month_end - 1 day` (`2026-09-30`, not the half-open `2026-10-01` that
  `_current_month_window()` returns) — exactly what `brand_creative_performance()` does. Plan review caught the
  ticket saying only "same convention".
- ads sorted by spend descending inside each currency. Pure function apart from the three repository reads.

Literal shape (values from the 2026-09-08 run against `brd_bughunt`, rounded here for reading; the function
returns raw precision like `_bucket()` does):

```json
{
  "window": {"start_date": "2026-09-01", "end_date": "2026-09-30"},
  "conversion_goal": null,
  "currencies": [
    {
      "currency": "TWD",
      "total": {"spend": 12747.0, "impressions": 127314, "clicks": 2833, "revenue": 22505.96,
                "roas": 2.81, "roas_conservative": 1.77, "roas_coverage": 0.386, "ad_count": 8},
      "ads": [
        {"entity_id": "120250876554370671", "entity_name": "踢罐子簡介1150730", "cpa": null,
         "spend": 5144.0, "impressions": 31755, "clicks": 1409, "revenue": 8455.03,
         "roas": 2.31, "roas_conservative": 1.64, "roas_coverage": 0.714, "ad_count": 1},
        {"entity_id": "120250979856360671", "entity_name": "1150803 圖文簡介", "cpa": null,
         "spend": 3837.0, "impressions": 63970, "clicks": 962, "revenue": 3662.97,
         "roas": 1.32, "roas_conservative": 0.95, "roas_coverage": 0.571, "ad_count": 1}
      ]
    }
  ]
}
```

No bound account, or no rows in the window → `{"window": …, "conversion_goal": …, "currencies": []}`.

### 2. Text — `app/schedule/jobs.py`

```
_account_performance_text(perf: dict, breakeven: tuple[float | None, str]) -> str
```

`breakeven = diagnosis_mod.breakeven_roas(conn, org_id, brand_id)` — the same call the diagnosis job makes.
Reuse `diagnosis_mod._pct`, `diagnosis_mod._roas_text`, `diagnosis_mod.DIRECTIONAL_ONLY_NOTE` and the
break-even line wording of `diagnosis_mod.compress()` (same module; private helpers are allowed inside it).
Rendered section, literal (numbers as above):

```
【這個帳戶目前的成效】（Meta 廣告層，2026-09-01 ~ 2026-09-30）
# 幣別 TWD｜本月總花費 12,747｜保守 ROAS 1.77x｜樂觀 ROAS 2.81x｜追蹤覆蓋率 39%｜8 則廣告
打平線 1.00x，來自這一期產品填的售價與成本，毛利率 100%
這是方向性判讀，不是統計顯著的結論。
| 廣告 | 花費 | 佔比 | 保守 ROAS | 樂觀 ROAS | 追蹤覆蓋率 | CPA |
|---|---|---|---|---|---|---|
| 踢罐子簡介1150730 | 5,144 | 40% | 1.64x | 2.31x | 71% | 未設定轉換目標 |
| 1150803 圖文簡介 | 3,837 | 30% | 0.95x | 1.32x | 57% | 未設定轉換目標 |
方案的 summary 與 reasoning 要引用上面的數字：指名哪一則廣告、哪個數字、這一期要把它推到多少。
```

One `# 幣別 …` block (header line, break-even line, note, table) per entry of `currencies`; the closing
instruction line once, at the end. CPA cell: `f"{cpa:,.0f}"` when a number; `未追蹤` when `None` and `conversion_goal` is set; `未設定轉換目標`
when `conversion_goal` is `None` (it is `None` for `brd_bughunt` today — setting it is the user's, in 設定頁).
ROAS cells use `_roas_text` (already prints `未追蹤` for `None`).

Empty case (`currencies == []`):

```
【這個帳戶目前的成效】
這個月（2026-09-01 ~ 2026-09-30）還沒有任何 Meta 花費資料。
```

### 3. Position — `jobs.schedule_plan()`

The section is appended as the **last** section of the plan prompt, after `brand_context`:
`(department_text, methodology_result.text, params_text, brand_context, performance_text)`.
Reason: it ends with an instruction, and `docs/contracts/schedule.md` "Position in the prompt decides whether
an instruction runs" says an instruction in the middle of a long prompt is ignored. Cost accepted: the
experiment-rules block `【本期要測的】` (inside `brand_context`) moves from last to second-last. Measured
2026-09-08: department 1,299 chars, methodology 9,418, brand_context 274 — the T8b finding was on a
21,679-char prompt; if a later measure shows adopted experiments stop appearing in plans, that is a new issue
under this goal, not a reason to reorder inside this ticket.

`context_scope` is unchanged. Nothing is stored; the section is recomputed on every run like the rest of the
prompt.

### 4. Contract page — `docs/contracts/schedule.md`

One line under "Module-local and reversible": the plan prompt carries this month's ad-level performance as its
last section (`performance.ad_performance()` → `jobs._account_performance_text()`); same window as the brand
page and the diagnosis.

## How we know it's done

Run every gate with `BRAND_OS_LLM_PROVIDER` unset (it overrides the fake provider in tests).

1. `app/tests/test_schedule.py`, in the bound-account test base (the class whose `setUp` calls
   `meta_repo.bind`, around line 1018): seed **one ad, two days** on the bound account with
   `meta_repo.upsert_entity_spend` (`level="ad"`, `campaign_id`/`adset_id`/`ad_id` filled): day A spend 100
   roas 3.0; day B spend 100 roas `None`. Also seed one confirmed brand fact so the brand context is non-empty.
   POST a plan, run the worker, read `fake.calls[0]["messages"][0]["content"]`:
   - contains `【這個帳戶目前的成效】`, the ad's `entity_name`, `保守 ROAS 1.50x`, `樂觀 ROAS 3.00x`, `50%`;
   - `index("【這個帳戶目前的成效】")` is greater than `index("SCHEDULE-PLAN-TASK-V1")` **and** greater than
     `index("【事實】品牌事實")` (section is last, after the brand context);
   - contains `未設定轉換目標` (test brand has no conversion goal).
   Red proof: delete the `performance_text` element from the tuple in `schedule_plan()` → fails.
2. Same file, same base: no spend rows → prompt contains `還沒有任何 Meta 花費資料` and the literal inclusive
   window `（{month_start} ~ {month_end - 1 day}）` computed in the test from `today_for_org` — the half-open
   end (`10-01` style) must fail. Plan review 2026-09-08 asked for the literal.
3. `app/tests/test_schedule_performance.py`: `ad_performance()` on three ads, two in TWD and one in USD (the
   `currency` field of the seeded rows) → `currencies` has two entries, the TWD `total["spend"]` equals the sum
   of the two TWD ads only (no cross-currency sum), `ads` sorted by spend desc inside TWD, `entity_name` filled
   from `spend_summary`; and `currencies == []` when the brand has no bound account. One test.
4. Machine gate, verbatim:
   `uv run ruff check app && uv run pyright && uv run pytest app/tests/test_schedule.py app/tests/test_schedule_performance.py app/tests/test_architecture_boundaries.py -q`
   then the e2e smoke per `CLAUDE.md`: `cd frontend && npm run e2e` (start the 8720 backend yourself, stop it
   after; `supabase start` is already up).
5. Ratchets, measured 2026-09-08 at ticket time (`app/tests/test_architecture_boundaries.py`):
   `_line_totals()` → tests 20236 = `TEST_LINES_CEILING` 20236; `_module_sizes()["app/schedule"]` 3955 =
   `KNOWN_MODULE_SIZES["app/schedule"]` 3955. **This ticket authorizes raising both to the measured value after
   the change**, each with a one-line reason at the constant (production: `ad_performance()` and
   `_account_performance_text()` are aggregation and formatting, same input same output; tests: checks 1–3 name
   prompt contract and data correctness). No other ratchet moves; no tolerance list widens.
6. Acceptance on a restarted worker (`啟動行銷系統.bat` window "Marketing OS Worker": close it and start again,
   or restart via the bat): open http://localhost:8710/ → 排程 → 出方案 with any product → wait → read the
   narrative. Count the account numbers or ad names it cites (baseline from the probe: 0 of 5 runs cite any).
   The walker records the count; the user judges whether the plan reads as "this account's plan".

## Shared files touched

Files edited: `app/schedule/performance.py` (new `ad_performance()`), `app/schedule/jobs.py`
(`_account_performance_text()`, `schedule_plan()` prompt tuple), `app/tests/test_schedule.py`,
`app/tests/test_schedule_performance.py`, `app/tests/test_architecture_boundaries.py` (two constants),
`docs/contracts/schedule.md` (one line).

No name stops existing. Names whose meaning or position changes, scanned whole-repo 2026-09-08:

```
### git grep -n "def schedule_plan\|jobs.schedule_plan"
app/schedule/jobs.py:154:def schedule_plan(org_id: str, brand_id: str, product_ids: list, platform: str, objective: str,
docs/issues/plan-quality/spec.md:10:同一份輸入（同 `input_context_hash`，codex_cli，零費用）連跑 5 次 `jobs.schedule_plan()`，每次 45～56 秒：
docs/issues/plan-quality/spec.md:20:探針本體是 `jobs.schedule_plan()` 直接呼叫 5 次＋讀回 `llm_task`，10 行以內，要重量就重寫。
### git grep -n "_bucket("
app/schedule/diagnosis.py:162:    """一個座標值 → 使用者可以自己核對的那幾個數字（`_bucket()` 的既有欄位，不重算）。"""
app/schedule/performance.py:109:def _bucket(rows: list) -> dict:
app/schedule/performance.py:144:def _untagged_bucket(rows: list) -> dict:
app/schedule/performance.py:145:    """`未標座標`桶子只有 `spend`／`ad_count` 兩欄（ticket 字面例子），不是 `_bucket()`
app/schedule/performance.py:177:            {"key": key, "label": labels.get((dimension, key), key), **_bucket(value_rows)}
app/schedule/performance.py:182:            "untagged": _untagged_bucket(dim_untagged_rows),
app/schedule/performance.py:189:        "untagged": _untagged_bucket(currency_untagged_rows),
app/tests/test_architecture_boundaries.py:1683:                            # （POST／GET .../diagnosis）＋`performance.py` `_bucket()`
app/tests/test_architecture_boundaries.py:1698:                           # 加的東西：(1) B1／ADR 0045 的時間分桶——`time_bucket()`（週末
app/tests/test_schedule_diagnosis.py:39:def _bucket(spend: float, *, roas=None, roas_conservative=None, coverage=1.0, ad_count=1) -> dict:
app/tests/test_schedule_diagnosis.py:57:                {"key": "v1", "label": "座標甲", **_bucket(600.0, roas=2.0, roas_conservative=1.5)},
app/tests/test_schedule_diagnosis.py:58:                {"key": "v2", "label": "座標乙", **_bucket(300.0, roas=1.0, roas_conservative=0.8)},
### git grep -n "TEST_LINES_CEILING ="
app/tests/test_architecture_boundaries.py:1316:TEST_LINES_CEILING = 20236  # 票 10 round 2（review 打回的缺口）：`test_schedule.py` 補
### git grep -n "\"app/schedule\": "
app/tests/test_architecture_boundaries.py:1661:    "app/schedule": 3955,  # 票 10（ADR 0064：一個綁定屬於做出它的那棵樹）：
### git grep -n "DIRECTIONAL_ONLY_NOTE\|def _roas_text\|def _pct"
app/schedule/diagnosis.py:61:DIRECTIONAL_ONLY_NOTE = "這是方向性判讀，不是統計顯著的結論。"
app/schedule/diagnosis.py:228:def _pct(spend: float, total: float) -> str:
app/schedule/diagnosis.py:232:def _roas_text(value: float | None) -> str:
app/schedule/diagnosis.py:263:            f"\n{DIRECTIONAL_ONLY_NOTE}"
app/schedule/diagnosis.py:278:        out.append(DIRECTIONAL_ONLY_NOTE)
app/schedule/diagnosis.py:431:    來源改寫進這段文字，沿用 `DIRECTIONAL_ONLY_NOTE`（決定 4，`ab-testing.md:75` 原文）而不是
app/schedule/diagnosis.py:438:    return f"{body}\n（本條來自 {round_date} 的成效判讀，{DIRECTIONAL_ONLY_NOTE}）"
### git grep -n "Module-local and reversible"
docs/contracts/background.md:79:Module-local and reversible, decided here rather than in an ADR:
docs/contracts/core.md:94:Module-local and reversible, decided here rather than in an ADR:
docs/contracts/intake.md:101:Module-local and reversible, decided here rather than in an ADR:
docs/contracts/schedule.md:87:Module-local and reversible, decided here rather than in an ADR:
```

`performance.py`'s file header says only `routes.py` calls it; `jobs.py` is inside the same module
(`app/schedule/`), so the container contract is not crossed — update that header sentence in the same diff.

## Contradiction check

- **Check 1 (section last) vs. the contract's measured fact** ("an instruction that is not last is ignored",
  T8b): after this ticket `【本期要測的】` is no longer last. Input that would show it: a brand with one adopted
  experiment rule and this month's spend; if the plan ignores the experiment, position is the cause. Settled in
  §3 above (accepted, re-measure later); not a contradiction inside this ticket's checks.
- **Check 1 vs. check 2**: a bound account whose rows are all in last month gives the "還沒有任何" text even
  though the account has data — by design (same window as the brand page); check 2 must assert the window dates
  are printed so the reader can see why.
- **Plan review 2026-09-08 (Opus, one round) found two holes, both folded in above:** a single `total` summed
  across currencies (ADR 0057 §4) — now one block per currency, check 3 seeds a USD row; and "same window
  convention" hiding the half-open end date — now the literal inclusive date is asserted in check 2. It also
  offered the lazier cut (total line only, five lines in `jobs.py`, no new function); rejected by the ticket
  writer because the spec's target sentence names an ad ("你的 XX 廣告 CPA 是 470"), which needs the per-ad rows.
- **Cheapest wrong implementation that leaves every check green:** (a) per-ad ROAS from `spend_summary`
  (`bool_and` → `None` → `未追蹤` everywhere) — caught by check 1's `1.50x`/`3.00x` on a half-tracked ad;
  (b) optimistic value printed in both ROAS columns — caught by `1.50x`; (c) section placed before
  `brand_context` — caught by the `【事實】品牌事實` index assertion. Not caught by any check: a table that
  renders correctly but the agent still ignores — that is what check 6's count is for, and it is judged, not
  asserted.
