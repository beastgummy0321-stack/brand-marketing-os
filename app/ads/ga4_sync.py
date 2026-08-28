"""app/ads/ga4_sync.py — GA4 服務帳戶同步（GitHub issue #34）。

比照 app/ads/sync.py（Meta）的骨架，但明顯更簡單：GA4 沒有「一個帳號服務多個品牌」
的歸屬認領問題（每個品牌設定自己的 GA4 資源編號），也不寫 performance_snapshot——
UTM 層（來源／媒介）資料寫進決策 0025 第 4 點指定的新表 ga4_summary／ga4_sync_status
（見 app/ads/migrations/0008_ga4.sql）。純資料同步，不呼叫 LLM、不登記 llm_task。
"""

from dataclasses import dataclass
from datetime import date, timedelta

from app.ads import ga4_api
from app.brand_intelligence import repository as bi
from app.core import settings as coresettings
from app.core.db import new_id, now_utc

PROPERTY_SETTING = "ga4_property_id"
SERVICE_ACCOUNT_SETTING = "ga4_service_account_json"

DEFAULT_LOOKBACK_DAYS = 30

# 決策 0039 第 3 條：GA4 回填沒有 Meta 那種寫死的官方月數上限——天花板是「這個 property
# 建立的那天」，因人而異、系統查不到（GA4 Data API 不會因為 since 早於建立日就報錯，
# 只會對還不存在的日子誠實回傳 0；GA4 Admin API 才能查到 property 建立日，但那是另一套
# 認證與依賴，超出本票「呼叫端薄改」範圍）。優雅降級＝不夾這一端、照樣送出請求，
# 完成後如實顯示「回填了 N 個月」（N＝實際請求的月數，不是猜測拿到多少真實資料）。


def get_property_id(conn) -> str | None:
    return coresettings.get_setting(conn, PROPERTY_SETTING) or None


def get_service_account_json(conn) -> str | None:
    return coresettings.get_setting(conn, SERVICE_ACCOUNT_SETTING) or None


def is_configured(conn) -> bool:
    return bool(get_property_id(conn) and get_service_account_json(conn))


def make_client(conn) -> ga4_api.GA4Client:
    return ga4_api.GA4Client(get_property_id(conn), get_service_account_json(conn))


@dataclass
class GA4SyncResult:
    rows: int = 0
    purchase_event_seen: bool | None = None
    error: str | None = None


def sync_brand(conn, brand_id: str, actor: str, *, client=None,
               since: str | None = None, until: str | None = None,
               today: str | None = None, on_stage=None) -> GA4SyncResult:
    """把這個品牌 GA4 資源的來源／媒介成效抓回來。失敗一律回帶 error 的結果，不拋例外、
    不半途留髒資料（比照 app/ads/sync.py sync_account 同一套防呆）。"""
    brand = bi.get_brand(conn, brand_id)
    if brand is None:
        raise ValueError(f"找不到品牌：{brand_id}")
    org_id = brand["org_id"]
    if not is_configured(conn):
        return GA4SyncResult(error=ga4_api.NO_CREDENTIALS_MESSAGE)

    client = client or make_client(conn)
    today = today or date.today().isoformat()
    until = until or today
    since = since or (date.fromisoformat(until) - timedelta(days=DEFAULT_LOOKBACK_DAYS)).isoformat()

    if on_stage:
        on_stage("connect")
    try:
        if on_stage:
            on_stage("fetch")
        rows = client.fetch_source_medium(since, until)
        purchase_seen = client.purchase_event_seen(since, until)
    except ga4_api.GA4ApiError as exc:
        return GA4SyncResult(error=str(exc))

    if on_stage:
        on_stage("save")
    ts = now_utc()
    # 每次同步先清掉同一品牌、同一期間的舊列再整批寫入——GA4 彙總是「這段期間的最終數字」，
    # 不是逐日累加的時序資料，重覆同步同一期間要覆蓋而不是疊加。
    conn.execute(
        "DELETE FROM ga4_summary WHERE brand_id = %s AND date_range_start = %s AND date_range_end = %s",
        (brand_id, since, until),
    )
    for row in rows:
        conn.execute(
            "INSERT INTO ga4_summary (id, org_id, brand_id, date_range_start, date_range_end, source,"
            " medium, sessions, conversions, revenue, synced_at, created_at)"
            " VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
            (new_id("ga4"), org_id, brand_id, since, until, row.source, row.medium,
             row.sessions, row.conversions, row.revenue, ts, ts),
        )
    conn.execute(
        "INSERT INTO ga4_sync_status (org_id, brand_id, date_range_start, date_range_end, row_count,"
        " purchase_event_seen, synced_at, updated_at) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)"
        " ON CONFLICT(brand_id) DO UPDATE SET date_range_start = excluded.date_range_start,"
        " date_range_end = excluded.date_range_end, row_count = excluded.row_count,"
        " purchase_event_seen = excluded.purchase_event_seen, synced_at = excluded.synced_at,"
        " updated_at = excluded.updated_at",
        (org_id, brand_id, since, until, len(rows), bool(purchase_seen), ts, ts),
    )
    conn.commit()
    return GA4SyncResult(rows=len(rows), purchase_event_seen=purchase_seen)


def latest_summary(conn, brand_id: str) -> list:
    """這個品牌最新一次同步的來源／媒介彙總列，工作階段數高的排前面。"""
    status = get_sync_status(conn, brand_id)
    if status is None:
        return []
    return [dict(r) for r in conn.execute(
        "SELECT * FROM ga4_summary WHERE brand_id = %s AND date_range_start = %s"
        " AND date_range_end = %s ORDER BY sessions DESC",
        (brand_id, status["date_range_start"], status["date_range_end"]),
    )]


def get_sync_status(conn, brand_id: str) -> dict | None:
    row = conn.execute(
        "SELECT * FROM ga4_sync_status WHERE brand_id = %s", (brand_id,)
    ).fetchone()
    return dict(row) if row else None
