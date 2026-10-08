"""app/ads/triage.py — F18-I02: classify every imported ad of a campaign by program against its
own previous window. Pure reads: no LLM call, no platform write (ARCHITECTURE.md §0 "程式整理，
LLM 判斷"). Platform-neutral (ARCHITECTURE.md §6.14/§6.15, F18 feature Decisions): no platform
literal in this file, no adapter import, no `attribution_key` parsing -- the judged cutoff is
`coverage.last_complete_day` (F50 Contract K), metrics reuse
`app/ads/review_evidence.py::aggregate`,
never a second, divergent definition of "known".
"""

import json
from collections import defaultdict
from datetime import timedelta
from hashlib import sha256

from app.ads import asset_binding_repository as bindings
from app.ads import (
    change_control_data,
    coverage,
    learning_rank,
    lifecycle,
    month_budget,
    queue_done,
    repository,
    result_kinds,
    review_evidence,
    runtime_events,
    targets,
    triage_capacity,
    triage_ladder,
    triage_scale,
)
from app.core import interrupts
from app.core.db import now_utc
from app.core.settings import today_for_org

# F18 discovery §2.3 (2026-09-21 user-confirmed numeric defaults, feature Decisions).
MIN_RESULT_EVENTS = 10
FLAT_BAND = 0.20
STOP_LOSS_SPEND_MULTIPLE = 3
WINDOW_STEPS = (7, 14, 28)
# The widest span any window pair (current + its equal-length previous window) can ever need,
# counting back from `cutoff` -- feeds the single per-campaign read (review fix: N+1 -> one read).
_MAX_LOOKBACK_DAYS = 2 * WINDOW_STEPS[-1] - 1

LABELS = {
    "stop_loss": "停損",
    "worse": "變差",
    "better": "變好",
    "flat": "持平",
    "insufficient": "資料不足",
    "no_target": "尚未設定目標",
}

# F28-I02 (ads.md §6.32), F29-I01 (§6.33 v10 words), F48 Contract R: every active ad is graded
# against the campaign's one cap T -- any known cost: 划算 <= T, 偏貴 <= 1.2T, 太貴 > 1.2T;
# 沒賣出 = spend >= 3T with a known zero result; a known zero under 3T = 剛開始、數字還不夠
# (`too_new`). Sample size is a shown flag (`sample`), never a gate. `grade_window` below is the
# one ruler (triage and `period_grades.grade_period` both call it); `class` above stays the trend
# note against the previous window and no decision reads it (§6.33 "One ruler").
WATCH_BAND = 1.2
# The money tag's 剛好打平 band: a cost within ±2 % of break-even (served by `rules()`).
BREAK_EVEN_BAND = 0.02
GRADE_LABELS = {
    "on_target": "划算", "watch": "偏貴", "over": "太貴", "wasted": "沒賣出", "no_target": "未判斷",
}
TOO_NEW_LABEL = "剛開始、數字還不夠"
NO_DATA_LABEL = "資料不足"
_TOO_NEW = ("insufficient", TOO_NEW_LABEL)
_NO_DATA = ("insufficient", NO_DATA_LABEL)
_NOT_JUDGED = ("no_target", GRADE_LABELS["no_target"])


def classify(conn, org_id: str, brand_id: str, campaign_id: str) -> dict:
    """F26-I01, F49 Contract L: judges the running ads and the ones whose delivery is unknown
    (`lifecycle.judged` -- unknown is never dropped, §6.30); an ad not delivering (in review,
    disapproved, billing) or off (paused／archived／deleted／its own adset or campaign paused) is
    kept and reported through the `closed` block below with its `delivery {state, label}`, never
    judged, never silently dropped (measured cause, feature Decisions "I01": the home strip used
    to read most of its 「資料不足」 count from closed ads)."""
    campaign = repository.get_campaign(conn, org_id, brand_id, campaign_id)
    if campaign is None:
        raise ValueError("campaign_unknown")
    target = targets.resolve(conn, org_id, brand_id, campaign)
    from app.ads import outcome

    target["cap_unit"] = outcome.cap_unit(conn, brand_id, target, campaign=campaign)
    target["break_even_unit"] = outcome.break_even_unit(conn, brand_id, target, campaign=campaign)
    cutoff = _judged_cutoff(conn, org_id, brand_id, campaign)
    read = _read_days(conn, org_id, brand_id, campaign, cutoff)
    ads = conn.execute(
        "SELECT * FROM ads_external_entity WHERE org_id=%s AND brand_id=%s AND campaign_id=%s "
        "AND native_kind='ad' ORDER BY name,id",
        (org_id, brand_id, campaign_id),
    ).fetchall()
    active_ads = [ad for ad in ads if lifecycle.judged(ad)]
    closed_ads = [ad for ad in ads if not lifecycle.judged(ad)]
    # One read for the whole campaign (review fix: was one query per ad per window step). Still
    # reads every ad's rows, closed ones included -- the `closed` block's own numbers (below)
    # reuse this same read, never a second query.
    rows_by_entity = _lookback_rows_by_entity(
        conn, org_id, brand_id, campaign_id, [ad["id"] for ad in ads], cutoff,
    )
    # F27-I09 Done #7: one campaign_objective lookup for the whole campaign (never per ad) --
    # every ACTIVE ad's own triage item carries the same `campaign_objective` its campaign card
    # would (`repository.campaign_objective_family`, the one function that tells a system-built
    # campaign's Chinese label apart from an imported campaign's own platform objective).
    campaign_objective = repository.campaign_objective_family(conn, org_id, brand_id, campaign)
    # F40-I01: every item (active and closed) names the local `ads_ad` bound to its platform ad
    # (`bound_ad_id`), so the detail page can tell a platform ad with no bound local ad apart
    # from a local ad never built without a second read. One query for the campaign's bound
    # ads, joined here by `native_id` -- never per item.
    bound_ad_by_native = _bound_ad_by_native_id(conn, org_id, brand_id, campaign_id)
    items = [
        _item(dict(ad), campaign["name"], campaign_objective, target, cutoff, read,
              rows_by_entity, bound_ad_by_native)
        for ad in active_ads
    ]
    # F27-I01 Contract A: ladder/history attaches to ACTIVE items only, never `_closed_block`.
    triage_ladder.attach(conn, org_id, brand_id, campaign_id, items)
    # F27-I06 Contract F: capacity is read over the SAME active-ads-only `items` list above --
    # never a second, divergent "active ad" query.
    owner_by_entity = triage_scale.owner_lookup(conn, org_id, brand_id)
    capacity = triage_capacity.capacity_view(items, target["value"], owner_by_entity)
    data = _data_view(conn, org_id, brand_id, campaign, cutoff, read, capacity)
    # F29 Contract D: the one data status, over the same judged window `missing_days` covers and
    # the rows this call already read (never a second query).
    window_start, window_end = read.window(cutoff, WINDOW_STEPS[-1])
    data["status"] = repository.campaign_data_status(
        conn, org_id, brand_id, campaign, sync=data["sync"], missing_days=data["missing_days"],
        has_rows=any(
            window_start <= row["day"] <= window_end
            for entity_rows in rows_by_entity.values() for row in entity_rows
        ),
    )
    return {
        "window_days": WINDOW_STEPS[-1], "items": items,
        "closed": _closed_block(closed_ads, rows_by_entity, cutoff, bound_ad_by_native),
        "data": data,
    }


def ad_item(conn, org_id, brand_id, campaign, entity) -> dict:
    """F45-I05 Contract P (ads.md §6.49): the `GET …/triage` item of ONE ad of `campaign`
    (`entity` is its `ads_external_entity` row), active or closed -- the same cutoff, coverage,
    target, per-ad window walk, `bound_ad_id` and ladder `classify()` gives its items, over one
    read of this ad's own lookback rows. Never a second definition of a grade or a window."""
    campaign_id = campaign["id"]
    target = targets.resolve(conn, org_id, brand_id, campaign)
    from app.ads import outcome

    target["cap_unit"] = outcome.cap_unit(conn, brand_id, target, campaign=campaign)
    target["break_even_unit"] = outcome.break_even_unit(conn, brand_id, target, campaign=campaign)
    cutoff = _judged_cutoff(conn, org_id, brand_id, campaign)
    read = _read_days(conn, org_id, brand_id, campaign, cutoff)
    rows_by_entity = _lookback_rows_by_entity(
        conn, org_id, brand_id, campaign_id, [entity["id"]], cutoff,
    )
    campaign_objective = repository.campaign_objective_family(conn, org_id, brand_id, campaign)
    bound_ad_by_native = _bound_ad_by_native_id(conn, org_id, brand_id, campaign_id)
    item = _item(dict(entity), campaign["name"], campaign_objective, target, cutoff, read,
                 rows_by_entity, bound_ad_by_native)
    # The item shape is the same for a closed ad (Contract P), so the ladder attaches either way.
    triage_ladder.attach(conn, org_id, brand_id, campaign_id, [item])
    return item


def _delivery_fields(entity) -> dict:
    """F49 Contract L: the ad's served delivery (`lifecycle.delivery`) beside its native status."""
    view = lifecycle.delivery(entity)
    return {"delivery": view, "delivery_label": view["label"]}


def _item(entity, campaign_name, campaign_objective, target, cutoff, read, rows_by_entity,
          bound_ad_by_native) -> dict:
    """One ad's triage item before the ladder -- shared by `classify()` and `ad_item()`."""
    return {
        **_classify_ad(entity, campaign_name, campaign_objective, target, cutoff, read,
                       rows_by_entity.get(entity["id"], [])),
        "bound_ad_id": bound_ad_by_native.get(entity["native_id"]),
        **_delivery_fields(entity),
    }


def _lookback_rows_by_entity(conn, org_id, brand_id, campaign_id, entity_ids, cutoff):
    """The ad-scope daily rows of `entity_ids` over `[cutoff - _MAX_LOOKBACK_DAYS, cutoff]`,
    grouped per entity -- every window any ad ever needs (current + its equal-length previous
    window, up to 28 days each) fits inside that range. One query, whatever the number of ads."""
    rows_by_entity = defaultdict(list)
    if not entity_ids:
        return rows_by_entity
    range_start = cutoff - timedelta(days=_MAX_LOOKBACK_DAYS)
    rows = conn.execute(
        "SELECT * FROM ads_external_daily WHERE org_id=%s AND brand_id=%s AND campaign_id=%s "
        "AND metric_scope='ad' AND entity_id = ANY(%s) AND day BETWEEN %s AND %s",
        (org_id, brand_id, campaign_id, list(entity_ids), range_start, cutoff),
    ).fetchall()
    for row in rows:
        rows_by_entity[row["entity_id"]].append(dict(row))
    return rows_by_entity


def _bound_ad_by_native_id(conn, org_id, brand_id, campaign_id) -> dict:
    """`{external_id: ads_ad.id}` of this campaign's bound local ads (`local_state='bound'`) --
    the one read behind every item's `bound_ad_id`."""
    return {
        row["external_id"]: row["id"]
        for row in conn.execute(
            "SELECT id, external_id FROM ads_ad WHERE org_id=%s AND brand_id=%s "
            "AND campaign_id=%s AND local_state='bound' AND external_id IS NOT NULL",
            (org_id, brand_id, campaign_id),
        ).fetchall()
    }


_CLOSED_ITEMS_CAP = 50


def _closed_item(entity, entity_rows, cutoff, bound_ad_by_native):
    """One closed ad's own last-window numbers (feature Decisions "I01") -- the SAME widest
    (`WINDOW_STEPS[-1]`-day) window `classify()` reports as its own `window_days`, sliced from the
    campaign-level read `classify()` already fetched (never a second query)."""
    days = WINDOW_STEPS[-1]
    end = cutoff
    start = end - timedelta(days=days - 1)
    view, spend = _ad_window(entity_rows, start, end)
    return {
        "entity_id": entity["id"], "name": entity.get("name"),
        "native_status": entity.get("native_status"), **_delivery_fields(entity),
        "thumbnail_url": _thumbnail_url(entity),
        "spend": spend, "cost_per_result": view["cost_per_result"] if view else None,
        "result_label": result_kinds.label(view["result_kind"] if view else None),
        "bound_ad_id": bound_ad_by_native.get(entity["native_id"]),
    }


def _closed_block(closed_ads, rows_by_entity, cutoff, bound_ad_by_native):
    """The `closed` block of `classify()`'s result (feature Decisions "I01", F49 Contract L):
    every ad not judged -- not delivering or off -- grouped by its served delivery label
    (`groups [{state, label, count}]`, first seen first, in the (name, id) order the campaign's
    own ad query returned), so the counts add up to `total`. `items` is capped at
    `_CLOSED_ITEMS_CAP`; `truncated` tells the frontend there's more than the cap without it having
    to compare lengths itself."""
    groups: dict = {}
    for ad in closed_ads:
        view = lifecycle.delivery(ad)
        group = groups.setdefault(view["label"], {**view, "count": 0})
        group["count"] += 1
    items = [
        _closed_item(dict(ad), rows_by_entity.get(ad["id"], []), cutoff, bound_ad_by_native)
        for ad in closed_ads[:_CLOSED_ITEMS_CAP]
    ]
    return {
        "groups": list(groups.values()),
        "total": len(closed_ads), "items": items,
        "truncated": len(closed_ads) > _CLOSED_ITEMS_CAP,
    }


def _data_view(conn, org_id, brand_id, campaign, cutoff, read, capacity):
    """The read-only `data` enrichment (F24-I01, feature Decisions) -- `sync` reuses
    `repository.campaign_sync_state` (same DB-only bound-accounts check `external_repository
    .external_view`'s own `connections` list makes); `coverage`/`missing_days`/`days` read this
    same call's own `cutoff` and day states (`read`, F49 Contract V -- never re-derived), so they
    can never disagree with what `classify()` above actually judged every ad against. The judged
    window is the widest step clipped to the campaign (`coverage.window`); `coverage` keeps its
    `{start, end}` shape = the first and last read day inside it (null when none), `days` serves
    every day's state. `capacity` (F27-I06 Contract F) is passed in already computed --
    `classify()`'s own `items`/`target` are the source, never re-derived here."""
    window_start, window_end = read.window(cutoff, WINDOW_STEPS[-1])
    return {
        "sync": repository.campaign_sync_state(conn, org_id, brand_id, campaign),
        "coverage": read.read_span(window_start, window_end),
        "missing_days": read.missing(window_start, window_end),
        "days": read.days(window_start, window_end),
        "capacity": capacity,
    }


def _read_days(conn, org_id, brand_id, campaign, cutoff):
    """F49 Contract V: the campaign's day states (`coverage.load`) over every window any ad of it
    can be judged on -- `[cutoff - _MAX_LOOKBACK_DAYS, cutoff]`, one read per campaign."""
    return coverage.load(
        conn, org_id, brand_id, campaign, cutoff - timedelta(days=_MAX_LOOKBACK_DAYS), cutoff,
    )


def _judged_cutoff(conn, org_id, brand_id, campaign):
    """The last day this campaign is judged on: its ad account's last complete day (F50 Contract
    K, `coverage.last_complete_day` -- the one answer every reader shares), never past the
    campaign's own end date (`coverage.window`) -- an ended campaign is judged up to its end."""
    cutoff = coverage.last_complete_day(conn, org_id, brand_id, campaign["id"])
    return coverage.window(campaign, cutoff, 1)[1]


def _previous_range(start, days):
    previous_end = start - timedelta(days=1)
    previous_start = previous_end - timedelta(days=days - 1)
    return previous_start, previous_end


def _window_view(start, end, days, extended_from):
    previous_start, previous_end = _previous_range(start, days)
    return {
        "start": start, "end": end, "days": days,
        "previous_start": previous_start, "previous_end": previous_end,
        "extended_from": extended_from,
    }


def _ad_spend(aggregated):
    """This ad's own known spend, summed across every `attribution_key` subgroup of its 'ad'
    scope -- reuses `aggregate()`'s own per-subgroup `metrics["spend"]` (already NULL-aware,
    F16-I06's completeness rule) rather than a second, divergent "known" predicate over the raw
    rows. Any unknown subgroup, or more than one currency among them, makes the whole window's
    spend unknown -- never an arbitrary pick, never a sum across currencies."""
    entries = [s for s in aggregated["series"] if s["metric_scope"] == "ad"]
    if not entries or any(s["metrics"]["spend"] is None for s in entries):
        return None
    if len({s["currency"] for s in entries}) > 1:
        return None
    return sum(s["metrics"]["spend"] for s in entries)


def _ad_view(aggregated):
    """This ad's one result view of an `aggregate()` output (or a stored evidence period, the same
    shape). More than one currency in the window has no single unambiguous view (same defensive
    shape `targets._trailing_30` uses) -- treated as unknown, never an arbitrary pick. F29-I01: it
    is reported as its own `mixed_currency` reason so `grade_window` reads it as 資料不足, never as
    剛開始 (`too_new`) or a 0. `None` when the window has no ad-scope row."""
    ad_views = [v for v in aggregated["result_views"] if v["metric_scope"] == "ad"]
    if len(ad_views) > 1:
        return _MIXED_CURRENCY_VIEW
    return ad_views[0] if ad_views else None


def _ad_window(entity_rows, start, end):
    """`entity_rows` is this ad's own pre-fetched rows for the whole campaign-level lookback
    (`classify()`'s single read) -- sliced here per window, never re-queried."""
    rows = [row for row in entity_rows if start <= row["day"] <= end]
    aggregated = review_evidence.aggregate(rows, start, end)
    return _ad_view(aggregated), _ad_spend(aggregated)


_MIXED_CURRENCY_VIEW = {
    "metric_scope": "ad", "currency": None, "result_kind": None, "result_count": None,
    "cost_per_result": None, "days_present": 0, "days_known": 0, "derived_zero_days": 0,
    "reason": "mixed_currency",
}


def _metrics_view(view, spend):
    """One window's numbers. `currency` (F48-I02) is the window's one currency -- `None` when
    unknown or mixed -- so a ranking over these numbers (`learning_rank.rank`, cleanup) never has
    to assume one."""
    if view is None:
        return {
            "spend": spend, "result_count": None, "cost_per_result": None,
            "result_kind": None, "result_label": result_kinds.label(None),
            "derived_zero_days": 0, "reason": "result_unknown_days", "currency": None,
        }
    return {
        "spend": spend, "result_count": view["result_count"],
        "cost_per_result": view["cost_per_result"], "result_kind": view["result_kind"],
        "result_label": result_kinds.label(view["result_kind"]),
        "derived_zero_days": view["derived_zero_days"], "reason": view["reason"],
        "currency": view["currency"],
        "result_action": view.get("result_action"),
        "result_attribution": view.get("result_attribution"),
    }


def _known_zero(view, spend):
    """A KNOWN zero result only -- an unknown/mixed window (`view["reason"] is not None`) or
    unknown spend never reads as 沒賣出 or 剛開始 (design caution, review-arbitrated)."""
    return spend is not None and view is not None and view["reason"] is None \
        and view["result_count"] == 0


def _sales(view):
    """The window's known result count as a whole number, else `None` (unknown, never 0)."""
    if view is None or view["reason"] is not None or view["result_count"] is None:
        return None
    return int(view["result_count"])


def _sample_view(spend, view, target_value, days):
    """F48 Contract R: the shown sample size of one graded window -- never a gate. `few` = 1 to
    `SAMPLE_FEW - 1` sales (「樣本少」); `too_new` = the ad has data on fewer than `WINDOW_STEPS[0]`
    days of this window and fewer than `MIN_RESULT_EVENTS` sales (「還太新」). `days` is the
    window's length; the ad's own days are the days it has rows inside it (`days_present`), so a
    7-day triage window over a 3-day-old ad still reads 還太新."""
    sales = _sales(view)
    ad_days = min(days, view["days_present"]) if view is not None else 0
    spend_multiple = spend / target_value if spend is not None and target_value else None
    days_with_events = (view["days_known"] - view["derived_zero_days"]) if view else 0
    return {
        "sales": sales,
        "few": sales is not None and 1 <= sales < learning_rank.SAMPLE_FEW,
        "too_new": ad_days < WINDOW_STEPS[0] and (sales or 0) < MIN_RESULT_EVENTS,
        "spend_multiple": spend_multiple, "days_with_events": days_with_events,
    }


def _compare(current_cost, previous_cost):
    """The guarded current-vs-previous comparison (review fix): a falsy current
    `cost_per_result` (0 -- a sale with no spend -- or `None`) is `insufficient`/`too_new`, never
    a division; kept explicit rather than relying on `_classify_ad` never passing one."""
    if not current_cost:
        return "insufficient", "too_new", None
    change_pct = (current_cost - previous_cost) / previous_cost
    if change_pct > FLAT_BAND:
        return "worse", "cost_per_result_up", change_pct
    if change_pct < -FLAT_BAND:
        return "better", "cost_per_result_down", change_pct
    return "flat", "cost_per_result_flat", change_pct


def cost_grade(cost, target_value):
    """`(grade, grade_label)` of one known cost against the cap: 划算 <= T, 偏貴 <= 1.2T, else
    太貴. An unknown cost (or no cap) is 資料不足／未判斷, never a guess."""
    if cost is None:
        return _NO_DATA
    if target_value is None:
        return _NOT_JUDGED
    if cost <= target_value:
        grade = "on_target"
    elif cost <= target_value * WATCH_BAND:
        grade = "watch"
    else:
        grade = "over"
    return grade, GRADE_LABELS[grade]


# The graded (ranked) grades -- every other grade key is "not graded" (剛開始／資料不足／未判斷).
GRADED = ("on_target", "watch", "over", "wasted")


def _figure(value) -> str:
    """A ruler number as words print it (`2`, `1.3`) -- never `2.0` or float noise."""
    return f"{round(value, 6):g}"


# F49 Contract Q: what to do about each reason. `resync` = read the platform again, `connections`
# = fix the data connection, `cap` = set the campaign's cap／result, `wait` = give it time, None =
# nothing the user can do here.
REASON_FIXES = ("resync", "connections", "cap", "wait")


def reasons() -> dict:
    """F49 Contract Q: `{reason_code: {title, text, fix}}` for every `reason_code` an item can
    carry -- the codes this module emits and the window reasons `review_evidence.aggregate` passes
    through (`app/tests/test_ads_one_ruler.py` checks the coverage by AST). The wait page prints
    these; the numbers come from the ruler constants."""
    unsold = _figure(STOP_LOSS_SPEND_MULTIPLE)
    flat = _figure(FLAT_BAND * 10)
    return {
        "too_new": {
            "title": TOO_NEW_LABEL,
            "text": f"這則廣告還沒賣出，也還沒花到上限 {unsold} 倍；再跑幾天數字才夠判斷",
            "fix": "wait",
        },
        "result_unknown_days": {
            "title": "有幾天的成果沒讀到",
            "text": (
                "平台沒回報這幾天的花費或成果數，系統不把沒讀到當成 0；"
                "重新讀取平台資料後再判斷"
            ),
            "fix": "resync",
        },
        "needs_resync": {
            "title": "有幾天的資料要重新讀",
            "text": "這段期間有幾天沒讀到，或是在系統開始記成果數之前讀的；重新讀取一次就會補上",
            "fix": "resync",
        },
        "mixed_currency": {
            "title": "混了兩種幣別",
            "text": "這段期間的花費有兩種幣別，系統不會自己換算加總，所以先不判斷",
            "fix": None,
        },
        "cap_currency_unknown": {
            "title": "上限的幣別尚未核實",
            "text": "舊上限的來源沒有原幣別，或這段資料的幣別未知；保留金額，先不比較。",
            "fix": "cap",
        },
        "cap_currency_mismatch": {
            "title": "上限與成效的幣別不同",
            "text": "這段成效與上限使用不同幣別，系統不換算，也不比較便宜或昂貴。",
            "fix": None,
        },
        "mixed_result_definition": {
            "title": "成果的算法不一致",
            "text": (
                "這段期間平台用了不只一種方式算成果（例如歸因設定改過），"
                "數字不能直接相加，所以先不判斷"
            ),
            "fix": None,
        },
        "no_previous_window": {
            "title": "沒有上一段可以比",
            "text": "這則廣告照常判斷划不划算；只是前一段同樣天數的資料不完整，看不出變好還是變差",
            "fix": "wait",
        },
        "result_kind_unknown": {
            "title": "還不知道要算哪種成果",
            "text": "這個活動還沒設定要看哪種成果（例如購買），平台資料也沒說；設定後才能判斷",
            "fix": "cap",
        },
        "target_unresolved": {
            "title": "還沒設定上限",
            "text": "這個活動還沒設定一筆訂單願意付多少廣告費，沒有尺可以量；設定上限後就會判斷",
            "fix": "cap",
        },
        "spend_over_target_no_result": {
            "title": GRADE_LABELS["wasted"],
            "text": f"花到上限 {unsold} 倍的錢，還一筆都沒賣出",
            "fix": None,
        },
        "cost_per_result_up": {
            "title": "比上一段貴",
            "text": f"跟前一段同樣天數比，每筆廣告費多了超過 {flat} 成",
            "fix": None,
        },
        "cost_per_result_down": {
            "title": "比上一段便宜",
            "text": f"跟前一段同樣天數比，每筆廣告費少了超過 {flat} 成",
            "fix": None,
        },
        "cost_per_result_flat": {
            "title": "跟上一段差不多",
            "text": f"跟前一段同樣天數比，每筆廣告費差不到 {flat} 成",
            "fix": None,
        },
    }


def limits() -> dict:
    """F50 Contract I (decision 11): the limits the screens quote, read from the constants that
    enforce them -- `review_monitor.DAYS_RANGE`／`DEFAULT_CADENCE_DAYS`,
    `brief.DEFAULT_PERIOD_DAYS`, `change_control_data.COPY_ITEMS_MAX`,
    `input_rules.UPLOAD_CAPS["ad_asset"]` (in MB)."""
    from app.ads import brief, change_control_data, review_monitor  # lazy: they import triage
    from app.core import input_rules

    low, high = review_monitor.DAYS_RANGE
    return {
        "review_days": {"min": low, "max": high},
        "review_cadence_default": review_monitor.DEFAULT_CADENCE_DAYS,
        "campaign_default_days": brief.DEFAULT_PERIOD_DAYS,
        "copy_items_max": change_control_data.COPY_ITEMS_MAX,
        "upload_max_mb": input_rules.UPLOAD_CAPS["ad_asset"] // (1024 * 1024),
    }


def rules() -> dict:
    """F48 Contract R-API: every threshold, label and glossary sentence the screens print, read
    from this module and `learning_rank` (the two ruler modules) and `experiments.DEFAULT_RULES`
    (the A/B rules) -- the frontend keeps no copy. Brand-independent today; served per brand so a
    per-brand rule can land without moving the endpoint. F49 Contract Q: `reasons` (`reasons()`)
    names every `reason_code` with its title, sentence and fix."""
    from app.ads import experiments  # lazy: experiments imports triage

    watch_tenths = _figure((WATCH_BAND - 1) * 10)
    band_pct = _figure(BREAK_EVEN_BAND * 100)
    unsold = _figure(STOP_LOSS_SPEND_MULTIPLE)
    return {
        "reasons": reasons(),
        "limits": limits(),
        "grade": {
            "watch_band": WATCH_BAND, "unsold_spend_multiple": STOP_LOSS_SPEND_MULTIPLE,
            "min_results": MIN_RESULT_EVENTS, "min_days": WINDOW_STEPS[0],
            "sample_few": learning_rank.SAMPLE_FEW, "near_best": learning_rank.NEAR_BEST,
            "break_even_band": BREAK_EVEN_BAND,
        },
        "ab": {
            key: experiments.DEFAULT_RULES[key]
            for key in ("min_days", "min_conversions_each", "relative_difference")
        },
        "labels": {
            "grade": {
                **{key: GRADE_LABELS[key] for key in ("on_target", "watch", "over", "wasted")},
                "too_new": TOO_NEW_LABEL, "no_data": NO_DATA_LABEL,
                "no_target": GRADE_LABELS["no_target"],
            },
            "verdict": dict(learning_rank.VERDICT_LABELS),
            "flags": {
                "few": learning_rank.FLAG_FEW, "relative": learning_rank.FLAG_RELATIVE,
                "relative_no_cap": learning_rank.FLAG_RELATIVE_NO_CAP,
            },
        },
        "glossary": {
            "cap": "你願意為一筆訂單付的廣告費，每個活動自己設",
            "on_target": "每筆廣告費沒超過這個活動的上限",
            "watch": f"每筆廣告費超過上限，但超過不到 {watch_tenths} 成",
            "over": f"每筆廣告費超過上限 {watch_tenths} 成以上，賣越多虧越多",
            "wasted": f"花到上限 {unsold} 倍的錢，還一筆都沒賣出",
            "thin": (
                f"賣出的廣告都有分數；還沒賣出且花不到上限 {unsold} 倍的先標「剛開始」；"
                f"成交少於 {_figure(learning_rank.SAMPLE_FEW)} 筆標「{learning_rank.FLAG_FEW}」"
            ),
            "money": (
                "拿每筆廣告費跟打平線比：比它低是有賺，比它高是在虧，"
                f"差不到 {band_pct}% 算剛好打平"
            ),
            "notebook": "系統記住哪些主打有效；下次開新活動，AI 會先讀這些，避開沒效的主打",
            # The value part 「（這裡是 X）」 is the frontend's: it knows the campaign's number.
            "break_even": "賣一筆扣掉商品成本和運費後剩下的錢；每筆廣告費超過它，就是在虧",
        },
    }


def grade_window(view, spend, target_value, days):
    """F29-I01 (ads.md §6.33 "One ruler"): the one cap grade of one window, `(grade, grade_label,
    reason_code)`. Triage (`_classify_ad`, current and previous window) and
    `period_grades.grade_period` both call this -- never a second copy. `reason_code` is `None`
    for a graded cost, `"spend_over_target_no_result"` for 沒賣出, `"too_new"` for 剛開始, else
    the unknown window's own reason (資料不足). No cap is 未判斷.

    F48 Contract R order: no cap; two currencies (資料不足); a known zero at >= 3 × cap (沒賣出);
    any other known zero (剛開始 -- no cost exists yet); an unknown window (資料不足); else the
    known cost is graded, whatever the sample size (`_sample_view` shows it). `days` is kept in
    the signature for its callers; no grade depends on it any more."""
    del days  # F48: the sample (days, results) is a shown flag, never a gate.
    if target_value is None:
        return (*_NOT_JUDGED, "target_unresolved")
    if view is not None and view["reason"] == "mixed_currency":
        return (*_NO_DATA, "mixed_currency")
    if _known_zero(view, spend):
        if spend >= STOP_LOSS_SPEND_MULTIPLE * target_value:
            return "wasted", GRADE_LABELS["wasted"], "spend_over_target_no_result"
        return (*_TOO_NEW, "too_new")
    if view is None or view["reason"] is not None or spend is None:
        reason = view["reason"] if view is not None else None
        return (*_NO_DATA, reason or "result_unknown_days")
    return (*cost_grade(view["cost_per_result"], target_value), None)


def _grade_move(previous_grade, grade):
    """`{from, to}` only when both windows are graded and the grade changed (Contract A)."""
    if previous_grade in GRADED and grade in GRADED and previous_grade != grade:
        return {"from": previous_grade, "to": grade}
    return None


def _thumbnail_url(entity):
    """This ad's own creative thumbnail, read from the already-loaded `ads_external_entity
    .creative` jsonb -- `creative.fields.thumbnail_url` first, else `.image_url`, else `None`
    (issue Done #1). Same field set `adapters/meta_read.py::creative_summary` writes; no new
    query, no platform branch."""
    fields = (entity.get("creative") or {}).get("fields") or {}
    return fields.get("thumbnail_url") or fields.get("image_url") or None


def _classify_ad(entity, campaign_name, campaign_objective, target, cutoff, read, entity_rows):
    """One ad's grade. Every window is `read.window` (F49 Contract V: ends at the judged cutoff,
    starts no earlier than the campaign's start) and must be read on every campaign day
    (`read.covered`: `data` or `empty`) before it proves anything."""
    base = {
        "entity_id": entity["id"], "native_id": entity["native_id"], "name": entity.get("name"),
        "campaign_id": entity["campaign_id"], "campaign_name": campaign_name,
        "campaign_objective": campaign_objective,
        "thumbnail_url": _thumbnail_url(entity),
    }
    from app.ads import outcome

    def comparison(view):
        return outcome.compare_cap_unit(target["cap_unit"], view["currency"] if view else None)

    def finish(cls, reason_code, grade, start, end, days, extended_from, view, spend,
               change_pct=None, previous=None):
        previous_start, previous_end = _previous_range(start, days)
        if previous is None:
            previous = _ad_window(entity_rows, previous_start, previous_end)
        prev_view, prev_spend = previous
        current_unit, previous_unit = comparison(view), comparison(prev_view)
        # F29-I01 Contract A: the previous equal-length window graded by the same ruler -- null
        # when it isn't fully synced, not graded (剛開始／資料不足), or when this ad isn't judged.
        previous_grade = None
        if (grade[0] != "no_target" and previous_unit["reason"] is None
                and read.covered(previous_start, previous_end)):
            prev_grade = grade_window(prev_view, prev_spend, target["value"], days)[0]
            previous_grade = prev_grade if prev_grade in GRADED else None
        return {
            **base, "class": cls, "label": LABELS[cls], "reason_code": reason_code,
            "grade": grade[0], "grade_label": grade[1],
            "previous_grade": previous_grade, "grade_move": _grade_move(previous_grade, grade[0]),
            "window": _window_view(start, end, days, extended_from),
            "target": {**target, "result_label": result_kinds.label(target["result_kind"])},
            "current": _metrics_view(view, spend), "previous": _metrics_view(prev_view, prev_spend),
            "change_pct": change_pct,
            "sample": _sample_view(
                spend, view, target["value"] if current_unit["reason"] is None else None, days,
            ),
            "cap_comparison": current_unit, "previous_cap_comparison": previous_unit,
        }

    if target["value"] is None:
        first_start, first_end = read.window(cutoff, WINDOW_STEPS[0])
        first_days = max((first_end - first_start).days + 1, 0)
        first_view, first_spend = _ad_window(entity_rows, first_start, first_end)
        return finish("no_target", "target_unresolved", _NOT_JUDGED, first_start, first_end,
                      first_days, None, first_view, first_spend)

    days = start = end = view = spend = None
    extended_from = None
    graded = None
    for step_idx, step_days in enumerate(WINDOW_STEPS):
        step_start, step_end = read.window(cutoff, step_days)
        if start is not None and step_start == start:
            # Clipped at the campaign's start: a longer step reads the same days again.
            break
        if start is not None:
            extended_from = days
        start, end = step_start, step_end
        days = (end - start).days + 1
        if days <= 0:
            # The campaign starts after the judged cutoff: nothing ran yet.
            return finish("insufficient", "too_new", _TOO_NEW, start, end, 0, None, None, None)
        if not read.covered(start, end):
            # Review blocker: an unsynced part of the window must never read as a proven
            # anything. Stop here -- a longer window is covered even less, so extending past a
            # coverage gap can only make the evidence worse, never better.
            view, spend = _ad_window(entity_rows, start, end)
            return finish("insufficient", "needs_resync", _NO_DATA, start, end, days,
                          extended_from, view, spend)
        view, spend = _ad_window(entity_rows, start, end)
        if step_idx == 0 and target["result_kind"] is None \
                and (view is None or view["result_kind"] is None):
            return finish("no_target", "result_kind_unknown", _NOT_JUDGED, start, end, days,
                          extended_from, view, spend)
        unit = comparison(view)
        if view is not None and view["reason"] is None and unit["reason"] is not None:
            return finish("insufficient", unit["reason"], _NO_DATA, start, end, days,
                          extended_from, view, spend)
        graded = grade_window(view, spend, target["value"], days)
        if graded[0] == "wasted":
            return finish("stop_loss", graded[2], graded[:2], start, end, days, extended_from,
                          view, spend)
        # F48: extend only while nothing is graded yet (剛開始／資料不足) -- a sold ad with a known
        # cost stops at the first covered window, whatever its sample size.
        if graded[0] != "insufficient" or step_idx == len(WINDOW_STEPS) - 1:
            break

    # `graded` is always set (WINDOW_STEPS is never empty); a graded window always has a view.
    if graded is None or view is None or graded[0] not in GRADED:
        graded = graded or (*_NO_DATA, "result_unknown_days")
        return finish("insufficient", graded[2] or "result_unknown_days", graded[:2], start, end,
                      days, extended_from, view, spend)

    # F28-I02: the grade stands on this window alone -- a missing previous window only leaves the
    # trend note (`class`) insufficient, it never blocks the grade.
    grade = graded[:2]
    previous_start, previous_end = _previous_range(start, days)
    if not read.covered(previous_start, previous_end):
        return finish("insufficient", "no_previous_window", grade, start, end, days,
                      extended_from, view, spend)
    prev_view, prev_spend = _ad_window(entity_rows, previous_start, previous_end)
    previous = (prev_view, prev_spend)
    previous_unit = comparison(prev_view)
    if (prev_view is not None and prev_view["reason"] is None
            and previous_unit["reason"] is not None):
        return finish("insufficient", previous_unit["reason"], grade, start, end, days,
                      extended_from, view, spend, previous=previous)
    # A previous cost_per_result of 0 or None (no previous result known, or known zero results)
    # is never a divisor -- `no_previous_window`, never a ZeroDivisionError.
    if prev_view is None or prev_view["reason"] is not None or not prev_view["cost_per_result"]:
        return finish("insufficient", "no_previous_window", grade, start, end, days,
                      extended_from, view, spend, previous=previous)

    cls, reason_code, change_pct = _compare(view["cost_per_result"], prev_view["cost_per_result"])
    return finish(cls, reason_code, grade, start, end, days, extended_from, view, spend,
                  change_pct=change_pct, previous=previous)


# ---------------------------------------------------------------------------
# F18-I03: brand decision queue over program triage, through the existing `interrupts` inbox.
# ---------------------------------------------------------------------------

# One interrupt category per queue kind (F27-I06: six kinds). F28-I02: `stop_loss` is no longer
# raised -- a 沒賣出 ad closes through its campaign's `cleanup` row -- but its category stays here
# so `_supersede_stale_open_rows` resolves every row still open from before.
QUEUE_CATEGORY = {
    "stop_loss": "ads_triage_stop_loss", "worse": "ads_triage_worse",
    "scale_budget": "ads_triage_scale_budget", "refresh_creative": "ads_triage_refresh_creative",
    "insufficient_data": "ads_triage_insufficient_data", "cleanup": "ads_triage_cleanup",
    # F29-I03 Contract E: the brand's period settle (`app/ads/settle.py::queue_candidate`).
    "settle": "ads_triage_settle",
    # F49 Contract Q: an ended internal campaign's closeout row.
    "closeout": "ads_triage_closeout",
}
ALL_CLASSES = ("stop_loss", "worse", "better", "flat", "insufficient", "no_target")
# F49 Contract Q: every kind the queue serves -- the decisions in board order, then the notices
# (`queue_done` owns both lists).
KINDS_AVAILABLE = [*queue_done.DECISION_KINDS, *queue_done.NOTICE_KINDS]
KINDS_PENDING = []
_NAME_BUDGET = 20  # keeps every queue message <= interrupts.MAX_MESSAGE_LEN (10 fixed chars).
_KEY_PREFIX = "ads-triage"


def _non_closed_campaign_ids(conn, org_id, brand_id):
    return lifecycle.campaign_ids(conn, org_id, brand_id, lifecycle.NOT_CLOSED)


def _queue_scope(conn, org_id, brand_id) -> dict:
    """F49 Contract Q: the campaigns the queue covers -- live ones, and ended ones that close
    internally (`lifecycle.can_close`: an imported ended campaign has no closeout, so it leaves the
    queue). `ids` keeps `lifecycle.campaigns`' order (oldest first); `ended` are the internal ended
    campaigns' rows, by id; `left` the ended campaigns the queue leaves (imported)."""
    rows = lifecycle.campaigns(conn, org_id, brand_id, ("live", "ended"))
    ended_ids = set(lifecycle.campaign_ids(conn, org_id, brand_id, ("ended",)))
    ended = {
        row["id"]: row for row in rows
        if row["id"] in ended_ids and lifecycle.can_close(row, "ended")
    }
    left = ended_ids - set(ended)
    ids = [row["id"] for row in rows if row["id"] not in left]
    return {"ids": ids, "ended": ended, "left": left}


def _classify_brand(conn, org_id, brand_id, campaign_ids=None):
    """Every imported ad of every non-closed campaign of this brand (or of `campaign_ids`), own
    program triage (`classify()`) -- a campaign with no imported ad entities contributes no items
    on its own."""
    if campaign_ids is None:
        campaign_ids = _non_closed_campaign_ids(conn, org_id, brand_id)
    items = []
    for campaign_id in campaign_ids:
        items.extend(classify(conn, org_id, brand_id, campaign_id)["items"])
    return items


def _safe_name(name):
    name = name or "(未命名廣告)"
    return name if len(name) <= _NAME_BUDGET else name[:_NAME_BUDGET - 1] + "…"


def _queue_message(cls, name):
    return f"廣告「{_safe_name(name)}」{LABELS[cls]}，待決定"


def _cost_message(trigger, name):
    if trigger == "crossed_cap":
        return _queue_message("worse", name)
    outcome = ("成本持續超過上限，待決定" if trigger == "persistently_over_cap"
               else "成本超過上限，待決定")
    room = interrupts.MAX_MESSAGE_LEN - len(outcome) - len("廣告「」")
    name = name or "(未命名廣告)"
    name = name if len(name) <= room else name[:room - 1] + "…"
    return f"廣告「{name}」{outcome}"


def _scale_message(owner_name):
    return f"「{_safe_name(owner_name)}」可加預算，待決定"


def _refresh_message(campaign_name):
    return f"「{_safe_name(campaign_name)}」素材待補，待決定"


def _insufficient_message(campaign_name):
    return f"「{_safe_name(campaign_name)}」資料不足，待處理"


def _cleanup_message(campaign_name):
    # F28-I02: a cleanup now also carries a 沒賣出 ad on a campaign within capacity, so the message
    # names what the row decides (the v9 decision card's own 花錢沒效), not "too many ads".
    return f"「{_safe_name(campaign_name)}」花錢沒效，待決定"


def _closeout_message(campaign_name):
    return f"「{_safe_name(campaign_name)}」已結束，待結案"


def _key_prefix(kind, identity_id):
    """The part of a row's dedupe key that names it whatever its window (`_dedupe_key`)."""
    return f"{_KEY_PREFIX}:{kind}:{identity_id}:"


def _key_identity(dedupe_key):
    """The identity id inside a queue row's dedupe key (`_dedupe_key`), else None."""
    parts = dedupe_key.split(":")
    return parts[2] if len(parts) == 4 and parts[0] == _KEY_PREFIX else None


def _dedupe_key(kind, identity_id, window_end):
    # Window end in the key (feature Decisions #3): a resolved decision stays resolved until the
    # window moves on to a new `window_end` -- a fresh dedupe key `interrupts.enqueue` never
    # confuses with the old, resolved-or-not, row. `identity_id`: the ad's `entity_id` for
    # `worse` (and the retired `stop_loss`), the budget owner's `id` for `scale_budget`, the
    # campaign's `id` for `refresh_creative`/`insufficient_data`/`cleanup`, the brand's `id` for
    # `settle` (window_end = the settled month's last day), the campaign's `id` for `closeout`
    # (window_end = its end date; `-` for a campaign stored ended without one).
    day = window_end.isoformat() if window_end is not None else "-"
    return f"{_key_prefix(kind, identity_id)}{day}"


def _classified_items_by_campaign(items):
    by_campaign = defaultdict(list)
    for item in items:
        by_campaign[item["campaign_id"]].append(item)
    return by_campaign


def _month_view_fn(conn, org_id, brand_id):
    """`additional_items -> budget dict`, bound to this brand's current month -- the SAME
    `month_budget.view` seam `preflight()` uses at approve, so a raised row and its own approval
    can never disagree. A callable so tests can stub it without a real month-budget fixture."""
    month = today_for_org(conn, org_id=org_id).strftime("%Y-%m")
    return lambda additional: month_budget.view(
        conn, org_id, brand_id, month, additional=additional
    )


def _campaign_insufficiency(conn, org_id, brand_id, campaign_id):
    """This one campaign's own `data` block plus its name (F26-I01, feature Decisions "I01") --
    reuses `classify()`'s own `_judged_cutoff`/`_read_days`/`_data_view` seam (one read of the
    campaign's row days, F49 Contract V), so this stays cheap alongside the per-campaign
    `classify()` call `_classify_brand` already makes.
    `None` when the campaign no longer exists (defensive -- `_non_closed_campaign_ids` only just
    listed live ids, but nothing here holds that row locked in between)."""
    campaign = repository.get_campaign(conn, org_id, brand_id, campaign_id)
    if campaign is None:
        return None
    cutoff = _judged_cutoff(conn, org_id, brand_id, campaign)
    read = _read_days(conn, org_id, brand_id, campaign, cutoff)
    # `capacity=None`: this helper only ever reads `missing_days`/`sync`/`coverage` back off
    # `data` (never serialised to a caller as `TriageData` itself) -- computing a real capacity
    # here would need `items`/`target`/an owner lookup this lightweight helper doesn't have.
    data = _data_view(conn, org_id, brand_id, campaign, cutoff, read, capacity=None)
    return {"campaign_name": campaign["name"], "data": data, "cutoff": cutoff, "read": read}


# F27-I09 correction 2: `auth_expired` is a failing-to-sync state exactly like `failed`/
# `disconnected` (a campaign stuck there needs a human to re-authorize before it can ever sync
# again) -- same 「資料不足」 queue row either way.
_SYNC_STATES_RAISING_INSUFFICIENT = {"failed", "disconnected", "auth_expired"}


def _insufficient_candidates(conn, org_id, brand_id, by_campaign) -> list:
    """The campaign-level 「資料不足」 queue row (F26-I01, feature Decisions "I01") -- one
    candidate per non-closed campaign that has at least one ACTIVE ad (`by_campaign` only ever
    carries a campaign whose triage items are active ads, `classify()` no longer judges closed
    ones) whose own `data` block shows `missing_days` non-empty OR `sync.state` failed/
    disconnected. `window_end` is the campaign's own account cutoff (the same date every other
    row's window would extend to on this campaign) -- it moves forward daily, so a resolved row
    stays resolved only until the NEXT day's refresh, same "window moves on" rule every other kind
    already follows. `triage` is the first active ad's own item (`by_campaign`'s own (name, id)
    order, same as `classify()`'s query) -- always present, since the >=1-active-ad gate above
    guarantees a non-empty list."""
    candidates = []
    for campaign_id, campaign_items in by_campaign.items():
        if not campaign_items:
            continue
        info = _campaign_insufficiency(conn, org_id, brand_id, campaign_id)
        if info is None:
            continue
        data = info["data"]
        if not (data["missing_days"] or data["sync"]["state"] in _SYNC_STATES_RAISING_INSUFFICIENT):
            continue
        window_end = info["cutoff"]
        triage_item = campaign_items[0]
        candidates.append({
            "kind": "insufficient_data", "identity_id": campaign_id, "campaign_id": campaign_id,
            "window_start": window_end, "window_end": window_end,
            "message": _insufficient_message(info["campaign_name"]),
            "action_url": f"/brands/{brand_id}/ads/campaigns/{campaign_id}/wait",
            "payload": {
                "triage": triage_item,
                "insufficient": {
                    "campaign_id": campaign_id, "campaign_name": info["campaign_name"],
                    "missing_days": data["missing_days"], "sync_state": data["sync"]["state"],
                    "coverage": data["coverage"],
                },
            },
        })
    return candidates


def _campaign_recent_rows_by_entity(conn, org_id, brand_id, campaign_id, entity_ids, start, end):
    """This campaign's own ad-scope daily rows over `[start, end]`, sliced per entity -- used only
    by `_cleanup_candidates` below (Contract F's own 7-day spend, never `classify()`'s wider
    lookback -- that window belongs to `classify()`'s own per-ad judgement, never re-borrowed
    here)."""
    rows_by_entity = defaultdict(list)
    if not entity_ids:
        return rows_by_entity
    rows = conn.execute(
        "SELECT * FROM ads_external_daily WHERE org_id=%s AND brand_id=%s AND campaign_id=%s "
        "AND metric_scope='ad' AND entity_id = ANY(%s) AND day BETWEEN %s AND %s",
        (org_id, brand_id, campaign_id, list(entity_ids), start, end),
    ).fetchall()
    for row in rows:
        rows_by_entity[row["entity_id"]].append(dict(row))
    return rows_by_entity


def _cleanup_candidates(conn, org_id, brand_id, by_campaign, scale_owner_by_campaign) -> list:
    """The cleanup queue row (Contract F, F28-I02 grades) -- one candidate per campaign that has a
    沒賣出 ad, or is over its own capacity (`triage_capacity.capacity_view`) with a 太貴／偏貴 ad to
    close (`triage_capacity.cleanup_candidates`). `owner_lookup` is one brand-wide read shared by
    every campaign here (never per campaign). A campaign whose own trailing 7-day window isn't
    fully synced never raises this row at all. `scale_owner_by_campaign` names the campaign's
    qualifying `scale_budget` owner, echoed while ads stay over capacity after the cut."""
    if not by_campaign:
        return []
    owner_by_entity = triage_scale.owner_lookup(conn, org_id, brand_id)
    memory = decision_memory(conn, org_id, brand_id)
    candidates = []
    for campaign_id, campaign_items in by_campaign.items():
        if not campaign_items:
            continue
        info = _campaign_insufficiency(conn, org_id, brand_id, campaign_id)
        if info is None:
            continue
        cutoff, read = info["cutoff"], info["read"]
        window_start = cutoff - timedelta(days=6)
        if not read.covered(window_start, cutoff):
            continue
        target_value = campaign_items[0]["target"].get("value")
        capacity = triage_capacity.capacity_view(campaign_items, target_value, owner_by_entity)
        rows_by_entity = _campaign_recent_rows_by_entity(
            conn, org_id, brand_id, campaign_id,
            {item["entity_id"] for item in campaign_items}, window_start, cutoff,
        )
        cleanup = triage_capacity.cleanup_candidates(
            conn, org_id, brand_id, campaign_id, info["campaign_name"], campaign_items,
            rows_by_entity, cutoff, capacity,
            scale_owner_id=scale_owner_by_campaign.get(campaign_id), memory=memory,
        )
        # F47-I07 (drill-10 Q1): a cleanup with nothing to close is no decision -- never an open
        # row offering 「核准清理（關 0 則）」.
        if cleanup is None or not cleanup["ads"]:
            continue
        candidates.append({
            "kind": "cleanup", "identity_id": campaign_id, "campaign_id": campaign_id,
            "window_start": window_start, "window_end": cutoff,
            "message": _cleanup_message(info["campaign_name"]),
            "action_url": f"/brands/{brand_id}/ads/campaigns/{campaign_id}"
                          f"/propose/cleanup/{campaign_id}",
            "payload": {"triage": campaign_items[0], "cleanup": cleanup},
        })
    return candidates


def _became_costly(item) -> bool:
    move = item.get("grade_move")
    return move is not None and move["from"] == "on_target" and move["to"] in {"watch", "over"}


def _cost_trigger(item):
    """The canonical absolute grade owns the decision; trend and sample size do not."""
    if item.get("grade") in {"watch", "over"} and _became_costly(item):
        return "crossed_cap"
    if item.get("grade") != "over":
        return None
    return ("persistently_over_cap" if item.get("previous_grade") == "over"
            else "currently_over_cap")


def decision_memory(conn, org_id, brand_id) -> dict:
    """F29-I01 Contract B: `triage_capacity.decision_memory` (newest memory per ad) with each
    entry's `grade_label` -- one brand-wide read shared by the cleanup rows and the month review."""
    return {
        entity_id: {**entry, "grade_label": GRADE_LABELS.get(entry["grade"], entry["grade"])}
        for entity_id, entry in triage_capacity.decision_memory(conn, org_id, brand_id).items()
    }


def campaign_cleanup(conn, org_id, brand_id, campaign_id) -> dict | None:
    """The cleanup proposal this campaign's queue row carries right now (`cleanup` payload), or
    `None` -- the same `_cleanup_candidates` path the brand queue uses, over this one campaign
    (`change_control.create` checks `declined_ids` against it)."""
    items = classify(conn, org_id, brand_id, campaign_id)["items"]
    candidates = _cleanup_candidates(conn, org_id, brand_id, {campaign_id: items}, {})
    return candidates[0]["payload"]["cleanup"] if candidates else None


def _queue_candidates(conn, org_id, brand_id, items, *, settle=True, holds=None) -> list:
    """Every row this brand's queue could raise -- qualifying `scale_budget` owners, `cleanup`
    campaigns, one `worse` row per crossed-cap or currently over-cap ad (never inside its
    campaign's cleanup `ads`, F28-I02), `refresh_creative` campaigns and `insufficient_data`
    campaigns (`triage_scale.py`/`triage_capacity.py`). `stop_loss` rows are no longer raised
    (F28-I02): a 沒賣出 ad closes through its campaign's cleanup row. Each candidate carries its
    `kind`, dedupe identity, window and queue message/action_url, plus the extra payload
    `_queue_payload` attaches to its row. `holds` (F48-I02) collects the owners a raise is held
    back for on sample size (`triage_scale.scale_candidates`)."""
    by_campaign = _classified_items_by_campaign(items)
    candidates = []
    scale_owner_by_campaign = {}
    month_view = _month_view_fn(conn, org_id, brand_id)
    for scale in triage_scale.scale_candidates(
        conn, org_id, brand_id, by_campaign, month_view, holds=holds,
    ):
        owner_id = scale["owner_id"]
        scale_owner_by_campaign.setdefault(scale["campaign_id"], owner_id)
        candidates.append({
            "kind": "scale_budget", "identity_id": owner_id, "campaign_id": scale["campaign_id"],
            "window_start": scale["window_start"], "window_end": scale["window_end"],
            "message": _scale_message(scale["scale"]["owner"]["name"]),
            "action_url": f"/brands/{brand_id}/ads/campaigns/{scale['campaign_id']}/detail"
                          f"?owner={owner_id}",
            "payload": {"triage": scale["triage"], "scale": scale["scale"]},
        })
    cleanup_candidates = _cleanup_candidates(
        conn, org_id, brand_id, by_campaign, scale_owner_by_campaign,
    )
    # An ad inside its campaign's cleanup proposal is decided there -- no second `worse` row.
    in_cleanup = {
        ad["entity_id"] for c in cleanup_candidates for ad in c["payload"]["cleanup"]["ads"]
    }
    for item in items:
        # Current cap grades own these decisions; the trend note never raises a row.
        trigger = _cost_trigger(item)
        if trigger is None or item["entity_id"] in in_cleanup:
            continue
        candidates.append({
            "kind": "worse", "identity_id": item["entity_id"], "campaign_id": item["campaign_id"],
            "window_start": item["window"]["start"], "window_end": item["window"]["end"],
            "message": _cost_message(trigger, item["name"]),
            "action_url": f"/brands/{brand_id}/ads/campaigns/{item['campaign_id']}/detail"
                          f"?ad={item['entity_id']}",
            "payload": {"triage": item, "trigger_reason": trigger},
        })
    # Correction 4: while a campaign has an open cleanup row, its refresh_creative row is not
    # raised (cleanup first) -- `identity_id` is the campaign id for both kinds.
    cleanup_campaign_ids = {c["identity_id"] for c in cleanup_candidates}
    candidates.extend(cleanup_candidates)
    for refresh in triage_scale.refresh_candidates(by_campaign):
        campaign_id = refresh["campaign_id"]
        if campaign_id in cleanup_campaign_ids:
            continue
        candidates.append({
            "kind": "refresh_creative", "identity_id": campaign_id, "campaign_id": campaign_id,
            "window_start": refresh["window_start"], "window_end": refresh["window_end"],
            "message": _refresh_message(refresh["campaign_name"]),
            "action_url": f"/brands/{brand_id}/ads/campaigns/{campaign_id}"
                          f"?tab=assets&material_new=1",
            "payload": {"triage": refresh["triage"], "refresh": refresh["refresh"]},
        })
    candidates.extend(_insufficient_candidates(conn, org_id, brand_id, by_campaign))
    if settle:
        candidates.extend(_settle_candidates(conn, org_id, brand_id))
    return candidates


def _settle_candidates(conn, org_id, brand_id) -> list:
    """F29-I03 Contract E: the brand's one `settle` row for the latest ended month
    (`settle.queue_candidate`, program reads only). Its `triage` is `None`: a settle is about the
    whole brand's month, not one active ad. Lazy import -- `settle` reads `period_grades`, which
    imports this module."""
    from app.ads import settle

    candidate = settle.queue_candidate(conn, org_id, brand_id)
    return [{"campaign_id": None, **candidate}] if candidate is not None else []


def _closeout_candidates(conn, org_id, brand_id, ended) -> list:
    """F49 Contract Q: one `closeout` row per internal ended campaign (`_queue_scope`) -- identity
    the campaign, window end its end date, payload `closeout {campaign_id, campaign_name, end_date,
    running {count, read_at}}` (`lifecycle.running_view`). Never done: it leaves when the campaign
    closes. One read of the ended campaigns' ad entities."""
    if not ended:
        return []
    ads_by_campaign = defaultdict(list)
    for row in conn.execute(
        "SELECT * FROM ads_external_entity WHERE org_id=%s AND brand_id=%s "
        "AND campaign_id = ANY(%s) AND native_kind='ad'",
        (org_id, brand_id, list(ended)),
    ).fetchall():
        ads_by_campaign[row["campaign_id"]].append(dict(row))
    reported = lifecycle.newest_reported(conn, org_id, brand_id)
    candidates = []
    for campaign_id, campaign in ended.items():
        end_date = lifecycle.end_date(campaign, None)
        running = lifecycle.running_view(
            campaign, ads_by_campaign.get(campaign_id, []), reported.get(campaign_id),
        )
        candidates.append({
            "kind": "closeout", "identity_id": campaign_id, "campaign_id": campaign_id,
            "window_start": end_date, "window_end": end_date,
            "message": _closeout_message(campaign["name"]),
            "action_url": f"/brands/{brand_id}/ads/campaigns/{campaign_id}?tab=perf&close=1",
            "payload": {
                "triage": None,
                "closeout": {
                    "campaign_id": campaign_id, "campaign_name": campaign["name"],
                    "end_date": end_date,
                    "running": {"count": running["count"], "read_at": running["read_at"]},
                },
            },
        })
    return candidates


def _scoped_candidates(conn, org_id, brand_id, items, open_rows, *, settle=True, holds=None,
                       scope=None):
    """F49 Contract Q: the queue's candidates over the campaigns it covers (`_queue_scope`), each
    with its `key`. An ended campaign raises its closeout row and nothing new: any other decision
    candidate of it is kept only while an open row of the same kind and identity exists (raised
    before the end), and keeps that row's key -- the judged window stops moving at the end date,
    but a row raised on the last live day still names the day before in its key. Notices of an
    ended campaign are dropped. Returns `(scoped items, candidates)`."""
    scope = scope or _queue_scope(conn, org_id, brand_id)
    items = [item for item in items if item["campaign_id"] not in scope["left"]]
    candidates = [
        *_queue_candidates(conn, org_id, brand_id, items, settle=settle, holds=holds),
        *_closeout_candidates(conn, org_id, brand_id, scope["ended"]),
    ]
    _prepare_review_candidates(conn, org_id, brand_id, candidates)
    open_keys = [row["dedupe_key"] for row in open_rows]
    done_rows = [row for row in interrupts.list_done(conn, brand_id=brand_id, org_id=org_id)
                 if row["org_id"] == org_id and row["brand_id"] == brand_id
                 and row["category"] == QUEUE_CATEGORY["worse"]] if any(
                     c.get("cost_scope") for c in candidates) else []
    done_rows.sort(key=lambda row: (str(row.get("resolved_at") or row["created_at"]), row["id"]),
                   reverse=True)
    kept = []
    for candidate in candidates:
        kind = candidate["kind"]
        candidate["ended"] = candidate["campaign_id"] in scope["ended"] and kind != "closeout"
        if not candidate["ended"]:
            candidate["key"] = _dedupe_key(kind, candidate["identity_id"],
                                           candidate["window_end"])
            if candidate.get("cost_scope"):
                suffix = "~" + candidate["cost_scope"]
                if candidate.get("review_cycle"):
                    suffix += "~" + candidate["review_cycle"]
                prefix = _key_prefix(kind, candidate["identity_id"])
                previous_episode = next((row["id"] for row in done_rows
                    if _key_identity(row["dedupe_key"]) == candidate["identity_id"]), None)
                if previous_episode is not None:
                    candidate["key"] += "-" + previous_episode
                # Keep an unresolved episode's owner across rolling dates. Once the
                # episode resolves, its receipt seeds a fresh owner even in the same window.
                candidate["key"] = next((k for k in open_keys
                    if k.startswith(prefix) and k.endswith(suffix)), candidate["key"] + suffix)
            elif candidate.get("review_cycle"):
                candidate["key"] += "~" + candidate["review_cycle"]
            kept.append(candidate)
            continue
        if kind not in queue_done.DECISION_KINDS:
            continue
        prefix = _key_prefix(kind, candidate["identity_id"])
        key = next((k for k in open_keys if k.startswith(prefix)), None)
        if key is not None:
            candidate["key"] = key
            kept.append(candidate)
    return items, kept


def _open_queue_rows(conn, org_id, brand_id) -> list:
    """This brand's open rows in every queue category (`archive_stale=False`: no side effect)."""
    categories = set(QUEUE_CATEGORY.values())
    return [
        row for row in interrupts.list_open(conn, org_id=org_id, brand_id=brand_id,
                                            archive_stale=False)
        if row["category"] in categories
    ]


def _supersede_stale_open_rows(conn, org_id, brand_id, live_keys) -> None:
    """Lead review arbitration (2026-09-21, F18-I03 REQUEST_CHANGES): the same `interrupt` table
    feeds the brand home and `/api/inbox`, and auto-archive only covers `informational` severity
    -- a stale open row (superseded by a newer window, or its kind no longer qualifying) would
    otherwise sit open forever and keep inflating `brand_health`. Close every OPEN row of this
    brand in every triage category (`QUEUE_CATEGORY.values()`, six as of F27-I06) whose
    `dedupe_key` is no longer live, through the
    existing public `interrupts.resolve()` -- never a direct UPDATE from `app/ads` (architecture
    boundary). `"system"` actor precedent: `app/llm/methodology.py`. Result: at most one open row
    per (kind, identity) at any time; a user-resolved key is already not 'open', so this loop
    never touches it and never re-raises it. F49 Contract Q: a notice (`scale_budget`／
    `insufficient_data`) is never live here, so its open rows resolve."""
    for category in QUEUE_CATEGORY.values():
        stale = [
            row for row in interrupts.list_open(conn, org_id=org_id, brand_id=brand_id,
                                                 category=category, archive_stale=False)
            if row["dedupe_key"] not in live_keys
        ]
        for row in stale:
            interrupts.resolve(conn, row["id"], actor="system", org_id=org_id)


def refresh_queue(conn, org_id, brand_id) -> dict:
    """`POST .../queue/refresh` (Done #3): classify the campaigns the queue covers
    (`_queue_scope`), raise one interrupt per decision row (`queue_done.DECISION_KINDS`; notices
    are served, never enqueued, F49 Contract Q). An ended campaign gets its closeout row and no
    new interrupt of any other kind (`_scoped_candidates`). One transaction -- every enqueue below,
    then a single commit. Afterward, supersede every open queue row no longer live
    (`_supersede_stale_open_rows`) -- each call its own `resolve()`, not part of the enqueue
    transaction. The returned payload is read back afterward, same shape as `get_queue()`.

    F27-I00 Contract J: also records one `queue_refresh` runtime event for this brand (Contract K's
    recovery step 4, a later F27 issue, reads it back) -- same transaction as the enqueue loop."""
    scope = _queue_scope(conn, org_id, brand_id)
    items = _classify_brand(conn, org_id, brand_id, scope["ids"])
    holds = []
    items, candidates = _scoped_candidates(
        conn, org_id, brand_id, items, _open_queue_rows(conn, org_id, brand_id), holds=holds,
        scope=scope,
    )
    decisions = [c for c in candidates if c["kind"] in queue_done.DECISION_KINDS]
    for candidate in decisions:
        if candidate["ended"] or queue_done.done({
            "kind_key": candidate["kind"], "proposal": candidate.get("proposal"),
        }):
            continue  # kept on its open row; nothing new for an ended campaign
        interrupts.enqueue(
            conn, org_id=org_id, brand_id=brand_id, category=QUEUE_CATEGORY[candidate["kind"]],
            dedupe_key=candidate["key"],
            message=candidate["message"], action_url=candidate["action_url"],
        )
    runtime_events.record(conn, "queue_refresh", org_id=org_id, brand_id=brand_id)
    conn.commit()
    _supersede_stale_open_rows(conn, org_id, brand_id, {
        c["key"] for c in decisions if not queue_done.done({
            "kind_key": c["kind"], "proposal": c.get("proposal"),
        })
    })
    return _queue_payload(conn, org_id, brand_id, items, candidates, holds)


def brand_items(conn, org_id, brand_id) -> list:
    """Every active ad's triage item across this brand's non-closed campaigns (`classify()`)."""
    return _classify_brand(conn, org_id, brand_id)


def get_queue(conn, org_id, brand_id, items=None, *, settle=True) -> dict:
    """`GET .../queue` (Done #4): read-only, no `resolve()` call here -- `refresh_queue()` is the
    only place that supersedes stale rows (it may not have run yet since the last classification
    change). Current classification decides which open interrupt rows are still live: an older
    window's open row whose kind no longer qualifies (e.g. an ad now flat, or an owner's ads no
    longer all stable) is filtered out of this payload the same way, without writing anything.
    Each listed row carries the current triage item that produced it (F19-I01, `_queue_payload`).
    `items` lets a caller that already classified the brand (`month_summary`) skip a second pass
    (items of a campaign the queue does not cover are left out); `settle=False` skips the brand's
    month `settle` row (it grades the previous month) for a caller that only counts one campaign's
    rows (`campaign_queue`). `scale_hold` (F48-I02) lists the budget owners whose raise is held
    back on sample size: `[{owner_id, owner_name, campaign_id, sales, reason_text}]`
    (`triage_scale.scale_candidates`). F49 Contract Q: every row carries `decision`, `done`,
    `position` and `campaign_id`; the payload carries `decisions {kinds, open}`."""
    scope = _queue_scope(conn, org_id, brand_id)
    if items is None:
        items = _classify_brand(conn, org_id, brand_id, scope["ids"])
    holds = []
    items, candidates = _scoped_candidates(
        conn, org_id, brand_id, items, _open_queue_rows(conn, org_id, brand_id), settle=settle,
        holds=holds, scope=scope,
    )
    return _queue_payload(conn, org_id, brand_id, items, candidates, holds)


# ---------------------------------------------------------------------------
# F49 Contract Q: the inbox follows the queue -- a row that turned done has no open interrupt.
# ---------------------------------------------------------------------------


def campaign_queue(conn, org_id, brand_id, campaign_id, items=None) -> dict:
    """The brand queue over one campaign's items (`classify()`'s, or `items` when the caller
    already has them), without the brand's `settle` row: its rows whose `campaign_id` is this
    campaign are exactly that campaign's rows of the brand queue. A campaign the queue no longer
    covers (closed; imported and ended) contributes no item."""
    if items is None:
        scope = _queue_scope(conn, org_id, brand_id)
        items = (
            classify(conn, org_id, brand_id, campaign_id)["items"]
            if campaign_id in scope["ids"] else []
        )
    return get_queue(conn, org_id, brand_id, items=items, settle=False)


def _resolve_unless_waiting(conn, org_id, brand_id, open_rows, campaign_id) -> None:
    """Resolve each of `open_rows` (open queue interrupts) that the campaign's queue no longer
    serves, or serves as `done` (`queue_done.done`). Each `interrupts.resolve` commits."""
    if not open_rows:
        return
    served = {
        row["dedupe_key"]: row
        for row in campaign_queue(conn, org_id, brand_id, campaign_id)["items"]
    }
    for row in open_rows:
        current = served.get(row["dedupe_key"])
        if current is None or current["done"]:
            interrupts.resolve(conn, row["id"], actor="system", org_id=org_id)


def _identity_campaign(conn, org_id, brand_id, kind, identity_id):
    """The campaign a queue row belongs to: its identity for a campaign row, the ad's campaign for
    a `worse` row (an `ads_external_entity` id)."""
    if kind != "worse":
        return identity_id
    row = conn.execute(
        "SELECT campaign_id FROM ads_external_entity WHERE org_id=%s AND brand_id=%s AND id=%s",
        (org_id, brand_id, identity_id),
    ).fetchone()
    return row["campaign_id"] if row is not None else None


def resolve_done(conn, org_id, brand_id, *, kind, identity_id) -> None:
    """F49 Contract Q: resolve the open interrupt(s) of the `kind` row of `identity_id` once
    `queue_done.done` holds for it (or the queue no longer serves it). Called after the write that
    made it done has committed: `change_control` decide／approve, the readback confirmation
    (`handoff_check`), `review_rounds.decide`. The brand's `settle` row is not resolved here."""
    if kind not in queue_done.DECISION_KINDS or kind == "settle":
        return
    prefix = _key_prefix(kind, identity_id)
    open_rows = [
        row for row in interrupts.list_open(
            conn, org_id=org_id, brand_id=brand_id, category=QUEUE_CATEGORY[kind],
            archive_stale=False,
        )
        if row["dedupe_key"].startswith(prefix)
    ]
    if not open_rows:
        return
    campaign_id = _identity_campaign(conn, org_id, brand_id, kind, identity_id)
    if campaign_id is not None:
        _resolve_unless_waiting(conn, org_id, brand_id, open_rows, campaign_id)


def resolve_change_set(conn, org_id, brand_id, change_set_id) -> None:
    """`resolve_done` for the queue row a change set answers: a cleanup set's `cleanup` row (the
    campaign), a review copy set's `worse` row (the ad its copy item targets). Any other set
    answers no decision row."""
    row = conn.execute(
        "SELECT campaign_id,plan_json FROM ads_change_set WHERE org_id=%s AND brand_id=%s "
        "AND id=%s",
        (org_id, brand_id, change_set_id),
    ).fetchone()
    if row is None:
        return
    plan = row["plan_json"] or {}
    if plan.get("source") == "cleanup":
        resolve_done(conn, org_id, brand_id, kind="cleanup", identity_id=row["campaign_id"])
    if plan.get("review_id"):
        for item in plan.get("items") or ():
            if item.get("kind") == "copy" and item.get("target_id"):
                resolve_done(conn, org_id, brand_id, kind="worse", identity_id=item["target_id"])


def resolve_action(conn, org_id, brand_id, action_id) -> None:
    """`resolve_change_set` for the set an `ads_action` belongs to (the readback confirmation)."""
    row = conn.execute(
        "SELECT change_set_id FROM ads_action WHERE org_id=%s AND brand_id=%s AND id=%s",
        (org_id, brand_id, action_id),
    ).fetchone()
    if row is not None and row["change_set_id"] is not None:
        resolve_change_set(conn, org_id, brand_id, row["change_set_id"])


def resolve_campaign(conn, org_id, brand_id, campaign_id) -> None:
    """Every open queue row of this campaign -- its own rows and its ads' and budget owners' rows,
    by the identity in the dedupe key -- that its queue no longer serves as waiting.
    `closeout.close` calls it once the campaign is closed, which leaves none of them open."""
    identities = {campaign_id} | {
        row["id"] for row in conn.execute(
            "SELECT id FROM ads_external_entity WHERE org_id=%s AND brand_id=%s "
            "AND campaign_id=%s",
            (org_id, brand_id, campaign_id),
        ).fetchall()
    }
    settle_category = QUEUE_CATEGORY["settle"]
    open_rows = [
        row for row in _open_queue_rows(conn, org_id, brand_id)
        if row["category"] != settle_category and _key_identity(row["dedupe_key"]) in identities
    ]
    _resolve_unless_waiting(conn, org_id, brand_id, open_rows, campaign_id)


# ---------------------------------------------------------------------------
# F23-I01/F25-I01/F27-I06: each queue row's own `proposal`, per the "Queue row state" rule
# (feature Decisions) -- on a `worse` row, the matching `ads_review_round` (if any), plus its own
# copy change set when one exists; on a `scale_budget`/`cleanup` row, the matching change set.
# F28-I02 removed the `stop_loss` row's pause proposal together with the row itself. Read-only,
# brand-wide (one query for every non-superseded change set, one for every `ads_action`
# verification_state, one for every review round) -- never per row.
# ---------------------------------------------------------------------------


def _brand_change_sets_by_campaign(conn, org_id, brand_id) -> dict:
    """Every non-superseded change set of this brand, newest (`created_at`) first -- one query
    for the whole brand. Grouped by `campaign_id` in Python; the SQL-level `ORDER BY created_at
    DESC` is preserved inside each campaign's own sublist (stable grouping), so "the newest
    change set of the row's campaign" is just "the first match found while walking that list"."""
    rows = conn.execute(
        "SELECT id,campaign_id,status,plan_json,decision_reason,revisit_at,created_at,"
        "decision_grades FROM ads_change_set WHERE org_id=%s AND brand_id=%s "
        "AND status != 'superseded' "
        "ORDER BY created_at DESC",
        (org_id, brand_id),
    ).fetchall()
    by_campaign = defaultdict(list)
    for row in rows:
        by_campaign[row["campaign_id"]].append(dict(row))
    return by_campaign


def _brand_action_verification_states(conn, org_id, brand_id) -> dict:
    """`ads_action.id -> verification_state` for this whole brand -- one query. A change-set
    item with no matching row here has never been approved, so it reads back `data.get()`'s own
    default of `"pending"` at the call site, not here."""
    rows = conn.execute(
        "SELECT id,verification_state FROM ads_action WHERE org_id=%s AND brand_id=%s",
        (org_id, brand_id),
    ).fetchall()
    return {row["id"]: row["verification_state"] for row in rows}


def _brand_review_rounds(conn, org_id, brand_id) -> dict:
    """Every `ads_review_round` of this brand, newest (`created_at`) first -- one query for the
    whole brand (F23-I01 Done #1, same shape as `_brand_change_sets_by_campaign`). Grouped by
    `(campaign_id, entity_id)` in Python; the SQL-level `ORDER BY created_at DESC` is preserved
    inside each group, so "the newest round of this entity" is the first match while walking it."""
    rows = conn.execute(
        "SELECT id,campaign_id,entity_id,window_end,status,decision,reason,revisit_at,result_json,"
        "evidence_json "
        "FROM ads_review_round WHERE org_id=%s AND brand_id=%s ORDER BY created_at DESC",
        (org_id, brand_id),
    ).fetchall()
    by_entity = defaultdict(list)
    for row in rows:
        by_entity[(row["campaign_id"], row["entity_id"])].append(dict(row))
    return by_entity


def _matching_review_round(rounds_by_entity, campaign_id, entity_id, window,
                           sets_by_campaign=None):
    """Explicit decisions and their action lineage survive rolling observation dates."""
    for round_ in rounds_by_entity.get((campaign_id, entity_id), ()):
        change_set = _matching_review_change_set(sets_by_campaign or {}, campaign_id, round_["id"])
        if round_["status"] in {"deferred", "unjudgeable"} or change_set is not None:
            return round_
        if window["start"] <= round_["window_end"] <= window["end"]:
            return round_
        # A newer round is a lineage barrier; an older disposition must not take it over.
        return None
    return None


def _matching_review_change_set(sets_by_campaign, campaign_id, review_id):
    """The newest non-superseded change set of `campaign_id` whose own `plan_json.review_id`
    matches this round (`change_control.py::create` stores it flat, never nested -- see
    `plan_json->>'review_id'` reused the same way by `review_evidence.py:276`) -- `None` when
    there isn't one."""
    for change_set in sets_by_campaign.get(campaign_id, ()):
        if change_set["plan_json"].get("review_id") == review_id:
            return change_set
    return None


def _first_adjust_recommendation_id(result_json):
    for recommendation in (result_json or {}).get("recommendations", ()):
        if recommendation.get("recommendation") == "adjust":
            return recommendation.get("id")
    return None


def review_creative_scope(entity):
    """Reuse the binding owner's content identity, excluding its volatile read metadata."""
    creative = entity.get("creative") or {}
    return {"kind": creative.get("kind"), "copy_fields": change_control_data.copy_fields(entity),
            "creative_hash": bindings.creative_hash(creative)}


def review_decision_scope(item, creative=None):
    """Only semantic conditions, never dates, counts, spend or a full evidence hash."""
    return {
        "target": {k: item.get("target", {}).get(k) for k in
                   ("value", "revision", "basis", "result_kind", "cap_unit")},
        "measurement": {k: item.get("current", {}).get(k) for k in
                        ("currency", "result_kind", "result_action", "result_attribution")},
        "creative": creative,
    }


def _creative_scope_changed(saved, current):
    if not saved or current is None:
        return False
    if not any(k in saved for k in ("kind", "copy_fields", "creative_hash")):
        # Before the complete representation, decision_grades retained only copy_fields.
        return saved != current["copy_fields"]
    return any(k in saved and saved[k] != current.get(k)
               for k in ("kind", "copy_fields", "creative_hash"))


def _evidence_creative_changed(evidence, creative):
    saved = (evidence.get("conditions") or {}).get("creative_snapshot") or {}
    stable_hash = (evidence.get("premise") or {}).get("creative_hash")
    if stable_hash is not None:
        saved = {**saved, "creative_hash": stable_hash}
    return _creative_scope_changed(saved, creative)


def _review_scope_changed(round_, item, creative, change_set):
    evidence = round_.get("evidence_json") or {}
    saved_target = (evidence.get("campaign") or {}).get("target") or {}
    scope = review_decision_scope(item, creative)
    if change_set is not None and change_set["status"] == "rejected":
        remembered = (change_set.get("decision_grades") or {}).get(item["entity_id"])
        if remembered and remembered.get("scope") is not None:
            saved_scope = remembered["scope"]
            saved_creative = saved_scope.get("creative")
            legacy_creative = not saved_creative or "creative_hash" not in saved_creative
            return (any(saved_scope.get(k) != scope[k] for k in ("target", "measurement"))
                    or _creative_scope_changed(saved_creative, creative)
                    or (legacy_creative and _evidence_creative_changed(evidence, creative)) or (
                remembered.get("grade") in triage_capacity.GRADE_RANK
                and triage_capacity.got_worse(remembered, item["grade"])
            ))
    if any(k in saved_target and saved_target[k] != v for k, v in scope["target"].items()):
        return True
    period = evidence.get("current") or {}
    if "result_views" in period:
        saved_view = _ad_view(period)
        # The same reducer grades both stored and current evidence. Newly comparable
        # evidence is a semantic change; choosing a first mixed view would hide it.
        if saved_view is None or saved_view.get("reason") is not None or period.get("missing_days"):
            return True
        if any(saved_view.get(k) != v for k, v in scope["measurement"].items()):
            return True
    if _evidence_creative_changed(evidence, creative):
        return True
    if change_set is not None and change_set["status"] == "rejected":
        remembered = (change_set.get("decision_grades") or {}).get(item["entity_id"])
        if remembered:
            if remembered.get("grade") in triage_capacity.GRADE_RANK:
                return triage_capacity.got_worse(remembered, item["grade"])
    return False


def _prepare_review_candidates(conn, org_id, brand_id, candidates):
    """Read dispositions before enqueue: a remembered decision is served, never re-raised."""
    reviews = [c for c in candidates if c["kind"] == "worse"]
    if not reviews:
        return
    rounds = _brand_review_rounds(conn, org_id, brand_id)
    sets = _brand_change_sets_by_campaign(conn, org_id, brand_id)
    states = _brand_action_verification_states(conn, org_id, brand_id)
    entities = conn.execute(
        "SELECT * FROM ads_external_entity WHERE org_id=%s AND brand_id=%s AND native_kind='ad'",
        (org_id, brand_id),
    ).fetchall()
    creatives = {e["id"]: review_creative_scope(e) for e in entities}
    lineage = {
        campaign_id: triage_capacity.open_lineage_entity_ids(conn, org_id, brand_id, campaign_id)
        for campaign_id in {c["campaign_id"] for c in reviews}
    }
    for candidate in reviews:
        item = candidate["payload"]["triage"]
        if (item["entity_id"] in lineage[item["campaign_id"]]
                or _cleanup_owns_review(sets, states, item)):
            candidates.remove(candidate)
            continue
        creative = creatives.get(item["entity_id"])
        if candidate["payload"]["trigger_reason"] != "crossed_cap":
            candidate["cost_scope"] = sha256(json.dumps(
                review_decision_scope(item, creative), sort_keys=True, default=str,
            ).encode()).hexdigest()[:16]
        candidate["proposal"] = _row_review_proposal(rounds, sets, states, item, creative)
        round_ = _matching_review_round(rounds, item["campaign_id"], item["entity_id"],
                                        item["window"], sets)
        if round_ is not None and candidate["proposal"] is None:
            cycle = {"review_id": round_["id"], "scope": review_decision_scope(item, creative),
                     "grade": item["grade"]}
            candidate["review_cycle"] = sha256(json.dumps(
                cycle, sort_keys=True, default=str).encode()).hexdigest()[:16]


def _cleanup_owns_review(sets, states, item):
    """An unfinished or explicitly held pause owns its ad even outside today's close list."""
    for change_set in sets.get(item["campaign_id"], ()):
        if change_set["plan_json"].get("source") != "cleanup":
            continue
        pause = next((i for i in change_set["plan_json"].get("items", ())
                      if i.get("kind") == "pause"
                      and i.get("target_id") == item["entity_id"]), None)
        if pause is None:
            continue
        status = change_set["status"]
        if status == "draft":
            return True
        if status == "approved":
            return states.get(pause["id"], "pending") not in {"confirmed", "stale", "deviated"}
        if status == "deferred":
            revisit = change_set.get("revisit_at")
            return revisit is None or revisit > now_utc()
        if status == "rejected":
            remembered = (change_set.get("decision_grades") or {}).get(item["entity_id"])
            return bool(remembered and remembered.get("grade") in triage_capacity.GRADE_RANK
                        and remembered.get("cap") == item["target"].get("value")
                        and not triage_capacity.got_worse(remembered, item["grade"]))
        return False
    return False


def _row_review_proposal(rounds_by_entity, sets_by_campaign, action_states, triage_item,
                         creative=None):
    """The `proposal` for one `worse` row (F23-I01, feature Decisions "Queue row state") -- the
    newest applicable round of this entity, including an explicit disposition beyond the rolling
    window. A due revisit or changed semantic conditions releases the disposition. The copy set
    is the newest
    non-superseded set whose `plan_json.review_id` names this round; its `verification_state`
    reads back the matching `copy` item targeting this same entity (reusing the F22 brand-wide
    `sets_by_campaign`/`action_states` maps, never a fresh query per row)."""
    campaign_id, entity_id = triage_item["campaign_id"], triage_item["entity_id"]
    round_ = _matching_review_round(rounds_by_entity, campaign_id, entity_id,
                                    triage_item["window"], sets_by_campaign)
    if round_ is None:
        return None
    change_set = _matching_review_change_set(sets_by_campaign, campaign_id, round_["id"])
    revisit_at = (change_set.get("revisit_at") if change_set and change_set["status"] == "deferred"
                  else round_["revisit_at"])
    if revisit_at is not None and revisit_at <= now_utc():
        return None
    if _review_scope_changed(round_, triage_item, creative, change_set):
        return None
    change_set_id = change_set_status = verification_state = None
    multi = False
    if change_set is not None:
        items = change_set["plan_json"].get("items", ())
        item = next(
            (i for i in items if i.get("kind") == "copy" and i.get("target_id") == entity_id),
            None,
        )
        change_set_id = change_set["id"]
        change_set_status = change_set["status"]
        verification_state = action_states.get(item["id"], "pending") if item else "pending"
        multi = len(items) > 1
    return {
        "kind": "review",
        "review_id": round_["id"],
        "status": round_["status"],
        "decision": round_["decision"],
        "reason": (change_set.get("decision_reason") or round_["reason"]
                   if change_set and change_set["status"] in {"deferred", "rejected"}
                   else round_["reason"]),
        "revisit_at": revisit_at,
        "recommendation_id": _first_adjust_recommendation_id(round_["result_json"]),
        "change_set_id": change_set_id,
        "change_set_status": change_set_status,
        "verification_state": verification_state,
        "verification_label": change_control_data.verification_label(verification_state),
        "multi": multi,
    }


def _matching_change_item(sets_by_campaign, campaign_id, target_id, kind):
    """The newest non-superseded change set of `campaign_id` whose items include a `kind` item
    targeting `target_id`, and that item itself -- `None, None` when there isn't one. Generalised
    by `kind` (F25-I01); since F28-I02 only the `scale_budget` row's budget match
    (`kind="budget"`, the budget owner's `id`) walks it."""
    for change_set in sets_by_campaign.get(campaign_id, ()):
        item = next(
            (i for i in change_set["plan_json"].get("items", ())
             if i.get("kind") == kind and i.get("target_id") == target_id),
            None,
        )
        if item is not None:
            return change_set, item
    return None, None


def _row_scale_proposal(sets_by_campaign, action_states, candidate):
    """The `proposal` for one `scale_budget` row (feature Decisions "Queue payload") -- the
    newest non-superseded change set whose items include a `budget` item targeting this owner,
    (reuses `_matching_change_item`); `None` when there is no matching set, or a `deferred` set
    past its own `revisit_at`, or a `rejected` set whose `created_at` day has fallen outside this
    row's current window."""
    triage_item = candidate["payload"]["triage"]
    change_set, matched_item = _matching_change_item(
        sets_by_campaign, triage_item["campaign_id"], candidate["identity_id"], kind="budget",
    )
    if change_set is None or matched_item is None:
        return None
    verification_state = action_states.get(matched_item["id"], "pending")
    if change_set["status"] == "deferred":
        revisit_at = change_set["revisit_at"]
        if revisit_at is not None and revisit_at <= now_utc():
            return None
    elif change_set["status"] == "rejected":
        created_day = change_set["created_at"].date()
        if not (candidate["window_start"] <= created_day <= candidate["window_end"]):
            return None
    return {
        "change_set_id": change_set["id"], "campaign_id": change_set["campaign_id"],
        "kind": matched_item["kind"], "status": change_set["status"],
        "verification_state": verification_state,
        "verification_label": change_control_data.verification_label(verification_state),
        "reason": change_set["decision_reason"],
        "revisit_at": change_set["revisit_at"],
        "multi": len(change_set["plan_json"].get("items", ())) > 1,
    }


def _matching_cleanup_set(sets_by_campaign, campaign_id):
    """The newest non-superseded change set of `campaign_id` whose `plan_json.source == "cleanup"`
    and that carries at least one `pause` item -- Contract F's own proposal match, never generalised
    through `_matching_change_item` (that helper matches by a single `target_id`; a cleanup set's
    own identity is the campaign, not one ad)."""
    for change_set in sets_by_campaign.get(campaign_id, ()):
        if change_set["plan_json"].get("source") != "cleanup":
            continue
        pause_items = [
            i for i in change_set["plan_json"].get("items", ()) if i.get("kind") == "pause"
        ]
        if pause_items:
            return change_set, pause_items
    return None, None


def _row_cleanup_proposal(sets_by_campaign, action_states, candidate):
    """The `proposal` for one `cleanup` row (Contract F) -- same shape `_row_scale_proposal`
    reports, `kind` always `"cleanup"` and `multi` always `True`
    (a cleanup set is inherently the multi-item kind, never computed from item count). A cleanup
    set carries several `pause` items (one per proposed ad); `verification_state` reads
    `"confirmed"` only once every one of them does, else the worst state present -- F49 Contract
    B's one aggregate (`change_control_data.worst_state`, the same one `handoff_check` uses)."""
    change_set, pause_items = _matching_cleanup_set(sets_by_campaign, candidate["identity_id"])
    if change_set is None or pause_items is None:
        return None
    verification_state = change_control_data.worst_state(
        action_states.get(item["id"], "pending") for item in pause_items
    )
    if change_set["status"] == "deferred":
        revisit_at = change_set["revisit_at"]
        if revisit_at is not None and revisit_at <= now_utc():
            return None
    elif change_set["status"] == "rejected":
        # F29-I01 Contract B: a rejection that left a memory is owned by that memory -- a row
        # raised again (an ad got worse, or a different ad is now proposed) is a fresh proposal.
        # A legacy rejection (no memory) keeps the window rule.
        if change_set.get("decision_grades") is not None:
            return None
        created_day = change_set["created_at"].date()
        if not (candidate["window_start"] <= created_day <= candidate["window_end"]):
            return None
    elif verification_state == "confirmed":
        # F28-I02: carried over from the retired stop-loss proposal -- a confirmed pause whose ad
        # is active again (it is back in this row's close list, and `classify()` only judges
        # active ads) needs a fresh proposal, never the old "done" one. F29-I01: same for an ad
        # the user unticked in that set that has since got worse (it re-entered the close list).
        closing = {ad["entity_id"] for ad in candidate["payload"]["cleanup"]["ads"]}
        declined = set(change_set["plan_json"].get("declined_ids") or ())
        if any(item.get("target_id") in closing for item in pause_items) or closing & declined:
            return None
    return {
        "change_set_id": change_set["id"], "campaign_id": change_set["campaign_id"],
        "kind": "cleanup", "status": change_set["status"],
        "verification_state": verification_state,
        "verification_label": change_control_data.verification_label(verification_state),
        "reason": change_set["decision_reason"],
        "revisit_at": change_set["revisit_at"], "multi": True,
    }


def _trend_counts(items) -> dict:
    """The trend-note tally (`counts`, one per `class`) -- the only reader of `class` outside the
    note builder `_classify_ad`, display only; no decision reads it (ads.md §6.33, enforced by
    `app/tests/test_ads_one_ruler.py`)."""
    counts = dict.fromkeys(ALL_CLASSES, 0)
    for item in items:
        counts[item["class"]] += 1
    return counts


def _notice_row(org_id, brand_id, candidate) -> dict:
    """F49 Contract Q: a notice (`queue_done.NOTICE_KINDS`) is served from its candidate, never an
    interrupt -- the same columns an interrupt row carries, `id` = its dedupe key."""
    category = QUEUE_CATEGORY[candidate["kind"]]
    return {
        "id": candidate["key"], "org_id": org_id, "brand_id": brand_id,
        "campaign_period_id": None, "dedupe_key": candidate["key"], "category": category,
        "kind": None, "severity": interrupts.CATEGORIES[category]["severity"],
        "message": candidate["message"], "action_url": candidate["action_url"],
        "visible_from": None, "status": "open", "created_at": None, "resolved_at": None,
    }


def _queue_payload(conn, org_id, brand_id, items, candidates, holds=()) -> dict:
    """The served queue: every decision candidate with an open interrupt (its key, F49 Contract
    Q), in the inbox's order, then every notice built from its candidate. Each row carries its
    current triage item (F19-I01; `None` on the brand's settle row and a closeout row), the
    candidate's extra payload (`scale`／`refresh`／`insufficient`／`cleanup`／`settle`／`closeout`),
    its `campaign_id` and its `proposal`; `queue_done.stamp` adds `decision`, `done` and
    `position` and gives the payload's `decisions {kinds, open}` -- the one count every screen
    reads. The frontend never parses `dedupe_key` strings itself."""
    decision_by_key = {
        c["key"]: c for c in candidates if c["kind"] in queue_done.DECISION_KINDS
    }
    queue_categories = set(QUEUE_CATEGORY.values())
    # archive_stale=False: this is a read inside a read-only path too (`get_queue`), and
    # `refresh_queue` already committed its own writes above -- neither call should also trigger
    # the unrelated informational-archival side effect of `list_open(archive_stale=True)`.
    listed = [
        (row, decision_by_key[row["dedupe_key"]])
        for row in interrupts.list_open(conn, org_id=org_id, brand_id=brand_id,
                                        archive_stale=False)
        if row["category"] in queue_categories and row["dedupe_key"] in decision_by_key
    ]
    listed.extend(
        (_notice_row(org_id, brand_id, c), c)
        for c in candidates if c["kind"] in queue_done.NOTICE_KINDS
    )
    listed_keys = {row["dedupe_key"] for row, _ in listed}
    listed.extend(
        ({**_notice_row(org_id, brand_id, c), "status": "resolved"}, c)
        for c in candidates if c["kind"] == "worse" and c["key"] not in listed_keys
        and queue_done.done({"kind_key": "worse", "proposal": c.get("proposal")})
    )
    sets_by_campaign = _brand_change_sets_by_campaign(conn, org_id, brand_id)
    action_states = _brand_action_verification_states(conn, org_id, brand_id)
    # F23-I01: `worse` rows' own proposal -- the matching review round (if any), brand-wide.
    open_rows = []
    for row, candidate in listed:
        kind = candidate["kind"]
        triage_item = candidate["payload"]["triage"]
        if kind == "worse":
            proposal = candidate["proposal"]
        elif kind == "scale_budget":
            proposal = _row_scale_proposal(sets_by_campaign, action_states, candidate)
        elif kind == "cleanup":
            proposal = _row_cleanup_proposal(sets_by_campaign, action_states, candidate)
        else:
            # refresh_creative/insufficient_data/settle/closeout: no change set -- the row's own
            # button goes elsewhere (the workbench / the wait page / the settle page / closeout).
            proposal = None
        extra = {k: v for k, v in candidate["payload"].items() if k != "triage"}
        open_rows.append({
            **row, "kind_key": kind, "campaign_id": candidate["campaign_id"],
            "triage": triage_item, **extra, "proposal": proposal,
        })
    # F47 Contract D, F49 Contract Q: the one owner of done-ness and of "which rows count"
    # (`queue_done`), read by the top bar, the home list, 「第 N 件／共 M 件」 and 「下一件」 alike.
    decisions = queue_done.stamp(open_rows)
    return {
        "items": open_rows, "counts": _trend_counts(items), "total_ads": len(items),
        "kinds_available": KINDS_AVAILABLE, "kinds_pending": KINDS_PENDING,
        "scale_hold": list(holds), "decisions": decisions,
    }
