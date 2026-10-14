"""Replay mechanics and guard limits are distinct from human grounding or live model proof."""

from app.tests.fixtures.ads_external import replay_reviews as replay


def test_cli_replays_only_an_explicit_synthetic_corpus_into_an_owned_file(tmp_path):
    import json
    import subprocess
    import sys

    output = tmp_path / "replay.json"
    run = subprocess.run([sys.executable, "-m", replay.__name__, "--synthetic", "--output",
                          str(output)], capture_output=True, text=True, timeout=15)
    assert run.returncode == 0, run.stderr
    report = json.loads(output.read_text("utf-8"))
    assert report["mode"] == "offline" and len(report["cases"]) == 8
    assert all(case["source_kind"] == "synthetic" for case in report["cases"])


def test_corpus_reports_existing_policy_acceptance_without_semantic_claims():
    results = {case["id"]: replay.replay(case) for case in replay.corpus()}
    assert results["proposed_duration"]["reason_code"] == "numeric_claim"
    assert results["grounded_figure"]["reason_code"] == "numeric_claim"
    assert results["unmeasured_quality"]["validator"] == "accepted"
    assert results["unmeasured_quality"]["human_judgment"]["grounding"] == "unverified"
    assert results["bad_target"]["reason_code"] == "target_or_action_invalid"
    assert results["bad_ref"]["reason_code"] == "evidence_ref_invalid"
    assert results["task_mismatch"]["reason_code"] == "task_binding_mismatch"
    assert results["missing_delayed"]["validator"] == "accepted"
    assert results["incompatible_unit"]["validator"] == "accepted"
    assert all(
        r["storage_match"] == "unknown" and r["inputs"]["state"] == "unknown"
        for r in results.values()
    )


def test_exact_capture_requires_identity_and_byte_hash_and_never_proves_delivery():
    case = replay.fixture_case("capture")
    case["input_capture"] = {
        "task_id": case["task"]["id"],
        "template_hash": "template-fixture",
        "text": "saved input",
        "sha256": replay.sha("saved input"),
    }
    result = replay.replay(case)
    assert result["inputs"]["state"] == "exact_saved"
    assert result["inputs"]["delivery_proof"] == "unknown"
    case["input_capture"]["sha256"] = "wrong"
    assert replay.replay(case)["inputs"]["state"] == "unknown"
    case.pop("input_capture")
    case["regenerated_input"] = "current-template reconstruction"
    assert replay.replay(case)["inputs"]["state"] == "regenerated"


def test_replay_checks_saved_projection_and_refuses_missing_policy_context():
    case = replay.fixture_case("stored")
    projection = replay.replay(case)["projection"]
    case["stored_projection"] = projection
    assert replay.replay(case)["storage_match"] is True
    case["stored_projection"] = {}
    assert replay.replay(case)["storage_match"] is False
    case = replay.fixture_case("copy", suggested_copy={"body": "Historical claim"})
    assert replay.replay(case)["reason_code"] == "policy_context_unavailable"


def test_report_redacts_secrets_and_urls_from_saved_or_human_material():
    case = replay.fixture_case(
        "redact", hypothesis="secret=private-value https://private.test/path"
    )
    case["human_judgment"] = {"access_token": "private-token", "note": "Bearer private-bearer"}
    result = str(replay.replay(case))
    for secret in ("private-value", "private-token", "private-bearer", "private.test"):
        assert secret not in result


def test_changed_evidence_is_not_replayed_as_original_task_and_unfinished_output_is_unknown():
    case = replay.fixture_case("changed")
    case["review"]["evidence_json"]["limitations"].append("new facts")
    assert replay.replay(case)["reason_code"] == "evidence_digest_mismatch"
    case = replay.fixture_case("unfinished")
    case["task"]["status"] = "running"
    assert replay.replay(case)["validator"] == "unknown"
