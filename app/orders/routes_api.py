"""訂單總覽的 JSON API。"""

from datetime import date

from fastapi import APIRouter, File, Query, Request, UploadFile

import app.shared.web as main_mod
from app.core import vocab
from app.orders import channel as orders_channel
from app.orders import dispatch as orders_dispatch
from app.orders import repository as orders_repo
from app.shared.web import JSONResponse

router = APIRouter(prefix="/api")

PAGE_SIZE = 12


def _bad_request(message: str) -> JSONResponse:
    return JSONResponse({"detail": message}, status_code=400)


@router.get("/brands/{brand_id}/orders")
def orders(request: Request, brand_id: str, page: int = Query(default=1, ge=1)):
    """回傳單一品牌的訂單統計與固定大小的一頁訂單清單。"""
    actor = main_mod.require_actor(request)
    try:
        brand = main_mod.require_brand(brand_id, actor)
    except main_mod.NotFoundKind:
        return JSONResponse({"detail": "找不到品牌"}, status_code=404)
    summary = orders_repo.stats(main_mod.conn, brand_id, today=date.today().isoformat())
    total = orders_repo.count_orders(main_mod.conn, brand_id)
    rows = orders_repo.list_orders(
        main_mod.conn, brand_id, limit=PAGE_SIZE, offset=(page - 1) * PAGE_SIZE,
    )
    items = [
        {
            "id": row["id"],
            "order_number": row["order_number"],
            "order_date": row["order_date"],
            "total_amount": row["total_amount"],
            "order_status": row["order_status"],
            "voucher_code": row["voucher_code"],
            "attribution_override": row["attribution_override"],
        }
        for row in rows
    ]
    policy_changes = [
        {
            "policy_type": row["policy_type"],
            "policy_type_label": orders_repo.POLICY_TYPE_LABELS.get(row["policy_type"], row["policy_type"]),
            "changed_at": row["changed_at"],
            "description": row["description"],
        }
        for row in orders_repo.list_policy_changes(main_mod.conn, brand_id)
    ]
    channel_entries = [
        {
            "channel": row["channel"],
            "channel_label": vocab.channel_type_label(row["channel"]),
            "entry_date": row["entry_date"],
            "revenue": row["revenue"],
            "quantity": row["quantity"],
            "note": row["note"] or "",
        }
        for row in orders_channel.list_channel_entries(main_mod.conn, brand_id)
    ]
    return {
        "brand": {"id": brand["id"], "name": brand["name"]},
        "summary": summary,
        "orders": {
            "items": items,
            "page": page,
            "page_size": PAGE_SIZE,
            "total": total,
        },
        "policy_changes": policy_changes,
        "channel_entries": channel_entries,
    }


@router.post("/brands/{brand_id}/orders/import")
async def import_orders(request: Request, brand_id: str, drop_file: UploadFile = File(...)):
    actor = main_mod.require_actor(request)
    try:
        main_mod.require_brand(brand_id, actor)
    except main_mod.NotFoundKind:
        return JSONResponse({"detail": "找不到品牌"}, status_code=404)
    if not drop_file.filename:
        return _bad_request("沒有選到檔案。")
    content = await drop_file.read()
    if not content:
        return _bad_request("這個檔案是空的。")

    result = orders_dispatch.import_dropped_file(
        main_mod.conn, brand_id, filename=drop_file.filename, content=content,
        actor=str(actor.user_id), today=date.today().isoformat(),
    )
    if result.kind == "unknown":
        return _bad_request(result.errors[0] if result.errors else "認不出這個檔案的格式。")
    if result.kind == "easystore_orders":
        if result.errors:
            return _bad_request(result.errors[0])
        imported = result.order_result
        message = (
            f"匯入 {imported.orders_imported} 筆新訂單、更新 {imported.orders_updated} 筆、"
            f"{imported.items_imported} 個商品品項。"
        )
        return {"ok": True, "message": message}
    if result.errors:
        return _bad_request(result.errors[0])
    imported = result.shopee_result
    return {"ok": True, "message": f"匯入 {imported.imported} 筆新蝦皮訂單、更新 {imported.updated} 筆。"}


@router.post("/brands/{brand_id}/orders/sku-cost")
def set_sku_cost(request: Request, brand_id: str, payload: dict):
    actor = main_mod.require_actor(request)
    try:
        main_mod.require_brand(brand_id, actor)
    except main_mod.NotFoundKind:
        return JSONResponse({"detail": "找不到品牌"}, status_code=404)
    sku = str(payload.get("sku", ""))
    value, ok = main_mod.parse_number(str(payload.get("unit_cost", "")))
    if not ok or value is None:
        return _bad_request("單位成本請填數字。")
    try:
        orders_repo.set_sku_cost(main_mod.conn, brand_id, sku, value, actor=str(actor.user_id))
    except ValueError as exc:
        return _bad_request(str(exc))
    return {"ok": True, "message": f"「{sku}」的單位成本已更新為 {value:,.2f}。"}


@router.post("/brands/{brand_id}/orders/policy-change")
def record_policy_change(request: Request, brand_id: str, payload: dict):
    actor = main_mod.require_actor(request)
    try:
        main_mod.require_brand(brand_id, actor)
    except main_mod.NotFoundKind:
        return JSONResponse({"detail": "找不到品牌"}, status_code=404)
    try:
        orders_repo.record_policy_change(
            main_mod.conn, brand_id, policy_type=str(payload.get("policy_type", "")),
            changed_at=str(payload.get("changed_at", "")), description=str(payload.get("description", "")),
            actor=str(actor.user_id),
        )
    except ValueError as exc:
        return _bad_request(str(exc))
    return {"ok": True, "message": "已記錄口徑變更。"}


@router.post("/brands/{brand_id}/orders/channel-entry")
def record_channel_entry(request: Request, brand_id: str, payload: dict):
    actor = main_mod.require_actor(request)
    try:
        main_mod.require_brand(brand_id, actor)
    except main_mod.NotFoundKind:
        return JSONResponse({"detail": "找不到品牌"}, status_code=404)
    # 通路合不合法只在 orders_channel.record_channel_entry() 判一次（含「官網不能手動
    # 登錄」），這裡不抄第二份——不合法就是它丟 ValueError，下面統一轉成 400。
    channel = str(payload.get("channel", ""))
    revenue, revenue_ok = main_mod.parse_number(str(payload.get("revenue", "")))
    if not revenue_ok:
        return _bad_request("營收請填數字，或留空。")
    quantity, quantity_ok = main_mod.parse_number(str(payload.get("quantity", "")))
    if not quantity_ok:
        return _bad_request("數量請填數字，或留空。")
    try:
        orders_channel.record_channel_entry(
            main_mod.conn, brand_id, channel=channel, entry_date=str(payload.get("entry_date", "")),
            revenue=revenue, quantity=quantity, note=str(payload.get("note", "")) or None,
            actor=str(actor.user_id),
        )
    except ValueError as exc:
        return _bad_request(str(exc))
    return {"ok": True, "message": "已記下這筆通路營收。"}


@router.post("/brands/{brand_id}/orders/{order_id}/attribution")
def set_attribution(request: Request, brand_id: str, order_id: str, payload: dict):
    actor = main_mod.require_actor(request)
    try:
        main_mod.require_brand(brand_id, actor)
    except main_mod.NotFoundKind:
        return JSONResponse({"detail": "找不到品牌"}, status_code=404)
    excluded = bool(payload.get("excluded", False))
    try:
        orders_repo.set_attribution_override(
            main_mod.conn, brand_id, order_id, excluded, actor=str(actor.user_id),
        )
    except ValueError as exc:
        return _bad_request(str(exc))
    message = "已標記為非廣告來源，淨歸因不會算進去。" if excluded else "已取消標記，恢復計入廣告歸因。"
    return {"ok": True, "message": message}
