"""app/meta/graph.py — Graph API client: listing the ad accounts a Meta access token can
see, and pulling one account's daily campaign insights. Private: only app/meta/routes.py
and app/meta/daily_pull.py (both inside this package) import this.

`fetch_page` does the real network call and is the unit tests replace by name (same
pattern as app/core/net.py's `fetch_url`, replaced in test_intake.py) — no network in
tests. `list_ad_accounts`/`list_campaign_insights` do the paging and shape-parsing
around it and are exercised for real; only the network edge is faked.

Verified live against the real host, 2026-08-29 (04-design-approved.md): v26.0 is the
current Graph API version. Success shape: {"data": [{"account_id","name","currency",
"id"}], "paging": {...}}. Error shape: {"error": {"message","type","code","fbtrace_id"}}.
Use the Graph API directly, not this session's Meta connector (it returns money as
formatted strings and cannot see two of the user's four accounts — see
HANDOFF-schedule-module.md §2).

Trust-boundary hardening (review round 1): Meta is a live third party — a non-JSON body
(5xx edge, HTML error page) or an account entry missing a field are real possibilities,
not hypotheticals, and must become a human GraphError instead of an uncaught 500.

Ticket 05 (`insights`, `list_campaign_insights`): the official Marketing API `insights`
reference confirms `spend`/`impressions`/`clicks`/`campaign_id`/`campaign_name` as plain
fields and `purchase_roas` as `list[{"action_type","value"}]` — not a scalar, and real
accounts often carry several synonymous `action_type` entries for the same purchase event
(`omni_purchase`, `onsite_web_purchase`, `offsite_conversion.fb_pixel_purchase`, …), so
`_extract_roas` below picks one deterministically instead of taking `list[0]`. Whether an
untracked campaign omits the key entirely, returns an empty list, or returns null could
not be confirmed against a real token in this session — `_extract_roas` treats all three
the same way (→ None, i.e. 未追蹤) so the behaviour is correct regardless of which shape
Meta actually sends; this should still be checked against a real token before trusting the
distinction never matters for some other reason.
"""

import json
from datetime import date
from decimal import Decimal, InvalidOperation

import httpx

GRAPH_API_VERSION = "v26.0"
GRAPH_BASE_URL = f"https://graph.facebook.com/{GRAPH_API_VERSION}"
_MAX_PAGES = 10  # design ceiling — a real account list is nowhere near this many pages


class GraphError(Exception):
    """Graph API 拒絕了這個權杖或這次呼叫。message 是 Graph 原文（英文）或本檔補的人話，
    呼叫端直接包進中文句子顯示——絕不含權杖本身。"""

    def __init__(self, message: str):
        self.message = message
        super().__init__(message)


def fetch_page(url: str, *, params: dict | None, headers: dict) -> dict:
    """一頁的真正網路呼叫；不呼叫 raise_for_status()——Graph API 的錯誤形狀
    （{"error": {...}}）本來就會用一般 HTTP 狀態碼回來，直接回傳解析好的 JSON 讓
    list_ad_accounts 統一判斷成功／失敗。測試換掉這支（同 app/core/net.py fetch_url
    的替換慣例），不打真正的網路。"""
    resp = httpx.get(url, params=params, headers=headers, timeout=10.0)
    return resp.json()


def _to_account(item: dict) -> dict | None:
    """一個帳號條目 → 我們要的三個欄位，缺 account_id 就整筆不能用（跳過）；缺 name／
    currency 不是致命傷，補一個看得懂的預設值，不因為一個欄位缺席就整包帳號清單報廢。"""
    account_id = item.get("account_id")
    if not account_id:
        return None
    return {
        "account_id": account_id,
        "name": item.get("name") or account_id,
        "currency": item.get("currency") or "",
    }


def _fetch_all_pages(url: str, params: dict | None, headers: dict) -> list[dict]:
    """共用的翻頁＋錯誤處理骨架（list_ad_accounts／list_campaign_insights 都要「打一頁→
    判斷錯誤形狀→收集 data→跟 paging.next」，只有 data 裡每一項怎麼轉型不同，抽出來
    避免兩份幾乎一樣的錯誤處理各錯各的）。回傳收集到的原始 data 項目，轉型交給呼叫端。"""
    items: list[dict] = []
    for _ in range(_MAX_PAGES):
        try:
            body = fetch_page(url, params=params, headers=headers)
        except httpx.HTTPError:
            raise GraphError("連不上 Meta，請稍後再試。") from None
        except json.JSONDecodeError:
            raise GraphError("Meta 回了看不懂的內容，請稍後再試。") from None
        if "error" in body:
            message = body["error"].get("message") or "Meta 回報了一個沒有說明的錯誤。"
            raise GraphError(message)
        items.extend(body.get("data", []))
        next_url = body.get("paging", {}).get("next")
        if not next_url:
            break
        url, params = next_url, None
    return items


def list_ad_accounts(token: str) -> list[dict]:
    """回傳這個權杖看得到的所有帳號 [{"account_id","name","currency"}]，跟著
    paging.next 翻頁最多 _MAX_PAGES 頁。權杖不能用（連不上 Meta、Meta 回了看不懂的
    內容）時丟 GraphError(人話原因)，呼叫端據此判斷「什麼都不存」
    （04-design-approved.md：一個連帳號都列不出來的權杖，什麼都不寫）。"""
    headers = {"Authorization": f"Bearer {token}"}
    url = f"{GRAPH_BASE_URL}/me/adaccounts"
    params: dict | None = {"fields": "account_id,name,currency", "limit": 100}
    items = _fetch_all_pages(url, params, headers)
    return [a for a in (_to_account(item) for item in items) if a is not None]


_ROAS_ACTION_PRIORITY = (
    "omni_purchase", "onsite_web_purchase", "offsite_conversion.fb_pixel_purchase", "purchase",
)


def _extract_roas(action_stats) -> Decimal | None:
    """purchase_roas 是 `list[{"action_type","value"}]`，同一筆常見好幾個同義
    action_type（見本檔檔頭說明）——固定用一份優先序挑第一個對得上的，不是盲目拿
    `list[0]`。缺席、空陣列、或沒有任何一個對得上優先序，一律當「未追蹤」（None，
    不是 0）——票 05 的核心規則，null 與 0 是兩件不同的事。"""
    if not action_stats:
        return None
    by_type = {a.get("action_type"): a.get("value") for a in action_stats if isinstance(a, dict)}
    for action_type in _ROAS_ACTION_PRIORITY:
        value = by_type.get(action_type)
        if value is not None:
            try:
                return Decimal(str(value))
            except InvalidOperation:
                return None
    return None


def _to_campaign_row(item: dict) -> dict | None:
    """一天一個活動的 insights 條目 → 我們要存的六個欄位；缺 campaign_id 或
    spend/impressions/clicks 解析不出數字，這一筆不能用（跳過，不讓整包報廢）。"""
    campaign_id = item.get("campaign_id")
    if not campaign_id:
        return None
    try:
        spend = Decimal(str(item.get("spend", "0")))
        impressions = int(item.get("impressions", 0) or 0)
        clicks = int(item.get("clicks", 0) or 0)
    except (InvalidOperation, TypeError, ValueError):
        return None
    return {
        "campaign_id": campaign_id,
        "campaign_name": item.get("campaign_name") or campaign_id,
        "spend": spend,
        "impressions": impressions,
        "clicks": clicks,
        "roas": _extract_roas(item.get("purchase_roas")),
    }


def list_campaign_insights(token: str, account_id: str, day: date) -> list[dict]:
    """回傳這個帳號『某一天』每個活動的成效
    [{"campaign_id","campaign_name","spend","impressions","clicks","roas"}]（roas 可能是
    None＝未追蹤）。`account_id` 是 `meta_ad_account.account_id`（純數字，無 act_ 前綴——
    見 migration 註解），這裡才補上 insights 端點要的 act_ 前綴。"""
    headers = {"Authorization": f"Bearer {token}"}
    url = f"{GRAPH_BASE_URL}/act_{account_id}/insights"
    params: dict | None = {
        "level": "campaign",
        "time_increment": 1,
        "time_range": json.dumps({"since": day.isoformat(), "until": day.isoformat()}),
        "fields": "campaign_id,campaign_name,spend,impressions,clicks,purchase_roas",
        "limit": 100,
    }
    items = _fetch_all_pages(url, params, headers)
    return [r for r in (_to_campaign_row(item) for item in items) if r is not None]
