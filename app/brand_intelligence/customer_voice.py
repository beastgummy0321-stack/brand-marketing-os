# -*- coding: utf-8 -*-
"""app/brand_intelligence/customer_voice.py — 顧客原話抽取的純資料函式。

見 GitHub issue #14、決策 0023 第 18a 條、決策 0024 第 2 條、app/methodology/customer-voice.md。

使用者貼入一段顧客原話全文（評論／留言／客服對話）＋出處，AI 依 customer-voice.md 的規則
（JTBD 三層任務、痛點判準、頻率×強度、原文用詞優先）抽出可用於文案的痛點與用語，逐條標記
任務層與訊號強度、保留原文用詞。抽取結果可以是空陣列——原話裡沒有值得引用的重點也是誠實
結果（principles 第 16 條「誠實狀態」），不因此擋住存檔（決策 0013 用戶優先：原文本身仍有
保存價值）。

組提示詞與驗證模型回覆的資料形狀；AI 呼叫留在 app.brand_web.routes_library。
"""

from typing import Optional

TASK_LAYERS = ("functional", "emotional", "social")
SIGNALS = ("unprompted", "prompted")

PARSE_FAIL_MESSAGE = "AI 有回覆，但格式讀不成預期的樣子。可以再試一次。"

# 票 B2-library：背景化之後補上超預算檢查（原本沒有，跟 product_ai 產品掃描不對等，
# 見 GRILL-B2-library.md「拿不準的點」）。單次抽取呼叫，跟 product_ai.COST_PRODUCT_SCAN
# 同量級（單次頁面/文字讀取＋一次整理）。
COST_CUSTOMER_VOICE_EXTRACTION = 0.30

_SYSTEM = (
    "你是資深顧客研究員，正在從一段顧客原話（評論／留言／客服對話）裡抽取對廣告文案有用的"
    "痛點與用語。只回傳 JSON，不要任何 JSON 以外的文字。"
)

_RULES = (
    "抽取規則（來自 app/methodology/customer-voice.md）：\n"
    "1. JTBD 三類任務要分開記：functional（字面上要完成的事）、emotional（想要的感覺）、"
    "social（想在別人眼中呈現的形象），一段原話可能同時抽出多層。\n"
    "2. 痛點判準：優先收「未被提示且帶情緒」的內容（顧客自己主動講、用情緒字眼），"
    "signal 標 unprompted；被動附和、被問卷選項引導出來的訊號較弱，signal 標 prompted。\n"
    "3. quote 必須是原文照抄的顧客用詞（不要改寫成「聽起來比較專業」的版本），"
    "insight 是這句話對文案有用的一句話重點。\n"
    "4. 反例（不值得收）：像「好用+1」「推推」「效果不錯」這種沒有具體情境、沒有顧客自己"
    "用詞的附和句，不要抽取。如果整段原話都沒有值得收的內容，回傳空陣列，不要硬湊。\n"
    "5. 不要編造原話裡沒有的內容；quote 一定要能在原文裡找到。"
)


def _normalize_extraction(data) -> Optional[list]:
    """驗證模型回覆的 JSON 形狀，回傳正規化後的抽取清單；形狀不符回 None。

    空陣列是合法結果（原話沒有值得收的重點），只有「根本不是預期形狀」才視為失敗。
    """
    if isinstance(data, dict):
        data = data.get("items")
    if not isinstance(data, list):
        return None
    normalized = []
    for item in data:
        if not isinstance(item, dict):
            return None
        task_layer = item.get("task_layer")
        quote = item.get("quote")
        insight = item.get("insight")
        if task_layer not in TASK_LAYERS:
            return None
        if not isinstance(quote, str) or not quote.strip():
            return None
        if not isinstance(insight, str) or not insight.strip():
            return None
        signal = item.get("signal") if item.get("signal") in SIGNALS else "unprompted"
        normalized.append({
            "task_layer": task_layer, "quote": quote.strip(),
            "insight": insight.strip(), "signal": signal,
        })
    return normalized


def _build_user_text(raw_text: str, source_channel: str, source_detail: Optional[str]) -> str:
    source_line = f"出處：{source_channel}" + (f"（{source_detail}）" if source_detail else "")
    return (
        f"{_RULES}\n\n{source_line}\n\n顧客原話全文：\n{raw_text}\n\n"
        "輸出格式：只回傳以下 JSON（items 可以是空陣列）：\n"
        '{"items": [\n'
        '  {"task_layer": "functional 或 emotional 或 social", '
        '"quote": "原文照抄的顧客用詞", "insight": "這句話對文案有用的重點", '
        '"signal": "unprompted 或 prompted"}\n'
        ']}'
    )
