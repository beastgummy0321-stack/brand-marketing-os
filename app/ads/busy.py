"""app/ads/busy.py — F50 Contract J (R7 B4): a long planner call survives a reload and a second
press. Private to app/ads: only `routes.py` imports it.

- `claim(conn, scope_id, kind)`: a session advisory lock (`pg_try_advisory_lock`) on this
  request's connection, held for the whole call and released in `finally`. A session lock is
  not a transaction lock: `gateway.run_task`'s commits and rollbacks inside the call leave it
  held; only `pg_advisory_unlock` or the session's end releases it (the pool's reset runs `RESET
  ROLE`／`RESET app.org_id` only, so the unlock here is what releases it). Held elsewhere ->
  `CampaignBusy` (409 `campaign_busy`). Strategy generation and adoption key it by campaign; a
  brief parse runs before its campaign exists and keys it by brand.
- `busy_state(conn, org, brand, campaign_id)`: `{kind, since}` of the newest `running` planner
  row of this campaign (task type -> kind below) started within its call's timeout + 30 s, else
  `None` -- an older `running` row is a crashed call, not busy.
"""

from contextlib import contextmanager
from datetime import timedelta

from app.ads import brief, plan, strategy
from app.ads import repository as ads_repo
from app.core import db

BUSY_MESSAGE = "上一次還在處理，等它好了再看。"

GRACE_S = 30.0

#: task type -> (busy kind, that call's timeout in seconds).
PLANNER_TASKS = {
    "ads_strategy": ("strategy", strategy.TIMEOUT_S),
    "ads_delivery_plan": ("plan", plan.TIMEOUT_S),
    "ads_brief_parse": ("brief", brief.TIMEOUT_S),
}


class CampaignBusy(ValueError):
    """`str()` is the code `campaign_busy`; `kind` is the call that was refused."""

    def __init__(self, kind: str):
        super().__init__("campaign_busy")
        self.kind = kind


def _lock_key(scope_id: str) -> str:
    return f"ads_busy:{scope_id}"


@contextmanager
def claim(conn, scope_id: str, kind: str):
    """Hold the planner lock of `scope_id` (a campaign id; a brand id for the brief parse) for the
    `with` body, or raise `CampaignBusy(kind)` at once when another session holds it."""
    key = _lock_key(scope_id)
    row = conn.execute(
        "SELECT pg_try_advisory_lock(hashtextextended(%s, 0)) AS held", (key,),
    ).fetchone()
    if not row or not row["held"]:
        raise CampaignBusy(kind)
    try:
        yield
    finally:
        _release(conn, key)


def _release(conn, key: str) -> None:
    """Unlock even when the body left the transaction aborted: an aborted transaction refuses
    every statement, so it is rolled back first (its work was lost already). An unlock takes
    effect whatever the surrounding transaction does later."""
    sql = "SELECT pg_advisory_unlock(hashtextextended(%s, 0))"
    try:
        conn.execute(sql, (key,))
    except Exception:  # the aborted-transaction error of whichever driver backs `conn`
        conn.rollback()
        conn.execute(sql, (key,))


def busy_state(conn, org_id: str, brand_id: str, campaign_id: str) -> dict | None:
    """`{kind, since}` (ISO instant the running call started) or `None` (Contract J)."""
    now = db.now_utc()
    longest = max(timeout for _, timeout in PLANNER_TASKS.values())
    rows = ads_repo.running_planner_tasks(
        conn, org_id, brand_id, campaign_id, task_types=list(PLANNER_TASKS),
        started_after=now - timedelta(seconds=longest + GRACE_S),
    )
    for row in rows:
        kind, timeout = PLANNER_TASKS[row["task_type"]]
        if row["started_at"] > now - timedelta(seconds=timeout + GRACE_S):
            return {"kind": kind, "since": row["started_at"].isoformat()}
    return None
