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
"""

import calendar
import json
import math
from datetime import date, timedelta

from app.ads import channels, objectives
from app.ads import repository as ads_repo
from app.brand_intelligence import repository as bi_repo
from app.core import settings as coresettings
from app.core.db import APP_DIR
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


def _draft_name(goal_text: str) -> str:
    """草稿名稱：使用者這句話的前 40 字——使用者在畫面上隨時可以改（`PATCH .../campaigns/{id}`
    的 `name` 欄位），這裡只給一個不空白的起點。"""
    text = goal_text.strip()
    return text if len(text) <= 40 else text[:40] + "…"


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
    if (not isinstance(product_ids, list) or not product_ids
            or not all(isinstance(p, str) and p for p in product_ids)):
        raise ValueError("products_required")
    by_id = {p["id"]: p for p in bi_repo.list_products(conn, brand_id)}
    if any(p not in by_id for p in product_ids):
        raise ValueError("product_unknown")
    product_ids = list(dict.fromkeys(product_ids))
    return {
        "product_ids": product_ids, "products": [by_id[p] for p in product_ids],
        "objective": objective, "budget": budget,
    }


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
    模型照樣同步呼叫一次，只補受眾方向與附註（沒有排隊）。"""
    structured = picks is not None
    if not structured and (not isinstance(goal_text, str) or not goal_text.strip()):
        raise ValueError("goal_text_required")
    # F04-I11：兩個都給 -> 照舊驗證（來源 user）；只給一個 -> 拒絕；兩個都沒給 -> 讓模型從
    # 句子判斷 `period`，等呼叫完再解析（R7：日曆算數在程式，不在 prompt 裡）。
    start = end = None
    if start_date or end_date:
        start, end = _validate_dates(start_date, end_date)
    constraints = dict(constraints or {})
    checked = _check_picks(conn, brand_id, picks) if picks is not None else None
    dates_source = "user"
    if checked is not None:
        if start is None or end is None:
            today = coresettings.today_for_org(conn, org_id=org_id)
            start, end = today, today + timedelta(days=30)
            dates_source = "system"
        if not isinstance(goal_text, str) or not goal_text.strip():
            goal_text = _compose_goal_text(checked, start, end)
        constraints["budget"] = checked["budget"]

    brand_text, knowledge_item_ids, brand_version, _product_version = context_compiler.compile(
        conn, brand_id, include_personas=False,
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
    # 算不算數（算得出來也是「你說的」——句子裡講了時間），解析不出來才落到「今天～+30 天」
    # 那個備援（那一格才是「系統帶入」，ARCHITECTURE.md §6.1 第 11 條）。
    if start is None:
        resolved_start, resolved_end = _resolve_period(fields["period"], today=today)
        if resolved_start is not None:
            start, end = resolved_start, resolved_end
        else:
            start, end = today, today + timedelta(days=30)
            dates_source = "system"

    # 使用者自己填的限制（chips）永遠勝過模型解析的——只在使用者沒填這一格時才補進去。
    if fields["budget_cap"] is not None and "budget" not in constraints:
        constraints["budget"] = fields["budget_cap"]
    if fields["platform"] is not None and "platform" not in constraints:
        constraints["platform"] = fields["platform"]

    brand_product_id_set = set(brand_product_ids)
    product_ids = [p for p in fields["product_ids"] if p and p in brand_product_id_set] or None
    if checked is not None:
        # The user's picks win over whatever the model read back from the composed sentence.
        product_ids = checked["product_ids"]
        fields["objective"] = checked["objective"]

    field_sources = {
        "product": "user" if product_ids else "system",
        "objective": "user" if parsed_ok or checked is not None else "system",
        "platform": "user" if constraints.get("platform") is not None else "system",
        "budget": "user" if constraints.get("budget") is not None else "system",
        "dates": dates_source,
        "audience": "user" if fields["audience_hint"] else "system",
    }

    campaign = {
        "name": _draft_name(goal_text),
        "goal_text": goal_text,
        "objective": fields["objective"],
        "target_cost": fields["cap"],
        "start_date": start,
        "end_date": end,
        "status": "draft",
        "context_json": {
            "brand_version": brand_version,
            "brand_setup": brand_setup,
            "product_ids": product_ids or [],
            "economics_ids": economics_ids,
            "llm_task_id": task_row["id"],
            "audience_hint": fields["audience_hint"],
            "notes": fields["notes"],
            "field_sources": field_sources,
        },
        "constraints_json": constraints,
    }
    row = ads_repo.create_campaign(conn, org_id, brand_id, campaign, created_by=actor)
    detail = ads_repo.campaign_detail(conn, org_id, brand_id, row["id"])
    assert detail is not None  # 剛剛才插入的那一列，一定讀得到
    detail["parsed"] = parsed_ok
    return detail
