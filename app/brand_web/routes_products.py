"""app/brand_intelligence/routes_products.py — 產品清單＋產品詳情 JSON API（票 B2-products
第二段，契約 `.scratch/grill/GRILL-B2-products.md`，型別逐欄對照 `frontend/src/lib/productsApi.ts`）。

`app/brand_intelligence/routes.py`／`repository.py` 兩檔都已頂到 `docs/tech-debt.md` 凍結的
行數上限，新路由不得再往那兩個檔案加（CLAUDE.md 第五節：超標檔案先拆再加）。本票新增的
路由全部放這個新檔案，寫法比照上一票的 `routes_library.py`：

1. `GET /api/products/brands/{brand_id}`：產品清單概況（S6.2）。
2. `POST /api/products/brands/{brand_id}`：手動新增產品（S6.9），沿用 `repo.create_product`。
3. `POST /api/products/brands/{brand_id}/research`：AI 調研新增（S6.10–S6.11）——同步建立產品
   （拿不準的點 1，`docs/ui-migration-contract.md` 第五節已裁決採方案 A：先建產品、背景調研、
   失敗留空產品可手動刪），背景跑調研。
4. `GET /api/products/brands/{brand_id}/products/{product_id}`：詳情整包（四分頁一次帶回，
   跟 S5 品牌智庫同一個「整包讀」決定，見 `libraryApi.ts` 檔頭）。
5. 背景調研狀態機（S6.29–S6.31；票 08：從行程內 dict＋`threading.Thread` 搬上
   `app.background` 佇列，見 `docs/contracts/background.md`）——新建與再次調研共用
   同一套：key＝`product_id`，procrastinate 的 `queueing_lock` 擋還在 `todo` 階段的
   重複按，`llm_task` 的 `running` 列擋 worker 已經在處理那一次的重複按。
6. 產品事實／經濟數字／規則／宣稱／交接包／永久刪除，一律重用既有的私有工具函式與
   `repository.py` 既有的 CRUD 函式——不重寫第二份業務邏輯，這裡只負責重新包一層 JSON 殼。
   `_create_source_ref` 仍在 `app/brand_web/routes.py`（那裡的品牌事實／規則／宣稱舊表單
   handler 也在用）；`_scan_budget_error`／`_apply_product_scan_result`／
   `_product_handoff_prompt` 三支只剩本檔在用，T4 刪品牌／產品管理舊頁時搬進
   `app/brand_web/routes_product_helpers.py`。

對外進入點：本檔的 `router`（`app/main.py` 直接 `include_router`）。誰依賴它：只有
`app/main.py`。
"""

from datetime import UTC, datetime

from fastapi import APIRouter, Request
from fastapi.responses import Response

from app.background import JOB_FAILED_MESSAGE
from app.background import enqueue as background_enqueue
from app.background import is_active as background_is_active
from app.background import job_outcome as background_job_outcome
from app.brand_intelligence import background_job, product_ai
from app.brand_intelligence import repository as repo
from app.brand_web import product_ai_calls
from app.brand_web import routes as legacy_routes
from app.brand_web import routes_product_helpers as product_helpers
from app.core import cleanup
from app.core import vocab as md
from app.core.db import connection as core_db_connection
from app.core.db import new_id
from app.llm import gateway
from app.shared import web
from app.shared.web import (
    JSONResponse,
    NotFoundKind,
    clean,
    require_actor,
    require_brand,
    require_product,
)

router = APIRouter()

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


def _str_field(body: dict, key: str) -> str:
    v = body.get(key)
    return v if isinstance(v, str) else ""


def _num_field(body: dict, key: str):
    """回傳 (value, ok)：JSON 數字型別才算合法，字串／布林／缺漏一律回 (None, False)。"""
    v = body.get(key)
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return None, False
    return float(v), True


# ---------------------------------------------------------------------------
# 產品事實／經濟數字／規則／宣稱的 JSON 顯示形狀（比照 routes_library.py 的 _fact_shape
# 等寫法，欄位集合各自對照 productsApi.ts 的型別，跟品牌智庫那份欄位不完全相同、不共用）。
# ---------------------------------------------------------------------------

def _source_ref_text(brand_id: str, source_reference_id: str | None) -> str | None:
    if not source_reference_id:
        return None
    row = repo.get_source_reference(web.conn, brand_id, source_reference_id)
    return row["title"] if row else None


def _fact_shape(brand_id: str, fact: dict) -> dict:
    return {
        "id": fact["id"], "fact_type": fact["fact_type"],
        "fact_type_label": md.product_fact_type_label(fact["fact_type"]),
        "label": fact["label"], "value": fact["value"], "status": fact["status"],
        "confirmed_by": fact.get("confirmed_by"), "confirmed_at": fact.get("confirmed_at"),
        "source_reference": _source_ref_text(brand_id, fact.get("source_reference_id")),
    }


def _economics_shape(economics: dict) -> dict:
    return {
        "selling_price": economics["selling_price"], "fixed_cost": economics["fixed_cost"],
        "unit_variable_cost": economics["unit_variable_cost"], "shipping_cost": economics["shipping_cost"],
        "currency": economics["currency"],
        "effective_from": economics["effective_from"], "status": economics["status"],
        "confirmed_by": economics["confirmed_by"],
        "close_rate": economics["close_rate"],
        "assumptions": economics.get("assumptions_json") or [],
    }


def _rule_shape(rule: dict) -> dict:
    return {
        "id": rule["id"], "severity": rule["severity"], "rule_type": rule["rule_type"],
        "rule_type_label": md.rule_type_label(rule["rule_type"]), "content": rule["content"],
        "product_id": rule["product_id"],
    }


def _claim_shape(brand_id: str, claim: dict) -> dict:
    return {
        "id": claim["id"], "claim_type": claim["claim_type"], "claim_text": claim["claim_text"],
        "evidence_source_reference": _source_ref_text(brand_id, claim.get("evidence_source_reference_id")),
        "product_id": claim["product_id"],
    }


def _product_list_item(brand_id: str, product: dict) -> dict:
    facts = repo.list_product_facts(web.conn, brand_id, product["id"])
    pending = sum(1 for f in facts if f["status"] == "pending")
    economics = repo.get_product_economics(web.conn, brand_id, product["id"])
    return {
        "id": product["id"], "name": product["name"], "status": product["status"],
        "parent_id": product["parent_id"],
        "fact_count": len(facts), "pending_fact_count": pending,
        "economics_status": economics["status"] if economics else "none",
    }


# ---------------------------------------------------------------------------
# 產品清單
# ---------------------------------------------------------------------------

@router.get("/api/products/brands/{brand_id}")
def product_list(request: Request, brand_id: str):
    actor = require_actor(request)
    require_brand(brand_id, actor)
    products = web.list_products(brand_id)
    return _envelope([_product_list_item(brand_id, p) for p in products])


@router.post("/api/products/brands/{brand_id}")
async def product_create(request: Request, brand_id: str):
    """S6.9 手動新增：純同步、不花錢，沿用 `repo.create_product`（既有 `product_new_post`
    邏輯，source_url 這顆表單本來就只給旁邊的 AI 調研按鈕用，手動建立不記錄網址，
    跟搬家前的行為一致）。"""
    actor = require_actor(request)
    require_brand(brand_id, actor)
    body = await _json_body(request)
    name_c = clean(_str_field(body, "name"))
    if not name_c:
        return _error(400, "請填寫產品名稱。")
    product = repo.create_product(web.conn, brand_id, name=name_c, actor=str(actor.user_id))
    return {"id": product["id"]}


# ---------------------------------------------------------------------------
# AI 調研新增與再次調研（`background.product_scan` 佇列工作，S6.10–S6.11／S6.17／
# S6.29–S6.31；票 08：從行程內 dict＋thread 搬上 app.background 佇列，見
# docs/contracts/background.md）。兩個入口共用同一套：key＝product_id。round 1 上線後
# 用 llm_task 的 running 列擋「worker 已經在處理那一次」被獨立審查抓到會漏——worker 撿走
# 到真的打 provider 之間那一段，llm_task 完全沒有列可以讀，第二次按下去會被誤判成「沒在
# 跑」而放行，兩邊都真的付了錢（票 08「Blocked」節）。round 2 改問
# `app/background.is_active(lock)`：它直接讀 procrastinate 自己的佇列表，這個 lock 名下
# 只要還有列卡在 `todo` 或 `doing` 就算在跑，覆蓋 llm_task 看不到的那一段窗口；
# `background_enqueue()` 的 `queueing_lock` 唯一索引仍然是第二層防線（擋 `is_active()`
# 讀取之後、`enqueue()` 真正寫入之前那一瞬間的競態）。
#
# 超預算檢查（`_scan_budget_error`）搬到 POST 端點同步做，不再放進背景工作裡：
# 佇列讀寫只認 llm_task，而「還沒排進去就先擋下」的失敗天生不會有那一列可以讀
# （`gateway.run_task()` 命中花費上限時故意不寫任何列，見該函式檔頭），沒有第二個
# 地方能誠實回報這個原因，所以檢查提前到 enqueue 之前——跟 `app/schedule/routes.py`
# `_run_plan()`／customer_voice_submit() 同一個次序。
# ---------------------------------------------------------------------------

_RESEARCH_USUAL_RANGE = "30 到 60 秒"
ALREADY_RESEARCHING_MESSAGE = "上一次還在跑，請等它跑完再按。"


def _research_state(conn, brand_id: str, product_id: str) -> dict:
    """讀 llm_task 取代讀行程內 dict（票 08）：`product_id` 存在
    `context_scope_json` 裡（見 `background_product_scan()`），這裡反查最新一列。
    逐步進度（讀取網址中→整理事實中→完成）比照票面決定放棄，running／failed 一律
    回固定字串；`added_count`／`price_created` 這兩個彙總數字沒有地方可以在執行
    結束後還讀得到（不是 llm_task 欄位，也不新增 schema），保留鍵與型別、值固定回
    None／False——前端 `ProductDetailPage.tsx` 的 `done` 分支本來就不讀這兩個值
    （轉成功就整包重新 `load()`），這裡是有回報過的簡化，不是悄悄近似。

    F31 Contract J 先看佇列：最新的 job 還在排／在跑＝running（即使有舊的 llm_task 列）；
    最新的 job 失敗＝failed（沒有那次呼叫的錯誤可引用時講背景程式）。其餘照 llm_task 列。"""
    row = conn.execute(
        "SELECT * FROM llm_task WHERE brand_id = %s AND task_type = 'product_scan' "
        "AND context_scope_json->>'product_id' = %s ORDER BY started_at DESC LIMIT 1",
        (brand_id, product_id),
    ).fetchone()
    outcome = background_job_outcome(f"product_scan:{product_id}")
    if outcome == "active":
        running_row = row is not None and row["status"] == "running"
        return {"status": "running", "stage": "讀取網址中",
                "started_at": row["started_at"] if running_row else datetime.now(UTC).isoformat(),
                "usual_range_text": _RESEARCH_USUAL_RANGE, "error": None, "added_count": None,
                "price_created": False}
    if outcome == "failed":
        own_error = row is not None and row["status"] not in ("running", "succeeded") and row["error"]
        return {"status": "failed", "stage": "整理事實中",
                "started_at": row["started_at"] if row is not None else datetime.now(UTC).isoformat(),
                "usual_range_text": _RESEARCH_USUAL_RANGE,
                "error": row["error"] if own_error else JOB_FAILED_MESSAGE,
                "added_count": None, "price_created": False}
    if row is None:
        return {"status": "done", "stage": "", "started_at": datetime.now(UTC).isoformat(),
                "usual_range_text": "", "error": None, "added_count": None, "price_created": False}
    if row["status"] == "running":
        return {"status": "running", "stage": "讀取網址中", "started_at": row["started_at"],
                "usual_range_text": _RESEARCH_USUAL_RANGE, "error": None, "added_count": None,
                "price_created": False}
    if row["status"] == "succeeded":
        result = product_ai._validate_scan_reply(gateway.parse_json_reply(row["rendered_output"]))
        if result is not None:
            return {"status": "done", "stage": "完成", "started_at": row["started_at"],
                    "usual_range_text": _RESEARCH_USUAL_RANGE, "error": None, "added_count": None,
                    "price_created": False}
        error = product_ai_calls.PARSE_FAIL_MESSAGE  # llm_task 成功但抽取結果驗證失敗
    else:
        error = row["error"]
    return {"status": "failed", "stage": "整理事實中", "started_at": row["started_at"],
            "usual_range_text": _RESEARCH_USUAL_RANGE, "error": error, "added_count": None,
            "price_created": False}


def _research_notify(conn, brand_id: str, product_id: str, message: str) -> None:
    background_job.notify(
        conn, brand_id, category="product_research_done", dedupe_key=new_id("prsjob"),
        message=message, action_url=f"/app/brands/{brand_id}/products/{product_id}",
    )


def background_product_scan(org_id: str, brand_id: str, product_id: str, actor: str,
                             product_name: str, url: str) -> None:
    """procrastinate task body（`background.product_scan`）——worker 執行，自己開一條
    連線（worker 不繼承 request 的連線）。超預算已經在 POST 端點同步擋過，這裡不重查。"""
    with core_db_connection() as conn:
        error, added = None, 0
        try:
            brand_facts = repo.list_brand_facts(conn, brand_id, status="confirmed")
            ok, result = product_ai_calls.run_product_scan(
                conn, brand_id, product_id, product_name, url, brand_facts)
            if ok:
                # F31-I02：套用結果也在防線裡——AI 成功但落地失敗時要寄失敗通知、job 記失敗
                src_id = legacy_routes._create_source_ref(brand_id, actor, url)
                added, _skipped, _price_created = product_helpers._apply_product_scan_result(
                    brand_id, product_id, actor, src_id, result)
        except Exception as exc:  # noqa: BLE001 — 先寄失敗通知，再往上丟讓 job 記成失敗
            conn.rollback()  # 失敗的交易先收掉，通知才寫得進去
            ok, error = False, exc
        if not ok:
            _research_notify(conn, brand_id, product_id, f"「{product_name}」調研失敗，可以重試")
            if error is not None:
                raise error  # Contract J：job 結局要是 failed，狀態端點才不會讀成完成
            return
        _research_notify(conn, brand_id, product_id, f"「{product_name}」調研完成，新增 {added} 條待確認")


_URL_FORMAT_ERROR = "這個網址看起來不完整，記得從 https:// 開始，例如「https://example.com/products/xxx」。"


def _valid_url(url: str) -> bool:
    return url.startswith("http://") or url.startswith("https://")


@router.post("/api/products/brands/{brand_id}/research")
async def product_research_start(request: Request, brand_id: str):
    actor = require_actor(request)
    require_brand(brand_id, actor)
    body = await _json_body(request)
    name_c = clean(_str_field(body, "name"))
    url_c = clean(_str_field(body, "source_url"))
    if not name_c:
        return _error(400, "請填寫產品名稱。")
    if not url_c:
        return _error(400, "請填寫產品頁網址，才能請 AI 幫忙調研；不填網址請改用「新增這個產品」。")
    if not _valid_url(url_c):
        return _error(400, _URL_FORMAT_ERROR)
    product = repo.create_product(web.conn, brand_id, name=name_c, actor=str(actor.user_id))
    budget_err = product_helpers._scan_budget_error(brand_id)
    if budget_err:
        return _error(422, budget_err)
    background_enqueue(
        "background.product_scan", org_id=actor.org_id, lock=f"product_scan:{product['id']}",
        brand_id=brand_id, product_id=product["id"], actor=str(actor.user_id),
        product_name=name_c, url=url_c,
    )
    return JSONResponse({"product_id": product["id"]}, status_code=202)


@router.post("/api/products/brands/{brand_id}/products/{product_id}/rescan")
async def product_rescan_start(request: Request, brand_id: str, product_id: str):
    actor = require_actor(request)
    brand = require_brand(brand_id, actor)
    product = require_product(brand, product_id)
    body = await _json_body(request)
    url_c = clean(_str_field(body, "source_url"))
    if not url_c:
        return _error(400, "請填寫網址，才能請 AI 再次調研。")
    if not _valid_url(url_c):
        return _error(400, _URL_FORMAT_ERROR)
    budget_err = product_helpers._scan_budget_error(brand_id)
    if budget_err:
        return _error(422, budget_err)
    lock = f"product_scan:{product_id}"
    if background_is_active(lock):
        return _error(409, ALREADY_RESEARCHING_MESSAGE)
    if not background_enqueue(
        "background.product_scan", org_id=actor.org_id, lock=lock,
        brand_id=brand_id, product_id=product_id, actor=str(actor.user_id),
        product_name=product["name"], url=url_c,
    ):
        return _error(409, ALREADY_RESEARCHING_MESSAGE)
    return JSONResponse({}, status_code=202)


@router.get("/api/products/brands/{brand_id}/products/{product_id}/research-status")
def product_research_status(request: Request, brand_id: str, product_id: str):
    actor = require_actor(request)
    brand = require_brand(brand_id, actor)
    require_product(brand, product_id)
    return _envelope(_research_state(web.conn, brand_id, product_id))


# ---------------------------------------------------------------------------
# 產品詳情（整包，S6.15–S6.39）
# ---------------------------------------------------------------------------

@router.get("/api/products/brands/{brand_id}/products/{product_id}")
def product_detail(request: Request, brand_id: str, product_id: str):
    actor = require_actor(request)
    brand = require_brand(brand_id, actor)
    product = require_product(brand, product_id)
    facts = repo.list_product_facts(web.conn, brand_id, product_id)
    facts_pending = sum(1 for f in facts if f["status"] == "pending")
    economics = repo.get_product_economics(web.conn, brand_id, product_id)
    rules = repo.list_rules_for_product(web.conn, brand_id, product_id)
    claims = repo.list_claims_for_product(web.conn, brand_id, product_id)
    cards = [
        {"key": "facts", "title": "產品事實", "count": len(facts), "pending": facts_pending},
        {"key": "economics-view", "title": "產品經濟數字",
         "count": 1 if economics else 0,
         "pending": 1 if economics and economics["status"] == "pending" else 0},
        {"key": "rules", "title": "適用規則", "count": len(rules), "pending": 0},
        {"key": "claims", "title": "適用宣稱", "count": len(claims), "pending": 0},
    ]
    data = {
        "id": product["id"], "brand_id": brand_id, "name": product["name"],
        "status": product["status"], "knowledge_version": product["knowledge_version"],
        "cards": cards,
        "latest_source_url": repo.get_latest_product_source_url(web.conn, brand_id, product_id),
        "economics_pending": bool(economics and economics["status"] == "pending"),
        "facts": [_fact_shape(brand_id, f) for f in facts],
        "economics": _economics_shape(economics) if economics else None,
        "rules": [_rule_shape(r) for r in rules],
        "claims": [_claim_shape(brand_id, c) for c in claims],
    }
    return _envelope(data)


@router.post("/api/products/brands/{brand_id}/products/{product_id}/archive")
def product_archive(request: Request, brand_id: str, product_id: str):
    actor = require_actor(request)
    brand = require_brand(brand_id, actor)
    product = require_product(brand, product_id)
    new_status = "archived" if product["status"] == "active" else "active"
    try:
        repo.update_product(web.conn, brand_id, product_id, name=product["name"], status=new_status,
                            actor=str(actor.user_id))
    except ValueError as exc:
        # F36-I10: restore collided with an active same-name product (partial unique index,
        # surfaced by the repository as ValueError("已有同名產品")).
        return _error(409, str(exc))
    return Response(status_code=204)


# ---------------------------------------------------------------------------
# 產品事實（S6.24–S6.27）
# ---------------------------------------------------------------------------

@router.post("/api/products/brands/{brand_id}/products/{product_id}/facts")
async def product_fact_create(request: Request, brand_id: str, product_id: str):
    actor = require_actor(request)
    brand = require_brand(brand_id, actor)
    require_product(brand, product_id)
    body = await _json_body(request)
    fact_type = clean(_str_field(body, "fact_type"))
    label = clean(_str_field(body, "label"))
    value = clean(_str_field(body, "value"))
    status = _str_field(body, "status") or "pending"
    if not fact_type:
        return _error(400, "請選擇這是哪一類產品事實。")
    if not label:
        return _error(400, "請填寫這條事實的名稱。")
    if not value:
        return _error(400, "請填寫事實內容。")
    if status not in ("confirmed", "pending"):
        return _error(400, "請選擇是否已經確認過。")
    src_id = legacy_routes._create_source_ref(brand_id, str(actor.user_id), _str_field(body, "source_reference"))
    confirmed_by = str(actor.user_id) if status == "confirmed" else None
    repo.create_product_fact(web.conn, brand_id, product_id, actor=str(actor.user_id), fact_type=fact_type,
                              label=label, value=value, status=status, source_reference_id=src_id,
                              confirmed_by=confirmed_by)
    return Response(status_code=204)


@router.post("/api/products/brands/{brand_id}/products/{product_id}/facts/{fact_id}")
async def product_fact_edit(request: Request, brand_id: str, product_id: str, fact_id: str):
    actor = require_actor(request)
    brand = require_brand(brand_id, actor)
    require_product(brand, product_id)
    fact = repo.get_product_fact(web.conn, brand_id, product_id, fact_id)
    if not fact:
        raise NotFoundKind("產品事實")
    body = await _json_body(request)
    fact_type = clean(_str_field(body, "fact_type"))
    label = clean(_str_field(body, "label"))
    value = clean(_str_field(body, "value"))
    if not fact_type:
        return _error(400, "請選擇這是哪一類事實。")
    if not label:
        return _error(400, "請填寫這條事實的名稱。")
    if not value:
        return _error(400, "請填寫事實內容。")
    src_id = (legacy_routes._create_source_ref(brand_id, str(actor.user_id), _str_field(body, "source_reference"))
              or fact["source_reference_id"])
    repo.update_product_fact(web.conn, brand_id, product_id, fact_id, actor=str(actor.user_id),
                              fact_type=fact_type, label=label, value=value, source_reference_id=src_id)
    return Response(status_code=204)


@router.post("/api/products/brands/{brand_id}/products/{product_id}/facts/{fact_id}/confirm")
async def product_fact_confirm(request: Request, brand_id: str, product_id: str, fact_id: str):
    actor = require_actor(request)
    brand = require_brand(brand_id, actor)
    require_product(brand, product_id)
    fact = repo.get_product_fact(web.conn, brand_id, product_id, fact_id)
    if not fact:
        raise NotFoundKind("產品事實")
    body = await _json_body(request)
    confirmed_by = clean(_str_field(body, "confirmed_by")) or "使用者"
    repo.confirm_product_fact(web.conn, brand_id, product_id, fact_id, confirmed_by=confirmed_by, actor=str(actor.user_id))
    return Response(status_code=204)


@router.post("/api/products/brands/{brand_id}/products/{product_id}/facts/{fact_id}/delete")
def product_fact_delete(request: Request, brand_id: str, product_id: str, fact_id: str):
    actor = require_actor(request)
    brand = require_brand(brand_id, actor)
    require_product(brand, product_id)
    fact = repo.get_product_fact(web.conn, brand_id, product_id, fact_id)
    if not fact:
        raise NotFoundKind("產品事實")
    repo.delete_product_fact(web.conn, brand_id, fact_id, actor=str(actor.user_id))
    return Response(status_code=204)


# ---------------------------------------------------------------------------
# 產品經濟數字（S6.32–S6.35）
# ---------------------------------------------------------------------------

@router.post("/api/products/brands/{brand_id}/products/{product_id}/economics")
async def economics_save(request: Request, brand_id: str, product_id: str):
    actor = require_actor(request)
    brand = require_brand(brand_id, actor)
    require_product(brand, product_id)
    body = await _json_body(request)
    price_val, price_ok = _num_field(body, "selling_price")
    if not price_ok:
        return _error(400, "售價請填數字，例如 1280。")
    fixed_val, fixed_ok = _num_field(body, "fixed_cost")
    if not fixed_ok:
        return _error(400, "固定成本請填數字，例如 0。")
    unit_val, unit_ok = _num_field(body, "unit_variable_cost")
    if not unit_ok:
        return _error(400, "單位變動成本請填數字，例如 430。")
    ship_val, ship_ok = _num_field(body, "shipping_cost")
    if not ship_ok:
        return _error(400, "運費請填數字，例如 60。")
    currency = clean(_str_field(body, "currency"))
    if not currency:
        return _error(400, "請選擇幣別。")
    confirmed_by = clean(_str_field(body, "confirmed_by"))
    if not confirmed_by:
        return _error(400, "請填寫確認人是誰。")
    close_rate_raw = body.get("close_rate")
    close_rate_val = None
    if close_rate_raw is not None:
        if isinstance(close_rate_raw, bool) or not isinstance(close_rate_raw, (int, float)) \
                or not (0 < close_rate_raw <= 1):
            return _error(400, "成交率請填 0 到 1 之間的數字，例如 0.2 代表五筆名單成交一筆。")
        close_rate_val = float(close_rate_raw)
    assumptions_raw = body.get("assumptions")
    assumptions_val = None
    if assumptions_raw is not None:
        if not isinstance(assumptions_raw, list) or not all(isinstance(v, str) for v in assumptions_raw):
            return _error(400, "assumptions 格式不對。")
        assumptions_val = assumptions_raw
    try:
        repo.save_product_economics(
            web.conn, brand_id, product_id, actor=str(actor.user_id),
            selling_price=price_val, currency=currency, confirmed_by=confirmed_by,
            fixed_cost=fixed_val, unit_variable_cost=unit_val, shipping_cost=ship_val,
            effective_from=clean(_str_field(body, "effective_from")) or None,
            close_rate=close_rate_val, assumptions=assumptions_val,
        )
    except ValueError as exc:
        return _error(400, str(exc))
    return Response(status_code=204)


@router.post("/api/products/brands/{brand_id}/products/{product_id}/economics/confirm")
def economics_confirm(request: Request, brand_id: str, product_id: str):
    actor = require_actor(request)
    brand = require_brand(brand_id, actor)
    require_product(brand, product_id)
    existing = repo.get_product_economics(web.conn, brand_id, product_id)
    if not existing:
        raise NotFoundKind("產品經濟數字")
    repo.confirm_product_economics(web.conn, brand_id, product_id, confirmed_by=str(actor.user_id),
                                    actor=str(actor.user_id))
    return Response(status_code=204)


# ---------------------------------------------------------------------------
# 調研交接包（S6.40–S6.47）：組提示詞、貼回解析，重用 legacy_routes 私有工具與
# product_ai 的解析／修復邏輯，不重寫第二份。
# ---------------------------------------------------------------------------

@router.get("/api/products/brands/{brand_id}/products/{product_id}/handoff")
def handoff_prompt(request: Request, brand_id: str, product_id: str):
    actor = require_actor(request)
    brand = require_brand(brand_id, actor)
    product = require_product(brand, product_id)
    return _envelope({"prompt_text": product_helpers._product_handoff_prompt(brand, product)})


@router.post("/api/products/brands/{brand_id}/products/{product_id}/handoff")
async def handoff_submit(request: Request, brand_id: str, product_id: str):
    actor = require_actor(request)
    brand = require_brand(brand_id, actor)
    product = require_product(brand, product_id)
    body = await _json_body(request)
    reply_text = _str_field(body, "reply_text")
    if not clean(reply_text):
        return _error(400, "請先把外部 AI 的回覆貼進來。")

    result = product_ai_calls.parse_product_handoff_reply(reply_text)
    if result is None:
        budget_err = product_helpers._scan_budget_error(
            brand_id, cost=product_ai.COST_PRODUCT_HANDOFF_FIX, action="請 AI 幫忙整理格式",
            fallback_hint="或先自己把貼上的內容改成正確格式，那樣不用花錢。")
        if budget_err:
            return _error(400, budget_err)
        ok, fixed = product_ai_calls.run_product_handoff_fix(web.conn, brand_id, reply_text)
        if not ok:
            return _error(400, fixed)
        result = fixed

    src_label = f"外部深研交接包・{datetime.now(UTC).date().isoformat()}"
    src_id = legacy_routes._create_source_ref(brand_id, str(actor.user_id), src_label)
    added, _skipped, _price_created = product_helpers._apply_product_scan_result(
        brand_id, product_id, str(actor.user_id), src_id, result)
    return {"added_count": added}


# ---------------------------------------------------------------------------
# 永久刪除產品（S6.49–S6.55）
# ---------------------------------------------------------------------------

@router.get("/api/products/brands/{brand_id}/products/{product_id}/delete")
def delete_impact(request: Request, brand_id: str, product_id: str):
    actor = require_actor(request)
    brand = require_brand(brand_id, actor)
    require_product(brand, product_id)
    rows = cleanup.count_all_product(web.conn, brand_id, product_id)
    return _envelope([{"label": label, "count": n} for label, n in rows if n > 0])


@router.post("/api/products/brands/{brand_id}/products/{product_id}/delete")
async def delete_confirm(request: Request, brand_id: str, product_id: str):
    actor = require_actor(request)
    brand = require_brand(brand_id, actor)
    product = require_product(brand, product_id)
    if product["status"] != "archived":
        return _error(400, "要先把產品封存，才能永久刪除。")
    body = await _json_body(request)
    if clean(_str_field(body, "confirm_name")) != product["name"]:
        return _error(400, "輸入的名稱跟產品名稱不一樣，請照著上面顯示的名稱再打一次。")
    repo.delete_product(web.conn, brand_id, product_id, actor=str(actor.user_id))
    return Response(status_code=204)
