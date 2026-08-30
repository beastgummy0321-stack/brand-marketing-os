"""app/brand_intelligence/routes_library.py — 品牌智庫 JSON API（票 B2-library 第二段，
契約 `.scratch/grill/GRILL-B2-library.md`，型別逐欄對照 `frontend/src/lib/libraryApi.ts`）。

`app/brand_intelligence/routes.py`／`repository.py` 兩檔都已頂到
`docs/tech-debt.md` 凍結的行數上限，新路由不得再往那兩個檔案加（CLAUDE.md 第五節：
超標檔案先拆再加）。本票新增的路由全部放這個新檔案：

1. `GET /api/library/brands/{brand_id}`：六分頁＋品牌資料整包（S5.1–S5.39 讀取部分）。
2. 自有渠道編輯／刪除（S5.31，後端本來沒有這兩個動詞，本票新補）。
3. 顧客原話貼入＋AI 抽取背景執行＋輪詢（S5.40–S5.42，五鐵則③生成不擋路）。

其餘六分頁既有的新增／編輯／確認／刪除／上傳，一律沿用 `app/brand_intelligence/routes.py`
既有的表單 POST 端點（前端已經這樣打，見契約「不用新增」節），這裡不重複第二份。

對外進入點：本檔的 `router`（`app/main.py` 直接 `include_router`，比照
`routes_inbox.py`／`routes_settings.py` 同一套「原檔頂到上限，新功能另開檔」的做法）。
誰依賴它：只有 `app/main.py`。
"""

import os
import re
from datetime import UTC, datetime
from pathlib import Path

from fastapi import APIRouter, File, Form, Request, UploadFile
from fastapi.responses import Response

import app.storage as storage
from app.brand_intelligence import background_job
from app.brand_intelligence import customer_voice as cv_mod
from app.brand_intelligence import repository as repo
from app.core import cleanup
from app.core import settings as core_settings
from app.core import vocab as md
from app.core.db import new_id
from app.llm import gateway, providers
from app.shared import web
from app.shared.web import JSONResponse, NotFoundKind, clean, require_actor, require_brand

router = APIRouter()

PROVIDER = providers.AnthropicProvider()
PARSE_FAIL_MESSAGE = cv_mod.PARSE_FAIL_MESSAGE
COST_CUSTOMER_VOICE_EXTRACTION = cv_mod.COST_CUSTOMER_VOICE_EXTRACTION

_ASSET_CONTENT_TYPES = {
    "jpg": "image/jpeg", "jpeg": "image/jpeg", "png": "image/png",
    "webp": "image/webp", "gif": "image/gif",
}
_UNSAFE_ASSET_FILENAME_CHARS = re.compile(r"[^A-Za-z0-9._-]+")


def _safe_asset_filename(name: str) -> str:
    name = os.path.basename((name or "").strip())
    name = _UNSAFE_ASSET_FILENAME_CHARS.sub("_", name)
    return name or "file"


def save_official_asset(brand_id: str, *, org_id: str, actor: str, asset_kind: str, product_id: str,
                        title: str, filename: str, content: bytes) -> tuple[bool, str | None]:
    """儲存一筆素材（Storage，票 storage-02）；失敗一律回傳可直接給 API 或表單顯示的訊息。
    `put` 失敗就不寫列——一列指到不存在的物件，畫面會永遠是張破圖（SPEC D9）。"""
    if asset_kind not in dict(md.ASSET_KINDS):
        return False, "請選擇素材類型。"
    product_id = clean(product_id)
    if product_id and not repo.get_product(web.conn, brand_id, product_id):
        return False, "找不到所選產品。"
    filename = filename or ""
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if not filename or not content:
        return False, "請選擇一個圖檔上傳。"
    if ext not in _ASSET_CONTENT_TYPES:
        return False, f"「{filename}」不是支援的圖片格式，請用 png、jpg、jpeg、webp 或 gif。"

    asset_id = new_id("oas")
    safe_name = _safe_asset_filename(filename)
    key = f"{org_id}/brands/{brand_id}/assets/{asset_id}/{safe_name}"
    try:
        storage.put(org_id=org_id, key=key, filename=safe_name, content=content,
                    content_type=_ASSET_CONTENT_TYPES[ext])
        repo.create_official_asset(
            web.conn, brand_id, actor=actor, asset_kind=asset_kind, storage_key=key,
            product_id=product_id or None, title=clean(title) or None,
        )
    except storage.StorageError:
        return False, "素材儲存失敗，請稍後再試。"
    return True, None


def extract(conn, brand_id: str, *, actor: str, raw_text: str, source_channel: str,
            source_detail: str | None = None, source_type: str = "manual") -> tuple:
    """抽取一筆顧客原話並入庫。成功回 (True, row)；失敗回 (False, 人話錯誤)，不入庫。"""
    brand = repo.get_brand(conn, brand_id)
    if brand is None:
        raise ValueError(f"找不到品牌：{brand_id}")

    user_text = cv_mod._build_user_text(raw_text, source_channel, source_detail)
    context = gateway.TaskContext(
        context_scope={"brand_id": brand_id}, knowledge_item_ids=[],
        brand_version=brand["knowledge_version"],
    )
    task = gateway.run_task(
        conn, PROVIDER, brand_id=brand_id, task_type="customer_voice_extraction",
        prompt_template_id="customer_voice_extraction", prompt_template_version="v1",
        system=cv_mod._SYSTEM, messages=[{"role": "user", "content": user_text}], context=context,
    )
    if task["status"] != "succeeded":
        return False, task["error"]

    data = gateway.parse_json_reply(task["rendered_output"])
    extraction = cv_mod._normalize_extraction(data)
    if extraction is None:
        return False, PARSE_FAIL_MESSAGE

    row = repo.create_customer_voice(
        conn, brand_id, actor=actor, raw_text=raw_text, source_channel=source_channel,
        source_detail=source_detail, source_type=source_type, extraction=extraction,
        llm_task_id=task["id"],
    )
    return True, row


# ---------------------------------------------------------------------------
# 六分頁＋品牌資料整包讀取
# ---------------------------------------------------------------------------

def _source_ref_text(brand_id: str, source_reference_id: str | None) -> str | None:
    if not source_reference_id:
        return None
    row = repo.get_source_reference(web.conn, brand_id, source_reference_id)
    return row["title"] if row else None


def _fact_shape(brand_id: str, fact: dict) -> dict:
    return {
        "id": fact["id"], "fact_type": fact["fact_type"],
        "fact_type_label": md.brand_fact_type_label(fact["fact_type"]),
        "label": fact["label"], "value": fact["value"], "status": fact["status"],
        "confirmed_by": fact.get("confirmed_by"), "confirmed_at": fact.get("confirmed_at"),
        "stale_label": web.fact_staleness(fact),
        "source_reference": _source_ref_text(brand_id, fact.get("source_reference_id")),
    }


def _rule_shape(brand_id: str, rule: dict) -> dict:
    return {
        "id": rule["id"], "rule_type": rule["rule_type"],
        "rule_type_label": md.rule_type_label(rule["rule_type"]),
        "content": rule["content"], "severity": rule["severity"], "product_id": rule["product_id"],
        "scope_label": web.scope_label(brand_id, rule["product_id"]),
        "source_reference": _source_ref_text(brand_id, rule.get("source_reference_id")),
    }


def _claim_shape(brand_id: str, claim: dict) -> dict:
    return {
        "id": claim["id"], "claim_text": claim["claim_text"], "claim_type": claim["claim_type"],
        "product_id": claim["product_id"],
        "scope_label": web.scope_label(brand_id, claim["product_id"]),
        "evidence_source_reference": _source_ref_text(
            brand_id, claim.get("evidence_source_reference_id")),
    }


def _asset_shape(brand_id: str, asset: dict) -> dict:
    filename = Path(asset["storage_key"]).name
    product = repo.get_product(web.conn, brand_id, asset["product_id"]) if asset.get("product_id") else None
    return {
        "id": asset["id"], "asset_kind": asset["asset_kind"],
        "asset_kind_label": md.asset_kind_label(asset["asset_kind"]),
        "title": asset.get("title"), "product_id": asset.get("product_id"),
        "product_name": product["name"] if product else None,
        "file_url": f"/brands/{brand_id}/assets/file/{asset['id']}/{filename}",
    }


def _channel_shape(channel: dict) -> dict:
    return {
        "id": channel["id"], "channel_type": channel["channel_type"],
        "channel_type_label": md.channel_type_label(channel["channel_type"]),
        "name": channel["name"], "identifier": channel["identifier"], "status": channel["status"],
    }


def _customer_voice_shape(cv: dict) -> dict:
    return {
        "id": cv["id"], "source_channel": cv["source_channel"],
        "source_channel_label": md.customer_voice_channel_label(cv["source_channel"]),
        "source_detail": cv.get("source_detail"), "raw_text": cv["raw_text"],
        "status": cv["status"], "extraction": cv["extraction"],
    }


def _brand_profile_shape(brand_id: str, brand: dict) -> dict:
    delete_impact = [{"label": label, "count": n}
                      for label, n in cleanup.count_all(web.conn, brand_id) if n > 0]
    return {
        "id": brand["id"], "name": brand["name"], "client_name": brand.get("client_name"),
        "status": brand["status"], "market_region": brand.get("market_region"),
        "conversion_goal": brand.get("conversion_goal"),
        "delete_impact": delete_impact,
    }


@router.get("/api/library/brands/{brand_id}")
def library_bundle(request: Request, brand_id: str):
    actor = require_actor(request)
    brand = require_brand(brand_id, actor)
    facts = (repo.list_brand_facts(web.conn, brand_id, status="confirmed")
             + repo.list_brand_facts(web.conn, brand_id, status="pending"))
    data = {
        "brand": _brand_profile_shape(brand_id, brand),
        "products": [{"id": p["id"], "name": p["name"]} for p in web.list_products(brand_id)],
        "facts": [_fact_shape(brand_id, f) for f in facts],
        "rules": [_rule_shape(brand_id, r) for r in repo.list_rules_for_brand(web.conn, brand_id)],
        "claims": [_claim_shape(brand_id, c) for c in repo.list_claims_for_brand(web.conn, brand_id)],
        "assets": [_asset_shape(brand_id, a) for a in repo.list_official_assets(web.conn, brand_id)],
        "channels": [_channel_shape(c) for c in repo.list_channels(web.conn, brand_id)],
        "customer_voices": [_customer_voice_shape(v)
                             for v in repo.list_customer_voices(web.conn, brand_id)],
    }
    return {"data": data, "generated_at": datetime.now(UTC).isoformat()}


@router.post("/api/library/brands/{brand_id}/delete")
async def brand_delete_api(request: Request, brand_id: str):
    """永久刪除品牌（S5.49 危險區二次確認）：取代舊版 Jinja 表單端點
    `/brands/{brand_id}/delete`，供 `BrandProfilePanel.tsx` 的 `ConfirmDeleteView`
    呼叫（`frontend/src/lib/libraryApi.ts` `deleteBrand()`）。流程跟舊頁一致——只收已
    封存品牌、打字確認名稱、備份 → 刪品牌 → 一併刪掉這個品牌在 Storage 底下的整個前綴
    （票 storage-02，取代舊版刪本機資料夾，順便補上舊版的漏洞：舊版只刪一個沒人寫過的
    空資料夾，官方素材檔案永遠留在磁碟上）。DB 已經 commit，這裡失敗不能 500，回一句
    人話讓呼叫端接在成功訊息後面，跟 `delete_folder()` 原本的 warn 契約一樣。"""
    actor = require_actor(request)
    brand = require_brand(brand_id, actor)
    if brand["status"] != "archived":
        return JSONResponse({"error": "要先把品牌封存，才能永久刪除。"}, status_code=400)
    try:
        body = await request.json()
    except Exception:
        body = {}
    confirm_name = clean(str(body.get("confirm_name") or "")) if isinstance(body, dict) else ""
    if confirm_name != brand["name"]:
        return JSONResponse(
            {"error": "輸入的名稱跟品牌名稱不一樣，請照著上面顯示的名稱再打一次。"},
            status_code=400,
        )
    repo.delete_brand(web.conn, brand_id, actor=str(actor.user_id))
    try:
        storage.delete_prefix(org_id=brand["org_id"], prefix=f"{brand['org_id']}/brands/{brand_id}/")
        warn = ""
    except storage.StorageError as exc:
        warn = f"（品牌的素材檔案沒有刪乾淨：{exc}，請自己到 Storage 後台確認。）"
    message = f"已永久刪除品牌「{brand['name']}」。{warn}".strip()
    return {"message": message}


@router.post("/api/brands/{brand_id}/assets")
async def asset_upload_api(request: Request, brand_id: str, asset_kind: str = Form(""),
                           product_id: str = Form(""), title: str = Form(""),
                           file: UploadFile = File(...)):
    actor = require_actor(request)
    brand = require_brand(brand_id, actor)
    ok, detail = save_official_asset(
        brand_id, org_id=brand["org_id"], actor=str(actor.user_id), asset_kind=asset_kind,
        product_id=product_id, title=title, filename=file.filename or "", content=await file.read(),
    )
    if not ok:
        return JSONResponse({"detail": detail}, status_code=400)
    return {"ok": True}


# ---------------------------------------------------------------------------
# 自有渠道編輯／刪除（S5.31：後端本來只有 create_channel／list_channels，本票新補）
# ---------------------------------------------------------------------------

@router.post("/brands/{brand_id}/channels/{channel_id}/edit")
def channel_edit_api(request: Request, brand_id: str, channel_id: str,
                            channel_type: str = Form(""), name: str = Form(""),
                            identifier: str = Form(""), status: str = Form("active")):
    actor = require_actor(request)
    require_brand(brand_id, actor)
    errors = {}
    if not clean(channel_type):
        errors["channel_type"] = "請選擇渠道類型。"
    if not clean(name):
        errors["name"] = "請填寫渠道名稱。"
    if not clean(identifier):
        errors["identifier"] = "請填寫網址或帳號。"
    if status not in ("active", "inactive"):
        errors["status"] = "請選擇狀態。"
    if errors:
        return JSONResponse({"errors": errors}, status_code=400)
    try:
        repo.update_channel(web.conn, brand_id, channel_id, actor=str(actor.user_id), channel_type=channel_type,
                             name=clean(name), identifier=clean(identifier), status=status)
    except ValueError:
        raise NotFoundKind("自有渠道")
    return Response(status_code=200)


@router.post("/brands/{brand_id}/channels/{channel_id}/delete")
def channel_delete_api(request: Request, brand_id: str, channel_id: str):
    actor = require_actor(request)
    require_brand(brand_id, actor)
    try:
        repo.delete_channel(web.conn, brand_id, channel_id, actor=str(actor.user_id))
    except ValueError:
        raise NotFoundKind("自有渠道")
    return Response(status_code=200)


# ---------------------------------------------------------------------------
# 顧客原話貼入＋AI 抽取：背景執行＋JSON 輪詢（S5.40–S5.42，五鐵則③生成不擋路）。
#
# 跟 app/ads/routes.py 的等待頁背景引擎（_progress_state 等）不同的地方：那套是給
# 「同一個 key（brand+cycle）F5 重整也不該重複觸發」的冪等閘 + meta-refresh 等待頁；
# 這裡每次貼入都是一筆新內容、天生不重複，job_key 用 new_id() 現生一個就夠，
# 不需要冪等閘與逾時清除那一整套，前端也是輪詢 JSON 而不是等待頁。
# （票要求：在 brand_intelligence 內重實作，不跨層依賴廣告分支）。
# ---------------------------------------------------------------------------

_cv_jobs = background_job.JobRegistry()


def active_jobs() -> list[dict]:
    """回傳進行中的原話轉換工作，供 dashboard 聚合；不洩漏 registry 狀態。"""
    return [
        {
            "brand_id": state["brand_id"],
            "kind": "library_convert",
            "status": state["status"],
            "stage": "分析原話中",
            "started_at": state.get("started_at") or "",
        "action_url": f"/app/brands/{state['brand_id']}/library",
        }
        for _job_key, state in _cv_jobs.items()
        if state.get("status") in ("running", "waiting") and state.get("brand_id")
    ]


def _cv_notify(brand_id: str, job_key: str, message: str) -> None:
    background_job.notify(
        web.conn, brand_id, category="customer_voice_extraction_done", dedupe_key=job_key,
        message=message, action_url=f"/app/brands/{brand_id}/library",
    )


def _run_customer_voice_job(job_key: str, brand_id: str, actor: str, raw_text: str,
                             source_channel: str, source_detail: str | None) -> None:
    try:
        ok, result = extract(
            web.conn, brand_id, actor=actor, raw_text=raw_text,
            source_channel=source_channel, source_detail=source_detail,
        )
    except Exception as exc:  # noqa: BLE001 — 背景執行緒最後一道防線，不能讓例外憑空消失
        ok, result = False, f"背景執行發生未預期錯誤：{exc}"

    # 先寫收件匣通知、確定 commit 完成，才把 job 狀態翻成 done／failed——順序反過來的話，
    # 輪詢端會有機會在通知還沒進 DB 前就看到「完成」，是一個真的會偶發的競態，不是理論上的。
    channel_label = md.customer_voice_channel_label(source_channel)
    if ok:
        shape = _customer_voice_shape(result)
        n = len(shape["extraction"])
        _cv_notify(brand_id, job_key,
                   f"「{channel_label}」原話分析完成，{f'找到 {n} 條重點' if n else '沒有找到重點'}")
        _cv_jobs.set(job_key, {"status": "done", "result": shape})
    else:
        _cv_notify(brand_id, job_key, f"「{channel_label}」原話分析失敗，可以重試")
        _cv_jobs.set(job_key, {"status": "failed", "message": result})


@router.post("/api/library/brands/{brand_id}/customer-voice")
async def customer_voice_submit(request: Request, brand_id: str):
    actor = require_actor(request)
    require_brand(brand_id, actor)
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"error": "請求格式不是合法的 JSON"}, status_code=400)
    if not isinstance(body, dict):
        return JSONResponse({"error": "請求格式不是合法的 JSON"}, status_code=400)

    source_channel = clean(body.get("source_channel") or "")
    source_detail = clean(body.get("source_detail") or "") or None
    raw_text = clean(body.get("raw_text") or "")
    if not source_channel:
        return JSONResponse({"error": "請選擇這段原話是從哪裡來的。"}, status_code=400)
    if not raw_text:
        return JSONResponse({"error": "請貼上顧客的原文內容。"}, status_code=400)

    budget_err = core_settings.budget_exceeded_message(
        web.conn, brand_id, cv_mod.COST_CUSTOMER_VOICE_EXTRACTION, org_id=actor.org_id,
        action="這次顧客原話分析", fallback_hint="或稍後再試。",
    )
    if budget_err:
        return JSONResponse({"error": budget_err}, status_code=422)

    job_key = new_id("cvjob")
    # brand_id／started_at：全站生成進度單一出口（票 B4-warroom）聚合端點列舉用，本身
    # 業務邏輯不讀這兩個鍵。
    _cv_jobs.start(job_key, {"status": "running", "brand_id": brand_id,
                             "started_at": datetime.now(UTC).isoformat()},
                   _run_customer_voice_job,
                   (job_key, brand_id, str(actor.user_id), raw_text, source_channel, source_detail))
    return {"job_key": job_key}


@router.get("/api/library/brands/{brand_id}/customer-voice/jobs/{job_key}")
def customer_voice_job_status(request: Request, brand_id: str, job_key: str):
    actor = require_actor(request)
    require_brand(brand_id, actor)
    return _cv_jobs.get(job_key, {"status": "running"})
