"""Explicitly confirmed observational comparisons, never a causal or randomized A/B claim."""

import hashlib
import json
from datetime import date, timedelta
from itertools import combinations

from app import workbench
from app.ads import assets, repository, simulation_mode
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
RULES = {"min_days": 7, "min_purchases_each": 10, "relative_difference": 0.10}
LIMITATION = "觀察性比較；同組不代表隨機分流或平均花費，不宣稱統計顯著或因果。"


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
    return detail


def _fingerprint(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, default=str).encode()).hexdigest()


def _materials(conn, org_id, brand_id, campaign_id):
    # Read the public workbench projection, including each currently adopted output.
    briefs = workbench.briefs_for_source(
        conn, org_id, brand_id, assets.PACK_SOURCE_KIND, {"ads_campaign_id": campaign_id}
    )
    result = {}
    for brief in briefs:
        ad_id = (brief.get("source_ref") or {}).get("ads_ad_id")
        if ad_id:
            outputs = {
                part: workbench.adopted_output(conn, org_id, brand_id, brief["id"], part)
                for part in (brief.get("parts") or {})
            }
            result[ad_id] = {"brief": brief, "outputs": outputs}
    return result


def propose(conn, org_id, brand_id, campaign_id):
    detail = _detail(conn, org_id, brand_id, campaign_id)
    labels = {
        (v["dimension"], v["key"]): v["label"]
        for v in repository.coordinate_vocabulary(conn, org_id, brand_id)
    }
    materials = _materials(conn, org_id, brand_id, campaign_id)
    pair = None
    for group in sorted(detail["groups"], key=lambda g: g["id"]):
        for a, b in combinations(sorted(group["ads"], key=lambda ad: ad["id"]), 2):
            if not a["audience_key"] or a["audience_key"] != b["audience_key"]:
                continue
            if any(not ad.get(f"{d}_key") for ad in (a, b) for d in DIMENSIONS):
                continue
            changed = [d for d in DIMENSIONS if a[f"{d}_key"] != b[f"{d}_key"]]
            if len(changed) == 1 and a.get("product_id") == b.get("product_id"):
                pair = group, a, b, changed[0]
                break
        if pair:
            break
    if pair is None:
        return (
            None,
            "缺少合格對照：請在同投放組、同受眾與同商品下建立兩則廣告，六項設定中只改一項；素材種類多不等於有效比較。",
        )
    group, a, b, dimension = pair
    start = group["start_date"] or detail["start_date"]
    end = group["end_date"] or detail["end_date"]
    if not start or not end or end < start:
        return None, "請先設定共同的開始與結束日期。"
    if float(group["daily_budget"]) <= 0:
        return None, "請先設定投放組的每日預算。"
    metric = detail["success_metric"]
    metric_label = {"cpa": "每次轉換成本", "roas": "ROAS（保守）", "purchases": "轉換數"}[metric]
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
    snapshot = {
        "campaign": {
            k: detail.get(k)
            for k in (
                "objective",
                "success_metric",
                "success_target",
                "start_date",
                "end_date",
                "budget_planned",
                "constraints_json",
            )
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
        "rules": RULES,
        "products": (detail.get("context_json") or {}).get("product_ids"),
        "labels": sorted((dim, key, value) for (dim, key), value in labels.items()),
    }
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
        f"觀察{metric_label}是否有至少 10% 的相對差異。",
        "variable": DIMENSIONS[dimension],
        "variants": [
            {"ad_id": ad["id"], "name": ad["name"], "value": value}
            for ad, value in ((a, left), (b, right))
        ],
        "shared": shared,
        "metric": metric,
        "metric_label": metric_label,
        "window": {"start": str(start), "end": str(end)},
        "rules": RULES,
        "stop": f"到 {end} 停止收樣；若先碰到每日預算 {group['daily_budget']}，"
        "先檢查配量並停止下結論。本計畫不會自動停止平台廣告。",
        "limitation": LIMITATION,
    }, None


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


def judge(conn, org_id, brand_id, campaign_id, proposal, confirmed, stale):
    result = {"verdict": "看不出", "reason": "請先確認比較計畫。", "values": []}
    if not confirmed:
        return result
    if stale:
        return {**result, "reason": "條件或素材已變更，原確認已過期。"}
    start, end = [date.fromisoformat(proposal["window"][k]) for k in ("start", "end")]
    today = settings.today_for_org(conn, org_id=org_id)
    if today < end or (end - start).days + 1 < RULES["min_days"]:
        return {**result, "reason": "尚未完成至少 7 天的共同觀察期間。"}
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
    required = {start + timedelta(days=i) for i in range((end - start).days + 1)}
    values = []
    for variant in proposal["variants"]:
        own = [r for r in rows if r["entity_id"] == variant["ad_id"]]
        if {r["day"] for r in own} != required:
            return {**result, "reason": "兩則廣告尚有缺日；缺資料不當成零。"}
        if any(r["source"] != "simulated" for r in own):
            return {**result, "reason": "目前真實平台回收未追蹤轉換，不能判讀此指標。"}
        total = {k: sum(float(r[k]) for r in own) for k in ("spend", "purchases", "revenue")}
        if total["purchases"] < RULES["min_purchases_each"]:
            return {**result, "reason": "每則至少需要 10 次轉換；目前樣本不足。"}
        metric = proposal["metric"]
        if metric == "roas" and not total["spend"]:
            return {**result, "reason": "花費為零，ROAS 無法計算。"}
        value = total["purchases"]
        if metric == "cpa":
            value = total["spend"] / total["purchases"]
        elif metric == "roas":
            value = total["revenue"] / total["spend"]
        values.append(
            {
                "ad_id": variant["ad_id"],
                "name": variant["name"],
                "value": value,
                "spend": total["spend"],
                "purchases": total["purchases"],
            }
        )
    a, b = [v["value"] for v in values]
    difference = abs(a - b) / max(abs(a), abs(b)) if max(abs(a), abs(b)) else 0
    if difference < RULES["relative_difference"]:
        return {**result, "values": values, "reason": "觀察差異未達預設 10% 門檻。"}
    index = (0 if a < b else 1) if proposal["metric"] == "cpa" else (0 if a > b else 1)
    return {
        "verdict": "觀察到差異",
        "values": values,
        "reason": f"「{values[index]['name']}」的指標較佳；隔離模擬數字僅驗證判讀流程，"
        "不構成市場優勝或因果證據。",
    }


def read(conn, org_id, brand_id, campaign_id):
    detail = _detail(conn, org_id, brand_id, campaign_id)
    proposal, missing = propose(conn, org_id, brand_id, campaign_id)
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
    }


def confirm(conn, org_id, brand_id, campaign_id, *, fingerprint, controls_checked, actor):
    detail = _detail(conn, org_id, brand_id, campaign_id, write=True)
    if detail["status"] == "closed":
        raise ValueError("活動已結案，不能更改比較計畫。")
    if not controls_checked:
        raise ValueError("請先核對素材與共同投放條件，確認只改一個因素。")
    proposal, missing = propose(conn, org_id, brand_id, campaign_id)
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
