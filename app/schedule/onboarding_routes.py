"""app/schedule/onboarding_routes.py — 票 S2「開帳讀歷史」的三支端點，獨立成第二個
`APIRouter`，不擠進 `app/schedule/routes.py`（那個檔案已經 675 行，`FileLineCapTest`
的 `FILE_LINE_CAP = 800` 硬擋任何新超標檔案、不開 `KNOWN_OVERSIZED_FILES` 新豁免——
見 S2-DESIGN.md D1）。

三支 handler 全部照抄 `app/schedule/routes.py:622-676` 既有生成端點的形狀：
`web.require_actor` → `web.require_brand`（租戶界線一律先於欄位驗證——
`test_identity_tenant_routes.py:86-134` 送空 body 也要先到 404，這是三支端點的
Request Model 全部欄位給預設值的理由）。真正的邏輯全部在 `app/schedule/onboarding.py`，
這裡只驗身分、轉呼叫，不重複寫一次判斷。
"""

from fastapi import APIRouter, Request
from pydantic import BaseModel

import app.shared.web as web
from app.schedule import onboarding

router = APIRouter(prefix="/api/schedule")


class AcceptRequest(BaseModel):
    # 全部欄位給預設值（同 routes.py PlanRequest 的理由）：租戶界線要先於「填了什麼」被
    # 檢查，真正的驗證在 `onboarding.accept_conclusions()` 裡逐一做，不在這裡假裝合法。
    task_id: str = ""
    indexes: list[int] = []


@router.get("/brands/{brand_id}/onboarding-read")
def get_onboarding_read(request: Request, brand_id: str):
    actor = web.require_actor(request)
    web.require_brand(brand_id, actor)  # 另一個組織的品牌 → 404
    return onboarding.brand_response(web.conn, brand_id, actor.org_id)


@router.post("/brands/{brand_id}/onboarding-read")
def create_onboarding_read(request: Request, brand_id: str):
    actor = web.require_actor(request)
    web.require_brand(brand_id, actor)  # 另一個組織的品牌 → 404
    return onboarding.start_onboarding_read(web.conn, brand_id, actor.org_id)


@router.post("/brands/{brand_id}/onboarding-read/accept")
def accept_onboarding_read(request: Request, brand_id: str, body: AcceptRequest):
    actor = web.require_actor(request)
    web.require_brand(brand_id, actor)  # 另一個組織的品牌 → 404
    return onboarding.accept_conclusions(
        web.conn, brand_id, actor.org_id, str(actor.user_id), body.task_id, body.indexes
    )
