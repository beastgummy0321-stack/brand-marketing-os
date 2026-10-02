"""app/ads/status_summary.py — Contract I (F27-I09): `GET /api/ads/brands/{b}/status-summary`.

Read-only, brand-wide: the freshest cleanly-synced moment among this brand's own non-closed
campaigns, how many of them are NOT syncing cleanly right now (`repository.campaign_sync_state`,
`"ok"` being the only state that doesn't count), and how many decisions are still waiting.

F47 Contract D: `open_items` is read from the same brand queue the home board reads
(`triage.get_queue`, each row carrying `done` from `queue_done.done`) and counts exactly the rows
the home 「需要你決定」 counts (`queue_done.open_count`) -- a deferred or decided row is not
waiting, so the top bar and the home can never disagree. Never a recount of open interrupts alone.
"""

from app.ads import queue_done, repository, triage


def get_status_summary(conn, org_id: str, brand_id: str) -> dict:
    rows = conn.execute(
        "SELECT * FROM ads_campaign WHERE org_id=%s AND brand_id=%s AND status != 'closed'",
        (org_id, brand_id),
    ).fetchall()
    accounts_cache: dict = {}
    last_success_at = None
    failing_campaigns = 0
    for row in rows:
        campaign = dict(row)
        sync = repository.campaign_sync_state(
            conn, org_id, brand_id, campaign, accounts_cache=accounts_cache,
        )
        if sync["state"] != "ok":
            failing_campaigns += 1
        elif sync["last_success_at"] is not None and (
            last_success_at is None or sync["last_success_at"] > last_success_at
        ):
            last_success_at = sync["last_success_at"]
    queue = triage.get_queue(conn, org_id, brand_id)
    return {
        "last_success_at": last_success_at,
        "failing_campaigns": failing_campaigns,
        "open_items": queue_done.open_count(queue["items"]),
    }
