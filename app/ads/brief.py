"""app/ads/brief.py — F03-I03: one sentence becomes a draft Campaign (§0 "golden path", the
**goal** link). Private to app/ads (container contract §1): only `routes.py` imports `create_draft`.

Input: the user's sentence plus dates/constraints, and the brand facts/products/product economics
that already exist — this never asks the user to re-enter them (`app/llm/context_compiler.py` for
confirmed brand facts, `app.brand_intelligence.repository` for products and today's effective
`product_economics`, both read-only). Output: one `ads_campaign` row in `status='draft'`. Trace:
`goal_text` verbatim, the `llm_task` row (via `gateway.run_task`), and `context_json` naming which
brand/product/economics rows fed the call.

Never dead-ends (same rule as `app/workbench/free_parse.py`'s `free_parse.parse()`): a failed,
timed-out or unparseable call still writes a usable draft — `objective='購買'`,
`success_metric='roas'`, `success_target=None`, `success_basis` explaining the sentence could not
be parsed — and the response carries `parsed: false` instead of raising.
"""

from datetime import date

from app.ads import repository as ads_repo
from app.brand_intelligence import repository as bi_repo
from app.core import settings as coresettings
from app.core.db import APP_DIR
from app.llm import context_compiler, gateway, providers

DEPARTMENT_PATH = APP_DIR / "departments" / "ads" / "brief_parse.md"

# 唯一的供應商實例，比照 app/workbench/free_parse.py：測試用
# `mock.patch.object(brief, "PROVIDER", FakeProvider(...))` 換掉。
PROVIDER = providers.AnthropicProvider()

_OBJECTIVES = frozenset({"購買", "加購物車", "名單", "流量", "知名度"})
_SUCCESS_METRICS = frozenset({"cpa", "roas", "purchases"})

NOT_PARSED_BASIS = "AI 沒能整理出可信的目標，這是預設值，請自己填一個成功條件。"
DATES_REQUIRED_MESSAGE = "請填投放的開始與結束日期。"
END_BEFORE_START_MESSAGE = "結束日期不能早於開始日期。"

_FALLBACK_PARSED = {
    "objective": "購買", "success_metric": "roas", "success_target": None,
    "success_basis": NOT_PARSED_BASIS, "product_ids": [], "audience_hint": None, "notes": None,
}


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


def _products_context(conn, org_id: str, brand_id: str) -> tuple[str, list[str], list[str]]:
    """商品清單＋今天有效的 `product_economics`，供 prompt 用；回傳 (prompt 文字段落,
    實際引用到的 economics id 清單, 這個品牌自己的商品 id 清單)——過期的價格（`effective_to`
    已經過去）照樣列出，只是標「已過期」，絕不悄悄當成現在有效的價格用（§0「a price whose
    effective window has passed is passed in labelled stale」）。商品 id 清單同時是
    `create_draft` 過濾模型瞎掰的 `product_ids` 用的唯一名單（F03-I19，別重複收集一次）。"""
    products = bi_repo.list_products(conn, brand_id)
    if not products:
        return "【商品清單】（品牌還沒有任何商品）", [], []

    today = coresettings.today_for_org(conn, org_id=org_id)
    lines = []
    economics_ids = []
    for product in products:
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
    return "【商品清單】\n" + "\n".join(lines), economics_ids, [p["id"] for p in products]


def _validate_reply(data) -> dict | None:
    if not isinstance(data, dict):
        return None
    objective = data.get("objective")
    if objective not in _OBJECTIVES:
        return None
    success_metric = data.get("success_metric")
    if success_metric not in _SUCCESS_METRICS:
        return None
    success_target = data.get("success_target")
    if success_target is not None and (
        isinstance(success_target, bool) or not isinstance(success_target, (int, float))
    ):
        return None
    product_ids = data.get("product_ids")
    if not isinstance(product_ids, list) or not all(isinstance(p, str) for p in product_ids):
        product_ids = []
    audience_hint = data.get("audience_hint")
    notes = data.get("notes")
    success_basis = data.get("success_basis")
    return {
        "objective": objective, "success_metric": success_metric,
        "success_target": float(success_target) if success_target is not None else None,
        "success_basis": success_basis if isinstance(success_basis, str) else None,
        "product_ids": product_ids,
        "audience_hint": audience_hint if isinstance(audience_hint, str) else None,
        "notes": notes if isinstance(notes, str) else None,
    }


def _draft_name(goal_text: str) -> str:
    """草稿名稱：使用者這句話的前 40 字——使用者在畫面上隨時可以改（`PATCH .../campaigns/{id}`
    的 `name` 欄位），這裡只給一個不空白的起點。"""
    text = goal_text.strip()
    return text if len(text) <= 40 else text[:40] + "…"


def create_draft(conn, org_id: str, brand_id: str, *, goal_text: str, start_date: str,
                  end_date: str, constraints: dict | None, actor: str) -> dict:
    """一句話 -> 一列 `status='draft'` 的 `ads_campaign`。回傳值是 `campaign_detail()` 的
    形狀再加一個 `parsed` 鍵（這次呼叫解析成功與否，不落地，只是這次回應的旗標）。"""
    if not isinstance(goal_text, str) or not goal_text.strip():
        raise ValueError("goal_text_required")
    start, end = _validate_dates(start_date, end_date)
    constraints = constraints or {}

    brand_text, knowledge_item_ids, brand_version, _product_version = context_compiler.compile(
        conn, brand_id, include_personas=False,
    )
    products_text, economics_ids, brand_product_ids = _products_context(conn, org_id, brand_id)

    department_text = DEPARTMENT_PATH.read_text(encoding="utf-8")
    prompt = (
        department_text
        + "\n\n## 使用者這句話\n\n" + goal_text
        + f"\n\n## 投放期間\n\n{start.isoformat()} ~ {end.isoformat()}"
        + "\n\n## 額外限制\n\n" + (str(constraints) if constraints else "（無）")
        + "\n\n## 品牌已知的事實\n\n" + (brand_text or "（這個品牌還沒有任何確認過的事實）")
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

    brand_product_id_set = set(brand_product_ids)
    product_ids = [p for p in fields["product_ids"] if p and p in brand_product_id_set] or None
    campaign = {
        "name": _draft_name(goal_text),
        "goal_text": goal_text,
        "objective": fields["objective"],
        "success_metric": fields["success_metric"],
        "success_target": fields["success_target"],
        "success_basis": fields["success_basis"],
        "start_date": start,
        "end_date": end,
        "status": "draft",
        "context_json": {
            "brand_version": brand_version,
            "product_ids": product_ids or [],
            "economics_ids": economics_ids,
            "llm_task_id": task_row["id"],
            "audience_hint": fields["audience_hint"],
            "notes": fields["notes"],
        },
        "constraints_json": constraints,
    }
    row = ads_repo.create_campaign(conn, org_id, brand_id, campaign, created_by=actor)
    detail = ads_repo.campaign_detail(conn, org_id, brand_id, row["id"])
    assert detail is not None  # 剛剛才插入的那一列，一定讀得到
    detail["parsed"] = parsed_ok
    return detail
