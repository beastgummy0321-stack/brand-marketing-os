"""Frozen qualification counterexamples; all data here is synthetic market-shaped evidence."""

from copy import deepcopy

from app.workbench import base_learning_scope, encode_learning_scope, qualify_learning_evidence


def current(**overrides):
    return {
        "org_id": "org",
        "brand_id": "brand",
        "product_id": "A",
        "org_day": "2026-10-08",
        "audience_keys": ["cold"],
        "customer_group_ids": ["A1"],
        "result_kind": "purchase",
        "currency": "TWD",
        "attribution": "7d",
        "mode": "real",
        "conditions": {
            "price_version": "price1",
            "offers": [],
            "materials": [],
            "target_version": "target1",
        },
        **overrides,
    }


def row(
    identity="one",
    *,
    start="2026-08-01",
    end="2026-08-31",
    events=10,
    direction="support",
    product="A",
    provenance="platform_observation",
    trial=None,
):
    evidence = {
        "schema_version": 1,
        "source_kind": "campaign",
        "source_ref": {
            "campaign_id": identity,
            "ad_id": None,
            "action_id": None,
            "entity_id": None,
            "trial_id": trial or identity,
        },
        "source_version": "source1",
        "provenance": provenance,
        "period": {"start": start, "end": end},
        "scope": {
            "product_id": product,
            "audience_key": "cold",
            "customer_group_id": "A1",
            "claim_key": "convenience",
            "claim_family": "performance",
            "objective_family": "sales",
            "result_kind": "purchase",
            "currency": "TWD",
            "attribution": "7d",
        },
        "conditions": {
            "price_version": "price1",
            "offer_key": "none",
            "offer_version": None,
            "material_version": None,
            "target_version": "target1",
            "valid_until": None,
        },
        "sample": {"result_events": events, "sufficient": True},
        "direction": direction,
        "limits": [],
    }
    return {
        "id": identity,
        "org_id": "org",
        "brand_id": "brand",
        "product_id": product,
        "learning_text": "Convenience is associated with lower cost in this period.",
        "applicability_scope": encode_learning_scope("ads", evidence),
        "needs_revalidation": False,
    }


def mutate(source, **changes):
    import json

    changed = deepcopy(source)
    raw = json.loads(changed["applicability_scope"].split("\n@evidence-v1:")[1])
    for key, value in changes.items():
        raw[key] = {**raw[key], **value} if isinstance(value, dict) else value
    changed["applicability_scope"] = encode_learning_scope("ads", raw)
    return changed


def qualify(rows, ctx=None):
    return qualify_learning_evidence(rows, ctx or current(), min_result_events=10, max_age_days=180)


def test_exact_unicode_delimiter_and_canonical_roundtrip():
    import json

    raw = json.loads(row()["applicability_scope"].split("\n@evidence-v1:")[1])
    base = "coord；v=2；angle=書包\n第二行"
    scope = encode_learning_scope(base, raw)
    assert base_learning_scope(scope) == base
    assert encode_learning_scope(scope, raw) == scope
    assert "\n" not in scope.split("\n@evidence-v1:")[1]
    assert base_learning_scope(base + "\n@evidence-v1:{broken") == base


def test_unknown_legacy_and_invalid_trailers_cannot_certify_support():
    for scope in (
        "ads",
        "ads\n@evidence-v1:{broken",
        "ads\n@evidence-v1:[]",
        'ads\n@evidence-v1:{"schema_version":2}',
    ):
        original = row()
        original["applicability_scope"] = scope
        item = qualify([original])["items"][0]
        assert item["provenance"] == "unknown"
        assert item["use_state"] == "history"
        assert item["allowed_uses"] == []
        assert "unknown_source" in item["reason_codes"]


def test_product_provenance_tenant_and_measurement_boundaries():
    for changed in (
        row(product="B"),
        row(product=None),
        row(provenance="simulation"),
        {**row(), "org_id": "other"},
        {**row(), "brand_id": "other"},
        mutate(row(), scope={"currency": "USD"}),
        mutate(row(), scope={"attribution": "1d"}),
        mutate(row(), scope={"result_kind": "visit"}),
        mutate(
            row(),
            source_ref={
                key: None for key in ("campaign_id", "ad_id", "action_id", "entity_id", "trial_id")
            },
        ),
    ):
        item = qualify([changed])["items"][0]
        assert item["use_state"] != "usable"
        assert item["independent_count"] == 0
        assert item["allowed_uses"] == []
    assert qualify([row()], current(product_id=None))["eligible_count"] == 0
    assert qualify([row()], current(mode="isolated_simulation"))["eligible_count"] == 1
    simulation = qualify([row(provenance="simulation")], current(mode="isolated_simulation"))[
        "items"
    ][0]
    assert "market_support" not in simulation["allowed_uses"]


def test_zero_unknown_thin_and_stored_validated_do_not_promote():
    for events in (0, 2, None, True, -1):
        item = qualify([{**row(events=events), "confidence": "validated"}])["items"][0]
        assert item["independent_count"] == 0
        assert "insufficient_sample" in item["reason_codes"]
        assert item["allowed_uses"] == ["test", "retain_control"]


def test_same_trial_derivatives_replay_and_overlap_do_not_add_support():
    original = row()
    derivatives = [
        mutate({**original, "id": kind}, source_kind=kind, source_version=kind)
        for kind in ("coordinate", "visual", "settle", "ab")
    ]
    overlap = row("overlap", start="2026-08-15", end="2026-09-15")
    items = qualify([original, *derivatives, overlap])["items"]
    assert {item["independent_count"] for item in items} == {1}
    newer = row("newer", start="2026-09-01", end="2026-09-30", trial="one")
    newer = mutate(newer, source_version="updated-source")
    result = qualify([original, newer])
    assert next(i for i in result["items"] if i["id"] == "one")["use_state"] == "history"
    assert next(i for i in result["items"] if i["id"] == "newer")["independent_count"] == 1


def test_null_identity_and_missing_trial_cannot_promote_market_support():
    source = mutate(row(), source_ref={"trial_id": None})
    result = qualify([source, {**row("other"), "id": None}])
    assert result["eligible_count"] == 1
    assert all(i["independent_count"] == 0 for i in result["items"])
    assert all("market_support" not in i["allowed_uses"] for i in result["items"])


def test_two_and_three_independent_observations_are_scoped_associations():
    july = row("july", start="2026-07-01", end="2026-07-31")
    august = row("august")
    september = row("september", start="2026-09-01", end="2026-09-30")
    for rows, count in (([july], 1), ([july, august], 2), ([july, august, september], 3)):
        items = qualify(rows)["items"]
        assert all(i["same_direction_count"] == count for i in items)
        assert all("僅表示相關" in i["support_label"] for i in items)
        assert all("market_support" in i["allowed_uses"] for i in items)


def test_contrary_result_resets_same_direction_and_retains_history():
    july = row("july", start="2026-07-01", end="2026-07-31")
    august = row("august")
    september = row("september", start="2026-09-01", end="2026-09-30", direction="contrary")
    items = qualify([july, august, september])["items"]
    latest = next(i for i in items if i["id"] == "september")
    assert (
        latest["independent_count"],
        latest["same_direction_count"],
        latest["contrary_count"],
    ) == (3, 1, 1)
    assert "market_support" not in latest["allowed_uses"]
    assert next(i for i in items if i["id"] == "august")["use_state"] == "history"
    october = row("october", start="2026-10-01", end="2026-10-08")
    latest = next(
        i for i in qualify([july, august, september, october])["items"] if i["id"] == "october"
    )
    assert (latest["independent_count"], latest["same_direction_count"]) == (4, 1)


def test_conditions_age_org_midnight_and_explicit_revalidation():
    stale = row(start="2025-08-01", end="2025-08-31")
    item = qualify([stale])["items"][0]
    assert "measurement_stale" in item["reason_codes"]
    assert item["use_state"] == "revalidation"
    for changed in (
        mutate(row(), conditions={"price_version": "price2"}),
        mutate(row(), conditions={"target_version": "target2"}),
        mutate(row(), conditions={"material_version": "image1"}),
        {**row(), "needs_revalidation": True},
    ):
        item = qualify([changed])["items"][0]
        assert item["use_state"] == "revalidation"
        assert item["allowed_uses"] == []
    offer = mutate(
        row(),
        conditions={
            "offer_key": "free_shipping",
            "offer_version": "offer1",
            "valid_until": "2026-10-07",
        },
    )
    ctx = current(
        conditions={
            **current()["conditions"],
            "offers": [{"key": "free_shipping", "version": "offer1", "valid_until": "2026-10-07"}],
        }
    )
    assert "offer_ended" in qualify([offer], ctx)["items"][0]["reason_codes"]
    ctx["org_day"] = "2026-10-07"
    assert "offer_ended" not in qualify([offer], ctx)["items"][0]["reason_codes"]


def test_brand_facts_do_not_expire_and_operation_is_only_an_operation():
    fact = mutate(
        row(product=None, provenance="user_report", start="2020-01-01", end="2020-01-31"),
        scope={"claim_family": "brand_fact"},
    )
    assert qualify([fact])["items"][0]["allowed_uses"] == ["brand_fact"]
    operation = mutate(row(provenance="operation_readback"), scope={"claim_family": "operation"})
    item = qualify([operation])["items"][0]
    assert item["allowed_uses"] == ["operation"]
    assert item["independent_count"] == 0


def test_revision_covers_actual_meaning_sources_eligibility_and_not_labels_or_order():
    original = row()
    other = row("july", start="2026-07-01", end="2026-07-31")
    before = qualify([original, other])
    assert before == qualify([other, original])
    assert before == qualify([{**original, "label": "renamed", "learned_at": "tomorrow"}, other])
    for changed in (
        {**original, "learning_text": "Changed actual meaning"},
        mutate(original, source_version="source2"),
        mutate(original, conditions={"price_version": "price2"}),
    ):
        assert before["revision"] != qualify([changed, other])["revision"]
    assert qualify([])["eligible_count"] == 0
