"""app/ads/budget.py — F03-I04: the money numbers are computed by the program, not by a model
(ARCHITECTURE.md §0). Serves the strategy link of the golden path: input is `product_economics`
(read through `app.brand_intelligence.repository` — the brand-permanent layer's own public
functions, never raw SQL against its table) and this brand's own spend history; output is the
three budget scenarios the strategy tab shows and the `basis` payload naming what each number came
from and which parts are estimates. Pure functions: no HTTP, no model call, no write to any table,
nothing here reads a rule card (ruling 4: AI only pre-fills, the arithmetic is ours).

`history` design note (no other caller exists yet, so this is this issue's call): the last-30-day
median CPA and the previous campaign's daily budget are aggregates over `ads_outcome_daily`
(this module's own table) that a future repository function computes once; `scenarios()` takes the
result as `history` (`None`/falsy when the brand has no settled spend yet) instead of querying it
itself, so this file stays a pure dict-in/dict-out calculator that a unit test can drive without a
database.
"""

import math

from app.brand_intelligence import repository as bi_repo

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
    相同；服務／名單型帶 `close_rate`，值是每筆名單／每次成交的期望毛利。`None` when the row is
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
    return value if close_rate is None else value * float(close_rate)


def _round_money(value: float | None) -> float | None:
    return None if value is None else round(value)


def _economics_for(
    conn, brand_id: str, product_ids: list[str] | None,
) -> tuple[dict | None, str | None]:
    """First `product_id` (in order) whose economics yields a breakeven CPA. Multiple products on
    one campaign is a later-issue shape; picking the first computable one is the minimal, honest
    choice for this issue — the `basis` always names which product it used.

    一個產品、很多賣法（ARCHITECTURE.md §8 第 1 條）：金額掛賣法，母產品自己沒有
    `product_economics`。選到母產品時取它的第一個賣法——建立順序（`created_at, id`），精靈先寫
    「單品」所以第一個就是單品；不能用 `list_products` 的名稱順序（F31-I01：「3 入組」會排在
    「單品」前面）。`basis` 記下實際用的那個賣法的 id，不是母產品的 id。"""
    for product_id in product_ids or []:
        economics = bi_repo.get_product_economics(conn, brand_id, product_id)
        if breakeven_cpa(economics) is not None:
            return economics, product_id
        if economics is None:
            children = sorted(
                (p for p in bi_repo.list_products(conn, brand_id)
                 if p["parent_id"] == product_id),
                key=lambda p: (p["created_at"], p["id"]),
            )
            if children:
                sell_way_id = children[0]["id"]
                sell_way_economics = bi_repo.get_product_economics(conn, brand_id, sell_way_id)
                if breakeven_cpa(sell_way_economics) is not None:
                    return sell_way_economics, sell_way_id
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
        daily = _round_money(cap * events) if cap is not None else None
        total = _round_money(daily * days) if daily is not None and days else None
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
        daily = round(last_daily * mult)
        total = round(daily * days) if days else None
        scenario_rows.append({
            "key": key, "label": label, "daily": daily, "total": total,
            # F03-I05 corrects this caption: the multiplication is base x0.6/1/1.6 — the
            # 30-day median CPA is context in `basis`, never a factor in this arithmetic.
            # F05-I11: `base_text` names where the base number came from (this brand's own
            # 迴圈 or its bound ad account) — never a hard-coded platform name here.
            "caption": f"{base_text} NT${round(last_daily)} ×{mult:g}",
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
    total = round(total)
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
    return round(value)


def amount_over_cap(total: float | None, budget_cap: float | None) -> int | None:
    """How much `total` is above `budget_cap`: `None` when either is unknown, `0` when within
    (a total exactly at the cap is not over)."""
    if total is None or budget_cap is None:
        return None
    return max(round(float(total) - budget_cap), 0)


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
        rows.insert(min(1, len(rows)), {
            "key": CAP_KEY, "label": _CAP_LABEL,
            "daily": round(budget_cap / days) if days else None, "total": budget_cap,
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
    start, end = campaign.get("start_date"), campaign.get("end_date")
    days = max((end - start).days + 1, 0) if start and end else 0
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
         "total": round(r["daily"] * days) if r.get("daily") is not None and days else None}
        for r in stored.get("scenarios", []) if r.get("key") != CAP_KEY
    ]
    return _with_budget_cap(result, budget_cap, days)


def reconcile_campaign(campaign: dict, conversion_label: str = "購買",
                       *, cap: float | None = None) -> dict:
    """Return an up-to-date projection. Never write budget_planned or group budgets.

    This is the campaign read every screen gets its scenarios from, so the recommendation is
    narrowed here to one that has an amount (`_recommended_with_amount`, may be `None`).
    `current_scenarios` itself keeps a row key: `strategy.generate` looks its recommended row up
    without a default (a total of `None` is fine there, a missing row is not)."""
    basis = campaign.get("budget_basis_json") or {}
    stored = basis.get("scenarios")
    if not stored:
        return campaign
    scenarios_now = current_scenarios(stored, campaign, conversion_label, cap=cap)
    scenarios_now["recommended"] = _recommended_with_amount(scenarios_now)
    strategy_now = dict(basis.get("strategy") or {})
    allocation = strategy_now.get("allocation") or []
    selected = campaign.get("budget_planned")
    if selected is None:
        recommended = next((r for r in scenarios_now["scenarios"]
                            if r["key"] == scenarios_now["recommended"]), {})
        selected = recommended.get("total")
    if allocation:
        amounts = split(selected, {str(i): r["pct"] / 100 for i, r in enumerate(allocation)}) \
            if selected is not None else []
        strategy_now["allocation"] = [
            {**r, "amount": amounts[i]["amount"] if amounts else None}
            for i, r in enumerate(allocation)
        ]
    return {**campaign, "budget_basis_json": {
        **basis, "scenarios": scenarios_now, "strategy": strategy_now,
    }}
