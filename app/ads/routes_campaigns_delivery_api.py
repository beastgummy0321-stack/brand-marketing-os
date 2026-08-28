"""T3 交付確認與駕駛艙補充 JSON API。"""


from fastapi import APIRouter, Request

import app.shared.web as main_mod
from app.ads import cockpit_extras, delivery
from app.ads import repository as ads_repo
from app.ads import repository_channel_plan as channel_repo
from app.ads.routes_common import _require_cycle
from app.shared.web import JSONResponse

router = APIRouter()


async def _body(request: Request) -> dict:
    try:
        body = await request.json()
    except ValueError:
        return {}
    return body if isinstance(body, dict) else {}


@router.get("/api/campaigns/{brand_id}/{cycle_id}/delivery")
async def delivery_get(brand_id: str, cycle_id: str):
    main_mod.require_brand(brand_id)
    _require_cycle(brand_id, cycle_id)
    return delivery.view(main_mod.conn, brand_id, cycle_id)


@router.post("/api/campaigns/{brand_id}/{cycle_id}/delivery/confirm")
async def delivery_confirm(request: Request, brand_id: str, cycle_id: str):
    main_mod.require_brand(brand_id)
    _require_cycle(brand_id, cycle_id)
    body = await _body(request)
    try:
        return delivery.confirm(main_mod.conn, brand_id, cycle_id, facts=body.get("facts"),
                                budget=body.get("budget") is True,
                                actor=main_mod.require_actor(request))
    except ValueError as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)


@router.post("/api/campaigns/{brand_id}/{cycle_id}/delivery/items/{item_id}/reject")
async def delivery_reject(request: Request, brand_id: str, cycle_id: str, item_id: str):
    main_mod.require_brand(brand_id)
    _require_cycle(brand_id, cycle_id)
    try:
        return delivery.reject_item(main_mod.conn, brand_id, cycle_id, item_id,
                                    actor=main_mod.require_actor(request))
    except ValueError as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)


# ponytail: 提案書的 GET 與交付 API 共用這個 JSON 路由登記點；只寫既有 channel_plan.enabled。
@router.put("/api/campaigns/brands/{brand_id}/cycles/{cycle_id}/channel-plan")
async def channel_plan_enabled_put(request: Request, brand_id: str, cycle_id: str):
    main_mod.require_brand(brand_id)
    _require_cycle(brand_id, cycle_id)
    body = await _body(request)
    changes = body.get("channels")
    if not isinstance(changes, list):
        return JSONResponse({"error": "請提供要調整的管道清單。"}, status_code=400)

    plans = {plan["channel"]: plan
             for plan in channel_repo.list_channel_plans(main_mod.conn, brand_id, cycle_id)}
    updates = []
    for change in changes:
        if not isinstance(change, dict) or set(change) != {"channel", "enabled"}:
            return JSONResponse({"error": "每個管道只能提供 channel 與 enabled。"}, status_code=400)
        channel = change["channel"]
        if channel not in plans:
            return JSONResponse({"error": "這期沒有這個管道可以調整。"}, status_code=400)
        if type(change["enabled"]) is not bool:
            return JSONResponse({"error": "enabled 請填 true 或 false。"}, status_code=400)
        updates.append((plans[channel], change["enabled"]))

    for plan, enabled in updates:
        channel_repo.update_channel_plan(
            main_mod.conn, brand_id, plan["id"], job=plan["job"], pct=plan["pct"],
            expected=plan["expected"], enabled=enabled, depth=plan["depth"])
    return {"channels": channel_repo.list_channel_plans(main_mod.conn, brand_id, cycle_id)}


@router.get("/api/campaigns/brands/{brand_id}/cockpit-extras")
async def cockpit_get(brand_id: str, cycle_id: str | None = None):
    main_mod.require_brand(brand_id)
    if cycle_id is None:
        cycles = ads_repo.list_cycles(main_mod.conn, brand_id)
        if not cycles:
            extras = cockpit_extras.get(main_mod.conn, brand_id, "")
            return {"legacy": extras["legacy"],
                    "task_cards": [],
                    "todo3": extras["todo3"]}
        cycle_id = cycles[0]["id"]
    _require_cycle(brand_id, cycle_id)
    return cockpit_extras.get(main_mod.conn, brand_id, cycle_id)


@router.post("/api/campaigns/brands/{brand_id}/task-cards/{card_id}/done")
async def task_card_done_for_brand(request: Request, brand_id: str, card_id: str):
    main_mod.require_brand(brand_id)
    main_mod.require_actor(request)
    try:
        return cockpit_extras.mark_done(main_mod.conn, brand_id, card_id)
    except ValueError as exc:
        return JSONResponse({"error": str(exc)}, status_code=404)
