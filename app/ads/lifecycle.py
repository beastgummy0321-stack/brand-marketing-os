"""app/ads/lifecycle.py — F49 Contract L: the one owner of "what state is this campaign in" and
"is this ad running". Pure rules plus the selectors that pick campaigns by state; no platform
literal -- an object's delivery comes from its platform adapter (`adapters.delivery`, the same
lazy dispatch seam as `adapters.is_auth_error`).

Delivery (one platform object): `running | not_running | off | unknown`, with the word the screen
prints. `ad_running` -> True (running) | False (not_running, off) | None (unknown); an unknown ad
is judged, never dropped (§6.30). `may_spend` = not off.

Campaign state: `draft | live | ended | closed`.
- internal: closed <= stored `closed`; draft <= stored `draft`／`ready` with no root entity read;
  ended <= stored `ended`, or `end_date < today` once on a platform (the end date is the last
  delivery day); live otherwise.
- imported: draft <= no root entity read; ended <= the root's delivery is `off` or the root's
  `end_date < today`; live otherwise. Never closed (closeout is internal-only).
Explicit transitions stay where they are (adopt -> ready, `bind_campaign` -> live, closeout ->
closed); the derived ones are written only by `record`. Readers call `state`, never the stored
derived value alone.

Selection: `campaigns`／`campaign_ids`／`brands`／`monitored_ids` are the only "which campaigns"
selectors (`monitored_ids` = what the background runtime reads, F49 Contract N) -- the
campaign-status selection SQL lives here and nowhere else in `app/ads`
(`app/tests/test_ads_one_ruler.py`).
"""

from datetime import UTC, date, datetime, timedelta

from app.core import settings

ENDED_GRACE_DAYS = 7
STATES = ("draft", "live", "ended", "closed")
NOT_CLOSED = frozenset({"draft", "live", "ended"})
LABELS = {"draft": "草稿", "live": "投放中", "ended": "已結束・待結案", "closed": "已結案"}
IMPORTED_LABELS = {**LABELS, "ended": "已結束"}
_CLOSABLE = frozenset({"live", "ended"})


# ---------------------------------------------------------------------------
# delivery (one platform object)
# ---------------------------------------------------------------------------


def delivery(entity: dict) -> dict:
    """`{state, label}` of one `ads_external_entity`-shaped dict (`platform`, `native_status`)."""
    from app.ads import adapters  # lazy: adapters -> manual -> … -> modules importing this one

    return adapters.delivery(entity.get("platform"), entity.get("native_status"))


def ad_running(entity: dict) -> bool | None:
    state = delivery(entity)["state"]
    if state == "running":
        return True
    if state == "unknown":
        return None
    return False


def judged(entity: dict) -> bool:
    """The ads a grade is given to: running, and unknown (never dropped)."""
    return ad_running(entity) is not False


def may_spend(entity: dict) -> bool:
    return delivery(entity)["state"] != "off"


def gone(entity: dict) -> bool:
    """The object is no longer on the platform (an `off` status the adapter calls gone)."""
    from app.ads import adapters

    return adapters.gone(entity.get("platform"), entity.get("native_status"))


# ---------------------------------------------------------------------------
# campaign state
# ---------------------------------------------------------------------------


def _as_date(value) -> date | None:
    if value is None or isinstance(value, date) and not isinstance(value, datetime):
        return value
    if isinstance(value, datetime):
        return value.date()
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def _imported(campaign: dict) -> bool:
    return campaign.get("origin") == "imported"


def state(campaign: dict, *, root: dict | None, today: date) -> str:
    """`draft | live | ended | closed` (module docstring). `root` is the campaign's root
    `ads_external_entity` row (`root()`／`roots()`), or None when none was read."""
    stored = campaign.get("status")
    if stored == "closed":
        return "closed"
    if _imported(campaign):
        if root is None:
            return "draft"
        end = _as_date(root.get("end_date"))
        if delivery(root)["state"] == "off" or (end is not None and end < today):
            return "ended"
        return "live"
    if stored in ("draft", "ready") and root is None:
        return "draft"
    end = _as_date(campaign.get("end_date"))
    if stored == "ended" or (end is not None and end < today):
        return "ended"
    return "live"


def label(state_: str, origin: str | None) -> str:
    return (IMPORTED_LABELS if origin == "imported" else LABELS)[state_]


def can_close(campaign: dict, state_: str) -> bool:
    return not _imported(campaign) and state_ in _CLOSABLE


def view(campaign: dict, *, root: dict | None, today: date) -> dict:
    """The served `lifecycle {state, label, can_close}`."""
    current = state(campaign, root=root, today=today)
    return {
        "state": current, "label": label(current, campaign.get("origin")),
        "can_close": can_close(campaign, current),
    }


def end_date(campaign: dict, root: dict | None) -> date | None:
    """The last delivery day: the plan's for an internal campaign, the root's for an imported."""
    if _imported(campaign):
        return _as_date((root or {}).get("end_date"))
    return _as_date(campaign.get("end_date"))


def monitored(campaign: dict, today: date, *, root: dict | None = None) -> bool:
    """Live, or ended within `ENDED_GRACE_DAYS` of its end date (late purchases keep landing on
    the last days within the platform's default 7-day click window). Closed and draft: never; an
    ended campaign with no end date (an imported root switched off) is not monitored."""
    current = state(campaign, root=root, today=today)
    if current == "live":
        return True
    if current != "ended":
        return False
    end = end_date(campaign, root)
    return end is not None and today <= end + timedelta(days=ENDED_GRACE_DAYS)


# ---------------------------------------------------------------------------
# reads
# ---------------------------------------------------------------------------

_ROOT_ORDER = "campaign_id,(native_kind<>'campaign'),platform,source_account,id"


def roots(conn, org_id: str, brand_id: str) -> dict:
    """campaign id -> its root `ads_external_entity` row (a platform campaign first), one read."""
    rows = conn.execute(
        "SELECT DISTINCT ON (campaign_id) * FROM ads_external_entity WHERE org_id=%s "
        "AND brand_id=%s AND parent_native_id IS NULL ORDER BY " + _ROOT_ORDER,
        (org_id, brand_id),
    ).fetchall()
    return {row["campaign_id"]: dict(row) for row in rows}


def root(conn, org_id: str, brand_id: str, campaign_id: str) -> dict | None:
    row = conn.execute(
        "SELECT * FROM ads_external_entity WHERE org_id=%s AND brand_id=%s AND campaign_id=%s "
        "AND parent_native_id IS NULL ORDER BY " + _ROOT_ORDER + " LIMIT 1",
        (org_id, brand_id, campaign_id),
    ).fetchone()
    return dict(row) if row is not None else None


def of(conn, org_id: str, brand_id: str, campaign: dict) -> dict:
    """`view()` for one campaign row, reading its root and the org's today."""
    return view(
        campaign, root=root(conn, org_id, brand_id, campaign["id"]),
        today=settings.today_for_org(conn, org_id=org_id),
    )


def record(conn, org_id: str, brand_id: str, campaign_id: str) -> str | None:
    """Write the derived transitions -- internal live -> ended; imported draft／live／ended -- and
    return the state (None for an unknown campaign). A closed campaign is never touched. Called by
    the runtime tick and by `external_repository.upsert_entity` when it writes an imported root;
    the caller commits."""
    row = conn.execute(
        "SELECT id,origin,status,end_date FROM ads_campaign WHERE org_id=%s AND brand_id=%s "
        "AND id=%s",
        (org_id, brand_id, campaign_id),
    ).fetchone()
    if row is None:
        return None
    campaign = dict(row)
    if campaign["status"] == "closed":
        return "closed"
    current = state(
        campaign, root=root(conn, org_id, brand_id, campaign_id),
        today=settings.today_for_org(conn, org_id=org_id),
    )
    if _imported(campaign):
        if current != campaign["status"]:
            conn.execute(
                "UPDATE ads_campaign SET status=%s WHERE org_id=%s AND brand_id=%s AND id=%s "
                "AND origin='imported' AND status=%s",
                (current, org_id, brand_id, campaign_id, campaign["status"]),
            )
    elif campaign["status"] == "live" and current == "ended":
        conn.execute(
            "UPDATE ads_campaign SET status='ended' WHERE org_id=%s AND brand_id=%s AND id=%s "
            "AND status='live' AND origin='internal'",
            (org_id, brand_id, campaign_id),
        )
    return current


# ---------------------------------------------------------------------------
# selection
# ---------------------------------------------------------------------------


def _wanted(states) -> frozenset:
    wanted = frozenset(states)
    unknown = wanted - set(STATES)
    if unknown:
        raise ValueError(f"lifecycle_state_unknown: {sorted(unknown)}")
    return wanted


def _stored_filter(wanted: frozenset) -> str:
    """The stored-status prefilter: `closed` is stored and terminal, so it decides alone."""
    if "closed" not in wanted:
        return " AND status <> 'closed'"
    if wanted == {"closed"}:
        return " AND status = 'closed'"
    return ""


def campaigns(conn, org_id: str, brand_id: str, states) -> list[dict]:
    """The brand's `ads_campaign` rows whose state is in `states`, oldest first."""
    wanted = _wanted(states)
    rows = [
        dict(row) for row in conn.execute(
            "SELECT * FROM ads_campaign WHERE org_id=%s AND brand_id=%s"
            + _stored_filter(wanted) + " ORDER BY created_at, id",
            (org_id, brand_id),
        ).fetchall()
    ]
    if NOT_CLOSED <= wanted:
        return rows  # every state but closed is wanted: the stored prefilter already decided
    by_campaign = roots(conn, org_id, brand_id)
    today = settings.today_for_org(conn, org_id=org_id)
    return [
        row for row in rows
        if state(row, root=by_campaign.get(row["id"]), today=today) in wanted
    ]


def campaign_ids(conn, org_id: str, brand_id: str, states) -> list[str]:
    return [row["id"] for row in campaigns(conn, org_id, brand_id, states)]


def monitored_ids(conn, org_id: str, brand_id: str) -> set[str]:
    """The brand's campaigns `monitored` today (live, or ended within the grace days) -- what the
    background runtime reads and syncs (F49 Contract N). Two reads: the campaigns, their roots."""
    rows = conn.execute(
        "SELECT * FROM ads_campaign WHERE org_id=%s AND brand_id=%s"
        + _stored_filter(frozenset({"live", "ended"})),
        (org_id, brand_id),
    ).fetchall()
    if not rows:
        return set()
    by_campaign = roots(conn, org_id, brand_id)
    today = settings.today_for_org(conn, org_id=org_id)
    return {
        row["id"] for row in rows
        if monitored(dict(row), today, root=by_campaign.get(row["id"]))
    }


def is_monitored(conn, org_id: str, brand_id: str, campaign_id: str) -> bool:
    """`monitored` for one campaign (False for an unknown one), reading its root and today."""
    row = conn.execute(
        "SELECT * FROM ads_campaign WHERE org_id=%s AND brand_id=%s AND id=%s",
        (org_id, brand_id, campaign_id),
    ).fetchone()
    if row is None:
        return False
    return monitored(
        dict(row), settings.today_for_org(conn, org_id=org_id),
        root=root(conn, org_id, brand_id, campaign_id),
    )


def brands(conn, states) -> list[dict]:
    """`[{org_id, brand_id}]` of every brand with at least one campaign in `states` (worker-wide,
    every org), ordered."""
    wanted = _wanted(states)
    rows = conn.execute(
        "SELECT DISTINCT org_id, brand_id FROM ads_campaign WHERE TRUE"
        + _stored_filter(wanted) + " ORDER BY org_id, brand_id",
    ).fetchall()
    found = [{"org_id": row["org_id"], "brand_id": row["brand_id"]} for row in rows]
    if NOT_CLOSED <= wanted:
        return found
    return [b for b in found if campaigns(conn, b["org_id"], b["brand_id"], wanted)]


# ---------------------------------------------------------------------------
# running ads (served `running {count, unknown, read_at, stale}`)
# ---------------------------------------------------------------------------


def _as_time(value) -> datetime | None:
    if isinstance(value, datetime):
        return value
    if value is None:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=UTC)


def structure_read_at(campaign: dict):
    """The campaign's newest clean structure read (`external_sync.structure.last_success_at`;
    a failed or partial read keeps the previous one)."""
    sync = (campaign.get("context_json") or {}).get("external_sync") or {}
    return (sync.get("structure") or {}).get("last_success_at")


def newest_reported(conn, org_id: str, brand_id: str, campaign_id: str | None = None) -> dict:
    """campaign id -> the newest `reported_at` of its launch hand-off items (one read)."""
    rows = conn.execute(
        "SELECT h.campaign_id, max(h.reported_at) AS at FROM ads_handoff_item h "
        "JOIN ads_change_set s ON s.org_id=h.org_id AND s.brand_id=h.brand_id "
        "AND s.campaign_id=h.campaign_id AND s.id=h.change_set_id "
        "WHERE h.org_id=%s AND h.brand_id=%s AND (%s::text IS NULL OR h.campaign_id=%s) "
        "AND h.reported_at IS NOT NULL AND s.plan_json ? 'launch_snapshot' "
        "GROUP BY h.campaign_id",
        (org_id, brand_id, campaign_id, campaign_id),
    ).fetchall()
    return {row["campaign_id"]: row["at"] for row in rows}


def running_view(campaign: dict, ads: list[dict], reported_at) -> dict:
    """`count` running ads and `unknown` ones among `ads` (the campaign's ad entities);
    `read_at` = the newest clean structure read; `stale` = that read is older than the newest
    launch item the user reported done (`reported_at`), so the count may miss it (drill-11 E5)."""
    read_at = structure_read_at(campaign)
    read_time, reported = _as_time(read_at), _as_time(reported_at)
    return {
        "count": sum(1 for ad in ads if ad_running(ad) is True),
        "unknown": sum(1 for ad in ads if ad_running(ad) is None),
        "read_at": read_at,
        "stale": reported is not None and (read_time is None or read_time < reported),
    }
