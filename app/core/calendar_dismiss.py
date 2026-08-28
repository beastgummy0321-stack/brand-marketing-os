"""app/core/calendar_dismiss.py — 節日類別永久覆寫（票 02-permanent-dismiss-category，
ADR 0014 第二、三節）。

使用者把某個節日類別永久標記為「跟我無關」：之後系統業種比對判成相關也不再提醒，
可在設定中心隨時重新開啟。跟 app/core/campaign_skip.py（票 03，ADR 0015）是不同表、
不同語意——那邊是「這次不投，明年還提醒」的單期紀錄；這裡是「系統業種判斷錯了，
之後都不用提醒」的永久覆寫，刻意不合併（ADR 0014 第二節）。

放在 app/core 而不是 app/dashboard：app/dashboard 是唯讀彙總層（app/tests/
test_architecture_boundaries.py DashboardReadOnlyTest 擋下任何寫入 SQL），比照
campaign_skip.py 同一個理由。

**`list_categories()` 刻意不 import app.dashboard.campaign_calendar，直接讀同一份
campaign_calendar_data.json**：LAYER_ORDER 裡 app.core 排最前面，只准依賴排在自己
前面的層，app.dashboard 排在後面，import 會違反 A1 三層地界；而本模組的呼叫端之一
`app/brand_intelligence/routes_settings.py` 依同一份地界也不得依賴 app.dashboard。
同款繞法、同款理由見 `app/ads/occasion.py` 檔頭說明——年份尾碼去除的兩行 regex
因此獨立宣告一份，不是 import 過來的同一個物件。

對外進入點：`dismiss()`／`undismiss()`（寫，供 HTTP 路由呼叫）、`list_dismissed()`
（讀，供 `app/dashboard/repository.py` 組 next_calendar_reminder／current_campaign_stage
的 `dismissed_categories` 參數）、`list_categories()`（讀，供設定中心「節日提醒」小節
出清單＋驗證 toggle 路由傳進來的 category 是否合法）。誰依賴它：
`app/dashboard/repository.py`、`app/brand_intelligence/routes_settings.py`。
"""

import json
import re
from pathlib import Path

from app.core import cleanup
from app.core.db import new_id, now_utc

_CALENDAR_DATA_PATH = (
    Path(__file__).resolve().parent.parent / "dashboard" / "campaign_calendar_data.json"
)
_YEAR_SUFFIX_RE = re.compile(r"_\d{4}$")


def list_categories() -> list:
    """去重後的節日類別清單（跨年份穩定識別碼＋名稱），依資料檔出現順序，同一類別
    取第一次出現的名稱。"""
    with open(_CALENDAR_DATA_PATH, encoding="utf-8") as f:
        events = json.load(f)
    labels = {}
    for event in events:
        category = _YEAR_SUFFIX_RE.sub("", event["id"])
        labels.setdefault(category, event["name"])
    return [{"category": category, "label": label} for category, label in labels.items()]


def dismiss(conn, brand_id: str, category: str, *, org_id: str) -> None:
    """永久關閉某品牌某節日類別的提醒。重複關閉不報錯、不疊加（ON CONFLICT DO NOTHING）。
    會 commit。"""
    conn.execute(
        "INSERT INTO brand_dismissed_calendar_category"
        " (id, org_id, brand_id, category, created_at) VALUES (%s, %s, %s, %s, %s)"
        " ON CONFLICT (brand_id, category) DO NOTHING",
        (new_id("bdc"), org_id, brand_id, category, now_utc()),
    )
    conn.commit()


def undismiss(conn, brand_id: str, category: str) -> None:
    """重新開啟提醒：刪除那筆覆寫紀錄。原本就沒關閉時是無操作，不報錯。會 commit。"""
    conn.execute(
        "DELETE FROM brand_dismissed_calendar_category WHERE brand_id = %s AND category = %s",
        (brand_id, category),
    )
    conn.commit()


def list_dismissed(conn, brand_id: str) -> set:
    """某品牌永久關閉的節日類別集合。供 campaign_calendar.py 的
    next_calendar_reminder()／current_campaign_stage() 濾掉已關閉類別。"""
    rows = conn.execute(
        "SELECT category FROM brand_dismissed_calendar_category WHERE brand_id = %s",
        (brand_id,),
    ).fetchall()
    return {row["category"] for row in rows}


# ---------------------------------------------------------------------------
# 刪品牌：向 app.core.cleanup 登記（同款登記見 app/core/campaign_skip.py 檔尾）。
# test_cleanup_coverage.py 會擋沒登記的帶 brand_id 新表。
# ---------------------------------------------------------------------------

BRAND_CASCADE_TABLES = (
    ("brand_dismissed_calendar_category", "節日類別永久覆寫"),
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


cleanup.register("節日類別永久覆寫", count_brand=count_brand_data, delete_brand=delete_brand_data,
                 brand_tables={t for t, _ in BRAND_CASCADE_TABLES},
                 count_product=None, delete_product=None, product_tables=frozenset())


def demo() -> None:
    """python -m app.core.calendar_dismiss —— 最小自檢，對本機 Supabase stack 跑（02-3b 票 9）。"""
    from app.core import db as coredb

    # 種子資料的 dev 組織 id（見 supabase/seed.sql）。db.py 的那個開發用常數不得出現在
    # app/core/db.py 以外的檔案（票 03-1），這裡直接寫字面值，不 import 它。
    demo_org_id = "org_dev"

    with coredb.connection() as conn:
        dismiss(conn, "brd_x", "cny", org_id=demo_org_id)
        assert list_dismissed(conn, "brd_x") == {"cny"}
        # 重複關閉不疊加
        dismiss(conn, "brd_x", "cny", org_id=demo_org_id)
        rows = conn.execute(
            "SELECT COUNT(*) AS c FROM brand_dismissed_calendar_category"
            " WHERE brand_id = %s AND category = %s", ("brd_x", "cny")).fetchone()
        assert rows["c"] == 1
        # 重新開啟＝刪除該筆
        undismiss(conn, "brd_x", "cny")
        assert list_dismissed(conn, "brd_x") == set()
        # 重新開啟一個本來就沒關閉的類別，無操作、不報錯
        undismiss(conn, "brd_x", "valentine")
        # 不同品牌互不影響
        dismiss(conn, "brd_a", "cny", org_id=demo_org_id)
        assert list_dismissed(conn, "brd_b") == set()
        conn.rollback()
        # 節日類別清單：真實資料檔去重後每類別只出現一次
        categories = list_categories()
        assert len(categories) > 0
        assert len({c["category"] for c in categories}) == len(categories)
        assert {"category": "cny", "label": "農曆新年"} in categories
    print("core.calendar_dismiss 自檢通過")


if __name__ == "__main__":
    demo()
