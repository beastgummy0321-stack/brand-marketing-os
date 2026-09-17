"""Manual handoff editing API; the existing campaign read returns the same record."""

from fastapi import APIRouter, Request
from pydantic import BaseModel, ConfigDict

import app.shared.web as web
from app.ads import manual_settings

router = APIRouter()


class ManualSettingsBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    values: dict[str, str]


@router.put("/brands/{brand_id}/campaigns/{campaign_id}/groups/{group_id}/manual-settings")
def put_settings(
    request: Request, brand_id: str, campaign_id: str, group_id: str, body: ManualSettingsBody
):
    actor = web.require_actor(request)
    web.require_brand(brand_id, actor)
    try:
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
