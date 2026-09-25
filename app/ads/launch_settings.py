"""app/ads/launch_settings.py — F29 Contract I: launch settings as choice fields.

One set of launch settings per campaign (`ads_campaign.context_json.launch_settings`), used by
every ad set of the launch. Values are the shared vocabulary below; the platform adapter maps its
own fields onto it for readback (`app/ads/adapters/meta_read.py::launch_settings_observed`).

Recommended values are program rules only, no model call (F29 Unresolved 4): the event from the
campaign's result kind, lowest cost, automatic placement, 18–65+, all genders, the brand's country
(TW when unknown) and the pixel when the account has exactly one. The pixel list is read from the
platform (read only) by `view()` and cached on the campaign, so the launch snapshot and the
approval never wait on a platform read. Nothing here writes to a platform (ads.md §6.4).
"""

import re
from datetime import UTC, datetime

from app.ads import channels, targets
from app.ads.adapters.external import SourceReadError
from app.brand_intelligence import repository as bi_repo
from app.core import db

# -- vocabulary (one-line plain notes from prototype v10 `SET_NOTE` and its field notes) ---------
# `{platform}` in a note is filled at read time with the channel's display label from
# `app/ads/channels.py` (e.g. 「讓 Meta 用最少的錢買到結果」); no platform name lives here.

EVENTS = [
    {"value": "purchase", "label": "購買", "note": "{platform} 要幫你找哪種人：會買的人"},
    {
        "value": "add_to_cart",
        "label": "加入購物車",
        "note": "{platform} 要幫你找哪種人：會放進購物車的人",
    },
    {
        "value": "initiate_checkout",
        "label": "開始結帳",
        "note": "{platform} 要幫你找哪種人：會開始結帳的人",
    },
    {
        "value": "view_content",
        "label": "內容瀏覽",
        "note": "{platform} 要幫你找哪種人：會點進來看的人",
    },
]
BIDS = [
    {"value": "lowest_cost", "label": "最低成本", "note": "讓 {platform} 用最少的錢買到結果"},
    {
        "value": "cost_cap",
        "label": "單次成果成本上限",
        "note": "每筆盡量不超過你設的金額，但量可能變少",
    },
    {"value": "bid_cap", "label": "出價上限", "note": "每次搶廣告位置最多出到某個價，懂競價再用"},
]
PLACEMENT_MODES = [
    {"value": "auto", "label": "自動", "note": "讓 {platform} 自己決定廣告出現在 FB、IG 哪裡"},
    {"value": "manual", "label": "手動", "note": "你自己挑廣告要出現在哪裡"},
]
POSITIONS = [
    {"value": "facebook_feed", "label": "Facebook 動態", "note": "滑 Facebook 首頁時看到"},
    {"value": "instagram_feed", "label": "Instagram 動態", "note": "滑 Instagram 首頁時看到"},
    {"value": "stories", "label": "限時動態", "note": "看限時動態時，夾在中間的全螢幕畫面"},
    {"value": "reels", "label": "Reels", "note": "看短影音時，夾在中間的直式畫面"},
    {"value": "messenger", "label": "Messenger", "note": "Messenger 聊天列表裡"},
]
GENDERS = [
    {"value": "all", "label": "不限", "note": "男女都給看"},
    {"value": "female", "label": "女性", "note": "只給女性看"},
    {"value": "male", "label": "男性", "note": "只給男性看"},
]
COUNTRIES = [
    {"value": "TW", "label": "台灣", "note": "整個台灣都看得到"},
    {"value": "HK", "label": "香港", "note": "整個香港都看得到"},
    {"value": "MO", "label": "澳門", "note": "整個澳門都看得到"},
    {"value": "SG", "label": "新加坡", "note": "整個新加坡都看得到"},
    {"value": "MY", "label": "馬來西亞", "note": "整個馬來西亞都看得到"},
    {"value": "JP", "label": "日本", "note": "整個日本都看得到"},
    {"value": "US", "label": "美國", "note": "整個美國都看得到"},
]
AGES = [18, 21, 25, 30, 35, 45, 54, 55, 65]
AGE_MIN, AGE_MAX = 18, 65  # 65 means 65+
FIELD_NOTES = {
    "audience": "要給哪些人看：年齡、性別、地區",
    "pixel_id": "官網上記錄誰買了東西的追蹤碼；選錯就看不到成效",
    "utm": "加在網址後面，讓官網後台分得出是哪個廣告帶來的",
}
# Top-level keys, in screen order; `edited` and the stale diff name these.
KEYS = ("optimization_event", "bid_strategy", "placement", "audience", "pixel_id", "utm")
KEY_LABELS = {
    "optimization_event": "優化事件",
    "bid_strategy": "出價方式",
    "placement": "版位",
    "audience": "受眾",
    "pixel_id": "像素",
    "utm": "UTM 追蹤參數",
}
# Readback compares these per ad set (all but `utm`) or per ad (`utm`).
READBACK_FIELDS = (
    ("optimization_event", "優化事件"),
    ("bid_strategy", "出價方式"),
    ("placement", "版位"),
    ("age", "年齡"),
    ("gender", "性別"),
    ("countries", "地區"),
    ("pixel_id", "像素"),
    ("utm", "UTM"),
)
AD_READBACK_KEYS = frozenset({"utm"})

_UTM = re.compile(r"^utm_[a-z_]+=[^\s&=]+(&utm_[a-z_]+=[^\s&=]+)*$")
_UTM_SOURCE = re.compile(r"(^|&)utm_source=")
_LABEL: dict[str, dict[str, str]] = {
    "optimization_event": {o["value"]: o["label"] for o in EVENTS},
    "bid_strategy": {o["value"]: o["label"] for o in BIDS},
    "position": {o["value"]: o["label"] for o in POSITIONS},
    "gender": {o["value"]: o["label"] for o in GENDERS},
    "country": {o["value"]: o["label"] for o in COUNTRIES},
}


def _label(kind: str, value) -> str:
    return _LABEL[kind].get(str(value), str(value))


# The shared result kind -> the event a system-built campaign optimises for.
_EVENT_FOR_RESULT = {"purchase": "purchase", "link_click": "view_content"}


class LaunchSettingsMalformed(ValueError):
    """A body that is not a launch-settings value at all (wrong type or unknown choice)."""


# -- stored record ---------------------------------------------------------------------------------


def _record(campaign: dict) -> dict:
    return (campaign.get("context_json") or {}).get("launch_settings") or {}


def cached_pixels(campaign: dict) -> list[dict] | None:
    """The last successful pixel read for this campaign, or None when none succeeded yet."""
    cached = _record(campaign).get("pixels")
    return cached.get("items") if isinstance(cached, dict) else None


def _channel(campaign: dict) -> str | None:
    for group in campaign.get("groups") or []:
        if group.get("channel_key"):
            return group["channel_key"]
    return campaign.get("channel")


def _platform_label(campaign: dict) -> str:
    key = _channel(campaign)
    return next((c["label"] for c in channels.CHANNELS if c["key"] == key), "平台")


def _filled(options: list[dict], platform: str) -> list[dict]:
    return [o | {"note": o["note"].replace("{platform}", platform)} for o in options]


def _country(conn, brand_id: str) -> str:
    region = ((bi_repo.get_brand(conn, brand_id) or {}).get("market_region") or "").upper()
    return region if region in _LABEL["country"] else "TW"


def recommended(conn, brand_id: str, campaign: dict, pixels: list[dict] | None) -> dict:
    event = _EVENT_FOR_RESULT.get(targets.effective_result_kind(campaign) or "", "purchase")
    if campaign.get("objective") == "加購物車":
        event = "add_to_cart"
    source = re.sub(r"[^a-z0-9_]", "", str(_channel(campaign) or "").lower()) or "ads"
    return {
        "optimization_event": event,
        "bid_strategy": "lowest_cost",
        "placement": {"mode": "auto", "positions": []},
        "audience": {
            "age_min": AGE_MIN,
            "age_max": AGE_MAX,
            "gender": "all",
            "countries": [_country(conn, brand_id)],
        },
        "pixel_id": pixels[0]["id"] if pixels and len(pixels) == 1 else None,
        "utm": f"utm_source={source}&utm_medium=paid&utm_campaign={campaign['id']}",
    }


def effective(conn, org_id: str, brand_id: str, campaign: dict) -> dict:
    """The values the launch uses now: the saved ones, else the recommendation over the cached
    pixel list. Never reads a platform (the launch snapshot calls this)."""
    saved = _record(campaign).get("values")
    if isinstance(saved, dict):
        return saved
    return recommended(conn, brand_id, campaign, cached_pixels(campaign))


# -- validation ------------------------------------------------------------------------------------


def normalize(body) -> dict:
    """Shape check of a PUT body; raises `LaunchSettingsMalformed`. Semantic problems (UTM format,
    age order, no manual position, unknown pixel) are `errors()`, saved and shown, not refused."""
    try:
        placement, audience = body["placement"], body["audience"]
        values = {
            "optimization_event": body["optimization_event"],
            "bid_strategy": body["bid_strategy"],
            "placement": {
                "mode": placement["mode"],
                "positions": list(dict.fromkeys(placement.get("positions") or [])),
            },
            "audience": {
                "age_min": audience["age_min"],
                "age_max": audience["age_max"],
                "gender": audience["gender"],
                "countries": list(dict.fromkeys(audience["countries"])),
            },
            "pixel_id": body.get("pixel_id"),
            "utm": body["utm"],
        }
    except (KeyError, TypeError, AttributeError):
        raise LaunchSettingsMalformed("launch_settings_malformed") from None
    audience = values["audience"]
    if (
        set(body) - set(KEYS)
        or values["optimization_event"] not in _LABEL["optimization_event"]
        or values["bid_strategy"] not in _LABEL["bid_strategy"]
        or values["placement"]["mode"] not in {"auto", "manual"}
        or any(p not in _LABEL["position"] for p in values["placement"]["positions"])
        or any(
            type(audience[k]) is not int or not AGE_MIN <= audience[k] <= AGE_MAX
            for k in ("age_min", "age_max")
        )
        or audience["gender"] not in _LABEL["gender"]
        or any(c not in _LABEL["country"] for c in audience["countries"])
        or not (values["pixel_id"] is None or isinstance(values["pixel_id"], str))
        or not isinstance(values["utm"], str)
        or len(values["utm"]) > 500
        or (isinstance(values["pixel_id"], str) and not 0 < len(values["pixel_id"]) <= 64)
    ):
        raise LaunchSettingsMalformed("launch_settings_malformed")
    if values["placement"]["mode"] == "auto":
        values["placement"]["positions"] = []
    values["utm"] = values["utm"].strip()
    return values


def errors(values: dict, pixels: list[dict] | None) -> list[dict]:
    """What blocks approval (409 `launch_settings_invalid`); empty when the launch may go."""
    found = []

    def add(field, code, message):
        found.append({"field": field, "code": code, "message": message})

    utm = values.get("utm") or ""
    if not _UTM.match(utm):
        add("utm", "utm_format", "格式不對：要像 utm_source=來源&utm_campaign=名稱，不能有空格")
    elif not _UTM_SOURCE.search(utm):
        add("utm", "utm_source_missing", "要有 utm_source")
    audience = values.get("audience") or {}
    if not audience.get("age_min", 0) < audience.get("age_max", 0):
        add("audience.age", "age_range", "年齡範圍不對：最小年齡要比最大年齡小")
    if not audience.get("countries"):
        add("audience.countries", "countries_empty", "地區至少選一個")
    placement = values.get("placement") or {}
    if placement.get("mode") == "manual" and not placement.get("positions"):
        add("placement.positions", "positions_empty", "手動版位至少選一個")
    pixel = values.get("pixel_id")
    if pixel is not None and pixels is not None and pixel not in {p["id"] for p in pixels}:
        add("pixel_id", "pixel_unknown", "這個像素不在廣告帳號的像素清單裡")
    return found


def edited(values: dict, recommended_values: dict) -> list[str]:
    return [key for key in KEYS if values.get(key) != recommended_values.get(key)]


# -- platform pixel read ---------------------------------------------------------------------------


def read_pixels(conn, org_id: str, brand_id: str, campaign: dict) -> tuple[list | None, str | None]:
    """The bound accounts' pixels through the channel's reader (read only), or `(None, reason)`.
    Commits (the platform facade never holds a transaction open across HTTP)."""
    platform = _channel(campaign)
    reader = channels.external_reader(platform) if platform else None
    if reader is None or not hasattr(reader, "pixels"):
        return None, "這個投放平台還不能讀像素清單。"
    try:
        accounts = reader.accounts(conn, org_id, brand_id)
        if not accounts:
            return None, "還沒連接廣告帳號，讀不到像素清單。"
        found = {}
        for account in accounts:
            for pixel in reader.pixels(conn, org_id, brand_id, account):
                found.setdefault(pixel["id"], pixel)
    except SourceReadError as exc:
        # Lazy: the adapter registry imports the manual adapter, which imports the launch module.
        from app.ads import adapters

        if adapters.is_auth_error(platform, exc.code):
            return None, "像素的讀取權限沒開，系統讀不到像素清單；請到廣告平台看一眼。"
        return None, f"像素清單暫時讀不到：{exc}"
    return sorted(found.values(), key=lambda p: (p["name"], p["id"])), None


def _merge(conn, org_id: str, brand_id: str, campaign_id: str, patch: dict, *, touch: bool):
    """One-statement merge into `context_json.launch_settings`: other context keys (the manual
    handoff records) are never rewritten from a stale read."""
    conn.execute(
        "UPDATE ads_campaign SET context_json = context_json || jsonb_build_object("
        "'launch_settings', COALESCE(context_json->'launch_settings','{}'::jsonb) || %s::jsonb)"
        + (", updated_at = now()" if touch else "")
        + " WHERE org_id = %s AND brand_id = %s AND id = %s",
        (db.jsonb(patch), org_id, brand_id, campaign_id),
    )


def _campaign(conn, org_id: str, brand_id: str, campaign_id: str) -> dict:
    from app.ads import repository

    campaign = repository.campaign_detail(conn, org_id, brand_id, campaign_id)
    if campaign is None:
        raise ValueError("campaign_unknown")
    if campaign.get("origin") == "imported":
        raise ValueError("launch_settings_unavailable")
    return campaign


def view(conn, org_id: str, brand_id: str, campaign_id: str, *, read: bool = True) -> dict:
    """`GET …/launch-settings`. `read` reads the pixel list from the platform first (and caches a
    successful read); a failed read keeps `pixels: null` with its reason, never an empty list."""
    campaign = _campaign(conn, org_id, brand_id, campaign_id)
    pixels_error = None
    if read:
        pixels, pixels_error = read_pixels(conn, org_id, brand_id, campaign)
        if pixels is not None and pixels != cached_pixels(campaign):
            _merge(
                conn,
                org_id,
                brand_id,
                campaign_id,
                {"pixels": {"read_at": db.now_utc().isoformat(), "items": pixels}},
                touch=False,
            )
            conn.commit()
            campaign = _campaign(conn, org_id, brand_id, campaign_id)
    pixels = cached_pixels(campaign) if pixels_error is None else None
    suggested = recommended(conn, brand_id, campaign, cached_pixels(campaign))
    values = effective(conn, org_id, brand_id, campaign)
    platform = _platform_label(campaign)
    return {
        "values": values,
        "recommended": suggested,
        "options": {
            "optimization_event": _filled(EVENTS, platform),
            "bid_strategy": _filled(BIDS, platform),
            "positions": POSITIONS,
            "countries": COUNTRIES,
            "pixels": pixels,
            "pixels_error": pixels_error,
            "placement_modes": _filled(PLACEMENT_MODES, platform),
            "genders": GENDERS,
            "ages": AGES,
            "field_notes": FIELD_NOTES,
        },
        "edited": edited(values, suggested),
        "errors": errors(values, pixels),
    }


def save(conn, org_id: str, brand_id: str, campaign_id: str, body, *, actor: str) -> dict:
    """`PUT …/launch-settings`: store the values (shape-checked), answer the fresh view. An edit
    after an approved launch makes it stale through the snapshot (F28 exit)."""
    values = normalize(body)
    row = conn.execute(
        "SELECT status FROM ads_campaign WHERE org_id=%s AND brand_id=%s AND id=%s FOR UPDATE",
        (org_id, brand_id, campaign_id),
    ).fetchone()
    if row is None:
        raise ValueError("campaign_unknown")
    if row["status"] == "closed":
        raise ValueError("campaign_closed")
    _campaign(conn, org_id, brand_id, campaign_id)
    record = {"values": values, "saved_at": datetime.now(UTC).isoformat(), "saved_by": actor}
    _merge(conn, org_id, brand_id, campaign_id, record, touch=True)
    conn.commit()
    return view(conn, org_id, brand_id, campaign_id)


def write_values(conn, org_id: str, brand_id: str, campaign_id: str, values: dict, actor: str):
    """Store `values` as the saved settings (approval materialises the recommendation it froze;
    a revert writes the approved values back). The caller owns the transaction."""
    record = {"values": values, "saved_at": db.now_utc().isoformat(), "saved_by": actor}
    _merge(conn, org_id, brand_id, campaign_id, record, touch=False)


def is_saved(campaign: dict) -> bool:
    return isinstance(_record(campaign).get("values"), dict)


# -- labels and readback comparison ----------------------------------------------------------------


def _age_label(age_min, age_max) -> str:
    return f"{age_min}–{age_max}{'+' if age_max == AGE_MAX else ''} 歲"


def _pixel_label(pixel_id, pixels) -> str:
    if not pixel_id:
        return "沒有選像素"
    name = next((p["name"] for p in pixels or [] if p["id"] == pixel_id), None)
    return f"{name}（{pixel_id}）" if name else str(pixel_id)


def _placement_label(placement: dict) -> str:
    if placement.get("mode") == "auto":
        return "自動版位"
    names = [_label("position", p) for p in placement.get("positions") or []]
    extra = [str(e) for e in placement.get("extra") or []]
    return "手動：" + ("、".join(names + extra) or "還沒選")


def _countries_label(countries, extra=()) -> str:
    names = [_label("country", c) for c in countries or []] + [str(e) for e in extra]
    return "、".join(names) or "沒有地區"


def value_label(key: str, values: dict | None, pixels=None) -> str | None:
    """Display text of one top-level key (the stale diff's before/after)."""
    if not values:
        return None
    value = values.get(key)
    if key in ("optimization_event", "bid_strategy"):
        return _label(key, value)
    if key == "placement":
        return _placement_label(value or {})
    if key == "audience":
        audience = value or {}
        return "・".join(
            [
                _age_label(audience.get("age_min"), audience.get("age_max")),
                _label("gender", audience.get("gender")),
                _countries_label(audience.get("countries")),
            ]
        )
    if key == "pixel_id":
        return _pixel_label(value, pixels)
    return value or "沒有設定"


def _expected(key: str, values: dict):
    audience = values.get("audience") or {}
    if key == "age":
        return {"age_min": audience.get("age_min"), "age_max": audience.get("age_max")}
    if key == "gender":
        return audience.get("gender")
    if key == "countries":
        return audience.get("countries") or []
    return values.get(key)


def readback_label(key: str, value, pixels=None, extra=()) -> str:
    if key == "age":
        return _age_label((value or {}).get("age_min"), (value or {}).get("age_max"))
    if key == "gender":
        return _label("gender", value)
    if key == "countries":
        return _countries_label(value, extra)
    if key == "placement":
        return _placement_label(value or {})
    if key == "pixel_id":
        return _pixel_label(value, pixels)
    if key == "utm":
        return value or "沒有設定"
    return _label(key, value)


def expected_label(key: str, values: dict, pixels=None) -> str:
    return readback_label(key, _expected(key, values), pixels)


def _same(key: str, expected, observed: dict) -> bool:
    value = observed.get("value")
    if value is None:
        # A platform value with no equivalent here (raw set) never matches; an unset pixel/UTM
        # matches only an unset expectation.
        return observed.get("raw") is None and expected in (None, "")
    if key == "placement":
        if expected.get("mode") == "auto" or value.get("mode") == "auto":
            return expected.get("mode") == value.get("mode")
        return not value.get("extra") and set(value.get("positions") or []) == set(
            expected.get("positions") or []
        )
    if key == "countries":
        return not value.get("extra") and set(value.get("countries") or []) == set(expected)
    return value == expected


def _observed_label(key: str, observed: dict, pixels) -> str:
    value, raw = observed.get("value"), observed.get("raw")
    if value is None:
        return raw if raw is not None else readback_label(key, None, pixels)
    if key == "countries":
        return readback_label(key, value.get("countries"), pixels, value.get("extra") or ())
    return readback_label(key, value, pixels)


def item_keys(expected_subset: dict) -> list[str]:
    """Readback keys an item's frozen subset covers: an ad set's all but UTM, an ad's UTM."""
    if set(expected_subset) == {"utm"}:
        return ["utm"]
    return [key for key, _ in READBACK_FIELDS if key not in AD_READBACK_KEYS]


def compare_item(expected_subset: dict | None, observed: dict | None, pixels=None) -> dict:
    """Per readback key of one handoff item: `{state: match|differ|unreadable, observed_label,
    reason}`. Nothing is compared when the item froze no settings or the reader observed none."""
    if not expected_subset or observed is None:
        return {}
    result = {}
    for key in item_keys(expected_subset):
        entry = observed.get(key)
        if not isinstance(entry, dict) or entry.get("state") != "read":
            reason = (entry or {}).get("reason") if isinstance(entry, dict) else None
            result[key] = {
                "state": "unreadable",
                "observed_label": None,
                "reason": reason or "平台沒有回傳這一項。",
            }
            continue
        same = _same(key, _expected(key, expected_subset), entry)
        result[key] = {
            "state": "match" if same else "differ",
            "observed_label": _observed_label(key, entry, pixels),
            "reason": None,
        }
    return result


def group_subset(values: dict | None) -> dict | None:
    return {k: v for k, v in values.items() if k != "utm"} if values else None


def ad_subset(values: dict | None) -> dict | None:
    return {"utm": values.get("utm")} if values else None
