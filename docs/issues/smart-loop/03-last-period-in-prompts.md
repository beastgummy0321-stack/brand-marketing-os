# 03 — The plan and tree prompts carry last period's scored nodes

Route B: behaviour change (two prompts gain a section; one screen sentence); no schema, no money path, no
permission path. Board row 越排越好, spec cut 2. Depends on ticket 01 (rows exist) and ticket 02 (`period_repository.py`
holds the period SQL; this ticket adds one read there). Staffing: Sonnet implements, a different Sonnet reviews.

Why: after ticket 01 the system remembers what each node did, but neither `jobs.schedule_plan()` nor
`jobs.schedule_tree()` reads it — `context_compiler.py` has zero references to `campaign_period` /
`period_node_result` (2026-09-08). The plan prompt already carries this month's ad-level performance (plan-quality
ticket 01, 2026-09-08, cited by 3/3 runs); the tree prompt carries nothing of the kind. "Last period" is the
memory; this ticket puts it in front of both agents. Ticket 04 adds the name-continuity instruction on top of it.

Not this ticket: telling the tree agent which names to keep (04); the next-period budget/date suggestion (05);
any change to the department task files (`app/departments/ads/*.md`); any change to `app/meta`.

## What

### 1. Read — `app/schedule/period_repository.py`

```
latest_settled_period(conn, org_id: str, brand_id: str) -> dict | None
```
`SELECT * FROM campaign_period WHERE org_id = %s AND brand_id = %s AND status = 'settled' ORDER BY settled_at DESC
LIMIT 1`. Its node rows come from the existing `period_node_results(conn, org_id, brand_id, period_id)`.

### 2. Text — `app/schedule/jobs.py`

```
_last_period_text(conn, org_id: str, brand_id: str) -> str      # "" when no settled period
```
Reads `latest_settled_period()`; `""` when `None` or when its `period_node_results()` is empty (a settled period
with no bound nodes has nothing to say — the brand-level numbers alone are not a memory of decisions).
Coordinate keys become labels through `performance_mod._coordinate_labels(conn, org_id, brand_id)` (same
module); an unknown key prints as the key. Verdict labels: `賺` / `賠` / `看不出` for `win` / `lose` / `unclear`,
one dict `VERDICT_LABELS` in `app/schedule/scoring.py` (jobs imports scoring; scoring never imports jobs — no
cycle). Depth labels: `組合` / `廣告` (2 / 3). ROAS cells through `diagnosis_mod._roas_text`, share as `55%`,
spend as `1,300`. Literal (numbers are the shape, not a measurement):

```
【上一期】2026-09-07 ~ 2026-09-14｜日預算 2,000｜結算花費 1,068｜這期間全通路營收 0｜打平線 1.00x
判決：賺 1、賠 1、看不出 8（組合 3、廣告 7）
| 節點 | 層 | 座標 | 核准比例 | 實花 | 實花佔比 | 保守 ROAS | 樂觀 ROAS | 判決 |
|---|---|---|---|---|---|---|---|---|
| Beast Gummy｜效率補給 | 組合 | — | 55% | 600 | 56% | 1.50x | 3.00x | 賺 |
| Beast Gummy｜效率補給｜再行銷 | 廣告 | 上班族／專注力／效率／… | — | 600 | 56% | 1.50x | 3.00x | 賺 |
| Beast Gummy｜送禮組合 | 組合 | — | 20% | 468 | 44% | 0.40x | 0.80x | 賠 |
上一期的判決是這一期的起點：說明哪些節點要延續、哪些要換、為什麼；「看不出」不是失敗，是樣本不夠。
```

- `實花佔比` = this row's `actual_spend` ÷ the sum of `actual_spend` over rows of the **same depth** (never across
  depths, ADR 0066 rule 2); `—` when that sum is 0.
- 座標 = the seven labels joined with `／`, only on depth 3; `—` on depth 2.
- 打平線 = the rows' `breakeven_roas` (they all carry the same value; print `算不出` when `NULL`).
- The closing instruction line is printed once, at the end of the section, in **both** prompts.

### 3. Position

`schedule_plan()`: the section becomes the last element of the prompt tuple, **after** `performance_text`
(the this-month section from plan-quality ticket 01): `(department_text, methodology_result.text, params_text,
brand_context, performance_text, last_period_text)`. `schedule_tree()`: last element after `brand_context`.
Reason: both end with an instruction, and `docs/contracts/schedule.md` "Position in the prompt decides whether an
instruction runs". Measured 2026-09-08: plan prompt ≈ 11k chars before this section; the T8b finding was at 21k.
Empty string is filtered by the existing `if section`.

### 4. Screen — `frontend/src/components/schedule/PeriodPanel.tsx`

One sentence under the settled numbers when `node_results.length > 0`:
「花費是品牌層的數字（含未登記的廣告）；下表只算這期綁定的節點。」 — the walk of ticket 01 saw 1,068 vs a table
of zeros and asked; ADR 0055 §11 is why. Wording per `docs/design-system.md`.

### 5. Contract page — `docs/contracts/schedule.md`

"Module-local and reversible" gains one bullet: both generation prompts carry the latest settled period's node
results as their last section (`period_repository.latest_settled_period()` → `jobs._last_period_text()`);
absent when no settled period or no scored nodes.

## How we know it's done

Run with `BRAND_OS_LLM_PROVIDER` unset.

1. `app/tests/test_schedule.py`, in the bound-account base (the class whose `setUp` calls `meta_repo.bind`):
   create a settled period with two node rows written through `period_repo.write_settlement()` +
   `period_repo.replace_period_node_results()` (a depth-2 row `actual_spend 600`, conservative 1.5, optimistic
   3.0, verdict `win`, `approved_share 0.55`; a depth-3 row with `coordinates_json` using a key that exists in the
   brand's `brand_coordinate` seed and verdict `lose`). POST a plan, run the worker, read
   `fake.calls[0]["messages"][0]["content"]`: contains `【上一期】`, the depth-2 node name, `賺`, `賠`, `55%`,
   `1.50x`, the coordinate **label** (not the key), and `index("【上一期】") > index("【這個帳戶目前的成效】")`.
   Then POST a tree (`plan_index 0`), run the worker: the tree prompt contains `【上一期】` and the same node name,
   and `index("【上一期】") > index("CAMPAIGN-TREE-TASK-V1")`. Red proof: drop the element from the plan tuple → first
   assertion fails; drop it from the tree tuple → second fails.
2. Same base: no settled period → neither prompt contains `【上一期】`; a settled period with zero node rows → same.
3. `實花佔比` is computed within one depth: with the two rows above (different depths) both print `100%`, not
   `50%`. Add this assertion to check 1.
4. Gate, verbatim: `uv run ruff check app && uv run pyright && uv run pytest app/tests/test_schedule.py app/tests/test_schedule_period.py app/tests/test_architecture_boundaries.py -q`
   then `cd frontend && npm run build && npm run e2e` (the panel sentence is a frontend change).
5. Ratchets: measure `_line_totals()` and `_module_sizes()["app/schedule"]` before you start (ticket 02 just
   moved them) and after; **this ticket authorizes raising both to the measured value after the change** with a
   one-line reason at each constant (production: one read + one renderer; tests: checks 1–3 name the prompt
   contract). No other list moves.
6. Acceptance on a restarted backend + worker: 排程 → the settled period 2026-09-07 panel shows the new sentence
   → 出方案 → the narrative refers to 上一期 (any of: 上一期, 上期, the settled period's dates, a node name from
   the table, or 看不出); count how many of the ten node names it mentions. Then 展開活動樹 for plan 1 → the tree
   narrative or node names refer to last period the same way. The counts are reported, not judged.

## Shared files touched

Files edited: `app/schedule/period_repository.py` (one read), `app/schedule/jobs.py` (`_last_period_text`, two
tuples), `app/schedule/scoring.py` (`VERDICT_LABELS`), `frontend/src/components/schedule/PeriodPanel.tsx`,
`app/tests/test_schedule.py`, `app/tests/test_architecture_boundaries.py` (two constants),
`docs/contracts/schedule.md`.

No name stops existing. The two prompt tuples change position/meaning — scanned 2026-09-08 (before ticket 02's
move; the `jobs.py` lines are unaffected by it):

```
### grep -n "performance_text\|brand_context) if section" app/schedule/jobs.py
app/schedule/jobs.py:162:def _account_performance_text(perf: dict, breakeven: tuple[float | None, str]) -> str:
app/schedule/jobs.py:240:        performance_text = _account_performance_text(performance, breakeven)
app/schedule/jobs.py:244:             performance_text) if section                      # plan tuple, schedule_plan()
app/schedule/jobs.py:305:            (department_text, methodology_result.text, params_text, brand_context) if section   # tree tuple
### git grep -n "_coordinate_labels"
app/schedule/diagnosis.py:36:# （不另開一份清單）——`performance._coordinate_labels()` 給的是座標**值**的 label，這裡是
app/schedule/performance.py:102:def _coordinate_labels(conn, org_id: str, brand_id: str) -> dict:
app/schedule/performance.py:210:    labels = _coordinate_labels(conn, org_id, brand_id)
### git grep -n "CAMPAIGN-TREE-TASK-V1"
app/departments/ads/campaign_tree.md:7:任務代號：CAMPAIGN-TREE-TASK-V1（本行是這份任務檔的識別行，請照樣保留，不要在回覆裡重複貼出）。
app/tests/test_schedule.py:982:        self.assertIn("CAMPAIGN-TREE-TASK-V1", prompt_text)
### git grep -n "【這個帳戶目前的成效】" -- 'app/*.py'
app/schedule/jobs.py:175:            "【這個帳戶目前的成效】\n"
app/schedule/jobs.py:185:    out = [f"【這個帳戶目前的成效】（Meta 廣告層，{window['start_date']} ~ {window['end_date']}）"]
app/tests/test_schedule.py:1755:        # 拿來跟 `【這個帳戶目前的成效】` 比 index 先後。
app/tests/test_schedule.py:1770:        self.assertIn("【這個帳戶目前的成效】", prompt_text)
app/tests/test_schedule.py:1776:        performance_index = prompt_text.index("【這個帳戶目前的成效】")
### grep -n "^from app.schedule" app/schedule/jobs.py
app/schedule/jobs.py:45:from app.schedule import binding as binding_mod
app/schedule/jobs.py:46:from app.schedule import diagnosis as diagnosis_mod
app/schedule/jobs.py:47:from app.schedule import performance as performance_mod
app/schedule/jobs.py:48:from app.schedule import plan as plan_mod
app/schedule/jobs.py:49:from app.schedule import repository, routes, state
### grep -n "^from app.schedule" app/schedule/scoring.py   (after ticket 02, 2026-09-08)
app/schedule/scoring.py:30:from app.schedule import diagnosis as diagnosis_mod
app/schedule/scoring.py:31:from app.schedule import performance as performance_mod
app/schedule/scoring.py:32:from app.schedule import period_repository as period_repo
app/schedule/scoring.py:33:from app.schedule import repository as schedule_repo
app/schedule/scoring.py:34:from app.schedule import tree as tree_mod
### scoring never imports jobs, so `jobs → scoring` adds no cycle. Ratchets at ticket time (after ticket 02):
### tests 20624 = TEST_LINES_CEILING 20624; app/schedule 4295 = KNOWN_MODULE_SIZES 4295 (zero headroom, see check 5).
### repository.py 625 / period_repository.py 188 / jobs.py 476 of the 800 cap.
```

## Contradiction check

- **Check 1 (section last, after the this-month section) vs. the contract's measured fact** (an instruction not
  last is ignored): the this-month section's own instruction line now sits second-to-last. Input that shows it: a
  run that cites last period but no longer cites this month's ads. Settled: the two sections are one story
  (this month's numbers, last period's verdicts); if a later probe shows the this-month citations drop from 3/3,
  that is a new issue under this goal, not a reorder inside this ticket.
- **Check 1 vs. check 2**: a brand whose latest settled period has rows but a *newer* unsettled period exists —
  `latest_settled_period()` picks by `settled_at`, not by `created_at`, so the section shows the settled one.
  Check 2 must seed exactly that (a newer `planning` period) and assert the settled one's dates appear.
- **Cheapest wrong implementation that leaves every check green**: (a) printing coordinate keys instead of labels
  — caught by check 1's label assertion only if the seeded key differs from its label (seed uses the brand's
  `brand_coordinate` rows, whose `key` ≠ `label`); (b) `實花佔比` over all rows — caught by check 3;
  (c) reading `get_latest_period()` and printing it when `status == 'settled'` — passes checks 1–2 unless check 2
  seeds the newer planning period; hence that seed is mandatory.
