"""週報只組既有資料，不另存一份報表或建立第二條資料管線。"""

from datetime import date, timedelta

from app.ads import performance as ads_performance
from app.ads import reading as ads_reading
from app.ads import weekly_proposals
from app.brand_intelligence import repository as bi_repo
from app.core import interrupts as core_interrupts


def _week_bounds(today: str) -> tuple[str, str]:
    # 週一產出的是剛結束的週一到週日，不能把尚未發生的本週資料混進去。
    end = date.fromisoformat(today) - timedelta(days=1)
    start = end - timedelta(days=end.weekday())
    return start.isoformat(), (start + timedelta(days=6)).isoformat()


def _order_stats(conn, brand_id: str, since: str, until: str) -> dict:
    """訂單沿用 app.main 已注入到判讀模組的既有 repository，ads 不直接 import orders。"""
    if ads_reading.orders_repo is None:
        raise RuntimeError("訂單資料尚未接上")
    return ads_reading.orders_repo.stats(conn, brand_id, since=since, until=until, today=until)


def _primary_card(cards: list[dict]) -> dict:
    """固定規則，不讓 AI 臨時決定：先阻止損失，再按可省下的額度選一張。

    既有週提案中「停掉」已是最高風險的止損動作；同類多張時才比既有的預估額度。
    """
    risk_rank = {"停掉": 3, "換素材": 2, "加碼": 1}
    return max(
        cards,
        key=lambda card: (
            risk_rank.get(card.get("action"), 0),
            float(card.get("estimated_saving") or card.get("suggested_amount") or 0),
        ),
    )


def assemble(conn, brand_id: str, cycle_id: str, *, today: str) -> dict | None:
    """組四行週報；任一必要來源未齊就回 None，絕不交出半份報告。"""
    week_start, week_end = _week_bounds(today)
    spend = ads_performance.brand_period_spend(conn, brand_id, week_start, week_end)
    orders = _order_stats(conn, brand_id, week_start, week_end)
    reading = ads_reading.load(conn, brand_id, cycle_id)
    cards = [
        card for card in weekly_proposals.list_cards(conn, brand_id, cycle_id)
        if card.get("status") == "GENERATED"
    ]
    keep = (reading.get("cycle") or {}).get("llm_explanation")
    if spend is None or not orders.get("has_history") or not keep or not cards:
        return None

    primary = _primary_card(cards)
    other = [card["id"] for card in cards if card["id"] != primary["id"]]
    return {
        "week_start": week_start,
        "week_end": week_end,
        "spend": spend,
        "orders": orders["order_count"],
        "revenue": orders["net_revenue"] if orders["net_revenue"] is not None else 0,
        "keep": keep,
        "primary_proposal_id": primary["id"],
        "primary_copy": weekly_proposals.present(primary, brand_id)["copy"],
        "other_count": len(other),
        "other_proposal_ids": other,
    }


def enqueue_if_ready(conn, brand_id: str, cycle_id: str, *, today: str) -> str | None:
    """同一週報只提醒一次；資料補齊後由既有同步／週引擎再次呼叫就會自動補上。"""
    report = assemble(conn, brand_id, cycle_id, today=today)
    if report is None:
        return None
    interrupt_id = core_interrupts.enqueue(
        conn,
        org_id=bi_repo.get_brand(conn, brand_id)["org_id"],
        category="weekly_report_ready",
        dedupe_key=f"weekly_report_ready:{cycle_id}:{report['week_start']}",
        message="本週報告好了",
        brand_id=brand_id,
        campaign_cycle_id=cycle_id,
    )
    if interrupt_id:
        conn.commit()
    return interrupt_id
