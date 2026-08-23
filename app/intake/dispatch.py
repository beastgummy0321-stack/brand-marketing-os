# -*- coding: utf-8 -*-
"""app/intake/dispatch.py — 調度台『開戶』模組門面（票 O1-02，ADR 0024）。

`status()`／`handle()` 是本模組對調度台的唯一公開面，取值全部沿用
`app/intake/repository.py` 既有公開函式，不重寫第二套查法（票面「取值來源」）。

自己在檔尾呼叫 `orchestrator.register_module()` 把自己掛進調度台（比照
`app/ads/diagnosis.py` 的登記制）——調度台本身不 import 這個檔案。

`handle()` 沒有任何 op：開戶靠真人訪談，沒有調度台可自動做的動作（票面裁決）。
"""

from app.brand_intelligence import repository as bi_repo
from app.core import orchestrator as core_orchestrator
from app.intake import repository as intake_repo


def status(conn, brand_id: str) -> dict:
    """調度台 facts：`intake.draft_open`（有沒有進行中的開戶草稿）、
    `intake.completed`（有沒有完成過任何一輪開戶）、`intake.pending_items`
    （進行中草稿裡還沒處理的項目數，沒有進行中草稿就是 0）、
    `intake.products_count`（這個品牌目前有幾個產品）。"""
    active_draft = intake_repo.get_active_draft(conn, brand_id)
    completed_draft = intake_repo.get_latest_completed_draft(conn, brand_id)
    pending_items = 0
    if active_draft is not None:
        pending_items = intake_repo.count_items_by_outcome(
            conn, brand_id, active_draft["id"]).get("pending", 0)
    return {
        "intake.draft_open": active_draft is not None,
        "intake.completed": completed_draft is not None,
        "intake.pending_items": pending_items,
        "intake.products_count": len(bi_repo.list_products(conn, brand_id)),
    }


def handle(conn, action: dict) -> dict:
    """開戶模組沒有任何 op：開戶靠真人訪談，沒有調度台可自動做的動作（票 O1-02 裁決）。
    收到任何 op 一律丟 ValueError（ADR 0024 決議 6）。"""
    raise ValueError(f"開戶模組不認得這個 op：{action['op']}")


core_orchestrator.register_module("intake", status=status, handle=handle)
