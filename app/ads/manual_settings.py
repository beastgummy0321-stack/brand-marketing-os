"""Editable manual handoff; local records never bind or mutate platform entities."""

from datetime import UTC, datetime
from urllib.parse import urlparse

from app.core.db import jsonb

# F29 Contract I: optimisation event, bid strategy, placement, pixel and UTM are choice fields of
# `app/ads/launch_settings.py` now. The rest stay free text per ad set, folded under 進階設定
# (F29 Unresolved 5): the landing URL and a retarget group's audience ID keep their required rule,
# the others are optional.
#
# F49 Contract B (decision 5): `readable` says whether any platform reader can see the value. A
# field declared `readable: False` is never asked of the user after launch: approving the launch
# is its one confirmation (`handoff_check._settings` files it under `confirmed_at_approval`).
# `readable: True` marks a value the Meta read does carry -- the retarget audience ID inside the ad
# set's `targeting`, the landing URL inside the ad creative's `object_story_spec` link -- so it is
# not declared, even though no comparison reads it yet (it stays a per-field eye confirm).
FIELDS = [
    {
        "key": "audience_source",
        "label": "受眾來源與納入條件",
        "section": "受眾",
        "required": False,
        "readable": False,
    },
    {
        "key": "audience_window",
        "label": "回溯期間（新客填不適用）",
        "section": "受眾",
        "required": False,
        "readable": False,
    },
    {
        "key": "audience_exclusions",
        "label": "排除條件（沒有請填無）",
        "section": "受眾",
        "required": False,
        "readable": False,
    },
    {
        "key": "audience_id",
        "label": "平台受眾 ID（再行銷必填）",
        "section": "受眾",
        "required": False,
        "readable": True,
    },
    {
        "key": "attribution",
        "label": "歸因期間",
        "section": "追蹤",
        "required": False,
        "readable": False,
    },
    {
        "key": "landing_url",
        "label": "落地頁網址",
        "section": "追蹤",
        "required": True,
        "readable": True,
    },
    {
        "key": "campaign_platform_id",
        "label": "平台活動 ID（手動紀錄）",
        "section": "上架紀錄",
        "required": False,
        "readable": False,
    },
    {
        "key": "group_platform_id",
        "label": "平台投放組 ID（手動紀錄）",
        "section": "上架紀錄",
        "required": False,
        "readable": False,
    },
    {
        "key": "ad_platform_ids",
        "label": "廣告對應（每行：系統廣告 ID = 平台廣告 ID）",
        "section": "上架紀錄",
        "required": False,
        "readable": False,
    },
    {
        "key": "execution_notes",
        "label": "實際執行差異與核對紀錄",
        "section": "上架紀錄",
        "required": False,
        "readable": False,
    },
]
# The keys no reader can see (decision 5).
DECLARED_UNREADABLE = frozenset(f["key"] for f in FIELDS if not f["readable"])
# The free-text keys that moved into launch settings. A value saved before stays in its record,
# readable and accepted back on save, but it is neither required nor part of the launch content.
LEGACY_KEYS = frozenset({"placements", "bidding", "optimization_event", "tracking", "utm"})


def validate_landing_url(value: str) -> None:
    """The one landing-URL rule (a group's setting and, F40-I04, the campaign default alike):
    a complete http/https URL with a host and no embedded credentials."""
    url = urlparse(value)
    if url.scheme not in {"http", "https"} or not url.netloc or url.username or url.password:
        raise ValueError("landing_url_invalid")


def handoff(campaign: dict) -> dict:
    context = campaign.get("context_json") or {}
    saved = context.get("manual_delivery") or {}
    # F40-I04: the landing URL given at create time (`context_json.landing_url`) is the default
    # of every group that has none of its own -- shown as the value with `sources.landing_url
    # = "campaign"` and counted as filled; a group's own saved value keeps winning.
    campaign_landing_url = context.get("landing_url") or None
    groups = []
    for group in campaign.get("groups") or []:
        record = saved.get(group["id"]) or {}
        values = dict(record.get("values") or {})
        sources = {}
        if campaign_landing_url and not values.get("landing_url"):
            values["landing_url"] = campaign_landing_url
            sources["landing_url"] = "campaign"
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
                "sources": sources,
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
    allowed = {f["key"] for f in FIELDS} | LEGACY_KEYS
    if set(values) - allowed or any(
        not isinstance(v, str) or len(v) > 2000 for v in values.values()
    ):
        raise ValueError("manual_settings_invalid")
    values = {k: v.strip() for k, v in values.items()}
    if values.get("landing_url"):
        validate_landing_url(values["landing_url"])
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
