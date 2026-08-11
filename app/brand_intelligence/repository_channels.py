# -*- coding: utf-8 -*-
"""app/brand_intelligence/repository_channels.py — Owned Channel（自有渠道）存取層。

從 `repository.py` 拆出（票 B2-library 第二段）：`repository.py` 行數已頂到
`docs/tech-debt.md` 凍結的行數上限，新增 `update_channel`／`delete_channel` 前
必須先拆，不得再往超標檔案裡加（CLAUDE.md 第五節）。`repository.py` 保留一行
re-export（`from app.brand_intelligence.repository_channels import ...`），既有呼叫端
`repo.create_channel()`／`repo.list_channels()` 寫法不必改。

`_require`／`_row`／`_rows` 在這裡各自留一份小的（不從 `repository.py` import）：
`repository.py` 要 import 本檔做 re-export，本檔若反過來 import `repository.py`
會形成 import 環，兩者不能互相 import。

對外進入點：本檔的五個公開函式（`create_channel`／`list_channels`／`get_channel`／
`update_channel`／`delete_channel`）。誰依賴它：`repository.py`（re-export）、
`app/brand_intelligence/routes.py`（`channels/new`）、
`app/brand_intelligence/routes_library.py`（渠道編輯／刪除、整包讀取）、
`app/ads/handoff.py`（`list_channels` 找預設到達網址）、`app/seed_demo.py`。
"""

import sqlite3
from typing import Optional

from app.core.audit import write_audit
from app.core.db import new_id, now_iso


def _require(value, message: str) -> None:
    if value is None or (isinstance(value, str) and not value.strip()):
        raise ValueError(message)


def _row(cursor_row) -> Optional[dict]:
    return dict(cursor_row) if cursor_row is not None else None


def _rows(cursor) -> list:
    return [dict(r) for r in cursor.fetchall()]


_CHANNEL_PLATFORM_DEFAULT = {"website": "web", "fb_page": "meta", "ig_account": "meta"}


def create_channel(conn: sqlite3.Connection, brand_id: str, *, actor: str, channel_type: str,
                    name: str, identifier: Optional[str] = None, status: str = "active",
                    platform: Optional[str] = None) -> dict:
    _require(channel_type, "owned_channel.channel_type 為必填")
    _require(name, "owned_channel.name 為必填")
    _require(actor, "actor 為必填")
    if status not in ("active", "inactive"):
        raise ValueError("owned_channel.status 只能是 active 或 inactive")
    resolved_platform = platform or _CHANNEL_PLATFORM_DEFAULT.get(channel_type, "web")
    channel_id = new_id("och")
    ts = now_iso()
    row = {
        "id": channel_id, "brand_id": brand_id, "channel_type": channel_type,
        "platform": resolved_platform, "name": name, "identifier": identifier, "status": status,
        "created_at": ts, "updated_at": ts,
    }
    conn.execute(
        "INSERT INTO owned_channel (id, brand_id, channel_type, platform, name, identifier, status, "
        "created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (row["id"], row["brand_id"], row["channel_type"], row["platform"], row["name"],
         row["identifier"], row["status"], row["created_at"], row["updated_at"]),
    )
    write_audit(conn, brand_id=brand_id, entity_type="owned_channel", entity_id=channel_id,
                action="create", actor=actor, before=None, after=row)
    conn.commit()
    return row


def list_channels(conn: sqlite3.Connection, brand_id: str) -> list:
    return _rows(conn.execute(
        "SELECT * FROM owned_channel WHERE brand_id = ? ORDER BY created_at", (brand_id,)
    ))


def get_channel(conn: sqlite3.Connection, brand_id: str, channel_id: str) -> Optional[dict]:
    return _row(conn.execute(
        "SELECT * FROM owned_channel WHERE id = ? AND brand_id = ?", (channel_id, brand_id)
    ).fetchone())


def update_channel(conn: sqlite3.Connection, brand_id: str, channel_id: str, *, actor: str,
                    channel_type: str, name: str, identifier: Optional[str] = None,
                    status: str = "active") -> dict:
    """編輯自有渠道（票 B2-library S5.31）：人工編輯直接生效，比照 update_rule。渠道不是
    AI 生成的 context 輸入，不像 brand_fact／rule／claim 那樣要 bump knowledge_version
    （create_channel 原本就沒 bump，這裡保持一致）。"""
    _require(channel_type, "owned_channel.channel_type 為必填")
    _require(name, "owned_channel.name 為必填")
    _require(actor, "actor 為必填")
    if status not in ("active", "inactive"):
        raise ValueError("owned_channel.status 只能是 active 或 inactive")
    before = get_channel(conn, brand_id, channel_id)
    if before is None:
        raise ValueError(f"找不到自有渠道：{channel_id}")
    platform = _CHANNEL_PLATFORM_DEFAULT.get(channel_type, "web")
    ts = now_iso()
    conn.execute(
        "UPDATE owned_channel SET channel_type = ?, platform = ?, name = ?, identifier = ?, "
        "status = ?, updated_at = ? WHERE id = ? AND brand_id = ?",
        (channel_type, platform, name, identifier, status, ts, channel_id, brand_id),
    )
    after = get_channel(conn, brand_id, channel_id)
    write_audit(conn, brand_id=brand_id, entity_type="owned_channel", entity_id=channel_id,
                action="update", actor=actor, before=before, after=after)
    conn.commit()
    return after


def delete_channel(conn: sqlite3.Connection, brand_id: str, channel_id: str, *, actor: str) -> None:
    """硬刪除，比照 repository.py `_delete_entity` 模式（決策 0013：把關人可直接清資料）。"""
    _require(actor, "actor 為必填")
    before = get_channel(conn, brand_id, channel_id)
    if before is None:
        raise ValueError(f"找不到自有渠道：{channel_id}")
    conn.execute("DELETE FROM owned_channel WHERE id = ? AND brand_id = ?", (channel_id, brand_id))
    write_audit(conn, brand_id=brand_id, entity_type="owned_channel", entity_id=channel_id,
                action="delete", actor=actor, before=before, after=None,
                reason="把關人刪除（決策 0013）")
    conn.commit()
