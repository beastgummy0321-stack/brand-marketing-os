"""Compatibility seam for the existing cold-start manual handoff, never a platform write."""

import json

from app.ads import (
    change_control,
    handoff_assignment,
    launch_settings,
    manual_settings,
    month_budget,
    plan,
)
from app.ads import change_control_data as data
from app.ads import repository as campaigns
from app.core import approval, db, settings
from app.core.audit import write_audit
from app.shared.web import to_json_value

# The "上架紀錄" fields are notes the user writes after building on the platform (platform IDs,
# execution differences) -- records, not plan content. Freezing them made every approved launch
# go stale the moment the user recorded what they built (F28-I04).
_PLAN_SETTING_KEYS = frozenset(
    f["key"] for f in manual_settings.FIELDS if f["section"] != "上架紀錄"
)


def ready_material(material) -> bool:
    """F30 Unresolved 1: a planned ad goes out in a launch batch only with a confirmed material
    (the same "ready" the assets slots show). The rule lives here, in the shared launch core --
    a future automatic publish cannot create an ad without a creative either."""
    return bool(material) and material.get("assignment_status") == "confirmed"


def _launched_ads(conn, org, brand, campaign_id):
    """Planned ads some approved launch version (current or superseded) already handed off."""
    return {
        r["planned_id"]
        for r in conn.execute(
            "SELECT DISTINCT h.planned_id FROM ads_handoff_item h JOIN ads_change_set c "
            "ON c.id=h.change_set_id AND c.org_id=h.org_id AND c.brand_id=h.brand_id "
            "AND c.campaign_id=h.campaign_id WHERE h.org_id=%s AND h.brand_id=%s "
            "AND h.campaign_id=%s AND h.planned_kind='ad' AND c.plan_json ? 'launch_snapshot' "
            "AND c.status IN ('approved','superseded')",
            (org, brand, campaign_id),
        ).fetchall()
    }


def snapshot(conn, org, brand, campaign_id, *, validate_material=False, deferred=None):
    """The launch content an approval freezes. An ad joins the batch once its material is
    ready; until then it stays in the plan and, when `deferred` is a list, is appended to it as
    `{ad_id, name, group_name}` -- it goes out with a later launch version. An ad an approved
    version already handed off never leaves the batch: an invalid material keeps F28's rule
    (shown in the diff, re-approval refused until it is re-assigned)."""
    campaign = campaigns.campaign_detail(conn, org, brand, campaign_id)
    if campaign is None:
        raise ValueError("campaign_unknown")
    launched = _launched_ads(conn, org, brand, campaign_id)
    fields = (
        "id",
        "name",
        "goal_text",
        "objective",
        "start_date",
        "end_date",
        "budget_planned",
        "channel",
        "external_id",
    )
    result = {key: campaign.get(key) for key in fields}
    result["month"] = settings.today_for_org(conn, org_id=org).strftime("%Y-%m")
    result["groups"] = []
    for group in campaign["groups"]:
        ads = []
        for ad in group.get("ads", []):
            material = handoff_assignment.material_snapshot(conn, org, brand, campaign_id, ad)
            if not ready_material(material) and ad["id"] not in launched:
                if deferred is not None:
                    deferred.append(
                        {"ad_id": ad["id"], "name": ad["name"], "group_name": group["name"]}
                    )
                continue
            if validate_material:
                material = handoff_assignment.material_snapshot(
                    conn, org, brand, campaign_id, ad, validate=True
                )
            ads.append(
                {
                    **{
                        key: ad.get(key)
                        for key in (
                            "id",
                            "name",
                            "external_id",
                            "asset_ready",
                            "copy_text",
                            "image_prompt_text",
                        )
                    },
                    "material_assignment": material,
                }
            )
        result["groups"].append(
            {
                **{
                    key: group.get(key)
                    for key in (
                        "id",
                        "name",
                        "daily_budget",
                        "start_date",
                        "end_date",
                        "external_id",
                    )
                },
                "ads": ads,
            }
        )
    result["manual_settings"] = [
        {
            "id": group["id"],
            "values": {k: v for k, v in group["values"].items() if k in _PLAN_SETTING_KEYS},
        }
        for group in manual_settings.handoff(campaign)["groups"]
    ]
    # F29 Contract I: the launch settings are part of the frozen launch content (an edit after
    # approval makes the launch stale). Never a platform read here.
    result["launch_settings"] = launch_settings.effective(conn, org, brand, campaign)
    # Workbench outputs were frozen for ads without an assigned material; such an ad is never in
    # a batch now (F30 Unresolved 1), so none remain. The key stays for the snapshot's shape.
    result["outputs"] = []
    return result


def _launch_item(conn, org, brand, campaign_id, frozen):
    daily = campaigns.group_budget_total(conn, org, brand, campaign_id)
    return {
        "id": db.new_id("adx"),
        "kind": "launch",
        "target_id": campaign_id,
        "target": {"id": campaign_id, "native_kind": "campaign", "name": frozen["name"]},
        "before": {},
        "after": {
            "daily_amount": daily,
            "start_date": frozen["start_date"],
            "end_date": frozen["end_date"],
        },
        "reason": "核准此計畫的人工上架交接；尚未在平台建立或發布。",
        "context": data.context(frozen),
    }


def _approve_set(
    conn, org, brand, campaign_id, actor, operation_id, request_hash, frozen, *, title, extra=None
):
    """Freeze `frozen` as one approved launch set: month-budget preflight, approval, the
    `publish` action and its handoff items. The caller owns the lock and the transaction."""
    content_hash = data.digest(frozen)
    item = _launch_item(conn, org, brand, campaign_id, frozen)
    daily = item["after"]["daily_amount"]
    month_budget.preflight(conn, org, brand, frozen["month"], [item])
    _materialize_settings(conn, org, brand, campaign_id, frozen, actor)
    set_id = db.new_id("acs")
    conn.execute(
        "INSERT INTO ads_change_set(id,org_id,brand_id,campaign_id,operation_id,"
        "request_hash,content_hash,title,month,plan_json,created_by) "
        "VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
        (
            set_id,
            org,
            brand,
            campaign_id,
            operation_id,
            request_hash,
            content_hash,
            title,
            frozen["month"],
            db.jsonb({"items": [item], "launch_snapshot": frozen, **(extra or {})}),
            actor,
        ),
    )
    detail = campaigns.campaign_detail(conn, org, brand, campaign_id)
    assert detail is not None
    approval_id = approval.approve(
        conn,
        org_id=org,
        brand_id=brand,
        scope_type=plan.APPROVAL_SCOPE_TYPE,
        scope_ref=campaign_id,
        content_hash=content_hash,
        amount=detail["budget_total"] or daily,
        max_daily_amount=daily,
        actor=actor,
        commit=False,
    )
    change_control._insert_actions(
        conn,
        org,
        brand,
        campaign_id,
        {
            "id": set_id,
            "month": frozen["month"],
            "items": [item],
            "operation_id": operation_id,
            "content_hash": content_hash,
        },
        actor,
    )
    conn.execute(
        "UPDATE ads_change_set SET status='approved',approval_id=%s,approved_at=now() WHERE id=%s",
        (approval_id, set_id),
    )
    from app.ads import handoff_data

    handoff_data.install_launch(conn, org, brand, campaign_id, set_id, item["id"], frozen)
    return set_id, item


def _refuse_no_ready_ads(frozen):
    """409 `launch_no_ready_ads`: a campaign and its ad sets alone are not a launch (F30)."""
    if not any(
        ready_material(ad.get("material_assignment"))
        for group in frozen["groups"]
        for ad in group.get("ads") or []
    ):
        raise ValueError("launch_no_ready_ads")


def _refuse_invalid_settings(conn, org, brand, campaign_id, frozen):
    """409 `launch_settings_invalid` while the frozen launch settings carry an error (Contract I).
    The pixel check uses the campaign's cached pixel list: approval never waits on a platform."""
    campaign = campaigns.get_campaign(conn, org, brand, campaign_id) or {}
    if launch_settings.errors(frozen["launch_settings"], launch_settings.cached_pixels(campaign)):
        raise ValueError("launch_settings_invalid")


def _materialize_settings(conn, org, brand, campaign_id, frozen, actor):
    """An approval that froze the recommendation stores it as the saved settings, so a later
    change of what would be recommended (pixel list, result kind) never makes it stale."""
    campaign = campaigns.get_campaign(conn, org, brand, campaign_id) or {}
    if not launch_settings.is_saved(campaign):
        launch_settings.write_values(
            conn, org, brand, campaign_id, frozen["launch_settings"], actor
        )


def publish(conn, org, brand, campaign_id, actor, operation_id, expected_hash):
    if not operation_id or not expected_hash:
        raise ValueError("請重新檢視手動交接內容，再核准這次操作。")
    data.operation(operation_id)
    try:
        data.lock(conn, org, brand)
        request_hash = data.digest(
            {"campaign_id": campaign_id, "content_hash": expected_hash, "kind": "launch"}
        )
        prior = conn.execute(
            "SELECT id,campaign_id,request_hash FROM ads_change_set WHERE "
            "org_id=%s AND brand_id=%s AND operation_id=%s",
            (org, brand, operation_id),
        ).fetchone()
        if prior:
            if prior["request_hash"] != request_hash or prior["campaign_id"] != campaign_id:
                raise ValueError("同一次操作的內容已改變，請重新檢視。")
            conn.commit()
            return {"ok": True, "change_set_id": prior["id"]}
        frozen = snapshot(conn, org, brand, campaign_id, validate_material=True)
        _refuse_invalid_settings(conn, org, brand, campaign_id, frozen)
        _refuse_no_ready_ads(frozen)
        content_hash = data.digest(frozen)
        if expected_hash != content_hash:
            raise ValueError("計畫、素材或月份已改變，請重新檢視後核准。")
        if conn.execute(
            "SELECT id FROM ads_action WHERE org_id=%s AND brand_id=%s "
            "AND campaign_id=%s AND kind='publish' AND change_set_id IS NOT NULL "
            "AND verification_state IN ('pending','reported','unknown') LIMIT 1",
            (org, brand, campaign_id),
        ).fetchone():
            raise ValueError("此計畫已有人工上架清單待核對，請先處理原清單。")
        set_id, _ = _approve_set(
            conn,
            org,
            brand,
            campaign_id,
            actor,
            operation_id,
            request_hash,
            frozen,
            title="首次投放人工交接",
        )
        conn.commit()
        return {"ok": True, "change_set_id": set_id}
    except Exception:
        conn.rollback()
        raise


# -- stale launch (F28 contract "Stale launch", ads.md §6.32) -------------------------------------
# An approved launch whose plan changed afterwards: show approved vs now, then either re-approve
# the current plan as the next version or write the approved values back. Neither touches a
# platform.

_CAMPAIGN_FIELDS = (
    ("name", "活動名稱"),
    ("goal_text", "活動目的"),
    ("objective", "活動目標"),
    ("start_date", "開始日期"),
    ("end_date", "結束日期"),
    ("budget_planned", "總預算"),
    ("channel", "投放平台"),
    ("month", "執行月份"),
)
_GROUP_FIELDS = (
    ("name", "投放組名稱"),
    ("daily_budget", "每日預算"),
    ("start_date", "開始日期"),
    ("end_date", "結束日期"),
)
_AD_FIELDS = (
    ("name", "廣告名稱"),
    ("asset_ready", "素材就位"),
    ("copy_text", "文案"),
    ("image_prompt_text", "圖片提示詞"),
)
_SETTING_LABELS = {f["key"]: f["label"] for f in manual_settings.FIELDS}
# Plan columns a revert may write back, per node kind (fixed names, never user input).
_WRITABLE = {
    "campaign": ("name", "goal_text", "objective", "start_date", "end_date", "budget_planned"),
    "group": ("name", "daily_budget", "start_date", "end_date"),
    "ad": ("name",),
}
_TABLES = {"campaign": "ads_campaign", "group": "ads_delivery_group", "ad": "ads_ad"}
_REAPPROVE_HINT = "請用現在的方案重新核准。"


def _canonical(value):
    if isinstance(value, dict):
        return {k: _canonical(v) for k, v in value.items() if k != "external_id"}
    if isinstance(value, list):
        return [_canonical(v) for v in value]
    return value


def normalized(value):
    """The comparable form of a launch snapshot: JSON values (dates as ISO text, numbers as
    floats), platform bindings (`external_id`) and post-build record fields left out -- so an
    approved snapshot read back from `plan_json` equals a fresh one of the same plan."""
    result = json.loads(json.dumps(_canonical(value), default=to_json_value))
    if isinstance(result, dict):
        for record in result.get("manual_settings") or []:
            values = record.get("values") or {}
            record["values"] = {k: v for k, v in values.items() if k in _PLAN_SETTING_KEYS}
    return result


def launch_set(conn, org, brand, campaign_id):
    """The campaign's current approved launch set (the latest), or None."""
    row = conn.execute(
        "SELECT * FROM ads_change_set WHERE org_id=%s AND brand_id=%s AND campaign_id=%s "
        "AND status='approved' AND plan_json ? 'launch_snapshot' "
        "ORDER BY approved_at DESC,id DESC LIMIT 1",
        (org, brand, campaign_id),
    ).fetchone()
    return dict(row) if row else None


def _material_label(value):
    if not value:
        return None
    text = f"{value.get('filename') or '素材'}・第 {value.get('placement_revision')} 版"
    if value.get("assignment_status") == "confirmed":
        return text
    return text + "（已修訂或未確認，需重新指派素材）"


def _outputs(value):
    found = {}
    for output in value.get("outputs") or []:
        found.setdefault(output.get("ad_id"), []).append(
            (output.get("part"), output.get("id"), output.get("text"))
        )
    return {k: sorted(v, key=str) for k, v in found.items()}


def _rows(original, current):
    """Field-level differences between two normalized snapshots. `planned_id` is internal."""
    rows = []

    def add(kind, planned_id, name, field, label, before, after):
        rows.append(
            {
                "kind": kind,
                "planned_id": planned_id,
                "name": name,
                "field": field,
                "field_label": label,
                "before": before,
                "after": after,
            }
        )

    name = current.get("name") or original.get("name")
    for key, label in _CAMPAIGN_FIELDS:
        if original.get(key) != current.get(key):
            add(
                "campaign",
                original.get("id"),
                name,
                key,
                label,
                original.get(key),
                current.get(key),
            )
    settings_before = original.get("launch_settings") or {}
    settings_after = current.get("launch_settings") or {}
    for key in launch_settings.KEYS:
        if settings_before.get(key) != settings_after.get(key):
            add(
                "campaign",
                original.get("id"),
                name,
                "launch_settings." + key,
                launch_settings.KEY_LABELS[key],
                launch_settings.value_label(key, original.get("launch_settings")),
                launch_settings.value_label(key, current.get("launch_settings")),
            )
    old_groups = {g["id"]: g for g in original.get("groups") or []}
    new_groups = {g["id"]: g for g in current.get("groups") or []}
    old_manual = {m["id"]: m.get("values") or {} for m in original.get("manual_settings") or []}
    new_manual = {m["id"]: m.get("values") or {} for m in current.get("manual_settings") or []}
    old_outputs, new_outputs = _outputs(original), _outputs(current)
    setting_keys = [f["key"] for f in manual_settings.FIELDS if f["key"] in _PLAN_SETTING_KEYS]
    for group_id in [*old_groups, *(g for g in new_groups if g not in old_groups)]:
        before, after = old_groups.get(group_id), new_groups.get(group_id)
        if before is None or after is None:
            present = after or before or {}
            add(
                "group",
                group_id,
                present.get("name"),
                "presence",
                "新增投放組" if before is None else "移除投放組",
                before and before.get("name"),
                after and after.get("name"),
            )
        else:
            for key, label in _GROUP_FIELDS:
                if before.get(key) != after.get(key):
                    add(
                        "group",
                        group_id,
                        after.get("name"),
                        key,
                        label,
                        before.get(key),
                        after.get(key),
                    )
            values_before = old_manual.get(group_id, {})
            values_after = new_manual.get(group_id, {})
            for key in setting_keys:
                if values_before.get(key) != values_after.get(key):
                    add(
                        "group",
                        group_id,
                        after.get("name"),
                        "manual_settings." + key,
                        _SETTING_LABELS[key],
                        values_before.get(key),
                        values_after.get(key),
                    )
        old_ads = {a["id"]: a for a in (before or {}).get("ads") or []}
        new_ads = {a["id"]: a for a in (after or {}).get("ads") or []}
        for ad_id in [*old_ads, *(a for a in new_ads if a not in old_ads)]:
            ad_before, ad_after = old_ads.get(ad_id), new_ads.get(ad_id)
            if ad_before is None or ad_after is None:
                present = ad_after or ad_before or {}
                add(
                    "ad",
                    ad_id,
                    present.get("name"),
                    "presence",
                    "新增廣告" if ad_before is None else "移除廣告",
                    ad_before and ad_before.get("name"),
                    ad_after and ad_after.get("name"),
                )
                continue
            ad_name = ad_after.get("name")
            text_changed = False
            for key, label in _AD_FIELDS:
                if ad_before.get(key) != ad_after.get(key):
                    text_changed = text_changed or key in {"copy_text", "image_prompt_text"}
                    add("ad", ad_id, ad_name, key, label, ad_before.get(key), ad_after.get(key))
            material_before = ad_before.get("material_assignment")
            material_after = ad_after.get("material_assignment")
            if material_before != material_after:
                add(
                    "ad",
                    ad_id,
                    ad_name,
                    "material",
                    "素材",
                    _material_label(material_before),
                    _material_label(material_after),
                )
            if not text_changed and old_outputs.get(ad_id) != new_outputs.get(ad_id):
                add(
                    "ad",
                    ad_id,
                    ad_name,
                    "adopted_output",
                    "採用的工作檯版本",
                    "核准時採用的版本",
                    "已改採其他版本",
                )
    if not rows:
        # Every snapshot key is diffed above; still never call a plan that compares different
        # "unchanged".
        add("campaign", original.get("id"), name, "other", "其他交接內容", None, None)
    return rows


def _blocker(conn, org, brand, campaign_id, row, original):
    """Why this diffed value cannot be written back exactly, or None when it can."""
    kind, field = row["kind"], row["field"]
    if field == "presence":
        return "核准後新增或移除了投放組或廣告，無法自動改回；" + _REAPPROVE_HINT
    if field == "month":
        return (
            f"執行月份已從 {row['before']} 換成 {row['after']}，核准時的月份無法改回；"
            + _REAPPROVE_HINT
        )
    if (
        field in _WRITABLE.get(kind, ())
        or field.startswith("manual_settings.")
        or field.startswith("launch_settings.")
    ):
        return None
    if kind == "ad" and field == "material":
        ad = next(
            (
                a
                for g in original.get("groups") or []
                for a in g.get("ads") or []
                if a["id"] == row["planned_id"]
            ),
            {},
        )
        approved = ad.get("material_assignment")
        if not approved:
            return None
        try:
            restored = handoff_assignment.material_snapshot(
                conn,
                org,
                brand,
                campaign_id,
                {
                    "material_placement_id": approved.get("placement_id"),
                    "material_placement_revision": approved.get("placement_revision"),
                },
            )
        except ValueError:
            restored = None
        if restored is None or normalized(restored) != approved:
            return "核准時的素材版本已修訂或不存在，無法改回；" + _REAPPROVE_HINT
        return None
    if kind == "ad" and field in {"copy_text", "image_prompt_text", "adopted_output"}:
        return (
            "文案或圖片提示詞是在素材工作檯採用的版本，無法從這裡改回；"
            "請到素材工作檯改回，或用現在的方案重新核准。"
        )
    return f"「{row['field_label']}」無法從這裡改回；" + _REAPPROVE_HINT


def _changed_at(conn, org, brand, campaign_id, rows, approved_at):
    """Latest update time of the changed plan rows after the approval, when one is known."""
    wanted = {"group": set(), "ad": set()}
    stamps = []
    if any(r["kind"] == "campaign" or r["field"].startswith("manual_settings.") for r in rows):
        found = conn.execute(
            "SELECT updated_at FROM ads_campaign WHERE org_id=%s AND brand_id=%s AND id=%s",
            (org, brand, campaign_id),
        ).fetchone()
        stamps.append(found["updated_at"] if found else None)
    for row in rows:
        if row["kind"] in wanted and not row["field"].startswith("manual_settings."):
            wanted[row["kind"]].add(row["planned_id"])
    for kind, ids in wanted.items():
        if ids:
            stamps.extend(
                r["updated_at"]
                for r in conn.execute(
                    f"SELECT updated_at FROM {_TABLES[kind]} WHERE org_id=%s AND brand_id=%s "
                    "AND campaign_id=%s AND id=ANY(%s)",
                    (org, brand, campaign_id, list(ids)),
                ).fetchall()
            )
    later = [s for s in stamps if s is not None and approved_at is not None and s > approved_at]
    return max(later) if later else None


def _comparable(original, current):
    """Both snapshots normalized. A launch approved before launch settings existed (F29) froze
    none, so they are not compared for it -- it never goes stale merely by being old."""
    original, current = normalized(original), normalized(current)
    if isinstance(original, dict) and isinstance(current, dict):
        if "launch_settings" not in original:
            current.pop("launch_settings", None)
    return original, current


def approved_matches(original, current) -> bool:
    """The comparison `GET …/handoff` reports as `launch_stale`, for a readback's own check."""
    before, now = _comparable(original, current)
    return before == now


def _compare(change_set, frozen):
    original, current = _comparable(change_set["plan_json"]["launch_snapshot"], frozen)
    if original == current:
        return original, None
    return original, _rows(original, current)


def is_stale(conn, org, brand, campaign_id):
    """True when the current approved launch no longer matches the plan."""
    change_set = launch_set(conn, org, brand, campaign_id)
    if change_set is None:
        return False
    return _compare(change_set, snapshot(conn, org, brand, campaign_id))[1] is not None


def material_frozen(conn, org, brand, campaign_id, ad_id) -> bool:
    """True when the current approved launch froze this planned ad's material and the plan has
    not changed since -- the only case a material assignment must be refused. An ad deferred
    from the batch (F30 Unresolved 1) is not frozen: it gets its material, the launch goes stale,
    and the re-approval is the later version that takes it out."""
    change_set = launch_set(conn, org, brand, campaign_id)
    if change_set is None:
        return False
    frozen_ids = {
        ad["id"]
        for group in change_set["plan_json"]["launch_snapshot"].get("groups") or []
        for ad in group.get("ads") or []
    }
    return ad_id in frozen_ids and not is_stale(conn, org, brand, campaign_id)


def stale(conn, org, brand, campaign_id, *, current=None):
    """`launch_stale` of `GET …/handoff`, computed on read; None while the approved launch still
    matches the plan (or there is no approved launch). `current` is the plan's snapshot when the
    caller already built it."""
    change_set = launch_set(conn, org, brand, campaign_id)
    if change_set is None:
        return None
    frozen = current if current is not None else snapshot(conn, org, brand, campaign_id)
    original, rows = _compare(change_set, frozen)
    if rows is None:
        return None
    items = {
        (r["planned_kind"], r["planned_id"]): r["id"]
        for r in conn.execute(
            "SELECT id,planned_kind,planned_id FROM ads_handoff_item WHERE org_id=%s "
            "AND brand_id=%s AND campaign_id=%s AND change_set_id=%s",
            (org, brand, campaign_id, change_set["id"]),
        ).fetchall()
    }
    changed = {(r["kind"], r["planned_id"]) for r in rows}
    blocker = next(
        (
            reason
            for reason in (_blocker(conn, org, brand, campaign_id, r, original) for r in rows)
            if reason
        ),
        None,
    )
    return {
        "change_set_id": change_set["id"],
        "approved_at": change_set["approved_at"],
        "changed_at": _changed_at(conn, org, brand, campaign_id, rows, change_set["approved_at"]),
        "content_hash": data.digest(frozen),
        "diff": [
            {
                "kind": r["kind"],
                "item_id": items.get((r["kind"], r["planned_id"])),
                **{k: r[k] for k in ("name", "field", "field_label", "before", "after")},
            }
            for r in rows
        ],
        "unchanged_count": sum(1 for key in items if key not in changed),
        "revertible": blocker is None,
        "revert_blocker": blocker,
    }


def _lock_campaign(conn, org, brand, campaign_id):
    # The same row lock `manual_settings.save` takes, so a settings save cannot interleave.
    if not conn.execute(
        "SELECT id FROM ads_campaign WHERE org_id=%s AND brand_id=%s AND id=%s FOR UPDATE",
        (org, brand, campaign_id),
    ).fetchone():
        raise ValueError("找不到此品牌的活動。")


def _current_launch(conn, org, brand, campaign_id, set_id):
    change_set = launch_set(conn, org, brand, campaign_id)
    if change_set is None or change_set["id"] != set_id:
        raise ValueError("這份上架清單已不是目前核准的版本，請重新載入。")
    return change_set


def _hash(value):
    if not isinstance(value, str) or len(value) != 64 or set(value) - set("0123456789abcdef"):
        raise ValueError("請重新檢視交接內容，再決定。")
    return value


def reapprove(conn, org, brand, campaign_id, set_id, expected_hash, actor):
    """Approve the current plan as the next launch version and supersede `set_id`. Unchanged,
    verified handoff items keep their result (`handoff_data.carry_launch`)."""
    expected_hash = _hash(expected_hash)
    if not isinstance(set_id, str):
        raise ValueError("請重新載入上架清單。")
    operation_id = data.operation(f"reapprove:{set_id}:{expected_hash[:32]}")
    request_hash = data.digest(
        {
            "campaign_id": campaign_id,
            "content_hash": expected_hash,
            "kind": "launch_reapprove",
            "supersedes_id": set_id,
        }
    )
    try:
        data.lock(conn, org, brand)
        _lock_campaign(conn, org, brand, campaign_id)
        prior = conn.execute(
            "SELECT id,campaign_id,request_hash FROM ads_change_set WHERE "
            "org_id=%s AND brand_id=%s AND operation_id=%s",
            (org, brand, operation_id),
        ).fetchone()
        if prior:
            if prior["request_hash"] != request_hash or prior["campaign_id"] != campaign_id:
                raise ValueError("同一次操作的內容已改變，請重新檢視。")
            conn.commit()
            return {"ok": True, "change_set_id": prior["id"]}
        old = _current_launch(conn, org, brand, campaign_id, set_id)
        frozen = snapshot(conn, org, brand, campaign_id, validate_material=True)
        _refuse_invalid_settings(conn, org, brand, campaign_id, frozen)
        _refuse_no_ready_ads(frozen)
        if data.digest(frozen) != expected_hash:
            raise ValueError("計畫、素材或月份已改變，請重新檢視後核准。")
        if _compare(old, frozen)[1] is None:
            raise ValueError("核准後方案沒有改變，不需要重新核准。")
        # Superseded first, so the month-budget preflight no longer counts the old launch.
        conn.execute(
            "UPDATE ads_change_set SET status='superseded' WHERE org_id=%s AND brand_id=%s "
            "AND campaign_id=%s AND id=%s",
            (org, brand, campaign_id, set_id),
        )
        version = int(old["plan_json"].get("version") or 1) + 1
        new_id, item = _approve_set(
            conn,
            org,
            brand,
            campaign_id,
            actor,
            operation_id,
            request_hash,
            frozen,
            title=f"首次投放人工交接（第 {version} 版）",
            extra={"supersedes_id": set_id, "version": version},
        )
        # The supersede pattern of `change_control.create`: the old action keeps its row and
        # evidence; an unfinished one is marked stale and points at its successor.
        conn.execute(
            "UPDATE ads_action SET verification_state=CASE WHEN verification_state='confirmed' "
            "THEN verification_state ELSE 'stale' END,evidence_json=evidence_json || %s::jsonb "
            "WHERE org_id=%s AND brand_id=%s AND campaign_id=%s AND change_set_id=%s",
            (
                db.jsonb(
                    {
                        "superseded_by": new_id,
                        "superseded_message": "改由重新核准的上架清單交接；原核對結果與證據保留。",
                    }
                ),
                org,
                brand,
                campaign_id,
                set_id,
            ),
        )
        from app.ads import handoff_data

        handoff_data.carry_launch(conn, org, brand, campaign_id, set_id, new_id, item["id"])
        conn.commit()
        return {"ok": True, "change_set_id": new_id}
    except Exception:
        conn.rollback()
        raise


def _restore(conn, org, brand, campaign_id, original, rows, actor):
    groups = {g["id"]: g for g in original.get("groups") or []}
    ads = {a["id"]: a for g in groups.values() for a in g.get("ads") or []}
    manual = {m["id"]: m.get("values") or {} for m in original.get("manual_settings") or []}
    updates, setting_groups, restore_settings = {}, set(), False
    for row in rows:
        kind, planned_id, field = row["kind"], row["planned_id"], row["field"]
        if field.startswith("manual_settings."):
            setting_groups.add(planned_id)
            continue
        if field.startswith("launch_settings."):
            restore_settings = True
            continue
        sources = {"campaign": original, "group": groups.get(planned_id), "ad": ads.get(planned_id)}
        source = sources[kind] or {}
        values = updates.setdefault((kind, planned_id), {})
        if field == "material":
            material = source.get("material_assignment") or {}
            values["material_placement_id"] = material.get("placement_id")
            values["material_placement_revision"] = material.get("placement_revision")
        else:
            values[field] = source.get(field)
    for (kind, planned_id), values in updates.items():
        # Column names come from `_WRITABLE` or the material pair only (`_blocker` refused the
        # rest before this runs).
        assignments = ",".join(f"{column}=%s" for column in values)
        conn.execute(
            f"UPDATE {_TABLES[kind]} SET {assignments},updated_at=now() "
            "WHERE org_id=%s AND brand_id=%s AND id=%s",
            (*values.values(), org, brand, planned_id),
        )
    if setting_groups:
        found = conn.execute(
            "SELECT context_json FROM ads_campaign WHERE org_id=%s AND brand_id=%s AND id=%s",
            (org, brand, campaign_id),
        ).fetchone()
        context = dict((found or {}).get("context_json") or {})
        records = dict(context.get("manual_delivery") or {})
        for group_id in setting_groups:
            record = dict(records.get(group_id) or {})
            kept = {
                k: v for k, v in (record.get("values") or {}).items() if k not in _PLAN_SETTING_KEYS
            }
            record.update(
                values={**kept, **manual.get(group_id, {})},
                saved_at=db.now_utc().isoformat(),
                saved_by=actor,
            )
            records[group_id] = record
        context["manual_delivery"] = records
        conn.execute(
            "UPDATE ads_campaign SET context_json=%s,updated_at=now() "
            "WHERE org_id=%s AND brand_id=%s AND id=%s",
            (db.jsonb(context), org, brand, campaign_id),
        )
    if restore_settings:
        launch_settings.write_values(
            conn, org, brand, campaign_id, original["launch_settings"], actor
        )


def revert(conn, org, brand, campaign_id, set_id, expected_hash, actor):
    """Write the approved values of every diffed field back to the plan rows in one
    transaction; the original approval stands. Refuses, naming the reason, when any value
    cannot be restored exactly."""
    expected_hash = _hash(expected_hash)
    try:
        data.lock(conn, org, brand)
        _lock_campaign(conn, org, brand, campaign_id)
        change_set = _current_launch(conn, org, brand, campaign_id, set_id)
        frozen = snapshot(conn, org, brand, campaign_id)
        if data.digest(frozen) != expected_hash:
            raise ValueError("計畫在你檢視後又改過，請重新載入再決定。")
        original, rows = _compare(change_set, frozen)
        if rows is None:
            raise ValueError("核准後方案沒有改變，不需要改回。")
        for row in rows:
            reason = _blocker(conn, org, brand, campaign_id, row, original)
            if reason:
                raise ValueError(reason)
        _restore(conn, org, brand, campaign_id, original, rows, actor)
        if not approved_matches(
            change_set["plan_json"]["launch_snapshot"], snapshot(conn, org, brand, campaign_id)
        ):
            raise ValueError("改回後仍與核准內容不同，已取消；" + _REAPPROVE_HINT)
        # Items a readback marked stale because of this change go back to waiting for a check.
        conn.execute(
            "UPDATE ads_handoff_item SET status='pending',"
            "evidence_json=evidence_json || %s::jsonb,updated_at=now() "
            "WHERE org_id=%s AND brand_id=%s AND campaign_id=%s AND change_set_id=%s "
            "AND status='stale'",
            (
                db.jsonb({"message": "已改回核准時的設定，請重新核對這一項。"}),
                org,
                brand,
                campaign_id,
                set_id,
            ),
        )
        write_audit(
            conn,
            org_id=org,
            brand_id=brand,
            entity_type="ads_change_set",
            entity_id=set_id,
            action="revert_plan",
            actor=actor,
            before={f"{r['kind']}:{r['planned_id']}:{r['field']}": r["after"] for r in rows},
            after={f"{r['kind']}:{r['planned_id']}:{r['field']}": r["before"] for r in rows},
        )
        conn.commit()
        return {"ok": True, "change_set_id": set_id}
    except Exception:
        conn.rollback()
        raise
