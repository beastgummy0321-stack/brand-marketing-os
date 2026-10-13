"""app/ads/targets.py — F16-I04, re-cut by F28-I01: every campaign, system-built or imported, is
judged against ONE cost-per-result cap (docs/architecture/ads.md §6.32, screen word 上限).

`resolve()` is pure: no LLM call anywhere (ARCHITECTURE.md §0 "程式整理，LLM 判斷" — this is
arithmetic and lookups, not judgment), no write to any table. It only reads what already exists:
the one stored cap (`ads_campaign.target_cost` with `target_basis='own'`) and product economics
(via `app/ads/budget.py`). Priority, fixed (never reordered by a caller): the user's own cap
always wins; else break-even using product economics when this campaign's own result is a
purchase and a product with a cost is known (a provisional cap, screen 暫用打平 X); else
unresolved, with `missing` naming what blocks it. Never a default number, never a fallback
constant, never zero, and never this campaign's own past actual (the trailing-30-day fallback
was removed by the 2026-09-23 ruling).

Platform-neutral: this file never branches on a Meta objective string — the objective -> result
mapping lives in the Meta adapter (`app/ads/adapters/meta_read.py`), not here.
"""

from app.ads import budget, objectives, result_kinds
from app.brand_intelligence import repository as bi_repo


def effective_result_kind(campaign: dict) -> str | None:
    """A stored choice wins; internal legacy rows use explicit catalog intent only.

    Origin alone cannot imply purchase. Imported unmapped kinds remain unknown.
    """
    result_kind = campaign.get("result_kind")
    if result_kind is not None:
        return result_kind
    return None if campaign.get("origin") == "imported" else objectives.expected_result_kind(
        campaign.get("objective"),
    )


def own_cap(campaign: dict) -> float | None:
    """The user's own cap, or `None` -- the one stored value (`target_basis='own'`)."""
    if campaign.get("target_basis") == "own" and campaign.get("target_cost") is not None:
        return float(campaign["target_cost"])
    return None


def _unit_cost_with_shipping(economics: dict) -> float:
    """Known unit cost plus known shipping, after the break-even input check."""
    return float(economics["unit_variable_cost"]) + float(economics["shipping_cost"])


def resolve(conn, org_id: str, brand_id: str, campaign: dict, *,
            product_id: str | None = None) -> dict:
    """`campaign` is one `ads_campaign` row (a dict, e.g. from `repository.get_campaign`).
    `product_id` is the caller's explicit product choice -- it overrides
    `context_json.product_ids` when given.

    Returns the cap view (feature F28 "Cap storage"): `{value, basis: "own"|"break_even"|None,
    own_value, break_even, price, cost, product_id, knowledge_product_id, result_kind,
    result_label, missing, revision}` (`knowledge_product_id`, F43-I04: the first knowledge
    product of `product_id`, `None` without one). `break_even`/`price` are read off product
    economics even when an own cap is set (the ruler's 打平 mark, ROAS 參考 = price ÷ cap).
    `cost` (F29 Contract D) is the unit cost including shipping from the SAME economics row
    `break_even` came from, so the screen's 「售價 X − 成本含運 Y」 subtracts to the break-even
    it shows; `None` whenever `break_even` is (no purchase result kind, no product, no cost).
    `economics_basis` preserves the economics currency and missing price, cost, shipping or
    sales-mix evidence independently of grading. An own cap remains usable even when a
    margin estimate is unavailable. `org_id` stays in the signature (every caller passes
    the tenant) although no read here needs it since the trailing-30 fallback was removed."""
    result_kind = effective_result_kind(campaign)
    own_value = own_cap(campaign)

    missing: list[str] = []
    economics_missing: list[str] = []
    economics_currency = None
    break_even = price = cost = used_product_id = None
    if result_kind is None:
        missing.append("result_kind")
    elif result_kind == "purchase":
        product_ids = (
            [product_id] if product_id
            else (campaign.get("context_json") or {}).get("product_ids") or []
        )
        if not product_ids:
            missing.append("product")
            economics_missing.append("product")
        elif len(set(product_ids)) > 1:
            missing.append("sales_mix")
            economics_missing.append("sales_mix")
        else:
            economics, used_product_id = budget.economics_for(conn, brand_id, product_ids)
            used_product_id = used_product_id or product_ids[0]
            for field, reason in (("selling_price", "product_price"),
                                  ("unit_variable_cost", "product_cost"),
                                  ("shipping_cost", "shipping_cost"), ("currency", "currency")):
                if economics is None or economics.get(field) is None:
                    economics_missing.append(reason)
            economics_currency = economics.get("currency") if economics else None
            break_even = None if economics_missing else budget.breakeven_cpa(economics)
            if economics is not None and break_even is not None:
                cost = _unit_cost_with_shipping(economics)
            else:
                missing.extend(economics_missing)
            if economics and economics.get("selling_price") is not None:
                price = float(economics["selling_price"])

    if own_value is not None:
        value, basis = own_value, "own"
    elif break_even is not None:
        value, basis = break_even, "break_even"
    else:
        value, basis = None, None
    # F43-I04: the knowledge product behind the sell-way (first of `knowledge_product_ids`), so
    # the 「去填商品成本」 links can open that product's 賣法與價格 step.
    knowledge_product_id = (
        bi_repo.knowledge_product_ids(conn, brand_id, used_product_id)[0]
        if used_product_id else None
    )
    return {
        "value": value, "basis": basis, "own_value": own_value, "break_even": break_even,
        "price": price, "cost": cost, "product_id": used_product_id,
        "knowledge_product_id": knowledge_product_id, "result_kind": result_kind,
        "result_label": result_kinds.label(result_kind),
        # An own cap is a complete answer: nothing is missing for grading any more.
        "missing": [] if own_value is not None else missing,
        "economics_basis": {"currency": economics_currency, "missing": economics_missing},
        "revision": campaign.get("target_revision") or 0,
    }
