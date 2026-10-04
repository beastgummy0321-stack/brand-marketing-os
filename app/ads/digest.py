"""F29-I08 Contract J: the brand's daily digest of its decision queue, delivered into the in-app
inbox only.

One builder (`build`) and one sender per channel (`SENDERS`): a later channel (LINE, email) adds a
sender here and never rewrites the digest. Nothing leaves the app today.

The digest never classifies anything itself: its items are the open rows of the same brand queue
the ads home reads (`triage.get_queue`, or the payload `triage.refresh_queue` just returned) --
its open decision rows (F49 Contract Q), settle and closeout rows included, in the queue's order.
The inbox row it writes has its own category (`ads_daily_digest`, informational) outside
`triage.QUEUE_CATEGORY`, so it never counts toward the home decisions or the brand health colour.
"""

from datetime import date

from app.ads import triage
from app.brand_intelligence.background_job import notify
from app.core import interrupts

CATEGORY = "ads_daily_digest"
MAX_ITEMS = 5


def dedupe_key(brand_id: str, day: date) -> str:
    return f"ads-digest:{brand_id}:{day.isoformat()}"


def build(conn, org_id: str, brand_id: str, today: date, *,
          queue: dict | None = None) -> dict | None:
    """`{date, open_count, items: [{kind, message, action_url}] <= 5}`, or `None` when the brand
    queue has nothing open. `queue`: the payload the caller already holds (the 06:30 refresh
    passes `refresh_queue`'s own return), so the queue is never derived a second time."""
    if queue is None:
        queue = triage.get_queue(conn, org_id, brand_id)
    # F49 Contract Q: the open decision rows, counted as the home and the top bar count them
    # (`decisions.open`) -- notices and done rows are not waiting on anyone.
    rows = [row for row in queue["items"] if row["decision"] and not row["done"]]
    if not rows:
        return None
    return {
        "date": today.isoformat(),
        "open_count": queue["decisions"]["open"],
        "items": [
            {"kind": row["kind_key"], "message": row["message"], "action_url": row["action_url"]}
            for row in rows[:MAX_ITEMS]
        ],
    }


def inbox_message(digest: dict) -> str:
    """One inbox line within `interrupts.MAX_MESSAGE_LEN`: the count, plus the first row's own
    message when both fit."""
    head = f"投放今日 {digest['open_count']} 件待處理"
    full = f"{head}：{digest['items'][0]['message']}"
    return full if len(full) <= interrupts.MAX_MESSAGE_LEN else head


def close_previous_inbox(conn, org_id: str, brand_id: str, keep_key: str | None) -> None:
    """Resolve every open digest row of this brand except `keep_key` (today's, when today has
    one) -- the inbox holds at most the latest digest, and none once nothing is open."""
    for row in interrupts.list_open(conn, org_id=org_id, brand_id=brand_id, category=CATEGORY,
                                    archive_stale=False):
        if row["dedupe_key"] != keep_key:
            interrupts.resolve(conn, row["id"], actor="system", org_id=org_id)


def send_inbox(conn, org_id: str, brand_id: str, digest: dict) -> None:
    """One `ads_daily_digest` inbox row per brand per day (dedupe `ads-digest:<brand>:<date>`),
    opening the ads home."""
    notify(conn, brand_id, category=CATEGORY,
           dedupe_key=dedupe_key(brand_id, date.fromisoformat(digest["date"])),
           message=inbox_message(digest), action_url=f"/brands/{brand_id}/ads")


SENDERS = {"inbox": send_inbox}


def deliver(conn, org_id: str, brand_id: str, today: date, *,
            queue: dict | None = None) -> dict | None:
    """Build once; close every earlier inbox digest (all of them when nothing is open today),
    then hand today's digest, if any, to every registered sender. `None` = nothing sent."""
    digest = build(conn, org_id, brand_id, today, queue=queue)
    close_previous_inbox(conn, org_id, brand_id,
                         dedupe_key(brand_id, today) if digest is not None else None)
    if digest is None:
        return None
    for send in SENDERS.values():
        send(conn, org_id, brand_id, digest)
    return digest
