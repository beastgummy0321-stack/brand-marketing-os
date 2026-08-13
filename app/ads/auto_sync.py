# -*- coding: utf-8 -*-
"""app/ads/auto_sync.py — 每日自動同步觸發器（票 07-auto-sync，規格 0001）。

沿用既有唯讀同步邏輯：Meta 帳號同步（app/ads/sync.py `sync_account`，全站一組連線、
一次涵蓋所有已認領品牌，比照手動同步鈕 `/brands/{b}/ads/sync` 的既有呼叫方式）＋
GA4 每品牌同步（app/ads/ga4_sync.py `sync_brand`，比照手動同步鈕 `/brands/{b}/ads/ga4/sync`）。
唯一差別是觸發者從「使用者按鈕」換成「排程呼叫這支函式」；不設定連線就跳過、不報錯。

失敗不拋例外、也不讓一個品牌的失敗擋住其他品牌：各自的同步結果各自處理，
失敗才送進打斷佇列（`auto_sync_failed` 類別，見 app/core/interrupts.py CATEGORIES）。
"""

from datetime import date, datetime, timedelta, timezone
from typing import Optional

from app.ads import ga4_sync
from app.ads import onboarding
from app.ads import pacing_curve
from app.ads import reading
from app.ads import repository as ads_repo
from app.ads import sync as ads_sync
from app.ads import tracking
from app.brand_intelligence import repository as bi_repo
from app.core import interrupts as core_interrupts

ACTOR = "auto_sync"

# 打斷佇列卡片內文上限 30 全形字（app/core/interrupts.py MAX_MESSAGE_LEN）——固定短句，
# 不把原始錯誤訊息塞進去（原始錯誤訊息通常較長且長度不可控，沿用其他模組固定短句的作法）。
_META_FAILURE_MESSAGE = "Meta 自動同步失敗，去設定頁看看。"
_GA4_FAILURE_MESSAGE = "GA4 自動同步失敗，去看看。"
_IMMEDIATE_SYNC_DEBOUNCE = timedelta(seconds=30)
_immediate_sync_cache = {}


def check_schedule_reminder(conn, brand_id: str, cycle_id: str, today: str):
    """排程與畫面共用同一條到期提醒路徑。"""
    cycle = ads_repo.get_cycle(conn, brand_id, cycle_id)
    if not cycle:
        return None
    plan = ads_repo.derived_plan(cycle)
    reminder = pacing_curve.due_schedule_change(cycle, plan.get("daily_budgets") or [], today)
    if reminder:
        core_interrupts.enqueue(
            conn, category="pacing_schedule_due", dedupe_key=f"schedule:{cycle_id}:{today}",
            brand_id=brand_id, message=reminder["copy_text"][:30],
            action_url=f"/brands/{brand_id}/ads/{cycle_id}",
        )
    return reminder


def run_due_readings(conn, brand_id: str, today: str) -> None:
    """用既有到期提醒觸發第 7 天判讀與期末結算。"""
    for reminder in onboarding.due_reminders(conn, brand_id, today=today):
        if reminder["kind"] == "day7_report":
            reading.run(conn, brand_id, reminder["campaign_cycle_id"], ACTOR)
        elif reminder["kind"] == "final_settlement":
            ok, _ = reading.finalize(
                conn, brand_id, reminder["campaign_cycle_id"], ACTOR,
            )
            if ok:
                core_interrupts.resolve(conn, reminder["id"], actor=ACTOR)


def run_cycle_checks(conn, brand_id: str, today: str, *, url_probe=None) -> None:
    for cycle in ads_repo.list_cycles(conn, brand_id):
        if cycle["status"] in ("LIVE", "EVALUATING"):
            check_schedule_reminder(conn, brand_id, cycle["id"], today)
    run_due_readings(conn, brand_id, today)
    tracking.run_post_sync_checks(conn, brand_id, today=today, url_probe=url_probe)


def sync_brand_now(conn, brand_id: str, actor: str, *, meta_client=None, ga4_client=None,
                   now: Optional[datetime] = None, url_probe=None) -> str:
    """同步單一品牌；30 秒內重按直接沿用同一次完成時間。"""
    now = now or datetime.now(timezone.utc)
    cached = _immediate_sync_cache.get(brand_id)
    if cached and now - cached[0] < _IMMEDIATE_SYNC_DEBOUNCE:
        return cached[1]
    today = now.date().isoformat()
    if ads_sync.is_configured(conn):
        meta_result = ads_sync.sync_account(
            conn, actor, client=meta_client, today=today, brand_id_filter=brand_id)
        if meta_result.error:
            raise ValueError(meta_result.error)
    if ga4_sync.is_configured(conn):
        ga4_result = ga4_sync.sync_brand(conn, brand_id, actor, client=ga4_client, today=today)
        if ga4_result.error:
            raise ValueError(ga4_result.error)
    run_cycle_checks(conn, brand_id, today, url_probe=url_probe)
    completed_at = now.isoformat()
    _immediate_sync_cache[brand_id] = (now, completed_at)
    conn.commit()
    return completed_at


def run(conn, *, today: Optional[str] = None, meta_client=None, ga4_client=None,
        url_probe=None) -> dict:
    """跑一輪每日自動同步。回傳 {"meta": SyncResult|None, "ga4": {brand_id: GA4SyncResult}}
    給呼叫端（測試、未來的執行紀錄）檢查跑了什麼。"""
    today = today or date.today().isoformat()
    outcome = {"meta": None, "ga4": {}}

    if ads_sync.is_configured(conn):
        meta_result = ads_sync.sync_account(conn, ACTOR, client=meta_client, today=today)
        outcome["meta"] = meta_result
        if meta_result.error:
            core_interrupts.enqueue(
                conn, category="auto_sync_failed",
                dedupe_key=f"auto_sync_failed:meta:{today}",
                message=_META_FAILURE_MESSAGE, action_url="/settings",
            )

    if ga4_sync.is_configured(conn):
        for brand in bi_repo.list_brands(conn, status="active"):
            ga4_result = ga4_sync.sync_brand(conn, brand["id"], ACTOR, client=ga4_client, today=today)
            outcome["ga4"][brand["id"]] = ga4_result
            if ga4_result.error:
                core_interrupts.enqueue(
                    conn, category="auto_sync_failed", brand_id=brand["id"],
                    dedupe_key=f"auto_sync_failed:ga4:{brand['id']}:{today}",
                    message=_GA4_FAILURE_MESSAGE,
                    action_url=f"/brands/{brand['id']}/ads/ga4",
                )

    for brand in bi_repo.list_brands(conn, status="active"):
        run_cycle_checks(conn, brand["id"], today, url_probe=url_probe)

    conn.commit()
    return outcome
