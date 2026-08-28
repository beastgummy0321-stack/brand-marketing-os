"""app/brand_web/routes_product_helpers.py — 產品調研共用工具（T4 刪除品牌／產品管理舊頁
時搬出）。

這三個函式原本定義在 app/brand_web/routes.py，供舊版 Jinja 頁面的 handler（產品新增
AI 調研／再次調研／調研交接包貼回等）使用；那些 handler 都已被 React 新殼取代
（改走 `/api/products/...`）並整批刪除，但 `app/brand_web/routes_products.py` 的
/api 端點仍在重用這幾個函式（不重寫第二份業務邏輯，見該檔檔頭註解），所以搬出來
獨立成檔，不掛在已經沒有其他理由留著這幾個函式的舊檔裡。

進入點：本檔函式（純工具，不掛 router）。誰依賴：app/brand_web/routes_products.py。
"""


from app.brand_intelligence import product_ai
from app.brand_intelligence import repository as repo
from app.shared import web


def _scan_budget_error(brand_id: str, cost: float | None = None, action: str = "這次調研",
                        fallback_hint: str = "或先用「新增這個產品」手動建立。") -> str | None:
    """產品快掃／再次調研／調研交接包貼回修復共用的超預算檢查，通過回 None。

    票 M2：核心檢查（已花費 + 這次預估 vs 上限，US$ 三個數字同一幣別直接比）搬進
    app/core/settings.budget_exceeded_message()——廣告分支的計畫／素材生成現在也共用
    同一個函式，這裡只是保留原本的呼叫簽名（cost 預設值＝產品快掃的校準值）給既有呼叫端用。
    """
    from app.core import settings as coresettings
    cost = product_ai.COST_PRODUCT_SCAN if cost is None else cost
    org_id = repo._org_id_for_brand(web.conn, brand_id)
    return coresettings.budget_exceeded_message(
        web.conn, brand_id, cost, org_id=org_id, action=action, fallback_hint=fallback_hint)


def _apply_product_scan_result(brand_id: str, product_id: str, actor: str,
                                source_reference_id: str | None, result: dict) -> tuple:
    """把快掃／再次調研結果套進一個產品：跳過跟既有事實（不論 pending 或 confirmed）同 label
    的結果，避免重複堆積；價格有抓到且這個產品目前完全沒有經濟數字列時，才建一筆 pending。
    回傳 (新增事實數, 跳過事實數, 是否新建了待確認經濟數字)。"""
    existing_labels = {f["label"] for f in repo.list_product_facts(web.conn, brand_id, product_id)}
    added, skipped = 0, 0
    for f in result["facts"]:
        if f["label"] in existing_labels:
            skipped += 1
            continue
        repo.create_product_fact(web.conn, brand_id, product_id, actor=actor,
                                 fact_type=f["fact_type"], label=f["label"], value=f["value"],
                                 status="pending", source_reference_id=source_reference_id)
        existing_labels.add(f["label"])
        added += 1
    price_created = False
    price = result.get("price")
    if price and repo.get_product_economics(web.conn, brand_id, product_id) is None:
        repo.create_pending_product_economics(
            web.conn, brand_id, product_id, actor=actor,
            selling_price=price["amount"], currency=price["currency"],
            source_reference_id=source_reference_id,
        )
        price_created = True
    return added, skipped, price_created


def _product_handoff_prompt(brand: dict, product: dict) -> str:
    brand_facts = repo.list_brand_facts(web.conn, brand["id"], status="confirmed")
    product_facts = repo.list_product_facts(web.conn, brand["id"], product["id"])
    return product_ai.build_product_handoff_prompt(brand["name"], product["name"], brand_facts, product_facts)
