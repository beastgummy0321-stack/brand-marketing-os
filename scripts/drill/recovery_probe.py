"""Owned, local-only recovery faults. This module never repairs product rows.

Usage (run through Harness; secrets stay in the inherited environment):
  python -m scripts.drill.recovery_probe init --port 8754
  python -m scripts.drill.recovery_probe start CONTEXT web
  python -m scripts.drill.recovery_probe start CONTEXT worker
  python -m scripts.drill.recovery_probe arm CONTEXT strategy-before-persist \
    --org ORG --brand BRAND --scope '{"campaign_id":"CAMPAIGN"}' \
    --draft-path /api/ads/brands/BRAND/campaigns/CAMPAIGN
  python -m scripts.drill.recovery_probe interrupt CONTEXT
  python -m scripts.drill.recovery_probe start CONTEXT web
  python -m scripts.drill.recovery_probe snapshot CONTEXT --token-env DRILL_ACCESS_TOKEN
  python -m scripts.drill.recovery_probe auth CONTEXT
  python -m scripts.drill.recovery_probe cleanup CONTEXT

Other arm modes: strategy-response-lost, worker-prefill, worker-copy. Use the
normal UI to trigger work/retry; arm never enqueues/replays a write. Prefill
defaults to intake_prefill; --task-type intake_product_prefill selects products.
Copy needs a verifier-supplied JSON reply fixture, --replies FILE at start.
All provider output is scripted/local evidence, never a model-quality pass.
After arm, snapshot before triggering work and again after restart. Response
loss also requires a separate GET snapshot while the response is held. Control
commands are sequential; do not run concurrent commands on one context.
Auth tests real backend exp checking on a locally signed short HS256 access
fixture, and real GoTrue refresh success/rejection after server session
revocation. It does not claim that GoTrue issued a short-lived token, or that
browser route/form retention passed. No frontend signOut event is fabricated.
"""

from __future__ import annotations

import argparse
import asyncio
import contextvars
import getpass
import hashlib
import json
import os
import re
import signal
import socket
import subprocess
import sys
import tempfile
import time
import uuid
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[2]
FAULTS = {
    "strategy-before-persist": ("web", "ads_strategy"),
    "strategy-response-lost": ("web", "ads_strategy"),
    "worker-prefill": ("worker", "intake_prefill"),
    "worker-copy": ("worker", "workbench_copy"),
}
CALL: contextvars.ContextVar[dict | None] = contextvars.ContextVar("recovery_call", default=None)
DB_IDENTITY_FIELDS = ("host", "hostaddr", "port", "dbname", "user")


def local_origin(value: str) -> str:
    parsed = urlsplit(value)
    if (
        parsed.scheme != "http"
        or parsed.hostname not in {"127.0.0.1", "localhost", "::1"}
        or parsed.username
        or parsed.password
        or parsed.path not in {"", "/"}
        or parsed.query
        or parsed.fragment
        or not parsed.port
    ):
        raise ValueError("An explicit loopback HTTP origin is required")
    return value.rstrip("/")


def bounded(value: float) -> float:
    if not 0 < value <= 120:
        raise ValueError("Deadline must be positive and at most 120 seconds")
    return value


def _windows_start_identity(kernel, handle) -> str:
    """Read creation time from the caller's existing process handle."""
    import ctypes
    from ctypes import wintypes

    times = [wintypes.FILETIME() for _ in range(4)]
    if not kernel.GetProcessTimes(handle, *(ctypes.byref(t) for t in times)):
        raise OSError(ctypes.get_last_error())
    return str((times[0].dwHighDateTime << 32) | times[0].dwLowDateTime)


def process_identity(pid: int) -> dict:
    if pid <= 0:
        raise ValueError("A positive process ID is required")
    if os.name == "nt":
        import ctypes
        from ctypes import wintypes

        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.OpenProcess.restype = wintypes.HANDLE
        handle = kernel.OpenProcess(0x1000, False, pid)
        if not handle:
            raise ProcessLookupError(pid)
        try:
            start = _windows_start_identity(kernel, handle)
        finally:
            kernel.CloseHandle(handle)
    elif sys.platform == "linux":
        stat = Path(f"/proc/{pid}/stat").read_text()
        ticks = stat[stat.rfind(")") + 2 :].split()[19]
        boot = Path("/proc/sys/kernel/random/boot_id").read_text().strip()
        start = f"{boot}:{ticks}"
    else:
        raise RuntimeError("Unsupported host: no atomic owned-process interruption")
    return {"pid": pid, "start_identity": start}


def interrupt_process(receipt: dict) -> None:
    """Use the same Windows handle / Linux pidfd for verification and termination."""
    pid = receipt["pid"]
    if os.name == "nt":
        import ctypes
        from ctypes import wintypes

        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.OpenProcess.restype = wintypes.HANDLE
        handle = kernel.OpenProcess(0x1000 | 1 | 0x100000, False, pid)
        if not handle:
            raise ProcessLookupError(pid)
        try:
            identity = _windows_start_identity(kernel, handle)
            if identity != receipt["start_identity"] or pid == os.getpid():
                raise RuntimeError("Process identity mismatch; refusing interruption")
            if not kernel.TerminateProcess(handle, 91):
                raise OSError(ctypes.get_last_error())
            if kernel.WaitForSingleObject(handle, 5000) != 0:
                raise TimeoutError("Owned process did not stop in five seconds")
        finally:
            kernel.CloseHandle(handle)
    elif sys.platform == "linux" and hasattr(os, "pidfd_open"):
        fd = os.pidfd_open(pid)
        try:
            if (
                process_identity(pid) != {k: receipt[k] for k in ("pid", "start_identity")}
                or pid == os.getpid()
            ):
                raise RuntimeError("Process identity mismatch; refusing interruption")
            signal.pidfd_send_signal(fd, signal.SIGKILL)
        finally:
            os.close(fd)
    else:
        raise RuntimeError("Unsupported host: no atomic owned-process interruption")


def digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def build() -> dict:
    head = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True, timeout=5
    ).strip()
    dirty = subprocess.check_output(
        ["git", "status", "--porcelain"], cwd=ROOT, text=True, timeout=5
    )
    files = sorted((ROOT / "frontend/dist").rglob("*"))
    assets = hashlib.sha256()
    for file in files:
        if file.is_file():
            assets.update(file.relative_to(ROOT).as_posix().encode())
            assets.update(file.read_bytes())
    backend = hashlib.sha256()
    for file in sorted([*(ROOT / "app").rglob("*.py"), *(ROOT / "scripts/drill").glob("*.py")]):
        backend.update(file.relative_to(ROOT).as_posix().encode())
        backend.update(file.read_bytes())
    return {
        "head": head,
        "dirty": bool(dirty),
        "frontend_hash": assets.hexdigest() if files else None,
        "backend_hash": backend.hexdigest(),
    }


def write(path: Path, value: dict) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(value, indent=2, ensure_ascii=False, default=str), encoding="utf-8"
    )
    temporary.replace(path)


def load(context: Path) -> dict:
    value = json.loads(context.read_text(encoding="utf-8"))
    if not re.fullmatch(r"f52_recovery_[a-f0-9]{12}", value["schema"]):
        raise ValueError("Invalid owned schema")
    local_origin(value["origin"])
    if value.get("cleaned"):
        raise RuntimeError("Owned context has already been cleaned")
    if Path(value["directory"]).resolve() != context.resolve().parent:
        raise ValueError("Context must remain in its owned evidence directory")
    return value


def require_live_runner(value: dict, role: str) -> dict:
    active = [row for row in value["processes"] if row["role"] == role and not row.get("stopped")]
    if len(active) != 1:
        raise RuntimeError("Exactly one live owned runner is required")
    row = active[0]
    if process_identity(row["pid"])["start_identity"] != row["start_identity"]:
        raise RuntimeError("Owned runner process identity mismatch")
    return row


def event(context: Path, kind: str, **fields) -> dict:
    item = {"event": kind, "time": time.time(), **process_identity(os.getpid()), **fields}
    data = (json.dumps(item, ensure_ascii=False, default=str) + "\n").encode()
    fd = os.open(context.parent / "events.jsonl", os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
    try:
        os.write(fd, data)
    finally:
        os.close(fd)
    return item


def events(context: Path) -> list:
    path = context.parent / "events.jsonl"
    if not path.exists():
        return []
    # An interrupted append may leave only the last line incomplete.
    result = []
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            result.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return result


def scoped_dsn(context: dict) -> str:
    from psycopg.conninfo import conninfo_to_dict, make_conninfo

    params = {
        key: str(value) for key, value in conninfo_to_dict(os.environ["DATABASE_URL"]).items()
    }
    # libpq uses hostaddr for the destination, and unset params may come from
    # PG* variables/service files. Reject service indirection; freeze the
    # effective endpoint and identity into this DSN before any connection.
    if params.get("service") or any(os.environ.get(k) for k in ("PGSERVICE", "PGSERVICEFILE")):
        raise ValueError("PostgreSQL service indirection is unsupported for local recovery")
    if params.get("host") not in {"localhost", "127.0.0.1", "::1"}:
        raise ValueError("Only local PostgreSQL is permitted")
    hostaddr = params.get("hostaddr") or os.environ.get("PGHOSTADDR")
    if not hostaddr:
        hostaddr = "::1" if params["host"] == "::1" else "127.0.0.1"
    if hostaddr not in {"127.0.0.1", "::1"}:
        raise ValueError("Only a single numeric local PostgreSQL address is permitted")
    params["hostaddr"] = hostaddr  # Never rely on localhost DNS or later PGHOSTADDR changes.
    port = params.get("port") or os.environ.get("PGPORT") or "5432"
    if not port.isdecimal() or not 1 <= int(port) <= 65535:
        raise ValueError("An explicit single local PostgreSQL port is required")
    params["port"] = str(int(port))
    params["user"] = params.get("user") or os.environ.get("PGUSER") or getpass.getuser()
    params["dbname"] = params.get("dbname") or os.environ.get("PGDATABASE") or params["user"]
    if "=" in params["dbname"] or params["dbname"].startswith(("postgres://", "postgresql://")):
        raise ValueError("Nested local PostgreSQL connection strings are unsupported")
    identity = {key: params[key] for key in DB_IDENTITY_FIELDS}
    if context.get("db_identity") and context["db_identity"] != identity:
        raise ValueError("Database identity differs from context")
    params["options"] = f"-c search_path={context['schema']}"
    return make_conninfo(**dict(sorted(params.items())))


def admit(environment=None) -> None:
    environment = os.environ if environment is None else environment
    if environment.get("BRAND_OS_ENV") != "local":
        raise ValueError("BRAND_OS_ENV=local is required")
    local_origin(environment["SUPABASE_URL"])
    if environment.get("IDENTITY_DEV_TOKEN"):
        raise ValueError("Recovery fixtures require real JWT authentication, not a dev bypass")


def init(port: int) -> Path:
    admit()
    if not 1024 <= port <= 65535 or port == 8737:
        raise ValueError("Choose a new unprivileged port; 8737 is excluded")
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", port))
    schema = "f52_recovery_" + uuid.uuid4().hex[:12]
    directory = Path(tempfile.mkdtemp(prefix=schema + "-"))
    from psycopg.conninfo import conninfo_to_dict

    value = {
        "schema": schema,
        "directory": str(directory),
        "origin": f"http://127.0.0.1:{port}",
        "nonce": uuid.uuid4().hex,
        "build": build(),
        "processes": [],
        "auth_users": [],
        "auth_origin": local_origin(os.environ["SUPABASE_URL"]),
    }
    dsn = scoped_dsn(value)
    params = conninfo_to_dict(dsn)
    value["db_identity"] = {key: params[key] for key in DB_IDENTITY_FIELDS}
    context = directory / "context.json"
    write(context, value)  # Persist ownership before a possible partial setup failure.
    import psycopg
    from psycopg import sql

    with psycopg.connect(dsn, connect_timeout=5) as conn:
        conn.execute("SET statement_timeout='30s'")
        conn.execute(
            sql.SQL("CREATE SCHEMA {}; SET search_path TO {}").format(
                sql.Identifier(schema), sql.Identifier(schema)
            )
        )
        conn.execute(
            b"\n".join(p.read_bytes() for p in sorted((ROOT / "supabase/migrations").glob("*.sql")))
        )
        conn.execute(
            sql.SQL("GRANT USAGE ON SCHEMA {} TO authenticated").format(sql.Identifier(schema))
        )
    event(context, "initialized", schema=schema, build=value["build"])
    return context


def child_boot(role: str) -> Path | None:
    raw = os.environ.get("DRILL_RECOVERY_CONTEXT")
    if not raw:
        return None
    context = Path(raw).resolve()
    value = load(context)
    admit()
    if value["auth_origin"] != local_origin(os.environ["SUPABASE_URL"]):
        raise ValueError("Child Auth origin differs from context")
    if os.environ.get("DRILL_RECOVERY_KEY") != value["nonce"]:
        raise ValueError("Child ownership key mismatch")
    if os.environ["DATABASE_URL"] != scoped_dsn(value):
        raise ValueError("Child database must use its owned schema exclusively")
    for name, filename in (("DRILL_CLOCK_PATH", "today"), ("DRILL_META_STATE", "meta.json")):
        if Path(os.environ.get(name, "")).resolve() != context.parent / filename:
            raise ValueError("Child fixture paths must be owned")
    if os.environ.get("BRAND_OS_JOB_QUEUE") == "memory":
        raise ValueError("Worker recovery requires the durable PostgreSQL queue")
    # Includes model/vendor requests, redirects and frozen-site fallthroughs.
    real_connect = socket.socket.connect

    def connect(sock, address):
        if isinstance(address, tuple) and address[0] not in {"127.0.0.1", "localhost", "::1"}:
            raise ValueError("Recovery child refuses nonlocal network connections")
        return real_connect(sock, address)

    socket.socket.connect = connect
    receipt = event(context, "boot", role=role, ownership=digest(value["nonce"]), build=build())
    write(context.parent / f"{role}-boot.json", receipt)
    return context


def gate(context: Path, *, role: str, stage: str, **fields) -> None:
    path = context.parent / "armed.json"
    if not path.exists():
        return
    fault = json.loads(path.read_text(encoding="utf-8"))
    if fault["role"] != role or fault["stage"] != stage:
        return
    # Atomic, one-shot claim: parallel calls cannot block a second attempt.
    claim = context.parent / (fault["id"] + ".claimed")
    try:
        fd = os.open(claim, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        os.close(fd)
    except FileExistsError:
        return
    event(context, "gate-entered", fault_id=fault["id"], role=role, stage=stage, **fields)
    deadline = time.monotonic() + bounded(fault["timeout"])
    release = context.parent / (fault["id"] + ".release")
    while time.monotonic() < deadline:
        if release.exists():
            event(context, "gate-released", fault_id=fault["id"])
            return
        time.sleep(0.025)
    event(context, "gate-timeout", fault_id=fault["id"])
    raise TimeoutError("Recovery gate deadline exceeded; no acceptance pass")


def install_provider(context: Path | None, role: str) -> None:
    if context is None:
        return
    from app.llm import gateway, providers

    original = gateway.run_task
    replies_path = os.environ.get("DRILL_RECOVERY_REPLIES")
    replies = json.loads(Path(replies_path).read_text("utf-8")) if replies_path else {}

    def run_task(conn, provider, **kwargs):
        token = CALL.set({"conn": conn, **kwargs})
        try:
            result = original(conn, provider, **kwargs)
            event(
                context,
                "task-returned",
                role=role,
                task_id=result.get("id"),
                attempt_no=result.get("attempt_no"),
                status=result.get("status"),
            )
            return result
        finally:
            CALL.reset(token)

    class LocalProvider:
        name = "scripted"

        def __init__(self, delegate, task_type):
            self.delegate = delegate
            self.task_type = task_type

        def complete(self, **kwargs):
            call = CALL.get()
            path = context.parent / "armed.json"
            fault = json.loads(path.read_text("utf-8")) if path.exists() else None
            if call and fault and fault["role"] == role and fault["task_type"] == self.task_type:
                scope = call["context"].context_scope
                if call["brand_id"] == fault["brand"] and all(
                    scope.get(k) == v for k, v in fault["scope"].items()
                ):
                    rows = gateway.find_tasks_for_scope(
                        call["conn"],
                        org_id=fault["org"],
                        brand_id=fault["brand"],
                        task_type=self.task_type,
                        context_scope=fault["scope"],
                        limit=2,
                    )
                    running = [row for row in rows if row["status"] == "running"]
                    if len(running) != 1:
                        raise RuntimeError(
                            "A unique running attempt is required; create a fresh fixture scope"
                        )
                    row = running[0]
                    event(
                        context,
                        "provider-entered",
                        fault_id=fault["id"],
                        role=role,
                        task_id=row["id"],
                        attempt_no=row["attempt_no"],
                        task_type=self.task_type,
                        scope=scope,
                    )
                    gate(
                        context,
                        role=role,
                        stage="provider-before-output",
                        task_id=row["id"],
                        attempt_no=row["attempt_no"],
                        task_type=self.task_type,
                    )
            return self.delegate.complete(**kwargs)

    def select(provider, task_type=None):
        if not isinstance(task_type, str):
            raise RuntimeError("A named local task type is required")
        reply = replies.get(task_type, providers.SCRIPTED_REPLIES.get(task_type))
        if reply is None:
            raise RuntimeError(f"Unsupported local reply fixture: {task_type}; supply --replies")
        delegate = (
            providers.FakeProvider(
                providers.ProviderResponse(
                    output_text=json.dumps(reply, ensure_ascii=False),
                    structured=None,
                    usage=providers.Usage(input_tokens=0, output_tokens=0),
                    stop_reason="end_turn",
                )
            )
            if task_type in replies
            else providers.ScriptedProvider(reply)
        )
        return LocalProvider(delegate, task_type)

    gateway.run_task = run_task
    providers.select_provider = select


class ResponseBoundary:
    """Hold a selected success response only after the entire inner app returns."""

    def __init__(self, app, context: Path):
        self.app, self.context = app, context

    async def __call__(self, scope, receive, send):
        path = self.context.parent / "armed.json"
        fault = json.loads(path.read_text("utf-8")) if path.exists() else None
        if not (
            fault
            and fault["stage"] == "response-after-commit"
            and scope["type"] == "http"
            and scope["method"] == "POST"
            and scope["path"] == fault["request_path"]
        ):
            return await self.app(scope, receive, send)
        messages, size = [], 0

        async def buffer(message):
            nonlocal size
            size += len(message.get("body", b""))
            if size > 2_000_000:
                raise RuntimeError("Recovery response exceeded the bounded buffer")
            messages.append(message)

        await self.app(scope, receive, buffer)
        status = next((m["status"] for m in messages if m["type"] == "http.response.start"), 0)
        if 200 <= status < 300:
            tasks = [
                e
                for e in events(self.context)
                if e["event"] == "provider-entered" and e.get("fault_id") == fault["id"]
            ]
            await asyncio.to_thread(
                gate,
                self.context,
                role="web",
                stage="response-after-commit",
                response_status=status,
                inner_app_returned=True,
                tasks=[{"task_id": e["task_id"], "attempt_no": e["attempt_no"]} for e in tasks],
            )
        for message in messages:
            await send(message)


def start(context: Path, role: str, replies: str | None = None) -> dict:
    admit()
    value = load(context)
    if value["auth_origin"] != local_origin(os.environ["SUPABASE_URL"]):
        raise ValueError("Auth origin differs from context")
    for row in value["processes"]:
        if row["role"] == role and not row.get("stopped"):
            raise RuntimeError("Interrupt/cleanup the previously owned process before restart")
    if role == "web":
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", urlsplit(value["origin"]).port))
    env = {
        **os.environ,
        "DATABASE_URL": scoped_dsn(value),
        "DRILL_RECOVERY_CONTEXT": str(context),
        "DRILL_RECOVERY_KEY": value["nonce"],
        "DRILL_CLOCK_PATH": str(context.parent / "today"),
        "DRILL_META_STATE": str(context.parent / "meta.json"),
        "BRAND_OS_LLM_PROVIDER": "scripted",
        "BRAND_OS_JOB_QUEUE": "",
        "IDENTITY_DEV_TOKEN": "",
        "PYTHONUTF8": "1",
    }
    if replies:
        env["DRILL_RECOVERY_REPLIES"] = str(Path(replies).resolve())
    boot_path = context.parent / f"{role}-boot.json"
    boot_path.unlink(missing_ok=True)
    command = [sys.executable, "-m", "scripts.drill." + ("serve" if role == "web" else "worker")]
    if role == "web":
        command += ["--port", str(urlsplit(value["origin"]).port)]
    with (context.parent / f"{role}-{len(value['processes'])}.log").open("ab") as log:
        child = subprocess.Popen(
            command,
            env=env,
            cwd=ROOT,
            stdout=log,
            stderr=log,
            stdin=subprocess.DEVNULL,
            creationflags=0x08000000 if os.name == "nt" else 0,
        )
    launcher = process_identity(child.pid)
    deadline = time.monotonic() + 20
    try:
        while not boot_path.exists():
            if child.poll() is not None:
                raise RuntimeError("Owned runner exited before boot; inspect its local log")
            if time.monotonic() >= deadline:
                raise TimeoutError("Owned runner did not boot in twenty seconds")
            time.sleep(0.05)
        receipt = json.loads(boot_path.read_text("utf-8"))
        if receipt["ownership"] != digest(value["nonce"]):
            raise RuntimeError("Child ownership receipt mismatch")
        if process_identity(receipt["pid"])["start_identity"] != receipt["start_identity"]:
            raise RuntimeError("Child process identity changed before boot receipt")
        receipt["launcher"] = launcher
        value["processes"].append(receipt)
        write(context, value)
        return receipt
    except Exception:
        if boot_path.exists():
            boot = json.loads(boot_path.read_text("utf-8"))
            if boot.get("ownership") == digest(value["nonce"]) and boot["pid"] != launcher["pid"]:
                try:
                    interrupt_process(boot)
                except ProcessLookupError:
                    pass
        if child.poll() is None:
            interrupt_process(launcher)
        raise


def stop(context: Path, receipt: dict, reason: str) -> None:
    for identity in (receipt, receipt["launcher"]):
        try:
            interrupt_process(identity)
        except ProcessLookupError:
            pass
    value = load(context)
    for row in value["processes"]:
        if row["pid"] == receipt["pid"] and row["start_identity"] == receipt["start_identity"]:
            row["stopped"] = True
    write(context, value)
    event(
        context,
        "process-stopped",
        target_pid=receipt["pid"],
        target_start=receipt["start_identity"],
        reason=reason,
    )


def arm(
    context: Path,
    fault: str,
    *,
    org: str,
    brand: str,
    scope: dict,
    draft_path: str,
    timeout: float = 60,
    task_type: str | None = None,
) -> dict:
    if fault not in FAULTS or not scope or not org or not brand:
        raise ValueError("An explicit tenant, brand and task scope are required")
    if (
        not draft_path.startswith("/api/")
        or "?" in draft_path
        or "#" in draft_path
        or ".." in draft_path
    ):
        raise ValueError("Use a local product read API path for the saved draft")
    role, default_task = FAULTS[fault]
    if task_type and not (fault == "worker-prefill" and task_type == "intake_product_prefill"):
        raise ValueError("Only the product-prefill task override is supported")
    value = load(context)
    if not any(row["role"] == role and not row.get("stopped") for row in value["processes"]):
        raise RuntimeError("Start an owned runner before arming its fault")
    armed_path = context.parent / "armed.json"
    if armed_path.exists():
        old = json.loads(armed_path.read_text("utf-8"))
        if not (context.parent / (old["id"] + ".claimed")).exists():
            raise RuntimeError("Previous fault is still armed")
    response = fault == "strategy-response-lost"
    if response and not scope.get("campaign_id"):
        raise ValueError("The response boundary requires campaign_id")
    item = {
        "id": uuid.uuid4().hex,
        "fault": fault,
        "role": role,
        "org": org,
        "brand": brand,
        "scope": scope,
        "draft_path": draft_path,
        "timeout": bounded(timeout),
        "task_type": task_type or default_task,
        "stage": "response-after-commit" if response else "provider-before-output",
        "request_path": f"/api/ads/brands/{brand}/campaigns/{scope.get('campaign_id')}/strategy",
    }
    write(armed_path, item)
    event(context, "armed", **item)
    return item


def interrupt(context: Path) -> dict:
    value = load(context)
    fault = json.loads((context.parent / "armed.json").read_text("utf-8"))
    entered = [
        e for e in events(context) if e["event"] == "gate-entered" and e["fault_id"] == fault["id"]
    ]
    if len(entered) != 1 or any(
        e["event"] in {"gate-timeout", "gate-released"} and e.get("fault_id") == fault["id"]
        for e in events(context)
    ):
        raise RuntimeError("Fault must be at its live gate, not pending/released/timed out")
    receipt = next(
        (
            row
            for row in value["processes"]
            if not row.get("stopped")
            and row["role"] == fault["role"]
            and row["pid"] == entered[0]["pid"]
            and row["start_identity"] == entered[0]["start_identity"]
        ),
        None,
    )
    if not receipt:
        raise RuntimeError("Gate process is not an owned runner")
    snapshots = [
        e
        for e in events(context)
        if e["event"] == "draft-snapshot" and e.get("fault_id") == fault["id"]
    ]
    if not any(e["time"] < entered[0]["time"] for e in snapshots):
        raise RuntimeError("Snapshot the last saved draft before triggering the fault")
    if fault["fault"] == "strategy-response-lost" and not any(
        e["time"] > entered[0]["time"] for e in snapshots
    ):
        raise RuntimeError("Confirm persisted strategy with a separate GET before interruption")
    stop(context, receipt, fault["fault"])
    return entered[0]


def snapshot(context: Path, token: str, path: str | None = None) -> dict:
    import httpx

    value = load(context)
    require_live_runner(value, "web")
    fault = json.loads((context.parent / "armed.json").read_text("utf-8"))
    path = path or fault["draft_path"]
    if (
        not isinstance(path, str)
        or not path.startswith("/api/")
        or ".." in path
        or "?" in path
        or "#" in path
    ):
        raise ValueError("Snapshot accepts only an explicit product GET path")
    response = httpx.get(
        value["origin"] + path,
        headers={"Authorization": "Bearer " + token, "X-Org-Id": fault["org"]},
        timeout=10,
        follow_redirects=False,
        trust_env=False,
    )
    response.raise_for_status()
    saved = response.json()
    receipt = event(
        context,
        "draft-snapshot",
        path=path,
        status=response.status_code,
        token_hash=digest(token),
        fault_id=fault["id"],
        saved=saved,
    )
    write(context.parent / f"snapshot-{int(time.time_ns())}.json", receipt)
    return receipt


def auth_probe(context: Path, environment=None) -> dict:
    """Real HTTP faults on a newly created account; session revocation keeps its sub."""
    environment = os.environ if environment is None else environment
    admit(environment)
    if environment.get("IDENTITY_ALLOW_HS256") != "1" or not environment.get("SUPABASE_JWT_SECRET"):
        raise RuntimeError("Unsupported Auth control: local HS256 signing is required")
    anon = environment.get("SUPABASE_ANON_KEY") or environment.get("VITE_SUPABASE_ANON_KEY")
    if not environment.get("SUPABASE_SERVICE_ROLE_KEY") or not anon:
        raise RuntimeError("Unsupported Auth control: local Admin and anon keys are required")
    import httpx
    import jwt

    value = load(context)
    require_live_runner(value, "web")
    if value["auth_origin"] != local_origin(environment["SUPABASE_URL"]):
        raise ValueError("Auth origin differs from context")
    origin = local_origin(environment["SUPABASE_URL"]) + "/auth/v1"
    email = "f52-recovery-" + uuid.uuid4().hex + "@example.test"
    password = uuid.uuid4().hex + "Aa1!"
    service = environment["SUPABASE_SERVICE_ROLE_KEY"]
    admin = {"apikey": service, "Authorization": "Bearer " + service}
    public = {"apikey": anon}
    package = ROOT / "frontend/node_modules/@supabase/auth-js/package.json"
    version = (
        json.loads(package.read_text("utf-8"))["version"] if package.exists() else "unavailable"
    )
    receipt = {
        "auth_js_version": version,
        "auth_source": "GoTrueAdminApi.signOut(jwt, local)",
        "access_fixture": "local-HS256-short-access",
        "refresh_issuer": "GoTrue",
        "browser_retention": "not-verified",
        "email": email,
        "key_present": True,
        "build": build(),
    }
    with httpx.Client(timeout=10, follow_redirects=False, trust_env=False) as client:
        created = client.post(
            origin + "/admin/users",
            headers=admin,
            json={"email": email, "password": password, "email_confirm": True},
        )
        if created.status_code not in {200, 201}:
            raise RuntimeError("Unsupported Auth control: owned user creation failed")
        user = created.json()
        user_id = user.get("id") or user.get("user", {}).get("id")
        uuid.UUID(user_id)
        value["auth_users"].append(user_id)
        write(context, value)  # Cleanup remains possible after any following failure.
        receipt["sub"] = user_id
        event(context, "auth-user-created", sub=user_id, email=email)

        def request(grant, payload):
            response = client.post(
                origin + "/token", params={"grant_type": grant}, headers=public, json=payload
            )
            return response

        login = request("password", {"email": email, "password": password})
        if login.status_code != 200:
            raise RuntimeError("Owned Auth password grant failed")
        session = login.json()
        refreshed = request("refresh_token", {"refresh_token": session["refresh_token"]})
        if refreshed.status_code != 200:
            raise RuntimeError("Successful-refresh control failed")
        session = refreshed.json()
        if session["user"]["id"] != user_id:
            raise RuntimeError("Auth scope changed unexpectedly")
        claims = jwt.decode(session["access_token"], options={"verify_signature": False})
        if claims.get("sub") != user_id or claims.get("aud") != "authenticated":
            raise RuntimeError("GoTrue session claims do not identify the owned account")
        short_claims = {**claims, "iat": int(time.time()), "exp": int(time.time()) + 3}
        short = jwt.encode(short_claims, environment["SUPABASE_JWT_SECRET"], algorithm="HS256")
        headers = {"Authorization": "Bearer " + short}
        accepted = client.get(value["origin"] + "/api/identity/me", headers=headers)
        if accepted.status_code != 200:
            raise RuntimeError("Local short access fixture was not accepted before expiry")
        org = accepted.json()["org"]["id"]
        receipt.update(
            org_id=org,
            access_hash=digest(short),
            refresh_hash=digest(session["refresh_token"]),
            access_before_status=200,
            refresh_control_status=refreshed.status_code,
            expires_at=short_claims["exp"],
        )
        deadline = time.monotonic() + 5
        while time.time() <= short_claims["exp"]:
            if time.monotonic() >= deadline:
                raise TimeoutError("Expiry clock failed to advance within five seconds")
            time.sleep(0.025)
        expired = client.get(value["origin"] + "/api/identity/me", headers=headers)
        if expired.status_code != 401:
            raise RuntimeError("Backend did not reject the genuinely expired access fixture")
        revoked = client.post(
            origin + "/logout",
            params={"scope": "local"},
            headers={**admin, "Authorization": "Bearer " + session["access_token"]},
        )
        if revoked.status_code != 204:
            raise RuntimeError("Unsupported Auth control: server session revocation failed")
        failed = request("refresh_token", {"refresh_token": session["refresh_token"]})
        if failed.status_code not in {400, 401, 403, 422}:
            raise RuntimeError("Revoked-session refresh did not produce a genuine Auth refusal")
        # Re-login uses the same account; the original organisation must remain.
        recovered = request("password", {"email": email, "password": password})
        if recovered.status_code != 200 or recovered.json()["user"]["id"] != user_id:
            raise RuntimeError("Same-account re-login control failed")
        restored = client.get(
            value["origin"] + "/api/identity/me",
            headers={"Authorization": "Bearer " + recovered.json()["access_token"]},
        )
        if restored.status_code != 200 or restored.json()["org"]["id"] != org:
            raise RuntimeError("Original organisation was not retained after re-login")
        receipt.update(
            access_expired_status=expired.status_code,
            revocation_status=revoked.status_code,
            refresh_failed_status=failed.status_code,
            refresh_failure_code=failed.json().get("error_code"),
            recovery_status=restored.status_code,
            original_org_retained=True,
            fault="server-session-revoked-refresh-failed",
        )
    event(context, "auth-probe-complete", **receipt)
    write(context.parent / f"auth-receipt-{time.time_ns()}.json", receipt)
    return receipt


def cleanup(context: Path) -> None:
    admit()
    value = load(context)
    if value["auth_origin"] != local_origin(os.environ["SUPABASE_URL"]):
        raise ValueError("Auth origin differs from context")
    dsn = scoped_dsn(value)  # Refuse mismatched/indirect DB settings before any cleanup action.
    for receipt in list(value["processes"]):
        if not receipt.get("stopped"):
            stop(context, receipt, "cleanup")
    import httpx
    import psycopg
    from psycopg import sql

    headers = {
        "apikey": os.environ["SUPABASE_SERVICE_ROLE_KEY"],
        "Authorization": "Bearer " + os.environ["SUPABASE_SERVICE_ROLE_KEY"],
    }
    with httpx.Client(timeout=10, follow_redirects=False, trust_env=False) as client:
        for user in value["auth_users"]:
            response = client.delete(
                local_origin(os.environ["SUPABASE_URL"]) + "/auth/v1/admin/users/" + user,
                headers=headers,
            )
            if response.status_code not in {200, 204, 404}:
                raise RuntimeError("Owned Auth user cleanup failed")
    schema = value["schema"]
    with psycopg.connect(dsn, connect_timeout=5) as conn:
        conn.execute("SET statement_timeout='10s'")
        conn.execute(
            sql.SQL("DROP SCHEMA IF EXISTS {} CASCADE").format(sql.Identifier(schema + "__queue"))
        )
        conn.execute(sql.SQL("DROP SCHEMA IF EXISTS {} CASCADE").format(sql.Identifier(schema)))
    event(context, "cleanup-complete", schema=schema, auth_users=value["auth_users"])
    value = load(context)
    value["cleaned"] = True
    write(context, value)


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    commands = parser.add_subparsers(dest="command", required=True)
    create = commands.add_parser("init")
    create.add_argument("--port", type=int, required=True)
    for name in ("start", "arm", "interrupt", "snapshot", "auth", "cleanup"):
        command = commands.add_parser(name)
        command.add_argument("context", type=Path)
        if name == "start":
            command.add_argument("role", choices=("web", "worker"))
            command.add_argument("--replies")
        if name == "arm":
            command.add_argument("fault", choices=FAULTS)
            command.add_argument("--org", required=True)
            command.add_argument("--brand", required=True)
            command.add_argument("--scope", type=json.loads, required=True)
            command.add_argument("--draft-path", required=True)
            command.add_argument("--timeout", type=float, default=60)
            command.add_argument("--task-type")
        if name == "snapshot":
            command.add_argument("--token-env", required=True)
            command.add_argument("--path")
    args = parser.parse_args()
    if args.command == "init":
        print(init(args.port))
    elif args.command == "start":
        print(json.dumps(start(args.context.resolve(), args.role, args.replies)))
    elif args.command == "arm":
        print(
            json.dumps(
                arm(
                    args.context.resolve(),
                    args.fault,
                    org=args.org,
                    brand=args.brand,
                    scope=args.scope,
                    draft_path=args.draft_path,
                    timeout=args.timeout,
                    task_type=args.task_type,
                )
            )
        )
    elif args.command == "interrupt":
        print(json.dumps(interrupt(args.context.resolve())))
    elif args.command == "snapshot":
        print(
            json.dumps(
                snapshot(args.context.resolve(), os.environ[args.token_env], args.path), default=str
            )
        )
    elif args.command == "cleanup":
        cleanup(args.context.resolve())
    else:
        print(json.dumps(auth_probe(args.context.resolve())))


if __name__ == "__main__":
    main()
