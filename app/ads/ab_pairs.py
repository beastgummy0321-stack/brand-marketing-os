"""app/ads/ab_pairs.py — F29-I04 Contract F: automatic A/B pairs on real data.

Every qualifying pair of an internal campaign (`experiments.pairs`: same group, audience and
product, exactly one coordinate different) is judged without a plan confirmation (Unresolved 3):
the window runs from the later ad's first delivery day to the last complete day, with the fixed
7-day / 10-each / 10% thresholds and the same judge core as the confirmed comparison
(`experiments.evaluate`). The old "group hit its daily budget" stop does not apply here -- real
delivery spends the full daily budget every day. Known days follow triage's convention: for real
rows, a day inside the campaign's recorded sync coverage with no row is a zero-delivery day; a
day outside coverage is missing and makes the pair `unreadable` (the days are named). An untracked
purchase count is never a 0 either.

A judged pair can propose pausing the loser through the normal approval flow
(`change_control.create_ab`, `source: "ab"`); nothing here writes to a platform. Imported
campaigns have no coordinates, so no pairs.
"""

from datetime import timedelta

from app.ads import (
    ads_learnings,
    change_control,
    coverage,
    experiments,
    live_creative,
    outcome,
    repository,
    triage,
)
from app.core import settings

# The ruler's thresholds through `experiments.DEFAULT_RULES` (F48 Contract R: `triage` constants).
RULES = {
    "min_days": experiments.DEFAULT_RULES["min_days"],
    "min_conversions_each": experiments.DEFAULT_RULES["min_conversions_each"],
    "relative_difference": experiments.DEFAULT_RULES["relative_difference"],
}
IMPORTED_REASON = "匯入的活動沒有廣告座標，無法自動配對 A/B 比較。"
_UNREADABLE = {"missing_days", "untracked", "zero_spend"}


class PairUnknown(ValueError):
    pass


class NotJudged(ValueError):
    pass


class LoserUnbound(ValueError):
    pass


def pair_id(a_id: str, b_id: str) -> str:
    return ":".join(sorted((a_id, b_id)))


def _entities(conn, org, brand, campaign_id, ads):
    """`ads_ad.id -> ads_external_entity` for each ad bound to exactly one platform ad of this
    campaign (`ads_ad.external_id` = the entity's `native_id`, written when the handoff reads the
    ad back). Unbound or ambiguous -> absent."""
    external_ids = {ad["id"]: ad["external_id"] for ad in ads if ad.get("external_id")}
    if not external_ids:
        return {}
    by_native = {}
    for row in conn.execute(
        "SELECT * FROM ads_external_entity WHERE org_id=%s AND brand_id=%s AND campaign_id=%s "
        "AND native_kind='ad' AND native_id = ANY(%s)",
        (org, brand, campaign_id, sorted(set(external_ids.values()))),
    ).fetchall():
        by_native.setdefault(row["native_id"], []).append(dict(row))
    return {
        ad_id: by_native[native][0]
        for ad_id, native in external_ids.items()
        if len(by_native.get(native, [])) == 1
    }


def _outcome_rows(conn, org, brand, campaign_id, ad_ids, last_day):
    """The ad-grain performance rows (`outcome.rows`, Contract P) of `ad_ids` up to `last_day`."""
    wanted = set(ad_ids)
    return [
        row for row in outcome.rows(conn, org, brand, campaign_id, "ad")
        if row["entity_id"] in wanted and row["day"] <= last_day
    ]


def _decisions(conn, org, brand, campaign_id):
    """`pair_id -> {change_set_id, status, verification_state}` from each pair's newest `ab`
    set. `verification_state` is the pause item's; null before approval."""
    decisions = {}
    for row in conn.execute(
        "SELECT s.id, s.status, s.plan_json->'ab'->>'pair_id' AS pair_id, "
        "(SELECT a.verification_state FROM ads_action a WHERE a.org_id=s.org_id "
        "AND a.change_set_id=s.id ORDER BY a.id LIMIT 1) AS verification_state "
        "FROM ads_change_set s WHERE s.org_id=%s AND s.brand_id=%s AND s.campaign_id=%s "
        "AND s.plan_json->>'source'='ab' ORDER BY s.created_at, s.id",
        (org, brand, campaign_id),
    ).fetchall():
        decisions[row["pair_id"]] = {
            "change_set_id": row["id"], "status": row["status"],
            "verification_state": row["verification_state"],
        }
    return decisions


def _first_row_day(rows, default):
    """The earliest day of `rows` (the span the day states are loaded over), else `default`."""
    return min((r["day"] for r in rows), default=default)


def _first_delivery(rows, ad_id, last_day):
    days = [
        r["day"] for r in rows
        if r["entity_id"] == ad_id and r["day"] <= last_day
        and r["spend"] is not None and float(r["spend"]) > 0
    ]
    return min(days) if days else None


def _side(ad, value_label, entity, total):
    results = total["purchases"] if total else None
    spend = total["spend"] if total else None
    return {
        "ad_id": ad["id"],
        "entity_id": entity["id"] if entity else None,
        "name": ad["name"],
        "value_label": value_label,
        "thumbnail_url": triage._thumbnail_url(entity) if entity else None,
        "spend": spend,
        "results": int(results) if results is not None else None,
        "cost_per_result": spend / results if spend is not None and results else None,
    }


def _missing(days, sides):
    def need(side):
        if side["results"] is None:
            return None
        return max(0, RULES["min_conversions_each"] - side["results"])

    return {
        "days": max(0, RULES["min_days"] - days),
        "a_results": need(sides[0]),
        "b_results": need(sides[1]),
    }


# The `source` of simulated delivery rows (`adapters/simulated.py`).
_SIMULATED_SOURCE = "simulated"


def _window_days(start, end):
    return [start + timedelta(days=i) for i in range((end - start).days + 1)]


def _covered_zero_rows(rows, ad_ids, start, end, read):
    """Lead ruling (F29-I04): the known-days convention of triage (`read` = `coverage.load`, F49
    Contract V). For a real ad (none of its rows is simulated), a day inside one of the
    campaign's recorded clean read ranges with no row of this ad is a tracked zero-delivery day
    (spend 0, results 0); any other day stays missing -- another ad's row proves its own day was
    read, not that this ad's rows of it arrived (`Days.cleanly_read`). Simulated ads are never
    padded. An untracked (NULL) purchase count on an existing row is untouched -- never 0."""
    padded = []
    for ad_id in ad_ids:
        own = [r for r in rows if r["entity_id"] == ad_id]
        # Platform-neutral (§0「不預設」): only the simulated source is named; a padded day carries
        # the ad's own existing source, never a platform literal.
        if not own or any(r["source"] == _SIMULATED_SOURCE for r in own):
            continue
        source = own[0]["source"]
        present = {r["day"] for r in own}
        padded.extend(
            {"entity_id": ad_id, "day": day, "spend": 0, "purchases": 0, "revenue": None,
             "source": source}
            for day in _window_days(start, end)
            if day not in present and read.cleanly_read(day, day)
        )
    return padded


def _gaps(rows, ad_ids, start, end):
    """The window days with no row for at least one side, oldest first (ISO dates)."""
    present = {(r["entity_id"], r["day"]) for r in rows}
    return [
        day.isoformat() for day in _window_days(start, end)
        if any((ad_id, day) not in present for ad_id in ad_ids)
    ]


def _judge_pair(group, a, b, dimension, labels, entities, rows, last_day, decision, read):
    dimension_label = experiments.DIMENSIONS[dimension]
    values = [labels.get((dimension, ad[f"{dimension}_key"]), ad[f"{dimension}_key"])
              for ad in (a, b)]
    first_a, first_b = (_first_delivery(rows, ad["id"], last_day) for ad in (a, b))
    base = {
        "pair_id": pair_id(a["id"], b["id"]), "group_id": group["id"],
        "group_name": group["name"], "dimension": dimension, "dimension_label": dimension_label,
        "rules": dict(RULES), "winner": None, "difference_pct": None, "decision": decision,
    }
    if first_a is None or first_b is None:
        sides = [_side(ad, v, entities.get(ad["id"]), None) for ad, v in zip((a, b), values,
                                                                                strict=True)]
        return {
            **base, "a": sides[0], "b": sides[1], "window": None, "days": 0,
            "state": "collecting",
            "missing": {"days": RULES["min_days"], "a_results": RULES["min_conversions_each"],
                        "b_results": RULES["min_conversions_each"]},
            "reason": "兩則廣告都開始投放後，才開始比較。",
        }
    start = max(first_a, first_b)
    days = (last_day - start).days + 1
    rows = rows + _covered_zero_rows(rows, (a["id"], b["id"]), start, last_day, read)
    core = experiments.evaluate(rows, [a["id"], b["id"]], start, last_day, RULES, "cpa")
    sides = [
        _side(ad, v, entities.get(ad["id"]), total)
        for ad, v, total in zip((a, b), values, core["totals"], strict=True)
    ]
    result = {
        **base, "a": sides[0], "b": sides[1],
        "window": {"start": start.isoformat(), "end": last_day.isoformat()}, "days": days,
        "missing": _missing(days, sides), "reason": core["reason"],
    }
    if core["state"] == "missing_days":
        gaps = _gaps(rows, (a["id"], b["id"]), start, last_day)
        return {**result, "state": "unreadable",
                "reason": f"缺 {'、'.join(gaps)} 的資料；缺資料不當成零。"}
    if core["state"] in _UNREADABLE:
        return {**result, "state": "unreadable"}
    if core["state"] in {"short", "thin"}:
        return {**result, "state": "collecting"}
    difference_pct = round(core["difference"] * 100, 1)
    if core["state"] == "no_difference":
        return {**result, "state": "no_difference", "difference_pct": difference_pct}
    winner = "a" if core["winner"] == 0 else "b"
    win, lose = (sides[0], sides[1]) if winner == "a" else (sides[1], sides[0])
    return {
        **result, "state": "judged", "winner": winner, "difference_pct": difference_pct,
        "reason": f"「{dimension_label}」用「{win['value_label']}」比「{lose['value_label']}」"
        f"每次轉換成本低 {difference_pct:g}%；{core['reason']}",
    }


def read(conn, org, brand, campaign_id) -> dict:
    """`GET …/campaigns/{c}/ab-pairs` (Contract F): `{pairs, unavailable}`. Pure reads."""
    detail = repository.campaign_detail(conn, org, brand, campaign_id)
    if detail is None:
        raise ValueError("找不到這個活動。")
    if detail.get("origin") == "imported":
        return {"pairs": [], "unavailable": IMPORTED_REASON}
    # F31-I05 Contract O: pair on the coordinates each creative was made for.
    detail = live_creative.with_learning_coordinates(conn, org, brand, detail)
    found = list(experiments.pairs(detail))
    if not found:
        return {"pairs": [], "unavailable": None}
    labels = {
        (v["dimension"], v["key"]): v["label"]
        for v in repository.coordinate_vocabulary(conn, org, brand)
    }
    ads = [ad for group in detail["groups"] for ad in group["ads"]]
    entities = _entities(conn, org, brand, campaign_id, ads)
    yesterday = coverage.last_complete_day(conn, org, brand, campaign_id)
    rows = _outcome_rows(conn, org, brand, campaign_id, [ad["id"] for ad in ads], yesterday)
    decisions = _decisions(conn, org, brand, campaign_id)
    read = coverage.load(conn, org, brand, detail, _first_row_day(rows, yesterday), yesterday)
    pairs = []
    for group, a, b, dimension in found:
        end = group.get("end_date") or detail.get("end_date")
        last_day = min(yesterday, end) if end else yesterday
        pairs.append(_judge_pair(
            group, a, b, dimension, labels, entities, rows, last_day,
            decisions.get(pair_id(a["id"], b["id"])), read,
        ))
    return {"pairs": pairs, "unavailable": None}


def _ab_side(side):
    return {k: side[k] for k in ("ad_id", "entity_id", "name", "value_label", "cost_per_result")}


def pause_loser(conn, org, brand, campaign_id, pid, operation_id, actor) -> dict:
    """`POST …/ab-pairs/{pair_id}/pause-loser` (Contract F): an open set for the pair is returned
    as it is; otherwise a judged pair with a bound loser becomes one `ab` change set with one
    pause item on the loser's platform ad, through the same create/approve flow as any set."""
    pair = next((p for p in read(conn, org, brand, campaign_id)["pairs"]
                 if p["pair_id"] == pid), None)
    if pair is None:
        raise PairUnknown("找不到這組 A/B 比較。")
    existing = change_control.open_ab_set(conn, org, brand, campaign_id, pid)
    if existing is not None:
        return existing
    if pair["state"] != "judged":
        raise NotJudged("這組比較還沒分出較划算的一則，不能暫停。")
    win, lose = (pair["a"], pair["b"]) if pair["winner"] == "a" else (pair["b"], pair["a"])
    if not lose["entity_id"]:
        raise LoserUnbound("較貴的那一則還沒對應到平台上的廣告，無法建立暫停清單。")
    ab = {
        "pair_id": pid, "dimension_label": pair["dimension_label"], "winner": _ab_side(win),
        "loser": _ab_side(lose), "window": pair["window"],
    }
    detail = repository.campaign_detail(conn, org, brand, campaign_id)
    if detail is None:
        raise PairUnknown("找不到這組 A/B 比較的活動。")
    detail = live_creative.with_learning_coordinates(conn, org, brand, detail)
    members = [ad for group in detail["groups"] for ad in group["ads"]
               if ad["id"] in {win["ad_id"], lose["ad_id"]}]
    observations = outcome.select_period(outcome.rows(conn, org, brand, campaign_id, "ad"),
                                         pair["window"])
    observations = [r for r in observations if r["entity_id"] in {a["id"] for a in members}]
    # Both sides are retained: a pause receipt cannot certify the market comparison.
    ab["evidence"] = ads_learnings.source_evidence(
        conn, org, brand, detail, kind="ab", window=pair["window"], members=members,
        observations=observations, claim_key="comparison:" + ads_learnings.semantic_version({
            "dimension": pair["dimension"], "winner": next(
                a.get(f"{pair['dimension']}_key") for a in members if a["id"] == win["ad_id"]),
            "loser": next(a.get(f"{pair['dimension']}_key") for a in members
                          if a["id"] == lose["ad_id"]), "messages": sorted(
                ads_learnings.message_claim(a) or "unknown" for a in members),
        }), direction="support", trial_id=campaign_id,
    )
    counts = [sum(float(r["result_count"]) for r in observations
                  if r["entity_id"] == a["id"] and r.get("result_count") is not None)
              for a in members]
    ab["evidence"]["sample"]["result_events"] = min(counts, default=None)
    month = settings.today_for_org(conn, org_id=org).strftime("%Y-%m")
    payload = {
        "operation_id": operation_id,
        "title": f"暫停 A/B 比較中較貴的一則：{lose['name']}"[:200],
        "month": month,
        "items": [{
            "kind": "pause", "target_id": lose["entity_id"], "after": {"status": "PAUSED"},
            "reason": (f"A/B 比較：「{pair['dimension_label']}」用「{win['value_label']}」"
                       f"比「{lose['value_label']}」划算，暫停較貴的一則。")[:2000],
        }],
    }
    return change_control.create_ab(conn, org, brand, campaign_id, payload, ab, actor)
