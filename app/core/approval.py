"""app/core/approval.py — 核准（ADR 0040：花錢煞車，ADR 0018 §1 四個使用者關卡之一）。

跟 `interrupt`／`rule_card_value`／`app_setting`／`audit_log` 同一層：這是外殼自己的字
（`CONTEXT.md` 三個業務詞之一），不是某個投放模組的資料，所以放在 `app/core`，不是
`app/schedule`。今天只有一個呼叫端（`app/schedule/routes.py`），一個 `scope_type`
（`"schedule_tree"`）——第二個呼叫端／`scope_type` 真的出現時再擴充，不先猜。

這裡只管落地：核准內容（`content_hash`）、金額怎麼算、`matches_current_tree` 怎麼比對，
一律是呼叫端的業務知識，本檔不碰、也不 import `app.schedule` 任何東西（集裝箱憲章§2：
狀態不外洩，本模組不知道「樹」長什麼樣子）。

沒有平台欄位，也不會有——這批花費要投去哪個平台，凍結在樹自己的
`context_scope_json.platform`，這裡加一欄平台名稱是加資料、不是加欄位（ADR 0035）。
"""

from app.core.audit import write_audit
from app.core.db import Conn, ConnProxy, new_id, now_utc

_AnyConn = Conn | ConnProxy


def approve(
    conn: _AnyConn, *, org_id: str, brand_id: str, scope_type: str, scope_ref: str,
    content_hash: str, amount: float, max_daily_amount: float, actor: str,
    note: str | None = None,
) -> str:
    """插入一列核准紀錄，寫一筆 audit_log，回傳新 id。舊列從不覆寫——重新核准是新的一列
    （ticket 明文：the old row is never rewritten）。比照 `rule_cards.set_value()` ／
    `interrupts.resolve()` 既有慣例：會 commit（這是一次完整、獨立的落地動作，不是留給
    呼叫端拼在別的交易裡）。

    `max_daily_amount` 必填、沒有預設值（ADR 0059）：給預設值等於把「上限＝簽核總額」
    這條業務規則塞進 `app/core`，跟本檔檔頭那句「核准內容、金額怎麼算……一律是呼叫端的
    業務知識，本檔不碰」矛盾——這裡只負責落地，上限要多少一律由呼叫端算好再傳進來。"""
    approval_id = new_id("apv")
    approved_at = now_utc()
    conn.execute(
        "INSERT INTO approval (id, org_id, brand_id, scope_type, scope_ref, content_hash,"
        " approved_amount, max_daily_amount, approved_by, approved_at, note, created_at)"
        " VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
        (approval_id, org_id, brand_id, scope_type, scope_ref, content_hash, amount,
         max_daily_amount, actor, approved_at, note, now_utc()),
    )
    write_audit(
        conn, org_id=org_id, brand_id=brand_id, entity_type="approval", entity_id=approval_id,
        action="approve", actor=actor,
        after={
            "scope_type": scope_type, "scope_ref": scope_ref, "amount": amount,
            "max_daily_amount": max_daily_amount,
        },
    )
    conn.commit()
    return approval_id


def latest(
    conn: _AnyConn, *, org_id: str, brand_id: str, scope_type: str,
) -> dict | None:
    """這個品牌這一類主體目前有效（未撤回）的最新一列，或 None。

    **刻意不篩 `scope_ref`**（2026-08-30 修正）：`scope_ref` 記的是「當初簽的是哪一份東西」
    ——以排程樹為例，是那棵樹自己的 `llm_task` id。樹每重新展開一次就是全新一列，所以拿
    當下那棵樹的 id 去查，永遠查不到上一次的核准，畫面會顯示「從沒核准過」而不是「核准過、
    但內容已經變了」，`content_hash` 也就永遠沒機會比對。查詢用「品牌＋類型」找最新一筆，
    `content_hash` 負責判斷新不新——兩件事分開，`scope_ref` 才留得住「簽的是哪一份」這個
    事後查得回去的答案。"""
    row = conn.execute(
        "SELECT * FROM approval WHERE org_id = %s AND brand_id = %s AND scope_type = %s"
        " AND revoked_at IS NULL ORDER BY approved_at DESC LIMIT 1",
        (org_id, brand_id, scope_type),
    ).fetchone()
    return dict(row) if row is not None else None


def revoke(conn: _AnyConn, *, approval_id: str, org_id: str, actor: str) -> None:
    """撤回：蓋 `revoked_by`/`revoked_at`，這一列本身留著（nothing is deleted）。租戶界線
    比照 `app/core/interrupts.py resolve()`：找不到、或這一列屬於別的組織，同一個錯誤，
    不區分「不存在」跟「不是你的」。"""
    row = conn.execute(
        "SELECT * FROM approval WHERE id = %s AND org_id = %s", (approval_id, org_id)
    ).fetchone()
    if row is None:
        raise ValueError(f"找不到核准紀錄：{approval_id}")
    conn.execute(
        "UPDATE approval SET revoked_by = %s, revoked_at = %s WHERE id = %s",
        (actor, now_utc(), approval_id),
    )
    write_audit(
        conn, org_id=row["org_id"], brand_id=row["brand_id"], entity_type="approval",
        entity_id=approval_id, action="revoke", actor=actor,
    )
    conn.commit()
