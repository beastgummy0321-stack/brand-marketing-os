"""app/intake/routes_offerings_api.py — 精靈第 3 步「賣什麼與數字」JSON API（F05-I07）。

因果鏈（票面已查證）：精靈原本把「售價／成本」存成 `product_fact` 的自由文字，
`product_economics` 全專案只有商品詳情頁一個呼叫端，於是每個新品牌都走不到那裡、
`breakeven_cpa` 回 None。這支路由改用同一個 facade（`app.brand_intelligence.repository`）
把「母產品＋賣法」寫成結構化的 `product` ／ `product_economics` 列，不開第二套形狀、
不自己寫 SQL（ARCHITECTURE.md §8 第 1 條）。

對外進入點：本檔的 `router`，由 `app/intake/routes_api.py` 檔尾比照 `t2_router` 併入。
"""

from datetime import UTC, datetime
from typing import cast

from fastapi import APIRouter, Request
from fastapi.responses import Response

from app.brand_intelligence import benchmarks as bi_benchmarks
from app.brand_intelligence import repository as bi_repo
from app.core.db import Conn
from app.intake import state
from app.shared import web
from app.shared.web import JSONResponse, require_actor, require_brand

router = APIRouter()

_BENCHMARK_KEYS = ("gross_margin", "shipping_cost", "close_rate")

_NUMERIC_FIELDS = (
    ("selling_price", "售價"),
    ("unit_variable_cost", "成本"),
    ("shipping_cost", "運費"),
)


def _envelope(data) -> dict:
    return {"data": data, "generated_at": datetime.now(UTC).isoformat()}


def _error(status_code: int, message: str) -> JSONResponse:
    return JSONResponse({"error": message}, status_code=status_code)


async def _json_body(request: Request) -> dict:
    try:
        body = await request.json()
    except Exception:
        return {}
    return body if isinstance(body, dict) else {}


@router.get("/api/intake/brands/{brand_id}/offerings")
def offerings_get(request: Request, brand_id: str):
    actor = require_actor(request)
    require_brand(brand_id, actor)
    conn = cast(Conn, web.conn)
    offerings = []
    # F31-I01: creation order, so a parent's sell-ways come back in the order they were entered
    # (the screen treats the first one as 單品). `list_products` itself keeps name order —
    # brief truncation and the wizard options depend on it.
    products = sorted(bi_repo.list_products(conn, brand_id),
                      key=lambda p: (p["created_at"], p["id"]))
    for product in products:
        econ = bi_repo.get_product_economics(conn, brand_id, product["id"])
        offerings.append({
            "product_id": product["id"],
            "name": product["name"],
            "parent_id": product["parent_id"],
            "selling_price": econ["selling_price"] if econ else None,
            "unit_variable_cost": econ["unit_variable_cost"] if econ else None,
            "shipping_cost": econ["shipping_cost"] if econ else None,
            "close_rate": econ["close_rate"] if econ else None,
            "assumptions": list(econ["assumptions_json"] or []) if econ else [],
        })
    benchmarks = {
        key: {
            "value": bi_benchmarks.get(key)["value"],
            "source_text": bi_benchmarks.source_text(key),
        }
        for key in _BENCHMARK_KEYS
    }
    return _envelope({
        "offerings": offerings, "benchmarks": benchmarks,
        "choice": state.offerings_choice(brand_id, conn=conn),
    })


def _display_name(parent_name: str, label: str) -> str:
    label = label.strip() or "單品"
    return f"{parent_name} · {label}" if parent_name else label


@router.post("/api/intake/brands/{brand_id}/offerings")
async def offerings_post(request: Request, brand_id: str):
    actor = require_actor(request)
    require_brand(brand_id, actor)
    actor_id = str(actor.user_id)
    body = await _json_body(request)
    offerings = body.get("offerings")
    if not isinstance(offerings, list) or not offerings:
        return _error(400, "至少要有一項要賣的東西。")
    raw_choice = body.get("choice")
    choice = state.parse_offerings_choice(raw_choice)
    if raw_choice is not None and choice is None:
        return _error(400, "請選你賣的是什麼、廣告帶來的是什麼。")
    conn = cast(Conn, web.conn)

    for offering in offerings:
        if not isinstance(offering, dict):
            return _error(400, "至少要有一項要賣的東西。")
        parent = offering.get("parent") or {}
        parent_id = parent.get("product_id")
        parent_name = str(parent.get("name") or "").strip()
        if parent_id:
            existing = bi_repo.get_product(conn, brand_id, parent_id)
            if existing is None:
                return _error(404, f"找不到產品：{parent_id}")
            parent_name = parent_name or existing["name"]
        else:
            if not parent_name:
                return _error(400, "請填品名。")
            parent_row = bi_repo.create_product(conn, brand_id, name=parent_name, actor=actor_id)
            parent_id = parent_row["id"]

        variants = offering.get("variants")
        if not isinstance(variants, list) or not variants:
            return _error(400, "至少要有一項要賣的東西。")

        for variant in variants:
            if not isinstance(variant, dict):
                return _error(400, "至少要有一項要賣的東西。")
            label = str(variant.get("label") or "").strip() or "單品"
            display_name = _display_name(parent_name, label)
            missing_field = next(
                (label_zh for field, label_zh in _NUMERIC_FIELDS if variant.get(field) is None),
                None,
            )
            if missing_field:
                suffix = "，沒有運費就填 0" if missing_field == "運費" else ""
                return _error(400, f"「{display_name}」的{missing_field}請填數字{suffix}。")

            variant_product_id = variant.get("product_id")
            if not variant_product_id:
                v_row = bi_repo.create_product(
                    conn, brand_id, name=display_name, actor=actor_id, parent_id=parent_id,
                )
                variant_product_id = v_row["id"]

            assumptions = variant.get("assumptions") or []
            try:
                # 上面的 `missing_field` 檢查已經擋掉 None，這裡三個數字實際上都有值——
                # `cast` 只是把已經驗證過的事實告訴型別檢查器，不是繞過驗證。
                bi_repo.save_product_economics(
                    conn, brand_id, variant_product_id, actor=actor_id,
                    selling_price=cast(float, variant.get("selling_price")), currency="TWD",
                    confirmed_by=actor_id,
                    unit_variable_cost=cast(float, variant.get("unit_variable_cost")),
                    shipping_cost=cast(float, variant.get("shipping_cost")),
                    close_rate=variant.get("close_rate"),
                    assumptions=assumptions,
                )
            except ValueError as exc:
                return _error(400, f"「{display_name}」{exc}")

    # F31-I01 Contract M: the saved choice lives on the draft (a finished brand reopening step 3
    # writes it on its latest completed draft), and a save moves the draft on to step 4.
    draft = state.require_draft_or_just_completed(brand_id, conn=conn)
    if choice is not None:
        state.save_offerings_choice(draft, choice, conn=conn)
    if draft["status"] == "draft" and draft["step"] < 4:
        state.touch(draft, f"/brands/{brand_id}/intake/tools", 4, conn=conn)
    return Response(status_code=204)
