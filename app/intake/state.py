# -*- coding: utf-8 -*-
"""app/intake/state.py — 建檔精靈的草稿狀態（存 intake_draft 資料表，重啟可續接）。

原本是模組層 dict 的 Mock；本輪改為每次讀寫都經 app/intake/repository.py 落地 DB。
對外仍回傳與 Mock 時代相同形狀的草稿 dict（模板與路由不必跟著大改）：
load 時把 §3A.2 的欄位（photos_json、scan_impressions_json、qa_json…）轉回畫面慣用的
鍵名；save 時再轉回去。花費（cost_spent / cost_items）不存副本，每次 load 都即時
SUM llm_task.cost（03 §3A.5 第 5 點）。

qa_json 一筆＝一題：{no, question, options:[{key,label,note}], suggested_key,
answer_key, answer_text, skipped, llm_task_id}（03 §3A.2）。answer_key 為空＝這題
還沒答（畫面上的「目前這一題」）。問答結束（AI 說夠了或到達上限）以結尾的
{"done": true} 哨兵標記——03 §3A 沒有專欄可放這個旗標，先以此代替（見回報）。
"""

import json
import os
import re
from pathlib import Path
from typing import Optional

from app.core.db import new_id
from app.intake import repository as ir
from app.intake import script

REFRESH_SECONDS = 3  # 進度頁 <meta refresh> 秒數，與 DESIGN.md §19.4 範例一致

WIZARD_STEPS = [
    (1, "起始輸入"),
    (2, "初步印象"),
    (3, "引導問答"),
    (4, "交接包"),
    (5, "貼回"),
]


def _conn(conn=None):
    """沒帶連線就用 app.shared.web 的共用連線（延遲 import 避免循環匯入；修憲落地
    A4：原本讀 app.main，會跟 main.py 兜成循環，改讀 app.shared.web；連線在測試
    會被 reopen_connection() 換掉，所以每次都要即時取屬性）。"""
    if conn is not None:
        return conn
    import app.shared.web as main_mod
    return main_mod.conn


# ---------------------------------------------------------------------------
# DB 列 ↔ 畫面草稿 dict
# ---------------------------------------------------------------------------

def _loads(raw, default):
    if not raw:
        return default
    try:
        return json.loads(raw)
    except ValueError:
        return default


def _qa_entries(qa: list) -> list:
    return [e for e in qa if not e.get("done")]


def _answer_label(entry: dict) -> str:
    key = entry.get("answer_key")
    if key == "other":
        return "以上都不是，我自己說"
    for opt in entry.get("options") or []:
        if opt.get("key") == key:
            return opt.get("label") or ""
    return key or ""


def _row_to_draft(conn, row: dict) -> dict:
    brand_row = conn.execute("SELECT name FROM brand WHERE id = ?", (row["brand_id"],)).fetchone()
    photos = [
        {"name": p.get("display_name"), "path": p.get("file_path"),
         "size_mb": round((p.get("size_bytes") or 0) / (1024 * 1024), 1)}
        for p in _loads(row["photos_json"], [])
    ]
    impressions = [
        {"looks_like": i.get("aspect"), "title": i.get("title"),
         "content": i.get("body"), "basis": i.get("basis")}
        for i in _loads(row["scan_impressions_json"], [])
    ]
    qa = _loads(row["qa_json"], [])
    entries = _qa_entries(qa)
    qa_done = any(e.get("done") for e in qa)
    answers = [
        {"index": e["no"] - 1, "question": e["question"],
         "choice_label": _answer_label(e), "note": e.get("answer_text") or ""}
        for e in entries if e.get("answer_key")
    ]
    current = next((e for e in entries if not e.get("answer_key") and not e.get("skipped")), None)
    resolved = len([e for e in entries if e.get("answer_key") or e.get("skipped")])
    validation = _loads(row["paste_validation_json"], None)

    draft = {
        "id": row["id"],
        "brand_id": row["brand_id"],
        "brand_name": brand_row["name"] if brand_row else "",
        "description": row["description"],
        "urls": _loads(row["research_urls_json"], []),
        "photos": photos,
        "budget_limit": row["cost_limit"],
        "scan_done": row["scan_impressions_json"] is not None,
        "scan_impressions": impressions,
        "scan_products": _loads(row["scan_products_json"], []),
        "url_results": _loads(row["scan_sources_json"], []),
        "qa": qa,
        "qa_done": qa_done,
        "answers": answers,
        "current_q": ({"question": current["question"],
                       "suggested": next(({"label": o["label"], "desc": o.get("note") or ""}
                                          for o in current.get("options") or []
                                          if o.get("key") == "suggested"), None),
                       "branches": [{"label": o["label"], "desc": o.get("note") or ""}
                                    for o in current.get("options") or []
                                    if str(o.get("key", "")).startswith("branch_")]}
                      if current else None),
        "question_index": resolved,
        "handoff_depth": row["handoff_depth"],
        "handoff_generated": row["handoff_generated_at"] is not None,
        "handoff_prompt": row["handoff_prompt"],
        "paste_raw": row["paste_raw"] or "",
        "paste_errors": (validation or {}).get("errors") or [],
        "paste_fix_used": row["repair_llm_task_id"] is not None,
        "step": row["current_step"],
    }
    draft["cost_items"] = ir.list_llm_cost_items(conn, row)
    draft["cost_spent"] = sum(it["amount"] for it in draft["cost_items"] if not it["failed"])
    pending = conn.execute(
        "SELECT COUNT(*) FROM intake_item WHERE intake_draft_id = ? AND outcome = 'pending'",
        (row["id"],),
    ).fetchone()[0]
    draft["pending_item_count"] = pending
    draft["resume_path"] = _resume_path(draft)
    return draft


def _resume_path(draft: dict) -> str:
    b = draft["brand_id"]
    step = draft["step"]
    if step <= 2:
        return f"/brands/{b}/intake/scan" if draft["scan_done"] else f"/brands/{b}/intake/scan/progress"
    if step == 3:
        return f"/brands/{b}/intake/question"
    if step == 4:
        return f"/brands/{b}/intake/handoff"
    return (f"/brands/{b}/intake/review" if draft["pending_item_count"]
            else f"/brands/{b}/intake/paste")


def save(draft: dict, conn=None) -> None:
    """把畫面草稿 dict 的可變欄位寫回 intake_draft（每一步送出即存草稿，§19.3 規則 1）。"""
    conn = _conn(conn)
    photos = [
        {"file_path": p.get("path"), "display_name": p.get("name"),
         "size_bytes": int(round((p.get("size_mb") or 0) * 1024 * 1024))}
        for p in draft["photos"]
    ]
    impressions = None
    if draft["scan_done"]:
        impressions = [
            {"aspect": i.get("looks_like"), "title": i.get("title"),
             "body": i.get("content"), "basis": i.get("basis")}
            for i in draft["scan_impressions"]
        ]
    entries = _qa_entries(draft["qa"])
    validation = None
    if draft["paste_raw"]:
        validation = {"ok": not draft["paste_errors"],
                      "total_rows": None, "errors": draft["paste_errors"]}
    ir.update_draft(
        conn, draft["brand_id"], draft["id"],
        current_step=draft["step"],
        current_question_no=len(entries),
        description=draft["description"],
        photos_json=json.dumps(photos, ensure_ascii=False),
        research_urls_json=json.dumps(draft["urls"], ensure_ascii=False),
        scan_sources_json=(json.dumps(draft["url_results"], ensure_ascii=False)
                           if draft["scan_done"] else None),
        scan_impressions_json=(json.dumps(impressions, ensure_ascii=False)
                               if impressions is not None else None),
        qa_json=json.dumps(draft["qa"], ensure_ascii=False) if draft["qa"] else None,
        handoff_depth=draft["handoff_depth"],
        paste_raw=draft["paste_raw"] or None,
        paste_validation_json=(json.dumps(validation, ensure_ascii=False)
                               if validation is not None else None),
        cost_limit=draft["budget_limit"],
    )


def new_draft(brand_id: str, brand_name: str, *, description: str, urls: list, photos: list,
              actor: str = "", conn=None) -> dict:
    conn = _conn(conn)
    photos_db = [
        {"file_path": p.get("path"), "display_name": p.get("name"),
         "size_bytes": int(round((p.get("size_mb") or 0) * 1024 * 1024))}
        for p in photos
    ]
    row = ir.create_draft(conn, brand_id, description, photos_db, urls, actor)
    return _row_to_draft(conn, row)


def get_draft(brand_id: str, conn=None) -> Optional[dict]:
    conn = _conn(conn)
    row = ir.get_active_draft(conn, brand_id)
    return _row_to_draft(conn, row) if row else None


def complete_draft(draft: dict, conn=None) -> None:
    ir.complete_draft(_conn(conn), draft["brand_id"], draft["id"])


def touch(draft: dict, path: str, step: int, conn=None) -> None:
    """每個精靈 GET 頁面呼叫一次：記下「現在停在第幾步」，供續接連結使用。"""
    if draft["step"] != step:
        draft["step"] = step
        ir.update_draft(_conn(conn), draft["brand_id"], draft["id"], current_step=step)
    draft["resume_path"] = path


# ---------------------------------------------------------------------------
# 照片上傳（W1）：真的存檔到本機資料夾（DESIGN.md §17 第 14 項），data/ 已在 .gitignore。
#
# W1 送出時可能還沒有品牌（表單驗證失敗要重來），所以先用一個跟 brand_id 無關的暫存
# token 當資料夾名稱；驗證通過真的建立品牌、寫進草稿後，token 這個暫存記錄就可以丟了。
# 暫存區留在記憶體沒關係——它只活在「表單還沒送成功」的幾分鐘內，不屬於草稿續接範圍。
# ---------------------------------------------------------------------------

DEFAULT_UPLOAD_DIR = Path("C:/Users/User/Desktop/marketing/data/uploads/intake")

_UNSAFE_FILENAME_CHARS = re.compile(r"[^A-Za-z0-9._-]+")

# token -> [{"name":.., "size_mb":.., "path":..}]（尚未落地成草稿前的暫存區）
PENDING_PHOTOS: dict = {}


def get_upload_dir() -> Path:
    raw = os.environ.get("BRAND_OS_UPLOADS")
    return Path(raw) if raw else DEFAULT_UPLOAD_DIR


def safe_filename(name: str) -> str:
    """os.path.basename 去掉路徑 + 危險字元換成 `_`，防路徑穿越（上傳檔名不可信任）。"""
    name = os.path.basename((name or "").strip())
    name = _UNSAFE_FILENAME_CHARS.sub("_", name)
    return name or "photo"


def new_photo_token() -> str:
    return new_id("pht")


def get_pending_photos(token: str) -> list:
    return list(PENDING_PHOTOS.get(token) or [])


def save_photo(token: str, filename: str, content: bytes) -> dict:
    """把這張照片的位元組真的寫進磁碟，並記進 token 的暫存清單。

    W1 驗證失敗、使用者補資料重送時，同一個 token 沿用已經存好的照片——不必也
    不會要求使用者重新選檔。
    """
    name = safe_filename(filename)
    folder = get_upload_dir() / token
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / name
    path.write_bytes(content)
    entry = {"name": name, "size_mb": round(len(content) / (1024 * 1024), 1), "path": str(path)}
    PENDING_PHOTOS.setdefault(token, []).append(entry)
    return entry


def discard_pending_photos(token: str) -> None:
    """草稿建立後，照片已經轉存進 photos_json，暫存區這筆就不再需要。"""
    PENDING_PHOTOS.pop(token, None)


# ---------------------------------------------------------------------------
# 花費（真實 token 成本：即時 SUM llm_task.cost，不存副本）
# ---------------------------------------------------------------------------

def would_exceed(draft: dict, amount: float) -> bool:
    """R3／W12：呼叫送出之前先判斷「已花費 + 本次預估 > 上限」。"""
    return draft["cost_spent"] + amount > draft["budget_limit"]


def cost_state(draft: dict) -> str:
    spent, limit = draft["cost_spent"], draft["budget_limit"]
    if limit <= 0 or spent >= limit:
        return "over"
    if spent >= limit * 0.8:
        return "near"
    return "normal"


# ---------------------------------------------------------------------------
# 問答紀錄（qa_json）
# ---------------------------------------------------------------------------

def append_question(draft: dict, question: str, suggested: dict, branches: list,
                    llm_task_id: Optional[str]) -> None:
    entries = _qa_entries(draft["qa"])
    options = [{"key": "suggested", "label": suggested.get("label") or "",
                "note": suggested.get("desc") or ""}]
    for i, b in enumerate(branches):
        options.append({"key": f"branch_{i}", "label": b.get("label") or "",
                        "note": b.get("desc") or ""})
    draft["qa"].append({
        "no": len(entries) + 1, "question": question, "options": options,
        "suggested_key": "suggested", "answer_key": None, "answer_text": None,
        "skipped": False, "llm_task_id": llm_task_id,
    })


def mark_qa_done(draft: dict) -> None:
    if not draft["qa_done"]:
        draft["qa"].append({"done": True})
        draft["qa_done"] = True


def current_entry(draft: dict) -> Optional[dict]:
    return next((e for e in _qa_entries(draft["qa"])
                 if not e.get("answer_key") and not e.get("skipped")), None)


def question_count(draft: dict) -> int:
    return len(_qa_entries(draft["qa"]))


# ---------------------------------------------------------------------------
# 示範資料專用：直接生出「已完成初掃、答了前兩題」的草稿（DESIGN.md §14.3 品牌 C）
# ---------------------------------------------------------------------------

def seed_in_progress_draft(brand_id: str, brand_name: str, conn=None) -> dict:
    """只給 app/seed_demo.py 呼叫。不跑一次精靈，直接構造出對應 §14.3 描述的草稿狀態
    （含三筆示範 llm_task，讓花費明細有東西可看），用來驗收「建檔進行中・繼續建檔」
    與草稿續接（§19.3）。"""
    conn = _conn(conn)
    draft = new_draft(
        brand_id, brand_name,
        description="做台灣中南部小農的烏龍與紅茶，主打單一產區、冷泡也不苦。",
        urls=["https://example.com/about", "https://example.com/products",
              "https://example.com/blog/2024", "https://example.com/press"],
        photos=[{"name": "小滿製茶_烏龍茶包_正面.jpg", "size_mb": 1.8, "path": None},
                {"name": "小滿製茶_包裝背標.png", "size_mb": 0.9, "path": None}],
        conn=conn,
    )
    draft["scan_done"] = True
    draft["scan_impressions"] = list(script.SCAN_IMPRESSIONS)
    draft["url_results"] = [
        {"url": draft["urls"][0], "ok": True}, {"url": draft["urls"][1], "ok": True},
        {"url": draft["urls"][2], "ok": True}, {"url": draft["urls"][3], "ok": False},
    ]
    demo_tasks = [
        ("讀取網址與整理初步印象", "intake_scan", 4.20),
        ("第 1 題", "intake_question", 1.50),
        ("第 2 題", "intake_question", 1.50),
    ]
    from app.core import db as coredb
    for purpose, task_type, cost in demo_tasks:
        task_id = coredb.new_id("llm")
        conn.execute(
            """INSERT INTO llm_task (id, brand_id, task_type, context_scope_json,
                input_context_ids_json, input_context_hash, knowledge_item_ids_json,
                brand_version, prompt_template_id, prompt_template_version, provider, model,
                status, attempt_no, cost, started_at, finished_at)
               VALUES (?, ?, ?, ?, '[]', '', '[]', 1, ?, 'v1', 'seed', 'seed-demo',
                       'succeeded', 1, ?, ?, ?)""",
            (task_id, brand_id, task_type,
             json.dumps({"brand_id": brand_id}, ensure_ascii=False),
             task_type, cost, coredb.now_iso(), coredb.now_iso()),
        )
        conn.commit()
        ir.add_llm_task_ref(conn, brand_id, draft["id"], task_id, purpose)
    for i in range(2):
        q = script.QUESTIONS[i]
        append_question(draft, q["question"], q["suggested"], q["branches"], None)
        draft["qa"][-1]["answer_key"] = "suggested"
    q3 = script.QUESTIONS[2]
    append_question(draft, q3["question"], q3["suggested"], q3["branches"], None)
    draft["step"] = 3
    save(draft, conn)
    return get_draft(brand_id, conn)
