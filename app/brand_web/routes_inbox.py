"""app/brand_intelligence/routes_inbox.py — 收件匣 JSON API（票 B1-inbox，契約
`.scratch/grill/GRILL-B1-inbox.md` S2）。

統一回應信封（`data`／`generated_at`，沿用 `app/dashboard/routes.py` 既有慣例）。
`GET /api/inbox` 只讀；「知道了」動作走本檔 `POST /api/interrupts/{id}/resolve`
（T4 步驟 1 已刪除舊版 `app/brand_web/routes.py` 的 HTML 版本，前端改打這支）。

對外進入點：本檔的 `router`（`app/main.py` 直接 `include_router`，不掛進
`app.brand_intelligence.routes`——那個檔已經頂著超標行數上限，不得再加新功能，
理由同 `app/brand_intelligence/routes_settings.py` 檔頭）。誰依賴它：只有 `app/main.py`。
"""

from datetime import UTC, datetime

from fastapi import APIRouter, Request

from app.core import interrupts as core_interrupts
from app.core import prototype_phase as core_prototype_phase
from app.shared import web
from app.shared.web import _with_brand_names, require_actor

router = APIRouter()


def _category_label(category: str) -> str:
    """反查 `app.core.interrupts.CATEGORIES` 的人話標籤（S2.5），單一權威不重造第二份。"""
    spec = core_interrupts.CATEGORIES.get(category)
    return spec["label"] if spec else category


def _inbox_item(row: dict) -> dict:
    """把 `interrupt` 資料列（已掛 `brand_name`）轉成契約 InboxItem 型別，契約沒寫的欄位
    不得產出（見 GRILL-B1-inbox.md TS type）。"""
    return {
        "id": row["id"],
        "brand_id": row["brand_id"],
        "brand_name": row["brand_name"],
        "category": row["category"],
        "category_label": _category_label(row["category"]),
        "severity": row["severity"],
        "message": row["message"],
        "action_url": row["action_url"],
        "resolved_at": row["resolved_at"],
    }


@router.get("/api/inbox")
async def api_inbox():
    """S2.2–S2.6、S2.11–S2.12：待辦／已結兩份清單一次回傳。排序沿用
    `core_interrupts.list_open()` 既有 `_sort_key`，這裡不重排。"""
    open_items = [_inbox_item(r) for r in _with_brand_names(core_interrupts.list_open(web.conn))]
    done_items = [_inbox_item(r) for r in _with_brand_names(core_interrupts.list_done(web.conn))]
    return {
        "data": {"open": open_items, "done": done_items},
        "generated_at": datetime.now(UTC).isoformat(),
    }


@router.post("/api/interrupts/{interrupt_id}/resolve")
async def api_interrupt_resolve(request: Request, interrupt_id: str):
    core_interrupts.resolve(web.conn, interrupt_id, actor=require_actor(request))
    return {"ok": True}


@router.get("/api/system/prototype-phase")
async def api_prototype_phase():
    """S2.15–S2.17：側板詳情，全站單一旗標，不帶 brand_id 參數。"""
    return {
        "data": {
            "ended": core_prototype_phase.has_ended(web.conn),
            "exemptions": core_prototype_phase.EXEMPTIONS,
        },
        "generated_at": datetime.now(UTC).isoformat(),
    }
