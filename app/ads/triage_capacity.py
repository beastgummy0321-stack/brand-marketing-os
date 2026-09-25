"""app/ads/triage_capacity.py — F27-I06: Contract F, per-campaign capacity and the cleanup
candidate ads for the brand queue. Read-only, no LLM call, no platform write
(ARCHITECTURE.md §0 "程式整理，LLM 判斷"). Reuses `triage_scale.owner_lookup` for the per-ad
daily budget owner (never a second, divergent definition of "daily budget owner", feature
Decisions "Gaps kept honest"). F28-I02: which ads close is decided by `classify()`'s own
per-ad grade against the one cap (ads.md §6.32), no longer by lowest 7-day spend.

Cleanup never touches an ad in an "open replacement lineage" (pre-dispatch correction 4): a
replacement ad whose own `new_ad` item hasn't reached `confirmed` yet, or an old ad a confirmed
`new_ad` item has already replaced but whose own follow-up pause (Contract E) hasn't happened.
This walks the SAME `plan_json.replaces_entity_id` / `ads_handoff_item.entity_id` link
`triage_ladder.py` uses for lineage, but over every verification state (not confirmed-only --
`triage_ladder` only cares about confirmed history, this cares about "not yet settled").
"""

import math
from datetime import datetime, timedelta

from app.ads import review_evidence

_CLEANUP_WINDOW_DAYS = 7


def capacity_view(items, target_value, owner_by_entity) -> dict:
    """Contract F: `{daily_budget, currency, target, can_support, active_ads}` for one campaign's
    own ACTIVE ads (`items`: this campaign's own `classify()` items, already active-ads-only).
    `daily_budget` is `null` when there are no active ads, when any active ad has no daily budget
    owner (correction 4), or when the qualifying owners don't share one currency (never a partial
    sum across currencies, same "Gaps kept honest" rule `triage_scale.py` follows). `can_support`
    is `floor(daily_budget / (target * 2))` once both are known and `target > 0`."""
    active_ads = len(items)
    daily_budget = currency = None
    if active_ads > 0:
        owners = {}
        every_has_owner = True
        for item in items:
            owner = owner_by_entity.get(item["entity_id"])
            if owner is None:
                every_has_owner = False
                break
            owners[owner["id"]] = owner
        if every_has_owner:
            currencies = {owner.get("currency") for owner in owners.values()}
            if len(currencies) == 1 and next(iter(currencies)) is not None:
                currency = next(iter(currencies))
                daily_budget = sum(float(owner["budget_amount"]) for owner in owners.values())
    can_support = None
    if daily_budget is not None and target_value is not None and target_value > 0:
        can_support = math.floor(daily_budget / (target_value * 2))
    return {
        "daily_budget": daily_budget, "currency": currency, "target": target_value,
        "can_support": can_support, "active_ads": active_ads,
    }


def _new_ad_rows(conn, org_id, brand_id, campaign_id) -> list:
    """Every `new_ad` plan_json item of this campaign's non-superseded change sets that carries a
    `replaces_entity_id` (a replacement, never a fresh non-replacement ad -- same eligibility
    `triage_ladder._new_ad_by_created_entity` applies), regardless of its own verification state
    (unlike `triage_ladder`, which only cares once `confirmed`) -- this needs to find the ones
    still UNsettled too."""
    sets = conn.execute(
        "SELECT id,plan_json,status FROM ads_change_set WHERE org_id=%s AND brand_id=%s "
        "AND campaign_id=%s AND status != 'superseded'",
        (org_id, brand_id, campaign_id),
    ).fetchall()
    rows = []
    for change_set in sets:
        change_set = dict(change_set)
        replaces_entity_id = change_set["plan_json"].get("replaces_entity_id")
        if not replaces_entity_id:
            continue
        for item in change_set["plan_json"].get("items", ()):
            if item.get("kind") == "new_ad":
                rows.append({
                    "set_id": change_set["id"], "item_id": item.get("id"),
                    "replaces_entity_id": replaces_entity_id,
                })
    return rows


def _open_lineage_entity_ids(conn, org_id, brand_id, campaign_id) -> set:
    """Entity ids that must never be a cleanup candidate (correction 4): the entity a still-
    unverified `new_ad` item created, or the old entity a CONFIRMED `new_ad` item has replaced
    while no non-superseded `pause` item targets that old entity yet (its own follow-up, Contract
    E, hasn't happened). One query for the campaign's own change sets (`_new_ad_rows`), one for
    the matching `ads_action` states, one for the created entity of each `new_ad` item
    (`ads_handoff_item.entity_id`, correction 11's same link) -- never per ad."""
    new_ad_rows = _new_ad_rows(conn, org_id, brand_id, campaign_id)
    if not new_ad_rows:
        return set()
    item_ids = [row["item_id"] for row in new_ad_rows]
    action_states = {
        r["id"]: r["verification_state"]
        for r in conn.execute(
            "SELECT id,verification_state FROM ads_action WHERE org_id=%s AND brand_id=%s "
            "AND campaign_id=%s AND id = ANY(%s)",
            (org_id, brand_id, campaign_id, item_ids),
        ).fetchall()
    }
    created_entity_by_item = {
        r["action_id"]: r["entity_id"]
        for r in conn.execute(
            "SELECT action_id,entity_id FROM ads_handoff_item WHERE org_id=%s AND brand_id=%s "
            "AND campaign_id=%s AND action_id = ANY(%s) AND entity_id IS NOT NULL",
            (org_id, brand_id, campaign_id, item_ids),
        ).fetchall()
    }
    paused_targets = set()
    for change_set in conn.execute(
        "SELECT plan_json FROM ads_change_set WHERE org_id=%s AND brand_id=%s "
        "AND campaign_id=%s AND status != 'superseded'",
        (org_id, brand_id, campaign_id),
    ).fetchall():
        for item in dict(change_set)["plan_json"].get("items", ()):
            if item.get("kind") == "pause":
                paused_targets.add(item.get("target_id"))

    open_ids = set()
    for row in new_ad_rows:
        created_entity = created_entity_by_item.get(row["item_id"])
        state = action_states.get(row["item_id"])
        if state == "confirmed":
            # The replacement is live -- the OLD ad is open until its own follow-up pause exists.
            if row["replaces_entity_id"] not in paused_targets:
                open_ids.add(row["replaces_entity_id"])
        elif created_entity is not None:
            # Not yet verified -- the NEW ad itself (once it actually exists as an entity) is open.
            open_ids.add(created_entity)
    return open_ids


def _ad_spend_7d(rows_by_entity, entity_id, start, end):
    """This ad's own known spend over `[start, end]` -- `None` unless every day of that window is
    known (never a partial-window guess), single currency, ad scope only (same shape
    `triage.py::_ad_spend` uses for its own windows -- not imported directly, `triage.py` is this
    module's own caller, never the other way around)."""
    rows = [r for r in rows_by_entity.get(entity_id, []) if start <= r["day"] <= end]
    aggregated = review_evidence.aggregate(rows, start, end)
    if aggregated["missing_days"]:
        return None
    entries = [s for s in aggregated["series"] if s["metric_scope"] == "ad"]
    if not entries or any(s["metrics"]["spend"] is None for s in entries):
        return None
    if len({s["currency"] for s in entries}) > 1:
        return None
    return sum(s["metrics"]["spend"] for s in entries)




# F28-I02 (ads.md §6.32): close order -- 沒賣出 always first, then 太貴 before 偏貴. 划算 and every
# ungraded ad (剛開始／資料不足／未判斷) never close through cleanup.
_CLOSE_RANK = {"wasted": 0, "over": 1, "watch": 2}
# F29-I01 Contract B: how bad a grade is -- a remembered ad re-enters a cleanup only when its
# current grade ranks strictly worse than the grade it had when the user said no.
GRADE_RANK = {"on_target": 0, "watch": 1, "over": 2, "wasted": 3}
_KEEP_RANK = {"wasted": 0, "over": 1, "watch": 2, "on_target": 3, "insufficient": 4, "no_target": 5}


def _cost_desc(item):
    """Highest cost per result first; an unknown cost sorts after every known one."""
    cost = item["current"].get("cost_per_result")
    return (cost is None, -(cost or 0))


def _spend_desc(item):
    spend = item["current"].get("spend")
    return (spend is None, -(spend or 0))


def _ad_view(item, spend_7d, rejected_before=None):
    """One cleanup `ads`/`keep` entry (F28 Contract "Queue"): the existing keys plus the ad's grade
    and its graded-window numbers (`classify()`'s own `current`, never re-derived). `daily_spend`
    is the last 7 days' average, `None` whenever that 7-day spend isn't fully known.
    `rejected_before` (F29-I01) is set only on a proposed ad that re-entered after a rejection."""
    current = item["current"]
    return {
        "entity_id": item["entity_id"], "name": item["name"],
        "thumbnail_url": item["thumbnail_url"], "spend_7d": spend_7d,
        "grade": item["grade"], "cost_per_result": current.get("cost_per_result"),
        "spend": current.get("spend"), "result_count": current.get("result_count"),
        "daily_spend": spend_7d / _CLEANUP_WINDOW_DAYS if spend_7d is not None else None,
        "rejected_before": rejected_before,
    }


def _entry_time(value, fallback):
    if isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value)
        except ValueError:
            return fallback
        return parsed if parsed.tzinfo is not None else fallback
    return fallback


def decision_memory(conn, org_id, brand_id) -> dict:
    """F29-I01 Contract B: the newest remembered decision per ad across this brand's change sets --
    `entity_id -> {grade, cost_per_result, cap, at, reason, change_set_id, campaign_id, title}`.
    One brand-wide read. `decision_grades` NULL (every set before this column, every set that never
    declined an ad) is no memory; a remembered grade that isn't ranked holds nothing (dropped).
    `at` is the entry's own decision time (else the set's `created_at`); the newest wins."""
    rows = conn.execute(
        "SELECT id,campaign_id,title,decision_reason,decision_grades,created_at "
        "FROM ads_change_set WHERE org_id=%s AND brand_id=%s AND decision_grades IS NOT NULL",
        (org_id, brand_id),
    ).fetchall()
    memory, times = {}, {}
    for row in rows:
        for entity_id, entry in (row["decision_grades"] or {}).items():
            if not isinstance(entry, dict) or entry.get("grade") not in GRADE_RANK:
                continue
            at = _entry_time(entry.get("at"), row["created_at"])
            if entity_id in times and times[entity_id] >= at:
                continue
            times[entity_id] = at
            memory[entity_id] = {
                "grade": entry["grade"], "cost_per_result": entry.get("cost_per_result"),
                "cap": entry.get("cap"), "at": at.isoformat(), "reason": row["decision_reason"],
                "change_set_id": row["id"], "campaign_id": row["campaign_id"],
                "title": row["title"],
            }
    return memory


def got_worse(entry, grade) -> bool:
    """A remembered ad is released only when its current grade ranks strictly worse (Contract B)."""
    return grade in GRADE_RANK and GRADE_RANK[grade] > GRADE_RANK[entry["grade"]]


def _rejected_before(entry):
    return {
        "grade": entry["grade"], "grade_label": entry.get("grade_label", entry["grade"]),
        "at": entry["at"], "reason": entry["reason"], "change_set_id": entry["change_set_id"],
    }


def cleanup_candidates(
    conn, org_id, brand_id, campaign_id, campaign_name, items, rows_by_entity, cutoff, capacity,
    scale_owner_id=None, memory=None,
) -> dict | None:
    """F28-I02 cleanup rule (ads.md §6.32) over `classify()`'s own grades: every 沒賣出 ad closes;
    then, while the active ads still exceed `can_support`, 太貴 then 偏貴 close, highest cost per
    result first (ties: higher spend, then entity id). 划算 and every ungraded ad never close. An ad
    in an open replacement lineage (correction 4) never closes either -- it stays in `keep`.

    `None` when nothing would close: a campaign over capacity with only 划算／ungraded ads left
    raises no cleanup row -- its budget owner's `scale_budget` row is the proposal instead.
    `short` is how many ads stay over capacity after the close list (0 when capacity is unknown or
    below one ad -- then only 沒賣出 closes, capacity never drives a close). `scale_owner_id` is
    echoed only while `short > 0` (the caller passes the campaign's qualifying budget owner).

    F29-I01 Contract B: `memory` (`entity_id -> remembered decision`, `decision_memory` above) is
    applied after the close order is chosen -- a remembered ad keeps its place (the cut is never
    refilled with the next ad) and is proposed only when its grade got worse, then carrying
    `rejected_before`. A close list the memory empties raises no row."""
    memory = memory or {}
    can_support = capacity["can_support"]
    active_ads = capacity["active_ads"]
    open_lineage = _open_lineage_entity_ids(conn, org_id, brand_id, campaign_id)
    closable = [
        item for item in items
        if item.get("grade") in _CLOSE_RANK and item["entity_id"] not in open_lineage
    ]
    wasted = sorted(
        (item for item in closable if item["grade"] == "wasted"),
        key=lambda item: (_spend_desc(item), item["entity_id"]),
    )
    costly = sorted(
        (item for item in closable if item["grade"] != "wasted"),
        key=lambda item: (
            _CLOSE_RANK[item["grade"]], _cost_desc(item), _spend_desc(item), item["entity_id"],
        ),
    )
    capacity_known = can_support is not None and can_support >= 1
    excess = active_ads - can_support if capacity_known else 0
    chosen = wasted + costly[:max(0, excess - len(wasted))]
    close = [
        item for item in chosen
        if item["entity_id"] not in memory or got_worse(memory[item["entity_id"]], item["grade"])
    ]
    if not close:
        return None
    short = max(0, excess - len(close))
    start = cutoff - timedelta(days=_CLEANUP_WINDOW_DAYS - 1)
    spend_7d = {
        item["entity_id"]: _ad_spend_7d(rows_by_entity, item["entity_id"], start, cutoff)
        for item in items
    }
    closing_ids = {item["entity_id"] for item in close}
    keep = sorted(
        (item for item in items if item["entity_id"] not in closing_ids),
        key=lambda item: (
            _KEEP_RANK.get(item.get("grade"), len(_KEEP_RANK)), _cost_desc(item),
            item["entity_id"],
        ),
    )
    ads = [
        _ad_view(
            item, spend_7d[item["entity_id"]],
            _rejected_before(memory[item["entity_id"]]) if item["entity_id"] in memory else None,
        )
        for item in close
    ]
    daily = [ad["daily_spend"] for ad in ads]
    return {
        "campaign_id": campaign_id, "campaign_name": campaign_name,
        "can_support": can_support, "active_ads": active_ads,
        "ads": ads,
        "keep": [_ad_view(item, spend_7d[item["entity_id"]]) for item in keep],
        "short": short,
        "daily_saving": sum(daily) if all(d is not None for d in daily) else None,
        "scale_owner_id": scale_owner_id if short > 0 else None,
    }
