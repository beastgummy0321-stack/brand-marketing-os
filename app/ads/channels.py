"""app/ads/channels.py — F03-I09: the channel registry (§0 决策 6「不寫死平台」). Campaign ->
通路 -> 投放組 -> 廣告 is the data model; the platform's own vocabulary only shows up here as a
label, never as a hard-coded branch anywhere else in `app/ads`. Private to app/ads (container
contract §1): only `routes.py` and `readiness.py` import this module's functions.
"""

from datetime import timedelta

from app.background import is_active as background_is_active
from app.core import settings as coresettings
from app.meta import daily_pull as meta_daily_pull
from app.meta import repository as meta_repo

CONNECTED = "connected"
NOT_CONNECTED = "未接上"

# F05-I11: budget_history 的退路來源名字——住在這裡，repository.py 只引用這個常數
# （§0「平台名字只准住在 channels.py」，test_ads_no_platform_literal.py 逐字檔案掃過）。
ACCOUNT_SOURCE = "meta_account"

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


def list_channels(conn, org_id: str, brand_id: str) -> list[dict]:
    """F05-I05：畫面要的通路清單——順序照 `CHANNELS`，每一列帶 `connected`（bool）與
    `state_text`（「已接上」／「未接上」，逐字給畫面印，不必知道平台名字）。"""
    result = []
    for channel in CHANNELS:
        state = connection_state(conn, org_id, brand_id, channel["key"])
        result.append({
            "key": channel["key"], "label": channel["label"],
            "connected": state == CONNECTED,
            "state_text": "已接上" if state == CONNECTED else "未接上",
        })
    return result


def default_channel_key(conn, org_id: str, brand_id: str, declared: str | None) -> str:
    """F05-I05：`app/ads/plan.py` 展開投放組時要一個通路 key，但不准自己寫死 `"meta"`。
    `declared`（Campaign 的 `constraints_json.platform`）在 `CHANNELS` 裡就用它；否則用這個
    品牌已接上的第一個通路；都沒有就退回 `CHANNELS[0]`（平台名字只准住在這個檔）。"""
    valid_keys = {c["key"] for c in CHANNELS}
    if declared in valid_keys:
        return declared
    for channel in CHANNELS:
        if connection_state(conn, org_id, brand_id, channel["key"]) == CONNECTED:
            return channel["key"]
    return CHANNELS[0]["key"]


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


def account_spend_history(
    conn, org_id: str, brand_id: str, conversion_goal: str | None,
) -> dict | None:
    """F05-I11: 這個品牌自己綁的廣告帳戶近 30 天真實花費——`app.ads.repository.budget_history`
    在迴圈自己沒有已結案花費時的退路（§8 第 5 條、演練四 V-13：「投放過」不該在系統眼裡等於
    「沒投放過」）。沒綁帳號，或這 30 天總花費是 0（沒補拉，或補拉完但真的沒花）→ `None`，
    誠實冷啟動；不用 ROAS 或客單價反推 CPA（呼叫端只認 `total["cpa"]` 原樣穿過）。
    `conversion_goal` 由呼叫端讀好傳進來（別的模組的表，容器規範不在這裡查），
    `spend_summary` 的 `level="campaign"` 語意就是這裡回的「帳戶層級」加總。
    「今天」用 `app.core.settings.today_for_org`，不是機器的 `date.today()`。

    F36-I05（演練六 #15，裁決 B）：`daily_spend` 的分母是**這 30 天窗裡真的有花費（> 0）的
    天數**，不是常數 30——只投 7 天的帳戶，日均不該被沒投放的 23 天稀釋。逐日花費讀
    `meta_repo.daily_entity_spend(level="campaign")` 再按 `spend_date` 加總；`days` 回的
    就是這個有花費天數，0 天＝沒有歷史（回 `None`）。窗仍是 30 天，CPA 仍沿用
    `spend_summary` 整段的誠實加總。

    F38 (decision 4): the account base stays on `meta_entity_spend`, not the sync table -- the
    sync table's monthly rows only hold campaigns bound to this brand, so unbound campaigns in
    the same account would be dropped and the base would undercount. The two sources stay; the
    caller's caption (`repository._account_history`) names this one as 「Meta 廣告帳戶全部活動」."""
    account_ids = meta_repo.bound_account_ids_for_brand(conn, org_id, brand_id)
    if not account_ids:
        return None
    today = coresettings.today_for_org(conn, org_id=org_id)
    since = today - timedelta(days=30)
    until = today + timedelta(days=1)
    spend_by_date: dict = {}
    for row in meta_repo.daily_entity_spend(
        conn, org_id, account_ids, since, until, level="campaign",
    ):
        spend_by_date[row["spend_date"]] = (
            spend_by_date.get(row["spend_date"], 0.0) + row["spend"]
        )
    days_with_spend = sum(1 for spend in spend_by_date.values() if spend > 0)
    if not days_with_spend:
        return None
    total_spend = sum(spend for spend in spend_by_date.values() if spend > 0)
    summary = meta_repo.spend_summary(
        conn, org_id, account_ids, since, until,
        level="campaign", conversion_goal=conversion_goal,
    )
    return {
        "cpa": summary["total"]["cpa"],
        "daily_spend": total_spend / days_with_spend,
        "days": days_with_spend,
        "channel_label": "Meta",
    }



def external_reader(platform):
    if platform == "meta":
        from app.ads.adapters.meta_read import MetaReader
        return MetaReader()
    if platform == "simulated":
        # F37 Contract R: the simulated channel reads like a platform; it is never a
        # user-facing row of `CHANNELS`.
        from app.ads.adapters.simulated_read import SimulatedReader
        return SimulatedReader()
    return None



def has_legacy_campaign_binding(platform, native_kind):
    """The old manual adapter stored only Meta campaign IDs on ads_campaign.external_id."""
    return platform == "meta" and native_kind == "campaign"
