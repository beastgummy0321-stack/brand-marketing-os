"""app/brand_intelligence/rule_lifecycle.py — 規則有效期與重新確認（rule-lifecycle/01，
ADR 0012 第一節）。

規則被接受後（`create_rule` 已寫入 `confirmed_at`，見 rule-lifecycle/02）超過設定期數沒有
被重新確認，狀態自動退回 `pending_reconfirm`：不進生成 prompt（`repository.list_rules_for_
brand`／`list_rules_for_product` 只挑 `status = 'active'`），但不刪除、不變 `inactive`——
使用者到累積智慧頁一鍵「延續」（`repository.reconfirm_rule`）即可恢復生效，不必重新輸入內容。

門檻期數讀 `app.core.rule_cards` 的 `rule_expiry.reconfirm_cycles`（分品牌，不寫死成常數，
settings-hub/01 已把 rule_cards 機制擴充成分品牌）。「期」換算天數用本地常數
`CYCLE_DAYS_APPROX`（14 天）——原本比照已刪除的廣告模組檔期預設天數，兩處數字本來就
各自獨立、刻意不共用（A1 三層地界只准依賴排在自己前面的層，反向 import 會被機器閘門
擋下）。

sweep_expired_rules() 比照 `app/core/interrupts.py` 的 `_archive_stale_informational`：
系統自動的 housekeeping 轉態，不寫 audit_log（沒有人類 actor，audit_log.actor 為必填）、
呼叫端在「列出生效中規則」前先跑一次（見 repository.list_rules_for_brand／for_product／
list_pending_reconfirm_rules），冪等（WHERE status = 'active' 已經翻過的列不會再被選中）。

對外進入點：`sweep_expired_rules(conn, brand_id)`。
誰依賴它：`app.brand_intelligence.repository`（同套件內的既有慣例，見 context_compiler.py
對 repository 的用法）。
"""

from __future__ import annotations

from datetime import datetime, timedelta

from app.core.db import Conn, new_id, now_utc
from app.core.rule_cards import get_value

CARD_KEY = "rule_expiry"
FIELD_KEY = "reconfirm_cycles"

# 檔期預設天數的近似值（原本比照已刪除的 app/ads 常數，現在是本模組自己的數字）。
CYCLE_DAYS_APPROX = 14


def _cutoff(conn: Conn, brand_id: str) -> datetime:
    """幾天前算逾期：現在往前推「門檻期數 × 一期天數」。"""
    cycles = get_value(conn, brand_id, CARD_KEY, FIELD_KEY)
    return now_utc() - timedelta(days=cycles * CYCLE_DAYS_APPROX)


def sweep_expired_rules(conn: Conn, brand_id: str) -> int:
    """超過門檻期數未重新確認的生效中規則，狀態退回 pending_reconfirm。回傳受影響筆數。"""
    cutoff = _cutoff(conn, brand_id)
    cursor = conn.execute(
        "UPDATE rule SET status = 'pending_reconfirm', updated_at = %s "
        "WHERE brand_id = %s AND status = 'active' AND confirmed_at IS NOT NULL AND confirmed_at < %s",
        (now_utc(), brand_id, cutoff),
    )
    conn.commit()
    return cursor.rowcount


def demo() -> None:
    """最小自測：剛確認的規則不受影響，逾期的規則被掃到；冪等（掃兩次結果一樣）。對本機
    Supabase stack 跑（02-3b 票 9）。sweep_expired_rules() 本身會 commit，重跑不能靠
    rollback 復原——brand_id／rule id 每次跑都重新產生，避免撞到上一次留下的列（比照
    本機 dev 資料可丟可重建，CLAUDE.md「資料狀態」節）。"""
    from app.core import db as coredb

    with coredb.connection() as conn:
        brand_id = new_id("brd")
        fresh_id, stale_id = new_id("rul"), new_id("rul")
        ts = now_utc()
        conn.execute(
            "INSERT INTO brand (id, org_id, name, status, knowledge_version, created_at, updated_at) "
            "VALUES (%s, %s, '示範品牌', 'active', 1, %s, %s)",
            (brand_id, "org_dev", ts, ts),
        )
        fresh_ts = now_utc()
        stale_ts = now_utc() - timedelta(days=200)
        conn.execute(
            "INSERT INTO rule (id, org_id, brand_id, rule_type, content, severity, status, "
            "created_at, updated_at, confirmed_at) VALUES "
            "(%s, %s, %s, 'tone', '剛確認', 'soft', 'active', %s, %s, %s), "
            "(%s, %s, %s, 'tone', '早就沒人確認', 'soft', 'active', %s, %s, %s)",
            (fresh_id, "org_dev", brand_id, fresh_ts, fresh_ts, fresh_ts,
             stale_id, "org_dev", brand_id, stale_ts, stale_ts, stale_ts),
        )
        conn.commit()

        affected = sweep_expired_rules(conn, brand_id)
        assert affected == 1, f"應該只有一條逾期，實際 {affected}"

        rows = {r["id"]: r["status"] for r in conn.execute(
            "SELECT id, status FROM rule WHERE brand_id = %s", (brand_id,))}
        assert rows[fresh_id] == "active", rows
        assert rows[stale_id] == "pending_reconfirm", rows

        # 冪等：再掃一次，已經翻過的列不會重複計入受影響筆數
        assert sweep_expired_rules(conn, brand_id) == 0
    print("rule_lifecycle demo OK")


if __name__ == "__main__":
    demo()
