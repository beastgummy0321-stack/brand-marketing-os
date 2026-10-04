"""app/ads/status_summary.py — Contract I (F27-I09): `GET /api/ads/brands/{b}/status-summary`.

Read-only, brand-wide: the freshest cleanly-synced moment among this brand's own non-closed
campaigns, how many data sources need the user, and how many decisions are still waiting.

F47 Contract D: `open_items` is read from the same brand queue the home board reads
(`triage.get_queue`, each row carrying `done` from `queue_done.done`) and counts exactly the rows
the home 「需要你決定」 counts (`queue_done.open_count`) -- a deferred or decided row is not
waiting, so the top bar and the home can never disagree. Never a recount of open interrupts alone.

F47 Contract H: `attention` is the connections page's own read (`connections.get_connections`):
`count` is that page's `attention_count` and `note` the note of the first source it counts, in the
page's order (null when none) -- the top bar links to that page, so the two can never disagree. A
draft never on a platform has no source row there, so it is never counted.
"""

from app.ads import connections, lifecycle, queue_done, repository, triage


def _attention(conn, org_id: str, brand_id: str) -> dict:
    view = connections.get_connections(conn, org_id, brand_id)
    first = next(
        (s for s in view["sources"] if s["state"] not in connections._ATTENTION_FREE), None
    )
    return {"count": view["attention_count"], "note": first["note"] if first else None}


def get_status_summary(conn, org_id: str, brand_id: str) -> dict:
    rows = lifecycle.campaigns(conn, org_id, brand_id, lifecycle.NOT_CLOSED)
    accounts_cache: dict = {}
    last_success_at = None
    for row in rows:
        campaign = dict(row)
        sync = repository.campaign_sync_state(
            conn, org_id, brand_id, campaign, accounts_cache=accounts_cache,
        )
        if sync["state"] == "ok" and sync["last_success_at"] is not None and (
            last_success_at is None or sync["last_success_at"] > last_success_at
        ):
            last_success_at = sync["last_success_at"]
    queue = triage.get_queue(conn, org_id, brand_id)
    return {
        "last_success_at": last_success_at,
        "attention": _attention(conn, org_id, brand_id),
        "open_items": queue_done.open_count(queue["items"]),
    }
