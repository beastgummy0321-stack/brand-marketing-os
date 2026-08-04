# -*- coding: utf-8 -*-
"""app/ads/meta_api.py — Meta 廣告 API 唯讀用戶端（票 9）。

依票 1 的調研結論（docs/design/15-meta-api-access-findings.md）：
走 Graph API REST ＋ Business Manager 的 System User token，只要 `ads_read`／`read_insights`
兩個唯讀權限，讀自己的廣告帳號不需要 App Review。**刻意不用官方 Ads MCP**——它是讀寫的，
牴觸鐵則 4（扣板機的是人）。

這一層只做三件事：帶 token 打 GET、把回應轉成我們的統一格式、把錯誤翻成人話。
不寫資料庫、不判斷歸屬（那是 app/ads/sync.py 的事）。

平台隔離（決策 0016 硬性原則 1）：Meta 專屬的欄位名與分頁規則全部關在這個檔案裡，
上層拿到的是平台中立的 dict。第二個平台進來時只寫新的 client，不動 sync 與判讀。
"""

from dataclasses import dataclass
from typing import Optional

API_VERSION = "v21.0"
BASE_URL = f"https://graph.facebook.com/{API_VERSION}"
TIMEOUT_S = 30.0
MAX_PAGES = 20  # 分頁上限，防呆用；正常帳號遠遠不會到

NO_TOKEN_MESSAGE = (
    "還沒有設定 Meta 廣告帳號的連線金鑰，這次不抓任何資料。"
    "請到「設定」頁填入唯讀金鑰與廣告帳號編號。"
)


class MetaApiError(Exception):
    """人話錯誤。訊息會直接顯示給使用者看，不得出現原始 API 錯誤碼。"""


@dataclass
class Campaign:
    campaign_id: str
    name: str
    objective: Optional[str]
    effective_status: Optional[str]


@dataclass
class Insight:
    """一個廣告層級在一段期間的成效，已轉成內部統一格式的欄位名。"""

    campaign_id: str
    adset_id: Optional[str]
    ad_id: Optional[str]
    date_start: str
    date_stop: str
    impressions: int
    clicks: int
    spend: float
    conversions: float
    revenue: float
    # 已刪除／已封存的活動不會出現在 list_campaigns，只能靠這裡補名字
    # 供品牌猜測（issue #73）；Meta 官方欄位，insights 本來就抓得到。
    campaign_name: Optional[str] = None


def _normalise_account_id(account_id: str) -> str:
    """Meta 的廣告帳號在 API 路徑上一律帶 act_ 前綴，使用者常只貼數字。"""
    account_id = (account_id or "").strip()
    return account_id if account_id.startswith("act_") else f"act_{account_id}"


def _sum_actions(rows, wanted: tuple) -> float:
    """把 actions／action_values 陣列裡我們認得的類型加總起來。

    Meta 用一個泛用的 actions 陣列表達所有轉換類型，名稱會隨帳號設定不同。
    這裡只認明確的購買類型——認不得的一律不計入，寧可少算也不要把「按讚」算成成交。
    """
    total = 0.0
    for row in rows or []:
        if row.get("action_type") in wanted:
            try:
                total += float(row.get("value") or 0)
            except (TypeError, ValueError):
                continue
    return total


_PURCHASE_ACTIONS = ("purchase", "omni_purchase", "offsite_conversion.fb_pixel_purchase")


class MetaClient:
    """真的會發網路請求的用戶端。唯讀——本類別刻意沒有任何 POST／DELETE 方法。"""

    def __init__(self, access_token: Optional[str]):
        self.access_token = (access_token or "").strip() or None

    def _get(self, path: str, params: dict) -> dict:
        if not self.access_token:
            raise MetaApiError(NO_TOKEN_MESSAGE)
        import httpx  # 延遲 import，讓本檔在未安裝時仍可被 import

        query = dict(params)
        query["access_token"] = self.access_token
        try:
            response = httpx.get(f"{BASE_URL}/{path}", params=query, timeout=TIMEOUT_S)
        except Exception:
            raise MetaApiError("連不上 Meta，可能是網路問題。稍後再試一次，或先用 CSV 匯入。")

        if response.status_code == 401 or response.status_code == 403:
            raise MetaApiError(
                "Meta 拒絕了這次連線，通常是金鑰失效或權限被收回。"
                "請到「設定」頁重新產生一組唯讀金鑰。"
            )
        if response.status_code == 429:
            raise MetaApiError("Meta 說這陣子問太多次了，等一下再試。")
        if response.status_code >= 400:
            raise MetaApiError("Meta 回了一個我們看不懂的錯誤，這次沒抓到資料。")
        try:
            return response.json()
        except ValueError:
            raise MetaApiError("Meta 的回覆讀不出來，這次沒抓到資料。")

    def _paged(self, path: str, params: dict) -> list:
        rows, page = [], 0
        payload = self._get(path, params)
        while True:
            rows.extend(payload.get("data") or [])
            page += 1
            next_url = ((payload.get("paging") or {}).get("cursors") or {}).get("after")
            if not next_url or page >= MAX_PAGES:
                break
            payload = self._get(path, {**params, "after": next_url})
        return rows

    def list_campaigns(self, account_id: str) -> list:
        rows = self._paged(f"{_normalise_account_id(account_id)}/campaigns",
                           {"fields": "id,name,objective,effective_status", "limit": 100})
        return [Campaign(campaign_id=str(r.get("id")), name=r.get("name") or "",
                         objective=r.get("objective"),
                         effective_status=r.get("effective_status")) for r in rows]

    def list_insights(self, account_id: str, since: str, until: str) -> list:
        rows = self._paged(
            f"{_normalise_account_id(account_id)}/insights",
            {"level": "ad", "time_range": f'{{"since":"{since}","until":"{until}"}}',
             "fields": "campaign_id,campaign_name,adset_id,ad_id,date_start,date_stop,"
                       "impressions,clicks,spend,actions,action_values",
             "limit": 200},
        )
        return [parse_insight_row(r) for r in rows]


def parse_insight_row(row: dict) -> Insight:
    """Meta 的一列 insights → 內部統一格式。所有數字欄位缺值一律當 0，不猜、不沿用。"""
    def _num(key, cast=float):
        try:
            return cast(row.get(key) or 0)
        except (TypeError, ValueError):
            return cast(0)

    return Insight(
        campaign_id=str(row.get("campaign_id") or ""),
        adset_id=str(row.get("adset_id")) if row.get("adset_id") else None,
        ad_id=str(row.get("ad_id")) if row.get("ad_id") else None,
        date_start=row.get("date_start") or "",
        date_stop=row.get("date_stop") or "",
        impressions=_num("impressions", int),
        clicks=_num("clicks", int),
        spend=_num("spend"),
        conversions=_sum_actions(row.get("actions"), _PURCHASE_ACTIONS),
        revenue=_sum_actions(row.get("action_values"), _PURCHASE_ACTIONS),
        campaign_name=row.get("campaign_name") or None,
    )


class FakeMetaClient:
    """測試用：不發任何網路請求，回放注入的資料或拋出注入的錯誤。"""

    def __init__(self, campaigns=None, insights=None, error: Optional[Exception] = None):
        self._campaigns = campaigns or []
        self._insights = insights or []
        self.error = error
        self.calls: list = []

    def list_campaigns(self, account_id: str) -> list:
        self.calls.append(("campaigns", account_id))
        if self.error:
            raise self.error
        return list(self._campaigns)

    def list_insights(self, account_id: str, since: str, until: str) -> list:
        self.calls.append(("insights", account_id, since, until))
        if self.error:
            raise self.error
        return list(self._insights)
