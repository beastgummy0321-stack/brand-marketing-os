"""app/identity/repository.py — app_user / membership / org_invite / organisation access.

Private: only app/identity/__init__.py and app/identity/routes.py import this (container
contract §1). All queries here are already org-scoped by construction (membership rows are
looked up by org_id + user_id together; organisation rows are only ever touched via a
membership row the caller already holds) — there is no "list everything" entry point.
"""

import secrets
from datetime import timedelta
from uuid import UUID

from app.core.db import Conn, ConnProxy, new_id, now_utc

INVITE_TTL_DAYS = 7


def get_user(conn: Conn | ConnProxy, user_id: UUID) -> dict | None:
    row = conn.execute(
        "SELECT id, email, created_at FROM app_user WHERE id = %s", (str(user_id),)
    ).fetchone()
    return dict(row) if row else None


def create_user(conn: Conn | ConnProxy, user_id: UUID, email: str) -> bool:
    """Idempotent insert (`ON CONFLICT (id) DO NOTHING`) — returns whether this call actually
    inserted the row. Ticket 03-1 r1 defect 3: two concurrent first logins for the same `sub`
    used to both pass a `get_user() is None` check and then both INSERT, crashing on the
    duplicate key. Now every request just tries to insert; only the one that actually inserted
    (`rowcount > 0`) is the "winner" that goes on to create the personal organisation +
    membership — the loser sees `False` and does nothing, safe to call unconditionally."""
    cursor = conn.execute(
        "INSERT INTO app_user (id, email, created_at) VALUES (%s, %s, %s)"
        " ON CONFLICT (id) DO NOTHING",
        (str(user_id), email, now_utc()),
    )
    return cursor.rowcount > 0


def create_membership(conn: Conn | ConnProxy, org_id: str, user_id: UUID, role: str) -> None:
    """`ON CONFLICT DO NOTHING` on the (org_id, user_id) primary key — same idempotency
    treatment as `create_user` (ticket 03-1 r1 defect 3) for the two call sites that reach
    here (first-login's owner membership, invite acceptance), in case either double-fires."""
    conn.execute(
        "INSERT INTO membership (org_id, user_id, role, created_at) VALUES (%s, %s, %s, %s)"
        " ON CONFLICT (org_id, user_id) DO NOTHING",
        (org_id, str(user_id), role, now_utc()),
    )


def create_personal_organisation(conn: Conn | ConnProxy, name: str) -> str:
    org_id = new_id("org")
    conn.execute(
        "INSERT INTO organisation (id, name, kind, created_at) VALUES (%s, %s, 'personal', %s)",
        (org_id, name, now_utc()),
    )
    return org_id


def get_organisation(conn: Conn | ConnProxy, org_id: str) -> dict | None:
    row = conn.execute(
        "SELECT id, name, kind, created_at FROM organisation WHERE id = %s", (org_id,)
    ).fetchone()
    return dict(row) if row else None


def rename_organisation(conn: Conn | ConnProxy, org_id: str, name: str) -> None:
    conn.execute(
        "UPDATE organisation SET kind = 'company', name = %s WHERE id = %s", (name, org_id)
    )


def get_membership(conn: Conn | ConnProxy, org_id: str, user_id: UUID) -> dict | None:
    row = conn.execute(
        "SELECT org_id, user_id, role, created_at FROM membership"
        " WHERE org_id = %s AND user_id = %s",
        (org_id, str(user_id)),
    ).fetchone()
    return dict(row) if row else None


def list_memberships(conn: Conn | ConnProxy, user_id: UUID) -> list:
    """每一列＝這個使用者所屬的一個組織，附上組織名稱／種類（/api/identity/me 用）。"""
    rows = conn.execute(
        """SELECT m.org_id, m.role, o.name AS org_name, o.kind AS org_kind
           FROM membership m JOIN organisation o ON o.id = m.org_id
           WHERE m.user_id = %s ORDER BY m.created_at""",
        (str(user_id),),
    )
    return [dict(r) for r in rows]


def get_personal_membership(conn: Conn | ConnProxy, user_id: UUID) -> dict | None:
    row = conn.execute(
        """SELECT m.org_id, m.role FROM membership m JOIN organisation o ON o.id = m.org_id
           WHERE m.user_id = %s AND o.kind = 'personal'""",
        (str(user_id),),
    ).fetchone()
    return dict(row) if row else None


def count_owners(conn: Conn | ConnProxy, org_id: str) -> int:
    row = conn.execute(
        "SELECT count(*) AS n FROM membership WHERE org_id = %s AND role = 'owner'", (org_id,)
    ).fetchone()
    return row["n"] if row else 0


def remove_membership(conn: Conn | ConnProxy, org_id: str, user_id: UUID) -> None:
    conn.execute(
        "DELETE FROM membership WHERE org_id = %s AND user_id = %s", (org_id, str(user_id))
    )


def create_invite(
    conn: Conn | ConnProxy, org_id: str, email: str, role: str, created_by: UUID
) -> dict:
    invite_id = new_id("inv")
    token = secrets.token_urlsafe(32)
    expires_at = now_utc() + timedelta(days=INVITE_TTL_DAYS)
    conn.execute(
        """INSERT INTO org_invite
           (id, org_id, email, role, token, expires_at, created_by, created_at)
           VALUES (%s, %s, %s, %s, %s, %s, %s, %s)""",
        (invite_id, org_id, email, role, token, expires_at, str(created_by), now_utc()),
    )
    return {
        "id": invite_id, "org_id": org_id, "email": email, "role": role,
        "token": token, "expires_at": expires_at,
    }


def get_invite_by_token(conn: Conn | ConnProxy, token: str) -> dict | None:
    row = conn.execute(
        """SELECT id, org_id, email, role, token, expires_at, accepted_at, created_by, created_at
           FROM org_invite WHERE token = %s""",
        (token,),
    ).fetchone()
    return dict(row) if row else None


def accept_invite(
    conn: Conn | ConnProxy, invite_id: str, user_id: UUID, org_id: str, role: str
) -> None:
    """同一交易內：標記邀請已用、加入 membership（呼叫端已檢查過期/已用/驗證過 token）。"""
    conn.execute("UPDATE org_invite SET accepted_at = %s WHERE id = %s", (now_utc(), invite_id))
    create_membership(conn, org_id, user_id, role)
