"""app/ads/targets.py — F16-I04: give every campaign, system-built or imported, a resolvable
target cost per result.

`resolve()` is pure: no LLM call anywhere (ARCHITECTURE.md §0 "程式整理，LLM 判斷" — this is
arithmetic and lookups, not judgment), no write to any table. It only reads what already exists:
a stored user override, product economics (via `app/ads/budget.py`), and this campaign's own
synced daily rows (via `app/ads/review_evidence.py::aggregate()`, F16-I03's NULL-aware
`result_views` — never a second, divergent definition of "known"). Priority, fixed by the feature
decision (never reordered by a caller): a user-set value always wins; else break-even using
product economics when this campaign's own result is a purchase and a product is known; else this
campaign's own trailing-30-day actual cost per result, labelled provisional; else unresolved.
Never a default number, never a fallback constant, never zero.

Platform-neutral: this file never branches on a Meta objective string and never parses the
Meta-formatted `attribution_key` column — the objective -> result mapping lives in the Meta
adapter (`app/ads/adapters/meta_read.py`), not here.
"""

from datetime import timedelta

from app.ads import budget, review_evidence
from app.core import settings


# Every internal (system-built) campaign has always been judged on purchases regardless of the
# Chinese objective label it was drafted with (`app/ads/brief.py::_OBJECTIVES` — "購買"／
# "加購物車"／"名單"／"流量"／"知名度" all go through the same `success_metric`
# cpa/roas/purchases): there is no other tracked conversion event at all
# (`review_evidence.METRICS` has no add-to-cart/lead column). An imported campaign carries no
# such assumption — whether it counts a purchase as its result is only known once `result_kind`
# is known, either a stored user choice (this issue's new `ads_campaign.result_kind` column) or
# whatever its own synced rows already carry.
def _is_sales(campaign: dict) -> bool:
    result_kind = campaign.get("result_kind")
    if result_kind is not None:
        return result_kind == "purchase"
    return campaign.get("origin") != "imported"


def _trailing_30(conn, org_id: str, brand_id: str, campaign_id: str) -> tuple[dict | None, list]:
    """This campaign's own actual cost per result over its last 30 complete days (today itself
    is never complete — same rule `review_evidence.snapshot()` uses). Reuses `aggregate()`'s
    `result_views` (one per (metric_scope, currency)); `metric_scope='campaign'` only, the same
    top-level-only filter `app/ads/month_budget.py::calculate()` uses to avoid double-counting
    group/ad rows under one campaign."""
    today = settings.today_for_org(conn, org_id=org_id)
    end = today - timedelta(days=1)
    start = end - timedelta(days=29)
    rows = conn.execute(
        "SELECT * FROM ads_external_daily WHERE org_id=%s AND brand_id=%s AND campaign_id=%s "
        "AND metric_scope='campaign' AND day BETWEEN %s AND %s",
        (org_id, brand_id, campaign_id, start, end),
    ).fetchall()
    if not rows:
        return None, ["trailing_30"]
    aggregated = review_evidence.aggregate([dict(r) for r in rows], start, end)
    views = aggregated["result_views"]
    if len(views) != 1:
        # No rows of this campaign's own scope, or more than one currency in the window --
        # either way there is no single unambiguous trailing-30 number to report.
        return None, ["trailing_30"]
    view = views[0]
    if view["reason"] is not None:
        # F16-I06: `_result_view` already discriminates the three unknown shapes into three
        # distinct, truthful reasons (`mixed_result_definition`, `needs_resync` for rows that
        # literally predate the F16-I03 result columns, `result_unknown_days` for a row a result
        # mapping ran against but that genuinely has nothing to report) -- this file names no
        # reason itself, never a second, divergent guess.
        return None, [view["reason"]]
    if view["cost_per_result"] is None:
        # Known days, but zero results happened -- spend/0 is never computed (F16-I03's own
        # rule), so this is "no usable rate yet", not a fabricated zero either.
        return None, ["trailing_30"]
    return {"value": view["cost_per_result"], "result_kind": view["result_kind"]}, []


def resolve(conn, org_id: str, brand_id: str, campaign: dict, *,
            product_id: str | None = None) -> dict:
    """`campaign` is one `ads_campaign` row (a dict, e.g. from `repository.get_campaign`).
    `product_id` is the caller's explicit product choice -- the one thing an imported campaign
    must supply for break-even (it has no wizard-set `context_json.product_ids`); it overrides
    `context_json.product_ids` when given.

    Returns `{"value": float|None, "basis": "own"|"break_even"|"trailing_30"|None,
    "result_kind": str|None, "missing": [str, ...]}`.
    """
    result_kind = campaign.get("result_kind")
    if campaign.get("target_basis") == "own" and campaign.get("target_cost") is not None:
        return {
            "value": float(campaign["target_cost"]), "basis": "own",
            "result_kind": result_kind, "missing": [],
        }

    missing: list[str] = []
    if _is_sales(campaign):
        product_ids = (
            [product_id] if product_id
            else (campaign.get("context_json") or {}).get("product_ids") or []
        )
        if not product_ids:
            missing.append("product")
        else:
            economics, _ = budget.economics_for(conn, brand_id, product_ids)
            value = budget.breakeven_cpa(economics)
            if value is not None:
                return {
                    "value": value, "basis": "break_even", "result_kind": "purchase",
                    "missing": [],
                }
            missing.append("product_cost")

    trailing, trailing_missing = _trailing_30(conn, org_id, brand_id, campaign["id"])
    if trailing is not None:
        return {
            "value": trailing["value"], "basis": "trailing_30",
            "result_kind": trailing["result_kind"], "missing": [],
        }
    missing.extend(m for m in trailing_missing if m not in missing)
    return {"value": None, "basis": None, "result_kind": result_kind, "missing": missing}
