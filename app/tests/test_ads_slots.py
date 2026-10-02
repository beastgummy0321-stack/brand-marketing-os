"""F30-I10 Contract F: the assets tab's slots and uploading a file into one planned ad's slot.

Readiness is the launch snapshot's rule (a confirmed assignment), a file uploaded into a slot
waits until its placement is confirmed and is then assigned to that planned ad, a launched
app-built ad carries its platform ad and that ad's replace request, an imported campaign's slots
are its live platform ads, and the open replace requests are listed with their own state.

F35 Contract T: each planned slot carries its copy half (`copy`) and `workbench_href`; a file
uploaded into a slot carries the ad's selected workbench copy in, fills the purpose with the
ad's name, confirms and assigns in the same call; a slot with a file but no copy takes one of
the brand's workbench copy versions through `POST …/slots/{ad}/copy`.

F44-I03: the confirmation judges a slot's copy against the ad's sell-way and offer coordinate
(real brand rows, the real `validate_claims`), a library placement against the campaign's
sell-way; a refusal carries Contract C details beside its sentences.

F44-I04 Contract D: a slot whose confirmation was refused keeps the refusal's details and reads
`blocked` with the first reason and its exit; a clean copy version or `POST …/slots/{ad}/recheck`
after the cause is removed makes it ready; every slot carries `blocked` and `offer_label`.

F45 Contract W (ads.md §6.49): `in_progress` only while a job for the slot runs (`job`), else
`waiting` with the user's next action; every confirmation path stores its refusal, and an edit of
the placement behind a slot (placement PATCH, copy pick, typed copy edit) is checked at once.
"""

from datetime import timedelta
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app import workbench
from app.ads import (
    asset_suggestions,
    change_control_data,
    change_control_launch,
    external_repository,
    handoff_assignment,
    material_tasks,
    slots,
)
from app.ads import (
    assets as legacy_assets,
)
from app.ads import repository as campaigns
from app.ads import user_assets_repository as user_assets
from app.brand_intelligence import repository as brands
from app.core import db, settings
from app.main import app

COPY = {"headline": "標題", "body": "文案", "description": "說明"}
WORKBENCH_COPY = {"headline": "晨光標題", "body": "工作檯寫的內文", "description": "工作檯說明"}


def placement_copy(label, fields=None):
    return {"source": "placement", "label": label, **(fields or COPY)}


@pytest.fixture
def env():
    conn, org = db.current(), db.DEV_ORG_ID
    brand = brands.create_brand(
        conn, org_id=org, name="素材格子品牌", actor="test", client_name=None
    )["id"]
    today = settings.today_for_org(conn, org_id=org)
    campaign = campaigns.create_campaign(
        conn,
        org,
        brand,
        {
            "name": "秋季上架",
            "goal_text": "檢驗訊息",
            "objective": "awareness",
            "start_date": today,
            "end_date": today + timedelta(days=7),
        },
        created_by="test",
    )["id"]
    group = db.new_id("adg")
    conn.execute(
        "INSERT INTO ads_delivery_group(id,org_id,brand_id,campaign_id,channel_key,"
        "name,daily_budget,role) VALUES(%s,%s,%s,%s,%s,%s,500,'new')",
        (group, org, brand, campaign, "fixture", "新客廣告組"),
    )
    ads = []
    for name in ("晨光隨行杯・日常出發", "通勤情境單圖", "辦公室一角"):
        ad = db.new_id("ada")
        # clock_timestamp: one transaction's now() ties created_at, and ids minted in the same
        # millisecond are not ordered -- the slots follow (created_at, id).
        conn.execute(
            "INSERT INTO ads_ad(id,org_id,brand_id,campaign_id,group_id,name,created_at) "
            "VALUES(%s,%s,%s,%s,%s,%s,clock_timestamp())",
            (ad, org, brand, campaign, group, name),
        )
        ads.append(ad)
    conn.commit()
    # The workbench's copy versions are faked through its public facade (the way
    # test_ads_live_creative does): `slots.workbench` is the `app.workbench` module, so every
    # caller sees the patch. `briefs_for_source` / `set_action_url` stay real -- the pack is
    # really dispatched, so the ad->set link and the studio URL are real.
    versions: dict = {}  # brief id -> {"id", "copy", "adopted", "name"}

    def adopted_output(conn, org_id, brand_id, brief_id, part):
        row = versions.get(brief_id)
        if row is None or part != "copy":
            return None
        return {
            "id": row["id"], "brief_id": brief_id, "part": "copy", "generation_round": 1,
            "version_index": 1, "is_adopted": row["adopted"],
            "adopted_at": db.now_utc() if row["adopted"] else None,
            "body_json": {"sets": [row["copy"]]},
        }

    def material_source(conn, org_id, brand_id, set_id, version_id, card_index=None):
        row = versions.get(set_id)
        if row is None or row["id"] != version_id:
            raise ValueError("找不到此品牌的提示詞或文案版本。")
        return {
            "source": "workbench", "set_id": set_id, "version_id": version_id,
            "card_index": None, "part": "copy", "pack_id": None,
            "text": "\n".join(row["copy"].values()), "copy_fields": dict(row["copy"]),
        }

    def material_options(conn, org_id, brand_id, *, part=None):
        return [
            {
                "set_id": set_id, "version_id": row["id"], "part": "copy", "card_index": None,
                "label": f"{row['name']} · 版本 1", "text": "\n".join(row["copy"].values()),
                "copy_fields": dict(row["copy"]),
            }
            for set_id, row in versions.items()
            if row["adopted"] and part in (None, "copy")
        ]

    patchers = [
        patch.object(workbench, name, side_effect=target)
        for name, target in (
            ("adopted_output", adopted_output),
            ("material_source", material_source),
            ("material_options", material_options),
        )
    ]
    for patcher in patchers:
        patcher.start()
    try:
        yield {
            "conn": conn, "org": org, "brand": brand, "campaign": campaign, "group": group,
            "ads": ads, "today": today, "versions": versions,
        }
    finally:
        for patcher in patchers:
            patcher.stop()


def user_asset(env, *, status="ready", thumbnail=True):
    conn, asset = env["conn"], db.new_id("aua")
    conn.execute(
        "INSERT INTO ads_user_asset(id,org_id,brand_id,sha256,storage_key,filename,"
        "mime_type,byte_size,status,thumbnail_key) "
        "VALUES(%s,%s,%s,%s,%s,'fall.png','image/png',1,%s,%s)",
        (
            asset, env["org"], env["brand"], asset, f"{env['org']}/{asset}", status,
            f"{env['org']}/{asset}/poster.jpg" if thumbnail else None,
        ),
    )
    conn.commit()
    return asset


def assign_confirmed(env, ad, asset):
    conn = env["conn"]
    placement = user_assets.attach(
        conn, env["org"], env["brand"], env["campaign"], asset, COPY, "human"
    )
    conn.execute(
        "UPDATE ads_asset_placement SET confirmed_at=now(),confirmed_by='human' WHERE id=%s",
        (placement["id"],),
    )
    conn.commit()
    handoff_assignment.assign(
        conn, env["org"], env["brand"], env["campaign"], ad, placement["id"], 1
    )
    return placement


def read(env, campaign=None):
    return slots.read(env["conn"], env["org"], env["brand"], campaign or env["campaign"])


def by_ad(view):
    return {s["ad_id"]: s for g in view["groups"] for s in g["slots"]}


def thumb(env, asset):
    return f"/api/ads/brands/{env['brand']}/user-assets/{asset}/thumbnail"


def upload(env, ad, body):
    return slots.upload(
        env["conn"], env["org"], env["brand"], env["campaign"], ad, body, "human"
    )


def launch(env):
    conn = env["conn"]
    frozen = change_control_launch.snapshot(conn, env["org"], env["brand"], env["campaign"])
    with patch.object(
        change_control_launch.month_budget, "preflight", return_value={"can_increase": True}
    ):
        return change_control_launch.publish(
            conn, env["org"], env["brand"], env["campaign"], "human", db.new_id("op"),
            change_control_data.digest(frozen),
        )["change_set_id"]


def platform_entity(env, native_id, *, campaign=None, **extra):
    entity = external_repository.upsert_entity(
        env["conn"],
        env["org"],
        env["brand"],
        campaign or env["campaign"],
        {
            "platform": "fixture",
            "source_account": "acct",
            "native_kind": "ad",
            "native_id": native_id,
            "native_status": "ACTIVE",
            "currency": "TWD",
            "name": "平台廣告 " + native_id,
            **extra,
        },
    )
    env["conn"].commit()
    return entity


def replace(env, entity_id, campaign=None):
    return material_tasks.create(
        env["conn"], env["org"], env["brand"], campaign or env["campaign"],
        {"operation_id": db.new_id("op"), "replaces_entity_id": entity_id}, "test",
    )


def workbench_copy(env, ad, copy=None, *, adopt=True):
    """Dispatch the campaign pack (once), then give this ad's real set one copy version in the
    faked workbench facade (selected unless `adopt=False`) -- the state the workbench leaves
    behind when the user picked a version."""
    conn, org, brand, campaign = env["conn"], env["org"], env["brand"], env["campaign"]
    if legacy_assets.pack_id(conn, org, brand, campaign) is None:
        workbench.register_tasks()
        legacy_assets.dispatch_pack(conn, org, brand, campaign)
        conn.commit()
    brief = workbench.briefs_for_source(
        conn, org, brand, legacy_assets.PACK_SOURCE_KIND,
        {"ads_campaign_id": campaign, "ads_ad_id": ad},
    )[-1]
    version_id = db.new_id("wbo")
    env["versions"][brief["id"]] = {
        "id": version_id, "copy": copy or WORKBENCH_COPY, "adopted": adopt,
        "name": brief.get("name") or "文案",
    }
    return {"set_id": brief["id"], "version_id": version_id}


def base(env):
    return f"/api/ads/brands/{env['brand']}/campaigns/{env['campaign']}"


# -- draft: ready / in progress / missing --------------------------------------------------------


def test_draft_slots_ready_uploaded_and_missing_follow_the_launch_rule(env):
    ready_ad, uploaded_ad, missing_ad = env["ads"]
    ready_asset = user_asset(env)
    assign_confirmed(env, ready_ad, ready_asset)
    waiting_asset = user_asset(env, status="pending", thumbnail=False)
    result = upload(env, uploaded_ad, {"asset_id": waiting_asset, "copy_fields": COPY})

    view = read(env)
    assert result["slots"] == view
    assert (view["ready"], view["total"]) == (1, 3)
    assert [(g["group_id"], g["name"]) for g in view["groups"]] == [(env["group"], "新客廣告組")]
    assert [s["ad_id"] for s in view["groups"][0]["slots"]] == env["ads"]
    slot = by_ad(view)
    assert slot[ready_ad] == {
        "ad_id": ready_ad, "entity_id": None, "name": "晨光隨行杯・日常出發", "state": "ready",
        "thumbnail_url": thumb(env, ready_asset), "confirmed": True, "replace_task_id": None,
        "copy": placement_copy("已確認"), "workbench_href": None, "format_key": None,
        "blocked": None, "offer_label": None, "waiting": None, "job": None,
    }
    # Uploaded, its original still pending: not confirmable yet, so not launchable and not
    # assigned (material stays confirmed-only); the copy half shows what came with the file.
    # Waiting for a preview is not a refusal: `in_progress` (the preview job), never `blocked`.
    assert (slot[uploaded_ad]["state"], slot[uploaded_ad]["blocked"]) == ("in_progress", None)
    assert slot[uploaded_ad]["job"] == {"kind": "preview", "done": None, "of": None}
    assert slot[uploaded_ad]["waiting"] is None
    assert result["placement"]["blocked_reasons"] == []
    assert slot[uploaded_ad]["confirmed"] is False
    assert slot[uploaded_ad]["thumbnail_url"] is None  # its preview is not made yet
    assert slot[uploaded_ad]["copy"] == placement_copy("待確認")
    assert slot[missing_ad]["state"] == "missing"
    assert slot[missing_ad]["thumbnail_url"] is None
    assert (slot[missing_ad]["copy"], slot[missing_ad]["workbench_href"]) == (None, None)
    ad = campaigns.get_ad(env["conn"], env["org"], env["brand"], uploaded_ad)
    assert ad["material_placement_id"] is None
    assert ad["slot_placement_id"] == result["placement"]["id"]
    assert view["requests"] == [] and view["requests_truncated"] is False


def test_pack_being_worked_is_in_progress_but_never_counts_as_ready(env):
    workbench.register_tasks()
    ready_ad = env["ads"][0]
    assign_confirmed(env, ready_ad, user_asset(env))
    legacy_assets.dispatch_pack(env["conn"], env["org"], env["brand"], env["campaign"])

    view = read(env)
    # A freshly dispatched set is queued for generation: its copy job runs (F45 Contract W).
    assert {a: s["state"] for a, s in by_ad(view).items()} == {
        ready_ad: "ready", env["ads"][1]: "in_progress", env["ads"][2]: "in_progress",
    }
    assert by_ad(view)[env["ads"][1]]["job"] == {"kind": "copy", "done": None, "of": None}
    assert view["ready"] == 1


def test_a_revised_assignment_waits_for_the_users_confirmation_not_ready(env):
    """F45 Contract W: nothing runs for a revised assignment -- it waits for the user."""
    ad = env["ads"][0]
    placement = assign_confirmed(env, ad, user_asset(env))
    user_assets.revise(
        env["conn"], env["org"], env["brand"], env["campaign"], placement["id"], 1,
        {"copy_fields": {**COPY, "body": "新版"}}, "human",
    )
    env["conn"].commit()
    slot = by_ad(read(env))[ad]
    assert (slot["state"], slot["job"]) == ("waiting", None)
    assert slot["waiting"] == {"action": "confirm_copy", "text": "等你：確認這版文案"}
    assert slot["copy"] == placement_copy("待確認", {**COPY, "body": "新版"})


# -- upload into a slot ---------------------------------------------------------------------------


def test_upload_waits_for_confirmation_then_assigns_the_confirmed_revision(env):
    """A placement the program cannot confirm (its copy misses a field) waits in the slot,
    `blocked` with that reason (F44); the slot follows the placement id through the user's
    revision -- which starts with no stored reason -- and confirmation."""
    ad = env["ads"][1]
    asset = user_asset(env)
    client = TestClient(app)
    partial = {"headline": "標題", "body": "文案"}

    response = client.post(
        f"{base(env)}/slots/{ad}/upload", json={"asset_id": asset, "copy_fields": partial}
    )
    assert response.status_code == 200, response.text
    placement = response.json()["placement"]
    assert placement["confirmed_at"] is None
    assert placement["purpose"] == "通勤情境單圖"  # filled by the program, not confirmed yet
    slot = by_ad(response.json()["slots"])[ad]
    assert (slot["state"], slot["thumbnail_url"]) == ("blocked", thumb(env, asset))
    assert slot["copy"] == placement_copy("待確認", {**partial, "description": None})
    assert slot["blocked"] == {
        "text": "請补齊標題、內文與說明，或補充可用品牌事實。", "terms": [], "fix": "copy",
        "more": 0,
    }
    assert response.json()["slots"]["ready"] == 0

    # Completing the copy is a new revision behind the slot: checked at once (F45 §6.49), so
    # it is confirmed and assigned by the edit itself.
    revised = client.patch(
        f"{base(env)}/placements/{placement['id']}",
        json={"expected_revision": 1, "copy_fields": COPY},
    )
    assert revised.status_code == 200, revised.text
    assert revised.json()["placement"]["revision"] == 2
    assert revised.json()["placement"]["blocked_reasons"] == []
    assert revised.json()["placement"]["confirmed_at"]

    # The advanced confirm route on an already confirmed revision is a no-op.
    confirmed = client.post(
        f"{base(env)}/placements/{placement['id']}/confirm", json={"expected_revision": 2}
    )
    assert confirmed.status_code == 200, confirmed.text
    assert confirmed.json()["placement"]["confirmed_at"]

    view = client.get(f"{base(env)}/slots").json()
    assert by_ad(view)[ad]["state"] == "ready"
    assert by_ad(view)[ad]["confirmed"] is True
    assert by_ad(view)[ad]["copy"] == placement_copy("已確認")
    assert view["ready"] == 1
    row = campaigns.get_ad(env["conn"], env["org"], env["brand"], ad)
    assert (row["material_placement_id"], row["material_placement_revision"]) == (
        placement["id"], 2,
    )
    assert row["slot_placement_id"] is None
    material = handoff_assignment.material_snapshot(
        env["conn"], env["org"], env["brand"], env["campaign"], row
    )
    assert material["assignment_status"] == "confirmed"


def test_upload_with_full_copy_confirms_and_assigns_in_one_call(env):
    """No workbench set: an explicit complete copy plus the program's purpose is enough."""
    ad = env["ads"][1]
    asset = user_asset(env)
    result = upload(env, ad, {"asset_id": asset, "copy_fields": COPY})
    assert result["placement"]["confirmed_at"]
    assert result["placement"]["purpose"] == "通勤情境單圖"
    assert result["placement"]["status"] == "manual_ready"
    slot = by_ad(result["slots"])[ad]
    assert (slot["state"], slot["confirmed"]) == ("ready", True)
    assert slot["copy"] == placement_copy("已確認")
    row = campaigns.get_ad(env["conn"], env["org"], env["brand"], ad)
    assert row["material_placement_id"] == result["placement"]["id"]
    assert row["slot_placement_id"] is None


# -- F35 Contract T: the copy half ---------------------------------------------------------------


def test_selected_workbench_copy_shows_as_copy_only_and_never_counts_as_ready(env):
    ad = env["ads"][0]
    workbench_copy(env, ad)
    view = read(env)
    slot = by_ad(view)[ad]
    assert slot["state"] == "copy_only"
    assert slot["confirmed"] is False
    assert slot["thumbnail_url"] is None
    assert slot["copy"] == {"source": "workbench", "label": "工作檯第 1 版", **WORKBENCH_COPY}
    assert slot["workbench_href"] and slot["workbench_href"].startswith(
        f"/app/brands/{env['brand']}/workbench/packs/"
    )
    assert view["ready"] == 0
    # The other ads have a set (the pack is being worked) but nothing selected: in_progress.
    others = {a: s for a, s in by_ad(view).items() if a != ad}
    assert {s["state"] for s in others.values()} == {"in_progress"}
    assert all(s["copy"] is None and s["workbench_href"] for s in others.values())


def test_unselected_workbench_version_is_not_the_ads_copy(env):
    ad = env["ads"][0]
    workbench_copy(env, ad, adopt=False)
    slot = by_ad(read(env))[ad]
    assert (slot["state"], slot["copy"]) == ("in_progress", None)


def test_upload_into_a_slot_with_workbench_copy_is_ready_at_once(env):
    ad = env["ads"][0]
    workbench_copy(env, ad)
    asset = user_asset(env)
    client = TestClient(app)
    response = client.post(f"{base(env)}/slots/{ad}/upload", json={"asset_id": asset})
    assert response.status_code == 200, response.text
    placement = response.json()["placement"]
    assert placement["confirmed_at"]
    assert placement["purpose"] == "晨光隨行杯・日常出發"
    assert placement["copy_fields"] == WORKBENCH_COPY
    slot = by_ad(response.json()["slots"])[ad]
    assert (slot["state"], slot["thumbnail_url"]) == ("ready", thumb(env, asset))
    assert slot["copy"] == placement_copy("已確認", WORKBENCH_COPY)
    assert response.json()["slots"]["ready"] == 1
    row = campaigns.get_ad(env["conn"], env["org"], env["brand"], ad)
    assert (row["material_placement_id"], row["material_placement_revision"]) == (
        placement["id"], 1,
    )
    assert row["slot_placement_id"] is None


def test_upload_with_explicit_copy_keeps_it_over_the_workbench_copy(env):
    ad = env["ads"][0]
    workbench_copy(env, ad)
    result = upload(env, ad, {"asset_id": user_asset(env), "copy_fields": COPY})
    assert result["placement"]["copy_fields"] == COPY
    assert result["placement"]["confirmed_at"]
    assert by_ad(result["slots"])[ad]["copy"] == placement_copy("已確認")


def test_upload_by_upload_id_without_copy_carries_the_workbench_copy(env):
    conn, ad = env["conn"], env["ads"][0]
    workbench_copy(env, ad)
    asset = user_asset(env)
    batch = user_assets.create_batch(
        conn, env["org"], env["brand"], [{"filename": "fall.png", "size": 1}], "human"
    )
    upload_id = batch["uploads"][0]["id"]
    conn.execute(
        "UPDATE ads_asset_upload SET status='complete',asset_id=%s WHERE id=%s",
        (asset, upload_id),
    )
    conn.commit()
    result = upload(env, ad, {"upload_id": upload_id})
    assert result["placement"]["copy_fields"] == WORKBENCH_COPY
    assert by_ad(result["slots"])[ad]["state"] == "ready"


def test_image_only_slot_takes_a_workbench_version_through_the_picker(env):
    picked_ad, other_ad = env["ads"][1], env["ads"][2]
    # The brand's copy version lives on another ad's set; `picked_ad` has nothing selected.
    option = workbench_copy(env, other_ad)
    client = TestClient(app)

    listed = client.get(f"{base(env)}/slots/copy-options")
    assert listed.status_code == 200, listed.text
    options = listed.json()["options"]
    assert [(o["set_id"], o["version_id"]) for o in options] == [
        (option["set_id"], option["version_id"])
    ]
    assert options[0]["copy_fields"] == WORKBENCH_COPY
    assert options[0]["label"]

    # No file yet: no picker.
    refused = client.post(f"{base(env)}/slots/{picked_ad}/copy", json=option)
    assert refused.status_code == 409, refused.text
    assert refused.json()["error"] == {
        "code": "slot_no_file", "message": "這一格還沒有圖，先上傳圖再選文案。", "details": None,
    }

    asset = user_asset(env)
    uploaded = client.post(f"{base(env)}/slots/{picked_ad}/upload", json={"asset_id": asset})
    assert uploaded.status_code == 200, uploaded.text
    assert uploaded.json()["placement"]["confirmed_at"] is None
    slot = by_ad(uploaded.json()["slots"])[picked_ad]
    assert (slot["state"], slot["copy"], slot["thumbnail_url"]) == (
        "image_only", None, thumb(env, asset),
    )
    assert slot["confirmed"] is False

    bad_bodies = (
        {"set_id": option["set_id"]}, {**option, "extra": 1}, {"set_id": 1, "version_id": 2},
    )
    for bad in bad_bodies:
        response = client.post(f"{base(env)}/slots/{picked_ad}/copy", json=bad)
        assert response.status_code == 400, response.text
        assert response.json()["error"]["code"] == "slot_copy_invalid"
    unknown = client.post(
        f"{base(env)}/slots/{picked_ad}/copy",
        json={"set_id": option["set_id"], "version_id": "wbo_missing"},
    )
    assert unknown.status_code == 409
    assert unknown.json()["error"]["message"] == "找不到這個文案版本。"

    chosen = client.post(f"{base(env)}/slots/{picked_ad}/copy", json=option)
    assert chosen.status_code == 200, chosen.text
    placement = chosen.json()["placement"]
    assert placement["id"] == uploaded.json()["placement"]["id"]
    assert placement["revision"] == 2
    assert placement["copy_fields"] == WORKBENCH_COPY
    assert placement["purpose"] == "通勤情境單圖"
    assert placement["confirmed_at"]
    slot = by_ad(chosen.json()["slots"])[picked_ad]
    assert (slot["state"], slot["confirmed"]) == ("ready", True)
    assert slot["copy"] == placement_copy("已確認", WORKBENCH_COPY)
    row = campaigns.get_ad(env["conn"], env["org"], env["brand"], picked_ad)
    assert (row["material_placement_id"], row["material_placement_revision"]) == (
        placement["id"], 2,
    )
    assert row["slot_placement_id"] is None
    # Once ready the slot has no picker any more (changing copy = a new workbench version).
    again = client.post(f"{base(env)}/slots/{picked_ad}/copy", json=option)
    assert again.status_code == 409
    assert again.json()["error"]["code"] == "slot_no_file"


def test_copy_options_and_picker_refuse_imported_and_unknown_campaigns(env):
    client = TestClient(app)
    imported = external_repository.create_imported_campaign(
        env["conn"], env["org"], env["brand"], name="既有活動"
    )["id"]
    env["conn"].commit()  # the route reads on its own connection
    prefix = f"/api/ads/brands/{env['brand']}/campaigns"
    assert client.get(f"{prefix}/adc_missing/slots/copy-options").status_code == 404
    assert client.get(f"{prefix}/{imported}/slots/copy-options").status_code == 409
    with pytest.raises(ValueError, match="slot_no_file"):
        slots.choose_copy(
            env["conn"], env["org"], env["brand"], env["campaign"], env["ads"][0],
            {"set_id": "s", "version_id": "v"}, "human",
        )


def test_pending_placement_with_zero_known_budget_is_blocked_with_no_slot_exit(env):
    """The confirmation is refused by `pending_reasons` (a zero platform budget): the slot keeps
    waiting with its copy shown, never ready -- `blocked` with the reason, and `fix: None`
    because neither another copy nor another file fixes a campaign-level reason."""
    conn, ad = env["conn"], env["ads"][0]
    workbench_copy(env, ad)
    conn.execute(
        "UPDATE ads_delivery_group SET daily_budget=0 WHERE id=%s", (env["group"],)
    )
    conn.commit()
    platform_entity(
        env, "root", native_kind="campaign", currency="TWD", budget_type="daily",
        budget_amount=0,
    )
    result = upload(env, ad, {"asset_id": user_asset(env)})
    assert result["placement"]["confirmed_at"] is None
    assert result["placement"]["copy_fields"] == WORKBENCH_COPY
    slot = by_ad(result["slots"])[ad]
    assert (slot["state"], slot["confirmed"]) == ("blocked", False)
    assert slot["copy"] == placement_copy("待確認", WORKBENCH_COPY)
    assert slot["blocked"] == {
        "text": (
            "目前已知預算為零，本件保留必用待安排；請先核對手動上架計畫，不會修改平台預算。"
        ),
        "terms": [], "fix": None, "more": 0,
    }
    assert result["slots"]["ready"] == 0
    row = campaigns.get_ad(conn, env["org"], env["brand"], ad)
    assert row["material_placement_id"] is None
    assert row["slot_placement_id"] == result["placement"]["id"]


def test_upload_by_upload_id_uses_the_placement_path_and_an_already_confirmed_file_assigns(env):
    conn, ad = env["conn"], env["ads"][2]
    asset = user_asset(env)
    batch = user_assets.create_batch(
        conn, env["org"], env["brand"],
        [{"filename": "fall.png", "size": 1, "copy_fields": COPY}], "human",
    )
    upload_id = batch["uploads"][0]["id"]
    conn.execute(
        "UPDATE ads_asset_upload SET status='complete',asset_id=%s WHERE id=%s",
        (asset, upload_id),
    )
    conn.commit()
    # The same file already placed and confirmed in this campaign as a library row (no ad):
    # since F40-I02 the slot upload is keyed by its ad, so it gets its own placement, which the
    # program confirms and assigns at once; the library row stays current and untouched.
    placement = user_assets.attach(
        conn, env["org"], env["brand"], env["campaign"], asset, COPY, "h"
    )
    conn.execute(
        "UPDATE ads_asset_placement SET confirmed_at=now(),confirmed_by='h' WHERE id=%s",
        (placement["id"],),
    )
    conn.commit()

    result = upload(env, ad, {"upload_id": upload_id})
    assert result["placement"]["id"] != placement["id"]
    assert (result["placement"]["ad_id"], result["placement"]["copy_fields"]) == (ad, COPY)
    assert result["placement"]["confirmed_at"]
    assert by_ad(result["slots"])[ad]["state"] == "ready"
    row = campaigns.get_ad(conn, env["org"], env["brand"], ad)
    assert row["material_placement_id"] == result["placement"]["id"]
    assert row["slot_placement_id"] is None
    library = user_assets.placement(
        conn, env["org"], env["brand"], env["campaign"], placement["id"]
    )
    assert (library["ad_id"], library["is_current"], library["revision"]) == (None, True, 1)


# -- F41-I01: the advanced 「將成品指派給計畫中的廣告」 panel places through the slot upload ---


LIBRARY_COPY = {"headline": "舊標題", "body": "素材庫上傳時的舊文案", "description": "舊說明"}


def library_placement(env, asset, copy=None):
    """A finished asset placed in the campaign without an ad and confirmed -- a row of the
    advanced panel's `ready_placements`."""
    placement = user_assets.attach(
        env["conn"], env["org"], env["brand"], env["campaign"], asset, copy or LIBRARY_COPY,
        "librarian",
    )
    env["conn"].execute(
        "UPDATE ads_asset_placement SET confirmed_at=now(),confirmed_by='librarian' WHERE id=%s",
        (placement["id"],),
    )
    env["conn"].commit()
    return placement


def place(env, ad, placement_id):
    return TestClient(app).post(
        f"{base(env)}/slots/{ad}/upload", json={"placement_id": placement_id}
    )


def material(env, ad):
    row = campaigns.get_ad(env["conn"], env["org"], env["brand"], ad)
    return row, handoff_assignment.material_snapshot(
        env["conn"], env["org"], env["brand"], env["campaign"], row
    )


def test_placing_a_finished_asset_carries_the_ads_workbench_copy(env):
    """The ad's selected workbench copy rides in over the library upload's old copy, the way a
    slot upload does; the library row itself stays untouched."""
    ad = env["ads"][0]
    workbench_copy(env, ad)
    asset = user_asset(env)
    library = library_placement(env, asset)

    response = place(env, ad, library["id"])
    assert response.status_code == 200, response.text
    placed = response.json()["placement"]
    assert placed["id"] != library["id"]
    assert (placed["asset_id"], placed["ad_id"], placed["copy_fields"]) == (
        asset, ad, WORKBENCH_COPY,
    )
    assert placed["confirmed_at"]
    row, snapshot = material(env, ad)
    assert row["material_placement_id"] == placed["id"]
    assert snapshot["copy_fields"] == WORKBENCH_COPY
    assert snapshot["assignment_status"] == "confirmed"
    assert by_ad(response.json()["slots"])[ad]["state"] == "ready"
    kept = user_assets.placement(
        env["conn"], env["org"], env["brand"], env["campaign"], library["id"]
    )
    assert (kept["ad_id"], kept["revision"], kept["copy_fields"]) == (None, 1, LIBRARY_COPY)


def test_placing_a_finished_asset_without_workbench_copy_keeps_its_own_copy(env):
    """No selected workbench copy (e.g. the memory queue never made one): the placement's own
    effective copy is the copy, as an upload's own copy is for `{upload_id}`."""
    ad = env["ads"][1]
    library = library_placement(env, user_asset(env))

    response = place(env, ad, library["id"])
    assert response.status_code == 200, response.text
    assert response.json()["placement"]["copy_fields"] == LIBRARY_COPY
    row, snapshot = material(env, ad)
    assert row["material_placement_id"] == response.json()["placement"]["id"]
    assert snapshot["copy_fields"] == LIBRARY_COPY
    assert snapshot["assignment_status"] == "confirmed"


def test_placing_a_finished_asset_explicit_copy_still_wins(env):
    ad = env["ads"][0]
    workbench_copy(env, ad)
    library = library_placement(env, user_asset(env))
    result = upload(env, ad, {"placement_id": library["id"], "copy_fields": COPY})
    assert result["placement"]["copy_fields"] == COPY


def test_placing_a_finished_asset_surfaces_the_slot_uploads_own_refusals(env):
    """One rule set: the advanced panel gets the slot upload's refusals unchanged -- an ad
    already on the platform, and the same file already in this ad with different copy."""
    conn = env["conn"]
    launched_ad, deferred_ad, redone_ad = env["ads"]
    assign_confirmed(env, launched_ad, user_asset(env))
    launch(env)
    entity = platform_entity(env, "n1")
    conn.execute(
        "UPDATE ads_handoff_item SET entity_id=%s WHERE campaign_id=%s AND planned_kind='ad' "
        "AND planned_id=%s",
        (entity["id"], env["campaign"], launched_ad),
    )
    conn.commit()
    upload(env, deferred_ad, {"asset_id": user_asset(env), "copy_fields": COPY})
    assert change_control_launch.is_stale(conn, env["org"], env["brand"], env["campaign"])
    asset = user_asset(env)
    library = library_placement(env, asset)

    on_platform = place(env, launched_ad, library["id"])
    assert on_platform.status_code == 409, on_platform.text
    assert on_platform.json()["error"]["code"] == "user_asset_unavailable"
    assert on_platform.json()["error"]["message"] == (
        "這則廣告已在平台上；要換素材請用「換掉這一則」。"
    )

    # The ad took this file with its workbench copy, then the user selected another version.
    ref = workbench_copy(env, redone_ad)
    assert by_ad(upload(env, redone_ad, {"asset_id": asset})["slots"])[redone_ad]["state"] == (
        "ready"
    )
    env["versions"][ref["set_id"]]["copy"] = {**WORKBENCH_COPY, "body": "換過的工作檯內文"}
    conflict = place(env, redone_ad, library["id"])
    assert conflict.status_code == 409, conflict.text
    assert conflict.json()["error"]["code"] == "placement_copy_conflict"
    assert conflict.json()["error"]["details"]["placement"]["ad_id"] == redone_ad


def test_placing_refuses_a_mixed_or_unknown_source(env):
    ad = env["ads"][0]
    asset = user_asset(env)
    with pytest.raises(ValueError, match="上傳欄位無效"):
        upload(env, ad, {"placement_id": "aap_x", "asset_id": asset})
    with pytest.raises(ValueError, match="上傳欄位無效"):
        upload(env, ad, {"placement_id": 3})
    with pytest.raises(ValueError, match="找不到素材安排"):
        upload(env, ad, {"placement_id": "aap_missing"})


def test_upload_refuses_unfinished_uploads_foreign_ads_and_bad_bodies(env):
    conn, ad = env["conn"], env["ads"][0]
    batch = user_assets.create_batch(
        conn, env["org"], env["brand"], [{"filename": "a.png", "size": 1}], "human"
    )
    with pytest.raises(ValueError, match="仍未上傳完成"):
        upload(env, ad, {"upload_id": batch["uploads"][0]["id"]})
    with pytest.raises(ValueError, match="找不到此活動的計畫廣告"):
        upload(env, "ada_missing", {"asset_id": user_asset(env)})
    with pytest.raises(ValueError, match="上傳欄位無效"):
        upload(env, ad, {"asset_id": user_asset(env), "entity_id": "x"})
    with pytest.raises(ValueError, match="請先上傳檔案"):
        upload(env, ad, {})
    client = TestClient(app)
    response = client.post(
        f"/api/ads/brands/{env['brand']}/campaigns/{env['campaign']}/slots/{ad}/upload",
        json={"copy_fields": {}},
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "user_asset_unavailable"


def test_upload_after_an_approved_launch_refuses_frozen_ads_and_fills_deferred_ones(env):
    frozen_ad, deferred_ad = env["ads"][0], env["ads"][1]
    assign_confirmed(env, frozen_ad, user_asset(env))
    launch(env)
    assert change_control_launch.material_frozen(
        env["conn"], env["org"], env["brand"], env["campaign"], frozen_ad
    )
    # The ad the approved batch froze is refused, like `handoff_assignment.assign`.
    with pytest.raises(ValueError, match="首次投放清單已核准"):
        upload(env, frozen_ad, {"asset_id": user_asset(env)})
    # The ad deferred from the batch for lack of material takes its file (F30 Unresolved 1);
    # with a complete copy the program confirms and assigns it in the same call.
    asset = user_asset(env)
    result = upload(env, deferred_ad, {"asset_id": asset, "copy_fields": COPY})
    assert by_ad(result["slots"])[deferred_ad]["state"] == "ready"
    row = campaigns.get_ad(env["conn"], env["org"], env["brand"], deferred_ad)
    assert row["material_placement_id"] == result["placement"]["id"]
    assert row["slot_placement_id"] is None
    # The plan changed under the approved launch: it is stale now, and the re-approval is the
    # later version that takes the deferred ad out (F28 "Stale launch"); nothing is frozen.
    assert change_control_launch.is_stale(env["conn"], env["org"], env["brand"], env["campaign"])
    assert not change_control_launch.material_frozen(
        env["conn"], env["org"], env["brand"], env["campaign"], frozen_ad
    )


# -- launched app-built ads and replace requests -------------------------------------------------


def test_replace_request_on_a_launched_app_built_ad_reaches_its_slot(env):
    conn = env["conn"]
    launched_ad, draft_ad = env["ads"][0], env["ads"][1]
    assign_confirmed(env, launched_ad, user_asset(env))  # a launch needs one ready ad
    launch(env)
    entity = platform_entity(
        env, "n1", creative={"kind": "image", "fields": {"thumbnail_url": "https://t/1.jpg"}}
    )
    conn.execute(
        "UPDATE ads_handoff_item SET entity_id=%s WHERE campaign_id=%s AND planned_kind='ad' "
        "AND planned_id=%s",
        (entity["id"], env["campaign"], launched_ad),
    )
    conn.commit()
    # A platform ad no planned ad holds (e.g. a replacement): listed, but on no slot.
    stray = platform_entity(env, "n2")
    task = replace(env, entity["id"])
    stray_task = replace(env, stray["id"])

    view = read(env)
    slot = by_ad(view)
    assert slot[launched_ad] == {
        "ad_id": launched_ad, "entity_id": entity["id"], "name": "晨光隨行杯・日常出發",
        "state": "ready", "thumbnail_url": "https://t/1.jpg", "confirmed": True,
        "replace_task_id": task["id"], "copy": placement_copy("已確認"), "workbench_href": None,
        "format_key": None, "blocked": None, "offer_label": None, "waiting": None, "job": None,
    }
    assert slot[draft_ad]["replace_task_id"] is None
    assert slot[draft_ad]["entity_id"] is None
    assert [r["task_id"] for r in view["requests"]] == [stray_task["id"], task["id"]]
    request = view["requests"][1]
    assert request["replaces"] == {
        "entity_id": entity["id"], "name": "平台廣告 n1", "thumbnail_url": "https://t/1.jpg",
    }
    assert request["state_label"] == "等素材工作檯"
    assert request["created_at"] == task["created_at"]
    with pytest.raises(ValueError, match="已在平台上"):
        upload(env, launched_ad, {"asset_id": user_asset(env)})


def test_request_state_label_comes_from_the_task_and_cancelled_requests_leave(env):
    conn = env["conn"]
    entity = platform_entity(env, "n1")
    task = replace(env, entity["id"])
    asset = user_asset(env)

    def mutate(action, **fields):
        current = material_tasks.get(conn, env["org"], env["brand"], env["campaign"], task["id"])
        return material_tasks.mutate(
            conn, env["org"], env["brand"], env["campaign"], task["id"],
            {"operation_id": db.new_id("op"), "expected_revision": current["revision"], **fields},
            action, "test",
        )

    with_candidate = mutate("candidates", asset_ids=[asset])
    assert read(env)["requests"][0]["state_label"] == "有候選圖"
    mutate(
        "select", candidate_id=with_candidate["candidates"][0]["id"],
        content_hash=with_candidate["content_hash"],
    )
    assert read(env)["requests"][0]["state_label"] == "已採用"
    material_tasks.cancel(conn, env["org"], env["brand"], env["campaign"], task["id"], "test")
    assert read(env)["requests"] == []


def test_a_deleted_replaced_entity_keeps_the_request_with_unknown_name_and_thumbnail(env):
    conn = env["conn"]
    entity = platform_entity(env, "gone")
    task = replace(env, entity["id"])
    conn.execute("DELETE FROM ads_external_entity WHERE id=%s", (entity["id"],))
    conn.commit()
    assert read(env)["requests"] == [
        {
            "task_id": task["id"],
            "replaces": {"entity_id": entity["id"], "name": None, "thumbnail_url": None},
            "created_at": task["created_at"],
            "state_label": "等素材工作檯",
        }
    ]


def test_requests_cap_at_one_hundred_and_say_truncated(env):
    ids = []
    for i in range(101):
        entity = platform_entity(env, f"cap{i:03d}")
        ids.append(replace(env, entity["id"])["id"])
    view = read(env)
    assert len(view["requests"]) == 100
    assert view["requests_truncated"] is True
    assert ids[0] not in {r["task_id"] for r in view["requests"]}  # oldest falls off


# -- imported campaigns ---------------------------------------------------------------------------


def test_imported_campaign_slots_are_its_live_platform_ads_under_their_ad_sets(env):
    imported = external_repository.create_imported_campaign(
        env["conn"], env["org"], env["brand"], name="既有活動"
    )["id"]
    parent = {"parent_native_kind": "adset", "parent_native_id": "set-b"}
    platform_entity(env, "set-b", campaign=imported, native_kind="adset", name="B 組")
    platform_entity(env, "set-a", campaign=imported, native_kind="adset", name="A 組")
    b2 = platform_entity(env, "b2", campaign=imported, name="晨光 2", **parent)
    b1 = platform_entity(
        env, "b1", campaign=imported, name="晨光 1",
        creative={"kind": "image", "fields": {"image_url": "https://t/b1.jpg"}}, **parent,
    )
    a1 = platform_entity(
        env, "a1", campaign=imported, name="通勤", parent_native_kind="adset",
        parent_native_id="set-a",
    )
    platform_entity(env, "closed", campaign=imported, native_status="DELETED", **parent)
    task = replace(env, b2["id"], campaign=imported)

    view = read(env, imported)
    assert (view["ready"], view["total"]) == (3, 3)
    assert [g["name"] for g in view["groups"]] == ["A 組", "B 組"]
    assert all(g["group_id"] is None for g in view["groups"])
    assert [s["entity_id"] for s in view["groups"][0]["slots"]] == [a1["id"]]
    assert [s["entity_id"] for s in view["groups"][1]["slots"]] == [b1["id"], b2["id"]]
    first = view["groups"][1]["slots"][0]
    assert first == {
        "ad_id": None, "entity_id": b1["id"], "name": "晨光 1", "state": "ready",
        "thumbnail_url": "https://t/b1.jpg", "confirmed": True, "replace_task_id": None,
        "copy": None, "workbench_href": None, "format_key": None,
        "blocked": None, "offer_label": None,  # an imported campaign has no offer coordinate
        "waiting": None, "job": None,
    }
    assert view["groups"][1]["slots"][1]["replace_task_id"] == task["id"]
    assert [r["task_id"] for r in view["requests"]] == [task["id"]]
    with pytest.raises(ValueError):
        slots.upload(
            env["conn"], env["org"], env["brand"], imported, b1["id"],
            {"asset_id": user_asset(env)}, "human",
        )


def test_one_original_uploaded_into_two_slots_backs_both_ads(env):
    """F40-I02 (drill-7 #6): the same file goes into two slots with its own (still partial,
    so unconfirmed and, since F44, `blocked`) copy -- two current placements keyed by ad, two
    `slot_placement_id`s, one shared thumbnail; the same ad with other copy is still the one
    conflict."""
    first_ad, second_ad, _ = env["ads"]
    asset = user_asset(env)
    first = upload(env, first_ad, {"asset_id": asset, "copy_fields": {"body": "第一則"}})
    second = upload(env, second_ad, {"asset_id": asset, "copy_fields": {"body": "第二則"}})
    assert first["placement"]["id"] != second["placement"]["id"]
    assert (first["placement"]["ad_id"], second["placement"]["ad_id"]) == (first_ad, second_ad)
    rows = env["conn"].execute(
        "SELECT p.asset_id,p.ad_id,p.is_current,a.slot_placement_id FROM ads_asset_placement p "
        "JOIN ads_ad a ON a.id=p.ad_id WHERE p.campaign_id=%s ORDER BY a.created_at,a.id",
        (env["campaign"],),
    ).fetchall()
    assert [(r["asset_id"], r["ad_id"], r["is_current"], r["slot_placement_id"]) for r in rows] == [
        (asset, first_ad, True, first["placement"]["id"]),
        (asset, second_ad, True, second["placement"]["id"]),
    ]
    slot = by_ad(second["slots"])
    assert slot[first_ad]["thumbnail_url"] == slot[second_ad]["thumbnail_url"] == thumb(env, asset)
    assert (slot[first_ad]["state"], slot[second_ad]["state"]) == ("blocked", "blocked")
    for ad, body in ((first_ad, "第一則"), (second_ad, "第二則")):
        assert slot[ad]["copy"] == placement_copy(
            "待確認", {"headline": None, "body": body, "description": None}
        )
    with pytest.raises(user_assets.PlacementConflict):
        upload(env, first_ad, {"asset_id": asset, "copy_fields": {"body": "第三稿"}})


def test_slot_carries_the_planned_ads_format_key(env):
    """F40-I01: a planned slot names its ad's own `format_key` (so the assets tab can say a
    video-format slot needs a script); an ad without one reads `None`."""
    video_ad, plain_ad, _ = env["ads"]
    env["conn"].execute("UPDATE ads_ad SET format_key='video' WHERE id=%s", (video_ad,))
    env["conn"].commit()
    slot = by_ad(read(env))
    assert slot[video_ad]["format_key"] == "video"
    assert slot[plain_ad]["format_key"] is None


def test_slots_route_reads_and_unknown_campaign_is_404(env):
    client = TestClient(app)
    ok = client.get(f"/api/ads/brands/{env['brand']}/campaigns/{env['campaign']}/slots")
    assert ok.status_code == 200, ok.text
    assert ok.json()["total"] == 3
    missing = client.get(f"/api/ads/brands/{env['brand']}/campaigns/adc_missing/slots")
    assert missing.status_code == 404


# -- F44-I03: the copy is judged against the ad's sell-way and offer coordinate -------------------


# The sell-way's registered offer sentence (F45, no product name):
# 「優惠價 NT$999（原價 NT$1,500）」.
PRICE_COPY = {
    "headline": "晨光軟糖三盒組",
    "body": "三盒組優惠價 NT$999（原價 NT$1,500）",
    "description": "每天兩顆",
}
SHIP_999 = [{"key": "ship_threshold", "params": {"threshold": 999}}]


def sell_way_campaign(env, *, qty=3, price=999, list_price=1500, policies=None):
    """The campaign sells one sell-way of a real brand product: `qty` units at `price`, below
    `list_price` -- its own offer is `bundle` (several units) or `discount` (one unit)."""
    conn = env["conn"]
    if policies:
        brands.save_brand_policies(conn, env["brand"], policies, actor="test")
    product = brands.create_product(conn, env["brand"], name="晨光軟糖", actor="test")["id"]
    # F45: one unit is a base sell-way; several units are a composed one of the 單盒 base.
    shape = {"product_id": product}
    if qty > 1:
        box = brands.save_sell_way(conn, env["brand"], name="單盒", actor="test",
                                   product_id=product, economics={"selling_price": 500})["id"]
        shape = {"components": [{"sell_way_id": box, "qty": qty}]}
    way = brands.save_sell_way(
        conn, env["brand"], name="三盒組", actor="test", **shape,
        economics={
            "selling_price": price, "list_price": list_price, "unit_variable_cost": 300,
            "shipping_cost": 60,
        },
    )["id"]
    campaigns.update_campaign(
        conn, env["org"], env["brand"], env["campaign"], {"product_ids": [way]}
    )
    conn.commit()
    return way


def plan_offer(env, ad, key, label):
    """The offer coordinate the plan gave this ad, with the label its snapshot kept."""
    env["conn"].execute(
        "UPDATE ads_ad SET offer_key=%s,coordinates_snapshot_json=%s WHERE id=%s",
        (key, db.jsonb({"offer": {"key": key, "label": label}}), ad),
    )
    env["conn"].commit()


def recheck(env, placement):
    return asset_suggestions.confirm_manual(
        env["conn"], env["org"], env["brand"], env["campaign"], placement["id"],
        placement["revision"], "human",
    )


def refusal(kind, text, terms=()):
    return {"kind": kind, "text": text, "terms": list(terms)}


def test_sell_way_price_copy_confirms_on_the_ad_planned_with_that_offer(env):
    """Drill-9 red #2: the sell-way's own 「優惠價／原價」 on an `offer=bundle` ad is backed."""
    ad = env["ads"][0]
    sell_way_campaign(env)
    plan_offer(env, ad, "bundle", "組合優惠")
    result = upload(env, ad, {"asset_id": user_asset(env), "copy_fields": PRICE_COPY})
    assert result["placement"]["confirmed_at"]
    assert result["placement"]["status"] == "manual_ready"
    assert by_ad(result["slots"])[ad]["state"] == "ready"


def test_the_same_copy_on_a_no_offer_ad_is_refused_with_the_mismatch(env):
    ad = env["ads"][0]
    sell_way_campaign(env)
    plan_offer(env, ad, "none", "無優惠")
    result = upload(env, ad, {"asset_id": user_asset(env), "copy_fields": PRICE_COPY})
    assert result["placement"]["confirmed_at"] is None
    assert by_ad(result["slots"])[ad]["state"] == "blocked"

    refused = recheck(env, result["placement"])
    # F46-I02 Contract O: 原價 is an offer word too.
    sentence = "這則規劃的是「無優惠」，文案卻寫了「優惠、原價」。"
    assert (refused["status"], refused["confirmed_at"]) == ("pending", None)
    assert refused["pending_reasons"] == [sentence]
    assert refused["pending_details"] == [refusal("copy", sentence, ["優惠", "原價"])]


def test_a_word_of_another_offer_family_is_a_mismatch_with_the_planned_offer(env):
    """The sell-way's offer is `bundle`, the ad was planned with 免運. F46-I02 Contract O: an
    offer word is backed only by its exact term in a registered sentence -- the bundle's
    「優惠價…（原價…）」 does not write 加贈, so it is unbacked, not a family mismatch."""
    ad = env["ads"][0]
    sell_way_campaign(env, policies=SHIP_999)
    plan_offer(env, ad, "free_shipping", "免運")
    copy = {**COPY, "body": "買三盒加贈一盒"}
    result = upload(env, ad, {"asset_id": user_asset(env), "copy_fields": copy})
    assert result["placement"]["confirmed_at"] is None
    sentence = "文案寫了「加贈」，品牌資料裡沒有登記這個優惠或背書。"
    assert recheck(env, result["placement"])["pending_details"] == [
        refusal("copy", sentence, ["加贈"])
    ]


def test_a_promise_the_sell_way_does_not_have_is_unbacked(env):
    """One unit below its list price is a `discount`: nothing registered backs 「加贈」, on any
    offer coordinate -- the unbacked sentence, not a mismatch."""
    ad = env["ads"][0]
    sell_way_campaign(env, qty=1, price=800, list_price=1000)
    plan_offer(env, ad, "discount", "折扣")
    copy = {**COPY, "body": "現在下單加贈一盒"}
    result = upload(env, ad, {"asset_id": user_asset(env), "copy_fields": copy})
    assert result["placement"]["confirmed_at"] is None
    sentence = "文案寫了「加贈」，品牌資料裡沒有登記這個優惠或背書。"
    refused = recheck(env, result["placement"])
    assert refused["pending_reasons"] == [sentence]
    assert refused["pending_details"] == [refusal("copy", sentence, ["加贈"])]


def test_library_placement_is_judged_with_the_campaigns_sell_way(env):
    conn = env["conn"]
    placement = user_assets.attach(
        conn, env["org"], env["brand"], env["campaign"], user_asset(env), PRICE_COPY, "human",
        purpose="產品介紹",
    )
    conn.commit()
    # No sell-way on the campaign: brand level, where no offer is registered.
    assert recheck(env, placement)["pending_details"] == [
        refusal("copy", "文案寫了「優惠、原價」，品牌資料裡沒有登記這個優惠或背書。",
                ["優惠", "原價"])
    ]
    sell_way_campaign(env)
    confirmed = recheck(env, placement)
    assert (confirmed["status"], confirmed["ad_id"]) == ("manual_ready", None)
    assert confirmed["confirmed_at"]


def test_snapshot_names_what_each_placement_is_judged_against(env):
    conn = env["conn"]
    way = sell_way_campaign(env)
    planned_ad, edited_ad, bare_ad = env["ads"]
    plan_offer(env, planned_ad, "bundle", "組合優惠")
    # Planned with `bundle`, edited to `none` afterwards: the snapshot's label is another key's,
    # so the label is the brand vocabulary's.
    plan_offer(env, edited_ad, "bundle", "組合優惠")
    conn.execute("UPDATE ads_ad SET offer_key='none' WHERE id=%s", (edited_ad,))
    conn.execute(
        "INSERT INTO brand_coordinate(id,org_id,brand_id,dimension,key,label) "
        "VALUES(%s,%s,%s,'offer','none','無優惠')",
        (db.new_id("crd"), env["org"], env["brand"]),
    )
    placed = {
        ad: user_assets.attach(
            conn, env["org"], env["brand"], env["campaign"], user_asset(env), COPY, "human",
            ad_id=ad,
        )
        for ad in (planned_ad, edited_ad, bare_ad, None)
    }
    conn.commit()
    data = asset_suggestions.snapshot(
        conn, env["org"], env["brand"], env["campaign"],
        [{"id": p["id"], "revision": 1} for p in placed.values()], "",
    )
    assert data["campaign"]["sell_way"] == way
    judged = {
        p["ad_id"]: (p["sell_way"], p["offer_key"], p["offer_label"]) for p in data["placements"]
    }
    assert judged == {
        planned_ad: (way, "bundle", "組合優惠"),
        edited_ad: (way, "none", "無優惠"),
        bare_ad: (way, None, None),
        None: (way, None, None),  # a library placement: the campaign's sell-way, no offer
    }


def test_refusal_details_name_the_exit_that_fixes_each_reason(env):
    conn = env["conn"]
    failed = user_asset(env, status="error", thumbnail=False)
    conn.execute("UPDATE ads_user_asset SET error='圖片格式讀不出來。' WHERE id=%s", (failed,))
    waiting = user_asset(env, status="pending", thumbnail=False)
    cases = (
        (failed, COPY, "產品介紹", [refusal("file", "圖片格式讀不出來。")]),
        (waiting, COPY, "產品介紹", [refusal("wait", "原檔預覽尚未完成，請先完成媒體處理。")]),
        (
            user_asset(env), {"headline": "標題"}, None,
            [
                refusal("copy", "請补齊標題、內文與說明，或補充可用品牌事實。"),
                refusal("campaign", "請補這件素材的投放用途。"),
            ],
        ),
    )
    for asset, copy, purpose, details in cases:
        placement = user_assets.attach(
            conn, env["org"], env["brand"], env["campaign"], asset, copy, "human",
            purpose=purpose,
        )
        conn.commit()
        refused = recheck(env, placement)
        assert refused["confirmed_at"] is None
        assert refused["pending_details"] == details
        assert refused["pending_reasons"] == [d["text"] for d in details]


# -- F44-I04 Contract D: a refused slot keeps its reason; the slots read says it ------------------


MISMATCH = "這則規劃的是「無優惠」，文案卻寫了「優惠、原價」。"  # F46-I02: 原價 too
MISMATCH_TERMS = ["優惠", "原價"]
CLEAN_COPY = {"headline": "晨光軟糖三盒組", "body": "讀到深夜也有它陪", "description": "每天兩顆"}


def blocked(text, terms=(), *, fix, more=0):
    return {"text": text, "terms": list(terms), "fix": fix, "more": more}


def stored_reasons(env, placement_id):
    return user_assets.placement(
        env["conn"], env["org"], env["brand"], env["campaign"], placement_id
    )["blocked_reasons"]


def refused_slot(env, ad):
    """The drill-9 red #2 slot: an ad planned with 無優惠 whose file came with the sell-way's
    price copy -- the confirmation refuses it."""
    sell_way_campaign(env)
    plan_offer(env, ad, "none", "無優惠")
    return upload(env, ad, {"asset_id": user_asset(env), "copy_fields": PRICE_COPY})


def test_a_refused_slot_keeps_its_reason_and_reads_blocked_with_the_copy_exit(env):
    ad, other_ad = env["ads"][0], env["ads"][1]
    result = refused_slot(env, ad)
    assert stored_reasons(env, result["placement"]["id"]) == [
        refusal("copy", MISMATCH, MISMATCH_TERMS)
    ]
    env["conn"].commit()  # the route reads on its own connection

    view = TestClient(app).get(f"{base(env)}/slots")
    assert view.status_code == 200, view.text
    assert view.json() == result["slots"]
    slot = by_ad(view.json())[ad]
    assert slot == {
        "ad_id": ad, "entity_id": None, "name": "晨光隨行杯・日常出發", "state": "blocked",
        "thumbnail_url": thumb(env, result["placement"]["asset_id"]), "confirmed": False,
        "replace_task_id": None, "copy": placement_copy("待確認", PRICE_COPY),
        "workbench_href": None, "format_key": None,
        "blocked": blocked(MISMATCH, MISMATCH_TERMS, fix="copy"), "offer_label": "無優惠",
        "waiting": None, "job": None,
    }
    # A blocked slot is not ready; the slots nothing was uploaded into carry `blocked: None`.
    assert (view.json()["ready"], view.json()["total"]) == (0, 3)
    assert by_ad(view.json())[other_ad]["blocked"] is None
    row = campaigns.get_ad(env["conn"], env["org"], env["brand"], ad)
    assert (row["material_placement_id"], row["slot_placement_id"]) == (
        None, result["placement"]["id"],
    )


def test_choosing_a_clean_copy_version_clears_the_reason_and_the_slot_is_ready(env):
    ad = env["ads"][0]
    result = refused_slot(env, ad)
    option = workbench_copy(env, ad, CLEAN_COPY)

    chosen = TestClient(app).post(f"{base(env)}/slots/{ad}/copy", json=option)
    assert chosen.status_code == 200, chosen.text
    placement = chosen.json()["placement"]
    assert (placement["id"], placement["revision"]) == (result["placement"]["id"], 2)
    assert placement["confirmed_at"]
    assert placement["blocked_reasons"] == []
    slot = by_ad(chosen.json()["slots"])[ad]
    assert (slot["state"], slot["blocked"]) == ("ready", None)
    assert slot["copy"] == placement_copy("已確認", CLEAN_COPY)
    assert chosen.json()["slots"]["ready"] == 1
    # The refused revision keeps what it was refused for (history), the current one is clean.
    refused = user_assets.placement(
        env["conn"], env["org"], env["brand"], env["campaign"], placement["id"], 1
    )
    assert refused["blocked_reasons"] == [refusal("copy", MISMATCH, MISMATCH_TERMS)]


def test_recheck_returns_the_same_reason_until_its_cause_is_removed(env):
    ad = env["ads"][0]
    result = refused_slot(env, ad)
    client = TestClient(app)

    again = client.post(f"{base(env)}/slots/{ad}/recheck")
    assert again.status_code == 200, again.text
    assert set(again.json()) == {"slots"}
    slot = by_ad(again.json()["slots"])[ad]
    assert (slot["state"], slot["blocked"]) == (
        "blocked", blocked(MISMATCH, MISMATCH_TERMS, fix="copy"),
    )

    # The cause removed: the ad's offer coordinate now matches what the copy says.
    plan_offer(env, ad, "bundle", "組合優惠")
    fixed = client.post(f"{base(env)}/slots/{ad}/recheck")
    assert fixed.status_code == 200, fixed.text
    slot = by_ad(fixed.json()["slots"])[ad]
    assert (slot["state"], slot["confirmed"], slot["blocked"]) == ("ready", True, None)
    assert slot["offer_label"] == "組合優惠"
    assert slot["copy"] == placement_copy("已確認", PRICE_COPY)
    assert fixed.json()["slots"]["ready"] == 1
    assert stored_reasons(env, result["placement"]["id"]) == []
    row = campaigns.get_ad(env["conn"], env["org"], env["brand"], ad)
    assert (row["material_placement_id"], row["material_placement_revision"]) == (
        result["placement"]["id"], 1,
    )
    assert row["slot_placement_id"] is None

    # Ready now: nothing left to check.
    done = client.post(f"{base(env)}/slots/{ad}/recheck")
    assert done.status_code == 409, done.text
    assert done.json()["error"]["code"] == "slot_no_file"


def test_recheck_replaces_the_stored_reasons_with_the_new_refusal(env):
    """Fixing one cause may leave another: the slot says the reason of the latest refusal."""
    conn, ad = env["conn"], env["ads"][0]
    result = refused_slot(env, ad)
    plan_offer(env, ad, "bundle", "組合優惠")
    conn.execute("UPDATE ads_delivery_group SET daily_budget=0 WHERE id=%s", (env["group"],))
    conn.commit()
    platform_entity(
        env, "root", native_kind="campaign", currency="TWD", budget_type="daily",
        budget_amount=0,
    )
    view = slots.recheck(conn, env["org"], env["brand"], env["campaign"], ad, "human")["slots"]
    slot = by_ad(view)[ad]
    assert slot["state"] == "blocked"
    assert (slot["blocked"]["fix"], slot["blocked"]["terms"], slot["blocked"]["more"]) == (
        None, [], 0,
    )
    assert slot["blocked"]["text"].startswith("目前已知預算為零")
    assert [d["kind"] for d in stored_reasons(env, result["placement"]["id"])] == ["campaign"]


def test_recheck_refuses_slots_with_nothing_to_check_and_foreign_campaigns(env):
    client = TestClient(app)
    empty_ad, ready_ad = env["ads"][0], env["ads"][1]
    assign_confirmed(env, ready_ad, user_asset(env))
    for ad in (empty_ad, ready_ad):
        response = client.post(f"{base(env)}/slots/{ad}/recheck")
        assert response.status_code == 409, response.text
        assert response.json()["error"]["code"] == "slot_no_file"
    unknown_ad = client.post(f"{base(env)}/slots/ada_missing/recheck")
    assert unknown_ad.status_code == 409
    assert unknown_ad.json()["error"] == {
        "code": "user_asset_unavailable", "message": "找不到此活動的計畫廣告。", "details": None,
    }
    imported = external_repository.create_imported_campaign(
        env["conn"], env["org"], env["brand"], name="既有活動"
    )["id"]
    env["conn"].commit()
    prefix = f"/api/ads/brands/{env['brand']}/campaigns"
    missing = client.post(f"{prefix}/adc_missing/slots/{empty_ad}/recheck")
    assert missing.status_code == 404
    assert missing.json()["error"]["code"] == "campaign_unknown"
    assert client.post(f"{prefix}/{imported}/slots/{empty_ad}/recheck").status_code == 409


def test_recheck_while_the_preview_is_not_made_stays_in_progress(env):
    """Waiting is not a refusal: nothing is stored, the slot keeps `in_progress`."""
    ad = env["ads"][0]
    waiting = user_asset(env, status="pending", thumbnail=False)
    result = upload(env, ad, {"asset_id": waiting, "copy_fields": COPY})
    view = slots.recheck(
        env["conn"], env["org"], env["brand"], env["campaign"], ad, "human"
    )["slots"]
    assert (by_ad(view)[ad]["state"], by_ad(view)[ad]["blocked"]) == ("in_progress", None)
    assert stored_reasons(env, result["placement"]["id"]) == []


def test_only_details_with_something_to_fix_are_stored(env):
    """The one writer (`asset_suggestions.store_refusal`) never keeps a `wait` detail: beside
    others it is left out, alone it leaves nothing to fix; the newest refusal replaces the last."""
    ad = env["ads"][0]
    result = upload(env, ad, {"asset_id": user_asset(env), "copy_fields": {"body": "內文"}})
    placement = result["placement"]
    assert [d["kind"] for d in stored_reasons(env, placement["id"])] == ["copy"]
    wait = refusal("wait", "原檔預覽尚未完成，請先完成媒體處理。")
    other = refusal("copy", "含品牌禁止宣稱，請修訂此安排的文案。")
    for details, expected in (([wait, other], [other]), ([wait], [])):
        kept = asset_suggestions.store_refusal(
            env["conn"], env["org"], env["brand"], env["campaign"], placement["id"],
            placement["revision"], details,
        )
        assert kept == expected
        assert stored_reasons(env, placement["id"]) == expected


def test_a_failed_original_reads_blocked_with_the_file_exit(env):
    conn = env["conn"]
    with_copy, without_copy, refused_ad = env["ads"]
    failed = user_asset(env, status="error", thumbnail=False)
    conn.execute("UPDATE ads_user_asset SET error='圖片格式讀不出來。' WHERE id=%s", (failed,))
    conn.commit()
    file_reason = "這個檔案處理失敗：圖片格式讀不出來。"
    result = upload(env, with_copy, {"asset_id": failed, "copy_fields": COPY})
    # Read from the original itself: the confirmation never ran, so nothing is stored.
    assert stored_reasons(env, result["placement"]["id"]) == []
    slot = by_ad(upload(env, without_copy, {"asset_id": failed})["slots"])
    assert slot[with_copy]["state"] == slot[without_copy]["state"] == "blocked"
    assert slot[with_copy]["blocked"] == blocked(file_reason, fix="file")
    assert slot[with_copy]["copy"] == placement_copy("待確認")
    assert slot[with_copy]["thumbnail_url"] is None
    # No copy either: the file is what blocks it, not the missing copy (never `image_only`).
    assert (slot[without_copy]["blocked"], slot[without_copy]["copy"]) == (
        blocked(file_reason, fix="file"), None,
    )

    # A slot already refused for its copy whose original then fails: the file first, one more.
    asset = user_asset(env)
    upload(env, refused_ad, {"asset_id": asset, "copy_fields": {"headline": "標題", "body": "x"}})
    conn.execute("UPDATE ads_user_asset SET status='error',error='損毀' WHERE id=%s", (asset,))
    conn.commit()
    assert by_ad(read(env))[refused_ad]["blocked"] == blocked(
        "這個檔案處理失敗：損毀", fix="file", more=1
    )
    # A transient failure the dispatcher still retries is not a failed original.
    conn.execute("UPDATE ads_user_asset SET status='retryable' WHERE id=%s", (failed,))
    conn.commit()
    assert by_ad(read(env))[with_copy]["state"] == "in_progress"


def test_a_file_without_copy_keeps_its_picker(env):
    """The missing copy is what the picker is for: the slot stays `image_only`, not `blocked`,
    even though the refused confirmation's reason is stored."""
    ad = env["ads"][0]
    result = upload(env, ad, {"asset_id": user_asset(env)})
    slot = by_ad(result["slots"])[ad]
    assert (slot["state"], slot["blocked"], slot["copy"]) == ("image_only", None, None)


def test_a_deleted_sell_way_blocks_the_slot_instead_of_failing_the_upload(env):
    ad = env["ads"][0]
    way = sell_way_campaign(env)
    # Only an archived product can be deleted.
    brands.update_product(
        env["conn"], env["brand"], way, name="三盒組", status="archived", actor="test"
    )
    brands.delete_product(env["conn"], env["brand"], way, actor="test")
    env["conn"].commit()
    response = TestClient(app).post(
        f"{base(env)}/slots/{ad}/upload", json={"asset_id": user_asset(env), "copy_fields": COPY}
    )
    assert response.status_code == 200, response.text
    assert response.json()["placement"]["confirmed_at"] is None
    slot = by_ad(response.json()["slots"])[ad]
    assert (slot["state"], slot["blocked"]) == (
        "blocked", blocked("找不到此品牌商品。", fix=None),
    )
    assert stored_reasons(env, response.json()["placement"]["id"]) == [
        refusal("campaign", "找不到此品牌商品。")
    ]


def test_every_planned_slot_names_its_ads_offer_coordinate(env):
    planned_ad, edited_ad, bare_ad = env["ads"]
    sell_way_campaign(env)
    plan_offer(env, planned_ad, "bundle", "組合優惠")
    # Edited to another key after the plan: the label is the brand vocabulary's, else the key.
    plan_offer(env, edited_ad, "bundle", "組合優惠")
    env["conn"].execute("UPDATE ads_ad SET offer_key='none' WHERE id=%s", (edited_ad,))
    env["conn"].commit()
    result = upload(env, planned_ad, {"asset_id": user_asset(env), "copy_fields": PRICE_COPY})
    slot = by_ad(result["slots"])
    assert (slot[planned_ad]["state"], slot[planned_ad]["offer_label"]) == ("ready", "組合優惠")
    assert (slot[edited_ad]["state"], slot[edited_ad]["offer_label"]) == ("missing", "none")
    assert slot[bare_ad]["offer_label"] is None


# -- F45 Contract W: a slot says who it waits for; every edit is checked at once ------------------


DOCTOR = "文案寫了「醫師推薦」，品牌資料裡沒有登記這個優惠或背書。"
DOCTOR_COPY = {**COPY, "body": "醫師推薦的好味道"}


def brief_status(status):
    """The workbench sets read through its facade, with their generation `status` set to
    `status` (the real brief read, its status overridden -- no workbench table is written)."""
    real = workbench.briefs_for_source

    def read_with_status(*args, **kwargs):
        return [{**brief, "status": status} for brief in real(*args, **kwargs)]

    return patch.object(workbench, "briefs_for_source", side_effect=read_with_status)


def test_drill10_b3_a_placement_edit_behind_a_slot_is_checked_at_once(env):
    """Drill 10 B3: a slot's copy revised through `PATCH …/placements` used to sit in
    `in_progress` for ever. The revision is confirmed when it is saved: 「醫師推薦」 (nothing
    backs it) reads `blocked` with the unbacked sentence; revised back it reads `ready`."""
    ad = env["ads"][1]
    client = TestClient(app)
    uploaded = client.post(
        f"{base(env)}/slots/{ad}/upload",
        json={"asset_id": user_asset(env), "copy_fields": {"headline": "標題", "body": "文案"}},
    )
    placement = uploaded.json()["placement"]
    assert by_ad(uploaded.json()["slots"])[ad]["state"] == "blocked"

    doctor = client.patch(
        f"{base(env)}/placements/{placement['id']}",
        json={"expected_revision": 1, "copy_fields": DOCTOR_COPY},
    )
    assert doctor.status_code == 200, doctor.text
    assert doctor.json()["placement"]["confirmed_at"] is None
    assert doctor.json()["placement"]["blocked_reasons"] == [
        refusal("copy", DOCTOR, ["醫師推薦"])
    ]
    slot = by_ad(client.get(f"{base(env)}/slots").json())[ad]
    assert (slot["state"], slot["blocked"]) == (
        "blocked", blocked(DOCTOR, ["醫師推薦"], fix="copy"),
    )
    assert (slot["waiting"], slot["job"]) == (None, None)

    back = client.patch(
        f"{base(env)}/placements/{placement['id']}",
        json={"expected_revision": 2, "copy_fields": COPY},
    )
    assert back.status_code == 200, back.text
    assert back.json()["placement"]["confirmed_at"]
    slot = by_ad(client.get(f"{base(env)}/slots").json())[ad]
    assert (slot["state"], slot["blocked"]) == ("ready", None)
    row = campaigns.get_ad(env["conn"], env["org"], env["brand"], ad)
    assert (row["material_placement_id"], row["material_placement_revision"]) == (
        placement["id"], 3,
    )
    assert row["slot_placement_id"] is None


def test_editing_an_assigned_material_points_the_slot_at_it_and_checks_it(env):
    """The material's placement backs the slot too: an edit with 「醫師推薦」 takes the slot from
    `ready` to `blocked` (no silent stale assignment); a library placement no slot uses is left
    alone (no confirmation runs for it)."""
    ad = env["ads"][0]
    placement = assign_confirmed(env, ad, user_asset(env))
    library = user_assets.attach(
        env["conn"], env["org"], env["brand"], env["campaign"], user_asset(env), COPY, "human",
    )
    env["conn"].commit()
    client = TestClient(app)
    edited = client.patch(
        f"{base(env)}/placements/{placement['id']}",
        json={"expected_revision": 1, "copy_fields": DOCTOR_COPY},
    )
    assert edited.status_code == 200, edited.text
    slot = by_ad(client.get(f"{base(env)}/slots").json())[ad]
    assert (slot["state"], slot["blocked"]["text"]) == ("blocked", DOCTOR)
    row = campaigns.get_ad(env["conn"], env["org"], env["brand"], ad)
    assert row["slot_placement_id"] == placement["id"]

    library_edit = client.patch(
        f"{base(env)}/placements/{library['id']}",
        json={"expected_revision": 1, "copy_fields": DOCTOR_COPY},
    )
    assert library_edit.status_code == 200, library_edit.text
    assert library_edit.json()["placement"]["blocked_reasons"] == []


def test_a_launched_ads_material_edit_is_not_rechecked(env):
    """A planned ad already on the platform (its handoff matched to a platform ad) is skipped
    without an error: its slot is the platform ad's."""
    conn, launched_ad = env["conn"], env["ads"][0]
    placement = assign_confirmed(env, launched_ad, user_asset(env))
    launch(env)
    entity = platform_entity(env, "n1")
    conn.execute(
        "UPDATE ads_handoff_item SET entity_id=%s WHERE campaign_id=%s AND planned_kind='ad' "
        "AND planned_id=%s",
        (entity["id"], env["campaign"], launched_ad),
    )
    conn.commit()
    edited = TestClient(app).patch(
        f"{base(env)}/placements/{placement['id']}",
        json={"expected_revision": 1, "copy_fields": DOCTOR_COPY},
    )
    assert edited.status_code == 200, edited.text
    assert edited.json()["placement"]["blocked_reasons"] == []
    row = campaigns.get_ad(env["conn"], env["org"], env["brand"], launched_ad)
    assert row["slot_placement_id"] is None


def test_the_advanced_confirm_route_stores_its_refusal(env):
    """A refused confirm is not an error response, and its reasons outlive the request."""
    placement = user_assets.attach(
        env["conn"], env["org"], env["brand"], env["campaign"], user_asset(env),
        {"headline": "標題"}, "human", purpose="產品介紹",
    )
    env["conn"].commit()
    response = TestClient(app).post(
        f"{base(env)}/placements/{placement['id']}/confirm", json={"expected_revision": 1}
    )
    assert response.status_code == 200, response.text
    body = response.json()["placement"]
    assert (body["status"], body["confirmed_at"]) == ("pending", None)
    expected = [refusal("copy", "請补齊標題、內文與說明，或補充可用品牌事實。")]
    assert body["blocked_reasons"] == expected
    assert stored_reasons(env, placement["id"]) == expected


def test_a_typed_copy_edit_is_checked_at_once(env):
    ad = env["ads"][0]
    result = refused_slot(env, ad)
    client = TestClient(app)

    doctor = client.post(
        f"{base(env)}/slots/{ad}/copy", json={"copy_fields": {"body": "醫師推薦的好味道"}}
    )
    assert doctor.status_code == 200, doctor.text
    placement = doctor.json()["placement"]
    assert (placement["id"], placement["revision"]) == (result["placement"]["id"], 2)
    # A field not sent keeps its value.
    assert placement["copy_fields"] == {**PRICE_COPY, "body": "醫師推薦的好味道"}
    assert placement["confirmed_at"] is None
    slot = by_ad(doctor.json()["slots"])[ad]
    assert (slot["state"], slot["blocked"]) == (
        "blocked", blocked(DOCTOR, ["醫師推薦"], fix="copy"),
    )

    clean = client.post(f"{base(env)}/slots/{ad}/copy", json={"copy_fields": CLEAN_COPY})
    assert clean.status_code == 200, clean.text
    assert clean.json()["placement"]["confirmed_at"]
    slot = by_ad(clean.json()["slots"])[ad]
    assert (slot["state"], slot["copy"]) == ("ready", placement_copy("已確認", CLEAN_COPY))

    # The same guards as the picker: bad bodies are 400, a ready slot has nothing to edit.
    for bad in (
        {"copy_fields": {"cta": "x"}}, {"copy_fields": "x"}, {"copy_fields": {}},
        {"copy_fields": {"body": 1}}, {"copy_fields": COPY, "set_id": "s"},
    ):
        response = client.post(f"{base(env)}/slots/{ad}/copy", json=bad)
        assert response.status_code == 400, (bad, response.text)
        assert response.json()["error"]["code"] == "slot_copy_invalid"
    again = client.post(f"{base(env)}/slots/{ad}/copy", json={"copy_fields": COPY})
    assert again.status_code == 409
    assert again.json()["error"]["code"] == "slot_no_file"


def test_recheck_on_a_revised_assigned_material_points_the_slot_back_and_confirms(env):
    ad = env["ads"][0]
    placement = assign_confirmed(env, ad, user_asset(env))
    # Revised outside the slot flow (no re-pointing): the slot waits for the user's check.
    user_assets.revise(
        env["conn"], env["org"], env["brand"], env["campaign"], placement["id"], 1,
        {"copy_fields": {**COPY, "body": "新版"}, "purpose": "產品介紹"}, "human",
    )
    env["conn"].commit()
    assert by_ad(read(env))[ad]["waiting"]["action"] == "confirm_copy"
    response = TestClient(app).post(f"{base(env)}/slots/{ad}/recheck")
    assert response.status_code == 200, response.text
    slot = by_ad(response.json()["slots"])[ad]
    assert (slot["state"], slot["copy"]) == (
        "ready", placement_copy("已確認", {**COPY, "body": "新版"}),
    )
    row = campaigns.get_ad(env["conn"], env["org"], env["brand"], ad)
    assert (row["material_placement_id"], row["material_placement_revision"]) == (
        placement["id"], 2,
    )
    assert row["slot_placement_id"] is None


def test_a_set_being_generated_is_in_progress_with_its_copy_job(env):
    ad = env["ads"][0]
    workbench_copy(env, ad, adopt=False)
    with brief_status("running"):
        slot = by_ad(read(env))[ad]
    assert (slot["state"], slot["waiting"]) == ("in_progress", None)
    assert slot["job"] == {"kind": "copy", "done": None, "of": None}
    assert slot["workbench_href"]


def test_a_generated_set_with_nothing_selected_waits_for_the_user_on_the_workbench(env):
    ad = env["ads"][0]
    workbench_copy(env, ad, adopt=False)
    with brief_status("done"):
        slot = by_ad(read(env))[ad]
    assert (slot["state"], slot["job"], slot["copy"]) == ("waiting", None, None)
    assert slot["waiting"] == {"action": "pick_on_workbench", "text": "等你：到工作檯選定一版文案"}


def test_an_unconfirmed_slot_placement_with_a_ready_original_waits_for_confirmation(env):
    conn, ad = env["conn"], env["ads"][0]
    placement = user_assets.attach(
        conn, env["org"], env["brand"], env["campaign"], user_asset(env), COPY, "human",
        ad_id=ad,
    )
    conn.execute("UPDATE ads_ad SET slot_placement_id=%s WHERE id=%s", (placement["id"], ad))
    conn.commit()
    slot = by_ad(read(env))[ad]
    assert (slot["state"], slot["blocked"], slot["job"]) == ("waiting", None, None)
    assert slot["waiting"] == {"action": "confirm_copy", "text": "等你：確認這版文案"}
    assert slot["copy"] == placement_copy("待確認")
    assert slot["thumbnail_url"] == thumb(env, placement["asset_id"])


def test_a_pending_original_is_in_progress_with_its_preview_job(env):
    ad = env["ads"][0]
    workbench_copy(env, ad)  # a selected copy does not outrank the running preview
    result = upload(env, ad, {"asset_id": user_asset(env, status="pending", thumbnail=False)})
    slot = by_ad(result["slots"])[ad]
    assert (slot["state"], slot["waiting"], slot["blocked"]) == ("in_progress", None, None)
    assert slot["job"] == {"kind": "preview", "done": None, "of": None}
    assert slot["copy"] == placement_copy("待確認", WORKBENCH_COPY)
