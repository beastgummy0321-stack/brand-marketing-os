"""F30-I10 Contract F: the assets tab's slots and uploading a file into one planned ad's slot.

Readiness is the launch snapshot's rule (a confirmed assignment), a file uploaded into a slot
waits until its placement is confirmed and is then assigned to that planned ad, a launched
app-built ad carries its platform ad and that ad's replace request, an imported campaign's slots
are its live platform ads, and the open replace requests are listed with their own state.

F35 Contract T: each planned slot carries its copy half (`copy`) and `workbench_href`; a file
uploaded into a slot carries the ad's selected workbench copy in, fills the purpose with the
ad's name, confirms and assigns in the same call; a slot with a file but no copy takes one of
the brand's workbench copy versions through `POST …/slots/{ad}/copy`.
"""

from datetime import timedelta
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app import workbench
from app.ads import (
    assets as legacy_assets,
)
from app.ads import (
    change_control_data,
    change_control_launch,
    external_repository,
    handoff_assignment,
    material_tasks,
    slots,
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
    }
    # Uploaded, its original still pending: not confirmable yet, so not launchable and not
    # assigned (material stays confirmed-only); the copy half shows what came with the file.
    assert slot[uploaded_ad]["state"] == "in_progress"
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
    assert {a: s["state"] for a, s in by_ad(view).items()} == {
        ready_ad: "ready", env["ads"][1]: "in_progress", env["ads"][2]: "in_progress",
    }
    assert view["ready"] == 1


def test_a_revised_assignment_is_in_progress_not_ready(env):
    ad = env["ads"][0]
    placement = assign_confirmed(env, ad, user_asset(env))
    user_assets.revise(
        env["conn"], env["org"], env["brand"], env["campaign"], placement["id"], 1,
        {"copy_fields": {**COPY, "body": "新版"}}, "human",
    )
    env["conn"].commit()
    assert by_ad(read(env))[ad]["state"] == "in_progress"


# -- upload into a slot ---------------------------------------------------------------------------


def test_upload_waits_for_confirmation_then_assigns_the_confirmed_revision(env):
    """A placement the program cannot confirm (its copy misses a field) waits in the slot; the
    slot follows the placement id through the user's revision and confirmation."""
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
    assert (slot["state"], slot["thumbnail_url"]) == ("in_progress", thumb(env, asset))
    assert slot["copy"] == placement_copy("待確認", {**partial, "description": None})

    # Completing the copy is a new revision: the slot follows the id.
    revised = client.patch(
        f"{base(env)}/placements/{placement['id']}",
        json={"expected_revision": 1, "copy_fields": COPY},
    )
    assert revised.status_code == 200, revised.text
    assert revised.json()["placement"]["revision"] == 2
    assert by_ad(client.get(f"{base(env)}/slots").json())[ad]["state"] == "in_progress"

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


def test_pending_placement_with_zero_known_budget_stays_in_progress(env):
    """The confirmation is refused by `pending_reasons` (a zero platform budget): the slot keeps
    waiting with its copy shown, never ready."""
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
    assert (slot["state"], slot["confirmed"]) == ("in_progress", False)
    assert slot["copy"] == placement_copy("待確認", WORKBENCH_COPY)
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
        "format_key": None,
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
    so unconfirmed) copy -- two current placements keyed by ad, two `slot_placement_id`s, one
    shared thumbnail; the same ad with other copy is still the one conflict."""
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
    assert (slot[first_ad]["state"], slot[second_ad]["state"]) == ("in_progress", "in_progress")
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
