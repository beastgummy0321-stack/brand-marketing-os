# -*- coding: utf-8 -*-
"""app/intake/routes.py — 建檔精靈 12 個頁面的路由（DESIGN.md §19）。

本輪已接真實資料庫與 LLM 窗口：
- 草稿存 intake_draft／intake_item（app/intake/repository.py），重啟伺服器可續接。
- 初掃、下一題、貼回格式修復經 app/llm/gateway 真實呼叫（app/intake/ai.py）；
  無金鑰時顯示人話錯誤與「前往設定頁」引導，不當機。
- 花費列與 W12 超限攔截：已花費即時 SUM llm_task.cost（真實 token 成本）；
  「下一步預估」仍用 script.COST_* 的預估值在呼叫送出之前攔（R3）。
- 進度頁流程：第一次 GET 先渲染進度頁（meta refresh 導向 ?run=1），?run=1 那一次
  同步執行真實呼叫（sync def 路由，FastAPI 丟 threadpool，不卡 event loop），
  跑完轉址到結果頁。中途重啟：結果還沒落地，回到進度頁重跑即可，不需要另存等待狀態。

本檔對共用 web 工具的依賴一律透過 `import app.shared.web as main_mod` 動態取用其屬性
（修憲落地 A4：原本 import app.main，會跟 main.py 兜成循環；現在單向依賴
app.shared.web），原因：1) 避免循環匯入；2) main_mod.conn 在測試會被
reopen_connection() 換掉。
"""

from typing import List, Optional
from urllib.parse import quote_plus

from fastapi import APIRouter, File, Form, Request, UploadFile
from fastapi.responses import FileResponse, RedirectResponse

import app.shared.web as main_mod
from app.brand_intelligence import repository as repo
from app.intake import ai, paste_parse, script, state
from app.intake import repository as ir

router = APIRouter()

_KINDS = ("scan", "question", "paste")

# 呼叫送出之前的「下一步預估」（W12 攔截用）；實際花費以 llm_task.cost 為準。
_ESTIMATE = {"scan": script.COST_SCAN, "question": script.COST_QUESTION,
             "paste": script.COST_PASTE_FIX}


def _draft_or_404(brand_id: str) -> dict:
    draft = state.get_draft(brand_id)
    if draft is None:
        raise main_mod.NotFoundKind("建檔進度")
    return draft


def _crumb(brand: dict, label: str) -> list:
    return [("品牌總覽", "/"), (brand["name"], f"/brands/{brand['id']}"), (label, None)]


def _result_url(kind: str, brand_id: str) -> str:
    return f"/brands/{brand_id}/intake/{kind}"


_PROGRESS_STEP = {"scan": 2, "question": 3, "paste": 5}
_PROGRESS_TITLE = {
    "scan": "正在讀你給的資料",
    "question": "正在準備下一題",
    "paste": "正在請 AI 整理格式",
}
_PROGRESS_CRUMB = {
    "scan": "建立品牌・初掃",
    "question": "建立品牌・引導問答",
    "paste": "貼回・請 AI 整理格式",
}
_PROGRESS_WAIT_HINT = {
    "scan": "通常要 20 到 40 秒。",
    "question": "通常要 10 到 20 秒。",
    "paste": "通常要 10 到 20 秒。",
}


def _progress_rows(kind: str, draft: dict) -> list:
    if kind == "scan":
        n = len(draft["urls"])
        url_text = f"共 {n} 個網址" if n else "沒有提供網址，直接整理描述"
        rows = [("讀取網址", url_text), ("整理初步印象", "進行中"), ("準備第一題", "還沒開始")]
    elif kind == "question":
        rows = [("整理你剛才的回答", "完成"), ("想下一題怎麼問", "進行中"), ("更新累計花費", "還沒開始")]
    else:
        rows = [("重新讀一次你貼的內容", "完成"), ("依格式規則重新整理", "進行中"), ("再檢查一次格式", "還沒開始")]
    return [(label, value, False) for label, value in rows]


def _known_products(brand_id: str) -> set:
    return {p["name"] for p in repo.list_products(main_mod.conn, brand_id)}


def _existing_data(brand_id: str) -> dict:
    """已確認的品牌資料摘要（交接包「不用重查」區塊＋貼回重複提示共用，issue #1）。"""
    conn = main_mod.conn
    from app import mock_data as md
    brand_facts = [(f["label"], f["value"])
                   for f in repo.list_brand_facts(conn, brand_id, status="confirmed")]
    product_facts = []
    for p in repo.list_products(conn, brand_id):
        for f in repo.list_product_facts(conn, brand_id, p["id"], status="confirmed"):
            product_facts.append((p["name"], f["label"], f["value"]))
    rules = [r["content"] for r in repo.list_rules_for_brand(conn, brand_id)]
    claims = [(md.claim_type_label(c["claim_type"]), c["claim_text"])
              for c in repo.list_claims_for_brand(conn, brand_id)]
    return {"brand_facts": brand_facts, "product_facts": product_facts,
            "rules": rules, "claims": claims}


def _normalize(text: str) -> str:
    return "".join(ch for ch in (text or "") if ch.isalnum()).lower()


def _duplicate_hints(brand_id: str, items: list) -> dict:
    """待辦列 → 可能重複的既有資料提示 {item_id: 既有內容一句話}。

    正規化後「完全相同」或「一方包含另一方（≥6 字）」就標記；只提醒、不阻擋（決策 0013）。"""
    existing = []
    data = _existing_data(brand_id)
    for label, value in data["brand_facts"]:
        existing.append((label, f"品牌事實「{label}」"))
    for product, label, value in data["product_facts"]:
        existing.append((label, f"產品事實（{product}）「{label}」"))
    for content in data["rules"]:
        title = content.split("：", 1)[0]
        existing.append((title, f"限制規則「{title}」"))
    for type_label, text in data["claims"]:
        existing.append((text, f"宣稱（{type_label}）「{text}」"))
    norm_existing = [(_normalize(t), desc) for t, desc in existing if len(_normalize(t)) >= 4]
    hints = {}
    for it in items:
        key = _normalize(it["title"])
        if len(key) < 4:
            continue
        for norm, desc in norm_existing:
            same = key == norm
            contains = len(key) >= 6 and len(norm) >= 6 and (key in norm or norm in key)
            if same or contains:
                hints[it["id"]] = desc
                break
    return hints


def _category_labels(kind_human: str) -> list:
    return [label for _, label in paste_parse.KIND_CATEGORY_SOURCE[kind_human]]


def _kind_done(draft: dict, kind: str) -> bool:
    """這一種 AI 工作是否已有結果（有結果就不重跑，進度頁直接轉到結果頁）。"""
    if kind == "scan":
        return draft["scan_done"]
    if kind == "question":
        return (draft["current_q"] is not None or draft["qa_done"]
                or state.question_count(draft) >= script.MAX_QUESTIONS)
    return False  # 整理格式不限次數（issue #1）：每次明確要求都真的執行


def _rewrite_scope(raw_text: str, name: str, new_scope: str) -> str:
    """把貼回文字裡「適用範圍＝name」的資料列改寫成 new_scope（歸到整個品牌用）。
    直接改在文字上，之後不論重驗幾次都不會忘記這個決定。"""
    out = []
    for line in raw_text.splitlines():
        parts = [p.strip() for p in line.split("|")]
        if len(parts) == 6 and parts[4] == name and parts != paste_parse.HEADER_COLUMNS:
            parts[4] = new_scope
            out.append(" | ".join(parts))
        else:
            out.append(line)
    return "\n".join(out)


def _apply_paste(draft: dict, raw_text: str) -> Optional[int]:
    """驗證＋（全過才）整批落地 intake_item。回傳落地筆數；驗證失敗回 None（錯誤已寫進草稿）。"""
    conn = main_mod.conn
    # 換行被剪貼簿吃掉的表格先重組，存重組後的版本——使用者在畫面上看到的就是系統讀懂的樣子
    raw_text = paste_parse.maybe_reflow(raw_text)
    draft["paste_raw"] = raw_text
    rows, errors = paste_parse.parse_paste(raw_text, _known_products(draft["brand_id"]),
                                           brand_name=draft["brand_name"])
    draft["paste_errors"] = errors
    state.save(draft)
    if rows is None:
        # 與 Mock 時代行為一致：重貼失敗就清掉上一次還沒處理的待辦列（已處理的留著追溯）
        conn.execute(
            "DELETE FROM intake_item WHERE intake_draft_id = ? AND brand_id = ? AND outcome = 'pending'",
            (draft["id"], draft["brand_id"]),
        )
        conn.commit()
        return None
    items = ir.create_items(conn, draft["brand_id"], draft["id"], rows)
    return len(items)


# ---------------------------------------------------------------------------
# W1 — 起始輸入
# ---------------------------------------------------------------------------

@router.get("/brands/intake/new")
async def intake_new_get(request: Request):
    values = {"name": "", "client_name": "", "description": "", "urls": ["", "", "", "", ""], "photos": [],
              "photo_token": state.new_photo_token()}
    return main_mod.templates.TemplateResponse(request, "intake/new.html", main_mod.ctx(
        request, brand=None, nav_current='hub', values=values, errors={},
    ))


@router.post("/brands/intake/new")
async def intake_new_post(request: Request, name: str = Form(""), client_name: str = Form(""),
                           description: str = Form(""),
                           url_1: str = Form(""), url_2: str = Form(""), url_3: str = Form(""),
                           url_4: str = Form(""), url_5: str = Form(""),
                           photo_token: str = Form(""),
                           photos: List[UploadFile] = File(default=[])):
    actor = main_mod.require_actor(request)
    url_inputs = [url_1, url_2, url_3, url_4, url_5]

    # 照片真的存檔（不是只算檔名/大小就丟掉位元組）。驗證失敗還沒有品牌可掛，先用
    # photo_token 這個暫存識別碼；同一個 token 重送時，新選的檔案疊加在已存的上面。
    token = main_mod.clean(photo_token) or state.new_photo_token()
    photo_error = None
    for p in photos:
        if not p.filename:
            continue
        content = await p.read()
        size_mb = round(len(content) / (1024 * 1024), 1)
        ext = p.filename.rsplit(".", 1)[-1].lower() if "." in p.filename else ""
        if ext not in ("jpg", "jpeg", "png", "webp"):
            photo_error = f"「{p.filename}」不是支援的圖片格式，請用 .jpg、.png 或 .webp。"
            continue
        if size_mb > 10:
            photo_error = f"「{p.filename}」超過 10 MB，請換一張小一點的照片。"
            continue
        state.save_photo(token, p.filename, content)
    photo_list = state.get_pending_photos(token)

    values = {"name": name, "client_name": client_name, "description": description,
              "urls": url_inputs, "photos": photo_list, "photo_token": token}
    errors = {}
    name_c = main_mod.clean(name)
    if not name_c:
        errors["name"] = "請填寫品牌名稱。"
    if not photo_list:
        errors["photos"] = "請至少放一張產品照。之後要請外部 AI 看照片，沒有照片它只能用猜的。"
    elif photo_error:
        errors["photos"] = photo_error
    if not main_mod.clean(description):
        errors["description"] = "請用幾句話描述這個品牌或產品。"
    url_clean = []
    for idx, raw in enumerate(url_inputs, start=1):
        u = main_mod.clean(raw)
        if not u:
            continue
        if not (u.startswith("http://") or u.startswith("https://")):
            errors[f"url_{idx}"] = "這個網址看起來不完整，記得從 https:// 開始，例如「https://example.com/about」。"
            continue
        url_clean.append(u)

    if errors:
        return main_mod.templates.TemplateResponse(request, "intake/new.html", main_mod.ctx(
            request, brand=None, nav_current='hub', values=values, errors=errors,
        ), status_code=400)

    brand = repo.create_brand(main_mod.conn, name=name_c, client_name=main_mod.clean(client_name) or None,
                               actor=actor)
    state.new_draft(brand["id"], name_c, description=main_mod.clean(description), urls=url_clean,
                     photos=photo_list, actor=actor)
    state.discard_pending_photos(token)
    return RedirectResponse(f"/brands/{brand['id']}/intake/scan/progress", status_code=303)


# ---------------------------------------------------------------------------
# W1b — 重新調研（對既有品牌開新一輪草稿，issue #1）
# ---------------------------------------------------------------------------

def _prev_photos(last_draft_row: Optional[dict]) -> list:
    """上一輪草稿的照片（photos_json 形狀 → 畫面／new_draft 慣用形狀）。"""
    import json as _json
    if not last_draft_row:
        return []
    return [
        {"name": p.get("display_name"), "path": p.get("file_path"),
         "size_mb": round((p.get("size_bytes") or 0) / (1024 * 1024), 1)}
        for p in _json.loads(last_draft_row["photos_json"] or "[]")
    ]


def _restart_values(brand_id: str, token: str) -> dict:
    import json as _json
    last = ir.get_latest_completed_draft(main_mod.conn, brand_id)
    urls = _json.loads(last["research_urls_json"] or "[]") if last else []
    urls = (urls + ["", "", "", "", ""])[:5]
    return {"name": "", "client_name": "", "description": (last["description"] if last else "") or "",
            "urls": urls, "photos": _prev_photos(last), "photo_token": token}


@router.get("/brands/{brand_id}/intake/restart")
async def intake_restart_get(request: Request, brand_id: str):
    brand = main_mod.require_brand(brand_id)
    if state.get_draft(brand_id):
        # 已有進行中草稿：不開平行的第二輪，回品牌頁走續接
        return RedirectResponse(f"/brands/{brand_id}", status_code=303)
    values = _restart_values(brand_id, state.new_photo_token())
    return main_mod.templates.TemplateResponse(request, "intake/new.html", main_mod.ctx(
        request, brand=brand, nav_current='hub', restart_brand=brand, values=values, errors={},
    ))


@router.post("/brands/{brand_id}/intake/restart")
async def intake_restart_post(request: Request, brand_id: str, description: str = Form(""),
                               url_1: str = Form(""), url_2: str = Form(""), url_3: str = Form(""),
                               url_4: str = Form(""), url_5: str = Form(""),
                               photo_token: str = Form(""),
                               photos: List[UploadFile] = File(default=[])):
    actor = main_mod.require_actor(request)
    brand = main_mod.require_brand(brand_id)
    if state.get_draft(brand_id):
        return RedirectResponse(f"/brands/{brand_id}", status_code=303)
    url_inputs = [url_1, url_2, url_3, url_4, url_5]

    token = main_mod.clean(photo_token) or state.new_photo_token()
    photo_error = None
    for p in photos:
        if not p.filename:
            continue
        content = await p.read()
        size_mb = round(len(content) / (1024 * 1024), 1)
        ext = p.filename.rsplit(".", 1)[-1].lower() if "." in p.filename else ""
        if ext not in ("jpg", "jpeg", "png", "webp"):
            photo_error = f"「{p.filename}」不是支援的圖片格式，請用 .jpg、.png 或 .webp。"
            continue
        if size_mb > 10:
            photo_error = f"「{p.filename}」超過 10 MB，請換一張小一點的照片。"
            continue
        state.save_photo(token, p.filename, content)

    carried = _prev_photos(ir.get_latest_completed_draft(main_mod.conn, brand_id))
    photo_list = carried + state.get_pending_photos(token)

    values = {"name": "", "client_name": "", "description": description,
              "urls": url_inputs, "photos": photo_list, "photo_token": token}
    errors = {}
    if not photo_list:
        errors["photos"] = "請至少放一張產品照。之後要請外部 AI 看照片，沒有照片它只能用猜的。"
    elif photo_error:
        errors["photos"] = photo_error
    if not main_mod.clean(description):
        errors["description"] = "請用幾句話描述這個品牌或產品。"
    url_clean = []
    for idx, raw in enumerate(url_inputs, start=1):
        u = main_mod.clean(raw)
        if not u:
            continue
        if not (u.startswith("http://") or u.startswith("https://")):
            errors[f"url_{idx}"] = "這個網址看起來不完整，記得從 https:// 開始，例如「https://example.com/about」。"
            continue
        url_clean.append(u)

    if errors:
        return main_mod.templates.TemplateResponse(request, "intake/new.html", main_mod.ctx(
            request, brand=brand, nav_current='hub', restart_brand=brand, values=values, errors=errors,
        ), status_code=400)

    state.new_draft(brand_id, brand["name"], description=main_mod.clean(description),
                     urls=url_clean, photos=photo_list, actor=actor)
    state.discard_pending_photos(token)
    return RedirectResponse(f"/brands/{brand_id}/intake/scan/progress", status_code=303)


# ---------------------------------------------------------------------------
# 產品照檔案（W1 上傳、W5 產品照提醒區「開啟這張照片」共用）
# ---------------------------------------------------------------------------

_PHOTO_CONTENT_TYPES = {"jpg": "image/jpeg", "jpeg": "image/jpeg", "png": "image/png", "webp": "image/webp"}


def _photo_content_type(name: str) -> str:
    ext = name.rsplit(".", 1)[-1].lower() if "." in name else ""
    return _PHOTO_CONTENT_TYPES.get(ext, "application/octet-stream")


@router.get("/brands/{brand_id}/intake/photos/{filename}")
async def intake_photo(request: Request, brand_id: str, filename: str):
    """只回傳「這個品牌目前草稿的 photos 清單裡登記過」的檔案——不從網址參數直接組路徑，
    天生擋掉路徑穿越；找不到品牌、沒有草稿、或這個檔名不屬於這份草稿，一律 404。"""
    main_mod.require_brand(brand_id)
    draft = _draft_or_404(brand_id)
    entry = next((p for p in (draft.get("photos") or []) if p.get("name") == filename), None)
    if entry is None or not entry.get("path"):
        raise main_mod.NotFoundKind("這張照片")
    return FileResponse(entry["path"], media_type=_photo_content_type(entry["name"]), filename=entry["name"])


# ---------------------------------------------------------------------------
# W2 — 等待 AI 的進度頁（初掃／問答／貼回修復共用）
#
# 第一次 GET：渲染進度頁，meta refresh 導向 ?run=1。
# ?run=1 那一次：同步執行真實呼叫（sync def → threadpool），跑完轉址到結果頁；
# 失敗轉址帶 ai_failed=1 與人話錯誤，結果頁顯示錯誤與「前往設定頁」引導。
# ---------------------------------------------------------------------------

def _paste_result_redirect(draft: dict) -> RedirectResponse:
    brand_id = draft["brand_id"]
    if draft["pending_item_count"]:
        return RedirectResponse(
            f"/brands/{brand_id}/intake/review?ok=1&n={draft['pending_item_count']}", status_code=303)
    return RedirectResponse(f"/brands/{brand_id}/intake/paste", status_code=303)


@router.get("/brands/{brand_id}/intake/{kind}/progress")
def intake_progress(request: Request, brand_id: str, kind: str, run: Optional[str] = None):
    if kind not in _KINDS:
        raise main_mod.NotFoundKind("頁面")
    brand = main_mod.require_brand(brand_id)
    draft = _draft_or_404(brand_id)
    result_url = _result_url(kind, brand_id)

    if kind == "paste" and not draft["paste_raw"]:
        return RedirectResponse(result_url, status_code=303)

    if _kind_done(draft, kind):
        if kind == "paste":
            return _paste_result_redirect(draft)
        return RedirectResponse(result_url, status_code=303)

    # R3／W12：呼叫送出之前先攔（已花費＝真實 token 成本、上限＝草稿的 cost_limit）
    est = _ESTIMATE[kind]
    if state.would_exceed(draft, est):
        return RedirectResponse(f"/brands/{brand_id}/intake/limit?kind={kind}", status_code=303)

    if run != "1":
        return main_mod.templates.TemplateResponse(request, "intake/progress.html", main_mod.ctx(
            request, brand=brand, nav_current='hub', draft=draft, kind=kind, title=_PROGRESS_TITLE[kind],
            wait_hint=_PROGRESS_WAIT_HINT[kind], crumb_label=_PROGRESS_CRUMB[kind],
            rows=_progress_rows(kind, draft), refresh=state.REFRESH_SECONDS,
            run_url=f"{request.url.path}?run=1", step=_PROGRESS_STEP[kind],
            breadcrumb_items=_crumb(brand, _PROGRESS_CRUMB[kind]),
        ))

    conn = main_mod.conn
    if kind == "scan":
        ok, err = ai.run_scan(conn, draft)
    elif kind == "question":
        ok, err = ai.run_next_question(conn, draft)
    else:
        ok, result = ai.run_paste_fix(conn, draft)
        if ok:
            _apply_paste(draft, result)
            draft = _draft_or_404(brand_id)  # 重新載入 pending_item_count
            return _paste_result_redirect(draft)
        err = result

    if not ok:
        return RedirectResponse(
            f"{result_url}?ai_failed=1&retry_cost={est}&err={quote_plus(err or '')}",
            status_code=303)
    return RedirectResponse(result_url, status_code=303)


@router.get("/brands/{brand_id}/intake/{kind}/skip")
async def intake_skip(request: Request, brand_id: str, kind: str):
    if kind not in _KINDS:
        raise main_mod.NotFoundKind("頁面")
    main_mod.require_brand(brand_id)
    draft = _draft_or_404(brand_id)
    if kind == "scan":
        draft["scan_done"] = True
        draft["scan_impressions"] = []
        draft["url_results"] = []
        state.save(draft)
    elif kind == "question":
        # 跳過「出下一題」＝不再問了，question 頁會顯示「沒有需要再問的問題了」
        state.mark_qa_done(draft)
        state.save(draft)
    return RedirectResponse(_result_url(kind, brand_id), status_code=303)


# ---------------------------------------------------------------------------
# W3 — 初掃結果
# ---------------------------------------------------------------------------

@router.get("/brands/{brand_id}/intake/scan")
async def scan_get(request: Request, brand_id: str,
                    ai_failed: Optional[str] = None, retry_cost: Optional[str] = None,
                    err: Optional[str] = None):
    brand = main_mod.require_brand(brand_id)
    draft = _draft_or_404(brand_id)
    if not draft["scan_done"] and not ai_failed:
        return RedirectResponse(f"/brands/{brand_id}/intake/scan/progress", status_code=303)
    state.touch(draft, f"/brands/{brand_id}/intake/scan", 2)
    created_n = request.query_params.get("created")
    return main_mod.templates.TemplateResponse(request, "intake/scan.html", main_mod.ctx(
        request, brand=brand, nav_current='hub', draft=draft, impressions=draft["scan_impressions"],
        url_results=draft["url_results"],
        suggested_products=draft["scan_products"], existing_products=_known_products(brand_id),
        created_n=created_n,
        ai_failed=bool(ai_failed), retry_cost=retry_cost, ai_error=err,
        breadcrumb_items=_crumb(brand, "建立品牌・初步印象"),
    ))


@router.post("/brands/{brand_id}/intake/scan/products")
async def scan_create_products(request: Request, brand_id: str):
    """初掃偵測到的產品名單一鍵建立（issue #1 後續：產品名單先於調研存在，
    交接包才能正確枚舉適用範圍——大賢生醫 20 產品情境的病因修正）。"""
    actor = main_mod.require_actor(request)
    main_mod.require_brand(brand_id)
    draft = _draft_or_404(brand_id)
    form = await request.form()
    names = [main_mod.clean(n) for n in form.getlist("product_names")]
    suggested = set(draft["scan_products"])
    known = _known_products(brand_id)
    created = 0
    for name in names:
        if name and name in suggested and name not in known:
            repo.create_product(main_mod.conn, brand_id, name=name, actor=actor)
            created += 1
    return RedirectResponse(f"/brands/{brand_id}/intake/scan?created={created}", status_code=303)


# ---------------------------------------------------------------------------
# W4 — 引導問答
# ---------------------------------------------------------------------------

def _question_options(q: dict) -> list:
    return ([("suggested", q["suggested"]["label"])]
            + [(f"branch_{i}", b["label"]) for i, b in enumerate(q["branches"])]
            + [("other", "以上都不是，我自己說")])


@router.get("/brands/{brand_id}/intake/question")
async def question_get(request: Request, brand_id: str, ai_failed: Optional[str] = None,
                        retry_cost: Optional[str] = None, err: Optional[str] = None):
    brand = main_mod.require_brand(brand_id)
    draft = _draft_or_404(brand_id)
    q = draft["current_q"]
    no_more = q is None and (draft["qa_done"] or state.question_count(draft) >= script.MAX_QUESTIONS)
    if q is None and not no_more and not ai_failed:
        # 還沒有可回答的題目：去進度頁請 AI 出（第一）題
        return RedirectResponse(f"/brands/{brand_id}/intake/question/progress", status_code=303)
    state.touch(draft, f"/brands/{brand_id}/intake/question", 3)
    return main_mod.templates.TemplateResponse(request, "intake/question.html", main_mod.ctx(
        request, brand=brand, nav_current='hub', draft=draft, no_more=no_more, q=q, q_index=draft["question_index"],
        total_hint=script.MAX_QUESTIONS, ai_failed=bool(ai_failed), retry_cost=retry_cost, ai_error=err,
        values={"choice": "suggested", "note": ""}, errors={},
        breadcrumb_items=_crumb(brand, "建立品牌・引導問答"),
    ))


@router.post("/brands/{brand_id}/intake/question")
async def question_post(request: Request, brand_id: str, action: str = Form("answer"),
                         choice: str = Form(""), note: str = Form("")):
    main_mod.require_actor(request)
    brand = main_mod.require_brand(brand_id)
    draft = _draft_or_404(brand_id)
    entry = state.current_entry(draft)
    q = draft["current_q"]
    if entry is None or q is None:
        return RedirectResponse(f"/brands/{brand_id}/intake/handoff", status_code=303)

    if action == "skip":
        entry["skipped"] = True
        state.save(draft)
        return RedirectResponse(f"/brands/{brand_id}/intake/question/progress", status_code=303)

    choice_map = dict(_question_options(q))
    errors = {}
    if choice not in choice_map:
        errors["choice"] = "請選一個選項。"
    elif choice == "other" and not main_mod.clean(note):
        errors["note"] = "你選了「我自己說」，請在補充欄寫一句你的想法。"

    if errors:
        return main_mod.templates.TemplateResponse(request, "intake/question.html", main_mod.ctx(
            request, brand=brand, nav_current='hub', draft=draft, no_more=False, q=q, q_index=draft["question_index"],
            total_hint=script.MAX_QUESTIONS, ai_failed=False, retry_cost=None, ai_error=None,
            values={"choice": choice, "note": note}, errors=errors,
            breadcrumb_items=_crumb(brand, "建立品牌・引導問答"),
        ), status_code=400)

    entry["answer_key"] = choice
    entry["answer_text"] = main_mod.clean(note)
    state.save(draft)
    return RedirectResponse(f"/brands/{brand_id}/intake/question/progress", status_code=303)


# ---------------------------------------------------------------------------
# W5 — 交接包 ／ W6・W7 操作卡
# ---------------------------------------------------------------------------

@router.get("/brands/{brand_id}/intake/handoff")
async def handoff_get(request: Request, brand_id: str):
    brand = main_mod.require_brand(brand_id)
    draft = _draft_or_404(brand_id)
    state.touch(draft, f"/brands/{brand_id}/intake/handoff", 4)
    # 交接包全文用「產生當下存起來的那一份」（03 §3A.2：追溯要對得起來，不每次重組）
    prompt_text = draft["handoff_prompt"] if draft["handoff_generated"] else None
    return main_mod.templates.TemplateResponse(request, "intake/handoff.html", main_mod.ctx(
        request, brand=brand, nav_current='hub', draft=draft, prompt_text=prompt_text,
        depth_options=script.DEPTH_OPTIONS, errors={},
        values={"depth": draft["handoff_depth"] or "standard"},
        no_products=(len(_known_products(brand_id)) == 0),
        breadcrumb_items=_crumb(brand, "建立品牌・交接包"),
    ))


@router.post("/brands/{brand_id}/intake/handoff")
async def handoff_post(request: Request, brand_id: str, depth: str = Form("standard")):
    main_mod.require_actor(request)
    brand = main_mod.require_brand(brand_id)
    draft = _draft_or_404(brand_id)
    if depth not in ("standard", "deep"):
        return main_mod.templates.TemplateResponse(request, "intake/handoff.html", main_mod.ctx(
            request, brand=brand, nav_current='hub', draft=draft, prompt_text=None, depth_options=script.DEPTH_OPTIONS,
            errors={"depth": "請選擇要跑多深。"}, values={"depth": depth},
            breadcrumb_items=_crumb(brand, "建立品牌・交接包"),
        ), status_code=400)
    prompt_text = script.build_prompt(draft, depth, known_products=sorted(_known_products(brand_id)),
                                       existing=_existing_data(brand_id))
    from app.core import db as coredb
    ir.update_draft(main_mod.conn, brand_id, draft["id"], handoff_depth=depth,
                    handoff_prompt=prompt_text, handoff_generated_at=coredb.now_iso())
    return RedirectResponse(f"/brands/{brand_id}/intake/handoff", status_code=303)


@router.get("/brands/{brand_id}/intake/handoff/{provider}")
async def operator_card(request: Request, brand_id: str, provider: str):
    if provider not in ("claude", "chatgpt"):
        raise main_mod.NotFoundKind("頁面")
    brand = main_mod.require_brand(brand_id)
    draft = _draft_or_404(brand_id)
    state.touch(draft, f"/brands/{brand_id}/intake/handoff/{provider}", 4)
    card = script.card_for(provider, draft["handoff_depth"] or "standard")
    label = "Claude 操作卡" if provider == "claude" else "ChatGPT 操作卡"
    return main_mod.templates.TemplateResponse(request, "intake/operator_card.html", main_mod.ctx(
        request, brand=brand, nav_current='hub', draft=draft, provider=provider, card=card,
        fallback_note=script.CARD_FALLBACK_NOTE,
        breadcrumb_items=[("品牌總覽", "/"), (brand["name"], f"/brands/{brand_id}"),
                           ("交接包", f"/brands/{brand_id}/intake/handoff"), (label, None)],
    ))


# ---------------------------------------------------------------------------
# W8 — 貼回
# ---------------------------------------------------------------------------

_PASTE_SAMPLES = {
    "sample": script.PASTE_SAMPLE_SUCCESS,
    "sample_errors": script.PASTE_SAMPLE_ERRORS,
    "sample_fixed": script.PASTE_SAMPLE_FIXED,
    "sample_unfixable": script.PASTE_SAMPLE_UNFIXABLE,
}


@router.get("/brands/{brand_id}/intake/paste")
async def paste_get(request: Request, brand_id: str, mock: Optional[str] = None,
                     ai_failed: Optional[str] = None, retry_cost: Optional[str] = None,
                     err: Optional[str] = None):
    brand = main_mod.require_brand(brand_id)
    draft = _draft_or_404(brand_id)
    state.touch(draft, f"/brands/{brand_id}/intake/paste", 5)
    raw_value = draft["paste_raw"] or _PASTE_SAMPLES.get(mock, "")
    total_lines = paste_parse.count_data_lines(draft["paste_raw"]) if draft["paste_raw"] else 0
    # 不認得的適用範圍名字，聚合成「建立成新產品／歸到整個品牌」的解決區塊（每個名字一組）
    unknown_scopes = {}
    for e in draft["paste_errors"] or []:
        name = e.get("unknown_scope")
        if name:
            unknown_scopes[name] = unknown_scopes.get(name, 0) + 1
    return main_mod.templates.TemplateResponse(request, "intake/paste.html", main_mod.ctx(
        request, brand=brand, nav_current='hub', draft=draft, raw_value=raw_value, errors=draft["paste_errors"],
        total_lines=total_lines, fix_used=draft["paste_fix_used"],
        unknown_scopes=unknown_scopes,
        ai_failed=bool(ai_failed), retry_cost=retry_cost, ai_error=err,
        breadcrumb_items=_crumb(brand, "貼回"),
    ))


@router.post("/brands/{brand_id}/intake/paste")
async def paste_post(request: Request, brand_id: str, action: str = Form("validate"),
                      raw_text: str = Form(""),
                      upload: Optional[UploadFile] = File(default=None)):
    main_mod.require_actor(request)
    main_mod.require_brand(brand_id)
    draft = _draft_or_404(brand_id)

    # 上傳 .md／.txt 檔（外部 AI 匯出的原始檔），完全繞過剪貼簿的換行問題；有檔案就以檔案為準
    if upload is not None and upload.filename:
        ext = upload.filename.rsplit(".", 1)[-1].lower() if "." in upload.filename else ""
        if ext not in ("md", "txt"):
            draft["paste_errors"] = [{"line": None,
                                      "msg": f"「{upload.filename}」不是支援的檔案格式，請上傳 .md 或 .txt 檔。"}]
            state.save(draft)
            return RedirectResponse(f"/brands/{brand_id}/intake/paste", status_code=303)
        raw_text = (await upload.read()).decode("utf-8", errors="replace")

    if action == "fix":
        # 決策 0013／issue #1：整理格式不限次數——每次照樣計費、照樣受 W12 攔截
        return RedirectResponse(f"/brands/{brand_id}/intake/paste/progress", status_code=303)

    if action == "resolve_scope":
        # 貼回頁「不認得的適用範圍」兩個出口：建立成新產品／這些列歸到整個品牌。
        # 都用草稿裡存的 paste_raw 重新驗證——一次解一個名字，還有別的未知名字就會再顯示。
        form = await request.form()
        scope_name = (form.get("scope_name") or "").strip()
        resolve_as = form.get("resolve_as")
        if not scope_name or not draft["paste_raw"]:
            return RedirectResponse(f"/brands/{brand_id}/intake/paste", status_code=303)
        raw = draft["paste_raw"]
        if resolve_as == "create":
            actor = main_mod.require_actor(request)
            if scope_name not in _known_products(brand_id):
                repo.create_product(main_mod.conn, brand_id, name=scope_name, actor=actor)
        else:
            raw = _rewrite_scope(raw, scope_name, "整個品牌")
        n = _apply_paste(draft, raw)
        if n is None:
            return RedirectResponse(f"/brands/{brand_id}/intake/paste", status_code=303)
        return RedirectResponse(f"/brands/{brand_id}/intake/review?ok=1&n={n}", status_code=303)

    if not raw_text.strip():
        draft["paste_raw"] = raw_text
        draft["paste_errors"] = [{"line": None, "msg": "請先貼上 AI 給你的表格內容。"}]
        state.save(draft)
        return RedirectResponse(f"/brands/{brand_id}/intake/paste", status_code=303)

    n = _apply_paste(draft, raw_text)
    if n is None:
        return RedirectResponse(f"/brands/{brand_id}/intake/paste", status_code=303)
    return RedirectResponse(f"/brands/{brand_id}/intake/review?ok=1&n={n}", status_code=303)


# ---------------------------------------------------------------------------
# W9 — AI 帶回的內容 ／ W10 — 逐條處理
# ---------------------------------------------------------------------------

@router.get("/brands/{brand_id}/intake/review")
async def review_list(request: Request, brand_id: str, ok: Optional[str] = None, n: Optional[str] = None):
    brand = main_mod.require_brand(brand_id)
    draft = _draft_or_404(brand_id)
    counts = ir.count_items_by_outcome(main_mod.conn, brand_id, draft["id"])
    open_items = ir.list_pending_items(main_mod.conn, brand_id, draft["id"])
    if not open_items:
        return RedirectResponse(f"/brands/{brand_id}/intake/paste", status_code=303)
    state.touch(draft, f"/brands/{brand_id}/intake/review", 5)
    return main_mod.templates.TemplateResponse(request, "intake/review.html", main_mod.ctx(
        request, brand=brand, nav_current='hub', draft=draft, items=open_items, total=sum(counts.values()),
        just_pasted=(ok == "1"), pasted_count=n,
        dup_hints=_duplicate_hints(brand_id, open_items),
        breadcrumb_items=_crumb(brand, "AI 帶回的內容"),
    ))


@router.post("/brands/{brand_id}/intake/review/pending-all")
async def review_pending_all(request: Request, brand_id: str):
    """「剩餘全部先存成待確認」一鍵收工（issue #1）。逐筆走唯一入口、逐筆寫稽核；
    「確認」仍然只能逐條——這裡只把安全的待確認狀態批次化。"""
    actor = main_mod.require_actor(request)
    brand = main_mod.require_brand(brand_id)
    draft = _draft_or_404(brand_id)
    saved, skipped = 0, 0
    for it in ir.list_pending_items(main_mod.conn, brand_id, draft["id"]):
        try:
            ir.resolve_item(main_mod.conn, brand_id, it["id"], "pending_saved", processed_by=actor)
            saved += 1
        except ValueError:
            # 例如產品事實還沒指定產品——留在清單，之後逐條處理
            skipped += 1
    remaining = ir.list_pending_items(main_mod.conn, brand_id, draft["id"])
    if remaining:
        return main_mod.redirect_with_message(
            f"/brands/{brand_id}/intake/review",
            f"已把 {saved} 筆存成待確認；還有 {skipped} 筆需要逐條處理（例如產品事實要先指定產品）。")
    state.complete_draft(draft)
    return main_mod.redirect_with_message(
        f"/brands/{brand_id}",
        f"這次建檔完成：{saved} 筆先存成待確認，之後可在品牌檔案頁慢慢確認。")


def _open_item_or_404(brand_id: str, draft: dict, i: int) -> tuple:
    items = ir.list_pending_items(main_mod.conn, brand_id, draft["id"])
    item = next((it for it in items if it["i"] == i), None)
    if item is None:
        raise main_mod.NotFoundKind("這筆待處理內容")
    counts = ir.count_items_by_outcome(main_mod.conn, brand_id, draft["id"])
    return item, sum(counts.values())


def _review_item_ctx(request, brand, draft, item, total, values, errors):
    return main_mod.ctx(
        request, brand=brand, nav_current='hub', draft=draft, item=item, total=total,
        category_options=_category_labels(item["kind"]),
        scope_options=["整個品牌"] + sorted(_known_products(brand["id"])),
        dup_hint=_duplicate_hints(brand["id"], [item]).get(item["id"]),
        values=values, errors=errors,
        breadcrumb_items=_crumb(brand, f"第 {item['i']} 筆"),
    )


@router.get("/brands/{brand_id}/intake/review/{i}")
async def review_item_get(request: Request, brand_id: str, i: int):
    brand = main_mod.require_brand(brand_id)
    draft = _draft_or_404(brand_id)
    item, total = _open_item_or_404(brand_id, draft, i)
    values = {"title": item["title"], "content": item["content"], "category": item["category"],
              "scope": item["scope"], "new_product": "", "severity": "soft"}
    return main_mod.templates.TemplateResponse(
        request, "intake/review_item.html",
        _review_item_ctx(request, brand, draft, item, total, values, {}))


_OUTCOME_BY_ACTION = {"confirm": "confirmed", "pending": "pending_saved", "discard": "discarded"}


@router.post("/brands/{brand_id}/intake/review/{i}")
async def review_item_post(request: Request, brand_id: str, i: int, action: str = Form(""),
                            title: str = Form(""), content: str = Form(""),
                            category: str = Form(""), scope: str = Form(""),
                            new_product: str = Form(""), severity: str = Form("soft")):
    actor = main_mod.require_actor(request)
    brand = main_mod.require_brand(brand_id)
    draft = _draft_or_404(brand_id)
    item, total = _open_item_or_404(brand_id, draft, i)

    values = {"title": title, "content": content, "category": category,
              "scope": scope, "new_product": new_product, "severity": severity}
    errors = {}
    if action not in _OUTCOME_BY_ACTION:
        errors["action"] = "請選擇要怎麼處理這一筆。"

    # 捨棄不管欄位內容；確認／待確認才驗證編輯後的值（決策 0013：只驗必要的最少項）
    scope_c = main_mod.clean(scope)
    if action in ("confirm", "pending"):
        if not main_mod.clean(title):
            errors["title"] = "標題不能是空的。"
        if not main_mod.clean(content):
            errors["content"] = "內容不能是空的。"
        if category not in _category_labels(item["kind"]):
            errors["category"] = "請選擇分類。"
        if scope_c == "__new__":
            if not main_mod.clean(new_product):
                errors["new_product"] = "請填新產品的名稱。"
            else:
                scope_c = main_mod.clean(new_product)
        if item["kind"] == "產品事實" and scope_c == "整個品牌":
            errors["scope"] = "產品事實需要掛在一個產品下。選一個產品，或建立新產品。"

    if errors:
        return main_mod.templates.TemplateResponse(
            request, "intake/review_item.html",
            _review_item_ctx(request, brand, draft, item, total, values, errors),
            status_code=400)

    if scope_c and scope_c != "整個品牌" and scope_c not in _known_products(brand_id):
        repo.create_product(main_mod.conn, brand_id, name=scope_c, actor=actor)

    edits = None
    if action in ("confirm", "pending"):
        edits = {"title": main_mod.clean(title), "content": main_mod.clean(content),
                 "category": ir._category_to_internal(item["kind"], category),
                 "scope_raw": scope_c}
    ir.resolve_item(main_mod.conn, brand_id, item["id"], _OUTCOME_BY_ACTION[action],
                    processed_by=actor, edits=edits,
                    rule_severity=(severity if severity in ("hard", "soft") else "soft"))

    remaining = ir.list_pending_items(main_mod.conn, brand_id, draft["id"])
    if remaining:
        next_i = min(it["i"] for it in remaining)
        return RedirectResponse(f"/brands/{brand_id}/intake/review/{next_i}", status_code=303)

    all_items = ir.list_items(main_mod.conn, brand_id, draft["id"])
    landed = [it for it in all_items if it["landed"]]
    landed_pending = [it for it in landed if it["landed_pending"]]
    state.complete_draft(draft)
    msg = f"這次建檔完成，共有 {len(landed)} 筆進到「{brand['name']}」，其中 {len(landed_pending)} 筆是待確認。"
    return main_mod.redirect_with_message(f"/brands/{brand_id}", msg)


# ---------------------------------------------------------------------------
# W11 — 花費上限設定
# ---------------------------------------------------------------------------

def _num_str(v: float) -> str:
    return str(int(v)) if float(v).is_integer() else str(v)


@router.get("/brands/{brand_id}/intake/budget")
async def budget_get(request: Request, brand_id: str, next: str = ""):
    brand = main_mod.require_brand(brand_id)
    draft = _draft_or_404(brand_id)
    target = next or f"/brands/{brand_id}"
    return main_mod.templates.TemplateResponse(request, "intake/budget.html", main_mod.ctx(
        request, brand=brand, nav_current='hub', draft=draft, values={"limit": _num_str(draft["budget_limit"])}, errors={},
        next=target, breadcrumb_items=_crumb(brand, "花費上限設定"),
    ))


@router.post("/brands/{brand_id}/intake/budget")
async def budget_post(request: Request, brand_id: str, limit: str = Form(""), next: str = Form("")):
    main_mod.require_actor(request)
    brand = main_mod.require_brand(brand_id)
    draft = _draft_or_404(brand_id)
    target = next if next.startswith(f"/brands/{brand_id}") else f"/brands/{brand_id}"
    value, ok = main_mod.parse_number(limit)
    errors = {}
    if main_mod.clean(limit) == "":
        errors["limit"] = "請填寫上限金額。"
    elif not ok:
        errors["limit"] = "上限金額請填數字，例如 30。"
    elif value < draft["cost_spent"]:
        errors["limit"] = f"這次已經花了 US$ {draft['cost_spent']:.2f}，上限不能設得比它低。"
    if errors:
        return main_mod.templates.TemplateResponse(request, "intake/budget.html", main_mod.ctx(
            request, brand=brand, nav_current='hub', draft=draft, values={"limit": limit}, errors=errors, next=target,
            breadcrumb_items=_crumb(brand, "花費上限設定"),
        ), status_code=400)
    draft["budget_limit"] = round(value, 2)
    state.save(draft)
    return RedirectResponse(target, status_code=303)


# ---------------------------------------------------------------------------
# W12 — 超限攔截（無伺服器端等待狀態：被攔下的那一步以 ?kind= 帶著走）
# ---------------------------------------------------------------------------

@router.get("/brands/{brand_id}/intake/limit")
async def limit_get(request: Request, brand_id: str, kind: Optional[str] = None):
    brand = main_mod.require_brand(brand_id)
    draft = _draft_or_404(brand_id)
    if kind not in _KINDS:
        return RedirectResponse(f"/brands/{brand_id}", status_code=303)
    block = {"kind": kind, "amount": _ESTIMATE[kind]}
    suggested_limit = int(draft["budget_limit"]) + 30
    return main_mod.templates.TemplateResponse(request, "intake/limit.html", main_mod.ctx(
        request, brand=brand, nav_current='hub', draft=draft, block=block, suggested_limit=suggested_limit,
        breadcrumb_items=_crumb(brand, "已達花費上限"),
    ))


@router.post("/brands/{brand_id}/intake/limit/raise")
async def limit_raise(request: Request, brand_id: str, kind: str = Form("")):
    main_mod.require_actor(request)
    main_mod.require_brand(brand_id)
    draft = _draft_or_404(brand_id)
    if kind not in _KINDS:
        return RedirectResponse(f"/brands/{brand_id}", status_code=303)
    draft["budget_limit"] = round(draft["budget_limit"] + 30, 2)
    state.save(draft)
    return RedirectResponse(f"/brands/{brand_id}/intake/{kind}/progress", status_code=303)


@router.get("/brands/{brand_id}/intake/limit/skip-to-handoff")
async def limit_skip(request: Request, brand_id: str):
    main_mod.require_brand(brand_id)
    _draft_or_404(brand_id)
    return RedirectResponse(f"/brands/{brand_id}/intake/handoff", status_code=303)
