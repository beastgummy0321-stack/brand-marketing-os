# -*- coding: utf-8 -*-
"""app/ads/routes_connections.py — Pixel／GA4 教學頁、資料與連線頁、萬用匯入、把舊資料
搬進來（第 8 刀從 app/ads/routes.py 拆出）。純搬移，網址與行為不變。

本檔負責的頁：
- `/brands/{b}/ads/pixel-guide`、`/ga4-guide`      Pixel／GA4 教學頁
- `/brands/{b}/ads/connections`                    資料與連線頁
- `/brands/{b}/ads/connections/import`             萬用檔案匯入
- `/brands/{b}/ads/data-migration`                 把舊資料搬進來

`orders_repo`／`orders_dispatch`：第 7 刀留下的注入變數，一律 `ads_routes.` 即時查值，
理由見 app/ads/routes.py 檔頭說明——不能靜態 `from ... import orders_repo`，main.py
的注入發生在 import 之後。
"""

from datetime import date

from fastapi import APIRouter, File, Request, UploadFile

import app.shared.web as main_mod
from app.ads import data_onboarding
from app.ads import ga4_sync
from app.ads import routes as ads_routes
from app.ads import sync as ads_sync
from app.ads.routes_common import _crumb

router = APIRouter()

@router.get("/brands/{brand_id}/ads/pixel-guide")
async def ads_pixel_guide(request: Request, brand_id: str):
    """Pixel 教學頁：簡短介紹＋導向各平台官方教學連結（決策 0023 第 13 點）。

    註冊順序要在 `/brands/{brand_id}/ads/{cycle_id}` 之前——不然 "pixel-guide" 會被那條路由
    當成 cycle_id 吃掉，變成「找不到廣告檔期」的 404。
    """
    brand = main_mod.require_brand(brand_id)
    return main_mod.templates.TemplateResponse(
        request, "ads_pixel_guide.html",
        main_mod.ctx(request, brand=brand, nav_current='ads',
                     breadcrumb_items=_crumb(brand, ("Pixel 安裝教學", None)),
                     **main_mod.banner_ctx(request)),
    )


@router.get("/brands/{brand_id}/ads/ga4-guide")
async def ads_ga4_guide(request: Request, brand_id: str):
    """GA4 服務帳戶設定教學頁：簡短介紹＋逐步操作＋官方連結（GitHub issue #34）。

    版型比照 ads_pixel_guide：簡介＋逐步＋官方連結。註冊順序同理要在
    `/brands/{brand_id}/ads/{cycle_id}` 之前，避免被那條路由當成 cycle_id 吃掉。
    """
    brand = main_mod.require_brand(brand_id)
    return main_mod.templates.TemplateResponse(
        request, "ads_ga4_guide.html",
        main_mod.ctx(request, brand=brand, nav_current='ads',
                     breadcrumb_items=_crumb(brand, ("GA4 服務帳戶教學", None)),
                     **main_mod.banner_ctx(request)),
    )


def _late_rerun_note(late_reruns: list) -> str:
    """跟 app/orders/routes.py 同名函式邏輯一致（那邊是私有函式，不便跨模組匯入，
    這裡是純粹的訊息組字，不是嗅探／匯入邏輯，複製這幾行不算重寫本票禁區）。"""
    if not late_reruns:
        return ""
    reversed_count = sum(1 for r in late_reruns if r["shift"] == "reversal")
    if reversed_count:
        return f" 有 {reversed_count} 期因此重判翻盤，已排進收件匣。"
    return f" 有 {len(late_reruns)} 期因此自動重判過一次。"


@router.get("/brands/{brand_id}/ads/connections")
async def ads_connections_page(request: Request, brand_id: str):
    """資料與連線頁（GitHub issue #44）：萬用檔案口＋Meta／GA4／訂單三個入口對稱排列＋
    待認領入口；金鑰一律深連結到 /settings 對應分區錨點（決策 0028、0029 第 12 點）。"""
    brand = main_mod.require_brand(brand_id)
    conn = main_mod.conn
    order_stats = ads_routes.orders_repo.stats(conn, brand_id, today=date.today().isoformat())
    return main_mod.templates.TemplateResponse(
        request, "ads_connections.html",
        main_mod.ctx(request, brand=brand, nav_current='ads',
                     meta_connected=ads_sync.is_configured(conn),
                     ga4_configured=ga4_sync.is_configured(conn),
                     pending_claims=len(ads_sync.list_pending_claims(conn, brand_id)),
                     has_order_data=order_stats["has_history"],
                     breadcrumb_items=_crumb(brand, ("資料與連線", None)),
                     **main_mod.banner_ctx(request)),
    )


@router.post("/brands/{brand_id}/ads/connections/import")
async def ads_connections_import(request: Request, brand_id: str,
                                 drop_file: UploadFile = File(...)):
    """廣告區薄匯入路由（GitHub issue #44）：收檔 → 呼叫既有的
    app.orders.dispatch.import_dropped_file() → 導回本頁。嗅探與匯入邏輯一行不重寫；
    既有 app/orders/routes.py 的 orders_import 導回目的地寫死是 /orders，這裡的
    使用情境需要留在資料與連線頁看結果，所以另開這條薄路由（決策 0029 第 13 點）。"""
    main_mod.require_brand(brand_id)
    actor = main_mod.require_actor(request)
    back = f"/brands/{brand_id}/ads/connections"

    if not drop_file.filename:
        return main_mod.redirect_with_message(back, "沒有選到檔案。", kind="danger")
    content = await drop_file.read()
    if not content:
        return main_mod.redirect_with_message(back, "這個檔案是空的。", kind="danger")

    result = ads_routes.orders_dispatch.import_dropped_file(
        main_mod.conn, brand_id, filename=drop_file.filename, content=content, actor=actor,
        today=date.today().isoformat())

    if result.kind == "unknown":
        return main_mod.redirect_with_message(
            back, result.errors[0] if result.errors else "認不出這個檔案的格式。", kind="danger")

    if result.kind == "easystore_orders":
        if result.errors:
            return main_mod.redirect_with_message(back, result.errors[0], kind="danger")
        r = result.order_result
        msg = f"匯入 {r.orders_imported} 筆新訂單、更新 {r.orders_updated} 筆、{r.items_imported} 個商品品項。"
        msg += _late_rerun_note(result.late_reruns)
        return main_mod.redirect_with_message(back, msg)

    if result.kind == "shopee_report":
        if result.errors:
            return main_mod.redirect_with_message(back, result.errors[0], kind="danger")
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


@router.get("/brands/{brand_id}/ads/data-migration")
async def ads_data_migration(request: Request, brand_id: str):
    """把舊資料搬進來（票 F7，決策 0039 第一節）：一次性導入檢查清單。四格狀態、部分
    基線小結、成熟門檻報告全部從既有資料查詢推導（app/ads/data_onboarding.py），不建新表、
    不存精靈狀態，天然冪等。

    註冊順序要在 `/brands/{brand_id}/ads/{cycle_id}` 之前——同 pixel-guide／ga4-guide／
    interview／learnings 的先例，不然 "data-migration" 會被那條萬用路由當成 cycle_id 吃掉。
    """
    brand = main_mod.require_brand(brand_id)
    conn = main_mod.conn
    checklist = data_onboarding.build_checklist(conn, brand_id)
    progress = data_onboarding.completion(checklist)
    maturity_rows = data_onboarding.maturity_report(conn, brand_id)
    return main_mod.templates.TemplateResponse(
        request, "ads_data_migration.html",
        main_mod.ctx(request, brand=brand, nav_current='ads',
                     checklist=checklist, progress=progress,
                     rail_items=data_onboarding.rail_items(checklist, progress["next_item"]),
                     maturity_rows=maturity_rows,
                     maturity_all_met=all(row["met"] for row in maturity_rows),
                     any_data=any(item["has_data"] for item in checklist if not item["optional"]),
                     breadcrumb_items=_crumb(brand, ("把舊資料搬進來", None)),
                     **main_mod.banner_ctx(request)),
    )


