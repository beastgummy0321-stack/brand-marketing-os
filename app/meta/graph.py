"""app/meta/graph.py — Graph API client: listing the ad accounts a Meta access token can
see, and pulling one account's insights across all three levels over a date range. Private,
inside this package only — importers are app/meta/routes.py and app/meta/daily_pull.py.
（讀 campaign／adset／ad 物件與素材的那一段隨票 S2 一起刪除，2026-08-31 使用者裁決刪掉重建；
要撿回來：`git show v0.3-onboarding-read-last:app/meta/graph.py`。）

`fetch_page` does the real network call and is the unit tests replace by name (same
pattern as app/core/net.py's `fetch_url`, replaced in test_intake.py) — no network in
tests. `list_ad_accounts`/`list_entity_insights` do the paging and shape-parsing
around it and are exercised for real; only the network edge is faked.

Verified live against the real host, 2026-08-29 (04-design-approved.md): v26.0 is the
current Graph API version. Success shape: {"data": [{"account_id","name","currency",
"id"}], "paging": {...}}. Error shape: {"error": {"message","type","code","fbtrace_id"}}.
Ticket T4 (2026-09-03): `timezone_name` is also requested — documented on the AdAccount node
(https://developers.facebook.com/docs/marketing-api/reference/ad-account/) — and, like
name/currency, is only ever missing when Meta genuinely omits it; `_to_account` below carries
it through when present and leaves it out when not (never a guessed value).
Use the Graph API directly, not this session's Meta connector (it returns money as
formatted strings and cannot see two of the user's four accounts — see
HANDOFF-schedule-module.md §2).

Trust-boundary hardening (review round 1): Meta is a live third party — a non-JSON body
(5xx edge, HTML error page) or an account entry missing a field are real possibilities,
not hypotheticals, and must become a human GraphError instead of an uncaught 500.

Ticket 05 (`insights`, formerly `list_campaign_insights`): the official Marketing API
`insights` reference confirms `spend`/`impressions`/`clicks`/`campaign_id`/`campaign_name`
as plain fields and `purchase_roas` as `list[{"action_type","value"}]` — not a scalar, and
real accounts often carry several synonymous `action_type` entries for the same purchase
event (`omni_purchase`, `onsite_web_purchase`, `offsite_conversion.fb_pixel_purchase`, …),
so `_extract_roas` below picks one deterministically instead of taking `list[0]`. Whether an
untracked campaign omits the key entirely, returns an empty list, or returns null could
not be confirmed against a real token in this session — `_extract_roas` treats all three
the same way (→ None, i.e. 未追蹤) so the behaviour is correct regardless of which shape
Meta actually sends; this should still be checked against a real token before trusting the
distinction never matters for some other reason.

票 S1 (`list_entity_insights`, replaces `list_campaign_insights`): 三個層級（campaign／
adset／ad）共用一支函式，收一個日期範圍而不是單一天——`time_increment: 1` 的一次呼叫在
同一份回應裡回好幾天，見 `_to_entity_row` 為什麼 `spend_date` 要從每一列自己的
`date_start` 讀，不能從呼叫端的迴圈變數來。`app/meta/repository.py` 的 `spend_summary()`
CPA 計算沿用下面 `_ROAS_ACTION_PRIORITY` 這份同義字優先序（同一組同義字只維護一份）——
改這裡的順序會連動改動 CPA。
"""

import json
from datetime import date
from decimal import Decimal, InvalidOperation

import httpx

GRAPH_API_VERSION = "v26.0"
GRAPH_BASE_URL = f"https://graph.facebook.com/{GRAPH_API_VERSION}"
# Runaway guard, not a data limit — hitting it raises (see `_fetch_all_pages`). Measured
# 2026-08-30 against a real account: a 91-day ad-level insights pull needs 6 pages at
# `limit: 100`. The old value of 10 was sized for the account list, and silently capped a
# multi-month pull at 1,000 rows.
_MAX_PAGES = 200


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
    的替換慣例），不打真正的網路。

    `timeout=10.0` 這次（票 S1）**維持不動**：ad 層一整個月的拉取實際要花多久，這個
    session 沒有量過——沒量到的數字不改。真的開始逾時時，官方文件給的下一步是
    "try to break down the query into smaller queries by putting in filters like date
    range"（SPEC §7.4(b)），再上去是 async insights job，**都不是把 timeout 調大**；
    而按月切分 backfill（見 daily_pull.py `_month_chunks`）已經在做了。"""
    resp = httpx.get(url, params=params, headers=headers, timeout=10.0)
    return resp.json()


def _to_account(item: dict) -> dict | None:
    """一個帳號條目 → 我們要的欄位，缺 account_id 就整筆不能用（跳過）；缺 name／
    currency 不是致命傷，補一個看得懂的預設值，不因為一個欄位缺席就整包帳號清單報廢。

    `timezone_name`（票 T4）不比照 name／currency 補預設值——缺席就整個 key 不放進字典
    （不是塞一個猜的時區），upsert_accounts 那端 `.get("timezone_name")` 讀到 None 存成
    NULL，daily_pull 讀到 NULL 退回組織時區。這裡刻意跟既有測試（GraphClientTest）的既有
    斷言相容：舊 fixture 沒有這個欄位，回傳字典就不該多一個 key。"""
    account_id = item.get("account_id")
    if not account_id:
        return None
    account = {
        "account_id": account_id,
        "name": item.get("name") or account_id,
        "currency": item.get("currency") or "",
    }
    if item.get("timezone_name"):
        account["timezone_name"] = item["timezone_name"]
    return account


def _raise_if_error(body: dict) -> None:
    """`{"error": {...}}` 形狀 → `GraphError`(人話原因)。`_fetch_all_pages`／`fetch_budgets`
    共用同一份判斷，不是各自寫各自的錯誤偵測（票 05-budget-level-mismatch 明文）。"""
    if "error" in body:
        message = body["error"].get("message") or "Meta 回報了一個沒有說明的錯誤。"
        raise GraphError(message)


def _fetch_all_pages(url: str, params: dict | None, headers: dict) -> list[dict]:
    """共用的翻頁＋錯誤處理骨架（list_ad_accounts／list_entity_insights 都要「打一頁→
    判斷錯誤形狀→收集 data→跟 paging.next」，只有 data 裡每一項怎麼轉型不同，抽出來
    避免兩份幾乎一樣的錯誤處理各錯各的）。回傳收集到的原始 data 項目，轉型交給呼叫端。

    2026-08-30（票 S0）：撞到 `_MAX_PAGES` 時**拋例外，不回一份殘缺的清單**。原本的寫法
    翻完上限就把手上有的回去，呼叫端沒有任何辦法知道自己拿到的是不是全部——少掉的那幾天
    會讓一則正在贏的廣告看起來像是停止投遞了。沒拿全的資料比拿不到更危險，因為它看起來
    像資料。"""
    items: list[dict] = []
    for _ in range(_MAX_PAGES):
        try:
            body = fetch_page(url, params=params, headers=headers)
        except httpx.HTTPError:
            raise GraphError("連不上 Meta，請稍後再試。") from None
        except json.JSONDecodeError:
            raise GraphError("Meta 回了看不懂的內容，請稍後再試。") from None
        _raise_if_error(body)
        items.extend(body.get("data", []))
        next_url = body.get("paging", {}).get("next")
        if not next_url:
            return items
        url, params = next_url, None
    raise GraphError(
        "Meta 的資料超過一次可以取回的上限，這次沒有全部拿到，請縮小日期範圍再試一次。"
    )


def list_ad_accounts(token: str) -> list[dict]:
    """回傳這個權杖看得到的所有帳號 [{"account_id","name","currency"}]，跟著
    paging.next 翻頁最多 _MAX_PAGES 頁。權杖不能用（連不上 Meta、Meta 回了看不懂的
    內容）時丟 GraphError(人話原因)，呼叫端據此判斷「什麼都不存」
    （04-design-approved.md：一個連帳號都列不出來的權杖，什麼都不寫）。"""
    headers = {"Authorization": f"Bearer {token}"}
    url = f"{GRAPH_BASE_URL}/me/adaccounts"
    params: dict | None = {"fields": "account_id,name,currency,timezone_name", "limit": 100}
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


def _to_campaign(item: dict) -> dict | None:
    """帳號活動清單的一筆 → 我們要的三個欄位；缺 id 這一筆不能用（跳過，比照 _to_account）。
    名稱缺席補空字串——精準比對永遠不會等於空字串，所以缺名稱＝配不到，不是配到別人。
    `effective_status` 是平台自己的字，原樣存、不缺席時補 None（票 T3b，ADR 0055 §4：
    我們不把它翻譯成自己的詞彙）。"""
    campaign_id = item.get("id")
    if not campaign_id:
        return None
    return {
        "campaign_id": campaign_id, "name": item.get("name") or "",
        "effective_status": item.get("effective_status"),
    }


def list_campaigns(token: str, account_id: str) -> list[dict]:
    """這個帳號目前所有活動的 [{"campaign_id","name","effective_status"}]，**包含還沒
    開跑的**。

    名稱比對要問的是「平台上存不存在這個活動」，不是「它花過錢」。insights 端點只回有
    投遞的活動：手動建好但維持關閉（PAUSED）的活動在那裡查不到，所以名稱比對不能建在
    `meta_entity_spend` 上——買廣告的人本來就是先照樹把活動建成關閉狀態、確認無誤才開跑
    （2026-08-29 對真帳號實測：BP AD 有 3 個活動，當天的 insights 只回 1 個）。

    `account_id` 同 `list_entity_insights`，是 `meta_ad_account.account_id`（純數字），
    act_ 前綴在這裡補。"""
    headers = {"Authorization": f"Bearer {token}"}
    url = f"{GRAPH_BASE_URL}/act_{account_id}/campaigns"
    params: dict | None = {"fields": "id,name,effective_status", "limit": 200}
    items = _fetch_all_pages(url, params, headers)
    return [r for r in (_to_campaign(item) for item in items) if r is not None]


def _to_ad_set(item: dict) -> dict | None:
    """一個廣告組合條目 → 我們要的三個欄位；缺 id 這一筆不能用（跳過，比照
    `_to_campaign`）。名稱缺席補空字串——精準比對永遠不會等於空字串，所以缺名稱＝配不到，
    不是配到別人。`effective_status` 原樣存、不缺席時補 None，同 `_to_campaign`。"""
    adset_id = item.get("id")
    if not adset_id:
        return None
    return {
        "adset_id": adset_id, "name": item.get("name") or "",
        "external_status": item.get("effective_status"),
    }


def list_ad_sets(token: str, campaign_id: str) -> list[dict]:
    """這個活動目前所有廣告組合的 [{"adset_id","name","external_status"}]，**包含還沒
    開跑的**——跟 `list_campaigns` 同一個理由：問的是「平台上存不存在」，不是「它花過
    錢」，手動建好但維持關閉的廣告組合在 insights 查不到（票 T3c，ADR 0055 §7）。

    `campaign_id` 是這個節點的父層節點已經綁定的 `channel_entity_map.external_id`；
    比對只在這個活動內部找，不跨活動——呼叫端（`app.schedule.binding`）負責只在父層
    綁定成功之後才呼叫這裡。活動 id 不像帳號 id 需要 `act_` 前綴。"""
    headers = {"Authorization": f"Bearer {token}"}
    url = f"{GRAPH_BASE_URL}/{campaign_id}/adsets"
    params: dict | None = {"fields": "id,name,effective_status", "limit": 200}
    items = _fetch_all_pages(url, params, headers)
    return [r for r in (_to_ad_set(item) for item in items) if r is not None]


def _to_ad(item: dict) -> dict | None:
    """一個廣告條目 → 我們要的三個欄位；缺 id 這一筆不能用（跳過，比照 `_to_ad_set`）。
    名稱缺席補空字串；`effective_status` 原樣存、不缺席時補 None，同 `_to_ad_set`。

    廣告層的 `effective_status` 有十二個值——比活動層（ADR 0055 §4）多六個：
    `PENDING_REVIEW`／`DISAPPROVED`／`PREAPPROVED`／`PENDING_BILLING_INFO`／`ADSET_PAUSED`／
    `IN_PROCESS`／`WITH_ISSUES`（連同活動層本來就有的 `ACTIVE`／`PAUSED`／`DELETED`／
    `CAMPAIGN_PAUSED`／`ARCHIVED`）。逐字存、不比對、不縮寫，`external_status` 沒有
    CHECK，票 T5 也不加一個（ADR 0057 §8）。"""
    ad_id = item.get("id")
    if not ad_id:
        return None
    return {
        "ad_id": ad_id, "name": item.get("name") or "",
        "external_status": item.get("effective_status"),
    }


def list_ads(token: str, adset_id: str) -> list[dict]:
    """這個廣告組合目前所有廣告的 [{"ad_id","name","external_status"}]，**包含還沒開跑
    的**——跟 `list_campaigns`／`list_ad_sets` 同一個理由：問的是「平台上存不存在」，不是
    「它花過錢」（票 T5，ADR 0057 §1：手動建好、維持關閉的廣告在 insights 查不到）。

    `adset_id` 是這個節點的父層節點已經綁定的 `channel_entity_map.external_id`；比對只在
    這個廣告組合內部找，不跨廣告組合——呼叫端（`app.schedule.binding`）負責只在父層
    （廣告組合）綁定成功之後才呼叫這裡。廣告 id 不像帳號 id 需要 `act_` 前綴，也不像活動
    id 需要任何前綴。"""
    headers = {"Authorization": f"Bearer {token}"}
    url = f"{GRAPH_BASE_URL}/{adset_id}/ads"
    params: dict | None = {"fields": "id,name,effective_status", "limit": 200}
    items = _fetch_all_pages(url, params, headers)
    return [r for r in (_to_ad(item) for item in items) if r is not None]


def fetch_budgets(token: str, external_ids: list[str]) -> dict[str, dict]:
    """票 05（`docs/issues/plan-quality/`）：每個 id 一次 `GET {GRAPH_BASE_URL}/{id}`
    （不是清單端點，不走 `_fetch_all_pages` 的翻頁——一個 id 一個物件，沒有分頁），問「這裡
    設了預算嗎」。回傳 `{external_id: {"daily_budget": str | None, "lifetime_budget": str |
    None}}`；Meta 兩個欄位都回帳戶最小貨幣單位的**字串**（例："500"），這裡原樣存，**不**
    解析成數字——這張票只問「這一層有沒有掛預算」，金額大小不是這裡的事。欄位缺席或顯式
    `null` 都用 `.get()` 收成 `None`，兩者在這裡是同一件事。連不上 Meta／回應看不懂／
    `{"error": …}` 形狀，一律 `GraphError`，跟本檔其他讀取同一套（`_raise_if_error`）。"""
    headers = {"Authorization": f"Bearer {token}"}
    result: dict[str, dict] = {}
    for external_id in external_ids:
        try:
            body = fetch_page(
                f"{GRAPH_BASE_URL}/{external_id}",
                params={"fields": "daily_budget,lifetime_budget"}, headers=headers,
            )
        except httpx.HTTPError:
            raise GraphError("連不上 Meta，請稍後再試。") from None
        except json.JSONDecodeError:
            raise GraphError("Meta 回了看不懂的內容，請稍後再試。") from None
        _raise_if_error(body)
        result[external_id] = {
            "daily_budget": body.get("daily_budget"),
            "lifetime_budget": body.get("lifetime_budget"),
        }
    return result


def _first_non_empty(*values):
    """第一個非 None、非空字串的值；全部都空就是 None。三個欄位（body／title／image_url）
    各自要「頂層欄位優先，退回 link_data」的同一種挑法，只寫一次。"""
    for value in values:
        if value:
            return value
    return None


def fetch_ad_creatives(token: str, ad_ids: list[str]) -> dict[str, dict | None]:
    """票 past-ads/02（ADR 0067 §1.9）：每個 id 一次 `GET {GRAPH_BASE_URL}/{ad_id}`（不是
    清單端點，比照 `fetch_budgets`——一個 id 一個物件，沒有分頁），問這則廣告投放時的
    素材文字／圖片。呼叫端最多一次給 15 個 id（ADR 0067 §1.7）。

    Sources, verified 2026-09-08:
    - Ad node `creative` field —
      https://developers.facebook.com/docs/marketing-api/reference/adgroup/
    - AdCreative `body`（"Not supported for video post creatives"）／`title`／`image_url`／
      `thumbnail_url`／`object_story_spec` —
      https://developers.facebook.com/docs/marketing-api/reference/ad-creative/
    - `object_story_spec.link_data`（"The spec for a link page post or carousel ad"）—
      https://developers.facebook.com/docs/marketing-api/reference/ad-creative-object-story-spec/
    - `link_data.message`（"The main body of the post."）／`name`（"Name of the link."）／
      `picture`（"URL of a picture to use in the post."）—
      https://developers.facebook.com/docs/marketing-api/reference/ad-creative-link-data/
    - Nested field expansion is Graph API field expansion —
      https://developers.facebook.com/docs/graph-api/using-graph-api

    每個 id 的值要嘛是 `None`——Meta 對這個 id 答的是 `{"error": …}`（刪除或讀不到的廣告；
    ADR 0067 §1.9：「Meta 現在回不出這則的素材」是一個狀態，這個 id 留在字典裡，值是
    `None`，絕不整筆丟掉）——要嘛是 name／created_time／effective_status 加上 body／title／
    image_url 三個「第一個非空值」欄位（見 `_first_non_empty`）：一則以連結貼文投放的廣告，
    文字在 `object_story_spec.link_data`，不在 `creative.body`（AdCreative `body` 欄位說明
    原文如上）。每個值原樣存，不修剪、不翻譯。

    `{"error": …}` 形狀不是 transport 失敗——`fetch_page` 不呼叫 `raise_for_status()`，
    Meta 用一般 HTTP 狀態碼＋JSON body 回錯誤，這裡照樣收得到那份 JSON，不會先被
    httpx 拋掉（同 `_raise_if_error` 檔頭）；所以這裡不能沿用 `_raise_if_error`（那支對
    這個形狀丟例外，會讓一個讀不到的 id 讓整批呼叫失敗，違反上一段的規矩）。連不上
    Meta（`httpx.HTTPError`）、或回應解析不出來（`json.JSONDecodeError`），才是真的
    transport 失敗，讓整支呼叫 `GraphError`，跟 `fetch_budgets` 同一套。"""
    headers = {"Authorization": f"Bearer {token}"}
    fields = (
        "name,created_time,effective_status,"
        "creative{body,title,image_url,thumbnail_url,object_story_spec}"
    )
    result: dict[str, dict | None] = {}
    for ad_id in ad_ids:
        try:
            body = fetch_page(
                f"{GRAPH_BASE_URL}/{ad_id}", params={"fields": fields}, headers=headers,
            )
        except httpx.HTTPError:
            raise GraphError("連不上 Meta，請稍後再試。") from None
        except json.JSONDecodeError:
            raise GraphError("Meta 回了看不懂的內容，請稍後再試。") from None
        if "error" in body:
            result[ad_id] = None
            continue
        creative = body.get("creative") or {}
        link_data = (creative.get("object_story_spec") or {}).get("link_data") or {}
        result[ad_id] = {
            "name": body.get("name"),
            "created_time": body.get("created_time"),
            "effective_status": body.get("effective_status"),
            "body": _first_non_empty(creative.get("body"), link_data.get("message")),
            "title": _first_non_empty(creative.get("title"), link_data.get("name")),
            "image_url": _first_non_empty(
                creative.get("image_url"), link_data.get("picture"), creative.get("thumbnail_url"),
            ),
        }
    return result


# 三個層級要的度量欄位完全一樣，只寫一次——三份幾乎相同的字串各自漂移是這種表格最典型的
# 壞法。
#
# **不要加 `reach`，不要加任何 breakdown（age／gender／placement）。** 官方 insights 參考頁
# 寫「The start date of the time range cannot be beyond 37 months from the current date」
# （developers.facebook.com/docs/marketing-api/reference/ad-account/insights/），但
# 2025-06-10 起「reach will no longer be returned for standard queries that apply
# breakdowns and use start_dates more than 13 months old」
# （/docs/marketing-api/insights/best-practices/），2025-10-16 官方公告再把 unique-count
# 類欄位與 hourly breakdown 收到 13 個月、frequency 收到 6 個月。多要一個 reach、或多要一個
# breakdown，可讀的歷史會從 37 個月**無聲**掉到 13 個月——不是報錯，是回來的資料變少，而少
# 掉的資料看起來就跟「那時候沒投」一模一樣。接手舊帳號的讀取（SPEC §7.4(a)、GRILL 決策 9）
# 就建在這 37 個月上。要加欄位前先回來讀這段。
_INSIGHT_METRIC_FIELDS = "spend,impressions,clicks,purchase_roas,actions,action_values"

# 每一層要「自己這層的 id／名稱」，再加上所有**上層**的 id——上層 id 不是裝飾，是
# meta_entity_spend 的 campaign_id／adset_id 兩欄：每一列都得知道自己掛在誰底下，否則
# 「level 2 分了多少錢、level 3 花在哪」永遠接不起來（GRILL.md §1：錢在 level 2 分，數字
# 只在 level 1，這個迴圈才學不起來）。官方 insights 欄位表把 campaign_id／campaign_name／
# adset_id／adset_name／ad_id／ad_name 都列為一般欄位，且是相對父鏈定義的（campaign_id＝
# 「your ad set belongs to」的那個活動），所以在 adset 層一起要 campaign_id 是文件內的用法。
# 反過來文件沒有保證較高層級要得到較低層級的 id——campaign 層不要 ad_id，那一列底下有好幾個
# ad，那個 id 沒有唯一值。也不要 campaign_name／adset_name 當父層名稱：這張表每一列只存自己
# 那層的 entity_name，要顯示父層名稱時去讀父層那幾列，不在每一列複製一份會各自過期的字串。
_LEVEL_FIELDS = {
    "campaign": f"campaign_id,campaign_name,{_INSIGHT_METRIC_FIELDS}",
    "adset": f"campaign_id,adset_id,adset_name,{_INSIGHT_METRIC_FIELDS}",
    "ad": f"campaign_id,adset_id,ad_id,ad_name,{_INSIGHT_METRIC_FIELDS}",
}

# 送出去的歸因窗，同時也是存進 meta_entity_spend.attribution_window 的那個字串——同一份
# 常數兩個用途，不會一邊改一邊沒改。為什麼不吃 API 預設值：文件寫預設值就是這個陣列，但
# 2025-10-16 官方公告寫「On January 12, 2026, we will deprecate certain attribution windows
# available today」——那天已經過了七個月。預設值是 Meta 的，不是我們的，而且它可以在我們
# 不知情的情況下改。兩個用不同窗量出來的 ROAS 不能互相比較，而 backfill 一次就會把舊列跟
# 新列混在同一張表裡（SPEC §7.4(d)，票 S1 D6）。
_ATTRIBUTION_WINDOWS = ("7d_click", "1d_view")


def _to_entity_row(item: dict, level: str, attribution_window: str) -> dict | None:
    """一天一個實體的 insights 條目 → meta_entity_spend 的一列。

    `entity_id`／`entity_name` 取的是**這一列自己那層**的 id 與名稱（ad 層就是 ad_id／
    ad_name）；`campaign_id` 每一層都有；`adset_id`／`ad_id` 在自己以上的層級一律 None——
    這正是那張表哪幾欄 NOT NULL、哪幾欄可 NULL 的分法。名稱缺席退回 id（比照
    `_to_campaign`）：entity_name 是 NOT NULL 而且是給人看的，退回 id 至少指得回同一個東西。

    `spend_date` 一律取這一列自己的 `date_start`，**不可以**用呼叫端迴圈裡的日期：
    `time_increment: 1` 的一次呼叫回的是「一個實體 x 一天」一列，一個月的範圍在同一份
    回應裡就有三十種日期。缺了它，這一列不知道自己是哪天的，唯一索引
    (ad_account_id, level, entity_id, spend_date) 也就無從落地——跳過，不猜。

    `actions`／`action_values` 原封不動往下傳，不解析、不挑選：哪一種 action_type 才算
    「一次轉換」是行業判斷，ADR 0036 不准把它編進程式；`app/meta/repository.py`
    `spend_summary()` 才是唯一算 CPA 的地方，且只在那裡讀這兩欄。`roas` 沿用 `_extract_roas`
    未改——2026-08-30 對真帳號實測，這個帳號回的就是 `omni_purchase`，本來就是那份優先序的
    第一個（GRILL.md §1(a)）。

    解析不出來的一列跳過、不讓整批報廢（沿用原 `_to_campaign_row` 的規矩）。在這裡這條規矩
    比原本更重要：ad 層一個月是好幾百列，一列壞掉就丟掉整個月，而少一列的損失跟平台本來就
    有的缺列同形（GRILL.md §1(d)：81% 的 (實體, 日) 組合本來就沒有列）——真的需要分辨兩者
    時，最便宜的作法是回傳被跳過的列數，不是每列寫 log。"""
    campaign_id = item.get("campaign_id")
    entity_id = item.get(f"{level}_id")
    date_start = item.get("date_start")
    if not campaign_id or not entity_id or not date_start:
        return None
    try:
        spend_date = date.fromisoformat(date_start)
        spend = Decimal(str(item.get("spend", "0")))
        impressions = int(item.get("impressions", 0) or 0)
        clicks = int(item.get("clicks", 0) or 0)
    except (InvalidOperation, TypeError, ValueError):
        return None
    return {
        "level": level,
        "entity_id": entity_id,
        "entity_name": item.get(f"{level}_name") or entity_id,
        "campaign_id": campaign_id,
        "adset_id": item.get("adset_id") if level != "campaign" else None,
        "ad_id": item.get("ad_id") if level == "ad" else None,
        "spend_date": spend_date,
        "spend": spend,
        "impressions": impressions,
        "clicks": clicks,
        "roas": _extract_roas(item.get("purchase_roas")),
        "actions": item.get("actions"),
        "action_values": item.get("action_values"),
        "attribution_window": attribution_window,
    }


def list_entity_insights(
    token: str, account_id: str, level: str, since: date, until: date,
) -> list[dict]:
    """這個帳號在 [since, until] 之間、`level`（campaign／adset／ad）每個實體**每一天**
    一列的成效；一列的形狀見 `_to_entity_row`。`account_id` 是 `meta_ad_account.account_id`
    （純數字、無 act_ 前綴——見 migration 註解），act_ 在這裡補。日期是閉區間：Meta 的
    `time_range` 兩端都含，since 當天與 until 當天都會回。

    沒有投遞的那一天**不會有列**，這裡也絕不補一列 0。2026-08-30 對真帳號實測：ad 層 35
    個實體 x 91 天 = 3,185 個 (實體, 日) 組合，只回 591 列——81% 根本沒有列（GRILL.md
    §1(d)）。「沒投遞」跟「投了沒成效」是兩件不同的事，補 0 會把前者偽造成後者。"""
    headers = {"Authorization": f"Bearer {token}"}
    url = f"{GRAPH_BASE_URL}/act_{account_id}/insights"
    # `time_range` 與 `action_attribution_windows` 都是 Graph API 的結構化參數，在 GET
    # query string 裡以 JSON 字面值當參數值傳（httpx 負責 URL 編碼）：官方參考頁把
    # time_range 印成 object、action_attribution_windows 印成 list<enum{...}>，並把預設值
    # 直接印成 `["7d_click","1d_view"]` 這個 JSON 陣列形狀；time_range 這條編碼路徑本檔已於
    # 2026-08-29 對真主機驗過（見檔頭）。
    params: dict | None = {
        "level": level,
        "time_increment": 1,
        "time_range": json.dumps({"since": since.isoformat(), "until": until.isoformat()}),
        "action_attribution_windows": json.dumps(list(_ATTRIBUTION_WINDOWS)),
        "fields": _LEVEL_FIELDS[level],
        "limit": 100,
    }
    window = ",".join(_ATTRIBUTION_WINDOWS)
    items = _fetch_all_pages(url, params, headers)
    return [r for r in (_to_entity_row(i, level, window) for i in items) if r is not None]

