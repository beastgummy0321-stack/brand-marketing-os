"""app/core/retention.py — llm_task 保留策略（修憲落地 A5；原文件已被 5eca0db 清除）。

問題：llm_task 內嵌完整模型輸出（structured_output_json／rendered_output／
validation_result_json）、只增不減，× 每日整檔備份 30 份（app/core/backup.py）——位元組會先爆。

鐵則 6「一切可追溯」不等於永不刪（原文件已刪，規則現在就活在這支檔案）：清理只清「模型產出內容」，
usage_json／cost／input_context_hash／provider／model／status／時間戳等對帳用欄位永遠保留，
所以清理後仍查得到「哪個品牌、什麼任務、花多少錢、對得上哪次輸入」，只是看不到逐字內容。

保留期＝90 天：這個原型階段的產品週期是「單一檔期＋成效判讀」，一個檔期通常數週，
90 天足夠涵蓋一個檔期＋事後覆核與爭議期的緩衝（也對齊每日備份 30 份的量級，
90 天約是 3 輪備份週期，就算某天清理漏跑也有餘裕補跑）。純為本原型階段拍板的數字，
不是規格既定值——之後真的有跨檔期覆核需求，抬高這個常數即可，不必改資料結構。
"""

from datetime import datetime, timedelta

from app.core.db import Conn, now_utc

RETENTION_DAYS = 90

# 清空的欄位：模型的完整產出內容，llm_task 裡最肥的欄位。
_PURGE_COLUMNS = ("structured_output_json", "rendered_output", "validation_result_json")


def purge_expired_llm_task_content(conn: Conn, *, now: datetime | None = None) -> int:
    """把超過保留期的已完成任務之大欄位清空，回傳實際清空的列數。

    只動 finished_at 早於 cutoff 的列（還在跑的任務不動，反正沒有大內容可清）；
    已經清過的列（大欄位已是 NULL）不會重複計入，可放心重跑（idempotent）。
    """
    cutoff = _cutoff(now)
    columns_clause = ", ".join(f"{col} = NULL" for col in _PURGE_COLUMNS)
    where_not_already_empty = " OR ".join(f"{col} IS NOT NULL" for col in _PURGE_COLUMNS)
    cur = conn.execute(
        f"""UPDATE llm_task SET {columns_clause}
            WHERE finished_at IS NOT NULL AND finished_at < %s
              AND ({where_not_already_empty})""",
        (cutoff,),
    )
    conn.commit()
    return cur.rowcount


def _cutoff(now: datetime | None = None) -> datetime:
    """回傳「現在往前推 RETENTION_DAYS 天」的 tz-aware datetime。"""
    reference = now or now_utc()
    return reference - timedelta(days=RETENTION_DAYS)
