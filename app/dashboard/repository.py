"""app/dashboard/repository.py — 跨品牌總覽彙整（票 02-overview-cards，規格 0001）。

接口鐵則：只透過各模組的公開查詢函式取數（app.brand_intelligence／app.orders／
app.core.interrupts），不直接對別層資料表下 SQL、不寫入任何資料表。

外殼切片（2026-08-28）：單品牌駕駛艙 `cockpit()` 與數字月報 `monthly_report()` 隨
`app/ads/` 一起刪掉——花費、ROAS、CAC、內容產線、最後同步時間全部來自廣告成效快照，
沒有成效資料就沒有這些數字（HANDOFF-shell-slice.md §3.8：v1 儀表板只顯示方案端數字）。
留下的只有跨品牌總覽 `overview()`。
"""

import calendar
from datetime import date

from app.brand_intelligence import repository as bi_repo
from app.core import interrupts as core_interrupts
from app.dashboard import guide_cards
from app.dashboard.health import brand_health
from app.intake import state as intake_state
from app.orders import repository as orders_repo


def _months_before(until: str, months: int) -> str:
    """`until` 往回推 `months` 個日曆月（比照使用者理解的「N 個月前」，不是 30N 天的近似值）。

    原本在 `app/ads/sync.py`，那支檔案刪掉後只剩本檔用得到，搬過來。用 stdlib
    calendar.monthrange 處理跨年與月底日期（例如 1/31 往回推一個月會夾到 2/28 或 2/29）。
    """
    d = date.fromisoformat(until)
    total = d.year * 12 + (d.month - 1) - months
    year, month0 = divmod(total, 12)
    month = month0 + 1
    day = min(d.day, calendar.monthrange(year, month)[1])
    return date(year, month, day).isoformat()


def _month_to_date_range(today: str) -> tuple:
    return today[:8] + "01", today


def _mom_pct(current, previous) -> float | None:
    """環比：current／previous 任一邊「沒得算」（None 或 0）就回 None，不硬除（鐵則 16）。"""
    return round((current - previous) / previous * 100, 1) if current is not None and previous else None


def _revenue_and_mom(conn, brand_id: str, today: str) -> tuple:
    """規格 KPI 口徑：本月營收＝訂單實收；環比＝與上月同期比較。

    上月同期抓不到（分母是 0 或 None）時環比回 None——「沒得算」跟「等於 0」是兩件事
    （鐵則 16，比照 app/orders/repository.py stats()）。
    """
    since, until = _month_to_date_range(today)

    def fetch(s, u):
        return orders_repo.stats(conn, brand_id, since=s, until=u, today=today)["net_revenue"]

    current = fetch(since, until)
    previous = fetch(_months_before(since, 1), _months_before(until, 1))
    return current, _mom_pct(current, previous)


# ---------------------------------------------------------------------------
# 下一步指南卡（票 04-guide-card-engine，規格 0001）：純函數引擎在
# app/dashboard/guide_cards.py，這裡只負責組 facts。facts 契約見 guide_cards.py 檔頭。
# ---------------------------------------------------------------------------


def _intake_draft_fact(conn, brand_id: str) -> dict | None:
    """票 B3-intake：這個品牌有沒有進行中的建檔精靈草稿——只轉 guide_cards 卡片需要的
    兩個欄位（step／resume_path），續接判斷沿用 `app/intake/state.py` 的 `_resume_path`，
    這裡不重算。"""
    draft = intake_state.get_draft(brand_id, conn)
    if not draft:
        return None
    return {"step": draft["step"], "resume_path": draft["resume_path"]}


def _guide_card_facts(conn, brand_id: str) -> dict:
    pending_facts = bi_repo.list_brand_facts(conn, brand_id, status="pending")
    brand = bi_repo.get_brand(conn, brand_id)
    return {
        "brand_id": brand_id,
        # 票 C：guide_cards.conversion_goal_missing 讀這個判斷方法論開關有沒有接電。
        "conversion_goal": brand["conversion_goal"] if brand else None,
        "pending_facts_count": len(pending_facts),
        "intake_draft": _intake_draft_fact(conn, brand_id),
    }


def _guide_cards(conn, brand_id: str) -> list:
    return guide_cards.build(_guide_card_facts(conn, brand_id))


def _brand_card(conn, brand: dict, today: str) -> dict:
    open_interrupts = core_interrupts.list_open(conn, brand_id=brand["id"], today=today,
                                                archive_stale=False)
    revenue, revenue_mom_pct = _revenue_and_mom(conn, brand["id"], today)
    cards = _guide_cards(conn, brand["id"])
    return {
        "brand_id": brand["id"],
        "brand_name": brand["name"],
        "health": brand_health(row["severity"] for row in open_interrupts),
        "revenue_this_month": revenue,
        "revenue_mom_pct": revenue_mom_pct,
        # 跨品牌總覽卡「最重要一件下一步」＝指南卡引擎排序後的第一筆（規格：
        # 「跨品牌總覽卡上的『最重要一件下一步』同時接上真貨源」）。
        "next_step": cards[0] if cards else None,
    }


def overview(conn, *, org_id: str, today: str | None = None) -> list:
    today = today or date.today().isoformat()
    brands = bi_repo.list_brands(conn, org_id, status="active")
    return [_brand_card(conn, brand, today) for brand in brands]
