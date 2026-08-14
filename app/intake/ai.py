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

import json

from app.core import net
from app.intake import repository as ir
from app.intake import script, state
from app.llm import gateway, providers

# 測試可整個換掉（跟 app/tests 既有 FakeProvider 風格一致）
PROVIDER = providers.AnthropicProvider()

# 綁成本模組的名字，測試才能只換這裡（實作已移到 app/core/net.py，產品調研也要用）
fetch_url = net.fetch_url

PARSE_FAIL_MESSAGE = "AI 有回覆，但格式讀不成預期的樣子。可以再試一次。"
QUESTION_ASPECTS = ("產品線", "價格帶", "客群", "語調", "法規風險")


_parse_json_reply = gateway.parse_json_reply  # 搬到 gateway.py 公開，這裡留別名（行為零變化）


def _run(conn, draft: dict, *, task_type: str, purpose: str, system: str, user_text: str,
         options: gateway.TaskOptions = None) -> dict:
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
    if asked >= script.MAX_QUESTIONS:
        state.mark_qa_done(draft)
        state.save(draft, conn)
        return True, None
    covered = [aspect for aspect in QUESTION_ASPECTS if any(
        isinstance(entry, dict) and entry.get("aspect") == aspect
        for entry in draft.get("qa") or []
    )]
    missing = [aspect for aspect in QUESTION_ASPECTS if aspect not in covered]
    lines = [f"品牌名稱：{draft['brand_name']}", f"業主描述：{draft['description']}"]
    for imp in draft["scan_impressions"]:
        lines.append(f"初步印象（{imp['looks_like']}）{imp['title']}：{imp['content']}")
    for a in draft["answers"]:
        note = f"（補充：{a['note']}）" if a["note"] else ""
        lines.append(f"已問過：{a['question']}／業主選：{a['choice_label']}{note}")
    lines.append(f"已覆蓋面向：{'、'.join(covered) if covered else '無'}")
    lines.append(f"未覆蓋面向：{'、'.join(missing) if missing else '無'}")
    lines.append(
        f"你已經問了 {asked} 題（上限 {script.MAX_QUESTIONS} 題）。"
        "收斂規則（硬性）：問到第 5 題起，除非還有一個「不問就會讓調研方向走錯」的明顯缺口，"
        '一律回 {"done": true} 收尾——寧可少問，不要為了問而問。\n'
        "只要還有未覆蓋面向且尚未達題數上限，就不能回 done，必須從未覆蓋面向繼續出題。"
        "還需要問時，每一題要有：所屬面向、問題本身、一個你最建議的答案"
        "（含一句白話說明為什麼建議、選了調研會往哪去）、2 到 3 個分支選項（各含說明）。"
        "問題要根據前面的回答遞進，不要重複問過的面向。\n"
        '還需要問：只回傳 {"done": false, "aspect": "產品線/價格帶/客群/語調/法規風險其中一個", '
        '"question": "問題", '
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
        if missing:
            return False, (f"還有 {len(missing)} 個面向沒問到：{'、'.join(missing)}。"
                           "請繼續出題。")
        state.mark_qa_done(draft)
        state.save(draft, conn)
        return True, None
    if (data.get("aspect") not in QUESTION_ASPECTS or not data.get("question")
            or not isinstance(data.get("suggested"), dict)):
        return False, PARSE_FAIL_MESSAGE
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
    from app.brand_intelligence import repository as bi_repo
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
    structured = json.loads(task["structured_output_json"]) if task["structured_output_json"] else None
    if isinstance(structured, dict) and isinstance(structured.get("rows"), list):
        return True, structured["rows"]
    return True, task["rendered_output"]
