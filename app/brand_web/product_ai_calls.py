# -*- coding: utf-8 -*-
"""app/brand_web/product_ai_calls.py — 產品 AI 呼叫邊界。
進入點＝本檔。
誰依賴＝routes.py、routes_products.py。
不碰＝不得 import app/brand_web 其他檔。
"""

from app.brand_intelligence import product_ai, repository as repo
from app.core import net
from app.llm import gateway, providers

PROVIDER = providers.AnthropicProvider()
fetch_url = net.fetch_url
PARSE_FAIL_MESSAGE = product_ai.PARSE_FAIL_MESSAGE
COST_PRODUCT_SCAN = product_ai.COST_PRODUCT_SCAN
COST_PRODUCT_HANDOFF_FIX = product_ai.COST_PRODUCT_HANDOFF_FIX
PRODUCT_SCAN_FACT_TYPES = product_ai.PRODUCT_SCAN_FACT_TYPES
_parse_json_reply = gateway.parse_json_reply


def run_product_scan(conn, brand_id: str, product_name: str, url: str, brand_facts: list) -> tuple:
    """讀產品頁網址內容＋已確認的品牌事實，請 AI 整理產品事實，並選填抽出售價。"""
    ok, text = fetch_url(url)
    parts = [f"產品名稱：{product_name}", f"產品頁網址：{url}"]
    if brand_facts:
        known = "\n".join(f"・{f['label']}：{f['value']}" for f in brand_facts)
        parts.append(f"這個品牌已經確認過的事實（背景參考，不要重複產出）：\n{known}")
    if ok and text:
        parts.append(f"以下是這個網址抓到的文字節錄：\n\n{text}")
    else:
        parts.append("（沒有抓到這個網址的內容，請完全依產品名稱與品牌背景推測，並在說明裡註明是推測。）")
    parts.append(
        "請整理這個產品的事實，只整理「產品線」「價格帶」「受眾」「語調」「法規風險」"
        "這五類看得出根據的內容，每類最多一條，看不出來的類別就不要列（可以是空陣列）。\n"
        "另外，如果頁面上有清楚寫出「售價」，選填回傳 price（金額與幣別代碼，例如 TWD／USD；"
        "看不出售價或不確定就整個不要回傳 price 這個欄位，不要用 0 或亂猜）。\n"
        '只回傳 JSON：{"facts": [{"fact_type": "五類其中之一", "label": "短標題", "value": "完整說明"}], '
        '"price": {"amount": 數字, "currency": "幣別代碼"}}（沒有售價就不要有 price 這個 key）'
    )
    # 跨層禁止裸 SQL（CrossLayerRawSqlScanTest），走 repository 公開進入點
    row = repo.get_brand(conn, brand_id)
    context = gateway.TaskContext(
        context_scope={"brand_id": brand_id, "product_scan_url": url}, knowledge_item_ids=[],
        brand_version=row["knowledge_version"] if row else 1,
    )
    task = gateway.run_task(
        conn, PROVIDER, brand_id=brand_id, task_type="product_scan",
        prompt_template_id="product_scan", prompt_template_version="v1",
        system=product_ai._PRODUCT_SCAN_SYSTEM,
        messages=[{"role": "user", "content": "\n\n".join(parts)}], context=context,
    )
    if task["status"] != "succeeded":
        return False, task["error"]
    result = product_ai._validate_scan_reply(_parse_json_reply(task["rendered_output"]))
    return (True, result) if result is not None else (False, PARSE_FAIL_MESSAGE)


def parse_product_handoff_reply(text: str):
    """貼回文字先嘗試直接解析（不花錢）。"""
    return product_ai._validate_scan_reply(_parse_json_reply(text))


def run_product_handoff_fix(conn, brand_id: str, raw_text: str) -> tuple:
    """直接解析失敗時，請 AI 把貼回文字照契約重排一次。"""
    user_text = (
        f"{product_ai.HANDOFF_FORMAT_BLOCK}\n\n"
        "以下是需要整理的原始內容（原封不動附上）：\n\n"
        f"{raw_text}"
    )
    # 跨層禁止裸 SQL（CrossLayerRawSqlScanTest），走 repository 公開進入點
    row = repo.get_brand(conn, brand_id)
    context = gateway.TaskContext(
        context_scope={"brand_id": brand_id, "task": "product_handoff_fix"},
        knowledge_item_ids=[], brand_version=row["knowledge_version"] if row else 1,
    )
    task = gateway.run_task(
        conn, PROVIDER, brand_id=brand_id, task_type="product_handoff_fix",
        prompt_template_id="product_handoff_fix", prompt_template_version="v1",
        system=product_ai._HANDOFF_FIX_SYSTEM,
        messages=[{"role": "user", "content": user_text}], context=context,
    )
    if task["status"] != "succeeded":
        return False, task["error"]
    result = product_ai._validate_scan_reply(_parse_json_reply(task["rendered_output"]))
    return (True, result) if result is not None else (False, PARSE_FAIL_MESSAGE)
