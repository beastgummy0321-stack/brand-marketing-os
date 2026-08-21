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

T4 刪除品牌／產品管理舊頁（2026-08-21）：這個檔案原本 68 支 TemplateResponse 頁面
handler 大多已被 React 新殼取代（品牌智庫走 `/api/library/...`、產品走
`/api/products/...`、報告走 `/api/brands/{id}/report`），刪光了純頁面渲染的部分。
但 `frontend/src/lib/libraryApi.ts` 的品牌事實／限制規則／宣稱／官方素材刪除／自有
渠道新增／品牌編輯這六類寫入動作，設計上直接沿用這裡的舊版表單 POST 端點（見該檔
檔頭註解），前端只認 `res.ok`——這些 POST 端點會 303 redirect 回對應的 `/hub/*`
或 `/brands/{id}`頁，因為 fetch 預設跟隨 redirect，redirect 目標也必須留著回
200，不然寫入動作在畫面上會顯示失敗（即使資料庫其實已經寫入成功）。所以本檔現在
只留：這些仍被前端直接呼叫的 POST 端點、它們 redirect 落地用的少數 GET hub 頁，
以及素材檔案服務（FileResponse，不是頁面）。其餘只被舊 Jinja 表單／連結呼叫的頁面
已整批刪除，改由 React 頁面接手。
"""

from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Form, Request
from fastapi.responses import FileResponse

from app import mock_data as md
from app.brand_intelligence import report as brand_report_mod
from app.brand_intelligence import repository as repo
from app.core import interrupts as core_interrupts
from app.intake import state as intake_state
from app.shared import web
from app.shared.web import (
    NotFoundKind,
    banner_ctx,
    clean,
    ctx,
    list_products,
    pending_brand_fact_count,
    pending_product_layer_count,
    redirect_with_message,
    require_actor,
    require_brand,
    scope_label,
    templates,
)
from app.brand_web import report_service

router = APIRouter()

PROVIDER = report_service.PROVIDER
SECTION_KEYS = brand_report_mod.SECTION_KEYS


def generate(conn, brand_id: str, actor: str) -> tuple:
    """保留舊頁測試的 provider 注入點，實際生成邏輯已搬至 report_service。"""
    return report_service.generate(conn, brand_id, actor, provider=PROVIDER)


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
# 全站打斷佇列（決策 0026）：收件匣頁本身已改走 GET /api/inbox（routes_inbox.py），
# 但收件匣卡片「知道了」這顆按鈕（S2.8）沿用既有這支端點，沒有重新造第二份，所以
# 這支還在用，不能跟著收件匣頁一起刪（見 test_inbox_api.py
# test_resolve_still_uses_existing_html_endpoint）。
# ---------------------------------------------------------------------------

@router.post("/interrupts/{interrupt_id}/resolve")
async def interrupt_resolve(request: Request, interrupt_id: str):
    actor = require_actor(request)
    core_interrupts.resolve(web.conn, interrupt_id, actor=actor)
    back = (request.headers.get("referer") or "/inbox").split("?")[0]
    return redirect_with_message(back, "好，知道了。")


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


# ---------------------------------------------------------------------------
# 品牌智庫（issue #8 決策 0021）：以下幾支 GET 頁只留著給前端六類舊表單 POST
# 端點（見檔頭 T4 說明）303 redirect 落地用，本身不再被任何人瀏覽。
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
# 顧客原話語料庫（GitHub issue #14，決策 0023 第 18a 條／0024 第 2 條）：新增已改走
# /api/library/brands/{id}/customer-voice（routes_library.py），這裡只留封存／刪除
# 兩支舊表單端點＋它們 redirect 落地用的 GET 頁（同上，見檔頭 T4 說明）。
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
# 品牌事實
# ---------------------------------------------------------------------------

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
# 官方素材（issue #3）：上傳已改走 POST /api/brands/{id}/assets（routes_library.py），
# 這裡只留刪除（前端仍直接呼叫這支舊端點）＋檔案服務（FileResponse，必留）。
# ---------------------------------------------------------------------------

_ASSET_CONTENT_TYPES = {"jpg": "image/jpeg", "jpeg": "image/jpeg", "png": "image/png",
                         "webp": "image/webp", "gif": "image/gif"}


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
