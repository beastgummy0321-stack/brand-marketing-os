# -*- coding: utf-8 -*-
"""app/brand_intelligence/rule_lifecycle.py — 規則有效期與重新確認（rule-lifecycle/01，
ADR 0012 第一節）。

規則被接受後（`create_rule` 已寫入 `confirmed_at`，見 rule-lifecycle/02）超過設定期數沒有
被重新確認，狀態自動退回 `pending_reconfirm`：不進生成 prompt（`repository.list_rules_for_
brand`／`list_rules_for_product` 只挑 `status = 'active'`），但不刪除、不變 `inactive`——
使用者到累積智慧頁一鍵「延續」（`repository.reconfirm_rule`）即可恢復生效，不必重新輸入內容。

門檻期數讀 `app.core.rule_cards` 的 `rule_expiry.reconfirm_cycles`（分品牌，不寫死成常數，
settings-hub/01 已把 rule_cards 機制擴充成分品牌）。「期」換算天數比照 `app.ads.budget.
DEFAULT_DURATION_DAYS`（檔期預設 14 天）——這裡不直接 import `app.ads`：A1 三層地界只准
依賴排在自己前面的層（`test_architecture_boundaries.py` LAYER_ORDER），`app.ads` 排在
`app.brand_intelligence` 之後，反向 import 會被機器閘門擋下。改用本地常數並註明對應關係，
兩處數字若有一天要拆開也各自獨立，不必共用。

sweep_expired_rules() 比照 `app/core/interrupts.py` 的 `_archive_stale_informational`：
系統自動的 housekeeping 轉態，不寫 audit_log（沒有人類 actor，audit_log.actor 為必填）、
呼叫端在「列出生效中規則」前先跑一次（見 repository.list_rules_for_brand／for_product／
list_pending_reconfirm_rules），冪等（WHERE status = 'active' 已經翻過的列不會再被選中）。

對外進入點：`sweep_expired_rules(conn, brand_id)`。
誰依賴它：`app.brand_intelligence.repository`（同套件內的既有慣例，見 context_compiler.py
對 repository 的用法）。
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.core.db import now_iso, Conn, DEV_ORG_ID
from app.core.rule_cards import get_value

CARD_KEY = "rule_expiry"
FIELD_KEY = "reconfirm_cycles"

# 比照 app.ads.budget.DEFAULT_DURATION_DAYS（檔期預設天數）；不直接 import 避免跨層依賴。
CYCLE_DAYS_APPROX = 14


def _cutoff_iso(conn: Conn, brand_id: str) -> str:
    """幾天前算逾期：現在往前推「門檻期數 × 一期天數」。"""
    cycles = get_value(conn, brand_id, CARD_KEY, FIELD_KEY)
    cutoff = datetime.now(timezone.utc) - timedelta(days=cycles * CYCLE_DAYS_APPROX)
    return cutoff.isoformat()


def sweep_expired_rules(conn: Conn, brand_id: str) -> int:
    """超過門檻期數未重新確認的生效中規則，狀態退回 pending_reconfirm。回傳受影響筆數。"""
    cutoff = _cutoff_iso(conn, brand_id)
    cursor = conn.execute(
        "UPDATE rule SET status = 'pending_reconfirm', updated_at = %s "
        "WHERE brand_id = %s AND status = 'active' AND confirmed_at IS NOT NULL AND confirmed_at < %s",
        (now_iso(), brand_id, cutoff),
    )
    conn.commit()
    return cursor.rowcount


def demo() -> None:
    """最小自測：剛確認的規則不受影響，逾期的規則被掃到；冪等（掃兩次結果一樣）。"""
    import tempfile
    from pathlib import Path

    from app.core import db as core_db

    with tempfile.TemporaryDirectory() as tmp:
        conn = core_db.connect_and_migrate(Path(tmp) / "demo.db")
        brand_id = "brd_demo"
        conn.execute(
            "INSERT INTO brand (id, org_id, name, status, knowledge_version, created_at, updated_at) "
            "VALUES (%s, %s, '示範品牌', 'active', 1, %s, %s)",
            (brand_id, DEV_ORG_ID, now_iso(), now_iso()),
        )
        fresh_iso = now_iso()
        stale_iso = (datetime.now(timezone.utc) - timedelta(days=200)).isoformat()
        conn.execute(
            "INSERT INTO rule (id, org_id, brand_id, rule_type, content, severity, status, "
            "created_at, updated_at, confirmed_at) VALUES "
            "('rul_fresh', %s, %s, 'tone', '剛確認', 'soft', 'active', %s, %s, %s), "
            "('rul_stale', %s, %s, 'tone', '早就沒人確認', 'soft', 'active', %s, %s, %s)",
            (DEV_ORG_ID, brand_id, fresh_iso, fresh_iso, fresh_iso,
             DEV_ORG_ID, brand_id, stale_iso, stale_iso, stale_iso),
        )
        conn.commit()

        affected = sweep_expired_rules(conn, brand_id)
        assert affected == 1, f"應該只有一條逾期，實際 {affected}"

        rows = {r["id"]: r["status"] for r in conn.execute("SELECT id, status FROM rule")}
        assert rows["rul_fresh"] == "active", rows
        assert rows["rul_stale"] == "pending_reconfirm", rows

        # 冪等：再掃一次，已經翻過的列不會重複計入受影響筆數
        assert sweep_expired_rules(conn, brand_id) == 0

        conn.close()
    print("rule_lifecycle demo OK")


if __name__ == "__main__":
    demo()
