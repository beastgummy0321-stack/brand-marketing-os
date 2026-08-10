# -*- coding: utf-8 -*-
"""app/dashboard/repository.py — 跨品牌總覽彙整（票 02-overview-cards，規格 0001）。

接口鐵則：只透過各模組的公開查詢函式取數（app.brand_intelligence／app.orders／
app.ads／app.core.interrupts／app.core.campaign_skip／app.core.calendar_dismiss），
不直接對別層資料表下 SQL、不寫入任何資料表（本檔只呼叫 campaign_skip.get_skip()／
calendar_dismiss.list_dismissed() 讀，不呼叫任一模組的寫入函式）。
"""

from calendar import monthrange
from datetime import date
from typing import Optional

from app.ads import creative_pipeline as ads_creative_pipeline
from app.ads import ga4_sync as ads_ga4_sync
from app.ads import nextcycle as ads_nextcycle
from app.ads import performance as ads_performance
from app.ads import reading as ads_reading
from app.ads import repository as ads_repo
from app.ads import stages as ads_stages
from app.ads import sync as ads_sync
from app.ads.routes_common import CYCLE_STATUS_LABELS, derive_cycle_stage
from app.brand_intelligence import repository as bi_repo
from app.core import calendar_dismiss as core_calendar_dismiss
from app.core import campaign_skip as core_campaign_skip
from app.core import interrupts as core_interrupts
from app.core import settings as core_settings
from app.dashboard import campaign_calendar
from app.dashboard import guide_cards
from app.dashboard.health import brand_health
from app.orders import repository as orders_repo

# 迷你趨勢線／主圖月數（票 03-cockpit-kpi-chart）：半年給得出趨勢形狀，不必逐日。
_TREND_MONTHS = 6


def _month_to_date_range(today: str) -> tuple:
    return today[:8] + "01", today


def _and_mom(today: str, fetch) -> tuple:
    """KPI 通用形狀：本月至今值＋與上月同期環比。fetch(since, until) 回該區間的值。

    上月同期抓不到（沒有上月資料，分母是 0 或 None）時環比回 None——「沒得算」跟
    「等於 0」是兩件事（鐵則 16，比照 app/orders/repository.py stats()）。
    """
    since, until = _month_to_date_range(today)
    current = fetch(since, until)
    previous = fetch(ads_sync.months_before(since, 1), ads_sync.months_before(until, 1))
    return current, _mom_pct(current, previous)


def _revenue_and_mom(conn, brand_id: str, today: str) -> tuple:
    """規格 KPI 口徑：本月營收＝訂單實收；環比＝與上月同期比較。"""
    return _and_mom(today, lambda s, u: orders_repo.stats(
        conn, brand_id, since=s, until=u, today=today)["net_revenue"])


def _latest_cycle(conn, brand_id: str) -> Optional[dict]:
    """最新一期未封存的檔期（依 list_cycles 既有排序：start_date DESC）。沒有任何檔期就
    回 None——「還沒開過檔期」跟「這期沒在投放」是兩件事，但本票只做狀態呈現，
    細分留給 03／04。"""
    cycles = ads_repo.list_cycles(conn, brand_id)
    return cycles[0] if cycles else None


def _cycle_summary(cycle: Optional[dict]) -> Optional[dict]:
    if not cycle:
        return None
    return {
        "id": cycle["id"],
        "status": cycle["status"],
        "status_label": CYCLE_STATUS_LABELS.get(cycle["status"], cycle["status"]),
    }


# ---------------------------------------------------------------------------
# 下一步指南卡（票 04-guide-card-engine，規格 0001）：純函數引擎在
# app/dashboard/guide_cards.py，這裡只負責組 facts。接口鐵則：只透過各模組的公開
# 查詢函式取數——derive_cycle_stage 是 app.ads.routes_common 公開函式（本票把它從
# 私有改公開），facts 契約見 guide_cards.py 檔頭說明。
#
# events（票 06-campaign-calendar 檔期資料）預設吃 campaign_calendar.load_events()
# 讀內建 JSON；overview()／cockpit() 開 calendar_events 這個測試縫（HTTP API 不暴露，
# routes.py 呼叫時一律用預設值）——真實檔期日期是外部世界的事實，沒辦法像訂單那樣
# 隨測試「今天」調整，才需要這個縫讓純函數情境測試以外的整合測試可控。
# ---------------------------------------------------------------------------

def _cycle_stage_label(conn, brand_id: str, cycle: dict) -> Optional[str]:
    """stage_label 為 None＝已經在成效格（第 5 格），指南卡不算「卡住」。"""
    stage_index = derive_cycle_stage(conn, brand_id, cycle)
    return ads_stages.STAGE_LABELS[stage_index - 1] if stage_index < 5 else None


_PACING_CATEGORIES = {"pacing_overspend": "overspend", "pacing_underspend": "underspend"}


def _pacing_alert(conn, brand_id: str, today: str) -> Optional[dict]:
    """未結的 pacing 打斷事件轉成指南卡 facts（規格：pacing 警示是指南卡貨源之一）。
    list_open 已按嚴重度排序，取第一筆 pacing 類即可。"""
    rows = core_interrupts.list_open(conn, brand_id=brand_id, today=today, archive_stale=False)
    for row in rows:
        kind = _PACING_CATEGORIES.get(row["category"])
        if kind:
            return {"kind": kind, "action_url": row["action_url"]}
    return None


# 票 03-cycle-skip-record（ADR 0015）：next_calendar_reminder() 選中的那張提醒卡，
# 若去年同一節日有跳過紀錄，附帶顯示去年的理由——純脈絡顯示，跟 app/ads/nextcycle.py
# 下期建議引擎完全無關（這裡只讀 campaign_skip，不寫、不影響任何演算法輸入）。
def _attach_last_year_skip(conn, brand_id: str, reminder: Optional[dict],
                            events: list) -> Optional[dict]:
    if not reminder:
        return reminder
    event = next((e for e in events if e["id"] == reminder["id"]), None)
    if not event:
        return reminder
    event_year = date.fromisoformat(event["date"]).year
    skip = core_campaign_skip.get_skip(
        conn, brand_id, campaign_calendar.holiday_id(event["id"]), event_year - 1)
    if not skip:
        return reminder
    return {**reminder, "last_year_skipped": True, "last_year_skip_reason": skip["reason"]}


def _guide_card_facts(conn, brand_id: str, cycle: Optional[dict], today: str, events: list) -> dict:
    pending_facts = bi_repo.list_brand_facts(conn, brand_id, status="pending")
    brand = bi_repo.get_brand(conn, brand_id)
    active_cycle = None
    reading_ready = False
    next_cycle_draft_ready = False
    if cycle:
        active_cycle = {"id": cycle["id"], "stage_label": _cycle_stage_label(conn, brand_id, cycle)}
        reading_ready = bool(ads_reading.load(conn, brand_id, cycle["id"])["cycle"])
        next_cycle_draft_ready = ads_nextcycle.load(conn, brand_id, cycle["id"]) is not None
    campaign_reminder = campaign_calendar.next_calendar_reminder(
        events, date.fromisoformat(today), brand["industry"] if brand else None,
        dismissed_categories=core_calendar_dismiss.list_dismissed(conn, brand_id))
    return {
        "brand_id": brand_id,
        # 票 C：guide_cards.conversion_goal_missing 讀這個判斷方法論開關有沒有接電。
        "conversion_goal": brand["conversion_goal"] if brand else None,
        "pending_facts_count": len(pending_facts),
        "active_cycle": active_cycle,
        "reading_ready": reading_ready,
        "next_cycle_draft_ready": next_cycle_draft_ready,
        "campaign_reminder": _attach_last_year_skip(conn, brand_id, campaign_reminder, events),
        "pacing_alert": _pacing_alert(conn, brand_id, today),
    }


def _guide_cards(conn, brand_id: str, cycle: Optional[dict], today: str, events: list) -> list:
    return guide_cards.build(_guide_card_facts(conn, brand_id, cycle, today, events))


def _brand_card(conn, brand: dict, today: str, events: list) -> dict:
    open_interrupts = core_interrupts.list_open(conn, brand_id=brand["id"], today=today,
                                                archive_stale=False)
    revenue, revenue_mom_pct = _revenue_and_mom(conn, brand["id"], today)
    cycle = _latest_cycle(conn, brand["id"])
    cards = _guide_cards(conn, brand["id"], cycle, today, events)
    return {
        "brand_id": brand["id"],
        "brand_name": brand["name"],
        "health": brand_health(row["severity"] for row in open_interrupts),
        "revenue_this_month": revenue,
        "revenue_mom_pct": revenue_mom_pct,
        "active_cycle": _cycle_summary(cycle),
        # 跨品牌總覽卡「最重要一件下一步」＝指南卡引擎排序後的第一筆（規格：
        # 「跨品牌總覽卡上的『最重要一件下一步』同時接上真貨源」）。
        "next_step": cards[0] if cards else None,
    }


def overview(conn, *, today: Optional[str] = None, calendar_events: Optional[list] = None) -> list:
    today = today or date.today().isoformat()
    events = calendar_events if calendar_events is not None else campaign_calendar.load_events()
    brands = bi_repo.list_brands(conn, status="active")
    return [_brand_card(conn, brand, today, events) for brand in brands]


# ---------------------------------------------------------------------------
# 單品牌駕駛艙（票 03-cockpit-kpi-chart）：四張 KPI 卡＋營收 vs 花費疊線主圖。
# KPI 口徑（規格 0001）：本月營收＝訂單實收；花費＝成效快照 spend 加總；
# ROAS 取自 derived_metric；環比＝與上月同期比較。
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# 警示區＋AI 油錢錶＋內容產線小計（票 05-alerts-fuel-pipeline）。警示區直接讀打斷
# 佇列，不另建通知機制；「知道了」／「詳情」沿用既有 core_interrupts.resolve() 與
# action_url（前端直接打既有 `/interrupts/{id}/resolve`，本模組不重寫、不寫入）。
# ---------------------------------------------------------------------------

def _alerts(conn, brand_id: str, today: str) -> list:
    """異常警示區：list_open() 本身已按嚴重度排序（app/core/interrupts.py _sort_key），
    這裡只挑畫面要的欄位。archive_stale=False：唯讀呼叫端不順手改資料庫狀態。"""
    rows = core_interrupts.list_open(conn, brand_id=brand_id, today=today, archive_stale=False)
    return [{"id": r["id"], "severity": r["severity"], "message": r["message"],
            "action_url": r["action_url"]} for r in rows]


def _fuel_gauge(conn, brand_id: str, today: str) -> dict:
    """AI 油錢錶：本月已花（llm_task 成本紀錄，since＝當月 1 號）／上限（全站共用設定）。"""
    since, _until = _month_to_date_range(today)
    return {
        "spent_this_month": core_settings.brand_llm_spent(conn, brand_id, since=since),
        "limit": core_settings.get_intake_budget_limit(conn),
    }

def _mom_pct(current, previous) -> Optional[float]:
    """環比：current／previous 任一邊「沒得算」（None 或 0）就回 None，不硬除
    （鐵則 16，比照 `_revenue_and_mom`）。"""
    return round((current - previous) / previous * 100, 1) if current is not None and previous else None


def _spend_and_mom(conn, brand_id: str, today: str) -> tuple:
    return _and_mom(today, lambda s, u: ads_performance.brand_period_spend(conn, brand_id, s, u))


def _roas_and_mom(conn, brand_id: str, today: str) -> tuple:
    return _and_mom(today, lambda s, u: ads_performance.latest_derived_metric(
        conn, brand_id, "roas", s, u))


def _orders_and_mom(conn, brand_id: str, today: str) -> tuple:
    return _and_mom(today, lambda s, u: orders_repo.stats(
        conn, brand_id, since=s, until=u, today=today)["order_count"])


def _month_bounds(month: str) -> tuple:
    """'YYYY-MM' → 該月第一天／最後一天的 'YYYY-MM-DD'。"""
    year, mon = int(month[:4]), int(month[5:7])
    return f"{month}-01", f"{month}-{monthrange(year, mon)[1]:02d}"


def _months_window(today: str, n: int) -> list:
    """今天所在月份往前數 n 個日曆月（含當月），依時間升冪排列。"""
    months, cursor = [], today[:7]
    for _ in range(n):
        months.append(cursor)
        cursor = ads_sync.months_before(f"{cursor}-01", 1)[:7]
    months.reverse()
    return months


def _monthly_trend(conn, brand_id: str, months: list) -> dict:
    """迷你趨勢線／主圖用的月度序列。缺資料的月份留 None——「沒得算」跟「等於 0」
    是兩件事，前端要能畫出「這個月沒資料」而不是誤畫成 0（鐵則 16；本票邊界測試：
    只有部分月份有資料）。"""
    revenue, spend, roas, orders = [], [], [], []
    for month in months:
        since, until = _month_bounds(month)
        month_stats = orders_repo.stats(conn, brand_id, since=since, until=until)
        revenue.append(month_stats["net_revenue"])
        orders.append(month_stats["order_count"])
        spend.append(ads_performance.brand_period_spend(conn, brand_id, since, until))
        roas.append(ads_performance.latest_derived_metric(conn, brand_id, "roas", since, until))
    return {"revenue": revenue, "spend": spend, "roas": roas, "orders": orders}


# ---------------------------------------------------------------------------
# 最後同步時間（票 07-auto-sync）：Meta 快照抓取時間與 GA4 同步時間取較新的一筆，
# 給駕駛艙標示數據新舊——「超過一天沒同步」用 data_stale 提醒使用者，不是默默沿用
# 舊數字（規格 0001）。
# ---------------------------------------------------------------------------

def _last_sync_at(conn, brand_id: str) -> Optional[str]:
    candidates = [ts for ts in (
        ads_performance.last_snapshot_at(conn, brand_id),
        (ads_ga4_sync.get_sync_status(conn, brand_id) or {}).get("synced_at"),
    ) if ts]
    return max(candidates) if candidates else None


def _is_data_stale(last_sync_at: Optional[str], today: str) -> bool:
    """從沒同步過，或最後一次同步不是今天，都算「數據可能過期」。

    ponytail: 用日期粒度比對（同步日期不是今天就算過期），不做到時分秒精算——本檔其餘
    環比／檔期判定也都是日期粒度；真要抓「剛過凌晨幾分鐘」這種邊界，再升級成完整
    時間戳比對。"""
    return not last_sync_at or last_sync_at[:10] < today


def cockpit(conn, brand_id: str, *, today: Optional[str] = None,
            calendar_events: Optional[list] = None) -> dict:
    today = today or date.today().isoformat()
    events = calendar_events if calendar_events is not None else campaign_calendar.load_events()
    revenue, revenue_mom = _revenue_and_mom(conn, brand_id, today)
    spend, spend_mom = _spend_and_mom(conn, brand_id, today)
    roas, roas_mom = _roas_and_mom(conn, brand_id, today)
    orders, orders_mom = _orders_and_mom(conn, brand_id, today)

    months = _months_window(today, _TREND_MONTHS)
    trend = _monthly_trend(conn, brand_id, months)

    cycle = _latest_cycle(conn, brand_id)
    last_sync_at = _last_sync_at(conn, brand_id)
    brand = bi_repo.get_brand(conn, brand_id)
    return {
        "kpis": {
            "revenue": {"value": revenue, "mom_pct": revenue_mom, "trend": trend["revenue"]},
            "spend": {"value": spend, "mom_pct": spend_mom, "trend": trend["spend"]},
            "roas": {"value": roas, "mom_pct": roas_mom, "trend": trend["roas"]},
            "orders": {"value": orders, "mom_pct": orders_mom, "trend": trend["orders"]},
        },
        "chart": {"months": months, "revenue": trend["revenue"], "spend": trend["spend"]},
        # 駕駛艙常駐下一步指南卡（票 04-guide-card-engine）：最多 3 件，沒有待辦是空清單，
        # 前端顯示「一切正常」。
        "guide_cards": _guide_cards(conn, brand_id, cycle, today, events),
        # 票 06-campaign-calendar：進行中檔期目前處於遠期備戰／中期備戰／近期備戰哪個階段
        # （{id, name, tier, tier_label, stage, days_until}）；沒有檔期在窗口內是 None。
        "campaign_stage": campaign_calendar.current_campaign_stage(
            events, date.fromisoformat(today), brand["industry"] if brand else None,
            dismissed_categories=core_calendar_dismiss.list_dismissed(conn, brand_id)),
        # 票 05-alerts-fuel-pipeline：異常警示區（空清單＝前端顯示「一切正常」）／
        # AI 油錢錶／內容產線小計。
        "alerts": _alerts(conn, brand_id, today),
        "fuel_gauge": _fuel_gauge(conn, brand_id, today),
        "content_pipeline": ads_creative_pipeline.pipeline_counts(conn, brand_id),
        # 票 07-auto-sync：最後同步時間／是否可能過期（Meta 快照抓取時間或 GA4 同步
        # 時間取較新者；從沒同步過也算過期）。
        "last_sync_at": last_sync_at,
        "data_stale": _is_data_stale(last_sync_at, today),
    }
