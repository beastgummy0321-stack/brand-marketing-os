"""Pure qualification of ledger evidence against explicitly supplied current conditions."""

import hashlib
import json
import math
from datetime import date
from typing import cast

_MARKER = "\n@evidence-v1:"
_REFS = ("campaign_id", "ad_id", "action_id", "entity_id", "trial_id")
_SCOPE = (
    "product_id",
    "audience_key",
    "customer_group_id",
    "claim_key",
    "claim_family",
    "objective_family",
    "result_kind",
    "currency",
    "attribution",
)
_CONDITIONS = (
    "price_version",
    "offer_key",
    "offer_version",
    "material_version",
    "target_version",
    "valid_until",
)
_REASONS = {
    "scope_required": "請先選擇商品範圍",
    "other_product": "這是其他商品的經驗",
    "unknown_source": "來源尚未核實，保留為歷史",
    "conditions_unknown": "適用條件尚未核實",
    "condition_changed": "適用條件已改變，需重新核對",
    "offer_ended": "優惠已結束",
    "measurement_stale": "成效期間已過，需要重新核對",
    "superseded": "已有較新的期間結論",
    "insufficient_sample": "樣本少，只能作為測試或對照",
    "simulated": "演練資料不能當市場成效",
    "operation_only": "僅證明操作已核對",
    "contradictory_result": "較新可比結果方向不同",
}


def _hash(value):
    return hashlib.sha256(
        json.dumps(
            value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), default=str
        ).encode()
    ).hexdigest()


def base_learning_scope(scope):
    """Return the exact legacy scope, even when its additive trailer is malformed."""
    return (scope or "").split(_MARKER, 1)[0]


def _scalar(value):
    return value if isinstance(value, str) and value else None


def _normalized(raw, row):
    raw = raw if isinstance(raw, dict) else {}
    scope = cast(dict, raw.get("scope")) if isinstance(raw.get("scope"), dict) else {}
    conditions = (
        cast(dict, raw.get("conditions")) if isinstance(raw.get("conditions"), dict) else {}
    )
    ref = cast(dict, raw.get("source_ref")) if isinstance(raw.get("source_ref"), dict) else {}
    period = cast(dict, raw.get("period")) if isinstance(raw.get("period"), dict) else {}
    sample = cast(dict, raw.get("sample")) if isinstance(raw.get("sample"), dict) else {}
    events = sample.get("result_events")
    if (
        isinstance(events, bool)
        or not isinstance(events, (int, float))
        or not math.isfinite(events)
        or events < 0
    ):
        events = None
    provenance = raw.get("provenance")
    if provenance not in {
        "platform_observation",
        "user_report",
        "operation_readback",
        "simulation",
        "unknown",
    }:
        provenance = "unknown"
    kind = raw.get("source_kind")
    if kind not in {"campaign", "pause", "ab", "settle", "coordinate", "visual"}:
        kind = None
    normalized_scope = {key: _scalar(scope.get(key)) for key in _SCOPE}
    if normalized_scope["claim_family"] not in {"performance", "brand_fact", "operation"}:
        normalized_scope["claim_family"] = None
    return {
        "schema_version": 1,
        "source_kind": kind,
        "source_ref": {key: _scalar(ref.get(key)) for key in _REFS},
        "source_version": _scalar(raw.get("source_version")),
        "provenance": provenance,
        "period": {key: _scalar(period.get(key)) for key in ("start", "end")},
        "scope": normalized_scope,
        "conditions": {key: _scalar(conditions.get(key)) for key in _CONDITIONS},
        "sample": {"result_events": events, "sufficient": None},
        "direction": raw.get("direction")
        if raw.get("direction") in {"support", "contrary", "inconclusive"}
        else "inconclusive",
        "limits": sorted({v for v in raw.get("limits", []) if isinstance(v, str)})
        if isinstance(raw.get("limits"), list)
        else [],
    }


def encode_learning_scope(base_scope, evidence):
    """Serialize one canonical trailer while preserving the exact base scope."""
    value = _normalized(evidence, {})
    sample = (evidence or {}).get("sample") or {}
    value["sample"]["sufficient"] = (
        sample.get("sufficient") if isinstance(sample.get("sufficient"), bool) else None
    )
    return (
        base_learning_scope(base_scope)
        + _MARKER
        + json.dumps(
            value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False
        )
    )


def _decode(row):
    text = row.get("applicability_scope") or ""
    try:
        raw = json.loads(text.split(_MARKER, 1)[1])
        if (
            not isinstance(raw, dict)
            or type(raw.get("schema_version")) is not int
            or raw.get("schema_version") != 1
        ):
            raw = {}
    except (ValueError, IndexError, TypeError):
        raw = {}
    normalized = _normalized(raw, row)
    if normalized["scope"]["product_id"] is None:
        normalized["scope"]["product_id"] = _scalar(row.get("product_id"))
    return normalized


def _day(value):
    try:
        return date.fromisoformat(str(value))
    except (ValueError, TypeError):
        return None


def _pair(value, kind):
    """Decode the private two-side carrier; partial or unknown versions never certify it."""
    if not isinstance(value, str) or not value.startswith("@pair-v1:"):
        return None
    try:
        sides = json.loads(value.removeprefix("@pair-v1:"))
    except (ValueError, TypeError):
        return None
    keys = (
        {"side", "ad_id", "version"}
        if kind == "material"
        else {"side", "key", "version", "valid_until"}
    )
    if not isinstance(sides, list) or len(sides) != 2:
        return None
    for side in sides:
        if not isinstance(side, dict) or set(side) != keys or not _scalar(side.get("side")):
            return None
        if kind == "material":
            if not _scalar(side.get("ad_id")) or not _scalar(side.get("version")):
                return None
        elif (
            not _scalar(side.get("key"))
            or (side["key"] != "none" and not _scalar(side.get("version")))
            or (side["valid_until"] is not None and not _day(side["valid_until"]))
        ):
            return None
    if sides[0]["side"] == sides[1]["side"]:
        return None
    return sorted(sides, key=lambda side: side["side"])


def _cohort_conditions(conditions):
    """A carried ad is the same content; retain each canonical side's material/offer relation."""
    material = _pair(conditions["material_version"], "material")
    offers = _pair(conditions["offer_key"], "offer")
    return {
        **conditions,
        "material_version": [{k: v for k, v in side.items() if k != "ad_id"} for side in material]
        if material
        else conditions["material_version"],
        "offer_key": offers if offers else conditions["offer_key"],
    }


def _pair_conditions(old, now, current):
    material = _pair(old["material_version"], "material")
    offers = _pair(old["offer_key"], "offer")
    if not material or not offers or [s["side"] for s in material] != [s["side"] for s in offers]:
        return ["conditions_unknown"]
    reasons = []
    for side in material:
        match = next((m for m in now.get("materials", []) if m.get("ad_id") == side["ad_id"]), {})
        reasons.append(
            "conditions_unknown"
            if not match.get("version")
            else "condition_changed"
            if match["version"] != side["version"]
            else ""
        )
    for side in offers:
        if side["key"] == "none":
            continue
        match = next((o for o in now.get("offers", []) if o.get("key") == side["key"]), {})
        reasons.append(
            "condition_changed"
            if not match
            else "conditions_unknown"
            if not match.get("version")
            else "condition_changed"
            if match["version"] != side["version"]
            else ""
        )
        ends = [_day(value) for value in (side["valid_until"], match.get("valid_until")) if value]
        today = _day(current.get("org_day"))
        if any(end and today and end < today for end in ends):
            reasons.append("offer_ended")
        if match.get("valid_until") and not _day(match["valid_until"]):
            reasons.append("conditions_unknown")
    return reasons


def _conditions(evidence, current):
    old, now = evidence["conditions"], current.get("conditions") or {}
    reasons = []
    if evidence["scope"]["claim_family"] is None:
        reasons.append("conditions_unknown")
    for key in ("price_version", "target_version"):
        if old[key] is not None:
            reasons.append(
                "conditions_unknown"
                if not now.get(key)
                else "condition_changed"
                if old[key] != now[key]
                else ""
            )
    paired = any(
        str(old[key] or "").startswith("@pair-") for key in ("material_version", "offer_key")
    )
    if paired:
        reasons.extend(_pair_conditions(old, now, current))
    offer = old["offer_key"]
    if not paired and offer and offer != "none":
        match = next((o for o in now.get("offers", []) if o.get("key") == offer), None)
        if match is None:
            reasons.append("condition_changed")
        elif old["offer_version"] is None or match.get("version") is None:
            reasons.append("conditions_unknown")
        elif old["offer_version"] != match["version"]:
            reasons.append("condition_changed")
        end = _day((match or {}).get("valid_until") or old["valid_until"])
        today = _day(current.get("org_day"))
        if end and today and end < today:
            reasons.append("offer_ended")
    if not paired and old["material_version"]:
        ad = evidence["source_ref"]["ad_id"]
        match = next((m for m in now.get("materials", []) if m.get("ad_id") == ad), None)
        reasons.append(
            "conditions_unknown"
            if match is None or match.get("version") is None
            else "condition_changed"
            if match["version"] != old["material_version"]
            else ""
        )
    if evidence["scope"]["claim_family"] == "performance" and any(
        old[key] is None for key in ("price_version", "offer_key", "target_version")
    ):
        reasons.append("conditions_unknown")
    if evidence["scope"]["claim_family"] == "performance" and any(
        evidence["scope"][key] is None for key in ("audience_key", "claim_key")
    ):
        reasons.append("conditions_unknown")
    for key, menu in (
        ("audience_key", "audience_keys"),
        ("customer_group_id", "customer_group_ids"),
    ):
        if evidence["scope"][key] and evidence["scope"][key] not in current.get(menu, []):
            reasons.append("condition_changed")
    for key in ("result_kind", "currency", "attribution"):
        if evidence["scope"]["claim_family"] == "performance":
            if not evidence["scope"][key] or not current.get(key):
                reasons.append("conditions_unknown")
            elif evidence["scope"][key] != current[key]:
                reasons.append("condition_changed")
    return [r for r in reasons if r]


def qualify_learning_evidence(rows, current, *, min_result_events, max_age_days):
    """Normalize actual meaning and compute independent scoped support without reading a clock."""
    prepared = []
    for row in rows:
        evidence = _decode(row)
        scope = evidence["scope"]
        reasons = []
        if not current.get("product_id"):
            reasons.append("scope_required")
        elif scope["product_id"] and scope["product_id"] != current["product_id"]:
            reasons.append("other_product")
        elif not scope["product_id"] and scope["claim_family"] != "brand_fact":
            reasons.append("scope_required")
        tenant_matches = all(
            row.get(key) == current.get(key) and current.get(key) for key in ("org_id", "brand_id")
        )
        source_known = (
            evidence["source_kind"]
            and evidence["source_version"]
            and any(evidence["source_ref"].values())
        )
        if (
            not row.get("id")
            or not tenant_matches
            or not source_known
            or evidence["provenance"] == "unknown"
        ):
            reasons.append("unknown_source")
        if evidence["provenance"] == "simulation":
            reasons.append("simulated")
        if evidence["provenance"] == "operation_readback" or scope["claim_family"] == "operation":
            reasons.append("operation_only")
        reasons.extend(_conditions(evidence, current))
        start, end, today = (
            _day(evidence["period"]["start"]),
            _day(evidence["period"]["end"]),
            _day(current.get("org_day")),
        )
        if scope["claim_family"] == "performance":
            if not start or not end or not today or end < start or end > today:
                reasons.append("conditions_unknown")
            elif (today - end).days > max_age_days:
                reasons.append("measurement_stale")
        if row.get("needs_revalidation"):
            reasons.append("condition_changed")
        if row.get("expired"):
            reasons.append("superseded")
        events = evidence["sample"]["result_events"]
        sufficient = events is not None and events >= min_result_events
        evidence["sample"]["sufficient"] = sufficient if events is not None else None
        if scope["claim_family"] == "performance" and not sufficient:
            reasons.append("insufficient_sample")
        reasons = sorted(set(reasons))
        state = "usable"
        if any(r in reasons for r in ("other_product", "scope_required")):
            state = "excluded"
        elif "simulated" in reasons and current.get("mode") != "isolated_simulation":
            state = "excluded"
        elif "unknown_source" in reasons:
            state = "history"
        elif "superseded" in reasons:
            state = "history"
        elif any(
            r in reasons
            for r in ("condition_changed", "offer_ended", "measurement_stale", "conditions_unknown")
        ):
            state = "revalidation"
        prepared.append(
            {
                "row": row,
                "e": evidence,
                "reasons": reasons,
                "state": state,
                "start": start,
                "end": end,
                "support": (0, 0, 0),
            }
        )

    # A trial is one observation across source tracks and revisions. A retained older window
    # of that same trial never creates another independent observation in a different cohort.
    newest_trials = {}
    for p in prepared:
        e, row = p["e"], p["row"]
        trial = e["source_ref"]["trial_id"]
        if not trial or not e["scope"]["claim_key"]:
            continue
        key = (
            row.get("org_id"),
            row.get("brand_id"),
            e["scope"]["product_id"],
            e["scope"]["claim_key"],
            trial,
        )
        newest_trials[key] = max(newest_trials.get(key, ""), e["period"]["end"] or "")
    for p in prepared:
        e, row = p["e"], p["row"]
        key = (
            row.get("org_id"),
            row.get("brand_id"),
            e["scope"]["product_id"],
            e["scope"]["claim_key"],
            e["source_ref"]["trial_id"],
        )
        if key in newest_trials and (e["period"]["end"] or "") < newest_trials[key]:
            p["reasons"].append("superseded")
            p["state"] = "history"

    cohorts = {}
    for p in prepared:
        e = p["e"]
        if (
            p["state"] != "usable"
            or e["scope"]["claim_family"] != "performance"
            or e["provenance"] != "platform_observation"
            or not e["sample"]["sufficient"]
            or e["direction"] == "inconclusive"
            or not e["scope"]["claim_key"]
            or not e["source_ref"]["trial_id"]
        ):
            continue
        key = _hash(
            [
                p["row"].get("org_id"),
                p["row"].get("brand_id"),
                e["scope"],
                _cohort_conditions(e["conditions"]),
                e["provenance"],
            ]
        )
        cohorts.setdefault(key, []).append(p)
    for cohort in cohorts.values():
        trials, accepted = set(), []
        for p in sorted(
            cohort,
            key=lambda p: (
                p["end"],
                p["start"],
                p["e"]["source_ref"]["trial_id"],
                str(p["row"].get("id")),
            ),
        ):
            trial = p["e"]["source_ref"]["trial_id"]
            if trial in trials or any(
                p["start"] <= q["end"] and q["start"] <= p["end"] for q in accepted
            ):
                continue
            trials.add(trial)
            accepted.append(p)
        if not accepted:
            continue
        direction = accepted[-1]["e"]["direction"]
        streak = 0
        for p in reversed(accepted):
            if p["e"]["direction"] != direction:
                break
            streak += 1
        contrary = sum(p["e"]["direction"] == "contrary" for p in accepted)
        for p in cohort:
            p["support"] = (len(accepted), streak, contrary)
            if p["e"]["direction"] != direction:
                p["reasons"].append("contradictory_result")
                p["state"] = "history"

    items = []
    for p in prepared:
        row, e = p["row"], p["e"]
        count, same, contrary = p["support"]
        reasons = sorted(set(p["reasons"]))
        allowed = []
        if p["state"] == "usable":
            if "operation_only" in reasons:
                allowed = ["operation"]
            elif e["scope"]["claim_family"] == "brand_fact":
                allowed = ["brand_fact"]
            elif e["scope"]["claim_family"] == "performance":
                allowed = ["test", "retain_control"]
                if same and e["direction"] == "support":
                    allowed.append("market_support")
        support_label = "來源尚未核實"
        if "operation_only" in reasons:
            support_label = "操作核對；成效原因未知"
        elif "simulated" in reasons:
            support_label = "演練資料"
        elif "superseded" in reasons:
            support_label = "已由較新結論取代；保留歷史"
        elif e["scope"]["claim_family"] == "brand_fact" and p["state"] == "usable":
            support_label = "已確認品牌事實"
        elif same:
            support_label = ("一次可比觀察", "兩次獨立同向觀察", "三次以上獨立同向觀察")[
                min(same, 3) - 1
            ] + "；僅表示相關"
        elif "insufficient_sample" in reasons:
            support_label = (
                "樣本數尚未完整核實；僅供測試或對照"
                if e["sample"]["result_events"] is None
                else "樣本少；僅供測試或對照"
            )
        elif p["state"] == "revalidation":
            support_label = "適用條件待核對"
        elif e["scope"]["claim_family"] == "performance" and "unknown_source" not in reasons:
            support_label = "本期看不出方向；僅供測試或對照"
        source_ids = list(dict.fromkeys(v for v in e["source_ref"].values() if v)) or [None]
        item = {
            "schema_version": 1,
            "id": row.get("id"),
            "meaning_revision": "",
            "display_text": row.get("learning_text") or "",
            "support_label": support_label,
            "provenance": e["provenance"],
            "sources": [
                {
                    "kind": e["source_kind"],
                    "id": source_id,
                    "version": e["source_version"],
                    "period": e["period"],
                    "label": None,
                }
                for source_id in source_ids
            ],
            "scope": {**e["scope"], "product_label": None},
            "conditions": e["conditions"],
            "sample": e["sample"],
            "independent_count": count,
            "same_direction_count": same,
            "contrary_count": contrary,
            "use_state": p["state"],
            "reason_codes": reasons,
            "reason_labels": [
                "樣本數尚未完整核實"
                if r == "insufficient_sample" and e["sample"]["result_events"] is None
                else _REASONS[r]
                for r in reasons
            ],
            "allowed_uses": allowed,
            "limits": sorted(
                set(
                    e["limits"]
                    + (["conditions_unknown"] if "conditions_unknown" in reasons else [])
                )
            ),
        }
        item["meaning_revision"] = _hash(
            [row.get("learning_text"), e, count, same, contrary, p["state"], reasons, allowed]
        )
        items.append(item)
    items.sort(key=lambda i: (i["sources"][0]["period"]["end"] or "", str(i["id"])), reverse=True)
    revisions = sorted(((i["id"], i["meaning_revision"]) for i in items), key=lambda r: str(r[0]))
    return {
        "items": items,
        "revision": _hash(revisions),
        "eligible_count": sum(
            i["use_state"] == "usable" and bool(i["allowed_uses"]) for i in items
        ),
    }
