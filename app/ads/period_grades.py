"""app/ads/period_grades.py — F29-I01 Contract A: every ad that spent inside a date window, graded
by the one cap ruler (`triage.grade_window`, ads.md §6.33 "One ruler") against its own campaign's
cap. Shared by the month review (Contract C) and the period settle (Contract E), so step 1 of a
settle equals the month review of that month. Pure reads: no LLM call, no platform write.

The window's numbers are cut the same way triage cuts its own windows (`triage._ad_window`: the
ad's own NULL-aware spend, one result view, two currencies = unknown), graded by the same ruler,
and carry the same shown `sample` (F48 Contract R: sample size is a flag, never a gate). Unknown
stays unknown: a window whose spend or result can't be known reads 資料不足 with
`spend`/`results` null, never 0.
"""

from collections import defaultdict

from app.ads import coverage, targets, triage

# Display order of the buckets (Contract C): 划算, 偏貴, 太貴, 沒賣出, then the ungraded ones.
BUCKET_ORDER = ("on_target", "watch", "over", "wasted", "insufficient", "no_target")


def _spent(rows) -> bool:
    return any(row["spend"] is not None and float(row["spend"]) > 0 for row in rows)


def _currency(rows):
    currencies = {row["currency"] for row in rows}
    return next(iter(currencies)) if len(currencies) == 1 else None


def _grade(view, spend, target, days):
    """`(grade, grade_label, reason_code)` -- the triage item's own three fields."""
    # Same "no result kind anywhere" rule triage applies on its first window -- never judged.
    if target["value"] is not None and target["result_kind"] is None \
            and (view is None or view["result_kind"] is None):
        return "no_target", triage.GRADE_LABELS["no_target"], "result_kind_unknown"
    return triage.grade_window(view, spend, target["value"], days)


def grade_period(conn, org_id, brand_id, start, end) -> list[dict]:
    """One row per ad with spend in `[start, end]` (active or closed, any campaign of this brand):
    `{campaign_id, campaign_name, origin, entity_id, name, group_name, thumbnail_url, spend,
    results, cost_per_result, cap, break_even, grade, grade_label, reason_code, sample, currency}`.
    `reason_code`/`sample` have the triage item's shapes (F48). `currency` is the ad's own single
    currency in the window (null across two). Ordered by campaign name, then ad
    name. Three reads for the whole brand plus one cap resolve per campaign -- never per ad."""
    rows_by_entity = defaultdict(list)
    for row in conn.execute(
        "SELECT * FROM ads_external_daily WHERE org_id=%s AND brand_id=%s AND metric_scope='ad' "
        "AND day BETWEEN %s AND %s",
        (org_id, brand_id, start, end),
    ).fetchall():
        rows_by_entity[row["entity_id"]].append(dict(row))
    spent_ids = [eid for eid, rows in rows_by_entity.items() if _spent(rows)]
    if not spent_ids:
        return []
    entities = {
        row["id"]: dict(row)
        for row in conn.execute(
            "SELECT * FROM ads_external_entity WHERE org_id=%s AND brand_id=%s "
            "AND native_kind='ad' AND id = ANY(%s)",
            (org_id, brand_id, spent_ids),
        ).fetchall()
    }
    campaign_ids = sorted({entity["campaign_id"] for entity in entities.values()})
    campaigns = {
        row["id"]: dict(row)
        for row in conn.execute(
            "SELECT * FROM ads_campaign WHERE org_id=%s AND brand_id=%s AND id = ANY(%s)",
            (org_id, brand_id, campaign_ids),
        ).fetchall()
    }
    group_names = {
        (row["campaign_id"], row["native_id"]): row["name"]
        for row in conn.execute(
            "SELECT campaign_id,native_id,name FROM ads_external_entity WHERE org_id=%s "
            "AND brand_id=%s AND native_kind='adset' AND campaign_id = ANY(%s)",
            (org_id, brand_id, campaign_ids),
        ).fetchall()
    }
    days = (end - start).days + 1
    target_by_campaign = {}
    out = []
    for entity_id in spent_ids:
        entity = entities.get(entity_id)
        if entity is None:
            continue
        campaign = campaigns.get(entity["campaign_id"])
        if campaign is None:
            continue
        if campaign["id"] not in target_by_campaign:
            target_by_campaign[campaign["id"]] = targets.resolve(conn, org_id, brand_id, campaign)
        target = target_by_campaign[campaign["id"]]
        entity_rows = rows_by_entity[entity_id]
        view, spend = triage._ad_window(entity_rows, start, end)
        grade, label, reason_code = _grade(view, spend, target, days)
        group_name = (
            group_names.get((campaign["id"], entity.get("parent_native_id")))
            if entity.get("parent_native_kind") == "adset" else None
        )
        out.append({
            "campaign_id": campaign["id"], "campaign_name": campaign["name"],
            "origin": campaign["origin"], "entity_id": entity_id, "name": entity.get("name"),
            "group_name": group_name, "thumbnail_url": triage._thumbnail_url(entity),
            "spend": spend,
            "results": view["result_count"] if view is not None else None,
            "cost_per_result": view["cost_per_result"] if view is not None else None,
            "cap": target["value"], "break_even": target.get("break_even"),
            "grade": grade, "grade_label": label, "reason_code": reason_code,
            "sample": triage._sample_view(spend, view, target["value"], days),
            "currency": _currency(entity_rows),
        })
    out.sort(key=lambda row: (row["campaign_name"] or "", row["name"] or "", row["entity_id"]))
    return out


def _known_sum(rows):
    """Sum of `spend` -- null when any is unknown or the rows span two currencies (never a partial
    sum, never a sum across currencies)."""
    if not rows or any(row["spend"] is None for row in rows):
        return None
    if len({row["currency"] for row in rows}) != 1 or rows[0]["currency"] is None:
        return None
    return sum(row["spend"] for row in rows)


def summarize(rows) -> dict:
    """`{spent, buckets}` over `grade_period` rows (Contract C): `spent` null unless every ad's
    spend is known in one currency; one bucket per grade in `BUCKET_ORDER`, empty ones included."""
    buckets = []
    for grade in BUCKET_ORDER:
        members = [row for row in rows if row["grade"] == grade]
        buckets.append({
            "grade": grade, "amount": _known_sum(members) if members else 0, "count": len(members),
            "ads": [
                {"entity_id": row["entity_id"], "name": row["name"],
                 "thumbnail_url": row["thumbnail_url"], "spend": row["spend"]}
                for row in members
            ],
        })
    return {"spent": _known_sum(rows), "buckets": buckets}


def missing(conn, org_id, brand_id, start, end) -> list[dict]:
    """Per campaign that delivered inside `[start, end]`: the days (from its first delivered day in
    the window to the last complete day, clipped to the campaign's own dates) nobody read --
    `coverage.load` (F49 Contract V): a day with a row, or inside a clean read range with no row
    (synced, simply no delivery), is read. `[{campaign_id, name, missing_days}]`, only campaigns
    with at least one."""
    days_by_campaign = defaultdict(set)
    for row in conn.execute(
        "SELECT DISTINCT campaign_id,day FROM ads_external_daily WHERE org_id=%s AND brand_id=%s "
        "AND metric_scope='ad' AND day BETWEEN %s AND %s",
        (org_id, brand_id, start, end),
    ).fetchall():
        days_by_campaign[row["campaign_id"]].add(row["day"])
    if not days_by_campaign:
        return []
    campaigns = {
        row["id"]: dict(row)
        for row in conn.execute(
            "SELECT * FROM ads_campaign WHERE org_id=%s AND brand_id=%s AND id = ANY(%s)",
            (org_id, brand_id, sorted(days_by_campaign)),
        ).fetchall()
    }
    out = []
    for campaign_id in sorted(days_by_campaign):
        campaign = campaigns.get(campaign_id)
        if campaign is None:
            continue
        first = min(days_by_campaign[campaign_id])
        last = min(end, triage._account_cutoff(conn, org_id, brand_id, campaign_id))
        gaps = (
            coverage.load(conn, org_id, brand_id, campaign, first, last).missing(
                first, last, cap=None,
            ) if first <= last else []
        )
        if gaps:
            out.append({"campaign_id": campaign_id, "name": campaign["name"], "missing_days": gaps})
    return out
