"""app/ads/channels.py — F03-I09: the channel registry (§0 决策 6「不寫死平台」). Campaign ->
通路 -> 投放組 -> 廣告 is the data model; the platform's own vocabulary only shows up here as a
label, never as a hard-coded branch anywhere else in `app/ads`. Private to app/ads (container
contract §1): only `routes.py` and `readiness.py` import this module's functions.
"""

from app.background import is_active as background_is_active
from app.meta import daily_pull as meta_daily_pull
from app.meta import repository as meta_repo

CONNECTED = "connected"
NOT_CONNECTED = "未接上"

# F03 決策 6：通路清單不等於「已接上的通路」——這版只有 meta 真的接得上，其餘四個原樣列出、
# 一律回報「未接上」，不是從畫面藏起來（§0「every other channel reports 未接上 from data」）。
CHANNELS = [
    {"key": "meta", "label": "Meta"},
    {"key": "google_ads", "label": "Google Ads"},
    {"key": "tiktok", "label": "TikTok"},
    {"key": "shopee", "label": "蝦皮"},
    {"key": "momo", "label": "momo"},
]


def connection_state(conn, org_id: str, brand_id: str, channel_key: str) -> str:
    """`connected`／`未接上`——目前只有 `meta` 有資料可以回答（這個品牌有沒有綁 Meta 廣告
    帳戶，`app/meta/repository.py::bound_account_ids_for_brand`），其餘通路沒有任何連線資料
    可查，原樣回 `未接上`。沒有平台專屬分支：這支只認得「有沒有資料」，不是某個通路的名字。
    """
    if channel_key == "meta":
        account_ids = meta_repo.bound_account_ids_for_brand(conn, org_id, brand_id)
        return CONNECTED if account_ids else NOT_CONNECTED
    return NOT_CONNECTED


def account_state(conn, org_id: str, brand_id: str) -> dict | None:
    """F05-I04：可投放檢查表要問「這個品牌有沒有一個接上的廣告帳戶」而不必知道是哪個平台。
    目前只有 `meta` 真的接得上（同 `connection_state`），其餘四個通路沒有帳戶資料，回 `None`
    （＝沒綁）。`backfill_done` 誠實地讀既有的 `daily_pull.backfill_status`：跑過至少一次
    （有花費列）且目前沒有補拉正在跑，才算「拉完了」——沒資料或還在跑都算沒完成，budget
    history 才不會拿半吊子的花費資料當近 30 天基準。"""
    account_ids = meta_repo.bound_account_ids_for_brand(conn, org_id, brand_id)
    if not account_ids:
        return None
    lock = meta_daily_pull.backfill_lock(org_id)
    running = background_is_active(lock)
    status = meta_daily_pull.backfill_status(conn, org_id, account_ids)
    done = (not running) and status["ad_rows"] > 0
    return {
        "channel_key": "meta", "label": "Meta",
        "backfill_done": done, "backfill_running": running,
    }
