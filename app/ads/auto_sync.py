# -*- coding: utf-8 -*-
"""app/ads/auto_sync.py — 每日自動同步觸發器（票 07-auto-sync，規格 0001）。

沿用既有唯讀同步邏輯：Meta 帳號同步（app/ads/sync.py `sync_account`，全站一組連線、
一次涵蓋所有已認領品牌，比照手動同步鈕 `/brands/{b}/ads/sync` 的既有呼叫方式）＋
GA4 每品牌同步（app/ads/ga4_sync.py `sync_brand`，比照手動同步鈕 `/brands/{b}/ads/ga4/sync`）。
唯一差別是觸發者從「使用者按鈕」換成「排程呼叫這支函式」；不設定連線就跳過、不報錯。

失敗不拋例外、也不讓一個品牌的失敗擋住其他品牌：各自的同步結果各自處理，
失敗才送進打斷佇列（`auto_sync_failed` 類別，見 app/core/interrupts.py CATEGORIES）。
"""

from datetime import date
from typing import Optional

from app.ads import ga4_sync
from app.ads import sync as ads_sync
from app.brand_intelligence import repository as bi_repo
from app.core import interrupts as core_interrupts

ACTOR = "auto_sync"

# 打斷佇列卡片內文上限 30 全形字（app/core/interrupts.py MAX_MESSAGE_LEN）——固定短句，
# 不把原始錯誤訊息塞進去（原始錯誤訊息通常較長且長度不可控，沿用其他模組固定短句的作法）。
_META_FAILURE_MESSAGE = "Meta 自動同步失敗，去設定頁看看。"
_GA4_FAILURE_MESSAGE = "GA4 自動同步失敗，去看看。"


def run(conn, *, today: Optional[str] = None, meta_client=None, ga4_client=None) -> dict:
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

    conn.commit()
    return outcome
