"""Local recovery tooling contracts; these are not final drill acceptance."""

import asyncio
import json
import os
import subprocess
import sys
import time

import pytest


def test_clock_cli_uses_owned_override_without_touching_default(tmp_path):
    owned = tmp_path / "owned" / "today"
    env = {**os.environ, "DRILL_CLOCK_PATH": str(owned)}
    result = subprocess.run(
        [sys.executable, "-m", "scripts.drill.clock", "set", "2030-01-02"],
        env=env,
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == 0, result.stderr
    assert owned.read_text(encoding="utf-8") == "2030-01-02"
    subprocess.run(
        [sys.executable, "-m", "scripts.drill.clock", "clear"],
        env=env,
        check=True,
        capture_output=True,
        timeout=10,
    )
    assert not owned.exists()


def test_probe_rejects_nonlocal_origin_and_pid_reuse(tmp_path):
    from scripts.drill import recovery_probe as probe

    for origin in (
        "https://example.com",
        "http://localhost.evil:8710",
        "http://127.0.0.1:8710@evil",
        "http://127.0.0.1:8710/x",
    ):
        with pytest.raises(ValueError):
            probe.local_origin(origin)
    receipt = probe.process_identity(os.getpid())
    receipt["start_identity"] = "reused-pid"
    with pytest.raises(RuntimeError, match="identity"):
        probe.interrupt_process(receipt)


def test_recovery_child_refuses_shared_clock_before_installation(tmp_path, monkeypatch):
    from scripts.drill import recovery_probe as probe

    context = tmp_path / "context.json"
    value = {
        "schema": "f52_recovery_0123abcdefab",
        "directory": str(tmp_path),
        "origin": "http://127.0.0.1:8754",
        "auth_origin": "http://127.0.0.1:54321",
        "nonce": "owned-key",
        "processes": [],
    }
    context.write_text(json.dumps(value))
    monkeypatch.setenv("DATABASE_URL", probe.scoped_dsn(value))
    monkeypatch.setenv("BRAND_OS_ENV", "local")
    monkeypatch.setenv("SUPABASE_URL", value["auth_origin"])
    monkeypatch.setenv("IDENTITY_DEV_TOKEN", "")
    monkeypatch.setenv("DRILL_RECOVERY_CONTEXT", str(context))
    monkeypatch.setenv("DRILL_RECOVERY_KEY", "owned-key")
    monkeypatch.setenv("DRILL_CLOCK_PATH", str(tmp_path / "unowned"))
    with pytest.raises(ValueError, match="paths must be owned"):
        probe.child_boot("web")


def test_response_loss_holds_only_after_inner_commit(tmp_path):
    from scripts.drill import recovery_probe as probe

    context = tmp_path / "context.json"
    (tmp_path / "armed.json").write_text(
        json.dumps(
            {
                "id": "fault",
                "role": "web",
                "stage": "response-after-commit",
                "request_path": "/api/strategy",
                "timeout": 0.05,
            }
        )
    )
    state = {"committed": False, "sent": []}

    async def app(scope, receive, send):
        await send({"type": "http.response.start", "status": 200})
        await send({"type": "http.response.body", "body": b"saved"})
        state["committed"] = True

    async def send(message):
        state["sent"].append(message)

    async def run():
        with pytest.raises(TimeoutError, match="deadline"):
            await probe.ResponseBoundary(app, context)(
                {"type": "http", "method": "POST", "path": "/api/strategy"},
                None,
                send,
            )

    asyncio.run(run())
    assert state["committed"]
    assert state["sent"] == []
    rows = probe.events(context)
    assert [row["event"] for row in rows] == ["gate-entered", "gate-timeout"]
    assert rows[0]["inner_app_returned"] is True


def test_actual_owned_child_is_interrupted_and_unrelated_process_survives(tmp_path):
    from scripts.drill import recovery_probe as probe

    code = (
        "import os,time,json; from pathlib import Path; "
        "from scripts.drill.recovery_probe import process_identity; "
        "Path(os.environ['BOOT_PATH']).write_text(json.dumps(process_identity(os.getpid()))); "
        "time.sleep(20)"
    )
    children = []
    try:
        for index in range(2):
            boot = tmp_path / f"boot-{index}.json"
            child = subprocess.Popen(
                [sys.executable, "-c", code],
                env={**os.environ, "BOOT_PATH": str(boot)},
                creationflags=0x08000000 if os.name == "nt" else 0,
            )
            children.append(child)
            deadline = time.monotonic() + 5
            while not boot.exists() and time.monotonic() < deadline:
                time.sleep(0.02)
            assert boot.exists(), "child must report its actual PID"
        actual = json.loads((tmp_path / "boot-0.json").read_text())
        probe.interrupt_process(actual)
        children[0].wait(timeout=5)
        assert children[0].returncode != 0
        assert children[1].poll() is None
    finally:
        for index, child in enumerate(children):
            boot = tmp_path / f"boot-{index}.json"
            if child.poll() is None:
                if boot.exists():
                    probe.interrupt_process(json.loads(boot.read_text()))
                if child.poll() is None:
                    probe.interrupt_process(probe.process_identity(child.pid))
                child.wait(timeout=5)


def test_auth_probe_is_not_logout_simulation(tmp_path):
    from scripts.drill import recovery_probe as probe

    # An unsupported environment must fail before making any network request.
    with pytest.raises(ValueError, match="local"):
        probe.auth_probe(tmp_path / "context.json", environment={"BRAND_OS_ENV": "production"})


@pytest.mark.parametrize(
    "fault,task_type,scope",
    [
        ("strategy-before-persist", "ads_strategy", {"campaign_id": "campaign"}),
        ("strategy-response-lost", "ads_strategy", {"campaign_id": "campaign"}),
        ("worker-prefill", "intake_prefill", {"brand_id": "dynamic"}),
        ("worker-copy", "workbench_copy", {"brief_id": "brief", "part": "copy"}),
    ],
)
def test_fault_provider_records_real_gateway_attempt_and_exact_scope(
    tmp_path,
    monkeypatch,
    fault,
    task_type,
    scope,
):
    from app.brand_intelligence import repository
    from app.core import db
    from app.llm import gateway, providers
    from scripts.drill import recovery_probe as probe

    conn = db.current()
    brand = repository.create_brand(
        conn, name="Recovery fixture", client_name=None, actor="test", org_id=db.DEV_ORG_ID
    )
    if task_type == "intake_prefill":
        scope = {"brand_id": brand["id"]}
    role = "worker" if fault.startswith("worker") else "web"
    context = tmp_path / "context.json"
    context.write_text(
        json.dumps(
            {
                "schema": "f52_recovery_0123abcdefab",
                "directory": str(tmp_path),
                "origin": "http://127.0.0.1:8754",
                "processes": [{"role": role}],
            }
        )
    )
    probe.arm(
        context,
        fault,
        org=db.DEV_ORG_ID,
        brand=brand["id"],
        scope=scope,
        draft_path="/api/fixture",
        timeout=0.03,
    )
    replies = tmp_path / "replies.json"
    replies.write_text(json.dumps({"workbench_copy": {"sets": [], "warnings": []}}))
    monkeypatch.setenv("DRILL_RECOVERY_REPLIES", str(replies))
    # Restore public fixture seams after this test; no product internals are mocked.
    monkeypatch.setattr(gateway, "run_task", gateway.run_task)
    monkeypatch.setattr(providers, "select_provider", providers.select_provider)
    probe.install_provider(context, role)
    arguments = dict(
        brand_id=brand["id"],
        task_type=task_type,
        prompt_template_id="recovery-test",
        prompt_template_version="v1",
        system=None,
        messages=[],
        context=gateway.TaskContext(scope, [], brand["knowledge_version"]),
        options=gateway.TaskOptions(max_retries=0),
    )
    if fault == "strategy-response-lost":
        assert (
            gateway.run_task(conn, providers.FakeProvider(), **arguments)["status"] == "succeeded"
        )
        assert not [row for row in probe.events(context) if row["event"] == "gate-entered"]
    else:
        with pytest.raises(TimeoutError, match="deadline"):
            gateway.run_task(conn, providers.FakeProvider(), **arguments)
        entered = next(row for row in probe.events(context) if row["event"] == "gate-entered")
        row = gateway.get_task(conn, entered["task_id"])
        assert row["status"] == "running"
        assert row["attempt_no"] == entered["attempt_no"] == 1
        assert row["brand_id"] == brand["id"]
        assert row["task_type"] == task_type
        assert row["context_scope_json"] == scope
