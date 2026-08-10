# -*- coding: utf-8 -*-
"""app/ads/routes_interview.py — 前朝教訓訪談、累積智慧、規則卡決定（第 8 刀從
app/ads/routes.py 拆出）。純搬移，網址與行為不變。

本檔負責的頁：
- `/brands/{b}/ads/interview`                          前朝教訓訪談
- `/brands/{b}/ads/learnings`                          累積智慧頁
- `/brands/{b}/ads/learnings/ledger/{id}/deactivate`   下架已確認學習
- `/brands/{b}/ads/learnings/rules/{id}/deactivate`    下架生效中的禁令
- `/brands/{b}/ads/learnings/rules/{id}/reconfirm`     延續待確認規則（票 01-rule-expiry-reconfirm）
- `/brands/{b}/ads/rule-cards/{id}/{action}`           規則卡接受／不接受
  （原本在檔案最後段，跟累積智慧頁同一個「學習→規則」流程，搬來同一檔）
"""

from typing import List, Optional

from fastapi import APIRouter, Form, Request

import app.shared.web as main_mod
from app.ads import fingerprint
from app.ads import interview as ads_interview
from app.ads import nextcycle
from app.ads import reading as ads_reading
from app.ads import repository as ads_repo
from app.ads.routes_common import _crumb
from app.brand_intelligence import repository as bi
from app.llm import context_compiler

router = APIRouter()

def _safe_next(brand_id: str, next_url: Optional[str]) -> Optional[str]:
    """`next` 跳轉參數的白名單檢查（票 F7）：只接受同品牌底下的路徑，避免這個公開可帶
    query string 的參數被拿去開放轉址；不合規就靜靜退回 None，呼叫端自己接預設值。"""
    if next_url and next_url.startswith(f"/brands/{brand_id}/"):
        return next_url
    return None


@router.get("/brands/{brand_id}/ads/interview")
async def ads_interview_get(request: Request, brand_id: str, next: Optional[str] = None):
    """前朝教訓訪談（GitHub issue #55）：老品牌第一天就能把既有經驗交給系統。

    註冊順序要在 `/brands/{brand_id}/ads/{cycle_id}` 之前——不然 "interview" 會被那條路由
    當成 cycle_id 吃掉，變成「找不到廣告檔期」的 404（同 pixel-guide／ga4-guide 的先例）。

    `next`（票 F7）：搬家精靈檢查清單頁把這格標「選做」的同時，需要訪談送出後跳回清單頁
    而不是廣告首頁——加這個跳轉參數，不重寫第二份訪談流程。
    """
    brand = main_mod.require_brand(brand_id)
    next_url = _safe_next(brand_id, next)
    return main_mod.templates.TemplateResponse(
        request, "ads_interview.html",
        main_mod.ctx(request, brand=brand, nav_current='ads', axes=fingerprint.AXES,
                     next_url=next_url,
                     breadcrumb_items=_crumb(brand, ("前朝教訓訪談", None)),
                     **main_mod.banner_ctx(request)),
    )


@router.post("/brands/{brand_id}/ads/interview")
async def ads_interview_post(request: Request, brand_id: str,
                             bad_angle: Optional[List[str]] = Form(None),
                             good_angle: Optional[List[str]] = Form(None),
                             bad_tone: Optional[List[str]] = Form(None),
                             good_tone: Optional[List[str]] = Form(None),
                             bad_format: Optional[List[str]] = Form(None),
                             good_format: Optional[List[str]] = Form(None),
                             bad_selling_point: Optional[List[str]] = Form(None),
                             good_selling_point: Optional[List[str]] = Form(None),
                             note: str = Form(""), next: Optional[str] = Form(None)):
    """全程選填、跳過不擋任何流程（決策 0025）：什麼都不勾也能送出，等同跳過。"""
    main_mod.require_brand(brand_id)
    conn = main_mod.conn
    actor = main_mod.require_actor(request)

    bad = {"angle": bad_angle or [], "tone": bad_tone or [],
           "format": bad_format or [], "selling_point": bad_selling_point or []}
    good = {"angle": good_angle or [], "tone": good_tone or [],
            "format": good_format or [], "selling_point": good_selling_point or []}
    result = ads_interview.submit(conn, brand_id, bad=bad, good=good, note=note, actor=actor)

    card_count = len(result["rule_cards"])
    hyp_count = len(result["hypotheses"])
    if not card_count and not hyp_count:
        message = "這次沒有勾選任何項目，之後隨時可以回來補。"
    else:
        message = f"記下了 {card_count} 條想避開的方向、{hyp_count} 條想再驗證的方向。"
    if result["conflicts"]:
        # 兩邊都勾＝矛盾，系統不替使用者挑一邊，誠實說哪幾項沒記（見 interview._drop_conflicts）
        message += "；" + "、".join(result["conflicts"]) + " 兩邊都勾了，這幾項先沒記，之後可以回來擇一。"
    back = _safe_next(brand_id, next) or f"/brands/{brand_id}/ads"
    return main_mod.redirect_with_message(back, message)


_PENDING_HYPOTHESIS_LABELS = {"proposed": "待驗證", "testing": "驗證中"}


def _learning_meta_line(conn, brand_id: str, entry: dict) -> str:
    """組「依據」欄的人話：適用範圍／來源期別／樣本數／可信度，程式組字不經 LLM
    （決策 0030 第 11 點：這些值本來就是程式帶入，不是模型判斷）。

    修憲落地 G4（決策 0035 第三節第 8、10 點）：`confidence` 是 ledger 自己的可信度分級
    （`reading.LEDGER_CONFIDENCE_LABELS`，樣本數＋是否重測過），不是資料成色標籤——兩者
    意義不同，不能互換顯示。`needs_revalidation` 這個欄位以前全庫沒有一行寫入過，這裡是
    它第一次真的被讀出來用。"""
    parts = []
    if entry["product_id"]:
        product = bi.get_product(conn, brand_id, entry["product_id"])
        parts.append(product["name"] if product else "已刪除的產品")
    else:
        parts.append("品牌整體")
    if entry["source_cycle_id"]:
        cycle = ads_repo.get_cycle(conn, brand_id, entry["source_cycle_id"])
        if cycle:
            parts.append(f"來源：{cycle['start_date']} 期")
    if entry["sample_size"]:
        parts.append(f"樣本 {entry['sample_size']}")
    if entry["confidence"]:
        parts.append(ads_reading.LEDGER_CONFIDENCE_LABELS.get(entry["confidence"],
                                                              entry["confidence"]))
    if entry["needs_revalidation"]:
        parts.append("建議找機會重新驗證")
    return " ・ ".join(parts)


@router.get("/brands/{brand_id}/ads/learnings")
async def ads_learnings_page(request: Request, brand_id: str):
    """累積智慧頁（GitHub issue #56）：三段——已確認學習／生效中的禁令／還沒處理的候選。

    註冊順序要在 `/brands/{brand_id}/ads/{cycle_id}` 之前——不然 "learnings" 會被那條路由
    當成 cycle_id 吃掉，變成「找不到廣告檔期」的 404（同 pixel-guide／ga4-guide／interview
    的先例）。
    """
    brand = main_mod.require_brand(brand_id)
    conn = main_mod.conn

    learnings = ads_repo.list_learning_ledger(conn, brand_id)
    for entry in learnings:
        entry["meta_line"] = _learning_meta_line(conn, brand_id, entry)

    # 規則有效期逾期未確認清單（票 01-rule-expiry-reconfirm，ADR 0012 第一節）：先撈這份
    # ——它內部會先掃一次逾期未確認的規則（rule_lifecycle.sweep_expired_rules），確保
    # 底下 active_bans／overflow_rules 讀到的是最新狀態，不是掃描前的舊資料。
    pending_reconfirm_rules = bi.list_pending_reconfirm_rules(conn, brand_id)

    active_bans = nextcycle.list_active_bans(conn, brand_id)
    pending_cards = nextcycle.list_pending_rule_cards(conn, brand_id)
    observing_signals = nextcycle.list_observing_signals(conn, brand_id)
    pending_hypotheses = [
        {**h, "status_label": _PENDING_HYPOTHESIS_LABELS.get(h["status"], h["status"])}
        for h in bi.list_strategy_hypotheses(conn, brand_id)
        if h["status"] in ads_reading.PENDING_HYPOTHESIS_STATUSES
    ]
    # 規則進 prompt 超過上限而這次未生效的清單（票 02-prompt-cap-and-overflow-list，
    # 決策 0012 第三節：不悄悄丟棄，累積智慧頁列出來）。
    overflow_rules = context_compiler.list_overflow_rules(conn, brand_id)

    return main_mod.templates.TemplateResponse(
        request, "ads_learnings.html",
        main_mod.ctx(request, brand=brand, nav_current='ads',
                     learnings=learnings, active_bans=active_bans,
                     pending_cards=pending_cards, observing_signals=observing_signals,
                     pending_hypotheses=pending_hypotheses, overflow_rules=overflow_rules,
                     pending_reconfirm_rules=pending_reconfirm_rules,
                     breadcrumb_items=_crumb(brand, ("累積智慧", None)),
                     **main_mod.banner_ctx(request)),
    )


@router.post("/brands/{brand_id}/ads/learnings/ledger/{entry_id}/deactivate")
async def ads_learnings_deactivate_ledger(request: Request, brand_id: str, entry_id: str):
    """下架一條已確認學習，下架後不再進 context_compiler 組出的 prompt（票 #56）。"""
    main_mod.require_brand(brand_id)
    actor = main_mod.require_actor(request)
    back = f"/brands/{brand_id}/ads/learnings"
    try:
        ads_repo.deactivate_learning_ledger_entry(main_mod.conn, brand_id, entry_id, actor=actor)
    except ValueError as err:
        return main_mod.redirect_with_message(back, str(err), kind="danger")
    return main_mod.redirect_with_message(back, "已下架這條學習，之後生成內容不會再引用它。")


@router.post("/brands/{brand_id}/ads/learnings/rules/{rule_id}/deactivate")
async def ads_learnings_deactivate_rule(request: Request, brand_id: str, rule_id: str):
    """下架一條生效中的禁令，下架後不再進 context_compiler 組出的 prompt（票 #56）。"""
    main_mod.require_brand(brand_id)
    actor = main_mod.require_actor(request)
    back = f"/brands/{brand_id}/ads/learnings"
    try:
        bi.deactivate_rule(main_mod.conn, brand_id, rule_id, actor=actor)
    except ValueError as err:
        return main_mod.redirect_with_message(back, str(err), kind="danger")
    return main_mod.redirect_with_message(back, "已下架這條禁令，之後生成內容不會再避開它。")


@router.post("/brands/{brand_id}/ads/learnings/rules/{rule_id}/reconfirm")
async def ads_learnings_reconfirm_rule(request: Request, brand_id: str, rule_id: str):
    """待確認規則的「延續」（票 01-rule-expiry-reconfirm，ADR 0012 第一節）：恢復生效、
    更新確認時間，不必重新輸入規則內容。"""
    main_mod.require_brand(brand_id)
    actor = main_mod.require_actor(request)
    back = f"/brands/{brand_id}/ads/learnings"
    try:
        bi.reconfirm_rule(main_mod.conn, brand_id, rule_id, actor=actor)
    except ValueError as err:
        return main_mod.redirect_with_message(back, str(err), kind="danger")
    return main_mod.redirect_with_message(back, "已延續這條規則，重新進入生成內容的判斷依據。")


@router.post("/brands/{brand_id}/ads/rule-cards/{card_id}/{action}")
async def ads_rule_card_decide(request: Request, brand_id: str, card_id: str, action: str):
    """規則卡的決定。接受才升級為品牌智庫的長期規則——學習不會自己變成規則（鐵則 3）。"""
    main_mod.require_brand(brand_id)
    actor = main_mod.require_actor(request)
    back = request.headers.get("referer") or f"/brands/{brand_id}/ads"
    try:
        card = nextcycle.decide_rule_card(main_mod.conn, brand_id, card_id,
                                          accept=(action == "accept"), actor=actor)
    except ValueError as exc:
        return main_mod.redirect_with_message(back.split("?")[0], str(exc), kind="warn")
    if card["fingerprint_axis"] == nextcycle.OVERCLAIM_CLAIM_AXIS:
        msg = ("已經登記為禁用宣稱，之後掃描與生成都會避開這句話。" if card["status"] == "accepted"
               else "好，這句先不登記。")
    else:
        msg = ("記住了，以後產素材會避開這個方向。" if card["status"] == "accepted"
               else "好，這條不記成長期規則。")
    return main_mod.redirect_with_message(back.split("?")[0], msg)


