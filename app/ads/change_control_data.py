"""Scoped immutable change lists; observation timestamps are not approval content."""

import hashlib
import json
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation

from app.ads import asset_binding_repository as bindings
from app.ads import repository as campaigns
from app.core import db, settings

_IDENTITY = (
    "id",
    "platform",
    "source_account",
    "native_kind",
    "native_id",
    "parent_native_kind",
    "parent_native_id",
)
_TARGET = (
    *_IDENTITY,
    "name",
    "budget_type",
    "budget_amount",
    "currency",
    "start_date",
    "end_date",
    "native_status",
)


def digest(value):
    return hashlib.sha256(
        json.dumps(
            value, sort_keys=True, ensure_ascii=False, default=str, separators=(",", ":")
        ).encode()
    ).hexdigest()


def budget_conditions(entity):
    return {
        key: str(entity[key]) if entity[key] is not None else None
        for key in ("currency", "start_date", "end_date", "budget_type")
        if key in entity
    }


def unchanged_readback(item):
    evidence = item.get("evidence_json") or {}
    try:
        observed = datetime.fromisoformat(str(evidence.get("observed_at")))
        age = db.now_utc() - observed if observed.tzinfo is not None else None
        recent = age is not None and timedelta(0) <= age < timedelta(hours=24)
    except ValueError:
        return False
    return bool(
        recent
        and item["verification_state"] == "pending"
        and evidence.get("setting_matches") is False
        and all(
            evidence.get("observed", {}).get(key) == item["before"].get(key)
            for key in item["after"]
        )
    )


def can_revise(value):
    return value["status"] in {"draft", "deferred", "rejected"} or (
        value["status"] == "approved"
        and any(i["verification_state"] != "confirmed" for i in value["items"])
        and all(
            i["verification_state"] in {"confirmed", "stale", "deviated"} or unchanged_readback(i)
            for i in value["items"]
        )
    )


def lock(conn, org, brand):
    conn.execute(
        "SELECT pg_advisory_xact_lock(hashtextextended(%s,0))", (f"ads-budget:{org}:{brand}",)
    )


def campaign(conn, org, brand, campaign_id):
    value = campaigns.get_campaign(conn, org, brand, campaign_id)
    if value is None:
        raise ValueError("找不到此品牌的活動。")
    return value


def context(value, kind: str | None = "copy"):
    if kind not in {"copy", "launch"}:
        return {}
    return {
        key: value.get(key)
        for key in ("goal_text", "objective", "success_metric", "success_target")
    }


def month(value):
    try:
        if not isinstance(value, str) or len(value) != 7:
            raise ValueError
        date.fromisoformat(value + "-01")
    except ValueError:
        raise ValueError("請選擇有效的預算月份。") from None
    return value


def operation(value):
    if (
        not isinstance(value, str)
        or not 1 <= len(value) <= 128
        or any(not (c.isascii() and (c.isalnum() or c in "-_:")) for c in value)
    ):
        raise ValueError("請重新開啟變更清單後再送出。")
    return value


def copy_fields(entity):
    creative = entity.get("creative") or {}
    fields = creative.get("fields") or {}
    spec = fields.get("object_story_spec") or {}
    link, video = spec.get("link_data") or {}, spec.get("video_data") or {}
    return {
        "body": fields.get("body", link.get("message", video.get("message"))),
        "title": fields.get("title", link.get("name", video.get("title"))),
    }


def media_identity(entity):
    creative = entity.get("creative") or {}
    if creative.get("kind") not in {"image", "video"}:
        return None
    fields = creative.get("fields") or {}
    spec = fields.get("object_story_spec") or {}
    link, video = spec.get("link_data") or {}, spec.get("video_data") or {}
    value = fields.get("image_hash") or link.get("image_hash") or fields.get("video_id")
    value = value or video.get("video_id")
    return {"kind": creative["kind"], "platform_media_id": str(value)} if value else None


def before(entity, kind):
    if kind == "copy":
        return copy_fields(entity)
    if kind == "budget":
        return {
            "daily_amount": entity.get("budget_amount")
            if entity.get("budget_type") == "daily"
            else None
        }
    return {"status": entity.get("native_status")}


def premise(entity, kind, c):
    result = {
        "identity": {k: entity.get(k) for k in _IDENTITY},
        "context": context(c, kind),
        "before": before(entity, kind),
    }
    if kind == "copy":
        result["creative_hash"] = bindings.creative_hash(entity.get("creative") or {})
    if kind == "budget":
        result["budget"] = {
            k: entity.get(k) for k in ("budget_type", "currency", "start_date", "end_date")
        }
    return result


def after(kind, value):
    keys = {"copy": {"body", "title"}, "budget": {"daily_amount"}, "pause": {"status"}}
    if kind not in keys or not isinstance(value, dict) or not value or set(value) - keys[kind]:
        raise ValueError("變更內容包含不支援的欄位。")
    if kind == "copy":
        if any(not isinstance(v, str) or not v.strip() or len(v) > 10000 for v in value.values()):
            raise ValueError("請填寫要修改的文案。")
        return value
    if kind == "pause":
        if value != {"status": "PAUSED"}:
            raise ValueError("此清單只支援明確的暫停操作。")
        return value
    try:
        amount = Decimal(str(value.get("daily_amount")))
        if not amount.is_finite() or amount < 0:
            raise ValueError
    except (ValueError, InvalidOperation):
        raise ValueError("每日預算必須是大於或等於零的金額。") from None
    return {"daily_amount": float(amount)}


def build_item(conn, org, brand, campaign_id, item, c):
    if not isinstance(item, dict) or set(item) - {"kind", "target_id", "after", "reason"}:
        raise ValueError("請重新載入變更內容，不接受自行填寫平台現況。")
    kind = item.get("kind")
    result = after(kind, item.get("after"))
    entity = bindings.entity(conn, org, brand, campaign_id, item.get("target_id"))
    if kind == "copy" and (entity.get("creative") or {}).get("kind") in {"dynamic", "carousel"}:
        raise ValueError("此廣告包含多組動態或輪播素材，不能用單一文案代表整組，請先檢視素材結構。")
    bindings.root(conn, org, brand, campaign_id, entity)
    if (kind == "copy" and entity["native_kind"] != "ad") or (
        kind == "budget" and entity["native_kind"] not in {"campaign", "adset"}
    ):
        raise ValueError("此操作不適用於選定的平台層級。")
    reason = item.get("reason")
    if not isinstance(reason, str) or not reason.strip() or len(reason) > 2000:
        raise ValueError("請說明這項變更的原因。")
    return {
        "id": db.new_id("adx"),
        "kind": kind,
        "target_id": entity["id"],
        "target": {k: entity.get(k) for k in _TARGET},
        "before": before(entity, kind),
        "after": result,
        "reason": reason.strip(),
        "context": context(c, kind),
        "media_identity": media_identity(entity) if kind == "copy" else None,
        "creative_snapshot": entity.get("creative") or {} if kind == "copy" else {},
        "premise_hash": digest(premise(entity, kind, c)),
    }


def get(conn, org, brand, campaign_id, set_id):
    campaign(conn, org, brand, campaign_id)
    row = conn.execute(
        "SELECT * FROM ads_change_set WHERE org_id=%s AND brand_id=%s AND campaign_id=%s AND id=%s",
        (org, brand, campaign_id, set_id),
    ).fetchone()
    if row is None:
        raise ValueError("找不到此品牌的變更清單。")
    result = dict(row)
    actions = {
        r["id"]: dict(r)
        for r in conn.execute(
            "SELECT * FROM ads_action WHERE org_id=%s AND brand_id=%s AND campaign_id=%s "
            "AND change_set_id=%s",
            (org, brand, campaign_id, set_id),
        ).fetchall()
    }
    result["items"] = []
    for item in result["plan_json"]["items"]:
        action = actions.get(item["id"], {})
        view = {
            **item,
            **{k: action.get(k) for k in ("reported_at", "first_observed_at", "verified_at")},
            "verification_state": action.get("verification_state", "pending"),
            "evidence_json": action.get("evidence_json", {}),
        }
        increases = item["kind"] in {"launch", "new_ad"} or (
            item["kind"] == "budget"
            and (
                item["before"].get("daily_amount") is None
                or item["after"]["daily_amount"] > item["before"]["daily_amount"]
            )
        )
        if (
            result["status"] == "approved"
            and increases
            and view["verification_state"] != "confirmed"
            and result["month"] != settings.today_for_org(conn, org_id=org).strftime("%Y-%m")
        ):
            view["verification_state"] = "stale"
            view["evidence_json"] = {
                **view["evidence_json"],
                "message": "執行月份已改變，新增花費需重新核對月預算與核准。",
            }
        result["items"].append(view)
    result["reason"] = result.pop("decision_reason")
    result["can_revise"] = can_revise(result)
    result["review_id"] = result["plan_json"].get("review_id")
    result["recommendation_id"] = result["plan_json"].get("recommendation_id")
    result["material_task_id"] = result["plan_json"].get("material_task_id")
    result["material_revision"] = result["plan_json"].get("material_revision")
    return result
