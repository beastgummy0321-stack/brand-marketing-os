# -*- coding: utf-8 -*-
"""app/main.py — 真正的組裝根（修憲落地 A4）：app factory、router 註冊、啟動流程。

原本這裡塞了 87 條品牌智庫業務路由（2426 行），卻頂著「組裝根永久豁免」的身分，
還被 app/ads、app/orders、app/intake 反向 import（main → ads.routes → main 的循環）。
拆成三塊（決策 0037 第 15 條）：

1. 本檔：只留 app factory、每日備份／保留策略的啟動節奏、router 註冊、錯誤處理。
2. `app/shared/web.py`：conn／templates／ctx／require_brand 等全站共用 web 工具。
3. `app/brand_intelligence/routes.py`：品牌智庫的業務路由本體。

拆完後 app/ads、app/orders、app/intake 一律改 import `app.shared.web`，不再 import
本檔，main → ads.routes → main 的循環自然消失（見 test_no_branch_imports_app_main）。

**例外**（刻意留在這裡，未搬進 brand_intelligence/routes.py，行數因此超過 100 行）：
首頁「今天要處理的事」（`_today_todos`／`/` 首頁）與 AI／Meta／GA4 設定頁——這兩處
直接碰 `app.ads`（讀廣告到期提醒；讀寫 Meta／GA4 連線設定），而 A2 落地的 import
掃描測試（test_architecture_boundaries.py）目前只允許 `app/main.py` 這個路徑 import
分支專屬層，本票不得為了搬移方便去修改那份既有測試。詳見票 A4 回報「Remaining risks」。

啟動流程：app.shared.web 一 import 就會套用 migrations、開一條全程共用的連線
（見該檔 `conn = coredb.connect_and_migrate()`）；這裡另外補每日備份／llm_task
保留策略清理的節奏（不能放進 app.shared.web，因為測試會直接改本檔的
`_last_backup_check` 模擬「今天還沒備份過」，見 test_backup.py）。

啟動：python -m uvicorn app.main:app --port 8710
"""

from datetime import datetime, timezone
from typing import Optional
from urllib.parse import urlencode

from fastapi import FastAPI, Form, Request
from fastapi.exception_handlers import http_exception_handler
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.ads import ga4_api  # noqa: E402  # 只用於設定頁測試連線，見「例外」說明
from app.ads import ga4_sync  # noqa: E402
from app.ads import meta_api  # noqa: E402
from app.ads import sync as ads_sync  # noqa: E402
from app.core import backup as corebackup
from app.core import db as coredb
from app.core import retention as core_retention
from app.core import settings as coresettings
from app.intake import state as intake_state
from app.llm import pricing as llm_pricing
from app.llm import providers as llm_providers
from app.shared import web
from app.shared.web import (
    MODEL_CHOICES,
    NeedOperator,
    _num_str,
    _with_brand_names,
    banner_ctx,
    ctx,
    list_active_brands,
    list_archived_brands,
    list_products,
    pending_brand_fact_count,
    parse_number,
    redirect_with_message,
    templates,
    clean,
)

# ---------------------------------------------------------------------------
# 啟動流程：每日備份檢查 ／ llm_task 保留策略清理（修憲落地 A5）
# ---------------------------------------------------------------------------

_last_backup_check: Optional[str] = None  # 記上次檢查過的日期（ISO 字串），避免同一天重複掃 backups 目錄
_last_retention_check: Optional[str] = None  # 同上，llm_task 保留策略清理版（修憲落地 A5）


def _backup_if_new_day() -> None:
    """跨日才真的備份；修憲落地 M5：舊版只在 process 啟動時跑一次，uvicorn 開一週
    就一週沒有新備份。這裡改成每個請求前比一次日期字串（成本極低），只有真的跨日
    才呼叫 run_daily_backup()（複製 DB＋清舊檔，見 app/core/backup.py）。"""
    global _last_backup_check
    today = datetime.now(timezone.utc).date().isoformat()
    if today != _last_backup_check:
        corebackup.run_daily_backup()
        _last_backup_check = today


def _purge_expired_llm_task_content_if_new_day() -> None:
    """跨日才清一次 llm_task 的過期大欄位（修憲落地 A5，見 app/core/retention.py）；
    做法比照 `_backup_if_new_day`。"""
    global _last_retention_check
    today = datetime.now(timezone.utc).date().isoformat()
    if today != _last_retention_check:
        core_retention.purge_expired_llm_task_content(web.conn)
        _last_retention_check = today


_backup_if_new_day()  # process 啟動時先跑一次（app.shared.web import 時已開好連線）


def reopen_connection():
    """模擬「重啟 app」：關掉現有連線、重新走一次啟動流程，回傳新連線。

    只給測試用，用來證明資料真的落地在 DB 檔案，不是活在記憶體物件裡
    （新連線是重新讀磁碟上的檔案，不會沿用舊連線的任何快取）。
    """
    web.conn.close()
    web.conn = coredb.connect_and_migrate()
    _backup_if_new_day()
    return web.conn


# ---------------------------------------------------------------------------
# FastAPI app
# ---------------------------------------------------------------------------

app = FastAPI(title="行銷作業系統（Phase 0 Mock UI）")
app.mount("/static", StaticFiles(directory=web.BASE_DIR / "static"), name="static")


@app.middleware("http")
async def _daily_backup_middleware(request: Request, call_next):
    """每個請求前補一次「今天備份了嗎」檢查（見 `_backup_if_new_day`），
    讓長時間不重啟的 process 也有每日備份，不必等下次重開才觸發。
    順帶補一次「今天清過 llm_task 過期大欄位了嗎」（修憲落地 A5）。"""
    _backup_if_new_day()
    _purge_expired_llm_task_content_if_new_day()
    return await call_next(request)


# ---------------------------------------------------------------------------
# 品牌總覽（例外，見檔頭說明：today todos 直接讀 app.ads 的廣告到期提醒）
# ---------------------------------------------------------------------------

def _today_todos() -> list:
    """首頁「今天要處理的事」：各品牌到期的廣告提醒（鐵則 15 聚合待辦）。

    這是全站唯一跨品牌的清單，因為品牌總覽本來就是跨品牌的頁面；
    每一則都標明是哪個品牌，點進去才會進入該品牌的畫面（不混排內容）。
    """
    from app.ads import onboarding as ads_onboarding
    return _with_brand_names(ads_onboarding.due_reminders(web.conn))


@app.get("/")
async def brand_overview(request: Request, empty: Optional[str] = None):
    show_empty = empty == "1"
    active = [] if show_empty else list_active_brands()
    archived = [] if show_empty else list_archived_brands()
    rows = []
    for b in active:
        products = list_products(b["id"])
        draft = intake_state.get_draft(b["id"])
        rows.append({
            "brand": b,
            "product_count": len(products),
            "pending": pending_brand_fact_count(b["id"]),
            "draft": draft,
        })
    return templates.TemplateResponse(request, "index.html", ctx(
        request, brand=None, active_brands=active,
        rows=rows, archived=archived, show_empty_demo=show_empty,
        todos=[] if show_empty else _today_todos(),
        **banner_ctx(request),
    ))


# ---------------------------------------------------------------------------
# 設定頁（AI 金鑰／模型／花費上限／Meta／GA4，docs/design/07 §1、§3；例外，見檔頭說明）
# ---------------------------------------------------------------------------

def _model_choices():
    """把費率（app/llm/pricing.py 唯一來源）併進選單，設定頁選項旁顯示定價。"""
    out = []
    for model_id, name in MODEL_CHOICES:
        rate = llm_pricing.PRICING[model_id]
        out.append({
            "id": model_id, "name": name,
            "price_text": (f"每百萬 token：輸入 US${rate['input_per_mtok']:g}、"
                           f"輸出 US${rate['output_per_mtok']:g}"),
        })
    return out


def _masked_key(key: Optional[str]) -> Optional[str]:
    """金鑰遮罩：只露開頭的 sk- 與末四碼，畫面永不顯示完整金鑰（07 §1 規則 5）。"""
    if not key:
        return None
    if len(key) < 8:
        return "…"
    prefix = "sk-" if key.startswith("sk-") else ""
    return f"{prefix}…{key[-4:]}"


def settings_ctx(request: Request, values=None, errors=None):
    return ctx(
        request, brand=None,
        masked_key=_masked_key(coresettings.get_api_key(web.conn)),
        api_key_source=coresettings.api_key_source(web.conn),
        db_key_present=bool(coresettings.get_setting(web.conn, coresettings.API_KEY_SETTING)),
        model_choices=_model_choices(),
        current_model=coresettings.get_llm_model(web.conn),
        # 任務 →（模型、思考等級）對照表：可視可核對（票 #27 驗收 1）。
        task_model_thinking_table=llm_providers.task_default_table(),
        masked_meta_token=_masked_key(ads_sync.get_token(web.conn)),
        meta_account_id=ads_sync.get_account_id(web.conn) or "",
        masked_ga4_key=_masked_key(ga4_sync.get_service_account_json(web.conn)),
        ga4_property_id=ga4_sync.get_property_id(web.conn) or "",
        values=values or {"intake_budget": _num_str(coresettings.get_intake_budget_limit(web.conn))},
        errors=errors or {},
        **banner_ctx(request),
    )


@app.get("/settings")
async def settings_get(request: Request):
    return templates.TemplateResponse(request, "settings.html", settings_ctx(request))


@app.post("/settings/api-key")
async def settings_api_key_post(request: Request, api_key: str = Form("")):
    key = clean(api_key)
    if not key:
        return templates.TemplateResponse(request, "settings.html", settings_ctx(
            request, errors={"api_key": "請貼上 AI 金鑰。"},
        ), status_code=400)
    coresettings.set_setting(web.conn, coresettings.API_KEY_SETTING, key)
    return redirect_with_message("/settings", "已儲存 AI 金鑰。之後的 AI 功能會用這把金鑰。")


@app.post("/settings/api-key/clear-db")
async def settings_api_key_clear_db_post(request: Request):
    """把資料庫裡的金鑰刪掉，不可逆——只在使用者按下按鈕（畫面上有二次確認）時執行，
    不會被任何流程自動觸發（修憲落地 M4）。"""
    coresettings.clear_api_key_from_db(web.conn)
    if coresettings.api_key_source(web.conn) == "env":
        msg = "已清除資料庫裡的金鑰。目前改用環境變數裡的金鑰，AI 功能不受影響。"
    else:
        msg = "已清除資料庫裡的金鑰。目前沒有可用的金鑰，AI 功能會提示尚未設定，請重新貼上或改設環境變數。"
    return redirect_with_message("/settings", msg)


@app.post("/settings/meta")
async def settings_meta_post(request: Request, meta_token: str = Form(""),
                             meta_account_id: str = Form("")):
    """Meta 廣告帳號的唯讀連線設定（票 9）。金鑰只存在本機資料庫，畫面只顯示遮罩後的樣子。"""
    account = clean(meta_account_id)
    token = clean(meta_token)
    if not account:
        return templates.TemplateResponse(request, "settings.html", settings_ctx(
            request, errors={"meta_account_id": "請填入廣告帳號編號。"},
        ), status_code=400)
    coresettings.set_setting(web.conn, ads_sync.ACCOUNT_SETTING, account)
    if token:
        coresettings.set_setting(web.conn, ads_sync.TOKEN_SETTING, token)
    return redirect_with_message("/settings", "已儲存 Meta 廣告帳號的連線設定。")


@app.post("/settings/ga4")
async def settings_ga4_post(request: Request, ga4_property_id: str = Form(""),
                            ga4_service_account_json: str = Form("")):
    """GA4 服務帳戶連線設定（票 34）。金鑰只存在本機資料庫，畫面只顯示遮罩後的樣子。"""
    property_id = clean(ga4_property_id)
    key_json = ga4_service_account_json.strip()
    if not property_id:
        return templates.TemplateResponse(request, "settings.html", settings_ctx(
            request, errors={"ga4_property_id": "請填入 GA4 資源編號。"},
        ), status_code=400)
    coresettings.set_setting(web.conn, ga4_sync.PROPERTY_SETTING, property_id)
    if key_json:
        coresettings.set_setting(web.conn, ga4_sync.SERVICE_ACCOUNT_SETTING, key_json)
    return redirect_with_message("/settings", "已儲存 GA4 服務帳戶的連線設定。")


@app.post("/settings/model")
async def settings_model_post(request: Request, llm_model: str = Form("")):
    labels = {m_id: name for m_id, name in MODEL_CHOICES}
    if llm_model not in labels:
        return templates.TemplateResponse(request, "settings.html", settings_ctx(
            request, errors={"llm_model": "請從選單中選一個模型。"},
        ), status_code=400)
    coresettings.set_setting(web.conn, coresettings.LLM_MODEL_SETTING, llm_model)
    return redirect_with_message("/settings", f"已將使用的模型設定為「{labels[llm_model]}」。")


@app.post("/settings/budget")
async def settings_budget_post(request: Request, intake_budget: str = Form("")):
    value, ok = parse_number(intake_budget)
    if not ok or value is None or value <= 0:
        return templates.TemplateResponse(request, "settings.html", settings_ctx(
            request, values={"intake_budget": intake_budget},
            errors={"intake_budget": "花費上限請填大於 0 的數字，例如 30。"},
        ), status_code=400)
    coresettings.set_setting(web.conn, coresettings.INTAKE_BUDGET_SETTING, _num_str(value))
    return redirect_with_message(
        "/settings", f"已將單次建檔的花費上限設為 $ {_num_str(value)}。"
    )


@app.post("/settings/test-connection")
async def settings_test_connection_post(request: Request):
    """發一次極小的真實請求驗證金鑰。沒有金鑰時不發請求，直接給人話提示。"""
    if not coresettings.get_api_key(web.conn):
        return redirect_with_message(
            "/settings", "尚未設定金鑰。請先在上方填入 AI 金鑰，儲存後再測試。", kind="warn",
        )
    try:
        llm_providers.AnthropicProvider().complete(
            model=coresettings.get_llm_model(web.conn), system=None,
            messages=[{"role": "user", "content": "hi"}], max_tokens=1, timeout_s=30.0,
        )
    except llm_providers.ProviderError as exc:
        # providers 已統一把供應商例外轉成人話（含 401＝金鑰錯誤、餘額不足），
        # 這裡直接顯示同一句，設定頁與建檔精靈才不會兩套說法。
        return redirect_with_message("/settings", str(exc), kind="danger")
    except Exception:
        return redirect_with_message(
            "/settings", "測試失敗：系統發生問題，請再試一次。", kind="danger",
        )
    return redirect_with_message("/settings", "金鑰有效：AI 服務有正常回應，可以開始使用 AI 功能。")


@app.post("/settings/meta/test-connection")
async def settings_meta_test_connection_post(request: Request):
    """驗證 Meta 唯讀連線。沒有設定帳號＋金鑰時不發請求，直接給人話提示（票 48）。"""
    if not ads_sync.is_configured(web.conn):
        return redirect_with_message(
            "/settings", "尚未設定 Meta 連線。請先在上方填入廣告帳號編號與唯讀金鑰，儲存後再測試。",
            kind="warn",
        )
    try:
        ads_sync.make_client(web.conn).list_campaigns(ads_sync.get_account_id(web.conn))
    except meta_api.MetaApiError as exc:
        return redirect_with_message("/settings", str(exc), kind="danger")
    except Exception:
        return redirect_with_message(
            "/settings", "測試失敗：系統發生問題，請再試一次。", kind="danger",
        )
    return redirect_with_message("/settings", "連線正常：可以讀到 Meta 廣告帳號的資料。")


@app.post("/settings/ga4/test-connection")
async def settings_ga4_test_connection_post(request: Request):
    """驗證 GA4 唯讀連線。沒有設定資源編號＋服務帳戶金鑰時不發請求，直接給人話提示（票 48）。"""
    if not ga4_sync.is_configured(web.conn):
        return redirect_with_message(
            "/settings", "尚未設定 GA4 連線。請先在上方填入資源編號與服務帳戶金鑰，儲存後再測試。",
            kind="warn",
        )
    today = datetime.now(timezone.utc).date().isoformat()
    try:
        ga4_sync.make_client(web.conn).fetch_source_medium(today, today)
    except ga4_api.GA4ApiError as exc:
        return redirect_with_message("/settings", str(exc), kind="danger")
    except Exception:
        return redirect_with_message(
            "/settings", "測試失敗：系統發生問題，請再試一次。", kind="danger",
        )
    return redirect_with_message("/settings", "連線正常：可以讀到 GA4 網站數據。")


# ---------------------------------------------------------------------------
# Router 註冊
# ---------------------------------------------------------------------------

from app.brand_intelligence.routes import router as brand_intelligence_router  # noqa: E402
from app.intake.routes import router as intake_router  # noqa: E402
from app.ads.routes import router as ads_router  # noqa: E402
from app.orders.routes import router as orders_router  # noqa: E402

app.include_router(brand_intelligence_router)
app.include_router(intake_router)
app.include_router(ads_router)
app.include_router(orders_router)

# 啟動斷言（第 2 刀「清理登記處」）：確認刪品牌時該連鎖清資料的模組都有登記進
# app.core.cleanup，少一個就不讓服務起來，避免又漏掉誰（orders 這家還沒接上登記處，
# 是第 5 刀的範圍，這裡先不列進來）。
from app.core import cleanup as core_cleanup  # noqa: E402

_REQUIRED_CLEANUP_MODULES = ("品牌智庫", "建檔精靈", "廣告")
_missing_cleanup = [n for n in _REQUIRED_CLEANUP_MODULES if n not in core_cleanup.registered_names()]
if _missing_cleanup:
    raise RuntimeError(f"清理登記處少登記了：{_missing_cleanup}")


# ---------------------------------------------------------------------------
# 錯誤處理
# ---------------------------------------------------------------------------

@app.exception_handler(NeedOperator)
async def handle_need_operator(request: Request, exc: NeedOperator):
    url = f"/settings/operator?{urlencode({'next': exc.next_path, 'blocked': '1'})}"
    return RedirectResponse(url, status_code=303)


@app.exception_handler(StarletteHTTPException)
async def handle_http_exception(request: Request, exc: StarletteHTTPException):
    if exc.status_code == 404:
        kind = exc.detail if isinstance(exc.detail, str) and exc.detail not in ("Not Found",) else "頁面"
        return templates.TemplateResponse(request, "error_404.html", ctx(
            request, brand=None, kind=kind, hide_sidebar=True,
        ), status_code=404)
    return await http_exception_handler(request, exc)


@app.exception_handler(Exception)
async def handle_unexpected_exception(request: Request, exc: Exception):
    return templates.TemplateResponse(request, "error_500.html", ctx(
        request, brand=None, hide_sidebar=True,
    ), status_code=500)


# ---------------------------------------------------------------------------
# 回溯相容：讓 `app.main.conn`／`.templates`／`.MODEL_CHOICES` 等既有測試直接讀的屬性
# 繼續解析——這些名字現在真正定義在 app.shared.web（conn 會被 reopen_connection()
# 換掉，必須即時代理查值，不能在這裡靜態 import 一次就固定住）。
# ---------------------------------------------------------------------------

def __getattr__(name):
    return getattr(web, name)
