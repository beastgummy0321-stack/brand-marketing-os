"""app/ads/runtime_events.py — Contract J (F27-I00), rescoped by F27-I24 (pre-dispatch
correction 12, superseding correction 3): the ads-owned `ads_runtime_event` trail (migration
`20260922000001_ads_runtime_events.sql`, rescoped by `20260922000002_ads_runtime_events_scoped
.sql`). Two kinds only, BOTH fully tenant-scoped now -- `org_id`/`brand_id` are NOT NULL on every
row (the tenant isolation gates require it; there is no documented brand-agnostic exception for
this table):

`beat` -- written every minute by the existing per-minute ads periodic task (`jobs.py`'s
`ads_runtime` cron), once per (org_id, brand_id) that has at least one non-closed `ads_campaign`
-- proves that brand's own slice of the ads background system is alive (Contract K's recovery
banner reads the gap between a brand's own consecutive beats).

`queue_refresh` -- written by `app.ads.triage.refresh_queue` for the one brand it just refreshed.

Pure persistence: no LLM call, no platform read, no interrupt/queue write (ARCHITECTURE.md §0
"程式整理，LLM 判斷" -- this is a heartbeat log, not a judgment).
"""

from datetime import timedelta

from app.core import db

KINDS = ("beat", "queue_refresh")


def record(conn, kind: str, *, org_id: str, brand_id: str) -> None:
    """Insert one event row, always scoped to a tenant (both kinds, since correction 12)."""
    if kind not in KINDS:
        raise ValueError("kind_unknown")
    conn.execute(
        "INSERT INTO ads_runtime_event(id,kind,org_id,brand_id) VALUES(%s,%s,%s,%s)",
        (db.new_id("are"), kind, org_id, brand_id),
    )


def list_since(conn, kind: str, since, *, brand_id: str) -> list[dict]:
    """Every `kind` row of `brand_id` at or after `since`, oldest first -- the shape both the
    recovery-gap beat scan and the `queue_refresh` recovery check need (both are per-brand since
    correction 12)."""
    rows = conn.execute(
        "SELECT * FROM ads_runtime_event WHERE kind=%s AND brand_id=%s AND at>=%s ORDER BY at",
        (kind, brand_id, since),
    ).fetchall()
    return [dict(row) for row in rows]


def prune(conn, *, older_than_hours: int = 48) -> int:
    """Delete every row older than `older_than_hours` (default 48h, the contract's own retention
    window) across every tenant -- retention here is whole-table housekeeping (called once an
    hour from the same per-minute periodic task that writes each tenant's own beat), not a
    tenant-scoped read: nothing is returned to any caller beyond a row count, so there is no
    cross-tenant data exposure for org_id/brand_id scoping to guard against. Returns the deleted
    row count (tests only; callers never branch on it)."""
    cutoff = db.now_utc() - timedelta(hours=older_than_hours)
    cursor = conn.execute("DELETE FROM ads_runtime_event WHERE at<%s", (cutoff,))
    return cursor.rowcount
