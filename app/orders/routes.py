# -*- coding: utf-8 -*-
"""app/orders/routes.py — 訂單／顧客資料的頁面路由（GitHub issue #33）。

依 app/ads/routes.py 既有做法：APIRouter ＋ 在函式內以 `main_mod` 動態取用
app.shared.web 的共用工具（修憲落地 A4：改 import app.shared.web，避免跟
main.py 兜成循環；呼叫端寫法不變）。

本檔負責的頁：
- `/brands/{b}/orders`         訂單總覽：統計卡＋萬用拖檔口＋逐 SKU 毛利
- `/brands/{b}/orders/import`  上傳（EasyStore xlsx／Meta CSV 皆走這個入口）
- `/brands/{b}/orders/sku-cost` 登記／更新單一 SKU 的單位成本
"""

from datetime import date

from fastapi import APIRouter, File, Form, Request, UploadFile

import app.shared.web as main_mod
from app.orders import channel as orders_channel
from app.orders import dispatch as orders_dispatch
from app.orders import repository as orders_repo

router = APIRouter()


def _crumb(brand: dict, *tail) -> list:
    items = [("品牌總覽", "/"), (brand["name"], f"/brands/{brand['id']}"), ("訂單", None)]
    items.extend(tail)
    if items[-1][1] is not None:
        items[-1] = (items[-1][0], None)
    return items


@router.get("/brands/{brand_id}/orders")
async def orders_home(request: Request, brand_id: str):
    brand = main_mod.require_brand(brand_id)
    conn = main_mod.conn
    summary = orders_repo.stats(conn, brand_id, today=date.today().isoformat())
    return main_mod.templates.TemplateResponse(
        request, "orders_home.html",
        main_mod.ctx(request, brand=brand, summary=summary,
                     sku_costs=orders_repo.list_sku_costs(conn, brand_id),
                     recent_orders=orders_repo.list_orders(conn, brand_id, limit=20),
                     policy_changes=orders_repo.list_policy_changes(conn, brand_id),
                     policy_type_labels=orders_repo.POLICY_TYPE_LABELS,
                     pharmacy_batches=orders_channel.list_pharmacy_batches(conn, brand_id),
                     breadcrumb_items=_crumb(brand), nav_current='ads',
                     **main_mod.banner_ctx(request)),
    )


@router.post("/brands/{brand_id}/orders/import")
async def orders_import(request: Request, brand_id: str, drop_file: UploadFile = File(...)):
    """萬用拖檔口：EasyStore 訂單匯出（.xlsx）與 Meta 廣告 CSV 都丟這裡，自動辨識路由。
    12 個月歷史回填也是這個入口——分批把不同月份的檔案拖進來即可。"""
    main_mod.require_brand(brand_id)
    actor = main_mod.require_actor(request)
    back = f"/brands/{brand_id}/orders"

    if not drop_file.filename:
        return main_mod.redirect_with_message(back, "沒有選到檔案。", kind="warn")
    content = await drop_file.read()
    if not content:
        return main_mod.redirect_with_message(back, "這個檔案是空的。", kind="warn")

    result = orders_dispatch.import_dropped_file(
        main_mod.conn, brand_id, filename=drop_file.filename, content=content, actor=actor,
        today=date.today().isoformat())

    if result.kind == "unknown":
        return main_mod.redirect_with_message(
            back, result.errors[0] if result.errors else "認不出這個檔案的格式。", kind="warn")

    if result.kind == "easystore_orders":
        if result.errors:
            return main_mod.redirect_with_message(back, result.errors[0], kind="warn")
        r = result.order_result
        msg = f"匯入 {r.orders_imported} 筆新訂單、更新 {r.orders_updated} 筆、{r.items_imported} 個商品品項。"
        msg += _late_rerun_note(result.late_reruns)
        return main_mod.redirect_with_message(back, msg)

    if result.kind == "shopee_report":
        if result.errors:
            return main_mod.redirect_with_message(back, result.errors[0], kind="warn")
        r = result.shopee_result
        return main_mod.redirect_with_message(
            back, f"匯入 {r.imported} 筆新蝦皮訂單、更新 {r.updated} 筆。")

    # meta_ads_csv
    msg = f"匯入 {result.ads_imported} 筆廣告成效資料到對應檔期。"
    if result.ads_quarantined:
        msg += f"其中 {result.ads_quarantined} 筆數字不合理，先擱在一旁不列入計算。"
    msg += _late_rerun_note(result.late_reruns)
    kind = "warn" if result.errors else "ok"
    if result.errors:
        msg += result.errors[0]
    return main_mod.redirect_with_message(back, msg, kind=kind)


def _late_rerun_note(late_reruns: list) -> str:
    """晚到資料自動觸發補件重判時，順便告訴使用者（GitHub issue #38：不靜默覆蓋）。"""
    if not late_reruns:
        return ""
    reversed_count = sum(1 for r in late_reruns if r["shift"] == "reversal")
    if reversed_count:
        return f" 有 {reversed_count} 期因此重判翻盤，已排進收件匣。"
    return f" 有 {len(late_reruns)} 期因此自動重判過一次。"


@router.post("/brands/{brand_id}/orders/sku-cost")
async def orders_sku_cost(request: Request, brand_id: str, sku: str = Form(...),
                          unit_cost: str = Form(...)):
    main_mod.require_brand(brand_id)
    actor = main_mod.require_actor(request)
    back = f"/brands/{brand_id}/orders"

    value, ok = main_mod.parse_number(unit_cost)
    if not ok or value is None:
        return main_mod.redirect_with_message(back, "單位成本請填數字。", kind="warn")
    try:
        orders_repo.set_sku_cost(main_mod.conn, brand_id, sku, value, actor=actor)
    except ValueError as exc:
        return main_mod.redirect_with_message(back, str(exc), kind="warn")
    return main_mod.redirect_with_message(back, f"「{sku}」的單位成本已更新為 {value:,.2f}。")


@router.post("/brands/{brand_id}/orders/policy-change")
async def orders_policy_change(request: Request, brand_id: str, policy_type: str = Form(...),
                                changed_at: str = Form(...), description: str = Form(...)):
    """折扣／退款口徑變更記變更日（GitHub issue #39，決策 0025 第 4 點）：跨口徑比較時，
    app/ads/reading.py 的基線比較會標注「不同尺」。"""
    main_mod.require_brand(brand_id)
    actor = main_mod.require_actor(request)
    back = f"/brands/{brand_id}/orders"
    try:
        orders_repo.record_policy_change(main_mod.conn, brand_id, policy_type=policy_type,
                                         changed_at=changed_at, description=description,
                                         actor=actor)
    except ValueError as exc:
        return main_mod.redirect_with_message(back, str(exc), kind="warn")
    return main_mod.redirect_with_message(back, "已記錄口徑變更。")


@router.post("/brands/{brand_id}/orders/pharmacy-batch")
async def orders_pharmacy_batch(request: Request, brand_id: str, batch_date: str = Form(...),
                                quantity: str = Form(""), note: str = Form("")):
    """藥局出貨批次紀錄（GitHub issue #40）：判讀看補貨間隔縮短，全部選填。"""
    main_mod.require_brand(brand_id)
    actor = main_mod.require_actor(request)
    back = f"/brands/{brand_id}/orders"

    qty_value = None
    if quantity.strip():
        qty_value, ok = main_mod.parse_number(quantity)
        if not ok:
            return main_mod.redirect_with_message(back, "數量請填數字，或留空。", kind="warn")
    try:
        orders_channel.record_pharmacy_batch(
            main_mod.conn, brand_id, batch_date=batch_date, quantity=qty_value,
            note=note or None, actor=actor)
    except ValueError as exc:
        return main_mod.redirect_with_message(back, str(exc), kind="warn")
    return main_mod.redirect_with_message(back, "已記下這筆藥局出貨批次。")


@router.post("/brands/{brand_id}/orders/{order_id}/attribution")
async def orders_set_attribution(request: Request, brand_id: str, order_id: str,
                                 excluded: str = Form("")):
    """訂單手動標記「非廣告來源」／取消標記（GitHub issue #35，決策 0025 補遺第 3 點）。"""
    main_mod.require_brand(brand_id)
    actor = main_mod.require_actor(request)
    back = f"/brands/{brand_id}/orders"
    try:
        orders_repo.set_attribution_override(main_mod.conn, brand_id, order_id,
                                             excluded == "1", actor=actor)
    except ValueError as exc:
        return main_mod.redirect_with_message(back, str(exc), kind="warn")
    msg = "已標記為非廣告來源，淨歸因不會算進去。" if excluded == "1" else "已取消標記，恢復計入廣告歸因。"
    return main_mod.redirect_with_message(back, msg)
