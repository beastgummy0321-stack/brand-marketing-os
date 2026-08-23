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
    "ads_create_ad_set", "ads_create_creative", "ads_create_ad", "ads_activate_entity",
)

NOT_CONNECTED_REASON = "還沒連接 Meta 廣告帳戶"
DISABLED_FALLBACK_REASON = "Meta 目前沒開放這個帳戶使用自動建廣告"

IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp"}

# 目標／出價／受眾預設（票面「實連結果」）：package 沒有的欄位，程式給固定值，不問 LLM、
# 不進畫面。ponytail: 沒有偵測帳戶是否掛 Pixel 就固定用轉換目標——沒有 Pixel 時 Meta 會在
# ads_create_ad_set 直接回錯誤，原樣顯示給使用者；真的要自動退 LINK_CLICKS，之後再串接
# 帳戶層級 Pixel 偵測（後續票再進設定中心）。
DEFAULT_OBJECTIVE = "OUTCOME_SALES"
DEFAULT_BUYING_TYPE = "AUCTION"
DEFAULT_BILLING_EVENT = "IMPRESSIONS"
DEFAULT_OPTIMIZATION_GOAL = "OFFSITE_CONVERSIONS"
DEFAULT_TARGETING = {"geo_locations": {"countries": ["TW"]}, "age_min": 18}


class MetaMcpError(Exception):
    """跟 Meta MCP／Graph API 往來時的內部錯誤，對外一律經 `_plain_error()` 轉白話。"""


def _plain_error(exc: Exception) -> str:
    text = str(exc).strip()
    if "190" in text or "OAuthException" in text:
        return "Meta 金鑰過期了，到設定中心重新貼一張"
    return text or "連不上 Meta，稍後再試一次。"


# ---------------------------------------------------------------------------
# 唯一的 MCP 呼叫函式：測試 monkeypatch 這支（`meta_mcp._client`）。
# ---------------------------------------------------------------------------

def _client(name: str, arguments: dict) -> dict:
    token = os.environ.get(TOKEN_ENV_VAR, "").strip()
    if not token:
        raise MetaMcpError("還沒有設定 META_MCP_TOKEN")
    import httpx  # 延遲 import，比照 meta_api.py 的既有慣例

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
        raise MetaMcpError(str(message))


# ---------------------------------------------------------------------------
# 憑證存取：token／帳號 ID 只認環境變數；粉絲專頁另外可由設定中心寫回 .env。
# ---------------------------------------------------------------------------

def _raw_account_id() -> str:
    """回傳不帶 act_ 前綴的數字帳號 ID（MCP 工具要的格式）；使用者填 .env 時貼了
    act_ 前綴也認得。"""
    raw = os.environ.get(ACCOUNT_ID_ENV_VAR, "").strip()
    return raw[4:] if raw.startswith("act_") else raw


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
    `images.{key}.hash`，這裡不假設 key 名稱，直接取第一筆有 hash 的值。
    """
    token = os.environ.get(TOKEN_ENV_VAR, "").strip()
    encoded = base64.b64encode(image_path.read_bytes()).decode("ascii")
    import httpx  # 延遲 import，比照 meta_api.py 的既有慣例

    try:
        response = httpx.post(
            f"https://graph.facebook.com/{meta_api.API_VERSION}/act_{account_id}/adimages",
            data={"access_token": token, "bytes": encoded}, timeout=60.0,
        )
    except Exception:
        raise MetaMcpError("圖片上傳失敗：連不上 Meta。")
    if response.status_code >= 400:
        raise MetaMcpError(f"圖片上傳失敗：Meta 回了 {response.status_code}。")
    try:
        payload = response.json()
    except ValueError:
        raise MetaMcpError("圖片上傳失敗：Meta 的回覆讀不出來。")
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
        "SELECT meta_campaign_id FROM external_ad_mapping WHERE brand_id = ?"
        " AND campaign_cycle_id = ? AND meta_campaign_id IS NOT NULL AND meta_campaign_id != ''"
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
    destination = package["destination_url"] or ""
    link_url = (f"{destination}{'&' if '?' in destination else '?'}{ads_handoff.utm_query(utm)}"
               if destination else None)
    args = {"ad_account_id": account_id, "page_id": page_id, "image_hash": image_hash,
            "name": package["ad_name"]}
    if link_url:
        args["link_url"] = link_url
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


def _create_adset(conn, brand_id: str, cycle_id: str, account_id: str,
                  campaign_id: str, package: dict) -> str:
    cycle = ads_repo.get_cycle(conn, brand_id, cycle_id)
    args = {
        "ad_account_id": account_id, "campaign_id": campaign_id,
        "ad_set_name": package["adset_name"], "billing_event": DEFAULT_BILLING_EVENT,
        "optimization_goal": DEFAULT_OPTIMIZATION_GOAL,
        "targeting": json.dumps(DEFAULT_TARGETING, ensure_ascii=False),
        "daily_budget": int(round((package["daily_budget"] or 0) * 100)),
    }
    if cycle and cycle.get("start_date"):
        args["start_time"] = cycle["start_date"]
    if cycle and cycle.get("end_date"):
        args["end_time"] = cycle["end_date"]

    result = _client("ads_create_ad_set", args)
    _raise_if_tool_error(result)
    adset_id = result.get("ad_set_id")
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


def create_package(conn, brand_id: str, cycle_id: str, package_id: str, *, actor: str) -> dict:
    row = conn.execute(
        "SELECT * FROM publishing_package WHERE brand_id = ? AND campaign_cycle_id = ? AND id = ?",
        (brand_id, cycle_id, package_id),
    ).fetchone()
    if row is None:
        return {"ok": False, "reason": "找不到這份交接包"}
    package = dict(row)

    # 先查有沒有圖、不必連 Meta 就能判斷——沒圖的包不該打一次 API 才發現要擋下
    # （票二 1(b)：沒圖的包回 reason 不呼叫 client）。
    image_path = _first_image_path(conn, brand_id, package["experiment_cell_id"])
    if image_path is None:
        return {"ok": False, "reason": "這個主題還沒放圖"}

    status = connect(conn)
    if not status["ok"]:
        return {"ok": False, "reason": status["reason"]}

    page_id = get_page_id()
    if not page_id:
        return {"ok": False, "reason": "還沒選粉絲專頁"}

    account_id = _raw_account_id()
    try:
        campaign_id = _ensure_campaign(conn, brand_id, cycle_id, account_id, package)
        image_hash = _upload_image(account_id, image_path)
        creative_id = _create_creative(conn, brand_id, account_id, page_id, image_hash, package)
        adset_id = _create_adset(conn, brand_id, cycle_id, account_id, campaign_id, package)
        ad_id = _create_ad(account_id, adset_id, creative_id, package)
    except MetaMcpError as exc:
        return {"ok": False, "reason": _plain_error(exc)}
    except Exception as exc:  # noqa: BLE001 — 對外呼叫一律不穿牆
        return {"ok": False, "reason": f"建立廣告時發生非預期錯誤：{exc}"}

    meta_ids = {"meta_account_id": account_id, "meta_campaign_id": campaign_id,
                "meta_adset_id": adset_id, "meta_ad_id": ad_id, "meta_creative_id": creative_id}
    try:
        # go_live=False：這裡建的物件全暫停，還沒開始花錢（ADR 0019 第 7 條）——只回填
        # mapping，不授權、不切 LIVE、不建提醒卡；那些留給 activate_cycle() 真的把 Meta
        # 實體切成開啟後才做。
        ads_handoff.authorize_and_map(conn, brand_id, cycle_id, package_id,
                                      meta_ids=meta_ids, actor=actor, go_live=False)
    except ValueError as exc:
        return {"ok": False, "reason": str(exc)}
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
        "SELECT * FROM publishing_package WHERE brand_id = ? AND campaign_cycle_id = ?",
        (brand_id, cycle_id),
    )]
    mapped = []
    for pkg in packages:
        mapping_row = conn.execute(
            "SELECT * FROM external_ad_mapping WHERE brand_id = ? AND publishing_package_id = ?"
            " ORDER BY created_at DESC LIMIT 1", (brand_id, pkg["id"]),
        ).fetchone()
        if mapping_row and mapping_row["meta_ad_id"]:
            mapped.append((pkg, dict(mapping_row)))

    if not mapped:
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
