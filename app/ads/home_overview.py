"""app/ads/home_overview.py — F28-I06 "Home overview": the month-level numbers the ads-centre home
(board D, prototype v9 `#/`) shows. Read-only: no LLM call, no write, no platform call
(ARCHITECTURE.md §0 "程式整理，LLM 判斷").

One spend grain for the whole payload: `ads_external_daily` rows with `metric_scope='ad'` (the
grain `month_summary.py` and `triage.py` already read; every campaign that has platform objects,
system-built or imported, writes it). The window is the requested calendar month in the org
timezone (`month_summary._month_window`), cut off BEFORE today -- today is never a complete day.

Invariants (issue Done #2):
- `spent` is the only brand-month spend figure; `quality.buckets` partition exactly the same rows
  by ad, so their amounts sum to `spent` to the cent. An ad's bucket is its triage grade
  (`triage.classify`, never recomputed here); spend on anything else -- a closed ad, an ad of a
  closed campaign -- lands in `ungraded`.
- Unknown is null, never zero: any row with an unknown spend, or more than one currency among the
  rows, nulls `spent` (same rule as `month_summary._ad_spend_and_currency`); a campaign's own
  numbers are null when its own rows are unknown or the brand's rows mix currencies.
- `money` covers purchase campaigns only (the cap view's `result_kind`); every other campaign
  with spend this month is listed in `excluded`. `earn_after_cost_and_ads` (F51 Contract F: the
  key is its basis) = Σ (purchases × break-even − spend) -- break-even already deducts the product
  cost -- and is null with `earn_missing` naming why when any input is unknown.
- `pace.budget_to_date` (F51 Contract F) = `budget.whole(month budget × day_of_month ÷
  days_in_month)`, null without a month budget -- the browser no longer rebuilds it.
- Each block is read on its own: a read that fails inside one block nulls that block only.
"""

import calendar
import logging
from collections import defaultdict
from datetime import datetime, time, timedelta
from decimal import Decimal

from app import background, orders
from app.ads import (
    budget,
    campaign_stage,
    change_control_launch,
    coverage,
    handoff_assignment,
    lifecycle,
    month_budget,
    month_summary,
    outcome,
    repository,
    review_evidence,
    runtime,
    targets,
    triage,
    triage_capacity,
    triage_scale,
)
from app.ads.external_repository import is_monthly_budget_row
from app.core import settings as coresettings

logger = logging.getLogger(__name__)

# Left-to-right order of the v9 money-quality band; `ungraded` last.
BUCKET_ORDER = ("on_target", "watch", "over", "wasted", "insufficient", "no_target", "ungraded")
BUCKET_ADS_CAP = 12
TIMELINE_DAYS = 31
TIMELINE_CAP = 6
_TIMELINE_KIND_ORDER = {"today": 0, "month_review": 1, "campaign_start": 2, "campaign_end": 3}
_CENT = Decimal("0.01")


def _money_out(value: Decimal | None) -> float | None:
    return None if value is None else float(value.quantize(_CENT))


def _count_out(value) -> float | int | None:
    if value is None:
        return None
    number = float(value)
    return int(number) if number.is_integer() else number


def _guarded(conn, block: str, fn):
    """One block's own reads. A failure is logged and nulls only this block; the read-only
    transaction is rolled back so the next block can still query (`Conn.rollback` re-applies the
    tenant scope)."""
    try:
        return fn()
    except Exception:
        logger.exception("home overview block %s failed", block)
        conn.rollback()
        return None


# ---------------------------------------------------------------------------
# Window and the one spend read
# ---------------------------------------------------------------------------


def _window(conn, org_id: str, brand_id: str, month: str) -> dict:
    """The month's days; `cutoff` = the brand's last complete platform day (F50 Contract K,
    `coverage.last_complete_day`), never past the month's end."""
    start, end, days_in_month, day_of_month = month_summary._month_window(conn, org_id, month)
    today = coresettings.today_for_org(conn, org_id=org_id)
    cutoff = min(end, coverage.last_complete_day(conn, org_id, brand_id))
    data_days = max((cutoff - start).days + 1, 0)
    return {
        "start": start, "end": end, "days_in_month": days_in_month,
        "day_of_month": day_of_month, "today": today, "cutoff": cutoff, "data_days": data_days,
    }


def _ad_rows(conn, org_id, brand_id, start, end) -> list[dict]:
    if end < start:
        return []
    rows = conn.execute(
        "SELECT * FROM ads_external_daily WHERE org_id=%s AND brand_id=%s "
        "AND metric_scope='ad' AND day BETWEEN %s AND %s ORDER BY day",
        (org_id, brand_id, start, end),
    ).fetchall()
    return [dict(r) for r in rows if not is_monthly_budget_row(r["attribution_key"])]


def _spend_view(rows, start, end) -> dict:
    """`known`/`currency` by `month_summary._ad_spend_and_currency` (one rule, not a second one);
    the amount itself is an exact Decimal sum of the same rows, so any partition of them (by ad,
    by campaign, by day) adds back to it exactly."""
    currencies = {r["currency"] for r in rows if r["currency"] is not None}
    single = next(iter(currencies)) if len(currencies) == 1 else None
    if not rows:
        return {"known": False, "amount": None, "currency": single}
    amount, _currency = month_summary._ad_spend_and_currency(
        review_evidence.aggregate(rows, start, end)
    )
    if amount is None:
        return {"known": False, "amount": None, "currency": single}
    return {
        "known": True, "amount": sum((Decimal(str(r["spend"])) for r in rows), Decimal(0)),
        "currency": single,
    }


def _purchases(rows, start, end):
    """A purchase campaign's own result count over `rows` -- `month_summary._ad_result`'s one
    ad-scope result view; unknown unless every row agrees it counts purchases."""
    if not rows:
        return Decimal(0)
    count, _cost, kind = month_summary._ad_result(review_evidence.aggregate(rows, start, end))
    if count is None or kind != "purchase":
        return None
    return Decimal(str(count))


# ---------------------------------------------------------------------------
# Campaign facts shared by the blocks
# ---------------------------------------------------------------------------


def _campaigns(conn, org_id, brand_id) -> dict:
    rows = conn.execute(
        "SELECT * FROM ads_campaign WHERE org_id=%s AND brand_id=%s ORDER BY created_at, id",
        (org_id, brand_id),
    ).fetchall()
    return {row["id"]: dict(row) for row in rows}


class _Caps:
    """`targets.resolve` once per campaign, on demand."""

    def __init__(self, conn, org_id, brand_id, campaigns):
        self._conn, self._org, self._brand, self._campaigns = conn, org_id, brand_id, campaigns
        self._cache: dict = {}

    def __call__(self, campaign_id):
        if campaign_id not in self._cache:
            campaign = self._campaigns[campaign_id]
            cap = targets.resolve(
                self._conn, self._org, self._brand, campaign,
            )
            cap["cap_unit"] = outcome.cap_unit(self._conn, self._brand, cap, campaign=campaign)
            cap["break_even_unit"] = outcome.break_even_unit(
                self._conn, self._brand, cap, campaign=campaign,
            )
            self._cache[campaign_id] = cap
        return self._cache[campaign_id]


def _configured_cap_out(cap: dict) -> dict | None:
    """Preserve a resolved value independently of whether its unit can be compared."""
    if cap["value"] is None:
        return None
    return {"value": cap["value"], "basis": cap["basis"]}


def _cap_out(cap: dict, currency: str | None) -> dict | None:
    """Only comparable inputs reach the screen's cost ruler and profit tag."""
    configured = _configured_cap_out(cap)
    if configured is None or outcome.compare_cap_unit(cap["cap_unit"], currency)["reason"]:
        return None
    break_even = cap["break_even"]
    if outcome.compare_cap_unit(cap["break_even_unit"], currency)["reason"]:
        break_even = None
    return {**configured, "break_even": break_even}


def _entities(conn, org_id, brand_id) -> list[dict]:
    rows = conn.execute(
        "SELECT * FROM ads_external_entity WHERE org_id=%s AND brand_id=%s ORDER BY name, id",
        (org_id, brand_id),
    ).fetchall()
    return [dict(r) for r in rows]


def _lifecycles(campaigns, roots, today) -> dict:
    """campaign id -> its served `lifecycle {state, label, can_close}` (`lifecycle.view`)."""
    return {
        campaign_id: lifecycle.view(campaign, root=roots.get(campaign_id), today=today)
        for campaign_id, campaign in campaigns.items()
    }


def _campaign_money(rows, start, end, brand_currency_ok) -> dict:
    view = _spend_view(rows, start, end)
    spend = view["amount"] if view["known"] and brand_currency_ok else None
    currencies = {row["currency"] for row in rows}
    currency = next(iter(currencies)) if len(currencies) == 1 else None
    return {"spend": spend, "purchases": _purchases(rows, start, end), "currency": currency}


# ---------------------------------------------------------------------------
# money
# ---------------------------------------------------------------------------


def _money_totals(rows_by_campaign, campaigns, caps, start, end, brand_currency_ok) -> dict:
    included, excluded = [], []
    for campaign_id, rows in rows_by_campaign.items():
        campaign = campaigns.get(campaign_id)
        if campaign is None:
            continue
        cap = caps(campaign_id)
        if cap["result_kind"] != "purchase":
            excluded.append({
                "campaign_id": campaign_id, "name": campaign["name"],
                "reason": "result_kind_unknown" if cap["result_kind"] is None else "not_purchase",
            })
            continue
        included.append((cap, _campaign_money(rows, start, end, brand_currency_ok)))

    purchases = spend = None
    if included:
        counts = [m["purchases"] for _, m in included]
        spends = [m["spend"] for _, m in included]
        purchases = None if any(c is None for c in counts) else sum(counts, Decimal(0))
        spend = None if any(s is None for s in spends) else sum(spends, Decimal(0))
    cost_per_purchase = spend / purchases if spend is not None and purchases else None

    earn_missing: list[str] = []
    if not included:
        earn_missing.append("no_purchase_campaign")
    if included and spend is None:
        earn_missing.append("spend")
    if included and purchases is None:
        earn_missing.append("purchases")
    for cap, money in included:
        if cap["break_even"] is None:
            reasons = cap["economics_basis"]["missing"]
            earn_missing.extend(reasons or ["product_cost"])
        elif outcome.compare_cap_unit(cap["break_even_unit"], money["currency"])["reason"]:
            earn_missing.append("currency")
    earn_missing = list(dict.fromkeys(earn_missing))
    earn_after_cost_and_ads = None
    if not earn_missing:
        earn_after_cost_and_ads = sum(
            (m["purchases"] * Decimal(str(cap["break_even"])) - m["spend"] for cap, m in included),
            Decimal(0),
        )

    caps_seen = {(cap["value"], cap["basis"], cap["cap_unit"]["currency"],
                  cap["cap_unit"]["source"], cap["cap_unit"]["unit_basis"])
                 for cap, _m in included}
    one_cap = configured_cap = cap_comparison = None
    if len(caps_seen) == 1 and included[0][0]["value"] is not None:
        cap = included[0][0]
        configured_cap = _configured_cap_out(cap)
        assert configured_cap is not None  # This branch requires a resolved value.
        currencies = {m["currency"] for _cap, m in included}
        currency = next(iter(currencies)) if brand_currency_ok and len(currencies) == 1 else None
        cap_comparison = outcome.compare_cap_unit(cap["cap_unit"], currency)
        if cap_comparison["reason"] is None:
            break_evens = set()
            for c, _m in included:
                comparable = _cap_out(c, currency)
                assert comparable is not None  # The shared value and unit were verified above.
                break_evens.add(comparable["break_even"])
            one_cap = {**configured_cap,
                       "break_even": next(iter(break_evens)) if len(break_evens) == 1 else None}
    return {
        "purchases": purchases, "cost_per_purchase": cost_per_purchase, "cap": one_cap,
        "configured_cap": configured_cap, "cap_comparison": cap_comparison,
        "earn_after_cost_and_ads": earn_after_cost_and_ads, "earn_missing": earn_missing,
        "excluded": excluded,
    }


def _currency_comparison(source, observed) -> dict:
    reason = ("currency_unknown" if not source or not observed
              else "currency_mismatch" if source != observed else None)
    return {"reason": reason}


def _previous_same_period(conn, org_id, brand_id, win, campaigns, caps,
                          current_currency=None) -> dict | None:
    """The same number of complete days at the start of the previous month, capped at that
    month's own length (`month_summary._orders_comparison`'s like-for-like rule). Null when this
    month has no complete day yet."""
    if win["data_days"] <= 0:
        return None
    previous_start = (win["start"] - timedelta(days=1)).replace(day=1)
    previous_len = calendar.monthrange(previous_start.year, previous_start.month)[1]
    days = min(win["data_days"], previous_len)
    previous_end = previous_start + timedelta(days=days - 1)
    rows = _ad_rows(conn, org_id, brand_id, previous_start, previous_end)
    currency_ok = len({r["currency"] for r in rows if r["currency"] is not None}) <= 1
    by_campaign = defaultdict(list)
    for row in rows:
        by_campaign[row["campaign_id"]].append(row)
    totals = _money_totals(by_campaign, campaigns, caps, previous_start, previous_end, currency_ok)
    previous_spend = _spend_view(rows, previous_start, previous_end)
    currency = previous_spend["currency"] if previous_spend["known"] else None
    return {
        "days": days, "purchases": _count_out(totals["purchases"]),
        "cost_per_purchase": _money_out(totals["cost_per_purchase"]),
        "currency": currency, "cost_comparison": _currency_comparison(currency, current_currency),
    }


def _money_block(conn, org_id, brand_id, win, rows_by_campaign, campaigns, caps,
                 currency_ok) -> dict:
    totals = _money_totals(
        rows_by_campaign, campaigns, caps, win["start"], win["cutoff"], currency_ok,
    )
    current_rows = [row for rows in rows_by_campaign.values() for row in rows]
    current_spend = _spend_view(current_rows, win["start"], win["cutoff"])
    current_currency = current_spend["currency"] if current_spend["known"] else None
    previous = _guarded(
        conn, "money.previous_same_period",
        lambda: _previous_same_period(
            conn, org_id, brand_id, win, campaigns, caps, current_currency,
        ),
    )
    return {
        "purchases": _count_out(totals["purchases"]),
        "cost_per_purchase": _money_out(totals["cost_per_purchase"]),
        "cap": totals["cap"],
        "configured_cap": totals["configured_cap"], "cap_comparison": totals["cap_comparison"],
        "earn_after_cost_and_ads": _money_out(totals["earn_after_cost_and_ads"]),
        "earn_missing": totals["earn_missing"], "excluded": totals["excluded"],
        "estimate_basis": {
            "kind": "platform_purchase_margin",
            "assumptions": [
                "平台購買數假設為每筆一份選定賣法，並使用目前售價、單位成本與運費。",
                "估算只扣商品變動成本、運費與廣告支出，未計固定成本、退款與其他費用。",
                "平台歸因購買數不是已付款訂單或廣告增量銷售；此數值是假設貢獻估算，不是已驗證獲利。",
            ],
            "missing": totals["earn_missing"],
        },
        "previous_same_period": previous,
    }


# ---------------------------------------------------------------------------
# pace
# ---------------------------------------------------------------------------


def _pace_block(conn, org_id, brand_id, month, win, rows, spent) -> dict:
    month_plan = month_budget.view(conn, org_id, brand_id, month)
    observed = _spend_view(rows, win["start"], win["cutoff"])
    observed_currency = observed["currency"] if observed["known"] else None
    budget_currency = month_plan["currency"]
    by_day = defaultdict(lambda: Decimal(0))
    for row in rows:
        if spent is not None:
            by_day[row["day"]] += Decimal(str(row["spend"]))
    daily, cumulative = [], Decimal(0)
    day = win["start"]
    while day <= win["cutoff"]:
        cumulative += by_day.get(day, Decimal(0))
        daily.append({
            "day": day.isoformat(),
            "cumulative": _money_out(cumulative) if spent is not None else None,
        })
        day += timedelta(days=1)
    projected = None
    if spent is not None and win["data_days"] > 0:
        projected = spent / win["data_days"] * win["days_in_month"]
    amount = month_plan["amount"]
    return {
        "budget_amount": amount, "available": month_plan["available"],
        "budget_currency": budget_currency,
        "budget_comparison": _currency_comparison(budget_currency, observed_currency),
        "budget_to_date": None if amount is None else budget.whole(
            amount * win["day_of_month"] / win["days_in_month"]
        ),
        "daily": daily, "projected_month_end": _money_out(projected),
    }


# ---------------------------------------------------------------------------
# quality
# ---------------------------------------------------------------------------


def _graded_items(conn, org_id, brand_id, campaigns, entities, states) -> dict:
    """Every judged ad's own triage item (`triage.classify`, the I02 grades), for every
    non-closed campaign that has an ad on a platform -- keyed by entity id."""
    with_ads = {e["campaign_id"] for e in entities if e["native_kind"] == "ad"}
    graded = {}
    for campaign_id in campaigns:
        if states[campaign_id]["state"] == "closed" or campaign_id not in with_ads:
            continue
        for item in triage.classify(conn, org_id, brand_id, campaign_id)["items"]:
            graded[item["entity_id"]] = item
    return graded


def _quality_block(conn, org_id, brand_id, rows, spent, campaigns, entities,
                   states) -> dict | None:
    if spent is None:
        return None
    graded = _graded_items(conn, org_id, brand_id, campaigns, entities, states)
    entity_by_id = {e["id"]: e for e in entities}
    spend_by_ad = defaultdict(lambda: Decimal(0))
    for row in rows:
        spend_by_ad[row["entity_id"]] += Decimal(str(row["spend"]))
    ads_by_bucket = defaultdict(list)
    for entity_id, amount in spend_by_ad.items():
        item = graded.get(entity_id)
        entity = entity_by_id.get(entity_id) or {}
        bucket = item["grade"] if item is not None else "ungraded"
        ads_by_bucket[bucket].append({
            "entity_id": entity_id,
            "name": item["name"] if item is not None else entity.get("name"),
            "thumbnail_url": (
                item["thumbnail_url"] if item is not None else triage._thumbnail_url(entity)
            ),
            # F48 Contract R: the triage item's shown sample flags, passed through (never a gate).
            "sample": item.get("sample") if item is not None else None,
            "spend": amount,
        })
    buckets = []
    for grade in BUCKET_ORDER:
        ads = sorted(ads_by_bucket.get(grade, []), key=lambda a: (-a["spend"], a["entity_id"]))
        amount = sum((a["spend"] for a in ads), Decimal(0))
        buckets.append({
            "grade": grade, "amount": _money_out(amount), "count": len(ads),
            "ads": [{**a, "spend": _money_out(a["spend"])} for a in ads[:BUCKET_ADS_CAP]],
        })
    return {"buckets": buckets}


# ---------------------------------------------------------------------------
# campaigns and timeline
# ---------------------------------------------------------------------------


def _draft_view(conn, org_id, brand_id, campaign, cap) -> dict:
    """`ads_ready` counts ads whose material the launch batch takes
    (`change_control_launch.ready_material` over `handoff_assignment.material_snapshot`), never
    a second definition of "ready"."""
    ads = repository.list_ads_for_campaign(conn, org_id, brand_id, campaign["id"])
    ready = 0
    for ad in ads:
        try:
            material = handoff_assignment.material_snapshot(
                conn, org_id, brand_id, campaign["id"], ad
            )
        except ValueError:
            material = None
        if change_control_launch.ready_material(material):
            ready += 1
    approved = conn.execute(
        "SELECT 1 FROM ads_change_set WHERE org_id=%s AND brand_id=%s AND campaign_id=%s "
        "AND status='approved' AND plan_json ? 'launch_snapshot' LIMIT 1",
        (org_id, brand_id, campaign["id"]),
    ).fetchone() is not None
    return {
        "start_date": campaign["start_date"].isoformat() if campaign["start_date"] else None,
        "cap_missing": cap["value"] is None, "ads_total": len(ads), "ads_ready": ready,
        "approved": approved,
    }


def _daily_budget(conn, org_id, brand_id, campaign, active_ads, draft,
                  owner_by_entity=None) -> float | None:
    """Draft: the plan's group total. Launched (ads.md §6.34, 2026-09-26): the ONE rule the
    workspace uses too -- `triage_capacity.capacity_view` over the daily budget owners of the
    campaign's judged ads (`lifecycle.judged`, the ads triage grades); an owner whose ads are all
    paused never counts."""
    if draft:
        total = repository.group_budget_total(conn, org_id, brand_id, campaign["id"])
        return total or None
    items = [{"entity_id": ad["id"]} for ad in active_ads]
    return triage_capacity.capacity_view(items, None, owner_by_entity or {})["daily_budget"]


def _missing_days(conn, org_id, brand_id, campaign, win) -> list:
    """This month's unread days up to the cutoff, clipped to the campaign (F49 Contract V)."""
    if win["data_days"] <= 0:
        return []
    return coverage.missing_days(conn, org_id, brand_id, campaign, win["start"], win["cutoff"])


_HANDOFF_CHECK_STATES = frozenset({"reported", "unknown", "deviated"})


def _handoff_sets(conn, org_id, brand_id) -> dict:
    """campaign id -> its newest approved change set and its newest approved launch set (the
    same "latest" order `change_control_launch.launch_set` uses), each with the
    `ads_action.verification_state` of its items -- ONE query for the whole brand, never one per
    campaign row. Newest first; a set that is both appears once."""
    rows = conn.execute(
        "WITH ranked AS (SELECT id,campaign_id,(plan_json ? 'launch_snapshot') AS is_launch,"
        "row_number() OVER (PARTITION BY campaign_id ORDER BY approved_at DESC,id DESC) AS newest,"
        "row_number() OVER (PARTITION BY campaign_id,(plan_json ? 'launch_snapshot') "
        "ORDER BY approved_at DESC,id DESC) AS newest_of_kind "
        "FROM ads_change_set WHERE org_id=%s AND brand_id=%s AND status='approved') "
        "SELECT r.id,r.campaign_id,r.is_launch,r.newest,"
        "array_remove(array_agg(a.verification_state),NULL) AS states "
        "FROM ranked r LEFT JOIN ads_action a ON a.org_id=%s AND a.brand_id=%s "
        "AND a.campaign_id=r.campaign_id AND a.change_set_id=r.id "
        "WHERE r.newest=1 OR (r.is_launch AND r.newest_of_kind=1) "
        "GROUP BY r.id,r.campaign_id,r.is_launch,r.newest ORDER BY r.campaign_id,r.newest",
        (org_id, brand_id, org_id, brand_id),
    ).fetchall()
    by_campaign = defaultdict(list)
    for row in rows:
        by_campaign[row["campaign_id"]].append(
            {"id": row["id"], "is_launch": row["is_launch"], "states": set(row["states"] or [])}
        )
    return by_campaign


def _handoff(conn, org_id, brand_id, campaign_id, sets) -> dict | None:
    """F29 Contract D home-row `handoff`: `platform` when the newest approved set or the approved
    launch still has an item `pending` (the user has not done it on the platform yet), else
    `check` when one is `reported`/`unknown`/`deviated` (done, the readback has not confirmed
    it), else `None` (all confirmed, stale or legacy). A launch whose plan changed after approval
    (`change_control_launch.is_stale`) is left out -- the F28 stale-launch exit owns it. That
    check builds the plan snapshot, so it runs only for a launch that would otherwise decide the
    state."""
    from app.ads import change_control_launch

    stale: dict = {}

    def usable(entry) -> bool:
        if not entry["is_launch"]:
            return True
        if "stale" not in stale:
            stale["stale"] = change_control_launch.is_stale(conn, org_id, brand_id, campaign_id)
        return not stale["stale"]

    for state, wanted in (("platform", {"pending"}), ("check", _HANDOFF_CHECK_STATES)):
        for entry in sets:
            if entry["states"] & wanted and usable(entry):
                return {"state": state, "change_set_id": entry["id"]}
    return None


def _campaigns_block(conn, org_id, brand_id, win, campaigns, caps, entities, rows_by_campaign,
                     currency_ok, states) -> list:
    handoff_sets = _handoff_sets(conn, org_id, brand_id)
    ads_by_campaign = defaultdict(list)
    for entity in entities:
        if entity["native_kind"] == "ad":
            ads_by_campaign[entity["campaign_id"]].append(entity)
    reported = lifecycle.newest_reported(conn, org_id, brand_id)
    owner_by_entity = triage_scale.owner_lookup(conn, org_id, brand_id)
    accounts_cache: dict = {}
    live, drafts = [], []
    for campaign_id, campaign in campaigns.items():
        state = states[campaign_id]
        if state["state"] == "closed":
            continue
        cap = caps(campaign_id)
        draft = state["state"] == "draft"
        ads = ads_by_campaign[campaign_id]
        judged_ads = [ad for ad in ads if lifecycle.judged(ad)]
        running = lifecycle.running_view(
            campaign, ads, reported.get(campaign_id), today=win["today"],
        )
        rows = rows_by_campaign.get(campaign_id, [])
        month = (
            _campaign_money(rows, win["start"], win["cutoff"], currency_ok) if rows
            else {"spend": None, "purchases": None, "currency": None}
        )
        purchases = month["purchases"] if cap["result_kind"] == "purchase" and rows else None
        spend = month["spend"]
        sync = repository.campaign_sync_state(
            conn, org_id, brand_id, campaign, accounts_cache=accounts_cache,
        )
        missing_days = [] if draft else _missing_days(conn, org_id, brand_id, campaign, win)
        entry = {
            "campaign_id": campaign_id, "name": campaign["name"], "origin": campaign["origin"],
            "status": campaign["status"], "lifecycle": state, "running": running,
            "next_action": campaign_stage.action_of(
                conn, org_id, brand_id, campaign, state, running,
                stage_key="assets" if cap["value"] is not None else None,
            ),
            "month_spend": _money_out(spend),
            "currency": month["currency"],
            "purchases": _count_out(purchases),
            "cost_per_purchase": _money_out(spend / purchases)
            if spend is not None and purchases else None,
            "cap": _cap_out(cap, month["currency"]),
            "configured_cap": _configured_cap_out(cap),
            "cap_comparison": outcome.compare_cap_unit(cap["cap_unit"], month["currency"]),
            "active_ads": running["count"],
            "daily_budget": _daily_budget(
                conn, org_id, brand_id, campaign, judged_ads, draft, owner_by_entity,
            ),
            "missing_days": missing_days,
            "sync_state": sync["state"],
            # F29 Contract D: the same function triage `data.status` uses, over this month's
            # window (the rows this payload already read).
            "data_status": repository.campaign_data_status(
                conn, org_id, brand_id, campaign, sync=sync, missing_days=missing_days,
                has_rows=bool(rows),
            ),
            "handoff": _handoff(conn, org_id, brand_id, campaign_id,
                                handoff_sets.get(campaign_id, [])),
            "draft": _draft_view(conn, org_id, brand_id, campaign, cap) if draft else None,
        }
        (drafts if draft else live).append(entry)
    live.sort(key=lambda c: (c["month_spend"] is None, -(c["month_spend"] or 0), c["name"]))
    drafts.sort(key=lambda c: (c["draft"]["start_date"] is None, c["draft"]["start_date"] or "",
                               c["name"]))
    return live + drafts


def _timeline_block(win, campaigns_out, campaigns) -> list:
    """Today, this month's review (its last day), then campaign starts and ends in the next 31
    days -- at most six items, soonest first. `ready` only on a start: a draft is ready once its
    cap resolves and every planned ad has confirmed material; a campaign already on a platform is
    ready."""
    today = win["today"]
    horizon = today + timedelta(days=TIMELINE_DAYS)
    month_end = today.replace(day=calendar.monthrange(today.year, today.month)[1])
    items = [
        {"date": today, "kind": "today", "campaign_id": None, "name": None, "ready": None},
        {"date": month_end, "kind": "month_review", "campaign_id": None, "name": None,
         "ready": None},
    ]
    for entry in campaigns_out:
        campaign = campaigns[entry["campaign_id"]]
        draft = entry["draft"]
        start, end = campaign.get("start_date"), campaign.get("end_date")
        if start is not None and today <= start <= horizon:
            ready = True if draft is None else (
                not draft["cap_missing"] and draft["ads_total"] > 0
                and draft["ads_ready"] == draft["ads_total"]
            )
            items.append({"date": start, "kind": "campaign_start",
                          "campaign_id": entry["campaign_id"], "name": entry["name"],
                          "ready": ready})
        if end is not None and today <= end <= horizon:
            items.append({"date": end, "kind": "campaign_end",
                          "campaign_id": entry["campaign_id"], "name": entry["name"],
                          "ready": None})
    items.sort(key=lambda i: (i["date"], _TIMELINE_KIND_ORDER[i["kind"]], i["name"] or ""))
    return [{**i, "date": i["date"].isoformat()} for i in items[:TIMELINE_CAP]]


def _sync_block(conn, org_id, brand_id) -> dict:
    """Newest successful account read, and the earliest time the runtime's due rule
    (`runtime.SYNC_SECONDS` after a job's last update) lets any idle account be read again."""
    rows = conn.execute(
        "SELECT status,last_success_at,updated_at FROM ads_external_sync_job "
        "WHERE org_id=%s AND brand_id=%s",
        (org_id, brand_id),
    ).fetchall()
    successes = [r["last_success_at"] for r in rows if r["last_success_at"] is not None]
    upcoming = [
        r["updated_at"] + timedelta(seconds=runtime.SYNC_SECONDS)
        for r in rows if r["status"] not in ("pending", "running") and r["updated_at"]
    ]
    health = background.worker_health()
    eligible = min(upcoming) if upcoming else None
    return {
        "last_success_at": max(successes) if successes else None,
        "eligible_at": eligible,
        "next_at": eligible if health["state"] == "alive" else None,
        "worker_health": health,
    }


# ---------------------------------------------------------------------------
# entry
# ---------------------------------------------------------------------------


def _closed_this_month(conn, org_id, brand_id, win) -> int:
    """How many campaigns were closed in this calendar month (org timezone), so the empty state
    never reads 「還沒有活動」 over them (drill-11 N3)."""
    zone = coresettings.org_timezone(conn, org_id=org_id)
    start = datetime.combine(win["start"], time.min, tzinfo=zone)
    end = datetime.combine(win["end"] + timedelta(days=1), time.min, tzinfo=zone)
    return len([
        c for c in lifecycle.campaigns(conn, org_id, brand_id, {"closed"})
        if c["closed_at"] is not None and start <= c["closed_at"] < end
    ])


def get_overview(conn, org_id: str, brand_id: str, month: str) -> dict:
    month = month_summary._require_month(month)
    win = _window(conn, org_id, brand_id, month)
    campaigns = _campaigns(conn, org_id, brand_id)
    caps = _Caps(conn, org_id, brand_id, campaigns)
    states = _lifecycles(campaigns, lifecycle.roots(conn, org_id, brand_id), win["today"])

    rows = _guarded(
        conn, "spend", lambda: _ad_rows(conn, org_id, brand_id, win["start"], win["cutoff"])
    )
    spend = _spend_view(rows or [], win["start"], win["cutoff"])
    spent = spend["amount"] if rows is not None and spend["known"] else None
    currency_ok = rows is not None and spend["currency"] is not None
    rows_by_campaign = defaultdict(list)
    for row in rows or []:
        rows_by_campaign[row["campaign_id"]].append(row)
    entities = _guarded(conn, "entities", lambda: _entities(conn, org_id, brand_id))

    commerce = None if win["data_days"] <= 0 else _guarded(
        conn, "commerce", lambda: orders.review_evidence(
            conn, org_id, brand_id, start=win["start"], end=win["cutoff"],
        ),
    )

    money = None if rows is None else _guarded(
        conn, "money",
        lambda: _money_block(conn, org_id, brand_id, win, rows_by_campaign, campaigns, caps,
                             currency_ok),
    )
    pace = _guarded(
        conn, "pace", lambda: _pace_block(conn, org_id, brand_id, month, win, rows or [], spent)
    )
    quality = None if rows is None or entities is None else _guarded(
        conn, "quality",
        lambda: _quality_block(conn, org_id, brand_id, rows, spent, campaigns, entities,
                               states),
    )
    # A failed spend read nulls the campaign rows too: their numbers and `data_status` rest on
    # it, and a failed read never reads as "no rows".
    campaigns_out = None if entities is None or rows is None else _guarded(
        conn, "campaigns",
        lambda: _campaigns_block(conn, org_id, brand_id, win, campaigns, caps, entities,
                                 rows_by_campaign, currency_ok, states),
    )
    timeline = None if campaigns_out is None else _guarded(
        conn, "timeline", lambda: _timeline_block(win, campaigns_out, campaigns)
    )
    sync = _guarded(conn, "sync", lambda: _sync_block(conn, org_id, brand_id))
    closed_this_month = _guarded(
        conn, "closed_this_month", lambda: _closed_this_month(conn, org_id, brand_id, win)
    )

    return {
        "month": month, "day_of_month": win["day_of_month"],
        "days_in_month": win["days_in_month"],
        "currency": spend["currency"] if rows is not None else None,
        "spent": _money_out(spent),
        "money": money, "commerce": commerce, "pace": pace, "quality": quality,
        "timeline": timeline,
        "campaigns": campaigns_out, "sync": sync, "closed_this_month": closed_this_month,
    }
