# -*- coding: utf-8 -*-
"""訂單總覽的唯讀 JSON API。"""

from datetime import date

from fastapi import APIRouter, Query
from fastapi.responses import JSONResponse

import app.shared.web as main_mod
from app.orders import repository as orders_repo

router = APIRouter(prefix="/api")

PAGE_SIZE = 12


@router.get("/brands/{brand_id}/orders")
async def orders(brand_id: str, page: int = Query(default=1, ge=1)):
    """回傳單一品牌的訂單統計與固定大小的一頁訂單清單。"""
    try:
        brand = main_mod.require_brand(brand_id)
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
    return {
        "brand": {"id": brand["id"], "name": brand["name"]},
        "summary": summary,
        "orders": {
            "items": items,
            "page": page,
            "page_size": PAGE_SIZE,
            "total": total,
        },
    }
