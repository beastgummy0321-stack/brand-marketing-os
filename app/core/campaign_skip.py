# -*- coding: utf-8 -*-
"""app/core/campaign_skip.py — 這期跳過紀錄（票 03-cycle-skip-record，ADR 0015）。

使用者標記「這次不投某個節日檔期」：品牌＋節日＋年份＋理由（選填）。純脈絡用途——
明年同一節日提醒觸發時附帶顯示去年的理由，不寫入、不影響 app/ads/nextcycle.py 下期
建議引擎的任何計算（ADR 0015 第二節）。跟 ADR 0014 的永久覆寫（`brand_dismissed_
calendar_category`，票 02，另一張表）語意不同：這裡是「今年不投不代表明年不投」，
刻意不合併。

放在 app/core 而不是 app/dashboard：app/dashboard 是唯讀彙總層（票 02-overview-cards
定案，app/tests/test_architecture_boundaries.py DashboardReadOnlyTest 機器檢查擋下
任何寫入 SQL），比照既有 rule_card／pacing_card 等窄範圍功能狀態掛在 app/core 的做法。
`holiday_id` 的推導（去掉節日 id 的年份尾碼）仍留在
app/dashboard/campaign_calendar.py——那是純函數、不碰 DB，本檔的呼叫端
（app/dashboard/repository.py）自己組好 holiday_id 再傳進來。

對外進入點：record_skip()（寫）／get_skip()（讀，供 app/dashboard/repository.py 組
guide_cards facts 時查「去年有沒有跳過」）。目前沒有 HTTP 路由——尚無 UI 票要打這支，
真的有前端要接時再補（YAGNI，見票 03 驗收清單：本票只要求紀錄機制與提醒附帶顯示，
沒有畫面契約項目）。
"""

from typing import Optional

from app.core import cleanup
from app.core.db import new_id, now_iso, DEV_ORG_ID


def record_skip(conn, brand_id: str, holiday_id: str, year: int,
                 reason: Optional[str] = None) -> None:
    """標記某品牌某年不投某個節日檔期。同品牌＋節日＋年份重複標記會覆蓋舊理由
    （使用者改變心意時只留最新一筆）。會 commit。"""
    conn.execute(
        "INSERT INTO campaign_skip (id, org_id, brand_id, holiday_id, year, reason, created_at)"
        " VALUES (%s, %s, %s, %s, %s, %s, %s)"
        " ON CONFLICT(brand_id, holiday_id, year) DO UPDATE SET"
        " reason = excluded.reason, created_at = excluded.created_at",
        (new_id("csk"), DEV_ORG_ID, brand_id, holiday_id, year, reason, now_iso()),
    )
    conn.commit()


def get_skip(conn, brand_id: str, holiday_id: str, year: int) -> Optional[dict]:
    """查某品牌某節日某年份的跳過紀錄，沒有就回 None。"""
    row = conn.execute(
        "SELECT reason FROM campaign_skip WHERE brand_id = %s AND holiday_id = %s AND year = %s",
        (brand_id, holiday_id, year),
    ).fetchone()
    return {"reason": row["reason"]} if row else None


# ---------------------------------------------------------------------------
# 刪品牌：向 app.core.cleanup 登記（同款登記見 app/core/interrupts.py 檔尾）。
# test_cleanup_coverage.py 會擋沒登記的帶 brand_id 新表。
# ---------------------------------------------------------------------------

BRAND_CASCADE_TABLES = (
    ("campaign_skip", "檔期跳過紀錄"),
)


def count_brand_data(conn, brand_id: str) -> list:
    counts = []
    for table, label in BRAND_CASCADE_TABLES:
        n = conn.execute(
            f"SELECT COUNT(*) AS c FROM {table} WHERE brand_id = %s", (brand_id,)
        ).fetchone()["c"]
        if n:
            counts.append((label, n))
    return counts


def delete_brand_data(conn, brand_id: str) -> dict:
    counts = dict(count_brand_data(conn, brand_id))
    for table, _label in BRAND_CASCADE_TABLES:
        conn.execute(f"DELETE FROM {table} WHERE brand_id = %s", (brand_id,))
    return counts


cleanup.register("檔期跳過紀錄", count_brand=count_brand_data, delete_brand=delete_brand_data,
                 brand_tables={t for t, _ in BRAND_CASCADE_TABLES},
                 count_product=None, delete_product=None, product_tables=frozenset())


def demo() -> None:
    """python -m app.core.campaign_skip —— 最小自檢：隔離 tmp DB，不碰 data/app.db。"""
    import tempfile
    from pathlib import Path

    from app.core import db

    with tempfile.TemporaryDirectory() as tmp:
        conn = db.connect_and_migrate(Path(tmp) / "test.db")
        assert get_skip(conn, "brd_x", "cny", 2026) is None
        record_skip(conn, "brd_x", "cny", 2026, reason="收假太晚，沒空間做素材")
        assert get_skip(conn, "brd_x", "cny", 2026) == {"reason": "收假太晚，沒空間做素材"}
        # 重複標記覆蓋舊理由，不是疊加
        record_skip(conn, "brd_x", "cny", 2026, reason="新理由")
        assert get_skip(conn, "brd_x", "cny", 2026) == {"reason": "新理由"}
        # 理由選填：不填也能記下「有跳過」這件事
        record_skip(conn, "brd_x", "valentine", 2026)
        assert get_skip(conn, "brd_x", "valentine", 2026) == {"reason": None}
        # 不同年份互不影響
        assert get_skip(conn, "brd_x", "cny", 2027) is None
        conn.close()
    print("core.campaign_skip 自檢通過")


if __name__ == "__main__":
    demo()
