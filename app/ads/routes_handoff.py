# -*- coding: utf-8 -*-
"""app/ads/routes_handoff.py — 交接包、期別配碼、投放授權、投放前檢查清單（第 8 刀從
app/ads/routes.py 拆出）。純搬移，網址與行為不變。

本檔負責的頁：
- `/brands/{b}/ads/{cycle}/handoff`                        交接包
- `/brands/{b}/ads/{cycle}/handoff/codes`、`/codes/verify` 期別配碼與校驗
- `/brands/{b}/ads/{cycle}/handoff/build`                  建立交接包
- `/brands/{b}/ads/{cycle}/handoff/missing-field`          回報找不到的欄位
- `/brands/{b}/ads/{cycle}/handoff/{package}/activate`     關卡三：投放授權
- `/brands/{b}/ads/{cycle}/handoff/qa-launch/{key}`        上線前 QA 五項提醒勾選（票 01）
- `/brands/{b}/ads/{cycle}/checklist`                      投放前檢查清單
- `/brands/{b}/ads/{cycle}/checklist/one-time/{key}`       一次性項目勾選
- `/brands/{b}/ads/{cycle}/checklist/cycle/{key}`          每期項目勾選
"""

from fastapi import APIRouter, Form, Request

import app.shared.web as main_mod
from app.ads import checklist as ads_checklist
from app.ads import codes as ads_codes
from app.ads import handoff as ads_handoff
from app.ads.routes_common import _crumb, _cycle_progress_items, _cycle_view, _require_cycle

router = APIRouter()

@router.get("/brands/{brand_id}/ads/{cycle_id}/handoff")
async def ads_handoff_page(request: Request, brand_id: str, cycle_id: str):
    """交接包：一頁照著貼，每格一鍵複製，欄位名用 Meta 現行介面的字。"""
    brand = main_mod.require_brand(brand_id)
    conn = main_mod.conn
    cycle = _require_cycle(brand_id, cycle_id)
    packages = ads_handoff.list_packages(conn, brand_id, cycle_id)
    extras = ads_handoff.build_extras(conn, brand_id, cycle_id)
    codes = ads_codes.list_codes(conn, brand_id, cycle_id)
    return main_mod.templates.TemplateResponse(
        request, "ads_handoff.html",
        main_mod.ctx(request, brand=brand, nav_current='ads', cycle=_cycle_view(conn, brand_id, cycle),
                     packages=packages, labels=ads_handoff.FIELD_LABELS, extras=extras,
                     qa_launch=ads_checklist.qa_launch_summary(conn, brand_id),
                     codes=codes, source_labels=ads_codes.SOURCE_LABELS,
                     verification=ads_codes.latest_verification(conn, brand_id, cycle_id),
                     verification_warning=ads_codes.verification_warning(conn, brand_id, cycle_id),
                     attribution=(ads_codes.attribution_summary(conn, brand_id, cycle_id)
                                  if codes else None),
                     stage_items=_cycle_progress_items(conn, brand_id, cycle),
                     breadcrumb_items=_crumb(brand, (f"{cycle['start_date']} 檔期",
                                                     f"/brands/{brand_id}/ads/{cycle_id}")),
                     **main_mod.banner_ctx(request)),
    )


@router.post("/brands/{brand_id}/ads/{cycle_id}/handoff/codes")
async def ads_handoff_generate_codes(request: Request, brand_id: str, cycle_id: str,
                                     discount_type: str = Form("percent"),
                                     discount_value: str = Form("")):
    """期別自動配碼：字碼／使用上限／效期由系統決定，折數是行銷決策由使用者填
    （GitHub issue #35）。"""
    main_mod.require_brand(brand_id)
    actor = main_mod.require_actor(request)
    _require_cycle(brand_id, cycle_id)
    back = f"/brands/{brand_id}/ads/{cycle_id}/handoff"
    value, ok = main_mod.parse_number(discount_value)
    if not ok or value is None:
        return main_mod.redirect_with_message(back, "折數請填數字。", kind="warn")
    try:
        ads_codes.generate_codes(main_mod.conn, brand_id, cycle_id,
                                 discount_type=discount_type, discount_value=value, actor=actor)
    except ValueError as exc:
        return main_mod.redirect_with_message(back, str(exc), kind="warn")
    return main_mod.redirect_with_message(
        back, "配碼好了，去 EasyStore 後台照著建立這兩組折扣碼。")


@router.post("/brands/{brand_id}/ads/{cycle_id}/handoff/codes/verify")
async def ads_handoff_verify_codes(request: Request, brand_id: str, cycle_id: str,
                                   ad_code: str = Form(""), ad_discount_type: str = Form(""),
                                   ad_discount_value: str = Form(""), ad_usage_limit: str = Form(""),
                                   ad_valid_from: str = Form(""), ad_valid_to: str = Form(""),
                                   wom_code: str = Form(""), wom_discount_type: str = Form(""),
                                   wom_discount_value: str = Form(""), wom_usage_limit: str = Form(""),
                                   wom_valid_from: str = Form(""), wom_valid_to: str = Form("")):
    """上線前逐欄校驗：規劃碼 vs 後台實際設定，不符只提醒不擋（ADR 0006）。"""
    main_mod.require_brand(brand_id)
    actor = main_mod.require_actor(request)
    _require_cycle(brand_id, cycle_id)
    back = f"/brands/{brand_id}/ads/{cycle_id}/handoff"
    actual = {
        "ad": {"code": ad_code, "discount_type": ad_discount_type,
               "discount_value": ad_discount_value, "usage_limit": ad_usage_limit,
               "valid_from": ad_valid_from, "valid_to": ad_valid_to},
        "word_of_mouth": {"code": wom_code, "discount_type": wom_discount_type,
                          "discount_value": wom_discount_value, "usage_limit": wom_usage_limit,
                          "valid_from": wom_valid_from, "valid_to": wom_valid_to},
    }
    try:
        result = ads_codes.verify(main_mod.conn, brand_id, cycle_id, actual=actual, actor=actor)
    except ValueError as exc:
        return main_mod.redirect_with_message(back, str(exc), kind="warn")
    if result["passed"]:
        return main_mod.redirect_with_message(back, "校驗過了，規劃碼跟後台設定一致。")
    return main_mod.redirect_with_message(
        back, "校驗沒過，規劃碼跟後台設定不一致，看下面的不符明細；要不要照這樣開跑由你決定。",
        kind="warn")


@router.post("/brands/{brand_id}/ads/{cycle_id}/handoff/build")
async def ads_handoff_build(request: Request, brand_id: str, cycle_id: str):
    main_mod.require_brand(brand_id)
    actor = main_mod.require_actor(request)
    _require_cycle(brand_id, cycle_id)
    count = ads_handoff.build_packages(main_mod.conn, brand_id, cycle_id, actor)
    back = f"/brands/{brand_id}/ads/{cycle_id}/handoff"
    if count == 0:
        return main_mod.redirect_with_message(
            back, "這期還沒有採用的素材，先去素材那一步確認。", kind="warn")
    return main_mod.redirect_with_message(back, f"交接包好了，共 {count} 組廣告設定。")


@router.post("/brands/{brand_id}/ads/{cycle_id}/handoff/missing-field")
async def ads_handoff_missing_field(request: Request, brand_id: str, cycle_id: str,
                                    field_key: str = Form("")):
    """「我找不到這欄位」：Meta 介面改版時，這是我們唯一會知道的管道。"""
    main_mod.require_brand(brand_id)
    actor = main_mod.require_actor(request)
    _require_cycle(brand_id, cycle_id)
    ads_handoff.report_missing_field(main_mod.conn, brand_id, cycle_id, field_key, actor)
    return main_mod.redirect_with_message(
        f"/brands/{brand_id}/ads/{cycle_id}/handoff",
        "收到了，我們會確認 Meta 是不是改了介面。這欄先跳過沒關係。")


@router.post("/brands/{brand_id}/ads/{cycle_id}/handoff/{package_id}/activate")
async def ads_handoff_activate(request: Request, brand_id: str, cycle_id: str, package_id: str,
                               meta_account_id: str = Form(""),
                               meta_campaign_id: str = Form(""),
                               meta_adset_id: str = Form(""),
                               meta_ad_id: str = Form("")):
    """關卡三：具名投放授權。使用者明確確認「已經在 Meta 開始跑了」才成立（鐵則 4）。"""
    main_mod.require_brand(brand_id)
    actor = main_mod.require_actor(request)
    _require_cycle(brand_id, cycle_id)
    back = f"/brands/{brand_id}/ads/{cycle_id}/handoff"
    try:
        ads_handoff.authorize_and_map(
            main_mod.conn, brand_id, cycle_id, package_id,
            meta_ids={"meta_account_id": meta_account_id,
                      "meta_campaign_id": meta_campaign_id,
                      "meta_adset_id": meta_adset_id, "meta_ad_id": meta_ad_id},
            actor=actor)
    except ValueError as exc:
        return main_mod.redirect_with_message(back, str(exc), kind="warn")
    return main_mod.redirect_with_message(
        back, "記下來了。之後回填成效時，系統就對得上這組廣告的數字。")


@router.post("/brands/{brand_id}/ads/{cycle_id}/handoff/qa-launch/{item_key}")
async def ads_handoff_qa_launch_toggle(request: Request, brand_id: str, cycle_id: str,
                                       item_key: str, checked: str = Form("1")):
    """上線前 QA 五項提醒（票 01，決策 0016）：確認／取消確認，只記錄不擋流程——跟下面
    「確認這組已經開始投放」（關卡三具名授權）完全獨立，不影響彼此的可點擊性。"""
    main_mod.require_brand(brand_id)
    actor = main_mod.require_actor(request)
    _require_cycle(brand_id, cycle_id)
    back = f"/brands/{brand_id}/ads/{cycle_id}/handoff"
    try:
        ads_checklist.set_qa_launch_item(main_mod.conn, brand_id, item_key, checked == "1", actor)
    except ValueError as exc:
        return main_mod.redirect_with_message(back, str(exc), kind="warn")
    return main_mod.redirect_with_message(back, "記下來了。")


@router.get("/brands/{brand_id}/ads/{cycle_id}/checklist")
async def ads_checklist_page(request: Request, brand_id: str, cycle_id: str):
    """投放前檢查清單：一次性（品牌層）＋每期必看，兩類都不擋流程，只記錄勾選（票 10）。"""
    brand = main_mod.require_brand(brand_id)
    conn = main_mod.conn
    cycle = _require_cycle(brand_id, cycle_id)
    return main_mod.templates.TemplateResponse(
        request, "ads_checklist.html",
        main_mod.ctx(request, brand=brand, nav_current='ads', cycle=_cycle_view(conn, brand_id, cycle),
                     one_time_items=ads_checklist.one_time_status(conn, brand_id),
                     cycle_items=ads_checklist.cycle_status(conn, brand_id, cycle_id),
                     stage_items=_cycle_progress_items(conn, brand_id, cycle),
                     breadcrumb_items=_crumb(brand, (f"{cycle['start_date']} 檔期",
                                                     f"/brands/{brand_id}/ads/{cycle_id}")),
                     **main_mod.banner_ctx(request)),
    )


@router.post("/brands/{brand_id}/ads/{cycle_id}/checklist/one-time/{item_key}")
async def ads_checklist_one_time_toggle(request: Request, brand_id: str, cycle_id: str,
                                        item_key: str, checked: str = Form("1")):
    main_mod.require_brand(brand_id)
    actor = main_mod.require_actor(request)
    _require_cycle(brand_id, cycle_id)
    try:
        ads_checklist.set_one_time(main_mod.conn, brand_id, item_key, checked == "1", actor)
    except ValueError as exc:
        return main_mod.redirect_with_message(
            f"/brands/{brand_id}/ads/{cycle_id}/checklist", str(exc), kind="warn")
    return main_mod.redirect_with_message(f"/brands/{brand_id}/ads/{cycle_id}/checklist", "記下來了。")


@router.post("/brands/{brand_id}/ads/{cycle_id}/checklist/cycle/{item_key}")
async def ads_checklist_cycle_toggle(request: Request, brand_id: str, cycle_id: str,
                                     item_key: str, checked: str = Form("1")):
    main_mod.require_brand(brand_id)
    actor = main_mod.require_actor(request)
    _require_cycle(brand_id, cycle_id)
    try:
        ads_checklist.set_cycle_item(main_mod.conn, brand_id, cycle_id, item_key,
                                     checked == "1", actor)
    except ValueError as exc:
        return main_mod.redirect_with_message(
            f"/brands/{brand_id}/ads/{cycle_id}/checklist", str(exc), kind="warn")
    return main_mod.redirect_with_message(f"/brands/{brand_id}/ads/{cycle_id}/checklist", "記下來了。")


