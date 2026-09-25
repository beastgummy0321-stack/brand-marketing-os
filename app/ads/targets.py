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

from app.ads import budget, result_kinds
from app.brand_intelligence import repository as bi_repo


def effective_result_kind(campaign: dict) -> str | None:
    """What this campaign counts as one result. A stored choice wins; a system-built campaign
    has always been judged on purchases (`app/ads/brief.py::_OBJECTIVES` — there is no other
    tracked conversion event, `review_evidence.METRICS` has no add-to-cart/lead column); an
    imported campaign with no stored kind is unknown, never assumed."""
    result_kind = campaign.get("result_kind")
    if result_kind is not None:
        return result_kind
    return None if campaign.get("origin") == "imported" else "purchase"


def own_cap(campaign: dict) -> float | None:
    """The user's own cap, or `None` -- the one stored value (`target_basis='own'`)."""
    if campaign.get("target_basis") == "own" and campaign.get("target_cost") is not None:
        return float(campaign["target_cost"])
    return None


def resolve(conn, org_id: str, brand_id: str, campaign: dict, *,
            product_id: str | None = None) -> dict:
    """`campaign` is one `ads_campaign` row (a dict, e.g. from `repository.get_campaign`).
    `product_id` is the caller's explicit product choice -- it overrides
    `context_json.product_ids` when given.

    Returns the cap view (feature F28 "Cap storage"): `{value, basis: "own"|"break_even"|None,
    own_value, break_even, price, product_id, result_kind, result_label, missing, revision}`.
    `break_even`/`price` are read off product economics even when an own cap is set (the ruler's
    打平 mark, ROAS 參考 = price ÷ cap). `missing` only ever names `"product"`,
    `"product_cost"` or `"result_kind"`. `org_id` stays in the signature (every caller passes
    the tenant) although no read here needs it since the trailing-30 fallback was removed."""
    result_kind = effective_result_kind(campaign)
    own_value = own_cap(campaign)

    missing: list[str] = []
    break_even = price = used_product_id = None
    if result_kind is None:
        missing.append("result_kind")
    elif result_kind == "purchase":
        product_ids = (
            [product_id] if product_id
            else (campaign.get("context_json") or {}).get("product_ids") or []
        )
        if not product_ids:
            missing.append("product")
        else:
            economics, used_product_id = budget.economics_for(conn, brand_id, product_ids)
            break_even = budget.breakeven_cpa(economics)
            if break_even is None:
                missing.append("product_cost")
                # No cost yet, but a known price still feeds ROAS 參考 (price / cap).
                used_product_id = product_ids[0]
                economics = bi_repo.get_product_economics(conn, brand_id, used_product_id)
            if economics and economics.get("selling_price") is not None:
                price = float(economics["selling_price"])

    if own_value is not None:
        value, basis = own_value, "own"
    elif break_even is not None:
        value, basis = break_even, "break_even"
    else:
        value, basis = None, None
    return {
        "value": value, "basis": basis, "own_value": own_value, "break_even": break_even,
        "price": price, "product_id": used_product_id, "result_kind": result_kind,
        "result_label": result_kinds.label(result_kind),
        # An own cap is a complete answer: nothing is missing for grading any more.
        "missing": [] if own_value is not None else missing,
        "revision": campaign.get("target_revision") or 0,
    }
