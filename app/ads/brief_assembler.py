"""app/ads/brief_assembler.py — 創意簡報組裝器（票 03-brief-assembler）。

給品牌＋檔期＋切角格＋格式 key，組出一份「創意簡報」（`CreativeBrief`）：11 項材料的
純資料快照，供（未來搬到 app/creative 的）無狀態生成引擎使用。純組裝，不呼叫 AI、
不落地任何東西；簡報本身不帶 `conn`、不帶任何回頭查 DB 的可呼叫參數——沒放進簡報的
資訊，對引擎來說就是不存在（spec .scratch/creative-studio/issues/01-c-reshape-spec.md
Implementation Decisions 第二點）。

既有 8 項材料的查法照抄 `app/ads/creative.py:287-346`（生成流程現查的邏輯，不重查不重造）：
品牌、檔期、核准計畫、品牌智庫 context、方法論、顧客語料、拒絕記憶、指紋語彙。唯一差異：
舊流程一次查整期所有切角；新模型的生成單位是「切角 × 格式 → 一個主題」，這裡改成只查
單一切角格，連帶讓品牌智庫 context 不必再處理「一期多產品」合併（單一切角格至多一個
product_id，直接傳給 `context_compiler.compile()` 就是完整範圍）。

新增 3 項：格式 key、生成範圍（哪格、生幾個主題）、同格既有主題摘要（防撞衫材料，
`app/ads/theme_repository.py` 的 `list_themes_for_cell()`，比照拒絕記憶同款「程式彙整、
不靠 LLM 回憶」模式）。
"""

from typing import NamedTuple

from app.ads import fingerprint as fp
from app.ads import plan as ads_plan
from app.ads import repository as ads_repo
from app.ads import theme_repository as theme_repo
from app.ads.creative import (
    METHODOLOGY_TASK_LABELS,
    _customer_voice_block,
    _rejection_constraints,
)
from app.brand_intelligence import repository as bi
from app.core.db import Conn
from app.llm import context_compiler, methodology

PLAN_NOT_APPROVED_MESSAGE = "這期的計畫還沒確認，先確認計畫再做素材。"


class CreativeBrief(NamedTuple):
    """引擎輸入契約（11 項材料）。純資料，沒有 `conn`、沒有任何回頭查 DB 的欄位。"""

    brand: dict
    cycle: dict                        # 含 offer_id；offer 內容另見 offer 欄位
    offer: dict | None              # 檔期沒掛 offer 時為 None
    plan: dict                         # 核准計畫內容
    cell: dict                         # 切角（單一 experiment_cell）
    brand_context: str                 # 品牌智庫 context
    methodology: str
    customer_voice: str
    customer_voice_available: bool
    rejection_constraints: list
    fingerprint_vocabulary: str
    format_key: str
    generation_scope: dict             # {"experiment_cell_id", "format_key", "theme_count"}
    existing_themes_summary: list      # [{"name", "fingerprints": [...]}, ...]；沒有主題時 []


def _row(cursor_row) -> dict | None:
    return dict(cursor_row) if cursor_row is not None else None


def assemble_brief(conn: Conn, brand_id: str, cycle_id: str,
                   experiment_cell_id: str, format_key: str, *,
                   theme_count: int, actor: str) -> tuple:
    """組一份創意簡報。成功回 (CreativeBrief, None)；計畫還沒核准回 (None, 人話錯誤)。

    品牌／檔期／切角格查無此 id 視為呼叫端傳錯（不是使用者能在畫面上碰到的狀態），
    直接拋 ValueError，比照 `creative.generate()` 既有慣例。
    """
    if not format_key or not format_key.strip():
        raise ValueError("格式 key（format_key）為必填")
    if not isinstance(theme_count, int) or theme_count < 1:
        raise ValueError("生成範圍的主題數（theme_count）必須是正整數")
    if not actor or not actor.strip():
        raise ValueError("actor 為必填")

    brand = bi.get_brand(conn, brand_id)
    cycle = ads_repo.get_cycle(conn, brand_id, cycle_id)
    if brand is None or cycle is None:
        raise ValueError("找不到品牌或廣告檔期")

    cell = _row(conn.execute(
        "SELECT * FROM experiment_cell WHERE brand_id = %s AND campaign_cycle_id = %s AND id = %s",
        (brand_id, cycle_id, experiment_cell_id),
    ).fetchone())
    if cell is None:
        raise ValueError(f"找不到切角格：{experiment_cell_id}")

    plan_row = ads_plan.get_latest_plan(conn, brand_id, cycle_id)
    if plan_row is None or plan_row["status"] != "approved":
        return None, PLAN_NOT_APPROVED_MESSAGE

    offer = None
    if cycle["offer_id"]:
        offer = _row(conn.execute(
            "SELECT * FROM offer WHERE brand_id = %s AND id = %s",
            (brand_id, cycle["offer_id"]),
        ).fetchone())

    context_text, _knowledge_item_ids, _brand_version, _product_version = (
        context_compiler.compile(conn, brand_id, cell["product_id"]))
    methodology_result = methodology.compile(
        conn, METHODOLOGY_TASK_LABELS, brand_id=brand_id, actor=actor)
    customer_voice_text, customer_voice_available = _customer_voice_block(conn, brand_id)
    constraints = _rejection_constraints(conn, brand_id)

    existing_themes_summary = [
        {"name": theme["name"],
         "fingerprints": [c["fingerprint_json"] for c in theme["components"]
                          if c["fingerprint_json"]]}
        for theme in theme_repo.list_themes_for_cell(conn, brand_id, experiment_cell_id)
    ]

    return CreativeBrief(
        brand=brand, cycle=cycle, offer=offer, plan=plan_row["plan"], cell=cell,
        brand_context=context_text, methodology=methodology_result.text,
        customer_voice=customer_voice_text, customer_voice_available=customer_voice_available,
        rejection_constraints=constraints, fingerprint_vocabulary=fp.prompt_vocabulary(),
        format_key=format_key.strip(),
        generation_scope={"experiment_cell_id": experiment_cell_id,
                          "format_key": format_key.strip(), "theme_count": theme_count},
        existing_themes_summary=existing_themes_summary,
    ), None
