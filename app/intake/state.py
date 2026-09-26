"""app/intake/state.py — 建檔精靈的草稿狀態（存 intake_draft 資料表，重啟可續接）。

原本是模組層 dict 的 Mock；本輪改為每次讀寫都經 app/intake/repository.py 落地 DB。
對外仍回傳與 Mock 時代相同形狀的草稿 dict（模板與路由不必跟著大改）：
load 時把 §3A.2 的欄位（photos_json、scan_impressions_json、qa_json…）轉回畫面慣用的
鍵名；save 時再轉回去。花費（cost_spent / cost_items）不存副本，每次 load 都即時
SUM llm_task.cost（03 §3A.5 第 5 點）。

qa_json 一筆＝一題：{no, aspect?, question, options:[{key,label,note}], suggested_key,
answer_key, answer_text, skipped, llm_task_id}（03 §3A.2）。answer_key 為空＝這題
還沒答（畫面上的「目前這一題」）。問答結束（AI 說夠了或到達上限）以結尾的
{"done": true} 哨兵標記——03 §3A 沒有專欄可放這個旗標，先以此代替（見回報）。
"""

import os
import re

from app import storage
from app.core.db import new_id
from app.intake import repository as ir

REFRESH_SECONDS = 3  # 進度頁 <meta refresh> 秒數（原設計文件 §19.4 範例已刪）

WIZARD_STEPS = [
    (1, "起始輸入"),
    (2, "初步印象"),
    (3, "賣什麼與數字"),
    (4, "接工具"),
    (5, "品牌知識"),
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
    """`raw` 是 jsonb 欄位讀出來的值：psycopg 已經解析成 dict/list，直接回傳即可
    （02-3b：不再是字串，不再需要 json.loads）。"""
    return raw if raw is not None else default


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


def _scan_product_data(raw) -> tuple[list, list]:
    """新舊 scan_products_json 相容：舊版是名稱陣列，新版同欄位再帶照片產品卡。"""
    value = _loads(raw, [])
    if isinstance(value, dict):
        names = value.get("names") if isinstance(value.get("names"), list) else []
        cards = (value.get("product_card_drafts")
                 if isinstance(value.get("product_card_drafts"), list) else [])
        return [str(name) for name in names if str(name).strip()], [c for c in cards if isinstance(c, dict)]
    if isinstance(value, list):
        return [str(name) for name in value if isinstance(name, str) and name.strip()], []
    return [], []


def _row_to_draft(conn, row: dict) -> dict:
    brand_row = conn.execute("SELECT name FROM brand WHERE id = %s", (row["brand_id"],)).fetchone()
    photos = [
        {"name": p.get("display_name"), "storage_key": p.get("storage_key"),
         "size_mb": round((p.get("size_bytes") or 0) / (1024 * 1024), 1),
         "token": p.get("token") or ""}
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
    scan_products, product_card_drafts = _scan_product_data(row["scan_products_json"])

    draft = {
        "id": row["id"],
        "brand_id": row["brand_id"],
        "brand_name": brand_row["name"] if brand_row else "",
        "status": row["status"],
        "description": row["description"],
        "urls": _loads(row["research_urls_json"], []),
        "photos": photos,
        "budget_limit": float(row["cost_limit"]),
        "scan_done": row["scan_impressions_json"] is not None,
        "scan_impressions": impressions,
        "scan_products": scan_products,
        "product_card_drafts": product_card_drafts,
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
        "SELECT COUNT(*) AS n FROM intake_item WHERE intake_draft_id = %s AND outcome = 'pending'",
        (row["id"],),
    ).fetchone()["n"]
    draft["pending_item_count"] = pending
    draft["resume_path"] = _resume_path(draft)
    return draft


def _resume_path(draft: dict) -> str:
    b = draft["brand_id"]
    return f"/app/brands/{b}/intake"


def save(draft: dict, conn=None) -> None:
    """把畫面草稿 dict 的可變欄位寫回 intake_draft（每一步送出即存草稿，§19.3 規則 1）。"""
    conn = _conn(conn)
    photos = [
        {"storage_key": p.get("storage_key"), "display_name": p.get("name"),
         "size_bytes": int(round((p.get("size_mb") or 0) * 1024 * 1024)),
         "token": p.get("token") or ""}
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
        photos_json=photos,
        research_urls_json=draft["urls"],
        scan_sources_json=(draft["url_results"] if draft["scan_done"] else None),
        scan_impressions_json=impressions,
        scan_products_json={
            "names": draft.get("scan_products") or [],
            "product_card_drafts": draft.get("product_card_drafts") or [],
        },
        qa_json=draft["qa"] if draft["qa"] else None,
        handoff_depth=draft["handoff_depth"],
        paste_raw=draft["paste_raw"] or None,
        paste_validation_json=validation,
        cost_limit=draft["budget_limit"],
    )


def new_draft(brand_id: str, brand_name: str, *, description: str, urls: list, photos: list,
              actor: str = "", conn=None) -> dict:
    conn = _conn(conn)
    photos_db = [
        {"storage_key": p.get("storage_key"), "display_name": p.get("name"),
         "size_bytes": int(round((p.get("size_mb") or 0) * 1024 * 1024)),
         "token": p.get("token") or ""}
        for p in photos
    ]
    row = ir.create_draft(conn, brand_id, description, photos_db, urls, actor)
    return _row_to_draft(conn, row)


def get_draft(brand_id: str, conn=None) -> dict | None:
    conn = _conn(conn)
    row = ir.get_active_draft(conn, brand_id)
    return _row_to_draft(conn, row) if row else None


def is_restart_draft(brand_id: str, draft_id: str, conn=None) -> bool:
    """這份草稿是不是「重新調研」（W1b）開出來的——用「同品牌是否已有其他完成過的草稿」
    當判準，不另開欄位（票 B3-intake，前端契約 `IntakeDraft.is_restart`）。"""
    conn = _conn(conn)
    row = conn.execute(
        "SELECT COUNT(*) AS c FROM intake_draft WHERE brand_id = %s AND id != %s AND status = 'completed'",
        (brand_id, draft_id),
    ).fetchone()
    return (row["c"] if row else 0) > 0


def invalid_url(urls: list) -> str | None:
    """回傳第一個格式不對的網址；全部合法回 None（S4.5，HTML／JSON 兩套路由共用）。"""
    return next((u for u in urls if not (u.startswith("http://") or u.startswith("https://"))), None)


def prev_photos(last_draft_row: dict | None) -> list:
    """上一輪草稿的照片（photos_json 形狀 → 畫面／new_draft 慣用形狀）；W1b 重新調研沿用。"""
    if not last_draft_row:
        return []
    return [
        {"name": p.get("display_name"), "storage_key": p.get("storage_key"),
         "size_mb": round((p.get("size_bytes") or 0) / (1024 * 1024), 1),
         "token": p.get("token") or ""}
        for p in (last_draft_row["photos_json"] or [])
    ]


def skip_scan(draft: dict) -> None:
    """把初掃標成做完，不留任何偵測結果——不呼叫模型（`/scan/skip` 端點與『起始輸入
    沒東西可掃』共用同一組賦值，CLAUDE.md 第五節：同一能力只准一條代碼路徑）。"""
    draft["scan_done"] = True
    draft["scan_impressions"] = []
    draft["scan_products"] = []
    draft["product_card_drafts"] = []
    draft["url_results"] = []


def start_draft(conn, brand_id: str, brand_name: str, *, description: str, urls: list,
                photos: list, actor: str) -> dict:
    """S4.9／S4.10 共用判斷：草稿永遠建立（2026-09-14 修法——F05 之後精靈第 3／4／5 步
    （賣什麼與數字／接工具／品牌知識）跟掃描無關，『沒東西可掃』不再等於『沒事做』，
    S4.9 時代『陽春路徑不建草稿』的假設已經不成立）。描述／網址／照片三者皆空時，建完
    草稿後照 `skip_scan` 把初掃標成做完、停在第 3 步；這條路徑上不准有任何模型呼叫，
    『不花錢』的性質原封不動保住。呼叫端（JSON API）先各自建好／取得品牌，這裡只管
    「建了草稿之後要不要略過初掃」這一刀，不重複寫兩次。"""
    draft = new_draft(brand_id, brand_name, description=description, urls=urls, photos=photos,
                      actor=actor, conn=conn)
    if not description and not urls and not photos:
        skip_scan(draft)
        draft["step"] = 3
        save(draft, conn)
    return draft


def apply_paste(draft: dict, paste_input, conn=None) -> int | None:
    """驗證＋（全過才）整批落地 intake_item。回傳落地筆數；驗證失敗回 None（錯誤已寫進草稿）。

    W8 貼回頁的 HTML 表單與 JSON API（paste/validate、paste/resolve-scope、AI 修格式完成後）
    共用同一支，不寫兩份（CLAUDE.md 第五節；票 B3-intake 從 routes.py `_apply_paste` 搬來）。"""
    from app.brand_intelligence import repository as bi_repo
    from app.intake import paste_parse
    conn = _conn(conn)
    known = {p["name"] for p in bi_repo.list_products(conn, draft["brand_id"])}
    if isinstance(paste_input, list):
        rows, errors = paste_parse.validate_rows(
            paste_input, known, brand_name=draft["brand_name"])
    else:
        # 先去掉 Markdown 外框／分隔線，再處理剪貼簿吃掉換行；草稿保存系統讀懂的版本。
        raw_text = paste_parse.normalize_markdown_table(str(paste_input))
        raw_text = paste_parse.maybe_reflow(raw_text)
        draft["paste_raw"] = raw_text
        rows, errors = paste_parse.parse_paste(raw_text, known, brand_name=draft["brand_name"])
    draft["paste_errors"] = errors
    save(draft, conn)
    if rows is None:
        # 重貼失敗就清掉上一次還沒處理的待辦列（已處理的留著追溯）
        conn.execute(
            "DELETE FROM intake_item WHERE intake_draft_id = %s AND brand_id = %s AND outcome = 'pending'",
            (draft["id"], draft["brand_id"]),
        )
        conn.commit()
        return None
    items = ir.create_items(conn, draft["brand_id"], draft["id"], rows)
    return len(items)


def create_scanned_products(conn, brand_id: str, draft: dict, names: list, actor: str) -> int:
    """S4.22 一鍵建立偵測到的產品：只准建「AI 有偵測到、且還沒存在」的名字。"""
    from app.brand_intelligence import repository as bi_repo
    suggested = set(draft["scan_products"])
    known = {p["name"] for p in bi_repo.list_products(conn, brand_id)}
    created = 0
    for name in names:
        name = (name or "").strip()
        if name and name in suggested and name not in known:
            bi_repo.create_product(conn, brand_id, name=name, actor=actor)
            created += 1
            known.add(name)
    return created


def create_product_from_card(conn, brand_id: str, draft: dict, source_photo_token: str,
                             actor: str) -> str | None:
    """照片產品卡沿用既有產品／產品事實入口；價格不寫入任何欄位。"""
    from app.brand_intelligence import repository as bi_repo
    card = next((item for item in draft.get("product_card_drafts") or []
                 if item.get("status") == "ready"
                 and item.get("source_photo_token") == source_photo_token), None)
    if card is None or not str(card.get("name") or "").strip():
        return None
    known = {product["name"] for product in bi_repo.list_products(conn, brand_id)}
    if card["name"] in known:
        return None
    product = bi_repo.create_product(conn, brand_id, name=card["name"], actor=actor)
    facts = []
    if str(card.get("specification") or "").strip():
        facts.append(("規格", str(card["specification"]).strip()))
    selling_points = "、".join(str(point).strip() for point in card.get("selling_points") or []
                               if str(point).strip())
    if selling_points:
        facts.append(("賣點", selling_points))
    for label, value in facts:
        bi_repo.create_product_fact(
            conn, brand_id, product["id"], actor=actor, fact_type="core_info",
            label=label, value=value, status="confirmed", confirmed_by="使用者",
        )
    return product["id"]


def complete_draft(draft: dict, conn=None) -> None:
    ir.complete_draft(_conn(conn), draft["brand_id"], draft["id"])


OFFERINGS_SELL_TYPES = ("product", "service", "both")
OFFERINGS_AD_DELIVERIES = ("direct", "ask", "lead")


def parse_offerings_choice(raw) -> dict | None:
    """Contract M: `{sell_type, ad_delivery}` with both values from the fixed sets, else None."""
    if not isinstance(raw, dict):
        return None
    sell_type, ad_delivery = raw.get("sell_type"), raw.get("ad_delivery")
    if sell_type not in OFFERINGS_SELL_TYPES or ad_delivery not in OFFERINGS_AD_DELIVERIES:
        return None
    return {"sell_type": sell_type, "ad_delivery": ad_delivery}


def offerings_choice(brand_id: str, conn=None) -> dict | None:
    """The offerings step's saved choice (Contract M): the active draft's, else the latest
    completed draft's (a finished brand reopening step 3); None when never saved."""
    conn = _conn(conn)
    row = ir.get_active_draft(conn, brand_id) or ir.get_latest_completed_draft(conn, brand_id)
    return parse_offerings_choice(row.get("offerings_choice_json")) if row else None


def save_offerings_choice(draft: dict, choice: dict, conn=None) -> None:
    ir.update_draft(_conn(conn), draft["brand_id"], draft["id"], offerings_choice_json=choice)


def touch(draft: dict, path: str, step: int, conn=None) -> None:
    """每個精靈 GET 頁面呼叫一次：記下「現在停在第幾步」，供續接連結使用。"""
    if draft["step"] != step:
        draft["step"] = step
        ir.update_draft(_conn(conn), draft["brand_id"], draft["id"], current_step=step)
    draft["resume_path"] = path


# ---------------------------------------------------------------------------
# 照片上傳（W1）：存進 Supabase Storage（app/storage，票 storage-03；ADR 0043 key 形狀
# `<org_id>/intake/<token>/<filename>`），本機磁碟不再落地。
#
# W1 送出時可能還沒有品牌（表單驗證失敗要重來），所以先用一個跟 brand_id 無關的暫存
# token 當 key 的一段；驗證通過真的建立品牌、寫進草稿後，token 這個暫存記錄就可以丟了。
# 暫存區留在記憶體沒關係——它只活在「表單還沒送成功」的幾分鐘內，不屬於草稿續接範圍。
# ---------------------------------------------------------------------------

_UNSAFE_FILENAME_CHARS = re.compile(r"[^A-Za-z0-9._-]+")

_PHOTO_CONTENT_TYPES = {
    "jpg": "image/jpeg", "jpeg": "image/jpeg", "png": "image/png", "webp": "image/webp",
}

# token -> [{"name":.., "size_mb":.., "storage_key":..}]（尚未落地成草稿前的暫存區）
PENDING_PHOTOS: dict = {}


def safe_filename(name: str) -> str:
    """os.path.basename 去掉路徑 + 危險字元換成 `_`，防路徑穿越（上傳檔名不可信任）。"""
    name = os.path.basename((name or "").strip())
    name = _UNSAFE_FILENAME_CHARS.sub("_", name)
    return name or "photo"


def new_photo_token() -> str:
    return new_id("pht")


def get_pending_photos(token: str) -> list:
    return list(PENDING_PHOTOS.get(token) or [])


def save_photo(token: str, filename: str, content: bytes, *, org_id: str) -> dict:
    """把這張照片的位元組存進 Storage（`<org_id>/intake/<token>/<filename>`），並記進
    token 的暫存清單。

    W1 驗證失敗、使用者補資料重送時，同一個 token 沿用已經存好的照片——不必也
    不會要求使用者重新選檔。
    """
    name = safe_filename(filename)
    key = f"{org_id}/intake/{token}/{name}"
    ext = name.rsplit(".", 1)[-1].lower() if "." in name else ""
    content_type = _PHOTO_CONTENT_TYPES.get(ext, "application/octet-stream")
    storage.put(org_id=org_id, key=key, filename=name, content=content, content_type=content_type)
    entry = {"name": name, "size_mb": round(len(content) / (1024 * 1024), 1), "storage_key": key}
    PENDING_PHOTOS.setdefault(token, []).append(entry)
    return entry


def discard_pending_photos(token: str) -> None:
    """草稿建立後，照片已經轉存進 photos_json，暫存區這筆就不再需要——不刪 Storage 物件，
    草稿此刻已經引用它了（票 storage-03「Explicitly not fixed here」：中途放棄的精靈
    session 留下孤兒物件，跟今天留下孤兒檔案一樣，行為不變、範圍之外）。"""
    PENDING_PHOTOS.pop(token, None)


PHOTO_EXTS = ("jpg", "jpeg", "png", "webp")


def validate_photo_upload(filename: str, content: bytes) -> str | None:
    """副檔名／單張大小驗證（S4.6）；回傳人話錯誤，通過回 None。HTML 表單與 JSON
    `/api/intake/photos` 共用同一支，不各自寫一份。"""
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if ext not in PHOTO_EXTS:
        return f"「{filename}」不是支援的圖片格式，請用 .jpg、.png 或 .webp。"
    if round(len(content) / (1024 * 1024), 1) > 10:
        return f"「{filename}」超過 10 MB，請換一張小一點的照片。"
    return None


def save_new_photo(filename: str, content: bytes, *, org_id: str) -> dict:
    """新 API 專用：單檔上傳各自拿一個 token（跟舊表單「一批共用一個 token」語意不同，
    對應前端 `IntakePhoto{token,name,size_mb}`），底層仍是同一套 `save_photo` 存檔邏輯。"""
    token = new_photo_token()
    entry = save_photo(token, filename, content, org_id=org_id)
    return {"token": token, "name": entry["name"], "size_mb": entry["size_mb"]}


def resolve_photo_tokens(tokens: list) -> list:
    """把新 API 送來的 token 清單換成已上傳的照片；用完即從暫存區丟掉（草稿已經接手）。"""
    photos = []
    for token in tokens:
        pending = get_pending_photos(token)
        if pending:
            photos.append({**pending[0], "token": token})
        discard_pending_photos(token)
    return photos


# ---------------------------------------------------------------------------
# 花費（真實 token 成本：即時 SUM llm_task.cost，不存副本）
# ---------------------------------------------------------------------------

def would_exceed(draft: dict, amount: float) -> bool:
    """R3／W12：呼叫送出之前先判斷「已花費 + 本次預估 > 上限」。"""
    return draft["cost_spent"] + amount > draft["budget_limit"]


def require_draft(brand_id: str, conn=None) -> dict:
    """草稿不存在就丟 404（票 B3-intake：HTML／JSON 兩套路由共用同一個唯一入口）。"""
    draft = get_draft(brand_id, conn)
    if draft is None:
        import app.shared.web as main_mod
        raise main_mod.NotFoundKind("建檔進度")
    return draft


def require_draft_or_just_completed(brand_id: str, conn=None) -> dict:
    """給待處理清單三支 JSON 端點用：解決最後一筆待處理項會在同一個請求裡把草稿標成
    completed（S4.65），前端緊接著會再打一次 GET /review 確認「還有沒有剩」——這時草稿
    已經不是 active，`require_draft` 會 404，前端就顯示不出「導回品牌頁」的完成訊息
    （票 B3 第三段實測抓到）。退回去找「最近一筆 completed」草稿，讓這個回合的收尾讀取
    照樣拿得到（值域仍是空清單），不影響 scan／question／paste 等仍需要 active 草稿的端點。"""
    draft = get_draft(brand_id, conn)
    if draft is not None:
        return draft
    row = ir.get_latest_completed_draft(_conn(conn), brand_id)
    if row is not None:
        return _row_to_draft(_conn(conn), row)
    import app.shared.web as main_mod
    raise main_mod.NotFoundKind("建檔進度")


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
                    llm_task_id: str | None, aspect: str | None = None) -> None:
    entries = _qa_entries(draft["qa"])
    options = [{"key": "suggested", "label": suggested.get("label") or "",
                "note": suggested.get("desc") or ""}]
    for i, b in enumerate(branches):
        options.append({"key": f"branch_{i}", "label": b.get("label") or "",
                        "note": b.get("desc") or ""})
    draft["qa"].append({
        "no": len(entries) + 1, "aspect": aspect, "question": question, "options": options,
        "suggested_key": "suggested", "answer_key": None, "answer_text": None,
        "skipped": False, "llm_task_id": llm_task_id,
    })


def mark_qa_done(draft: dict) -> None:
    if not draft["qa_done"]:
        draft["qa"].append({"done": True})
        draft["qa_done"] = True


def current_entry(draft: dict) -> dict | None:
    return next((e for e in _qa_entries(draft["qa"])
                 if not e.get("answer_key") and not e.get("skipped")), None)


def question_count(draft: dict) -> int:
    return len(_qa_entries(draft["qa"]))


def question_options(q: dict) -> list:
    """目前這題的可選項清單 [(key,label)]（HTML 表單下拉／JSON 驗證共用，S4.27）。"""
    return ([("suggested", q["suggested"]["label"])]
            + [(f"branch_{i}", b["label"]) for i, b in enumerate(q["branches"])]
            + [("other", "以上都不是，我自己說")])


