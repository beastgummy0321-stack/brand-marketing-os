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

import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, Form, Request
from fastapi.exception_handlers import http_exception_handler
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.ads import auto_sync as ads_auto_sync  # noqa: E402
from app.ads import ga4_api  # noqa: E402  # 只用於設定頁測試連線，見「例外」說明
from app.ads import ga4_sync  # noqa: E402
from app.ads import meta_api  # noqa: E402
from app.ads import sync as ads_sync  # noqa: E402
from app.core import backup as corebackup
from app.core import creative_assets as corecreative
from app.core import db as coredb
from app.core import retention as core_retention
from app.core import settings as coresettings
from app.intake import state as intake_state
from app.llm import pricing as llm_pricing
from app.llm import providers as llm_providers
from app.shared import web
from app.shared.web import (
    MODEL_CHOICES,
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
# ---------------------------------------------------------------------------
# 自動同步（LIVE 每四小時、其餘每日；應用程式啟動時註冊程式內排程）
# ---------------------------------------------------------------------------
_last_auto_sync_check: Optional[datetime] = None
_last_weekly_engine_check: Optional[datetime] = None
_AUTO_SYNC_POLL_SECONDS = 3600  # 每小時檢查是否已到四小時或跨日門檻


def _auto_sync_if_due(now: Optional[datetime] = None) -> None:
    """LIVE 檔期每四小時同步；其餘狀態維持每日一次。"""
    global _last_auto_sync_check
    now = now or datetime.now(timezone.utc)
    has_live = bool(web.conn.execute(
        "SELECT 1 FROM campaign_cycle WHERE status = 'LIVE' AND archived = 0 LIMIT 1"
    ).fetchone())
    due = (_last_auto_sync_check is None
           or (has_live and now - _last_auto_sync_check >= timedelta(hours=4))
           or (not has_live and now.date() != _last_auto_sync_check.date()))
    if due:
        ads_auto_sync.run(web.conn, today=now.date().isoformat())
        _last_auto_sync_check = now


def _weekly_engine_if_due(now: Optional[datetime] = None) -> None:
    """每個 ISO 週只跑一次週判讀；process 重啟後會補跑當週。"""
    global _last_weekly_engine_check
    now = now or datetime.now(timezone.utc)
    current_week = now.isocalendar()[:2]
    last_week = _last_weekly_engine_check.isocalendar()[:2] if _last_weekly_engine_check else None
    if last_week != current_week:
        ads_auto_sync.run_weekly_engine(web.conn, today=now.date().isoformat())
        _last_weekly_engine_check = now


def _auto_sync_loop() -> None:
    """背景執行緒，每小時檢查同步門檻——用背景執行緒而不是像備份那樣掛在
    `_daily_backup_middleware`（每個 HTTP 請求都會跑一次），是因為自動同步會打外部
    API：絕不能讓它被測試的 TestClient 請求意外觸發。這個迴圈只掛在 FastAPI
    `startup` 事件底下才會啟動，而 `TestClient(app)`（不用 `with` context manager，
    這個 repo 目前所有測試都是這樣用）不會觸發 startup 事件——測試因此永遠碰不到
    這條路徑，見 app/tests/test_ads_auto_sync.py 檔頭驗證過的行為。"""
    while True:
        time.sleep(_AUTO_SYNC_POLL_SECONDS)
        _auto_sync_if_due()
        _weekly_engine_if_due()


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

# 新殼（票 01-react-shell，ADR 0003）：production 掛 frontend/dist 於 /app，
# 舊 145 條 HTML 路由原封不動。frontend/dist 是建置產物、不進版控，開發期走
# Vite dev server（npm run dev）不會有這個目錄，所以只有目錄存在才掛載，
# 沒 build 過的機器（例如測試環境）啟動仍要照常成功。


class _SpaStaticFiles(StaticFiles):
    """票 05-spa-routing：新殼裝了 react-router-dom，子路徑（如 /app/brands/xxx）
    不對應任何實體檔案，預設 StaticFiles(html=True) 找不到檔案就回 404——這正是
    ADR 0003 之後「直接貼網址進子路徑會 404」的根因。子路徑一律退回 index.html，
    交給前端路由庫接手決定畫面；真正存在的檔案（JS/CSS/圖片等靜態資產）不受影響，
    照舊直接回傳。"""

    async def get_response(self, path: str, scope):
        try:
            return await super().get_response(path, scope)
        except StarletteHTTPException as exc:
            if exc.status_code == 404:
                return await super().get_response("index.html", scope)
            raise


_FRONTEND_DIST = web.BASE_DIR.parent / "frontend" / "dist"
if _FRONTEND_DIST.is_dir():
    app.mount("/app", _SpaStaticFiles(directory=_FRONTEND_DIST, html=True), name="react-shell")

@app.on_event("startup")
def _register_auto_sync_schedule() -> None:
    """票 07-auto-sync：應用程式啟動時註冊程式內排程。啟動當下先跑一次（不等第一個
    小時），之後交給背景執行緒每小時檢查四小時／每日門檻。"""
    _auto_sync_if_due()
    _weekly_engine_if_due()
    threading.Thread(target=_auto_sync_loop, daemon=True).start()


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
        # 各欄位的預設值先鋪好，再讓某一格的錯誤回顯蓋上去——values 整包取代的話，
        # 存花費上限失敗時素材資料夾那格會變空白（兩格在同一頁、互不相干）。
        values={"intake_budget": _num_str(coresettings.get_intake_budget_limit(web.conn)),
                "creative_root": str(corecreative.get_root(web.conn)),
                "prompt_header": coresettings.get_setting(
                    web.conn, coresettings.IMAGE_PROMPT_HEADER_SETTING, ""),
                **(values or {})},
        errors=errors or {},
        **banner_ctx(request),
    )


@app.get("/settings")
async def settings_get(request: Request):
    return templates.TemplateResponse(request, "settings.html", settings_ctx(request))


# ---------------------------------------------------------------------------
# 設定頁寫入邏輯（純函式，回傳錯誤人話訊息／None＝成功）：HTML 表單路由與下方 JSON API
# 路由共用同一份，不為了 JSON 契約重寫第二份寫入邏輯（票 B1-settings）。
# ---------------------------------------------------------------------------

def _write_api_key(api_key: str) -> Optional[str]:
    key = clean(api_key)
    if not key:
        return "請貼上 AI 金鑰。"
    coresettings.set_setting(web.conn, coresettings.API_KEY_SETTING, key)
    return None


def _write_meta_settings(account_id: str, token: str) -> Optional[str]:
    account = clean(account_id)
    token_c = clean(token)
    if not account:
        return "請填入廣告帳號編號。"
    coresettings.set_setting(web.conn, ads_sync.ACCOUNT_SETTING, account)
    if token_c:
        coresettings.set_setting(web.conn, ads_sync.TOKEN_SETTING, token_c)
    return None


def _write_ga4_settings(property_id: str, service_account_json: str) -> Optional[str]:
    property_id_c = clean(property_id)
    key_json = (service_account_json or "").strip()
    if not property_id_c:
        return "請填入 GA4 資源編號。"
    coresettings.set_setting(web.conn, ga4_sync.PROPERTY_SETTING, property_id_c)
    if key_json:
        coresettings.set_setting(web.conn, ga4_sync.SERVICE_ACCOUNT_SETTING, key_json)
    return None


def _write_model(llm_model: str) -> Optional[str]:
    labels = {m_id: name for m_id, name in MODEL_CHOICES}
    if llm_model not in labels:
        return "請從選單中選一個模型。"
    coresettings.set_setting(web.conn, coresettings.LLM_MODEL_SETTING, llm_model)
    return None


def _write_budget(raw_budget) -> Optional[str]:
    """raw_budget 接受字串（表單）或數字（JSON）——先轉字串再走既有 parse_number，
    驗證規則只寫一份。"""
    raw = "" if raw_budget is None else str(raw_budget)
    value, ok = parse_number(raw)
    if not ok or value is None or value <= 0:
        return "花費上限請填大於 0 的數字，例如 30。"
    coresettings.set_setting(web.conn, coresettings.INTAKE_BUDGET_SETTING, _num_str(value))
    return None


def _write_creative_root(raw_root: str) -> Optional[str]:
    """三道驗證：有填、是完整路徑、不是磁碟機根目錄——刪品牌／刪檔期會刪掉這底下對應的
    子資料夾，指到 `C:\\` 這種地方很危險。不驗資料夾存不存在：使用者可能先填好路徑，
    等一下才插上那顆外接硬碟。"""
    raw = clean(raw_root)
    path = Path(raw) if raw else None
    if path is None or not path.is_absolute() or path.parent == path:
        return ("請填一個完整的資料夾路徑（例如 D:\\行銷素材），"
                "不要只填資料夾名稱，也不要填磁碟機根目錄。")
    coresettings.set_setting(web.conn, corecreative.SETTING_KEY, str(path))
    return None


def _write_prompt_header(prompt_header: str) -> None:
    coresettings.set_setting(
        web.conn, coresettings.IMAGE_PROMPT_HEADER_SETTING, (prompt_header or "").strip())


def _run_ai_test_connection() -> tuple:
    """回傳 (人話訊息, kind)：kind 沿用 `redirect_with_message` 既有的 'ok'／'warn'／'danger'
    三種，HTML 與 JSON 路由共用同一份判斷。"""
    if not coresettings.get_api_key(web.conn):
        return "尚未設定金鑰。請先在上方填入 AI 金鑰，儲存後再測試。", "warn"
    try:
        llm_providers.AnthropicProvider().complete(
            model=coresettings.get_llm_model(web.conn), system=None,
            messages=[{"role": "user", "content": "hi"}], max_tokens=1, timeout_s=30.0,
        )
    except llm_providers.ProviderError as exc:
        # providers 已統一把供應商例外轉成人話（含 401＝金鑰錯誤、餘額不足），
        # 這裡直接顯示同一句，設定頁與建檔精靈才不會兩套說法。
        return str(exc), "danger"
    except Exception:
        return "測試失敗：系統發生問題，請再試一次。", "danger"
    return "金鑰有效：AI 服務有正常回應，可以開始使用 AI 功能。", "ok"


def _run_meta_test_connection() -> tuple:
    if not ads_sync.is_configured(web.conn):
        return "尚未設定 Meta 連線。請先在上方填入廣告帳號編號與唯讀金鑰，儲存後再測試。", "warn"
    try:
        ads_sync.make_client(web.conn).list_campaigns(ads_sync.get_account_id(web.conn))
    except meta_api.MetaApiError as exc:
        return str(exc), "danger"
    except Exception:
        return "測試失敗：系統發生問題，請再試一次。", "danger"
    return "連線正常：可以讀到 Meta 廣告帳號的資料。", "ok"


def _run_ga4_test_connection() -> tuple:
    if not ga4_sync.is_configured(web.conn):
        return "尚未設定 GA4 連線。請先在上方填入資源編號與服務帳戶金鑰，儲存後再測試。", "warn"
    today = datetime.now(timezone.utc).date().isoformat()
    try:
        ga4_sync.make_client(web.conn).fetch_source_medium(today, today)
    except ga4_api.GA4ApiError as exc:
        return str(exc), "danger"
    except Exception:
        return "測試失敗：系統發生問題，請再試一次。", "danger"
    return "連線正常：可以讀到 GA4 網站數據。", "ok"


@app.post("/settings/api-key")
async def settings_api_key_post(request: Request, api_key: str = Form("")):
    error = _write_api_key(api_key)
    if error:
        return templates.TemplateResponse(request, "settings.html", settings_ctx(
            request, errors={"api_key": error},
        ), status_code=400)
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
    error = _write_meta_settings(meta_account_id, meta_token)
    if error:
        return templates.TemplateResponse(request, "settings.html", settings_ctx(
            request, errors={"meta_account_id": error},
        ), status_code=400)
    return redirect_with_message("/settings", "已儲存 Meta 廣告帳號的連線設定。")


@app.post("/settings/ga4")
async def settings_ga4_post(request: Request, ga4_property_id: str = Form(""),
                            ga4_service_account_json: str = Form("")):
    """GA4 服務帳戶連線設定（票 34）。金鑰只存在本機資料庫，畫面只顯示遮罩後的樣子。"""
    error = _write_ga4_settings(ga4_property_id, ga4_service_account_json)
    if error:
        return templates.TemplateResponse(request, "settings.html", settings_ctx(
            request, errors={"ga4_property_id": error},
        ), status_code=400)
    return redirect_with_message("/settings", "已儲存 GA4 服務帳戶的連線設定。")


@app.post("/settings/model")
async def settings_model_post(request: Request, llm_model: str = Form("")):
    error = _write_model(llm_model)
    if error:
        return templates.TemplateResponse(request, "settings.html", settings_ctx(
            request, errors={"llm_model": error},
        ), status_code=400)
    labels = {m_id: name for m_id, name in MODEL_CHOICES}
    return redirect_with_message("/settings", f"已將使用的模型設定為「{labels[llm_model]}」。")


@app.post("/settings/budget")
async def settings_budget_post(request: Request, intake_budget: str = Form("")):
    error = _write_budget(intake_budget)
    if error:
        return templates.TemplateResponse(request, "settings.html", settings_ctx(
            request, values={"intake_budget": intake_budget}, errors={"intake_budget": error},
        ), status_code=400)
    return redirect_with_message(
        "/settings",
        f"已將單次建檔的花費上限設為 $ {_num_str(coresettings.get_intake_budget_limit(web.conn))}。"
    )


@app.post("/settings/creative-root")
async def settings_creative_root_post(request: Request, creative_root: str = Form("")):
    error = _write_creative_root(creative_root)
    if error:
        return templates.TemplateResponse(request, "settings.html", settings_ctx(
            request, values={"creative_root": creative_root}, errors={"creative_root": error},
        ), status_code=400)
    return redirect_with_message(
        "/settings", f"素材圖檔資料夾已設為 {corecreative.get_root(web.conn)}。")


@app.post("/settings/prompt-header")
async def settings_prompt_header_post(request: Request, prompt_header: str = Form("")):
    """整組複製提示詞的自訂開頭（票 11-copy-flows；ADR 0008 三）：全站一份、不分品牌，
    存進 app_setting。選填——留白代表整組複製時不加開頭那一行，不是輸入錯誤。"""
    _write_prompt_header(prompt_header)
    return redirect_with_message("/settings", "已儲存整組複製提示詞的自訂開頭。")


@app.post("/settings/test-connection")
async def settings_test_connection_post(request: Request):
    """發一次極小的真實請求驗證金鑰。沒有金鑰時不發請求，直接給人話提示。"""
    message, kind = _run_ai_test_connection()
    return redirect_with_message("/settings", message, kind=kind)


@app.post("/settings/meta/test-connection")
async def settings_meta_test_connection_post(request: Request):
    """驗證 Meta 唯讀連線。沒有設定帳號＋金鑰時不發請求，直接給人話提示（票 48）。"""
    message, kind = _run_meta_test_connection()
    return redirect_with_message("/settings", message, kind=kind)


@app.post("/settings/ga4/test-connection")
async def settings_ga4_test_connection_post(request: Request):
    """驗證 GA4 唯讀連線。沒有設定資源編號＋服務帳戶金鑰時不發請求，直接給人話提示（票 48）。"""
    message, kind = _run_ga4_test_connection()
    return redirect_with_message("/settings", message, kind=kind)


# ---------------------------------------------------------------------------
# 設定頁 JSON API（票 B1-settings，契約 `.scratch/grill/GRILL-B1-settings.md` S15）。
# 讀值與寫入邏輯全部重用上面／settings_ctx() 既有函式，這裡只做「解析請求 → 呼叫 →
# 組 JSON」的薄層。規則卡（S15.29–S15.33）另掛在 app/ads/routes_settings.py 同模組。
# ---------------------------------------------------------------------------

async def _parse_json_body(request: Request):
    """回傳 (body, None) 成功；(None, 錯誤回應) 失敗。錯誤文案沿用既有
    `app/ads/routes_quick_generate.py` 的慣例，不重複發明第二份。"""
    try:
        body = await request.json()
    except ValueError:
        return None, JSONResponse({"error": "請求格式不是合法的 JSON"}, status_code=400)
    if not isinstance(body, dict):
        return None, JSONResponse({"error": "請求格式不是合法的 JSON"}, status_code=400)
    return body, None


def _settings_json_data() -> dict:
    """GET /api/settings 的資料組裝（契約 SettingsData 型別）。讀值邏輯與 settings_ctx()
    共用同一批底層存取函式，這裡只是換一種給 JSON 用的型別（原始 float／list，不是表單
    用的字串）。"""
    return {
        "masked_key": _masked_key(coresettings.get_api_key(web.conn)),
        "api_key_source": coresettings.api_key_source(web.conn),
        "db_key_present": bool(coresettings.get_setting(web.conn, coresettings.API_KEY_SETTING)),
        "model_choices": _model_choices(),
        "current_model": coresettings.get_llm_model(web.conn),
        # 契約 TaskModelThinkingRow 只有這三欄；task_default_table() 另外多回一個
        # task_type（HTML 頁不用、JSON 契約沒寫），這裡投影掉，不把內部鍵洩漏出去。
        "task_model_thinking_table": [
            {"task_label": r["task_label"], "model_label": r["model_label"],
             "thinking_label": r["thinking_label"]}
            for r in llm_providers.task_default_table()
        ],
        "masked_meta_token": _masked_key(ads_sync.get_token(web.conn)),
        "meta_account_id": ads_sync.get_account_id(web.conn) or "",
        "masked_ga4_key": _masked_key(ga4_sync.get_service_account_json(web.conn)),
        "ga4_property_id": ga4_sync.get_property_id(web.conn) or "",
        "creative_root": str(corecreative.get_root(web.conn)),
        "prompt_header": coresettings.get_setting(web.conn, coresettings.IMAGE_PROMPT_HEADER_SETTING, ""),
        "intake_budget": coresettings.get_intake_budget_limit(web.conn),
    }


@app.get("/api/settings")
async def api_settings_get():
    return {"data": _settings_json_data(), "generated_at": datetime.now(timezone.utc).isoformat()}


@app.post("/api/settings/meta")
async def api_settings_meta_post(request: Request):
    body, err = await _parse_json_body(request)
    if err:
        return err
    error = _write_meta_settings(body.get("meta_account_id", ""), body.get("meta_token", ""))
    if error:
        return JSONResponse({"error": error}, status_code=400)
    return {}


@app.post("/api/settings/meta/test-connection")
async def api_settings_meta_test_connection_post():
    message, kind = _run_meta_test_connection()
    return {"message": message, "kind": kind}


@app.post("/api/settings/ga4")
async def api_settings_ga4_post(request: Request):
    body, err = await _parse_json_body(request)
    if err:
        return err
    error = _write_ga4_settings(body.get("ga4_property_id", ""), body.get("ga4_service_account_json", ""))
    if error:
        return JSONResponse({"error": error}, status_code=400)
    return {}


@app.post("/api/settings/ga4/test-connection")
async def api_settings_ga4_test_connection_post():
    message, kind = _run_ga4_test_connection()
    return {"message": message, "kind": kind}


@app.post("/api/settings/api-key")
async def api_settings_api_key_post(request: Request):
    body, err = await _parse_json_body(request)
    if err:
        return err
    error = _write_api_key(body.get("api_key", ""))
    if error:
        return JSONResponse({"error": error}, status_code=400)
    return {}


@app.post("/api/settings/api-key/clear-db")
async def api_settings_api_key_clear_db_post():
    """不可逆動作：清空資料庫裡的金鑰。二次確認在前端做（S15.17），這裡跟舊表單路由
    一樣不再另外確認一次。"""
    coresettings.clear_api_key_from_db(web.conn)
    return {}


@app.post("/api/settings/test-connection")
async def api_settings_test_connection_post():
    message, kind = _run_ai_test_connection()
    return {"message": message, "kind": kind}


@app.post("/api/settings/model")
async def api_settings_model_post(request: Request):
    body, err = await _parse_json_body(request)
    if err:
        return err
    error = _write_model(body.get("llm_model", ""))
    if error:
        return JSONResponse({"error": error}, status_code=400)
    return {}


@app.post("/api/settings/creative-root")
async def api_settings_creative_root_post(request: Request):
    body, err = await _parse_json_body(request)
    if err:
        return err
    error = _write_creative_root(body.get("creative_root", ""))
    if error:
        return JSONResponse({"error": error}, status_code=400)
    return {}


@app.post("/api/settings/prompt-header")
async def api_settings_prompt_header_post(request: Request):
    body, err = await _parse_json_body(request)
    if err:
        return err
    _write_prompt_header(body.get("prompt_header", ""))
    return {}


@app.post("/api/settings/budget")
async def api_settings_budget_post(request: Request):
    body, err = await _parse_json_body(request)
    if err:
        return err
    error = _write_budget(body.get("intake_budget"))
    if error:
        return JSONResponse({"error": error}, status_code=400)
    return {}


# ---------------------------------------------------------------------------
# Router 註冊
# ---------------------------------------------------------------------------

from app.brand_intelligence.routes import router as brand_intelligence_router  # noqa: E402
from app.brand_intelligence.routes_inbox import router as inbox_router  # noqa: E402
from app.brand_intelligence.routes_library import router as library_router  # noqa: E402
from app.brand_intelligence.routes_products import router as products_router  # noqa: E402
from app.brand_intelligence.routes_settings import router as settings_hub_router  # noqa: E402
from app.intake.routes import router as intake_router  # noqa: E402
from app.intake.routes_api import router as intake_api_router  # noqa: E402
from app.ads.routes import router as ads_router  # noqa: E402
from app.orders.routes import router as orders_router  # noqa: E402
from app.dashboard.routes import router as dashboard_router  # noqa: E402
from app.dashboard.routes_pinned_views_api import router as pinned_views_router  # noqa: E402
from app.dashboard.routes_jobs_api import router as jobs_active_router  # noqa: E402

app.include_router(brand_intelligence_router)
app.include_router(inbox_router)
app.include_router(library_router)
app.include_router(products_router)
app.include_router(settings_hub_router)
app.include_router(intake_router)
app.include_router(intake_api_router)
app.include_router(ads_router)
app.include_router(orders_router)
app.include_router(dashboard_router)
app.include_router(pinned_views_router)
app.include_router(jobs_active_router)

# ---------------------------------------------------------------------------
# app.ads → app.orders 依賴注入（第 7 刀，A1 三層地界新規則：app/ads 不得 import
# app.orders；app/orders 允許 import app.ads，方向只能單向，見
# test_architecture_boundaries.py）。這幾個 app.ads 模組原本各自 import
# app.orders.repository／channel／dispatch，改成在這裡（唯一合法跨層組裝的組裝根）
# 把真正的模組指派進去，模組內部呼叫寫法完全不變（等同延用同一顆物件）。
# ---------------------------------------------------------------------------
from app.ads import codes as ads_codes  # noqa: E402
from app.ads import data_onboarding as ads_data_onboarding  # noqa: E402
from app.ads import inflation as ads_inflation  # noqa: E402
from app.ads import reading as ads_reading  # noqa: E402
from app.ads import routes as ads_routes_mod  # noqa: E402
from app.ads import settlement as ads_settlement  # noqa: E402
from app.ads import tracking as ads_tracking  # noqa: E402
from app.orders import channel as orders_channel  # noqa: E402
from app.orders import dispatch as orders_dispatch  # noqa: E402
from app.orders import repository as orders_repo  # noqa: E402

ads_codes.orders_repo = orders_repo
ads_data_onboarding.orders_repo = orders_repo
ads_inflation.orders_repo = orders_repo
ads_reading.orders_repo = orders_repo
ads_reading.orders_channel = orders_channel
ads_routes_mod.orders_channel = orders_channel
ads_routes_mod.orders_dispatch = orders_dispatch
ads_routes_mod.orders_repo = orders_repo
ads_settlement.orders_repo = orders_repo
ads_tracking.orders_channel = orders_channel

# 啟動斷言：確認上面每一格都真的注入了。那幾個模組裡的預設值是 None——少注入一格
# 不會當場報錯，要等到使用者剛好走到那條路徑才炸出一句看不懂的
# 「'NoneType' object has no attribute ...」。這裡當場擋下來，比照清理登記處那道斷言。
_INJECTIONS = (
    ("app.ads.codes.orders_repo", ads_codes.orders_repo),
    ("app.ads.data_onboarding.orders_repo", ads_data_onboarding.orders_repo),
    ("app.ads.inflation.orders_repo", ads_inflation.orders_repo),
    ("app.ads.reading.orders_repo", ads_reading.orders_repo),
    ("app.ads.reading.orders_channel", ads_reading.orders_channel),
    ("app.ads.routes.orders_channel", ads_routes_mod.orders_channel),
    ("app.ads.routes.orders_dispatch", ads_routes_mod.orders_dispatch),
    ("app.ads.routes.orders_repo", ads_routes_mod.orders_repo),
    ("app.ads.settlement.orders_repo", ads_settlement.orders_repo),
    ("app.ads.tracking.orders_channel", ads_tracking.orders_channel),
)
_missing_injections = [name for name, value in _INJECTIONS if value is None]
if _missing_injections:
    raise RuntimeError(f"app.ads → app.orders 依賴注入少了：{_missing_injections}")

# 啟動斷言（第 2 刀「清理登記處」）：確認刪品牌時該連鎖清資料的模組都有登記進
# app.core.cleanup，少一個就不讓服務起來，避免又漏掉誰。
from app.core import cleanup as core_cleanup  # noqa: E402

_REQUIRED_CLEANUP_MODULES = ("品牌智庫", "建檔精靈", "廣告", "訂單", "中斷提醒")
_missing_cleanup = [n for n in _REQUIRED_CLEANUP_MODULES if n not in core_cleanup.registered_names()]
if _missing_cleanup:
    raise RuntimeError(f"清理登記處少登記了：{_missing_cleanup}")


# ---------------------------------------------------------------------------
# 錯誤處理
# ---------------------------------------------------------------------------

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
