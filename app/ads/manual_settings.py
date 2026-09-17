"""Editable manual handoff; local records never bind or mutate platform entities."""

from datetime import UTC, datetime
from urllib.parse import urlparse

from app.core.db import jsonb

FIELDS = [
    {"key": "audience_source", "label": "受眾來源與納入條件", "section": "受眾", "required": True},
    {
        "key": "audience_window",
        "label": "回溯期間（新客填不適用）",
        "section": "受眾",
        "required": True,
    },
    {
        "key": "audience_exclusions",
        "label": "排除條件（沒有請填無）",
        "section": "受眾",
        "required": True,
    },
    {
        "key": "audience_id",
        "label": "平台受眾 ID（再行銷必填）",
        "section": "受眾",
        "required": False,
    },
    {"key": "placements", "label": "版位", "section": "受眾", "required": True},
    {"key": "bidding", "label": "出價策略", "section": "受眾", "required": True},
    {"key": "optimization_event", "label": "優化事件", "section": "追蹤", "required": True},
    {"key": "attribution", "label": "歸因期間", "section": "追蹤", "required": True},
    {
        "key": "tracking",
        "label": "追蹤來源／像素 ID 與驗證方式",
        "section": "追蹤",
        "required": True,
    },
    {"key": "landing_url", "label": "落地頁網址", "section": "追蹤", "required": True},
    {"key": "utm", "label": "UTM 參數（不使用請寫原因）", "section": "追蹤", "required": True},
    {
        "key": "campaign_platform_id",
        "label": "平台活動 ID（手動紀錄）",
        "section": "上架紀錄",
        "required": False,
    },
    {
        "key": "group_platform_id",
        "label": "平台投放組 ID（手動紀錄）",
        "section": "上架紀錄",
        "required": False,
    },
    {
        "key": "ad_platform_ids",
        "label": "廣告對應（每行：系統廣告 ID = 平台廣告 ID）",
        "section": "上架紀錄",
        "required": False,
    },
    {
        "key": "execution_notes",
        "label": "實際執行差異與核對紀錄",
        "section": "上架紀錄",
        "required": False,
    },
]


def handoff(campaign: dict) -> dict:
    saved = (campaign.get("context_json") or {}).get("manual_delivery") or {}
    groups = []
    for group in campaign.get("groups") or []:
        record = saved.get(group["id"]) or {}
        values = record.get("values") or {}
        missing = [f["label"] for f in FIELDS if f["required"] and not values.get(f["key"])]
        if group.get("role") == "retarget" and not values.get("audience_id"):
            missing.append("再行銷受眾 ID")
        if not (group.get("start_date") or campaign.get("start_date")):
            missing.append("投放開始日期")
        if not (group.get("end_date") or campaign.get("end_date")):
            missing.append("投放結束日期")
        groups.append(
            {
                "id": group["id"],
                "name": group["name"],
                "values": values,
                "missing": missing,
                "status": "待補設定" if missing else "資料已填齊，待平台核對",
                "saved_at": record.get("saved_at"),
                "saved_by": record.get("saved_by"),
                "ads": [{"id": a["id"], "name": a["name"]} for a in group.get("ads") or []],
            }
        )
    return {
        "fields": FIELDS,
        "groups": groups,
        "pending_count": sum(bool(g["missing"]) for g in groups),
    }


def save(
    conn, org_id: str, brand_id: str, campaign_id: str, group_id: str, values: dict, *, actor: str
) -> dict:
    from app.ads import repository

    # Serialize edits to the context document. Other groups and field_sources survive.
    row = conn.execute(
        "SELECT * FROM ads_campaign WHERE org_id = %s AND brand_id = %s AND id = %s FOR UPDATE",
        (org_id, brand_id, campaign_id),
    ).fetchone()
    if row is None:
        raise ValueError("campaign_unknown")
    if row["status"] == "closed":
        raise ValueError("campaign_closed")
    group = repository.get_group(conn, org_id, brand_id, group_id)
    if group is None or group["campaign_id"] != campaign_id:
        raise ValueError("group_unknown")
    allowed = {f["key"] for f in FIELDS}
    if set(values) - allowed or any(
        not isinstance(v, str) or len(v) > 2000 for v in values.values()
    ):
        raise ValueError("manual_settings_invalid")
    values = {k: v.strip() for k, v in values.items()}
    if values.get("landing_url"):
        url = urlparse(values["landing_url"])
        if url.scheme not in {"http", "https"} or not url.netloc or url.username or url.password:
            raise ValueError("landing_url_invalid")
    ad_ids = {
        r["id"]
        for r in conn.execute(
            "SELECT id FROM ads_ad WHERE org_id = %s AND brand_id = %s AND group_id = %s",
            (org_id, brand_id, group_id),
        ).fetchall()
    }
    seen = set()
    for line in values.get("ad_platform_ids", "").splitlines():
        if not line.strip():
            continue
        local, separator, platform = line.partition("=")
        local = local.strip()
        if not separator or local not in ad_ids or not platform.strip() or local in seen:
            raise ValueError("ad_mapping_invalid")
        seen.add(local)
    context = dict(row["context_json"] or {})
    records = dict(context.get("manual_delivery") or {})
    records[group_id] = {
        "values": values,
        "saved_at": datetime.now(UTC).isoformat(),
        "saved_by": actor,
    }
    context["manual_delivery"] = records
    conn.execute(
        "UPDATE ads_campaign SET context_json = %s, updated_at = now()"
        " WHERE org_id = %s AND brand_id = %s AND id = %s",
        (jsonb(context), org_id, brand_id, campaign_id),
    )
    detail = repository.campaign_detail(conn, org_id, brand_id, campaign_id)
    assert detail is not None
    return detail
