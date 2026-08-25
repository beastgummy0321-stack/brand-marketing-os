# -*- coding: utf-8 -*-
"""app/core/audit.py — audit_log 寫入。

存取層強制：本檔只提供 write_audit（INSERT），刻意不提供 update / delete 函式，
落實「append-only」（03 §3.1、§8.5）。呼叫端負責在同一個交易內把資料異動與稽核紀錄
一起 commit（本函式本身不 commit，交由呼叫端決定交易邊界）。
"""

from typing import Optional

from app.core.db import new_id, now_utc, jsonb, Conn, DEV_ORG_ID


def write_audit(
    conn: Conn,
    *,
    brand_id: Optional[str],
    entity_type: str,
    entity_id: str,
    action: str,
    actor: str,
    before=None,
    after=None,
    reason: Optional[str] = None,
) -> str:
    """寫一筆 audit_log。brand_id 為 None 表示系統級事件；品牌級事件必填（03 §3.1）。"""
    if not actor or not actor.strip():
        raise ValueError("audit_log.actor 為必填（具名操作人）")
    if not entity_type or not entity_id or not action:
        raise ValueError("audit_log.entity_type / entity_id / action 為必填")

    audit_id = new_id("aud")
    conn.execute(
        """INSERT INTO audit_log
           (id, org_id, brand_id, entity_type, entity_id, action, actor, before_json, after_json, reason, created_at)
           VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
        (
            audit_id,
            DEV_ORG_ID,
            brand_id,
            entity_type,
            entity_id,
            action,
            actor.strip(),
            jsonb(before) if before is not None else None,
            jsonb(after) if after is not None else None,
            reason,
            now_utc(),
        ),
    )
    return audit_id
