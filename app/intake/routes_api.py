"""app/intake/routes_api.py — brand onboarding JSON API: photo upload, brand create／restart, the
draft read, and the background prefill job (website/photo scan, F42-I05).

F42-I14 removed the retired onboarding stage from this file: the old impression scan
(`scan/start|status|skip`, `scan/products`), the AI Q&A (`question/*`), the cost rail
(`budget*`, `skip-remaining-ai`), the handoff prompt (`handoff/*`), paste-back (`paste/*`), the
pending list (`review/*`) and the research reports (`research-reports*`). The seven-step routes
live in `routes_onboarding_api.py`, personas in `routes_t2_api.py`, step 6 in
`routes_tools_api.py`, product onboarding (F43-I05) in `routes_product_api.py`; all four are
included at the end of this file.

Entry point: this file's `router` (`app/intake/__init__.register` includes it). Depended on by
`app/intake/__init__.py` only (the background task).
"""

from datetime import UTC, datetime

from fastapi import APIRouter, File, Request, UploadFile

from app import schedule
from app.brand_intelligence import background_job
from app.brand_intelligence import repository as repo
from app.core.db import connection as core_db_connection
from app.core.db import new_id
from app.intake import ai, onboarding, state
from app.intake import repository as ir
from app.shared import web
from app.shared.web import JSONResponse, clean, require_actor, require_brand

router = APIRouter()


def _error(status_code: int, message: str) -> JSONResponse:
    return JSONResponse({"error": message}, status_code=status_code)


def _envelope(data) -> dict:
    return {"data": data, "generated_at": datetime.now(UTC).isoformat()}


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
    # F42-I04: brand onboarding step 1 also sends the photo kinds (parallel to photo_tokens),
    # the market region and the regulatory regime; every photo becomes a brand-level asset.
    tokens = [str(t) for t in form.getlist("photo_tokens")]
    kinds = [str(k) for k in form.getlist("photo_kinds")]
    try:
        urls = onboarding.check_urls([str(u) for u in form.getlist("urls")])
        onboarding.check_photo_kinds(kinds, len(tokens))
        market_region = onboarding.check_market_region(form.get("market_region"))
        regime = onboarding.check_regime(form.get("regulatory_regime"))
    except ValueError as exc:
        return _error(400, str(exc))
    photos = onboarding.resolve_photos(tokens, kinds)
    client_name = clean(str(form.get("client_name") or ""))
    actor_id = str(actor.user_id)
    brand = repo.create_brand(web.conn, org_id=actor.org_id, name=brand_name,
                               client_name=client_name or None, actor=actor_id)
    schedule.seed_brand_vocabulary(web.conn, actor.org_id, brand["id"])
    if market_region:
        repo.set_brand_switches(web.conn, brand["id"], market_region=market_region,
                                conversion_goal=None, actor=actor_id)
    if regime:
        repo.set_regulatory_regime(web.conn, brand["id"], regime, actor=actor_id)
    onboarding.save_new_photos(web.conn, brand["id"], photos, actor=actor_id)
    state.start_draft(web.conn, brand["id"], brand_name, description=description,
                      urls=urls, photos=photos, actor=actor_id)
    # quick 恆為 False（2026-09-14 起草稿永遠建立）；留著這個鍵只因為
    # frontend/src/lib/intakeApi.ts 還在讀它，那個檔另有票在動，不在這張票拿掉。
    return {"brand_id": brand["id"], "quick": False}


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
    state.start_draft(web.conn, brand_id, brand["name"], description=description,
                      urls=urls, photos=photos, actor=str(actor.user_id))
    return {"quick": False}


def _draft_shape(draft: dict) -> dict:
    photos = [{"token": p.get("token") or "", "name": p["name"], "size_mb": p["size_mb"]}
              for p in draft["photos"]]
    return {
        "id": draft["id"], "brand_id": draft["brand_id"], "brand_name": draft["brand_name"],
        "step": draft["step"], "completed": draft.get("status") == "completed",
        "description": draft["description"], "urls": draft["urls"], "photos": photos,
        "scan_done": draft["scan_done"],
    }


@router.get("/api/intake/brands/{brand_id}/draft")
def draft_get(request: Request, brand_id: str):
    """The onboarding shell's draft read: the open draft, else the brand's latest completed one
    (a finished brand re-entering the wizard), else 404."""
    actor = require_actor(request)
    require_brand(brand_id, actor)
    draft = state.require_draft_or_just_completed(brand_id)
    return _envelope(_draft_shape(draft))


# ---------------------------------------------------------------------------
# Background prefill (F42-I05): queued by `POST …/onboarding/scan` under `ai.prefill_lock`.
# ---------------------------------------------------------------------------

def _notify_step_done(conn, brand_id: str, brand_name: str, ok: bool, *, verbs: tuple) -> None:
    background_job.notify(
        conn, brand_id, category="intake_ai_step_done", dedupe_key=new_id("itkjob"),
        message=f"「{brand_name}」{verbs[0] if ok else verbs[1]}", action_url=f"/app/brands/{brand_id}/intake",
    )


def background_intake_scan(org_id: str, brand_id: str, prefill: bool = True) -> None:
    """The brand-onboarding website/photo prefill. `prefill` stays in the signature because
    `onboarding.start_scan` queues the job with `prefill=True`; the old impression scan it used to
    select against was removed by F42-I14."""
    with core_db_connection() as conn:
        brand = repo.get_brand(conn, brand_id)
        brand_name = brand["name"] if brand else brand_id
        error = None
        try:
            draft = state.require_draft(brand_id, conn=conn)
            ok, message = ai.run_prefill(conn, draft)
            if not ok:
                error = RuntimeError(message)
        except Exception as exc:  # noqa: BLE001 — notify first, then re-raise so the job fails
            conn.rollback()
            error = exc
        _notify_step_done(conn, brand_id, brand_name, error is None,
                          verbs=("AI 讀完網站，可以回去確認", "AI 讀網站失敗，可以回去重試"))
        if error is not None:
            raise error  # Contract J: the job ends failed; the status reads the call's error


from app.intake.routes_onboarding_api import router as onboarding_router  # noqa: E402
from app.intake.routes_product_api import router as product_router  # noqa: E402
from app.intake.routes_t2_api import router as t2_router  # noqa: E402
from app.intake.routes_tools_api import router as tools_router  # noqa: E402

router.include_router(t2_router)
router.include_router(tools_router)
router.include_router(onboarding_router)
router.include_router(product_router)
