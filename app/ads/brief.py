"""app/ads/brief.py — F03-I03: one sentence becomes a draft Campaign (§0 "golden path", the
**goal** link). Private to app/ads (container contract §1): only `routes.py` imports `create_draft`.

Input: the user's sentence plus dates/constraints, and the brand facts/products/product economics
that already exist — this never asks the user to re-enter them (`app/llm/context_compiler.py` for
confirmed brand facts, `app.brand_intelligence.repository` for products and today's effective
`product_economics`, both read-only). Output: one `ads_campaign` row in `status='draft'`. Trace:
`goal_text` verbatim, the `llm_task` row (via `gateway.run_task`), and `context_json` naming which
brand/product/economics rows fed the call.

Never dead-ends (same rule as `app/workbench/free_parse.py`'s `free_parse.parse()`): a failed,
timed-out or unparseable call still writes a usable draft — `objective='購買'` and no cap —
and the response carries `parsed: false` instead of raising.

F28-I01: the sentence only ever yields one number for judging, the cost-per-purchase cap
(`cap`, stored as `target_cost` with `target_basis='own'`). A ROAS or a count in the sentence is
not converted into a cap; a reply without `cap` still parses (no cap).

F43-I04 (feature F43 Decisions 「Campaign defaults」): a structured create picks one sell-way and
takes the rest from the brand and that sell-way -- `context_json.customer_group_ids` = every
customer group of its knowledge products (`field_sources.audience = "sell_way"`), landing = its
effective landing (`"sell_way"`), cap = its `cap_per_sale` when set, stored as the campaign's own
cap (`field_sources.cap = "sell_way"`; unset -> break-even, resolved by `targets`), objective = the
request's (the page preselects the brand's goal), platform = the plan default. Request values win
(`"user"`). `audience_hint` stays readable on old campaigns and is still accepted from the
request, but the model's audience guess is no longer stored on a structured create (the audience
is the groups). The sentence path gets no sell-way defaults.

F46-I08 (feature F46 Contract D, user ruling 2026-10-02, supersedes ads §6.47 for these three
fields): a structured create starts from the same sell-way's previous campaign
(`wizard_options.previous_campaign`: newest internal non-draft campaign of that sell-way), for a
value the request does not send -- platform = previous (`"copied"`) else the brand's first
connected channel (`"brand"`) else none (`"system"`); cap = previous `target_cost` (`"copied"`)
else the sell-way's `cap_per_sale` (`"sell_way"`) else its whole break-even (`"break_even"`,
stored as the campaign's own cap) else none (`"system"`); budget is `"copied"` when the sent
budget equals the previous one. A previous field that is empty falls through for that field
alone. These are the values `wizard_options.options()` hands the form, so shown = stored.
"""

import calendar
import json
import math
from datetime import date, timedelta

from app.ads import (
    channels,
    external_models,
    manual_settings,
    objectives,
    planner_context,
    wizard_options,
)
from app.ads import repository as ads_repo
from app.brand_intelligence import repository as bi_repo
from app.core import settings as coresettings
from app.core.db import APP_DIR, jsonb
from app.core.vocab import CONVERSION_GOAL_LABELS
from app.llm import context_compiler, gateway, providers

DEPARTMENT_PATH = APP_DIR / "departments" / "ads" / "brief_parse.md"

# 唯一的供應商實例，比照 app/workbench/free_parse.py：測試用
# `mock.patch.object(brief, "PROVIDER", FakeProvider(...))` 換掉。
PROVIDER = providers.AnthropicProvider()

# F30-I04: derived from the one objective catalog (`objectives.py`, Contract C) -- the available
# objectives plus 加購物車 (accepted from the parse, never listed).
_OBJECTIVES = objectives.ACCEPTED

DATES_REQUIRED_MESSAGE = (
    "投放的開始與結束日期請一起填，或兩個都留空讓行銷駕駛艙從你的描述判斷。"
)
END_BEFORE_START_MESSAGE = "結束日期不能早於開始日期。"

_FALLBACK_PARSED = {
    "objective": "購買", "cap": None, "product_ids": [], "audience_hint": None, "notes": None,
    "budget_cap": None, "platform": None, "period": None,
}

# prompt 裡最多列幾個商品——大品牌可能有幾百個 SKU，全部塞進去是傾印不是判斷（F04-I03）。
_MAX_PRODUCTS = 20


def _validate_dates(start_date: str, end_date: str) -> tuple[date, date]:
    """`(start_date, end_date)` 讀成 `date`；`start_date > end_date` 一律 `ValueError`
    ——這支檔案自己驗（不 import `app.schedule`：`ads` 不依賴 `schedule`，§0）。錯誤一律用
    snake_case 代碼（F03-I19「Error codes are machine tokens」）；`routes.py` 把代碼翻成
    `DATES_REQUIRED_MESSAGE`／`END_BEFORE_START_MESSAGE` 這兩個常數當 `message`。"""
    if not start_date or not end_date:
        raise ValueError("dates_required")
    try:
        start = date.fromisoformat(start_date)
        end = date.fromisoformat(end_date)
    except ValueError as exc:
        raise ValueError("dates_required") from exc
    if end < start:
        raise ValueError("end_before_start")
    return start, end


def _resolve_period(period: dict | None, *, today: date) -> tuple[date | None, date | None]:
    """F04-I11：把模型解析出來的 `period`（月份或日期區間）換成 `(start, end)`——日曆算數
    在程式，R7：模型只認得「9 月」，年份與月底是幾號一律這裡算。解析不出來（`None`、
    形狀不對、`end < start`）一律回 `(None, None)`，呼叫端自己決定備援。"""
    if not isinstance(period, dict):
        return None, None
    kind = period.get("kind")
    if kind == "range":
        start_text, end_text = period.get("start"), period.get("end")
        if not isinstance(start_text, str) or not isinstance(end_text, str):
            return None, None
        try:
            start, end = date.fromisoformat(start_text), date.fromisoformat(end_text)
        except ValueError:
            return None, None
        if end < start:
            return None, None
        return start, end
    if kind == "month":
        month = period.get("month")
        if isinstance(month, bool) or not isinstance(month, int) or not 1 <= month <= 12:
            return None, None
        # 使用者說「9 月」時是在排未來的檔期：這個月已經過完就當作明年同月，不是回頭排
        # 已經走過的月份。
        year = today.year if month >= today.month else today.year + 1
        start = date(year, month, 1)
        end = date(year, month, calendar.monthrange(year, month)[1])
        return start, end
    return None, None


def _validate_period(period) -> dict | None:
    if not isinstance(period, dict):
        return None
    kind = period.get("kind")
    if kind == "month":
        month = period.get("month")
        if isinstance(month, bool) or not isinstance(month, int) or not 1 <= month <= 12:
            return None
        return {"kind": "month", "month": month}
    if kind == "range":
        start_text, end_text = period.get("start"), period.get("end")
        if not isinstance(start_text, str) or not isinstance(end_text, str):
            return None
        try:
            date.fromisoformat(start_text)
            date.fromisoformat(end_text)
        except ValueError:
            return None
        return {"kind": "range", "start": start_text, "end": end_text}
    return None


def _products_context(conn, org_id: str, brand_id: str) -> tuple[str, list[str], list[str]]:
    """商品清單＋今天有效的 `product_economics`，供 prompt 用；回傳 (prompt 文字段落,
    實際引用到的 economics id 清單, 這個品牌自己的商品 id 清單)——過期的價格（`effective_to`
    已經過去）照樣列出，只是標「已過期」，絕不悄悄當成現在有效的價格用（§0「a price whose
    effective window has passed is passed in labelled stale」）。商品 id 清單同時是
    `create_draft` 過濾模型瞎掰的 `product_ids` 用的唯一名單（F03-I19，別重複收集一次）。"""
    products = bi_repo.list_products(conn, brand_id)
    if not products:
        return "【商品清單】（品牌還沒有任何商品）", [], []

    # 白名單一律是這個品牌「全部」商品 id，不是被截斷後的那 20 個——這是拿來過濾模型瞎掰的
    # `product_ids` 用的，不是 prompt 內容，截了會讓合法的商品被當成瞎掰（F04-I03）。
    brand_product_ids = [p["id"] for p in products]
    kept, omitted = products[:_MAX_PRODUCTS], products[_MAX_PRODUCTS:]

    today = coresettings.today_for_org(conn, org_id=org_id)
    lines = []
    economics_ids = []
    for product in kept:
        economics = bi_repo.get_product_economics(conn, brand_id, product["id"])
        if economics is None:
            lines.append(f"- {product['id']}｜{product['name']}｜沒有價格資料")
            continue
        economics_ids.append(economics["id"])
        effective_to = economics.get("effective_to")
        stale = effective_to is not None and effective_to < today
        price_text = (
            f"售價 {economics.get('selling_price')}"
            f"／單位成本 {economics.get('unit_variable_cost')}"
            f"／運費 {economics.get('shipping_cost')}"
        )
        if stale:
            price_text += "（已過期，僅供參考，不當成現在的價格）"
        lines.append(f"- {product['id']}｜{product['name']}｜{price_text}")
    if omitted:
        lines.append(f"（這個品牌另有 {len(omitted)} 個商品沒有列出）")
    return "【商品清單】\n" + "\n".join(lines), economics_ids, brand_product_ids


def _validate_reply(data) -> dict | None:
    if not isinstance(data, dict):
        return None
    objective = data.get("objective")
    if objective not in _OBJECTIVES:
        return None
    cap = data.get("cap")
    if (isinstance(cap, bool) or not isinstance(cap, (int, float)) or not math.isfinite(cap)
            or cap <= 0):
        cap = None  # missing or unparsed -> no cap; never a ROAS, never a guessed number
    product_ids = data.get("product_ids")
    if not isinstance(product_ids, list) or not all(isinstance(p, str) for p in product_ids):
        product_ids = []
    audience_hint = data.get("audience_hint")
    notes = data.get("notes")
    budget_cap = data.get("budget_cap")
    if isinstance(budget_cap, bool) or not isinstance(budget_cap, (int, float)) or budget_cap <= 0:
        budget_cap = None
    platform = data.get("platform")
    if platform not in {c["key"] for c in channels.CHANNELS}:
        platform = None
    return {
        "objective": objective,
        "cap": float(cap) if cap is not None else None,
        "product_ids": product_ids,
        "budget_cap": float(budget_cap) if budget_cap is not None else None,
        "platform": platform,
        "period": _validate_period(data.get("period")),
        "audience_hint": audience_hint if isinstance(audience_hint, str) else None,
        "notes": notes if isinstance(notes, str) else None,
    }


# A create with no dates runs from the org's today for this many days (both the structured and
# the sentence path); served as `GET …/rules` `limits.campaign_default_days` (F50 Contract I).
DEFAULT_PERIOD_DAYS = 30

_NAME_BASE_LIMIT = 30


def _draft_name(base: str, start: date | None = None, end: date | None = None) -> str:
    """草稿名稱 = `<base>・MM/DD～MM/DD`（F41-I03，drill-8 #5）。`<base>` 在結構化路徑是選的
    商品名，否則是使用者那句話；只有 `<base>` 會縮短（30 字 +「…」），日期尾巴永遠不切，
    所以每一期的名稱都不同（讀回綁定才不會撞名）。使用者在畫面上隨時可以改
    （`PATCH .../campaigns/{id}` 的 `name` 欄位），這裡只給一個不空白的起點。"""
    text = base.strip()
    if len(text) > _NAME_BASE_LIMIT:
        text = text[:_NAME_BASE_LIMIT] + "…"
    if start is None or end is None:
        return text
    return f"{text}・{start:%m/%d}～{end:%m/%d}"


def _valid_budget(value) -> bool:
    """The wizard's 「這個活動最多花」 is a positive, finite number -- never a bool or a string."""
    return (
        not isinstance(value, bool) and isinstance(value, (int, float))
        and math.isfinite(value) and value > 0
    )


def _check_picks(conn, brand_id: str, picks: dict) -> dict:
    """F30-I04 (Contract D): the wizard's structured picks, validated before any model call
    (a refused create never spends). Returns `{product_ids, products, objective, budget}`."""
    objective = objectives.check(picks.get("objective"))
    budget = picks.get("budget")
    if not _valid_budget(budget):
        raise ValueError("budget_invalid")
    product_ids = picks.get("product_ids")
    # Contract D: `product_ids: [id]` -- exactly one pick.
    if (not isinstance(product_ids, list) or len(product_ids) != 1
            or not isinstance(product_ids[0], str) or not product_ids[0]):
        raise ValueError("products_required")
    # Only what the wizard lists is pickable (same function, not a second rule): a knowledge
    # product, an archived sell-way or a 建到一半 product's sell-way is `product_unknown`.
    by_id = {p["id"]: p for p in wizard_options.sellable_products(conn, brand_id)}
    product = by_id.get(product_ids[0])
    if product is None:
        raise ValueError("product_unknown")
    group_ids = [g["id"] for g in wizard_options.customer_groups(conn, brand_id, product)]
    return {
        "product_ids": [product["id"]], "products": [product],
        "objective": objective, "budget": budget,
        "group_ids": group_ids,
        "customer_group_ids": _check_customer_groups(picks.get("customer_group_ids"), group_ids),
    }


def _check_customer_groups(value, group_ids: list[str]) -> list[str] | None:
    """F43-I04: the fold's audience override -- `None` or `[]` = not overridden (every group of
    the sell-way); else a list of this sell-way's group ids (kept in the sell-way's order, each
    once). Anything else is `customer_group_unknown`."""
    if value is None or value == []:
        return None
    if not isinstance(value, list) or not all(isinstance(v, str) for v in value) \
            or not set(value) <= set(group_ids):
        raise ValueError("customer_group_unknown")
    return [group_id for group_id in group_ids if group_id in set(value)]


# F30-I04: any of these present -> the wizard's structured create. `_check_extras` (platform /
# audience_hint / cap / landing_url) is accepted on the picks path and the sentence path alike.
_STRUCTURED_KEYS = ("product_ids", "objective", "budget")


def _check_extras(picks: dict) -> dict:
    """Validate the request's platform / audience_hint / cap / landing_url before any model
    call, with the rules the existing edit paths use: platform through `channels.CHANNELS`,
    cap with the one cap rule (`target_value_unknown`, same code as `PUT .../target`), the
    landing URL with `manual_settings.validate_landing_url`. Missing keys stay `None`."""
    platform = picks.get("platform")
    if platform is not None and platform not in {c["key"] for c in channels.CHANNELS}:
        raise ValueError("platform_unknown")
    audience_hint = picks.get("audience_hint")
    if audience_hint is not None:
        if not isinstance(audience_hint, str):
            raise ValueError("audience_hint_unknown")
        audience_hint = audience_hint.strip() or None
    cap = picks.get("cap")
    if cap is not None:
        if not _valid_budget(cap):
            raise ValueError("target_value_unknown")
        cap = float(cap)
    landing_url = picks.get("landing_url")
    if landing_url is not None:
        if not isinstance(landing_url, str):
            raise ValueError("landing_url_unknown")
        landing_url = landing_url.strip() or None
        if landing_url is not None:
            manual_settings.validate_landing_url(landing_url)
    return {
        "platform": platform, "audience_hint": audience_hint, "cap": cap,
        "landing_url": landing_url,
    }


def _sentence_sell_way(conn, brand_id: str, product_ids: list[str] | None) -> dict | None:
    """F50 (R6 B1): the first sell-way the sentence named that the wizard offers
    (`wizard_options.sellable_products`), shaped like `_check_picks`' result for
    `_sell_way_defaults`; `None` when the sentence named none."""
    if not product_ids:
        return None
    by_id = {p["id"]: p for p in wizard_options.sellable_products(conn, brand_id)}
    way = next((by_id[p] for p in product_ids if p in by_id), None)
    if way is None:
        return None
    return {
        "products": [way], "customer_group_ids": None,
        "group_ids": [g["id"] for g in wizard_options.customer_groups(conn, brand_id, way)],
    }


def _sell_way_defaults(conn, org_id: str, brand_id: str, checked: dict | None) -> dict:
    """F43-I04: what the picked sell-way supplies when the request does not -- `{group_ids,
    customer_group_ids (the request's override or None), landing_url, cap}`; F46-I08 adds
    `previous` (`wizard_options.previous_values` of the sell-way's previous campaign, or None),
    `break_even` (the whole break-even of its current economics) and `platform` (the brand's
    first connected channel). All empty with no sell-way (a sentence that named none); the
    caller still fills the brand's platform then (`create_draft`)."""
    if checked is None:
        return {"group_ids": [], "customer_group_ids": None, "landing_url": None, "cap": None,
                "previous": None, "break_even": None, "platform": None}
    way = checked["products"][0]
    today = coresettings.today_for_org(conn, org_id=org_id)
    cap = (wizard_options.current_economics(way, today) or {}).get("cap_per_sale")
    return {
        "group_ids": checked["group_ids"],
        "customer_group_ids": checked["customer_group_ids"],
        "landing_url": way.get("effective_landing_url") or None,
        "cap": float(cap) if cap is not None else None,
        "previous": wizard_options.previous_values(
            wizard_options.previous_campaign(conn, org_id, brand_id, way["id"])),
        "break_even": wizard_options.whole_break_even(way, today),
        "platform": wizard_options.default_platform(conn, org_id, brand_id),
    }


def set_landing_url(conn, org_id: str, brand_id: str, campaign_id: str, value) -> None:
    """F40-I04 (2b): the brief page's edit of `context_json.landing_url` -- a string (validated
    like a group's landing URL) or `None`/blank to clear; the slot's `field_sources` becomes
    `"user"`. Same refusals as the other draft edits: unknown campaign, imported campaign."""
    row = conn.execute(
        "SELECT origin, context_json FROM ads_campaign"
        " WHERE org_id = %s AND brand_id = %s AND id = %s FOR UPDATE",
        (org_id, brand_id, campaign_id),
    ).fetchone()
    if row is None:
        raise ValueError("campaign_unknown")
    if row["origin"] == "imported":
        raise ValueError(external_models.IMPORTED_REASON)
    if value is not None and not isinstance(value, str):
        raise ValueError("landing_url_unknown")
    landing_url = (value.strip() or None) if value is not None else None
    if landing_url is not None:
        manual_settings.validate_landing_url(landing_url)
    context = dict(row["context_json"] or {})
    context["landing_url"] = landing_url
    field_sources = dict(context.get("field_sources") or {})
    field_sources["landing_url"] = "user"
    context["field_sources"] = field_sources
    conn.execute(
        "UPDATE ads_campaign SET context_json = %s, updated_at = now()"
        " WHERE org_id = %s AND brand_id = %s AND id = %s",
        (jsonb(context), org_id, brand_id, campaign_id),
    )


def set_customer_groups(conn, org_id: str, brand_id: str, campaign_id: str, value, *,
                        picked: bool) -> None:
    """F43-I18: the draft's audience after a PATCH, against the campaign's *current* sell-way
    (call after `product_ids` is written). `picked` = the request carried `customer_group_ids`:
    validated with the create rule (`_check_customer_groups`, `customer_group_unknown`) -- a
    list of this sell-way's groups is the user's (`field_sources.audience = "user"`); `[]`/`None`
    is no override. Not picked (the sell-way changed) or no override -> every group of the
    sell-way, `"sell_way"` (`"system"` when it has none), as the create path stores it. Same
    refusals as the other draft edits: unknown campaign, imported campaign."""
    row = conn.execute(
        "SELECT origin, context_json FROM ads_campaign"
        " WHERE org_id = %s AND brand_id = %s AND id = %s FOR UPDATE",
        (org_id, brand_id, campaign_id),
    ).fetchone()
    if row is None:
        raise ValueError("campaign_unknown")
    if row["origin"] == "imported":
        raise ValueError(external_models.IMPORTED_REASON)
    context = dict(row["context_json"] or {})
    group_ids = [g["id"] for g in wizard_options.product_customer_groups(
        conn, brand_id, list(context.get("product_ids") or []),
    )]
    override = _check_customer_groups(value, group_ids) if picked else None
    if override is not None:
        customer_group_ids, source = override, "user"
    else:
        customer_group_ids, source = group_ids, ("sell_way" if group_ids else "system")
    context["customer_group_ids"] = customer_group_ids
    field_sources = dict(context.get("field_sources") or {})
    field_sources["audience"] = source
    context["field_sources"] = field_sources
    conn.execute(
        "UPDATE ads_campaign SET context_json = %s, updated_at = now()"
        " WHERE org_id = %s AND brand_id = %s AND id = %s",
        (jsonb(context), org_id, brand_id, campaign_id),
    )


def _amount_text(value: float) -> str:
    return str(int(value)) if float(value).is_integer() else str(value)


def _compose_goal_text(picks: dict, start: date, end: date) -> str:
    """The sentence a structured create stores as `goal_text` when the user typed none: the
    picks said back in words, nothing added (no audience, no promise, no guessed number)."""
    names = "、".join(p["name"] for p in picks["products"])
    return (
        f"推「{names}」，想要的結果：{objectives.label(picks['objective'])}，"
        f"期間 {start.isoformat()} ~ {end.isoformat()}，"
        f"這個活動最多花 {_amount_text(picks['budget'])}。"
    )


def create_draft(conn, org_id: str, brand_id: str, *, goal_text: str, start_date: str,
                  end_date: str, constraints: dict | None, actor: str,
                  picks: dict | None = None) -> dict:
    """一句話 -> 一列 `status='draft'` 的 `ads_campaign`。回傳值是 `campaign_detail()` 的
    形狀再加一個 `parsed` 鍵（這次呼叫解析成功與否，不落地，只是這次回應的旗標）。

    F30-I04（Contract D）：`picks`（`{product_ids, objective, budget}`）是建立精靈的結構化
    選擇——商品、目標、日期、預算上限都是使用者自己選的，模型的解析結果不能蓋過它們；
    `goal_text` 可以不填（由選擇組出一句話）；沒給日期時從組織自己的今天起算 30 天。
    模型照樣同步呼叫一次，只補受眾方向與附註（沒有排隊）。

    F40-I04：`picks` 另外可帶 `platform`／`audience_hint`／`cap`／`landing_url`（一句話路徑
    也收）。F43-I04：結構化路徑另收 `customer_group_ids`（這個賣法的顧客群）；沒帶的從賣法
    帶入（`_sell_way_defaults`）。F46-I08：平台、上限、預算先看同一個賣法的上一期（模組說明）。"""
    picks = dict(picks or {})
    structured = any(picks.get(key) is not None for key in _STRUCTURED_KEYS)
    if not structured and (not isinstance(goal_text, str) or not goal_text.strip()):
        raise ValueError("goal_text_required")
    # F04-I11：兩個都給 -> 照舊驗證（來源 user）；只給一個 -> 拒絕；兩個都沒給 -> 讓模型從
    # 句子判斷 `period`，等呼叫完再解析（R7：日曆算數在程式，不在 prompt 裡）。
    start = end = None
    if start_date or end_date:
        start, end = _validate_dates(start_date, end_date)
    constraints = dict(constraints or {})
    extras = _check_extras(picks)
    checked = _check_picks(conn, brand_id, picks) if structured else None
    if checked is None and picks.get("customer_group_ids") not in (None, []):
        raise ValueError("customer_group_unknown")  # groups belong to a picked sell-way
    # The sentence path resolves its defaults after the model named a sell-way (below).
    defaults = _sell_way_defaults(conn, org_id, brand_id, checked) if checked else None
    goal_composed = False
    dates_source = "user"
    if checked is not None:
        if start is None or end is None:
            today = coresettings.today_for_org(conn, org_id=org_id)
            start, end = today, today + timedelta(days=DEFAULT_PERIOD_DAYS)
            dates_source = "system"
        if not isinstance(goal_text, str) or not goal_text.strip():
            goal_text = _compose_goal_text(checked, start, end)
            goal_composed = True
        constraints["budget"] = checked["budget"]
    if extras["platform"] is not None:
        # An explicit platform pick is the user's own, like a chip -- it wins over the model.
        constraints["platform"] = extras["platform"]

    # F48 Contract P: a picked sell-way's knowledge (facts, claims, rules) is compiled for it, and
    # the prompt prints the sell-way and its 「不能講」 list from the one planner context.
    picked_id = checked["product_ids"][0] if checked is not None else None
    brand_text, knowledge_item_ids, brand_version, _product_version = context_compiler.compile(
        conn, brand_id, picked_id, include_personas=False,
    )
    picked_text = ""
    if picked_id is not None:
        ctx = planner_context.planner_context(conn, org_id, brand_id, picked_id)
        picked_text = "".join(
            "\n\n" + planner_context.section_text(ctx, which) for which in ("product", "forbidden")
        )
    products_text, economics_ids, brand_product_ids = _products_context(conn, org_id, brand_id)
    brand = bi_repo.get_brand(conn, brand_id) or {}
    conversion_goal = brand.get("conversion_goal")
    connected_channels = [
        {"key": channel["key"], "label": channel["label"]}
        for channel in channels.list_channels(conn, org_id, brand_id) if channel["connected"]
    ]
    brand_setup = {"conversion_goal": conversion_goal, "connected_channels": connected_channels}
    setup_text = json.dumps({
        **brand_setup,
        "conversion_goal_label": CONVERSION_GOAL_LABELS.get(conversion_goal or "", "尚未設定"),
    }, ensure_ascii=False)

    today = coresettings.today_for_org(conn, org_id=org_id)
    if start is not None and end is not None:
        period_text = f"{start.isoformat()} ~ {end.isoformat()}"
    else:
        period_text = "（使用者沒有指定，請從句子判斷 `period`）"

    department_text = DEPARTMENT_PATH.read_text(encoding="utf-8")
    prompt = (
        department_text
        + "\n\n## 使用者這句話\n\n" + goal_text
        + f"\n\n## 投放期間\n\n{period_text}"
        + f"\n\n今天是 {today.isoformat()}。"
        + "\n\n## 額外限制\n\n" + (str(constraints) if constraints else "（無）")
        + "\n\n## 品牌已知的事實\n\n" + (brand_text or "（這個品牌還沒有任何確認過的事實）")
        + "\n\n## 已保存的成效目標與平台設定\n\n" + setup_text
        + "\n使用者沒有另行指定時，沿用已知目標與平台作為建議依據；缺少的設定明示待確認。"
        + "平台已綁定只表示本機已有連線設定，不證明權限仍有效，也不表示目前活動已匯入。"
        + "品牌月額度不是本次活動預算；不要將它直接套入活動預算。"
        + "\n\n" + products_text
        + picked_text
    )

    context = gateway.TaskContext(
        context_scope={"brand_id": brand_id}, knowledge_item_ids=knowledge_item_ids,
        brand_version=brand_version,
    )
    task_row = gateway.run_task(
        conn, PROVIDER, brand_id=brand_id, task_type="ads_brief_parse",
        prompt_template_id="ads_brief_parse", prompt_template_version="v1",
        system=None, messages=[{"role": "user", "content": prompt}], context=context,
        options=gateway.TaskOptions(max_tokens=2000, timeout_s=60.0, max_retries=0),
    )

    parsed_ok = False
    fields = dict(_FALLBACK_PARSED)
    if task_row["status"] == "succeeded":
        data = gateway.parse_json_reply(task_row.get("rendered_output") or "")
        validated = _validate_reply(data) if data is not None else None
        if validated is not None:
            parsed_ok = True
            fields = validated

    # 日期：呼叫端給了兩個就是「你說的」；兩個都沒給就看模型從句子解析出來的 `period`
    # 算不算數——F50：模型讀出來的是 `"parsed"`（猜的，請確認），不是「你說的」；解析不出來
    # 才落到「今天～+30 天」那個備援（那一格才是「系統帶入」，ARCHITECTURE.md §6.1 第 11 條）。
    if start is None:
        resolved_start, resolved_end = _resolve_period(fields["period"], today=today)
        if resolved_start is not None:
            start, end = resolved_start, resolved_end
            dates_source = "parsed"
        else:
            start, end = today, today + timedelta(days=DEFAULT_PERIOD_DAYS)
            dates_source = "system"

    # 使用者自己填的限制（chips）永遠勝過模型解析的——只在使用者沒填這一格時才補進去。
    # F50 (planning #4／#12): a value the model parsed from the sentence is `"parsed"`, never
    # the user's own pick.
    parsed_keys = set()
    if fields["budget_cap"] is not None and "budget" not in constraints:
        constraints["budget"] = fields["budget_cap"]
        parsed_keys.add("budget")
    if fields["platform"] is not None and "platform" not in constraints:
        constraints["platform"] = fields["platform"]
        parsed_keys.add("platform")

    brand_product_id_set = set(brand_product_ids)
    product_ids = [p for p in fields["product_ids"] if p and p in brand_product_id_set] or None
    if checked is not None:
        # The user's picks win over whatever the model read back from the composed sentence.
        product_ids = checked["product_ids"]
        fields["objective"] = checked["objective"]
    else:
        # F50 (R6 B1): the sentence path fills platform and cap defaults exactly like the
        # structured path -- from the sell-way the sentence named, else the brand's platform.
        defaults = _sell_way_defaults(
            conn, org_id, brand_id, _sentence_sell_way(conn, brand_id, product_ids))

    # A stated value (request first, then what the sentence said) wins; F43-I04: whatever is
    # still empty comes from the picked sell-way (`defaults`), named `"sell_way"`.
    if checked is not None:
        # The audience of a structured create is the sell-way's customer groups: the model's
        # audience guess is not stored beside them (only a request's own hint is).
        audience_hint = extras["audience_hint"]
    else:
        audience_hint = extras["audience_hint"] or fields["audience_hint"]
        if not extras["audience_hint"] and audience_hint:
            parsed_keys.add("audience")
    if extras["cap"] is not None:
        target_cost = extras["cap"]
    else:
        # A sentence the program composed carries no cap the user stated: whatever the model
        # read as `cap` is dropped.
        target_cost = None if goal_composed else fields["cap"]
    if extras["cap"] is not None:
        cap_source = "user"
    else:  # F50: a cap the model read from the sentence is `parsed`, never the user's
        cap_source = "parsed" if target_cost is not None else "system"
    # F46-I08 (Contract D): the same sell-way's previous campaign first, then the sell-way's
    # own cap, then its break-even -- each stored as the campaign's own cap, so the cap the
    # form showed is the cap saved. A previous campaign without a cap falls through.
    previous = defaults["previous"] or {}
    platform_source = "user" if constraints.get("platform") is not None else "system"
    if "platform" in parsed_keys:
        platform_source = "parsed"
    if target_cost is None and previous.get("cap") is not None:
        target_cost, cap_source = previous["cap"], "copied"
    if constraints.get("platform") is None:
        if previous.get("platform") is not None:
            constraints["platform"], platform_source = previous["platform"], "copied"
        elif defaults["platform"] is not None:
            constraints["platform"], platform_source = defaults["platform"], "brand"
        elif checked is None:
            # F50 (R6 B1): a sentence that named no sell-way still gets the structured path's
            # platform default, the brand's first connected channel.
            fallback = wizard_options.default_platform(conn, org_id, brand_id)
            if fallback is not None:
                constraints["platform"], platform_source = fallback, "brand"
    if target_cost is None and defaults["cap"] is not None:
        target_cost, cap_source = defaults["cap"], "sell_way"
    if target_cost is None and defaults["break_even"] is not None:
        target_cost, cap_source = defaults["break_even"], "break_even"
    budget_source = "user" if constraints.get("budget") is not None else "system"
    if "budget" in parsed_keys:
        budget_source = "parsed"
    if checked is not None and previous.get("budget") is not None \
            and float(checked["budget"]) == previous["budget"]:
        budget_source = "copied"
    landing_url = extras["landing_url"]
    landing_source = "user" if landing_url else "system"
    if checked is not None and landing_url is None and defaults["landing_url"] is not None:
        landing_url, landing_source = defaults["landing_url"], "sell_way"
    audience_source = "user" if audience_hint else "system"
    if "audience" in parsed_keys:
        audience_source = "parsed"  # the model's guess is not the user's pick (planning #12)
    customer_group_ids = None
    if checked is not None:
        if defaults["customer_group_ids"] is not None:
            customer_group_ids, audience_source = defaults["customer_group_ids"], "user"
        else:
            customer_group_ids = defaults["group_ids"]
            audience_source = "sell_way" if customer_group_ids else audience_source

    field_sources = {
        "product": "user" if product_ids else "system",
        # F50: the wizard's pick is the user's; an objective the model read is `parsed`.
        "objective": "user" if checked is not None else "parsed" if parsed_ok else "system",
        "platform": platform_source,
        "budget": budget_source,
        "dates": dates_source,
        "audience": audience_source,
        "cap": cap_source,
        "landing_url": landing_source,
    }

    campaign = {
        "name": _draft_name(
            checked["products"][0]["name"] if checked is not None else goal_text, start, end,
        ),
        "goal_text": goal_text,
        "objective": fields["objective"],
        "target_cost": target_cost,
        "start_date": start,
        "end_date": end,
        "status": "draft",
        "context_json": {
            "brand_version": brand_version,
            "brand_setup": brand_setup,
            "product_ids": product_ids or [],
            "economics_ids": economics_ids,
            "llm_task_id": task_row["id"],
            "audience_hint": audience_hint,
            "landing_url": landing_url,
            "notes": fields["notes"],
            "field_sources": field_sources,
        },
        "constraints_json": constraints,
    }
    if customer_group_ids is not None:
        campaign["context_json"]["customer_group_ids"] = customer_group_ids
    row =ads_repo.create_campaign(conn, org_id, brand_id, campaign, created_by=actor)
    detail = ads_repo.campaign_detail(conn, org_id, brand_id, row["id"])
    assert detail is not None  # 剛剛才插入的那一列，一定讀得到
    detail["parsed"] = parsed_ok
    return detail
