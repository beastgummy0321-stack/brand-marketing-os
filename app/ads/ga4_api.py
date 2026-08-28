"""app/ads/ga4_api.py — GA4 Data API 唯讀轉接層（GitHub issue #34）。

決策 0025 第 4 點：GA4 走 Data API 服務帳戶自動同步，UTM 歸因（來源／媒介）放 GA4
彙總層，不強求電商後台的 UTM 對接。比照 app/ads/meta_api.py 的平台隔離原則：GA4
專屬的呼叫方式與欄位名全部關在這個檔案裡，上層（app/ads/ga4_sync.py）拿到的是
平台中立的 dataclass，第二個第三方數據源進來時只寫新的 client，不動 sync 與判讀。

真實用戶端延遲 import Google 官方 `google-analytics-data`／`google-auth` client
library（本機開發與自動測試環境不需要裝這兩個套件也能 import 這個檔案——所有測試
走 FakeGA4Client，真實用戶端只在正式串接服務帳戶、實際呼叫 fetch_source_medium／
purchase_event_seen 時才會用到；部署環境需自行 `pip install google-analytics-data`）。
"""

from dataclasses import dataclass

NO_CREDENTIALS_MESSAGE = (
    "還沒有設定 GA4 服務帳戶金鑰，這次不抓任何資料。"
    "請到「設定」頁貼上服務帳戶金鑰與 GA4 資源編號，或先看服務帳戶設定教學。"
)


class GA4ApiError(Exception):
    """人話錯誤。訊息會直接顯示給使用者看，不得出現原始 API 錯誤碼。"""


@dataclass
class SourceMediumRow:
    """一列「來源／媒介」在一段期間的成效，已轉成內部統一格式的欄位名。"""

    source: str
    medium: str
    sessions: int
    conversions: float
    revenue: float


class GA4Client:
    """真的會呼叫 Google Analytics Data API 的用戶端。唯讀——本類別刻意沒有任何寫入方法。"""

    def __init__(self, property_id: str | None, service_account_json: str | None):
        self.property_id = (property_id or "").strip() or None
        self.service_account_json = (service_account_json or "").strip() or None

    def _make_client(self):
        if not self.property_id or not self.service_account_json:
            raise GA4ApiError(NO_CREDENTIALS_MESSAGE)
        import json as _json

        from google.analytics.data_v1beta import BetaAnalyticsDataClient  # 延遲 import
        from google.oauth2 import service_account

        try:
            info = _json.loads(self.service_account_json)
        except ValueError:
            raise GA4ApiError("GA4 服務帳戶金鑰格式不對，確認貼上的是完整 JSON 內容。")
        try:
            credentials = service_account.Credentials.from_service_account_info(
                info, scopes=["https://www.googleapis.com/auth/analytics.readonly"])
            return BetaAnalyticsDataClient(credentials=credentials)
        except Exception:
            raise GA4ApiError("GA4 服務帳戶金鑰內容有問題，連不上 GA4。")

    def fetch_source_medium(self, since: str, until: str) -> list:
        """來源／媒介 × 工作階段／轉換／收益，期間內彙總。"""
        from google.analytics.data_v1beta.types import (
            DateRange,
            Dimension,
            Metric,
            RunReportRequest,
        )

        client = self._make_client()
        try:
            response = client.run_report(RunReportRequest(
                property=f"properties/{self.property_id}",
                dimensions=[Dimension(name="sessionSource"), Dimension(name="sessionMedium")],
                metrics=[Metric(name="sessions"), Metric(name="conversions"),
                        Metric(name="totalRevenue")],
                date_ranges=[DateRange(start_date=since, end_date=until)],
            ))
        except GA4ApiError:
            raise
        except Exception:
            raise GA4ApiError("連不上 GA4，可能是網路問題或金鑰權限不足。稍後再試一次。")

        rows = []
        for row in response.rows:
            rows.append(SourceMediumRow(
                source=row.dimension_values[0].value or "(not set)",
                medium=row.dimension_values[1].value or "(not set)",
                sessions=int(float(row.metric_values[0].value or 0)),
                conversions=float(row.metric_values[1].value or 0),
                revenue=float(row.metric_values[2].value or 0),
            ))
        return rows

    def purchase_event_seen(self, since: str, until: str) -> bool:
        """purchase 事件在指定期間內是否有收到——驗證「有沒有裝好」用（決策 0025 第 4 點）。"""
        from google.analytics.data_v1beta.types import (
            DateRange,
            Dimension,
            Filter,
            FilterExpression,
            Metric,
            RunReportRequest,
        )

        client = self._make_client()
        try:
            response = client.run_report(RunReportRequest(
                property=f"properties/{self.property_id}",
                dimensions=[Dimension(name="eventName")],
                metrics=[Metric(name="eventCount")],
                date_ranges=[DateRange(start_date=since, end_date=until)],
                dimension_filter=FilterExpression(filter=Filter(
                    field_name="eventName",
                    string_filter=Filter.StringFilter(value="purchase"))),
            ))
        except GA4ApiError:
            raise
        except Exception:
            raise GA4ApiError("連不上 GA4，可能是網路問題或金鑰權限不足。稍後再試一次。")
        return any(float(row.metric_values[0].value or 0) > 0 for row in response.rows)


class FakeGA4Client:
    """測試用：不發任何網路請求，回放注入的資料或拋出注入的錯誤。"""

    def __init__(self, rows=None, purchase_seen: bool = True, error: Exception | None = None):
        self._rows = rows or []
        self._purchase_seen = purchase_seen
        self.error = error
        self.calls: list = []

    def fetch_source_medium(self, since: str, until: str) -> list:
        self.calls.append(("source_medium", since, until))
        if self.error:
            raise self.error
        return list(self._rows)

    def purchase_event_seen(self, since: str, until: str) -> bool:
        self.calls.append(("purchase_seen", since, until))
        if self.error:
            raise self.error
        return self._purchase_seen
