"""Subprocess-only safety tests for the legacy local runtime seam; no services or DB writes."""

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RUNNER = ROOT / "scripts/verify_ads_semantics.py"


def execute(*args):
    return subprocess.run(
        [sys.executable, str(RUNNER), *args], cwd=ROOT, capture_output=True, text=True, timeout=15
    )


def test_runtime_requires_explicit_isolation_before_service_or_database_access():
    result = execute()
    assert result.returncode == 2
    assert json.loads(result.stdout)["code"] == "isolation_confirmation_required"


def test_shared_database_is_refused_without_printing_credentials(tmp_path):
    env = tmp_path / "private.env"
    env.write_text("DATABASE_URL=postgresql://user:private-password@127.0.0.1/postgres\n", "utf-8")
    result = execute("--isolated", "--env-file", str(env))
    assert result.returncode == 2
    assert json.loads(result.stdout)["code"] == "shared_or_remote_database_refused"
    assert "private-password" not in result.stdout + result.stderr


def test_wrong_owner_is_refused_before_network_or_schema_creation(tmp_path):
    env = tmp_path / "private.env"
    env.write_text(
        "DATABASE_URL=postgresql://user:private-password@127.0.0.1/f15_validation_f55_1234567890\n",
        "utf-8",
    )
    receipt = tmp_path / "owner.json"
    receipt.write_text(json.dumps({"owner": "other", "database": "f15_validation_f55_1234567890"}))
    result = execute("--isolated", "--env-file", str(env), "--ownership-file", str(receipt))
    assert result.returncode == 2
    assert json.loads(result.stdout)["code"] == "database_ownership_mismatch"
