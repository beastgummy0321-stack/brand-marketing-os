"""app/ads/budget.py — F03-I04: the money numbers are computed by the program, not by a model
(ARCHITECTURE.md §0). Serves the strategy link of the golden path: input is `product_economics`
(read through `app.brand_intelligence.repository` — the brand-permanent layer's own public
functions, never raw SQL against its table) and this brand's own spend history; output is the
three budget scenarios the strategy tab shows and the `basis` payload naming what each number came
from and which parts are estimates. Pure functions: no HTTP, no model call, no write to any table,
nothing here reads a rule card (ruling 4: AI only pre-fills, the arithmetic is ours).

`history` design note (no other caller exists yet, so this is this issue's call): the last-30-day
median CPA and the previous campaign's daily budget are aggregates over `ads_external_daily`
through `repository.performance_rows`'s join (`repository.budget_history` computes them once);
`scenarios()` takes the result as `history` (`None`/falsy when the brand has no settled spend
yet) instead of querying it itself, so this file stays a pure dict-in/dict-out calculator that
a unit test can drive without a database.
"""

import math
from typing import SupportsFloat, overload

from app.brand_intelligence import repository as bi_repo
from app.core import input_rules

# key, 中文 label, 每天想要的購買數 — ruling 4: 2 / 5 / 10; labels per F28 (keys unchanged).
_COLD_START_EVENTS = (
    ("minimum", "最低", 2), ("recommended", "穩定成長", 5), ("aggressive", "積極", 10),
)

# key, 中文 label, 上一期 daily budget 的乘數 — ruling 4: x0.6 / x1 / x1.6; labels per F28.
_HISTORY_MULTIPLIERS = (
    ("conservative", "保守", 0.6), ("recommended", "照上一期", 1.0), ("aggressive", "積極", 1.6),
)

# F28-I03: the extra row added when the campaign has a budget cap (`constraints_json.budget`).
CAP_KEY = "cap"
_CAP_LABEL = "照預算上限"


def breakeven_cpa(economics: dict | None) -> float | None:
    """打平 CPA＝一次轉換的價值 = (售價 − 單位成本 − 運費) x 成交率，from one `product_economics`
    row. 商品（`close_rate` 是 `None`）不帶成交率，一次轉換就是一次成交，行為與 F05 之前完全
    相同；服務／名單型帶 `close_rate`（百分比 0–100，乘數經 `input_rules.rate_fraction`，F50
    Contract I），值是每筆名單／每次成交的期望毛利。`None` when the row is
    missing or `unit_variable_cost` is `None` — an unknown cost stays unknown, never a guessed
    margin (Blocked-if: no fallback to the `gross_margin` rule card)."""
    if not economics:
        return None
    price = economics.get("selling_price")
    unit_cost = economics.get("unit_variable_cost")
    if price is None or unit_cost is None:
        return None
    shipping = economics.get("shipping_cost") or 0
    value = float(price) - float(unit_cost) - float(shipping)
    close_rate = economics.get("close_rate")
    return value if close_rate is None else value * input_rules.rate_fraction(close_rate)


# -- F48 Contract M: the one money calculator -----------------------------------------------------


@overload
def whole(value: None) -> None: ...
@overload
def whole(value: SupportsFloat | str) -> int: ...
def whole(value):
    """A money figure as a whole number, half up (`floor(x + 0.5)`) -- the only rounding of a
    money figure in `app/ads` (Python's `round` is banker's rounding: 2.5 -> 2). `None` passes
    through."""
    return None if value is None else math.floor(float(value) + 0.5)


def daily_of(total, days):
    """One day's whole budget of a period total -- `floor(total / days)`, the one exception to
    half-up, so the structure never commits more than the chosen total and never trips the cap
    gate by rounding. `None` without a total or a positive length."""
    if total is None or days is None or days <= 0:
        return None
    return math.floor(float(total) / days)


def total_of(daily_sum, days):
    """The period total of a daily amount -- `daily_sum x days`, exact. `None` when either side is
    unknown (no daily amount, or no positive length)."""
    if daily_sum is None or days is None or days <= 0:
        return None
    product = float(daily_sum) * days
    return int(product) if product.is_integer() else product


def preview(chosen, days) -> dict | None:
    """`budget_preview` of a chosen period total (Contract M): the whole daily budget the structure
    will get and the period total that daily really spends; `note` only when the two totals
    differ. `None` before a total is chosen."""
    if chosen is None:
        return None
    chosen = float(chosen)
    chosen = int(chosen) if chosen.is_integer() else chosen
    daily = daily_of(chosen, days)
    total = total_of(daily, days)
    note = None
    if total is not None and total != chosen:
        note = f"每天要是整數，這期實際 {total:,}"
    return {"daily": daily, "total": total, "chosen": chosen, "note": note}


def resplit(daily_total: int, groups: list[dict], allocation: list[dict]) -> dict:
    """Decision 8: a new total after adoption re-splits the ad sets by the stored allocation
    pcts -> `{group_id: new daily}` summing exactly to `daily_total` (`split`). A role's share is
    divided evenly among that role's groups; a group whose role is not in the allocation (added
    by hand after adoption) keeps its current share of the daily sum, the allocation roles share
    the rest."""
    pct = {row["role"]: float(row.get("pct") or 0) / 100 for row in allocation}
    old_sum = sum(float(g["daily_budget"] or 0) for g in groups)
    outside = [g for g in groups if g["role"] not in pct]
    outside_share = (
        sum(float(g["daily_budget"] or 0) for g in outside) / old_sum if old_sum > 0 else 0.0
    )
    present = {g["role"] for g in groups if g["role"] in pct}
    # Normalise only when an allocation role has no group left (its share goes to the others).
    role_sum = 1.0 if present == set(pct) else sum(pct[r] for r in present)
    weights = {}
    for group in groups:
        role = group["role"]
        if role in pct:
            count = sum(1 for g in groups if g["role"] == role)
            share = pct[role] / role_sum if role_sum > 0 else 1 / len(present)
            weights[group["id"]] = (1 - outside_share) * share / count
        else:
            weights[group["id"]] = (
                float(group["daily_budget"] or 0) / old_sum if old_sum > 0 else 0.0
            )
    return {row["label"]: row["amount"] for row in split(daily_total, weights)}


def _economics_for(
    conn, brand_id: str, product_ids: list[str] | None,
) -> tuple[dict | None, str | None]:
    """First `product_id` (in order) whose economics yields a breakeven CPA. Multiple products on
    one campaign is a later-issue shape; picking the first computable one is the minimal, honest
    choice for this issue — the `basis` always names which product it used.

    F43-I04: a campaign always carries a sell-way id (only sell-ways are pickable), so the old
    parent -> first-sell-way fallback is gone; the numbers are the sell-way's effective economics
    (`get_product_economics`: a bundle's NULL cost is Σ its components' costs)."""
    for product_id in product_ids or []:
        economics = bi_repo.get_product_economics(conn, brand_id, product_id)
        if breakeven_cpa(economics) is not None:
            return economics, product_id
    return None, None


def economics_for(
    conn, brand_id: str, product_ids: list[str] | None,
) -> tuple[dict | None, str | None]:
    """Public wrapper for `_economics_for` -- F16-I04's `app/ads/targets.py::resolve()` needs the
    exact same "first computable product" lookup this file's own `scenarios()` already uses; no
    second implementation of that rule."""
    return _economics_for(conn, brand_id, product_ids)


def scenarios(conn, org_id, brand_id, *, product_ids: list[str] | None, days: int,
              history: dict | None, conversion_label: str = "購買",
              cap: float | None = None) -> dict:
    """Three budget scenarios for the strategy tab. `history` truthy (has a `last_daily_budget`)
    means this brand has settled spend to scale from; otherwise cold start applies: the
    campaign's one cap (`targets.resolve()["value"]`, F28-I01 -- no ratio on top of it) x
    purchases per day. `conversion_label` 是這個品牌的「購買」該叫什麼
    （`judgment.conversion_labels()["conversion"]`）——只換冷啟動 caption 裡的名詞。"""
    if history and history.get("last_daily_budget") is not None:
        return _history_scenarios(history, days)
    _economics, product_id = _economics_for(conn, brand_id, product_ids)
    return _cold_start_scenarios(cap, product_id, days, conversion_label)


def _cold_start_scenarios(
    cap: float | None, product_id: str | None, days: int, conversion_label: str,
) -> dict:
    scenario_rows = []
    for key, label, events in _COLD_START_EVENTS:
        daily = whole(cap * events) if cap is not None else None
        total = total_of(daily, days)
        scenario_rows.append({
            "key": key, "label": label, "daily": daily, "total": total,
            "caption": f"冷啟動估算：上限 x 每天 {events} 筆{conversion_label}",
        })
    basis = {
        "mode": "cold_start", "product_id": product_id, "cap": cap,
        "assumption": "每天購買數（2／5／10）是假設，非實測",
    }
    return {
        "mode": "cold_start", "scenarios": scenario_rows, "recommended": "recommended",
        "basis": basis,
    }


def _history_scenarios(history: dict, days: int) -> dict:
    last_daily = float(history["last_daily_budget"])
    cpa = history.get("cpa")
    base_text = history.get("source_text") or "上一期日預算"
    scenario_rows = []
    for key, label, mult in _HISTORY_MULTIPLIERS:
        daily = whole(last_daily * mult)
        total = total_of(daily, days)
        scenario_rows.append({
            "key": key, "label": label, "daily": daily, "total": total,
            # F03-I05 corrects this caption: the multiplication is base x0.6/1/1.6 — the
            # 30-day median CPA is context in `basis`, never a factor in this arithmetic.
            # F05-I11: `base_text` names where the base number came from (this brand's own
            # 迴圈 or its bound ad account) — never a hard-coded platform name here.
            # F36-I05: printed unchanged — the day count (「有投放的 N 天」) already lives in
            # `source_text`; this caption never re-adds a 「30 天」 of its own.
            "caption": f"{base_text} NT${whole(last_daily)} ×{mult:g}",
        })
    basis = {
        "mode": "history", "cpa": cpa, "source": history.get("source"),
        "sample_days": history.get("sample_days"), "sample_ads": history.get("sample_ads"),
    }
    return {
        "mode": "history", "scenarios": scenario_rows, "recommended": "recommended",
        "basis": basis,
    }


def split(total: float, weights: dict) -> list:
    """`total` split by `weights` (label -> share, e.g. `{"新客": 0.5, "再行銷": 0.3, "探索":
    0.2}`) into whole NT$ amounts that sum exactly to `total`: each share is floored, and the
    leftover goes to the largest share so the table always adds up."""
    if not weights:
        return []
    total = whole(total)
    amounts = {label: int(total * share) for label, share in weights.items()}
    remainder = total - sum(amounts.values())
    if remainder:
        largest_label = max(weights, key=lambda label: weights[label])
        amounts[largest_label] += remainder
    return [{"label": label, "amount": amounts[label]} for label in weights]


def budget_cap_of(constraints: dict | None) -> int | None:
    """The campaign's budget cap (`constraints_json.budget`, F28-I03) as whole money, or `None`.

    Unset, zero, negative, non-finite, bool or non-numeric all mean "no cap" -- the soft warning
    never fires on a number nobody set. A numeric string (the wizard's chip input) is read as
    its number."""
    value = (constraints or {}).get("budget")
    if isinstance(value, bool):
        return None
    if isinstance(value, str):
        try:
            value = float(value.replace(",", "").strip())
        except ValueError:
            return None
    if not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0:
        return None
    return whole(value)


def amount_over_cap(total: float | None, budget_cap: float | None) -> int | None:
    """How much `total` is above `budget_cap`: `None` when either is unknown, `0` when within
    (a total exactly at the cap is not over)."""
    if total is None or budget_cap is None:
        return None
    return max(whole(float(total) - budget_cap), 0)


def _with_budget_cap(result: dict, budget_cap: int | None, days: int) -> dict:
    """Add the budget-cap view to a scenario result (F28-I03, ads.md §6.32 "Budget cap is a
    soft warning"): `budget_cap`, per-row `over_cap`, the 照預算上限 row when a cap exists, and
    `recommended` moved to that row when the old recommendation is over the cap. Idempotent:
    a stored snapshot's earlier cap row and moved recommendation are dropped first."""
    rows = [r for r in result.get("scenarios", []) if r.get("key") != CAP_KEY]
    recommended = result.get("recommended")
    if recommended == CAP_KEY or recommended not in {r["key"] for r in rows}:
        recommended = "recommended"
    if budget_cap is not None:
        # Contract M: the cap row's daily is `daily_of(cap)` and its total what that daily really
        # spends, so `over_cap` is 0 by construction. Without a period there is no daily and the
        # cap itself stays the row's total.
        cap_daily = daily_of(budget_cap, days)
        rows.insert(min(1, len(rows)), {
            "key": CAP_KEY, "label": _CAP_LABEL, "daily": cap_daily,
            "total": budget_cap if cap_daily is None else total_of(cap_daily, days),
            "caption": f"用滿你設的預算上限 NT${budget_cap:,}",
        })
    rows = [{**r, "over_cap": amount_over_cap(r.get("total"), budget_cap)} for r in rows]
    old = next((r for r in rows if r["key"] == recommended), None)
    if old is not None and old["over_cap"]:
        recommended = CAP_KEY
    return {**result, "scenarios": rows, "recommended": recommended, "budget_cap": budget_cap}


def _recommended_with_amount(result: dict) -> str | None:
    """F29 Contract D: the recommended row the screen shows always has an amount -- the
    projected recommendation (the §6.32 over-cap rule already applied) when its total is known,
    else the first row in display order with a known total, else `None`."""
    rows = result.get("scenarios", [])
    picked = next((r for r in rows if r["key"] == result.get("recommended")), None)
    if picked is not None and picked.get("total") is not None:
        return picked["key"]
    return next((r["key"] for r in rows if r.get("total") is not None), None)


def current_scenarios(stored: dict, campaign: dict, conversion_label: str = "購買",
                      *, cap: float | None = None) -> dict:
    """Project recommendations from current inputs, without changing adopted money.

    History rows retain their observed daily basis; cold starts use the campaign's one cap
    (`cap`, resolved by the caller through `targets.resolve`). No cap is unknown, never an
    old product estimate. Called on every detail/selection read so stored snapshots reconcile,
    including the budget cap (`constraints_json.budget`, F28-I03) and the current row labels.
    """
    days = period_days(campaign)
    budget_cap = budget_cap_of(campaign.get("constraints_json"))
    if stored.get("mode") == "cold_start":
        result = _cold_start_scenarios(cap, None, days, conversion_label)
        result["basis"].update({
            "days": days, "source_text": "目前的上限" if cap else "尚未設定上限",
        })
        return _with_budget_cap(result, budget_cap, days)
    labels = {key: label for key, label, _mult in _HISTORY_MULTIPLIERS}
    result = {**stored, "basis": {**stored.get("basis", {}), "days": days}}
    result["scenarios"] = [
        {**r, "label": labels.get(r["key"], r.get("label")),
         "total": total_of(r.get("daily"), days)}
        for r in stored.get("scenarios", []) if r.get("key") != CAP_KEY
    ]
    return _with_budget_cap(result, budget_cap, days)


def period_days(campaign: dict) -> int:
    """The campaign's length in days, both ends inclusive; 0 without both dates."""
    start, end = campaign.get("start_date"), campaign.get("end_date")
    return max((end - start).days + 1, 0) if start and end else 0


def reconcile_campaign(campaign: dict, conversion_label: str = "購買",
                       *, cap: float | None = None) -> dict:
    """Return an up-to-date projection. Never write budget_planned or group budgets.

    This is the campaign read every screen gets its scenarios from, so the recommendation is
    narrowed here to one that has an amount (`_recommended_with_amount`, may be `None`).
    `current_scenarios` itself keeps a row key: `strategy.generate` looks its recommended row up
    without a default (a total of `None` is fine there, a missing row is not).

    F48 Contract M: serves `budget_preview` (`preview` of `budget_planned`). Allocation amounts
    are a projection only while nothing is chosen (`budget_planned is None`); once a total is
    selected the stored amounts stand (no re-split on read), and once groups exist the campaign
    detail serves them from the groups (`adopted_allocation`)."""
    campaign = {**campaign, "budget_preview": preview(campaign.get("budget_planned"),
                                                      period_days(campaign))}
    basis = campaign.get("budget_basis_json") or {}
    stored = basis.get("scenarios")
    if not stored:
        return campaign
    scenarios_now = current_scenarios(stored, campaign, conversion_label, cap=cap)
    scenarios_now["recommended"] = _recommended_with_amount(scenarios_now)
    strategy_now = dict(basis.get("strategy") or {})
    allocation = strategy_now.get("allocation") or []
    if allocation and campaign.get("budget_planned") is None:
        recommended = next((r for r in scenarios_now["scenarios"]
                            if r["key"] == scenarios_now["recommended"]), {})
        selected = recommended.get("total")
        weights = {str(i): r["pct"] / 100 for i, r in enumerate(allocation)}
        amounts = split(selected, weights) if selected is not None else []
        strategy_now["allocation"] = [
            {**r, "amount": amounts[i]["amount"] if amounts else None}
            for i, r in enumerate(allocation)
        ]
    return {**campaign, "budget_basis_json": {
        **basis, "scenarios": scenarios_now, "strategy": strategy_now,
    }}


def adopted_allocation(allocation: list[dict], groups: list[dict], days: int) -> list[dict]:
    """After adoption the money lives in the groups: each allocation row's amount is
    `total_of(Σ that role's group daily, days)` (Contract M)."""
    by_role: dict = {}
    for group in groups:
        by_role[group["role"]] = by_role.get(group["role"], 0) + float(group["daily_budget"] or 0)
    return [{**row, "amount": total_of(by_role.get(row["role"], 0), days)} for row in allocation]
