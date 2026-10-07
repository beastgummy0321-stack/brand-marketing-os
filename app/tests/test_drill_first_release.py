"""Synthetic boundary tests; never execute provider/Auth/restore acceptance probes."""

import hashlib
import subprocess

import pytest

from scripts.drill import first_release_acceptance as runner
from scripts.drill import first_release_cases as cases


def test_frozen_input_bytes_and_complete_qualification_counterexamples():
    assert cases.frozen_cases()["periods"][2]["cost_per_result"] == 400
    reports = cases.qualification_cases()
    identifiers = {r["case"] for r in reports}
    assert {"G1-thin", "G2-one", "G3-contrary", "N03-derivatives",
            "N03-replay-overlap", "R02-400-days", "D02-N08-revision"} <= identifiers
    assert all(r.get("raw") and r.get("current") for r in reports)


def test_frozen_case_edit_never_silently_replaces_expectations(tmp_path):
    path = tmp_path / "cases.json"
    path.write_bytes(cases.CASES.read_bytes().replace(b'"events": 2', b'"events": 10'))
    with pytest.raises(ValueError, match="Frozen semantic"):
        cases.frozen_cases(path)


def test_global_migration_exact_skip_and_unknown_global_refusal(tmp_path):
    audit = runner.migration_audit()
    assert {r["path"] for r in audit["skipped_global_bootstraps"]} == set(runner.GLOBAL_BOOTSTRAPS)
    directory = tmp_path / "supabase/migrations"
    directory.mkdir(parents=True)
    (directory / "unexpected.sql").write_text("UPDATE storage.buckets SET public=true;")
    with pytest.raises(runner.ReceiptError, match="global migration"):
        runner.migration_audit(tmp_path)
    (directory / "unexpected.sql").unlink()
    (directory / next(iter(runner.GLOBAL_BOOTSTRAPS))).write_text("SELECT 1")
    with pytest.raises(runner.ReceiptError, match="bootstrap bytes"):
        runner.migration_audit(tmp_path)


def test_bounded_attempt_is_reserved_even_after_a_failed_call(tmp_path):
    runner.once(tmp_path, "provider")
    with pytest.raises(FileExistsError):
        runner.once(tmp_path, "provider")


def test_evidence_refuses_mutation_and_counts_cannot_pass_gate(tmp_path):
    evidence = tmp_path / "raw.json"
    evidence.write_text('{"count": 999, "ok": true}')
    ref = runner.reference(evidence)
    with pytest.raises(runner.ReceiptError, match="lacks matching"):
        runner.validate_gate("G6", {"status": "pass", "hashes": {}, "count": 999}, {})
    evidence.write_text('{"count": 1000, "ok": true}')
    with pytest.raises(runner.ReceiptError, match="bytes changed"):
        runner.dereference(ref)


def test_harness_signature_matches_installed_byte_algorithm(tmp_path):
    def git(*args):
        subprocess.run(["git", *args], cwd=tmp_path, check=True, capture_output=True)

    git("init", "-q")
    git("config", "user.name", "Boundary fixture")
    git("config", "user.email", "fixture@example.test")
    (tmp_path / "source.py").write_bytes(b"raw\r\nbytes\n")
    (tmp_path / ".work/features").mkdir(parents=True)
    (tmp_path / ".work/features/F53.md").write_bytes(b"feature\r\n")
    (tmp_path / ".work/done").mkdir()
    (tmp_path / ".work/done/F53-I02.md").write_bytes(b"second\r\n")
    (tmp_path / ".work/done/F53-I01.md").write_bytes(b"first\n")
    git("add", ".")
    git("commit", "-qm", "Fixture")
    signature, inputs = runner.integration_signature(tmp_path)
    expected = hashlib.sha256()
    expected.update(runner.source_fingerprint(tmp_path).encode())
    expected.update(runner.git(tmp_path, "rev-parse", "HEAD").strip())
    expected.update(b"feature\r\n")
    expected.update(b"doneF53-I01first\n")
    expected.update(b"doneF53-I02second\r\n")
    assert signature == expected.hexdigest()
    assert inputs["issues"][0]["id"] == "F53-I01"
    (tmp_path / ".work/done/F53-I01.md").write_bytes(b"first\r\n")
    assert runner.integration_signature(tmp_path)[0] != signature


def test_readonly_preintegration_never_calls_a_probe(tmp_path, monkeypatch):
    packet = {"feature": "F53", "cases_sha256": cases.CASES_SHA256, "gates": {},
              "G8": {"status": "pending", "sidecar": ".harness/scratch/F53/final"}}
    path = tmp_path / "packet.json"
    runner.write(path, packet)
    monkeypatch.setattr(runner, "command", lambda *a, **k: pytest.fail("executed a command"))
    with pytest.raises(runner.ReceiptError, match="G1 remains missing"):
        runner.check_receipt(path, pre_integration=True, hashes={})
