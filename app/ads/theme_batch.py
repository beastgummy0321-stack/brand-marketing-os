"""app/ads/theme_batch.py — 預選格批次生成（票 09-preselect-autogen）。

計畫核准後自動先生：每個切角格（experiment_cell）以 2 個主題為基準，再由已可信的歷史
切角成效加減 1，不必等使用者點灰卡。新品牌／資料不足仍完整維持每格 2 個。

**預選格式怎麼選（讀過才別重猜）**：ADR 0008 第四節說「切角層另外算出這個切角建議開幾則
廣告、各用什麼格式」，但那套建議演算法目前不存在——計畫核准流程（app/ads/plan.py）產出的
`plan_json.angles` 只有 title／message／why／product_id，沒有格式建議；
`app/creative/format_specs.py` 的 `media_cap_per_theme` 在 sales 以外的四種目標三格式全部
=1，沒有可比的訊號；`experiment_cell.format` 欄位是舊模型遺留、新流程從不寫入，永遠是
NULL。找不到任何「這格該用哪個格式」的既有訊號，因此不自創評分演算法（reuse-first.md
第四節），改用最小、誠實、可逆的規則：**每個切角格固定預選 single_image**——它是唯一在
FORMAT_SPECS 三格式裡對 sales 目標明顯有最大產能（10 media）的格式，其餘四個目標三格式
持平但 single_image 仍是矩陣第一欄（見 studio-wireframe.html 畫面 2）。carousel／video
留給矩陣的灰卡「生成一個主題」入口，使用者按了才生（候選不消失，ADR 0008 第四節）。

ponytail：`PRESELECT_FORMAT` 是天花板已知的簡化——未來排程層真的做出「這格建議開幾則、
各用什麼格式」的演算法時，把這個常數換成該演算法的每格輸出即可，
`generate_preselected_batch()`／呼叫端（app/ads/routes_plan.py）都不必改。

批次走跟「生成一個主題」（app/ads/routes_creative_theme.py）完全相同的路徑
（brief_assembler.assemble_brief → 引擎 → save_generated_theme），只差呼叫端對同一格連續
呼叫 1～3 次、中間重新組簡報——第二次組簡報時 brief_assembler 會查到剛存的第一個主題，
`existing_themes_summary` 因此非空，第二個主題的 prompt 自動帶防撞衫指令（沿用
theme_engine.py 既有機制，不新寫一套）。

費用攔截（票 09 驗收 4）：每次生成前用跟引擎內部完全相同的
`coresettings.budget_exceeded_message` 算法查一次；超過就整批誠實停下、已經生成的主題保留，
不回滾。跟 `generate_single_image_theme()` 內部再檢查一次是重複而非衝突——同一個品牌、
同一段時間內不會有第二個呼叫者插進來改變已花費金額（單機單人使用），這裡的預檢查只是讓
批次迴圈能在呼叫引擎前就知道「該收手了」，不必解析引擎回傳的錯誤字串來分辨是不是費用問題。
"""


from app.ads import brief_assembler, nextcycle, theme_engine, theme_feedback
from app.brand_intelligence import repository as bi_repo
from app.core import orchestrator as core_orchestrator
from app.core import settings as coresettings
from app.core.db import Conn
from app.llm import pricing, providers

PRESELECT_FORMAT = "single_image"
THEME_COUNT_PRESELECT = theme_feedback.BASE_THEME_QUOTA


def preselected_cells(conn: Conn, brand_id: str, cycle_id: str) -> list:
    """這期核准計畫底下的每個切角格都是預選格（見檔頭：目前沒有格式建議演算法，所以是
    「每格」而不是「挑 3–5 格」）。查詢沿用 app/ads/creative.py:296-299 既有的
    `SELECT * FROM experiment_cell WHERE brand_id = %s AND campaign_cycle_id = %s ORDER BY id`
    慣例。"""
    return [dict(r) for r in conn.execute(
        "SELECT * FROM experiment_cell WHERE brand_id = %s AND campaign_cycle_id = %s ORDER BY id",
        (brand_id, cycle_id),
    )]


def _budget_blocked(conn: Conn, brand_id: str) -> bool:
    org_id = bi_repo._org_id_for_brand(conn, brand_id)
    model = providers.resolve_model(task_type="creative_theme", conn=conn, brand_id=brand_id)
    return coresettings.budget_exceeded_message(
        conn, brand_id, pricing.cost_ceiling(model, theme_engine.THEME_MAX_TOKENS), org_id=org_id,
    ) is not None


def generation_count(conn: Conn, brand_id: str, cycle_id: str) -> int:
    """這次核准實際會跑幾次生成——`preselected_cells()` 逐格用
    `theme_feedback.theme_quota()` 算配額後加總，跟 `generate_preselected_batch()` 內層
    迴圈數的是同一個數字。`estimated_batch_cost()`（花費預估，D3）與票 13
    `proposal_approve_status` 的進度逾時天花板（見 routes_campaigns_open_api.py）共用
    這同一個計數，不重寫第二套。

    純讀取：不呼叫 AI、不檢查費用上限、不寫入任何東西。
    """
    historical_cells = nextcycle.historical_cell_performance(
        conn, brand_id, exclude_cycle_id=cycle_id)
    return sum(
        theme_feedback.theme_quota(cell, historical_cells)
        for cell in preselected_cells(conn, brand_id, cycle_id)
    )


def estimated_batch_cost(conn: Conn, brand_id: str, cycle_id: str) -> float:
    """核可提案書前，先讓使用者看到這次核准會花多少錢（票 13-approve-must-not-block-or-
    surprise，D3）。跟矩陣頁「生成一個主題」灰卡標的預估費用同一個天花板——
    `pricing.cost_ceiling(model, theme_engine.THEME_MAX_TOKENS)`（見
    routes_creative_theme.py:104，跟本檔 `_budget_blocked` 用的是同一行算式）——只是
    乘上這次核准實際會跑的生成次數（`generation_count()`），不重寫第二套估算。

    純讀取：不呼叫 AI、不檢查費用上限、不寫入任何東西。
    """
    model = providers.resolve_model(task_type="creative_theme", conn=conn, brand_id=brand_id)
    per_generation_ceiling = pricing.cost_ceiling(model, theme_engine.THEME_MAX_TOKENS)
    return per_generation_ceiling * generation_count(conn, brand_id, cycle_id)


def generate_preselected_batch(conn: Conn, brand_id: str, cycle_id: str, *,
                                actor: str) -> dict:
    """計畫核准觸發（票 09 驗收 1）：每個切角格以 THEME_COUNT_PRESELECT 為基準，依可信
    歷史成效加減 1 個 single_image 主題；non-預選格式（carousel／video）零生成。

    回傳 `{"themes": [...新主題...], "budget_stopped": bool, "errors": [...]}`。

    費用超過上限時整批誠實停下、已生成的主題保留（票 09 驗收 4，`budget_stopped=True`）。
    其餘生成失敗（AI 沒回、格式讀不成）只記一筆錯誤、跳過那一次嘗試，不牽連其他格——
    這是生成過程本身的意外，不是「該收手了」的訊號，不停整批。
    """
    generator = theme_engine.GENERATORS[PRESELECT_FORMAT]
    historical_cells = nextcycle.historical_cell_performance(
        conn, brand_id, exclude_cycle_id=cycle_id)
    anti_echo = theme_feedback.anti_echo_summary(
        conn, brand_id, cycle_id, PRESELECT_FORMAT)
    anti_echo_reserved = False
    themes: list = []
    errors: list = []
    budget_stopped = False

    for cell in preselected_cells(conn, brand_id, cycle_id):
        quota = theme_feedback.theme_quota(cell, historical_cells)
        for _ in range(quota):
            if _budget_blocked(conn, brand_id):
                budget_stopped = True
                break

            brief, err = brief_assembler.assemble_brief(
                conn, brand_id, cycle_id, cell["id"], PRESELECT_FORMAT,
                theme_count=1, actor=actor)
            if err:
                errors.append({"experiment_cell_id": cell["id"],
                               "format_key": PRESELECT_FORMAT, "error": err})
                break  # 這種錯誤（計畫沒核准等）跟這格無關，同格重試也不會過

            # 最近一期亮回音室燈時，第一個能走到生成器的組把歷史指紋與最遠目標放進既有
            # existing_themes_summary；引擎沿原本的「不要撞衫」段落收到，不新增 prompt 類型。
            if anti_echo and not anti_echo_reserved:
                brief = brief._replace(
                    existing_themes_summary=[*brief.existing_themes_summary, anti_echo])

            generated, err = generator(conn, brief, actor=actor)
            if err:
                errors.append({"experiment_cell_id": cell["id"],
                               "format_key": PRESELECT_FORMAT, "error": err})
                continue  # AI 這次沒能產出，換下一次嘗試（同格還差的則數）

            themes.append(theme_engine.save_generated_theme(conn, brief, generated, actor=actor))
            if anti_echo and not anti_echo_reserved:
                anti_echo_reserved = True
        if budget_stopped:
            break

    return {"themes": themes, "budget_stopped": budget_stopped, "errors": errors}


# ---------------------------------------------------------------------------
# 調度台『創意』模組門面（票 O1-01，ADR 0024）
# ---------------------------------------------------------------------------
# 票 03-orchestrator-core.md 原文把 add_theme 猜在 app/ads/weekly_proposals.py（優化）
# 底下，那是猜錯的：weekly_proposals.py 只管「三張卡：停掉／加碼／換素材」，沒有補主題。
# 真正的進入點是本檔的 `generate_preselected_batch()`——計畫核准後自動先生走的同一條路
# （呼叫端 app/ads/routes_campaigns_open_api.py:314、:563），所以登記在這裡。
# 註：PLAN.md 模組表把創意模組的進入點寫成 app/ads/creative_pipeline.py，那支其實只有
# 駕駛艙用的統計函式，不是補主題的路——別照那份草稿去找（2026-08-23 審查查證）。

_HANDLE_ACTOR = "orchestrator"


def status(conn: Conn, brand_id: str) -> dict:
    """目前沒有任何規則要讀創意層 facts，回空字典（O1-01 這條垂直線只需要 handle()）。"""
    return {}


def handle(conn: Conn, action: dict) -> dict:
    """調度台唯一支援的 op：add_theme（叫創意補主題）。不認得的 op 一律丟 ValueError
    （ADR 0024 決議 6）。"""
    if action["op"] != "add_theme":
        raise ValueError(f"創意模組不認得這個 op：{action['op']}")
    return generate_preselected_batch(
        conn, action["brand_id"], action["params"]["cycle_id"], actor=_HANDLE_ACTOR)


def _rule_add_theme_on_ctr_bottleneck(facts: dict) -> "dict | None":
    """規則 2（票 03-orchestrator-core.md）：瓶頸 primary == "ctr" → 創意.add_theme，
    risk asset（保守檔出卡等同意；放手檔自動做）。"""
    if facts.get("diagnosis.bottleneck_primary") != "ctr":
        return None
    cycle_id = facts.get("optimize.cycle_id")
    if not cycle_id:
        return None
    return {
        "module": "creative", "op": "add_theme", "brand_id": facts.get("brand_id"),
        "params": {"cycle_id": cycle_id}, "risk": "asset",
        "dedupe_key": f"add_theme:{cycle_id}",
    }


core_orchestrator.register_module("creative", status=status, handle=handle)
core_orchestrator.register_rule(
    "add_theme_on_ctr_bottleneck", _rule_add_theme_on_ctr_bottleneck)
