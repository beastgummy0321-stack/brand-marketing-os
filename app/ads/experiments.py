"""Explicitly confirmed observational comparisons, never a causal or randomized A/B claim."""

import hashlib
import json
import math
from datetime import date, timedelta
from itertools import combinations

from app.ads import live_creative, repository, simulation_mode
from app.core import settings
from app.core.db import jsonb, now_utc

DIMENSIONS = {
    "pain": "需求",
    "angle": "訴求角度",
    "hook": "開場",
    "proof": "佐證",
    "offer": "方案",
    "format": "形式",
}
DEFAULT_RULES = {"min_days": 7, "min_conversions_each": 10, "relative_difference": 0.10}
LIMITATION = "觀察性比較；同組不代表隨機分流或平均花費，不宣稱統計顯著或因果。"
SETTING_KEYS = frozenset((*DEFAULT_RULES, "window"))


class InvalidSettings(ValueError):
    pass


class StaleSettings(ValueError):
    pass


class ClosedSettings(ValueError):
    pass


def _detail(conn, org_id, brand_id, campaign_id, *, write=False):
    if write:
        simulation_mode.lock(conn, org_id, brand_id)
        conn.execute(
            "SELECT id FROM ads_campaign WHERE org_id=%s AND brand_id=%s AND id=%s FOR UPDATE",
            (org_id, brand_id, campaign_id),
        )
    detail = repository.campaign_detail(conn, org_id, brand_id, campaign_id)
    if detail is None:
        raise ValueError("找不到這個活動。")
    if write:
        repository.require_internal_campaign(conn, org_id, brand_id, campaign_id)
    # F31-I05 Contract O: pairs compare the coordinates each creative was made for (the
    # dispatched set's snapshot), not coordinates edited after dispatch.
    return live_creative.with_learning_coordinates(conn, org_id, brand_id, detail)


def _fingerprint(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, default=str).encode()).hexdigest()


def _percent(value):
    percent = value * 100
    return f"{percent:g}%"


def pairs(detail):
    """Every qualifying pair, in a stable order (group id, then ad ids): same group, same
    audience, same product, every coordinate set, exactly one coordinate different (F29-I04
    Contract F generalises the first-pair rule to all pairs). Yields `(group, a, b, dimension)`
    with `a.id < b.id`; an ad may sit in more than one pair."""
    for group in sorted(detail["groups"], key=lambda g: g["id"]):
        for a, b in combinations(sorted(group["ads"], key=lambda ad: ad["id"]), 2):
            if not a["audience_key"] or a["audience_key"] != b["audience_key"]:
                continue
            if any(not ad.get(f"{d}_key") for ad in (a, b) for d in DIMENSIONS):
                continue
            changed = [d for d in DIMENSIONS if a[f"{d}_key"] != b[f"{d}_key"]]
            if len(changed) == 1 and a.get("product_id") == b.get("product_id"):
                yield group, a, b, changed[0]


def _pair(detail):
    return next(pairs(detail), None)


def _default_window(detail, pair=None):
    group = pair[0] if pair else None
    start = (group or {}).get("start_date") or detail.get("start_date")
    end = (group or {}).get("end_date") or detail.get("end_date")
    return {
        "start": str(start) if start else None,
        "end": str(end) if end else None,
    }


def _settings(detail, pair=None):
    record = (detail.get("context_json") or {}).get("comparison_settings") or {}
    overrides = record.get("overrides") if isinstance(record, dict) else {}
    overrides = dict(overrides) if isinstance(overrides, dict) else {}
    defaults = {**DEFAULT_RULES, "window": _default_window(detail, pair)}
    effective = {**defaults, **overrides}
    revision = record.get("revision", 0) if isinstance(record, dict) else 0
    revision = revision if isinstance(revision, int) and not isinstance(revision, bool) else 0
    return {
        "revision": str(max(revision, 0)),
        "scope": "campaign",
        "defaults": defaults,
        "effective": effective,
        "overrides": overrides,
        "customized": sorted(overrides),
    }


def _parse_window(value, *, bounds):
    if not isinstance(value, dict) or set(value) != {"start", "end"}:
        raise InvalidSettings("觀察期間必須包含 start 與 end。")
    if any(not isinstance(value[key], str) for key in ("start", "end")):
        raise InvalidSettings("觀察期間必須使用 ISO 日期。")
    try:
        start, end = (date.fromisoformat(value[key]) for key in ("start", "end"))
    except ValueError as exc:
        raise InvalidSettings("觀察期間必須使用有效的 ISO 日期。") from exc
    if end < start:
        raise InvalidSettings("觀察期間結束日不可早於開始日。")
    if not bounds["start"] or not bounds["end"]:
        raise InvalidSettings("請先設定共同投放期間，再自訂觀察期間。")
    bound_start, bound_end = (date.fromisoformat(bounds[key]) for key in ("start", "end"))
    if start < bound_start or end > bound_end:
        raise InvalidSettings("觀察期間不可超出共同投放期間。")
    return {"start": start.isoformat(), "end": end.isoformat()}


def _validated_overrides(overrides, defaults):
    if not isinstance(overrides, dict):
        raise InvalidSettings("overrides 必須是物件。")
    unknown = set(overrides) - SETTING_KEYS
    if unknown:
        raise InvalidSettings(f"不支援的比較設定：{', '.join(sorted(unknown))}。")
    normalized = {}
    for key in ("min_days", "min_conversions_each"):
        if key not in overrides:
            continue
        value = overrides[key]
        if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
            raise InvalidSettings(f"{key} 必須是正整數。")
        normalized[key] = value
    if "relative_difference" in overrides:
        value = overrides["relative_difference"]
        if (
            not isinstance(value, (int, float))
            or isinstance(value, bool)
            or not math.isfinite(float(value))
            or not 0 < float(value) <= 1
        ):
            raise InvalidSettings("relative_difference 必須大於 0 且不超過 1。")
        normalized["relative_difference"] = float(value)
    if "window" in overrides:
        normalized["window"] = _parse_window(overrides["window"], bounds=defaults["window"])
    effective = {**defaults, **normalized}
    if "min_days" in overrides or "window" in overrides:
        window = effective["window"]
        if not window["start"] or not window["end"]:
            raise InvalidSettings("請先設定共同投放期間，再自訂最少天數。")
        span = (date.fromisoformat(window["end"]) - date.fromisoformat(window["start"])).days + 1
        if effective["min_days"] > span:
            raise InvalidSettings("最少天數不可超過有效觀察期間。")
    return normalized


def save_settings(conn, org_id, brand_id, campaign_id, *, revision, overrides, actor):
    detail = _detail(conn, org_id, brand_id, campaign_id, write=True)
    if detail["status"] == "closed":
        raise ClosedSettings("活動已結案，不能修改比較設定。")
    pair = _pair(detail)
    current = _settings(detail, pair)
    if revision != current["revision"]:
        raise StaleSettings("比較設定已被更新，請重新讀取後再儲存。")
    normalized = _validated_overrides(overrides, current["defaults"])
    next_revision = int(current["revision"]) + 1
    context = dict(detail.get("context_json") or {})
    context["comparison_settings"] = {
        "overrides": normalized,
        "revision": next_revision,
        "updated_by": actor,
        "updated_at": now_utc().isoformat(),
    }
    conn.execute(
        "UPDATE ads_campaign SET context_json=%s, updated_at=now() "
        "WHERE org_id=%s AND brand_id=%s AND id=%s",
        (jsonb(context), org_id, brand_id, campaign_id),
    )
    return _settings({**detail, "context_json": context}, pair)


def _materials(conn, org_id, brand_id, campaign_id):
    # The creative each ad shows through the public workbench projection: the outputs its
    # approved launch froze once launched, the set's current selection before (F31-I05 Contract
    # O). Same `{ad_id: {brief, outputs}}` shape, so an unchanged creative keeps its fingerprint.
    return live_creative.materials(conn, org_id, brand_id, campaign_id)


def _build_proposal(conn, org_id, brand_id, campaign_id, detail):
    labels = {
        (v["dimension"], v["key"]): v["label"]
        for v in repository.coordinate_vocabulary(conn, org_id, brand_id)
    }
    materials = _materials(conn, org_id, brand_id, campaign_id)
    pair = _pair(detail)
    if pair is None:
        return (
            None,
            "缺少合格對照：請在同投放組、同受眾與同商品下建立兩則廣告，六項設定中只改一項；素材種類多不等於有效比較。",
        )
    group, a, b, dimension = pair
    comparison_settings = _settings(detail, pair)
    try:
        _validated_overrides(
            comparison_settings["overrides"], comparison_settings["defaults"]
        )
    except InvalidSettings as exc:
        return None, f"已保存的比較設定不再符合共同投放期間，請還原或重新設定：{exc}"
    effective = comparison_settings["effective"]
    start = effective["window"]["start"]
    end = effective["window"]["end"]
    if not start or not end or end < start:
        return None, "請先設定共同的開始與結束日期。"
    if float(group["daily_budget"]) <= 0:
        return None, "請先設定投放組的每日預算。"
    # F28-I01: one cap per campaign, cost per result -- the comparison reads the same metric.
    metric = "cpa"
    metric_label = "每次轉換成本"
    left, right = [
        labels.get((dimension, ad[f"{dimension}_key"]), ad[f"{dimension}_key"]) for ad in (a, b)
    ]
    shared = {
        "group_id": group["id"],
        "group": group["name"],
        "audience": labels.get(("audience", a["audience_key"]), a["audience_key"]),
        "channel": group["channel_key"],
        "daily_budget": float(group["daily_budget"]),
        "objective": detail["objective"],
    }
    constraints = detail.get("constraints_json") or {}
    snapshot = {
        "campaign": {
            **{
                k: detail.get(k)
                for k in (
                    "objective",
                    "start_date",
                    "end_date",
                    "budget_planned",
                )
            },
            # F28-I03: only the platform is a comparison condition. The budget cap is an
            # internal planning number, editable in any status, and never makes a confirmed
            # comparison stale (ads.md §6.32).
            "constraints_json": {k: constraints[k] for k in ("platform",) if k in constraints},
        },
        "manual_delivery": (detail.get("context_json") or {}).get("manual_delivery"),
        "groups": [
            {
                k: g[k]
                for k in (
                    "id",
                    "channel_key",
                    "role",
                    "daily_budget",
                    "start_date",
                    "end_date",
                    "ads",
                )
            }
            for g in sorted(detail["groups"], key=lambda row: row["id"])
        ],
        "materials": materials,
        # Keep the legacy snapshot shape so deploying this contract alone does not invalidate
        # an already-confirmed default plan. Non-default effective values still change the hash.
        "rules": {
            "min_days": effective["min_days"],
            "min_purchases_each": effective["min_conversions_each"],
            "relative_difference": effective["relative_difference"],
        },
        "products": (detail.get("context_json") or {}).get("product_ids"),
        "labels": sorted((dim, key, value) for (dim, key), value in labels.items()),
    }
    if effective["window"] != comparison_settings["defaults"]["window"]:
        snapshot["comparison_window"] = effective["window"]
    # Platform binding itself may change after a plan is confirmed; creative identity must not.
    for g in snapshot["groups"]:
        g["ads"] = [
            {
                k: ad.get(k)
                for k in (
                    "id",
                    "name",
                    "product_id",
                    "audience_key",
                    *[f"{d}_key" for d in DIMENSIONS],
                    "asset_ready_source",
                    "asset_ready_at",
                )
            }
            for ad in sorted(g["ads"], key=lambda row: row["id"])
        ]
    return {
        "fingerprint": _fingerprint(snapshot),
        "snapshot": snapshot,
        "hypothesis": f"在共同條件下，把{DIMENSIONS[dimension]}從「{left}」改為「{right}」，"
        f"觀察{metric_label}是否有至少 {_percent(effective['relative_difference'])} 的相對差異。",
        "variable": DIMENSIONS[dimension],
        "variants": [
            {"ad_id": ad["id"], "name": ad["name"], "value": value}
            for ad, value in ((a, left), (b, right))
        ],
        "shared": shared,
        "metric": metric,
        "metric_label": metric_label,
        "window": {"start": str(start), "end": str(end)},
        "rules": {key: effective[key] for key in DEFAULT_RULES},
        "stop": f"到 {end} 停止收樣；若先碰到每日預算 {group['daily_budget']}，"
        "先檢查配量並停止下結論。本計畫不會自動停止平台廣告。",
        "limitation": LIMITATION,
    }, None


def propose(conn, org_id, brand_id, campaign_id):
    detail = _detail(conn, org_id, brand_id, campaign_id)
    return _build_proposal(conn, org_id, brand_id, campaign_id, detail)


def _rows(conn, org_id, brand_id, campaign_id, proposal):
    return conn.execute(
        "SELECT * FROM ads_outcome_daily WHERE org_id=%s AND brand_id=%s AND campaign_id=%s "
        "AND entity_kind='ad' AND entity_id=ANY(%s) AND day BETWEEN %s AND %s ORDER BY day",
        (
            org_id,
            brand_id,
            campaign_id,
            [v["ad_id"] for v in proposal["variants"]],
            proposal["window"]["start"],
            proposal["window"]["end"],
        ),
    ).fetchall()


def evaluate(rows, ad_ids, start, end, rules, metric="cpa"):
    """The one judge core (F29-I04 Contract F), shared by a confirmed plan's `judge` and the
    automatic pairs (`ab_pairs`). `rows` are `ads_outcome_daily` ad rows of `ad_ids`; only the
    days in `[start, end]` count. Unknown stays unknown: a missing day or an untracked purchase
    count blocks the judgement and is never summed as 0. There is no data-source gate -- real
    and simulated rows are read the same way. Returns `{state, reason, totals, difference,
    winner}`:

    - `state`: `missing_days` | `untracked` | `short` (fewer than `min_days`) | `thin` (a side
      under `min_conversions_each`) | `zero_spend` (ROAS without spend) | `no_difference` |
      `judged`;
    - `totals[i]` for `ad_ids[i]`: `{ad_id, days_present, spend, purchases, revenue, value}` --
      `spend` null when a day is missing, `purchases` also null when a day is untracked, `value`
      only once both sides pass the thresholds;
    - `difference`: the relative difference once both sides pass the thresholds, else null;
    - `winner`: the index into `ad_ids` of the better side, only for `judged`.
    """
    min_days = rules["min_days"]
    min_conversions = rules.get("min_conversions_each", rules.get("min_purchases_each"))
    relative_difference = rules["relative_difference"]
    required = {start + timedelta(days=i) for i in range((end - start).days + 1)}
    tracked_keys = ("purchases", "revenue") if metric == "roas" else ("purchases",)
    totals, missing, untracked = [], False, False
    for ad_id in ad_ids:
        own = [r for r in rows if r["entity_id"] == ad_id and r["day"] in required]
        present = {r["day"] for r in own}
        complete = present == required
        known = all(r[k] is not None for r in own for k in tracked_keys)
        missing = missing or not complete
        untracked = untracked or not known
        total = {"ad_id": ad_id, "days_present": len(present), "spend": None, "purchases": None,
                 "revenue": None, "value": None}
        if complete:
            total["spend"] = sum(float(r["spend"]) for r in own)
            if known:
                total["purchases"] = sum(float(r["purchases"]) for r in own)
            if all(r["revenue"] is not None for r in own):
                total["revenue"] = sum(float(r["revenue"]) for r in own)
        totals.append(total)
    result = {"state": None, "reason": None, "totals": totals, "difference": None,
              "winner": None}
    if missing:
        return {**result, "state": "missing_days", "reason": "兩則廣告尚有缺日；缺資料不當成零。"}
    if untracked:
        return {**result, "state": "untracked",
                "reason": "平台回收有未追蹤轉換的日子；未追蹤不當成零，不能判讀此指標。"}
    if len(required) < min_days:
        return {**result, "state": "short",
                "reason": f"尚未完成至少 {min_days} 天的共同觀察期間。"}
    if any(t["purchases"] < min_conversions for t in totals):
        return {**result, "state": "thin",
                "reason": f"每則至少需要 {min_conversions} 次轉換；目前樣本不足。"}
    for total in totals:
        value = total["purchases"]
        if metric == "cpa":
            value = total["spend"] / total["purchases"]
        elif metric == "roas":
            if not total["spend"]:
                return {**result, "state": "zero_spend", "reason": "花費為零，ROAS 無法計算。"}
            value = total["revenue"] / total["spend"]
        total["value"] = value
    a, b = [t["value"] for t in totals]
    difference = abs(a - b) / max(abs(a), abs(b)) if max(abs(a), abs(b)) else 0
    if difference < relative_difference:
        threshold_kind = (
            "預設" if relative_difference == DEFAULT_RULES["relative_difference"] else "自訂"
        )
        return {**result, "state": "no_difference", "difference": difference,
                "reason": f"觀察差異未達{threshold_kind} {_percent(relative_difference)} 門檻。"}
    winner = (0 if a < b else 1) if metric == "cpa" else (0 if a > b else 1)
    return {**result, "state": "judged", "difference": difference, "winner": winner,
            "reason": "觀察性比較，不構成市場優勝或因果證據。"}


def judge(conn, org_id, brand_id, campaign_id, proposal, confirmed, stale):
    result = {"verdict": "看不出", "reason": "請先確認比較計畫。", "values": []}
    if not confirmed:
        return result
    if stale:
        return {**result, "reason": "條件或素材已變更，原確認已過期。"}
    metric = proposal["metric"]
    if metric not in {"cpa", "roas", "purchases"}:
        return {**result, "reason": f"目前不支援活動成功指標「{metric}」，無法判讀。"}
    rules = proposal["rules"]
    min_days = rules["min_days"]
    start, end = [date.fromisoformat(proposal["window"][k]) for k in ("start", "end")]
    today = settings.today_for_org(conn, org_id=org_id)
    if today < end or (end - start).days + 1 < min_days:
        return {**result, "reason": f"尚未完成至少 {min_days} 天的共同觀察期間。"}
    rows = _rows(conn, org_id, brand_id, campaign_id, proposal)
    cap_hit = conn.execute(
        "SELECT 1 FROM ads_outcome_daily WHERE org_id=%s AND brand_id=%s AND campaign_id=%s "
        "AND entity_kind='group' AND entity_id=%s AND day BETWEEN %s AND %s "
        "AND spend >= %s LIMIT 1",
        (
            org_id,
            brand_id,
            campaign_id,
            proposal["shared"]["group_id"],
            start,
            end,
            proposal["shared"]["daily_budget"],
        ),
    ).fetchone()
    if cap_hit:
        return {**result, "reason": "已碰到預設每日預算停止條件，先檢查配量；暫不判優劣。"}
    variants = proposal["variants"]
    core = evaluate(rows, [v["ad_id"] for v in variants], start, end, rules, metric)
    if core["state"] not in {"no_difference", "judged"}:
        return {**result, "reason": core["reason"]}
    values = [
        {
            "ad_id": variant["ad_id"],
            "name": variant["name"],
            "value": total["value"],
            "spend": total["spend"],
            "purchases": total["purchases"],
        }
        for variant, total in zip(variants, core["totals"], strict=True)
    ]
    if core["state"] == "no_difference":
        return {**result, "values": values, "reason": core["reason"]}
    return {
        "verdict": "觀察到差異",
        "values": values,
        "reason": f"「{values[core['winner']]['name']}」的指標較佳；{core['reason']}",
    }


def read(conn, org_id, brand_id, campaign_id):
    detail = _detail(conn, org_id, brand_id, campaign_id)
    pair = _pair(detail)
    proposal, missing = _build_proposal(conn, org_id, brand_id, campaign_id, detail)
    confirmed = (detail.get("context_json") or {}).get("comparison_plan")
    stale = bool(
        confirmed and (not proposal or confirmed["fingerprint"] != proposal["fingerprint"])
    )
    result = (
        judge(conn, org_id, brand_id, campaign_id, proposal, confirmed, stale)
        if proposal
        else {"verdict": "看不出", "reason": missing, "values": []}
    )
    return {
        "proposal": proposal,
        "missing": missing,
        "confirmed": confirmed,
        "stale": stale,
        "closed": detail["status"] == "closed",
        "result": result,
        "simulation": simulation_mode.enabled(conn, org_id, brand_id),
        "settings": _settings(detail, pair),
    }


def confirm(conn, org_id, brand_id, campaign_id, *, fingerprint, controls_checked, actor):
    detail = _detail(conn, org_id, brand_id, campaign_id, write=True)
    if detail["status"] == "closed":
        raise ValueError("活動已結案，不能更改比較計畫。")
    if not controls_checked:
        raise ValueError("請先核對素材與共同投放條件，確認只改一個因素。")
    proposal, missing = _build_proposal(conn, org_id, brand_id, campaign_id, detail)
    if not proposal:
        raise ValueError(missing)
    if fingerprint != proposal["fingerprint"]:
        raise ValueError("提案條件已變更，請重新讀取後確認。")
    context = dict(detail.get("context_json") or {})
    existing = context.get("comparison_plan")
    if existing and existing["fingerprint"] == fingerprint:
        return
    proposal["confirmed_at"] = now_utc().isoformat()
    proposal["confirmed_by"] = actor
    proposal["timing"] = (
        "retrospective" if _rows(conn, org_id, brand_id, campaign_id, proposal) else "before_data"
    )
    context["comparison_plan"] = proposal
    conn.execute(
        "UPDATE ads_campaign SET context_json=%s WHERE org_id=%s AND brand_id=%s AND id=%s",
        (jsonb(context), org_id, brand_id, campaign_id),
    )
