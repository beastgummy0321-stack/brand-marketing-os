"""Manual handoff editing API; the existing campaign read returns the same record. F29 Contract I:
the launch settings (choice fields) are read and saved here too."""

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, ConfigDict

import app.shared.web as web
from app.ads import launch_settings, manual_settings

router = APIRouter()


class ManualSettingsBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    values: dict[str, str]


def _guard(request: Request, brand_id: str):
    actor = web.require_actor(request)
    web.require_brand(brand_id, actor)
    return actor


@router.put(
    "/brands/{brand_id}/campaigns/{campaign_id}/groups/{group_id}/manual-settings",
    dependencies=[Depends(_guard)],
)
def put_settings(
    request: Request, brand_id: str, campaign_id: str, group_id: str, body: ManualSettingsBody
):
    actor = web.require_actor(request)
    try:
        with web.conn.atomic():
            manual_settings.save(
                web.conn,
                actor.org_id,
                brand_id,
                campaign_id,
                group_id,
                body.values,
                actor=str(actor.user_id),
            )
    except ValueError as exc:
        errors = {
            "campaign_unknown": (404, "找不到這個活動。"),
            "group_unknown": (404, "找不到這個活動的投放組。"),
            "campaign_closed": (409, "活動已結案，不能改寫上架紀錄。"),
            "manual_settings_invalid": (400, "設定欄位不正確或超過 2000 字。"),
            "landing_url_invalid": (400, "落地頁請填完整的 http 或 https 網址，不可包含密碼。"),
            "ad_mapping_invalid": (400, "廣告對應請使用本組的廣告 ID，每行一組，不可重複。"),
        }
        status, message = errors.get(str(exc), (400, "無法儲存設定。"))
        raise web.ApiError(status, str(exc), message) from exc
    return {"ok": True}


_LAUNCH_ERRORS = {
    "campaign_unknown": (404, "找不到這個活動。"),
    "campaign_closed": (409, "活動已結案，不能改投放設定。"),
    "launch_settings_unavailable": (409, "匯入的活動沒有上架清單，不用設定投放設定。"),
    "launch_settings_malformed": (400, "投放設定的欄位或選項不正確。"),
}


def _launch_error(exc: ValueError):
    status, message = _LAUNCH_ERRORS.get(str(exc), (400, "無法處理投放設定。"))
    return web.ApiError(status, str(exc), message)


@router.get(
    "/brands/{brand_id}/campaigns/{campaign_id}/launch-settings", dependencies=[Depends(_guard)]
)
def get_launch_settings(request: Request, brand_id: str, campaign_id: str):
    actor = web.require_actor(request)
    try:
        return launch_settings.view(web.conn, actor.org_id, brand_id, campaign_id)
    except ValueError as exc:
        web.conn.rollback()
        raise _launch_error(exc) from exc


@router.put(
    "/brands/{brand_id}/campaigns/{campaign_id}/launch-settings", dependencies=[Depends(_guard)]
)
def put_launch_settings(request: Request, brand_id: str, campaign_id: str, body: dict):
    actor = web.require_actor(request)
    try:
        return launch_settings.save(
            web.conn, actor.org_id, brand_id, campaign_id, body, actor=str(actor.user_id)
        )
    except ValueError as exc:
        web.conn.rollback()
        raise _launch_error(exc) from exc
