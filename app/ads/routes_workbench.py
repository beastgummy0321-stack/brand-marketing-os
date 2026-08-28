"""app/ads/routes_workbench.py — 素材工作檯任務卡衍生查詢（票 13-workbench-cards）。

畫面契約畫面 1（.scratch/creative-studio/studio-wireframe.html）：「上游派來的任務」各
上游從自身狀態衍生，不建表、不做佇列。本檔只做「廣告任務卡」這一種來源——計畫已核准
（campaign_plan 最新版 status == 'approved'，跟 app/ads/brief_assembler.py assemble_brief()
同一個判準）＋矩陣還沒全部生成完（切角格 × 格式還有格子沒主題）的檔期，各出一張卡；兩個
條件有一個不成立就不出卡，沒有任務時回空清單，空狀態文案是前端的事。

「格」＝切角格 × 格式，跟矩陣頁（app/ads/routes_creative_theme.py theme_matrix()）用
同一份格式清單 GENERATORS，不另開一份，格式增減兩邊自動一致。已生成＝這一格至少有一個
主題。已採用數只算主題整包被一鍵採用（adoption_decision target_type='theme' AND
decision='adopted'），跟 theme_repository.adopt_theme() 寫入的那一種同一套資料，不重算。
"""

from fastapi import APIRouter

import app.shared.web as main_mod
from app.ads import plan as ads_plan
from app.ads import repository as ads_repo
from app.ads.routes_creative_theme import GENERATORS

router = APIRouter(prefix="/api/ads")


def _cycle_label(cycle: dict) -> str:
    """檔期沒有名稱欄位，用日期範圍當識別文字（比照 app/ads/routes_plan.py 既有的
    _cycle_label() 慣例：畫面與刪除確認都用這個格式，這裡沿用同一種文字形狀）。"""
    return f"{cycle['start_date']} ～ {cycle['end_date']}"


def _generated_cell_count(conn, brand_id: str, cycle_id: str) -> int:
    """有幾格（切角格 × 格式）至少生出一個主題——distinct 配對數，格式限定在 GENERATORS
    目前支援的清單內（跟矩陣頁全展開的欄位一致，格式停用後不倒扣進分母）。"""
    rows = conn.execute(
        "SELECT DISTINCT experiment_cell_id, format_key FROM creative_theme"
        " WHERE brand_id = %s AND campaign_cycle_id = %s", (brand_id, cycle_id)).fetchall()
    return sum(1 for row in rows if row["format_key"] in GENERATORS)


def _adopted_count(conn, brand_id: str, cycle_id: str) -> int:
    row = conn.execute(
        "SELECT COUNT(*) AS n FROM adoption_decision WHERE brand_id = %s"
        " AND campaign_cycle_id = %s AND target_type = 'theme' AND decision = 'adopted'",
        (brand_id, cycle_id)).fetchone()
    return row["n"]


def _cell_count(conn, brand_id: str, cycle_id: str) -> int:
    row = conn.execute(
        "SELECT COUNT(*) AS n FROM experiment_cell WHERE brand_id = %s"
        " AND campaign_cycle_id = %s", (brand_id, cycle_id)).fetchone()
    return row["n"]


@router.get("/brands/{brand_id}/workbench/tasks")
async def workbench_tasks(brand_id: str):
    """畫面 1 任務卡：計畫已核准＋素材未完成的檔期各出一張卡（不含已封存檔期，比照
    ads_repo.list_cycles() 預設行為）。零新資料表，全部從既有表衍生，沒有任務回空清單。
    """
    main_mod.require_brand(brand_id)
    conn = main_mod.conn

    tasks = []
    for cycle in ads_repo.list_cycles(conn, brand_id):
        plan_row = ads_plan.get_latest_plan(conn, brand_id, cycle["id"])
        if plan_row is None or plan_row["status"] != "approved":
            continue  # 計畫還沒核准：不算工作檯的任務

        total_cells = _cell_count(conn, brand_id, cycle["id"]) * len(GENERATORS)
        if total_cells == 0:
            continue  # 沒有切角格可生，沒有工作可做
        generated_cells = _generated_cell_count(conn, brand_id, cycle["id"])
        if generated_cells >= total_cells:
            continue  # 素材已完成：矩陣全部格子都生過了，不出卡

        tasks.append({
            "source": "廣告檔期",
            "cycle_id": cycle["id"],
            "cycle_label": _cycle_label(cycle),
            "generated_cells": generated_cells,
            "total_cells": total_cells,
            "adopted_count": _adopted_count(conn, brand_id, cycle["id"]),
        })
    return {"tasks": tasks}
