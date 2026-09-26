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

F31-I13: the lookup is the SECURITY DEFINER function `ads_external_id_owned_elsewhere`
(`supabase/migrations/20260927000021_ads_external_owner_fn.sql`), which returns only a boolean.
A plain SELECT found nothing on a request connection: every `ads_*` table has org-isolation
RLS and a request runs as `authenticated` scoped to the caller's org.
"""


def owned_by_another_org(conn, org_id: str, external_id: str) -> bool:
    """True when another org bound or lists `external_id` in the ads center."""
    row = conn.execute(
        "SELECT ads_external_id_owned_elsewhere(%s, %s) AS owned", (external_id, org_id),
    ).fetchone()
    return bool(row and row["owned"])
