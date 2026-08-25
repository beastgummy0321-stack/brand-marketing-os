# -*- coding: utf-8 -*-
"""app/ads/meta_mcp.py — Meta 官方 Ads MCP：建廣告（暫停）＋發布（票 M1-01，ADR 0023）。

進入點（其餘檔案只能 import 這支，不得直接打 MCP 或 Graph API）：
- `connect(conn)`：連線狀態＋這個帳號開不開放自動建廣告。
- `list_pages(conn)`：這個廣告帳號底下能選的粉絲專頁（設定中心用）。
- `get_page_id()` / `save_page_id(page_id)`：選定的粉絲專頁，存在 `.env`（不進 DB）。
- `create_package(conn, brand_id, cycle_id, package_id, *, actor)`：把一份交接包建成
  Meta 活動／廣告組合／素材／廣告，全部暫停；成功後呼叫既有 `handoff.authorize_and_map()`
  （`go_live=False`）寫 `external_ad_mapping`，不另寫 INSERT——這時候還沒開始花錢
  （ADR 0019 第 7 條），不建投放授權、不切檔期 LIVE、不建提醒卡。
- `activate_cycle(conn, brand_id, cycle_id, *, actor)`：把這期已建好的包從暫停切成開啟；
  每一包 Meta 端真的切成開啟成功後，才呼叫既有 `handoff.go_live()` 建投放授權＋切 LIVE＋
  建提醒卡——花錢那一刻是這裡，不是 `create_package()`。
- `ads_manager_url(meta_account_id)`：Meta 廣告管理員連結（前端「到後台看」用）。

憑證只認 `.env` 三把鑰匙（`META_MCP_TOKEN`／`META_AD_ACCOUNT_ID`／`META_PAGE_ID`），跟
`app/ads/meta_api.py` 一樣用 `os.environ.get()`，不落地在 DB——DB 會跟著每日備份同步出去
（比照 `app/core/settings.py` 金鑰優先序的理由）。

Transport（票面「實連結果」，已用 curl 實連驗證，取代最初「一定要先 list_tools」的假設）：
純 HTTP POST `https://mcp.facebook.com/ads`，`Authorization: Bearer <token>`，
`Accept: application/json, text/event-stream`，不需要 initialize 交握，也不需要 `mcp`
套件——回應是 SSE 文字，`data: {...}` 那一行就是 JSON-RPC 回覆。所有工具的參數名稱一律照
`.scratch/m1/reports/tools.json`，不得另編。

安全邊界：本檔只建暫停的物件、只在明確呼叫 `activate_cycle()` 時才切成開啟——扣板機的是人
（鐵則 4）。對外呼叫一律包 try，錯誤轉白話後回 `{"ok": false}`，不拋例外穿牆。
"""

import base64
import json
import os
from pathlib import Path
from typing import Optional

from app.ads import creative as ads_creative
from app.ads import handoff as ads_handoff
from app.ads import meta_api
from app.ads import repository as ads_repo
from app.ads import theme_engine
from app.ads import theme_repository as theme_repo
from app.core import creative_assets
from app.core import orchestrator as core_orchestrator
from app.core.db import REPO_ROOT

MCP_URL = "https://mcp.facebook.com/ads"
TOKEN_ENV_VAR = "META_MCP_TOKEN"
ACCOUNT_ID_ENV_VAR = "META_AD_ACCOUNT_ID"
PAGE_ID_ENV_VAR = "META_PAGE_ID"

# .env 路徑：模組層常數，測試整包換成暫存檔（比照 theme_engine.PROVIDER 的測試慣例），
# 不會動到真正的專案根 .env。
ENV_PATH = REPO_ROOT / ".env"

_TOOLS_USED = (
    "ads_get_ad_accounts", "ads_get_ad_account_pages", "ads_create_campaign",
    "ads_create_creative", "ads_create_ad", "ads_activate_entity", "ads_get_datasets",
)
# 廣告組合已改走 Graph API 直打（見 graph_post()／_create_adset()）——Ads MCP 的
# ads_create_ad_set 沒有 regional_* 參數（tools.json 查證），Meta 會拒絕鎖定台灣的組合。
# 不再列進 _TOOLS_USED，connect() 回報的工具清單才誠實。

NOT_CONNECTED_REASON = "還沒連接 Meta 廣告帳戶"

# 金額單位：Meta 的預算欄位以「該幣別的最小單位」計價，多數幣別是分（要乘 100），
# 台幣不是——原始值就是元。2026-08-23 真帳戶查證三個獨立證據：後台把原始值 214286
# 顯示成 NT$214,286；帳戶裡真人建的活動原始值是 2000／500／1900（當成分就是
# NT$20／5／19，低於最低日預算）；`ads_get_ad_accounts` 回的 min_daily_budget_cents
# 是 33（NT$33 合理，NT$0.33 不合理）。
# 這張表只收「實測查證過」的幣別。猜錯一位數就是 100 倍的錢，所以沒查證過的一律擋下，
# 不給預設值——寧可建不出來，也不要默默送出 100 倍的預算。
CURRENCY_MINOR_UNIT_FACTOR = {"TWD": 1}
UNVERIFIED_CURRENCY_REASON = (
    "這個廣告帳戶的幣別（{currency}）還沒有查證過金額單位，為了避免送錯 100 倍的預算，"
    "系統不會替你建立廣告。")
DISABLED_FALLBACK_REASON = "Meta 目前沒開放這個帳戶使用自動建廣告"

IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp"}

# 目標／出價／受眾預設（票面「實連結果」）：package 沒有的欄位，程式給固定值，不問 LLM、
# 不進畫面。像素（Pixel）用 ads_get_datasets 現查：有就帶 promoted_object 走轉換目標，
# 沒有退成 LINK_CLICKS（真人實測：Meta 對 OFFSITE_CONVERSIONS 一定要 promoted_object）。
# ponytail: 多個像素時取最近有開火的那個；要讓使用者自己選，之後再進設定中心。
DEFAULT_OBJECTIVE = "OUTCOME_SALES"
DEFAULT_BUYING_TYPE = "AUCTION"
DEFAULT_BILLING_EVENT = "IMPRESSIONS"
DEFAULT_OPTIMIZATION_GOAL = "OFFSITE_CONVERSIONS"
FALLBACK_OPTIMIZATION_GOAL = "LINK_CLICKS"  # 帳戶沒有像素時
DEFAULT_TARGETING = {"geo_locations": {"countries": ["TW"]}, "age_min": 18}
DEFAULT_CALL_TO_ACTION = "SHOP_NOW"

# 台灣廣告主身分驗證（真人實測發現，2026-08-23）：GET /act_{id}/adsets 查證，帳戶底下
# 每個既有廣告組合都帶 regional_regulated_categories=["TAIWAN_UNIVERSAL"] 與
# regional_regulation_identities（受益人／付款人 ID）——Meta 對鎖定台灣的廣告組合強制
# 要求這兩個欄位，Ads MCP 的 ads_create_ad_set 完全沒有對應參數（tools.json 查證），
# 新建組合一律會被拒絕。官方文件（廣告組合欄位參考）：
# https://developers.facebook.com/docs/marketing-api/reference/ad-campaign/
TAIWAN_IDENTITY_ENV_VAR = "META_TW_IDENTITY_ID"
TAIWAN_REGULATED_CATEGORIES = ["TAIWAN_UNIVERSAL"]
TAIWAN_IDENTITY_MISSING_REASON = (
    "這個帳戶還沒有台灣廣告主身分驗證（受益人／付款人），先在 Meta 廣告管理員手動建一個"
    "鎖定台灣的廣告組合完成驗證，系統之後會沿用。"
)
_TW_IDENTITY_CACHE: dict = {}  # account_id -> identity_id or None，行程層快取


class MetaMcpError(Exception):
    """跟 Meta MCP／Graph API 往來時的內部錯誤，對外一律經 `_plain_error()` 轉白話。"""


def _plain_error(exc: Exception) -> str:
    text = _meta_message(str(exc).strip())
    if "190" in text or "OAuthException" in text:
        return "Meta 金鑰過期了，到設定中心重新貼一張"
    return text or "連不上 Meta，稍後再試一次。"


# ---------------------------------------------------------------------------
# 唯一的 MCP 呼叫函式：測試 monkeypatch 這支（`meta_mcp._client`）。
# ---------------------------------------------------------------------------

ADVERTISER_REQUEST = "在品牌行銷作業系統按「一鍵建到 Meta（暫停）」／「發布全部」"
_CONVERSATION = {"id": None}


def _conversation_id() -> str:
    """一個伺服器行程共用一組 20 字元追蹤碼（A-Z a-z 0-9）；ponytail: 每次 create-all 換一組
    更貼近「一段對話」，但工具只要求格式與一致性，先一行解決。"""
    if not _CONVERSATION["id"]:
        import secrets, string
        alphabet = string.ascii_letters + string.digits
        _CONVERSATION["id"] = "".join(secrets.choice(alphabet) for _ in range(20))
    return _CONVERSATION["id"]


def _client(name: str, arguments: dict) -> dict:
    token = os.environ.get(TOKEN_ENV_VAR, "").strip()
    if not token:
        raise MetaMcpError("還沒有設定 META_MCP_TOKEN")
    import httpx  # 延遲 import，比照 meta_api.py 的既有慣例

    # 工具說明明文要求每次呼叫都帶 client_conversation_id（20 字元、同一輪作業共用）
    # 與 advertiser_request（使用者原話）；兩個都是追蹤用，缺了會被當成不合規呼叫。
    arguments = {"client_conversation_id": _conversation_id(),
                 "advertiser_request": ADVERTISER_REQUEST, **arguments}
    payload = {"jsonrpc": "2.0", "method": "tools/call", "id": 1,
               "params": {"name": name, "arguments": arguments}}
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json",
               "Accept": "application/json, text/event-stream"}
    try:
        response = httpx.post(MCP_URL, json=payload, headers=headers, timeout=60.0)
    except Exception:
        raise MetaMcpError("連不上 Meta，可能是網路問題。")
    if response.status_code >= 400:
        raise MetaMcpError(f"Meta 回了 {response.status_code}：{response.text[:200]}")

    data = _parse_response(response.text)
    if data is None:
        raise MetaMcpError("Meta 的回覆讀不出來。")
    if data.get("error"):
        error = data["error"]
        raise MetaMcpError(str((error or {}).get("message") or error))

    result = data.get("result") or {}
    if result.get("isError"):
        raise MetaMcpError(_extract_text(result) or "Meta 回了一個錯誤")
    structured = result.get("structuredContent")
    if isinstance(structured, dict):
        return structured
    text = _extract_text(result)
    if text:
        try:
            parsed = json.loads(text)
        except ValueError:
            parsed = None
        if isinstance(parsed, dict):
            return parsed
    return {}


def _parse_response(text: str) -> Optional[dict]:
    """回應可能是純 JSON，也可能是 SSE（`data: {...}` 那一行）——兩種都認。"""
    text = (text or "").strip()
    if not text:
        return None
    try:
        return json.loads(text)
    except ValueError:
        pass
    for line in text.splitlines():
        line = line.strip()
        if not line.startswith("data:"):
            continue
        payload = line[len("data:"):].strip()
        if not payload:
            continue
        try:
            return json.loads(payload)
        except ValueError:
            continue
    return None


def _extract_text(result: dict) -> str:
    parts = [str(item.get("text") or "") for item in (result.get("content") or [])
             if isinstance(item, dict) and item.get("type") == "text"]
    return "\n".join(p for p in parts if p)


def _raise_if_tool_error(result: dict) -> None:
    """ads_create_* 系列成功時走 JSON-RPC 成功，失敗時把原因放在自己的
    error_message／error_category 欄位裡（見 tools.json outputSchema），不是協定層錯誤。"""
    message = result.get("error_message")
    if message:
        raise MetaMcpError(_meta_message(str(message)))


def _meta_message(text: str) -> str:
    """工具有時把整包 {"error_category":..,"error_message":..} 當字串回來；只留人看得懂的那句。"""
    try:
        data = json.loads(text)
    except ValueError:
        return text
    return str(data.get("error_message") or text) if isinstance(data, dict) else text


# ---------------------------------------------------------------------------
# 唯一的 Graph API 寫入呼叫（測試 monkeypatch 這支，跟 `_client` 同等地位）：
# Ads MCP 沒有涵蓋的欄位（廣告組合的台灣法規欄位、圖片直傳）改直打 Graph API，同一把
# `META_MCP_TOKEN`（跟既有 `meta_api.py` 唯讀客戶端同一套 access_token 概念）。
# ---------------------------------------------------------------------------

def graph_post(path: str, data: dict) -> dict:
    """`path` 是相對路徑（例如 `act_123/adsets`），不含網域／版本。"""
    token = os.environ.get(TOKEN_ENV_VAR, "").strip()
    if not token:
        raise MetaMcpError("還沒有設定 META_MCP_TOKEN")
    import httpx  # 延遲 import，比照 meta_api.py 的既有慣例

    try:
        response = httpx.post(
            f"https://graph.facebook.com/{meta_api.API_VERSION}/{path}",
            data={**data, "access_token": token}, timeout=60.0,
        )
    except Exception:
        raise MetaMcpError("連不上 Meta，可能是網路問題。")
    try:
        payload = response.json()
    except ValueError:
        raise MetaMcpError("Meta 的回覆讀不出來。")
    if isinstance(payload, dict) and payload.get("error"):
        error = payload["error"] or {}
        raise MetaMcpError(str(error.get("error_user_msg") or error.get("message")
                               or f"Meta 回了 {response.status_code}"))
    if response.status_code >= 400:
        raise MetaMcpError(f"Meta 回了 {response.status_code}。")
    return payload


def budget_in_minor_units(amount: Optional[float], currency: Optional[str]) -> int:
    """把「元」換算成 Meta 預算欄位要的單位。查證過的幣別才換算，其餘一律拋
    `MetaMcpError`——見 `CURRENCY_MINOR_UNIT_FACTOR` 的註解。"""
    factor = CURRENCY_MINOR_UNIT_FACTOR.get((currency or "").strip().upper())
    if factor is None:
        raise MetaMcpError(UNVERIFIED_CURRENCY_REASON.format(currency=currency or "未知"))
    return int(round((amount or 0) * factor))


_CURRENCY_CACHE: dict = {}


def _account_currency(account_id: str) -> Optional[str]:
    """這個廣告帳戶的幣別。`ads_get_ad_accounts` 本來就會回 currency，不另外打 Graph。"""
    if account_id in _CURRENCY_CACHE:
        return _CURRENCY_CACHE[account_id]
    result = _client("ads_get_ad_accounts", {})
    currency = None
    for account in result.get("ad_accounts") or []:
        if account.get("ad_account_id") == account_id:
            currency = account.get("currency")
            break
    _CURRENCY_CACHE[account_id] = currency
    return currency


# ---------------------------------------------------------------------------
# 憑證存取：token／帳號 ID 只認環境變數；粉絲專頁另外可由設定中心寫回 .env。
# ---------------------------------------------------------------------------

def _raw_account_id() -> str:
    """回傳不帶 act_ 前綴的數字帳號 ID（MCP 工具要的格式）；使用者填 .env 時貼了
    act_ 前綴也認得。"""
    raw = os.environ.get(ACCOUNT_ID_ENV_VAR, "").strip()
    return raw[4:] if raw.startswith("act_") else raw


# 公開別名（票 Q1-01）：qa_autocheck.py 要打同一支 transport／讀同一個帳號 ID／
# 轉同一套白話錯誤訊息，跨模組呼叫一律走公開函式，不直接碰底線開頭的私有名稱
# （比照 app/ads/checklist.py:144 的 `pixel_anomaly = _pixel_anomaly` 先例）。
call_tool = _client
raw_account_id = _raw_account_id
plain_error = _plain_error


def get_page_id() -> Optional[str]:
    return os.environ.get(PAGE_ID_ENV_VAR, "").strip() or None


def save_page_id(page_id: str) -> None:
    """存進 .env（單機單人，不進 DB）＋當場更新目前 process 的環境變數，
    不必重啟服務就生效。ponytail: 沒有選檔案鎖，寫入視窗極短、單人使用衝突機率可忽略，
    真的出問題再加鎖。"""
    page_id = (page_id or "").strip()
    if not page_id:
        raise ValueError("請選一個粉絲專頁。")
    _write_env_var(PAGE_ID_ENV_VAR, page_id)
    os.environ[PAGE_ID_ENV_VAR] = page_id


def _write_env_var(key: str, value: str) -> None:
    lines = ENV_PATH.read_text(encoding="utf-8").splitlines() if ENV_PATH.exists() else []
    out, found = [], False
    prefix = f"{key}="
    for line in lines:
        if line.strip().startswith(prefix):
            out.append(f"{key}={value}")
            found = True
        else:
            out.append(line)
    if not found:
        out.append(f"{key}={value}")
    ENV_PATH.write_text("\n".join(out) + "\n", encoding="utf-8")


# ---------------------------------------------------------------------------
# 連線狀態
# ---------------------------------------------------------------------------

def connect(conn) -> dict:
    """`conn` 目前沒用到（憑證只走環境變數），留著是跟其餘進入點同一種簽章，
    之後真要併品牌層設定時不必改介面。"""
    token = os.environ.get(TOKEN_ENV_VAR, "").strip()
    account_id = _raw_account_id()
    if not token or not account_id:
        return {"ok": False, "reason": NOT_CONNECTED_REASON}
    try:
        result = _client("ads_get_ad_accounts", {})
    except Exception as exc:  # noqa: BLE001 — 對外呼叫一律不穿牆，測試用假 client 拋的
        # 未必是 MetaMcpError（票二 1(d)），一律接住轉白話。
        return {"ok": False, "reason": _plain_error(exc)}
    account = next(
        (a for a in (result.get("ad_accounts") or []) if a.get("ad_account_id") == account_id),
        None)
    if account is None:
        return {"ok": False,
                "reason": "在這組金鑰底下找不到 META_AD_ACCOUNT_ID 這個帳號，請確認填對了。"}
    if not account.get("is_ads_mcp_enabled"):
        return {"ok": False,
                "reason": account.get("is_ads_mcp_disabled_reason") or DISABLED_FALLBACK_REASON}
    return {"ok": True, "account_id": f"act_{account_id}", "tools": list(_TOOLS_USED)}


def list_pages(conn) -> dict:
    status = connect(conn)
    if not status["ok"]:
        return status
    try:
        result = _client("ads_get_ad_account_pages", {"ad_account_id": _raw_account_id()})
    except Exception as exc:  # noqa: BLE001 — 同 connect()：一律接住轉白話。
        return {"ok": False, "reason": _plain_error(exc)}
    pages = [{"page_id": p.get("page_id"), "page_name": p.get("page_name")}
             for p in (result.get("pages") or [])]
    return {"ok": True, "pages": pages}


def ads_manager_url(meta_account_id: str) -> str:
    account_id = (meta_account_id or "").strip()
    if account_id.startswith("act_"):
        account_id = account_id[4:]
    return f"https://adsmanager.facebook.com/adsmanager/manage/campaigns?act={account_id}"


# ---------------------------------------------------------------------------
# 圖片：主題資料夾（決策 0008：圖不進系統）取第一張 —— 沿用既有路徑規則
# app/ads/theme_engine.theme_folder_name() ＋ app/core/creative_assets.theme_dir()。
# ---------------------------------------------------------------------------

def _first_image_path(conn, brand_id: str, experiment_cell_id: Optional[str]) -> Optional[Path]:
    if not experiment_cell_id:
        return None
    themes = [t for t in theme_repo.list_themes_for_cell(conn, brand_id, experiment_cell_id)
              if t["status"] == "adopted"]
    for theme in themes:
        folder = creative_assets.theme_dir(
            conn, brand_id, theme["campaign_cycle_id"], theme_engine.theme_folder_name(theme))
        if not folder.is_dir():
            continue
        images = sorted(p for p in folder.iterdir()
                        if p.is_file() and p.suffix.lower() in IMAGE_EXTENSIONS)
        if images:
            return images[0]
    return None


def _upload_image(account_id: str, image_path: Path) -> str:
    """圖片直傳 Marketing API——Ads MCP 的 `ads_creative_upload_image` 只吃公開網址，
    `ads_creative_upload_local_image` 要走 Upload Service 多步握手，本票改用同一把
    token 打 Marketing API（官方文件，2026-08-23 WebFetch 確認）：
    https://developers.facebook.com/docs/marketing-api/reference/ad-account/adimages/
    文件記載的參數是 `bytes`（Base64 字串），不是 multipart 檔案欄位；回應形狀
    `images.{key}.hash`，這裡不假設 key 名稱，直接取第一筆有 hash 的值。走
    `graph_post()`——跟廣告組合共用同一個 Graph API 寫入邊界，錯誤訊息一致。
    """
    encoded = base64.b64encode(image_path.read_bytes()).decode("ascii")
    payload = graph_post(f"act_{account_id}/adimages", {"bytes": encoded})
    for entry in (payload.get("images") or {}).values():
        if isinstance(entry, dict) and entry.get("hash"):
            return entry["hash"]
    raise MetaMcpError("圖片上傳失敗：Meta 沒有回傳圖片雜湊值。")


def _variant_text(conn, brand_id: str, variant_id: Optional[str]) -> Optional[str]:
    if not variant_id:
        return None
    variant = ads_creative.get_variant(conn, brand_id, variant_id)
    return variant["content"] if variant else None


# ---------------------------------------------------------------------------
# 建廣告（全部暫停）
# ---------------------------------------------------------------------------

def _ensure_campaign(conn, brand_id: str, cycle_id: str, account_id: str, package: dict) -> str:
    """同一期的包共用同一個 Meta campaign：第一包建、其餘沿用（以 campaign_name 為準，
    build_names() 本來就一檔期一活動名）。"""
    row = conn.execute(
        "SELECT meta_campaign_id FROM external_ad_mapping WHERE brand_id = %s"
        " AND campaign_cycle_id = %s AND meta_campaign_id IS NOT NULL AND meta_campaign_id != ''"
        " AND claim_status = 'confirmed' AND meta_adset_id IS NOT NULL"  # 同步「猜的」列不算（真人實測：tracking.py 把發現的活動掛到第一包）
        " ORDER BY created_at LIMIT 1", (brand_id, cycle_id),
    ).fetchone()
    if row:
        return row["meta_campaign_id"]
    result = _client("ads_create_campaign", {
        "ad_account_id": account_id, "campaign_name": package["campaign_name"],
        "objective": DEFAULT_OBJECTIVE, "buying_type": DEFAULT_BUYING_TYPE,
    })
    _raise_if_tool_error(result)
    campaign_id = result.get("campaign_id")
    if not campaign_id:
        raise MetaMcpError("Meta 沒有回傳行銷活動 ID")
    return campaign_id


def _create_creative(conn, brand_id: str, account_id: str, page_id: str,
                     image_hash: str, package: dict) -> str:
    utm = json.loads(package["utm_json"] or "{}")
    # 呼叫端（create_package）preflight 已經擋掉空到達網址的包，這裡一律帶 link_url——
    # 真人實測發現 Meta 對圖片廣告缺這個欄位是直接拒絕，不是可選。
    destination = package["destination_url"] or ""
    link_url = f"{destination}{'&' if '?' in destination else '?'}{ads_handoff.utm_query(utm)}"
    args = {"ad_account_id": account_id, "page_id": page_id, "image_hash": image_hash,
            "name": package["ad_name"], "link_url": link_url,
            "call_to_action_type": DEFAULT_CALL_TO_ACTION}
    headline = _variant_text(conn, brand_id, package["hook_id"])
    if headline:
        args["headline"] = headline
    message = _variant_text(conn, brand_id, package["copy_variant_id"])
    if message:
        args["message"] = message

    result = _client("ads_create_creative", args)
    _raise_if_tool_error(result)
    creative_id = result.get("creative_id")
    if not creative_id:
        raise MetaMcpError("Meta 沒有回傳素材 ID")
    return creative_id


def _pick_pixel(account_id: str) -> Optional[str]:
    """帳戶的像素：取啟用中、最近有開火的那個；沒有回 None（呼叫端退 LINK_CLICKS）。"""
    result = _client("ads_get_datasets", {"ad_account_id": account_id})
    seen, active = set(), []
    for d in result.get("datasets") or []:
        if d.get("dataset_id") and d.get("is_active") and d["dataset_id"] not in seen:
            seen.add(d["dataset_id"])
            active.append(d)
    if not active:
        return None
    active.sort(key=lambda d: str(d.get("last_fired_time") or ""), reverse=True)
    return str(active[0]["dataset_id"])


def _lookup_taiwan_identity(account_id: str) -> Optional[str]:
    """GET 帳戶既有廣告組合，抓第一個台灣通用受益人身分 ID——新建組合一律沿用同一個
    （已經驗證過的）身分，不猜、不自己造一個。查不到／連不上都回 None，呼叫端擋下。"""
    token = os.environ.get(TOKEN_ENV_VAR, "").strip()
    if not token:
        return None
    import httpx  # 延遲 import，比照既有慣例

    try:
        response = httpx.get(
            f"https://graph.facebook.com/{meta_api.API_VERSION}/act_{account_id}/adsets",
            params={"fields": "regional_regulation_identities", "limit": 25,
                    "access_token": token}, timeout=30.0,
        )
        payload = response.json()
    except Exception:
        return None
    for row in (payload.get("data") or []):
        identities = row.get("regional_regulation_identities") or {}
        beneficiary = identities.get("taiwan_universal_beneficiary")
        if beneficiary:
            return str(beneficiary)
    return None


def _taiwan_identity(account_id: str) -> Optional[str]:
    """`META_TW_IDENTITY_ID` 環境變數優先（每次都現讀，不快取，設定變更立刻生效）；
    沒設就查帳戶既有廣告組合，查過的結果快取在行程記憶體（`_TW_IDENTITY_CACHE`）——
    同一次 create-all 建好幾包，不必每包都打一次 Graph API。"""
    env_id = os.environ.get(TAIWAN_IDENTITY_ENV_VAR, "").strip()
    if env_id:
        return env_id
    if account_id in _TW_IDENTITY_CACHE:
        return _TW_IDENTITY_CACHE[account_id]
    identity_id = _lookup_taiwan_identity(account_id)
    _TW_IDENTITY_CACHE[account_id] = identity_id
    return identity_id


def _create_adset(conn, brand_id: str, cycle_id: str, account_id: str,
                  campaign_id: str, package: dict, *, identity_id: str) -> str:
    """走 Graph API 直打（`graph_post()`），不是 Ads MCP——`ads_create_ad_set` 沒有
    `regional_*` 參數（tools.json 查證），鎖定台灣一定會被拒絕（見模組頭常數註解）。"""
    cycle = ads_repo.get_cycle(conn, brand_id, cycle_id)
    data = {
        "name": package["adset_name"], "campaign_id": campaign_id, "status": "PAUSED",
        "billing_event": DEFAULT_BILLING_EVENT,
        "targeting": json.dumps(DEFAULT_TARGETING, ensure_ascii=False),
        "daily_budget": budget_in_minor_units(package["daily_budget"],
                                              _account_currency(account_id)),
        "destination_type": "WEBSITE",
        "bid_strategy": "LOWEST_COST_WITHOUT_CAP",  # validate_only 實測：沒明示會被拒「必須提供出價金額或限制」
        "regional_regulated_categories": json.dumps(TAIWAN_REGULATED_CATEGORIES),
        "regional_regulation_identities": json.dumps({
            "taiwan_universal_beneficiary": identity_id, "taiwan_universal_payer": identity_id,
        }),
    }
    pixel_id = _pick_pixel(account_id)
    if pixel_id:
        data["optimization_goal"] = DEFAULT_OPTIMIZATION_GOAL
        data["promoted_object"] = json.dumps({"pixel_id": pixel_id, "custom_event_type": "PURCHASE"})
    else:
        data["optimization_goal"] = FALLBACK_OPTIMIZATION_GOAL
    if cycle and cycle.get("start_date"):
        data["start_time"] = f"{cycle['start_date']}T00:00:00+0800"
    if cycle and cycle.get("end_date"):
        data["end_time"] = f"{cycle['end_date']}T23:59:59+0800"

    payload = graph_post(f"act_{account_id}/adsets", data)
    adset_id = payload.get("id")
    if not adset_id:
        raise MetaMcpError("Meta 沒有回傳廣告組 ID")
    return adset_id


def _create_ad(account_id: str, adset_id: str, creative_id: str, package: dict) -> str:
    result = _client("ads_create_ad", {
        "ad_account_id": account_id, "ad_set_id": adset_id, "ad_name": package["ad_name"],
        "creative": json.dumps({"creative_id": creative_id}),
    })
    _raise_if_tool_error(result)
    ad_id = result.get("ad_id")
    if not ad_id:
        raise MetaMcpError("Meta 沒有回傳廣告 ID")
    return ad_id


def create_package(conn, brand_id: str, cycle_id: str, package_id: str, *, actor: str,
                   campaign_id: Optional[str] = None) -> dict:
    """`campaign_id`：呼叫端（create-all 路由）已經知道這期用的是哪個 Meta campaign 時
    直接傳進來，跳過 `_ensure_campaign()`——真人實測發現的問題：campaign 建成功、
    素材建失敗（例如缺到達網址）的包從來沒走到 authorize_and_map()，DB 裡沒留下
    campaign_id，同一期後續包的 `_ensure_campaign()` DB 查詢因此每包都查不到、每包都
    另建一個 campaign。不給就照舊先查 DB、沒有才建（見 `_ensure_campaign()`）。"""
    row = conn.execute(
        "SELECT * FROM publishing_package WHERE brand_id = %s AND campaign_cycle_id = %s AND id = %s",
        (brand_id, cycle_id, package_id),
    ).fetchone()
    if row is None:
        return {"ok": False, "reason": "找不到這份交接包"}
    package = dict(row)

    # 打 Meta 之前先查完能查的、不必連線就能判斷的兩件事——沒圖／沒到達網址的包不該打一次
    # API 才發現要擋下（票二 1(b)；真人實測發現：ready 的包也可能沒有到達網址，Meta 建
    # 素材會直接拒絕 image ads 缺 link_url）。
    image_path = _first_image_path(conn, brand_id, package["experiment_cell_id"])
    if image_path is None:
        return {"ok": False, "reason": "這個主題還沒放圖"}

    # 到達網址現場算，不信任建交接包當下存的舊值：品牌常常是先產交接包、後來才補登記
    # 官網，build_packages() 不會回頭幫已經產出的包補這一欄（真人實測發現的情境）。
    # 補到了就寫回去，讓交接頁跟著顯示這個網址，不必重產交接包。
    destination = (package["destination_url"] or "").strip() \
        or ads_handoff._default_destination(conn, brand_id)
    if not destination:
        return {"ok": False,
                "reason": "這包還沒有到達網址（商品頁連結）。到品牌資料的自有渠道加官網，"
                         "再重新產出交接包。"}
    if destination != package["destination_url"]:
        conn.execute("UPDATE publishing_package SET destination_url = %s WHERE id = %s",
                     (destination, package_id))
        conn.commit()
        package["destination_url"] = destination

    status = connect(conn)
    if not status["ok"]:
        return {"ok": False, "reason": status["reason"]}

    page_id = get_page_id()
    if not page_id:
        return {"ok": False, "reason": "還沒選粉絲專頁"}

    account_id = _raw_account_id()

    # 台灣廣告主身分驗證（真人實測發現）：鎖定台灣的廣告組合一定要帶受益人／付款人
    # ID，Ads MCP 沒有對應參數可填，只能沿用帳戶既有廣告組合驗證過的身分——查不到就
    # 擋在建 campaign 之前，不要建了一半才發現廣告組合會被拒絕。
    identity_id = _taiwan_identity(account_id)
    if not identity_id:
        return {"ok": False, "reason": TAIWAN_IDENTITY_MISSING_REASON}

    try:
        resolved_campaign_id = campaign_id or _ensure_campaign(
            conn, brand_id, cycle_id, account_id, package)
    except MetaMcpError as exc:
        return {"ok": False, "reason": _plain_error(exc)}
    except Exception as exc:  # noqa: BLE001 — 對外呼叫一律不穿牆
        return {"ok": False, "reason": f"建立廣告時發生非預期錯誤：{exc}"}

    try:
        image_hash = _upload_image(account_id, image_path)
        creative_id = _create_creative(conn, brand_id, account_id, page_id, image_hash, package)
        adset_id = _create_adset(conn, brand_id, cycle_id, account_id, resolved_campaign_id,
                                 package, identity_id=identity_id)
        ad_id = _create_ad(account_id, adset_id, creative_id, package)
    except MetaMcpError as exc:
        # campaign 已經建成功——回傳它的 ID，呼叫端（create-all 路由）才接得住、傳給
        # 下一包沿用，不必每包各自另建一個。
        return {"ok": False, "reason": _plain_error(exc), "meta_campaign_id": resolved_campaign_id}
    except Exception as exc:  # noqa: BLE001 — 對外呼叫一律不穿牆
        return {"ok": False, "reason": f"建立廣告時發生非預期錯誤：{exc}",
                "meta_campaign_id": resolved_campaign_id}

    meta_ids = {"meta_account_id": account_id, "meta_campaign_id": resolved_campaign_id,
                "meta_adset_id": adset_id, "meta_ad_id": ad_id, "meta_creative_id": creative_id}
    try:
        # go_live=False：這裡建的物件全暫停，還沒開始花錢（ADR 0019 第 7 條）——只回填
        # mapping，不授權、不切 LIVE、不建提醒卡；那些留給 activate_cycle() 真的把 Meta
        # 實體切成開啟後才做。
        ads_handoff.authorize_and_map(conn, brand_id, cycle_id, package_id,
                                      meta_ids=meta_ids, actor=actor, go_live=False)
    except ValueError as exc:
        return {"ok": False, "reason": str(exc), "meta_campaign_id": resolved_campaign_id}
    return {"ok": True, "meta_ids": meta_ids}


# ---------------------------------------------------------------------------
# 發布（暫停 → 開啟）
# ---------------------------------------------------------------------------

def _activate(account_id: str, entity_id: str, entity_type: str) -> None:
    result = _client("ads_activate_entity", {
        "ad_account_id": account_id, "entity_id": entity_id, "entity_type": entity_type})
    raw = result.get("result")
    if not raw:
        return
    try:
        parsed = json.loads(raw)
    except (TypeError, ValueError):
        return
    if isinstance(parsed, dict) and parsed.get("success") is False:
        raise MetaMcpError(parsed.get("status") or "Meta 沒有成功切換這個物件的狀態")


def activate_cycle(conn, brand_id: str, cycle_id: str, *, actor: str) -> dict:
    cycle = ads_repo.get_cycle(conn, brand_id, cycle_id)
    if cycle is None:
        return {"ok": False, "reason": "找不到這個廣告檔期"}

    packages = [dict(r) for r in conn.execute(
        "SELECT * FROM publishing_package WHERE brand_id = %s AND campaign_cycle_id = %s",
        (brand_id, cycle_id),
    )]
    mapped = []
    for pkg in packages:
        mapping_row = conn.execute(
            "SELECT * FROM external_ad_mapping WHERE brand_id = %s AND publishing_package_id = %s"
            " ORDER BY created_at DESC LIMIT 1", (brand_id, pkg["id"]),
        ).fetchone()
        if not (mapping_row and mapping_row["meta_ad_id"]):
            continue
        already_live = conn.execute(
            "SELECT 1 FROM activation_authorization WHERE brand_id = %s"
            " AND scope_type = 'campaign_activation' AND scope_ref = %s", (brand_id, pkg["id"]),
        ).fetchone()
        if already_live:  # 連按兩次「發布全部」不重複寫授權列與提醒卡
            continue
        mapped.append((pkg, dict(mapping_row)))

    if not mapped:
        if packages and any(
            conn.execute("SELECT 1 FROM activation_authorization WHERE brand_id = %s"
                         " AND scope_type = 'campaign_activation' AND scope_ref = %s",
                         (brand_id, p["id"])).fetchone() for p in packages):
            return {"ok": True, "activated": 0, "failed": []}  # 全部早就發布過
        return {"ok": False, "reason": "這期還沒有已建到 Meta 的包，先按「一鍵建到 Meta」。"}

    account_id = _raw_account_id()
    activated_campaigns, activated_adsets = set(), set()
    activated, failed = 0, []
    for pkg, mapping in mapped:
        try:
            campaign_id = mapping["meta_campaign_id"]
            if campaign_id and campaign_id not in activated_campaigns:
                _activate(account_id, campaign_id, "campaign")
                activated_campaigns.add(campaign_id)
            adset_id = mapping["meta_adset_id"]
            if adset_id and adset_id not in activated_adsets:
                _activate(account_id, adset_id, "ad_set")
                activated_adsets.add(adset_id)
            _activate(account_id, mapping["meta_ad_id"], "ad")
            # 只有這裡（Meta 端真的切成開啟）才算「花錢那一刻」（ADR 0019 第 7 條）：
            # 建授權、切 LIVE、建提醒卡；失敗的包不會走到這裡，不會有授權列。
            ads_handoff.go_live(conn, brand_id, cycle_id, pkg["id"], mapping["id"], actor=actor)
        except MetaMcpError as exc:
            failed.append({"package_id": pkg["id"], "reason": _plain_error(exc)})
            continue
        except Exception as exc:  # noqa: BLE001 — 對外呼叫一律不穿牆
            failed.append({"package_id": pkg["id"], "reason": str(exc)})
            continue
        activated += 1

    return {"ok": True, "activated": activated, "failed": failed}


# ---------------------------------------------------------------------------
# 調度台『上架』模組門面（票 O1-02，ADR 0024）
# ---------------------------------------------------------------------------
# 使用者 2026-08-23 裁決：create_package()／activate_cycle() 一律不開放成 op，建廣告
# 與開啟廣告永遠只由使用者在畫面上按（Meta 寫入被 error 31 擋住，看板 M1-01）。

def _current_cycle(conn, brand_id: str) -> "Optional[dict]":
    """比照 app/ads/diagnosis.py:29 _current_cycle()：取最新一個投放中或等判讀的檔期。"""
    for cycle in ads_repo.list_cycles(conn, brand_id):
        if cycle["status"] in ("LIVE", "EVALUATING"):
            return cycle
    return None


def status(conn, brand_id: str) -> dict:
    """調度台 facts：`publish.cycle_id`、`publish.packages_total`、
    `publish.packages_mapped`（已經建到 Meta 且拿到 meta_ad_id 的包數）、`publish.live`。
    只數不撈（比照 activate_cycle() 既有查法，不呼叫 handoff.list_packages()／
    readiness_ring()——那兩支每包都重查一次檔期與素材，太重）。"""
    cycle = _current_cycle(conn, brand_id)
    if cycle is None:
        return {"publish.cycle_id": None, "publish.packages_total": 0,
                "publish.packages_mapped": 0, "publish.live": False}
    packages_total = conn.execute(
        "SELECT COUNT(*) AS c FROM publishing_package WHERE brand_id = %s"
        " AND campaign_cycle_id = %s", (brand_id, cycle["id"]),
    ).fetchone()["c"]
    packages_mapped = conn.execute(
        "SELECT COUNT(*) AS c FROM publishing_package AS pp WHERE pp.brand_id = %s"
        " AND pp.campaign_cycle_id = %s AND EXISTS (SELECT 1 FROM external_ad_mapping AS eam"
        " WHERE eam.brand_id = pp.brand_id AND eam.publishing_package_id = pp.id"
        " AND eam.meta_ad_id IS NOT NULL)", (brand_id, cycle["id"]),
    ).fetchone()["c"]
    return {
        "publish.cycle_id": cycle["id"],
        "publish.packages_total": packages_total,
        "publish.packages_mapped": packages_mapped,
        "publish.live": cycle["status"] == "LIVE",
    }


def handle(conn, action: dict) -> dict:
    """上架模組沒有任何 op：建廣告與開啟廣告永遠只由使用者在畫面上按（票 O1-02 裁決）。
    收到任何 op 一律丟 ValueError（ADR 0024 決議 6）。"""
    raise ValueError(f"上架模組不認得這個 op：{action['op']}")


core_orchestrator.register_module("publish", status=status, handle=handle)
