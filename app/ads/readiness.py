"""app/ads/readiness.py — F05-I04: the launch readiness checklist (ARCHITECTURE.md §8 第 5 條).
演練四兩個人在第七站才發現地基是空的（product 0 列、brand_fact 0 列，畫面零提醒）——這支是「一個
品牌要能投放，最少要有什麼」第一次被定義的地方，程式算、三種顏色、**永遠不擋人**。

F42-I02: the rows are the brand rows the brand-onboarding completion screen (`#/b7`) lists, in
its order -- 品牌是誰 (`identity`)、證據與政策 (`evidence`)、素材 (`media`)、廣告帳戶 (`channel`,
which now also carries the conversion goal; the separate `goal` row is merged into it)、商品
(`offering`). Each brand row's fix link opens its own onboarding step (`/intake?step=3..6`); the
offering row opens the products page.

Public entry: `app.ads.launch_readiness`（`app/ads/__init__.py` 匯出）。純讀取：不寫任何東西、
不打模型。只走既有 facade（`app.brand_intelligence.repository`、`app.ads.channels`、
`app.ads.budget.breakeven_cpa`）——不寫 SQL、不 import `app.meta`、不出現 `"meta"` 字串（平台名字
只准住在 `app/ads/channels.py`）。
"""

from app.ads import channels
from app.ads.budget import breakeven_cpa
from app.brand_intelligence import repository as bi_repo
from app.core.vocab import CONVERSION_GOAL_LABELS, COOLING_OFF_EXEMPT_KEY

_ASSUMPTION_FIELD_LABELS = {
    "cost": "每單成本", "shipping": "運費", "close_rate": "成交率",
}

_MEDIA_REASONS = {"photo": "素材：只有照片", "photo_video": "素材：照片和影片"}


def _intake_step(brand_id: str, step: int) -> str:
    return f"/brands/{brand_id}/intake?step={step}"


def _identity_item(confirmed: list, brand_id: str) -> dict:
    """Green when the brand's positioning and tone are both confirmed facts (onboarding step 3)."""
    types = {fact["fact_type"] for fact in confirmed}
    fix = {"label": "品牌是誰", "fix_href": _intake_step(brand_id, 3)}
    if {"positioning", "tone"} <= types:
        return {"key": "identity", "state": "green", "reason": "一句話和口氣已確認。",
                "fix_label": "去改", **fix}
    return {"key": "identity", "state": "yellow", "reason": "還沒確認品牌的一句話和口氣。",
            "fix_label": "去確認品牌是誰", **fix}


def _evidence_item(confirmed: list, brand_id: str) -> dict:
    """Green with at least one confirmed proof or store-policy fact (onboarding step 4). The
    cooling-off exemption is a legal notice, not something an ad can say, so it is not counted."""
    proof = sum(1 for fact in confirmed if fact["fact_type"] == "proof")
    policy = sum(1 for fact in confirmed if fact["fact_type"] == "policy"
                 and fact.get("fact_key") != COOLING_OFF_EXEMPT_KEY)
    fix = {"label": "證據與政策", "fix_href": _intake_step(brand_id, 4)}
    if proof or policy:
        return {"key": "evidence", "state": "green",
                "reason": f"品牌證據 {proof} 項・政策 {policy} 項", "fix_label": "去改", **fix}
    return {"key": "evidence", "state": "yellow",
            "reason": "還沒有登記證據或政策；廣告只會講產品本身",
            "fix_label": "去登記證據與政策", **fix}


def _media_item(brand: dict, brand_id: str) -> dict:
    """`brand.media_capability` (onboarding step 5); NULL = never asked -> yellow."""
    fix = {"label": "素材", "fix_href": _intake_step(brand_id, 5)}
    reason = _MEDIA_REASONS.get(brand.get("media_capability") or "")
    if reason:
        return {"key": "media", "state": "green", "reason": reason, "fix_label": "去改", **fix}
    return {"key": "media", "state": "yellow",
            "reason": "還沒選手上有哪些素材；規劃會照常排影片格。",
            "fix_label": "去選素材", **fix}


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

    fix = {"label": "商品", "fix_href": f"/brands/{brand_id}/products"}
    if not products:
        return {
            "key": "offering", "state": "red", "reason": "還沒有商品",
            "fix_label": "建第一個商品", **fix,
        }
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


def _account_part(conn, org_id: str, brand_id: str) -> tuple[str, str, str]:
    """(state, reason, fix_label) of the ad account alone."""
    account = channels.account_state(conn, org_id, brand_id)
    if account is None:
        return "red", "還沒接上廣告帳戶。", "去接廣告帳戶"
    if not account["backfill_done"]:
        reason = (
            "花費還在拉，拉完才能用近 30 天當預算依據。"
            if account["backfill_running"]
            else "這個帳戶還沒有任何花費紀錄，預算只能先用你填的數字。"
        )
        return "yellow", reason, "去改"
    return "green", f"已接上 {account['label']}，花費資料齊全。", "去接廣告帳戶"


def _channel_item(conn, org_id: str, brand: dict, brand_id: str) -> dict:
    """The ad account plus the conversion goal (onboarding step 6 asks both): the reason names
    the goal, and a missing goal makes the row red whatever the account's state."""
    state, reason, fix_label = _account_part(conn, org_id, brand_id)
    goal = brand.get("conversion_goal")
    if goal:
        goal_text = CONVERSION_GOAL_LABELS.get(goal, goal)
    else:
        goal_text = "還沒設定"
        if state != "red":
            fix_label = "去設定成效目標"
        state = "red"
    return {
        "key": "channel", "label": "廣告帳戶", "state": state,
        "reason": f"{reason.rstrip('。')}・成效目標：{goal_text}",
        "fix_label": fix_label, "fix_href": _intake_step(brand_id, 6),
    }


_STATE_RANK = {"green": 0, "yellow": 1, "red": 2}

_PRIMARY_BY_STATE = {
    "red": "先補齊地基",
    "yellow": "進入投放中心（有假設值）",
    "green": "進入投放中心",
}


def launch_readiness(conn, org_id: str, brand_id: str) -> dict:
    brand = bi_repo.get_brand(conn, brand_id) or {}
    confirmed = bi_repo.list_brand_facts(conn, brand_id, status="confirmed")
    items = [
        _identity_item(confirmed, brand_id),
        _evidence_item(confirmed, brand_id),
        _media_item(brand, brand_id),
        _channel_item(conn, org_id, brand, brand_id),
        _offering_item(conn, brand_id),
    ]
    state = max((item["state"] for item in items), key=lambda s: _STATE_RANK[s])

    notes = [{"key": "knowledge", "text": f"品牌知識 {len(confirmed)} 條（已確認）"}]

    ads_href = f"/brands/{brand_id}/ads"
    primary = {"label": _PRIMARY_BY_STATE[state], "href": ads_href}
    secondary = None
    if state == "red":
        worst = max(items, key=lambda item: _STATE_RANK[item["state"]])
        primary = {"label": "先補齊地基", "href": worst["fix_href"]}
        secondary = {"label": "還是要先建立", "href": f"/brands/{brand_id}/ads/new"}

    return {
        "state": state, "items": items, "notes": notes,
        "primary": primary, "secondary": secondary,
    }
