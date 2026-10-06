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

F49 Contract T: `STATE_TEXT` is the one state -> (chip, sentence) table; every slot serves
`state`, `state_label` and `state_text`. The stored states are told as they are: a preview that
failed and will be tried again is `retrying` (its error and `retry_at`), a workbench set whose
generation failed is `failed` (its `last_error`, the workbench exit), a confirmed placement whose
assignment was refused is `blocked` with that refusal (stored as kind `assign`). The asset and
brief status vocabularies are read only by `_original_state`／`brief_state`. A ready slot's copy can
be changed until the launch is approved (`copy_editable`); copy options are the campaign's
sell-way's only.
"""

from app import workbench
from app.ads import actual_format, handoff_assignment, lifecycle, material_tasks, sell_way
from app.ads import asset_binding_repository as bindings
from app.ads import assets as legacy_readiness
from app.ads import change_control_launch as launch
from app.ads import repository as ads_repo
from app.ads import user_assets_repository as user_assets
from app.brand_intelligence import repository as brands
from app.core import settings


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


# F49 Contract T: the one state -> (chip, sentence) table. A `{…}` in a sentence is filled from
# the slot's own facts at read (`_slot(say=…)`).
STATE_TEXT = {
    "ready": ("已確認", "{note}"),
    "in_progress": ("處理中", "{work}"),
    "retrying": ("處理中", "圖片預覽沒做成（{error}），{retry_at} 會再試"),
    "failed": ("失敗", "文案沒產生出來：{last_error}"),
    "blocked": ("卡住", "{reason}"),
    "image_only": ("等你", "有圖，還缺文案"),
    "copy_only": ("等你", "有文案，還缺圖"),
    "waiting": ("等你", "{next}"),
    "missing": ("缺", "還沒有素材"),
}
# A ready slot's sentence: its copy can change until the launch is approved, then it is frozen;
# a platform ad is changed by replacing it.
READY_NOTE = {
    "editable": "圖和文案都確認了；上架清單核准前還能改文案。",
    "frozen": "圖和文案都確認了；首次投放清單已核准，要改請先處理原核准清單。",
    "on_platform": "已在平台上；要換素材請用「換掉這一則」。",
}
JOB_TEXT = {"preview": "圖片處理中", "copy": "文案產生中"}
NO_CAUSE = "原因沒有記下來"


def _slot(
    ad_id, entity_id, name, state, thumbnail_url, replace_task_id=None, *, copy=None,
    workbench_href=None, format_key=None, blocked=None, offer_label=None, waiting=None,
    job=None, format_note=None, offer_key=None, statutory=None, say=None, retry_at=None,
    copy_editable=False,
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
    and on an imported campaign.
    F49 Contract T: `state_label` (the chip) and `state_text` (the sentence) come from
    `STATE_TEXT[state]`, filled with `say`; `retry_at` is set on a `retrying` slot only;
    `copy_editable` is true only on a ready planned ad whose launch is not approved yet."""
    label, sentence = STATE_TEXT[state]
    return {
        "ad_id": ad_id,
        "entity_id": entity_id,
        "name": name,
        "state": state,
        "state_label": label,
        "state_text": sentence.format(**(say or {})),
        "retry_at": retry_at,
        "copy_editable": copy_editable,
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
RUNNING_ORIGINAL = ("pending", "processing")  # the original's preview is queued or being made


def _waiting(action) -> dict:
    return {"action": action, "text": WAITING[action]}


def _original_state(asset) -> str | None:
    """F49 Contract T: the one reader of `ads_user_asset.status` here -- `blocked` (the preview
    failed for good, `error`), `retrying` (an attempt failed and another is due, `retryable`),
    `in_progress` (queued or being made), `ready`, or None when the original cannot be read."""
    if asset is None:
        return None
    status = asset["status"]
    if status == "error":
        return "blocked"
    if status == "retryable":
        return "retrying"
    if status in RUNNING_ORIGINAL:
        return "in_progress"
    return "ready" if status == "ready" else "in_progress"


def brief_state(brief) -> str | None:
    """F49 Contract T: the one reader of a workbench set's `status` in ads -- `in_progress` while
    its generation is queued or running, `failed` when the last one failed, else None (idle or
    done: what the user picked decides)."""
    status = (brief or {}).get("status")
    if status in RUNNING_BRIEF:
        return "in_progress"
    if status == "failed":
        return "failed"
    return None


def _job(kind, brief=None) -> dict:
    """`done` / `of` only when the workbench read carries them; the brief read does not today."""
    brief = brief or {}
    done, of = brief.get("done"), brief.get("of")
    if not isinstance(done, int) or not isinstance(of, int):
        done = of = None
    return {"kind": kind, "done": done, "of": of}


def _clock(at, tz) -> str:
    """The time a retry is due, on the org's clock (「14:05」); 「稍後」 when none is stored."""
    return "稍後" if at is None else f"{at.astimezone(tz):%H:%M}"


def _blocked(asset, pending) -> dict | None:
    """Contract D `blocked` for a slot's pending placement (`asset` = its original, None when it
    cannot be read), or None when nothing blocks it: the first reason plus how many others. A
    failed original comes first (no copy fixes a file that cannot be processed), then the details
    the last refused confirmation stored. `wait` details are never stored, so every reason here
    has something to fix. F49 Contract T: a confirmed revision keeps only why its assignment was
    refused (kind `assign`), and that is read too."""
    details = []
    if _original_state(asset) == "blocked":
        reason = f"：{asset['error']}" if asset["error"] else "。"
        details.append({"kind": "file", "text": f"這個檔案處理失敗{reason}", "terms": []})
    stored = pending.get("blocked_reasons") or []
    if pending["confirmed_at"]:
        stored = [d for d in stored if d["kind"] == "assign"]
    details += stored
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
    format_names=None, regime=None, tz=None,
) -> dict:
    """`judged` = `asset_suggestions._judged_against` of the ad (its offer key and label); `tz` =
    the org's clock a retry time is told on."""
    material = _material(conn, org, brand, campaign, ad)
    material_thumb = (
        _asset_thumbnail(conn, org, brand, material["asset_id"]) if material else None
    )
    href = workbench.set_action_url(conn, org, brand, brief["id"]) if brief else None
    # `material_snapshot.copy_fields` is `bindings.effective_copy` of the assigned revision.
    material_copy = _copy_half("placement", "已確認", material["copy_fields"]) if material else None

    def slot(
        state, thumbnail, copy, entity_id=None, replace_task_id=None, blocked=None,
        waiting=None, job=None, asset=None, say=None, retry_at=None, copy_editable=False,
    ):
        # F46 Contract F: the file the tile shows decides the format that ships.
        note = actual_format.note(
            ad.get("format_key"), actual_format.of_asset(asset), format_names or {}
        )
        if blocked is not None:
            say = {"reason": blocked["text"]}
        elif waiting is not None:
            say = {"next": waiting["text"]}
        elif job is not None:
            say = {"work": JOB_TEXT[job["kind"]]}
        return _slot(
            ad["id"], entity_id, ad["name"], state, thumbnail, replace_task_id, copy=copy,
            workbench_href=href, format_key=ad.get("format_key"), blocked=blocked,
            offer_label=judged["offer_label"], waiting=waiting, job=job, format_note=note,
            offer_key=judged["offer_key"], statutory=_statutory(copy, regime), say=say,
            retry_at=retry_at, copy_editable=copy_editable,
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
            say={"note": READY_NOTE["on_platform"]},
        )
    if launch.ready_material(material):
        # F49 Contract T: its copy can change until the launch is approved (`choose_copy`).
        editable = not launch.material_frozen(conn, org, brand, campaign, ad["id"])
        return slot(
            "ready", material_thumb, material_copy, asset=material_asset,
            say={"note": READY_NOTE["editable" if editable else "frozen"]},
            copy_editable=editable,
        )
    pending = _backing(conn, org, brand, campaign, ad, material)
    if pending is not None:
        # Contract W, in this order: a failed original, its preview retrying or running, no
        # copy, a stored refusal, else the user's confirmation is what the slot waits for.
        pending_copy = bindings.effective_copy(pending)
        pending_thumb = _asset_thumbnail(conn, org, brand, pending["asset_id"])
        copy_half = (
            _copy_half("placement", "待確認", pending_copy) if _has_copy(pending_copy) else None
        )
        try:
            original = user_assets.get_asset(conn, org, brand, pending["asset_id"])
        except ValueError:
            original = None
        progress = _original_state(original)
        blocked = _blocked(original, pending)
        if progress == "blocked":
            # The file itself failed: no copy unblocks the slot.
            return slot("blocked", pending_thumb, copy_half, blocked=blocked, asset=original)
        if progress == "retrying" and original is not None:
            # An attempt failed and another is due: the error and when, never a silent 處理中.
            # (`_original_state` is None for an unreadable original, so it is read here.)
            return slot(
                "retrying", pending_thumb, copy_half, asset=original,
                retry_at=original["next_attempt_at"],
                say={
                    "error": original["error"] or NO_CAUSE,
                    "retry_at": _clock(original["next_attempt_at"], tz),
                },
            )
        if progress == "in_progress":
            return slot(
                "in_progress", pending_thumb, copy_half, job=_job("preview"), asset=original
            )
        if copy_half is None:
            # A file with no copy: the picker (`choose_copy`) fills the other half.
            return slot("image_only", pending_thumb, None, asset=original)
        if blocked is not None:
            # F44: the refusal is told, with its exit (F49: a refused assignment too).
            return slot("blocked", pending_thumb, copy_half, blocked=blocked, asset=original)
        return slot(
            "waiting", pending_thumb, copy_half, waiting=_waiting("confirm_copy"), asset=original
        )
    selected = _workbench_copy(conn, org, brand, brief)
    if selected is not None:
        # The copy half is known before any file: the user picked it on the workbench.
        return slot("copy_only", None, {"source": "workbench", **selected})
    if brief is not None:
        work = brief_state(brief)
        if work == "in_progress":
            return slot("in_progress", None, None, job=_job("copy", brief))
        if work == "failed":
            # The generation failed: nothing to pick; the workbench (`workbench_href`) reruns it.
            return slot(
                "failed", None, None, say={"last_error": brief.get("last_error") or NO_CAUSE}
            )
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
    tz = settings.org_timezone(conn, org_id=org)
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
                    tz,
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
        if entity["native_kind"] != "ad" or not lifecycle.may_spend(entity):
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
                say={"note": READY_NOTE["on_platform"]},
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


# F49 Contract T: why `handoff_assignment.assign` refused a confirmed revision, by code.
ASSIGN_REFUSALS = {
    "campaign_closed": "活動已結案，這個檔案沒有放上這則廣告；素材歷史仍可查看。",
    "launch_frozen": "首次投放清單已核准，這個檔案沒有換上這則廣告；要換請先處理原核准清單。",
}


def _assign_refusal(conn, org, brand, campaign_id, ad_id, exc) -> dict:
    """The stored refusal (kind `assign`) for a refused assignment: `campaign_closed` (a closed
    campaign takes no new material), `launch_frozen` (the approved launch froze this ad), else
    the refusal's own sentence with no code."""
    from app.ads import asset_suggestions

    campaign = ads_repo.get_campaign(conn, org, brand, campaign_id) or {}
    code: str | None = None
    if campaign.get("status") == "closed":
        code = "campaign_closed"
    elif launch.material_frozen(conn, org, brand, campaign_id, ad_id):
        code = "launch_frozen"
    text = ASSIGN_REFUSALS[code] if code is not None else str(exc)
    return {**asset_suggestions.policy.detail("assign", text), "code": code}


def settle(conn, org, brand, campaign_id, placement_id) -> None:
    """Assign a slot's uploaded placement once its current revision is confirmed. F49 Contract T:
    a refusal by `handoff_assignment.assign` (a closed campaign, an approved launch that froze
    the materials) is stored on the confirmed revision as kind `assign`, so the slot reads
    `blocked` with why; the confirmation itself stands. A later assignment that goes through
    clears it."""
    from app.ads import asset_suggestions

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
    refusals = []
    for row in waiting:
        try:
            handoff_assignment.assign(
                conn, org, brand, campaign_id, row["id"], placement_id, current["revision"]
            )
        except ValueError as exc:
            refusal = _assign_refusal(conn, org, brand, campaign_id, row["id"], exc)
            if refusal not in refusals:
                refusals.append(refusal)
            continue
        conn.execute(
            "UPDATE ads_ad SET slot_placement_id=NULL,updated_at=now() WHERE org_id=%s "
            "AND brand_id=%s AND campaign_id=%s AND id=%s AND slot_placement_id=%s",
            (org, brand, campaign_id, row["id"], placement_id),
        )
    conn.commit()
    stored = [d for d in current.get("blocked_reasons") or [] if d["kind"] == "assign"]
    if refusals or stored:
        asset_suggestions.store_refusal(
            conn, org, brand, campaign_id, placement_id, current["revision"], refusals,
            assignment=True,
        )


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
    _place(conn, org, brand, campaign_id, ad_id, placement, actor)
    return {
        "placement": user_assets.placement(conn, org, brand, campaign_id, placement["id"]),
        "slots": read(conn, org, brand, campaign_id),
    }


def _place(conn, org, brand, campaign_id, ad_id, placement, actor) -> None:
    """Point the slot at `placement`, then the no-AI confirmation and the assignment."""
    _point(conn, org, brand, campaign_id, ad_id, placement["id"])
    conn.commit()
    _confirm_if_ready(conn, org, brand, campaign_id, placement, actor)
    settle(conn, org, brand, campaign_id, placement["id"])


def carry(conn, org, brand, campaign_id, ad_id, asset_id, copy_fields, actor, *,
          atomic=False) -> None:
    """F48 Contract K: a 留下 ad carried into the next plan takes the original and copy it went
    out with -- `user_assets.attach(…, ad_id=…)` on the same original with that copy (purpose =
    the ad's name), then the same pointer／confirmation／assignment an upload runs, so the slot
    reads ready without a second click (or `blocked` with the refusal's reason)."""
    ad = _slot_ad_for_write(conn, org, brand, campaign_id, ad_id)
    placement = user_assets.attach(
        conn, org, brand, campaign_id, asset_id, copy_fields, actor, purpose=ad["name"],
        ad_id=ad_id,
    )
    if not atomic:
        _place(conn, org, brand, campaign_id, ad_id, placement, actor)
        return
    # Contract S: the adoption transaction owns every write and any refusal rolls it back.
    from app.ads import asset_suggestions
    confirmed = asset_suggestions.confirm_manual(
        conn, org, brand, campaign_id, placement["id"], placement["revision"], actor,
        strict=True,
    )
    handoff_assignment.assign(conn, org, brand, campaign_id, ad_id, confirmed["id"],
                              confirmed["revision"], commit=False)


def copy_options(conn, org, brand, campaign_id) -> dict:
    """`GET …/campaigns/{c}/slots/copy-options`: the workbench copy versions of the campaign's
    sell-way (F49 Contract T: another sell-way's copy is not offered; a campaign without one
    lists the brand's), for the picker on a slot with a file or a ready slot's copy change."""
    campaign = ads_repo.require_internal_campaign(conn, org, brand, campaign_id)
    return {
        "options": workbench.material_options(
            conn, org, brand, part="copy", product_id=sell_way.of_campaign(campaign)
        )
    }


def _editable(conn, org, brand, campaign_id, ad) -> dict | None:
    """The placement a slot's copy action works on: the one behind a slot that is not ready
    (`_backing`), else -- F49 Contract T -- a ready slot's assigned material (its copy can change
    until the launch is approved; `_slot_ad_for_write` already refused a frozen or launched ad).
    None for a slot with no file."""
    backing = _backing(conn, org, brand, campaign_id, ad)
    if backing is not None or ad.get("material_placement_id") is None:
        return backing
    if not launch.ready_material(_material(conn, org, brand, campaign_id, ad)):
        return None
    try:
        return user_assets.placement(conn, org, brand, campaign_id, ad["material_placement_id"])
    except ValueError:
        return None


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
    is then pointed at, confirmed and settled (`follow_revision`). F49 Contract T: on a ready
    slot the assigned material is revised the same way (still ready once confirmed) until the
    launch is approved, then `FROZEN_MESSAGE`. A slot with no file behind it has no picker:
    `ValueError("slot_no_file")`."""
    kind, value = _copy_body(body)
    ad = _slot_ad_for_write(conn, org, brand, campaign_id, ad_id)
    current = _editable(conn, org, brand, campaign_id, ad)
    if current is None:
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
    upload. Still refused: the stored reasons are the new refusal's. F49 Contract T: a confirmed
    placement whose assignment was refused is assigned again (still refused: the new refusal is
    stored); a ready slot has nothing left to check and answers its slots. A slot with no file
    behind it has nothing to check: `ValueError("slot_no_file")`."""
    ad = _slot_ad_for_write(conn, org, brand, campaign_id, ad_id)
    current = _editable(conn, org, brand, campaign_id, ad)
    if current is None:
        raise ValueError("slot_no_file")
    if not current["confirmed_at"] and ad.get("slot_placement_id") != current["id"]:
        _point(conn, org, brand, campaign_id, ad_id, current["id"])
        conn.commit()
    _confirm_if_ready(conn, org, brand, campaign_id, current, actor)
    settle(conn, org, brand, campaign_id, current["id"])
    return {"slots": read(conn, org, brand, campaign_id)}
