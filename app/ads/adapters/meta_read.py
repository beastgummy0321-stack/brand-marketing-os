"""Meta native read adapter; field contracts follow Meta's official Business SDK.
https://github.com/facebook/facebook-python-business-sdk/tree/main/facebook_business/adobjects
Field declarations do not establish live account permissions.
"""

import re
from datetime import date
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from app.ads import external_repository
from app.ads.adapters.external import SourcePage, SourceReadError
from app.ads.external_repository import MONTHLY_BUDGET_ATTRIBUTION_KEY
from app.core.db import now_utc
from app.meta import repository as source

# Meta Marketing API currency offsets. Source: https://developers.facebook.com/docs/
# marketing-api/currencies (fetched 2026-09-20): "Each currency has an offset which specifies
# how the platform handles its subdivisions." An amount in API minor units is divided by the
# currency's offset to get the amount in the account currency. Cross-checked read-only against
# campaign 120250284145340671 on TWD account 368741390835357: daily_budget "1900" only holds
# together against that campaign's actual daily spend (1,639-2,383 TWD) at offset 1 (NT$1,900/day);
# offset 100 (NT$19/day) is impossible against that spend. See docs/architecture/ads.md §6.12.
# A currency in neither set below resolves to budget_amount=None with a reason; never a default.
_OFFSET_1_CURRENCIES = frozenset({
    "CLP", "COP", "CRC", "HUF", "IDR", "ISK", "JPY", "KRW", "PYG", "TWD", "VND",
})
_OFFSET_100_CURRENCIES = frozenset({
    "DZD", "ARS", "AUD", "BHD", "BDT", "BOB", "BGN", "BRL", "GBP", "CAD", "CNY", "HRK", "CZK",
    "DKK", "EGP", "EUR", "GTQ", "HNL", "HKD", "INR", "ILS", "JOD", "KES", "LVL", "LTL", "MOP",
    "MYR", "MXN", "NZD", "NIO", "NGN", "NOK", "PKR", "PEN", "PHP", "PLN", "QAR", "RON", "RUB",
    "SAR", "RSD", "SGD", "SKK", "ZAR", "SEK", "CHF", "THB", "TRY", "AED", "UAH", "USD", "UYU",
    "VEF", "FBZ", "VES",
})


def _budget_minor_unit_amount(raw_value, currency):
    """Resolve one Meta minor-unit budget into the account currency, or explain why not.

    Returns (amount: float|None, reason: str). `reason` is always a machine-readable token:
    an "offset_table:<n>" trail for a resolved amount, or the specific block for an unresolved
    one. Unknown is never a number — a currency absent from both documented offset sets stays
    None rather than guessing 1 or 100.
    """
    if not currency or not re.fullmatch(r"[A-Z]{3}", currency):
        return None, "currency_absent"
    if currency in _OFFSET_1_CURRENCIES:
        offset, places = 1, 0
    elif currency in _OFFSET_100_CURRENCIES:
        offset, places = 100, 2
    else:
        return None, "currency_not_in_offset_table"
    if raw_value is None:
        return None, "no_budget_value"
    try:
        units = Decimal(str(raw_value))
    except InvalidOperation:
        return None, "no_budget_value"
    if not units.is_finite():
        return None, "no_budget_value"
    # Meta always reports minor units as integers, so this division is exact for well-formed
    # platform data; ROUND_HALF_UP is a defensive fallback only, never a source of precision
    # loss on a resolved two-decimal currency (Decimal throughout, no binary float division).
    quantum = Decimal(1).scaleb(-places)
    amount = (units / Decimal(offset)).quantize(quantum, rounding=ROUND_HALF_UP)
    return float(amount), f"offset_table:{offset}"


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
        "native_label": {"campaign": "活動", "adset": "廣告組", "ad": "廣告"}[kind],
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
        budget_type = (
            "lifetime"
            if _number(raw.get("lifetime_budget"))
            else "daily"
            if _number(raw.get("daily_budget"))
            else "unknown"
        )
        currency = account.get("currency")
        if budget_type == "unknown":
            amount, conversion = None, "no_budget_value"
        else:
            raw_value = raw.get("lifetime_budget" if budget_type == "lifetime" else "daily_budget")
            amount, conversion = _budget_minor_unit_amount(raw_value, currency)
        budget_raw = {
            "values": raw,
            "unit": "minor_units" if amount is not None else "unknown",
            "conversion": conversion,
        }
        # A campaign whose raw payload carries neither budget field is, by Meta's own API
        # semantics, an ad-set-budget (ABO) campaign -- the real budget lives on its ad sets.
        # `budget_type` stays "unknown" (the schema has no `None` to spare, F25-I01 2026-09-22
        # "ABO without a schema change") -- only this marker distinguishes "verified: no campaign
        # budget, look at the children" from "unknown: this campaign was simply never read".
        # Ad sets keep today's behaviour: this signal only ever concerns the campaign's own
        # missing budget, never a sibling.
        if kind == "campaign" and not raw:
            budget_raw["owner"] = "children_verified"
        result.update(
            budget_type=budget_type,
            budget_raw=budget_raw,
            currency=currency,
            budget_source="graph",
            budget_amount=amount,
        )
        result["availability"]["budget_amount"] = "available" if amount is not None else "unknown"
    return result


def _verified_snapshot(raw, kind, account):
    """Partial reads never erase fields the provider did not return."""
    parsed = _entity(raw, kind, account)
    keys = {
        "platform",
        "source_account",
        "native_kind",
        "native_id",
        "parent_native_kind",
        "parent_native_id",
    }
    for target, field in (
        ("native_status", "effective_status"),
        ("name", "name"),
        ("objective", "objective"),
        ("start_date", "start_time"),
        ("end_date", "stop_time" if kind == "campaign" else "end_time"),
    ):
        if field in raw:
            keys.add(target)
    if kind != "ad" and any(field in raw for field in ("daily_budget", "lifetime_budget")):
        keys.update({"budget_type", "budget_amount", "budget_raw", "currency", "budget_source"})
    return {key: value for key, value in parsed.items() if key in keys}


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


# Meta campaign objective -> this ad's own "result" (F16-I03, docs/architecture/ads.md §6.13).
# ODAX (current, "OUTCOME_*") and pre-ODAX legacy objective names Meta still accepts both map
# here; the shared vocabulary the rest of the app reads is only `result_kind`/`result_count`/
# `cost_per_result` — this table, and the Meta action_type synonyms it points at, are the one
# place that knows Meta's own naming. An objective absent from this table has no defined result
# and stays NULL — never a fallback to purchase; that silent fallback is exactly the false
# stop-loss on incidental purchases this ticket removes.
_SALES_OBJECTIVES = frozenset({"OUTCOME_SALES", "CONVERSIONS", "PRODUCT_CATALOG_SALES"})
_OBJECTIVE_RESULT_ACTIONS: dict[str, tuple[str, tuple[str, ...]]] = {
    "OUTCOME_ENGAGEMENT": ("engagement", ("post_engagement", "page_engagement")),
    "POST_ENGAGEMENT": ("engagement", ("post_engagement", "page_engagement")),
    "OUTCOME_TRAFFIC": ("link_click", ("link_click", "landing_page_view")),
    "LINK_CLICKS": ("link_click", ("link_click", "landing_page_view")),
    "OUTCOME_LEADS": ("lead", ("lead",)),
    "LEAD_GENERATION": ("lead", ("lead",)),
    "OUTCOME_APP_PROMOTION": ("app_install", ("mobile_app_install",)),
    "APP_INSTALLS": ("app_install", ("mobile_app_install",)),
    "VIDEO_VIEWS": ("video_view", ("video_view",)),
    "MESSAGES": ("message", ("onsite_conversion.messaging_conversation_started_7d",)),
    "STORE_VISITS": ("store_visit", ("store_visit",)),
}

# Sentinel, not None: `read_monthly` never looks up an objective (account-wide monthly rollups
# aren't judged per ad — `_save_monthly` validates that dict shape strictly against
# `ExternalObservation`), so its `observation()` calls must add no result keys at all.
# `read_observations` always passes an explicit `objective` (itself may be None when the
# entity hasn't synced one yet), which is how the two call sites stay distinguishable.
_NO_OBJECTIVE = object()

# The attribution setting every result count below is read under. A fixed literal today, not a
# parse of `attribution_key` — shared code (review_evidence.aggregate) must learn this only
# through `result_attribution`, never by splitting the Meta-formatted `attribution_key` string.
_ATTRIBUTION_WINDOW = "7d_click+1d_view"


def _objective_result(objective, actions, purchase, attribution):
    """This campaign's own (label, count, action, attribution) — reusing the one purchase
    definition for sales objectives, and never letting any other objective read a stray purchase
    as its result. `action`/`attribution` are only filled alongside a known `count` (F16-I03
    repair): an unknown count means no specific action was actually read that day."""
    if objective in _SALES_OBJECTIVES:
        count = purchase["purchases"]
        action = purchase["action_type"] if count is not None else None
        return "purchase", count, action, (attribution if count is not None else None)
    mapped = _OBJECTIVE_RESULT_ACTIONS.get(objective)
    if mapped is None:
        return None, None, None, None
    label, action_types = mapped
    counts = {a.get("action_type"): a.get("value") for a in (actions or []) if isinstance(a, dict)}
    for action_type in action_types:
        if action_type in counts:
            count = _number(counts[action_type])
            if count is None:
                return label, None, None, None
            return label, count, action_type, attribution
    return label, None, None, None


def observation(item, level, account, objective=_NO_OBJECTIVE):
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
    result = {
        "native_kind": level,
        "native_id": str(native_id),
        "day": day,
        "metric_scope": level,
        "attribution_key": _ATTRIBUTION_WINDOW + ":" + (purchase["action_type"] or "unavailable"),
        "currency": item.get("account_currency") or account.get("currency"),
        **metrics,
        "availability": {
            key: "available" if val is not None else "unavailable" for key, val in metrics.items()
        },
        "source": "graph",
    }
    if objective is not _NO_OBJECTIVE:
        (
            result["result_kind"],
            result["result_count"],
            result["result_action"],
            result["result_attribution"],
        ) = _objective_result(objective, item.get("actions"), purchase, _ATTRIBUTION_WINDOW)
    return result


def result_kind_for_objective(objective) -> str | None:
    """F16-I04: this adapter's own objective -> result-kind mapping (§0 "the objective -> result
    mapping lives in the Meta adapter"), exposed to shared code (`app/ads/external_sync.py`)
    through `MetaReader.result_kind()` so nothing outside this file ever reads a Meta objective
    string. Reuses the exact same tables `_objective_result` keys observations by -- one
    definition, not a second one that could drift. An objective absent from both tables (or
    `None`, not yet synced) has no defined result and stays `None` -- never a fallback to
    `"purchase"`."""
    if objective in _SALES_OBJECTIVES:
        return "purchase"
    mapped = _OBJECTIVE_RESULT_ACTIONS.get(objective)
    return mapped[0] if mapped else None


# F22-I01: this adapter's own read-time deep link into Meta Ads Manager, one object kind per
# entry point Ads Manager can select directly by id (campaign/adset/ad) -- an object kind absent
# from this table (or, in practice, none today) has no defined link and stays unmapped, never a
# guessed URL shape.
_MANAGE_SEGMENT = {"campaign": "campaigns", "adset": "adsets", "ad": "ads"}
_MANAGE_SELECTED_PARAM = {
    "campaign": "selected_campaign_ids", "adset": "selected_adset_ids", "ad": "selected_ad_ids",
}


def platform_url(target: dict) -> str | None:
    """This change item's own target (`app/ads/change_control_data.py::_TARGET` shape) -> a Meta
    Ads Manager deep link, computed at read time only -- never written to `plan_json`, so no
    approval hash ever depends on it (F22-I01, "↗ 打開平台"). `None` when the native kind isn't
    one Ads Manager can select directly, or an identifying field (`native_id`/`source_account`)
    is missing -- the caller falls back to the target's own name/native id, never a broken link.
    """
    native_kind = target.get("native_kind")
    native_id = target.get("native_id")
    account = target.get("source_account")
    if native_kind not in _MANAGE_SEGMENT or not native_id or not account:
        return None
    segment, param = _MANAGE_SEGMENT[native_kind], _MANAGE_SELECTED_PARAM[native_kind]
    return (
        f"https://adsmanager.facebook.com/adsmanager/manage/{segment}"
        f"?act={account}&{param}={native_id}"
    )


class MetaReader:
    def sync_scopes(self, conn):
        return source.external_sync_scopes(conn)

    def result_kind(self, entity: dict) -> str | None:
        """F16-I04: result kind for this synced entity -- the campaign-level entity's own
        `objective` field (`_entity()`'s raw Meta string), mapped through this file's one
        objective -> result table. `app/ads/external_sync.py` calls this instead of reading
        `entity["objective"]` itself -- shared code never branches on a Meta objective string."""
        return result_kind_for_objective(entity.get("objective"))

    def accounts(self, conn, org_id, brand_id):
        return source.external_bound_accounts(conn, org_id, brand_id)

    def _page(self, conn, org_id, brand_id, account, section, **kwargs):
        try:
            return source.read_external_page(
                conn, org_id, brand_id, account["account_id"], section, **kwargs
            )
        except source.ExternalReadError as exc:
            raise SourceReadError(str(exc), exc.code) from None

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
        # The result mapping is keyed by the campaign's own Meta objective at every level
        # (adset/ad observations still belong to one campaign) — looked up once per page.
        objective = external_repository.campaign_objective(
            conn, org_id, brand_id, "meta", account["account_id"], native_id
        )
        following = {"campaign": "adset", "adset": "ad"}.get(phase)
        return SourcePage(
            [observation(item, phase, account, objective) for item in page["data"]],
            {"phase": phase, "after": page["cursor"]}
            if page["cursor"]
            else {"phase": following}
            if following
            else None,
        )

    def read_monthly(self, conn, org_id, brand_id, account, *, start, end, cursor=None, **kwargs):
        # A successful empty account query is evidence; an absent/invalid field is not.
        start, end = str(start), str(end)
        try:
            first, last = date.fromisoformat(start), date.fromisoformat(end)
            if first.day != 1 or first > last or first.strftime("%Y-%m") != last.strftime("%Y-%m"):
                raise ValueError
            ZoneInfo(account.get("timezone_name") or "")
            if not re.fullmatch(r"[A-Z]{3}", account.get("currency") or ""):
                raise ValueError
        except (ValueError, ZoneInfoNotFoundError):
            raise SourceReadError(
                "帳戶月份、幣別或時區無法核對。", "invalid_monthly_scope"
            ) from None
        query = {
            "start": start,
            "end": end,
            "account_id": account["account_id"],
            "currency": account["currency"],
            "timezone_name": account["timezone_name"],
        }
        if cursor and cursor.get("query") != query:
            raise SourceReadError("月份分頁條件已變更，請完整重讀。", "invalid_monthly_scope")
        page = self._page(
            conn,
            org_id,
            brand_id,
            account,
            "monthly",
            start=start,
            end=end,
            cursor=(cursor or {}).get("after"),
        )
        rows = []
        for item in page["data"]:
            row = observation(item, "campaign", account)
            if (
                item.get("account_currency") != account["currency"]
                or not first <= date.fromisoformat(row["day"]) <= last
                or item.get("date_start") != row["day"]
                or item.get("date_stop") != row["day"]
                or isinstance(item.get("spend"), bool)
                or row["spend"] is None
                or row["spend"] < 0
            ):
                raise SourceReadError(
                    "月份來源列的日期、幣別或花費無法核對。", "invalid_source_page"
                )
            row["attribution_key"] = MONTHLY_BUDGET_ATTRIBUTION_KEY
            rows.append(row)
        return SourcePage(
            rows,
            {"after": page["cursor"], "query": query} if page["cursor"] else None,
            coverage={"scope": "account_campaign_day", **query},
        )

    def binding_kinds(self):
        return ("ad",)

    def verify_native(
        self,
        conn,
        org_id,
        brand_id,
        account,
        *,
        native_kind,
        native_id,
        root_kind,
        root_id,
        original,
    ):
        if native_kind not in {"ad", "adset", "campaign"} or root_kind != "campaign":
            raise SourceReadError("此來源不支援指定素材核對。", "unsupported")
        try:
            raw = source.read_external_object(
                conn, org_id, brand_id, account["account_id"], native_kind, native_id
            )
            if native_kind == "campaign":
                if str(raw.get("id")) != root_id:
                    raise ValueError("活動不符。")
                parents = []
            else:
                if str(raw.get("campaign_id")) != root_id:
                    raise ValueError("物件不屬於指定活動。")
                parents = []
                if native_kind == "ad":
                    if not raw.get("adset_id"):
                        raise ValueError("廣告缺少父層。")
                    adset = source.read_external_object(
                        conn, org_id, brand_id, account["account_id"], "adset", str(raw["adset_id"])
                    )
                    if str(adset.get("campaign_id")) != root_id:
                        raise ValueError("廣告父層不屬於指定活動。")
                    parents.append(_verified_snapshot(adset, "adset", account))
                campaign = source.read_external_object(
                    conn, org_id, brand_id, account["account_id"], "campaign", root_id
                )
                parents.append(_verified_snapshot(campaign, "campaign", account))
            entity = _verified_snapshot(raw, native_kind, account)
            if native_kind == "ad":
                entity["creative"] = creative_summary(raw.get("creative"))
            return {
                "entity": entity,
                "parents": parents,
                "timezone_name": account.get("timezone_name"),
                "media_equivalence": None,
                "continuous_intervals": [],
                "limitations": [
                    "目前讀取介面尚未取得原檔等價與連續素材版本歷史；無法將成效分到素材版本。"
                ],
            }
        except source.ExternalReadError as exc:
            raise SourceReadError(str(exc), exc.code) from None
        except ValueError:
            raise SourceReadError("平台物件或完整父鏈無法核對。", "parent_mismatch") from None
