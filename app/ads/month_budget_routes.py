"""Brand envelope: authenticated local confirmation, never a platform setting."""

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, ConfigDict, Field

from app.ads import month_budget
from app.core import db, settings
from app.shared import web


def _guard(request: Request, brand_id: str):
    web.require_brand(brand_id, web.require_actor(request))


router = APIRouter(prefix="/api/ads", dependencies=[Depends(_guard)])


@router.get("/brands/{brand_id}/change-control-summary")
def change_summary(request: Request, brand_id: str):
    actor = web.require_actor(request)
    rows = (
        db.current()
        .execute(
            "SELECT s.id,s.campaign_id,c.name AS campaign_name,s.title,s.status,"
            "count(a.id) FILTER(WHERE a.verification_state<>'confirmed') AS pending_items,"
            "count(a.id) FILTER(WHERE a.verification_state='unknown') AS unknown_items,"
            "count(*) OVER() AS total FROM ads_change_set s "
            "JOIN ads_campaign c ON c.id=s.campaign_id AND c.org_id=s.org_id "
            "AND c.brand_id=s.brand_id LEFT JOIN ads_action a ON a.change_set_id=s.id "
            "AND NOT (a.evidence_json ? 'superseded_by') "
            "WHERE s.org_id=%s AND s.brand_id=%s AND s.status IN ('draft','deferred','approved') "
            "GROUP BY s.id,c.name HAVING s.status<>'approved' OR "
            "count(a.id) FILTER(WHERE a.verification_state<>'confirmed')>0 "
            "ORDER BY s.created_at DESC LIMIT 20",
            (actor.org_id, brand_id),
        )
        .fetchall()
    )
    total = rows[0]["total"] if rows else 0
    return {"pending_count": total, "items": [dict(r) for r in rows], "truncated": total > 20}


class BudgetRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    month: str = Field(pattern=r"^\d{4}-\d{2}$")
    currency: str = Field(pattern=r"^[A-Z]{3}$")
    # F47 Contract A: the value is passed as sent; `month_budget.total` alone owns the rule (> 0,
    # unset/None refused with its sentence), so a negative gets the store sentence, not a 422.
    amount: float | None = None
    expected_revision: int = Field(ge=0, strict=True)


@router.get("/brands/{brand_id}/monthly-budget")
def read_budget(request: Request, brand_id: str, month: str | None = None):
    actor = web.require_actor(request)
    conn = db.current()
    month = month or settings.today_for_org(conn, org_id=actor.org_id).strftime("%Y-%m")
    try:
        return {"budget": month_budget.view(conn, actor.org_id, brand_id, month)}
    except ValueError as exc:
        raise web.ApiError(409, "monthly_budget_unavailable", str(exc)) from None


@router.put("/brands/{brand_id}/monthly-budget")
def confirm_budget(request: Request, brand_id: str, body: BudgetRequest):
    actor = web.require_actor(request)
    try:
        return {
            "budget": month_budget.save(
                db.current(), actor.org_id, brand_id, actor=str(actor.user_id), **body.model_dump()
            )
        }
    except ValueError as exc:
        raise web.ApiError(409, "monthly_budget_conflict", str(exc)) from None
