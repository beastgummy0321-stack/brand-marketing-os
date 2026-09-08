"""app/brand_intelligence/advertising_history.py — 票 past-ads/03（ADR 0067 rule 6）：
`brand.advertising_history` 這一欄的唯一寫入路徑。獨立成小檔而不是加進 `repository.py`：
`repository.py` 1398 行，`app/tests/test_architecture_boundaries.py` 的
`KNOWN_OVERSIZED_FILES` 凍在 1667，CLAUDE.md「超標檔要加功能就先拆」——這欄不是超標檔的
理由，不該讓它變得更靠近上限；比照 `personas.py`／`repository_channels.py` 既有的「新功能
開新小檔」慣例。

對外進入點：本檔的 `set_advertising_history`。誰依賴它：`app/brand_web/routes_library_write.py`
的 PUT `/api/library/brands/{brand_id}/advertising-history`。
"""

from app.brand_intelligence.repository import _org_id_for_brand, get_brand
from app.core.audit import write_audit
from app.core.db import Conn, now_utc

ADVERTISING_HISTORY_VALUES = ("has_history", "none")


def set_advertising_history(conn: Conn, brand_id: str, value: str, *, actor: str) -> dict:
    """ADR 0067 rule 6：品牌是否投放過（`NULL` = 還沒被問過，不是 `'none'`——那是「問過、
    答沒有」）。跟 `brand_intelligence/repository.py` 裡形狀相同的既有寫法一致
    （`update_brand`／`set_brand_switches`）：UPDATE → 重讀 → `write_audit` → 一次
    commit。"""
    if value not in ADVERTISING_HISTORY_VALUES:
        allowed = "/".join(ADVERTISING_HISTORY_VALUES)
        raise ValueError(f"advertising_history 只能是 {allowed} 其中之一")
    before = get_brand(conn, brand_id)
    if before is None:
        raise ValueError(f"找不到品牌：{brand_id}")
    ts = now_utc()
    conn.execute(
        "UPDATE brand SET advertising_history = %s, updated_at = %s WHERE id = %s",
        (value, ts, brand_id),
    )
    after = get_brand(conn, brand_id)
    assert after is not None  # 剛 UPDATE 過的那一列，找不到代表資料庫壞了，不是正常分支
    org_id = _org_id_for_brand(conn, brand_id)
    write_audit(conn, org_id=org_id, brand_id=brand_id, entity_type="brand", entity_id=brand_id,
                action="advertising_history", actor=actor, before=before, after=after)
    conn.commit()
    return after
