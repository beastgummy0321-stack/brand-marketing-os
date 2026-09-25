"""app/ads/workspace_reads.py — F30-I06 (Contract E): the campaign workspace's three reads -- the
head and stage (`workspace`), the tree (`structure`) and the change history (`timeline`).
Read-only: no LLM call, no write, no platform call (ARCHITECTURE.md §0 "程式整理，LLM 判斷").

Every number and state here comes from a function that already owns it, never a second copy:
- stage: `campaign_stage.stage`, fed by `home_overview._is_draft`, `targets.resolve`,
  `change_control_launch.launch_set`, triage `data.status` and this campaign's open queue rows
  (`triage.get_queue`, over this campaign's own `classify()` items);
- grades: `triage.classify` (the one cap ruler), never the trend `class`;
- `daily_budget`／`can_support`／`active_ads`: see `_capacity`;
- `next_sync_at`: `home_overview._sync_block` (the home's `sync.next_at`);
- timeline states: the home row `_handoff` rule plus `change_control_launch.is_stale`.

Unknown is null, never zero: each sub-read runs through `home_overview._guarded`, so a failed read
nulls only its own field (and rolls the read transaction back for the next one).
"""

from datetime import timedelta

from app.ads import (
    ad_status,
    campaign_stage,
    change_control_launch,
    handoff_assignment,
    home_overview,
    month_summary,
    repository,
    review_evidence,
    targets,
    triage,
)
from app.ads.external_repository import is_monthly_budget_row
from app.core import settings as coresettings

TOTALS_DAYS = 14
TIMELINE_CAP = 50
# `ads_action.verification_state` of an approved pause still on its way to the platform: not done
# yet (`pending`) or done and not yet confirmed by a readback (the home `check` states).
_OPEN_PAUSE_STATES = ("pending", *sorted(home_overview._HANDOFF_CHECK_STATES))


def _campaign(conn, org_id, brand_id, campaign_id) -> dict:
    campaign = repository.get_campaign(conn, org_id, brand_id, campaign_id)
    if campaign is None:
        raise ValueError("campaign_unknown")
    return campaign


def _entities(conn, org_id, brand_id, campaign_id) -> list[dict]:
    rows = conn.execute(
        "SELECT * FROM ads_external_entity WHERE org_id=%s AND brand_id=%s AND campaign_id=%s "
        "ORDER BY name,id",
        (org_id, brand_id, campaign_id),
    ).fetchall()
    return [dict(r) for r in rows]


def _is_draft(campaign, entities) -> bool:
    return home_overview._is_draft(campaign, {campaign["id"]} if entities else set())


# ---------------------------------------------------------------------------
# workspace
# ---------------------------------------------------------------------------


def _open_queue_count(conn, org_id, brand_id, campaign_id, items) -> int:
    """This campaign's open queue rows: the brand queue's own candidate rules and open-row filter
    (`triage.get_queue`) over this campaign's own `classify()` items. Every row kind but the
    brand's `settle` row is raised from one campaign's items and carries that campaign's triage
    item, so the rows it returns for these items are exactly this campaign's rows of the brand
    queue; `settle` (no triage item, the whole brand's month) is not this campaign's."""
    queue = triage.get_queue(conn, org_id, brand_id, items=items)
    return sum(
        1 for row in queue["items"]
        if (row.get("triage") or {}).get("campaign_id") == campaign_id
    )


def _totals(conn, org_id, brand_id, campaign) -> dict:
    """The last 14 complete days in the org timezone (yesterday back), one window -- never the
    triage 7/14/28 widening. A day of this window the platform read never covered has no row, and
    a missing row would otherwise read as zero spend: so the window's own unread days are taken
    from the campaign's recorded sync coverage with the same functions the `data_status` missing
    days come from (`triage._coverage` / `triage._missing_days`), and any unread day -- or no
    recorded coverage at all -- nulls spend, results and cost per result together. Over a fully
    read window: spend and currency by `home_overview._spend_view` (a null-spend row or mixed
    currencies -> null), results and cost per result by `month_summary._ad_result` (the one
    ad-scope result view; null unless every row agrees on one result kind). A read day with a
    zero-spend row, or with no row at all, is a known zero; a window without any row is unknown,
    as on the home."""
    campaign_id = campaign["id"]
    end = coresettings.today_for_org(conn, org_id=org_id) - timedelta(days=1)
    start = end - timedelta(days=TOTALS_DAYS - 1)
    coverage = triage._coverage(campaign)
    unread = coverage is None or bool(triage._missing_days(coverage, start, end))
    rows = [
        dict(r) for r in conn.execute(
            "SELECT * FROM ads_external_daily WHERE org_id=%s AND brand_id=%s AND campaign_id=%s "
            "AND metric_scope='ad' AND day BETWEEN %s AND %s ORDER BY day",
            (org_id, brand_id, campaign_id, start, end),
        ).fetchall()
        if not is_monthly_budget_row(r["attribution_key"])
    ]
    spend = home_overview._spend_view(rows, start, end)
    results, cost_per_result, _kind = month_summary._ad_result(
        review_evidence.aggregate(rows, start, end)
    )
    if unread:
        return {
            "start": start.isoformat(), "end": end.isoformat(), "currency": spend["currency"],
            "spend": None, "results": None, "cost_per_result": None,
        }
    return {
        "start": start.isoformat(), "end": end.isoformat(), "currency": spend["currency"],
        "spend": home_overview._money_out(spend["amount"]) if spend["known"] else None,
        "results": home_overview._count_out(results),
        "cost_per_result": None if cost_per_result is None else round(cost_per_result, 2),
    }


def _launch_counts(conn, org_id, brand_id, change_set_ids) -> dict:
    """launch set id -> `(checked, total)` over its handoff items (one per campaign／group／ad
    node the launch builds; `confirmed` is checked)."""
    if not change_set_ids:
        return {}
    rows = conn.execute(
        "SELECT change_set_id,count(*) AS total,"
        "count(*) FILTER (WHERE status='confirmed') AS checked FROM ads_handoff_item "
        "WHERE org_id=%s AND brand_id=%s AND change_set_id = ANY(%s) GROUP BY change_set_id",
        (org_id, brand_id, list(change_set_ids)),
    ).fetchall()
    return {r["change_set_id"]: (r["checked"], r["total"]) for r in rows}


def _draft_block(conn, org_id, brand_id, campaign, cap, launch) -> dict:
    """The draft checklist (上限、預算、素材 x／y、上架 n／N). Slots are
    `home_overview._draft_view`'s ready count (the launch snapshot's material check); the budget
    is set once a scenario total is adopted (`budget_planned`, `repository.select_scenario`)."""
    view = home_overview._draft_view(conn, org_id, brand_id, campaign, cap)
    checked = total = 0
    if launch is not None:
        checked, total = _launch_counts(conn, org_id, brand_id, [launch["id"]]).get(
            launch["id"], (0, 0)
        )
    return {
        "cap_set": not view["cap_missing"], "budget_set": campaign["budget_planned"] is not None,
        "slots_ready": view["ads_ready"], "slots_total": view["ads_total"],
        "launch_checked": checked, "launch_total": total,
    }


def _capacity(conn, org_id, brand_id, campaign, draft, triaged) -> dict:
    """ONE daily-budget rule per lifecycle, and `can_support` always from the same number:
    - launched: triage `data.capacity` (`triage_capacity.capacity_view`) -- the daily budget
      owners of the ACTIVE ads, summed in one currency (null when an active ad has no daily owner
      or currencies mix), and `can_support = floor(daily_budget / (cap × 2))` from that very sum.
      It is the number the cleanup proposal's 「每日 X 撐得起 N 則」 uses.
    - draft: nothing is on a platform, so the plan's group total
      (`home_overview._daily_budget`, the home row's draft rule); no active ad, so `can_support`
      is null.
    `triaged` is `classify()`'s result, or None when that read failed (both fields null)."""
    if draft:
        daily = home_overview._guarded(
            conn, "workspace.daily_budget",
            lambda: home_overview._daily_budget(conn, org_id, brand_id, campaign, [], True),
        )
        return {"daily_budget": daily, "can_support": None}
    if triaged is None:
        return {"daily_budget": None, "can_support": None}
    capacity = triaged["data"]["capacity"]
    return {"daily_budget": capacity["daily_budget"], "can_support": capacity["can_support"]}


def workspace(conn, org_id: str, brand_id: str, campaign_id: str) -> dict:
    campaign = _campaign(conn, org_id, brand_id, campaign_id)
    entities = _entities(conn, org_id, brand_id, campaign_id)
    draft = _is_draft(campaign, entities)
    closed = campaign["status"] == "closed"
    cap = targets.resolve(conn, org_id, brand_id, campaign)
    launch = change_control_launch.launch_set(conn, org_id, brand_id, campaign_id)
    active_ads = sum(
        1 for e in entities
        if e["native_kind"] == "ad" and not ad_status.is_closed(e.get("native_status"))
    )

    triaged = None
    if not draft:
        triaged = home_overview._guarded(
            conn, "workspace.triage",
            lambda: triage.classify(conn, org_id, brand_id, campaign_id),
        )
    if draft or closed:
        # No queue row can be open: every row but the brand's settle is raised from a campaign's
        # active platform ads, a draft has none, and the queue never covers a closed campaign
        # (`triage._non_closed_campaign_ids`).
        pending = 0
    elif triaged is None:
        pending = None
    else:
        items = triaged["items"]
        pending = home_overview._guarded(
            conn, "workspace.pending",
            lambda: _open_queue_count(conn, org_id, brand_id, campaign_id, items),
        )
    data_ready = None if triaged is None else triaged["data"]["status"]["state"] == "ready"
    # The days of the judged window never read (triage `data.status.missing_days`, the same
    # window `data_ready` is judged on); a draft has no platform day to miss.
    missing_days: list | None
    if draft:
        missing_days = []
    else:
        missing_days = None if triaged is None else triaged["data"]["status"]["missing_days"]

    sync = home_overview._guarded(
        conn, "workspace.sync", lambda: home_overview._sync_block(conn, org_id, brand_id)
    )
    totals = None if draft else home_overview._guarded(
        conn, "workspace.totals", lambda: _totals(conn, org_id, brand_id, campaign)
    )
    draft_block = None if not draft else home_overview._guarded(
        conn, "workspace.draft",
        lambda: _draft_block(conn, org_id, brand_id, campaign, cap, launch),
    )
    return {
        "stage": campaign_stage.stage(
            closed=closed, draft=draft, launch_approved=launch is not None,
            cap_set=cap["value"] is not None, data_ready=data_ready, open_items=pending,
        ),
        "pending_count": pending,
        **_capacity(conn, org_id, brand_id, campaign, draft, triaged),
        "active_ads": active_ads,
        "next_sync_at": sync["next_at"] if sync is not None else None,
        "missing_days": missing_days,
        "totals": totals,
        "draft": draft_block,
    }


# ---------------------------------------------------------------------------
# structure
# ---------------------------------------------------------------------------


def _closing_entity_ids(conn, org_id, brand_id, campaign_id) -> set:
    """Ads with an approved pause not yet confirmed (`_OPEN_PAUSE_STATES`)."""
    rows = conn.execute(
        "SELECT a.target_id FROM ads_action a JOIN ads_change_set s ON s.id=a.change_set_id "
        "AND s.org_id=a.org_id AND s.brand_id=a.brand_id AND s.campaign_id=a.campaign_id "
        "WHERE a.org_id=%s AND a.brand_id=%s AND a.campaign_id=%s AND a.kind='pause' "
        "AND s.status='approved' AND a.verification_state = ANY(%s)",
        (org_id, brand_id, campaign_id, list(_OPEN_PAUSE_STATES)),
    ).fetchall()
    return {r["target_id"] for r in rows}


def _planned_entities(conn, org_id, brand_id, campaign_id) -> dict:
    """`(planned_kind, planned_id) -> entity id`: the platform object each planned group／ad was
    matched to by its launch handoff (`ads_handoff_item.entity_id`), newest match first."""
    rows = conn.execute(
        "SELECT planned_kind,planned_id,entity_id FROM ads_handoff_item WHERE org_id=%s "
        "AND brand_id=%s AND campaign_id=%s AND entity_id IS NOT NULL "
        "ORDER BY created_at DESC,id DESC",
        (org_id, brand_id, campaign_id),
    ).fetchall()
    found: dict = {}
    for row in rows:
        found.setdefault((row["planned_kind"], row["planned_id"]), row["entity_id"])
    return found


def _entity_daily_budget(entity) -> float | None:
    if entity is None or entity.get("budget_type") != "daily" or entity["budget_amount"] is None:
        return None
    return float(entity["budget_amount"])


def _missing_material(conn, org_id, brand_id, campaign_id, ad) -> bool:
    """Not ready by the launch snapshot's own check (`home_overview._draft_view`'s rule)."""
    try:
        material = handoff_assignment.material_snapshot(conn, org_id, brand_id, campaign_id, ad)
    except ValueError:
        material = None
    return not (material and material["assignment_status"] == "confirmed")


def _platform_ad(entity, graded, closing, *, ad_id=None, name=None) -> dict:
    item = graded.get(entity["id"]) if graded is not None else None
    current = (item or {}).get("current") or {}
    return {
        "ad_id": ad_id, "entity_id": entity["id"],
        "name": name or entity.get("name") or entity["native_id"],
        "thumbnail_url": triage._thumbnail_url(entity),
        "grade": item["grade"] if item else None,
        "grade_label": item["grade_label"] if item else None,
        # The ad's own spend over the window its grade was judged on (triage `current.spend`),
        # null when unknown -- never 0.
        "spend": None if current.get("spend") is None else round(float(current["spend"]), 2),
        "cost_per_result": current.get("cost_per_result"),
        "results": home_overview._count_out(current.get("result_count")),
        "closing": entity["id"] in closing, "missing_material": False,
    }


def structure(conn, org_id: str, brand_id: str, campaign_id: str) -> dict:
    """App-built: the plan's groups and planned ads (a planned ad matched to a platform ad carries
    its grade; one not on a platform yet carries `missing_material`), then any live platform ad of
    the campaign the plan does not hold (e.g. a replacement), under the group its parent was
    matched to, else under its own platform parent. Imported: the platform parents (ad sets) and
    their ads. Only live ads (`ad_status.is_closed` false) are listed -- a closed ad is not in the
    structure any more. Grades are `triage.classify`'s; a failed triage read leaves every grade
    null, never a guess."""
    campaign = _campaign(conn, org_id, brand_id, campaign_id)
    entities = _entities(conn, org_id, brand_id, campaign_id)
    closing = _closing_entity_ids(conn, org_id, brand_id, campaign_id)
    graded = None
    if entities:
        triaged = home_overview._guarded(
            conn, "structure.triage",
            lambda: triage.classify(conn, org_id, brand_id, campaign_id),
        )
        graded = None if triaged is None else {i["entity_id"]: i for i in triaged["items"]}
    by_id = {e["id"]: e for e in entities}
    by_native = {(e["native_kind"], e["native_id"]): e for e in entities}
    live_ads = [
        e for e in entities
        if e["native_kind"] == "ad" and not ad_status.is_closed(e.get("native_status"))
    ]

    groups: list[dict] = []
    placed: set = set()
    group_of_parent: dict = {}
    if campaign["origin"] != "imported":
        matched = _planned_entities(conn, org_id, brand_id, campaign_id)
        ads = repository.list_ads_for_campaign(conn, org_id, brand_id, campaign_id)
        for group in repository._groups_for_campaign(conn, org_id, brand_id, campaign_id):
            group_entity = by_id.get(matched.get(("group", group["id"])))
            if group_entity is not None:
                group_of_parent[group_entity["id"]] = len(groups)
            out_ads = []
            for ad in (a for a in ads if a["group_id"] == group["id"]):
                entity = by_id.get(matched.get(("ad", ad["id"])))
                if entity is None:
                    out_ads.append({
                        "ad_id": ad["id"], "entity_id": None, "name": ad["name"],
                        "thumbnail_url": None, "spend": None, "grade": None,
                        "grade_label": None,
                        "cost_per_result": None, "results": None, "closing": False,
                        "missing_material": _missing_material(
                            conn, org_id, brand_id, campaign_id, ad
                        ),
                    })
                    continue
                placed.add(entity["id"])
                if ad_status.is_closed(entity.get("native_status")):
                    continue
                out_ads.append(
                    _platform_ad(entity, graded, closing, ad_id=ad["id"], name=ad["name"])
                )
            groups.append({
                "group_id": group["id"], "name": group["name"],
                # A group on a platform: its platform daily budget (the fact, a later budget
                # change included); a plan-only group: the plan's own figure.
                "daily_budget": _entity_daily_budget(group_entity) if group_entity is not None
                else float(group["daily_budget"]),
                "ads": out_ads,
            })

    platform_groups: dict = {}
    for entity in live_ads:
        if entity["id"] in placed:
            continue
        parent = by_native.get((entity.get("parent_native_kind"), entity.get("parent_native_id")))
        parent_key = parent["id"] if parent is not None else None
        ad = _platform_ad(entity, graded, closing)
        if parent_key in group_of_parent:
            groups[group_of_parent[parent_key]]["ads"].append(ad)
            continue
        if parent_key not in platform_groups:
            platform_groups[parent_key] = {
                "group_id": None,
                "name": (parent or {}).get("name") or entity.get("parent_native_id") or "",
                "daily_budget": _entity_daily_budget(parent), "ads": [],
            }
        platform_groups[parent_key]["ads"].append(ad)
    # Plan groups keep the plan's order; platform parents follow by name (ads inside by name).
    groups.extend(sorted(platform_groups.values(), key=lambda g: g["name"]))
    return {"groups": groups}


# ---------------------------------------------------------------------------
# timeline
# ---------------------------------------------------------------------------


def _action_states(conn, org_id, brand_id, change_set_ids) -> dict:
    if not change_set_ids:
        return {}
    rows = conn.execute(
        "SELECT change_set_id,verification_state FROM ads_action WHERE org_id=%s AND brand_id=%s "
        "AND change_set_id = ANY(%s)",
        (org_id, brand_id, list(change_set_ids)),
    ).fetchall()
    states: dict = {}
    for row in rows:
        states.setdefault(row["change_set_id"], []).append(row["verification_state"])
    return states


def _approved_state(conn, org_id, brand_id, campaign_id, change_set_id, states, stale_launch):
    """The home row `_handoff` rule over this one set (`platform` while an item is not done on the
    platform, `check` while one waits for its readback), `stale` for the current launch whose plan
    changed after approval (`change_control_launch.is_stale`, decided by the caller once) or a set
    with a stale item, else `verified`. The set goes to `_handoff` as a non-launch entry because
    its staleness is already decided here -- `_handoff` would otherwise rebuild the launch snapshot
    for it again."""
    if stale_launch:
        return "stale"
    handoff = home_overview._handoff(
        conn, org_id, brand_id, campaign_id,
        [{"id": change_set_id, "is_launch": False, "states": set(states)}],
    )
    if handoff is not None:
        return handoff["state"]
    return "stale" if "stale" in states else "verified"


def timeline(conn, org_id: str, brand_id: str, campaign_id: str) -> dict:
    """Every change set of the campaign but superseded and deferred ones, newest first
    (`created_at DESC, id DESC`), at most `TIMELINE_CAP` with `truncated` when there are more.
    `checked／total`: a launch counts its handoff items (one per node it builds), any other
    approved set its items (`ads_action`), a draft or rejected set its planned items with none
    checked. `version` only on a launch (`plan_json.version`; the first launch has none, so 1)."""
    _campaign(conn, org_id, brand_id, campaign_id)
    rows = [dict(r) for r in conn.execute(
        "SELECT id,title,status,plan_json,decision_reason,created_at FROM ads_change_set "
        "WHERE org_id=%s AND brand_id=%s AND campaign_id=%s "
        "AND status NOT IN ('superseded','deferred') ORDER BY created_at DESC,id DESC LIMIT %s",
        (org_id, brand_id, campaign_id, TIMELINE_CAP + 1),
    ).fetchall()]
    truncated = len(rows) > TIMELINE_CAP
    rows = rows[:TIMELINE_CAP]
    ids = [r["id"] for r in rows]
    launches = [r["id"] for r in rows if "launch_snapshot" in r["plan_json"]]
    states = _action_states(conn, org_id, brand_id, ids)
    launch_counts = _launch_counts(conn, org_id, brand_id, launches)
    current_launch = change_control_launch.launch_set(conn, org_id, brand_id, campaign_id)
    stale_launch_id = None
    if current_launch is not None and current_launch["id"] in ids and \
            change_control_launch.is_stale(conn, org_id, brand_id, campaign_id):
        stale_launch_id = current_launch["id"]

    out = []
    for row in rows:
        is_launch = row["id"] in launches
        set_states = states.get(row["id"], [])
        if row["status"] == "approved":
            state = _approved_state(conn, org_id, brand_id, campaign_id, row["id"], set_states,
                                    row["id"] == stale_launch_id)
            checked, total = (
                launch_counts.get(row["id"], (0, 0)) if is_launch
                else (sum(1 for s in set_states if s == "confirmed"), len(set_states))
            )
        else:
            state = row["status"]  # "draft" | "rejected"
            checked, total = 0, len(row["plan_json"].get("items") or ())
        out.append({
            "change_set_id": row["id"], "title": row["title"], "at": row["created_at"],
            "state": state, "reason": row["decision_reason"], "checked": checked,
            "total": total,
            "version": int(row["plan_json"].get("version") or 1) if is_launch else None,
        })
    return {"rows": out, "truncated": truncated}
