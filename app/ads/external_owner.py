"""app/ads/external_owner.py — does another org hold this platform id in the ads center?

F31-I03 (item 5): `app.meta.repository._refuse_if_parent_owned_by_another_org` refuses a
parent id (campaign/ad set) that another org owns before any name match reaches Meta. It only
knew the schedule module's `channel_entity_map`; the ads center records its own bindings on
`ads_campaign`/`ads_delivery_group`/`ads_ad` (`external_id`) and lists synced platform objects
in `ads_external_entity` (`native_id`). `app.meta` sits below `app.ads` in `LAYER_ORDER` and
may not import it, so this module answers the question and `app/ads/__init__.py` registers it
through `app.meta.repository.register_parent_owner_check` at import time.

Any recorded id counts, whatever its `local_state`: a detached or retired row still names an
object living in that org's ad account.

Known limit (measured 2026-09-26, same as the `channel_entity_map` half of the guard): every
`ads_*` table has org-isolation RLS, and a request connection runs as `authenticated` scoped to
the caller's org after `require_actor()`. There, other orgs' rows are invisible, so this query
finds nothing; it only sees them on an unscoped connection. Closing that needs a database-side
lookup (e.g. a SECURITY DEFINER function), which is a migration outside this issue.
"""

_OTHER_ORG_HOLDS_ID = (
    "SELECT 1 FROM ads_campaign WHERE external_id = %(id)s AND org_id <> %(org)s"
    " UNION ALL SELECT 1 FROM ads_delivery_group WHERE external_id = %(id)s AND org_id <> %(org)s"
    " UNION ALL SELECT 1 FROM ads_ad WHERE external_id = %(id)s AND org_id <> %(org)s"
    " UNION ALL SELECT 1 FROM ads_external_entity"
    "   WHERE platform = 'meta' AND native_id = %(id)s AND org_id <> %(org)s"
    " LIMIT 1"
)


def owned_by_another_org(conn, org_id: str, external_id: str) -> bool:
    """True when another org bound or lists `external_id` in the ads center."""
    row = conn.execute(_OTHER_ORG_HOLDS_ID, {"id": external_id, "org": org_id}).fetchone()
    return row is not None
