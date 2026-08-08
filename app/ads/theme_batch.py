# -*- coding: utf-8 -*-
"""app/ads/theme_batch.py — 預選格批次生成（票 09-preselect-autogen）。

計畫核准後自動先生：每個切角格（experiment_cell）先生 THEME_COUNT_PRESELECT 個主題，
不必等使用者點灰卡。

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
呼叫兩次、中間重新組簡報——第二次組簡報時 brief_assembler 會查到剛存的第一個主題，
`existing_themes_summary` 因此非空，第二個主題的 prompt 自動帶防撞衫指令（沿用
theme_engine.py 既有機制，不新寫一套）。

費用攔截（票 09 驗收 4）：每次生成前用跟引擎內部完全相同的
`coresettings.budget_exceeded_message` 算法查一次；超過就整批誠實停下、已經生成的主題保留，
不回滾。跟 `generate_single_image_theme()` 內部再檢查一次是重複而非衝突——同一個品牌、
同一段時間內不會有第二個呼叫者插進來改變已花費金額（單機單人使用），這裡的預檢查只是讓
批次迴圈能在呼叫引擎前就知道「該收手了」，不必解析引擎回傳的錯誤字串來分辨是不是費用問題。
"""

import sqlite3

from app.ads import brief_assembler
from app.ads import theme_engine
from app.core import settings as coresettings
from app.llm import pricing, providers

PRESELECT_FORMAT = "single_image"
THEME_COUNT_PRESELECT = 2


def preselected_cells(conn: sqlite3.Connection, brand_id: str, cycle_id: str) -> list:
    """這期核准計畫底下的每個切角格都是預選格（見檔頭：目前沒有格式建議演算法，所以是
    「每格」而不是「挑 3–5 格」）。查詢沿用 app/ads/creative.py:296-299 既有的
    `SELECT * FROM experiment_cell WHERE brand_id = ? AND campaign_cycle_id = ? ORDER BY id`
    慣例。"""
    return [dict(r) for r in conn.execute(
        "SELECT * FROM experiment_cell WHERE brand_id = ? AND campaign_cycle_id = ? ORDER BY id",
        (brand_id, cycle_id),
    )]


def _budget_blocked(conn: sqlite3.Connection, brand_id: str) -> bool:
    model = providers.resolve_model(task_type="creative_theme", conn=conn)
    return coresettings.budget_exceeded_message(
        conn, brand_id, pricing.cost_ceiling(model, theme_engine.THEME_MAX_TOKENS),
    ) is not None


def generate_preselected_batch(conn: sqlite3.Connection, brand_id: str, cycle_id: str, *,
                                actor: str) -> dict:
    """計畫核准觸發（票 09 驗收 1）：每個切角格生 THEME_COUNT_PRESELECT 個 single_image
    主題；non-預選格式（carousel／video）零生成——本函式從不呼叫它們的生成器。

    回傳 `{"themes": [...新主題...], "budget_stopped": bool, "errors": [...]}`。

    費用超過上限時整批誠實停下、已生成的主題保留（票 09 驗收 4，`budget_stopped=True`）。
    其餘生成失敗（AI 沒回、格式讀不成）只記一筆錯誤、跳過那一次嘗試，不牽連其他格——
    這是生成過程本身的意外，不是「該收手了」的訊號，不停整批。
    """
    generator = theme_engine.GENERATORS[PRESELECT_FORMAT]
    themes: list = []
    errors: list = []
    budget_stopped = False

    for cell in preselected_cells(conn, brand_id, cycle_id):
        for _ in range(THEME_COUNT_PRESELECT):
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

            generated, err = generator(conn, brief, actor=actor)
            if err:
                errors.append({"experiment_cell_id": cell["id"],
                               "format_key": PRESELECT_FORMAT, "error": err})
                continue  # AI 這次沒能產出，換下一次嘗試（同格還差的則數）

            themes.append(theme_engine.save_generated_theme(conn, brief, generated, actor=actor))
        if budget_stopped:
            break

    return {"themes": themes, "budget_stopped": budget_stopped, "errors": errors}
