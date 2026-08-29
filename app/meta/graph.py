"""app/meta/graph.py — Graph API client for listing the ad accounts a Meta access token
can see. Private: only app/meta/routes.py imports this.

`fetch_page` does the real network call and is the unit tests replace by name (same
pattern as app/core/net.py's `fetch_url`, replaced in test_intake.py) — no network in
tests. `list_ad_accounts` does the paging and shape-parsing around it and is exercised
for real; only the network edge is faked.

Verified live against the real host, 2026-08-29 (04-design-approved.md): v26.0 is the
current Graph API version. Success shape: {"data": [{"account_id","name","currency",
"id"}], "paging": {...}}. Error shape: {"error": {"message","type","code","fbtrace_id"}}.
Use the Graph API directly, not this session's Meta connector (it returns money as
formatted strings and cannot see two of the user's four accounts — see
HANDOFF-schedule-module.md §2).

Trust-boundary hardening (review round 1): Meta is a live third party — a non-JSON body
(5xx edge, HTML error page) or an account entry missing a field are real possibilities,
not hypotheticals, and must become a human GraphError instead of an uncaught 500.
"""

import json

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


def list_ad_accounts(token: str) -> list[dict]:
    """回傳這個權杖看得到的所有帳號 [{"account_id","name","currency"}]，跟著
    paging.next 翻頁最多 _MAX_PAGES 頁。權杖不能用（連不上 Meta、Meta 回了看不懂的
    內容）時丟 GraphError(人話原因)，呼叫端據此判斷「什麼都不存」
    （04-design-approved.md：一個連帳號都列不出來的權杖，什麼都不寫）。"""
    headers = {"Authorization": f"Bearer {token}"}
    url = f"{GRAPH_BASE_URL}/me/adaccounts"
    params: dict | None = {"fields": "account_id,name,currency", "limit": 100}
    accounts: list[dict] = []
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
        for item in body.get("data", []):
            account = _to_account(item)
            if account is not None:
                accounts.append(account)
        next_url = body.get("paging", {}).get("next")
        if not next_url:
            break
        url, params = next_url, None
    return accounts
