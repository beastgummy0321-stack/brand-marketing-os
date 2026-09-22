"""Scoped immutable change lists; observation timestamps are not approval content."""

import hashlib
import json
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any

from app.ads import ads_learnings
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


def copy_fields(entity) -> dict[str, Any]:
    # Contract B: the return shape depends on the creative's own kind ({titles,bodies} lists for
    # dynamic, {body,title} strings otherwise) -- callers outside this module (e.g.
    # `handoff_check._settings`, which only ever sees non-dynamic new-ad creatives) still treat
    # every value as opaque, so a plain `dict[str, Any]` return type is the honest contract here,
    # not a narrower union pyright would otherwise infer and then reject mutation against.
    creative = entity.get("creative") or {}
    fields = creative.get("fields") or {}
    if creative.get("kind") == "dynamic":
        variants = fields.get("copy_variants") or {}
        return {
            "titles": list(variants.get("titles") or []),
            "bodies": list(variants.get("bodies") or []),
        }
    spec = fields.get("object_story_spec") or {}
    link, video = spec.get("link_data") or {}, spec.get("video_data") or {}
    return {
        "body": fields.get("body", link.get("message", video.get("message"))),
        "title": fields.get("title", link.get("name", video.get("title"))),
    }


def copy_editable(creative):
    """Contract B / correction 7 -- computed fresh from the creative's own kind and fields,
    never stored: a later re-sync (creative kind changes, or Meta finally returns titles/bodies)
    must change the answer without touching anything already approved."""
    creative = creative or {}
    kind = creative.get("kind")
    if kind in {"image", "video"}:
        return {"ok": True, "mode": "single", "reason": None}
    if kind == "dynamic":
        fields = creative.get("fields") or {}
        variants = fields.get("copy_variants") or {}
        catalog_only = fields.get("product_set_id") and not variants.get("titles") and not (
            variants.get("bodies")
        )
        if catalog_only:
            return {"ok": False, "mode": None, "reason": "商品目錄素材沒有可改的文字。"}
        return {"ok": True, "mode": "variants", "reason": None}
    if kind == "carousel":
        return {
            "ok": False,
            "mode": None,
            "reason": "此廣告包含多組輪播素材，不能用單一文案代表整組，請先檢視素材結構。",
        }
    return {"ok": False, "mode": None, "reason": "尚未讀到可辨識的素材，暫不能改文字。"}


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


def _copy_variants_after(value):
    """Correction 7: 0-5 items per list (Meta's own per-type maximum), at least one non-empty
    item overall -- not the original 1-10-each-required shape."""
    if not isinstance(value, dict) or not value or set(value) - {"titles", "bodies"}:
        raise ValueError("變更內容包含不支援的欄位。")
    result, total = {}, 0
    for key in ("titles", "bodies"):
        items = value.get(key, [])
        if not isinstance(items, list) or len(items) > 5:
            raise ValueError("每組文案最多 5 則。")
        cleaned = []
        for text in items:
            if not isinstance(text, str) or not text.strip() or len(text) > 10000:
                raise ValueError("請填寫要修改的文案。")
            cleaned.append(text)
        total += len(cleaned)
        result[key] = cleaned
    if total == 0:
        raise ValueError("請至少填寫一則文案。")
    return result


def after(kind, value, copy_mode=None):
    if kind == "copy" and copy_mode == "variants":
        return _copy_variants_after(value)
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


def angle(kind, value):
    """Contract C: a `pause` item may carry a free-text angle (<=40 chars, trimmed); part of the
    item itself, so it flows into `content_hash`/`premise_hash` like every other item field."""
    if value is None:
        return None
    if kind != "pause":
        raise ValueError("只有暫停動作可以標記這則廣告主打什麼。")
    if not isinstance(value, str):
        raise ValueError("主打內容格式無效。")
    text = value.strip()
    if not text:
        return None
    if len(text) > 40:
        raise ValueError("主打內容最多四十字。")
    return text


def build_item(conn, org, brand, campaign_id, item, c):
    if not isinstance(item, dict) or set(item) - {"kind", "target_id", "after", "reason", "angle"}:
        raise ValueError("請重新載入變更內容，不接受自行填寫平台現況。")
    kind = item.get("kind")
    entity = bindings.entity(conn, org, brand, campaign_id, item.get("target_id"))
    # Only an "ad" carries a creative at all -- a wrong-level submission (campaign/adset) falls
    # through to the existing single-copy validation below and is caught by the native_kind check
    # after `bindings.root()`, same as before this contract.
    editable = (
        copy_editable(entity.get("creative") or {})
        if kind == "copy" and entity["native_kind"] == "ad"
        else None
    )
    if editable is not None and not editable["ok"]:
        raise ValueError(editable["reason"] or "此素材沒有可改的文字。")
    result = after(kind, item.get("after"), editable["mode"] if editable else None)
    marked_angle = angle(kind, item.get("angle"))
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
        "angle": marked_angle,
        "context": context(c, kind),
        "media_identity": media_identity(entity) if kind == "copy" else None,
        "creative_snapshot": entity.get("creative") or {} if kind == "copy" else {},
        "premise_hash": digest(premise(entity, kind, c)),
    }


def get(conn, org, brand, campaign_id, set_id):
    # Lazy: `app.ads.adapters` -> `manual` -> `change_control_launch` -> this module would be an
    # import-time cycle if this were a module-level import (same seam `channels.py` uses for the
    # same reason).
    from app.ads import adapters

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
            # F22-I01: read-time only, never part of `item` itself -- `plan_json` and every hash
            # derived from it (`content_hash`, `premise_hash`) are computed before this point and
            # never touched here.
            "platform_url": adapters.platform_url(item["target"]),
            # Contract D: only a `pause` item can ever carry an `angle` (`build_item`'s
            # `angle()` refuses one on any other kind), so every other item's learning is
            # trivially "not recorded" without a lookup.
            "learning": (
                ads_learnings.view_for_item(conn, brand, item["id"])
                if item["kind"] == "pause" and item.get("angle")
                else {"recorded": False, "confidence": None, "count": 0}
            ),
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
    # Contract E: a `new_ad` item may name the ACTIVE ad it replaces (validated at creation,
    # `handoff_new_ad.create`) -- `replaces` is read live (the old ad's name may since have
    # changed); `follow_up` only once that item's own verification reads back `confirmed`, and
    # only while no non-superseded change set of this campaign already carries a `pause` item
    # targeting the old ad (the user may have proposed that pause through any route).
    new_ad_item = next(
        (i for i in result["plan_json"]["items"] if i["kind"] == "new_ad"), None
    )
    result["replaces"] = None
    result["follow_up"] = None
    if new_ad_item and new_ad_item.get("replaces_entity_id"):
        old_entity_id = new_ad_item["replaces_entity_id"]
        old = bindings.entity(conn, org, brand, campaign_id, old_entity_id)
        result["replaces"] = {"entity_id": old["id"], "name": old.get("name") or old["native_id"]}
        item_view = next(v for v in result["items"] if v["id"] == new_ad_item["id"])
        if item_view["verification_state"] == "confirmed" and not conn.execute(
            "SELECT 1 FROM ads_change_set WHERE org_id=%s AND brand_id=%s AND campaign_id=%s "
            "AND status != 'superseded' AND EXISTS (SELECT 1 FROM jsonb_array_elements("
            "plan_json->'items') AS elem WHERE elem->>'kind'='pause' AND elem->>'target_id'=%s) "
            "LIMIT 1",
            (org, brand, campaign_id, old_entity_id),
        ).fetchone():
            result["follow_up"] = {"kind": "pause_old", "entity_id": old_entity_id}
    return result
