"""Meta native read adapter; field contracts follow Meta's official Business SDK.
https://github.com/facebook/facebook-python-business-sdk/tree/main/facebook_business/adobjects
Field declarations do not establish live account permissions.
"""

from datetime import date
from decimal import Decimal, InvalidOperation

from app.ads.adapters.external import SourcePage
from app.core.db import now_utc
from app.meta import repository as source


def _number(value):
    if value is None:
        return None
    try:
        number = Decimal(str(value))
        return float(number) if number.is_finite() else None
    except (InvalidOperation, ValueError):
        return None


def _date(value):
    try:
        return date.fromisoformat(str(value)[:10]).isoformat() if value else None
    except ValueError:
        return None


def _entity(item, kind, account):
    if not item.get("id") or str(item.get("account_id")) != account["account_id"]:
        raise ValueError("平台物件缺少可核對的同帳號識別。")
    fields = {
        "name": "name",
        "objective": "objective",
        "native_status": "effective_status",
        "start_date": "start_time",
        "end_date": "stop_time" if kind == "campaign" else "end_time",
    }
    result = {
        "platform": "meta",
        "source_account": account["account_id"],
        "native_id": str(item["id"]),
        "native_kind": kind,
        "native_label": kind,
        "availability": {},
        "last_attempt_at": now_utc(),
        "last_success_at": now_utc(),
        "sync_status": "success",
        "sync_error": None,
    }
    for target, key in fields.items():
        value = _date(item.get(key)) if target.endswith("date") else item.get(key)
        result[target] = value
        result["availability"][target] = "available" if value is not None else "unknown"
    if kind != "campaign":
        parent_key = "campaign_id" if kind == "adset" else "adset_id"
        if not item.get(parent_key):
            raise ValueError("平台物件缺少父層識別。")
        result.update(
            parent_native_kind="campaign" if kind == "adset" else "adset",
            parent_native_id=str(item[parent_key]),
        )
    if kind != "ad":
        raw = {key: item[key] for key in ("daily_budget", "lifetime_budget") if key in item}
        result.update(
            budget_type="lifetime"
            if _number(raw.get("lifetime_budget"))
            else "daily"
            if _number(raw.get("daily_budget"))
            else "unknown",
            budget_raw={
                "values": raw,
                "unit": "platform_minor_unit",
                "conversion": "unverified_currency_denominator",
            },
            currency=account.get("currency"),
            budget_source="graph",
            budget_amount=None,
        )
        result["availability"]["budget_amount"] = "unknown"
    return result


def creative_summary(value):
    """Preserve readable fields only. A thumbnail is never the video source."""
    if not isinstance(value, dict):
        return {"kind": "unknown", "availability": "unavailable", "missing": ["creative"]}
    spec = value.get("object_story_spec") or {}
    link = spec.get("link_data") or {}
    video = spec.get("video_data") or {}
    carousel = link.get("child_attachments")
    dynamic = bool(value.get("asset_feed_spec") or value.get("product_set_id"))
    kind = (
        "dynamic"
        if dynamic
        else "carousel"
        if carousel
        else "video"
        if (value.get("video_id") or video.get("video_id"))
        else "image"
        if (value.get("image_hash") or value.get("image_url") or link.get("image_hash"))
        else "unknown"
    )
    keys = (
        "id",
        "body",
        "title",
        "image_hash",
        "image_url",
        "video_id",
        "thumbnail_url",
        "object_story_spec",
        "asset_feed_spec",
        "product_set_id",
    )
    result = {
        "kind": kind,
        "fields": {key: value[key] for key in keys if key in value},
        "missing": [key for key in keys if key not in value],
        "availability": "partial" if dynamic or kind == "unknown" else "available",
        "video_original": None,
        "video_original_availability": "unavailable",
        "thumbnail_is_original": False,
        "observed_at": now_utc(),
    }
    if dynamic:
        result["unsupported"] = "動態／商品目錄素材無法完整還原。"
    return result


def observation(item, level, account):
    """Never interpret absent purchase actions as zero or infer revenue from ROAS."""
    if str(item.get("account_id")) != account["account_id"]:
        raise ValueError("平台成效帳號不符。")
    native_id = item.get({"campaign": "campaign_id", "adset": "adset_id", "ad": "ad_id"}[level])
    day = _date(item.get("date_start"))
    if not native_id or not day or item.get("date_stop", day) != day:
        raise ValueError("平台未回傳可核對的單日成效。")
    metrics = {key: _number(item.get(key)) for key in ("spend", "impressions", "clicks")}
    # The legacy source facade defines synonymous purchase actions once.
    purchase = source.external_purchase_values(item.get("actions"), item.get("action_values"))
    metrics.update(purchases=purchase["purchases"], revenue=purchase["revenue"])
    return {
        "native_kind": level,
        "native_id": str(native_id),
        "day": day,
        "metric_scope": level,
        "attribution_key": "7d_click+1d_view:" + (purchase["action_type"] or "unavailable"),
        "currency": item.get("account_currency") or account.get("currency"),
        **metrics,
        "availability": {
            key: "available" if val is not None else "unavailable" for key, val in metrics.items()
        },
        "source": "graph",
    }


class MetaReader:
    def accounts(self, conn, org_id, brand_id):
        return source.external_bound_accounts(conn, org_id, brand_id)

    def _page(self, conn, org_id, brand_id, account, section, **kwargs):
        return source.read_external_page(
            conn, org_id, brand_id, account["account_id"], section, **kwargs
        )

    def list_existing(self, conn, org_id, brand_id, account, *, cursor=None, **kwargs):
        page = self._page(
            conn, org_id, brand_id, account, "campaigns", cursor=(cursor or {}).get("after")
        )
        return SourcePage(
            [_entity(item, "campaign", account) for item in page["data"]],
            {"after": page["cursor"]} if page["cursor"] else None,
        )

    def read_structure(self, conn, org_id, brand_id, account, *, native_id, cursor=None, **kwargs):
        phase = (cursor or {}).get("phase", "campaign")
        if phase not in {"campaign", "adsets", "ads"}:
            raise ValueError("來源結構游標無效。")
        page = self._page(
            conn,
            org_id,
            brand_id,
            account,
            phase,
            native_id=native_id,
            cursor=(cursor or {}).get("after"),
        )
        kind = {"campaign": "campaign", "adsets": "adset", "ads": "ad"}[phase]
        items = []
        for item in page["data"]:
            if (kind == "campaign" and str(item.get("id")) != native_id) or (
                kind != "campaign" and str(item.get("campaign_id")) != native_id
            ):
                raise ValueError("平台物件不屬於此活動。")
            items.append(_entity(item, kind, account))
        next_phase = {"campaign": "adsets", "adsets": "ads"}.get(phase)
        next_cursor = (
            {"phase": phase, "after": page["cursor"]}
            if page["cursor"]
            else {"phase": next_phase}
            if next_phase
            else None
        )
        return SourcePage(items, next_cursor)

    def read_creatives(self, conn, org_id, brand_id, account, *, native_id, cursor=None, **kwargs):
        page = self._page(
            conn,
            org_id,
            brand_id,
            account,
            "creatives",
            native_id=native_id,
            cursor=(cursor or {}).get("after"),
        )
        items = []
        for item in page["data"]:
            if str(item.get("campaign_id")) != native_id:
                raise ValueError("平台素材不屬於此活動。")
            entity = _entity(item, "ad", account)
            # This phase owns creative, not the structure/name/status fields.
            items.append(
                {
                    key: entity[key]
                    for key in ("platform", "source_account", "native_kind", "native_id")
                }
                | {"creative": creative_summary(item.get("creative"))}
            )
        return SourcePage(items, {"after": page["cursor"]} if page["cursor"] else None)

    def read_observations(
        self, conn, org_id, brand_id, account, *, native_id, cursor=None, start, end, **kwargs
    ):
        phase = (cursor or {}).get("phase", "campaign")
        if phase not in {"campaign", "adset", "ad"}:
            raise ValueError("來源成效游標無效。")
        page = self._page(
            conn,
            org_id,
            brand_id,
            account,
            "insights",
            native_id=native_id,
            level=phase,
            cursor=(cursor or {}).get("after"),
            start=start,
            end=end,
        )
        if any(str(item.get("campaign_id")) != native_id for item in page["data"]):
            raise ValueError("平台成效不屬於此活動。")
        following = {"campaign": "adset", "adset": "ad"}.get(phase)
        return SourcePage(
            [observation(item, phase, account) for item in page["data"]],
            {"phase": phase, "after": page["cursor"]}
            if page["cursor"]
            else {"phase": following}
            if following
            else None,
        )
