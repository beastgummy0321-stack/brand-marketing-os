"""app/ads/triage_scale.py — F25-I01: program rules A (scale_budget) and B (refresh_creative)
over the same per-ad triage `classify()` already produced (`app/ads/triage.py`). Split into its
own file to keep `triage.py` under the module's file-size cap.

Both rules are pure reads: no LLM call, no platform write (ARCHITECTURE.md §0 "程式整理，LLM
判斷"). Rule A additionally asks `app/ads/month_budget.py::view()` the SAME question
`preflight()` asks at approve time (the identical `additional=[proposed item]` seam), so a raised
row and its own approval can never disagree (feature Decisions "Rule A").
"""

from collections import defaultdict

from app.ads import ad_status, budget, learning_rank

# Feature Decisions "Rule A"/"Rule B" (pre-dispatch challenge corrections folded in). F26-I01: the
# active/closed line now comes from the shared `ad_status.CLOSED_STATUSES` (five values) rather
# than this file's own three-value copy -- `classify()` already excludes closed ads from `items`
# entirely, so this filter is now mostly a defensive no-op against `native_status_by_entity`
# reading a status `classify()` didn't see (never re-diverges from the one true definition).
# F29-I01 (ads.md §6.33 "One ruler"): an ad is readable once the cap ruler gives it a cost grade
# (划算／偏貴／太貴) -- the trend note (`class`) no longer decides it.
_READABLE_GRADES = {"on_target", "watch", "over"}
SCALE_FACTOR = 1.2
MIN_ACTIVE_ADS_FOR_REFRESH_GATE = 3
MAX_READABLE_FOR_REFRESH_ROW = 2


def _is_active(item, native_status_by_entity):
    return not ad_status.is_closed(native_status_by_entity.get(item["entity_id"]))


def _too_new(item):
    """剛開始、數字還不夠 (F28-I02, F29-I01 words; F48 `too_new`): a known zero result under the
    沒賣出 line -- the one ungraded state that never blocks a scale-up. Any other ungraded ad
    (資料不足／未判斷) does."""
    return item.get("grade") == "insufficient" and item["reason_code"] == "too_new"


def _cheapest_on_target(active):
    """The owner's 划算 ad with the lowest cost per result (ties: `classify()`'s own (name, id)
    order) -- the row's own display item."""
    on_target = [item for item in active if item.get("grade") == "on_target"]
    return min(on_target, key=lambda item: item["current"]["cost_per_result"])


def owner_lookup(conn, org_id, brand_id):
    """One brand-wide read: for every ad entity, its budget owner -- the `ads_external_entity`
    that carries `budget_type == 'daily'` and a non-null `budget_amount`: the ad's own parent
    when it's an adset carrying a daily budget, else the campaign entity when IT carries a daily
    budget (CBO), else `None` (a lifetime-budget owner, an unresolved/ABO campaign budget, or a
    genuine data gap -- see "Gaps kept honest"). Items never carry `parent_native_id`
    themselves, so this is the one query that reads it (feature Decisions).

    F27-I06: public on purpose -- `triage_capacity.py`'s own `capacity_view` needs the exact same
    "daily budget owner" definition (never a second, divergent copy), so this is no longer
    module-private."""
    rows = conn.execute(
        "SELECT id,campaign_id,native_kind,native_id,parent_native_kind,parent_native_id,name,"
        "budget_type,budget_amount,currency,start_date,end_date FROM ads_external_entity "
        "WHERE org_id=%s AND brand_id=%s AND native_kind IN ('ad','adset','campaign')",
        (org_id, brand_id),
    ).fetchall()
    ads = []
    adsets_by_campaign = defaultdict(dict)  # campaign_id -> {native_id: row}
    campaign_owner_by_campaign = {}  # campaign_id -> row
    for row in rows:
        row = dict(row)
        if row["native_kind"] == "ad":
            ads.append(row)
        elif row["native_kind"] == "adset":
            adsets_by_campaign[row["campaign_id"]][row["native_id"]] = row
        elif row["native_kind"] == "campaign":
            campaign_owner_by_campaign[row["campaign_id"]] = row

    def _has_daily_budget(row):
        return (
            row is not None and row["budget_type"] == "daily" and row["budget_amount"] is not None
        )

    owner_by_entity = {}
    for ad in ads:
        owner = None
        if ad["parent_native_kind"] == "adset":
            adset = adsets_by_campaign.get(ad["campaign_id"], {}).get(ad["parent_native_id"])
            if _has_daily_budget(adset):
                owner = adset
        if owner is None:
            campaign_owner = campaign_owner_by_campaign.get(ad["campaign_id"])
            if _has_daily_budget(campaign_owner):
                owner = campaign_owner
        if owner is not None:
            owner_by_entity[ad["id"]] = owner
    return owner_by_entity


SCALE_HOLD_TEXT = "樣本少，先不加碼"


def _sales(item) -> int:
    """The graded window's known result count (unknown counts as none sold)."""
    count = item["current"].get("result_count")
    return int(count) if count is not None else 0


def _raise_tenths() -> str:
    """The raise as the owner reads it: `SCALE_FACTOR` 1.2 -> 「2 成」 (no float noise)."""
    return f"{(SCALE_FACTOR - 1) * 10:g} 成"


def scale_reason_text(best_item) -> str:
    """F48 Contract R "reason texts": the raise's reason from the owner's cheapest 划算 ad --
    「近期每筆 X 都在上限 Y 內，加碼 2 成擴量」 (money through `learning_rank.whole`)."""
    cost = learning_rank.whole(best_item["current"]["cost_per_result"])
    cap = learning_rank.whole(best_item["target"]["value"])
    return f"近期每筆 {cost} 都在上限 {cap} 內，加碼 {_raise_tenths()}擴量"


def scale_candidates(conn, org_id, brand_id, classified_items_by_campaign, native_status_by_entity,
                      month_view, holds=None):
    """Rule A -- one candidate per budget owner (adset, or the campaign when the campaign holds
    the budget) whose every ACTIVE graded ad is 划算 (F28-I02, ads.md §6.32: `grade ==
    "on_target"`; 剛開始 is allowed, any other grade or ungraded state blocks), with at least one
    划算 ad -- the trend (`class`/`previous`) is a note only, never a gate -- and whose proposed
    +20% raise still leaves this month's budget
    `available` not null and >= 0 through the SAME `month_budget.view(..., additional=[...])`
    seam `preflight()` uses at approve. `month_view` is `additional_items -> budget dict`,
    already bound to this brand/month (`triage.py::_month_view_fn`) -- kept as a callable so this
    function never needs its own month string or a second `conn`/`org`/`brand` triple, and so
    tests can stub it without a real month-budget fixture.

    F48 Contract R (a money action states its reason): an owner that qualifies on grades but whose
    active ads sold fewer than `triage.MIN_RESULT_EVENTS` in their graded windows (summed) is not
    proposed; when the caller passes a `holds` list it gets one entry per such owner --
    `{owner_id, owner_name, campaign_id, sales, reason_text: "樣本少，先不加碼"}` (the queue serves
    them as `scale_hold`). A proposed row's `scale.reason_text` is `scale_reason_text`."""
    from app.ads import triage  # lazy: triage imports this module

    owner_by_entity = owner_lookup(conn, org_id, brand_id)
    items_by_owner = defaultdict(list)
    owner_by_id = {}
    for items in classified_items_by_campaign.values():
        for item in items:
            owner = owner_by_entity.get(item["entity_id"])
            if owner is None:
                continue
            items_by_owner[owner["id"]].append(item)
            owner_by_id[owner["id"]] = owner

    # Qualify every owner against the ad-level rule first (cheap, no DB) -- `month_view` is only
    # ever called for owners that already pass, and the baseline (no proposed item) is computed
    # at most once, never per owner.
    qualified = []
    for owner_id, items in items_by_owner.items():
        owner = owner_by_id[owner_id]
        target = items[0]["target"]
        if target.get("value") is None:
            continue
        active = [item for item in items if _is_active(item, native_status_by_entity)]
        if not active:
            continue
        if any(item.get("grade") != "on_target" and not _too_new(item) for item in active):
            continue
        if not any(item.get("grade") == "on_target" for item in active):
            continue
        sales = sum(_sales(item) for item in active)
        if sales < triage.MIN_RESULT_EVENTS:
            if holds is not None:
                holds.append({
                    "owner_id": owner["id"], "owner_name": owner.get("name"),
                    "campaign_id": active[0]["campaign_id"], "sales": sales,
                    "reason_text": SCALE_HOLD_TEXT,
                })
            continue
        qualified.append((owner, items, active, target))

    if not qualified:
        return []

    baseline = month_view([])
    candidates = []
    for owner, items, active, target in qualified:
        from_amount = float(owner["budget_amount"])
        # F48 Contract M: the raised daily is a money figure -> `budget.whole` (half up).
        to_amount = budget.whole(from_amount * SCALE_FACTOR)
        proposed_item = {
            "kind": "budget", "target_id": owner["id"],
            "target": {"start_date": owner.get("start_date"), "end_date": owner.get("end_date")},
            "before": {"daily_amount": from_amount}, "after": {"daily_amount": to_amount},
        }
        month = month_view([proposed_item])
        if month.get("available") is None or month["available"] < 0:
            continue
        extra_needed = month["reserved_increases"] - baseline["reserved_increases"]
        best_item = _cheapest_on_target(active)
        owner_view = {
            "id": owner["id"], "name": owner.get("name"), "native_kind": owner["native_kind"],
            "native_id": owner["native_id"],
            # This owner's whole ad group, not just the currently-active subset -- a budget
            # change affects every ad sitting under this owner, paused ones included.
            "ads_count": len(items), "currency": owner.get("currency"),
        }
        candidates.append({
            "owner_id": owner["id"], "campaign_id": best_item["campaign_id"],
            "window_start": best_item["window"]["start"], "window_end": best_item["window"]["end"],
            "triage": best_item,
            "scale": {
                "owner": owner_view, "from": from_amount, "to": to_amount,
                "cost_per_result": best_item["current"]["cost_per_result"],
                "previous_cost_per_result": best_item["previous"]["cost_per_result"],
                "target": target, "window_days": best_item["window"]["days"],
                "month": {"available": month["available"], "extra_needed": extra_needed},
                "reason_text": scale_reason_text(best_item),
            },
        })
    return candidates


def refresh_candidates(classified_items_by_campaign, native_status_by_entity):
    """Rule B -- one candidate per campaign (with a target) whose readable active ads (a cost
    grade 划算／偏貴／太貴, F29-I01) have thinned to 2 or fewer while at least 3 active ads exist
    with some classification -- skipped entirely when any ad (active or not) reads `needs_resync`
    (feature Decisions: a data gap is not a creative shortage, the 資料不足 card owns that)."""
    candidates = []
    for campaign_id, items in classified_items_by_campaign.items():
        if not items:
            continue
        if any(item["reason_code"] == "needs_resync" for item in items):
            continue
        target = items[0]["target"]
        if target.get("value") is None:
            continue
        active = [item for item in items if _is_active(item, native_status_by_entity)]
        if len(active) < MIN_ACTIVE_ADS_FOR_REFRESH_GATE:
            continue
        readable = [item for item in active if item.get("grade") in _READABLE_GRADES]
        if len(readable) > MAX_READABLE_FOR_REFRESH_ROW:
            continue
        # Never null: the gate above already guarantees >= 3 active, classified ads.
        triage_item = readable[0] if readable else active[0]
        thumbnails = [item["thumbnail_url"] for item in active[:4]]
        candidates.append({
            "campaign_id": campaign_id, "campaign_name": items[0]["campaign_name"],
            "window_start": active[0]["window"]["start"], "window_end": active[0]["window"]["end"],
            "triage": triage_item,
            "refresh": {
                "campaign_id": campaign_id, "campaign_name": items[0]["campaign_name"],
                "readable_count": len(readable), "classified_count": len(active),
                "thumbnails": thumbnails,
            },
        })
    return candidates
