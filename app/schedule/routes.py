"""app/schedule/routes.py — /api/schedule/*. Private: only app/schedule/__init__.py imports
this (container contract §1); it is only ever loaded via `register()`.

票 07：檔期規劃最薄路徑——選產品、確認，拿回一張方案卡。ADR 0028／0029／0032／0033：
部門是 repo 裡的一個資料夾（`app/departments/ads/schedule.md`），外殼原樣把它貼進 prompt，
從不解析；品牌上下文經既有的 `context_compiler.compile()` 組出來；`gateway.run_task()`
是全站唯一的 LLM 入口，這裡不重寫第二個。money 由 `plan.py` 的純函數算，代理只給比例。

`conn` 在下面的私有函式一律不標型別：`web.conn` 是 `ConnProxy`、
`context_compiler.compile()`／`gateway.run_task()`／`repo.get_product()` 三個既有函式簽章
都吃 `Conn`（非 `ConnProxy`），比照 `app/intake/persona_generation.py`／
`app/brand_web/product_ai_calls.py` 既有寫法——`conn` 參數留白讓 pyright 用型別
不定（Unknown）通過，呼叫端只在路由這一層傳入真正的 `web.conn`。
"""

from fastapi import APIRouter, Request
from pydantic import BaseModel

import app.shared.web as web
from app.brand_intelligence import repository as bi_repo
from app.core import rule_cards
from app.core.db import APP_DIR
from app.llm import context_compiler, gateway, methodology, providers
from app.schedule import plan as plan_mod

router = APIRouter(prefix="/api/schedule")

# task_type：providers.py TASK_TYPE_LABELS／TASK_DEFAULTS 的 "schedule_plan"（票 07 settled 段：
# 重新命名死掉的 campaign_plan，不是新增第二個型別）。
TASK_TYPE = "schedule_plan"
# 對照 app/methodology/README.md 既有的「檔期計畫生成」列，不新增列。
METHODOLOGY_TASK_LABELS = ["檔期計畫生成"]
DEPARTMENT_FILE = APP_DIR / "departments" / "ads" / "schedule.md"

# 唯一的供應商實例，比照 app/brand_web/routes_library.py 既有寫法：測試用
# `mock.patch.object(routes, "PROVIDER", FakeProvider(...))` 換掉，不動這裡的呼叫端程式碼。
PROVIDER = providers.AnthropicProvider()


class PlanRequest(BaseModel):
    # 預設空清單，不是必填：租戶界線（require_brand）要先於「選了哪些產品」被檢查，見
    # test_identity_auth.py／test_identity_tenant_routes.py 的全站 sweep（送空 body 也要
    # 先走到 401／404，不能被 pydantic 必填欄位擋在驗證身分之前）——真的沒選產品仍在
    # `_validate_products()` 回人話的 400，不會假裝成功。
    product_ids: list[str] = []


def _latest_task_row(conn, brand_id: str) -> dict | None:
    row = conn.execute(
        "SELECT * FROM llm_task WHERE brand_id = %s AND task_type = %s "
        "ORDER BY started_at DESC LIMIT 1",
        (brand_id, TASK_TYPE),
    ).fetchone()
    return dict(row) if row is not None else None


def _brand_response(conn, brand_id: str) -> dict:
    current_daily_budget = rule_cards.get_value(conn, brand_id, "schedule_budget", "daily_budget")
    row = _latest_task_row(conn, brand_id)
    plan = plan_mod.plan_from_task_row(row) if row is not None else None
    return {"daily_budget": current_daily_budget, "plan": plan}


def _validate_products(conn, brand_id: str, product_ids: list) -> None:
    if not product_ids:
        raise web.ApiError(400, "no_products", "請至少選擇一項產品。")
    for product_id in product_ids:
        if bi_repo.get_product(conn, brand_id, product_id) is None:
            raise web.ApiError(400, "product_not_found", f"找不到產品：{product_id}")


def _compile_brand_context(conn, brand_id: str, product_ids: list) -> tuple:
    """對每個選定產品各跑一次 `context_compiler.compile()`，用空行接起來；`knowledge_item_ids`
    取聯集、保留原順序去重（票 07 settled 段「品牌上下文」）。回傳 (prompt 片段,
    knowledge_item_ids, brand_version)。

    ponytail: 品牌層段落（規則／宣稱／品牌事實）會隨產品數重複出現——每個產品各自一次
    compile()，沒有跨產品去重這件事。這是票 07 明文接受的上限（最薄路徑，先求打通），
    真的因為 prompt 太長而困擾時再考慮把品牌層與產品層拆開各編一次。
    """
    texts, knowledge_item_ids, seen = [], [], set()
    brand_version = None
    for product_id in product_ids:
        text, ids, brand_version, _product_version = context_compiler.compile(
            conn, brand_id, product_id
        )
        texts.append(text)
        for kid in ids:
            if kid not in seen:
                seen.add(kid)
                knowledge_item_ids.append(kid)
    return "\n\n".join(texts), knowledge_item_ids, brand_version


def _run_plan(conn, brand_id: str, product_ids: list) -> dict:
    _validate_products(conn, brand_id, product_ids)

    daily_budget = rule_cards.get_value(conn, brand_id, "schedule_budget", "daily_budget")
    if not daily_budget:
        raise web.ApiError(400, "budget_not_set", plan_mod.BUDGET_NOT_SET_MESSAGE)

    brand_context, knowledge_item_ids, brand_version = _compile_brand_context(
        conn, brand_id, product_ids
    )
    department_text = DEPARTMENT_FILE.read_text(encoding="utf-8")
    methodology_result = methodology.compile(conn, METHODOLOGY_TASK_LABELS, brand_id=brand_id)
    prompt = "\n\n".join(
        section for section in (department_text, methodology_result.text, brand_context) if section
    )

    context = gateway.TaskContext(
        # 預算凍結在跑的當下（票 07 settled 段「No migration」）：之後改規則卡不會悄悄
        # 改寫這張已經出過的方案。
        context_scope={
            "brand_id": brand_id, "product_ids": product_ids, "daily_budget": daily_budget,
        },
        knowledge_item_ids=knowledge_item_ids,
        brand_version=brand_version,
        product_version=None,  # 一次任務跨 N 個產品，這個欄位只吃單一值，見票 07 settled 段
    )
    gateway.run_task(
        conn, PROVIDER, brand_id=brand_id, task_type=TASK_TYPE,
        prompt_template_id=TASK_TYPE, prompt_template_version="v1",
        system=None, messages=[{"role": "user", "content": prompt}], context=context,
    )
    return _brand_response(conn, brand_id)


@router.get("/brands/{brand_id}")
async def get_schedule(request: Request, brand_id: str):
    actor = web.require_actor(request)
    web.require_brand(brand_id, actor)  # 另一個組織的品牌 → 404
    return _brand_response(web.conn, brand_id)


@router.post("/brands/{brand_id}/plans")
async def create_plan(request: Request, brand_id: str, body: PlanRequest):
    actor = web.require_actor(request)
    web.require_brand(brand_id, actor)  # 另一個組織的品牌 → 404
    return _run_plan(web.conn, brand_id, body.product_ids)
