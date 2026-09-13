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

from app.brand_intelligence import repository as bi_repo

TARGET_CPA_RATIO = 0.7  # 2026-09-12 ruling 4: 目標 CPA = 打平 CPA x 0.7

# key, 中文 label, 每天想要的購買數 — ruling 4: 最低 2 / 推薦 5 / 積極 10
_COLD_START_EVENTS = (
    ("minimum", "最低", 2), ("recommended", "推薦", 5), ("aggressive", "積極", 10),
)

# key, 中文 label, 上一期 daily budget 的乘數 — ruling 4: x0.6 / x1 / x1.6
_HISTORY_MULTIPLIERS = (
    ("conservative", "保守", 0.6), ("recommended", "推薦", 1.0), ("aggressive", "積極", 1.6),
)


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


def target_cpa(breakeven: float | None) -> float | None:
    """目標 CPA = 打平 CPA x TARGET_CPA_RATIO."""
    if breakeven is None:
        return None
    return breakeven * TARGET_CPA_RATIO


def _round_money(value: float | None) -> float | None:
    return None if value is None else round(value)


def _economics_for(
    conn, brand_id: str, product_ids: list[str] | None,
) -> tuple[dict | None, str | None]:
    """First `product_id` (in order) whose economics yields a breakeven CPA. Multiple products on
    one campaign is a later-issue shape; picking the first computable one is the minimal, honest
    choice for this issue — the `basis` always names which product it used.

    一個產品、很多賣法（ARCHITECTURE.md §8 第 1 條）：金額掛賣法，母產品自己沒有
    `product_economics`。選到母產品時取它的第一個賣法（`list_products` 的既有順序，精靈先寫
    「單品」所以第一個就是單品），`basis` 記下實際用的那個賣法的 id，不是母產品的 id。"""
    for product_id in product_ids or []:
        economics = bi_repo.get_product_economics(conn, brand_id, product_id)
        if breakeven_cpa(economics) is not None:
            return economics, product_id
        if economics is None:
            children = [
                p for p in bi_repo.list_products(conn, brand_id)
                if p["parent_id"] == product_id
            ]
            if children:
                sell_way_id = children[0]["id"]
                sell_way_economics = bi_repo.get_product_economics(conn, brand_id, sell_way_id)
                if breakeven_cpa(sell_way_economics) is not None:
                    return sell_way_economics, sell_way_id
    return None, None


def scenarios(conn, org_id, brand_id, *, product_ids: list[str] | None, days: int,
              history: dict | None) -> dict:
    """Three budget scenarios for the strategy tab. `history` truthy (has a `last_daily_budget`)
    means this brand has settled spend to scale from; otherwise cold start applies (ruling 4: "沒
    投放過" falls back to target-CPA x purchase-count, even if `history` is passed but empty)."""
    if history and history.get("last_daily_budget") is not None:
        return _history_scenarios(history, days)
    economics, product_id = _economics_for(conn, brand_id, product_ids)
    target = target_cpa(breakeven_cpa(economics))
    return _cold_start_scenarios(target, product_id, days)


def _cold_start_scenarios(target: float | None, product_id: str | None, days: int) -> dict:
    scenario_rows = []
    for key, label, events in _COLD_START_EVENTS:
        daily = _round_money(target * events) if target is not None else None
        total = _round_money(daily * days) if daily is not None and days else None
        scenario_rows.append({
            "key": key, "label": label, "daily": daily, "total": total,
            "caption": f"冷啟動估算：目標 CPA x 每天 {events} 個購買",
        })
    basis = {
        "mode": "cold_start", "product_id": product_id, "target_cpa": target,
        "assumption": "每天購買數（2／5／10）是假設，非實測",
    }
    return {
        "mode": "cold_start", "scenarios": scenario_rows, "recommended": "recommended",
        "basis": basis,
    }


def _history_scenarios(history: dict, days: int) -> dict:
    last_daily = float(history["last_daily_budget"])
    cpa = history.get("cpa")
    scenario_rows = []
    for key, label, mult in _HISTORY_MULTIPLIERS:
        daily = round(last_daily * mult)
        total = round(daily * days) if days else None
        scenario_rows.append({
            "key": key, "label": label, "daily": daily, "total": total,
            # F03-I05 corrects this caption: the multiplication is 上一期日預算 x0.6/1/1.6 —
            # the 30-day median CPA is context in `basis`, never a factor in this arithmetic.
            "caption": f"上一期日預算 NT${round(last_daily)} ×{mult:g}",
        })
    basis = {
        "mode": "history", "cpa": cpa,
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
