# -*- coding: utf-8 -*-
"""app/ads/routes_quick_generate.py — 快速生成端點（票 01-quick-generate-endpoint／G12）。

素材工作檯「快速生成」：不開檔期、不用切角格，選一個類型（完整貼文／完整影片／單張圖片／
單則腳本）＋可選套用某個既有產品＋打一句話重點，直接呼叫既有生成引擎產出結果——**不落地**
（`creative_theme.campaign_cycle_id`／`experiment_cell_id` 皆 `NOT NULL`，硬塞假值會污染
真實檔期資料，見 app/ads/migrations/0015_creative_theme.sql；理由詳見票 Implementation
Decisions「不落地」一節），端點回應即棄，不寫入任何資料表。

跟矩陣頁生成（app/ads/routes_creative_theme.py generate_theme()）共用同一套引擎（AI 呼叫、
花費上限查核、`app.creative` 純函式），差異只在三點：①沒有真實檔期／切角格，簡報用最小值
組（brand_context／methodology／customer_voice／rejection_constraints 照常查，cycle／
generation_scope 留空，cell 只放 topic 與 product_id）；②沒有行銷目標，欄位數量直接讀
`FORMAT_SPECS` 原始定義（`app.creative.theme_engine.build_quick_generate_plan`），不查
`*_fields_plan(objective)`；③產出後只回傳 `QUICK_GENERATE_SCOPES[scope]["fields"]` 那個
子集（title／description 一律不回，四類都不含，使用者明確排除）。

呼叫 `build_single_image_prompt()`／`normalize_single_image()`（單圖引擎）與
`build_video_prompt()`／`normalize_video()`（影片引擎）時仍照這兩支函式既有的介面傳「全
欄位」plan（`FORMAT_SPECS[base_format]["fields"]`，本來就是它們的既有介面契約，改成只傳
子集會在組 prompt 時對不存在的鍵 KeyError）——AI 因此仍會產出 title／description，只是
這裡收到後就地過濾掉，不回給呼叫端。

ponytail：多花一點 AI 產出（title／description 生完即丟）換取「零改動既有引擎介面」——
兩支函式目前只有這一種呼叫端會傳窄 plan，沒有第二個真實需求前不替它們加「部分欄位」模式；
未來若要精簡成本，再回頭把 build_single_image_prompt／build_video_prompt 改成依 plan 缺鍵
自動略過對應段落。

不做字數守門（over_budget_items／apply_char_rewrites）與相似度標黃（apply_similarity_flag）
——票 Implementation Decisions 沒有列這兩項，且「不落地」代表沒有同格既有主題可比對相似度，
相似度標黃在這裡本來就是空操作。

對外進入點：`router`（`POST /api/creative/brands/{brand_id}/quick-generate` 生成本體，
`GET /api/creative/brands/{brand_id}/products` 給產品 pills 用，兩支都掛進 app/ads/routes.py）。
誰依賴它：素材工作檯前端快速生成入口（frontend/src/components/workbench/QuickGenerate.tsx）。
"""

from fastapi import APIRouter, Request
from app.shared.web import JSONResponse

import app.shared.web as main_mod
from app.ads import compliance
from app.ads import fingerprint as fp
from app.ads import theme_engine
from app.ads.brief_assembler import CreativeBrief
from app.ads.creative import METHODOLOGY_TASK_LABELS, _customer_voice_block, _rejection_constraints
from app.core import settings as coresettings
from app.creative import theme_engine as core_theme_engine
from app.creative import theme_engine_video as core_theme_engine_video
from app.creative.format_specs import FORMAT_SPECS, QUICK_GENERATE_SCOPES
from app.llm import context_compiler, gateway, methodology, pricing, providers

router = APIRouter(prefix="/api/creative")


def _assemble_quick_brief(conn, brand: dict, *, product_id, topic: str,
                          base_format: str, actor: str) -> CreativeBrief:
    """最小創意簡報：檔期／計畫／生成範圍／同格既有主題摘要留空，切角＝使用者輸入的 topic
    （沿用既有 cell.creative_angle 欄位，不新增）。品牌智庫 context／方法論／顧客語料／
    拒絕記憶照常查（跟 brief_assembler.assemble_brief() 既有邏輯一致，只是不查
    cycle／plan_row／theme_repo.list_themes_for_cell）。
    """
    context_text, _knowledge_item_ids, _brand_version, _product_version = (
        context_compiler.compile(conn, brand["id"], product_id))
    methodology_result = methodology.compile(
        conn, METHODOLOGY_TASK_LABELS, brand_id=brand["id"], actor=actor)
    customer_voice_text, customer_voice_available = _customer_voice_block(conn, brand["id"])
    constraints = _rejection_constraints(conn, brand["id"])

    return CreativeBrief(
        brand=brand, cycle={}, offer=None, plan={"summary": ""},
        cell={"creative_angle": topic, "product_id": product_id},
        brand_context=context_text, methodology=methodology_result.text,
        customer_voice=customer_voice_text, customer_voice_available=customer_voice_available,
        rejection_constraints=constraints, fingerprint_vocabulary=fp.prompt_vocabulary(),
        format_key=base_format, generation_scope={}, existing_themes_summary=[],
    )


def _quick_generate_ai_call(conn, brand: dict, *, scope: str, product_id, cost_ceiling: float,
                            user_text: str) -> tuple:
    """一次 AI 呼叫：先查花費上限，再打 gateway.run_task()。回 (rendered_output, None) 成功，
    或 (None, 人話錯誤) 失敗。single_image 一次呼叫、video 一支切角 3 次呼叫都共用這支，
    避免 gateway.run_task() 的呼叫組態複製多份。
    """
    budget_err = coresettings.budget_exceeded_message(
        conn, brand["id"], cost_ceiling,
        action="快速生成", fallback_hint="可以到設定頁調高上限後再試。")
    if budget_err:
        return None, budget_err

    task = gateway.run_task(
        conn, theme_engine.PROVIDER, brand_id=brand["id"], task_type="creative_theme",
        prompt_template_id=f"quick_generate_{scope}", prompt_template_version="v1",
        system=theme_engine._SYSTEM, messages=[{"role": "user", "content": user_text}],
        context=gateway.TaskContext(
            context_scope={"brand_id": brand["id"], "product_id": product_id,
                          "quick_generate_scope": scope},
            knowledge_item_ids=[], brand_version=0,
        ),
        options=gateway.TaskOptions(max_tokens=theme_engine.THEME_MAX_TOKENS),
    )
    if task["status"] != "succeeded":
        return None, task["error"]
    return gateway.parse_json_reply(task["rendered_output"]), None


def _run_quick_generate(conn, brand: dict, *, scope: str, topic: str, product_id,
                        actor: str) -> tuple:
    """回 (result_dict, None) 成功，或 (None, 人話錯誤) 失敗。不落地：不呼叫
    theme_engine.save_generated_theme()，成功也不寫任何資料表。

    scope="video"／"script" 的 base_format 都是 video：既有排程流程規則「一支腳本＝一個
    主題」不可改（app/ads/theme_engine_video.py generate_video_theme() 同一個形狀），所以
    這裡要真的呼叫 3 次（script_count，取自 FORMAT_SPECS，不寫死數字）。第一次沿用既有
    needs_hook_pool=True 生 10 個共用 Hook，第二、三次改傳 needs_hook_pool=False＋第一次的
    hook_pool 當 existing_hooks，不讓每次呼叫各自重生一份 Hook（那樣使用者會拿到 30 個而
    不是共用的 10 個）。body／title／description 只收第一次的——第二、三次呼叫的目的只是
    多拿 2 支腳本，不是要多一批文案。
    """
    base_format = QUICK_GENERATE_SCOPES[scope]["base_format"]
    # 這個類型要顯示哪些欄位，供產出後過濾用（見檔頭說明：不是餵給 build_*_prompt 的 plan）。
    target_fields = set(core_theme_engine.build_quick_generate_plan(scope).keys())
    # 全欄位 plan：build_single_image_prompt()／build_video_prompt() 的既有介面契約，見檔頭
    # ponytail 說明。直接讀 FORMAT_SPECS 原始定義，不查 *_fields_plan(objective)。
    full_plan = FORMAT_SPECS[base_format]["fields"]

    brief = _assemble_quick_brief(
        conn, brand, product_id=product_id, topic=topic, base_format=base_format, actor=actor)

    model = providers.resolve_model(task_type="creative_theme", conn=conn)
    cost_ceiling = pricing.cost_ceiling(model, theme_engine.THEME_MAX_TOKENS)

    if base_format == "single_image":
        user_text = core_theme_engine.build_single_image_prompt(brief, full_plan, fp)
        data, err = _quick_generate_ai_call(
            conn, brand, scope=scope, product_id=product_id, cost_ceiling=cost_ceiling,
            user_text=user_text)
        if err:
            return None, err
        generated = core_theme_engine.normalize_single_image(data, full_plan, fp)
        if generated is None:
            return None, core_theme_engine.PARSE_FAIL_MESSAGE
        components = [c for c in generated["components"] if c["component_type"] in target_fields]
        return {"scope": scope, "name": generated["name"], "components": components}, None

    # base_format == "video"：一支腳本一次呼叫，跑 script_count 次（見上方 docstring）。
    script_count = full_plan["script"]["count"]
    existing_hooks: list = []
    name = None
    merged_components: list = []
    for i in range(script_count):
        needs_hook_pool = i == 0
        user_text = core_theme_engine_video.build_video_prompt(
            brief, full_plan, fp, needs_hook_pool=needs_hook_pool, existing_hooks=existing_hooks)
        data, err = _quick_generate_ai_call(
            conn, brand, scope=scope, product_id=product_id, cost_ceiling=cost_ceiling,
            user_text=user_text)
        if err:
            return None, err
        generated = core_theme_engine_video.normalize_video(
            data, full_plan, fp, needs_hook_pool=needs_hook_pool)
        if generated is None:
            return None, core_theme_engine.PARSE_FAIL_MESSAGE

        if needs_hook_pool:
            name = generated["name"]
            existing_hooks = [c["content"] for c in generated["components"]
                              if c["component_type"] == "hook_pool"]
            merged_components.extend(generated["components"])
        else:
            merged_components.extend(
                c for c in generated["components"] if c["component_type"] == "script")

    components = [c for c in merged_components if c["component_type"] in target_fields]
    return {"scope": scope, "name": name, "components": components}, None


@router.get("/brands/{brand_id}/products")
async def quick_generate_products(brand_id: str):
    """產品 pills 的清單（契約 G12.0）：這個品牌旗下的產品，只回 id／name——pills 用不到
    其他欄位。沿用既有 `main_mod.list_products()`（app/shared/web.py:71，內部就是
    `brand_intelligence.repository.list_products()`，契約指名的同一支），不另外查表。
    「不指定」那顆是前端固定選項，不佔一筆資料。
    """
    main_mod.require_brand(brand_id)
    return {"products": [{"id": p["id"], "name": p["name"]}
                         for p in main_mod.list_products(brand_id)]}


@router.post("/brands/{brand_id}/quick-generate")
async def quick_generate(request: Request, brand_id: str):
    """快速生成：四選一類型＋可選產品＋一句話重點 → 純顯示即棄的生成結果。"""
    brand = main_mod.require_brand(brand_id)
    actor = main_mod.require_actor(request)
    conn = main_mod.conn

    try:
        body = await request.json()
    except ValueError:
        return JSONResponse({"error": "請求格式不是合法的 JSON"}, status_code=400)
    if not isinstance(body, dict):
        return JSONResponse({"error": "請求格式不是合法的 JSON"}, status_code=400)

    scope = body.get("scope")
    if scope not in QUICK_GENERATE_SCOPES:
        return JSONResponse({"error": "請選擇要生成的類型。"}, status_code=400)
    topic = body.get("topic")
    if not isinstance(topic, str) or not topic.strip():
        return JSONResponse({"error": "請輸入這次想講的重點。"}, status_code=400)
    product_id = body.get("product_id") or None
    if product_id is not None:
        main_mod.require_product(brand, product_id)  # 找不到／不屬於這個品牌就 404

    result, err = _run_quick_generate(
        conn, brand, scope=scope, topic=topic.strip(), product_id=product_id, actor=actor)
    if err:
        return JSONResponse({"error": err}, status_code=422)

    # 票 S1-01：快速生成的元件不落地、沒有 DB 主鍵，用清單索引把命中結果貼回每則元件
    # （compliance.scan_components() 對沒有 id 的元件本來就用索引當 key，見該函式 docstring）。
    hits_by_key = compliance.scan_components(
        conn, brand["id"], result["components"], product_id=product_id)
    for index, component in enumerate(result["components"]):
        component["compliance_hits"] = hits_by_key.get(index, [])
    return {"result": result, "scan_note": compliance.SCAN_LIMITS_NOTE}
