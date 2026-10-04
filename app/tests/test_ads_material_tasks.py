"""Material provenance persists independently of model generation and platform action."""

from unittest.mock import Mock, patch

import pytest
from fastapi.testclient import TestClient

from app import workbench
from app.ads import assets as legacy_assets
from app.ads import external_repository
from app.ads import material_tasks as tasks
from app.ads import repository as ads
from app.ads import user_assets_repository as assets
from app.brand_intelligence import repository as brands
from app.core import db
from app.main import app


@pytest.fixture
def setup(monkeypatch):
    enqueue = Mock(return_value=True)
    monkeypatch.setattr("app.background.enqueue", enqueue)
    conn = db.current()
    org = db.DEV_ORG_ID
    brand = brands.create_brand(
        conn, org_id=org, name="虛構素材來源商店", client_name=None, actor="test"
    )["id"]
    campaign = ads.create_campaign(
        conn,
        org,
        brand,
        {
            "name": "虛構新活動",
            "goal_text": "觀察素材",
            "objective": "購買",
            "target_cost": 100,
            "start_date": "2026-09-01",
            "end_date": "2026-09-30",
            "status": "draft",
        },
        created_by="test",
    )["id"]
    conn.commit()
    return conn, org, brand, campaign, enqueue


def asset(setup, label="image", brand=None):
    conn, org, own_brand, _, _ = setup
    aid = db.new_id("aua")
    conn.execute(
        "INSERT INTO ads_user_asset(id,org_id,brand_id,sha256,storage_key,filename,"
        "mime_type,byte_size,status) VALUES(%s,%s,%s,%s,%s,%s,'image/png',100,'ready')",
        (aid, org, brand or own_brand, aid, "fixture/" + aid, label + ".png"),
    )
    conn.commit()
    return aid


def create(setup, mode="external_image", **fields):
    conn, org, brand, campaign, _ = setup
    return tasks.create(
        conn,
        org,
        brand,
        campaign,
        {
            "operation_id": db.new_id("op"),
            "title": "下一輪素材",
            "mode": mode,
            **fields,
        },
        "test",
    )


def change(setup, task, action, **fields):
    conn, org, brand, campaign, _ = setup
    return tasks.mutate(
        conn,
        org,
        brand,
        campaign,
        task["id"],
        {
            "operation_id": db.new_id("op"),
            "expected_revision": task["revision"],
            **fields,
        },
        action,
        "test",
    )


def test_existing_assets_never_force_generation_and_history_keeps_prompt_reference_chain(setup):
    conn, org, brand, campaign, enqueue = setup
    reference, image = asset(setup, "R"), asset(setup, "I7")
    task = create(setup, "existing", copy_fields={"body": "自帶原文"})
    prompt = {"source": "manual", "text": "P2 原始提示詞", "origin": "使用者提供"}
    gathered = change(
        setup, task, "candidates", asset_ids=[image], prompt=prompt, reference_asset_ids=[reference]
    )
    chosen = change(
        setup,
        gathered,
        "select",
        content_hash=gathered["content_hash"],
        candidate_id=gathered["candidates"][0]["id"],
    )
    assert chosen["placement_current"] is True
    assert chosen["candidates"][0]["prompt"]["text"] == "P2 原始提示詞"
    assert chosen["candidates"][0]["reference_asset_ids"] == [reference]
    assert assets.placement(conn, org, brand, campaign, chosen["placement_id"])["copy_fields"] == {
        "body": "自帶原文",
    }
    revised = change(setup, chosen, "update", prompt={"source": "manual", "text": "P3 新提示詞"})
    assert revised["selected_candidate_id"] is None
    assert revised["candidates"][0]["prompt"]["text"] == "P2 原始提示詞"
    old = tasks.get(conn, org, brand, campaign, task["id"], chosen["revision"])
    assert old["selected_candidate_id"] == chosen["selected_candidate_id"]
    assert old["placement_revision"] == 1
    assert task["id"] == revised["id"]
    enqueue.assert_not_called()


def test_operation_replays_and_mismatched_content_rejected(setup):
    conn, org, brand, campaign, enqueue = setup
    payload = {"operation_id": "same_operation", "title": "原始任務", "mode": "existing"}
    first = tasks.create(conn, org, brand, campaign, payload, "test")
    assert tasks.create(conn, org, brand, campaign, payload, "test")["id"] == first["id"]
    with pytest.raises(ValueError, match="同一次操作"):
        tasks.create(conn, org, brand, campaign, {**payload, "title": "改過內容"}, "test")
    another = tasks.create(
        conn, org, brand, campaign, {**payload, "operation_id": "another"}, "test"
    )
    assert another["content_hash"] == first["content_hash"]
    candidate_payload = {"operation_id": "add", "expected_revision": 1, "asset_ids": [asset(setup)]}
    added = tasks.mutate(
        conn, org, brand, campaign, first["id"], candidate_payload, "candidates", "test"
    )
    replay = tasks.mutate(
        conn, org, brand, campaign, first["id"], candidate_payload, "candidates", "test"
    )
    assert replay["revision"] == added["revision"] == 2
    assert replay["candidates"] == added["candidates"]
    enqueue.assert_not_called()


def test_missing_batch_provenance_is_unknown_and_multiple_batches_are_retained(setup):
    task = create(setup, prompt={"source": "manual", "text": "任務預設不代表每張圖確實使用"})
    ids = [asset(setup, str(i)) for i in range(11)]
    first = change(setup, task, "candidates", asset_ids=ids[:10])
    second = change(setup, first, "candidates", asset_ids=ids[10:])
    assert len(second["candidates"]) == 11
    assert all(c["prompt"] == {"source": "none", "text": None} for c in second["candidates"])
    assert all(c["reference_asset_ids"] == [] for c in second["candidates"])
    assert second["candidates"][:10] == first["candidates"]
    with pytest.raises(ValueError, match="一至十"):
        change(setup, second, "candidates", asset_ids=ids)


def test_foreign_assets_brand_campaign_and_stale_revision_rejected(setup):
    conn, org, brand, campaign, _ = setup
    other = brands.create_brand(
        conn, org_id=org, name="虛構另一品牌", client_name=None, actor="test"
    )["id"]
    foreign = asset(setup, brand=other)
    task = create(setup)
    with pytest.raises(ValueError, match="找不到品牌原檔"):
        change(setup, task, "candidates", asset_ids=[foreign])
    with pytest.raises(ValueError, match="找不到"):
        tasks.get(conn, org, other, campaign, task["id"])
    with pytest.raises(ValueError, match="找不到"):
        tasks.get(conn, "org_other", brand, campaign, task["id"])
    updated = change(setup, task, "update", instruction="新的指示")
    with pytest.raises(ValueError, match="已更新"):
        change(setup, task, "update", instruction="舊版延遲保存")
    assert tasks.get(conn, org, brand, campaign, task["id"])["revision"] == updated["revision"]


def test_selection_requires_exact_content_hash_and_detects_later_placement_revision(setup):
    conn, org, brand, campaign, _ = setup
    task = change(setup, create(setup), "candidates", asset_ids=[asset(setup)])
    with pytest.raises(ValueError, match="內容已改變"):
        change(
            setup,
            task,
            "select",
            content_hash="not-the-content",
            candidate_id=task["candidates"][0]["id"],
        )
    selected = change(
        setup,
        task,
        "select",
        content_hash=task["content_hash"],
        candidate_id=task["candidates"][0]["id"],
    )
    assets.revise(
        conn,
        org,
        brand,
        campaign,
        selected["placement_id"],
        1,
        {"copy_fields": {"body": "後續編輯"}},
        "test",
    )
    conn.commit()
    assert tasks.get(conn, org, brand, campaign, task["id"])["placement_current"] is False
    assert selected["placement_revision"] == 1


def test_dispatch_new_packs_for_imported_campaign_without_disturbing_original_pack(setup):
    conn, org, brand, campaign, enqueue = setup
    old_pack = workbench.submit_pack(
        conn,
        org,
        brand,
        {
            "source_kind": "schedule_node",
            "source_ref": {"ads_campaign_id": campaign},
            "name": "舊包",
            "sets": [
                {
                    "name": "舊素材",
                    "source_ref": {"ads_campaign_id": campaign},
                    "required_outputs": {"copy": 1},
                }
            ],
        },
    )
    conn.execute("UPDATE ads_campaign SET origin='imported' WHERE id=%s", (campaign,))
    conn.commit()
    enqueue.reset_mock()
    task = create(setup, "copy", instruction="保留圖片，只寫文案")
    enqueue.assert_not_called()
    payload = {
        "operation_id": "dispatch_once",
        "expected_revision": 1,
        "content_hash": task["content_hash"],
    }
    dispatched = tasks.dispatch(conn, org, brand, campaign, task["id"], payload, "test")
    assert dispatched["dispatch_status"] == "queued"
    assert dispatched["approved_hash"] == task["content_hash"]
    assert dispatched["pack_id"] != old_pack
    assert legacy_assets.pack_id(conn, org, brand, campaign) == old_pack
    assert enqueue.call_count == 1
    assert enqueue.call_args.kwargs["part"] == "copy"
    again = tasks.dispatch(conn, org, brand, campaign, task["id"], payload, "test")
    assert again["pack_id"] == dispatched["pack_id"]
    tasks.dispatch(
        conn, org, brand, campaign, task["id"], {**payload, "operation_id": "another"}, "test"
    )
    assert enqueue.call_count == 1
    new = change(setup, task, "update", instruction="第二輪，不同假設")
    second = tasks.dispatch(
        conn,
        org,
        brand,
        campaign,
        task["id"],
        {
            "operation_id": "next",
            "expected_revision": 2,
            "content_hash": new["content_hash"],
        },
        "test",
    )
    assert second["pack_id"] not in {old_pack, dispatched["pack_id"]}
    assert tasks.get(conn, org, brand, campaign, task["id"], 1)["pack_id"] == dispatched["pack_id"]


def test_enqueue_failure_is_unknown_and_a_second_dispatch_starts_the_same_pack_once(setup):
    """F49 Contract T (audit W10 #11): a failed enqueue is not a success with a dead button --
    the revision reads `unknown` 「交棒沒送出・可重試」, and the next dispatch starts that same
    pack (never a second one) exactly once."""
    conn, org, brand, campaign, enqueue = setup
    task = create(setup, "workbench_image")
    payload = {
        "operation_id": "dispatch_unknown",
        "expected_revision": 1,
        "content_hash": task["content_hash"],
    }
    enqueue.side_effect = RuntimeError("fixture unavailable")
    result = tasks.dispatch(conn, org, brand, campaign, task["id"], payload, "test")
    assert result["dispatch_status"] == "unknown"
    assert result["state_label"] == "交棒沒送出・可重試"
    assert result["pack_id"]
    assert enqueue.call_count == 1
    # The set went back to idle: nothing was queued.
    (brief,) = workbench.briefs_for_source(
        conn, org, brand, "schedule_node", {"material_task_id": task["id"]}
    )
    assert brief["status"] == "idle"

    enqueue.side_effect = None
    retried = tasks.dispatch(
        conn, org, brand, campaign, task["id"], {**payload, "operation_id": "retry"}, "test"
    )
    assert (retried["dispatch_status"], retried["state_label"]) == ("queued", "工作檯製作中")
    assert retried["pack_id"] == result["pack_id"]
    assert enqueue.call_count == 2
    # Queued now: neither a replay nor another dispatch enqueues it again.
    tasks.dispatch(conn, org, brand, campaign, task["id"], payload, "test")
    tasks.dispatch(
        conn, org, brand, campaign, task["id"], {**payload, "operation_id": "third"}, "test"
    )
    assert enqueue.call_count == 2
    assert len(workbench.briefs_for_source(
        conn, org, brand, "schedule_node", {"material_task_id": task["id"]}
    )) == 1


def test_a_replayed_dispatch_retries_an_unknown_hand_off_too(setup):
    conn, org, brand, campaign, enqueue = setup
    task = create(setup, "copy")
    payload = {
        "operation_id": "same_click",
        "expected_revision": 1,
        "content_hash": task["content_hash"],
    }
    enqueue.side_effect = RuntimeError("fixture unavailable")
    first = tasks.dispatch(conn, org, brand, campaign, task["id"], payload, "test")
    assert first["dispatch_status"] == "unknown"
    enqueue.side_effect = None
    replay = tasks.dispatch(conn, org, brand, campaign, task["id"], payload, "test")
    assert (replay["dispatch_status"], replay["pack_id"]) == ("queued", first["pack_id"])
    assert enqueue.call_count == 2


def test_material_task_labels_follow_the_hand_off_and_the_pack(setup):
    """F49 Contract T: not handed off, made on the workbench, the workbench failed -- each its own
    label (they all read 「等素材工作檯」 before)."""
    conn, org, brand, campaign, _ = setup
    task = create(setup, "workbench_image")
    assert task["state_label"] == "還沒交棒"
    dispatched = tasks.dispatch(
        conn, org, brand, campaign, task["id"],
        {"operation_id": db.new_id("op"), "expected_revision": 1,
         "content_hash": task["content_hash"]},
        "test",
    )
    assert dispatched["state_label"] == "工作檯製作中"
    real = workbench.briefs_for_source

    def failed(*args, **kwargs):
        return [{**b, "status": "failed", "last_error": "逾時"} for b in real(*args, **kwargs)]

    with patch.object(workbench, "briefs_for_source", side_effect=failed):
        assert tasks.get(conn, org, brand, campaign, task["id"])["state_label"] == "工作檯沒做成"
    gathered = change(setup, tasks.get(conn, org, brand, campaign, task["id"]), "candidates",
                      asset_ids=[asset(setup)])
    assert gathered["state_label"] == "有候選圖"
    chosen = change(setup, gathered, "select", content_hash=gathered["content_hash"],
                    candidate_id=gathered["candidates"][0]["id"])
    assert chosen["state_label"] == "已採用"


def test_workbench_version_source_uses_public_canonical_text_not_client_text(setup, monkeypatch):
    conn, org, brand, campaign, _ = setup
    task = create(setup)
    canonical = {
        "source": "workbench",
        "set_id": "saved-set",
        "version_id": "saved-version",
        "part": "image_prompt",
        "pack_id": "saved-pack",
        "card_index": 0,
        "text": "伺服器保存的P2",
    }
    options_reader = Mock(return_value=[canonical])
    source_reader = Mock(return_value=canonical)
    monkeypatch.setattr(workbench, "material_options", options_reader)
    monkeypatch.setattr(workbench, "material_source", source_reader)
    options = tasks.prompt_options(conn, org, brand, campaign, task["id"])["options"]
    assert options[0]["text"] == "伺服器保存的P2"
    assert options[0]["set_id"] == canonical["set_id"]
    options_reader.assert_called_once_with(conn, org, brand, part="image_prompt")
    updated = change(
        setup,
        task,
        "update",
        prompt={
            "source": "workbench",
            "set_id": canonical["set_id"],
            "version_id": canonical["version_id"],
            "text": "前端篡改不應採用",
        },
    )
    assert updated["prompt"]["text"] == "伺服器保存的P2"
    assert updated["prompt"]["version_id"] == canonical["version_id"]
    source_reader.assert_called_once_with(conn, org, brand, "saved-set", "saved-version", None)
    assert tasks.get(conn, org, brand, campaign, task["id"], 1)["prompt"]["source"] == "none"
    assert tasks.get(conn, org, brand, campaign, task["id"])["prompt"] == canonical
    source_reader.side_effect = ValueError("找不到此品牌的提示詞或文案版本。")
    with pytest.raises(ValueError, match="找不到"):
        change(
            setup,
            updated,
            "update",
            prompt={"source": "workbench", "set_id": "other_set", "version_id": "saved-version"},
        )


def test_recovery_selection_and_copy_edit_keep_existing_dispatch_identity(setup):
    conn, org, brand, campaign, enqueue = setup
    task = create(setup, "workbench_image", instruction="同一次圖片提示詞需求")
    dispatched = tasks.dispatch(
        conn,
        org,
        brand,
        campaign,
        task["id"],
        {
            "operation_id": "original_dispatch",
            "expected_revision": 1,
            "content_hash": task["content_hash"],
        },
        "test",
    )
    gathered = change(setup, dispatched, "candidates", asset_ids=[asset(setup)])
    selected = change(
        setup,
        gathered,
        "select",
        content_hash=gathered["content_hash"],
        candidate_id=gathered["candidates"][0]["id"],
    )
    updated = change(setup, selected, "update", copy_fields={"body": "只編輯選定文案"})
    again = tasks.dispatch(
        conn,
        org,
        brand,
        campaign,
        task["id"],
        {
            "operation_id": "later_dispatch",
            "expected_revision": updated["revision"],
            "content_hash": updated["content_hash"],
        },
        "test",
    )
    assert again["pack_id"] == gathered["pack_id"] == selected["pack_id"] == dispatched["pack_id"]
    assert again["dispatch_status"] == "queued"
    assert again["approved_hash"] == dispatched["approved_hash"]
    assert enqueue.call_count == 1


def test_review_hypothesis_and_prefixed_sources_are_preserved_in_next_pack(setup):
    conn, org, brand, campaign, enqueue = setup
    ad = external_repository.upsert_entity(
        conn,
        org,
        brand,
        campaign,
        {
            "platform": "fixture",
            "source_account": "fixture",
            "native_kind": "ad",
            "native_id": "original-ad",
            "native_status": "ACTIVE",
            "currency": "TWD",
            "creative": {"kind": "image", "fields": {"body": "原廣告"}},
        },
    )
    evidence = {
        "sources": [{"id": "S1", "text": "原始證據原文"}, {"id": "S2", "text": "未引用"}],
        "limitations": ["樣本不足"],
        "provider": "fixture",
    }
    recommendation = {
        "id": "R1",
        "target_id": ad["id"],
        "recommendation": "new_test",
        "hypothesis": "待驗證的新假設",
        "next_step": "保留原圖調整描述",
        "risks": ["不能歸因"],
        "evidence_refs": ["source:S1", "commerce:current"],
    }
    conn.execute(
        "INSERT INTO ads_review_round(id,org_id,brand_id,campaign_id,entity_id,window_start,"
        "window_end,evidence_json,evidence_hash,result_json,status,created_by)"
        " VALUES('review-material',%s,%s,%s,%s,'2026-09-01','2026-09-02',%s,%s,%s,'ready','test')",
        (
            org,
            brand,
            campaign,
            ad["id"],
            db.jsonb(evidence),
            "source-hash",
            db.jsonb({"recommendations": [recommendation]}),
        ),
    )
    conn.commit()
    task = create(setup, "copy", review_id="review-material", recommendation_id="R1")
    assert task["review_context"]["sources"] == [evidence["sources"][0]]
    assert task["review_context"]["evidence_refs"] == recommendation["evidence_refs"]
    assert task["review_context"]["evidence_hash"] == "source-hash"
    enqueue.assert_not_called()
    dispatched = tasks.dispatch(
        conn,
        org,
        brand,
        campaign,
        task["id"],
        {
            "operation_id": "review-dispatch",
            "expected_revision": 1,
            "content_hash": task["content_hash"],
        },
        "test",
    )
    briefs = workbench.briefs_for_source(
        conn,
        org,
        brand,
        "schedule_node",
        {
            "material_task_id": task["id"],
            "material_revision": 1,
            "campaign_id": campaign,
            "review_id": "review-material",
            "recommendation_id": "R1",
        },
    )
    assert briefs[0]["pack_id"] == dispatched["pack_id"]
    assert "待驗證的新假設" in briefs[0]["request_json"]["free_text"]
    assert "原始證據原文" in briefs[0]["request_json"]["free_text"]
    assert "未引用" not in briefs[0]["request_json"]["free_text"]
    with pytest.raises(ValueError, match="請選擇"):
        create(setup, "copy", review_id="review-material", recommendation_id="wrong")


def test_api_saves_reopens_and_rejects_unknown_fields_without_generation(setup):
    _, _, brand, campaign, enqueue = setup
    client = TestClient(app)
    url = f"/api/ads/brands/{brand}/campaigns/{campaign}/material-tasks"
    saved = client.post(
        url, json={"operation_id": "api-save", "title": "API 原始素材", "mode": "existing"}
    )
    assert saved.status_code == 200, saved.text
    value = saved.json()["task"]
    assert client.get(url + "/" + value["id"]).json()["task"]["prompt"]["source"] == "none"
    assert client.get(url).json()["tasks"][0]["id"] == value["id"]
    assert (
        client.post(
            url,
            json={"operation_id": "api-bad", "title": "錯誤", "mode": "existing", "publish": True},
        ).status_code
        == 422
    )
    enqueue.assert_not_called()


def test_public_copy_version_is_preserved_until_explicit_manual_revision(setup, monkeypatch):
    conn, org, brand, _, enqueue = setup
    canonical = {
        "source": "workbench",
        "set_id": "copy-set",
        "version_id": "copy-version",
        "part": "copy",
        "pack_id": "copy-pack",
        "card_index": None,
        "text": "保存的文案\n標題",
        "copy_fields": {"body": "保存的文案", "headline": "標題"},
    }
    source_reader = Mock(return_value=canonical)
    monkeypatch.setattr(workbench, "material_source", source_reader)
    task = create(
        setup,
        "copy",
        prompt={"source": "workbench", "set_id": "copy-set", "version_id": "copy-version"},
    )
    assert task["copy_fields"] == {"body": "保存的文案", "headline": "標題"}
    assert task["prompt"]["version_id"] == "copy-version"
    source_reader.assert_called_once_with(conn, org, brand, "copy-set", "copy-version", None)
    with pytest.raises(ValueError, match="不同於工作檯"):
        change(setup, task, "update", copy_fields={"body": "已手改文案"})
    edited = change(
        setup,
        task,
        "update",
        copy_fields={"body": "已手改文案"},
        prompt={
            "source": "manual",
            "text": "已手改文案",
            "origin": "改寫工作檯版本 copy-version",
        },
    )
    assert edited["prompt"]["source"] == "manual"
    assert "copy-version" in edited["prompt"]["origin"]
    original = tasks.get(conn, org, brand, setup[3], task["id"], 1)
    assert original["copy_fields"] == canonical["copy_fields"]
    assert original["prompt"]["version_id"] == "copy-version"
    assert edited["revision"] == 2
    enqueue.assert_not_called()


def ad_entity(setup, native_id, kind="ad", campaign=None, **extra):
    conn, org, brand, own_campaign, _ = setup
    entity = external_repository.upsert_entity(
        conn,
        org,
        brand,
        campaign or own_campaign,
        {
            "platform": "fixture",
            "source_account": "fixture",
            "native_kind": kind,
            "native_id": native_id,
            "native_status": "ACTIVE",
            "currency": "TWD",
            "name": "舊廣告 " + native_id,
            **extra,
        },
    )
    conn.commit()
    return entity


def replace(setup, entity_id, operation_id=None):
    conn, org, brand, campaign, _ = setup
    return tasks.create(
        conn,
        org,
        brand,
        campaign,
        {"operation_id": operation_id or db.new_id("op"), "replaces_entity_id": entity_id},
        "test",
    )


def cancel(setup, task):
    conn, org, brand, campaign, _ = setup
    return tasks.cancel(conn, org, brand, campaign, task["id"], "test")


def test_replace_request_binds_the_ad_with_one_click_defaults_and_repeat_returns_it(setup):
    conn, org, brand, campaign, enqueue = setup
    ad = ad_entity(
        setup, "old-ad", creative={"kind": "image", "fields": {"thumbnail_url": "https://t/1.jpg"}}
    )
    task = replace(setup, ad["id"])
    assert task["mode"] == "workbench_image"
    assert task["title"] == "換掉：舊廣告 old-ad"
    assert task["replaces"] == {
        "entity_id": ad["id"],
        "name": "舊廣告 old-ad",
        "thumbnail_url": "https://t/1.jpg",
    }
    assert task["cancelled_at"] is None
    again = replace(setup, ad["id"])
    assert again["id"] == task["id"]
    # A fuller request for the same open ad still returns the open one, not a second task.
    fuller = create(setup, "external_image", replaces_entity_id=ad["id"])
    assert fuller["id"] == task["id"]
    assert [t["id"] for t in tasks.workspace(conn, org, brand, campaign)["tasks"]] == [task["id"]]
    plain = create(setup)
    assert plain["replaces"] is None
    enqueue.assert_not_called()


def test_replace_request_operation_id_replays_and_refuses_changed_content(setup):
    first_ad, second_ad = ad_entity(setup, "a1"), ad_entity(setup, "a2")
    task = replace(setup, first_ad["id"], "replace-op")
    assert replace(setup, first_ad["id"], "replace-op")["id"] == task["id"]
    with pytest.raises(ValueError, match="同一次操作"):
        replace(setup, second_ad["id"], "replace-op")


def test_replace_request_refuses_foreign_non_ad_and_closed_campaign(setup):
    conn, org, brand, campaign, _ = setup
    other = ads.create_campaign(
        conn,
        org,
        brand,
        {
            "name": "虛構另一活動",
            "goal_text": "對照",
            "objective": "購買",
            "start_date": "2026-09-01",
            "end_date": "2026-09-30",
            "status": "draft",
        },
        created_by="test",
    )["id"]
    conn.commit()
    foreign = ad_entity(setup, "foreign-ad", campaign=other)
    with pytest.raises(ValueError, match="不屬於此品牌活動"):
        replace(setup, foreign["id"])
    adset = ad_entity(setup, "group-1", kind="adset")
    with pytest.raises(ValueError, match="一則廣告"):
        replace(setup, adset["id"])
    ad = ad_entity(setup, "closing-ad")
    conn.execute("UPDATE ads_campaign SET status='closed' WHERE id=%s", (campaign,))
    conn.commit()
    with pytest.raises(ValueError, match="已結案"):
        replace(setup, ad["id"])
    assert (
        conn.execute(
            "SELECT count(*) AS n FROM ads_material_task WHERE campaign_id=%s", (campaign,)
        ).fetchone()["n"]
        == 0
    )


def test_cancel_hides_the_task_frees_the_slot_and_keeps_history_readable(setup):
    conn, org, brand, campaign, _ = setup
    ad = ad_entity(setup, "cancel-ad")
    task = replace(setup, ad["id"])
    cancelled = cancel(setup, task)
    assert cancelled["cancelled_at"] is not None
    assert cancel(setup, task)["cancelled_at"] == cancelled["cancelled_at"]
    assert tasks.workspace(conn, org, brand, campaign)["tasks"] == []
    assert tasks.get(conn, org, brand, campaign, task["id"])["replaces"]["entity_id"] == ad["id"]
    with pytest.raises(ValueError, match="已取消"):
        change(setup, cancelled, "update", instruction="取消後不可再改")
    fresh = replace(setup, ad["id"])
    assert fresh["id"] != task["id"]
    assert [t["id"] for t in tasks.workspace(conn, org, brand, campaign)["tasks"]] == [fresh["id"]]


def test_cancel_refused_once_an_approved_change_set_uses_the_task(setup):
    conn, org, brand, campaign, _ = setup
    task = replace(setup, ad_entity(setup, "used-ad")["id"])

    def change_set(status):
        conn.execute(
            "INSERT INTO ads_change_set(id,org_id,brand_id,campaign_id,operation_id,request_hash,"
            "content_hash,title,month,status,plan_json,created_by)"
            " VALUES(%s,%s,%s,%s,%s,'h','h','換素材','2026-09',%s,%s,'test')",
            (
                db.new_id("acs"),
                org,
                brand,
                campaign,
                db.new_id("op"),
                status,
                db.jsonb({"items": [], "material_task_id": task["id"]}),
            ),
        )
        conn.commit()

    change_set("draft")
    change_set("rejected")
    other = replace(setup, ad_entity(setup, "free-ad")["id"])
    change_set("approved")
    with pytest.raises(tasks.InUse):
        cancel(setup, task)
    assert tasks.get(conn, org, brand, campaign, task["id"])["cancelled_at"] is None
    assert cancel(setup, other)["cancelled_at"] is not None


def test_api_one_click_replace_cancel_and_in_use_code(setup):
    conn, org, brand, campaign, _ = setup
    ad = ad_entity(setup, "api-ad")
    client = TestClient(app)
    url = f"/api/ads/brands/{brand}/campaigns/{campaign}/material-tasks"
    assert client.post(url, json={"operation_id": "api-missing"}).status_code == 422
    saved = client.post(url, json={"operation_id": "api-replace", "replaces_entity_id": ad["id"]})
    assert saved.status_code == 200, saved.text
    value = saved.json()["task"]
    assert value["replaces"]["entity_id"] == ad["id"]
    assert value["mode"] == "workbench_image"
    conn.execute(
        "INSERT INTO ads_change_set(id,org_id,brand_id,campaign_id,operation_id,request_hash,"
        "content_hash,title,month,status,plan_json,created_by)"
        " VALUES(%s,%s,%s,%s,'api-used','h','h','換素材','2026-09','approved',%s,'test')",
        (db.new_id("acs"), org, brand, campaign, db.jsonb({"material_task_id": value["id"]})),
    )
    conn.commit()
    refused = client.post(f"{url}/{value['id']}/cancel")
    assert refused.status_code == 409
    assert refused.json()["error"]["code"] == "material_task_in_use"
    free = client.post(url, json={"operation_id": "api-free", "title": "另一個", "mode": "copy"})
    done = client.post(f"{url}/{free.json()['task']['id']}/cancel")
    assert done.status_code == 200, done.text
    assert done.json()["task"]["cancelled_at"]
    assert [t["id"] for t in client.get(url).json()["tasks"]] == [value["id"]]
