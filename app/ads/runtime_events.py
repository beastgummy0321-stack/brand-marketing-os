"""app/ads/runtime_events.py — Contract J (F27-I00): the ads-owned `ads_runtime_event` trail
(migration `20260922000001_ads_runtime_events.sql`). Two kinds only:

`beat` -- written every minute by the existing per-minute ads periodic task (`jobs.py`'s
`ads_runtime` cron); `org_id`/`brand_id` are always `None` -- a beat proves the whole ads
background system is alive, never any one brand's own worker (Contract K's recovery banner, a
later F27 issue, reads the gap between consecutive beats).

`queue_refresh` -- written by `app.ads.triage.refresh_queue` for the one brand it just refreshed;
`org_id`/`brand_id` are always filled (pre-dispatch correction 3).

Pure persistence: no LLM call, no platform read, no interrupt/queue write (ARCHITECTURE.md §0
"程式整理，LLM 判斷" -- this is a heartbeat log, not a judgment).
"""

from datetime import timedelta

from app.core import db

KINDS = ("beat", "queue_refresh")


def record(conn, kind: str, *, org_id: str | None = None, brand_id: str | None = None) -> None:
    """Insert one event row. `org_id`/`brand_id` default to `None` (a `beat`); `queue_refresh`
    callers pass both (correction 3)."""
    if kind not in KINDS:
        raise ValueError("kind_unknown")
    conn.execute(
        "INSERT INTO ads_runtime_event(id,kind,org_id,brand_id) VALUES(%s,%s,%s,%s)",
        (db.new_id("are"), kind, org_id, brand_id),
    )


def list_since(conn, kind: str, since, *, brand_id: str | None = None) -> list[dict]:
    """Every `kind` row at or after `since`, oldest first -- `brand_id=None` reads every row of
    that kind regardless of brand (the shape a global `beat` scan needs); passing a `brand_id`
    narrows to that brand's own rows (the shape a `queue_refresh` recovery check needs)."""
    if brand_id is None:
        rows = conn.execute(
            "SELECT * FROM ads_runtime_event WHERE kind=%s AND at>=%s ORDER BY at",
            (kind, since),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM ads_runtime_event WHERE kind=%s AND brand_id=%s AND at>=%s ORDER BY at",
            (kind, brand_id, since),
        ).fetchall()
    return [dict(row) for row in rows]


def prune(conn, *, older_than_hours: int = 48) -> int:
    """Delete every row older than `older_than_hours` (default 48h, the contract's own retention
    window) -- intentionally not filtered by org_id/brand_id: `ads_runtime_event.org_id` and
    `.brand_id` are both nullable by design (a `beat` row carries neither, see `record()` above),
    so a per-tenant sweep could never even reach a beat row. Retention here is whole-table
    housekeeping, not a tenant-scoped read -- nothing is returned to any caller beyond a row
    count, so there is no cross-tenant data exposure for org_id/brand_id scoping to guard
    against. Returns the deleted row count (tests only; callers never branch on it)."""
    cutoff = db.now_utc() - timedelta(hours=older_than_hours)
    cursor = conn.execute("DELETE FROM ads_runtime_event WHERE at<%s", (cutoff,))
    return cursor.rowcount
