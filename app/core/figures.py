"""app/core/figures.py — F51 Contract F: every ROAS and derived money figure is named by its basis,
and this table is the one place a basis is defined.

The rule (this docstring is the authority):
- A served figure's payload key IS its basis code (`roas_all_spend`, never a bare `roas`); a
  backend reader never invents a second name for the same number, and no payload under
  `app/ads`, `app/dashboard` or `app/meta/routes.py` serves a bare `roas`／`roas_conservative`／
  `roas_optimistic` (`app/tests/test_figure_basis.py`).
- Money keeps its `currency` beside it; currencies are never summed together.
- Unknown is `null` (with the payload's own reason where it has one), never 0.
- The browser prints `label` as the caption and `formula` behind a tooltip; it never restates
  them (`GET /api/figures`, read once per session).

`unit`: `ratio` prints as `2.10x`, `money` through the money formatter with its currency.

Pure data (app.core is the lowest layer): `app/main.py` serves it as `GET /api/figures`.
"""

BASES: dict[str, dict[str, str]] = {
    "roas_all_spend": {
        "label": "保守", "formula": "營收 ÷ 全部花費", "unit": "ratio",
    },
    "roas_tracked_spend": {
        "label": "樂觀", "formula": "營收 ÷ 有追到營收的那部分花費", "unit": "ratio",
    },
    "roas_at_cap": {
        "label": "花到上限時", "formula": "售價 ÷ 每筆上限", "unit": "ratio",
    },
    "roas_platform": {
        "label": "平台回報", "formula": "平台回報的購買金額 ÷ 花費", "unit": "ratio",
    },
    "roas_all_channels": {
        "label": "全通路", "formula": "全通路訂單營收 ÷ 廣告花費（只算同幣別花費）",
        "unit": "ratio",
    },
    "earn_after_cost_and_ads": {
        "label": "扣掉商品成本和廣告費", "formula": "成交數 ×（售價 − 成本含運）− 廣告費",
        "unit": "money",
    },
    "budget_to_date": {
        "label": "照預算平均花，今天應花到", "formula": "月預算 × 今天是第幾天 ÷ 本月天數",
        "unit": "money",
    },
}
