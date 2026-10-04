"""app/ads/recovery.py — Contract K (F27-I10), rescoped by F27-I24 (correction 12: beats are
per brand -- a gap is judged on the requesting brand's own beats) and pre-dispatch correction 10
(step 3 is judged per sync SECTION, not the job-level `last_success_at`).

`GET /api/ads/brands/{b}/recovery`: whether this brand's own slice of the ads background system
just came back from an outage -- a gap is two consecutive `beat` events of THIS brand more than
120 minutes apart (`app/ads/runtime_events.py`'s per-minute heartbeat) -- and, while such a gap
ended within the last 24 hours and at least one of the five recovery steps is not yet done, which
step the brand is waiting on. Read-only: this module only re-derives state already written
elsewhere -- `runtime_events` (beats, `queue_refresh`), `repository.campaign_sync_state` (sync
sections, disconnected/auth_expired) and `runtime.py::_readback` (`evidence_json.runtime_checked_at`
on `ads_handoff_item`/`ads_action`). No migration, no interrupt/queue write.
"""

from datetime import datetime, timedelta

from app.ads import lifecycle, repository, runtime_events
from app.core import db

_GAP_MINUTES = 120
_RECOVERING_WINDOW_HOURS = 24
# Nothing older than this survives `runtime_events.prune()`'s own retention window -- a gap
# whose earlier beat fell outside it can never be reconstructed, so there is no point scanning
# further back.
_LOOKBACK_HOURS = 48

_STEP_LABELS = (
    ("reconnect", "重新連線"),
    ("auth", "確認讀取權限"),
    ("resync", None),  # built per-gap below: 「補 N 小時的資料」
    ("requeue", "重新判斷廣告"),
    ("reports", "核對你回報的操作"),
)


def _parse(value):
    """`evidence_json`/`context_json` timestamps round-trip through jsonb as ISO-8601 strings
    (`app/core/db.py::_json_default`); DB columns (`ads_runtime_event.at`) already come back as
    tz-aware `datetime`. Accept either; unparsable/absent reads as "not yet" everywhere below."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None


def _find_gap(beats: list[dict]) -> dict | None:
    """The most recent pair of this brand's own consecutive beats more than `_GAP_MINUTES`
    apart, oldest-pair-first input (`runtime_events.list_since` order) -- the LAST qualifying
    pair scanned wins, so a brand with more than one outage in the lookback window reads its
    latest one. `None` when beats never had a gap that wide (including 0 or 1 beat total)."""
    gap = None
    for prev, curr in zip(beats, beats[1:], strict=False):
        minutes = (curr["at"] - prev["at"]).total_seconds() / 60
        if minutes > _GAP_MINUTES:
            gap = {"start": prev["at"], "end": curr["at"], "minutes": round(minutes)}
    return gap


def _campaigns(conn, org_id: str, brand_id: str) -> list[dict]:
    return lifecycle.campaigns(conn, org_id, brand_id, lifecycle.NOT_CLOSED)


def _reconnect_done(conn, brand_id: str, gap_end) -> bool:
    """重新連線: a beat strictly after the gap -- the beat AT `gap.end` is the one that closed
    the gap (proves the outage ended); this step asks for a FOLLOWING one, proving the
    reconnection held rather than being a single blip."""
    rows = runtime_events.list_since(conn, "beat", gap_end, brand_id=brand_id)
    return any(row["at"] > gap_end for row in rows)


def _auth_done(conn, org_id: str, brand_id: str) -> bool:
    """確認讀取權限: none of this brand's own non-closed campaigns are `disconnected` or
    `auth_expired` right now (`repository.campaign_sync_state`). Vacuously true with no
    campaigns."""
    cache: dict = {}
    return all(
        repository.campaign_sync_state(
            conn, org_id, brand_id, campaign, accounts_cache=cache,
        )["state"] not in ("disconnected", "auth_expired")
        for campaign in _campaigns(conn, org_id, brand_id)
    )


def _resync_done(conn, org_id: str, brand_id: str, gap_end) -> bool:
    """補 N 小時的資料 (pre-dispatch correction 10): every sync SECTION
    (`context_json.external_sync[...]`) of every non-closed campaign has its OWN
    `last_success_at` after `gap.end` -- not the job-level `ads_external_sync_job.last_success_at`.
    A campaign with no sections recorded yet (`"never"` sync state) has nothing to catch up on.
    Vacuously true with no campaigns or no sections anywhere."""
    for campaign in _campaigns(conn, org_id, brand_id):
        sections = (campaign.get("context_json") or {}).get("external_sync") or {}
        for section in sections.values():
            success = _parse(section.get("last_success_at"))
            if success is None or success <= gap_end:
                return False
    return True


def _requeue_done(conn, brand_id: str, gap_end) -> bool:
    """重新判斷廣告: this brand's own `queue_refresh` event (`triage.refresh_queue`) after
    `gap.end` -- the daily queue refresh re-judging ads with post-gap data."""
    rows = runtime_events.list_since(conn, "queue_refresh", gap_end, brand_id=brand_id)
    return any(row["at"] > gap_end for row in rows)


def _pending_evidence(conn, org_id: str, brand_id: str) -> list[dict]:
    """Every "reported but not final" item of this brand -- `ads_handoff_item`/`ads_action` rows
    whose own status/`verification_state` is `'reported'` (the human said they did it) or
    `'unknown'` (a check ran but couldn't confirm it), scoped to approved change sets, same shape
    `runtime.py::_readback` periodically re-checks (its two queries here, minus the LIMIT/ORDER):
    handoff items with a bound entity, and actions with no handoff item of their own (simple
    settings changes verified directly). F49 Contract N: only items of campaigns the lifecycle
    still monitors -- the tick never re-checks a closed campaign, or one ended past the grace
    days, so its items would hold this step open forever."""
    monitored = sorted(lifecycle.monitored_ids(conn, org_id, brand_id))
    handoff_rows = conn.execute(
        "SELECT h.evidence_json FROM ads_handoff_item h JOIN ads_change_set c "
        "ON c.id=h.change_set_id AND c.org_id=h.org_id AND c.brand_id=h.brand_id "
        "WHERE h.org_id=%s AND h.brand_id=%s AND c.status='approved' "
        "AND h.entity_id IS NOT NULL AND h.status IN ('reported','unknown') "
        "AND h.campaign_id = ANY(%s)",
        (org_id, brand_id, monitored),
    ).fetchall()
    action_rows = conn.execute(
        "SELECT a.evidence_json FROM ads_action a JOIN ads_change_set c "
        "ON c.id=a.change_set_id AND c.org_id=a.org_id AND c.brand_id=a.brand_id "
        "WHERE a.org_id=%s AND a.brand_id=%s AND c.status='approved' "
        "AND a.verification_state IN ('reported','unknown') "
        "AND a.campaign_id = ANY(%s) "
        "AND NOT EXISTS (SELECT 1 FROM ads_handoff_item h WHERE h.action_id=a.id)",
        (org_id, brand_id, monitored),
    ).fetchall()
    return [row["evidence_json"] for row in handoff_rows] + [
        row["evidence_json"] for row in action_rows
    ]


def _reports_done(conn, org_id: str, brand_id: str, gap_end) -> bool:
    """核對你回報的操作: every reported-but-not-final item was CHECKED (`runtime_checked_at`,
    stamped only by the background `_readback` re-check, never a manual API check call) after
    `gap.end`. Vacuously true with nothing pending."""
    for evidence in _pending_evidence(conn, org_id, brand_id):
        checked = _parse((evidence or {}).get("runtime_checked_at"))
        if checked is None or checked <= gap_end:
            return False
    return True


def _steps(conn, org_id: str, brand_id: str, gap: dict) -> list[dict]:
    gap_end = gap["end"]
    hours = round(gap["minutes"] / 60)
    done_by_key = {
        "reconnect": _reconnect_done(conn, brand_id, gap_end),
        "auth": _auth_done(conn, org_id, brand_id),
        "resync": _resync_done(conn, org_id, brand_id, gap_end),
        "requeue": _requeue_done(conn, brand_id, gap_end),
        "reports": _reports_done(conn, org_id, brand_id, gap_end),
    }
    steps = []
    seen_not_done = False
    for key, label in _STEP_LABELS:
        if key == "resync":
            label = f"補 {hours} 小時的資料"
        done = done_by_key[key]
        if seen_not_done:
            state = "todo"
        elif done:
            state = "done"
        else:
            state = "active"
            seen_not_done = True
        steps.append({"key": key, "label": label, "state": state})
    return steps


def get_recovery(conn, org_id: str, brand_id: str) -> dict:
    now = db.now_utc()
    since = now - timedelta(hours=_LOOKBACK_HOURS)
    beats = runtime_events.list_since(conn, "beat", since, brand_id=brand_id)
    gap = _find_gap(beats)
    if gap is None or now - gap["end"] > timedelta(hours=_RECOVERING_WINDOW_HOURS):
        return {"recovering": False, "gap": None, "steps": []}
    steps = _steps(conn, org_id, brand_id, gap)
    if all(step["state"] == "done" for step in steps):
        return {"recovering": False, "gap": None, "steps": []}
    return {
        "recovering": True,
        "gap": {"start": gap["start"], "end": gap["end"], "minutes": gap["minutes"]},
        "steps": steps,
    }
