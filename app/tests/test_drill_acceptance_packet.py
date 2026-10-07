"""Bounded packet-tool contracts; these fixtures are not fresh product/drill verdicts."""

import copy
import hashlib
import json
from decimal import Decimal
from pathlib import Path

import pytest

from scripts.drill import acceptance_packet as packet


def control(state="plain", *, event="event-1", verdict="pass", scope="fresh", **extra):
    return {
        "route": "/app/workbench",
        "state": state,
        "action": "select-copy",
        "prerequisite": "The owned candidate exists",
        "expected": "Selection is visible",
        "event_id": event,
        "verdict": verdict,
        "scope": scope,
        "run_id": "fixture-run",
        "head": "fixture-head",
        "evidence": ["evidence"],
        **extra,
    }


def coverage(events, **extra):
    return packet.control_coverage(events, run_id="fixture-run", head="fixture-head", **extra)


@pytest.fixture
def inputs(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    spec = {
        "schema": "acceptance-packet-v1",
        "head": "fixture-head",
        "run_id": "fixture-run",
        "comparison_side": "Original",
        "product_side": "Product",
        "sources": [],
        "periods": [],
        "variants": [],
        "controls": [],
        "layers": {},
        "inventory_complete": False,
        "disclosures": ["Local fixture evidence only"],
    }

    def add(key, value, *, raw=None):
        data = raw if raw is not None else json.dumps(value, ensure_ascii=False).encode("utf-8")
        path = source / (key + ".json")
        path.write_bytes(data)
        spec["sources"].append(
            {
                "id": key,
                "path": path.name,
                "bytes": len(data),
                "sha256": hashlib.sha256(data).hexdigest(),
            }
        )
        return key

    for key in ("facts", "persona", "calendar", "fit_rubric", "aggregate_rubric"):
        add(key, {"fixture": key})
    add("evidence", {}, raw=b"exact independent fixture evidence\r\n")
    spec["context"] = {
        key: key for key in ("facts", "persona", "calendar", "fit_rubric", "aggregate_rubric")
    }
    previous = {}
    for side in ("Original", "Product"):
        for period in (1, 2, 3):
            key = f"{side}-{period}"
            name = f"exact-{side}-ad-{period}"
            plan = {
                "side": side,
                "period": period,
                "start_date": "2026-10-01",
                "end_date": "2026-10-01",
                "groups": [
                    {
                        "name": "original group",
                        "daily_budget": 600,
                        "audience_key": "first-ad-audience",
                        "ads": [
                            {
                                "name": name,
                                "audience_key": "actual-ad-audience",
                                "body": "Original copy remains exact. 優惠原句",
                                "format_key": None,
                            }
                        ],
                    }
                ],
            }
            plan_id = add(key + "-plan", plan)
            fit_id = add(
                key + "-fit",
                {
                    "ads": {
                        name: {
                            "fit": "1.15",
                            "tags": [],
                            "compliance": "ok",
                            "proof_present": False,
                            "reason": "Independent fixture quote",
                        }
                    }
                },
            )
            reasoning = add(key + "-reason", {"reason": "Original reason"})
            copy_id = add(key + "-copy", {"body": plan["groups"][0]["ads"][0]["body"]})
            prior_creatives = [row["plan"] for row in spec["periods"] if row["side"] == side]
            spec["periods"].append(
                {
                    "side": side,
                    "period": period,
                    "plan": plan_id,
                    "fit": fit_id,
                    "reasoning": reasoning,
                    "copy": copy_id,
                    "prior_creatives": prior_creatives,
                    "requested_budget": None,
                    "requested_ad_count": None,
                }
            )
            for dates in ("actual", "aligned"):
                for audience in ("ad", "group"):
                    variant = (side, dates, audience)
                    rows_id = add(
                        key + f"-{dates}-{audience}",
                        [
                            {
                                "side": side,
                                "period": period,
                                "date": "2026-10-01",
                                "group_name": "original group",
                                "ad_name": name,
                                "spend": "559",
                                "purchases": 1,
                                "revenue": "999",
                                "impressions": 100,
                                "clicks": 2,
                            }
                        ],
                    )
                    spec["variants"].append(
                        {
                            "side": side,
                            "period": period,
                            "date_mode": dates,
                            "audience_mode": audience,
                            "plan": plan_id,
                            "rows": rows_id,
                            "priors": list(previous.get(variant, [])),
                        }
                    )
                    previous.setdefault(variant, []).append(rows_id)

    def prepare(**changes):
        selected = copy.deepcopy(spec)
        selected.update(changes)
        input_file = source / "input.json"
        input_file.write_text(json.dumps(selected, ensure_ascii=False), encoding="utf-8")
        return packet.prepare_packet(
            input_file, source_root=source, fresh_root=tmp_path, output=tmp_path / "packet"
        )

    return source, spec, add, prepare


def test_generated_instances_deduplicate_only_identical_semantics_and_append_retests():
    events = [
        control(generated_instance="card-1"),
        control(event="event-2", generated_instance="card-2"),
        control("warning", event="event-3", verdict="partial"),
    ]
    result = coverage(events)
    rows = [row for row in result["rows"] if row["route"] == "/app/workbench"]
    assert len(rows) == 2
    assert len(rows[0]["events"]) == 2
    assert result["passed"] == 1
    rerun = coverage([control(event="event-4", verdict="fail")], previous=result)
    assert rerun["passed"] == 0
    assert len(next(row for row in rerun["rows"] if row["state"] == "plain")["events"]) == 3
    assert rerun["rows"][0]["id"] == result["rows"][0]["id"]


def test_semantic_conflict_or_reused_event_cannot_hide_a_distinct_branch():
    with pytest.raises(packet.PacketError, match="semantic_key_conflict"):
        coverage([control(), control(event="event-2", expected="A different branch result")])
    with pytest.raises(packet.PacketError, match="event_id_conflict"):
        coverage([control(), control(verdict="fail")])


def test_historical_pass_is_retained_but_fresh_unknown_and_all_required_gaps_stay():
    result = coverage([control(scope="historical")], inventory_complete=True)
    assert result["passed"] == 0 and result["denominator"] > 20
    row = next(row for row in result["rows"] if row["state"] == "plain")
    assert row["verdict"] == "unknown" and row["events"][0]["verdict"] == "pass"
    assert {"A216", "A247", "A248", "B-empty-fill", "C-cleanup-eligible"} <= set(
        result["required_gaps"]
    )
    assert len([key for key in result["required_gaps"] if key.startswith("C-partial-")]) == 23
    assert result["complete"] is False and result["acceptance_95"] is False


@pytest.mark.parametrize("verdict", ["unknown", "untested", "partial", "fail"])
def test_applicable_nonpasses_receive_no_credit(verdict):
    result = coverage([control(verdict=verdict)])
    assert result["passed"] == 0 and result["denominator"] >= 1


def test_exclusion_requires_reason_and_retains_independent_matrix():
    with pytest.raises(packet.PacketError, match="exclusion_reason"):
        coverage([control(verdict="unsupported")])
    result = coverage(
        [control(verdict="unsupported", exclusion_reason="Current isolated capability unavailable")]
    )
    assert len(result["exclusions"]) == 1 and result["passed"] == 0
    assert result["exclusions"][0]["exclusion_reason"]


@pytest.mark.parametrize("fit,passing", [("1.15", True), ("1.149999999999999999999", False)])
def test_fit_boundary_does_not_round_across_threshold(fit, passing):
    assert packet.fit_summary([{"fit": fit}])["threshold_met"] is passing


@pytest.mark.parametrize("spend,passing", [("559", True), ("559.00000000000000000001", False)])
def test_cpa_boundary_does_not_round_across_threshold(spend, passing):
    result = packet.simulation_totals([{"spend": spend, "purchases": 1, "revenue": "999"}])
    assert Decimal(result["cpa"]) == Decimal(spend)
    assert result["threshold_met"] is passing
    assert packet.simulation_totals([{"spend": "559", "purchases": 0, "revenue": 0}])["cpa"] is None


def test_score_math_checks_independent_inputs_and_never_generates_grades():
    assert (
        packet.validate_scores({"dimensions": {"1": "7", "2": "8"}, "total": "15", "mean": "7.5"})[
            "total"
        ]
        == "15"
    )
    with pytest.raises(packet.PacketError, match="score_arithmetic"):
        packet.validate_scores({"dimensions": {"1": 7, "2": 8}, "total": 16})
    with pytest.raises(packet.PacketError, match="nonfinite"):
        packet.fit_summary([{"fit": "NaN"}])


def test_packet_freezes_raw_identity_full_variants_and_priors_without_quality_pass(inputs):
    source, spec, _, prepare = inputs
    original = {row["path"]: (source / row["path"]).read_bytes() for row in spec["sources"]}
    result = prepare()
    assert result["quality_verdict"] == "not_certified"
    assert len(result["variants"]) == 24
    assert all(len(row["priors"]) == row["period"] - 1 for row in result["variants"])
    assert all(
        row["requested_budget"] is None and row["requested_ad_count"] is None
        for row in result["periods"]
    )
    assert all((source / key).read_bytes() == raw for key, raw in original.items())
    assert any(row["layer"] == "human_approval" for row in result["missing"])
    for row in result["raw_sources"]:
        assert Path(row["frozen_path"]).read_bytes() == original[row["original_path"]]
    assert result["metrics"]["aligned.ad"]["cpa"] == "559"


def test_fit_packets_have_one_masked_plan_full_priors_and_no_simulator_or_opposite_plan(inputs):
    _, _, _, prepare = inputs
    result = prepare()
    mapping = json.loads(Path(result["private_mapping"]).read_text(encoding="utf-8"))
    assert set(mapping["sides"].values()) == {"Original", "Product"}
    assert all("exact-" in row["original_ad_name"] for row in mapping["ads"])
    fit_files = list(Path(result["output"]).glob("public/fit/*.json"))
    assert len(fit_files) == 6
    for file in fit_files:
        value = json.loads(file.read_text(encoding="utf-8"))
        assert set(value) == {
            "candidate",
            "period",
            "plan",
            "facts",
            "persona",
            "calendar",
            "rubric",
            "prior_creatives",
            "limitations",
        }
        assert len(value["prior_creatives"]) == value["period"] - 1
        assert "Original" not in value["plan"]["side"] and "Product" not in value["plan"]["side"]
        assert (
            value["plan"]["groups"][0]["ads"][0]["body"] == "Original copy remains exact. 優惠原句"
        )
        assert "threshold" not in json.dumps(value)
        assert value["plan"]["groups"][0]["ads"][0]["format_key"] is None


def test_missing_variant_or_layer_stays_explicit_and_never_invents_data(inputs):
    _, spec, _, prepare = inputs
    result = prepare(variants=spec["variants"][:-1], layers={})
    assert any(row["layer"] == "variant" for row in result["missing"])
    assert result["metrics"]["aligned.group"]["threshold_met"] is None
    assert result["quality_verdict"] == "not_certified"


def test_wrong_prior_chain_and_fit_keys_fail_closed(inputs):
    _, spec, _, prepare = inputs
    spec["variants"][-1]["priors"].reverse()
    with pytest.raises(packet.PacketError, match="prior_chain"):
        prepare()


def test_source_hash_mismatch_and_escape_are_refused_before_output(inputs):
    source, spec, _, prepare = inputs
    (source / spec["sources"][0]["path"]).write_bytes(b"changed")
    with pytest.raises(packet.PacketError, match="source_integrity"):
        prepare()
    assert not (source.parent / "packet").exists()


def test_output_existing_escape_and_original_drill12_are_refused(inputs):
    source, _, _, prepare = inputs
    prepare()
    with pytest.raises(packet.PacketError, match="output_exists"):
        prepare()
    for output in [source.parent.parent / "escape", source.parent / "drill12" / "packet"]:
        with pytest.raises(packet.PacketError, match="output_boundary"):
            packet.prepare_packet(
                source / "input.json", source_root=source, fresh_root=source.parent, output=output
            )


def test_referenced_file_cannot_escape_source_root(inputs):
    source, spec, _, prepare = inputs
    external = source.parent / "foreign.json"
    external.write_bytes(b"foreign")
    spec["sources"][0].update(
        path="../foreign.json", bytes=7, sha256=hashlib.sha256(b"foreign").hexdigest()
    )
    with pytest.raises(packet.PacketError, match="source_boundary"):
        prepare()


def test_historical_required_mapping_does_not_resolve_fresh_gap():
    result = coverage([control(scope="historical", obligations=["A216"])], inventory_complete=True)
    assert "A216" in result["required_gaps"] and result["complete"] is False
    assert not any(row["id"] == "required-A216" for row in result["rows"])


def test_missing_fit_can_freeze_one_plan_inputs_but_never_complete_average(inputs):
    _, spec, _, prepare = inputs
    spec["periods"][-1]["fit"] = None
    result = prepare()
    assert result["copy_fit"]["mean"] is None and result["copy_fit"]["threshold_met"] is None
    assert result["copy_fit"]["missing"] == 1
    assert len(list(Path(result["output"]).glob("public/fit/*.json"))) == 6


def test_original_markdown_material_and_raw_fit_details_are_preserved(inputs):
    _, spec, add, prepare = inputs
    spec["context"]["fit_rubric"] = add(
        "original-rubric", None, raw=b"# Original fit rubric\r\nNo simulator input.\r\n"
    )
    spec["periods"][0]["reasoning"] = add(
        "original-reason", None, raw=b"Exact original reason.\r\n"
    )
    result = prepare()
    fit = json.loads(
        next(Path(result["output"]).glob("public/fit/*.json")).read_text(encoding="utf-8")
    )
    assert fit["rubric"] == "# Original fit rubric\r\nNo simulator input.\r\n"
    aggregate = json.loads(
        (Path(result["output"]) / "public/aggregate.json").read_text(encoding="utf-8")
    )
    plan = next(
        row for row in aggregate["plans"] if row["reasoning"] == "Exact original reason.\r\n"
    )
    record = next(iter(plan["fit_records"].values()))
    assert record["proof_present"] is False and record["reason"] == "Independent fixture quote"
    assert set(record) == {"fit", "tags", "compliance", "proof_present", "reason"}


@pytest.mark.parametrize("failure", ["missing", "duplicate", "foreign-ad"])
def test_simulation_rows_must_cover_every_ad_day_without_duplicate_or_foreign_rows(inputs, failure):
    _, spec, add, prepare = inputs
    variant = spec["variants"][-1]
    source_id = variant["rows"]
    source = next(row for row in spec["sources"] if row["id"] == source_id)
    root = inputs[0]
    rows = json.loads((root / source["path"]).read_text(encoding="utf-8"))
    if failure == "missing":
        rows = []
    elif failure == "duplicate":
        rows += copy.deepcopy(rows)
    else:
        rows[0]["ad_name"] = "not-the-actual-plan-ad"
    variant["rows"] = add("bad-rows", rows)
    with pytest.raises(packet.PacketError, match="row_coverage|row_identity"):
        prepare()


def test_frozen_output_hashes_verify_actual_generated_files(inputs):
    _, _, _, prepare = inputs
    result = prepare()
    for row in result["frozen_files"]:
        data = (Path(result["output"]) / row["path"]).read_bytes()
        assert len(data) == row["bytes"] and hashlib.sha256(data).hexdigest() == row["sha256"]


def test_missing_earlier_variant_propagates_gap_instead_of_certifying_later_priors(inputs):
    _, spec, _, prepare = inputs
    spec["variants"] = [
        row
        for row in spec["variants"]
        if not (
            row["side"] == "Product"
            and row["period"] == 1
            and row["date_mode"] == "aligned"
            and row["audience_mode"] == "ad"
        )
    ]
    result = prepare()
    assert any(row["layer"] == "variant_prior" for row in result["missing"])
    assert result["metrics"]["aligned.ad"]["threshold_met"] is None


def test_wrong_fit_keys_are_not_relabelled_to_achieve_a_score(inputs):
    _, spec, add, prepare = inputs
    spec["periods"][-1]["fit"] = add("wrong-fit", {"ads": {"some-other-ad": {"fit": "1.4"}}})
    with pytest.raises(packet.PacketError, match="fit_keys"):
        prepare()


def test_prior_creative_full_text_is_not_laundered_by_a_renamed_ad(inputs):
    _, spec, _, prepare = inputs
    spec["periods"][-1]["prior_creatives"].reverse()
    with pytest.raises(packet.PacketError, match="creative_prior_chain"):
        prepare()


def test_existing_ledger_cannot_credit_an_orphaned_evidence_reference(inputs):
    _, spec, add, prepare = inputs
    ledger = coverage([control(evidence=["missing-old-source"])])
    spec["previous_controls"] = add("old-controls", ledger)
    with pytest.raises(packet.PacketError, match="source_reference"):
        prepare()
