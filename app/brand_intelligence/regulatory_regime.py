"""app/brand_intelligence/regulatory_regime.py — F34-I01（Contract R）：`brand.regulatory_regime`
這一欄的唯一寫入路徑。獨立成小檔而不是加進 `repository.py`，理由同 `advertising_history.py`：
`repository.py` 已貼近 `KNOWN_OVERSIZED_FILES` 的上限，新欄位不該讓它更靠近。

對外進入點：本檔的 `set_regulatory_regime`（`repository.set_regulatory_regime` 是給其他模組
走的 facade）。誰依賴它：`app/brand_web/routes_library_write.py` 的
PUT `/api/library/brands/{brand_id}/regulatory-regime`。
"""

from app.brand_intelligence.repository import _org_id_for_brand, get_brand
from app.core.audit import write_audit
from app.core.db import Conn, now_utc

REGULATORY_REGIMES = ("food_tw",)


def set_regulatory_regime(conn: Conn, brand_id: str, value: str | None, *, actor: str) -> dict:
    """F34 裁決 1A：品牌適用哪一套廣告法規，由使用者自己選。`None` 清除（= 不適用／未設定，
    只有一個意思）；不在 `REGULATORY_REGIMES` 裡的值一律 `ValueError`。寫法跟
    `advertising_history.py` 一模一樣：UPDATE → 重讀 → `write_audit` → 一次 commit。"""
    if value is not None and value not in REGULATORY_REGIMES:
        allowed = "/".join(REGULATORY_REGIMES)
        raise ValueError(f"regulatory_regime 只能是 {allowed} 其中之一，或留空")
    before = get_brand(conn, brand_id)
    if before is None:
        raise ValueError(f"找不到品牌：{brand_id}")
    ts = now_utc()
    conn.execute(
        "UPDATE brand SET regulatory_regime = %s, updated_at = %s WHERE id = %s",
        (value, ts, brand_id),
    )
    after = get_brand(conn, brand_id)
    assert after is not None  # 剛 UPDATE 過的那一列，找不到代表資料庫壞了，不是正常分支
    org_id = _org_id_for_brand(conn, brand_id)
    write_audit(conn, org_id=org_id, brand_id=brand_id, entity_type="brand", entity_id=brand_id,
                action="regulatory_regime", actor=actor, before=before, after=after)
    conn.commit()
    return after
