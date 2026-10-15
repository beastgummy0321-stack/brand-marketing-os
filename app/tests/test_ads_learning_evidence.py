"""Additive wire contracts preserve unknown history and explicit selected scope."""

import json
from copy import deepcopy
from datetime import UTC, date, datetime
from unittest.mock import Mock, patch
from zoneinfo import ZoneInfo

from app.ads import ads_learnings, learning_rank
from app.core import db
from app.workbench import encode_learning_scope, qualify_learning_evidence


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


def unknown_current(product):
    return {
        "org_id": "org",
        "brand_id": "brand",
        "product_id": product,
        "org_day": "2026-10-08",
        "mode": "real",
        "conditions": {},
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
            conn,
            "org",
            "brand",
            "A",
            rows=[legacy("one"), legacy("two")],
            cap=1,
            current=unknown_current("A"),
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
        unknown = ads_learnings.evidence_context(
            Mock(), "org", "brand", "deleted", rows=[legacy()], current=unknown_current(None)
        )
        empty = ads_learnings.evidence_context(
            Mock(), "org", "brand", None, rows=[], current=unknown_current(None)
        )
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


def retained_ad():
    return {
        "id": "ad",
        "campaign_id": "campaign",
        "audience_key": "cold",
        "customer_group_id": None,
        "angle_key": "convenience",
        "offer_key": "none",
        "live_creative_json": {
            "outputs": {},
            "evidence_conditions": {
                "price_version": "price",
                "target_version": "target",
                "offers": [],
            },
        },
    }


def observation(**changes):
    value = {
        "observation_id": "observation",
        "entity_id": "ad",
        "day": date(2026, 8, 1),
        "source": "graph",
        "result_kind": "purchase",
        "result_action": "omni_purchase",
        "result_attribution": "7d_click",
        "result_count": 10,
        "currency": "TWD",
        "attribution_key": "7d",
        "spend": 1000,
        "purchases": 10,
        "revenue": 10000,
        "impressions": 100,
        "clicks": 10,
        **changes,
    }
    value.setdefault("availability", {key: "available" if value.get(key) is not None else "unknown"
                                      for key in ("spend", "impressions", "clicks", "purchases",
                                                  "revenue", "result_count")})
    return value


def metadata(
    *,
    campaign_id="campaign",
    ad=None,
    rows=None,
    kind="campaign",
    start="2026-08-01",
    end="2026-08-10",
    direction="support",
):
    ad = retained_ad() if ad is None else ad
    campaign = {
        "id": campaign_id,
        "result_kind": "purchase",
        "origin": "internal",
        "context_json": {"product_ids": ["A"]},
        "groups": [{"ads": [ad]}],
    }
    with patch.object(ads_learnings.ads_repo, "campaign_objective_family", return_value="sales"):
        return ads_learnings.source_evidence(
            Mock(),
            "org",
            "brand",
            campaign,
            kind=kind,
            window={"start": start, "end": end},
            observations=[observation()] if rows is None else rows,
            claim_key=ads_learnings.message_claim(ad),
            direction=direction,
        )


def scoped_current(source):
    material = source["conditions"]["material_version"]
    materials = (
        json.loads(material.removeprefix("@pair-v1:"))
        if material and material.startswith("@pair-v1:")
        else []
    )
    return {
        "org_id": "org",
        "brand_id": "brand",
        "product_id": "A",
        "org_day": "2026-10-08",
        "audience_keys": ["cold"],
        "customer_group_ids": [],
        "mode": "real",
        **{k: source["scope"][k] for k in ("result_kind", "currency", "attribution")},
        "conditions": {
            "price_version": "price",
            "target_version": "target",
            "offers": [],
            "materials": [
                {"ad_id": side["ad_id"], "version": side["version"]} for side in materials
            ],
        },
    }


def projected(source, current=None):
    raw = {**legacy(), "applicability_scope": encode_learning_scope("ads", source)}
    return qualify_learning_evidence(
        [raw], current or scoped_current(source), min_result_events=10, max_age_days=180
    )


def test_retained_definitions_and_unknowns_survive_source_extraction():
    actual = metadata()
    assert actual["provenance"] == "platform_observation"
    assert actual["sample"]["result_events"] == 10
    assert actual["scope"]["currency"] == "TWD"
    assert '"action":"omni_purchase"' in actual["scope"]["attribution"]
    assert projected(actual)["items"][0]["allowed_uses"] == [
        "test",
        "retain_control",
        "market_support",
    ]
    for field in ("result_kind", "result_action", "result_attribution", "attribution_key"):
        unknown = metadata(rows=[observation(**{field: None})])
        assert unknown["scope"]["result_kind"] is None
        assert unknown["scope"]["attribution"] is None or field == "result_kind"
        assert projected(unknown)["items"][0]["allowed_uses"] == []
    mixed = metadata(rows=[observation(), observation(result_action="onsite_web_purchase")])
    assert mixed["scope"]["attribution"] is None
    assert projected(mixed)["items"][0]["use_state"] == "revalidation"


def test_simulation_unknown_source_and_unfrozen_price_cannot_be_market_proof():
    for source, expected in (("simulated", "simulation"), ("test", "unknown"), (None, "unknown")):
        result = metadata(rows=[observation(source=source)])
        assert result["provenance"] == expected
        assert "market_support" not in projected(result)["items"][0]["allowed_uses"]
    old = retained_ad()
    del old["live_creative_json"]["evidence_conditions"]
    historical = metadata(ad=old)
    assert historical["conditions"]["price_version"] is None
    assert projected(historical)["items"][0]["use_state"] == "revalidation"


def test_source_revision_ignores_labels_read_times_and_detects_actual_facts():
    original = metadata()
    renamed = retained_ad()
    renamed["name"] = "Renamed"
    same = metadata(ad=renamed, rows=[observation(observed_at="later", name="Presentation")])
    assert same["source_version"] == original["source_version"]
    changed = metadata(rows=[observation(result_count=11)])
    assert changed["source_version"] != original["source_version"]
    assert metadata(rows=[observation(result_count=None)])["sample"]["result_events"] is None
    assert metadata(rows=[observation(result_count=0)])["sample"]["result_events"] == 0


def test_writer_uses_independent_scoped_support_and_resets_after_contrary_result():
    retained = []

    def save(conn, brand, **values):
        result = {
            "id": f"learning{len(retained)}",
            "org_id": "org",
            "brand_id": brand,
            "product_id": values["product_id"],
            **values,
        }
        retained.append(result)
        return result

    first = metadata()
    sources = [
        first,
        {**first, "source_kind": "coordinate"},
        metadata(campaign_id="second", start="2026-09-01", end="2026-09-10"),
        metadata(campaign_id="third", start="2026-09-11", end="2026-09-20", direction="contrary"),
        metadata(campaign_id="fourth", start="2026-09-21", end="2026-09-30"),
        metadata(campaign_id="fifth", start="2026-10-01", end="2026-10-07"),
    ]
    with (
        patch.object(ads_learnings.bi_repo, "list_learnings", side_effect=lambda *a, **k: retained),
        patch.object(ads_learnings.bi_repo, "record_learning", side_effect=save),
        patch.object(ads_learnings.bi_repo, "get_product", return_value={"id": "A", "name": "A"}),
        patch.object(ads_learnings.ads_repo, "get_campaign", return_value={}),
        patch.object(ads_learnings, "current_conditions", return_value=scoped_current(first)),
    ):
        levels = [
            ads_learnings.write(
                Mock(),
                "org",
                "brand",
                product_id="A",
                text="The same actual message",
                scope="ads",
                confidence="validated",
                sample_size="10",
                source_cycle_id=str(n),
                source_track="ads",
                evidence=source,
            )["confidence"]
            for n, source in enumerate(sources)
        ]
    assert levels == ["observed", "observed", "likely", "observed", "observed", "likely"]


def test_carried_binding_identity_does_not_change_material_content_version():
    content = {"sha256": "actual-file", "copy": {"headline": "Actual copy"}}
    original = {
        "material_placement_id": "old",
        "material_placement_revision": 1,
        "material_evidence": content,
    }
    carried = {
        **original,
        "id": "new-ad",
        "material_placement_id": "new",
        "material_placement_revision": 2,
    }
    first = ads_learnings.material_version(original, {})
    assert (
        ads_learnings.material_version(carried, {"copy": {"body_json": {"label": "New set"}}})
        == first
    )
    changed = {**carried, "material_evidence": {**content, "copy": {"headline": "Changed"}}}
    assert ads_learnings.material_version(changed, {}) != first
    prompt = {
        "image_prompt": {"body_json": {"fingerprint": {"look": {"key": "phone", "label": "Phone"}}}}
    }
    same = deepcopy(prompt)
    same["image_prompt"]["body_json"]["fingerprint"]["look"]["label"] = "Renamed label"
    assert ads_learnings.material_version({}, prompt) == ads_learnings.material_version({}, same)


def test_price_expires_at_org_midnight_without_editing_money():
    economics = {
        "status": "confirmed",
        "selling_price": 1000,
        "currency": "TWD",
        "effective_from": date(2026, 9, 1),
        "effective_to": date(2026, 10, 7),
    }
    from app.ads import targets

    before = deepcopy(economics)
    with (
        patch.object(ads_learnings.bi_repo, "get_product_economics", return_value=economics),
        patch.object(ads_learnings.bi_repo, "offer_sources", return_value=[]),
        patch.object(ads_learnings.bi_repo, "list_brand_policies", return_value=[]),
        patch.object(
            targets,
            "resolve",
            return_value={"value": 300, "basis": "own", "result_kind": "purchase"},
        ),
        patch.object(
            ads_learnings.coresettings, "org_timezone", return_value=ZoneInfo("Asia/Taipei")
        ),
    ):
        with patch.object(db, "now_utc", return_value=datetime(2026, 10, 7, 15, 59, tzinfo=UTC)):
            active = ads_learnings.condition_snapshot(Mock(), "org", "brand", {}, "A")
        with patch.object(db, "now_utc", return_value=datetime(2026, 10, 7, 16, 0, tzinfo=UTC)):
            expired = ads_learnings.condition_snapshot(Mock(), "org", "brand", {}, "A")
    assert active["price_version"]
    assert expired["price_version"] is None
    source = metadata(end="2026-10-06")
    source["conditions"].update(
        price_version=active["price_version"], target_version=active["target_version"]
    )
    valid = projected(
        source,
        {
            **scoped_current(source),
            "org_day": "2026-10-07",
            "conditions": {**active, "materials": []},
        },
    )
    stale = projected(
        source, {**scoped_current(source), "conditions": {**expired, "materials": []}}
    )
    assert "market_support" in valid["items"][0]["allowed_uses"]
    assert stale["items"][0]["use_state"] == "revalidation"
    assert stale["revision"] != valid["revision"]
    assert economics == before


def test_new_draft_uses_retained_same_product_definition_and_keeps_mixed_unknown():
    from app.ads import live_creative, outcome

    draft = {"id": "draft", "result_kind": "purchase", "context_json": {"product_ids": ["A"]}}
    previous = {**draft, "id": "previous"}
    other = {**draft, "id": "other", "context_json": {"product_ids": ["B"]}}
    conn = Mock()
    conn.execute.return_value.fetchall.side_effect = [[draft, other, previous], [], []] * 2
    rows = [observation()]
    called = []

    def actual(conn, org, brand, campaign, kind):
        called.append(campaign)
        return [] if campaign == "draft" else rows

    with (
        patch.object(ads_learnings.bi_repo, "get_product", return_value={"id": "A"}),
        patch.object(ads_learnings.customer_groups, "knowledge_product_ids", return_value=["A"]),
        patch.object(ads_learnings.bi_repo, "list_customer_groups", return_value=[]),
        patch.object(ads_learnings.ads_repo, "coordinate_vocabulary", return_value=[]),
        patch.object(ads_learnings, "condition_snapshot", return_value={}),
        patch.object(ads_learnings.coresettings, "today_for_org", return_value=date(2026, 10, 8)),
        patch.object(live_creative, "launched_outputs", return_value={}),
        patch.object(outcome, "rows", side_effect=actual),
    ):
        current = ads_learnings.current_conditions(conn, "org", "brand", "A", campaign=draft)
        assert current["result_kind"] == "purchase"
        assert current["attribution"]
        assert "other" not in called
        rows.append(observation(result_action="other_action"))
        mixed = ads_learnings.current_conditions(conn, "org", "brand", "A", campaign=draft)
        assert mixed["result_kind"] is None
        assert mixed["attribution"] is None


def test_visual_swap_retires_comparable_winners_but_keeps_inspectable_history():
    from app.ads import learning, live_creative, outcome, visual_learning

    retained = []
    a, b = ({**retained_ad(), "id": identity} for identity in ("a", "b"))
    detail = {
        "id": "first",
        "result_kind": "purchase",
        "context_json": {"product_ids": ["A"]},
        "groups": [{"ads": [a, b]}],
    }
    window = {"start": "2026-08-01", "end": "2026-08-10", "days": 10}
    observations = []

    def save(conn, brand, **values):
        raw = {
            "id": f"visual{len(retained)}",
            "org_id": "org",
            "brand_id": brand,
            "expired": False,
            **values,
        }
        retained.append(raw)
        return raw

    def retire(conn, brand, identity, **kwargs):
        next(r for r in retained if r["id"] == identity)["expired"] = True

    def write_trial(identity, start, end, a_spend, b_spend, *, unknown=False):
        detail["id"] = identity
        window.update(start=start, end=end)
        observations[:] = [
            observation(entity_id="a", day=date.fromisoformat(start), spend=a_spend),
            observation(entity_id="b", day=date.fromisoformat(start), spend=b_spend),
        ]
        if unknown:
            observations.append(
                observation(entity_id="a", day=date.fromisoformat(end), result_count=None, spend=0)
            )
        return visual_learning.write_visual_learnings(
            Mock(), "org", "brand", identity, actor="test", days=10, labels={"cpa": "CPA"}
        )

    with (
        patch.object(visual_learning.ads_repo, "campaign_detail", return_value=detail),
        patch("app.ads.targets.resolve", return_value={"result_kind": "purchase", "value": 200,
                                                      "basis": "own"}),
        patch.object(visual_learning.ads_repo, "campaign_objective_family", return_value="sales"),
        patch.object(live_creative, "with_learning_coordinates", side_effect=lambda *args: detail),
        patch.object(outcome, "period_window", return_value=window),
        patch.object(outcome, "rows", return_value=observations),
        patch.object(
            visual_learning,
            "_kept_ads",
            return_value={
                "a": {"look": {"key": "phone", "label": "Phone"}},
                "b": {"look": {"key": "studio", "label": "Studio"}},
            },
        ),
        patch.object(visual_learning, "_label_lookup", return_value={"cold": "Cold"}),
        patch.object(learning, "_needs_revalidation", return_value=False),
        patch.object(ads_learnings.bi_repo, "list_learnings", side_effect=lambda *a, **k: retained),
        patch.object(ads_learnings.bi_repo, "record_learning", side_effect=save),
        patch.object(ads_learnings.bi_repo, "expire_learning", side_effect=retire),
        patch.object(ads_learnings.bi_repo, "get_product", return_value={"id": "A", "name": "A"}),
        patch.object(ads_learnings.ads_repo, "get_campaign", return_value={}),
        patch.object(ads_learnings, "current_conditions", return_value=scoped_current(metadata())),
    ):
        assert (
            write_trial("first", "2026-08-01", "2026-08-10", 100, 200)[0]["confidence"]
            == "observed"
        )
        assert (
            write_trial("second", "2026-09-01", "2026-09-10", 100, 200)[0]["confidence"] == "likely"
        )
        assert (
            write_trial("third", "2026-09-11", "2026-09-20", 200, 100)[0]["confidence"]
            == "observed"
        )
        assert [r["expired"] for r in retained] == [True, True, False]
        context = ads_learnings.evidence_context(Mock(), "org", "brand", "A")
        assert len(context["items"]) == 3
        history = [i for i in context["items"] if i["use_state"] == "history"]
        assert len(history) == 2
        assert all("superseded" in i["reason_codes"] and not i["allowed_uses"] for i in history)
        thin = write_trial("fourth", "2026-09-21", "2026-09-30", 100, 300, unknown=True)[0]
        raw = ads_learnings.stored_evidence(thin)
        assert raw["sample"]["result_events"] is None
        assert thin["confidence"] == "observed"
        assert not retained[2]["expired"]


def test_ab_side_with_ten_known_and_one_unknown_never_becomes_sufficient():
    from app.ads import ab_pairs, change_control, live_creative, outcome

    a, b = ({**retained_ad(), "id": identity, "hook_key": identity} for identity in ("a", "b"))
    for ad in (a, b):
        ad["live_creative_json"] = deepcopy(ad["live_creative_json"])
        ad["live_creative_json"]["evidence_conditions"]["material_version"] = f"content-{ad['id']}"
    detail = {
        "id": "campaign",
        "result_kind": "purchase",
        "context_json": {"product_ids": ["A"]},
        "groups": [{"ads": [a, b]}],
    }
    pair = {
        "pair_id": "a:b",
        "dimension": "hook",
        "dimension_label": "Hook",
        "state": "judged",
        "winner": "a",
        "window": {"start": "2026-08-01", "end": "2026-08-10"},
    }
    for key in ("a", "b"):
        pair[key] = {
            "ad_id": key,
            "entity_id": key,
            "name": key,
            "value_label": key,
            "cost_per_result": 100 if key == "a" else 200,
        }
    rows = [
        observation(entity_id="a"),
        observation(entity_id="a", result_count=None),
        observation(entity_id="b"),
    ]
    with (
        patch.object(ab_pairs, "read", return_value={"pairs": [pair]}),
        patch.object(change_control, "open_ab_set", return_value=None),
        patch.object(change_control, "create_ab", side_effect=lambda *args: args[5]),
        patch.object(ab_pairs.repository, "campaign_detail", return_value=detail),
        patch.object(ab_pairs.repository, "campaign_objective_family", return_value="sales"),
        patch.object(live_creative, "with_learning_coordinates", return_value=detail),
        patch.object(outcome, "rows", return_value=rows),
        patch.object(ab_pairs.settings, "today_for_org", return_value=date(2026, 10, 8)),
    ):
        ab = ab_pairs.pause_loser(Mock(), "org", "brand", "campaign", "a:b", "op", "actor")
        rows[:] = [observation(entity_id="a"), observation(entity_id="b", spend=2000)]
        first = ab_pairs.pause_loser(Mock(), "org", "brand", "campaign", "a:b", "op1", "actor")
        actual_rows = {"campaign": deepcopy(rows)}
        pair["window"] = {"start": "2026-08-11", "end": "2026-08-20"}
        detail["id"] = "middle"
        rows[:] = [
            observation(entity_id="a", day=date(2026, 8, 11)),
            observation(entity_id="b", day=date(2026, 8, 11), spend=2000),
        ]
        middle = ab_pairs.pause_loser(Mock(), "org", "brand", "middle", "a:b", "opm", "actor")
        actual_rows["middle"] = deepcopy(rows)
        pair["winner"] = "b"
        pair["window"] = {"start": "2026-09-01", "end": "2026-09-10"}
        detail["id"] = "second"
        rows[:] = [
            observation(entity_id="a", day=date(2026, 9, 1), spend=2000),
            observation(entity_id="b", day=date(2026, 9, 1), spend=1000),
        ]
        second = ab_pairs.pause_loser(Mock(), "org", "brand", "second", "a:b", "op2", "actor")
        actual_rows["second"] = deepcopy(rows)
        rows[0]["result_count"] = 11
        with (
            patch.object(ads_learnings, "_ads_rows", return_value=[]),
            patch.object(ads_learnings.sell_way, "of_campaign_id", return_value="A"),
            patch.object(ads_learnings, "write", side_effect=lambda *a, **k: k),
        ):
            stale = ads_learnings.record_for_ab_item(
                Mock(),
                "org",
                "brand",
                "second",
                {"plan_json": {"source": "ab", "ab": second}},
                {"kind": "pause", "id": "action"},
            )
            assert stale["needs_revalidation"] is True
            assert stale["evidence"]["source_version"] == second["evidence"]["source_version"]
    assert ab["evidence"]["sample"]["result_events"] is None
    item = projected(ab["evidence"])["items"][0]
    assert item["sample"]["sufficient"] is None
    assert "market_support" not in item["allowed_uses"]
    assert first["evidence"]["scope"]["claim_key"] == second["evidence"]["scope"]["claim_key"]
    assert first["evidence"]["direction"] == "support"
    assert second["evidence"]["direction"] == "contrary"
    assert "a" in ads_learnings.ab_text(first)
    assert "b" in ads_learnings.ab_text(second)
    sources = [first["evidence"], middle["evidence"], second["evidence"]]
    unknown = deepcopy(second["evidence"])
    unknown.update(
        provenance="unknown",
        direction="support",
        period={"start": "2026-09-11", "end": "2026-09-20"},
    )
    unknown["source_ref"]["trial_id"] = "unknown"
    changed = deepcopy(unknown)
    changed["provenance"] = "platform_observation"
    changed["conditions"]["target_version"] = "changed"
    changed["source_ref"]["trial_id"] = "changed"
    for newer in (None, unknown, changed):
        raw_rows = [
            {**legacy(str(n)), "applicability_scope": encode_learning_scope("ads", evidence)}
            for n, evidence in enumerate([*sources, *([newer] if newer else [])])
        ]
        items = {
            i["id"]: i
            for i in qualify_learning_evidence(
                raw_rows,
                scoped_current(first["evidence"]),
                min_result_events=10,
                max_age_days=180,
            )["items"]
        }
        assert items["0"]["use_state"] == "history"
        assert "contradictory_result" in items["0"]["reason_codes"]
        assert items["1"]["use_state"] == "history"
        assert items["2"]["use_state"] == "usable"
        assert items["2"]["independent_count"] == 3
        assert items["2"]["same_direction_count"] == 1
        assert items["2"]["contrary_count"] == 1
    retained = []

    def save(conn, brand, **values):
        raw = {"id": str(len(retained)), "org_id": "org", "brand_id": brand, **values}
        retained.append(raw)
        return raw

    def campaign_detail(conn, org, brand, identity):
        return {**detail, "id": identity}

    with (
        patch.object(ads_learnings.bi_repo, "list_learnings", side_effect=lambda *a, **k: retained),
        patch.object(ads_learnings.bi_repo, "record_learning", side_effect=save),
        patch.object(ads_learnings.bi_repo, "get_product", return_value={"id": "A", "name": "A"}),
        patch.object(ads_learnings.ads_repo, "get_campaign", return_value={}),
        patch.object(ads_learnings.ads_repo, "campaign_detail", side_effect=campaign_detail),
        patch.object(ads_learnings.ads_repo, "campaign_objective_family", return_value="sales"),
        patch.object(ads_learnings.sell_way, "of_campaign_id", return_value="A"),
        patch.object(ads_learnings, "current_conditions", return_value=scoped_current(sources[0])),
        patch.object(live_creative, "with_learning_coordinates", side_effect=lambda *args: args[3]),
        patch.object(
            outcome, "rows", side_effect=lambda c, o, b, identity, k: actual_rows[identity]
        ),
    ):
        levels = []
        for n, comparison in enumerate((first, middle, second)):
            identity = comparison["evidence"]["source_ref"]["campaign_id"]
            row = ads_learnings.record_for_ab_item(
                Mock(),
                "org",
                "brand",
                identity,
                {"plan_json": {"source": "ab", "ab": comparison}},
                {"kind": "pause", "id": f"action{n}"},
            )
            assert row["needs_revalidation"] is False
            levels.append(row["confidence"])
        assert levels == ["observed", "likely", "observed"]
        context = ads_learnings.evidence_context(Mock(), "org", "brand", "A")
        items = {i["id"]: i for i in context["items"]}
        assert items["2"]["independent_count"] == 3
        assert items["2"]["same_direction_count"] == items["2"]["contrary_count"] == 1
        assert items["0"]["use_state"] == items["1"]["use_state"] == "history"
