"""app/ads/readiness.py — F05-I04: the launch readiness checklist (ARCHITECTURE.md §8 第 5 條).
演練四兩個人在第七站才發現地基是空的（product 0 列、brand_fact 0 列，畫面零提醒）——這支是「一個
品牌要能投放，最少要有什麼」第一次被定義的地方，程式算、三種顏色、**永遠不擋人**。

Public entry: `app.ads.launch_readiness`（`app/ads/__init__.py` 匯出）。純讀取：不寫任何東西、
不打模型。只走既有 facade（`app.brand_intelligence.repository`、`app.ads.channels`、
`app.ads.budget.breakeven_cpa`）——不寫 SQL、不 import `app.meta`、不出現 `"meta"` 字串（平台名字
只准住在 `app/ads/channels.py`）。
"""

from app.ads import channels
from app.ads.budget import breakeven_cpa
from app.brand_intelligence import repository as bi_repo
from app.core.vocab import CONVERSION_GOAL_LABELS

_ASSUMPTION_FIELD_LABELS = {
    "cost": "每單成本", "shipping": "運費", "close_rate": "成交率",
}


def _offering_item(conn, brand_id: str) -> dict:
    products = bi_repo.list_products(conn, brand_id)
    best_economics = None
    assumed_product_name = None
    assumed_fields: list[str] = []
    for product in products:
        economics = bi_repo.get_product_economics(conn, brand_id, product["id"])
        assumptions = economics.get("assumptions_json") if economics else None
        if assumptions and assumed_product_name is None:
            assumed_product_name = product["name"]
            assumed_fields = list(assumptions)
        if breakeven_cpa(economics) is not None and best_economics is None:
            best_economics = economics

    fix = {"label": "賣的東西與數字", "fix_href": f"/brands/{brand_id}/intake"}
    if best_economics is None:
        return {
            "key": "offering", "state": "red",
            "reason": "還沒有任何一項賣的東西填得出數字。",
            "fix_label": "去補商品與數字", **fix,
        }
    if assumed_product_name is not None:
        fields = "、".join(_ASSUMPTION_FIELD_LABELS.get(f, f) for f in assumed_fields)
        return {
            "key": "offering", "state": "yellow",
            "reason": f"用假設值：{assumed_product_name}的{fields} — 之後用真實數字取代。",
            "fix_label": "去改", **fix,
        }
    return {
        "key": "offering", "state": "green",
        "reason": "有賣法算得出打平 CPA。",
        "fix_label": "去補商品與數字", **fix,
    }


def _goal_item(brand: dict, brand_id: str) -> dict:
    goal = brand.get("conversion_goal")
    fix = {
        "label": "成效目標", "fix_label": "去設定成效目標",
        "fix_href": f"/brands/{brand_id}/intake",
    }
    if not goal:
        return {"key": "goal", "state": "red", "reason": "還沒設定成效目標。", **fix}
    label = CONVERSION_GOAL_LABELS.get(goal, goal)
    return {"key": "goal", "state": "green", "reason": f"成效目標：{label}。", **fix}


def _channel_item(conn, org_id: str, brand_id: str) -> dict:
    fix_href = f"/brands/{brand_id}/intake"
    account = channels.account_state(conn, org_id, brand_id)
    if account is None:
        return {
            "key": "channel", "label": "廣告帳戶", "state": "red",
            "reason": "還沒接上廣告帳戶。", "fix_label": "去接廣告帳戶", "fix_href": fix_href,
        }
    if not account["backfill_done"]:
        reason = (
            "花費還在拉，拉完才能用近 30 天當預算依據。"
            if account["backfill_running"]
            else "這個帳戶還沒有任何花費紀錄，預算只能先用你填的數字。"
        )
        return {
            "key": "channel", "label": "廣告帳戶", "state": "yellow",
            "reason": reason,
            "fix_label": "去改", "fix_href": fix_href,
        }
    return {
        "key": "channel", "label": "廣告帳戶", "state": "green",
        "reason": f"已接上 {account['label']}，花費資料齊全。",
        "fix_label": "去接廣告帳戶", "fix_href": fix_href,
    }


_STATE_RANK = {"green": 0, "yellow": 1, "red": 2}

_PRIMARY_BY_STATE = {
    "red": "先補齊地基",
    "yellow": "進入投放中心（有假設值）",
    "green": "進入投放中心",
}


def launch_readiness(conn, org_id: str, brand_id: str) -> dict:
    brand = bi_repo.get_brand(conn, brand_id)
    items = [
        _offering_item(conn, brand_id),
        _goal_item(brand or {}, brand_id),
        _channel_item(conn, org_id, brand_id),
    ]
    state = max((item["state"] for item in items), key=lambda s: _STATE_RANK[s])

    confirmed = bi_repo.list_brand_facts(conn, brand_id, status="confirmed")
    notes = [{"key": "knowledge", "text": f"品牌知識 {len(confirmed)} 條（已確認）"}]

    ads_href = f"/brands/{brand_id}/ads"
    primary = {"label": _PRIMARY_BY_STATE[state], "href": ads_href}
    secondary = None
    if state == "red":
        primary = {"label": "先補齊地基", "href": f"/brands/{brand_id}/intake"}
        secondary = {"label": "還是要先建立", "href": f"/brands/{brand_id}/ads/new"}

    return {
        "state": state, "items": items, "notes": notes,
        "primary": primary, "secondary": secondary,
    }
