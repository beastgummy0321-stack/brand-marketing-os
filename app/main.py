"""app/main.py — 真正的組裝根（修憲落地 A4）：app factory、router 註冊、啟動流程。

原本這裡塞了 87 條品牌智庫業務路由（2426 行），卻頂著「組裝根永久豁免」的身分，
還被 app/ads、app/orders、app/intake 反向 import（main → ads.routes → main 的循環）。
拆成三塊（決策 0037 第 15 條）：

1. 本檔：只留 app factory、保留策略的啟動節奏、router 註冊、錯誤處理。
2. `app/shared/web.py`：conn／templates／ctx／require_brand 等全站共用 web 工具。
3. `app/brand_web/routes.py`：品牌智庫的業務路由本體。

拆完後 app/ads、app/orders、app/intake 一律改 import `app.shared.web`，不再 import
本檔，main → ads.routes → main 的循環自然消失（見 test_no_branch_imports_app_main）。

**例外**（刻意留在這裡，未搬進 brand_intelligence/routes.py，行數因此超過 100 行）：
首頁「今天要處理的事」（`_today_todos`／`/` 首頁）與 AI／Meta／GA4 設定頁——這兩處
直接碰 `app.ads`（讀廣告到期提醒；讀寫 Meta／GA4 連線設定），而 A2 落地的 import
掃描測試（test_architecture_boundaries.py）目前只允許 `app/main.py` 這個路徑 import
分支專屬層，本票不得為了搬移方便去修改那份既有測試。詳見票 A4 回報「Remaining risks」。

ADR 0027 起：連線不再全程共用一條，改成每個 request／背景工作跟連線池借一條
（`app.core.db.connection()`，見本檔最外層那道 HTTP middleware）；`app.shared.web.conn`
是 `coredb.ConnProxy()`，即時轉發到當下綁定的那條。每日備份（sqlite 檔案複製）
在 Postgres 世界沒有意義（Supabase 自己做備份），ADR 0027 決策 5 整個模組退場
（原 `app/core/backup.py`）；這裡只留 llm_task 保留策略清理的啟動節奏。

啟動：python -m uvicorn app.main:app --port 8710
"""

import os
import sys
import threading
import time
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.exception_handlers import http_exception_handler
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException

# ---- .env → 環境變數（必須跑在任何 app.* 被 import 之前，所以擠在 import 中間）----

def _parse_env_file(text: str) -> dict:
    """把 .env 內容解析成 {鍵: 值}。忽略空行、`#` 開頭的註解、以及沒有等號的行；
    值裡面還有等號時只切第一個（base64 金鑰會有）。鍵值兩邊空白去掉，值頭尾成對的
    引號也去掉——貼上來的金鑰常常自帶引號，帶著引號送出去一定認證失敗。"""
    parsed = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key, value = key.strip(), value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
            value = value[1:-1]
        if key:
            parsed[key] = value
    return parsed


def _load_dotenv() -> int:
    """把專案根的 `.env` 灌進環境變數，**已經有值的不覆蓋**（真的環境變數優先）。
    回傳這次實際設進去的筆數。

    為什麼要有這支：原本只有「啟動行銷系統.bat」做這件事，換個方式啟動就悄悄少了金鑰。
    Meta 連線會顯示「還沒連接 Meta 廣告帳戶」，而 AI 金鑰有資料庫備援（見
    `app/core/settings.py` 的優先序）所以照常運作，把問題整個蓋住——2026-08-23 實測
    花了近一小時才定位。設定該由程式自己讀，不該綁在某一種啟動方式上。

    測試中一律跳過：測試程序不該拿到真金鑰，誤打出去要花錢
    （同 `app/tools/real_db_probe.py` 把金鑰換成假值的理由）。
    """
    if "pytest" in sys.modules:
        return 0
    env_path = Path(__file__).resolve().parent.parent / ".env"
    if not env_path.exists():
        return 0
    loaded = 0
    for key, value in _parse_env_file(env_path.read_text(encoding="utf-8-sig")).items():
        if not os.environ.get(key):
            os.environ[key] = value
            loaded += 1
    return loaded


_load_dotenv()

from app.ads import auto_sync as ads_auto_sync  # noqa: E402
from app.ads import (
    ga4_api,  # noqa: E402  # 只用於設定頁測試連線，見「例外」說明
    ga4_sync,  # noqa: E402
    meta_api,  # noqa: E402
)
from app.ads import sync as ads_sync  # noqa: E402
from app.core import creative_assets as corecreative
from app.core import db as coredb
from app.core import retention as core_retention
from app.core import settings as coresettings
from app.llm import pricing as llm_pricing
from app.llm import providers as llm_providers
from app.shared import logging as app_logging
from app.shared import web
from app.shared.web import (
    MODEL_CHOICES,
    _num_str,
    _with_brand_names,
    clean,
    parse_number,
)

# ---------------------------------------------------------------------------
# 啟動流程：llm_task 保留策略清理（修憲落地 A5）
# ---------------------------------------------------------------------------

_last_retention_check: str | None = None  # 記上次檢查過的日期（ISO 字串），llm_task 保留策略清理用（修憲落地 A5）


def _purge_expired_llm_task_content_if_new_day() -> None:
    """跨日才清一次 llm_task 的過期大欄位（修憲落地 A5，見 app/core/retention.py）；
    每個 request 前比一次日期字串（成本極低），只有真的跨日才動手清。"""
    global _last_retention_check
    today = datetime.now(UTC).date().isoformat()
    if today != _last_retention_check:
        core_retention.purge_expired_llm_task_content(web.conn)
        _last_retention_check = today
# ---------------------------------------------------------------------------
# 自動同步（LIVE 每四小時、其餘每日；應用程式啟動時註冊程式內排程）
# ---------------------------------------------------------------------------
_last_auto_sync_check: datetime | None = None
_last_weekly_engine_check: datetime | None = None
_AUTO_SYNC_POLL_SECONDS = 3600  # 每小時檢查是否已到四小時或跨日門檻


def _auto_sync_if_due(now: datetime | None = None) -> None:
    """LIVE 檔期每四小時同步；其餘狀態維持每日一次。"""
    global _last_auto_sync_check
    now = now or datetime.now(UTC)
    has_live = bool(web.conn.execute(
        "SELECT 1 FROM campaign_cycle WHERE status = 'LIVE' AND archived = false LIMIT 1"
    ).fetchone())
    due = (_last_auto_sync_check is None
           or (has_live and now - _last_auto_sync_check >= timedelta(hours=4))
           or (not has_live and now.date() != _last_auto_sync_check.date()))
    if due:
        # 02-3c：餵給業務邏輯的「今天」要轉本機時區再取日期——app/ads、app/orders
        # 全站幾十處預設值都是 date.today()（本機時區）；這裡原本直接用 now.date()
        # （UTC 曆日），本機時區早於 UTC 時（例如台灣 UTC+8 的凌晨）會跟
        # onboarding.create_reminders() 訂出來的 visible_from 差一天，到期提醒
        # （如 final_settlement）晚一天才追上。astimezone() 而不是改叫 date.today()，
        # 是為了保留 now 參數本來就有的可測試性（測試傳固定 now 仍決定得了「今天」）。
        ads_auto_sync.run(web.conn, today=now.astimezone().date().isoformat())
        _last_auto_sync_check = now


def _weekly_engine_if_due(now: datetime | None = None) -> None:
    """每個 ISO 週只跑一次週判讀；process 重啟後會補跑當週。"""
    global _last_weekly_engine_check
    now = now or datetime.now(UTC)
    current_week = now.isocalendar()[:2]
    last_week = _last_weekly_engine_check.isocalendar()[:2] if _last_weekly_engine_check else None
    if last_week != current_week:
        # 02-3c：同 _auto_sync_if_due()，本機時區才是全站「今天」的基準。
        ads_auto_sync.run_weekly_engine(web.conn, today=now.astimezone().date().isoformat())
        _last_weekly_engine_check = now


def _auto_sync_loop() -> None:
    """背景執行緒，每小時檢查同步門檻——用背景執行緒而不是像 llm_task 保留策略那樣掛在
    每個 HTTP 請求的 middleware，是因為自動同步會打外部 API：絕不能讓它被測試的
    TestClient 請求意外觸發。這個迴圈只掛在 FastAPI `startup` 事件底下才會啟動，而
    `TestClient(app)`（不用 `with` context manager，這個 repo 目前所有測試都是這樣用）
    不會觸發 startup 事件——測試因此永遠碰不到這條路徑，見
    app/tests/test_ads_auto_sync.py 檔頭驗證過的行為。

    ADR 0027：背景執行緒不在任何 request 裡，沒有 middleware 幫忙借連線，body 自己
    包一層 `with coredb.connection():`（procrastinate 在切片 ⑤ 取代這整個執行緒）。"""
    while True:
        time.sleep(_AUTO_SYNC_POLL_SECONDS)
        with coredb.connection():
            _auto_sync_if_due()
            _weekly_engine_if_due()


# ---------------------------------------------------------------------------
# FastAPI app
# ---------------------------------------------------------------------------

app_logging.install()  # 票 03-1 附錄 A：JSON formatter + request_id/user_id/org_id filter

app = FastAPI(title="行銷作業系統（Phase 0 Mock UI）")

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
    小時），之後交給背景執行緒每小時檢查四小時／每日門檻。

    票 F6：這次補跑常常是「機器關了一陣子、開機馬上要追上進度」那一下，外部 API／
    資料庫都比平常更容易撞到暫時性錯誤。補跑本身丟例外不能讓這支 FastAPI startup
    handler 跟著炸——那等於開機直接失敗，比「晚一點才結算」嚴重得多（集裝箱憲章
    第 5 節：錯誤不穿牆）。背景執行緒仍要照常掛上去，下一個整點會再檢查一次。

    ADR 0027：這支 startup handler 跑在任何 HTTP request 之外，沒有 middleware
    幫忙借連線，自己包一層 `with coredb.connection():`。"""
    with coredb.connection():
        try:
            _auto_sync_if_due()
        except Exception:  # noqa: BLE001 — 開機補跑失敗不能把整個 app 帶垮，見上方說明
            web.conn.rollback()
        _weekly_engine_if_due()
    threading.Thread(target=_auto_sync_loop, daemon=True).start()


@app.middleware("http")
async def _db_connection_middleware(request: Request, call_next):
    """ADR 0027：每個 request 從連線池借一條連線，掛在這個 request 的 contextvar 上
    （`app.core.db.connection()`——乾淨結束 commit、例外 rollback、結束一律歸還連線池）。
    整條 middleware 鏈只有這一個，天然是最外層，request 進來第一件事就是借好連線，
    路由與其他邏輯全程透過 `web.conn`（`ConnProxy`）拿到同一條。

    順帶補一次「今天清過 llm_task 過期大欄位了嗎」（修憲落地 A5；原本掛在已退場的
    每日備份 middleware——備份是複製 sqlite 檔案，Postgres 世界沒有意義，ADR 0027
    決策 5 整個模組退場，見 docs/adr/0027）。

    票 03-1 附錄 A：順便產生這個 request 的 request_id（uuid4），存進 logging 的
    contextvar、也回傳成 `X-Request-Id` header；user_id／org_id 由 `require_actor()`
    在拿到 `ActorContext` 後補上（見 app/shared/web.py）。
    """
    request_id = str(uuid.uuid4())
    app_logging.set_request_id(request_id)
    with coredb.connection():
        _purge_expired_llm_task_content_if_new_day()
        response = await call_next(request)
    response.headers["X-Request-Id"] = request_id
    return response


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
async def brand_overview(brand: str | None = None):
    destination = f"/app/brands/{brand}" if brand else "/app/"
    return RedirectResponse(destination, status_code=303)


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


def _masked_key(key: str | None) -> str | None:
    """金鑰遮罩：只露開頭的 sk- 與末四碼，畫面永不顯示完整金鑰（07 §1 規則 5）。"""
    if not key:
        return None
    if len(key) < 8:
        return "…"
    prefix = "sk-" if key.startswith("sk-") else ""
    return f"{prefix}…{key[-4:]}"


# ---------------------------------------------------------------------------
# 設定頁寫入邏輯（純函式，回傳錯誤人話訊息／None＝成功）：下方 JSON API 唯一呼叫者
# （HTML 表單路由已刪除，見票 T4 A4；不為了 JSON 契約重寫第二份寫入邏輯，票 B1-settings）。
# ---------------------------------------------------------------------------

def _write_api_key(api_key: str) -> str | None:
    key = clean(api_key)
    if not key:
        return "請貼上 AI 金鑰。"
    coresettings.set_setting(web.conn, coresettings.API_KEY_SETTING, key)
    return None


def _write_meta_settings(account_id: str, token: str) -> str | None:
    account = clean(account_id)
    token_c = clean(token)
    if not account:
        return "請填入廣告帳號編號。"
    coresettings.set_setting(web.conn, ads_sync.ACCOUNT_SETTING, account)
    if token_c:
        coresettings.set_setting(web.conn, ads_sync.TOKEN_SETTING, token_c)
    return None


def _write_ga4_settings(property_id: str, service_account_json: str) -> str | None:
    property_id_c = clean(property_id)
    key_json = (service_account_json or "").strip()
    if not property_id_c:
        return "請填入 GA4 資源編號。"
    coresettings.set_setting(web.conn, ga4_sync.PROPERTY_SETTING, property_id_c)
    if key_json:
        coresettings.set_setting(web.conn, ga4_sync.SERVICE_ACCOUNT_SETTING, key_json)
    return None


def _write_model(llm_model: str) -> str | None:
    labels = {m_id: name for m_id, name in MODEL_CHOICES}
    if llm_model not in labels:
        return "請從選單中選一個模型。"
    coresettings.set_setting(web.conn, coresettings.LLM_MODEL_SETTING, llm_model)
    return None


def _write_budget(raw_budget) -> str | None:
    """raw_budget 接受字串（表單）或數字（JSON）——先轉字串再走既有 parse_number，
    驗證規則只寫一份。"""
    raw = "" if raw_budget is None else str(raw_budget)
    value, ok = parse_number(raw)
    if not ok or value is None or value <= 0:
        return "花費上限請填大於 0 的數字，例如 30。"
    coresettings.set_setting(web.conn, coresettings.INTAKE_BUDGET_SETTING, _num_str(value))
    return None


def _write_creative_root(raw_root: str) -> str | None:
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
    today = datetime.now(UTC).date().isoformat()
    try:
        ga4_sync.make_client(web.conn).fetch_source_medium(today, today)
    except ga4_api.GA4ApiError as exc:
        return str(exc), "danger"
    except Exception:
        return "測試失敗：系統發生問題，請再試一次。", "danger"
    return "連線正常：可以讀到 GA4 網站數據。", "ok"


# ---------------------------------------------------------------------------
# 設定頁 JSON API（票 B1-settings，契約 `.scratch/grill/GRILL-B1-settings.md` S15）。
# 讀值與寫入邏輯全部重用上面既有函式，這裡只做「解析請求 → 呼叫 → 組 JSON」的薄層
# （HTML 表單路由已刪除，見票 T4 A4；React /settings 頁只打這批 /api/settings/*）。
# 規則卡（S15.29–S15.33）另掛在 app/ads/routes_settings.py 同模組。
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
    return {"data": _settings_json_data(), "generated_at": datetime.now(UTC).isoformat()}


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

from app import ads as ads_module  # noqa: E402
from app import brand_web as brand_web_module  # noqa: E402
from app import dashboard as dashboard_module  # noqa: E402
from app import identity as identity_module  # noqa: E402
from app import intake as intake_module  # noqa: E402
from app import orders as orders_module  # noqa: E402

# 票 03-1：每個模組的路由掛載交給它自己的 register(app)（機械式：路由本身不變，
# 只是把 main.py 逐條 include_router 收斂成一個迴圈）。identity 排最後——它的
# register() 會在 IDENTITY_DEV_TOKEN 設定錯誤時 raise，讓這種設定錯誤盡早炸在啟動
# 階段，而不是等到第一個請求才發現。
for _module in (ads_module, brand_web_module, intake_module, orders_module,
                 dashboard_module, identity_module):
    _module.register(app)

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

def _error_page(message: str) -> str:
    """404／500 錯誤頁：新殼（React /app）接管畫面後，這兩頁只有真正走漏網之魚的
    後端路徑或非 /api 的裸連結才會看到，不值得一整套 Jinja2Templates（票 T4 A4）。
    純內嵌字串比一個只有兩個呼叫點的 template 檔好找、好維護。"""
    return (
        "<!doctype html><html><head><meta charset=\"utf-8\"><title>行銷作業系統</title></head>"
        "<body style=\"font-family:sans-serif;text-align:center;padding:4rem 1rem;\">"
        f"<p>{message}</p><p><a href=\"/app/\">回首頁</a></p>"
        "</body></html>"
    )


@app.exception_handler(web.ApiError)
async def handle_api_error(request: Request, exc: web.ApiError):
    """票 03-1 附錄 A：新路由（目前是 app.identity）統一用這個信封回應——既有路由的
    HTTPException 走下面 handle_http_exception，兩邊互不影響。"""
    return JSONResponse(
        {"error": {"code": exc.code, "message": exc.message, "details": exc.details}},
        status_code=exc.status,
    )


@app.exception_handler(StarletteHTTPException)
async def handle_http_exception(request: Request, exc: StarletteHTTPException):
    if exc.status_code == 404:
        kind = exc.detail if isinstance(exc.detail, str) and exc.detail not in ("Not Found",) else "頁面"
        # /api 一律回 JSON：新殼 fetch 拿到 HTML 會炸在 res.json()，使用者看到的是解析錯誤
        # 而不是人話。修在這個共用出口，不必逐支端點包 try/except。
        if request.url.path.startswith("/api/"):
            return JSONResponse({"detail": f"找不到{kind}"}, status_code=404)
        return HTMLResponse(_error_page("找不到這一頁。"), status_code=404)
    return await http_exception_handler(request, exc)


@app.exception_handler(Exception)
async def handle_unexpected_exception(request: Request, exc: Exception):
    return HTMLResponse(_error_page("系統出了點狀況，再試一次。"), status_code=500)


# ---------------------------------------------------------------------------
# 回溯相容：讓 `app.main.conn`／`.templates`／`.MODEL_CHOICES` 等既有測試直接讀的屬性
# 繼續解析——這些名字現在真正定義在 app.shared.web（conn 是 ConnProxy，必須即時
# 代理查值，不能在這裡靜態 import 一次就固定住）。
# ---------------------------------------------------------------------------

def __getattr__(name):
    return getattr(web, name)
