"""app/intake/routes_api.py — 建檔精靈 JSON API（票 B3-intake 第二段前半）。

契約：`.scratch/grill/GRILL-B3-intake.md`「要新增的 API」節前 16 支裡屬本檔負責的部分
（起始輸入／初掃／引導問答／花費上限／超限攔截；交接包／貼回／待處理清單留給下一段）。
形狀逐欄對照 `frontend/src/lib/intakeApi.ts`（前端實際打的路徑與回應形狀為準）。

`app/intake/routes.py` 已頂到技術債凍結的 951 行上限（依精靈五步分檔中，見
`docs/tech-debt.md`），新路由一律放這個新檔，不再往那份加。業務邏輯（S4.9 陽春路徑判斷、
照片驗證、問答選項、產品建立）已抽到 `app/intake/state.py`，HTML 表單路由與這裡的 JSON
路由共用同一份，不寫兩次（CLAUDE.md 第五節）。

背景工作（初掃／出下一題／貼回修格式）票 09 起搬上 `app.background` 佇列（範本
`app/brand_web/routes_products.py`），取代原本行程內工作狀態表＋背景執行緒；狀態端點讀
`llm_task`。逐步進度（初掃「正在看照片（第 N／M 張）」）票 09 明文放棄，running 回「處理中」。

對外進入點：本檔的 `router`（`app/main.py` 直接 `include_router`）。誰依賴它：只有
`app/main.py`。
"""

import re
from datetime import UTC, datetime

from fastapi import APIRouter, File, Request, UploadFile
from fastapi.responses import Response

from app.background import enqueue as background_enqueue
from app.background import is_active as background_is_active
from app.brand_intelligence import background_job
from app.brand_intelligence import repository as repo
from app.core.db import connection as core_db_connection
from app.core.db import new_id, now_iso, now_utc
from app.intake import ai, paste_parse, script, state
from app.intake import repository as ir
from app.shared import web
from app.shared.web import JSONResponse, NotFoundKind, clean, require_actor, require_brand

router = APIRouter()

REPORT_SECTION_TITLES = (
    "市場與品類",
    "競品拆解",
    "消費者洞察與評論探勘",
    "定價",
    "通路",
    "法規備忘",
    "綜整",
)
_REPORT_SECTION_HEADING = re.compile(
    r"(?m)^[\t #>*-]*(?:(?:[1-7]|[一二三四五六七])[、.．)）]\s*)?"
    + r"(?P<title>" + "|".join(re.escape(title) for title in REPORT_SECTION_TITLES) + r")"
    + r"(?=\s|[:：]|[（(]|$)",
)


def _error(status_code: int, message: str) -> JSONResponse:
    return JSONResponse({"error": message}, status_code=status_code)


def _envelope(data) -> dict:
    return {"data": data, "generated_at": datetime.now(UTC).isoformat()}


async def _json_body(request: Request) -> dict:
    try:
        body = await request.json()
    except Exception:
        return {}
    return body if isinstance(body, dict) else {}


# ---------------------------------------------------------------------------
# 起始輸入（S4.1-S4.13）
# ---------------------------------------------------------------------------

@router.post("/api/intake/photos")
async def photo_upload(request: Request, photo: UploadFile = File(...)):
    actor = require_actor(request)  # 這一步還沒有品牌（建檔精靈第一步），但組織一定有
    if not photo.filename:
        return _error(400, "請選擇檔案。")
    content = await photo.read()
    err = state.validate_photo_upload(photo.filename, content)
    if err:
        return _error(400, err)
    return state.save_new_photo(photo.filename, content, org_id=actor.org_id)


@router.post("/api/intake/brands")
async def brand_start(request: Request):
    actor = require_actor(request)
    form = await request.form()
    brand_name = clean(str(form.get("brand_name") or ""))
    if not brand_name:
        return _error(400, "請填寫品牌名稱。")
    description = clean(str(form.get("description") or ""))
    urls = [clean(str(u)) for u in form.getlist("urls") if clean(str(u))]
    bad = state.invalid_url(urls)
    if bad:
        return _error(400, f"「{bad}」不是有效的網址，請以 https:// 或 http:// 開頭。")
    photos = state.resolve_photo_tokens([str(t) for t in form.getlist("photo_tokens")])
    client_name = clean(str(form.get("client_name") or ""))
    brand = repo.create_brand(web.conn, org_id=actor.org_id, name=brand_name,
                               client_name=client_name or None, actor=str(actor.user_id))
    draft = state.start_or_quick(web.conn, brand["id"], brand_name, description=description,
                                 urls=urls, photos=photos, actor=str(actor.user_id))
    return {"brand_id": brand["id"], "quick": draft is None}


@router.post("/api/intake/brands/{brand_id}/restart")
async def brand_restart(request: Request, brand_id: str):
    actor = require_actor(request)
    brand = require_brand(brand_id, actor)
    if state.get_draft(brand_id):
        return {"quick": False, "already_running": True}  # S4.12：不開第二輪
    form = await request.form()
    description = clean(str(form.get("description") or ""))
    urls = [clean(str(u)) for u in form.getlist("urls") if clean(str(u))]
    bad = state.invalid_url(urls)
    if bad:
        return _error(400, f"「{bad}」不是有效的網址，請以 https:// 或 http:// 開頭。")
    new_photos = state.resolve_photo_tokens([str(t) for t in form.getlist("photo_tokens")])
    carried = state.prev_photos(ir.get_latest_completed_draft(web.conn, brand_id))
    photos = carried + new_photos
    draft = state.start_or_quick(web.conn, brand_id, brand["name"], description=description,
                                 urls=urls, photos=photos, actor=str(actor.user_id))
    return {"quick": draft is None}


def _is_restart(brand_id: str, draft: dict) -> bool:
    return state.is_restart_draft(brand_id, draft["id"], conn=web.conn)


def _draft_shape(brand_id: str, draft: dict) -> dict:
    photos = [{"token": p.get("token") or "", "name": p["name"], "size_mb": p["size_mb"]}
              for p in draft["photos"]]
    created_product_names = sorted(p["name"] for p in repo.list_products(web.conn, brand_id))
    return {
        "id": draft["id"], "brand_id": draft["brand_id"], "brand_name": draft["brand_name"],
        "step": draft["step"], "completed": draft.get("status") == "completed",
        "is_restart": _is_restart(brand_id, draft),
        "description": draft["description"], "urls": draft["urls"], "photos": photos,
        "scan_done": draft["scan_done"], "scan_impressions": draft["scan_impressions"],
        "scan_products": draft["scan_products"], "created_product_names": created_product_names,
        "product_card_drafts": draft.get("product_card_drafts") or [],
        "url_results": draft["url_results"],
        "qa_done": draft["qa_done"], "current_q": draft["current_q"], "answers": draft["answers"],
        "question_index": draft["question_index"],
        "handoff_depth": draft["handoff_depth"], "handoff_generated": draft["handoff_generated"],
        "handoff_prompt": draft["handoff_prompt"],
        "paste_raw": draft["paste_raw"], "paste_errors": draft["paste_errors"],
        "paste_fix_used": draft["paste_fix_used"],
        "pending_item_count": draft["pending_item_count"],
        "budget_limit": draft["budget_limit"], "cost_spent": draft["cost_spent"],
        "cost_items": draft["cost_items"],
    }


@router.get("/api/intake/brands/{brand_id}/draft")
def draft_get(request: Request, brand_id: str):
    """建檔精靈整包讀。收尾那一下（真相卡送出）會在同一個請求裡把草稿標成 completed，
    前端緊接著 refresh 這支——所以跟 review／truth-card 一樣退回去找剛完成的那份，
    不然完成畫面會變成 404「找不到建檔進度」（e2e-adflow finding 1）。"""
    actor = require_actor(request)
    require_brand(brand_id, actor)
    draft = state.require_draft_or_just_completed(brand_id)
    return _envelope(_draft_shape(brand_id, draft))


# ---------------------------------------------------------------------------
# 調研報告回顯（T2a 1.2-1.4）
# ---------------------------------------------------------------------------

def detect_report_sections(raw_text: str) -> tuple[str, list[dict]]:
    """依深度調研七章標題切出原文區段；每個字元都保留在前言或其中一章。"""
    matches = list(_REPORT_SECTION_HEADING.finditer(raw_text))
    if not matches:
        return raw_text, []
    sections = []
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(raw_text)
        sections.append({"title": match.group("title"), "raw_text": raw_text[match.start():end]})
    return raw_text[:matches[0].start()], sections


def _research_report_json(report: dict) -> dict:
    leading_text, sections = detect_report_sections(report["paste_raw"])
    return {**report, "leading_text": leading_text, "sections": sections}


@router.get("/api/intake/brands/{brand_id}/research-reports")
def research_report_list(request: Request, brand_id: str):
    actor = require_actor(request)
    require_brand(brand_id, actor)
    return _envelope(ir.list_research_reports(web.conn, brand_id))


@router.get("/api/intake/brands/{brand_id}/research-reports/{draft_id}")
def research_report_get(request: Request, brand_id: str, draft_id: str):
    actor = require_actor(request)
    require_brand(brand_id, actor)
    report = ir.get_research_report(web.conn, brand_id, draft_id)
    if report is None:
        raise NotFoundKind("調研報告")
    return _envelope(_research_report_json(report))


# ---------------------------------------------------------------------------
# 背景工作機制（初掃／出下一題／貼回修格式共用；票 09：搬上 app.background 佇列）
# ---------------------------------------------------------------------------

_USUAL_RANGE = {"scan": "20 到 40 秒", "question": "10 到 20 秒", "paste_fix": "10 到 20 秒"}
_STAGE_START = {"scan": "讀取網址中", "question": "正在準備下一題", "paste_fix": "正在請 AI 整理格式"}
_STAGE_RUNNING = {"scan": "處理中", "question": _STAGE_START["question"], "paste_fix": _STAGE_START["paste_fix"]}
_ESTIMATE = {"scan": script.COST_SCAN, "question": script.COST_QUESTION, "paste_fix": script.COST_PASTE_FIX}
_TASK_TYPE = {"scan": "intake_scan", "question": "intake_question", "paste_fix": "intake_paste_fix"}


def _idle_job() -> dict:
    return {"status": "done", "stage": "", "started_at": now_iso(), "usual_range_text": "", "error": None}


def _job(status: str, kind: str, started_at: str, error: str | None = None) -> dict:
    stage = {"running": _STAGE_RUNNING[kind], "done": "完成", "failed": _STAGE_START[kind]}[status]
    return {"status": status, "stage": stage, "started_at": started_at,
            "usual_range_text": _USUAL_RANGE[kind], "error": error}


def _latest_task_row(brand_id: str, kind: str) -> dict | None:
    row = web.conn.execute(
        "SELECT * FROM llm_task WHERE brand_id = %s AND task_type = %s "
        "ORDER BY started_at DESC LIMIT 1",
        (brand_id, _TASK_TYPE[kind]),
    ).fetchone()
    return dict(row) if row is not None else None


def _job_state(draft: dict, kind: str) -> dict:
    """讀 llm_task 取代讀行程內 dict；succeeded 列重驗（比照 `_research_state()`）。"""
    brand_id = draft["brand_id"]
    lock = f"intake_{kind}:{brand_id}"
    row = _latest_task_row(brand_id, kind)
    if row is None:
        return _job("running", kind, now_iso()) if background_is_active(lock) else _idle_job()
    started_at = row["started_at"].isoformat() if row["started_at"] else now_iso()
    if row["status"] == "running":
        return _job("running", kind, started_at)
    if row["status"] != "succeeded":
        return _job("failed", kind, started_at, row["error"] or "背景工作失敗，可以再試一次。")
    if kind == "scan":
        ok = ai.parse_scan_reply(row["rendered_output"]) is not None
        err = ai.PARSE_FAIL_MESSAGE
    elif kind == "question":
        ok, err = ai.validate_question_reply(row["structured_output_json"], ai.question_coverage(draft)[1])
    else:
        ok, err = True, None
    if not ok:
        return _job("failed", kind, started_at, err)
    if background_is_active(lock):
        return _job("running", kind, started_at)  # 主呼叫已成功，仍在做後續處理（例如讀照片）
    return _job("done", kind, started_at)


def _limit_block(draft: dict, kind: str) -> dict:
    return {"kind": kind, "amount": _ESTIMATE[kind], "cost_spent": draft["cost_spent"],
            "budget_limit": draft["budget_limit"], "suggested_limit": round(draft["budget_limit"] + 30, 2)}


def _notify_step_done(conn, brand_id: str, brand_name: str, ok: bool, *, verbs: tuple) -> None:
    background_job.notify(
        conn, brand_id, category="intake_ai_step_done", dedupe_key=new_id("itkjob"),
        message=f"「{brand_name}」{verbs[0] if ok else verbs[1]}", action_url=f"/app/brands/{brand_id}/intake",
    )


def background_intake_scan(org_id: str, brand_id: str) -> None:
    with core_db_connection() as conn:
        brand = repo.get_brand(conn, brand_id)
        brand_name = brand["name"] if brand else brand_id
        try:
            draft = state.require_draft(brand_id, conn=conn)
            ok, _err = ai.run_scan(conn, draft)
        except Exception:  # noqa: BLE001 — worker 最後一道防線，不能讓例外憑空消失
            ok = False
        _notify_step_done(conn, brand_id, brand_name, ok,
                          verbs=("初掃完成，可以回去看初步印象", "初掃失敗，可以回去重試"))


def background_intake_question(org_id: str, brand_id: str) -> None:
    with core_db_connection() as conn:
        try:
            draft = state.require_draft(brand_id, conn=conn)
            ai.run_next_question(conn, draft)  # 出下一題不進收件匣（GRILL 決策：洗版）
        except Exception:  # noqa: BLE001
            pass


def background_intake_paste_fix(org_id: str, brand_id: str) -> None:
    with core_db_connection() as conn:
        brand = repo.get_brand(conn, brand_id)
        brand_name = brand["name"] if brand else brand_id
        ok = False
        try:
            draft = state.require_draft(brand_id, conn=conn)
            ok, result = ai.run_paste_fix(conn, draft)
            if ok:
                # 修好的文字重新驗證：成功就併入步驟 5（AI 帶回的內容），失敗把修過的文字
                # 留在草稿讓使用者手改（S4.54）——這裡的 ok 只代表 AI 呼叫本身有沒有成功。
                n = state.apply_paste(draft, result, conn=conn)
                draft = state.require_draft(brand_id, conn=conn)
                if n is not None and draft["step"] < 4:
                    state.touch(draft, f"/brands/{brand_id}/intake/paste", 4, conn=conn)
        except Exception:  # noqa: BLE001 — worker 最後一道防線，不能讓例外憑空消失
            ok = False
        _notify_step_done(conn, brand_id, brand_name, ok,
                          verbs=("貼回格式已修好，可以回去看", "貼回修格式失敗，可以回去重試"))


def _start(kind: str, brand_id: str, org_id: str) -> None:
    lock = f"intake_{kind}:{brand_id}"
    if background_is_active(lock):
        return  # 已經在跑，no-op（原本行程內狀態表的 idempotent=True 同一個行為）
    background_enqueue(f"background.{_TASK_TYPE[kind]}", org_id=org_id, lock=lock, brand_id=brand_id)


# ---------------------------------------------------------------------------
# 初掃（S4.14-S4.24）
# ---------------------------------------------------------------------------

@router.post("/api/intake/brands/{brand_id}/scan/start")
def scan_start(request: Request, brand_id: str):
    actor = require_actor(request)
    require_brand(brand_id, actor)
    draft = state.require_draft(brand_id)
    if draft["scan_done"]:
        return {"limit_block": None}
    if state.would_exceed(draft, script.COST_SCAN):
        return {"limit_block": _limit_block(draft, "scan")}
    _start("scan", brand_id, actor.org_id)
    return {"limit_block": None}


@router.get("/api/intake/brands/{brand_id}/scan/status")
def scan_status(request: Request, brand_id: str):
    actor = require_actor(request)
    require_brand(brand_id, actor)
    draft = state.require_draft(brand_id)
    return _envelope(_job_state(draft, "scan"))


@router.post("/api/intake/brands/{brand_id}/scan/skip")
def scan_skip(request: Request, brand_id: str):
    actor = require_actor(request)
    require_brand(brand_id, actor)
    draft = state.require_draft(brand_id)
    draft["scan_done"] = True
    draft["scan_impressions"] = []
    draft["scan_products"] = []
    draft["product_card_drafts"] = []
    draft["url_results"] = []
    state.save(draft)
    return Response(status_code=204)


@router.post("/api/intake/brands/{brand_id}/scan/products")
async def scan_products(request: Request, brand_id: str):
    actor = require_actor(request)
    require_brand(brand_id, actor)
    draft = state.require_draft(brand_id)
    body = await _json_body(request)
    names = body.get("names")
    names = names if isinstance(names, list) else []
    created = state.create_scanned_products(web.conn, brand_id, draft, names, str(actor.user_id))
    product_id = None
    source_photo_token = str(body.get("source_photo_token") or "").strip()
    if source_photo_token:
        product_id = state.create_product_from_card(
            web.conn, brand_id, draft, source_photo_token, str(actor.user_id),
        )
        created += 1 if product_id else 0
    return {"created_count": created, "product_id": product_id}


# ---------------------------------------------------------------------------
# 引導問答（S4.25-S4.32）
# ---------------------------------------------------------------------------

@router.post("/api/intake/brands/{brand_id}/question/start")
def question_start(request: Request, brand_id: str):
    actor = require_actor(request)
    require_brand(brand_id, actor)
    draft = state.require_draft(brand_id)
    if draft["step"] < 4:
        state.touch(draft, f"/brands/{brand_id}/intake/question", 4)
    if draft["qa_done"] or draft["current_q"] is not None:
        return {"limit_block": None}
    if state.would_exceed(draft, script.COST_QUESTION):
        return {"limit_block": _limit_block(draft, "question")}
    _start("question", brand_id, actor.org_id)
    return {"limit_block": None}


@router.get("/api/intake/brands/{brand_id}/question/status")
def question_status(request: Request, brand_id: str):
    actor = require_actor(request)
    require_brand(brand_id, actor)
    draft = state.require_draft(brand_id)
    return _envelope(_job_state(draft, "question"))


@router.post("/api/intake/brands/{brand_id}/question/answer")
async def question_answer(request: Request, brand_id: str):
    actor = require_actor(request)
    require_brand(brand_id, actor)
    draft = state.require_draft(brand_id)
    entry = state.current_entry(draft)
    q = draft["current_q"]
    if entry is None or q is None:
        return _error(400, "目前沒有可回答的題目。")
    body = await _json_body(request)
    choice = str(body.get("choice") or "")
    note = clean(str(body.get("note") or ""))

    if choice == "skip":
        entry["skipped"] = True
        state.save(draft)
        return Response(status_code=204)

    choice_map = dict(state.question_options(q))
    if choice not in choice_map:
        return _error(400, "請選一個選項。")
    if choice == "other" and not note:
        return _error(400, "你選了「我自己說」，請在補充欄寫一句你的想法。")

    entry["answer_key"] = choice
    entry["answer_text"] = note
    state.save(draft)
    return Response(status_code=204)


@router.post("/api/intake/brands/{brand_id}/question/skip-remaining")
def question_skip_remaining(request: Request, brand_id: str):
    actor = require_actor(request)
    require_brand(brand_id, actor)
    draft = state.require_draft(brand_id)
    state.mark_qa_done(draft)
    state.save(draft)
    return Response(status_code=204)


# ---------------------------------------------------------------------------
# 花費上限（S4.67-S4.70）／超限攔截（S4.71-S4.74）
# ---------------------------------------------------------------------------

@router.post("/api/intake/brands/{brand_id}/budget")
async def budget_set(request: Request, brand_id: str):
    actor = require_actor(request)
    require_brand(brand_id, actor)
    draft = state.require_draft(brand_id)
    body = await _json_body(request)
    limit = body.get("limit")
    if limit is None or limit == "":
        return _error(400, "請填寫上限金額。")
    if isinstance(limit, bool) or not isinstance(limit, (int, float)):
        return _error(400, "上限金額請填數字，例如 30。")
    limit = float(limit)
    if limit < draft["cost_spent"]:
        return _error(400, f"這次已經花了 US$ {draft['cost_spent']:.2f}，上限不能設得比它低。")
    draft["budget_limit"] = round(limit, 2)
    state.save(draft)
    return Response(status_code=204)


@router.post("/api/intake/brands/{brand_id}/budget/raise")
async def budget_raise(request: Request, brand_id: str):
    actor = require_actor(request)
    require_brand(brand_id, actor)
    draft = state.require_draft(brand_id)
    body = await _json_body(request)
    kind = body.get("kind") if body.get("kind") in ("scan", "question", "paste_fix") else "scan"
    draft["budget_limit"] = round(draft["budget_limit"] + 30, 2)
    state.save(draft)
    if kind == "scan" and not draft["scan_done"]:
        _start("scan", brand_id, actor.org_id)
    elif kind == "question" and not draft["qa_done"] and draft["current_q"] is None:
        _start("question", brand_id, actor.org_id)
    elif kind == "paste_fix":
        _start("paste_fix", brand_id, actor.org_id)
    return {"job": _job_state(draft, kind)}


@router.post("/api/intake/brands/{brand_id}/skip-remaining-ai")
def skip_remaining_ai(request: Request, brand_id: str):
    actor = require_actor(request)
    require_brand(brand_id, actor)
    draft = state.require_draft(brand_id)
    if not draft["scan_done"]:
        draft["scan_done"] = True
        draft["scan_impressions"] = []
        draft["scan_products"] = []
        draft["product_card_drafts"] = []
        draft["url_results"] = []
    state.mark_qa_done(draft)
    draft["step"] = 4
    state.save(draft)
    return Response(status_code=204)


# ---------------------------------------------------------------------------
# 交接包（S4.33-S4.41）／操作卡（S4.42-S4.45）——同步、免費，不進背景
# ---------------------------------------------------------------------------

@router.post("/api/intake/brands/{brand_id}/handoff")
async def handoff_generate(request: Request, brand_id: str):
    actor = require_actor(request)
    require_brand(brand_id, actor)
    draft = state.require_draft(brand_id)
    body = await _json_body(request)
    depth = body.get("depth")
    if depth not in ("standard", "deep"):
        return _error(400, "請選擇要跑多深。")
    known = sorted(p["name"] for p in repo.list_products(web.conn, brand_id))
    prompt_text = script.build_prompt(draft, depth, known_products=known,
                                      existing=ir.existing_confirmed_data(web.conn, brand_id))
    ir.update_draft(web.conn, brand_id, draft["id"], handoff_depth=depth,
                    handoff_prompt=prompt_text, handoff_generated_at=now_utc())
    if draft["step"] < 4:
        state.touch(draft, f"/brands/{brand_id}/intake/handoff", 4)
    return {"prompt_text": prompt_text}


@router.get("/api/intake/brands/{brand_id}/handoff/{provider}")
def operator_card(request: Request, brand_id: str, provider: str):
    if provider not in ("claude", "chatgpt"):
        raise NotFoundKind("操作卡")
    actor = require_actor(request)
    require_brand(brand_id, actor)
    draft = state.require_draft(brand_id)
    return _envelope(script.card_for(provider, draft["handoff_depth"] or "standard"))


# ---------------------------------------------------------------------------
# 貼回（S4.46-S4.57）：驗證／解決未知適用範圍同步免費，AI 修格式走背景
# ---------------------------------------------------------------------------

def _paste_result(draft: dict) -> dict:
    total_lines = paste_parse.count_data_lines(draft["paste_raw"]) if draft["paste_raw"] else 0
    return {"errors": draft["paste_errors"], "data_line_count": total_lines}


@router.post("/api/intake/brands/{brand_id}/paste/validate")
async def paste_validate(request: Request, brand_id: str):
    actor = require_actor(request)
    require_brand(brand_id, actor)
    draft = state.require_draft(brand_id)
    body = await _json_body(request)
    raw_text = str(body.get("raw_text") or "")
    if not raw_text.strip():
        return _error(400, "請先貼上 AI 給你的表格內容。")
    n = state.apply_paste(draft, raw_text, conn=web.conn)
    if n is not None and draft["step"] < 4:
        state.touch(draft, f"/brands/{brand_id}/intake/paste", 4)
    return _paste_result(draft)


@router.post("/api/intake/brands/{brand_id}/paste/resolve-scope")
async def paste_resolve_scope(request: Request, brand_id: str):
    actor = require_actor(request)
    require_brand(brand_id, actor)
    draft = state.require_draft(brand_id)
    body = await _json_body(request)
    scope_name = clean(str(body.get("scope_name") or ""))
    action = body.get("action") if body.get("action") in ("create_product", "assign_brand") else "assign_brand"
    if action == "create_product":
        known = {p["name"] for p in repo.list_products(web.conn, brand_id)}
        if scope_name and scope_name not in known:
            repo.create_product(web.conn, brand_id, name=scope_name, actor=str(actor.user_id))
    else:
        draft["paste_raw"] = paste_parse.rewrite_scope(draft["paste_raw"], scope_name, "整個品牌")
    n = state.apply_paste(draft, draft["paste_raw"], conn=web.conn)
    if n is not None and draft["step"] < 4:
        state.touch(draft, f"/brands/{brand_id}/intake/paste", 4)
    return _paste_result(draft)


@router.post("/api/intake/brands/{brand_id}/paste/fix/start")
def paste_fix_start(request: Request, brand_id: str):
    actor = require_actor(request)
    require_brand(brand_id, actor)
    draft = state.require_draft(brand_id)
    if state.would_exceed(draft, script.COST_PASTE_FIX):
        return {"limit_block": _limit_block(draft, "paste_fix")}
    _start("paste_fix", brand_id, actor.org_id)
    return {"limit_block": None}


@router.get("/api/intake/brands/{brand_id}/paste/fix/status")
def paste_fix_status(request: Request, brand_id: str):
    actor = require_actor(request)
    require_brand(brand_id, actor)
    draft = state.require_draft(brand_id)
    return _envelope(_job_state(draft, "paste_fix"))


# ---------------------------------------------------------------------------
# AI 帶回的內容清單／逐條處理（S4.58-S4.66）
# ---------------------------------------------------------------------------

def _review_item_json(item: dict, hints: dict) -> dict:
    return {
        "id": item["id"], "i": item["i"], "kind": item["kind"], "category": item["category"],
        "title": item["title"], "content": item["content"], "scope": item["scope"],
        "evidence": item["evidence"], "dup_hint": hints.get(item["id"]),
        "severity": "soft" if item["kind"] == "限制規則" else None,
    }


@router.get("/api/intake/brands/{brand_id}/review")
def review_list(request: Request, brand_id: str):
    actor = require_actor(request)
    require_brand(brand_id, actor)
    draft = state.require_draft_or_just_completed(brand_id)
    items = ir.list_pending_items(web.conn, brand_id, draft["id"])
    hints = ir.duplicate_hints(web.conn, brand_id, items)
    return _envelope([_review_item_json(it, hints) for it in items])


@router.post("/api/intake/brands/{brand_id}/review/pending-all")
def review_pending_all(request: Request, brand_id: str):
    """「剩餘全部先存成待確認」一鍵收工（issue #1）。逐筆走唯一入口 `ir.resolve_item`；
    產品事實還沒指定產品的列會 raise ValueError，跳過留在清單，不整批擋下（S4.62）。"""
    actor = require_actor(request)
    require_brand(brand_id, actor)
    draft = state.require_draft(brand_id)
    for it in ir.list_pending_items(web.conn, brand_id, draft["id"]):
        try:
            ir.resolve_item(web.conn, brand_id, it["id"], "pending_saved", processed_by=str(actor.user_id))
        except ValueError:
            continue
    if not ir.list_pending_items(web.conn, brand_id, draft["id"]):
        state.complete_draft(draft)
    return Response(status_code=204)


@router.get("/api/intake/brands/{brand_id}/review/{i}")
def review_item_get(request: Request, brand_id: str, i: int):
    actor = require_actor(request)
    require_brand(brand_id, actor)
    draft = state.require_draft_or_just_completed(brand_id)
    items = ir.list_items(web.conn, brand_id, draft["id"])
    item = next((it for it in items if it["i"] == i), None)
    if item is None:
        return _error(404, "找不到這一筆。")
    hints = ir.duplicate_hints(web.conn, brand_id, [item])
    return _envelope(_review_item_json(item, hints))


_OUTCOME_MAP = {"confirm": "confirmed", "pending": "pending_saved", "discard": "discarded"}


@router.post("/api/intake/brands/{brand_id}/review/{i}")
async def review_item_post(request: Request, brand_id: str, i: int):
    actor = require_actor(request)
    require_brand(brand_id, actor)
    draft = state.require_draft_or_just_completed(brand_id)
    items = ir.list_items(web.conn, brand_id, draft["id"])
    item = next((it for it in items if it["i"] == i), None)
    if item is None:
        return _error(404, "找不到這一筆。")
    body = await _json_body(request)
    outcome = body.get("outcome") if body.get("outcome") in _OUTCOME_MAP else "pending"
    scope = clean(str(body.get("scope") or item["scope"]))

    edits = None
    if outcome != "discard":
        title = clean(str(body.get("title") or ""))
        content = clean(str(body.get("content") or ""))
        category = str(body.get("category") or "")
        if not title:
            return _error(400, "請填寫標題。")
        if not content:
            return _error(400, "請填寫內容。")
        if not category:
            return _error(400, "請選擇分類。")
        if item["kind"] == "產品事實" and scope == "整個品牌":
            return _error(400, "產品事實要選一個產品，不能是「整個品牌」。")
        if scope and scope != "整個品牌":
            known = {p["name"] for p in repo.list_products(web.conn, brand_id)}
            if scope not in known:
                if item["outcome"] != "pending" and item["kind"] == "產品事實":
                    return _error(400, "已落檔的產品事實不能在這裡改掛其他產品。")
                repo.create_product(web.conn, brand_id, name=scope, actor=str(actor.user_id))
        edits = {"title": title, "content": content,
                 "category": ir._category_to_internal(item["kind"], category), "scope_raw": scope}

    severity = body.get("severity") if body.get("severity") in ("soft", "hard") else "soft"
    if item["outcome"] != "pending":
        if outcome != "confirm":
            return _error(400, "已落檔內容只能修改後重新確認。")
        try:
            ir.update_resolved_item(
                web.conn, brand_id, item["id"], processed_by=str(actor.user_id), edits=edits or {},
            )
        except ValueError as exc:
            return _error(400, str(exc))
        return Response(status_code=204)
    ir.resolve_item(web.conn, brand_id, item["id"], _OUTCOME_MAP[outcome],
                    processed_by=str(actor.user_id), edits=edits, rule_severity=severity)

    if not ir.list_pending_items(web.conn, brand_id, draft["id"]):
        state.complete_draft(draft)
    return Response(status_code=204)


# T2 新端點拆在小檔；本檔已接近 800 行，不再把新功能直接塞進來。
from app.intake.routes_offerings_api import router as offerings_router  # noqa: E402
from app.intake.routes_t2_api import router as t2_router  # noqa: E402

router.include_router(t2_router)
router.include_router(offerings_router)
