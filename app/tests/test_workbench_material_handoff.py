"""Real workbench source seams own their saved-output fixtures and tenant checks."""

from unittest.mock import Mock

import pytest

from app import workbench
from app.brand_intelligence import repository as brands
from app.core import db
from app.workbench import repository


@pytest.fixture
def setup(monkeypatch):
    enqueue = Mock(return_value=True)
    monkeypatch.setattr("app.background.enqueue", enqueue)
    conn, org = db.current(), db.DEV_ORG_ID
    brand = brands.create_brand(
        conn, org_id=org, name="工作檯來源邊界", client_name=None, actor="test"
    )["id"]
    conn.commit()
    return conn, org, brand, enqueue


def prepare(setup, part):
    conn, org, brand, _ = setup
    payload = {
        "source_ref": {"material_fixture": db.new_id("fixture")},
        "name": "精確素材來源",
        "sets": [{"name": "保存版本", "required_outputs": {part: 1}}],
    }
    pack = workbench.prepare_material_pack(conn, org, brand, payload)
    assert workbench.prepare_material_pack(conn, org, brand, payload) == pack
    briefs = workbench.briefs_for_source(conn, org, brand, "schedule_node", payload["source_ref"])
    assert len(briefs) == 1
    assert briefs[0]["status"] == "idle"
    assert briefs[0]["pack_id"] == pack
    return pack, briefs[0]


def save(setup, brief, part, body):
    conn, org, brand, _ = setup
    return repository.write_output(
        conn,
        org_id=org,
        brand_id=brand,
        brief_id=brief["id"],
        part=part,
        generation_round=1,
        body_json=body,
        coordinates_json=None,
        llm_task_id=None,
    )


def test_prepared_pack_is_idle_and_image_source_uses_exact_saved_text(setup):
    conn, org, brand, enqueue = setup
    pack, brief = prepare(setup, "image_prompt")
    output = save(
        setup,
        brief,
        "image_prompt",
        {"title": "P2", "text": "伺服器保存的P2\n第二行", "prompt": "舊欄位不採用"},
    )
    options = workbench.material_options(conn, org, brand, part="image_prompt")
    selected = next(row for row in options if row["version_id"] == output["id"])
    assert selected["text"] == "伺服器保存的P2\n第二行"
    assert selected["set_id"] == brief["id"]
    source = workbench.material_source(conn, org, brand, brief["id"], output["id"])
    assert source["text"] == selected["text"]
    assert source["version_id"] == output["id"]
    assert source["part"] == "image_prompt"
    assert source["pack_id"] == pack
    with pytest.raises(ValueError, match="找不到"):
        workbench.material_source(conn, org, brand, "other-set", output["id"])
    with pytest.raises(ValueError, match="找不到這張"):
        workbench.material_source(conn, org, brand, brief["id"], output["id"], 999)
    enqueue.assert_not_called()


def test_copy_options_and_exact_version_remain_distinct_without_generation(setup):
    conn, org, brand, enqueue = setup
    pack, brief = prepare(setup, "copy")
    body = {
        "sets": [
            {"body": "第一版文案", "headline": "第一版標題"},
            {"body": "第二版文案", "headline": "第二版標題", "description": "第二版說明"},
        ]
    }
    outputs = save(setup, brief, "copy", [body, body])
    options = workbench.material_options(conn, org, brand, part="copy")
    assert {o["version_id"] for o in options} == {o["id"] for o in outputs}
    first = workbench.material_source(conn, org, brand, brief["id"], outputs[0]["id"])
    second = workbench.material_source(conn, org, brand, brief["id"], outputs[1]["id"])
    assert first["copy_fields"] == {"body": "第一版文案", "headline": "第一版標題"}
    assert first["text"] == "第一版文案\n第一版標題"
    assert second["copy_fields"] == {
        "body": "第二版文案",
        "headline": "第二版標題",
        "description": "第二版說明",
    }
    assert second["text"] == "第二版文案\n第二版標題\n第二版說明"
    assert first["pack_id"] == second["pack_id"] == pack
    assert first["card_index"] is None
    assert workbench.material_options(conn, org, brand, part="image_prompt") == []
    enqueue.assert_not_called()


def test_saved_material_sources_reject_wrong_brand_and_tenant(setup):
    conn, org, brand, enqueue = setup
    _, brief = prepare(setup, "copy")
    output = save(setup, brief, "copy", {"sets": [{"body": "品牌內部文案"}]})
    other = brands.create_brand(conn, org_id=org, name="另一品牌", client_name=None, actor="test")[
        "id"
    ]
    assert workbench.material_options(conn, org, other) == []
    with pytest.raises(ValueError, match="找不到"):
        workbench.material_source(conn, org, other, brief["id"], output["id"])
    with pytest.raises(ValueError, match="找不到品牌"):
        workbench.material_options(conn, "org_other", brand)
    with pytest.raises(ValueError, match="找不到品牌"):
        workbench.material_source(conn, "org_other", brand, brief["id"], output["id"])
    with pytest.raises(ValueError, match="找不到品牌"):
        workbench.prepare_material_pack(
            conn,
            "org_other",
            brand,
            {
                "source_ref": {"test": "foreign"},
                "name": "拒絕跨租戶",
                "sets": [{"name": "文案", "required_outputs": {"copy": 1}}],
            },
        )
    enqueue.assert_not_called()


def test_copy_options_narrow_to_one_sell_way_and_none_keeps_the_brand_list(setup):
    """F49 Contract T: a campaign's copy picker lists its own sell-way's copy only."""
    conn, org, brand, _ = setup
    ours = brands.create_product(conn, brand, name="晨光軟糖", actor="test")["id"]
    theirs = brands.create_product(conn, brand, name="午後花茶", actor="test")["id"]
    saved = {}
    for product in (ours, theirs, None):
        payload = {
            "source_ref": {"material_fixture": db.new_id("fixture")},
            "name": "賣法文案",
            "sets": [{"name": "文案", "required_outputs": {"copy": 1}, "product_id": product}],
        }
        workbench.prepare_material_pack(conn, org, brand, payload)
        (brief,) = workbench.briefs_for_source(
            conn, org, brand, "schedule_node", payload["source_ref"]
        )
        assert brief["product_id"] == product
        saved[product] = save(setup, brief, "copy", {"sets": [{"body": f"{product} 的文案"}]})
    narrowed = workbench.material_options(conn, org, brand, part="copy", product_id=ours)
    assert [o["version_id"] for o in narrowed] == [saved[ours]["id"]]
    every = workbench.material_options(conn, org, brand, part="copy")
    assert {o["version_id"] for o in every} == {row["id"] for row in saved.values()}


def test_a_failed_enqueue_leaves_the_set_idle_so_the_same_pack_starts_on_retry(setup):
    conn, org, brand, enqueue = setup
    pack, brief = prepare(setup, "copy")
    enqueue.side_effect = RuntimeError("queue down")
    with pytest.raises(RuntimeError):
        workbench.start_material_pack(conn, org, brand, pack)
    (after,) = workbench.briefs_for_source(conn, org, brand, "schedule_node", brief["source_ref"])
    assert after["status"] == "idle"
    enqueue.side_effect = None
    assert workbench.start_material_pack(conn, org, brand, pack) == "idle"
    # queued now: never restarted
    assert workbench.start_material_pack(conn, org, brand, pack) == "queued"
    (queued,) = workbench.briefs_for_source(conn, org, brand, "schedule_node", brief["source_ref"])
    assert queued["status"] == "queued"
    assert enqueue.call_count == 2


def test_a_failed_set_is_restarted_once_on_the_same_pack_keeping_its_versions(setup):
    """F50 Contract J (intake #22): `start` returns the status it found and restarts a failed
    set on this same pack -- one enqueue, no second pack, saved versions and selections kept."""
    conn, org, brand, enqueue = setup
    pack, brief = prepare(setup, "copy")
    saved = save(setup, brief, "copy", {"sets": [{"body": "上一輪的文案"}]})
    repository.select_version_for_set(conn, org, brand, brief["id"], saved["id"])
    repository.mark_brief_failed(conn, org, brand, brief["id"], "上一輪失敗了。")

    assert workbench.start_material_pack(conn, org, brand, pack) == "failed"
    assert enqueue.call_count == 1
    assert enqueue.call_args.kwargs["lock"] == f"workbench:{brief['id']}:copy"
    assert workbench.start_material_pack(conn, org, brand, pack) == "queued"
    assert enqueue.call_count == 1
    (after,) = workbench.briefs_for_source(conn, org, brand, "schedule_node", brief["source_ref"])
    assert after["status"] == "queued"
    assert after["pack_id"] == pack
    adopted = workbench.adopted_output(conn, org, brand, brief["id"], "copy")
    assert adopted is not None and adopted["is_adopted"]
    assert adopted["id"] == saved["id"]
    for status in ("running", "done"):
        repository.mark_brief_status(conn, org, brand, brief["id"], status)
        assert workbench.start_material_pack(conn, org, brand, pack) == status
    assert enqueue.call_count == 1


def test_a_failed_restart_whose_enqueue_fails_stays_failed_with_its_reason(setup):
    conn, org, brand, enqueue = setup
    pack, brief = prepare(setup, "copy")
    repository.mark_brief_failed(conn, org, brand, brief["id"], "上一輪失敗了。")
    enqueue.side_effect = RuntimeError("queue down")
    with pytest.raises(RuntimeError):
        workbench.start_material_pack(conn, org, brand, pack)
    after = repository.get_brief(conn, org, brand, brief["id"])
    assert after is not None
    assert (after["status"], after["last_error"]) == ("failed", "上一輪失敗了。")
