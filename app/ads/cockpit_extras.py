# -*- coding: utf-8 -*-
"""T3 駕駛艙補充資料；只讀既有公開品牌資料與 task_card。"""

from app.ads import repository_channel_plan as plans
from app.brand_intelligence import repository as intelligence


def _legacy(conn, brand_id: str) -> list:
    rules = intelligence.list_rules_for_brand(conn, brand_id)
    learnings = intelligence.list_learning_ledger(conn, brand_id)
    hypotheses = intelligence.list_strategy_hypotheses(conn, brand_id)
    voices = intelligence.list_customer_voices(conn, brand_id)
    products = intelligence.list_products(conn, brand_id)
    return [
        {"key": "wisdom", "value": len(learnings)},
        {"key": "effective_direction", "value": sum(1 for h in hypotheses if h.get("status") == "supported")},
        {"key": "prohibition", "value": sum(1 for r in rules if r.get("rule_type") == "prohibition")},
        {"key": "material_stock", "value": len(intelligence.list_official_assets(conn, brand_id))},
        {"key": "customer_understanding", "value": bool(voices)},
    ], products


def _product_completeness(conn, brand_id: str, products: list) -> int:
    """品牌檔案的產品必填資料完成率，不把資料列數當成百分比。"""
    if not products:
        return 0
    filled = 0
    total = len(products) * 3  # 名稱、產品事實、產品經濟數字三個既有必填面向。
    for product in products:
        counts = dict(intelligence.count_product_data(conn, brand_id, product["id"]))
        filled += int(bool(product.get("name")))
        filled += int(bool(counts.get("產品事實")))
        filled += int(bool(counts.get("產品經濟數據")))
    return round(filled * 100 / total)


def get(conn, brand_id: str, cycle_id: str) -> dict:
    legacy, products = _legacy(conn, brand_id)
    return {
        "legacy": legacy,
        "task_cards": plans.list_task_cards(conn, brand_id, cycle_id),
        "todo3": {"product_completeness": _product_completeness(conn, brand_id, products),
                  "good_customer_defined": bool(legacy[-1]["value"]),
                  "reply_speed": None},
    }


def mark_done(conn, brand_id: str, card_id: str) -> dict:
    card = plans.get_task_card(conn, brand_id, card_id)
    if card is None:
        raise ValueError("找不到任務卡")
    return plans.update_task_card(conn, brand_id, card_id, title=card["title"],
                                  draft_hint=card.get("draft_hint"), done=True)
