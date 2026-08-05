# -*- coding: utf-8 -*-
"""app/dashboard/repository.py — 跨品牌總覽彙整（票 02-overview-cards，規格 0001）。

接口鐵則：只透過各模組的公開查詢函式取數（app.brand_intelligence／app.orders／
app.ads／app.core.interrupts），不直接對別層資料表下 SQL、不寫入任何資料表。
"""

from datetime import date
from typing import Optional

from app.ads import repository as ads_repo
from app.ads import sync as ads_sync
from app.ads.routes_common import CYCLE_STATUS_LABELS
from app.brand_intelligence import repository as bi_repo
from app.core import interrupts as core_interrupts
from app.dashboard.health import brand_health
from app.orders import repository as orders_repo


def _month_to_date_range(today: str) -> tuple:
    return today[:8] + "01", today


def _revenue_and_mom(conn, brand_id: str, today: str) -> tuple:
    """本月至今營收與環比（規格 KPI 口徑：本月營收＝訂單實收；環比＝與上月同期比較）。

    上月同期抓不到（沒有上月資料，分母是 0 或 None）時環比回 None——「沒得算」跟
    「等於 0」是兩件事（鐵則 16，比照 app/orders/repository.py stats()）。
    """
    since, until = _month_to_date_range(today)
    current = orders_repo.stats(conn, brand_id, since=since, until=until, today=today)["net_revenue"]
    prev_since = ads_sync.months_before(since, 1)
    prev_until = ads_sync.months_before(until, 1)
    previous = orders_repo.stats(conn, brand_id, since=prev_since, until=prev_until,
                                 today=today)["net_revenue"]
    mom_pct = round((current - previous) / previous * 100, 1) if current is not None and previous else None
    return current, mom_pct


def _active_cycle_summary(conn, brand_id: str) -> Optional[dict]:
    """最新一期未封存的檔期（依 list_cycles 既有排序：start_date DESC）。沒有任何檔期就
    回 None——「還沒開過檔期」跟「這期沒在投放」是兩件事，但本票只做狀態呈現，
    細分留給 03／04。"""
    cycles = ads_repo.list_cycles(conn, brand_id)
    if not cycles:
        return None
    cycle = cycles[0]
    return {
        "id": cycle["id"],
        "status": cycle["status"],
        "status_label": CYCLE_STATUS_LABELS.get(cycle["status"], cycle["status"]),
    }


def _brand_card(conn, brand: dict, today: str) -> dict:
    open_interrupts = core_interrupts.list_open(conn, brand_id=brand["id"], today=today,
                                                archive_stale=False)
    revenue, revenue_mom_pct = _revenue_and_mom(conn, brand["id"], today)
    return {
        "brand_id": brand["id"],
        "brand_name": brand["name"],
        "health": brand_health(row["severity"] for row in open_interrupts),
        "revenue_this_month": revenue,
        "revenue_mom_pct": revenue_mom_pct,
        "active_cycle": _active_cycle_summary(conn, brand["id"]),
        "next_step": None,  # 本票先留位，04-guide-card-engine 接上真貨源
    }


def overview(conn, *, today: Optional[str] = None) -> list:
    today = today or date.today().isoformat()
    brands = bi_repo.list_brands(conn, status="active")
    return [_brand_card(conn, brand, today) for brand in brands]
