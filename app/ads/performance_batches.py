# -*- coding: utf-8 -*-
"""app/ads/performance_batches.py — 檔期「現在結算」＋匯入整批撤銷（票 S1-01，
`.scratch/s1/issues/01-settle-now-and-batch-undo.md`）。

新邏輯集中在這裡，不擠進 `routes_campaigns_performance_api.py`（268 行）或
`performance.py`（796 行，加 batch_id kwarg 就會超過 800 行上限——`delete_snapshots`／
`list_snapshots` 這兩個既有函式因此純搬過來，邏輯不變，見票第一節第 3 點）。

純讀取／純聚合為主：`can_settle`／`list_batches` 不呼叫 AI、不改資料。真的要重跑判讀
或收帳，一律轉回 `app/ads/reading.py` 既有的 `finalize`／`run`／`rerun_for_late_data`，
這裡不重寫第二套判讀或刪除邏輯。
"""

from typing import Optional

BATCH_LIST_LIMIT = 5


def delete_snapshots(conn, brand_id: str, cycle_id: str, *, source: Optional[str] = None,
                     batch_id: Optional[str] = None) -> int:
    """刪除某期的成效資料，連同掛在上面的 derived_metric 一起（先子後父）。

    唯一的刪除入口：derived_metric 有外鍵指向 performance_snapshot，呼叫端各自寫
    DELETE 一定會有人忘了先刪子表，然後在使用者按第二次時才爆。集中在這裡處理一次。
    （append-only 原則管的是「不覆寫已收到的數字」；重新產生模擬資料屬於重算，不是竄改。）
    batch_id：票 S1-01 整批撤銷用，撤一批匯入而不動同期其他批。
    """
    params = [brand_id, cycle_id]
    where = "brand_id = %s AND campaign_cycle_id = %s"
    if source:
        where += " AND source = %s"
        params.append(source)
    if batch_id:
        where += " AND import_batch_id = %s"
        params.append(batch_id)

    conn.execute(
        f"DELETE FROM derived_metric WHERE performance_snapshot_id IN"
        f" (SELECT id FROM performance_snapshot WHERE {where})", params,
    )
    cursor = conn.execute(f"DELETE FROM performance_snapshot WHERE {where}", params)
    conn.commit()
    return cursor.rowcount


def list_snapshots(conn, brand_id: str, cycle_id: str) -> list:
    return [dict(r) for r in conn.execute(
        "SELECT * FROM performance_snapshot WHERE brand_id = %s AND campaign_cycle_id = %s"
        " ORDER BY as_of_date DESC, created_at DESC", (brand_id, cycle_id),
    )]


def can_settle(conn, brand_id: str, cycle_id: str, cycle: dict) -> tuple:
    """GET/POST settle-now 共用的判定：回 (can_settle, reason, already_closed)。

    已 CLOSED：不能再結一次。沒有任何未隔離、非模擬的成效列：沒東西可結。
    """
    if cycle["status"] == "CLOSED":
        return False, "這期已經收帳了。", True
    row = conn.execute(
        "SELECT 1 FROM performance_snapshot WHERE brand_id = %s AND campaign_cycle_id = %s"
        " AND quarantined = 0 AND source != 'simulated' LIMIT 1", (brand_id, cycle_id),
    ).fetchone()
    if row is None:
        return False, "這期還沒有任何成效數字，先匯入或手填一筆再結算。", False
    return True, None, False


def list_batches(conn, brand_id: str, cycle_id: str) -> list:
    """最近 `BATCH_LIST_LIMIT` 批匯入（排除模擬資料），依匯入時間新到舊。

    rows 含隔離列；spend 是這批回報的花費總額，不分隔離與否（票第一節第 1 點：
    這裡是「匯了什麼」的帳目，不是判讀會採信的數字）。
    """
    rows = conn.execute(
        "SELECT import_batch_id AS batch_id, source, MAX(created_at) AS imported_at,"
        " COUNT(*) AS rows, SUM(quarantined) AS quarantined, SUM(spend) AS spend"
        " FROM performance_snapshot WHERE brand_id = %s AND campaign_cycle_id = %s"
        " AND source != 'simulated' AND import_batch_id IS NOT NULL"
        " GROUP BY import_batch_id, source ORDER BY imported_at DESC LIMIT %s",
        (brand_id, cycle_id, BATCH_LIST_LIMIT),
    ).fetchall()
    return [dict(r) for r in rows]
