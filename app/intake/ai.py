"""app/intake/ai.py — 建檔精靈的真實 LLM 呼叫（初掃／下一題／貼回格式修復，以及 F42-I05 品牌建檔
的「AI 讀網站與品牌照片預填」`run_prefill`；「自訂」在 app/intake/custom.py）。

全部經 app/llm/gateway.run_task 進出（寫 llm_task、算成本、失敗重試一次），呼叫後
把 llm_task_id 記進草稿的 llm_task_refs_json——花費累計即時 SUM llm_task.cost，
不存副本（03 §3A.5 第 5 點）。

無金鑰時 AnthropicProvider 在打出網路請求前就拋人話錯誤（07 §3），gateway 把它記成
失敗列；本檔一律回傳 (ok, 人話錯誤訊息)，路由層據此顯示錯誤與「前往設定頁」引導，
不當機、不假裝成功（principles 16 誠實狀態）。

測試／煙霧測試把模組層 PROVIDER 換成 FakeProvider、fetch_url 換成假抓取，
不發任何真實網路請求。
"""

import json
import logging

from app import storage
from app.brand_intelligence import repository as bi_repo
from app.core import net, vocab
from app.intake import onboarding, script, state
from app.intake import repository as ir
from app.llm import gateway, providers

_log = logging.getLogger(__name__)

# 測試可整個換掉（跟 app/tests 既有 FakeProvider 風格一致）
PROVIDER = providers.AnthropicProvider()

# 綁成本模組的名字，測試才能只換這裡（實作已移到 app/core/net.py，產品調研也要用）
fetch_url = net.fetch_url

PARSE_FAIL_MESSAGE = "AI 有回覆，但格式讀不成預期的樣子。可以再試一次。"
QUESTION_ASPECTS = ("產品線", "價格帶", "客群", "語調", "法規風險")

# 成本上限（F04-I06）：使用者能無限拖照片／問答輪數往上疊，模型呼叫不能照樣無限跟漲。
MAX_PHOTO_SCANS = 12  # 第 13 張起不打模型，卡片標成 skipped
MAX_IMPRESSION_LINES = 8  # 出題只帶最近 8 條初步印象
MAX_ANSWER_LINES = 3  # 出題只帶最近 3 題問答；更早的已收斂進「已覆蓋面向」


_parse_json_reply = gateway.parse_json_reply  # 搬到 gateway.py 公開，這裡留別名（行為零變化）


def _run(conn, draft: dict, *, task_type: str, purpose: str, system: str, user_text: str,
         options: gateway.TaskOptions = None, content_blocks: list = None) -> dict:
    brand_id = draft["brand_id"]
    row = conn.execute("SELECT knowledge_version FROM brand WHERE id = %s", (brand_id,)).fetchone()
    context = gateway.TaskContext(
        context_scope={"brand_id": brand_id, "intake_draft_id": draft["id"]},
        knowledge_item_ids=[],  # 建檔階段：品牌還沒有已確認的知識可組
        brand_version=row["knowledge_version"] if row else 1,
    )
    task = gateway.run_task(
        conn, PROVIDER, brand_id=brand_id, task_type=task_type,
        prompt_template_id=task_type, prompt_template_version="v1",
        system=system,
        messages=[{"role": "user", "content": content_blocks if content_blocks is not None else user_text}],
        context=context,
        options=options,
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

_PHOTO_PRODUCT_SYSTEM = (
    "你正在替品牌方讀產品照片。只整理照片上看得出來的內容；價格即使看得到也不要抄、"
    "不要猜，價格一定交給使用者回答。請用指定工具回傳。"
)

_PHOTO_PRODUCT_TOOL = {
    "name": "submit_photo_product",
    "description": "提交這張照片中看得到的產品資訊；價格不得提交。",
    "input_schema": {
        "type": "object",
        "properties": {
            "readable": {"type": "boolean"},
            "name": {"type": "string"},
            "specification": {"type": "string"},
            "selling_points": {"type": "array", "items": {"type": "string"}, "maxItems": 5},
            "gaps": {"type": "array", "items": {"type": "string"}, "maxItems": 8},
        },
        "required": ["readable", "name", "specification", "selling_points", "gaps"],
        "additionalProperties": False,
    },
}

def _photo_card(photo: dict, *, status: str, message: str = None, data: dict = None) -> dict:
    data = data or {}
    name = str(data.get("name") or "").strip()
    specification = str(data.get("specification") or "").strip()
    selling_points = [str(point).strip() for point in (data.get("selling_points") or [])
                      if str(point).strip()][:5]
    gaps = [str(gap).strip() for gap in (data.get("gaps") or []) if str(gap).strip()]
    if not name and "品名" not in gaps:
        gaps.append("品名")
    if not specification and "規格" not in gaps:
        gaps.append("規格")
    if not selling_points and "賣點" not in gaps:
        gaps.append("賣點")
    if "價格" not in gaps:
        gaps.append("價格")
    return {
        "status": status, "name": name, "specification": specification,
        "selling_points": selling_points, "source_photo_token": photo.get("token") or "",
        "gaps": gaps, "message": message,
    }


def _read_photo_product(conn, draft: dict, photo: dict, purpose: str) -> dict:
    try:
        storage_key = photo.get("storage_key") or ""
        if not storage_key:
            raise ValueError("找不到照片檔案，可以重試或先跳過。")
        org_id = storage_key.split("/", 1)[0]
        content, content_type = storage.get(org_id=org_id, key=storage_key)
        image = providers.base64_image_block(content_type, content)
        text = {
            "type": "text",
            "text": (
                "請讀這張產品照片。讀得到時填品名、規格、最多五個賣點與仍缺的資料；"
                "讀不到品名就把 readable 設為 false。價格一律列為缺口，不得輸出價格。"
            ),
        }
        task = _run(
            conn, draft, task_type="intake_photo_scan", purpose=purpose,
            system=_PHOTO_PRODUCT_SYSTEM, user_text="", content_blocks=[image, text],
            options=gateway.TaskOptions(max_tokens=1200, tools=[_PHOTO_PRODUCT_TOOL]),
        )
        if task["status"] != "succeeded":
            return _photo_card(photo, status="failed", message=task["error"])
        data = task["structured_output_json"]
        if not isinstance(data, dict) or not data.get("readable") or not str(data.get("name") or "").strip():
            return _photo_card(
                photo, status="unreadable", data=data if isinstance(data, dict) else None,
                message="這張照片讀不出產品資訊，可以自己填或略過。",
            )
        return _photo_card(photo, status="ready", data=data)
    except (storage.StorageError, ValueError, json.JSONDecodeError) as exc:
        return _photo_card(photo, status="failed", message=str(exc))


def _read_photo_products(conn, draft: dict) -> list:
    cards = []
    for index, photo in enumerate(draft["photos"], start=1):
        if index > MAX_PHOTO_SCANS:
            card = _photo_card(
                photo, status="skipped",
                message=(
                    f"一次最多讀 {MAX_PHOTO_SCANS} 張照片，這張沒有讀；"
                    "照片產品卡可以自己填，或先完成這批再上傳。"
                ),
            )
        else:
            card = _read_photo_product(conn, draft, photo, f"讀取第 {index} 張照片")
        cards.append(card)
        draft["product_card_drafts"] = list(cards)
        ready_names = [c["name"] for c in cards if c["status"] == "ready" and c["name"]]
        draft["scan_products"] = list(dict.fromkeys((draft.get("scan_products") or []) + ready_names))
        state.save(draft, conn)
    return cards


def retry_photo_product(conn, draft: dict, source_photo_token: str) -> dict:
    photo = next((p for p in draft["photos"] if p.get("token") == source_photo_token), None)
    cards = list(draft.get("product_card_drafts") or [])
    card_index = next((i for i, card in enumerate(cards)
                       if card.get("source_photo_token") == source_photo_token), None)
    if photo is None or card_index is None:
        raise ValueError("找不到這張照片產品卡。")
    card = _read_photo_product(conn, draft, photo, "重讀指定照片")
    cards[card_index] = card
    draft["product_card_drafts"] = cards
    if card["status"] == "ready" and card["name"]:
        draft["scan_products"] = list(dict.fromkeys(
            (draft.get("scan_products") or []) + [card["name"]],
        ))
    state.save(draft, conn)
    return card


def parse_scan_reply(rendered_output: str) -> dict | None:  # 格式不符回 None；佇列狀態端點重驗用
    data = _parse_json_reply(rendered_output)
    impressions = (data or {}).get("impressions") if isinstance(data, dict) else None
    valid = isinstance(impressions, list) and all(
        isinstance(i, dict) and i.get("title") for i in impressions)
    return {"impressions": impressions, "products": (data or {}).get("products") or []} if valid else None


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
        "（例如：產品線、價格帶、客群、語調、法規風險），下一句話標題、一段完整說明、"
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
    parsed = parse_scan_reply(task["rendered_output"])
    if parsed is None:
        return False, PARSE_FAIL_MESSAGE
    draft["scan_done"] = True
    draft["scan_impressions"] = [
        {"looks_like": i.get("looks_like") or "整體", "title": i.get("title"),
         "content": i.get("content") or "", "basis": i.get("basis") or ""}
        for i in parsed["impressions"]
    ]
    draft["url_results"] = url_results
    products = [str(p).strip() for p in parsed["products"]
                if isinstance(p, str) and str(p).strip()][:20]
    draft["scan_products"] = list(dict.fromkeys(products))
    draft["product_card_drafts"] = []
    state.save(draft, conn)
    ir.update_draft(conn, draft["brand_id"], draft["id"], scan_llm_task_id=task["id"])
    _read_photo_products(conn, draft)
    return True, None


# ---------------------------------------------------------------------------
# (2) 引導問答：出下一題
# ---------------------------------------------------------------------------

_QUESTION_SYSTEM = (
    "你是資深品牌顧問，正在用少量的選擇題把品牌調研的方向抓準。"
    "請用指定工具回傳。"
)

_CHOICE_SCHEMA = {
    "type": "object",
    "properties": {"label": {"type": "string"}, "desc": {"type": "string"}},
    "required": ["label", "desc"],
    "additionalProperties": False,
}

# 出題改走強制工具（跟同檔的 _PHOTO_PRODUCT_TOOL／_PASTE_ROWS_TOOL 一致）：以前是在散文裡
# 要求「只回傳 JSON」，模型少收一個括號就整題讀不出來。工具回來的 input 已經是解析好的
# dict，格式壞掉這個可能性直接消失。只有 done 必填，讓「問夠了」是一次合法的單欄位呼叫。
_QUESTION_TOOL = {
    "name": "submit_next_question",
    "description": "提交下一題；已經問夠了就只送 done=true。",
    "input_schema": {
        "type": "object",
        "properties": {
            "done": {"type": "boolean"},
            "aspect": {"type": "string", "enum": list(QUESTION_ASPECTS)},
            "question": {"type": "string"},
            "suggested": _CHOICE_SCHEMA,
            "branches": {"type": "array", "items": _CHOICE_SCHEMA, "minItems": 2, "maxItems": 3},
        },
        "required": ["done"],
        "additionalProperties": False,
    },
}


def question_coverage(draft: dict) -> tuple[list, list]:  # 出題與佇列狀態端點共用同一份
    covered = [aspect for aspect in QUESTION_ASPECTS if any(
        isinstance(entry, dict) and entry.get("aspect") == aspect
        for entry in draft.get("qa") or []
    )]
    missing = [aspect for aspect in QUESTION_ASPECTS if aspect not in covered]
    return covered, missing


def validate_question_reply(data, missing: list) -> tuple[bool, str | None]:  # missing 由呼叫端傳入
    if not isinstance(data, dict):
        return False, PARSE_FAIL_MESSAGE
    if data.get("done"):
        if missing:
            return False, (f"還有 {len(missing)} 個面向沒問到：{'、'.join(missing)}。"
                           "請繼續出題。")
        return True, None
    if (data.get("aspect") not in QUESTION_ASPECTS or not data.get("question")
            or not isinstance(data.get("suggested"), dict)):
        return False, PARSE_FAIL_MESSAGE
    return True, None


def run_next_question(conn, draft: dict) -> tuple:
    """請 AI 出下一題（含建議選項與分支）。AI 認為問夠了就標記問答結束。"""
    asked = state.question_count(draft)
    if asked >= script.MAX_QUESTIONS:
        state.mark_qa_done(draft)
        state.save(draft, conn)
        return True, None
    covered, missing = question_coverage(draft)
    lines = [f"品牌名稱：{draft['brand_name']}", f"業主描述：{draft['description']}"]
    impressions = draft["scan_impressions"]
    shown_impressions = impressions[-MAX_IMPRESSION_LINES:]
    if len(impressions) > MAX_IMPRESSION_LINES:
        lines.append(f"另有 {len(impressions) - MAX_IMPRESSION_LINES} 條初步印象沒有列出。")
    for imp in shown_impressions:
        lines.append(f"初步印象（{imp['looks_like']}）{imp['title']}：{imp['content']}")
    photo_gaps = []
    for card in draft.get("product_card_drafts") or []:
        if card.get("status") == "skipped":
            continue
        gaps = [str(gap).strip() for gap in card.get("gaps") or [] if str(gap).strip()]
        if gaps:
            photo_gaps.append(f"{card.get('name') or '讀不出品名的照片'}：{'、'.join(gaps)}")
    if photo_gaps:
        lines.append("照片產品卡缺口（優先補問）：" + "；".join(photo_gaps))
    answers = draft["answers"]
    if len(answers) > MAX_ANSWER_LINES:
        lines.append("更早的問答已收斂成下面的「已覆蓋面向」。")  # 摘要已存在，不必逐字重送
    for a in answers[-MAX_ANSWER_LINES:]:
        note = f"（補充：{a['note']}）" if a["note"] else ""
        lines.append(f"已問過：{a['question']}／業主選：{a['choice_label']}{note}")
    lines.append(f"已覆蓋面向：{'、'.join(covered) if covered else '無'}")
    lines.append(f"未覆蓋面向：{'、'.join(missing) if missing else '無'}")
    lines.append(
        f"你已經問了 {asked} 題（上限 {script.MAX_QUESTIONS} 題）。"
        "收斂規則（硬性）：問到第 5 題起，除非還有一個「不問就會讓調研方向走錯」的明顯缺口，"
        "一律把 done 設為 true 收尾——寧可少問，不要為了問而問。\n"
        "只要還有未覆蓋面向且尚未達題數上限，就不能回 done，必須從未覆蓋面向繼續出題。"
        "還需要問時，每一題要有：所屬面向、問題本身、一個你最建議的答案"
        "（含一句白話說明為什麼建議、選了調研會往哪去）、2 到 3 個分支選項（各含說明）。"
        "問題要根據前面的回答遞進，不要重複問過的面向。"
    )
    task = _run(conn, draft, task_type="intake_question", purpose=f"第 {asked + 1} 題",
                system=_QUESTION_SYSTEM, user_text="\n".join(lines),
                options=gateway.TaskOptions(tools=[_QUESTION_TOOL]))
    if task["status"] != "succeeded":
        return False, task["error"]
    data = task["structured_output_json"]
    ok, err = validate_question_reply(data, missing)
    if not ok:
        return False, err
    if data.get("done"):
        state.mark_qa_done(draft)
        state.save(draft, conn)
        return True, None
    state.append_question(
        draft, data["question"], data["suggested"],
        [b for b in (data.get("branches") or []) if isinstance(b, dict) and b.get("label")],
        task["id"], aspect=data["aspect"],
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

_PASTE_ROWS_TOOL = {
    "name": "submit_paste_rows",
    "description": "提交整理完成的調研總結列。只能整理原文格式，不得改寫、新增或刪減內容。",
    "input_schema": {
        "type": "object",
        "properties": {
            "rows": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "kind": {"type": "string", "enum": ["品牌事實", "產品事實", "限制規則", "宣稱", "顧客原話"]},
                        "category": {"type": "string"},
                        "title": {"type": "string"},
                        "content": {"type": "string"},
                        "scope": {"type": "string"},
                        "evidence": {"type": "string"},
                    },
                    "required": ["kind", "category", "title", "content", "scope", "evidence"],
                    "additionalProperties": False,
                },
            },
        },
        "required": ["rows"],
        "additionalProperties": False,
    },
}


def run_paste_fix(conn, draft: dict) -> tuple:
    """把貼回原文交給 AI 重排；成功回傳結構化列，缺結構時回傳修復文字。"""
    known = sorted(p["name"] for p in bi_repo.list_products(conn, draft["brand_id"]))
    user_text = (
        f"{script.output_contract_block(known)}\n\n"
        "以下是需要整理的原始內容（原封不動附上）：\n\n"
        f"{draft['paste_raw']}"
    )
    task = _run(conn, draft, task_type="intake_paste_fix", purpose="請 AI 幫我整理格式",
                system=_FIX_SYSTEM, user_text=user_text,
                options=gateway.TaskOptions(tools=[_PASTE_ROWS_TOOL]))
    if task["status"] != "succeeded":
        return False, task["error"]
    # 額度只在成功時用掉：repair_llm_task_id 非空＝用過（03 §3A.2）
    ir.update_draft(conn, draft["brand_id"], draft["id"], repair_llm_task_id=task["id"])
    draft["paste_fix_used"] = True
    structured = task["structured_output_json"] or None
    if isinstance(structured, dict) and isinstance(structured.get("rows"), list):
        return True, structured["rows"]
    return True, task["rendered_output"]


# ---------------------------------------------------------------------------
# (4) Brand onboarding prefill (F42-I05): one call reads the draft's website pages and brand
# photos and proposes what steps 3/4 (#/b3, #/b4) show with an 「AI 讀到」 tag. The reply is
# contract-checked entry by entry here; the result is a proposal in `intake_draft.prefill_json`,
# never a confirmed fact (the step's 下一步 confirms it).
# ---------------------------------------------------------------------------

PREFILL_TASK_TYPE = "intake_prefill"
PREFILL_PURPOSE = "AI 讀網站與品牌照片預填"  # llm_task_refs_json purpose: how the status finds its call
COST_PREFILL = 0.30  # estimate checked against the draft cost cap before the job is queued
PREFILL_MAX_TOKENS = 4000
MAX_PREFILL_PAGES = onboarding.MAX_URLS
MAX_PREFILL_PHOTOS = 5
MAX_POSITIONING_CHARS = 60
MAX_VISUAL_CHARS = onboarding.MAX_TEXT_CHARS
MAX_PROOF_CHARS = onboarding.MAX_TEXT_CHARS
MAX_PREFILL_PRODUCTS = 20
MAX_PRODUCT_NAME_CHARS = 40
MAX_NOTE_CHARS = 40
MAX_POLICY_PARAM_CHARS = 60

# What the scan may report as 「沒找到」 (display labels, in the prototype's step order).
AREA_POSITIONING, AREA_TONE, AREA_VISUAL = "一句話定位", "說話的口氣", "畫面風格"
AREA_POLICIES, AREA_PRODUCTS = "全店政策", "可能的商品"
PREFILL_AREAS = (AREA_POSITIONING, AREA_TONE, AREA_VISUAL,
                 *(label for _, label in vocab.PROOF_KINDS), AREA_POLICIES, AREA_PRODUCTS)
_PREFILL_KEYS = ("positioning", "tone", "visual", "proof", "policies", "products", "not_found")
_PROOF_LABELS = dict(vocab.PROOF_KINDS)


def prefill_lock(brand_id: str) -> str:
    """Queueing lock of the prefill job (task `background.intake_scan` with `prefill=True`)."""
    return f"intake_prefill:{brand_id}"


_PREFILL_SYSTEM = (
    "你是品牌建檔助手。只根據這次提供的網站頁面文字與品牌照片整理資料，"
    "不用自己的知識補、不猜、不上網查。只回傳 JSON，不要任何 JSON 以外的文字。"
)


def _policy_menu() -> str:
    rows = []
    for p in vocab.POLICY_TYPES:
        params = "、".join(f"{q['name']}（{q['label']}）" for q in p["params"])
        rows.append(f"{p['key']}＝{p['label']}" + (f"：{params}" if params else ""))
    return "；".join(rows)


def _prefill_prompt(brand_name: str, pages: list, photo_kinds: list) -> str:
    lines = [f"品牌名稱：{brand_name}"]
    for index, (url, text) in enumerate(pages, start=1):
        lines.append(f"【頁面 {index}】{url}\n{text}")
    if photo_kinds:
        lines.append("附上的品牌照片依序是：" + "、".join(
            f"第 {i} 張＝{kind}" for i, kind in enumerate(photo_kinds, start=1)))
    lines.append("可選的說話口氣：" + "、".join(vocab.TONES))
    lines.append("證據種類（fact_key＝名稱）：" + "；".join(f"{k}＝{label}" for k, label in vocab.PROOF_KINDS))
    lines.append("全店政策（key＝名稱：參數）：" + _policy_menu())
    lines.append("「沒找到」只能從這些面向挑：" + "、".join(PREFILL_AREAS))
    lines.append(
        "規則：\n"
        "1. 每一項都要在 note 寫出處：來自網站就寫「頁面 N」或那一頁的名稱，來自照片就寫「品牌照片」。"
        "不得編造出處；找不到出處的東西就不要寫。\n"
        f"2. positioning：一句話說這個品牌是給誰、解決什麼（最多 {MAX_POSITIONING_CHARS} 字）。\n"
        "3. tone：從可選的說話口氣挑 1～2 個。visual：畫面風格（色調、光線、場景）。\n"
        "4. proof：網站或照片上寫明的證據，fact_key 只能用上面的證據種類。\n"
        "5. policies：網站上寫明的全店政策，key 只能用上面的清單，params 只填網站寫明的數字或文字，"
        "沒寫就不要填那個參數；清單裡沒有的政策不要列。\n"
        f"6. products：實際看到的商品名稱（最多 {MAX_PREFILL_PRODUCTS} 個），url 是該商品頁網址，"
        "不知道就 null；不要列價格。\n"
        "7. 沒找到的面向列進 not_found；沒有就不要填，不要用推測補。\n"
        '只回傳 JSON：{"positioning": {"value": "…", "note": "出處"}, '
        '"tone": {"values": ["…"], "note": "出處"}, "visual": {"value": "…", "note": "出處"}, '
        '"proof": [{"fact_key": "…", "text": "…", "note": "出處"}], '
        '"policies": [{"key": "…", "params": {"參數": "值"}, "note": "出處"}], '
        '"products": [{"name": "…", "url": null}], "not_found": ["面向"]}'
    )
    return "\n\n".join(lines)


def _clean_text(value, limit: int) -> str | None:
    """A non-empty string within `limit` chars, else None."""
    if not isinstance(value, str):
        return None
    text = value.strip()
    return text if text and len(text) <= limit else None


def _clean_note(value, *, pages_read: int, photos_read: int) -> str | None:
    """The entry's source note ("" = none given), or None when it names a source this scan did
    not read (a photo note without photos, a page note without pages): an invented source."""
    if value is None or (isinstance(value, str) and not value.strip()):
        return ""
    note = _clean_text(value, MAX_NOTE_CHARS)
    if note is None:
        return None
    if "照片" in note:
        return note if photos_read else None
    return note if pages_read else None


def _clean_policy_params(key: str, raw) -> dict | None:
    """Only the registry's own param names with a scalar value; None = params not an object."""
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        return None
    names = {p["name"] for p in vocab.POLICY_TYPES_BY_KEY[key]["params"]}
    out = {}
    for name, value in raw.items():
        if name not in names or isinstance(value, bool) or value is None:
            continue
        if isinstance(value, (int, float)):
            out[name] = value
        elif isinstance(value, str) and value.strip() and len(value.strip()) <= MAX_POLICY_PARAM_CHARS:
            out[name] = value.strip()
    return out


def _check_value_blocks(data: dict, note_of) -> tuple[dict, int]:
    out, dropped = {}, 0
    for key, limit in (("positioning", MAX_POSITIONING_CHARS), ("visual", MAX_VISUAL_CHARS)):
        item = data.get(key)
        if item is None:
            continue
        value = _clean_text(item.get("value"), limit) if isinstance(item, dict) else None
        note = note_of(item) if isinstance(item, dict) else None
        if value is None or note is None:
            dropped += 1
            continue
        out[key] = {"value": value, "note": note}
    return out, dropped


def _check_tone(tone, note_of) -> tuple[dict | None, int]:
    if tone is None:
        return None, 0
    raw = tone.get("values") if isinstance(tone, dict) else None
    raw = raw if isinstance(raw, list) else []
    values = list(dict.fromkeys(v for v in raw if isinstance(v, str) and v in vocab.TONES))
    dropped = len(raw) - len(values)  # outside TONES, or a repeat
    if len(values) > onboarding.TONE_MAX:
        dropped += len(values) - onboarding.TONE_MAX
        values = values[:onboarding.TONE_MAX]
    note = note_of(tone) if isinstance(tone, dict) else None
    if not values or note is None:
        return None, dropped + (1 if values or not raw else 0)
    return {"values": values, "note": note}, dropped


def _check_proof(items, note_of) -> tuple[list, int]:
    proof, seen, dropped = [], set(), 0
    for item in items if isinstance(items, list) else []:
        fact_key = item.get("fact_key") if isinstance(item, dict) else None
        text = _clean_text(item.get("text"), MAX_PROOF_CHARS) if isinstance(item, dict) else None
        note = note_of(item) if isinstance(item, dict) else None
        if fact_key not in _PROOF_LABELS or text is None or note is None or (fact_key, text) in seen:
            dropped += 1
            continue
        seen.add((fact_key, text))
        proof.append({"fact_key": fact_key, "text": text, "note": note})
    return proof, dropped


def _check_policies(items, note_of) -> tuple[list, int]:
    policies, seen, dropped = [], set(), 0
    for item in items if isinstance(items, list) else []:
        key = item.get("key") if isinstance(item, dict) else None
        if not isinstance(key, str) or key not in vocab.POLICY_TYPES_BY_KEY or key in seen:
            dropped += 1
            continue
        params = _clean_policy_params(key, item.get("params"))
        note = note_of(item)
        if params is None or note is None:
            dropped += 1
            continue
        seen.add(key)
        policies.append({"key": key, "params": params, "note": note})
    return policies, dropped


def _check_products(items) -> tuple[list, int]:
    products, seen, dropped = [], set(), 0
    for item in items if isinstance(items, list) else []:
        name = _clean_text(item.get("name"), MAX_PRODUCT_NAME_CHARS) if isinstance(item, dict) else None
        if name is None or name in seen or len(products) >= MAX_PREFILL_PRODUCTS:
            dropped += 1
            continue
        seen.add(name)
        url = item.get("url")
        url = url.strip() if isinstance(url, str) and url.strip().startswith(("https://", "http://")) else None
        products.append({"name": name, "url": url})
    return products, dropped


def found_areas(prefill: dict) -> set:
    """The `PREFILL_AREAS` a checked prefill has something for."""
    found = {AREA_POSITIONING} if prefill.get("positioning") else set()
    found |= {AREA_TONE} if prefill.get("tone") else set()
    found |= {AREA_VISUAL} if prefill.get("visual") else set()
    found |= {_PROOF_LABELS[p["fact_key"]] for p in prefill.get("proof") or []}
    found |= {AREA_POLICIES} if prefill.get("policies") else set()
    found |= {AREA_PRODUCTS} if prefill.get("products") else set()
    return found


def validate_prefill_reply(data, *, pages_read: int, photos_read: int) -> tuple[dict | None, int]:
    """Program check of the prefill reply contract -> (prefill, dropped entry count).
    `None` = unreadable (not an object, or none of the contract's keys). Every entry is checked on
    its own: an invalid one (a tone outside `TONES`, an unknown proof/policy key, over-long text, a
    source this scan did not read, …) is dropped and counted; the rest is kept."""
    if not isinstance(data, dict) or not any(key in data for key in _PREFILL_KEYS):
        return None, 0

    def note_of(item: dict) -> str | None:
        return _clean_note(item.get("note"), pages_read=pages_read, photos_read=photos_read)

    out, dropped = _check_value_blocks(data, note_of)
    tone, n = _check_tone(data.get("tone"), note_of)
    dropped += n
    if tone is not None:
        out["tone"] = tone
    out["proof"], n = _check_proof(data.get("proof"), note_of)
    dropped += n
    out["policies"], n = _check_policies(data.get("policies"), note_of)
    dropped += n
    out["products"], n = _check_products(data.get("products"))
    dropped += n
    found = found_areas(out)
    raw_missing = data.get("not_found") if isinstance(data.get("not_found"), list) else []
    out["not_found"] = [a for a in dict.fromkeys(raw_missing) if a in PREFILL_AREAS and a not in found]
    dropped += len(raw_missing) - len(out["not_found"])
    return out, dropped


def _read_pages(urls: list) -> list:
    pages = []
    for url in urls[:MAX_PREFILL_PAGES]:
        ok, text = fetch_url(url)
        if ok and text and text.strip():
            pages.append((url, text.strip()))
    return pages


def _brand_photo_blocks(conn, brand_id: str) -> tuple[list, list]:
    """Up to `MAX_PREFILL_PHOTOS` brand photos as image content blocks + their kind labels. A
    photo that cannot be read or has an unsupported format is skipped (not counted as read)."""
    brand = bi_repo.get_brand(conn, brand_id) or {}
    blocks, kinds = [], []
    for asset in onboarding.brand_photo_assets(conn, brand_id):
        if len(blocks) >= MAX_PREFILL_PHOTOS:
            break
        try:
            content, content_type = storage.get(org_id=brand["org_id"], key=asset["storage_key"])
            blocks.append(providers.base64_image_block(content_type, content))
        except (storage.StorageError, ValueError, KeyError):
            continue
        kinds.append(vocab.asset_kind_label(asset["asset_kind"]))
    return blocks, kinds


def empty_prefill() -> dict:
    return {"proof": [], "policies": [], "products": [], "not_found": [],
            "pages_read": 0, "photos_read": 0}


def run_prefill(conn, draft: dict) -> tuple:
    """Read the draft's website pages (≤5) and brand photos (≤5) and send them in ONE call; store
    the checked proposal in `intake_draft.prefill_json` with `pages_read`/`photos_read`.
    (True, None) on success; (False, 人話錯誤) when the call failed or the reply is unreadable.
    Nothing readable (every page failed, no photo): no call, an empty prefill that read 0/0."""
    brand_id = draft["brand_id"]
    pages = _read_pages(draft["urls"])
    blocks, kinds = _brand_photo_blocks(conn, brand_id)
    if not pages and not blocks:
        ir.update_draft(conn, brand_id, draft["id"], prefill_json=empty_prefill())
        return True, None
    text = {"type": "text", "text": _prefill_prompt(draft["brand_name"], pages, kinds)}
    task = _run(conn, draft, task_type=PREFILL_TASK_TYPE, purpose=PREFILL_PURPOSE,
                system=_PREFILL_SYSTEM, user_text="", content_blocks=[*blocks, text],
                options=gateway.TaskOptions(max_tokens=PREFILL_MAX_TOKENS))
    if task["status"] != "succeeded":
        return False, task["error"]
    prefill, dropped = validate_prefill_reply(
        _parse_json_reply(task["rendered_output"]), pages_read=len(pages), photos_read=len(blocks))
    if prefill is None:
        return False, PARSE_FAIL_MESSAGE
    if dropped:
        _log.info("intake prefill %s: dropped %d invalid entries", task["id"], dropped)
    prefill.update(pages_read=len(pages), photos_read=len(blocks))
    ir.update_draft(conn, brand_id, draft["id"], prefill_json=prefill)
    return True, None


def prefill_failure_message(conn, draft_row: dict) -> str:
    """What a failed prefill job shows: its last model call's own error; a call that succeeded
    means the reply was unreadable; no call at all = the queue's generic message."""
    from app.background import JOB_FAILED_MESSAGE

    refs = [r for r in draft_row.get("llm_task_refs_json") or [] if r.get("purpose") == PREFILL_PURPOSE]
    task = gateway.get_task(conn, refs[-1]["llm_task_id"]) if refs else None
    if task is None:
        return JOB_FAILED_MESSAGE
    if task["status"] == "succeeded":
        return PARSE_FAIL_MESSAGE
    return task["error"] or JOB_FAILED_MESSAGE
