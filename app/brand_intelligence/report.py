# -*- coding: utf-8 -*-
"""app/brand_intelligence/report.py — 顧問分析報告的純資料函式（決策 0017、GitHub issue #4）。

組提示詞與驗證模型回覆的資料形狀；AI 呼叫留在 app.brand_web.routes。
"""

from typing import Optional

# 五章固定順序、固定 key（只存在程式與 JSON 裡，畫面一律顯示中文章名，見 main.py REPORT_SECTIONS）
SECTION_KEYS = ("positioning", "market", "audience", "claims", "rhythm")

THIN_DATA_ITEMS = 5  # 已確認資料條數低於這個門檻，視為「資料尚少」

PARSE_FAIL_MESSAGE = "AI 有回覆，但格式讀不成預期的樣子。可以再試一次。"

_SYSTEM = "你是資深品牌顧問，正在替客戶寫一份給老闆看的品牌分析報告。只回傳 JSON，不要任何 JSON 以外的文字。"

_SECTION_BRIEF = {
    "positioning": "「品牌定位」：這個品牌在賣什麼、對誰賣、憑什麼跟別人不一樣。只寫得出已確認事實支持的判斷；語調、價格帶、品類歸屬寫在這章，不寫市況。",
    "market": "「市場與競爭觀察」：對品類走向、常見競爭對手打法、平台／通路環境的判讀。",
    "audience": "「受眾洞察」：主要客群輪廓、購買動機、常見顧慮與反對意見、他們會在哪裡看到品牌。資料不足時寫成「推測」並標明依據來自哪一條事實。",
    "claims": "「可用宣稱與紅線」：可以講的話（對應 approved 宣稱）、要小心的話（high_risk，附條件）、絕對不能講的話（forbidden 與 hard 限制規則）。",
    "rhythm": "「建議節奏方向」：只給穩定的方向性建議——內容主軸該圍繞什麼、哪類內容適合長期經營、哪些溝通重點應該反覆講、大致的輕重比例。",
}


def _normalize_sections(data) -> Optional[dict]:
    """驗證模型回覆的 JSON 形狀，回傳正規化後的五章 dict；任何一項不符回 None。"""
    if not isinstance(data, dict):
        return None
    normalized = {}
    for key in SECTION_KEYS:
        section = data.get(key)
        if not isinstance(section, dict):
            return None
        summary = section.get("summary")
        if not isinstance(summary, str) or not summary.strip():
            return None
        points_raw = section.get("points")
        points = [p.strip() for p in points_raw if isinstance(p, str) and p.strip()] \
            if isinstance(points_raw, list) else []
        normalized[key] = {"summary": summary.strip(), "points": points[:8]}
    return normalized


def _build_user_text(brand: dict, products: list, context_text: str,
                      source_fact_count: int, today: str) -> str:
    product_line = "產品清單：" + "、".join(products) if products else "目前尚未登錄產品"
    parts = [
        f"品牌名稱：{brand['name']}",
        f"所屬客戶：{brand['client_name'] or '未填寫'}",
        f"報告生成日期：{today}",
        product_line,
    ]
    parts.append(context_text if context_text else "（目前沒有任何已確認的品牌資料。）")

    section_lines = "\n".join(f"- {key}：{brief}" for key, brief in _SECTION_BRIEF.items())
    parts.append(
        "請完成以下五章：\n" + section_lines + "\n\n"
        "三條硬規則：\n"
        f"1. 「{_SECTION_BRIEF['market'].split('：')[0]}」是你在報告生成當日（{today}）的判讀，"
        "請寫成當下觀察，不要寫成永久成立的事實；不得編造市佔率、營收、檢驗數據或不確定的競品名稱。\n"
        f"2. 「{_SECTION_BRIEF['claims'].split('：')[0]}」只能依上面已登錄的宣稱與規則整理，"
        "不得放寬、不得新增可用宣稱。\n"
        f"3. 「{_SECTION_BRIEF['rhythm'].split('：')[0]}」只給方向，禁止出現任何具體排程"
        "（日期、週次、每週幾則、預算金額、檔期）。"
    )

    if source_fact_count < THIN_DATA_ITEMS:
        parts.append(
            f"這個品牌目前只有 {source_fact_count} 條已確認資料，請照樣完成五章，"
            "但把推測寫成推測、標明依據，不要編造具體數字、競品名或檢驗結果。"
        )

    parts.append(
        "輸出格式：只回傳以下 JSON，五個章節都要有，summary 用繁體中文完整句子：\n"
        '{\n'
        '  "positioning": {"summary": "2到4句敘事", "points": ["重點一", "重點二"]},\n'
        '  "market":      {"summary": "...", "points": ["..."]},\n'
        '  "audience":    {"summary": "...", "points": ["..."]},\n'
        '  "claims":      {"summary": "...", "points": ["..."]},\n'
        '  "rhythm":      {"summary": "...", "points": ["..."]}\n'
        '}'
    )
    return "\n\n".join(parts)
