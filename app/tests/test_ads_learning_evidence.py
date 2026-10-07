"""Additive wire contracts preserve unknown history and explicit selected scope."""

from datetime import date
from unittest.mock import Mock, patch

from app.ads import ads_learnings, learning_rank
from app.workbench import encode_learning_scope


def legacy(identity="one", product="A"):
    return {
        "id": identity,
        "org_id": "org",
        "brand_id": "brand",
        "product_id": product,
        "learning_text": "Actual retained meaning",
        "applicability_scope": "ads",
        "source_cycle_id": identity,
        "confidence": "validated",
        "needs_revalidation": False,
    }


def test_full_projection_field_map_and_capped_context():
    conn = Mock()
    with (
        patch.object(
            ads_learnings.bi_repo, "get_product", return_value={"id": "A", "name": "Selected"}
        ),
        patch.object(ads_learnings.coresettings, "today_for_org", return_value=date(2026, 10, 8)),
    ):
        context = ads_learnings.evidence_context(
            conn, "org", "brand", "A", rows=[legacy("one"), legacy("two")], cap=1
        )
    assert set(context) == {
        "schema_version",
        "revision",
        "scope_product_id",
        "scope_label",
        "eligible_count",
        "items",
        "omitted",
    }
    assert context["scope_product_id"] == "A"
    assert context["scope_label"] == "Selected"
    assert context["omitted"] == 1
    assert context["eligible_count"] == 0
    item = context["items"][0]
    assert set(item) == {
        "schema_version",
        "id",
        "meaning_revision",
        "display_text",
        "support_label",
        "provenance",
        "sources",
        "scope",
        "conditions",
        "sample",
        "independent_count",
        "same_direction_count",
        "contrary_count",
        "use_state",
        "reason_codes",
        "reason_labels",
        "allowed_uses",
        "limits",
    }
    assert set(item["scope"]) == {
        "product_id",
        "product_label",
        "audience_key",
        "customer_group_id",
        "claim_key",
        "claim_family",
        "objective_family",
        "result_kind",
        "currency",
        "attribution",
    }
    assert set(item["conditions"]) == {
        "price_version",
        "offer_key",
        "offer_version",
        "material_version",
        "target_version",
        "valid_until",
    }
    assert item["display_text"] == "Actual retained meaning"
    assert item["sample"] == {"result_events": None, "sufficient": None}
    assert item["scope"]["product_id"] == "A"
    assert item["provenance"] == "unknown"
    assert "conditions_unknown" in item["limits"]


def test_unknown_deleted_scope_and_empty_items_are_explicit():
    with (
        patch.object(ads_learnings.bi_repo, "get_product", return_value=None),
        patch.object(ads_learnings.coresettings, "today_for_org", return_value=date(2026, 10, 8)),
    ):
        unknown = ads_learnings.evidence_context(Mock(), "org", "brand", "deleted", rows=[legacy()])
        empty = ads_learnings.evidence_context(Mock(), "org", "brand", None, rows=[])
    assert unknown["scope_product_id"] is None
    assert unknown["scope_label"] is None
    assert unknown["items"][0]["use_state"] == "excluded"
    assert "scope_required" in unknown["items"][0]["reason_codes"]
    assert empty["items"] == []
    assert empty["eligible_count"] == empty["omitted"] == 0
    assert empty["revision"]


def test_coordinate_v2_parser_preserves_numbers_with_valid_and_invalid_trailer():
    base = (
        "coord；v=2；verdict=keep；rank=1；of=1；sales=10；spend=2000；cpr=200；cap=300；few=0"
        "；group=none；audience=cold；pain=p；angle=a；hook=h；proof=none；offer=none"
        "；format=single_image；cur=TWD"
    )
    original = learning_rank.parse_scope(base)
    assert original is not None
    assert learning_rank.parse_scope(encode_learning_scope(base, {})) == original
    assert learning_rank.parse_scope(base + "\n@evidence-v1:{broken") == original
