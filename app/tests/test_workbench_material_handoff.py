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
