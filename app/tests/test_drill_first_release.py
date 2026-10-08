"""Synthetic boundary tests; never execute provider/Auth/restore acceptance probes."""

import hashlib
import json
import subprocess
from types import SimpleNamespace
from typing import Any, cast

import pytest

from scripts.drill import first_release_acceptance as runner
from scripts.drill import first_release_cases as cases


@pytest.mark.parametrize("error_name,expected_type", [
    ("TimeoutError", "TimeoutError"), ("credential-error-marker", "Error"),
])
def test_auth_browser_real_login_selector_and_failed_stage_are_credential_safe(
    error_name, expected_type
):
    """Execute the actual browser script against in-memory Node boundaries, without a browser."""
    import re
    import shutil

    node = shutil.which("node")
    assert node, "Harness Node runtime is required for the browser-script regression"
    login_source = (runner.ROOT / "frontend/src/components/auth/LoginPage.tsx").read_text(
        encoding="utf-8"
    )
    assert 'type="text"' in login_source
    assert re.search(r'<label\b[^>]*>.*?>Email</span>.*?<Input\s+type="text"', login_source, re.S)
    script = "\n".join(
        line for line in runner.AUTH_BROWSER.splitlines() if not line.startswith("import ")
    )
    harness = r"""
const crypto = require('node:crypto');
const calls = [], diagnostics = [];
const cfg = {email:'credential-email-marker', password:'credential-password-marker',
  origin:'http://owned.invalid', directory:'owned-directory', frontend_package:'owned-package'};
const fs = {existsSync:()=>true, readFileSync:filename=>JSON.stringify(
  String(filename).endsWith('browser-contained.json') ? {pid:process.pid} : cfg),
  writeFileSync:(filename, content)=>diagnostics.push(JSON.parse(content))};
const page = {on:()=>{}, goto:async()=>{},
  getByLabel:label=>({fill:async()=>calls.push({kind:'label', label})}),
  locator:selector=>({fill:async()=>calls.push({kind:'selector', selector}),
    click:async()=>{const e = Error(cfg.email+' '+cfg.password+' Authorization secret-token');
          e.name=ERROR_NAME; throw e;}})};
const createRequire = () => () => ({chromium:{launch:async()=>({
  newPage:async()=>page, close:async()=>calls.push({kind:'closed'})})}});
const AsyncFunction = Object.getPrototypeOf(async function(){}).constructor;
new AsyncFunction('crypto','fs','createRequire', SOURCE)(crypto,fs,createRequire).catch(error=>{
  console.log(JSON.stringify({calls,diagnostics,error:error.message}));
});
    """.replace("SOURCE", json.dumps(script)).replace("ERROR_NAME", json.dumps(error_name))
    result = subprocess.run([node], input=harness, text=True, capture_output=True, timeout=10)
    assert result.returncode == 0
    output = result.stdout + result.stderr
    for secret in (
        "credential-email-marker", "credential-password-marker", "secret-token",
        "credential-error-marker",
    ):
        assert secret not in output
    actual = json.loads(result.stdout)
    assert {"kind": "label", "label": "Email"} in actual["calls"]
    assert {"kind": "selector", "selector": "input[type=email]"} not in actual["calls"]
    assert actual["calls"][-1] == {"kind": "closed"}
    assert actual["diagnostics"][-1]["stage"] == "initial-login"
    assert actual["diagnostics"][-1]["status"] == "unverified"
    assert actual["diagnostics"][-1]["error_type"] == expected_type
    assert set(actual["diagnostics"][-1]) == {"stage", "status", "at", "error_type"}
    assert actual["error"] == "Owned Auth browser failed at finite stage: initial-login"


@pytest.mark.parametrize(
    "caller,dsn_name", [(runner.run_provider, "dsn"), (runner.auth_probe, "scoped")]
)
def test_operational_app_connection_seams_supply_real_dict_row(caller, dsn_name):
    """Evaluate each actual connect expression with a strict in-memory psycopg boundary."""
    import ast
    import inspect

    from psycopg.pq import ExecStatus
    from psycopg.rows import dict_row

    from app.brand_intelligence import repository
    from app.core import db

    class Cursor:
        description = ("id", "name")
        rowcount = 1
        _encoding = "utf-8"
        pgresult = SimpleNamespace(
            nfields=2, status=ExecStatus.TUPLES_OK, fname=lambda index: (b"id", b"name")[index]
        )

        def __init__(self, factory):
            self.make_row = factory(self) if factory else tuple

        def fetchall(self):
            return [self.make_row(("brd_synthetic", "Owned brand"))]

    class Connection:
        def __init__(self, **kwargs):
            self.factory = kwargs.get("row_factory")

        def execute(self, query, parameters=()):
            return Cursor(self.factory)

    calls = []

    def connect(*args, **kwargs):
        calls.append(kwargs)
        return Connection(**kwargs)

    tree = ast.parse(inspect.getsource(caller))
    expression = next(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "connect"
        and node.args
        and isinstance(node.args[0], ast.Name)
        and node.args[0].id == dsn_name
    )
    scope = {
        "psycopg": SimpleNamespace(connect=connect),
        dsn_name: "synthetic-dsn",
        "dict_row": dict_row,
        "cast": cast,
        "Any": Any,
    }
    raw = eval(compile(ast.Expression(expression), "<actual-connect-seam>", "eval"), scope)
    assert calls[-1]["row_factory"] is dict_row
    assert repository.get_brand(db.Conn(cast(Any, raw)), "brd_synthetic") == {
        "id": "brd_synthetic",
        "name": "Owned brand",
    }
    # Default tuples reproduce the actual pre-browser failure through the same public read.
    with pytest.raises(ValueError):
        repository.get_brand(db.Conn(cast(Any, Connection())), "brd_synthetic")


@pytest.mark.parametrize("auth_status", ["unverified", "pass"])
def test_operational_incomplete_auth_and_pass_restore_remain_unverified(
    tmp_path, monkeypatch, auth_status
):
    context = {
        "directory": str(tmp_path),
        "hashes": {"probe": "synthetic"},
        "run_id": "synthetic-run",
        "gates": {},
    }
    monkeypatch.setattr(runner, "context_at", lambda path: context)
    monkeypatch.setattr(
        runner, "command", lambda *a, **kw: pytest.fail("No actual operation allowed")
    )
    restored = []
    monkeypatch.setattr(runner, "verify_restore_receipt", lambda receipt: restored.append(receipt))
    auth = {"status": auth_status, "cleanup": {"database": True, "browser": False}}
    restore = {"status": "pass", "cleanup": {"storage": True, "target_database": True}}
    runner.write(tmp_path / "auth-receipt.json", auth)
    runner.write(tmp_path / "restore-receipt.json", restore)
    original_bytes = [
        (tmp_path / name).read_bytes() for name in ("auth-receipt.json", "restore-receipt.json")
    ]
    record = runner.record_operations(tmp_path / "context.json")
    assert record["status"] == "unverified"
    assert restored == [restore]
    assert record["cleanup"] == {
        "auth.database": True,
        "auth.browser": False,
        "restore.storage": True,
        "restore.target_database": True,
    }
    assert len(record["evidence"]) == 2
    assert [runner.dereference(ref) for ref in record["evidence"]] == original_bytes
    with pytest.raises(runner.ReceiptError, match="remains unverified"):
        runner.validate_gate("G7", record, context["hashes"])


@pytest.mark.parametrize("bad_mode", ["auth", "restore"])
def test_operational_either_failed_mode_cannot_be_substituted_by_other_pass(
    tmp_path, monkeypatch, bad_mode
):
    context = {"directory": str(tmp_path), "hashes": {}, "run_id": "mock", "gates": {}}
    monkeypatch.setattr(runner, "context_at", lambda path: context)
    called = []
    monkeypatch.setattr(runner, "verify_auth_receipt", lambda receipt: called.append("auth"))
    monkeypatch.setattr(runner, "verify_restore_receipt", lambda receipt: called.append("restore"))
    for mode in ("auth", "restore"):
        runner.write(
            tmp_path / (mode + "-receipt.json"),
            {"status": "unverified" if mode == bad_mode else "pass", "cleanup": {"owned": True}},
        )
    record = runner.record_operations(tmp_path / "context.json")
    assert record["status"] == "unverified"
    assert called == ["restore" if bad_mode == "auth" else "auth"]
    assert record["cleanup"] == {"auth.owned": True, "restore.owned": True}
    assert len(record["evidence"]) == 2


def test_frozen_input_bytes_and_complete_qualification_counterexamples():
    assert cases.frozen_cases()["periods"][2]["cost_per_result"] == 400
    reports = cases.qualification_cases()
    identifiers = {r["case"] for r in reports}
    assert {
        "G1-thin",
        "G2-one",
        "G3-contrary",
        "N03-derivatives",
        "N03-replay-overlap",
        "R02-400-days",
        "D02-N08-revision",
    } <= identifiers
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


def test_effective_cycle_config_binds_file_first_values_without_disclosing_secrets(tmp_path):
    from scripts import verify_existing_campaigns_assets as lifecycle

    environment = {"DATABASE_URL": "shell-db-secret", "SUPABASE_JWT_SECRET": "shell-jwt-secret"}
    args = SimpleNamespace(env_file=None)
    original = runner.runtime_config_hash(tmp_path, environment)
    (tmp_path / ".env").write_text(
        "DATABASE_URL=\"file-db-secret\"\nSUPABASE_JWT_SECRET='file-jwt-secret'\n"
    )
    resolved = lifecycle.resolved_env(args, root=tmp_path, environment=environment)
    assert resolved["DATABASE_URL"] == "file-db-secret"
    assert resolved["SUPABASE_JWT_SECRET"] == "file-jwt-secret"
    current = runner.runtime_config_hash(tmp_path, environment)
    assert current != original
    assert len(current) == 64 and "secret" not in current
    (tmp_path / ".env").write_text("DATABASE_URL=file-db-secret\nSUPABASE_JWT_SECRET=changed-jwt\n")
    assert runner.runtime_config_hash(tmp_path, environment) != current


def test_safe_env_uses_the_same_readonly_resolution_and_preserves_admission(tmp_path, monkeypatch):
    from scripts import verify_existing_campaigns_assets as lifecycle

    monkeypatch.setattr(lifecycle, "ROOT", tmp_path)
    monkeypatch.setenv("DATABASE_URL", "shell-db")
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "shell-service-key")
    (tmp_path / ".env").write_text("DATABASE_URL=file-db\nSUPABASE_SERVICE_ROLE_KEY=file-key\n")
    args = SimpleNamespace(env_file=None)
    assert lifecycle.safe_env(args) == lifecycle.resolved_env(args, root=tmp_path)
    assert lifecycle.safe_env(args)["DATABASE_URL"] == "file-db"
    (tmp_path / ".env").write_text("DATABASE_URL=\nSUPABASE_SERVICE_ROLE_KEY=file-key\n")
    with pytest.raises(RuntimeError, match="Provide local DATABASE_URL"):
        lifecycle.safe_env(args)


@pytest.mark.parametrize("key", ["DATABASE_URL", "SUPABASE_URL", "IDENTITY_ALLOW_HS256", "PGPORT"])
def test_effective_config_detects_direct_shell_drift_even_when_cycle_file_wins(tmp_path, key):
    from scripts import verify_existing_campaigns_assets as lifecycle

    (tmp_path / ".env").write_text("DATABASE_URL=file-db\nSUPABASE_URL=http://127.0.0.1:54321\n")
    environment = {"DATABASE_URL": "shell-db", "SUPABASE_URL": "http://127.0.0.1:54321"}
    previous = runner.runtime_config_hash(tmp_path, environment)
    after = {**environment, key: "changed-direct-setting"}
    assert runner.runtime_config_hash(tmp_path, after) != previous
    if key == "DATABASE_URL":
        args = SimpleNamespace(env_file=None)
        assert lifecycle.resolved_env(args, root=tmp_path, environment=after)[key] == "file-db"


@pytest.mark.parametrize(
    "filename", [".env", ".env.local", ".env.production", ".env.production.local"]
)
def test_effective_config_binds_frontend_production_dotenv_inputs(tmp_path, filename):
    (tmp_path / "frontend").mkdir()
    path = tmp_path / "frontend" / filename
    previous = runner.runtime_config_hash(tmp_path, {})
    path.write_text("VITE_SUPABASE_URL=http://127.0.0.1:54321\nVITE_SUPABASE_ANON_KEY=secret\n")
    current = runner.runtime_config_hash(tmp_path, {})
    assert current != previous
    path.write_text("VITE_SUPABASE_URL=http://127.0.0.1:59999\nVITE_SUPABASE_ANON_KEY=secret\n")
    assert runner.runtime_config_hash(tmp_path, {}) != current


def test_readonly_context_check_refuses_ignored_env_drift_without_launching_probe(
    tmp_path, monkeypatch
):
    environment = {"DATABASE_URL": "original-shell-db"}
    monkeypatch.setattr(runner, "ROOT", tmp_path)
    monkeypatch.setattr(
        runner,
        "relevant_hashes",
        lambda: {"runtime_config": runner.runtime_config_hash(tmp_path, environment)},
    )
    monkeypatch.setattr(
        runner, "command", lambda *a, **kw: pytest.fail("Readonly check launched a command")
    )
    directory = tmp_path / ".scratch/F53/owned"
    cases_path = tmp_path / "cases.json"
    cases_path.write_text("{}")
    context = {
        "directory": str(directory),
        "feature": "F53",
        "nonce": "a" * 32,
        "cases": runner.reference(cases_path),
        "hashes": runner.relevant_hashes(),
    }
    runner.write(directory / "context.json", context)
    assert runner.context_at(directory / "context.json") == context
    (tmp_path / ".env").write_text("DATABASE_URL=changed-file-db\n")
    with pytest.raises(runner.ReceiptError, match="configuration changed"):
        runner.context_at(directory / "context.json")


def test_readonly_preintegration_never_calls_a_probe(tmp_path, monkeypatch):
    packet = {
        "feature": "F53",
        "cases_sha256": cases.CASES_SHA256,
        "gates": {},
        "G8": {"status": "pending", "sidecar": ".harness/scratch/F53/final"},
    }
    path = tmp_path / "packet.json"
    runner.write(path, packet)
    monkeypatch.setattr(runner, "command", lambda *a, **k: pytest.fail("executed a command"))
    with pytest.raises(runner.ReceiptError, match="G1 remains missing"):
        runner.check_receipt(path, pre_integration=True, hashes={})


@pytest.mark.parametrize(
    "statement",
    [
        'UPDATE "storage"."buckets" SET public=true;',
        'INSERT INTO "auth"."users" (id) VALUES (1);',
        'DELETE FROM "public"."brand";',
        'TRUNCATE TABLE "storage"."objects";',
        'ALTER TABLE "auth"."users" ADD COLUMN unsafe int;',
    ],
)
def test_quoted_global_writes_fail_before_connect(tmp_path, statement):
    directory = tmp_path / "supabase/migrations"
    directory.mkdir(parents=True)
    (directory / "unsafe.sql").write_text(statement)
    with pytest.raises(runner.ReceiptError, match="global migration"):
        runner.migration_audit(tmp_path)


def test_manifest_requirements_are_independent_and_use_real_fallbacks(tmp_path):
    (tmp_path / ".work/features").mkdir(parents=True)
    (tmp_path / ".work/features/F53.md").write_text(
        '---\n{"verify":["feature-check"],"runtime":["runtime-check"]}\n---\n'
    )
    (tmp_path / "ARCHITECTURE.md").write_text(
        '---\n{"verify":{"typecheck_before_test":null,"typecheck":"types",'
        '"build":"build","test":"tests","smoke_after_build":"smoke-build",'
        '"smoke":"smoke-fallback"}}\n---\n'
    )
    assert set(runner.required_integration_steps(tmp_path)) == {
        "container checker",
        "feature-check",
        "runtime-check",
        "types",
        "build",
        "tests",
        "smoke-build",
    }


def auth_fixture(tmp_path):
    """Receipt-only fixture: no token signing, GoTrue or browser execution."""
    issued = {
        "access_sha256": "token-A",
        "iat": 1,
        "exp": 45,
        "session_id": "owned-session",
        "sub": "owned-user",
    }
    saved = {"id": "campaign-A", "org_id": "owned-org", "sha256": "saved-bytes"}
    browser = {
        "auth_js_version": "2.112.4",
        "issuances": [issued],
        "same_token_expired_sha256": "token-A",
        "before_access_sha256": "token-A",
        "before_status": 200,
        "access_expired_status": 401,
        "before_at": 44000,
        "expired_at": 45001,
        "login_at": 46000,
        "recovered_at": 47000,
        "revocation_status": 204,
        "refresh_refused_status": 400,
        "refresh_error_code": "refresh_token_not_found",
        "saved_work": saved,
        "recovered_work": dict(saved),
        "product_requests": [],
        "requests_after_relogin": [],
    }
    path = tmp_path / "auth-browser-receipt.json"
    runner.write(path, browser)
    ownership = tmp_path / "browser-ownership.json"
    runner.write(
        ownership,
        {"pid": 123, "start_identity": "owned-start", "cleanup": True, "launcher_ended": True},
    )
    receipt = {
        "status": "pass",
        "auth_image": runner.AUTH_IMAGE,
        "auth_version": runner.AUTH_VERSION,
        "namespace": "auth",
        "search_path": "auth,pg_catalog",
        "database": "owned-db",
        "database_identity": {
            "database": "owned-db",
            "schema": "auth",
            "search_path": "auth,pg_catalog",
            "role": "owned-role",
        },
        "container_identity": {
            "id": "owned-id",
            "created": "created",
            "started": "started",
            "owner": "nonce",
            "image": runner.AUTH_IMAGE,
        },
        "browser": runner.reference(path),
        "browser_ownership": runner.reference(ownership),
        "refresh_success_control": {"status": 200},
        "cleanup": {"all_owned": True},
    }
    return receipt, browser, path


@pytest.mark.parametrize(
    "mutation",
    [
        "different-token",
        "write",
        "missing-tracker",
        "not-expired",
        "fake-refusal",
        "wrong-work",
        "missing-schema",
        "leaked-browser",
    ],
)
def test_auth_receipt_rejects_false_controls_and_cleanup(tmp_path, mutation):
    receipt, browser, path = auth_fixture(tmp_path)
    runner.verify_auth_receipt(receipt)
    if mutation == "different-token":
        browser["before_access_sha256"] = "token-B"
    elif mutation == "write":
        browser["product_requests"] = [{"at": 46001, "method": "POST", "path": "/api/save"}]
        browser["requests_after_relogin"] = list(browser["product_requests"])
    elif mutation == "missing-tracker":
        del browser["product_requests"]
    elif mutation == "not-expired":
        browser["expired_at"] = 44999
    elif mutation == "fake-refusal":
        browser["refresh_refused_status"] = 500
    elif mutation == "wrong-work":
        browser["recovered_work"]["id"] = "replacement"
    elif mutation == "missing-schema":
        receipt["database_identity"]["schema"] = "public"
    elif mutation == "leaked-browser":
        receipt["cleanup"]["browser"] = False
    runner.write(path, browser)
    receipt["browser"] = runner.reference(path)
    with pytest.raises(runner.ReceiptError):
        runner.verify_auth_receipt(receipt)


def test_container_timeout_discovery_requires_exact_name_owner_image(tmp_path, monkeypatch):
    actual = {
        "Id": "owned-id",
        "Name": "/owned-name",
        "Image": runner.AUTH_IMAGE,
        "Created": "start",
        "State": {"StartedAt": "running"},
        "Config": {"Labels": {"f53.owner": "nonce"}},
    }
    monkeypatch.setattr(
        runner,
        "command",
        lambda *a, **k: SimpleNamespace(returncode=0, stdout=json.dumps([actual]).encode()),
    )
    assert runner.inspect_owned_container("owned-name", "nonce")["id"] == "owned-id"
    actual["Config"]["Labels"]["f53.owner"] = "another-owner"
    with pytest.raises(runner.ReceiptError, match="ownership changed"):
        runner.inspect_owned_container("owned-name", "nonce")
    monkeypatch.setattr(runner, "command", lambda *a, **k: SimpleNamespace(returncode=1))
    with pytest.raises(runner.ReceiptError, match="unverified"):
        runner.inspect_owned_container("owned-name", "nonce")


def test_child_cli_accepts_existing_lifecycle_shape_without_executing_probe(monkeypatch, tmp_path):
    calls = []
    context = tmp_path / "context.json"
    monkeypatch.setattr(
        runner.sys, "argv", ["runner", "--child", "--context", str(context), "--port", "8758"]
    )
    monkeypatch.setattr(runner, "first_release_child", lambda *a: calls.append(a))
    runner.main()
    assert calls == [(context, 8758)]


def test_cleanup_cli_rejects_shared_prefix_without_storage_access(monkeypatch):
    monkeypatch.setattr(runner.sys, "argv", ["runner", "--cleanup-storage", "org_shared"])
    with pytest.raises(SystemExit) as failure:
        runner.main()
    assert failure.value.code == 1


def test_browser_timeout_kills_owned_job_and_preserves_identity(tmp_path, monkeypatch):
    from scripts.drill import recovery_probe

    class Process:
        pid = 123
        returncode = None

        def communicate(self, timeout):
            assert runner.read(tmp_path / "browser-contained.json")["pid"] == self.pid
            raise subprocess.TimeoutExpired("owned-node", timeout)

        def wait(self, timeout):
            self.returncode = -1

        def poll(self):
            return self.returncode

    terminated = []

    class Kernel:
        def TerminateJobObject(self, handle, code):
            terminated.append((handle, code))
            return True

        def CloseHandle(self, handle):
            terminated.append((handle, "close"))

    monkeypatch.setattr(runner.subprocess, "Popen", lambda *a, **k: Process())
    monkeypatch.setattr(runner, "browser_job", lambda process: (Kernel(), "private-job"))
    monkeypatch.setattr(
        recovery_probe,
        "process_identity",
        lambda pid: {"pid": pid, "start_identity": "owned-start"},
    )
    with pytest.raises(subprocess.TimeoutExpired):
        runner.bounded_browser(["never-executed"], tmp_path, timeout=1, env={})
    assert terminated == [("private-job", 1), ("private-job", "close")]
    assert runner.read(tmp_path / "browser-ownership.json")["cleanup"] is True


@pytest.mark.parametrize(
    "statement",
    [
        "MERGE INTO storage.buckets USING x ON true WHEN MATCHED THEN DELETE;",
        "CREATE POLICY unsafe ON storage.objects USING (true);",
        "DO $$ BEGIN EXECUTE 'UPDATE ' || 'storage.buckets SET public=true'; END $$;",
    ],
)
def test_complete_migration_admission_refuses_sql_beyond_pattern_match(tmp_path, statement):
    directory = tmp_path / "supabase/migrations"
    directory.mkdir(parents=True)
    (directory / "unreviewed.sql").write_text(statement)
    with pytest.raises(runner.ReceiptError, match="migration bytes changed"):
        runner.migration_audit(tmp_path)


def grain_period_fixture(period=None):
    """Hand-authored retained reports: two children in one group, one zero child in another."""
    period = period or cases.frozen_cases()["periods"][0]
    count = period["events"] // 2
    campaign_id = "grain-" + period["id"]
    groups = [
        {"id": "group-A", "external_id": "native-group-A", "ads": [
            {"id": "ad-A1", "external_id": "native-ad-A1"},
            {"id": "ad-A2", "external_id": "native-ad-A2"},
        ]},
        {"id": "group-B", "external_id": "native-group-B", "ads": [
            {"id": "ad-B1", "external_id": "native-ad-B1"},
        ]},
    ]
    common = {"org_id": "owned-org", "brand_id": "owned-brand", "campaign_id": campaign_id}
    entities, raw_ads, raw_groups, members = [], [], [], []
    for group_index, group in enumerate(groups):
        group_entity = "entity-" + group["id"]
        entities.append({**common, "id": group_entity, "native_kind": "adset",
                         "native_id": group["external_id"], "platform": "test",
                         "source_account": "test"})
        children = []
        for ad in group["ads"]:
            entity_id = "entity-" + ad["id"]
            entities.append({**common, "id": entity_id, "native_kind": "ad",
                             "native_id": ad["external_id"], "parent_native_kind": "adset",
                             "parent_native_id": group["external_id"], "platform": "test",
                             "source_account": "test"})
            row = {
                **common, "id": "source-" + ad["id"], "entity_id": entity_id,
                "metric_scope": "ad", "day": period["end"], "source": "graph",
                "currency": "TWD", "attribution_key": "fixed-known-fixture",
                "result_attribution": "fixed-known-fixture", "result_kind": "purchase",
                "result_action": "omni_purchase", "revenue": None,
                "spend": count * period["cost_per_result"] if group_index == 0 else 0,
                "purchases": count if group_index == 0 else 0,
                "result_count": count if group_index == 0 else 0,
                "impressions": 1000, "clicks": 30,
            }
            children.append(row)
            raw_ads.append(row)
        group_count = period["events"] if group_index == 0 else 0
        report = {**children[0], "id": "source-" + group["id"], "entity_id": group_entity,
                  "metric_scope": "adset", "spend": group_count * period["cost_per_result"],
                  "purchases": group_count, "result_count": group_count,
                  "impressions": 2000 if group_index == 0 else 1000,
                  "clicks": 60 if group_index == 0 else 30}
        raw_groups.append(report)
        members.append({
            "group_id": group["id"], "group_entity_id": group_entity,
            "group_native_id": group["external_id"], "group_observation_id": report["id"],
            "child_ad_ids": [ad["id"] for ad in group["ads"]],
            "child_entity_ids": [row["entity_id"] for row in children],
            "child_native_ids": [ad["external_id"] for ad in group["ads"]],
            "child_observation_ids": [row["id"] for row in children], "trial_id": campaign_id,
        })
    return {"period": period, "accepted": {"id": campaign_id, "groups": groups,
                                          "org_id": "owned-org", "brand_id": "owned-brand"},
            "observations": {"raw_observations": raw_ads, "raw_group_observations": raw_groups,
                             "bound_entities": entities, "bound_groups": groups,
                             "group_membership": members}}


@pytest.mark.parametrize("mutation", [
    "missing-group", "duplicate-group", "missing-ad", "duplicate-ad", "wrong-group",
    "wrong-source-row", "wrong-local-ad-binding", "wrong-value", "grain-mixing", "double-total",
    "new-trial", "wrong-day", "unknown-revenue-as-zero", "wrong-account", "foreign-owner-packet",
])
def test_raw_group_reports_cannot_duplicate_or_change_frozen_child_facts(mutation):
    period = grain_period_fixture()
    runner.verify_observation_grains(period)
    data = period["observations"]
    if mutation == "missing-group":
        data["raw_group_observations"].pop()
    elif mutation == "duplicate-group":
        data["raw_group_observations"].append(dict(data["raw_group_observations"][0]))
    elif mutation == "missing-ad":
        data["raw_observations"].pop()
    elif mutation == "duplicate-ad":
        data["raw_observations"].append(dict(data["raw_observations"][0]))
    elif mutation == "wrong-group":
        data["bound_entities"][1]["parent_native_id"] = "native-group-B"
    elif mutation == "wrong-source-row":
        data["group_membership"][0]["child_observation_ids"][0] = "source-ad-B1"
    elif mutation == "wrong-local-ad-binding":
        data["bound_groups"][0]["ads"][0]["external_id"] = "another-native-ad"
    elif mutation == "wrong-value":
        data["raw_group_observations"][0]["spend"] = 401
    elif mutation == "grain-mixing":
        data["raw_group_observations"][0]["metric_scope"] = "ad"
    elif mutation == "double-total":
        data["raw_observations"].extend(data["raw_group_observations"])
    elif mutation == "new-trial":
        data["group_membership"][0]["trial_id"] = "new-independent-trial"
    elif mutation == "wrong-day":
        data["raw_group_observations"][0]["day"] = "2026-07-30"
    elif mutation == "unknown-revenue-as-zero":
        data["raw_group_observations"][0]["revenue"] = 0
    elif mutation == "wrong-account":
        data["bound_entities"][0]["source_account"] = "foreign-account"
    else:
        for row in [*data["raw_observations"], *data["raw_group_observations"],
                    *data["bound_entities"]]:
            row["org_id"], row["brand_id"] = "foreign-org", "foreign-brand"
    with pytest.raises(runner.ReceiptError):
        runner.verify_observation_grains(period)


def http_cycle_fixture():
    """Raw reader/HTTP fixture only: does not execute a cycle or claim real acceptance."""
    from copy import deepcopy

    periods = []
    for index, period in enumerate(cases.frozen_cases()["periods"]):
        identity = "controlled-" + str(index)
        item = {
            "id": identity,
            "sample": {"result_events": period["events"]},
            "scope": {"product_id": "product-A"},
            "use_state": "usable",
            "independent_count": index,
            "same_direction_count": int(index > 0),
            "contrary_count": int(index == 2),
            "allowed_uses": ["market_support"] if index == 1 else ["test", "retain_control"],
            "support_label": "qualified-" + str(index),
        }
        b = {
            **item,
            "id": "product-B-" + str(index),
            "scope": {"product_id": "product-B"},
            "use_state": "excluded",
            "allowed_uses": [],
        }
        decision = {
            "revision": "period-" + str(index),
            "slots": [
                {
                    "customer_group_id": "A1",
                    "carry_from_ad_id": None,
                    "evidence_refs": [{"kind": "learning", "id": "controlled-" + str(index - 1)}]
                    if index
                    else [{"kind": "brand_fact", "id": "fact-A"}],
                }
            ],
        }
        proposal = {
            "id": "grain-" + period["id"],
            "budget_basis_json": {"strategy": {"decision": decision}},
        }
        raw = {
            "source_ref": {"trial_id": "trial-" + str(index)},
            "period": {"start": period["start"], "end": period["end"]},
            "source_version": "source-" + str(index),
            "source_kind": "campaign",
        }
        injected = []
        derivative_items = []
        for kind in ("coordinate", "visual", "replay", "product-B"):
            evidence = deepcopy(raw)
            if kind == "replay":
                evidence["period"]["start"] = evidence["period"]["end"]
                evidence["source_version"] += "-replay"
            elif kind in {"coordinate", "visual"}:
                evidence["source_kind"] = kind
            else:
                evidence["source_ref"]["trial_id"] = "trial-B"
            derived = b if kind == "product-B" else {**item, "id": kind + "-" + str(index)}
            derivative_items.append(derived)
            injected.append(
                {
                    "id": derived["id"],
                    "product_id": derived["scope"]["product_id"],
                    "fixture_kind": kind,
                    "fixture_evidence": evidence,
                }
            )
        periods.append(
            {
                "period": period,
                "proposal": proposal,
                "reader": {"evidence_context": {"items": [item, b, *derivative_items[:-1]]}},
                "accepted": grain_period_fixture(period)["accepted"],
                "observations": {
                    **grain_period_fixture(period)["observations"],
                    "controlled_learning": {"id": identity},
                },
                "derivatives": {
                    "injected": injected,
                    "original": {"id": identity},
                    "original_evidence": raw,
                },
            }
        )
    prior = deepcopy(periods[1]["reader"]["evidence_context"]["items"][0])
    prior.update(use_state="history", allowed_uses=[])
    periods[2]["reader"]["evidence_context"]["items"].append(prior)
    contexts = []
    for index, period in enumerate(periods):
        delivered = (
            [] if not index else [periods[index - 1]["reader"]["evidence_context"]["items"][0]]
        )
        text = delivered[0]["support_label"] if delivered else "No prior learning"
        contexts.append(
            {
                "campaign": period["proposal"]["id"],
                "items": delivered,
                "sections": {"learnings": text, "ranked": "Ranks"},
                "prompt": text + " Ranks",
                "binding": {
                    "evidence_refs": period["proposal"]["budget_basis_json"]["strategy"][
                        "decision"
                    ]["slots"][0]["evidence_refs"]
                },
            }
        )
    stale = []
    for kind in ("offer", "price", "material", "target", "same-ID-meaning"):
        proposed = {
            "budget_basis_json": {
                "strategy": {
                    "decision": {
                        "revision": kind,
                        "slots": [{"customer_group_id": "A2", "carry_from_ad_id": None}],
                    }
                }
            }
        }
        fresh = deepcopy(proposed)
        fresh["budget_basis_json"]["strategy"]["decision"]["revision"] += "-fresh"
        retained = {field: None for field in runner.RETAINED_FIELDS}
        retained.update(
            goal_text="Retained explicit synthetic test input",
            context_json={"product_ids": ["product-A"]},
            start_date="2026-10-01",
            end_date="2026-10-31",
            target_cost=300,
        )
        after = deepcopy(retained)
        if kind == "target":
            after["target_cost"] = 301
        stale.append(
            {
                "kind": kind,
                "proposal": proposed,
                "refreshed": fresh,
                "rejection": {"status": 409, "body": {"error": {"code": "strategy_changed"}}},
                "mutation": {
                    "before": 300,
                    "after": 301,
                    "id": "controlled-1",
                    "proposal_refs": [{"kind": "learning", "id": "controlled-1"}],
                },
                "retained_before": retained,
                "retained_after": after,
                "served_after_rejection": {**after, "groups": []},
                "adopted": {},
            }
        )
    return {
        "periods": periods,
        "stale_cases": stale,
        "consumer_contexts": contexts,
    }


@pytest.mark.parametrize(
    "mutation",
    [
        "thin-promotes",
        "independent-inflation",
        "product-B",
        "prior-still-market",
        "missing-stale",
        "dirty-input",
        "no-refresh",
        "wrong-ref",
        "no-adaptation",
        "missing-period-prompt",
        "missing-prompt-section",
        "facts-only-after-support",
        "wrong-409",
        "lost-goal",
        "lost-product",
        "missing-derivative",
        "empty-derivatives",
        "wrong-trial",
        "wrong-window",
        "unrelated-meaning",
    ],
)
def test_actual_http_gate_checks_raw_results_instead_of_pass_counts(monkeypatch, mutation):
    cycle = http_cycle_fixture()
    monkeypatch.setattr(runner, "check_adopted_bindings", lambda *a: None)
    runner.verify_http_cycle(cycle)
    if mutation == "thin-promotes":
        cycle["periods"][0]["reader"]["evidence_context"]["items"][0]["allowed_uses"] = [
            "market_support"
        ]
    elif mutation == "independent-inflation":
        cycle["periods"][1]["reader"]["evidence_context"]["items"][0]["independent_count"] = 4
    elif mutation == "product-B":
        cycle["periods"][1]["reader"]["evidence_context"]["items"][1]["allowed_uses"] = [
            "market_support"
        ]
    elif mutation == "prior-still-market":
        cycle["periods"][2]["reader"]["evidence_context"]["items"][-1]["allowed_uses"] = [
            "market_support"
        ]
    elif mutation == "missing-stale":
        cycle["stale_cases"].pop()
    elif mutation == "dirty-input":
        cycle["stale_cases"][0]["retained_after"]["goal_text"] = "silently-replaced"
    elif mutation == "no-refresh":
        cycle["stale_cases"][0]["refreshed"] = cycle["stale_cases"][0]["proposal"]
    elif mutation == "wrong-ref":
        cycle["consumer_contexts"][0]["binding"]["evidence_refs"] = [
            {"kind": "result", "id": "fact-A"}
        ]
    elif mutation == "missing-period-prompt":
        cycle["consumer_contexts"].pop()
    elif mutation == "missing-prompt-section":
        cycle["consumer_contexts"][1]["prompt"] = "No qualification received"
    elif mutation == "facts-only-after-support":
        cycle["periods"][2]["proposal"]["budget_basis_json"]["strategy"]["decision"]["slots"][0][
            "evidence_refs"
        ] = [{"kind": "brand_fact", "id": "fact-A"}]
        cycle["consumer_contexts"][2]["binding"]["evidence_refs"] = [
            {"kind": "brand_fact", "id": "fact-A"}
        ]
    elif mutation == "wrong-409":
        cycle["stale_cases"][0]["rejection"]["body"]["error"]["code"] = "campaign_busy"
    elif mutation == "lost-goal":
        cycle["stale_cases"][0]["served_after_rejection"]["goal_text"] = None
    elif mutation == "lost-product":
        cycle["stale_cases"][0]["served_after_rejection"]["context_json"]["product_ids"] = []
    elif mutation == "missing-derivative":
        cycle["periods"][0]["derivatives"]["injected"].pop(1)
    elif mutation == "empty-derivatives":
        cycle["periods"][0]["derivatives"]["injected"] = []
    elif mutation == "wrong-trial":
        cycle["periods"][1]["derivatives"]["injected"][0]["fixture_evidence"]["source_ref"][
            "trial_id"
        ] = "unrelated-trial"
    elif mutation == "wrong-window":
        cycle["periods"][1]["derivatives"]["injected"][1]["fixture_evidence"]["period"]["start"] = (
            "2026-01-01"
        )
    elif mutation == "unrelated-meaning":
        cycle["stale_cases"][-1]["mutation"]["id"] = "unrelated-learning"
    else:
        cycle["stale_cases"][0]["proposal"]["budget_basis_json"]["strategy"]["decision"]["slots"][
            0
        ]["customer_group_id"] = "A1"
    with pytest.raises(runner.ReceiptError):
        runner.verify_http_cycle(cycle)


def test_contract_provider_uses_only_delivered_prompt_without_db_lookup(tmp_path, monkeypatch):
    from app.core import db
    from app.llm import providers

    def forbidden_lookup():
        pytest.fail("The canned provider must not fetch an alternate qualification context")

    monkeypatch.setattr(db, "current", forbidden_lookup)
    binding = {
        "customers": [{"id": "A1"}, {"id": "A2"}],
        "carried": [],
        "evidence_refs": [{"kind": "learning", "id": "delivered"}],
    }
    monkeypatch.setattr(providers.ScriptedProvider, "_json_section", lambda *args: binding)
    context = {
        "evidence_dir": str(tmp_path),
        "f53_planning_campaign": "campaign",
        "f53_prompt_delivery": {
            "campaign": "campaign",
            "sections": {"learnings": "Contrary source", "ranked": "Rank"},
            "items": [{"id": "delivered", "contrary_count": 1, "use_state": "usable"}],
        },
    }
    reply = runner.fixture_provider(context).complete(
        messages=[{"role": "user", "content": "Contrary source Rank"}]
    )
    assert json.loads(reply.output_text)["slots"][0]["customer_group_id"] == "A2"
    receipt = json.loads((tmp_path / "consumer-contexts.jsonl").read_text())
    assert receipt["prompt"] == "Contrary source Rank"
    assert receipt["items"][0]["id"] == "delivered"
    with pytest.raises(runner.ReceiptError, match="did not reach"):
        runner.fixture_provider(context).complete(messages=[{"role": "user", "content": "Absent"}])


@pytest.mark.parametrize("bad_refs", [None, [], [{"kind": "learning", "id": "invented"}]])
def test_provider_structural_checker_requires_supplied_evidence_bindings(bad_refs):
    from copy import deepcopy

    output = deepcopy(runner.provider_input()["output_shape"])
    task = {"status": "succeeded", "rendered_output": json.dumps(output)}
    assert runner.validate_provider_output(task)["status"] == "contract-pass"
    output["slots"][0]["evidence_refs"] = bad_refs
    task["rendered_output"] = json.dumps(output)
    assert runner.validate_provider_output(task)["status"] == "unverified"


def integration_fixture(tmp_path, monkeypatch):
    """All receipts synthetic; isolates the readonly final-seal checker seam."""
    monkeypatch.setattr(runner, "validate_gate", lambda *a: None)
    monkeypatch.setattr(
        runner, "integration_signature", lambda *a: ("exact-signature", {"head": "fixed-head"})
    )
    (tmp_path / ".work/features").mkdir(parents=True)
    (tmp_path / ".work/features/F53.md").write_text('---\n{"verify":[],"runtime":[]}\n---\n')
    (tmp_path / "ARCHITECTURE.md").write_text('---\n{"verify":{"typecheck":"types"}}\n---\n')
    packet_path = tmp_path / "packet.json"
    runner.write(
        packet_path,
        {
            "feature": "F53",
            "cases_sha256": cases.CASES_SHA256,
            "gates": {},
            "G8": {"status": "pending", "sidecar": ".harness/scratch/F53/final"},
        },
    )
    directory = tmp_path / ".harness/scratch/F53/final"
    directory.mkdir(parents=True)
    cli = {
        "ok": True,
        "feature": "F53",
        "steps": [{"step": "container checker", "ok": True}, {"step": "types", "ok": True}],
    }
    runtime = {"signature": "exact-signature", "at": 20}
    runner.write(directory / "cli.json", cli)
    runner.write(directory / "runtime.json", runtime)
    (directory / "run.log").write_text("Raw captured invocation\n" + json.dumps(cli))
    runner.write(tmp_path / ".harness/runtime/integrations/F53.json", runtime)
    seal = {
        "signature": "exact-signature",
        "inputs": {"head": "fixed-head"},
        "cli_result": runner.reference(directory / "cli.json"),
        "runtime_receipt": runner.reference(directory / "runtime.json"),
        "log": runner.reference(directory / "run.log"),
        "exit_code": 0,
        "runtime_at": 20,
        "hashes": {},
        "packet": runner.reference(packet_path),
        "started_ms": 10,
        "finished_ms": 30,
        "required_steps": ["container checker", "types"],
    }
    runner.write(directory / "integration-capture.json", seal)
    return packet_path, directory, cli, seal


@pytest.mark.parametrize(
    "mutation",
    [
        "exit",
        "missing-step",
        "self-declared-steps",
        "fake-log",
        "outside-time",
        "live-runtime-drift",
        "config-drift",
    ],
)
def test_final_seal_rejects_forged_or_stale_actual_run(tmp_path, monkeypatch, mutation):
    path, directory, cli, seal = integration_fixture(tmp_path, monkeypatch)
    assert runner.check_receipt(path, root=tmp_path, hashes={})["release_eligible"] is False
    if mutation == "exit":
        seal["exit_code"] = 1
    elif mutation == "missing-step":
        cli["steps"].pop()
        runner.write(directory / "cli.json", cli)
        (directory / "run.log").write_text(json.dumps(cli))
        seal["cli_result"] = runner.reference(directory / "cli.json")
        seal["log"] = runner.reference(directory / "run.log")
    elif mutation == "self-declared-steps":
        seal["required_steps"] = ["container checker"]
    elif mutation == "fake-log":
        (directory / "run.log").write_text("success: true; count=999")
        seal["log"] = runner.reference(directory / "run.log")
    elif mutation == "outside-time":
        seal["finished_ms"] = 19
    elif mutation == "live-runtime-drift":
        runner.write(
            tmp_path / ".harness/runtime/integrations/F53.json",
            {"signature": "another-run", "at": 20},
        )
    else:
        seal["hashes"] = {"runtime_config": "different"}
    runner.write(directory / "integration-capture.json", seal)
    with pytest.raises(runner.ReceiptError):
        runner.check_receipt(path, root=tmp_path, hashes={})


@pytest.mark.parametrize(
    "returned",
    [
        [["other-brand"]],
        [["own-brand"], ["other-brand"]],
        [["own-brand"], ["own-brand"]],
        [["missing"]],
    ],
)
def test_restore_receipt_recomputes_exact_tenant_ids(tmp_path, returned):
    backup, exported = tmp_path / "dump.sql", tmp_path / "sample.bin"
    backup.write_bytes(b"synthetic owned dump")
    exported.write_bytes(b"exported sample")
    rows = {
        "brand": {
            "rows": [
                {"id": "own-brand", "org_id": "owner"},
                {"id": "other-brand", "org_id": "other"},
            ]
        }
    }
    receipt = {
        "status": "pass",
        "target_database": "f53_restore_" + "a" * 12,
        "backup": runner.reference(backup),
        "storage_export": runner.reference(exported),
        "asset": {
            "source_key": "owner/source",
            "restored_key": "owner/restored",
            "restored_db_reference": "owner/restored",
            "source_deleted_before_verify": True,
            "sha256": runner.sha(exported.read_bytes()),
            "bytes": len(exported.read_bytes()),
        },
        "row_inventory": rows,
        "schema_inventory_hash": cases.digest(rows),
        "tenant_queries": {
            "owner": "owner",
            "other": "other",
            "returned_brand_ids": [["own-brand"]],
        },
        "cleanup": {"owned": True},
    }
    runner.verify_restore_receipt(receipt)
    receipt["tenant_queries"]["returned_brand_ids"] = returned
    with pytest.raises(runner.ReceiptError, match="tenant separation"):
        runner.verify_restore_receipt(receipt)
