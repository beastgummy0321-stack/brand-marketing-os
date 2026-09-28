"""F37 test seeding for the one performance pipeline (Contract P).

An internal campaign's performance rows are `ads_external_daily` rows of the platform entities
its local nodes are bound to. Tests build that shape here instead of writing a daily table by
hand: `bind_platform` registers the campaign → adset → ad entity chain (platform `"test"`) and
gives every local group/ad an `external_id`; `seed_day` writes one observation for one local
node and day; `set_coverage` records the observations read range the coverage rule reads.
Unknown metrics stay `None` -- nothing here fills a default for purchases or revenue.
"""

from datetime import date

from app.ads import external_repository
from app.ads import repository as ads_repo

PLATFORM = "test"
SOURCE_ACCOUNT = "test"
ATTRIBUTION_KEY = "test"
_SCOPE = {"group": "adset", "ad": "ad"}
_TABLE = {"group": "ads_delivery_group", "ad": "ads_ad"}


def _detail(conn, org_id, brand_id, campaign_detail):
    if isinstance(campaign_detail, str):
        detail = ads_repo.campaign_detail(conn, org_id, brand_id, campaign_detail)
        if detail is None:
            raise ValueError("campaign_unknown")
        return detail
    return campaign_detail


def bind_platform(conn, org_id, brand_id, campaign_detail) -> dict:
    """Register the entity chain of `campaign_detail` (a `repository.campaign_detail` dict or a
    campaign id) and bind every local group/ad that has no `external_id` yet. A node already
    bound keeps its id. Returns `local node id -> ads_external_entity.id`."""
    detail = _detail(conn, org_id, brand_id, campaign_detail)
    campaign_id = detail["id"]
    campaign_native = detail.get("external_id") or f"tc_{campaign_id}"

    def register(kind, native_id, name, parent=None):
        # A node already on a platform of this campaign keeps that entity (one native id, one
        # entity -- a second copy would make the binding ambiguous).
        existing = conn.execute(
            "SELECT id FROM ads_external_entity WHERE org_id = %s AND brand_id = %s"
            " AND campaign_id = %s AND native_kind = %s AND native_id = %s",
            (org_id, brand_id, campaign_id, kind, native_id),
        ).fetchall()
        if len(existing) == 1:
            return existing[0]["id"]
        fields = {
            "platform": PLATFORM, "source_account": SOURCE_ACCOUNT, "native_kind": kind,
            "native_id": native_id, "name": name, "native_status": "ACTIVE",
        }
        if parent is not None:
            fields["parent_native_kind"], fields["parent_native_id"] = parent
        return external_repository.upsert_entity(conn, org_id, brand_id, campaign_id, fields)["id"]

    def bind(kind, node, prefix):
        native = node.get("external_id")
        if not native:
            native = f"{prefix}_{node['id']}"
            conn.execute(
                f"UPDATE {_TABLE[kind]} SET external_id = %s"  # noqa: S608 — module constant
                " WHERE org_id = %s AND brand_id = %s AND id = %s",
                (native, org_id, brand_id, node["id"]),
            )
        return native

    ids = {campaign_id: register("campaign", campaign_native, detail.get("name"))}
    for group in detail["groups"]:
        group_native = bind("group", group, "tg")
        ids[group["id"]] = register(
            "adset", group_native, group.get("name"), ("campaign", campaign_native),
        )
        for ad in group.get("ads") or []:
            ad_native = bind("ad", ad, "ta")
            ids[ad["id"]] = register("ad", ad_native, ad.get("name"), ("adset", group_native))
    return ids


def seed_day(conn, org_id, brand_id, campaign_id, kind, local_id, day: date, *, spend,
             impressions=0, clicks=0, purchases=None, revenue=None, source="test",
             attribution_key=ATTRIBUTION_KEY, currency="TWD") -> dict:
    """One observation of local node `local_id` (`kind` "group"/"ad") on `day`, written the way
    a platform read writes it. A node not yet on the test platform is bound first
    (`bind_platform` over its whole campaign)."""

    def lookup():
        node = conn.execute(
            f"SELECT external_id FROM {_TABLE[kind]}"  # noqa: S608 — module constant
            " WHERE org_id = %s AND brand_id = %s AND id = %s",
            (org_id, brand_id, local_id),
        ).fetchone()
        if node is None:
            raise ValueError("node_unknown")
        if not node["external_id"]:
            return None
        return conn.execute(
            "SELECT id FROM ads_external_entity WHERE org_id = %s AND brand_id = %s"
            " AND campaign_id = %s AND native_kind = %s AND native_id = %s",
            (org_id, brand_id, campaign_id, _SCOPE[kind], node["external_id"]),
        ).fetchone()

    entity = lookup()
    if entity is None:
        bind_platform(conn, org_id, brand_id, campaign_id)
        entity = lookup()
    if entity is None:
        raise ValueError("entity_not_registered")
    return external_repository.upsert_observation(conn, org_id, brand_id, campaign_id, {
        "entity_id": entity["id"], "day": day, "metric_scope": _SCOPE[kind],
        "attribution_key": attribution_key, "currency": currency, "spend": spend,
        "impressions": impressions, "clicks": clicks, "purchases": purchases,
        "revenue": revenue, "source": source,
    })


def set_coverage(conn, org_id, brand_id, campaign_id, start: date, end: date) -> None:
    """Record `[start, end]` as the campaign's successfully read observations range."""
    external_repository.record_sync(
        conn, org_id, brand_id, campaign_id, section="observations",
        state={"status": "success", "coverage": {"start": start.isoformat(),
                                                   "end": end.isoformat()}},
    )
