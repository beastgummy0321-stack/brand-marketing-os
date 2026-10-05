"""app/brand_intelligence/product_ai.py — 產品快掃與產品調研交接包的純資料函式。

原本住在 `app/intake/ai.py`：建檔精靈當初順手實作了產品快掃，但產品是
brand_intelligence 的概念（`repository.create_product` / `list_products` 都在這裡），
建檔精靈自己一行都沒用到這些函式，唯一的呼叫端是 `brand_intelligence/routes.py`。
放在 intake 只是歷史意外，也讓 brand_intelligence 得回頭 import intake。搬回本家。

行為與搬家前完全相同，只有兩處寫法變了：
- `fetch_url` 改從 `app/core/net.py` 取（原本是 intake/ai.py 的區域函式）。
- `COST_PRODUCT_HANDOFF_FIX` 直接寫 0.50，不再 `= intake.script.COST_PASTE_FIX`
  ——引用它就會把剛切掉的依賴接回來。數值相同；兩邊本來就只是「同量級」不是同一筆。

AI 呼叫與網頁抓取留在 app.brand_web.routes_products。
"""

from app.core import vocab

PARSE_FAIL_MESSAGE = "AI 有回覆，但格式讀不成預期的樣子。可以再試一次。"


# ---------------------------------------------------------------------------
# (1) 產品快掃
# ---------------------------------------------------------------------------

COST_PRODUCT_SCAN = 0.30  # 校準依據同 COST_SCAN（單次頁面讀取＋一次整理，同量級呼叫）

# F50 Contract I (lead ruling 2026-10-05, one vocabulary): the scan writes `product_fact` rows,
# so its types are `vocab.PRODUCT_FACT_TYPES` keys -- core_info (product line and specs, price
# band) and audience. Tone and regulatory risk are brand facts (`tone`／`regulatory`), not asked
# here. `_SCAN_TYPE_HINTS` = what each type covers, in the prompts' words.
PRODUCT_SCAN_FACT_TYPES = ("core_info", "audience")
_SCAN_TYPE_HINTS = {"core_info": "產品線與規格、價格帶", "audience": "目標受眾"}
# A reply written to the old five-type contract (a handoff package copied before this change):
# its product types map onto the vocab; its brand-level types are left out, not stored.
_LEGACY_SCAN_TYPES = {"產品線": "core_info", "價格帶": "core_info", "受眾": "audience"}
_BRAND_LEVEL_SCAN_TYPES = frozenset({"語調", "法規風險"})


def scan_types_text() -> str:
    """「core_info（產品線與規格、價格帶）、audience（目標受眾）」 -- the type list both prompts quote."""
    return "、".join(f"{key}（{_SCAN_TYPE_HINTS[key]}）" for key in PRODUCT_SCAN_FACT_TYPES)


_PRODUCT_SCAN_SYSTEM = (
    "你是資深品牌顧問，正在替一個新產品做快速調研，只整理看得出根據的產品事實。"
    "只回傳 JSON，不要任何 JSON 以外的文字。"
)


def _validate_scan_reply(data):
    """已解析的 JSON -> {"facts": [...], "price": {...}|None}；形狀不對回 None。

    共用於 run_product_scan 與產品調研交接包貼回解析（issue #7 深研交接包）——
    兩邊要求外部 AI 回覆同一份契約，驗證規則只寫一次。"""
    facts = (data or {}).get("facts") if isinstance(data, dict) else None
    if not isinstance(facts, list) or not all(
        isinstance(f, dict)
        and (f.get("fact_type") in PRODUCT_SCAN_FACT_TYPES
             or f.get("fact_type") in _LEGACY_SCAN_TYPES
             or f.get("fact_type") in _BRAND_LEVEL_SCAN_TYPES)
        and str(f.get("label") or "").strip() and str(f.get("value") or "").strip()
        for f in facts
    ):
        return None
    clean_facts = [
        {"fact_type": _LEGACY_SCAN_TYPES.get(f["fact_type"], f["fact_type"]),
         "label": str(f["label"]).strip(), "value": str(f["value"]).strip()}
        for f in facts
        if f["fact_type"] not in _BRAND_LEVEL_SCAN_TYPES
    ]
    # price 選填：格式不對或看不出金額就當沒抓到，不讓整次快掃失敗（架構限制：選填不報錯）。
    price = None
    raw_price = data.get("price") if isinstance(data, dict) else None
    if isinstance(raw_price, dict):
        amount = raw_price.get("amount")
        if isinstance(amount, (int, float)) and not isinstance(amount, bool) and amount > 0:
            currency = str(raw_price.get("currency") or "TWD").strip().upper() or "TWD"
            price = {"amount": float(amount), "currency": currency}
    return {"facts": clean_facts, "price": price}


# ---------------------------------------------------------------------------
# (2) 產品調研交接包（GitHub issue #7）：比快掃更深的調研——組一份交接包文字給使用者，
# 貼去外部 AI 網頁版跑深研，再把結果貼回來解析入庫。回覆契約跟 run_product_scan 完全
# 同形狀（facts 的類別＋選填 price），因此解析與驗證直接共用 _validate_scan_reply。
# ---------------------------------------------------------------------------

COST_PRODUCT_HANDOFF_FIX = 0.50  # 貼回格式修復，跟建檔精靈貼回修復（intake.script.COST_PASTE_FIX）同量級呼叫

HANDOFF_FORMAT_BLOCK = f"""【回覆格式——請只回傳這個 JSON，不要有其他文字】
{{
  "facts": [
    {{"fact_type": "{'／'.join(PRODUCT_SCAN_FACT_TYPES)} 其中一種", "label": "短標題", "value": "完整說明"}}
  ],
  "price": {{"amount": 數字, "currency": "幣別代碼，例如 TWD 或 USD"}}
}}
規則：
- facts 的 fact_type 只能是{scan_types_text()}這 {len(PRODUCT_SCAN_FACT_TYPES)} 種之一（填英文代號），看不出根據的類別就不要列。
- 每一條 facts 都要有 label（短標題）與 value（完整說明），不能是空字串。
- price 是選填：查得到清楚的售價才回傳；查不到、不確定，就整個不要有 price 這個欄位，不要用 0 或亂猜。
- 除了這個 JSON 以外，不要輸出任何其他文字——不要有開頭的說明，也不要有結尾的補充。"""


def _known_brand_facts_text(brand_facts: list) -> str:
    if not brand_facts:
        return "（目前這個品牌還沒有已確認的品牌事實。）"
    return "\n".join(f"- {f['label']}：{f['value']}" for f in brand_facts)


def _known_product_facts_text(product_facts: list) -> str:
    if not product_facts:
        return "（目前這個產品還沒有任何已知事實。）"
    lines = []
    for f in product_facts:
        tag = "已確認" if f["status"] == "confirmed" else "待確認"
        lines.append(f"- （{tag}・{vocab.product_fact_type_label(f['fact_type'])}）{f['label']}：{f['value']}")
    return "\n".join(lines)


def build_product_handoff_prompt(brand_name: str, product_name: str,
                                  brand_facts: list, product_facts: list) -> str:
    """組出「調研交接包」要複製的那一段文字：品牌背景＋產品已知事實＋任務說明＋回覆格式。

    brand_facts：已確認的品牌事實列（repo.list_brand_facts status='confirmed'）。
    product_facts：這個產品目前所有事實列，含待確認（repo.list_product_facts 不篩 status）。"""
    return (
        "你是一位資深品牌顧問，替品牌方的其中一項產品做深入調研。這份調研的唯一目的，"
        "是為後續的廣告與品牌內容生成打下可用的產品事實庫——所有內容都要能直接變成"
        "之後可用的事實或依據；跟這個目的無關的分析不要寫。\n\n"
        f"【品牌】{brand_name}\n"
        f"【已確認的品牌背景】\n{_known_brand_facts_text(brand_facts)}\n\n"
        f"【產品】{product_name}\n"
        f"【這個產品目前已知的事實】\n{_known_product_facts_text(product_facts)}\n\n"
        f"【調研任務】請針對「{product_name}」這個產品做更深入的調研，"
        "補齊或更新上面「已知事實」還沒涵蓋、或值得再查證的部分，聚焦在："
        "產品線與規格、價格帶、目標受眾這幾個面向。"
        "查得到就附來源；查不到就照實說查不到，不要用猜的當成肯定的事實。\n\n"
        f"{HANDOFF_FORMAT_BLOCK}"
    )


_HANDOFF_FIX_SYSTEM = (
    "你是格式整理助手。把使用者貼上的調研輸出整理成指定的 JSON 格式，"
    "內容一字不改寫、不新增、不刪減，只調整格式。只輸出 JSON 本身，不要任何其他文字。"
)
