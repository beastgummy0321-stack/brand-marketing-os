"""F29-I03 Contract E: the period settle -- brand-scoped (a settle spans every campaign of the
brand, imported ones included), same auth shape as `month_summary_routes.py`: `require_actor` ->
`require_brand` -> one `settle.py` function -> wrap. Mounted through `routes.py`."""

from fastapi import APIRouter, Request
from pydantic import BaseModel, ConfigDict, Field

import app.shared.web as web
from app.ads import settle


class Pick(BaseModel):
    model_config = ConfigDict(extra="forbid")
    entity_id: str = Field(min_length=1, max_length=200)
    # Length (1–12 after trimming) is checked by `settle.write` so a bad pick reads its own code.
    angle: str = Field(max_length=200)


class SettleRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    month: str = Field(pattern=r"^\d{4}-\d{2}$")
    picks: list[Pick] = Field(default_factory=list, max_length=500)


router = APIRouter()


def _error(exc: settle.SettleError) -> web.ApiError:
    return web.ApiError(exc.status, exc.code, exc.message)


@router.get("/brands/{brand_id}/settle")
def get_settle(request: Request, brand_id: str, month: str | None = None):
    actor = web.require_actor(request)
    web.require_brand(brand_id, actor)  # 另一個組織的品牌 → 404
    month = month or settle.previous_month(web.conn, actor.org_id)
    try:
        return settle.view(web.conn, actor.org_id, brand_id, month)
    except settle.SettleError as exc:
        raise _error(exc) from None


@router.post("/brands/{brand_id}/settle")
def post_settle(request: Request, brand_id: str, body: SettleRequest):
    actor = web.require_actor(request)
    web.require_brand(brand_id, actor)
    try:
        return settle.write(
            web.conn, actor.org_id, brand_id, body.month,
            [pick.model_dump() for pick in body.picks], str(actor.user_id),
        )
    except settle.SettleError as exc:
        web.conn.rollback()
        raise _error(exc) from None
