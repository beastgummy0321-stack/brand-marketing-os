"""F30 Contract F: the assets tab's slots -- one planned ad (app-built) or one platform ad
(imported) per slot -- and uploading a file into one planned ad's slot.

Readiness is the launch batch's own rule (`change_control_launch.ready_material` over
`handoff_assignment.material_snapshot`, the same count `assets.readiness_summary` and
`home_overview._draft_view` show), never a second definition. A file uploaded into a slot goes
through the user-asset placement path (`user_assets_repository.attach_selected`) and waits on
`ads_ad.slot_placement_id` until that placement is confirmed; only then is it assigned through
`handoff_assignment.assign`, so `material_placement_id` keeps pointing at confirmed versions
only. The pointer follows the placement id (not a revision) because the manual confirmation
needs a revision first (purpose).

F35 Contract T: a planned ad's slot is two halves, the image and the copy. The copy half is
the placement's effective copy once a file is in the slot, else the ad's selected workbench copy
(the copy output of the set the campaign pack made for it, read only through the `app.workbench`
facade). A file uploaded into a slot carries that copy in, fills the purpose with the ad's name,
confirms the placement through `asset_suggestions.confirm_manual` and settles -- one call, no
retyping. Copy never makes a slot ready on its own (§6.34: the launch rule needs a file).

F44 Contract D: a confirmation the program refused keeps why on the placement's revision
(`blocked_reasons`, Contract C details) and the slot reads `blocked` with the first reason and
the exit that fixes it; `recheck` runs the confirmation again. Every slot names its ad's offer
coordinate (`offer_label`).
"""

from app import workbench
from app.ads import ad_status, handoff_assignment, material_tasks
from app.ads import asset_binding_repository as bindings
from app.ads import assets as legacy_readiness
from app.ads import change_control_launch as launch
from app.ads import repository as ads_repo
from app.ads import user_assets_repository as user_assets
from app.core import db


def _asset_thumbnail(conn, org, brand, asset_id) -> str | None:
    """The brand original's poster, served by the user-asset content route (an authenticated
    same-origin path); None while its preview is not made yet."""
    try:
        asset = user_assets.get_asset(conn, org, brand, asset_id)
    except ValueError:
        return None
    if not asset.get("thumbnail_key"):
        return None
    return f"/api/ads/brands/{brand}/user-assets/{asset_id}/thumbnail"


def _planned_entities(conn, org, brand, campaign) -> dict:
    """planned ad id -> the platform ad its launch handoff was matched to (newest match)."""
    rows = conn.execute(
        "SELECT h.planned_id,e.* FROM ads_handoff_item h JOIN ads_external_entity e "
        "ON e.id=h.entity_id AND e.org_id=h.org_id AND e.brand_id=h.brand_id "
        "AND e.campaign_id=h.campaign_id WHERE h.org_id=%s AND h.brand_id=%s "
        "AND h.campaign_id=%s AND h.planned_kind='ad' AND h.entity_id IS NOT NULL "
        "ORDER BY h.created_at DESC,h.id DESC",
        (org, brand, campaign),
    ).fetchall()
    found: dict = {}
    for row in rows:
        found.setdefault(row["planned_id"], dict(row))
    return found


def _material(conn, org, brand, campaign, ad) -> dict | None:
    try:
        return handoff_assignment.material_snapshot(conn, org, brand, campaign, ad)
    except ValueError:
        return None


def _pending(conn, org, brand, campaign, ad) -> dict | None:
    """The current revision of the placement uploaded into this slot, not yet assigned."""
    placement_id = ad.get("slot_placement_id")
    if placement_id is None:
        return None
    try:
        return user_assets.placement(conn, org, brand, campaign, placement_id)
    except ValueError:
        return None


COPY_FIELDS = ("headline", "body", "description")


def _ad_sets(conn, org, brand, campaign) -> dict:
    """planned ad id -> the workbench set (brief) the campaign pack made for it; the latest
    brief per `source_ref.ads_ad_id` wins (the same walk as `routes._enriched_campaign`)."""
    found: dict = {}
    for brief in workbench.briefs_for_source(
        conn, org, brand, legacy_readiness.PACK_SOURCE_KIND, {"ads_campaign_id": campaign}
    ):
        ad_id = (brief.get("source_ref") or {}).get("ads_ad_id")
        if ad_id:
            found[ad_id] = brief
    return found


def _workbench_copy(conn, org, brand, brief) -> dict | None:
    """The copy version the user selected on the ad's set (`is_adopted`), as the three copy
    fields plus its label; None when nothing is selected or the version carries no text."""
    if brief is None:
        return None
    out = workbench.adopted_output(conn, org, brand, brief["id"], "copy")
    if not out or not out["is_adopted"]:
        return None
    try:
        source = workbench.material_source(conn, org, brand, brief["id"], out["id"])
    except ValueError:
        return None
    fields = source.get("copy_fields") or {}
    return {
        "label": f"工作檯第 {out['version_index']} 版",
        **{k: fields.get(k) for k in COPY_FIELDS},
    }


def _copy_half(source, label, fields) -> dict:
    return {
        "source": source,
        "label": label,
        **{k: fields.get(k) for k in COPY_FIELDS},
    }


def _has_copy(fields) -> bool:
    """The copy half is filled when the copy has a headline or a body (blank counts as none)."""
    return any(str(fields.get(k) or "").strip() for k in ("headline", "body"))


def _slot(
    ad_id, entity_id, name, state, thumbnail_url, replace_task_id=None, *, copy=None,
    workbench_href=None, format_key=None, blocked=None, offer_label=None,
) -> dict:
    """One slot. F40-I01: `format_key` is the planned ad's own `ads_ad.format_key` (`None` for an
    ad without one, and for an imported campaign's platform ad) so the assets tab can say a
    video-format slot needs a script. F44 Contract D: `blocked` is set on a `blocked` slot only;
    `offer_label` is the planned ad's offer coordinate label (`None` for an ad without one, and
    for an imported campaign's platform ad)."""
    return {
        "ad_id": ad_id,
        "entity_id": entity_id,
        "name": name,
        "state": state,
        "thumbnail_url": thumbnail_url,
        "confirmed": state == "ready",
        "replace_task_id": replace_task_id,
        "copy": copy,
        "workbench_href": workbench_href,
        "format_key": format_key,
        "blocked": blocked,
        "offer_label": offer_label,
    }


FAILED_ORIGINAL = "error"  # the status `user_assets.process_preview` leaves on a failed original


def _blocked(conn, org, brand, pending) -> dict | None:
    """Contract D `blocked` for a slot's pending placement, or None when nothing blocks it: the
    first reason plus how many others. A failed original comes first (no copy fixes a file that
    cannot be processed), then the details the last refused confirmation stored. `wait` details
    are never stored, so every reason here has something to fix."""
    details = []
    try:
        asset = user_assets.get_asset(conn, org, brand, pending["asset_id"])
    except ValueError:
        asset = None
    if asset is not None and asset["status"] == FAILED_ORIGINAL:
        reason = f"：{asset['error']}" if asset["error"] else "。"
        details.append({"kind": "file", "text": f"這個檔案處理失敗{reason}", "terms": []})
    if not pending["confirmed_at"]:
        details += pending.get("blocked_reasons") or []
    if not details:
        return None
    first = details[0]
    return {
        "text": first["text"],
        "terms": first["terms"],
        "fix": first["kind"] if first["kind"] in ("copy", "file") else None,
        "more": len(details) - 1,
    }


def _planned_slot(
    conn, org, brand, campaign, ad, entity, readiness, replace_by_entity, brief, offer_label
) -> dict:
    material = _material(conn, org, brand, campaign, ad)
    pending = _pending(conn, org, brand, campaign, ad)
    material_thumb = (
        _asset_thumbnail(conn, org, brand, material["asset_id"]) if material else None
    )
    href = workbench.set_action_url(conn, org, brand, brief["id"]) if brief else None
    # `material_snapshot.copy_fields` is `bindings.effective_copy` of the assigned revision.
    material_copy = _copy_half("placement", "已確認", material["copy_fields"]) if material else None

    def slot(state, thumbnail, copy, entity_id=None, replace_task_id=None, blocked=None):
        return _slot(
            ad["id"], entity_id, ad["name"], state, thumbnail, replace_task_id, copy=copy,
            workbench_href=href, format_key=ad.get("format_key"), blocked=blocked,
            offer_label=offer_label,
        )

    if entity is not None:
        # Launched: the platform ad is the fact; a replace request reaches it through its id.
        from app.ads import triage

        return slot(
            "ready",
            triage._thumbnail_url(entity) or material_thumb,
            material_copy,
            entity["id"],
            replace_by_entity.get(entity["id"]),
        )
    if launch.ready_material(material):
        return slot("ready", material_thumb, material_copy)
    if pending is not None:
        pending_copy = bindings.effective_copy(pending)
        pending_thumb = _asset_thumbnail(conn, org, brand, pending["asset_id"])
        blocked = _blocked(conn, org, brand, pending)
        if not _has_copy(pending_copy):
            if blocked is not None and blocked["fix"] == "file":
                # The file itself failed: picking a copy would not unblock the slot.
                return slot("blocked", pending_thumb, None, blocked=blocked)
            # A file with no copy: the picker (`choose_copy`) fills the other half.
            return slot("image_only", pending_thumb, None)
        waiting_copy = _copy_half("placement", "待確認", pending_copy)
        if blocked is not None:
            # F44: the refusal is told, with its exit, instead of an endless `in_progress`.
            return slot("blocked", pending_thumb, waiting_copy, blocked=blocked)
        return slot("in_progress", pending_thumb, waiting_copy)
    if material is not None:
        # Assigned, but the version was revised or its original is not ready: not launchable.
        stale_copy = _copy_half("placement", "待確認", material["copy_fields"])
        return slot("in_progress", material_thumb, stale_copy)
    selected = _workbench_copy(conn, org, brand, brief)
    if selected is not None:
        # The copy half is known before any file: the user picked it on the workbench. That
        # selection outranks "pack being worked" (the pack lock is a separate fact).
        return slot("copy_only", None, {"source": "workbench", **selected})
    if readiness.get(ad["id"]) == "in_progress":
        return slot("in_progress", None, None)
    return slot("missing", None, None)


def _planned_groups(conn, org, brand, campaign_row, replace_by_entity) -> list:
    # Lazy, as in `_confirm_if_ready`. The offer label has one resolver: the one the
    # confirmation judges the copy against.
    from app.ads import asset_suggestions

    campaign = campaign_row["id"]
    ads = ads_repo.list_ads_for_campaign(conn, org, brand, campaign)
    readiness = {
        row["ad_id"]: row["state"]
        for row in legacy_readiness.readiness(conn, org, brand, campaign)
    }
    entities = _planned_entities(conn, org, brand, campaign)
    sets = _ad_sets(conn, org, brand, campaign)
    return [
        {
            "group_id": group["id"],
            "name": group["name"],
            "slots": [
                _planned_slot(
                    conn, org, brand, campaign, ad, entities.get(ad["id"]), readiness,
                    replace_by_entity, sets.get(ad["id"]),
                    asset_suggestions._judged_against(
                        conn, org, brand, campaign_row, ad["id"]
                    )["offer_label"],
                )
                for ad in ads
                if ad["group_id"] == group["id"]
            ],
        }
        for group in ads_repo._groups_for_campaign(conn, org, brand, campaign)
    ]


def _platform_groups(conn, org, brand, campaign, replace_by_entity) -> list:
    """Imported: every live platform ad under its platform parent (ad set); parents by name."""
    from app.ads import triage

    rows = [
        dict(r)
        for r in conn.execute(
            "SELECT * FROM ads_external_entity WHERE org_id=%s AND brand_id=%s "
            "AND campaign_id=%s ORDER BY id",
            (org, brand, campaign),
        ).fetchall()
    ]
    by_native = {(r["native_kind"], r["native_id"]): r for r in rows}
    groups: dict = {}
    for entity in rows:
        if entity["native_kind"] != "ad" or ad_status.is_closed(entity.get("native_status")):
            continue
        parent = by_native.get((entity.get("parent_native_kind"), entity.get("parent_native_id")))
        key = parent["id"] if parent is not None else None
        group = groups.setdefault(
            key,
            {
                "group_id": None,
                "name": (parent or {}).get("name") or entity.get("parent_native_id") or "",
                "slots": [],
            },
        )
        group["slots"].append(
            _slot(
                None,
                entity["id"],
                entity.get("name") or entity["native_id"],
                "ready",
                triage._thumbnail_url(entity),
                replace_by_entity.get(entity["id"]),
                format_key=None,
            )
        )
    ordered = sorted(groups.values(), key=lambda g: g["name"])
    for group in ordered:
        group["slots"].sort(key=lambda s: s["name"])
    return ordered


def read(conn, org, brand, campaign_id) -> dict:
    """`GET …/campaigns/{c}/slots` (Contract F)."""
    campaign = ads_repo.get_campaign(conn, org, brand, campaign_id)
    if campaign is None:
        raise ValueError("找不到此品牌的活動。")
    requests = material_tasks.replace_requests(conn, org, brand, campaign_id)
    by_entity = requests["by_entity"]
    if campaign["origin"] == "imported":
        groups = _platform_groups(conn, org, brand, campaign_id, by_entity)
    else:
        groups = _planned_groups(conn, org, brand, campaign, by_entity)
    slots = [s for g in groups for s in g["slots"]]
    return {
        "ready": sum(1 for s in slots if s["state"] == "ready"),
        "total": len(slots),
        "groups": groups,
        "requests": requests["requests"],
        "requests_truncated": requests["truncated"],
    }


def _planned_ad(conn, org, brand, campaign_id, ad_id) -> dict:
    row = conn.execute(
        "SELECT * FROM ads_ad WHERE org_id=%s AND brand_id=%s AND campaign_id=%s AND id=%s "
        "FOR UPDATE",
        (org, brand, campaign_id, ad_id),
    ).fetchone()
    if row is None:
        raise ValueError("找不到此活動的計畫廣告。")
    return dict(row)


def settle(conn, org, brand, campaign_id, placement_id) -> None:
    """Assign a slot's uploaded placement once its current revision is confirmed. A refusal by
    `handoff_assignment.assign` (e.g. an approved launch freezes the materials) leaves the slot
    waiting; the confirmation itself stands."""
    try:
        current = user_assets.placement(conn, org, brand, campaign_id, placement_id)
        asset = user_assets.get_asset(conn, org, brand, current["asset_id"])
    except ValueError:
        return
    if not current["confirmed_at"] or asset["status"] != "ready":
        return
    waiting = conn.execute(
        "SELECT id FROM ads_ad WHERE org_id=%s AND brand_id=%s AND campaign_id=%s "
        "AND slot_placement_id=%s ORDER BY created_at,id",
        (org, brand, campaign_id, placement_id),
    ).fetchall()
    for row in waiting:
        try:
            handoff_assignment.assign(
                conn, org, brand, campaign_id, row["id"], placement_id, current["revision"]
            )
        except ValueError:
            continue
        conn.execute(
            "UPDATE ads_ad SET slot_placement_id=NULL,updated_at=now() WHERE org_id=%s "
            "AND brand_id=%s AND campaign_id=%s AND id=%s AND slot_placement_id=%s",
            (org, brand, campaign_id, row["id"], placement_id),
        )
    conn.commit()


FROZEN_MESSAGE = "首次投放清單已核准，不能改寫原交接素材；請先處理原核准清單。"


def _confirm_if_ready(conn, org, brand, campaign_id, placement, actor) -> None:
    """The no-AI confirmation of a slot's placement once its original is ready. A result that
    still carries `pending_reasons` (zero budget, copy missing a field) is not an error and
    nothing is forced: the refusal's Contract C details are kept on this revision
    (`blocked_reasons`) so the slot reads `blocked` and says why. `wait` details (the preview is
    not made yet) are not kept; a refusal with only those leaves the slot `in_progress`."""
    if placement["confirmed_at"]:
        return
    try:
        asset = user_assets.get_asset(conn, org, brand, placement["asset_id"])
    except ValueError:
        return
    if asset["status"] != "ready":
        return
    # Lazy, the way the routes reach `settle`: `asset_suggestions` loads this module's
    # neighbours at import time.
    from app.ads import asset_suggestions

    try:
        result = asset_suggestions.confirm_manual(
            conn, org, brand, campaign_id, placement["id"], placement["revision"], actor
        )
    except ValueError as exc:
        # E.g. the campaign's sell-way was deleted (`validate_claims`): the placement is
        # already stored, so the slot says it instead of the upload failing.
        details = [asset_suggestions.policy.detail("campaign", str(exc))]
    else:
        details = [d for d in result.get("pending_details") or [] if d["kind"] != "wait"]
    if not details:
        return
    conn.execute(
        "UPDATE ads_asset_placement SET blocked_reasons=%s WHERE org_id=%s AND brand_id=%s "
        "AND campaign_id=%s AND id=%s AND revision=%s AND confirmed_at IS NULL",
        (db.jsonb(details), org, brand, campaign_id, placement["id"], placement["revision"]),
    )
    conn.commit()


PREVIEW_ACTOR = "system:preview"


def settle_ready_asset(conn, org, brand, asset_id) -> int:
    """Drill-8 #4: once an original's preview is made (`user_assets.process_preview`, its only
    reader), confirm and settle every slot still waiting on it -- the same two calls `upload`
    runs, so a file uploaded while its original was pending reaches `ready` with no second click.

    Only current, unconfirmed placements an `ads_ad` points at through `slot_placement_id` are
    touched; a library placement (no ad points at it) waits for the user's own confirmation. The
    actor is the placement's `created_by` (who uploaded it into the slot), else `system:preview`.
    Returns how many slots were settled (ads whose slot now carries the confirmed placement)."""
    waiting = conn.execute(
        "SELECT DISTINCT a.campaign_id,a.slot_placement_id FROM ads_ad a "
        "JOIN ads_asset_placement p ON p.id=a.slot_placement_id AND p.org_id=a.org_id "
        "AND p.brand_id=a.brand_id AND p.campaign_id=a.campaign_id AND p.is_current "
        "WHERE a.org_id=%s AND a.brand_id=%s AND p.asset_id=%s AND p.confirmed_at IS NULL "
        "ORDER BY a.campaign_id,a.slot_placement_id",
        (org, brand, asset_id),
    ).fetchall()
    settled = 0
    for row in waiting:
        campaign_id, placement_id = row["campaign_id"], row["slot_placement_id"]
        placement = user_assets.placement(conn, org, brand, campaign_id, placement_id)
        _confirm_if_ready(
            conn, org, brand, campaign_id, placement, placement["created_by"] or PREVIEW_ACTOR
        )
        conn.commit()
        before = _slot_ads(conn, org, brand, campaign_id, placement_id)
        settle(conn, org, brand, campaign_id, placement_id)
        settled += len(before - _slot_ads(conn, org, brand, campaign_id, placement_id))
    return settled


def _slot_ads(conn, org, brand, campaign_id, placement_id) -> set:
    return {
        r["id"]
        for r in conn.execute(
            "SELECT id FROM ads_ad WHERE org_id=%s AND brand_id=%s AND campaign_id=%s "
            "AND slot_placement_id=%s",
            (org, brand, campaign_id, placement_id),
        ).fetchall()
    }


def _slot_ad_for_write(conn, org, brand, campaign_id, ad_id) -> dict:
    ads_repo.require_internal_campaign(conn, org, brand, campaign_id)
    ad = _planned_ad(conn, org, brand, campaign_id, ad_id)
    if ad["id"] in _planned_entities(conn, org, brand, campaign_id):
        raise ValueError("這則廣告已在平台上；要換素材請用「換掉這一則」。")
    # The same freeze `handoff_assignment.assign` applies, told before the file is placed; an ad
    # deferred from the approved batch for lack of material is not frozen (F30 Unresolved 1).
    if launch.material_frozen(conn, org, brand, campaign_id, ad_id):
        raise ValueError(FROZEN_MESSAGE)
    return ad


def upload(conn, org, brand, campaign_id, ad_id, body, actor) -> dict:
    """`POST …/campaigns/{c}/slots/{ad_id}/upload`: `{upload_id}` (a finished upload) or
    `{asset_id}`, optional `copy_fields` -- the same inputs as `POST …/placements`. Without
    `copy_fields` the ad's selected workbench copy rides in; the purpose is the ad's name; a
    ready original is confirmed and assigned in this same call (Contract T).

    F41-I01: `{placement_id}` (a finished asset already placed in this campaign -- the advanced
    「將成品指派給計畫中的廣告」 panel) places that placement's original for this ad. Its effective
    copy plays the part an upload's own copy plays for `{upload_id}`: used only when neither
    `copy_fields` nor the ad's selected workbench copy is there. One rule set, one place."""
    if not isinstance(body, dict) or set(body) - {
        "upload_id", "asset_id", "placement_id", "copy_fields"
    }:
        raise ValueError("上傳欄位無效。")
    if body.get("placement_id") is not None and (
        not isinstance(body["placement_id"], str)
        or not body["placement_id"]
        or body.get("upload_id")
        or body.get("asset_id")
    ):
        raise ValueError("上傳欄位無效。")
    if not body.get("upload_id") and not body.get("asset_id") and not body.get("placement_id"):
        raise ValueError("請先上傳檔案，或選一個品牌原檔。")
    ad = _slot_ad_for_write(conn, org, brand, campaign_id, ad_id)
    own_copy = None
    if body.get("placement_id"):
        source = user_assets.placement(conn, org, brand, campaign_id, body["placement_id"])
        own_copy = bindings.effective_copy(source)
        body = {"asset_id": source["asset_id"], "copy_fields": body.get("copy_fields")}
    if body.get("copy_fields") is None:
        ad_copy = _workbench_copy(
            conn, org, brand, _ad_sets(conn, org, brand, campaign_id).get(ad["id"])
        )
        if ad_copy is not None:
            body = {
                **body,
                "copy_fields": {
                    k: ad_copy[k] for k in COPY_FIELDS if isinstance(ad_copy.get(k), str)
                },
            }
        elif own_copy is not None:
            body = {**body, "copy_fields": own_copy}
    placement = user_assets.attach_selected(
        conn, org, brand, campaign_id, body, actor, purpose=ad["name"], ad_id=ad["id"]
    )
    conn.execute(
        "UPDATE ads_ad SET slot_placement_id=%s,updated_at=now() WHERE org_id=%s "
        "AND brand_id=%s AND campaign_id=%s AND id=%s",
        (placement["id"], org, brand, campaign_id, ad_id),
    )
    conn.commit()
    _confirm_if_ready(conn, org, brand, campaign_id, placement, actor)
    settle(conn, org, brand, campaign_id, placement["id"])
    return {
        "placement": user_assets.placement(conn, org, brand, campaign_id, placement["id"]),
        "slots": read(conn, org, brand, campaign_id),
    }


def copy_options(conn, org, brand, campaign_id) -> dict:
    """`GET …/campaigns/{c}/slots/copy-options`: the brand's workbench copy versions, for the
    picker on a slot that has a file and whose ad has no selected copy."""
    ads_repo.require_internal_campaign(conn, org, brand, campaign_id)
    return {"options": workbench.material_options(conn, org, brand, part="copy")}


def choose_copy(conn, org, brand, campaign_id, ad_id, body, actor) -> dict:
    """`POST …/campaigns/{c}/slots/{ad_id}/copy` `{set_id, version_id}`: write that workbench
    version into the slot's pending placement (a new revision), confirm it and settle. A slot
    with no file has no picker: `ValueError("slot_no_file")`."""
    if (
        not isinstance(body, dict)
        or set(body) != {"set_id", "version_id"}
        or not all(isinstance(body[k], str) and body[k] for k in ("set_id", "version_id"))
    ):
        raise ValueError("文案選項無效。")
    ad = _slot_ad_for_write(conn, org, brand, campaign_id, ad_id)
    current = _pending(conn, org, brand, campaign_id, ad)
    if current is None or current["confirmed_at"]:
        raise ValueError("slot_no_file")
    try:
        source = workbench.material_source(conn, org, brand, body["set_id"], body["version_id"])
    except ValueError:
        source = None
    if source is None or source.get("part") != "copy":
        raise ValueError("找不到這個文案版本。")
    fields = {
        k: v for k, v in (source.get("copy_fields") or {}).items()
        if k in COPY_FIELDS and isinstance(v, str)
    }
    revised = user_assets.revise(
        conn,
        org,
        brand,
        campaign_id,
        current["id"],
        current["revision"],
        {"copy_fields": fields, "purpose": current["purpose"] or ad["name"]},
        actor,
    )
    conn.commit()
    _confirm_if_ready(conn, org, brand, campaign_id, revised, actor)
    settle(conn, org, brand, campaign_id, revised["id"])
    return {
        "placement": user_assets.placement(conn, org, brand, campaign_id, revised["id"]),
        "slots": read(conn, org, brand, campaign_id),
    }


def recheck(conn, org, brand, campaign_id, ad_id, actor) -> dict:
    """`POST …/campaigns/{c}/slots/{ad_id}/recheck` (F44 Contract D): run the confirmation of the
    slot's pending placement again -- after the user fixed what blocked it somewhere else -- and
    settle. Still refused: the stored reasons are the new refusal's. A slot with no unconfirmed
    placement has nothing to check: `ValueError("slot_no_file")`."""
    ad = _slot_ad_for_write(conn, org, brand, campaign_id, ad_id)
    current = _pending(conn, org, brand, campaign_id, ad)
    if current is None or current["confirmed_at"]:
        raise ValueError("slot_no_file")
    _confirm_if_ready(conn, org, brand, campaign_id, current, actor)
    settle(conn, org, brand, campaign_id, current["id"])
    return {"slots": read(conn, org, brand, campaign_id)}
