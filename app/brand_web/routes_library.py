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
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID

from fastapi import APIRouter, File, Form, Request, UploadFile
from fastapi.responses import Response

import app.storage as storage
from app.background import JOB_FAILED_MESSAGE
from app.background import enqueue as background_enqueue
from app.background import job_state as background_job_state
from app.background import queue_snapshot as background_queue_snapshot
from app.brand_intelligence import background_job
from app.brand_intelligence import customer_voice as cv_mod
from app.brand_intelligence import repository as repo
from app.core import cleanup, input_rules
from app.core import interrupts as core_interrupts
from app.core import settings as core_settings
from app.core import vocab as md
from app.core.db import connection as core_db_connection
from app.core.db import new_id, now_iso, now_utc
from app.identity import repository as identity_repo
from app.llm import gateway, providers
from app.shared import web
from app.shared.web import JSONResponse, NotFoundKind, app_path, clean, require_actor, require_brand

router = APIRouter()

PROVIDER = providers.AnthropicProvider()
PARSE_FAIL_MESSAGE = cv_mod.PARSE_FAIL_MESSAGE
COST_CUSTOMER_VOICE_EXTRACTION = cv_mod.COST_CUSTOMER_VOICE_EXTRACTION

_ASSET_KINDS = ("image/jpeg", "image/png", "image/webp", "image/gif")
_UNSAFE_ASSET_FILENAME_CHARS = re.compile(r"[^A-Za-z0-9._-]+")

# 上傳大小上限：F50 Contract I 的 `input_rules.UPLOAD_CAPS["library_asset"]`（50 MiB＝
# `supabase/config.toml` `[storage]` 的 `file_size_limit`）。路由在 `await file.read()` 之前
# 先用同一張表擋一次，免得整個 body 讀進記憶體之後才收到英文的 Storage 例外。
_UPLOAD_PATH = "library_asset"


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
    if not filename:
        return False, "請選擇一個圖檔上傳。"
    # F47 Contract A: the content decides (not the extension) and is the stored type; F50
    # Contract I: empty and oversize files get the one table's sentences.
    try:
        input_rules.check_upload(filename, len(content), path=_UPLOAD_PATH)
        content_type = input_rules.check_image_upload(filename, content, _ASSET_KINDS)
    except input_rules.InputRuleError as exc:
        return False, str(exc)

    asset_id = new_id("oas")
    safe_name = _safe_asset_filename(filename)
    key = f"{org_id}/brands/{brand_id}/assets/{asset_id}/{safe_name}"
    try:
        storage.put(org_id=org_id, key=key, filename=safe_name, content=content,
                    content_type=content_type)
        repo.create_official_asset(
            web.conn, brand_id, actor=actor, asset_kind=asset_kind, storage_key=key,
            product_id=product_id or None, title=clean(title) or None,
        )
    except storage.StorageError:
        return False, "素材儲存失敗，請稍後再試。"
    return True, None


def extract(conn, brand_id: str, *, actor: str, raw_text: str, source_channel: str,
            source_detail: str | None = None, source_type: str = "manual",
            job_key: str | None = None) -> tuple:
    """抽取一筆顧客原話並入庫。成功回 (True, row)；失敗回 (False, 人話錯誤)，不入庫。

    `job_key`（票 08）：背景 task 呼叫時帶進來，寫進 `context_scope_json`，只給狀態
    端點事後用 `context_scope_json->>'job_key'` 反查這一列 llm_task（見
    `_cv_job_status()`）；直接呼叫本函式的既有呼叫端（測試、其他工具）不必填。"""
    brand = repo.get_brand(conn, brand_id)
    if brand is None:
        raise ValueError(f"找不到品牌：{brand_id}")

    user_text = cv_mod._build_user_text(raw_text, source_channel, source_detail)
    context = gateway.TaskContext(
        context_scope={"brand_id": brand_id, **({"job_key": job_key} if job_key else {})},
        knowledge_item_ids=[], brand_version=brand["knowledge_version"],
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


FORMER_MEMBER_LABEL = "已不在這個組織的成員"


def confirmer_label(org_id: str, confirmed_by: str | None) -> str | None:
    """F47-I03 (drill-10 外觀 #11): 「確認人」 never shows a user id. A stored user id (written by the
    confirm routes as `actor.user_id`) reads as that member's e-mail through the identity facade;
    an id that is no longer a member of this org reads as `FORMER_MEMBER_LABEL`; anything else is
    a name somebody typed and shows as typed. Shared by the library and product read shapes
    (`routes_products`)."""
    if not confirmed_by:
        return confirmed_by
    try:
        user_id = UUID(confirmed_by)
    except ValueError:
        return confirmed_by
    if identity_repo.get_membership(web.conn, org_id, user_id) is None:
        return FORMER_MEMBER_LABEL
    user = identity_repo.get_user(web.conn, user_id)
    return user["email"] if user else FORMER_MEMBER_LABEL


def _fact_shape(brand_id: str, fact: dict, org_id: str | None = None) -> dict:
    """`org_id` = the brand's org when the caller already holds it (the bundle read); the single-fact
    write responses leave it out and it is read from the brand."""
    if org_id is None:
        brand = repo.get_brand(web.conn, brand_id)
        org_id = brand["org_id"] if brand else ""
    return {
        "id": fact["id"], "fact_type": fact["fact_type"],
        "fact_type_label": md.brand_fact_type_label(fact["fact_type"]),
        "fact_key": fact.get("fact_key"),
        "fact_key_label": md.proof_kind_label(fact["fact_key"]) if fact.get("fact_key") else None,
        "label": fact["label"], "value": fact["value"], "status": fact["status"],
        "confirmed_by": confirmer_label(org_id, fact.get("confirmed_by")),
        "confirmed_at": fact.get("confirmed_at"),
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
        "advertising_history": brand.get("advertising_history"),
        "regulatory_regime": brand.get("regulatory_regime"),
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
        # F50 Contract R: the scope pickers list the brand's active knowledge products.
        "products": [{"id": p["id"], "name": p["name"]}
                     for p in repo.knowledge_products(web.conn, brand_id)],
        "facts": [_fact_shape(brand_id, f, brand["org_id"]) for f in facts],
        "rules": [_rule_shape(brand_id, r) for r in repo.list_rules_for_brand(web.conn, brand_id)],
        "claims": [_claim_shape(brand_id, c) for c in repo.list_claims_for_brand(web.conn, brand_id)],
        "assets": [_asset_shape(brand_id, a) for a in repo.list_official_assets(web.conn, brand_id)],
        "channels": [_channel_shape(c) for c in repo.list_channels(web.conn, brand_id)],
        "customer_voices": [_customer_voice_shape(v)
                             for v in repo.list_customer_voices(web.conn, brand_id)],
        "customer_voice_jobs": _cv_recent_jobs(web.conn, brand_id),
    }
    return {"data": data, "generated_at": now_iso()}


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
    if file.size:  # the size is known before the body is read: refuse an oversize file now
        try:
            input_rules.check_upload(file.filename or "", file.size, path=_UPLOAD_PATH)
        except input_rules.InputRuleError as exc:
            return JSONResponse({"detail": str(exc)}, status_code=400)
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
    except input_rules.InputRuleError as exc:
        return JSONResponse({"errors": {"channel_type": str(exc)}}, status_code=400)
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
# 顧客原話貼入＋AI 抽取：background.customer_voice_extraction 佇列工作＋JSON 輪詢
# （S5.40–S5.42，五鐵則③生成不擋路；票 08：從行程內 thread＋dict 搬上
# `app.background` 佇列，見 docs/contracts/background.md）。
#
# 每次貼入都是一筆新內容、天生不重複，`job_key` 用 new_id() 現生一個就夠，本身不需要
# 「同一個 key 已經在跑就不重新啟動」那道冪等閘——`enqueue()` 的 `lock` 用 job_key
# 組成，保證獨一無二，不會擋到任何一次合法送出。
# ---------------------------------------------------------------------------


def background_customer_voice_extraction(org_id: str, brand_id: str, job_key: str, actor: str,
                                          raw_text: str, source_channel: str,
                                          source_detail: str | None) -> None:
    """procrastinate task body（`background.customer_voice_extraction`）——worker 執行，
    自己開一條連線（worker 不繼承 request 的連線）。"""
    with core_db_connection() as conn:
        error = None
        try:
            ok, result = extract(
                conn, brand_id, actor=actor, raw_text=raw_text, source_channel=source_channel,
                source_detail=source_detail, job_key=job_key,
            )
        except Exception as exc:  # noqa: BLE001 — 先寄失敗通知，再往上丟讓 job 記成失敗
            conn.rollback()  # 失敗的交易先收掉，通知才寫得進去
            ok, result, error = False, f"背景執行發生未預期錯誤：{exc}", exc

        channel_label = md.customer_voice_channel_label(source_channel)
        if ok:
            n = len(result["extraction"])
            message = core_interrupts.notice(
                f"原話分析完成，{f'找到 {n} 條重點' if n else '沒有找到重點'}", channel_label)
        else:
            message = core_interrupts.notice("原話分析失敗，可以重試", channel_label)
        background_job.notify(
            conn, brand_id, category="customer_voice_extraction_done", dedupe_key=job_key,
            message=message, action_url=app_path(f"/brands/{brand_id}/library"),
        )
        if error is not None:
            raise error  # Contract J：job 結局要是 failed，狀態端點才不會讀成還在跑


_CV_TASK_SQL = (
    "SELECT * FROM llm_task WHERE brand_id = %s AND task_type = 'customer_voice_extraction' "
    "AND context_scope_json->>'job_key' = %s ORDER BY started_at DESC LIMIT 1"
)
#: F50-I07 (other F10): how far back the library payload lists customer-voice jobs.
CV_RECENT_JOBS_HOURS = 24
_CV_TASK_NAME = "background.customer_voice_extraction"


def _cv_lock(job_key: str) -> str:
    return f"customer_voice_extraction:{job_key}"


def _cv_status_from(conn, brand_id: str, job_key: str, row) -> dict:
    """One customer-voice job's status from its queue outcome and its newest `llm_task` row
    (F50-I07, Contract J): `background.job_state()` decides running／failed／unknown; a
    succeeded row still has to have produced a stored customer voice."""
    state = background_job_state(_cv_lock(job_key), row)
    if state["status"] in ("running", "unknown"):
        return {"status": state["status"]}
    if state["status"] in ("failed", "empty") or row is None or row["status"] != "succeeded":
        return {"status": "failed", "message": state["error"] or JOB_FAILED_MESSAGE}
    cv = repo.get_customer_voice_by_llm_task_id(conn, brand_id, row["id"])
    if cv is None:
        # llm_task 成功但抽取結果解析／驗證失敗（誠實失敗，沒有入庫）——見 extract()。
        return {"status": "failed", "message": PARSE_FAIL_MESSAGE}
    return {"status": "done", "result": _customer_voice_shape(cv)}


def _cv_job_status(conn, brand_id: str, job_key: str) -> dict:
    """讀 llm_task 取代讀行程內 dict（票 08）：`job_key` 存在 `context_scope_json`
    裡（見 `extract()`），這裡反查最新一列。

    F50-I07（Contract J）：佇列還在排／在跑＝running；失敗＝failed（這次呼叫留下失敗列就
    引用它的錯誤，否則講背景程式）；沒有 job 也沒有列＝`unknown`（不再猜「還在跑」）。"""
    row = conn.execute(_CV_TASK_SQL, (brand_id, job_key)).fetchone()
    return _cv_status_from(conn, brand_id, job_key, row)


def _cv_queued_job_keys(brand_id: str) -> list[str]:
    """The brand's customer-voice jobs still waiting or running on the queue (F50-I16): a job
    the worker has not picked up yet has no `llm_task` row, so the queue is its only trace."""
    snapshot = background_queue_snapshot(since=now_utc())
    return [job["args"]["job_key"] for job in snapshot["jobs"]
            if job["task_name"] == _CV_TASK_NAME and job["args"].get("brand_id") == brand_id
            and job["args"].get("job_key")]


def _cv_recent_jobs(conn, brand_id: str) -> list:
    """F50-I07 (other F10): the brand's customer-voice jobs of the last 24 h, newest per
    `job_key`, as `[{job_key, status, error, started_at}]` (newest first) — so a reload still
    shows a job that is running or failed. F50-I16: jobs still queued (no AI call yet, so no
    `llm_task` row) are listed too, read through `background.job_state` (`started_at` = when it
    was queued), so a reload right after 送出 still shows the job."""
    rows = conn.execute(
        "SELECT DISTINCT ON (context_scope_json->>'job_key') * FROM llm_task"
        " WHERE brand_id = %s AND task_type = 'customer_voice_extraction'"
        " AND context_scope_json->>'job_key' IS NOT NULL AND started_at >= %s"
        " ORDER BY context_scope_json->>'job_key', started_at DESC",
        (brand_id, now_utc() - timedelta(hours=CV_RECENT_JOBS_HOURS)),
    ).fetchall()
    jobs = []
    for row in rows:
        job_key = row["context_scope_json"]["job_key"]
        status = _cv_status_from(conn, brand_id, job_key, row)
        jobs.append({"job_key": job_key, "status": status["status"],
                     "error": status.get("message"), "started_at": row["started_at"]})
    listed = {job["job_key"] for job in jobs}
    for job_key in _cv_queued_job_keys(brand_id):
        if job_key in listed:
            continue
        listed.add(job_key)
        state = background_job_state(_cv_lock(job_key), None)
        # Finished between the two reads: its stored row decides, like the status endpoint.
        status = ({"status": "running"} if state["status"] == "running"
                  else _cv_job_status(conn, brand_id, job_key))
        jobs.append({"job_key": job_key, "status": status["status"],
                     "error": status.get("message"), "started_at": state["started_at"]})
    oldest = datetime.min.replace(tzinfo=UTC)
    jobs.sort(key=lambda job: job["started_at"] or oldest, reverse=True)
    return jobs


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
    try:  # checked before the paid extraction; the writer runs the same check
        md.require("customer_voice_source", source_channel)
    except input_rules.InputRuleError as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)
    if not raw_text:
        return JSONResponse({"error": "請貼上顧客的原文內容。"}, status_code=400)

    budget_err = core_settings.budget_exceeded_message(
        web.conn, brand_id, cv_mod.COST_CUSTOMER_VOICE_EXTRACTION, org_id=actor.org_id,
        action="這次顧客原話分析", fallback_hint="或稍後再試。",
    )
    if budget_err:
        return JSONResponse({"error": budget_err}, status_code=422)

    job_key = new_id("cvjob")
    background_enqueue(
        _CV_TASK_NAME, org_id=actor.org_id,
        lock=_cv_lock(job_key), brand_id=brand_id, job_key=job_key,
        actor=str(actor.user_id), raw_text=raw_text, source_channel=source_channel,
        source_detail=source_detail,
    )
    return {"job_key": job_key}


@router.get("/api/library/brands/{brand_id}/customer-voice/jobs/{job_key}")
def customer_voice_job_status(request: Request, brand_id: str, job_key: str):
    actor = require_actor(request)
    require_brand(brand_id, actor)
    return _cv_job_status(web.conn, brand_id, job_key)
