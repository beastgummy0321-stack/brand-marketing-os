# -*- coding: utf-8 -*-
"""app/intake/ai.py — 建檔精靈的三種真實 LLM 呼叫（初掃／下一題／貼回格式修復）。

全部經 app/llm/gateway.run_task 進出（寫 llm_task、算成本、失敗重試一次），呼叫後
把 llm_task_id 記進草稿的 llm_task_refs_json——花費累計即時 SUM llm_task.cost，
不存副本（03 §3A.5 第 5 點）。

無金鑰時 AnthropicProvider 在打出網路請求前就拋人話錯誤（07 §3），gateway 把它記成
失敗列；本檔一律回傳 (ok, 人話錯誤訊息)，路由層據此顯示錯誤與「前往設定頁」引導，
不當機、不假裝成功（principles 16 誠實狀態）。

測試／煙霧測試把模組層 PROVIDER 換成 FakeProvider、fetch_url 換成假抓取，
不發任何真實網路請求。
"""

import html.parser
import json
import urllib.request

from app.intake import repository as ir
from app.intake import script, state
from app.llm import gateway, providers

# 測試可整個換掉（跟 app/tests 既有 FakeProvider 風格一致）
PROVIDER = providers.AnthropicProvider()

URL_FETCH_TIMEOUT_S = 10
URL_EXCERPT_CHARS = 3000

PARSE_FAIL_MESSAGE = "AI 有回覆，但格式讀不成預期的樣子。可以再試一次。"


class _TextExtractor(html.parser.HTMLParser):
    def __init__(self):
        super().__init__()
        self.chunks = []
        self._skip = 0

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style"):
            self._skip += 1

    def handle_endtag(self, tag):
        if tag in ("script", "style") and self._skip:
            self._skip -= 1

    def handle_data(self, data):
        if not self._skip and data.strip():
            self.chunks.append(data.strip())


def fetch_url(url: str) -> tuple:
    """讀一個網址，回 (ok, 純文字節錄)。讀不到只回 (False, "")——不存狀態碼、
    不存例外訊息（§19.2(b) 優雅缺席）。"""
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (BrandOS intake)"})
        with urllib.request.urlopen(req, timeout=URL_FETCH_TIMEOUT_S) as resp:
            raw = resp.read(500_000).decode("utf-8", errors="replace")
    except Exception:
        return False, ""
    extractor = _TextExtractor()
    try:
        extractor.feed(raw)
        text = " ".join(extractor.chunks)
    except Exception:
        text = raw
    return True, text[:URL_EXCERPT_CHARS]


_parse_json_reply = gateway.parse_json_reply  # 搬到 gateway.py 公開，這裡留別名（行為零變化）


def _run(conn, draft: dict, *, task_type: str, purpose: str, system: str, user_text: str) -> dict:
    brand_id = draft["brand_id"]
    row = conn.execute("SELECT knowledge_version FROM brand WHERE id = ?", (brand_id,)).fetchone()
    context = gateway.TaskContext(
        context_scope={"brand_id": brand_id, "intake_draft_id": draft["id"]},
        knowledge_item_ids=[],  # 建檔階段：品牌還沒有已確認的知識可組
        brand_version=row["knowledge_version"] if row else 1,
    )
    task = gateway.run_task(
        conn, PROVIDER, brand_id=brand_id, task_type=task_type,
        prompt_template_id=task_type, prompt_template_version="v1",
        system=system, messages=[{"role": "user", "content": user_text}], context=context,
    )
    ir.add_llm_task_ref(conn, brand_id, draft["id"], task["id"], purpose)
    return task


# ---------------------------------------------------------------------------
# (1) 初掃
# ---------------------------------------------------------------------------

_SCAN_SYSTEM = (
    "你是資深品牌顧問，正在替接案前的品牌做第一輪快速掃描。"
    "只回傳 JSON，不要任何 JSON 以外的文字。"
)


def run_scan(conn, draft: dict) -> tuple:
    """讀網址＋整理初步印象。成功回 (True, None) 並更新草稿；失敗回 (False, 人話錯誤)。"""
    url_results = []
    excerpts = []
    for u in draft["urls"]:
        ok, text = fetch_url(u)
        url_results.append({"url": u, "ok": ok})
        if ok and text:
            excerpts.append(f"【{u}】\n{text}")

    parts = [f"品牌名稱：{draft['brand_name']}", f"業主描述：{draft['description']}"]
    if excerpts:
        parts.append("以下是各網址抓到的文字內容節錄：\n\n" + "\n\n".join(excerpts))
    else:
        parts.append("（沒有可讀取的網址內容，請完全依業主描述推測，並在 basis 註明是推測。）")
    parts.append(
        "請整理 3 到 5 條「初步印象」。每一條指出它看起來像品牌的哪一面向"
        "（例如：產品線、價格帶、受眾、語調、法規風險），下一句話標題、一段完整說明、"
        "以及依據（來自哪個網址或「依業主描述推測」）。這些只是印象，不是事實。\n"
        "另外把你在資料裡實際看到的「產品名稱」列成清單（只要名字、最多 20 個；"
        "看不到任何具體產品名就給空陣列，不要猜）。\n"
        '只回傳 JSON：{"impressions": [{"looks_like": "面向", "title": "短標題", '
        '"content": "完整說明", "basis": "依據"}], "products": ["產品名稱"]}'
    )

    task = _run(conn, draft, task_type="intake_scan", purpose="讀取網址與整理初步印象",
                system=_SCAN_SYSTEM, user_text="\n\n".join(parts))
    if task["status"] != "succeeded":
        return False, task["error"]
    data = _parse_json_reply(task["rendered_output"])
    impressions = (data or {}).get("impressions") if isinstance(data, dict) else None
    if not isinstance(impressions, list) or not all(
        isinstance(i, dict) and i.get("title") for i in impressions
    ):
        return False, PARSE_FAIL_MESSAGE
    draft["scan_done"] = True
    draft["scan_impressions"] = [
        {"looks_like": i.get("looks_like") or "整體", "title": i.get("title"),
         "content": i.get("content") or "", "basis": i.get("basis") or ""}
        for i in impressions
    ]
    draft["url_results"] = url_results
    state.save(draft, conn)
    products = [str(p).strip() for p in ((data or {}).get("products") or [])
                if isinstance(p, str) and str(p).strip()][:20]
    ir.update_draft(conn, draft["brand_id"], draft["id"], scan_llm_task_id=task["id"],
                    scan_products_json=json.dumps(products, ensure_ascii=False))
    return True, None


# ---------------------------------------------------------------------------
# (2) 引導問答：出下一題
# ---------------------------------------------------------------------------

_QUESTION_SYSTEM = (
    "你是資深品牌顧問，正在用少量的選擇題把品牌調研的方向抓準。"
    "只回傳 JSON，不要任何 JSON 以外的文字。"
)


def run_next_question(conn, draft: dict) -> tuple:
    """請 AI 出下一題（含建議選項與分支）。AI 認為問夠了就標記問答結束。"""
    asked = state.question_count(draft)
    lines = [f"品牌名稱：{draft['brand_name']}", f"業主描述：{draft['description']}"]
    for imp in draft["scan_impressions"]:
        lines.append(f"初步印象（{imp['looks_like']}）{imp['title']}：{imp['content']}")
    for a in draft["answers"]:
        note = f"（補充：{a['note']}）" if a["note"] else ""
        lines.append(f"已問過：{a['question']}／業主選：{a['choice_label']}{note}")
    lines.append(
        f"你已經問了 {asked} 題（上限 {script.MAX_QUESTIONS} 題）。"
        "收斂規則（硬性）：問到第 5 題起，除非還有一個「不問就會讓調研方向走錯」的明顯缺口，"
        '一律回 {"done": true} 收尾——寧可少問，不要為了問而問。\n'
        "還需要問時，每一題要有：問題本身、一個你最建議的答案"
        "（含一句白話說明為什麼建議、選了調研會往哪去）、2 到 3 個分支選項（各含說明）。"
        "問題要根據前面的回答遞進，不要重複問過的面向。\n"
        '還需要問：只回傳 {"done": false, "question": "問題", '
        '"suggested": {"label": "建議答案", "desc": "說明"}, '
        '"branches": [{"label": "分支", "desc": "說明"}]}\n'
        '不用再問了：只回傳 {"done": true}'
    )
    task = _run(conn, draft, task_type="intake_question", purpose=f"第 {asked + 1} 題",
                system=_QUESTION_SYSTEM, user_text="\n".join(lines))
    if task["status"] != "succeeded":
        return False, task["error"]
    data = _parse_json_reply(task["rendered_output"])
    if not isinstance(data, dict):
        return False, PARSE_FAIL_MESSAGE
    if data.get("done"):
        state.mark_qa_done(draft)
        state.save(draft, conn)
        return True, None
    if not data.get("question") or not isinstance(data.get("suggested"), dict):
        return False, PARSE_FAIL_MESSAGE
    state.append_question(
        draft, data["question"], data["suggested"],
        [b for b in (data.get("branches") or []) if isinstance(b, dict) and b.get("label")],
        task["id"],
    )
    state.save(draft, conn)
    return True, None


# ---------------------------------------------------------------------------
# (3) 貼回：請 AI 幫我整理格式（只允許一次，§19.2(e) 規則 3）
# ---------------------------------------------------------------------------

_FIX_SYSTEM = (
    "你是格式整理助手。把使用者貼上的調研輸出整理成指定格式的表格，"
    "內容一字不改寫、不新增、不刪減，只調整格式。只輸出表格本身，不要任何其他文字。"
)


def run_paste_fix(conn, draft: dict) -> tuple:
    """把貼回原文原封不動交給 AI 照契約格式重排一次。成功回 (True, 修復後文字)。"""
    from app.brand_intelligence import repository as bi_repo
    known = sorted(p["name"] for p in bi_repo.list_products(conn, draft["brand_id"]))
    user_text = (
        f"{script.output_contract_block(known)}\n\n"
        "以下是需要整理的原始內容（原封不動附上）：\n\n"
        f"{draft['paste_raw']}"
    )
    task = _run(conn, draft, task_type="intake_paste_fix", purpose="請 AI 幫我整理格式",
                system=_FIX_SYSTEM, user_text=user_text)
    if task["status"] != "succeeded":
        return False, task["error"]
    # 額度只在成功時用掉：repair_llm_task_id 非空＝用過（03 §3A.2）
    ir.update_draft(conn, draft["brand_id"], draft["id"], repair_llm_task_id=task["id"])
    draft["paste_fix_used"] = True
    return True, task["rendered_output"]


# ---------------------------------------------------------------------------
# (4) 產品快掃（GitHub issue #6）：新增產品時填了網址，讀該頁＋已確認品牌事實，
# 請 AI 整理成待確認的產品事實。不掛在建檔精靈草稿底下（新增產品不一定有進行中草稿），
# 直接呼叫 gateway.run_task，呼叫方式跟 _run() 同一套、只是不寫 llm_task_refs_json。
# ---------------------------------------------------------------------------

COST_PRODUCT_SCAN = 0.30  # 校準依據同 COST_SCAN（單次頁面讀取＋一次整理，同量級呼叫）

# 事實分類固定五類（跟建檔精靈初掃「看起來像哪一面向」同一套詞彙，DoR 架構限制）
PRODUCT_SCAN_FACT_TYPES = ("產品線", "價格帶", "受眾", "語調", "法規風險")

_PRODUCT_SCAN_SYSTEM = (
    "你是資深品牌顧問，正在替一個新產品做快速調研，只整理看得出根據的產品事實。"
    "只回傳 JSON，不要任何 JSON 以外的文字。"
)


def run_product_scan(conn, brand_id: str, product_name: str, url: str, brand_facts: list) -> tuple:
    """讀產品頁網址內容＋已確認的品牌事實，請 AI 整理產品事實，並選填抽出售價。

    成功回 (True, result)，result 形狀 {"facts": [{"fact_type","label","value"}]（fact_type 限五類），
    "price": {"amount","currency"} 或 None（沒抓到就是 None，不報錯）}；
    失敗回 (False, 人話錯誤)。"""
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

    row = conn.execute("SELECT knowledge_version FROM brand WHERE id = ?", (brand_id,)).fetchone()
    context = gateway.TaskContext(
        context_scope={"brand_id": brand_id, "product_scan_url": url},
        knowledge_item_ids=[],
        brand_version=row["knowledge_version"] if row else 1,
    )
    task = gateway.run_task(
        conn, PROVIDER, brand_id=brand_id, task_type="product_scan",
        prompt_template_id="product_scan", prompt_template_version="v1",
        system=_PRODUCT_SCAN_SYSTEM, messages=[{"role": "user", "content": "\n\n".join(parts)}],
        context=context,
    )
    if task["status"] != "succeeded":
        return False, task["error"]
    result = _validate_scan_reply(_parse_json_reply(task["rendered_output"]))
    if result is None:
        return False, PARSE_FAIL_MESSAGE
    return True, result


def _validate_scan_reply(data):
    """已解析的 JSON -> {"facts": [...], "price": {...}|None}；形狀不對回 None。

    共用於 run_product_scan 與產品調研交接包貼回解析（issue #7 深研交接包）——
    兩邊要求外部 AI 回覆同一份契約，驗證規則只寫一次。"""
    facts = (data or {}).get("facts") if isinstance(data, dict) else None
    if not isinstance(facts, list) or not all(
        isinstance(f, dict) and f.get("fact_type") in PRODUCT_SCAN_FACT_TYPES
        and str(f.get("label") or "").strip() and str(f.get("value") or "").strip()
        for f in facts
    ):
        return None
    clean_facts = [
        {"fact_type": f["fact_type"], "label": str(f["label"]).strip(), "value": str(f["value"]).strip()}
        for f in facts
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
# (5) 產品調研交接包（GitHub issue #7）：比快掃更深的調研——組一份交接包文字給使用者，
# 貼去外部 AI 網頁版跑深研，再把結果貼回來解析入庫。回覆契約跟 run_product_scan 完全
# 同形狀（facts 五類＋選填 price），因此解析與驗證直接共用 _validate_scan_reply。
# ---------------------------------------------------------------------------

COST_PRODUCT_HANDOFF_FIX = script.COST_PASTE_FIX  # 貼回格式修復，跟建檔精靈貼回修復同量級呼叫

HANDOFF_FORMAT_BLOCK = f"""【回覆格式——請只回傳這個 JSON，不要有其他文字】
{{
  "facts": [
    {{"fact_type": "{'／'.join(PRODUCT_SCAN_FACT_TYPES)} 其中一種", "label": "短標題", "value": "完整說明"}}
  ],
  "price": {{"amount": 數字, "currency": "幣別代碼，例如 TWD 或 USD"}}
}}
規則：
- facts 的 fact_type 只能是{ '、'.join(f'「{t}」' for t in PRODUCT_SCAN_FACT_TYPES) }這五種之一，看不出根據的類別就不要列。
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
        lines.append(f"- （{tag}・{f['fact_type']}）{f['label']}：{f['value']}")
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
        "產品線與規格、價格帶、目標受眾、語調風格、可能的法規風險這五個面向。"
        "查得到就附來源；查不到就照實說查不到，不要用猜的當成肯定的事實。\n\n"
        f"{HANDOFF_FORMAT_BLOCK}"
    )


def parse_product_handoff_reply(text: str):
    """貼回文字先嘗試直接解析（不花錢）。成功回 {"facts":..., "price":...}；形狀不對回 None。"""
    return _validate_scan_reply(_parse_json_reply(text))


_HANDOFF_FIX_SYSTEM = (
    "你是格式整理助手。把使用者貼上的調研輸出整理成指定的 JSON 格式，"
    "內容一字不改寫、不新增、不刪減，只調整格式。只輸出 JSON 本身，不要任何其他文字。"
)


def run_product_handoff_fix(conn, brand_id: str, raw_text: str) -> tuple:
    """直接解析失敗時，請 AI 把貼回文字照契約重排一次（只呼叫一次，跟建檔精靈貼回修復同規則）。

    成功回 (True, result)，result 形狀同 run_product_scan；失敗回 (False, 人話錯誤)。"""
    user_text = (
        f"{HANDOFF_FORMAT_BLOCK}\n\n"
        "以下是需要整理的原始內容（原封不動附上）：\n\n"
        f"{raw_text}"
    )
    row = conn.execute("SELECT knowledge_version FROM brand WHERE id = ?", (brand_id,)).fetchone()
    context = gateway.TaskContext(
        context_scope={"brand_id": brand_id, "task": "product_handoff_fix"},
        knowledge_item_ids=[], brand_version=row["knowledge_version"] if row else 1,
    )
    task = gateway.run_task(
        conn, PROVIDER, brand_id=brand_id, task_type="product_handoff_fix",
        prompt_template_id="product_handoff_fix", prompt_template_version="v1",
        system=_HANDOFF_FIX_SYSTEM, messages=[{"role": "user", "content": user_text}], context=context,
    )
    if task["status"] != "succeeded":
        return False, task["error"]
    result = _validate_scan_reply(_parse_json_reply(task["rendered_output"]))
    if result is None:
        return False, PARSE_FAIL_MESSAGE
    return True, result
