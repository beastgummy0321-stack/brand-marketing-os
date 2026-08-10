# -*- coding: utf-8 -*-
"""app/brand_intelligence/routes.py — 品牌智庫業務路由（修憲落地 A4，從 app/main.py 拆出）。

原本 87 條路由跟共用 web 工具（conn／templates／require_brand…）擠在同一個檔，
main.py 因此頂著「組裝根永久豁免」的身分卻塞滿業務邏輯，還被 app/ads、app/orders、
app/intake 反向 import（main → ads.routes → main 的循環）。拆出來以後：

- 共用 web 工具改放 `app/shared/web.py`，這裡跟 app/ads/routes.py 等分支路由一樣，
  只單向依賴那一份，不再互相纏繞。
- `conn`（全程共用、可被 reopen_connection() 換掉的連線）一律寫成 `web.conn`
  即時查值，其餘工具（require_brand／ctx／templates…）是建立後不再改變的函式物件，
  用一般 `from app.shared.web import ...` 靜態匯入即可，呼叫端寫法不變。

例外（刻意留在 app/main.py，未搬進本檔）：首頁「今天要處理的事」與 AI／Meta／GA4
設定頁——這兩處會直接碰 `app.ads`（today todos 讀廣告到期提醒；設定頁讀寫 Meta／GA4
連線設定），而 A2 落地的 import 掃描測試（test_architecture_boundaries.py）目前只允許
`app/main.py` 這個路徑 import 分支專屬層，本檔不在允許清單內、不能改測試去配合。
這是搬移過程中新發現的既有邊界，非本票新增的例外，詳見票 A4 回報。
"""

import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, File, Form, Request, UploadFile
from fastapi.responses import FileResponse, RedirectResponse

from app import mock_data as md
from app.brand_intelligence import customer_voice as cv_mod
from app.brand_intelligence import product_ai
from app.brand_intelligence import report as brand_report_mod
from app.brand_intelligence import repository as repo
from app.core import backup as corebackup
from app.core import cleanup
from app.core import creative_assets
from app.core import interrupts as core_interrupts
from app.core import prototype_phase as core_prototype_phase
from app.core.db import new_id
from app.intake import state as intake_state
from app.shared import web
from app.shared.web import (
    NotFoundKind,
    _num_str,
    _with_brand_names,
    banner_ctx,
    clean,
    ctx,
    list_archived_brands,
    list_products,
    parse_number,
    pending_brand_fact_count,
    pending_product_layer_count,
    redirect_with_message,
    report_staleness,
    require_actor,
    require_brand,
    require_product,
    scope_label,
    templates,
)

router = APIRouter()


# ---------------------------------------------------------------------------
# 資料存取的小包裝：補上「畫面需要、但 repository 沒有」的顯示邏輯（業務專屬，
# 不是共用 web 工具，所以留在這裡而不是 app/shared/web.py）
# ---------------------------------------------------------------------------

def _create_source_ref(brand_id: str, actor: str, text: str) -> Optional[str]:
    """使用者填的「資料來源」自由文字 -> source_reference 表一筆列的 id；空字串回 None。"""
    text = clean(text)
    if not text:
        return None
    row = repo.create_source_reference(
        web.conn, brand_id, actor=actor, title=text, source_type="other",
        captured_date=datetime.now(timezone.utc).date().isoformat(),
    )
    return row["id"]


def _source_ref_text(brand_id: str, source_reference_id: Optional[str]) -> Optional[str]:
    if not source_reference_id:
        return None
    row = repo.get_source_reference(web.conn, brand_id, source_reference_id)
    return row["title"] if row else None


def _augment_fact(brand_id: str, fact: dict) -> dict:
    """補上畫面要的 source_reference 顯示文字，並把 confirmed_at 轉成 datetime
    （fact_item.html 對它呼叫 .strftime()）。"""
    fact = dict(fact)
    fact["source_reference"] = _source_ref_text(brand_id, fact.get("source_reference_id"))
    if fact.get("confirmed_at"):
        fact["confirmed_at"] = datetime.fromisoformat(fact["confirmed_at"])
    return fact


def _scan_budget_error(brand_id: str, cost: Optional[float] = None, action: str = "這次調研",
                        fallback_hint: str = "或先用「新增這個產品」手動建立。") -> Optional[str]:
    """產品快掃／再次調研／調研交接包貼回修復共用的超預算檢查，通過回 None。

    票 M2：核心檢查（已花費 + 這次預估 vs 上限，US$ 三個數字同一幣別直接比）搬進
    app/core/settings.budget_exceeded_message()——廣告分支的計畫／素材生成現在也共用
    同一個函式，這裡只是保留原本的呼叫簽名（cost 預設值＝產品快掃的校準值）給既有呼叫端用。
    """
    from app.core import settings as coresettings
    cost = product_ai.COST_PRODUCT_SCAN if cost is None else cost
    return coresettings.budget_exceeded_message(
        web.conn, brand_id, cost, action=action, fallback_hint=fallback_hint)


def _apply_product_scan_result(brand_id: str, product_id: str, actor: str,
                                source_reference_id: Optional[str], result: dict) -> tuple:
    """把快掃／再次調研結果套進一個產品：跳過跟既有事實（不論 pending 或 confirmed）同 label
    的結果，避免重複堆積；價格有抓到且這個產品目前完全沒有經濟數字列時，才建一筆 pending。
    回傳 (新增事實數, 跳過事實數, 是否新建了待確認經濟數字)。"""
    existing_labels = {f["label"] for f in repo.list_product_facts(web.conn, brand_id, product_id)}
    added, skipped = 0, 0
    for f in result["facts"]:
        if f["label"] in existing_labels:
            skipped += 1
            continue
        repo.create_product_fact(web.conn, brand_id, product_id, actor=actor,
                                 fact_type=f["fact_type"], label=f["label"], value=f["value"],
                                 status="pending", source_reference_id=source_reference_id)
        existing_labels.add(f["label"])
        added += 1
    price_created = False
    price = result.get("price")
    if price and repo.get_product_economics(web.conn, brand_id, product_id) is None:
        repo.create_pending_product_economics(
            web.conn, brand_id, product_id, actor=actor,
            selling_price=price["amount"], currency=price["currency"],
            source_reference_id=source_reference_id,
        )
        price_created = True
    return added, skipped, price_created


def _augment_claim(brand_id: str, claim: dict) -> dict:
    claim = dict(claim)
    claim["evidence_source_reference"] = _source_ref_text(brand_id, claim.get("evidence_source_reference_id"))
    return claim


def _augment_asset(brand_id: str, asset: dict) -> dict:
    """補上畫面要的檔名（縮圖網址用）與掛載產品的名稱。"""
    asset = dict(asset)
    asset["filename"] = Path(asset["file_path"]).name
    product = repo.get_product(web.conn, brand_id, asset["product_id"]) if asset.get("product_id") else None
    asset["product_name"] = product["name"] if product else None
    return asset


# ---------------------------------------------------------------------------
# 全站打斷佇列（決策 0026）：收件匣頁＋通用「知道了」
# ---------------------------------------------------------------------------

@router.get("/inbox")
async def inbox(request: Request):
    return templates.TemplateResponse(request, "inbox.html", ctx(
        request, brand=None,
        open_items=_with_brand_names(core_interrupts.list_open(web.conn)),
        done_items=_with_brand_names(core_interrupts.list_done(web.conn)),
        **banner_ctx(request),
    ))


@router.get("/system/prototype-phase")
async def prototype_phase_detail(request: Request):
    """原型階段結束提醒的「詳情」頁（修憲落地 A6 修正）：唯讀，逐項列出四項技術豁免現況，
    使用者從打斷佇列卡片點進來才看得到到底要重新決定什麼。"""
    return templates.TemplateResponse(request, "prototype_phase.html", ctx(
        request, brand=None,
        ended=core_prototype_phase.has_ended(web.conn),
        exemptions=core_prototype_phase.EXEMPTIONS,
        **banner_ctx(request),
    ))


@router.post("/interrupts/{interrupt_id}/resolve")
async def interrupt_resolve(request: Request, interrupt_id: str):
    actor = require_actor(request)
    core_interrupts.resolve(web.conn, interrupt_id, actor=actor)
    back = (request.headers.get("referer") or "/inbox").split("?")[0]
    return redirect_with_message(back, "好，知道了。")


@router.get("/brands/new")
async def brand_new_get(request: Request):
    return templates.TemplateResponse(request, "brand_new.html", ctx(
        request, brand=None, values={}, errors={}, nav_current='hub',
    ))


@router.post("/brands/new")
async def brand_new_post(request: Request, name: str = Form(""), client_name: str = Form("")):
    actor = require_actor(request)
    values = {"name": name, "client_name": client_name}
    errors = {}
    name_c = clean(name)
    if not name_c:
        errors["name"] = "請填寫品牌名稱。"
    if errors:
        return templates.TemplateResponse(request, "brand_new.html", ctx(
            request, brand=None, values=values, errors=errors, nav_current='hub',
        ), status_code=400)
    brand = repo.create_brand(web.conn, name=name_c, client_name=clean(client_name), actor=actor)
    return redirect_with_message(f"/brands/{brand['id']}", f"已新增品牌「{name_c}」。")


# ---------------------------------------------------------------------------
# 品牌檔案頁 ＋ 編輯品牌
# ---------------------------------------------------------------------------

@router.get("/brands/{brand_id}")
async def brand_menu(request: Request, brand_id: str, continue_dismissed: Optional[str] = None):
    """品牌功能選單頁（issue #8 決策 0021）：地基資料收進「品牌智庫」子頁，這裡只留功能入口
    ＋跨分類的待確認提醒卡。"""
    brand = require_brand(brand_id)
    intake_draft = intake_state.get_draft(brand_id)
    return templates.TemplateResponse(request, "brand_menu.html", ctx(
        request, brand=brand,
        intake_draft=intake_draft, continue_dismissed=continue_dismissed == "1",
        pending_facts_count=pending_brand_fact_count(brand_id),
        pending_product_layer_count=pending_product_layer_count(brand_id),
        nav_current='hub',
        **banner_ctx(request),
    ))


# 票 C：conversion_goal 選單選項（值來自 repo.CONVERSION_GOALS，順序不得自創，
# 標籤來自 md.CONVERSION_GOAL_LABELS）。組出來的 pairs 給 brand_edit.html 的下拉選單用。
def _conversion_goal_options() -> list:
    return [(v, md.CONVERSION_GOAL_LABELS[v]) for v in repo.CONVERSION_GOALS]


# ADR 0014：業種選單選項（值來自 repo.INDUSTRIES，標籤來自 md.INDUSTRY_LABELS）。
# 沒有這個選單，brand.industry 永遠是 NULL，節日相關性比對只會命中標「all」的節日。
def _industry_options() -> list:
    return [(v, md.INDUSTRY_LABELS[v]) for v in repo.INDUSTRIES]


def _persona_conversion_goal_default(persona: str) -> Optional[str]:
    """人設沒填 conversion_goal 時的預設值：從既有的 persona_switch_defaults() 開關表
    推回轉換目標，不另外發明第二張人設對照表。推法對齊
    repo.compute_methodology_switches() 對「站內交易」的定義本身就是
    conversion_goal == 'purchase'：站內交易開＝purchase；沒有站內交易但有自有網站
    （服務／預約制）＝booking；兩者都沒有（KOL／其他）＝awareness。"""
    if persona not in md.PERSONA_SWITCH_DEFAULTS:
        return None
    switches = md.persona_switch_defaults(persona)
    if switches["站內交易"]:
        return "purchase"
    if switches["有自有網站"]:
        return "booking"
    return "awareness"


def _brand_edit_form_ctx(request: Request, brand: dict, values: dict, errors: dict):
    return ctx(
        request, brand=brand, values=values, errors=errors, nav_current='hub',
        persona_types=md.PERSONA_TYPES, market_regions=md.MARKET_REGIONS,
        conversion_goals=_conversion_goal_options(), industries=_industry_options(),
    )


@router.get("/brands/{brand_id}/edit")
async def brand_edit_get(request: Request, brand_id: str):
    brand = require_brand(brand_id)
    values = {
        "name": brand["name"], "client_name": brand["client_name"] or "", "status": brand["status"],
        "persona": "", "market_region": brand["market_region"] or "",
        "conversion_goal": brand["conversion_goal"] or "", "industry": brand["industry"] or "",
    }
    return templates.TemplateResponse(request, "brand_edit.html",
                                       _brand_edit_form_ctx(request, brand, values, {}))


@router.post("/brands/{brand_id}/edit")
async def brand_edit_post(request: Request, brand_id: str, name: str = Form(""),
                           client_name: str = Form(""), status: str = Form("active"),
                           persona: str = Form(""), market_region: str = Form(""),
                           conversion_goal: str = Form(""), industry: str = Form("")):
    actor = require_actor(request)
    brand = require_brand(brand_id)
    values = {"name": name, "client_name": client_name, "status": status,
              "persona": persona, "market_region": market_region, "conversion_goal": conversion_goal,
              "industry": industry}
    errors = {}
    name_c = clean(name)
    if not name_c:
        errors["name"] = "請填寫品牌名稱。"
    if status not in ("active", "archived"):
        errors["status"] = "請選擇品牌狀態。"
    region_c = clean(market_region)
    if region_c and region_c not in dict(md.MARKET_REGIONS):
        errors["market_region"] = "請選擇有效的市場地區。"
    goal_c = clean(conversion_goal)
    if goal_c and goal_c not in repo.CONVERSION_GOALS:
        errors["conversion_goal"] = "請選擇有效的廣告目標。"
    industry_c = clean(industry)
    if industry_c and industry_c not in repo.INDUSTRIES:
        errors["industry"] = "請選擇有效的業種。"
    if errors:
        return templates.TemplateResponse(request, "brand_edit.html",
                                           _brand_edit_form_ctx(request, brand, values, errors),
                                           status_code=400)
    was_archived = brand["status"] == "archived"
    repo.update_brand(web.conn, brand_id, name=name_c, client_name=clean(client_name), status=status,
                       actor=actor)
    # 後兩欄（市場地區／廣告目標）留白就用人設的預設值填；人設本身不入庫，只是填表捷徑。
    # 市場地區沒有人設可以推——這一版本來就只有「台灣」一個實值，留白＝未設定，不補值。
    repo.set_brand_switches(
        web.conn, brand_id, market_region=region_c or None,
        conversion_goal=goal_c or _persona_conversion_goal_default(persona), actor=actor,
    )
    # 業種跟方法論開關是不同功能領域（ADR 0014），沒有人設可以推、留白就是未設定。
    repo.set_brand_industry(web.conn, brand_id, industry=industry_c or None, actor=actor)
    if status == "archived" and not was_archived:
        msg = f"已封存品牌「{name_c}」。"
    elif status == "active" and was_archived:
        msg = f"已恢復品牌「{name_c}」為使用中。"
    else:
        msg = f"已更新品牌「{name_c}」的基本資料。"
    return redirect_with_message(f"/brands/{brand_id}", msg)


def _delete_counts(brand_id: str) -> list:
    """刪除確認頁要列的「會一起消失的資料」，只留有東西的項目（改由清理登記處
    彙整所有登記模組的清點結果，不再由本檔手寫死要問誰）。"""
    return [(label, n) for label, n in cleanup.count_all(web.conn, brand_id) if n > 0]


@router.get("/brands/{brand_id}/delete")
async def brand_delete_get(request: Request, brand_id: str):
    brand = require_brand(brand_id)
    if brand["status"] != "archived":
        return redirect_with_message(f"/brands/{brand_id}/edit",
                                      "要先把品牌封存，才能永久刪除。", kind="warn")
    return templates.TemplateResponse(request, "brand_delete.html", ctx(
        request, brand=brand, counts=_delete_counts(brand_id), error=None, nav_current='hub',
    ))


@router.post("/brands/{brand_id}/delete")
async def brand_delete_post(request: Request, brand_id: str, confirm_name: str = Form("")):
    actor = require_actor(request)
    brand = require_brand(brand_id)
    if brand["status"] != "archived":
        return redirect_with_message(f"/brands/{brand_id}/edit",
                                      "要先把品牌封存，才能永久刪除。", kind="warn")
    if clean(confirm_name) != brand["name"]:
        return templates.TemplateResponse(request, "brand_delete.html", ctx(
            request, brand=brand, counts=_delete_counts(brand_id), nav_current='hub',
            error="輸入的名稱跟品牌名稱不一樣，請照著上面顯示的名稱再打一次。",
        ), status_code=400)
    corebackup.snapshot(f"before-delete-{brand_id}")
    repo.delete_brand(web.conn, brand_id, actor=actor)
    warn = creative_assets.delete_folder(web.conn, brand_id)  # 素材圖檔資料夾一起刪（決策 0008）
    return redirect_with_message(
        "/", f"已永久刪除品牌「{brand['name']}」。刪除前的備份已存進 backups 資料夾。{warn}")


# ---------------------------------------------------------------------------
# 品牌智庫（issue #8 決策 0021；issue #49 收斂「限制規則」＋「宣稱」為一張「規則與宣稱」）：
# 品牌功能選單頁的地基資料收在這裡，入口卡各自對到一個獨立子頁（「規則與宣稱」卡對到
# /hub/rules，並在詳情內另附 /hub/claims 連結），內容與操作沿用原本各自子頁，只是換
# 首頁卡片容器；子頁網址與行為不變。
# ---------------------------------------------------------------------------

def _hub_crumb(brand: dict, *tail) -> list:
    """品牌智庫麵包屑：品牌總覽 / 品牌 / 品牌智庫 / ...tail（(label, url) 對，最後一個 url 通常 None）。"""
    return [("品牌總覽", "/"), (brand["name"], f"/brands/{brand['id']}"),
            ("品牌智庫", f"/brands/{brand['id']}/hub"), *tail]


def _product_hub_crumb(brand: dict, product: dict, *tail) -> list:
    """產品頁面麵包屑：品牌總覽 / 品牌 / 品牌智庫 / 產品 / ...tail（issue #9 決策 0021）。"""
    return [("品牌總覽", "/"), (brand["name"], f"/brands/{brand['id']}"),
            ("品牌智庫", f"/brands/{brand['id']}/hub"),
            (product["name"], f"/brands/{brand['id']}/products/{product['id']}"), *tail]


@router.get("/brands/{brand_id}/hub")
async def brand_hub(request: Request, brand_id: str):
    brand = require_brand(brand_id)
    facts_confirmed = len(repo.list_brand_facts(web.conn, brand_id, status="confirmed"))
    facts_pending = len(repo.list_brand_facts(web.conn, brand_id, status="pending"))
    rules = repo.list_rules_for_brand(web.conn, brand_id)
    claims = repo.list_claims_for_brand(web.conn, brand_id)
    products = list_products(brand_id)
    assets = repo.list_official_assets(web.conn, brand_id)
    channels = repo.list_channels(web.conn, brand_id)
    voices = repo.list_customer_voices(web.conn, brand_id, status="active")
    # 卡片描述句已拿掉（修憲落地 V5，說明句改成資料）：標題＋筆數已經講得清楚，
    # 不需要「這裡放…」這類重述標題的句子（console-ui skill text-to-data）。
    cards = [
        {"key": "facts", "title": "品牌事實",
         "count": facts_confirmed + facts_pending, "pending": facts_pending},
        {"key": "rules", "title": "規則與宣稱",
         "sub_links": [("限制規則", len(rules), "rules"), ("宣稱", len(claims), "claims")],
         "pending": 0},
        {"key": "products", "title": "產品",
         "count": len(products), "pending": pending_product_layer_count(brand_id)},
        {"key": "assets", "title": "素材與渠道",
         "sub_links": [("官方素材", len(assets), "assets"), ("自有渠道", len(channels), "channels")],
         "pending": 0},
        {"key": "customer-voice", "title": "顧客原話",
         "count": len(voices), "pending": 0},
    ]
    return templates.TemplateResponse(request, "hub_home.html", ctx(
        request, brand=brand, cards=cards, nav_current='hub',
    ))


@router.get("/brands/{brand_id}/hub/facts")
async def hub_facts(request: Request, brand_id: str):
    brand = require_brand(brand_id)
    confirmed_facts = [_augment_fact(brand_id, f)
                        for f in repo.list_brand_facts(web.conn, brand_id, status="confirmed")]
    pending_facts = [_augment_fact(brand_id, f)
                      for f in repo.list_brand_facts(web.conn, brand_id, status="pending")]
    return templates.TemplateResponse(request, "hub_facts.html", ctx(
        request, brand=brand, confirmed_facts=confirmed_facts, pending_facts=pending_facts,
        breadcrumb_items=_hub_crumb(brand, ("品牌事實", None)), nav_current='hub',
        **banner_ctx(request),
    ))


@router.get("/brands/{brand_id}/hub/rules")
async def hub_rules(request: Request, brand_id: str):
    brand = require_brand(brand_id)
    rules = repo.list_rules_for_brand(web.conn, brand_id)
    return templates.TemplateResponse(request, "hub_rules.html", ctx(
        request, brand=brand, rules=rules,
        breadcrumb_items=_hub_crumb(brand, ("限制規則", None)), nav_current='hub',
        **banner_ctx(request),
    ))


@router.get("/brands/{brand_id}/hub/claims")
async def hub_claims(request: Request, brand_id: str):
    brand = require_brand(brand_id)
    claims = [_augment_claim(brand_id, c) for c in repo.list_claims_for_brand(web.conn, brand_id)]
    claims_by_type = {
        "approved": [c for c in claims if c["claim_type"] == "approved"],
        "high_risk": [c for c in claims if c["claim_type"] == "high_risk"],
        "forbidden": [c for c in claims if c["claim_type"] == "forbidden"],
    }
    return templates.TemplateResponse(request, "hub_claims.html", ctx(
        request, brand=brand, claims_by_type=claims_by_type, claim_total=len(claims),
        breadcrumb_items=_hub_crumb(brand, ("宣稱", None)), nav_current='hub',
        **banner_ctx(request),
    ))


@router.get("/brands/{brand_id}/hub/products")
async def hub_products(request: Request, brand_id: str):
    brand = require_brand(brand_id)
    products = list_products(brand_id)
    product_rows = []
    for p in products:
        pc = repo.list_product_facts(web.conn, brand_id, p["id"], status="confirmed")
        pp = repo.list_product_facts(web.conn, brand_id, p["id"], status="pending")
        product_rows.append({
            "product": p,
            "fact_count": len(pc) + len(pp),
            "pending_count": len(pp),
            "economics": repo.get_product_economics(web.conn, brand_id, p["id"]),
        })
    return templates.TemplateResponse(request, "hub_products.html", ctx(
        request, brand=brand, product_rows=product_rows,
        breadcrumb_items=_hub_crumb(brand, ("產品", None)), nav_current='hub',
        **banner_ctx(request),
    ))


@router.get("/brands/{brand_id}/hub/assets")
async def hub_assets(request: Request, brand_id: str):
    brand = require_brand(brand_id)
    assets = [_augment_asset(brand_id, a) for a in repo.list_official_assets(web.conn, brand_id)]
    return templates.TemplateResponse(request, "hub_assets.html", ctx(
        request, brand=brand, assets=assets,
        breadcrumb_items=_hub_crumb(brand, ("官方素材", None)), nav_current='hub',
        **banner_ctx(request),
    ))


@router.get("/brands/{brand_id}/hub/channels")
async def hub_channels(request: Request, brand_id: str):
    brand = require_brand(brand_id)
    channels = repo.list_channels(web.conn, brand_id)
    return templates.TemplateResponse(request, "hub_channels.html", ctx(
        request, brand=brand, channels=channels,
        breadcrumb_items=_hub_crumb(brand, ("自有渠道", None)), nav_current='hub',
        **banner_ctx(request),
    ))


# ---------------------------------------------------------------------------
# 顧客原話語料庫（GitHub issue #14，決策 0023 第 18a 條／0024 第 2 條）
# ---------------------------------------------------------------------------

@router.get("/brands/{brand_id}/hub/customer-voice")
async def hub_customer_voice(request: Request, brand_id: str):
    brand = require_brand(brand_id)
    active_voices = repo.list_customer_voices(web.conn, brand_id, status="active")
    archived_voices = repo.list_customer_voices(web.conn, brand_id, status="archived")
    return templates.TemplateResponse(request, "hub_customer_voice.html", ctx(
        request, brand=brand, active_voices=active_voices, archived_voices=archived_voices,
        breadcrumb_items=_hub_crumb(brand, ("顧客原話", None)), nav_current='hub',
        **banner_ctx(request),
    ))


@router.get("/brands/{brand_id}/customer-voice/guide")
async def customer_voice_guide(request: Request, brand_id: str):
    brand = require_brand(brand_id)
    return templates.TemplateResponse(request, "customer_voice_guide.html", ctx(
        request, brand=brand, nav_current='hub',
        breadcrumb_items=_hub_crumb(brand, ("顧客原話", f"/brands/{brand_id}/hub/customer-voice"),
                                     ("去哪找顧客原話", None)),
    ))


@router.get("/brands/{brand_id}/customer-voice/new")
async def customer_voice_new_get(request: Request, brand_id: str):
    brand = require_brand(brand_id)
    values = {"source_channel": "", "source_detail": "", "raw_text": ""}
    return templates.TemplateResponse(request, "customer_voice_new.html", ctx(
        request, brand=brand, values=values, errors={}, nav_current='hub',
        breadcrumb_items=_hub_crumb(brand, ("顧客原話", f"/brands/{brand_id}/hub/customer-voice"),
                                     ("貼入顧客原話", None)),
    ))


@router.post("/brands/{brand_id}/customer-voice/new")
async def customer_voice_new_post(request: Request, brand_id: str,
                                   source_channel: str = Form(""), source_detail: str = Form(""),
                                   raw_text: str = Form("")):
    actor = require_actor(request)
    brand = require_brand(brand_id)
    values = {"source_channel": source_channel, "source_detail": source_detail, "raw_text": raw_text}
    errors = {}
    if not clean(source_channel):
        errors["source_channel"] = "請選擇這段原話是從哪裡來的。"
    raw_text_c = clean(raw_text)
    if not raw_text_c:
        errors["raw_text"] = "請貼上顧客的原文內容。"
    if errors:
        return templates.TemplateResponse(request, "customer_voice_new.html", ctx(
            request, brand=brand, values=values, errors=errors, nav_current='hub',
            breadcrumb_items=_hub_crumb(brand, ("顧客原話", f"/brands/{brand_id}/hub/customer-voice"),
                                         ("貼入顧客原話", None)),
        ), status_code=400)

    ok, result = cv_mod.extract(
        web.conn, brand_id, actor=actor, raw_text=raw_text_c,
        source_channel=source_channel, source_detail=clean(source_detail) or None,
    )
    if not ok:
        errors["raw_text"] = result
        return templates.TemplateResponse(request, "customer_voice_new.html", ctx(
            request, brand=brand, values=values, errors=errors, nav_current='hub',
            breadcrumb_items=_hub_crumb(brand, ("顧客原話", f"/brands/{brand_id}/hub/customer-voice"),
                                         ("貼入顧客原話", None)),
        ), status_code=400)

    n = len(result["extraction"])
    msg = f"已存入這段顧客原話，AI 抽出了 {n} 條重點。" if n else "已存入這段顧客原話，AI 沒有在裡面找到值得引用的重點。"
    return redirect_with_message(f"/brands/{brand_id}/hub/customer-voice", msg,
                                  again=f"/brands/{brand_id}/customer-voice/new")


@router.post("/brands/{brand_id}/customer-voice/{cv_id}/archive")
async def customer_voice_archive_post(request: Request, brand_id: str, cv_id: str):
    actor = require_actor(request)
    require_brand(brand_id)
    voice = repo.get_customer_voice(web.conn, brand_id, cv_id)
    if voice is None:
        raise NotFoundKind("顧客原話")
    new_status = "active" if voice["status"] == "archived" else "archived"
    repo.set_customer_voice_status(web.conn, brand_id, cv_id, status=new_status, actor=actor)
    msg = "已恢復這筆顧客原話。" if new_status == "active" else "已封存這筆顧客原話。"
    return redirect_with_message(f"/brands/{brand_id}/hub/customer-voice", msg)


@router.post("/brands/{brand_id}/customer-voice/{cv_id}/delete")
async def customer_voice_delete_post(request: Request, brand_id: str, cv_id: str):
    actor = require_actor(request)
    require_brand(brand_id)
    voice = repo.get_customer_voice(web.conn, brand_id, cv_id)
    if voice is None:
        raise NotFoundKind("顧客原話")
    repo.delete_customer_voice(web.conn, brand_id, cv_id, actor=actor)
    return redirect_with_message(f"/brands/{brand_id}/hub/customer-voice", "已刪除這筆顧客原話。")


# ---------------------------------------------------------------------------
# 顧問分析報告（決策 0017、GitHub issue #4）
# ---------------------------------------------------------------------------

REPORT_SECTION_LABELS = {
    "positioning": "品牌定位",
    "market": "市場與競爭觀察",
    "audience": "受眾洞察",
    "claims": "可用宣稱與紅線",
    "rhythm": "建議節奏方向",
}

# ponytail: 手殘重整進度頁不重跑一次；真的要再生成一份，兩分鐘後再按即可
_REPORT_RECENT_SECONDS = 120


def _report_sections(report: dict) -> list:
    return [
        {"label": REPORT_SECTION_LABELS[key], **report["sections"][key]}
        for key in brand_report_mod.SECTION_KEYS
    ]


def _report_recent(brand_id: str) -> bool:
    latest = repo.get_latest_brand_report(web.conn, brand_id)
    if latest is None:
        return False
    generated_at = datetime.fromisoformat(latest["generated_at"])
    if generated_at.tzinfo is None:
        generated_at = generated_at.replace(tzinfo=timezone.utc)
    age = (datetime.now(timezone.utc) - generated_at).total_seconds()
    return age < _REPORT_RECENT_SECONDS


@router.get("/brands/{brand_id}/report")
async def brand_report_get(request: Request, brand_id: str):
    brand = require_brand(brand_id)
    report = repo.get_latest_brand_report(web.conn, brand_id)
    if report is None:
        return templates.TemplateResponse(request, "report.html", ctx(
            request, brand=brand, report=None, nav_current='hub', **banner_ctx(request),
        ))
    cost_row = None
    if report["llm_task_id"]:
        cost_row = web.conn.execute(
            "SELECT cost FROM llm_task WHERE id = ?", (report["llm_task_id"],)
        ).fetchone()
    return templates.TemplateResponse(request, "report.html", ctx(
        request, brand=brand, report=report, sections=_report_sections(report),
        staleness=report_staleness(report),
        thin_data=report["source_fact_count"] < brand_report_mod.THIN_DATA_ITEMS,
        cost=cost_row["cost"] if cost_row else None, nav_current='hub',
        **banner_ctx(request),
    ))


@router.get("/brands/{brand_id}/report/progress")
def brand_report_progress(request: Request, brand_id: str, run: Optional[str] = None):
    """比照建檔精靈的進度頁模式（intake/routes.py intake_progress）：一次生成五章要
    30–90 秒，裸 POST 會讓瀏覽器空白等待，這裡沿用同一套 meta-refresh 機制。"""
    brand = require_brand(brand_id)
    actor = require_actor(request)
    result_url = f"/brands/{brand_id}/report"

    if _report_recent(brand_id):
        return RedirectResponse(result_url, status_code=303)

    if run != "1":
        return templates.TemplateResponse(request, "report_progress.html", ctx(
            request, brand=brand, run_url=f"{request.url.path}?run=1",
            refresh=intake_state.REFRESH_SECONDS, nav_current='hub',
        ))

    ok, err = brand_report_mod.generate(web.conn, brand_id, actor)
    if not ok:
        return redirect_with_message(result_url, err, kind="warn")
    return redirect_with_message(result_url, "報告已生成。")


@router.get("/brands/{brand_id}/report/export")
async def brand_report_export(request: Request, brand_id: str):
    brand = require_brand(brand_id)
    report = repo.get_latest_brand_report(web.conn, brand_id)
    if report is None:
        return RedirectResponse(f"/brands/{brand_id}/report", status_code=303)
    return templates.TemplateResponse(request, "report_export.html", ctx(
        request, brand=brand, report=report, sections=_report_sections(report),
        staleness=report_staleness(report),
        thin_data=report["source_fact_count"] < brand_report_mod.THIN_DATA_ITEMS,
        today=datetime.now(timezone.utc).date().isoformat(),
    ))


# ---------------------------------------------------------------------------
# 品牌事實
# ---------------------------------------------------------------------------

@router.get("/brands/{brand_id}/facts/new")
async def brand_fact_new_get(request: Request, brand_id: str):
    brand = require_brand(brand_id)
    values = {"fact_type": "", "label": "", "value": "", "status": "pending", "source_reference": ""}
    return templates.TemplateResponse(request, "fact_new.html", ctx(
        request, brand=brand, values=values, errors={}, nav_current='hub',
        scope="brand", fact_types=md.BRAND_FACT_TYPES,
        form_action=f"/brands/{brand_id}/facts/new",
        back_url=f"/brands/{brand_id}/hub/facts", back_label="品牌事實",
        breadcrumb_items=_hub_crumb(brand, ("品牌事實", f"/brands/{brand_id}/hub/facts"),
                                     ("新增品牌事實", None)),
    ))


@router.post("/brands/{brand_id}/facts/new")
async def brand_fact_new_post(request: Request, brand_id: str, fact_type: str = Form(""),
                               label: str = Form(""), value: str = Form(""),
                               status: str = Form("pending"), source_reference: str = Form("")):
    actor = require_actor(request)
    brand = require_brand(brand_id)
    values = {"fact_type": fact_type, "label": label, "value": value,
              "status": status, "source_reference": source_reference}
    errors = {}
    if not clean(fact_type):
        errors["fact_type"] = "請選擇這是哪一類事實。"
    if not clean(label):
        errors["label"] = "請填寫這條事實的名稱。"
    if not clean(value):
        errors["value"] = "請填寫事實內容。"
    if status not in ("confirmed", "pending"):
        errors["status"] = "請選擇是否已經確認過。"
    if errors:
        return templates.TemplateResponse(request, "fact_new.html", ctx(
            request, brand=brand, values=values, errors=errors, nav_current='hub',
            scope="brand", fact_types=md.BRAND_FACT_TYPES,
            form_action=f"/brands/{brand_id}/facts/new",
            back_url=f"/brands/{brand_id}/hub/facts", back_label="品牌事實",
            breadcrumb_items=_hub_crumb(brand, ("品牌事實", f"/brands/{brand_id}/hub/facts"),
                                         ("新增品牌事實", None)),
        ), status_code=400)
    src_id = _create_source_ref(brand_id, actor, source_reference)
    # 這個表單沒有另外的「確認人」欄位；直接以「已確認」建立時，確認人視同這次操作的人。
    confirmed_by = actor if status == "confirmed" else None
    repo.create_brand_fact(
        web.conn, brand_id, actor=actor, fact_type=fact_type, label=clean(label), value=clean(value),
        status=status, source_reference_id=src_id, confirmed_by=confirmed_by,
    )
    status_label = "已確認" if status == "confirmed" else "待確認"
    return redirect_with_message(
        f"/brands/{brand_id}/hub/facts", f"已新增品牌事實「{clean(label)}」，狀態為{status_label}。",
        again=f"/brands/{brand_id}/facts/new",
    )


@router.get("/brands/{brand_id}/facts/{fact_id}/confirm")
async def brand_fact_confirm_get(request: Request, brand_id: str, fact_id: str):
    brand = require_brand(brand_id)
    fact = repo.get_brand_fact(web.conn, brand_id, fact_id)
    if not fact:
        raise NotFoundKind("品牌事實")
    return templates.TemplateResponse(request, "fact_confirm.html", ctx(
        request, brand=brand, fact=fact, nav_current='hub',
        type_label=md.brand_fact_type_label(fact["fact_type"]),
        values={"confirmed_by": ""}, errors={},
        form_action=f"/brands/{brand_id}/facts/{fact_id}/confirm",
        back_url=f"/brands/{brand_id}/hub/facts", back_label="品牌事實",
        edit_url=f"/brands/{brand_id}/facts/new",
        breadcrumb_items=_hub_crumb(brand, ("品牌事實", f"/brands/{brand_id}/hub/facts"),
                                     ("確認這條品牌事實", None)),
    ))


@router.post("/brands/{brand_id}/facts/{fact_id}/confirm")
async def brand_fact_confirm_post(request: Request, brand_id: str, fact_id: str,
                                   confirmed_by: str = Form("")):
    actor = require_actor(request)
    brand = require_brand(brand_id)
    fact = repo.get_brand_fact(web.conn, brand_id, fact_id)
    if not fact:
        raise NotFoundKind("品牌事實")
    confirmed_by_c = clean(confirmed_by)
    if not confirmed_by_c:
        return templates.TemplateResponse(request, "fact_confirm.html", ctx(
            request, brand=brand, fact=fact, nav_current='hub',
            type_label=md.brand_fact_type_label(fact["fact_type"]),
            values={"confirmed_by": confirmed_by}, errors={"confirmed_by": "請填寫確認人是誰。"},
            form_action=f"/brands/{brand_id}/facts/{fact_id}/confirm",
            back_url=f"/brands/{brand_id}/hub/facts", back_label="品牌事實",
            edit_url=f"/brands/{brand_id}/facts/new",
            breadcrumb_items=_hub_crumb(brand, ("品牌事實", f"/brands/{brand_id}/hub/facts"),
                                         ("確認這條品牌事實", None)),
        ), status_code=400)
    repo.confirm_brand_fact(web.conn, brand_id, fact_id, confirmed_by=confirmed_by_c, actor=actor)
    return redirect_with_message(
        f"/brands/{brand_id}/hub/facts", f"已確認「{fact['label']}」，確認人：{confirmed_by_c}。",
    )


# 修改／刪除（決策 0013 用戶優先：人工編輯直接生效、不退回待確認；刪除記 audit 可追溯）

def _fact_edit_ctx(request, brand, values, errors, *, form_action, crumb_label,
                    fact_types, scope, product=None):
    if scope == "brand":
        back_url = f"/brands/{brand['id']}/hub/facts"
        back_label = "品牌事實"
        breadcrumb_items = _hub_crumb(brand, ("品牌事實", back_url), (crumb_label, None))
    else:
        back_url = f"/brands/{brand['id']}/products/{product['id']}/facts"
        back_label = "產品事實"
        breadcrumb_items = _product_hub_crumb(brand, product, ("產品事實", back_url), (crumb_label, None))
    return ctx(request, brand=brand, values=values, errors=errors,
               scope=scope, fact_types=fact_types, editing=True, product=product,
               form_action=form_action, nav_current='hub',
               back_url=back_url, back_label=back_label,
               breadcrumb_items=breadcrumb_items)


@router.get("/brands/{brand_id}/facts/{fact_id}/edit")
async def brand_fact_edit_get(request: Request, brand_id: str, fact_id: str):
    brand = require_brand(brand_id)
    fact = repo.get_brand_fact(web.conn, brand_id, fact_id)
    if not fact:
        raise NotFoundKind("品牌事實")
    values = {"fact_type": fact["fact_type"], "label": fact["label"], "value": fact["value"],
              "status": fact["status"], "source_reference": ""}
    return templates.TemplateResponse(request, "fact_new.html", _fact_edit_ctx(
        request, brand, values, {}, form_action=f"/brands/{brand_id}/facts/{fact_id}/edit",
        crumb_label="修改品牌事實", fact_types=md.BRAND_FACT_TYPES, scope="brand"))


@router.post("/brands/{brand_id}/facts/{fact_id}/edit")
async def brand_fact_edit_post(request: Request, brand_id: str, fact_id: str,
                                fact_type: str = Form(""), label: str = Form(""),
                                value: str = Form(""), source_reference: str = Form("")):
    actor = require_actor(request)
    brand = require_brand(brand_id)
    fact = repo.get_brand_fact(web.conn, brand_id, fact_id)
    if not fact:
        raise NotFoundKind("品牌事實")
    values = {"fact_type": fact_type, "label": label, "value": value,
              "status": fact["status"], "source_reference": source_reference}
    errors = {}
    if not clean(fact_type):
        errors["fact_type"] = "請選擇這是哪一類事實。"
    if not clean(label):
        errors["label"] = "請填寫這條事實的名稱。"
    if not clean(value):
        errors["value"] = "請填寫事實內容。"
    if errors:
        return templates.TemplateResponse(request, "fact_new.html", _fact_edit_ctx(
            request, brand, values, errors,
            form_action=f"/brands/{brand_id}/facts/{fact_id}/edit",
            crumb_label="修改品牌事實", fact_types=md.BRAND_FACT_TYPES, scope="brand"),
            status_code=400)
    src_id = (_create_source_ref(brand_id, actor, source_reference)
              or fact["source_reference_id"])  # 留空＝維持原來源
    repo.update_brand_fact(web.conn, brand_id, fact_id, actor=actor, fact_type=fact_type,
                            label=clean(label), value=clean(value), source_reference_id=src_id)
    return redirect_with_message(f"/brands/{brand_id}/hub/facts", f"已更新「{clean(label)}」。")


@router.post("/brands/{brand_id}/facts/{fact_id}/delete")
async def brand_fact_delete_post(request: Request, brand_id: str, fact_id: str):
    actor = require_actor(request)
    require_brand(brand_id)
    fact = repo.get_brand_fact(web.conn, brand_id, fact_id)
    if not fact:
        raise NotFoundKind("品牌事實")
    repo.delete_brand_fact(web.conn, brand_id, fact_id, actor=actor)
    return redirect_with_message(f"/brands/{brand_id}/hub/facts", f"已刪除「{fact['label']}」。")


@router.get("/brands/{brand_id}/products/{product_id}/facts/{fact_id}/edit")
async def product_fact_edit_get(request: Request, brand_id: str, product_id: str, fact_id: str):
    brand = require_brand(brand_id)
    product = require_product(brand, product_id)
    fact = repo.get_product_fact(web.conn, brand_id, product_id, fact_id)
    if not fact:
        raise NotFoundKind("產品事實")
    values = {"fact_type": fact["fact_type"], "label": fact["label"], "value": fact["value"],
              "status": fact["status"], "source_reference": ""}
    return templates.TemplateResponse(request, "fact_new.html", _fact_edit_ctx(
        request, brand, values, {},
        form_action=f"/brands/{brand_id}/products/{product_id}/facts/{fact_id}/edit",
        crumb_label="修改產品事實", fact_types=md.PRODUCT_FACT_TYPES, scope="product", product=product))


@router.post("/brands/{brand_id}/products/{product_id}/facts/{fact_id}/edit")
async def product_fact_edit_post(request: Request, brand_id: str, product_id: str, fact_id: str,
                                  fact_type: str = Form(""), label: str = Form(""),
                                  value: str = Form(""), source_reference: str = Form("")):
    actor = require_actor(request)
    brand = require_brand(brand_id)
    product = require_product(brand, product_id)
    fact = repo.get_product_fact(web.conn, brand_id, product_id, fact_id)
    if not fact:
        raise NotFoundKind("產品事實")
    values = {"fact_type": fact_type, "label": label, "value": value,
              "status": fact["status"], "source_reference": source_reference}
    errors = {}
    if not clean(fact_type):
        errors["fact_type"] = "請選擇這是哪一類事實。"
    if not clean(label):
        errors["label"] = "請填寫這條事實的名稱。"
    if not clean(value):
        errors["value"] = "請填寫事實內容。"
    if errors:
        return templates.TemplateResponse(request, "fact_new.html", _fact_edit_ctx(
            request, brand, values, errors,
            form_action=f"/brands/{brand_id}/products/{product_id}/facts/{fact_id}/edit",
            crumb_label="修改產品事實", fact_types=md.PRODUCT_FACT_TYPES, scope="product", product=product),
            status_code=400)
    src_id = (_create_source_ref(brand_id, actor, source_reference)
              or fact["source_reference_id"])
    repo.update_product_fact(web.conn, brand_id, product_id, fact_id, actor=actor,
                              fact_type=fact_type, label=clean(label), value=clean(value),
                              source_reference_id=src_id)
    return redirect_with_message(f"/brands/{brand_id}/products/{product_id}/facts",
                                  f"已更新「{clean(label)}」。")


@router.post("/brands/{brand_id}/products/{product_id}/facts/{fact_id}/delete")
async def product_fact_delete_post(request: Request, brand_id: str, product_id: str, fact_id: str):
    actor = require_actor(request)
    require_brand(brand_id)
    fact = repo.get_product_fact(web.conn, brand_id, product_id, fact_id)
    if not fact:
        raise NotFoundKind("產品事實")
    repo.delete_product_fact(web.conn, brand_id, fact_id, actor=actor)
    return redirect_with_message(f"/brands/{brand_id}/products/{product_id}/facts",
                                  f"已刪除「{fact['label']}」。")


@router.get("/brands/{brand_id}/rules/{rule_id}/edit")
async def rule_edit_get(request: Request, brand_id: str, rule_id: str):
    brand = require_brand(brand_id)
    rule = repo.get_rule(web.conn, brand_id, rule_id)
    if not rule:
        raise NotFoundKind("限制規則")
    products = list_products(brand_id)
    values = {"rule_type": rule["rule_type"], "content": rule["content"], "severity": rule["severity"],
              "product_id": rule["product_id"] or "", "source_reference": ""}
    return templates.TemplateResponse(request, "rule_edit.html", ctx(
        request, brand=brand, values=values, errors={}, products=products, nav_current='hub',
        form_action=f"/brands/{brand_id}/rules/{rule_id}/edit",
    ))


@router.post("/brands/{brand_id}/rules/{rule_id}/edit")
async def rule_edit_post(request: Request, brand_id: str, rule_id: str, rule_type: str = Form(""),
                          content: str = Form(""), severity: str = Form("soft"),
                          product_id: str = Form(""), source_reference: str = Form("")):
    actor = require_actor(request)
    brand = require_brand(brand_id)
    rule = repo.get_rule(web.conn, brand_id, rule_id)
    if not rule:
        raise NotFoundKind("限制規則")
    products = list_products(brand_id)
    values = {"rule_type": rule_type, "content": content, "severity": severity,
              "product_id": product_id, "source_reference": source_reference}
    errors = {}
    if not clean(rule_type):
        errors["rule_type"] = "請選擇規則類型。"
    if not clean(content):
        errors["content"] = "請填寫規則內容。"
    if severity not in ("hard", "soft"):
        errors["severity"] = "請選擇必須遵守或建議遵守。"
    if product_id and not repo.get_product(web.conn, brand_id, product_id):
        errors["product_id"] = "請選擇適用範圍。"
    if errors:
        return templates.TemplateResponse(request, "rule_edit.html", ctx(
            request, brand=brand, values=values, errors=errors, products=products, nav_current='hub',
            form_action=f"/brands/{brand_id}/rules/{rule_id}/edit",
        ), status_code=400)
    src_id = _create_source_ref(brand_id, actor, source_reference) or rule["source_reference_id"]
    repo.update_rule(web.conn, brand_id, rule_id, actor=actor, rule_type=rule_type, content=clean(content),
                      severity=severity, product_id=product_id or None, source_reference_id=src_id)
    return redirect_with_message(f"/brands/{brand_id}/hub/rules", "已更新這條限制規則。")


@router.post("/brands/{brand_id}/rules/{rule_id}/delete")
async def rule_delete_post(request: Request, brand_id: str, rule_id: str):
    actor = require_actor(request)
    require_brand(brand_id)
    repo.delete_rule(web.conn, brand_id, rule_id, actor=actor)
    return redirect_with_message(f"/brands/{brand_id}/hub/rules", "已刪除這條限制規則。")


@router.get("/brands/{brand_id}/claims/{claim_id}/edit")
async def claim_edit_get(request: Request, brand_id: str, claim_id: str):
    brand = require_brand(brand_id)
    claim = repo.get_claim(web.conn, brand_id, claim_id)
    if not claim:
        raise NotFoundKind("宣稱")
    products = list_products(brand_id)
    values = {"claim_text": claim["claim_text"], "claim_type": claim["claim_type"],
              "product_id": claim["product_id"] or "", "evidence_source_reference": ""}
    return templates.TemplateResponse(request, "claim_edit.html", ctx(
        request, brand=brand, values=values, errors={}, products=products, nav_current='hub',
        form_action=f"/brands/{brand_id}/claims/{claim_id}/edit",
    ))


@router.post("/brands/{brand_id}/claims/{claim_id}/edit")
async def claim_edit_post(request: Request, brand_id: str, claim_id: str, claim_text: str = Form(""),
                           claim_type: str = Form("high_risk"), product_id: str = Form(""),
                           evidence_source_reference: str = Form("")):
    actor = require_actor(request)
    brand = require_brand(brand_id)
    claim = repo.get_claim(web.conn, brand_id, claim_id)
    if not claim:
        raise NotFoundKind("宣稱")
    products = list_products(brand_id)
    values = {"claim_text": claim_text, "claim_type": claim_type,
              "product_id": product_id, "evidence_source_reference": evidence_source_reference}
    errors = {}
    if not clean(claim_text):
        errors["claim_text"] = "請填寫宣稱內容。"
    if claim_type not in ("approved", "high_risk", "forbidden"):
        errors["claim_type"] = "請選擇這句宣稱屬於哪一類。"
    if product_id and not repo.get_product(web.conn, brand_id, product_id):
        errors["product_id"] = "請選擇適用範圍。"
    if errors:
        return templates.TemplateResponse(request, "claim_edit.html", ctx(
            request, brand=brand, values=values, errors=errors, products=products, nav_current='hub',
            form_action=f"/brands/{brand_id}/claims/{claim_id}/edit",
        ), status_code=400)
    src_id = (_create_source_ref(brand_id, actor, evidence_source_reference)
              or claim["evidence_source_reference_id"])
    repo.update_claim(web.conn, brand_id, claim_id, actor=actor, claim_text=clean(claim_text),
                       claim_type=claim_type, product_id=product_id or None,
                       evidence_source_reference_id=src_id)
    return redirect_with_message(f"/brands/{brand_id}/hub/claims", "已更新這句宣稱。")


@router.post("/brands/{brand_id}/claims/{claim_id}/delete")
async def claim_delete_post(request: Request, brand_id: str, claim_id: str):
    actor = require_actor(request)
    require_brand(brand_id)
    repo.delete_claim(web.conn, brand_id, claim_id, actor=actor)
    return redirect_with_message(f"/brands/{brand_id}/hub/claims", "已刪除這條宣稱。")


# ---------------------------------------------------------------------------
# 產品
# ---------------------------------------------------------------------------

@router.get("/brands/{brand_id}/products/new")
async def product_new_get(request: Request, brand_id: str):
    brand = require_brand(brand_id)
    return templates.TemplateResponse(request, "product_new.html", ctx(
        request, brand=brand, values={"name": "", "url": ""}, errors={},
        research_cost=product_ai.COST_PRODUCT_SCAN, nav_current='hub',
    ))


@router.post("/brands/{brand_id}/products/new")
async def product_new_post(request: Request, brand_id: str, name: str = Form("")):
    actor = require_actor(request)
    brand = require_brand(brand_id)
    name_c = clean(name)
    if not name_c:
        return templates.TemplateResponse(request, "product_new.html", ctx(
            request, brand=brand, values={"name": name, "url": ""}, errors={"name": "請填寫產品名稱。"},
            research_cost=product_ai.COST_PRODUCT_SCAN, nav_current='hub',
        ), status_code=400)
    product = repo.create_product(web.conn, brand_id, name=name_c, actor=actor)
    return redirect_with_message(f"/brands/{brand_id}/products/{product['id']}", f"已新增產品「{name_c}」。")


@router.post("/brands/{brand_id}/products/new/research")
async def product_new_research_post(request: Request, brand_id: str,
                                     name: str = Form(""), url: str = Form("")):
    """「AI 幫我調研」：讀產品頁網址＋已確認品牌事實，請 AI 整理產品事實，
    建立產品並把整理出的事實全部存成 pending（issue #6）。不填網址走原本純手動建立，
    這條路由完全不動那個行為。"""
    actor = require_actor(request)
    brand = require_brand(brand_id)
    name_c = clean(name)
    url_c = clean(url)
    values = {"name": name, "url": url}
    errors = {}
    if not name_c:
        errors["name"] = "請填寫產品名稱。"
    if not url_c:
        errors["url"] = "請填寫產品頁網址，才能請 AI 幫忙調研；不填網址請改用「新增這個產品」。"
    elif not (url_c.startswith("http://") or url_c.startswith("https://")):
        errors["url"] = "這個網址看起來不完整，記得從 https:// 開始，例如「https://example.com/products/xxx」。"
    if errors:
        return templates.TemplateResponse(request, "product_new.html", ctx(
            request, brand=brand, values=values, errors=errors,
            research_cost=product_ai.COST_PRODUCT_SCAN, nav_current='hub',
        ), status_code=400)

    budget_err = _scan_budget_error(brand_id)
    if budget_err:
        errors["url"] = budget_err
        return templates.TemplateResponse(request, "product_new.html", ctx(
            request, brand=brand, values=values, errors=errors,
            research_cost=product_ai.COST_PRODUCT_SCAN, nav_current='hub',
        ), status_code=400)

    brand_facts = repo.list_brand_facts(web.conn, brand_id, status="confirmed")
    ok, result = product_ai.run_product_scan(web.conn, brand_id, name_c, url_c, brand_facts)
    if not ok:
        errors["url"] = result
        return templates.TemplateResponse(request, "product_new.html", ctx(
            request, brand=brand, values=values, errors=errors,
            research_cost=product_ai.COST_PRODUCT_SCAN, nav_current='hub',
        ), status_code=400)

    product = repo.create_product(web.conn, brand_id, name=name_c, actor=actor)
    src_id = _create_source_ref(brand_id, actor, url_c)
    added, _skipped, price_created = _apply_product_scan_result(brand_id, product["id"], actor, src_id, result)
    msg = f"已建立產品「{name_c}」，AI 整理了 {added} 條待確認的產品事實"
    if price_created:
        msg += "，也抓到售價存成待確認的經濟數字"
    msg += "，記得去確認。"
    return redirect_with_message(f"/brands/{brand_id}/products/{product['id']}", msg)


# ---------------------------------------------------------------------------
# 產品智庫（issue #9 決策 0021）：產品功能選單頁的地基資料收在這裡，四張入口卡
# 各自對到一個獨立子頁，內容與操作沿用原本產品檔案頁四大區，只是換頁面容器。
# ---------------------------------------------------------------------------

@router.get("/brands/{brand_id}/products/{product_id}")
async def product_hub(request: Request, brand_id: str, product_id: str):
    brand = require_brand(brand_id)
    product = require_product(brand, product_id)
    facts_confirmed = len(repo.list_product_facts(web.conn, brand_id, product_id, status="confirmed"))
    facts_pending = len(repo.list_product_facts(web.conn, brand_id, product_id, status="pending"))
    economics = repo.get_product_economics(web.conn, brand_id, product_id)
    rules = repo.list_rules_for_product(web.conn, brand_id, product_id)
    claims = repo.list_claims_for_product(web.conn, brand_id, product_id)
    rescan_url = repo.get_latest_product_source_url(web.conn, brand_id, product_id) or ""
    # 卡片描述句已拿掉（修憲落地 V5，說明句改成資料）：標題＋筆數已經講得清楚。
    cards = [
        {"key": "facts", "title": "產品事實",
         "count": facts_confirmed + facts_pending, "pending": facts_pending},
        {"key": "economics-view", "title": "產品經濟數字",
         "count": 1 if economics else 0,
         "pending": 1 if economics and economics["status"] == "pending" else 0},
        {"key": "rules", "title": "適用規則",
         "count": len(rules), "pending": 0},
        {"key": "claims", "title": "適用宣稱",
         "count": len(claims), "pending": 0},
    ]
    return templates.TemplateResponse(request, "product_hub.html", ctx(
        request, brand=brand, product=product, cards=cards, economics=economics,
        rescan_url=rescan_url, research_cost=product_ai.COST_PRODUCT_SCAN, nav_current='hub',
        **banner_ctx(request),
    ))


@router.get("/brands/{brand_id}/products/{product_id}/facts")
async def product_hub_facts(request: Request, brand_id: str, product_id: str):
    brand = require_brand(brand_id)
    product = require_product(brand, product_id)
    confirmed_facts = [_augment_fact(brand_id, f)
                        for f in repo.list_product_facts(web.conn, brand_id, product_id, status="confirmed")]
    pending_facts = [_augment_fact(brand_id, f)
                      for f in repo.list_product_facts(web.conn, brand_id, product_id, status="pending")]
    return templates.TemplateResponse(request, "product_hub_facts.html", ctx(
        request, brand=brand, product=product,
        confirmed_facts=confirmed_facts, pending_facts=pending_facts,
        breadcrumb_items=_product_hub_crumb(brand, product, ("產品事實", None)), nav_current='hub',
        **banner_ctx(request),
    ))


@router.get("/brands/{brand_id}/products/{product_id}/economics-view")
async def product_hub_economics(request: Request, brand_id: str, product_id: str):
    brand = require_brand(brand_id)
    product = require_product(brand, product_id)
    economics = repo.get_product_economics(web.conn, brand_id, product_id)
    return templates.TemplateResponse(request, "product_hub_economics.html", ctx(
        request, brand=brand, product=product, economics=economics,
        breadcrumb_items=_product_hub_crumb(brand, product, ("產品經濟數字", None)), nav_current='hub',
        **banner_ctx(request),
    ))


@router.get("/brands/{brand_id}/products/{product_id}/rules")
async def product_hub_rules(request: Request, brand_id: str, product_id: str):
    brand = require_brand(brand_id)
    product = require_product(brand, product_id)
    rules = repo.list_rules_for_product(web.conn, brand_id, product_id)
    return templates.TemplateResponse(request, "product_hub_rules.html", ctx(
        request, brand=brand, product=product, rules=rules,
        breadcrumb_items=_product_hub_crumb(brand, product, ("適用規則", None)), nav_current='hub',
    ))


@router.get("/brands/{brand_id}/products/{product_id}/claims")
async def product_hub_claims(request: Request, brand_id: str, product_id: str):
    brand = require_brand(brand_id)
    product = require_product(brand, product_id)
    claims = [_augment_claim(brand_id, c) for c in repo.list_claims_for_product(web.conn, brand_id, product_id)]
    return templates.TemplateResponse(request, "product_hub_claims.html", ctx(
        request, brand=brand, product=product, claims=claims,
        breadcrumb_items=_product_hub_crumb(brand, product, ("適用宣稱", None)), nav_current='hub',
    ))


@router.post("/brands/{brand_id}/products/{product_id}/rescan")
async def product_rescan_post(request: Request, brand_id: str, product_id: str, url: str = Form("")):
    """「AI 再次調研」：對已建立的產品重跑一次快掃（issue：產品快掃可再次調研）。
    網址由畫面預填最近一次帶網址的來源引用，使用者可改。同 label 的結果自動略過，
    不會跟既有事實／經濟數字重複堆積。"""
    actor = require_actor(request)
    brand = require_brand(brand_id)
    product = require_product(brand, product_id)
    url_c = clean(url)
    if not url_c:
        return redirect_with_message(f"/brands/{brand_id}/products/{product_id}",
                                      "請填寫網址，才能請 AI 再次調研。", kind="danger")
    if not (url_c.startswith("http://") or url_c.startswith("https://")):
        return redirect_with_message(
            f"/brands/{brand_id}/products/{product_id}",
            "這個網址看起來不完整，記得從 https:// 開始，例如「https://example.com/products/xxx」。",
            kind="danger",
        )
    budget_err = _scan_budget_error(brand_id)
    if budget_err:
        return redirect_with_message(f"/brands/{brand_id}/products/{product_id}", budget_err,
                                      kind="danger")

    brand_facts = repo.list_brand_facts(web.conn, brand_id, status="confirmed")
    ok, result = product_ai.run_product_scan(web.conn, brand_id, product["name"], url_c, brand_facts)
    if not ok:
        return redirect_with_message(f"/brands/{brand_id}/products/{product_id}", result,
                                      kind="danger")

    src_id = _create_source_ref(brand_id, actor, url_c)
    added, skipped, price_created = _apply_product_scan_result(brand_id, product_id, actor, src_id, result)
    msg = f"AI 再次調研完成，新增了 {added} 條待確認的產品事實"
    if skipped:
        msg += f"（{skipped} 條跟既有內容重複，已略過）"
    if price_created:
        msg += "，也抓到售價存成待確認的經濟數字"
    msg += "。"
    return redirect_with_message(f"/brands/{brand_id}/products/{product_id}", msg)


# ---------------------------------------------------------------------------
# 產品調研交接包（GitHub issue #7）：產品快掃只讀一頁網頁，這裡讓使用者把交接包文字
# 帶去外部 AI（Claude／ChatGPT 網頁版）跑更深的調研，再把回覆貼回來解析入庫。
# ---------------------------------------------------------------------------

def _product_handoff_prompt(brand: dict, product: dict) -> str:
    brand_facts = repo.list_brand_facts(web.conn, brand["id"], status="confirmed")
    product_facts = repo.list_product_facts(web.conn, brand["id"], product["id"])
    return product_ai.build_product_handoff_prompt(brand["name"], product["name"], brand_facts, product_facts)


def _product_handoff_ctx(request: Request, brand: dict, product: dict, values: dict, errors: dict) -> dict:
    return ctx(
        request, brand=brand, product=product, prompt_text=_product_handoff_prompt(brand, product),
        values=values, errors=errors, fix_cost=product_ai.COST_PRODUCT_HANDOFF_FIX,
        breadcrumb_items=_product_hub_crumb(brand, product, ("調研交接包", None)), nav_current='hub',
    )


@router.get("/brands/{brand_id}/products/{product_id}/handoff")
async def product_handoff_get(request: Request, brand_id: str, product_id: str):
    brand = require_brand(brand_id)
    product = require_product(brand, product_id)
    return templates.TemplateResponse(request, "product_handoff.html", _product_handoff_ctx(
        request, brand, product, values={"raw_text": ""}, errors={},
    ))


@router.post("/brands/{brand_id}/products/{product_id}/handoff")
async def product_handoff_post(request: Request, brand_id: str, product_id: str,
                                raw_text: str = Form("")):
    """貼回解析：先試直接解析 JSON（不花錢），失敗才呼叫 AI 修復格式（受花費上限保護）。
    成功後重用票 A 的 _apply_product_scan_result 入庫，同 label 去重、price 依規則建 pending。"""
    actor = require_actor(request)
    brand = require_brand(brand_id)
    product = require_product(brand, product_id)
    values = {"raw_text": raw_text}

    if not clean(raw_text):
        return templates.TemplateResponse(request, "product_handoff.html", _product_handoff_ctx(
            request, brand, product, values=values, errors={"raw_text": "請先把外部 AI 的回覆貼進來。"},
        ), status_code=400)

    result = product_ai.parse_product_handoff_reply(raw_text)
    if result is None:
        budget_err = _scan_budget_error(
            brand_id, cost=product_ai.COST_PRODUCT_HANDOFF_FIX, action="請 AI 幫忙整理格式",
            fallback_hint="或先自己把貼上的內容改成正確格式，那樣不用花錢。")
        if budget_err:
            return templates.TemplateResponse(request, "product_handoff.html", _product_handoff_ctx(
                request, brand, product, values=values, errors={"raw_text": budget_err},
            ), status_code=400)
        ok, fixed = product_ai.run_product_handoff_fix(web.conn, brand_id, raw_text)
        if not ok:
            return templates.TemplateResponse(request, "product_handoff.html", _product_handoff_ctx(
                request, brand, product, values=values, errors={"raw_text": fixed},
            ), status_code=400)
        result = fixed

    src_label = f"外部深研交接包・{datetime.now(timezone.utc).date().isoformat()}"
    src_id = _create_source_ref(brand_id, actor, src_label)
    added, skipped, price_created = _apply_product_scan_result(brand_id, product_id, actor, src_id, result)
    msg = f"深研交接包貼回完成，新增了 {added} 條待確認的產品事實"
    if skipped:
        msg += f"（{skipped} 條跟既有內容重複，已略過）"
    if price_created:
        msg += "，也抓到售價存成待確認的經濟數字"
    msg += "。"
    return redirect_with_message(f"/brands/{brand_id}/products/{product_id}", msg)


@router.post("/brands/{brand_id}/products/{product_id}/archive")
async def product_archive_post(request: Request, brand_id: str, product_id: str):
    actor = require_actor(request)
    brand = require_brand(brand_id)
    product = require_product(brand, product_id)
    new_status = "archived" if product["status"] == "active" else "active"
    repo.update_product(web.conn, brand_id, product_id, name=product["name"], status=new_status, actor=actor)
    msg = (f"已封存產品「{product['name']}」。" if new_status == "archived"
           else f"已恢復產品「{product['name']}」為使用中。")
    return redirect_with_message(f"/brands/{brand_id}/products/{product_id}", msg)


def _product_delete_counts(brand_id: str, product_id: str) -> list:
    """刪除確認頁要列的「會一起消失的資料」，只留有東西的項目（改由清理登記處
    彙整所有登記模組的清點結果，不再只問品牌智庫自己——第 6 刀）。"""
    rows = cleanup.count_all_product(web.conn, brand_id, product_id)
    return [(label, n) for label, n in rows if n > 0]


@router.get("/brands/{brand_id}/products/{product_id}/delete")
async def product_delete_get(request: Request, brand_id: str, product_id: str):
    brand = require_brand(brand_id)
    product = require_product(brand, product_id)
    if product["status"] != "archived":
        return redirect_with_message(f"/brands/{brand_id}/products/{product_id}",
                                      "要先把產品封存，才能永久刪除。", kind="warn")
    return templates.TemplateResponse(request, "product_delete.html", ctx(
        request, brand=brand, product=product,
        counts=_product_delete_counts(brand_id, product_id), error=None, nav_current='hub',
    ))


@router.post("/brands/{brand_id}/products/{product_id}/delete")
async def product_delete_post(request: Request, brand_id: str, product_id: str,
                               confirm_name: str = Form("")):
    actor = require_actor(request)
    brand = require_brand(brand_id)
    product = require_product(brand, product_id)
    if product["status"] != "archived":
        return redirect_with_message(f"/brands/{brand_id}/products/{product_id}",
                                      "要先把產品封存，才能永久刪除。", kind="warn")
    if clean(confirm_name) != product["name"]:
        return templates.TemplateResponse(request, "product_delete.html", ctx(
            request, brand=brand, product=product,
            counts=_product_delete_counts(brand_id, product_id),
            error="輸入的名稱跟產品名稱不一樣，請照著上面顯示的名稱再打一次。",
            nav_current='hub',
        ), status_code=400)
    corebackup.snapshot(f"before-delete-{product_id}")
    repo.delete_product(web.conn, brand_id, product_id, actor=actor)
    return redirect_with_message(
        f"/brands/{brand_id}/hub/products",
        f"已永久刪除產品「{product['name']}」。刪除前的備份已存進 backups 資料夾。")


@router.get("/brands/{brand_id}/products/{product_id}/facts/new")
async def product_fact_new_get(request: Request, brand_id: str, product_id: str):
    brand = require_brand(brand_id)
    product = require_product(brand, product_id)
    values = {"fact_type": "", "label": "", "value": "", "status": "pending", "source_reference": ""}
    facts_url = f"/brands/{brand_id}/products/{product_id}/facts"
    return templates.TemplateResponse(request, "fact_new.html", ctx(
        request, brand=brand, values=values, errors={}, nav_current='hub',
        scope="product", fact_types=md.PRODUCT_FACT_TYPES, product=product,
        form_action=f"/brands/{brand_id}/products/{product_id}/facts/new",
        back_url=facts_url, back_label="產品事實",
        breadcrumb_items=_product_hub_crumb(brand, product, ("產品事實", facts_url), ("新增產品事實", None)),
    ))


@router.post("/brands/{brand_id}/products/{product_id}/facts/new")
async def product_fact_new_post(request: Request, brand_id: str, product_id: str,
                                 fact_type: str = Form(""), label: str = Form(""), value: str = Form(""),
                                 status: str = Form("pending"), source_reference: str = Form("")):
    actor = require_actor(request)
    brand = require_brand(brand_id)
    product = require_product(brand, product_id)
    values = {"fact_type": fact_type, "label": label, "value": value,
              "status": status, "source_reference": source_reference}
    errors = {}
    if not clean(fact_type):
        errors["fact_type"] = "請選擇這是哪一類產品事實。"
    if not clean(label):
        errors["label"] = "請填寫這條事實的名稱。"
    if not clean(value):
        errors["value"] = "請填寫事實內容。"
    if status not in ("confirmed", "pending"):
        errors["status"] = "請選擇是否已經確認過。"
    facts_url = f"/brands/{brand_id}/products/{product_id}/facts"
    if errors:
        return templates.TemplateResponse(request, "fact_new.html", ctx(
            request, brand=brand, values=values, errors=errors, nav_current='hub',
            scope="product", fact_types=md.PRODUCT_FACT_TYPES, product=product,
            form_action=f"/brands/{brand_id}/products/{product_id}/facts/new",
            back_url=facts_url, back_label="產品事實",
            breadcrumb_items=_product_hub_crumb(brand, product, ("產品事實", facts_url), ("新增產品事實", None)),
        ), status_code=400)
    src_id = _create_source_ref(brand_id, actor, source_reference)
    confirmed_by = actor if status == "confirmed" else None
    repo.create_product_fact(
        web.conn, brand_id, product_id, actor=actor, fact_type=fact_type, label=clean(label), value=clean(value),
        status=status, source_reference_id=src_id, confirmed_by=confirmed_by,
    )
    status_label = "已確認" if status == "confirmed" else "待確認"
    return redirect_with_message(
        facts_url, f"已新增產品事實「{clean(label)}」，狀態為{status_label}。",
        again=f"/brands/{brand_id}/products/{product_id}/facts/new",
    )


@router.get("/brands/{brand_id}/products/{product_id}/facts/{fact_id}/confirm")
async def product_fact_confirm_get(request: Request, brand_id: str, product_id: str, fact_id: str):
    brand = require_brand(brand_id)
    product = require_product(brand, product_id)
    fact = repo.get_product_fact(web.conn, brand_id, product_id, fact_id)
    if not fact:
        raise NotFoundKind("產品事實")
    facts_url = f"/brands/{brand_id}/products/{product_id}/facts"
    return templates.TemplateResponse(request, "fact_confirm.html", ctx(
        request, brand=brand, product=product, fact=fact, nav_current='hub',
        type_label=md.product_fact_type_label(fact["fact_type"]),
        values={"confirmed_by": ""}, errors={},
        form_action=f"/brands/{brand_id}/products/{product_id}/facts/{fact_id}/confirm",
        back_url=facts_url, back_label="產品事實",
        edit_url=f"/brands/{brand_id}/products/{product_id}/facts/new",
        breadcrumb_items=_product_hub_crumb(brand, product, ("產品事實", facts_url), ("確認這條產品事實", None)),
    ))


@router.post("/brands/{brand_id}/products/{product_id}/facts/{fact_id}/confirm")
async def product_fact_confirm_post(request: Request, brand_id: str, product_id: str, fact_id: str,
                                     confirmed_by: str = Form("")):
    actor = require_actor(request)
    brand = require_brand(brand_id)
    product = require_product(brand, product_id)
    fact = repo.get_product_fact(web.conn, brand_id, product_id, fact_id)
    if not fact:
        raise NotFoundKind("產品事實")
    confirmed_by_c = clean(confirmed_by)
    facts_url = f"/brands/{brand_id}/products/{product_id}/facts"
    if not confirmed_by_c:
        return templates.TemplateResponse(request, "fact_confirm.html", ctx(
            request, brand=brand, product=product, fact=fact, nav_current='hub',
            type_label=md.product_fact_type_label(fact["fact_type"]),
            values={"confirmed_by": confirmed_by}, errors={"confirmed_by": "請填寫確認人是誰。"},
            form_action=f"/brands/{brand_id}/products/{product_id}/facts/{fact_id}/confirm",
            back_url=facts_url, back_label="產品事實",
            edit_url=f"/brands/{brand_id}/products/{product_id}/facts/new",
            breadcrumb_items=_product_hub_crumb(brand, product, ("產品事實", facts_url), ("確認這條產品事實", None)),
        ), status_code=400)
    repo.confirm_product_fact(web.conn, brand_id, product_id, fact_id, confirmed_by=confirmed_by_c,
                               actor=actor)
    return redirect_with_message(
        facts_url, f"已確認「{fact['label']}」，確認人：{confirmed_by_c}。",
    )


# ---------------------------------------------------------------------------
# 限制規則
# ---------------------------------------------------------------------------

@router.get("/brands/{brand_id}/rules/new")
async def rule_new_get(request: Request, brand_id: str):
    brand = require_brand(brand_id)
    products = list_products(brand_id)
    values = {"rule_type": "", "content": "", "severity": "soft", "product_id": "", "source_reference": ""}
    return templates.TemplateResponse(request, "rule_new.html", ctx(
        request, brand=brand, values=values, errors={}, products=products, nav_current='hub',
    ))


@router.post("/brands/{brand_id}/rules/new")
async def rule_new_post(request: Request, brand_id: str, rule_type: str = Form(""),
                         content: str = Form(""), severity: str = Form("soft"),
                         product_id: str = Form(""), source_reference: str = Form("")):
    actor = require_actor(request)
    brand = require_brand(brand_id)
    products = list_products(brand_id)
    values = {"rule_type": rule_type, "content": content, "severity": severity,
              "product_id": product_id, "source_reference": source_reference}
    errors = {}
    if not clean(rule_type):
        errors["rule_type"] = "請選擇規則類型。"
    if not clean(content):
        errors["content"] = "請填寫規則內容。"
    if severity not in ("hard", "soft"):
        errors["severity"] = "請選擇必須遵守或建議遵守。"
    if product_id and not repo.get_product(web.conn, brand_id, product_id):
        errors["product_id"] = "請選擇適用範圍。"
    if errors:
        return templates.TemplateResponse(request, "rule_new.html", ctx(
            request, brand=brand, values=values, errors=errors, products=products, nav_current='hub',
        ), status_code=400)
    src_id = _create_source_ref(brand_id, actor, source_reference)
    repo.create_rule(web.conn, brand_id, actor=actor, rule_type=rule_type, content=clean(content),
                      severity=severity, product_id=product_id or None, source_reference_id=src_id)
    scope_txt = scope_label(brand_id, product_id or None)
    return redirect_with_message(
        f"/brands/{brand_id}/hub/rules",
        f"已新增限制規則「{md.rule_type_label(rule_type)}」，適用範圍：{scope_txt}。",
        again=f"/brands/{brand_id}/rules/new",
    )


# ---------------------------------------------------------------------------
# 宣稱
# ---------------------------------------------------------------------------

@router.get("/brands/{brand_id}/claims/new")
async def claim_new_get(request: Request, brand_id: str):
    brand = require_brand(brand_id)
    products = list_products(brand_id)
    values = {"claim_text": "", "claim_type": "high_risk", "product_id": "", "evidence_source_reference": ""}
    return templates.TemplateResponse(request, "claim_new.html", ctx(
        request, brand=brand, values=values, errors={}, products=products, nav_current='hub',
    ))


@router.post("/brands/{brand_id}/claims/new")
async def claim_new_post(request: Request, brand_id: str, claim_text: str = Form(""),
                          claim_type: str = Form("high_risk"), product_id: str = Form(""),
                          evidence_source_reference: str = Form("")):
    actor = require_actor(request)
    brand = require_brand(brand_id)
    products = list_products(brand_id)
    values = {"claim_text": claim_text, "claim_type": claim_type,
              "product_id": product_id, "evidence_source_reference": evidence_source_reference}
    errors = {}
    if not clean(claim_text):
        errors["claim_text"] = "請填寫宣稱內容。"
    if claim_type not in ("approved", "high_risk", "forbidden"):
        errors["claim_type"] = "請選擇這句宣稱屬於哪一類。"
    if product_id and not repo.get_product(web.conn, brand_id, product_id):
        errors["product_id"] = "請選擇適用範圍。"
    if errors:
        return templates.TemplateResponse(request, "claim_new.html", ctx(
            request, brand=brand, values=values, errors=errors, products=products, nav_current='hub',
        ), status_code=400)
    src_id = _create_source_ref(brand_id, actor, evidence_source_reference)
    repo.create_claim(web.conn, brand_id, actor=actor, claim_text=clean(claim_text), claim_type=claim_type,
                       product_id=product_id or None, evidence_source_reference_id=src_id)
    return redirect_with_message(
        f"/brands/{brand_id}/hub/claims", f"已新增宣稱「{clean(claim_text)}」。",
        again=f"/brands/{brand_id}/claims/new",
    )


# ---------------------------------------------------------------------------
# 自有渠道
# ---------------------------------------------------------------------------

@router.get("/brands/{brand_id}/channels/new")
async def channel_new_get(request: Request, brand_id: str):
    brand = require_brand(brand_id)
    values = {"channel_type": "", "name": "", "identifier": "", "status": "active"}
    return templates.TemplateResponse(request, "channel_new.html", ctx(
        request, brand=brand, values=values, errors={}, nav_current='hub',
    ))


@router.post("/brands/{brand_id}/channels/new")
async def channel_new_post(request: Request, brand_id: str, channel_type: str = Form(""),
                            name: str = Form(""), identifier: str = Form(""),
                            status: str = Form("active")):
    actor = require_actor(request)
    brand = require_brand(brand_id)
    values = {"channel_type": channel_type, "name": name, "identifier": identifier, "status": status}
    errors = {}
    if not clean(channel_type):
        errors["channel_type"] = "請選擇渠道類型。"
    if not clean(name):
        errors["name"] = "請填寫渠道名稱。"
    if not clean(identifier):
        errors["identifier"] = "請填寫網址或帳號。"
    if status not in ("active", "inactive"):
        errors["status"] = "請選擇狀態。"
    if errors:
        return templates.TemplateResponse(request, "channel_new.html", ctx(
            request, brand=brand, values=values, errors=errors, nav_current='hub',
        ), status_code=400)
    repo.create_channel(web.conn, brand_id, actor=actor, channel_type=channel_type,
                         name=clean(name), identifier=clean(identifier), status=status)
    return redirect_with_message(
        f"/brands/{brand_id}/hub/channels", f"已新增自有渠道「{clean(name)}」。",
        again=f"/brands/{brand_id}/channels/new",
    )


# ---------------------------------------------------------------------------
# 產品經濟數字
# ---------------------------------------------------------------------------

@router.get("/brands/{brand_id}/products/{product_id}/economics")
async def economics_get(request: Request, brand_id: str, product_id: str):
    brand = require_brand(brand_id)
    product = require_product(brand, product_id)
    existing = repo.get_product_economics(web.conn, brand_id, product_id)
    if existing:
        values = {
            "selling_price": _num_str(existing["selling_price"]),
            # 不確定／AI 只抓到售價時，成本欄位建議先填 0，之後隨時可以再改（鐵則 14 每格有路）。
            "fixed_cost": _num_str(existing["fixed_cost"]) or "0",
            "unit_variable_cost": _num_str(existing["unit_variable_cost"]) or "0",
            "shipping_cost": _num_str(existing["shipping_cost"]) or "0",
            "currency": existing["currency"],
            "cpa_roas_basis": existing["cpa_roas_basis"] or "",
            "effective_from": existing["effective_from"] or "",
            "confirmed_by": existing["confirmed_by"] or "",
        }
    else:
        values = {"selling_price": "", "fixed_cost": "0", "unit_variable_cost": "0", "shipping_cost": "0",
                   "currency": "TWD", "cpa_roas_basis": "", "effective_from": "",
                   "confirmed_by": ""}
    return templates.TemplateResponse(request, "economics_form.html", ctx(
        request, brand=brand, product=product, values=values, errors={}, is_update=existing is not None,
        nav_current='hub',
    ))


@router.post("/brands/{brand_id}/products/{product_id}/economics")
async def economics_post(request: Request, brand_id: str, product_id: str,
                          selling_price: str = Form(""), fixed_cost: str = Form(""),
                          unit_variable_cost: str = Form(""), shipping_cost: str = Form(""),
                          currency: str = Form("TWD"), cpa_roas_basis: str = Form(""),
                          effective_from: str = Form(""), confirmed_by: str = Form("")):
    actor = require_actor(request)
    brand = require_brand(brand_id)
    product = require_product(brand, product_id)
    values = {"selling_price": selling_price, "fixed_cost": fixed_cost,
              "unit_variable_cost": unit_variable_cost, "shipping_cost": shipping_cost,
              "currency": currency, "cpa_roas_basis": cpa_roas_basis,
              "effective_from": effective_from, "confirmed_by": confirmed_by}
    errors = {}
    price_val, price_ok = parse_number(selling_price)
    if clean(selling_price) == "":
        errors["selling_price"] = "請填寫售價。"
    elif not price_ok:
        errors["selling_price"] = "售價請填數字，例如 1280。"
    fixed_val, fixed_ok = parse_number(fixed_cost)
    if not fixed_ok:
        errors["fixed_cost"] = "固定成本請填數字，例如 0。"
    unit_val, unit_ok = parse_number(unit_variable_cost)
    if not unit_ok:
        errors["unit_variable_cost"] = "單位變動成本請填數字，例如 430。"
    ship_val, ship_ok = parse_number(shipping_cost)
    if not ship_ok:
        errors["shipping_cost"] = "運費請填數字，例如 60。"
    if not clean(currency):
        errors["currency"] = "請選擇幣別。"
    if not clean(confirmed_by):
        errors["confirmed_by"] = "請填寫確認人是誰。"
    if errors:
        return templates.TemplateResponse(request, "economics_form.html", ctx(
            request, brand=brand, product=product, values=values, errors=errors,
            is_update=repo.get_product_economics(web.conn, brand_id, product_id) is not None,
            nav_current='hub',
        ), status_code=400)
    repo.save_product_economics(
        web.conn, brand_id, product_id, actor=actor,
        selling_price=price_val, currency=currency, confirmed_by=clean(confirmed_by),
        fixed_cost=fixed_val, unit_variable_cost=unit_val, shipping_cost=ship_val,
        cpa_roas_basis=clean(cpa_roas_basis) or None, effective_from=clean(effective_from) or None,
    )
    return redirect_with_message(
        f"/brands/{brand_id}/products/{product_id}/economics-view",
        f"已儲存「{product['name']}」的產品經濟數字。",
    )


@router.post("/brands/{brand_id}/products/{product_id}/economics/confirm")
async def economics_confirm_post(request: Request, brand_id: str, product_id: str):
    """待確認經濟數字的一鍵確認（比照產品事實的確認模式，最小版：不用另外填確認人，
    直接用目前的操作人）。欄位還沒補齊也能先確認存在、之後仍可用「更新數字」補上。"""
    actor = require_actor(request)
    brand = require_brand(brand_id)
    product = require_product(brand, product_id)
    existing = repo.get_product_economics(web.conn, brand_id, product_id)
    if not existing:
        raise NotFoundKind("產品經濟數字")
    repo.confirm_product_economics(web.conn, brand_id, product_id, confirmed_by=actor, actor=actor)
    return redirect_with_message(
        f"/brands/{brand_id}/products/{product_id}",
        f"已確認「{product['name']}」的產品經濟數字，確認人：{actor}。",
    )


# ---------------------------------------------------------------------------
# 官方素材（issue #3）：Logo／產品照／包裝／其他，上傳、列表縮圖、刪除
# ---------------------------------------------------------------------------

_ASSET_CONTENT_TYPES = {"jpg": "image/jpeg", "jpeg": "image/jpeg", "png": "image/png",
                         "webp": "image/webp", "gif": "image/gif"}
_UNSAFE_ASSET_FILENAME_CHARS = re.compile(r"[^A-Za-z0-9._-]+")


def _assets_upload_dir() -> Path:
    raw = os.environ.get("BRAND_OS_UPLOADS")
    base = Path(raw) if raw else Path("C:/Users/User/Desktop/marketing/data/uploads")
    return base / "assets"


def _safe_asset_filename(name: str) -> str:
    """os.path.basename 去掉路徑 + 危險字元換成 `_`，比照 intake 照片的檔名驗證做法。"""
    name = os.path.basename((name or "").strip())
    name = _UNSAFE_ASSET_FILENAME_CHARS.sub("_", name)
    return name or "file"


@router.get("/brands/{brand_id}/assets/new")
async def asset_new_get(request: Request, brand_id: str):
    brand = require_brand(brand_id)
    values = {"asset_kind": "", "product_id": "", "title": ""}
    return templates.TemplateResponse(request, "asset_new.html", ctx(
        request, brand=brand, values=values, errors={}, products=list_products(brand_id),
        nav_current='hub',
    ))


@router.post("/brands/{brand_id}/assets/new")
async def asset_new_post(request: Request, brand_id: str, asset_kind: str = Form(""),
                          product_id: str = Form(""), title: str = Form(""),
                          file: UploadFile = File(...)):
    actor = require_actor(request)
    brand = require_brand(brand_id)
    products = list_products(brand_id)
    values = {"asset_kind": asset_kind, "product_id": product_id, "title": title}
    errors = {}
    if asset_kind not in dict(md.ASSET_KINDS):
        errors["asset_kind"] = "請選擇這是哪一種素材。"
    product_id_c = clean(product_id)
    if product_id_c and not repo.get_product(web.conn, brand_id, product_id_c):
        errors["product_id"] = "找不到這個產品，請重新選擇。"
    content = await file.read()
    filename = file.filename or ""
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if not filename or not content:
        errors["file"] = "請選擇一個圖檔上傳。"
    elif ext not in _ASSET_CONTENT_TYPES:
        errors["file"] = f"「{filename}」不是支援的圖片格式，請用 png、jpg、jpeg、webp 或 gif。"
    if errors:
        return templates.TemplateResponse(request, "asset_new.html", ctx(
            request, brand=brand, values=values, errors=errors, products=products,
            nav_current='hub',
        ), status_code=400)
    dest_dir = _assets_upload_dir() / new_id("oas")
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest_path = dest_dir / _safe_asset_filename(filename)
    dest_path.write_bytes(content)
    repo.create_official_asset(
        web.conn, brand_id, actor=actor, asset_kind=asset_kind, file_path=str(dest_path),
        product_id=product_id_c or None, title=clean(title) or None,
    )
    return redirect_with_message(
        f"/brands/{brand_id}/hub/assets", f"已上傳「{md.asset_kind_label(asset_kind)}」素材。")


@router.post("/brands/{brand_id}/assets/{asset_id}/delete")
async def asset_delete_post(request: Request, brand_id: str, asset_id: str):
    actor = require_actor(request)
    require_brand(brand_id)
    asset = repo.get_official_asset(web.conn, brand_id, asset_id)
    if not asset:
        raise NotFoundKind("官方素材")
    repo.delete_official_asset(web.conn, brand_id, asset_id, actor=actor)
    try:
        Path(asset["file_path"]).unlink(missing_ok=True)
    except OSError:
        pass
    return redirect_with_message(f"/brands/{brand_id}/hub/assets", "已刪除這個素材檔案。")


@router.get("/brands/{brand_id}/assets/file/{asset_id}/{filename}")
async def asset_file(request: Request, brand_id: str, asset_id: str, filename: str):
    """只回傳「這筆官方素材登記過的檔案」——不從網址參數直接組路徑，天生擋掉路徑穿越；
    找不到品牌、找不到素材、或檔名跟登記的不一致，一律 404（比照 intake 照片的做法）。"""
    require_brand(brand_id)
    asset = repo.get_official_asset(web.conn, brand_id, asset_id)
    if asset is None or Path(asset["file_path"]).name != filename:
        raise NotFoundKind("這個素材檔案")
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    return FileResponse(asset["file_path"], media_type=_ASSET_CONTENT_TYPES.get(ext, "application/octet-stream"),
                         filename=filename)


# 規則卡（issue #12）改分品牌後搬到 app/brand_intelligence/routes_settings.py（設定中心票
# 01，/brands/{brand_id}/settings/ads），這裡不再放平台層級的 /rule-cards 路由——
# app.core.rule_cards 的 CARDS 機制現在每個函式都要求 brand_id，沒有品牌上下文的全域頁面
# 已經無法運作。


