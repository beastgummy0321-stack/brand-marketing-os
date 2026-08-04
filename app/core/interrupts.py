# -*- coding: utf-8 -*-
"""app/core/interrupts.py — 全站打斷佇列（GitHub issue #32，決策 0025／0026）。

全站所有「需要人看」的訊息只剩一個出口：這裡的 enqueue()。各模組只能認領 CATEGORIES
裡登記好的一個類別，嚴重度由類別反查、呼叫端不得自報數字——避免每個模組都覺得自己最急。

嚴重度分級（單一中央位置，DESIGN.md §20／決策 0026）：金額損失 ＞ 不可逆 ＞ 規則警示 ＞ 資訊性。
排序＝嚴重度為主，同級內按行動價值（CATEGORIES 的登記順序，越早登記代表價值越高）。

去重：同一品牌下同一 dedupe_key 二次 enqueue 只留第一筆（INSERT 前用 brand_id ＋ dedupe_key
查重，命中就不寫，回傳 None），呼叫端可用回傳值判斷這次是不是新排的。不同品牌就算 dedupe_key
剛好相同也各自獨立去重，不會互相蓋掉（票 M6，DB 唯一索引見 migrations/0007）。

資訊性項目逾期自動降級封存：見 _archive_stale_informational（每次 list_open 前跑一次）。
"""

from datetime import date, timedelta
from typing import Optional

from app.core.audit import write_audit
from app.core.db import new_id, now_iso

# 嚴重度分級（決策 0025／0026 定案，DESIGN.md §20 規則 4 的資料層對應）。
SEVERITY_ORDER = ["money_loss", "irreversible", "rule_warning", "informational"]
SEVERITY_RANK = {level: i for i, level in enumerate(SEVERITY_ORDER)}
SEVERITY_LABELS = {
    "money_loss": "金額損失",
    "irreversible": "不可逆",
    "rule_warning": "規則警示",
    "informational": "資訊性",
}

# 類別登記表（單一權威）：新模組要送打斷佇列，在這裡登記一筆，不得在呼叫端自報 severity。
# dict 順序＝同嚴重度內的行動價值排序。
CATEGORIES = {
    "cycle_reminder": {"severity": "informational", "label": "檔期提醒"},
    "code_surge_alert": {"severity": "rule_warning", "label": "用碼異常警示"},  # 票 #35
    "revenue_reconcile_due": {"severity": "informational", "label": "營收對帳提醒"},  # 票 #36
    "reading_reversal": {"severity": "rule_warning", "label": "判讀翻盤警示"},  # 票 #38
    "repurchase_conflict": {"severity": "rule_warning", "label": "回購校正異議"},  # 票 #39
    "hypothesis_unresolved": {"severity": "informational", "label": "假設待結案"},  # 票 #53
    "prototype_phase_ended": {"severity": "rule_warning", "label": "原型階段結束提醒"},  # 修憲落地 A6
}
_CATEGORY_RANK = {name: i for i, name in enumerate(CATEGORIES)}

MAX_MESSAGE_LEN = 30  # DESIGN.md §20 規則 4：一卡一句 ≤30 全形字
STALE_AFTER_DAYS = 14  # 資訊性項目逾期自動降級封存的門檻（比照 0025 期末＋14 天結算節奏）


def enqueue(conn, *, category: str, dedupe_key: str, message: str,
            brand_id: Optional[str] = None, campaign_cycle_id: Optional[str] = None,
            action_url: Optional[str] = None, kind: Optional[str] = None,
            visible_from: Optional[str] = None) -> Optional[str]:
    """送進打斷佇列；同去重鍵已存在就不重複塞（回傳 None）。不自動 commit（比照 write_audit，
    交由呼叫端決定交易邊界，方便一次排多筆用同一個交易）。"""
    spec = CATEGORIES.get(category)
    if spec is None:
        raise ValueError(f"未登記的打斷類別：{category}（見 CATEGORIES，模組不得自報嚴重度）")
    if not dedupe_key or not dedupe_key.strip():
        raise ValueError("interrupt.dedupe_key 為必填（用於去重）")
    if not message or not message.strip():
        raise ValueError("interrupt.message 為必填")
    if len(message) > MAX_MESSAGE_LEN:
        raise ValueError(
            f"卡片內文超過 {MAX_MESSAGE_LEN} 全形字上限（DESIGN.md §20 規則 4）：{message}"
        )

    # 去重比對要連 brand_id 一起看（票 M6）：SQLite 的 IS 運算子對 NULL 也能正確比對，
    # brand_id 為 None 時會比對「brand_id IS NULL」而不是誤判成跟別的品牌撞鍵。
    existing = conn.execute(
        "SELECT id FROM interrupt WHERE dedupe_key = ? AND brand_id IS ?",
        (dedupe_key, brand_id),
    ).fetchone()
    if existing:
        return None

    interrupt_id = new_id("itr")
    conn.execute(
        "INSERT INTO interrupt (id, brand_id, campaign_cycle_id, dedupe_key, category, kind,"
        " severity, message, action_url, visible_from, status, created_at)"
        " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'open', ?)",
        (interrupt_id, brand_id, campaign_cycle_id, dedupe_key, category, kind,
         spec["severity"], message, action_url, visible_from, now_iso()),
    )
    return interrupt_id


# 期中檢查點（app/ads/onboarding.py 的 day3／day7 提醒）不吃這條規則——它們有自己專屬的
# 生命週期（onboarding.resolve_stale_checkpoint_reminders，決策 0025 審查補遺第 4 點：
# 「提醒進佇列不過期；使用者過時才來則直接併入期末判讀」）。逾期不代表沒用，逾期只代表
# 該併入期末結論，不是該悄悄消失（票 #38）。
_NEVER_STALE_KINDS = ("day3_look_dont_touch", "day7_report")


def _archive_stale_informational(conn, today: Optional[str] = None) -> int:
    """資訊性項目逾期自動降級封存：**到期**超過 STALE_AFTER_DAYS 天沒人處理，自動轉
    archived，不再佔待辦清單（不擋路，見 0025 懶人優先總則）。

    逾期起算點是 visible_from（這則提醒實際浮出、使用者才看得到的那天），不是
    created_at（enqueue 當下）——很多提醒是提早排入佇列、visible_from 訂在未來
    （例如票 #38 的 final_settlement 排在檔期結束＋14 天），起算點若用 created_at，
    這類提醒還沒被使用者看過就已經因為「早就存在資料庫裡」而被判定逾期、悄悄消失，
    等於從沒機會被看到（曾是真實的潛在 bug，不是本函式故意的行為）。
    """
    today = today or date.today().isoformat()
    cutoff = (date.fromisoformat(today) - timedelta(days=STALE_AFTER_DAYS)).isoformat()
    placeholders = ",".join("?" for _ in _NEVER_STALE_KINDS)
    cursor = conn.execute(
        "UPDATE interrupt SET status = 'archived', resolved_at = ?"
        " WHERE status = 'open' AND severity = 'informational'"
        " AND COALESCE(visible_from, created_at) < ?"
        f" AND (kind IS NULL OR kind NOT IN ({placeholders}))",
        (now_iso(), cutoff, *_NEVER_STALE_KINDS),
    )
    conn.commit()
    return cursor.rowcount


def _sort_key(row: dict):
    return (
        SEVERITY_RANK.get(row["severity"], len(SEVERITY_ORDER)),
        _CATEGORY_RANK.get(row["category"], len(CATEGORIES)),
        row["visible_from"] or row["created_at"],
        row["created_at"],
    )


def list_open(conn, brand_id: Optional[str] = None, category: Optional[str] = None,
              today: Optional[str] = None) -> list:
    """待辦清單：已到 visible_from 的 open 項目，嚴重度為主、同級按行動價值排序。

    brand_id 省略＝跨品牌查（首頁待辦、全站收件匣用）。
    """
    _archive_stale_informational(conn, today)
    today = today or date.today().isoformat()
    sql = "SELECT * FROM interrupt WHERE status = 'open' AND (visible_from IS NULL OR visible_from <= ?)"
    params: list = [today]
    if brand_id:
        sql += " AND brand_id = ?"
        params.append(brand_id)
    if category:
        sql += " AND category = ?"
        params.append(category)
    rows = [dict(r) for r in conn.execute(sql, params)]
    rows.sort(key=_sort_key)
    return rows


def list_done(conn, brand_id: Optional[str] = None) -> list:
    """已結清單（人工處理 resolved ＋ 逾期自動封存 archived），最近結案的排前面。"""
    sql = "SELECT * FROM interrupt WHERE status IN ('resolved', 'archived')"
    params: list = []
    if brand_id:
        sql += " AND brand_id = ?"
        params.append(brand_id)
    sql += " ORDER BY resolved_at DESC"
    return [dict(r) for r in conn.execute(sql, params)]


def current_card(conn, brand_id: Optional[str] = None) -> Optional[dict]:
    """頁頂「當前一件」：待辦清單依排序取第一筆，沒有就回 None（優雅缺席）。"""
    rows = list_open(conn, brand_id=brand_id)
    return rows[0] if rows else None


def resolve(conn, interrupt_id: str, *, actor: str) -> None:
    """人工處理完畢，轉 resolved；寫一筆 audit_log（write_audit 會擋空 actor）。會 commit。"""
    row = conn.execute("SELECT * FROM interrupt WHERE id = ?", (interrupt_id,)).fetchone()
    if row is None:
        raise ValueError(f"找不到打斷佇列項目：{interrupt_id}")
    conn.execute(
        "UPDATE interrupt SET status = 'resolved', resolved_at = ? WHERE id = ?",
        (now_iso(), interrupt_id),
    )
    write_audit(conn, brand_id=row["brand_id"], entity_type="interrupt", entity_id=interrupt_id,
                action="resolve", actor=actor)
    conn.commit()
