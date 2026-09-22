"""app/ads/status_summary.py — Contract I (F27-I09): `GET /api/ads/brands/{b}/status-summary`.

Read-only, brand-wide: the freshest cleanly-synced moment among this brand's own non-closed
campaigns, how many of them are NOT syncing cleanly right now (`repository.campaign_sync_state`,
`"ok"` being the only state that doesn't count), and how many open `ads_triage_*` queue rows
(`app/core/interrupts`, the six kinds `triage.QUEUE_CATEGORY` registers) are waiting on a
decision. The same one summary a later issue's top bar and wait page both read through -- never a
per-page recount of the same numbers.
"""

from app.ads import repository, triage
from app.core import interrupts


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
    triage_categories = set(triage.QUEUE_CATEGORY.values())
    open_items = sum(
        1
        for row in interrupts.list_open(conn, brand_id=brand_id, archive_stale=False)
        if row["category"] in triage_categories
    )
    return {
        "last_success_at": last_success_at,
        "failing_campaigns": failing_campaigns,
        "open_items": open_items,
    }
