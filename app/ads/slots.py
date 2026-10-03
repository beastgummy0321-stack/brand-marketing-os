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

F45 Contract W (§6.49): `in_progress` only while a job for the slot runs (its original's
preview, or its workbench set's generation), with `job`; otherwise a slot that is not ready,
blocked or half-filled reads `waiting` with the user's next action. A new revision of the
placement behind a slot (placement edit, copy pick, typed copy edit) is confirmed at once
(`follow_revision`); every refusal is stored by `asset_suggestions.store_refusal`.

F46 Contract F: every slot carries `format_note` -- the sentence when the file the slot shows
(its material, else the placement behind it) ships in another format than the ad's planned
`format_key` (`actual_format`); `None` otherwise and on an imported campaign.

F48 Contract G: every slot carries `offer_key` beside `offer_label` (the offer the ad's copy was
written for, `live_creative.offer_for`, the one the confirmation judges against) and `statutory`
-- the 食安法 reminder over its copy half (`workbench.statutory_reminder`, brand regime read once
per read), computed at read and never stored.
"""

from app import workbench
from app.ads import actual_format, ad_status, handoff_assignment, material_tasks
from app.ads import asset_binding_repository as bindings
from app.ads import assets as legacy_readiness
from app.ads import change_control_launch as launch
from app.ads import repository as ads_repo
from app.ads import user_assets_repository as user_assets
from app.brand_intelligence import repository as brands


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


def _readable_asset(conn, org, brand, asset_id) -> dict | None:
    try:
        return user_assets.get_asset(conn, org, brand, asset_id)
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
    workbench_href=None, format_key=None, blocked=None, offer_label=None, waiting=None,
    job=None, format_note=None, offer_key=None, statutory=None,
) -> dict:
    """One slot. F40-I01: `format_key` is the planned ad's own `ads_ad.format_key` (`None` for an
    ad without one, and for an imported campaign's platform ad) so the assets tab can say a
    video-format slot needs a script. F44 Contract D: `blocked` is set on a `blocked` slot only;
    `offer_label` is the planned ad's offer coordinate label (`None` for an ad without one, and
    for an imported campaign's platform ad). F45 Contract W: `waiting` is set on a `waiting`
    slot only (`{action, text}`), `job` on an `in_progress` slot only (`{kind, done, of}`).
    F46 Contract F: `format_note` says when the file in the slot ships in another format than
    planned (`actual_format.note`); `None` when they agree, with no file, and when imported.
    F48 Contract G: `offer_key` beside `offer_label` (the same resolver, `live_creative.
    offer_for`); `statutory` = the 食安法 reminder over the slot's copy
    (`workbench.statutory_reminder`, computed at read), `None` without a hit, a regime, a copy,
    and on an imported campaign."""
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
        "offer_key": offer_key,
        "waiting": waiting,
        "job": job,
        "format_note": format_note,
        "statutory": statutory,
    }


# F45 Contract W: who the slot is waiting for. `in_progress` only while a job for it runs.
WAITING = {
    "pick_on_workbench": "等你：到工作檯選定一版文案",
    "confirm_copy": "等你：確認這版文案",
}
RUNNING_BRIEF = ("queued", "running")  # the workbench set's generation is queued or running


def _waiting(action) -> dict:
    return {"action": action, "text": WAITING[action]}


def _job(kind, brief=None) -> dict:
    """`done` / `of` only when the workbench read carries them; the brief read does not today."""
    brief = brief or {}
    done, of = brief.get("done"), brief.get("of")
    if not isinstance(done, int) or not isinstance(of, int):
        done = of = None
    return {"kind": kind, "done": done, "of": of}


FAILED_ORIGINAL = "error"  # the status `user_assets.process_preview` leaves on a failed original


def _blocked(asset, pending) -> dict | None:
    """Contract D `blocked` for a slot's pending placement (`asset` = its original, None when it
    cannot be read), or None when nothing blocks it: the first reason plus how many others. A
    failed original comes first (no copy fixes a file that cannot be processed), then the details
    the last refused confirmation stored. `wait` details are never stored, so every reason here
    has something to fix."""
    details = []
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


def _backing(conn, org, brand, campaign, ad, material=None) -> dict | None:
    """The current revision of the placement behind a slot that is not ready: the one uploaded
    into it (`slot_placement_id`), else its assigned material's placement once that assignment is
    no longer launchable (revised, or its original not ready). None for a ready or empty slot."""
    pending = _pending(conn, org, brand, campaign, ad)
    if pending is not None or ad.get("material_placement_id") is None:
        return pending
    if material is None:
        material = _material(conn, org, brand, campaign, ad)
    if material is None or launch.ready_material(material):
        return None
    try:
        return user_assets.placement(conn, org, brand, campaign, ad["material_placement_id"])
    except ValueError:
        return None


def _statutory(copy, regime) -> dict | None:
    """The 食安法 reminder over a slot's copy half (its three copy fields), else None."""
    if not copy:
        return None
    return workbench.statutory_reminder({k: copy.get(k) or "" for k in COPY_FIELDS}, regime)


def _planned_slot(
    conn, org, brand, campaign, ad, entity, replace_by_entity, brief, judged,
    format_names=None, regime=None,
) -> dict:
    """`judged` = `asset_suggestions._judged_against` of the ad (its offer key and label)."""
    material = _material(conn, org, brand, campaign, ad)
    material_thumb = (
        _asset_thumbnail(conn, org, brand, material["asset_id"]) if material else None
    )
    href = workbench.set_action_url(conn, org, brand, brief["id"]) if brief else None
    # `material_snapshot.copy_fields` is `bindings.effective_copy` of the assigned revision.
    material_copy = _copy_half("placement", "已確認", material["copy_fields"]) if material else None

    def slot(
        state, thumbnail, copy, entity_id=None, replace_task_id=None, blocked=None,
        waiting=None, job=None, asset=None,
    ):
        # F46 Contract F: the file the tile shows decides the format that ships.
        note = actual_format.note(
            ad.get("format_key"), actual_format.of_asset(asset), format_names or {}
        )
        return _slot(
            ad["id"], entity_id, ad["name"], state, thumbnail, replace_task_id, copy=copy,
            workbench_href=href, format_key=ad.get("format_key"), blocked=blocked,
            offer_label=judged["offer_label"], waiting=waiting, job=job, format_note=note,
            offer_key=judged["offer_key"], statutory=_statutory(copy, regime),
        )

    material_asset = _readable_asset(conn, org, brand, material["asset_id"]) if material else None

    if entity is not None:
        # Launched: the platform ad is the fact; a replace request reaches it through its id.
        from app.ads import triage

        return slot(
            "ready",
            triage._thumbnail_url(entity) or material_thumb,
            material_copy,
            entity["id"],
            replace_by_entity.get(entity["id"]),
            asset=material_asset,
        )
    if launch.ready_material(material):
        return slot("ready", material_thumb, material_copy, asset=material_asset)
    pending = _backing(conn, org, brand, campaign, ad, material)
    if pending is not None:
        # Contract W, in this order: a failed original, its preview running, no copy, a stored
        # refusal, else the user's confirmation is what the slot waits for.
        pending_copy = bindings.effective_copy(pending)
        pending_thumb = _asset_thumbnail(conn, org, brand, pending["asset_id"])
        copy_half = (
            _copy_half("placement", "待確認", pending_copy) if _has_copy(pending_copy) else None
        )
        try:
            original = user_assets.get_asset(conn, org, brand, pending["asset_id"])
        except ValueError:
            original = None
        blocked = _blocked(original, pending)
        if original is not None and original["status"] == FAILED_ORIGINAL:
            # The file itself failed: no copy unblocks the slot.
            return slot("blocked", pending_thumb, copy_half, blocked=blocked, asset=original)
        if original is not None and original["status"] != "ready":
            # Its preview is being made (pending / processing / retryable).
            return slot(
                "in_progress", pending_thumb, copy_half, job=_job("preview"), asset=original
            )
        if copy_half is None:
            # A file with no copy: the picker (`choose_copy`) fills the other half.
            return slot("image_only", pending_thumb, None, asset=original)
        if blocked is not None:
            # F44: the refusal is told, with its exit.
            return slot("blocked", pending_thumb, copy_half, blocked=blocked, asset=original)
        return slot(
            "waiting", pending_thumb, copy_half, waiting=_waiting("confirm_copy"), asset=original
        )
    selected = _workbench_copy(conn, org, brand, brief)
    if selected is not None:
        # The copy half is known before any file: the user picked it on the workbench.
        return slot("copy_only", None, {"source": "workbench", **selected})
    if brief is not None:
        if brief.get("status") in RUNNING_BRIEF:
            return slot("in_progress", None, None, job=_job("copy", brief))
        # Generated (or stopped) with nothing selected: the user picks on the workbench.
        return slot("waiting", None, None, waiting=_waiting("pick_on_workbench"))
    return slot("missing", None, None)


def _planned_groups(conn, org, brand, campaign_row, replace_by_entity) -> list:
    # Lazy, as in `_confirm_if_ready`. The offer key and label have one resolver: the one the
    # confirmation judges the copy against.
    from app.ads import asset_suggestions

    campaign = campaign_row["id"]
    ads = ads_repo.list_ads_for_campaign(conn, org, brand, campaign)
    entities = _planned_entities(conn, org, brand, campaign)
    sets = _ad_sets(conn, org, brand, campaign)
    format_names = actual_format.labels(conn, org, brand)
    # F48 Contract G: the brand's regime, read once per slots read.
    regime = (brands.get_brand(conn, brand) or {}).get("regulatory_regime")
    return [
        {
            "group_id": group["id"],
            "name": group["name"],
            "slots": [
                _planned_slot(
                    conn, org, brand, campaign, ad, entities.get(ad["id"]),
                    replace_by_entity, sets.get(ad["id"]),
                    asset_suggestions._judged_against(
                        conn, org, brand, campaign_row, ad["id"]
                    ),
                    format_names,
                    regime,
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
    nothing is forced: `asset_suggestions.confirm_manual` itself keeps the refusal's Contract C
    details on this revision (`blocked_reasons`) so the slot reads `blocked` and says why. A
    refusal raised as `ValueError` is kept through the same writer."""
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
        asset_suggestions.confirm_manual(
            conn, org, brand, campaign_id, placement["id"], placement["revision"], actor
        )
    except ValueError as exc:
        # E.g. the campaign's sell-way was deleted (`validate_claims`): the placement is
        # already stored, so the slot says it instead of the upload failing.
        asset_suggestions.store_refusal(
            conn, org, brand, campaign_id, placement["id"], placement["revision"],
            [asset_suggestions.policy.detail("campaign", str(exc))],
        )


def follow_revision(conn, org, brand, campaign_id, placement, actor) -> None:
    """§6.49: a new revision of a placement that backs a planned ad's slot (the ad's
    `slot_placement_id`, or -- with none -- its assigned material's placement) is pointed at by
    that ad's `slot_placement_id`, confirmed and settled at once, so an edit is checked when it
    is saved. A launched or frozen ad is skipped (no error); a library placement no slot uses
    and an already confirmed revision are left alone."""
    if placement["confirmed_at"]:
        return
    rows = conn.execute(
        "SELECT id,slot_placement_id FROM ads_ad WHERE org_id=%s AND brand_id=%s "
        "AND campaign_id=%s AND (slot_placement_id=%s OR (slot_placement_id IS NULL "
        "AND material_placement_id=%s)) ORDER BY created_at,id",
        (org, brand, campaign_id, placement["id"], placement["id"]),
    ).fetchall()
    if not rows:
        return
    launched = _planned_entities(conn, org, brand, campaign_id)
    backed = False
    for row in rows:
        if row["id"] in launched or launch.material_frozen(
            conn, org, brand, campaign_id, row["id"]
        ):
            continue
        backed = True
        if row["slot_placement_id"] != placement["id"]:
            _point(conn, org, brand, campaign_id, row["id"], placement["id"])
    if not backed:
        return
    conn.commit()
    _confirm_if_ready(conn, org, brand, campaign_id, placement, actor)
    settle(conn, org, brand, campaign_id, placement["id"])


def _point(conn, org, brand, campaign_id, ad_id, placement_id) -> None:
    conn.execute(
        "UPDATE ads_ad SET slot_placement_id=%s,updated_at=now() WHERE org_id=%s "
        "AND brand_id=%s AND campaign_id=%s AND id=%s",
        (placement_id, org, brand, campaign_id, ad_id),
    )


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
    _point(conn, org, brand, campaign_id, ad_id, placement["id"])
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


def _copy_body(body) -> tuple[str, dict]:
    """The two bodies of `POST …/slots/{ad}/copy`: `{set_id, version_id}` (a workbench version)
    or `{copy_fields: {headline?, body?, description?}}` (the copy typed in the slot editor)."""
    if isinstance(body, dict) and set(body) == {"copy_fields"}:
        fields = body["copy_fields"]
        try:
            user_assets.validate_copy(fields)
        except ValueError:
            raise ValueError("文案選項無效。") from None
        if not fields or set(fields) - set(COPY_FIELDS):
            raise ValueError("文案選項無效。")
        return "typed", fields
    if (
        not isinstance(body, dict)
        or set(body) != {"set_id", "version_id"}
        or not all(isinstance(body[k], str) and body[k] for k in ("set_id", "version_id"))
    ):
        raise ValueError("文案選項無效。")
    return "workbench", body


def choose_copy(conn, org, brand, campaign_id, ad_id, body, actor) -> dict:
    """`POST …/campaigns/{c}/slots/{ad_id}/copy`: `{set_id, version_id}` writes that workbench
    version, `{copy_fields}` the copy typed in the slot editor (over the placement's own fields;
    a field not sent keeps its value), into the placement behind the slot (a new revision), which
    is then pointed at, confirmed and settled (`follow_revision`). A slot with no unconfirmed
    placement behind it has no picker: `ValueError("slot_no_file")`."""
    kind, value = _copy_body(body)
    ad = _slot_ad_for_write(conn, org, brand, campaign_id, ad_id)
    current = _backing(conn, org, brand, campaign_id, ad)
    if current is None or current["confirmed_at"]:
        raise ValueError("slot_no_file")
    if kind == "typed":
        fields = {**(current["copy_fields"] or {}), **value}
    else:
        try:
            source = workbench.material_source(
                conn, org, brand, value["set_id"], value["version_id"]
            )
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
    follow_revision(conn, org, brand, campaign_id, revised, actor)
    return {
        "placement": user_assets.placement(conn, org, brand, campaign_id, revised["id"]),
        "slots": read(conn, org, brand, campaign_id),
    }


def recheck(conn, org, brand, campaign_id, ad_id, actor) -> dict:
    """`POST …/campaigns/{c}/slots/{ad_id}/recheck` (F44 Contract D): run the confirmation of the
    placement behind the slot again -- after the user fixed what blocked it somewhere else -- and
    settle. A revised assigned material is pointed at first (§6.49), so it is checked like an
    upload. Still refused: the stored reasons are the new refusal's. A slot with no unconfirmed
    placement behind it has nothing to check: `ValueError("slot_no_file")`."""
    ad = _slot_ad_for_write(conn, org, brand, campaign_id, ad_id)
    current = _backing(conn, org, brand, campaign_id, ad)
    if current is None or current["confirmed_at"]:
        raise ValueError("slot_no_file")
    if ad.get("slot_placement_id") != current["id"]:
        _point(conn, org, brand, campaign_id, ad_id, current["id"])
        conn.commit()
    _confirm_if_ready(conn, org, brand, campaign_id, current, actor)
    settle(conn, org, brand, campaign_id, current["id"])
    return {"slots": read(conn, org, brand, campaign_id)}
