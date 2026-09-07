# 05 — The schedule form is pre-filled with next period's dates and a suggested daily budget

Route B: behaviour change (one read-time function, one response key, one rule-card field, one form card); no
schema (the rule-card field is a `CARDS` entry, decision 1b on the contract page), no money path (nothing is
spent; the user still presses 出方案 and 核准, constitution §9), no permission path. Board row 越排越好, spec cut 4.
Depends on tickets 01–03. Staffing: Sonnet implements, a different Sonnet reviews.

Why: today the daily budget lives only in the rule card `schedule_budget.daily_budget` and the dates are typed by
hand on the schedule form (`ScheduleSetup.tsx`); nothing computes a next period from the last one. Every drill
persona got lost in the settings detour (`docs/issues/ui/issue-settings-detour-has-no-link.md`). Spec decision 3
(user, 2026-09-08): step rate is a rule card, default 20%, with the card text saying Meta publishes no number.

Not this ticket: writing to Meta; auto-creating the period (it is still born when 出方案 succeeds, ADR 0053);
changing `period.settle()` or the node table.

## What

### 1. Rule card — `app/core/rule_cards.py`

`CARDS["schedule_budget"]["fields"]` gains one field (no migration: an unset field falls back to `default`, per the
file header):

```python
"step_rate": {
    "label": "每期調幅", "unit": "%", "default": 20.0,
    "help": "系統建議下一期日預算時，往上或往下調的幅度。Meta 沒有公布官方數字（它只說「看幅度大小」）；"
            "20% 是業界慣例，可以改。",
},
```

The settings page renders card fields generically (`RuleCardsSection.tsx`), so the field appears there without
frontend work. Store as a percentage number (20.0), consistent with the card's other fields being plain numbers.

### 2. Read-time suggestion — `app/schedule/period.py`

```
next_period_suggestion(conn, org_id: str, brand_id: str) -> dict | None
```
Read-time, nothing stored, no new table (same convention as `_advance_if_ended`). `None` when the brand has no
settled period (first period; the screen says so). Otherwise, with `last = period_repo.latest_settled_period()`
and `rows = period_repo.period_node_results(last)` at depth 2 only:

- `start_date = last.end_date + 1 day`; `end_date = start_date + (last.end_date − last.start_date)`.
- `baseline = last.daily_budget` (the number the period's plan was computed from, ADR 0053: frozen at creation).
  Module-local decision, recorded on the contract page: the spec said "上期核准額"; `approval.latest()` is per brand,
  not per period, and cannot be tied back to `last`'s tree without a join the module does not have — the period's
  own `daily_budget` is the same money on the day the plan was made.
- direction from the depth-2 rows, spend-weighted: `spend = Σ actual_spend`, `revenue = Σ revenue_tracked` (rows
  with `NULL` count 0), `tracked_spend = Σ (revenue_tracked ÷ roas_optimistic)` over rows where both are set;
  `conservative = revenue ÷ spend`, `optimistic = revenue ÷ tracked_spend`; `breakeven` = the rows' `breakeven_roas`
  (all equal; `NULL` → `None`). `verdict = scoring.verdict(conservative, optimistic, breakeven)` — the same three
  values as a node (ADR 0066 rule 4), `unclear` when `spend == 0` or `revenue == 0` or no break-even.
  `win` → `up`, `lose` → `down`, `unclear` → `hold`.
- `step = rule_cards.get_value(conn, brand_id, "schedule_budget", "step_rate") / 100`;
  `daily_budget = round(baseline × (1 + step))` for `up`, `round(baseline × (1 − step))` for `down`, `baseline`
  for `hold`. Never below 0.
- `overlaps = [p["name"] for p in period_repo.list_non_draft_periods(...) + the draft, if p overlaps [start, end]
  and p is not settled]` — the screen must say when the suggestion collides with an existing period (plan review
  found two overlapping `planning` rows locally); nothing is auto-resolved.

Literal (the settled period 2026-09-07 ~ 2026-09-07 with daily 2,000, verdict `unclear` because no tracked
revenue, step 20):

```json
{
  "based_on_period_id": "cpd_01M1Y012CPJJW2F07KV8TJAC8J",
  "based_on_name": "2026-09-07 ~ 2026-09-14",
  "start_date": "2026-09-08", "end_date": "2026-09-08",
  "baseline_daily_budget": 2000.0, "daily_budget": 2000.0, "direction": "hold", "step_rate": 20.0,
  "verdict": "unclear", "roas_conservative": null, "roas_optimistic": null, "breakeven_roas": 1.0,
  "why": "上一期綁定的節點沒有追蹤到的營收，判決「看不出」，日預算先不動。",
  "overlaps": ["2026-09-08 ~ 2026-09-15"]
}
```
`why` is one sentence, built from the direction: `up` → 「上一期保守 ROAS 1.50x 高於打平線 1.00x，判決「賺」，建議加 20%。」;
`down` → 「上一期樂觀 ROAS 0.80x 低於打平線 1.00x，判決「賠」，建議減 20%。」; `hold` → the sentence above (or
「…判決「看不出」，日預算先不動。」 with the two ROAS when they exist). ROAS text through `diagnosis._roas_text`.

### 3. Response — `app/schedule/state.py`

`_brand_response()` gains `"next_period_suggestion": period_mod.next_period_suggestion(conn, org_id, brand_id)`.
There is no existing key-set assertion on that response (verified 2026-09-08: `plan_count_min` appears only as a
value check at `app/tests/test_schedule.py:636`); check 3 adds a presence assertion for the new key.

### 4. Screen — `frontend/src/components/schedule/SchedulePage.tsx`, `ScheduleSetup.tsx`, `frontend/src/lib/scheduleApi.ts`

- `ScheduleState` gains `next_period_suggestion: NextPeriodSuggestion | null` (fields as in the JSON above).
- `SchedulePage`: when the suggestion is non-null and both `startDate` and `endDate` are still `""`, set them from
  it once (on first load of a state carrying a suggestion; never overwrite what the user typed).
- `ScheduleSetup`: a card 「建議下一期」 above the form summary: dates, 「建議日預算 NT$ 2,000（目前 NT$ 2,000）」,
  the `why` sentence, the overlap warning 「跟現有檔期重疊：…」 when `overlaps` is non-empty, and a button
  「採用這個預算」 that calls `saveRuleCard(brandId, "schedule_budget", { daily_budget, step_rate })` (both current
  values, since the endpoint takes the card's fields) and then re-fetches the schedule state so the 本期每日預算
  figure updates. When `next_period_suggestion` is `null`: one line 「這是第一期，還沒有上一期可以參考。」 and no
  button. Wording per `docs/design-system.md`.

### 5. Contract page — `docs/contracts/schedule.md`

One bullet under "Module-local and reversible": next-period suggestion is read-time
(`period.next_period_suggestion()`), baseline = the settled period's own `daily_budget`, direction = the depth-2
rows' spend-weighted verdict, step = rule card `schedule_budget.step_rate` (default 20, no official Meta figure —
source: user ruling 2026-09-08, spec decision 3).

## How we know it's done

Run with `BRAND_OS_LLM_PROVIDER` unset.

1. `app/tests/test_schedule_period.py`, `_PeriodTestBase`: a settled period 09-01 ~ 09-07 with `daily_budget 2000`
   and depth-2 rows: (a) one `win` row spend 100 revenue 300 optimistic 3.0, breakeven 1.0 →
   `direction "up"`, `daily_budget 2400`, `start_date 09-08`, `end_date 09-14`; (b) rows replaced by one `lose`
   row spend 100 revenue 50 optimistic 0.5 → `"down"`, `1600`; (c) rows with `actual_spend 0` → `"hold"`, `2000`,
   `why` contains 看不出; (d) no settled period → `None`. (e) set `step_rate` to 10 via `rule_cards.set_value` →
   case (a) gives `2200`. Red proof: return `None` unconditionally → (a) fails.
2. Same file: a `planning` period 09-10 ~ 09-12 exists → `overlaps` contains its name; none → `[]`.
3. `app/tests/test_schedule.py`: `GET /api/schedule/brands/{id}` carries the key `next_period_suggestion`, `None`
   before any settled period (one assertion added to the existing GET test around line 626-640).
4. Gate, verbatim: `uv run ruff check app && uv run pyright && uv run pytest app/tests/test_schedule_period.py app/tests/test_schedule.py app/tests/test_rule_cards.py app/tests/test_rule_cards_api.py app/tests/test_architecture_boundaries.py -q`
   then `cd frontend && npm run build && npm run e2e`.
5. Ratchets: measure before and after; **this ticket authorizes raising both to the measured value** with a
   one-line reason at each constant.
6. Acceptance on a restarted backend + worker: 排程 → the 設定檔期 tab shows 「建議下一期」 with 2026-09-08 dates
   pre-filled, 建議日預算 NT$ 2,000, the 看不出 sentence, and the overlap warning naming 2026-09-08 ~ 2026-09-15;
   press 採用這個預算 → the 本期每日預算 figure re-reads (unchanged at 2,000 today); 設定頁 → the 檔期日預算 card
   shows the new 每期調幅 field at 20.

## Shared files touched

Files edited: `app/core/rule_cards.py` (one field), `app/schedule/period.py` (`next_period_suggestion`),
`app/schedule/state.py` (one key), `frontend/src/lib/scheduleApi.ts`, `frontend/src/components/schedule/SchedulePage.tsx`,
`frontend/src/components/schedule/ScheduleSetup.tsx`, `app/tests/test_schedule_period.py`, `app/tests/test_schedule.py`,
`app/tests/test_architecture_boundaries.py` (two constants), `docs/contracts/schedule.md`.

Names whose meaning changes — scanned 2026-09-08:

```
### git grep -n '"schedule_budget"' -- 'app/*.py' 'frontend/src/*'
app/core/rule_cards.py:49:    "schedule_budget": {
app/schedule/routes.py:249:    daily_budget = rule_cards.get_value(conn, brand_id, "schedule_budget", "daily_budget")
app/schedule/state.py:157:    current_daily_budget = rule_cards.get_value(conn, brand_id, "schedule_budget", "daily_budget")
app/schedule/jobs.py:349:        daily_budget = rule_cards.get_value(conn, brand_id, "schedule_budget", "daily_budget")
(tests naming the card: app/tests/test_approval.py ×1, app/tests/test_schedule.py ×3 — they set daily_budget; unchanged)
### git grep -n "step_rate" — no hits outside this ticket (new name)
### rule card POST endpoint: app/brand_web/routes_brand_settings.py:71  @router.post("/api/settings/rule-cards/brands/{brand_id}/{card_key}")
(read it before choosing how the new field is validated — the endpoint decides which field keys it accepts)
### git grep -n "_brand_response(" -- 'app/*.py'
app/schedule/state.py:156:def _brand_response(conn, brand_id: str, org_id: str) -> dict:
app/schedule/routes.py  (every endpoint returns it — unchanged callers)
### grep -n "startDate\|endDate" frontend/src/components/schedule/SchedulePage.tsx
frontend/src/components/schedule/SchedulePage.tsx:43:  const [startDate, setStartDate] = useState("");
frontend/src/components/schedule/SchedulePage.tsx:44:  const [endDate, setEndDate] = useState("");
frontend/src/components/schedule/SchedulePage.tsx:191:        startDate, endDate,
frontend/src/components/schedule/SchedulePage.tsx:287-288:  updateDraft patch handling
frontend/src/components/schedule/SchedulePage.tsx:306:  <ScheduleSetup … draft={{ …, startDate, endDate }} …/>
### frontend/src/lib/settingsApi.ts:129  saveRuleCard(brandId, cardKey, fields: Record<string, number>)  (POST the card's fields)
### app/core/approval.py:56  latest(conn, *, org_id, brand_id, scope_type)  — read, not used by this ticket (see §2 baseline decision)
### app/schedule/period.py:244  _advance_if_ended  — the read-time convention this function copies
```

## Contradiction check

- **Check 1(a) (`up` from a `win` depth-2 row) vs. the spec's plan-review line** ("沒有任何追蹤到的營收 → 只回日期、
  不回金額方向"): a period with tracked revenue on a depth-3 row only (its depth-2 parent untracked) — the depth-2
  aggregate says `unclear`, the depth-3 row says `win`. Settled: depth 2 is the budget-carrying level (ADR 0066 rule 2);
  the suggestion follows the money's level. Check 1 must seed only depth-2 rows so the reading is explicit.
- **Check 1 vs. check 2 (overlap)**: the suggested dates 09-08 ~ 09-14 overlap the `planning` period 09-08 ~ 09-15 in
  the local DB — the suggestion is still made (dates are the rule), the overlap is reported; the screen does not
  hide the card. Check 2 asserts presence in `overlaps`, not absence of the suggestion.
- **Cheapest wrong implementation that leaves every check green**: (a) baseline from the rule card's current
  `daily_budget` instead of the settled period's — caught by check 1 only if the test sets the rule card to a
  different value (say 5000) than the period's 2000; make that explicit in the seed; (b) direction from the
  brand-level `settled_revenue` (orders) — caught by check 1(a) because the seed writes no orders; (c) rounding
  the percentage as a fraction (20 → ×21) — caught by 2400.
