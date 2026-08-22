# -*- coding: utf-8 -*-
"""T3 開檔建議的純規則。

對外進入點：opening_suggestion() 與 save_channel_answer()。
輸入輸出：收 SQLite 連線、brand_id（後者另收 actor/answer），回傳凍結的 JSON dict 形狀。
誰依賴它：routes_campaigns_open_api.py。
不碰什麼：不呼叫 LLM，不 import app.orders、app.dashboard，也不對品牌永久層下原生 SQL。
"""

from collections import defaultdict

from app.ads import budget
from app.ads import nextcycle
from app.ads import repository as ads_repo
from app.ads import target_cpa
from app.brand_intelligence import repository as bi


CHANNEL_ASK = {
    "question": "客人主要去哪買？",
    "options": ["官網", "LINE", "蝦皮等平台", "實體店"],
}

_ANSWER_CHANNEL = {
    "官網": ("website", "官方網站", "web"),
    "LINE": ("line", "LINE", "line"),
    "蝦皮等平台": ("marketplace", "平台商店", "marketplace"),
    "實體店": ("physical_store", "實體店", "store"),
}


def _unavailable(reason: str, *, ask_for_channel: bool = True) -> dict:
    response = {"available": False, "reason": reason}
    if ask_for_channel:
        response["channel_ask"] = CHANNEL_ASK
    return response


def _active_products(conn, brand_id: str) -> list:
    return [product for product in bi.list_products(conn, brand_id) if product["status"] == "active"]


def _historical_products(conn, brand_id: str) -> dict:
    """歷來每個產品累積的轉換數：切角有 product_id 直接記；沒有時退用該切角所屬檔期的
    產品（跟 `historical_cell_performance()` 算打平線時同一條退路，D4），轉換數均分給
    那些產品後累加。每個 cycle_id 只查一次、快取起來。
    ponytail：均分是刻意的簡化，同期產品均分，之後切角有自己的 product_id 再改用真實歸屬。
    """
    totals = defaultdict(float)
    cycle_products_cache: dict = {}
    for cell in nextcycle.historical_cell_performance(conn, brand_id):
        conversions = float(cell.get("conversions") or 0)
        product_id = cell.get("product_id")
        if product_id:
            totals[product_id] += conversions
            continue
        cycle_id = cell.get("campaign_cycle_id")
        if cycle_id not in cycle_products_cache:
            cycle_products_cache[cycle_id] = ads_repo.list_cycle_products(conn, brand_id, cycle_id)
        cycle_products = cycle_products_cache[cycle_id]
        if not cycle_products:
            continue
        share = conversions / len(cycle_products)
        for cycle_product in cycle_products:
            totals[cycle_product["product_id"]] += share
    return totals


def _choose_product(conn, brand_id: str) -> tuple[dict | None, str]:
    products = _active_products(conn, brand_id)
    if not products:
        return None, ""
    history = _historical_products(conn, brand_id)
    candidates = [product for product in products if product["id"] in history]
    if candidates:
        return max(candidates, key=lambda product: (history[product["id"]], product["name"])), "沿用有效方向"
    # 「首次」看跑過任何一期沒有，不是看湊不湊得出 history（history 湊不出東西不等於沒開過檔期）。
    label = "首次" if not ads_repo.has_any_cycle(conn, brand_id) else "推新品"
    if len(products) == 1:
        return products[0], label
    margins = {
        product["id"]: budget.gross_margin(bi.get_product_economics(conn, brand_id, product["id"]))
        for product in products
    }
    chosen = max(
        products,
        key=lambda product: (margins[product["id"]] if margins[product["id"]] is not None else float("-inf"),
                             product["name"]),
    )
    return chosen, label


def _last_closed_budget(conn, brand_id: str):
    """最近一期 CLOSED 檔期存的覆盤建議預算（D2/D3）：只看 `list_cycles()` 排序下第一個
    CLOSED 檔期，讀 `nextcycle.load()` 存好的 proposed_budget，不重算、不往更舊的翻。
    取不到、或值 <= 0 → None（表示改用今天的痛點金額）。"""
    for cycle in ads_repo.list_cycles(conn, brand_id):
        if cycle["status"] != "CLOSED":
            continue
        stored = nextcycle.load(conn, brand_id, cycle["id"])
        if not stored:
            return None
        amount = (stored["content"].get("budget") or {}).get("proposed_budget")
        return amount if amount and amount > 0 else None
    return None


def opening_suggestion(conn, brand_id: str) -> dict:
    """依既有商品、歷史、預算引擎組出開檔預填；任何缺口回人話失敗形狀。"""
    try:
        if not any(channel["status"] == "active" for channel in bi.list_channels(conn, brand_id)):
            return _unavailable("還不知道客人主要去哪買，先選一個讓我幫你安排。")
        product, direction = _choose_product(conn, brand_id)
        if product is None:
            return _unavailable("還沒有可主打的商品，先補一項商品資料。", ask_for_channel=False)
        pain = target_cpa.suggest_pain_value(conn, brand_id, "sales", [product["id"]])
        last_closed = _last_closed_budget(conn, brand_id)
        basis = "closing_review" if last_closed else "pain_amount"
        basis_text = "依上一期覆盤建議" if basis == "closing_review" else "依你設定的痛點金額"
        plan = budget.plan_from_pain(last_closed or pain["amount"])
        suggestion = {
            "platform": "meta", "product_id": product["id"], "product_name": product["name"],
            "budget": plan.total_budget, "duration_days": plan.duration_days, "direction": direction,
        }
        summary = (
            f"這期先用 Meta 推 {product['name']}，預算 NT${plan.total_budget:,.0f}（{basis_text}）、"
            f"跑 {plan.duration_days} 天；{direction}，讓這期有清楚的起點可以觀察。"
        )
        return {"available": True, "summary": summary, "suggestion": suggestion, "channel_ask": None,
                "budget_basis": basis}
    except Exception:  # noqa: BLE001 — 開檔不能被建議失敗擋住
        return {"available": False, "reason": "建議暫時整理不出來，你可以直接手動開檔。"}


def save_channel_answer(conn, brand_id: str, *, actor: str, answer: str) -> dict:
    """把四選一答案寫入既有 owned_channel，再立即回傳同一份建議。"""
    channel = _ANSWER_CHANNEL.get(answer)
    if channel is None:
        return _unavailable("請從四個選項中選一個常用的購買方式。")
    channel_type, name, platform = channel
    current = bi.list_channels(conn, brand_id)
    if not any(row["channel_type"] == channel_type and row["status"] == "active" for row in current):
        bi.create_channel(conn, brand_id, actor=actor, channel_type=channel_type, name=name, platform=platform)
    return opening_suggestion(conn, brand_id)
