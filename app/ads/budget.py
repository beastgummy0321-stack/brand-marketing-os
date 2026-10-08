"""Program-owned budget arithmetic and read-only current advice (ARCHITECTURE.md §0).

Scenario arithmetic accepts supplied history as comparison choices. Advice independently reads
the scoped current cohort and the existing coverage, result, target and money owners; only a
comparable affordable amount can be recommended. Economics is read through its public facade.
No HTTP, model call, table write or rule-card interpretation belongs here.
"""

import hashlib
import json
import math
from datetime import timedelta
from typing import SupportsFloat, overload

from app.brand_intelligence import repository as bi_repo
from app.core import input_rules


def advice(conn, org_id, brand_id, campaign: dict) -> dict:
    """Current comparable evidence and affordability, without recursive campaign reads.

    Brand/account history remains a comparison menu. Only one explicitly linked, recent
    campaign supplies a retain amount; the canonical result reducer rejects mixed units,
    actions and attribution. No growth multiplier is recommended here.
    """
    from app.ads import (
        coverage,
        lifecycle,
        month_budget,
        outcome,
        repository,
        targets,
        triage,
        triage_capacity,
        triage_scale,
    )
    from app.core import settings

    target = targets.resolve(conn, org_id, brand_id, campaign)
    unit = outcome.cap_unit(conn, brand_id, target, campaign=campaign)
    cutoff = coverage.last_complete_day(conn, org_id, brand_id)
    start = cutoff - timedelta(days=6)
    products = sorted(set((campaign.get("context_json") or {}).get("product_ids") or []))
    candidates = conn.execute(
        "SELECT * FROM ads_campaign WHERE org_id=%s AND brand_id=%s "
        "ORDER BY (id=%s) DESC, end_date DESC NULLS LAST, id",
        (org_id, brand_id, campaign["id"]),
    ).fetchall()
    cohort, rows, entities = None, [], []
    covered = False
    # Cross-campaign evidence needs one explicit sell-way; an unlinked current ID stands alone.
    if len(products) <= 1 and target["result_kind"] is not None:
        for raw in candidates:
            candidate = dict(raw)
            linked = sorted(set((candidate.get("context_json") or {}).get("product_ids") or []))
            if (linked != products
                    or targets.effective_result_kind(candidate) != target["result_kind"]
                    or repository.campaign_objective_family(conn, org_id, brand_id, candidate)
                    != repository.campaign_objective_family(conn, org_id, brand_id, campaign)):
                continue
            if not products and candidate["id"] != campaign["id"]:
                continue
            selected_start, selected_end = coverage.clip(candidate, start, cutoff)
            selected = conn.execute(
                "SELECT d.* FROM ads_external_daily d JOIN ads_external_entity e "
                "ON e.id=d.entity_id AND e.org_id=d.org_id AND e.brand_id=d.brand_id "
                "AND e.campaign_id=d.campaign_id WHERE d.org_id=%s AND d.brand_id=%s "
                "AND d.campaign_id=%s AND d.metric_scope='ad' AND d.day BETWEEN %s AND %s "
                "AND NOT EXISTS (SELECT 1 FROM ads_ad a WHERE a.org_id=d.org_id "
                "AND a.brand_id=d.brand_id AND a.campaign_id=d.campaign_id "
                "AND a.external_id=e.native_id AND a.product_id IS NOT NULL AND a.product_id<>%s) "
                "ORDER BY d.day,d.id",
                (org_id, brand_id, candidate["id"], selected_start, selected_end,
                 products[0] if products else None),
            ).fetchall()
            if selected:
                entities = [dict(entity) for entity in conn.execute(
                    "SELECT * FROM ads_external_entity WHERE org_id=%s AND brand_id=%s "
                    "AND campaign_id=%s AND native_kind='ad' ORDER BY id",
                    (org_id, brand_id, candidate["id"]),
                ).fetchall() if lifecycle.judged(dict(entity))]
                ids = {entity["id"] for entity in entities}
                cohort = candidate
                rows = [dict(row) for row in selected if row["entity_id"] in ids]
                read = coverage.load(
                    conn, org_id, brand_id, candidate, selected_start, selected_end,
                )
                covered = (read.cleanly_read(selected_start, selected_end)
                           and ids == {row["entity_id"] for row in rows})
                start, cutoff = selected_start, selected_end
                break
    view, spend = triage._ad_window(rows, start, cutoff)
    currency = view.get("currency") if view else None
    comparison = outcome.compare_cap_unit(unit, currency)
    grade, _, reason = triage.grade_window(view, spend, target["value"], 7)
    if comparison["reason"] or (view and view["result_kind"] != target["result_kind"]):
        grade, reason = "insufficient", comparison["reason"] or "result_kind_mismatch"
    if view and (view.get("result_action") is None or view.get("result_attribution") is None):
        grade, reason = "insufficient", "result_definition_unverified"
    days_read = max((cutoff - start).days + 1, 0)
    if not covered:
        grade, reason = "insufficient", "coverage_unverified"
    evidence = {
        "window": {"start": start.isoformat(), "end": cutoff.isoformat(),
                   "campaign_id": cohort["id"] if cohort else None},
        "cost_per_result": view.get("cost_per_result") if view else None,
        "target": {"value": target["value"], "basis": target["basis"],
                   "revision": target["revision"], "unit": unit},
        "grade": grade, "currency": currency,
        "attribution": {"kind": view.get("result_kind"), "action": view.get("result_action"),
                        "window": view.get("result_attribution")} if view else None,
        "sample_flag": triage._sample_view(spend, view, target["value"], days_read),
    }
    daily = None
    source = None
    owners = triage_scale.owner_lookup(conn, org_id, brand_id) if cohort else {}
    capacity = triage_capacity.capacity_view(
        [{"entity_id": entity["id"]} for entity in entities], target["value"], owners,
    )
    if capacity["currency"] == currency:
        daily = capacity["daily_budget"]
        source = "observed_daily_owner" if daily is not None else None
    if daily is not None and (not math.isfinite(daily) or daily <= 0):
        daily = None
    days = period_days(campaign)
    total = total_of(daily, days)
    selected_owners = {owners[e["id"]]["id"]: owners[e["id"]]
                       for e in entities if e["id"] in owners}
    cap = budget_cap_of(campaign.get("constraints_json"))
    cap_known = currency == "TWD" and cap is not None
    affordable = total is not None and cap_known and cap is not None and total <= cap
    funds = None
    first, last = campaign.get("start_date"), campaign.get("end_date")
    if (grade == "on_target" and currency == "TWD" and total is not None
            and cap is None and first and last
            and first.strftime("%Y-%m") == last.strftime("%Y-%m")):
        try:
            with conn.atomic():
                funds = month_budget.view(conn, org_id, brand_id, first.strftime("%Y-%m"))
        except Exception:
            funds = None
        ongoing = {row["entity_id"]: row for row in (funds or {}).get("ongoing_owners", [])}
        remaining_start = max(first, settings.today_for_org(conn, org_id=org_id))
        remaining_days = max((last - remaining_start).days + 1, 0)
        already_committed = bool(
            cohort and cohort["id"] == campaign["id"] and selected_owners and remaining_days > 0
            and all(oid in ongoing and ongoing[oid]["daily"] == float(owner["budget_amount"])
                    and ongoing[oid]["days"] >= remaining_days
                    and owner.get("start_date") is not None and owner["start_date"] <= first
                    and owner.get("end_date") is not None and owner["end_date"] >= last
                    for oid, owner in selected_owners.items())
        )
        required = 0 if already_committed else total
        affordable = (funds is not None and funds["currency"] == currency
                      and funds["amount"] is not None and funds["confirmed_at"] is not None
                      and not funds["uncertainties"] and funds["available"] is not None
                      and funds["available"] >= required)
    state, key, reasons = "insufficient_evidence", None, [reason or "budget_unverified"]
    if grade in {"watch", "over", "wasted"}:
        state, reasons = "repair_before_budget", ["cost_" + grade]
    elif grade == "on_target" and capacity["currency"] != "TWD":
        reasons = ["planning_currency_unverified" if capacity["currency"] is None
                   else "planning_currency_mismatch"]
    elif grade == "on_target" and affordable:
        state, key, reasons = "retain", "retain", ["on_target_affordable"]
    elif grade == "on_target" and total is not None and (
            cap_known or (funds is not None and funds["currency"] == currency
                          and funds["amount"] is not None and funds["confirmed_at"] is not None
                          and not funds["uncertainties"] and funds["available"] is not None)):
        state, reasons = "unaffordable", ["period_budget_exceeded"]
    result = {"state": state, "recommended_key": key, "reason_codes": reasons, "evidence": evidence}
    stable = {**result, "products": products, "dates": [first, last],
              "chosen": float(campaign["budget_planned"])
              if campaign.get("budget_planned") is not None else None, "budget_cap": cap,
              "prior": {"daily": daily, "source": source, "currency": currency,
                        "owners": [{key: selected_owners[oid].get(key) for key in (
                            "id", "native_kind", "budget_type", "budget_amount", "currency",
                            "start_date", "end_date",
                        )} for oid in sorted(selected_owners)]},
              "coverage": {"verified": covered,
                           "ranges": coverage.served(cohort) if cohort else []},
              "entities": sorted(entity["id"] for entity in entities),
              "sources": sorted({(r["entity_id"], r["source"], r["attribution_key"])
                                 for r in rows}),
              "funds": {key: funds.get(key) for key in (
                  "amount", "currency", "available", "uncertainties", "revision", "confirmed_at",
              )} if funds else None}
    if funds:
        stable["commitments"] = [{key: row.get(key) for key in (
            "entity_id", "daily", "days", "commitment",
        )} for row in sorted(funds.get("ongoing_owners", []), key=lambda row: row["entity_id"])
                                 if row["entity_id"] in selected_owners]
    result["revision"] = hashlib.sha256(json.dumps(
        stable, sort_keys=True, default=str, ensure_ascii=False,
    ).encode()).hexdigest()
    return {**result, "retain": {"daily": daily, "total": total, "currency": currency,
                                 "source": source}
            if daily is not None and currency == "TWD" else None}


def apply_advice(result: dict, current: dict) -> dict:
    """Project the exact advice and its optional scoped choice; never restore a null pick."""
    rows = [row for row in result["scenarios"] if row["key"] != "retain"]
    if result["mode"] == "cold_start":
        currency = current["evidence"]["target"]["unit"]["currency"]
        rows = [{**row, "currency": currency,
                 **({"daily": None, "total": None, "over_cap": None,
                     "reason": "planning_currency_unverified" if currency is None
                     else "planning_currency_mismatch"} if currency != "TWD" else {})}
                if row["key"] != CAP_KEY else {**row, "currency": "TWD"} for row in rows]
    retained = current.get("retain")
    if retained and retained["currency"] == "TWD":
        rows.append({"key": "retain", "label": "維持已知日預算", **retained,
                     "caption": "同賣法已知日預算；不是成長估算",
                     "over_cap": amount_over_cap(retained["total"], result.get("budget_cap"))
                     if retained["currency"] == "TWD" else None})
    exact = {key: value for key, value in current.items() if key != "retain"}
    return {**result, "scenarios": rows, "recommended": current["recommended_key"], "advice": exact}

# key, 中文 label, 每天想要的購買數 — ruling 4: 2 / 5 / 10; labels per F28 (keys unchanged).
_COLD_START_EVENTS = (
    ("minimum", "小額測試", 2), ("recommended", "一般測試", 5), ("aggressive", "較高額測試", 10),
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
    row. A recorded close rate scales the margin (percent 0–100); no close rate means one
    purchase. Missing price, cost or shipping yields None. An explicit zero is known;
    an unknown cost never becomes a guessed margin or free shipping.
    """
    if not economics:
        return None
    price = economics.get("selling_price")
    unit_cost = economics.get("unit_variable_cost")
    if price is None or unit_cost is None:
        return None
    shipping = economics.get("shipping_cost")
    if shipping is None:
        return None
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
    """One selected sell-way's effective economics; no mix is evidenced for multiple choices.

    A composed sell-way is still one choice: its owner resolves component costs. Multiple
    sell-ways have no observed sales weights, so neither their first row nor their mean is a
    defensible unit margin. Missing fields remain available for the caller's explanation.
    """
    ids = list(dict.fromkeys(product_ids or []))
    if len(ids) != 1:
        return None, None
    economics = bi_repo.get_product_economics(conn, brand_id, ids[0])
    return (economics, ids[0]) if economics else (None, None)


def economics_for(
    conn, brand_id: str, product_ids: list[str] | None,
) -> tuple[dict | None, str | None]:
    """The shared, single sell-way economics lookup used by targets and scenarios."""
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
        "mode": "cold_start", "scenarios": scenario_rows, "recommended": None,
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
            "caption": f"{base_text}（幣別未核實）{whole(last_daily)} ×{mult:g}",
            "currency": None,
        })
    basis = {
        "mode": "history", "cpa": cpa, "source": history.get("source"),
        "sample_days": history.get("sample_days"), "sample_ads": history.get("sample_ads"),
    }
    return {
        "mode": "history", "scenarios": scenario_rows, "recommended": None,
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
    if recommended not in {r["key"] for r in rows}:
        recommended = None
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
    """A recommended row must have an amount. Missing or suppressed picks stay null."""
    rows = result.get("scenarios", [])
    picked = next((r for r in rows if r["key"] == result.get("recommended")), None)
    if picked is not None and picked.get("total") is not None:
        return picked["key"]
    return None


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
                       *, cap: float | None = None, current_advice: dict | None = None) -> dict:
    """Return current choices and advice, preserving explicitly chosen/adopted amounts.

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
    if current_advice is not None:
        scenarios_now = apply_advice(scenarios_now, current_advice)
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
