"""Daily replacement snapshots for explicitly isolated local test brands."""

import hashlib
import json
from datetime import date

from app.ads import outcome, repository, simulation_mode
from app.ads.adapters import simulated
from app.core import config, settings
from app.core.db import jsonb, now_utc
from app.meta import repository as meta_repo

METRICS = ("spend", "impressions", "clicks", "purchases", "revenue")


def _campaign(conn, org_id, brand_id, campaign_id, *, write=False):
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
    if write and (detail.get("context_json") or {}).get("simulation_recovery", {}).get("closing"):
        raise ValueError("活動正在結案，模擬成效已凍結。")
    if write and detail["status"] == "closed":
        raise ValueError("活動已結案，模擬成效已凍結。")
    return detail


def eligibility(conn, org_id, brand_id) -> str | None:
    if config.settings().brand_os_env != "local":
        return "隔離模擬入口只在本機測試環境開放。"
    if meta_repo.bound_account_ids_for_brand(conn, org_id, brand_id):
        return "這個品牌已綁真實廣告帳戶，請另建隔離測試品牌。"
    if conn.execute(
        "SELECT 1 FROM ads_external_daily WHERE org_id=%s AND brand_id=%s "
        "AND source <> %s LIMIT 1",
        (org_id, brand_id, simulated.SOURCE),
    ).fetchone():
        return "這個品牌已有真實成效，不能改成模擬品牌。"
    for campaign in repository.list_campaigns(conn, org_id, brand_id):
        detail = repository.campaign_detail(conn, org_id, brand_id, campaign["id"])
        if detail is None:
            continue
        nodes = [detail, *detail["groups"], *[a for g in detail["groups"] for a in g["ads"]]]
        if any(n.get("external_id") and not n["external_id"].startswith("sim_") for n in nodes):
            return "這個品牌已有真實平台對應，請另建隔離測試品牌。"
    return None


def _require(conn, org_id, brand_id):
    reason = eligibility(conn, org_id, brand_id)
    if reason:
        raise ValueError(reason)
    if not simulation_mode.enabled(conn, org_id, brand_id):
        raise ValueError("請先確認啟用隔離模擬品牌。")


def start(conn, org_id, brand_id, campaign_id, *, actor, confirm_isolation):
    detail = _campaign(conn, org_id, brand_id, campaign_id, write=True)
    reason = eligibility(conn, org_id, brand_id)
    if reason:
        raise ValueError(reason)
    if not detail["start_date"] or not detail["end_date"]:
        raise ValueError("先設定活動的開始與結束日期。")
    if not any(g["ads"] for g in detail["groups"]):
        raise ValueError("先建立至少一個投放組與廣告，才能對應模擬資料。")
    if sum(float(g["daily_budget"]) for g in detail["groups"]) <= 0:
        raise ValueError("投放組的每日預算合計必須大於零。")
    context = dict(detail.get("context_json") or {})
    if context.get("simulation_recovery"):
        return
    if outcome.rows(conn, org_id, brand_id, campaign_id, "group") or outcome.rows(
        conn, org_id, brand_id, campaign_id, "ad",
    ):
        raise ValueError("此活動已有示意成效；請另建一個活動，避免把既有資料混入手動回收。")
    if not simulation_mode.enabled(conn, org_id, brand_id):
        if not confirm_isolation:
            raise ValueError("請確認這個品牌只作隔離測試，不再用於正式投放。")
        settings.set_setting(conn, f"ads_simulation_brand:{brand_id}", "1", org_id=org_id)
        detail = _campaign(conn, org_id, brand_id, campaign_id, write=True)
        context = dict(detail.get("context_json") or {})
        if context.get("simulation_recovery"):
            return
    context["simulation_recovery"] = {
        "started_by": actor,
        "started_at": now_utc().isoformat(),
        "mode": "daily_increment",
        "days": {},
    }
    conn.execute(
        "UPDATE ads_campaign SET context_json=%s WHERE org_id=%s AND brand_id=%s AND id=%s",
        (jsonb(context), org_id, brand_id, campaign_id),
    )
    simulated.publish(conn, org_id, brand_id, campaign_id, actor=actor)


def read_day(conn, org_id, brand_id, campaign_id, day: date):
    detail = _campaign(conn, org_id, brand_id, campaign_id)
    recovery = (detail.get("context_json") or {}).get("simulation_recovery") or {}
    saved = recovery.get("days", {}).get(day.isoformat(), {})
    rows = [
        {"ad_id": r["entity_id"], **{key: r[key] for key in METRICS}}
        for r in outcome.rows(conn, org_id, brand_id, campaign_id, "ad")
        if r["day"] == day and r["source"] == simulated.SOURCE
    ]
    return {
        "enabled": simulation_mode.enabled(conn, org_id, brand_id),
        "reason": eligibility(conn, org_id, brand_id),
        "started": bool(recovery),
        "day": day,
        "revision": saved.get("revision", 0),
        "saved_at": saved.get("saved_at"),
        "saved_by": saved.get("saved_by"),
        "rows": rows,
        "receipts": recovery.get("days", {}),
        "closed": detail["status"] == "closed",
    }


def save_day(
    conn,
    org_id,
    brand_id,
    campaign_id,
    day: date,
    rows: list[dict],
    *,
    revision: int,
    mode: str,
    actor: str,
):
    detail = _campaign(conn, org_id, brand_id, campaign_id, write=True)
    _require(conn, org_id, brand_id)
    context = dict(detail.get("context_json") or {})
    recovery = context.get("simulation_recovery")
    if not recovery:
        raise ValueError("請先啟用此活動的隔離回收。")
    if mode != "daily_increment":
        raise ValueError("只接受每日增量，不接受跨日累計值；請先換算各日差額。")
    if (
        not detail["start_date"]
        <= day
        <= min(detail["end_date"], settings.today_for_org(conn, org_id=org_id))
    ):
        raise ValueError("日期必須在活動期間內，而且不能晚於今天。")
    ads = {a["id"]: g["id"] for g in detail["groups"] for a in g["ads"]}
    if len({r["ad_id"] for r in rows}) != len(rows) or any(r["ad_id"] not in ads for r in rows):
        raise ValueError("廣告必須屬於此活動，且同一天不可重複。")
    if any(r["clicks"] > r["impressions"] for r in rows):
        raise ValueError("點擊數不能大於曝光數。")
    rows = sorted(rows, key=lambda r: r["ad_id"])
    digest = hashlib.sha256(json.dumps(rows, sort_keys=True).encode()).hexdigest()
    previous = recovery["days"].get(day.isoformat(), {})
    if previous.get("hash") == digest:
        return
    if revision != previous.get("revision", 0):
        raise ValueError("此日期已被其他操作更新，請重新讀取再修改。")
    conn.execute(
        "DELETE FROM ads_external_daily WHERE org_id=%s AND brand_id=%s AND campaign_id=%s "
        "AND day=%s AND source=%s",
        (org_id, brand_id, campaign_id, day, simulated.SOURCE),
    )
    natives = {
        n["id"]: n["external_id"]
        for g in detail["groups"] for n in (g, *g["ads"]) if n.get("external_id")
    }
    totals = {}
    out = []
    for row in rows:
        group_id = ads[row["ad_id"]]
        total = totals.setdefault(group_id, dict.fromkeys(METRICS, 0))
        for key in METRICS:
            total[key] += row[key]
        out.append(_row("ad", natives.get(row["ad_id"]), day, row))
    for group_id, values in totals.items():
        out.append(_row("adset", natives.get(group_id), day, values))
    simulated.write_rows(
        conn, org_id, brand_id, campaign_id, [r for r in out if r["native_id"]],
        simulated.entity_ids(conn, org_id, brand_id, campaign_id),
    )
    recovery["days"][day.isoformat()] = {
        "revision": revision + 1,
        "hash": digest,
        "saved_at": now_utc().isoformat(),
        "saved_by": actor,
        "ad_count": len(rows),
        "missing_ad_count": len(ads) - len(rows),
        "mode": mode,
    }
    conn.execute(
        "UPDATE ads_campaign SET context_json=%s WHERE org_id=%s AND brand_id=%s AND id=%s",
        (jsonb(context), org_id, brand_id, campaign_id),
    )
    # After the context write above (it replaces `context_json` whole): this day now counts as
    # read, the same recorded coverage a platform sync extends (Contract R).
    simulated.extend_coverage(conn, org_id, brand_id, campaign_id, detail, day, day)


def _row(kind, native_id, day, values):
    """One simulated observation row (`simulated.write_rows` shape) of this saved day."""
    return {
        "native_kind": kind, "native_id": native_id, "metric_scope": kind, "day": day,
        "spend": round(values["spend"], 2), "impressions": values["impressions"],
        "clicks": values["clicks"], "purchases": values["purchases"],
        "revenue": round(values["revenue"], 2), "currency": simulated.CURRENCY,
        "attribution_key": simulated.ATTRIBUTION_KEY, "source": simulated.SOURCE,
    }
