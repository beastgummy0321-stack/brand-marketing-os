"""Bounded F53 tooling. Run through Harness; receipt checks never execute a probe.

Modes: --prepare, --run, --provider-diagnosis, --provider, --auth, --restore,
--assemble, --capture-integration, --check-receipt [--pre-integration].
Every execution uses a fresh ignored owned directory, freezes inputs before work,
and preserves failed evidence. Synthetic source/contract proof is never market proof.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import time
import uuid
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from threading import Event, Thread
from typing import Any, cast
from urllib.parse import quote

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from scripts.drill import first_release_cases as cases  # noqa: E402

GLOBAL_BOOTSTRAPS = {
    "20260830000002_core_storage_assets_bucket.sql": (
        "ca11be1800f6d3e0f7301be55d1455454bafcad929d46e3f081571dcc06573bd"
    ),
    "20260905000001_core_storage_assets_bucket_size_limit.sql": (
        "1b9839f2e3121c744566142991464d7476947bbf611d9fe84e9f7657e7651e50"
    ),
}
# Migration bytes match approved frozen source 2375e161d06da0455977e87a8010db6dc4f7137f.
MIGRATIONS_SHA256 = "7ca915eb255fecf439829234f1ca19f5f3ae632017aec4c596ede1ed14e0f88d"
PROTECTED_PORTS = {8710, 8720, 8764}
GATES = tuple(f"G{n}" for n in range(1, 8))
PROBE_PATHS = [
    "scripts/drill/first_release_acceptance.py",
    "scripts/drill/first_release_cases.py",
    "scripts/drill/recovery_probe.py",
    "scripts/drill/serve.py",
    "scripts/drill/clock.py",
    "scripts/verify_existing_campaigns_assets.py",
    "scripts/verify_ads_cycle.py",
]
CONFIG_KEYS = (
    "BRAND_OS_ENV",
    "BRAND_OS_LLM_PROVIDER",
    "IDENTITY_ALLOW_HS256",
    "SUPABASE_URL",
    "VITE_SUPABASE_URL",
    "VITE_SUPABASE_ANON_KEY",
    "SUPABASE_ANON_KEY",
    "SUPABASE_SERVICE_ROLE_KEY",
    "SUPABASE_JWT_SECRET",
    "DATABASE_URL",
    "BRAND_OS_JOB_QUEUE",
    "IDENTITY_DEV_TOKEN",
    "BRAND_OS_LLM_MODEL",
    "BRAND_OS_TODAY",
    "ANTHROPIC_API_KEY",
    "PGHOSTADDR",
    "PGPORT",
    "PGUSER",
    "PGDATABASE",
    "PGPASSWORD",
    "PGSERVICE",
    "PGSERVICEFILE",
)


class ReceiptError(ValueError):
    """Fail closed without promoting absence or diagnostics into acceptance."""


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def now():
    return datetime.now(UTC).isoformat()


def read(path):
    return json.loads(Path(path).read_text("utf-8-sig"))


def write(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8"
    )
    temporary.replace(path)


def command(argv, *, cwd=ROOT, timeout: float = 15, env=None, input=None):
    return subprocess.run(
        argv,
        cwd=cwd,
        timeout=timeout,
        env=env,
        input=input,
        capture_output=True,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        check=False,
    )


def required(value: Any, boundary="Owned fixture row") -> Any:
    if value is None:
        raise ReceiptError(boundary + " is absent; acceptance remains unverified")
    return value


def dsn_string(parameters):
    from psycopg.conninfo import make_conninfo

    return make_conninfo(**{key: str(value) for key, value in parameters.items()})


def browser_job(process):
    """Contain only this launcher and its descendants before allowing Chromium to launch."""
    if os.name != "nt":
        return None
    import ctypes
    from ctypes import wintypes

    class BasicLimits(ctypes.Structure):
        _fields_ = [
            ("process_time", ctypes.c_int64),
            ("job_time", ctypes.c_int64),
            ("flags", wintypes.DWORD),
            ("min_ws", ctypes.c_size_t),
            ("max_ws", ctypes.c_size_t),
            ("active", wintypes.DWORD),
            ("affinity", ctypes.c_size_t),
            ("priority", wintypes.DWORD),
            ("scheduling", wintypes.DWORD),
        ]

    class IoCounters(ctypes.Structure):
        _fields_ = [
            (name, ctypes.c_uint64)
            for name in ("read_ops", "write_ops", "other_ops", "read", "write", "other")
        ]

    class Limits(ctypes.Structure):
        _fields_ = [
            ("basic", BasicLimits),
            ("io", IoCounters),
            ("process_memory", ctypes.c_size_t),
            ("job_memory", ctypes.c_size_t),
            ("peak_process", ctypes.c_size_t),
            ("peak_job", ctypes.c_size_t),
        ]

    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.CreateJobObjectW.restype = wintypes.HANDLE
    kernel.SetInformationJobObject.argtypes = [
        wintypes.HANDLE,
        ctypes.c_int,
        ctypes.c_void_p,
        wintypes.DWORD,
    ]
    kernel.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
    kernel.TerminateJobObject.argtypes = [wintypes.HANDLE, wintypes.UINT]
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    handle = kernel.CreateJobObjectW(None, None)
    limits = Limits()
    limits.basic.flags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE.
    if not handle or not kernel.SetInformationJobObject(
        handle, 9, ctypes.byref(limits), ctypes.sizeof(limits)
    ):
        if handle:
            kernel.CloseHandle(handle)
        raise ReceiptError("Owned browser process containment unavailable")
    if not kernel.AssignProcessToJobObject(handle, int(process._handle)):
        kernel.CloseHandle(handle)
        raise ReceiptError("Owned browser launcher could not join its private job")
    return kernel, handle


def bounded_browser(argv, directory, *, timeout, env):
    """A timeout closes the owned job/group, including Chromium; it never kills by name."""
    import signal

    from scripts.drill import recovery_probe

    directory = Path(directory)
    ready = directory / "browser-contained.json"
    if ready.exists():
        raise ReceiptError("Browser containment handshake must be fresh")
    receipt = {
        "cleanup": False,
        "containment": "windows-job" if os.name == "nt" else "process-group",
    }
    process = None
    job = None
    try:
        process = subprocess.Popen(
            argv,
            cwd=ROOT,
            env=env,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            start_new_session=os.name != "nt",
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        receipt.update(recovery_probe.process_identity(process.pid))
        write(directory / "browser-ownership.json", receipt)
        job = browser_job(process)
        write(ready, {"pid": process.pid, "start_identity": receipt["start_identity"]})
        stdout, stderr = process.communicate(timeout=timeout)
        return subprocess.CompletedProcess(argv, process.returncode, stdout, stderr)
    finally:
        if job is not None:
            kernel, handle = job
            terminated = bool(kernel.TerminateJobObject(handle, 1))
            kernel.CloseHandle(handle)
            receipt["cleanup"] = terminated
        elif process is not None and os.name != "nt":
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            receipt["cleanup"] = True
        elif process is not None:
            # Containment failed while Node was still waiting for the handshake.
            process.kill()
            receipt["cleanup"] = True
        if process is not None:
            process.wait(timeout=5)
            receipt["launcher_ended"] = process.poll() is not None
        write(directory / "browser-ownership.json", receipt)


def git(root, *args):
    result = command(["git", *args], cwd=root)
    if result.returncode:
        raise ReceiptError("Git input inventory unavailable")
    return result.stdout


def js_sorted(paths):
    # JavaScript default sort compares UTF-16 code units, not Python code points.
    return sorted(paths, key=lambda p: p.encode("utf-16-be", errors="surrogatepass"))


def fingerprint(root, paths):
    value = hashlib.sha256()
    for name in js_sorted(paths):
        value.update(name.encode())
        path = Path(root) / name
        value.update(path.read_bytes() if path.exists() else b"deleted")
    return value.hexdigest()


def source_fingerprint(root=ROOT):
    paths = git(root, "ls-files", "-z").decode().split("\0")
    return fingerprint(root, [p for p in paths if p and not p.startswith((".work/", ".harness/"))])


def runtime_config_hash(root=ROOT, environment=None):
    """Bind actual mode inputs without reading a DB, loading dotenv, or publishing secrets."""
    from scripts import verify_existing_campaigns_assets as lifecycle

    root = Path(root)
    environment = os.environ if environment is None else environment
    cycle_values = lifecycle.resolved_env(
        argparse.Namespace(env_file=None), root=root, environment=environment
    )

    def hashed(values):
        return {key: sha(str(value).encode()) for key, value in values.items()}

    # Direct provider/Auth/restore use the invoking environment. Cycle uses safe_env's
    # file-first values before its explicit local/scripted/queue/guard overrides.
    cycle_child = {
        **{
            key: environment.get(key, "")
            for key in CONFIG_KEYS
            if not any(
                part in key.upper()
                for part in ("API_KEY", "TOKEN", "SECRET", "DATABASE_URL", "BRAND_OS_LLM_PROVIDER")
            )
        },
        **cycle_values,
        "BRAND_OS_ENV": "local",
        "BRAND_OS_JOB_QUEUE": "memory",
        "BRAND_OS_LLM_PROVIDER": "scripted",
        "IDENTITY_DEV_TOKEN": "",
        "IDENTITY_ALLOW_HS256": "1",
    }
    # Vite's production dotenv files are independent build inputs. Binding raw hashes
    # also covers interpolation and quoted/multiline values without emulating Vite.
    # Auth explicitly overrides URL/anon, whose source values are in direct_runtime.
    frontend_files = {
        name: sha(path.read_bytes()) if path.is_file() else None
        for name in (".env", ".env.local", ".env.production", ".env.production.local")
        for path in (root / "frontend" / name,)
    }
    return cases.digest(
        {
            "direct_runtime": hashed({key: environment.get(key, "") for key in CONFIG_KEYS}),
            "cycle_resolved": hashed(cycle_values),
            "cycle_child": hashed(cycle_child),
            "frontend_files": frontend_files,
            "frontend_shell": hashed(
                {key: value for key, value in environment.items() if key.startswith("VITE_")}
            ),
        }
    )


def relevant_hashes(root=ROOT, environment=None):
    paths = [p for p in git(root, "ls-files", "-z").decode().split("\0") if p]
    environment = os.environ if environment is None else environment
    product = [
        p
        for p in paths
        if p.startswith(
            (
                "app/ads/",
                "app/workbench/",
                "app/core/",
                "app/identity/",
                "app/llm/",
                "app/storage/",
                "app/brand_intelligence/",
                "supabase/migrations/",
            )
        )
        and not p.endswith((".test.ts", ".test.tsx"))
    ]
    ui = [
        p
        for p in paths
        if p.startswith(("frontend/src/", "frontend/package", "frontend/vite.config."))
        and not p.endswith((".test.ts", ".test.tsx"))
    ]
    return {
        "product": fingerprint(root, product),
        "ui": fingerprint(root, ui),
        "probe": fingerprint(root, PROBE_PATHS),
        "runtime_config": runtime_config_hash(root, environment),
    }


def integration_signature(root=ROOT):
    value = hashlib.sha256()
    value.update(source_fingerprint(root).encode())
    value.update(git(root, "rev-parse", "HEAD").strip())
    feature = Path(root) / ".work/features/F53.md"
    value.update(feature.read_bytes())
    inputs = {
        "head": git(root, "rev-parse", "HEAD").decode().strip(),
        "source": source_fingerprint(root),
        "feature_sha256": sha(feature.read_bytes()),
        "issues": [],
    }
    for state in ("ready", "doing", "blocked", "done"):
        for path in sorted((Path(root) / ".work" / state).glob("F53-*.md")):
            identity = path.stem
            value.update((state + identity).encode())
            value.update(path.read_bytes())
            inputs["issues"].append(
                {"state": state, "id": identity, "sha256": sha(path.read_bytes())}
            )
    return value.hexdigest(), inputs


def migration_audit(root=ROOT):
    """Skip only two complete known global blocks; no arbitrary SQL deletion."""
    included, skipped = [], []
    for path in sorted((Path(root) / "supabase/migrations").glob("*.sql")):
        raw = path.read_bytes()
        if path.name in GLOBAL_BOOTSTRAPS:
            if sha(raw) != GLOBAL_BOOTSTRAPS[path.name]:
                raise ReceiptError("Global bootstrap bytes changed: " + path.name)
            skipped.append({"path": path.name, "sha256": sha(raw)})
            continue
        # Ignore comments, but retain function bodies: those can perform global writes later.
        sql = re.sub(r"--[^\n]*|/\*.*?\*/", "", raw.decode("utf-8"), flags=re.S)
        if re.search(
            r"\b(?:INSERT\s+INTO|UPDATE|DELETE\s+FROM|ALTER\s+TABLE|DROP\s+TABLE|"
            r'CREATE\s+TABLE|TRUNCATE(?:\s+TABLE)?)\s+"?(?:public|auth|storage)"?\s*\.',
            sql,
            re.I,
        ):
            raise ReceiptError("Unapproved global migration write: " + path.name)
        included.append({"path": path.name, "sha256": sha(raw)})
    migrations = sorted((Path(root) / "supabase/migrations").glob("*.sql"))
    raw_set = hashlib.sha256()
    for path in migrations:
        raw_set.update(path.name.encode())
        raw_set.update(path.read_bytes())
    if len(migrations) != 119 or raw_set.hexdigest() != MIGRATIONS_SHA256:
        raise ReceiptError("Approved complete migration bytes changed; admission refused")
    return {
        "included": included,
        "skipped_global_bootstraps": skipped,
        "approved_migrations_sha256": raw_set.hexdigest(),
    }


def reference(path):
    path = Path(path).resolve()
    raw = path.read_bytes()
    return {"path": str(path), "bytes": len(raw), "sha256": sha(raw)}


def dereference(ref):
    path = Path(ref["path"]).resolve()
    raw = path.read_bytes()
    if len(raw) != ref["bytes"] or sha(raw) != ref["sha256"]:
        raise ReceiptError("Evidence bytes changed: " + str(path))
    return raw


def fresh_directory(path):
    path = Path(path).resolve()
    allowed = (ROOT / ".scratch/F53").resolve()
    if not path.is_relative_to(allowed) or path == allowed or path.exists():
        raise ReceiptError("A fresh owned .scratch/F53 child is required")
    path.mkdir(parents=True)
    return path


def prepare(path):
    directory = fresh_directory(path)
    value = cases.frozen_cases()
    context = {
        "schema_version": 1,
        "feature": "F53",
        "run_id": uuid.uuid4().hex,
        "created_at": now(),
        "directory": str(directory),
        "nonce": uuid.uuid4().hex,
        "cases": reference(cases.CASES),
        "expectations_hash": cases.digest(value),
        "hashes": relevant_hashes(),
        "migration_audit": migration_audit(),
        "provenance": "synthetic-fixtures-not-market-results",
        "processes": [],
        "resources": [],
        "gates": {},
        "human_acceptance": "pending",
    }
    write(directory / "context.json", context)
    return context


def context_at(path):
    path = Path(path).resolve()
    value = read(path)
    directory = Path(value["directory"]).resolve()
    if path != directory / "context.json" or not directory.is_relative_to(ROOT / ".scratch/F53"):
        raise ReceiptError("Context is outside owned acceptance directory")
    if value.get("feature") != "F53" or not re.fullmatch(r"[a-f0-9]{32}", value.get("nonce", "")):
        raise ReceiptError("Ownership receipt unavailable")
    dereference(value["cases"])
    if value["hashes"] != relevant_hashes():
        raise ReceiptError("Relevant product/probe/runtime configuration changed")
    return value


def once(directory, name):
    # Atomic reservation remains even on failure; checking never launches another attempt.
    with (Path(directory) / (name + "-attempt.json")).open("x", encoding="utf-8") as stream:
        json.dump({"started_at": now(), "name": name}, stream)


def save_gate(context_path, gate, evidence, *, status, limitations, cleanup):
    value = context_at(context_path)
    record = {
        "status": status,
        "evidence": [reference(p) for p in evidence],
        "finished_at": now(),
        "hashes": value["hashes"],
        "limitations": limitations,
        "cleanup": cleanup,
        "run_id": value["run_id"],
    }
    value["gates"][gate] = record
    write(context_path, value)
    return record


def validate_gate(gate, record, hashes):
    if record.get("status") != "pass":
        raise ReceiptError(gate + " remains " + record.get("status", "missing"))
    if record.get("hashes") != hashes or not record.get("evidence"):
        raise ReceiptError(gate + " lacks matching source evidence")
    for ref in record["evidence"]:
        dereference(ref)
    cleanup = record.get("cleanup", {})
    if not cleanup or any(value is not True for value in cleanup.values()):
        raise ReceiptError(gate + " owned cleanup is not proved")
    verify_raw_gate(gate, record)


def evidence_json(record, suffix):
    ref = next((r for r in record["evidence"] if Path(r["path"]).name == suffix), None)
    if not ref:
        raise ReceiptError("Raw boundary receipt absent: " + suffix)
    return json.loads(dereference(ref))


def verify_auth_receipt(receipt):
    browser = json.loads(dereference(receipt["browser"]))
    if (
        receipt.get("status") != "pass"
        or receipt.get("auth_image") != AUTH_IMAGE
        or receipt.get("auth_version") != AUTH_VERSION
        or receipt.get("namespace") != "auth"
        or receipt.get("search_path") != "auth,pg_catalog"
        or browser.get("auth_js_version") != "2.112.4"
    ):
        raise ReceiptError("G7 does not bind the actual supported issuer/SDK fixture")
    expired = next(
        (
            s
            for s in browser.get("issuances", [])
            if s.get("access_sha256") == browser.get("same_token_expired_sha256")
        ),
        None,
    )
    if not expired or not (
        expired["iat"] < expired["exp"] and expired["exp"] * 1000 < browser["expired_at"]
    ):
        raise ReceiptError("G7 lacks genuine same-token issued expiry chronology")
    if not expired.get("session_id") or not expired.get("sub"):
        raise ReceiptError("G7 genuine session mapping absent")
    database = receipt.get("database_identity", {})
    container = receipt.get("container_identity", {})
    browser_owner = json.loads(dereference(receipt["browser_ownership"]))
    if (
        database.get("database") != receipt.get("database")
        or database.get("schema") != "auth"
        or database.get("search_path", "").replace(" ", "") != "auth,pg_catalog"
        or not database.get("role")
        or container.get("image") != AUTH_IMAGE
        or not all(container.get(k) for k in ("id", "created", "started", "owner"))
        or not browser_owner.get("pid")
        or not browser_owner.get("start_identity")
        or browser_owner.get("cleanup") is not True
        or browser_owner.get("launcher_ended") is not True
    ):
        raise ReceiptError("G7 actual fixture/process identity or containment cleanup absent")
    if (
        browser.get("before_status") != 200
        or browser.get("access_expired_status") != 401
        or not browser["before_at"] < expired["exp"] * 1000
        or browser.get("revocation_status") != 204
        or browser.get("refresh_refused_status") not in {400, 401, 403, 422}
        or browser.get("refresh_error_code")
        not in {
            "refresh_token_not_found",
            "refresh_token_already_used",
            "session_not_found",
            "session_expired",
        }
    ):
        raise ReceiptError("G7 server expiry/refresh refusal controls are not proved")
    saved, restored = browser.get("saved_work", {}), browser.get("recovered_work", {})
    if (
        not saved.get("id")
        or not saved.get("org_id")
        or saved.get("sha256") != restored.get("sha256")
        or saved.get("id") != restored.get("id")
        or saved.get("org_id") != restored.get("org_id")
        or browser.get("before_access_sha256") != browser.get("same_token_expired_sha256")
        or not isinstance(browser.get("product_requests"), list)
        or not isinstance(browser.get("requests_after_relogin"), list)
        or browser["requests_after_relogin"]
        != [r for r in browser["product_requests"] if r["at"] >= browser["login_at"]]
        or browser["requests_after_relogin"]
        or not browser["expired_at"] <= browser["login_at"] <= browser["recovered_at"]
    ):
        raise ReceiptError("G7 ordinary login did not recover identical supported saved work")
    if receipt.get("refresh_success_control", {}).get("status") != 200:
        raise ReceiptError("G7 successful-refresh control absent")
    if not all(receipt.get("cleanup", {}).values()) or receipt.get("cleanup_errors"):
        raise ReceiptError("G7 Auth ownership cleanup incomplete")


def verify_restore_receipt(receipt):
    if receipt.get("status") != "pass" or not re.fullmatch(
        r"f53_restore_[a-f0-9]{12}", receipt.get("target_database", "")
    ):
        raise ReceiptError("G7 restored target is not a disposable independent database")
    dereference(receipt["backup"])
    data = dereference(receipt["storage_export"])
    asset = receipt.get("asset", {})
    if (
        asset.get("source_key") == asset.get("restored_key")
        or asset.get("source_deleted_before_verify") is not True
        or asset.get("restored_db_reference") != asset.get("restored_key")
        or sha(data) != asset.get("sha256")
        or len(data) != asset.get("bytes")
    ):
        raise ReceiptError("G7 Storage bytes were not restored through an independent DB reference")
    rows = receipt.get("row_inventory", {})
    if cases.digest(rows) != receipt.get("schema_inventory_hash"):
        raise ReceiptError("G7 restored schema/row inventory differs")
    queries = receipt.get("tenant_queries", {})
    brands = rows.get("brand", {}).get("rows", [])
    expected_ids = {b["id"] for b in brands if b["org_id"] == queries.get("owner")}
    other_ids = {b["id"] for b in brands if b["org_id"] == queries.get("other")}
    returned = queries.get("returned_brand_ids", [])
    returned_ids = {r[0] for r in returned if isinstance(r, (list, tuple)) and len(r) == 1}
    if (
        {b["org_id"] for b in brands} != {queries.get("owner"), queries.get("other")}
        or queries.get("owner") == queries.get("other")
        or not expected_ids
        or len(returned) != len(expected_ids)
        or returned_ids != expected_ids
        or returned_ids & other_ids
    ):
        raise ReceiptError("G7 restored tenant separation absent")
    if not all(receipt.get("cleanup", {}).values()) or receipt.get("cleanup_errors"):
        raise ReceiptError("G7 restore cleanup incomplete")


def verify_raw_gate(gate, record):
    """Re-evaluate concrete gate observations rather than trusting status/count summaries."""
    if gate in {"G1", "G2", "G3", "G4"}:
        cycle = evidence_json(record, "fixed-cycle.json")
        if (
            cycle.get("provenance") != "synthetic-only"
            or cycle.get("expectations_sha256") != cases.CASES_SHA256
            or cycle.get("run_id") != record.get("run_id")
        ):
            raise ReceiptError("Fixed cycle provenance/input binding differs")
        periods = cycle.get("periods", [])
        verify_http_cycle(cycle)
        if len(periods) != 3:
            raise ReceiptError("Three complete frozen periods are required")
        for actual, expected in zip(periods, cases.frozen_cases()["periods"], strict=True):
            if actual.get("period") != expected:
                raise ReceiptError("Frozen fixed-period semantic inputs changed")
            decision = actual["proposal"]["budget_basis_json"]["strategy"]["decision"]
            check_adopted_bindings(decision, actual["accepted"])
            raw = actual.get("observations", {}).get("raw_observations", [])
            if (
                not raw
                or sum(r.get("result_count") for r in raw) != expected["events"]
                or sum(float(r["spend"]) for r in raw)
                != expected["events"] * expected["cost_per_result"]
                or any(r.get("source") != "graph" or r.get("currency") != "TWD" for r in raw)
                or actual["closed"]["verdict_json"].get("actual") != expected["cost_per_result"]
            ):
                raise ReceiptError(
                    "Raw retained synthetic observations differ from the frozen period"
                )
        if not any(
            s["offer_key"] == "none"
            for s in periods[0]["adoption_receipt"]["slots"]
            if "offer_key" in s
        ):
            first = periods[0]["proposal"]["budget_basis_json"]["strategy"]["decision"]
            if not any(s["offer_key"] == "none" for s in first["slots"]):
                raise ReceiptError("G1 explicit no-offer test absent")
        raw_cases = evidence_json(record, "qualification-cases.json")
        if raw_cases != cases.qualification_cases():
            raise ReceiptError("Frozen qualification counterexample outputs differ")
        source = evidence_json(record, "source-boundaries.json")
        if (
            source.get("status") != "pass"
            or not source.get("raw_ledger")
            or "FAILED" in source.get("raw_log", "")
        ):
            raise ReceiptError("Actual targeted source writer checks failed or lack raw ledger")
        if not {"ads", "coordinate", "visual"} <= {r["source_track"] for r in source["raw_ledger"]}:
            raise ReceiptError("G4 all-track source/read boundary proof absent")
    elif gate == "G5":
        manifest = evidence_json(record, "ui-manifest.json")
        screens = [json.loads(dereference(ref)) for ref in manifest.get("screens", [])]
        if {s.get("screen") for s in screens} != {"strategy", "library", "verify"}:
            raise ReceiptError("G5 three source matched screens absent")
        for screen in screens:
            if screen.get("ui_hash") != record["hashes"]["ui"]:
                raise ReceiptError("G5 UI source/build fingerprint differs")
            if {p["width"] for p in screen.get("pairs", [])} != {1024, 1920}:
                raise ReceiptError("G5 exact width pairs absent")
            for pair in screen["pairs"]:
                for key in ("reference", "built"):
                    dereference(pair[key])
            if not {
                "loading",
                "cold",
                "error",
                "retry",
                "stale",
                "retained-input",
                "keyboard",
                "source-focus",
            } <= set(screen.get("states", [])):
                raise ReceiptError("G5 required UI state checks absent")
            for ref in screen.get("machine_evidence", []):
                dereference(ref)
            if not screen.get("machine_evidence"):
                raise ReceiptError("G5 machine state/keyboard proof absent")
    elif gate == "G6":
        model = evidence_json(record, "provider-receipt.json")
        provider_owner = json.loads(dereference(model["schema"]))
        if (
            not re.fullmatch(r"f13_runtime_[a-f0-9]{12}", provider_owner.get("schema", ""))
            or provider_owner.get("cleanup") is not True
        ):
            raise ReceiptError("G6 isolated gateway ledger cleanup absent")
        if model.get("options") != {"max_retries": 0, "timeout_s": 60, "tools": None}:
            raise ReceiptError("G6 provider policy changed")
        if model.get("provider_attempts") != 1 or model["task"].get("attempt_no") != 1:
            raise ReceiptError("G6 bounded one-attempt proof absent")
        if json.loads(dereference(model["input"])) != provider_input():
            raise ReceiptError("G6 frozen provider semantic input changed")
        if validate_provider_output(model["task"])["status"] != "contract-pass":
            raise ReceiptError("G6 actual gateway output failed structural/binding checks")
        semantic = evidence_json(record, "provider-semantic-review.json")
        if (
            semantic.get("status") != "accepted"
            or not semantic.get("reviewer")
            or semantic.get("receipt_sha256") != cases.digest(model)
            or set(semantic.get("accepted_items", []))
            != set(provider_input()["semantic_checklist"])
        ):
            raise ReceiptError("G6 independent semantic acceptance absent")
    elif gate == "G7":
        verify_auth_receipt(evidence_json(record, "auth-receipt.json"))
        verify_restore_receipt(evidence_json(record, "restore-receipt.json"))


RETAINED_FIELDS = (
    "name",
    "goal_text",
    "objective",
    "start_date",
    "end_date",
    "target_cost",
    "budget_planned",
    "budget_scenario",
    "budget_basis_json",
    "context_json",
    "constraints_json",
)


def retained_input(campaign):
    return {field: campaign.get(field) for field in RETAINED_FIELDS}


def verify_retained_case(row):
    before = row["retained_before"]
    after = row["retained_after"]
    if set(before) != set(RETAINED_FIELDS) or set(after) != set(RETAINED_FIELDS):
        raise ReceiptError("Complete original campaign input proof absent")
    expected = dict(before)
    mutation = row["mutation"]
    if row["kind"] == "target":
        expected["target_cost"] = mutation["after"]
    served = retained_input(row["served_after_rejection"])
    if after != expected or any(
        served[field] != expected[field]
        for field in RETAINED_FIELDS
        if field != "budget_basis_json"
    ):
        raise ReceiptError("Stale rejection changed an input beyond its intentional mutation")
    if mutation["before"] == mutation["after"] or not mutation["proposal_refs"]:
        raise ReceiptError("Stale fixture is not bound to a displayed changed source")
    if row["kind"] == "same-ID-meaning" and not any(
        ref["kind"] == "learning" and ref["id"] == mutation["id"]
        for ref in mutation["proposal_refs"]
    ):
        raise ReceiptError("Changed learning meaning is unrelated to the displayed proposal")


def verify_http_cycle(cycle):
    """Evaluate actual served reader/adoption data; pure-helper reports cannot substitute."""
    periods = cycle.get("periods", [])
    if len(periods) != 3:
        raise ReceiptError("Actual reader periods absent")
    controls = []
    for period in periods:
        items = {item["id"]: item for item in period["reader"]["evidence_context"]["items"]}
        identity = period["observations"]["controlled_learning"]["id"]
        if identity not in items:
            raise ReceiptError("Actual controlled source is absent from the scoped HTTP reader")
        item = items[identity]
        controls.append(item)
        injected = period["derivatives"]["injected"]
        if (
            len(injected) != 4
            or {r.get("fixture_kind") for r in injected}
            != {"coordinate", "visual", "replay", "product-B"}
            or len({r["id"] for r in injected}) != 4
        ):
            raise ReceiptError("Actual four derivative/product-B injections are incomplete")
        original_raw = period["derivatives"]["original_evidence"]
        if period["derivatives"]["original"]["id"] != identity:
            raise ReceiptError("Injected derivatives do not bind the controlled raw source")
        for row in injected:
            raw = row["fixture_evidence"]
            if row["fixture_kind"] != "product-B":
                if raw["source_ref"]["trial_id"] != original_raw["source_ref"]["trial_id"]:
                    raise ReceiptError("Derivative changed the independent trial identity")
                expected_period = dict(original_raw["period"])
                if row["fixture_kind"] == "replay":
                    expected_period["start"] = expected_period["end"]
                    if raw["source_version"] == original_raw["source_version"]:
                        raise ReceiptError("Replay did not exercise a changed source version")
                if raw["period"] != expected_period:
                    raise ReceiptError("Derivative/replay window proof differs from its source")
                if row["fixture_kind"] in {"coordinate", "visual"} and (
                    raw["source_kind"] != row["fixture_kind"]
                ):
                    raise ReceiptError("Actual derivative source kind is not represented")
            derived = items.get(row["id"])
            if not derived:
                raise ReceiptError("Actual derivative/product-B reader proof absent")
            if row["product_id"] != item["scope"]["product_id"]:
                if derived["use_state"] != "excluded" or derived["allowed_uses"]:
                    raise ReceiptError("Product B promoted the selected product")
            elif derived["independent_count"] != item["independent_count"]:
                raise ReceiptError("A derivative/replay added an independent trial")
    thin, supported, contrary = controls
    if thin["sample"]["result_events"] != 2 or "market_support" in thin["allowed_uses"]:
        raise ReceiptError("Actual thin reader promoted support")
    if (
        supported["sample"]["result_events"] != 10
        or supported["independent_count"] != 1
        or supported["same_direction_count"] != 1
        or "market_support" not in supported["allowed_uses"]
    ):
        raise ReceiptError("Actual sufficient reader is not one compatible independent trial")
    latest_items = {item["id"]: item for item in periods[2]["reader"]["evidence_context"]["items"]}
    prior = latest_items[supported["id"]]
    if (
        contrary["sample"]["result_events"] != 10
        or contrary["independent_count"] != 2
        or contrary["contrary_count"] != 1
        or "market_support" in contrary["allowed_uses"]
        or prior["use_state"] != "history"
        or "market_support" in prior["allowed_uses"]
    ):
        raise ReceiptError("Actual contrary reader did not retire same-direction market support")
    stale_cases = cycle.get("stale_cases", [])
    if {row["kind"] for row in stale_cases} != {
        "offer",
        "price",
        "material",
        "target",
        "same-ID-meaning",
    }:
        raise ReceiptError("Actual HTTP stale condition/meaning cases are incomplete")
    for row in stale_cases:
        original = row["proposal"]["budget_basis_json"]["strategy"]["decision"]
        fresh = row["refreshed"]["budget_basis_json"]["strategy"]["decision"]
        verify_retained_case(row)
        if (
            row["rejection"]["status"] != 409
            or row["rejection"].get("body", {}).get("error", {}).get("code") != "strategy_changed"
            or row["served_after_rejection"]["groups"]
            or original["revision"] == fresh["revision"]
        ):
            raise ReceiptError(
                "Stale confirmation lost input, executed, or did not explicitly refresh"
            )
        check_adopted_bindings(fresh, row["adopted"])
    contexts = cycle.get("consumer_contexts", [])
    if not contexts:
        raise ReceiptError("Actual qualified consumer input proof absent")
    for index, period in enumerate(periods):
        matching = [r for r in contexts if r["campaign"] == period["proposal"]["id"]]
        if len(matching) != 1:
            raise ReceiptError("Each actual proposal needs its own delivered prompt context")
        row = matching[0]
        if set(row["sections"]) != {"learnings", "ranked"} or any(
            not text or text not in row["prompt"] for text in row["sections"].values()
        ):
            raise ReceiptError("Actual rendered qualification sections are missing from prompt")
        allowed = {(ref["kind"], ref["id"]) for ref in row["binding"]["evidence_refs"]}
        delivered = {item["id"]: item for item in row["items"]}
        refs = []
        for slot in period["proposal"]["budget_basis_json"]["strategy"]["decision"]["slots"]:
            if not slot["evidence_refs"] or any(
                (r["kind"], r["id"]) not in allowed for r in slot["evidence_refs"]
            ):
                raise ReceiptError("Proposal cites a source outside its actual consumer input")
            refs.extend(ref for ref in slot["evidence_refs"] if ref["kind"] == "learning")
        if index and not refs:
            raise ReceiptError("Historical qualification never reached the proposal citations")
        for ref in refs:
            evidence = delivered.get(ref["id"])
            if (
                not evidence
                or evidence["use_state"] != "usable"
                or not any(evidence["support_label"] in text for text in row["sections"].values())
            ):
                raise ReceiptError("Learning citation is not actually delivered qualified input")
            if index == 1 and "market_support" in evidence["allowed_uses"]:
                raise ReceiptError("Thin prompt input was promoted beyond a test/control")
        if index == 2 and not any(
            "market_support" in delivered[ref["id"]]["allowed_uses"] for ref in refs
        ):
            raise ReceiptError("Sufficient qualified input did not reach the next proposal")
    # The post-contrary concrete test must address A2 rather than silently repeat A1.
    refreshed = stale_cases[0]["proposal"]["budget_basis_json"]["strategy"]["decision"]
    previous = periods[2]["proposal"]["budget_basis_json"]["strategy"]["decision"]
    old_targets = {s["customer_group_id"] for s in previous["slots"] if not s["carry_from_ad_id"]}
    new_targets = {s["customer_group_id"] for s in refreshed["slots"] if not s["carry_from_ad_id"]}
    if not new_targets or new_targets == old_targets:
        raise ReceiptError("Post-contrary proposal lacks a changed executable buyer hypothesis")


def required_integration_steps(root=ROOT):
    """Independently read the same manifest fields used by installed queue.mjs integrate."""
    feature = (Path(root) / ".work/features/F53.md").read_text("utf-8")
    feature_config = json.loads(feature.split("---", 2)[1])
    manifest = json.loads((Path(root) / "ARCHITECTURE.md").read_text("utf-8").split("---", 2)[1])
    verify = manifest.get("verify", {})
    required = ["container checker"]
    executed = {manifest.get("checker", {}).get("command")}
    for key in ("typecheck", "build", "test"):
        item = (
            (verify.get("typecheck_before_test") or verify.get(key))
            if key == "typecheck"
            else verify.get(key)
        )
        if item and item not in executed:
            required.append(item)
            executed.add(item)
    for item in feature_config.get("verify", []):
        if item not in executed:
            required.append(item)
            executed.add(item)
    smoke = (
        verify.get("smoke_after_build")
        if verify.get("build") and verify.get("smoke_after_build")
        else verify.get("smoke")
    )
    if smoke and smoke not in executed:
        required.append(smoke)
        executed.add(smoke)
    for item in feature_config.get("runtime", []):
        if item not in executed:
            required.append(item)
            executed.add(item)
    return list(dict.fromkeys(required))


def check_receipt(path, *, pre_integration=False, root=ROOT, hashes=None):
    packet = read(path)
    current = relevant_hashes(root) if hashes is None else hashes
    if packet.get("feature") != "F53" or packet.get("cases_sha256") != cases.CASES_SHA256:
        raise ReceiptError("Packet does not bind frozen F53 inputs")
    for gate in GATES:
        validate_gate(gate, packet.get("gates", {}).get(gate, {}), current)
    pending = packet.get("G8", {})
    if pending.get("status") != "pending" or pending.get("sidecar") != ".harness/scratch/F53/final":
        raise ReceiptError("Tracked G8 must be only its finite pending sidecar pointer")
    if pre_integration:
        return {
            "machine": "G1-G7 verified",
            "G8": "pending actual integration",
            "human": packet.get("human_acceptance", "pending"),
            "release_eligible": False,
        }
    sidecar = Path(root) / pending["sidecar"]
    seal = read(sidecar / "integration-capture.json")
    signature, inputs = integration_signature(root)
    if seal.get("signature") != signature or seal.get("inputs") != inputs:
        raise ReceiptError("Exact Harness HEAD/source/queue byte signature changed")
    cli = json.loads(dereference(seal["cli_result"]))
    runtime = json.loads(dereference(seal["runtime_receipt"]))
    log = dereference(seal["log"])
    if seal.get("exit_code") != 0 or cli.get("ok") is not True or cli.get("feature") != "F53":
        raise ReceiptError("Actual integration exit/result is not successful")
    if runtime != {"signature": signature, "at": seal.get("runtime_at")}:
        raise ReceiptError("Actual runtime integration stamp differs")
    if read(Path(root) / ".harness/runtime/integrations/F53.json") != runtime:
        raise ReceiptError("Current actual integration stamp differs from archived run")
    if cases.canonical(cli) not in log.decode("utf-8", errors="strict"):
        # CLI output may have indentation, but must contain the same complete JSON result.
        decoder = json.JSONDecoder()
        decoded = []
        log_text = log.decode("utf-8", errors="strict")
        for match in re.finditer(r"\{", log_text):
            try:
                item, _ = decoder.raw_decode(log_text[match.start() :])
                decoded.append(item)
            except ValueError:
                continue
        if cli not in decoded:
            raise ReceiptError("Actual CLI result is absent from its integration log")
    if seal.get("hashes") != current or seal.get("packet") != reference(path):
        raise ReceiptError("Integration capture source/config/packet changed")
    if not (seal["started_ms"] <= runtime["at"] <= seal["finished_ms"]):
        raise ReceiptError("Runtime stamp is outside the captured integration run")
    if not log or not cli.get("steps"):
        raise ReceiptError("Actual integration log/steps absent")
    expected = required_integration_steps(root)
    if expected != seal.get("required_steps"):
        raise ReceiptError("Seal supplied requirements differ from the installed manifest")
    actual = {step["step"] for step in cli["steps"] if step.get("ok") is True}
    if not expected or set(expected) - actual or any(s.get("ok") is not True for s in cli["steps"]):
        raise ReceiptError("Required actual integration steps missing or failed")
    if list(dict.fromkeys(step["step"] for step in cli["steps"])) != expected:
        raise ReceiptError("Actual integration steps differ from installed execution order")
    return {
        "machine": "G1-G8 verified",
        "signature": signature,
        "pre_close_inputs": inputs,
        "human": packet.get("human_acceptance", "pending"),
        "release_eligible": False,
        "F48_F52": "open; original F52 drill remains paused",
    }


def diagnose_provider(context_path):
    """Only non-generating CLI controls; retain hashes instead of credential-bearing output."""
    value = context_at(context_path)
    directory = Path(value["directory"])
    executable = shutil.which("codex")
    facts = {
        "at": now(),
        "executable_available": executable is not None,
        "executable_sha256": sha(Path(executable).read_bytes()) if executable else None,
        "model": "gpt-5.6-luna",
        "cause": "unknown",
        "controls": [],
        "historical_boundary": "Prior sample was direct provider, not gateway",
    }
    previous = ROOT / ".harness/scratch/launch-direction-probe-20261007/planning-results.json"
    if previous.exists():
        facts["prior_timeout"] = reference(previous)
    if executable:
        for name, args in (("version", ["--version"]), ("login", ["login", "status"])):
            try:
                result = command([executable, *args], timeout=8)
                raw = result.stdout + result.stderr
                facts["controls"].append(
                    {
                        "name": name,
                        "exit_code": result.returncode,
                        "output_hash": sha(raw),
                        "output_bytes": len(raw),
                        "version": re.findall(rb"codex-cli\s+[0-9][\w.+-]*", raw)[0].decode()
                        if name == "version" and re.search(rb"codex-cli\s+[0-9][\w.+-]*", raw)
                        else None,
                    }
                )
            except (OSError, subprocess.TimeoutExpired) as exc:
                facts["controls"].append({"name": name, "failure": type(exc).__name__})
    write(directory / "provider-diagnosis.json", facts)
    return facts


def owned_connection(value):
    """Use only the pinned local acceptance schema; reject libpq indirection before connect."""
    from psycopg.conninfo import conninfo_to_dict

    from scripts.drill import recovery_probe

    if not re.fullmatch(r"f13_runtime_[a-f0-9]{12}", value.get("schema", "")):
        raise ReceiptError("Owned acceptance schema is required")
    dsn = recovery_probe.scoped_dsn(value)
    params = conninfo_to_dict(dsn)
    if value.get("db_identity") != {k: params[k] for k in recovery_probe.DB_IDENTITY_FIELDS}:
        raise ReceiptError("Pinned local database identity is required")
    return dsn


@contextmanager
def provider_schema(directory):
    """Provider runs separately from the cycle: its ledger has its own bounded owned schema."""
    import psycopg
    from psycopg import sql
    from psycopg.conninfo import conninfo_to_dict

    from scripts import verify_existing_campaigns_assets as lifecycle
    from scripts.drill import recovery_probe

    recovery_probe.admit()
    migration_audit()
    schema = "f13_runtime_" + uuid.uuid4().hex[:12]
    org, brand = "org_" + schema, "brd_" + schema
    parameters = conninfo_to_dict(recovery_probe.scoped_dsn({"schema": schema}))
    parameters.pop("options", None)
    admin = dsn_string(parameters)
    receipt = {
        "schema": schema,
        "org_id": org,
        "brand_id": brand,
        "created_at": now(),
        "cleanup": False,
    }
    write(Path(directory) / "provider-schema.json", receipt)
    deadline = time.monotonic() + 45

    def remaining():
        left = deadline - time.monotonic()
        if left <= 0:
            raise TimeoutError("Provider schema bootstrap exceeded its separate bound")
        return left

    try:
        _, scoped, _ = lifecycle.create_schema(
            {"DATABASE_URL": admin}, schema, org, [brand], remaining, f53_schema_only=True
        )
        yield scoped, brand
    finally:
        with psycopg.connect(admin, autocommit=True, connect_timeout=5) as conn:
            conn.execute("SET statement_timeout='15s'")
            for owned in (schema + "__queue", schema):
                conn.execute(
                    sql.SQL("DROP SCHEMA IF EXISTS {} CASCADE").format(sql.Identifier(owned))
                )
        receipt["cleanup"] = True
        receipt["finished_at"] = now()
        write(Path(directory) / "provider-schema.json", receipt)


def provider_input():
    return {
        "schema_version": 1,
        "provenance": "synthetic-frozen-context",
        "facts": ["One box contains individually wrapped snacks."],
        "products": [{"id": "product_A", "name": "One box"}],
        "customers": [
            {"id": "A1", "who": "Workday snack buyers"},
            {"id": "A2", "who": "Weekend snack buyers"},
        ],
        "offers": [{"key": "shipping", "label": "Free shipping"}],
        "explicit_none_offer": True,
        "carried": [],
        "observation": {
            "result_events": 2,
            "cost_per_result": 200,
            "support": "thin, not market proof",
        },
        "cap": 300,
        "currency": "TWD",
        "allowed_roles": ["new", "explore"],
        "evidence_refs": [{"kind": "brand_fact", "id": "synthetic-fact-snack"}],
        "output_shape": {
            "allocation": [{"role": "new", "pct": 100, "rationale": "Limited test."}],
            "slots": [
                {
                    "id": "test",
                    "role": "new",
                    "customer_group_id": "A1",
                    "offer_key": "none",
                    "carry_from_ad_id": None,
                    "test_intent": "Test the supplied buyer hypothesis.",
                    "evidence_refs": [{"kind": "brand_fact", "id": "synthetic-fact-snack"}],
                    "rationale": "Supplied fact only; effectiveness remains unknown.",
                }
            ],
            "why": ["Explain the buyer hypothesis using supplied facts."],
            "unknowns": ["Market effectiveness remains unknown."],
            "alternatives": [],
        },
        "semantic_checklist": [
            "only supplied facts",
            "uncertainty retained",
            "explicit none offer",
            "bindable executable slots",
            "no causal/profit/optimal claim",
        ],
    }


def validate_provider_output(task):
    from app.ads import strategy
    from app.llm import gateway

    reply = gateway.parse_json_reply(task.get("rendered_output"))
    payload = strategy._validate_reply(reply, frozenset({"new", "explore"}))
    if task.get("status") != "succeeded" or not payload:
        return {"status": "unverified", "reason": "gateway or contract output not accepted"}
    slots = payload.get("slots") or []
    bindable = (
        isinstance(slots, list)
        and bool(slots)
        and all(
            isinstance(s, dict)
            and s.get("customer_group_id") in {"A1", "A2"}
            and s.get("offer_key") in {"none", "shipping"}
            and s.get("carry_from_ad_id") is None
            and s.get("test_intent")
            and s.get("role") in {"new", "explore"}
            and s.get("id")
            and isinstance(s.get("evidence_refs"), list)
            and s["evidence_refs"]
            and all(ref in provider_input()["evidence_refs"] for ref in s["evidence_refs"])
            for s in slots
        )
    )
    if not bindable or not any(s["offer_key"] == "none" for s in slots):
        return {"status": "unverified", "reason": "bindable explicit none-offer test absent"}
    # Semantics are independently inspectable. Structural success never pre-fills human judgment.
    return {
        "status": "contract-pass",
        "semantic_acceptance": "pending-independent-review",
        "payload": payload,
    }


def run_provider(context_path):
    value = context_at(context_path)
    directory = Path(value["directory"])
    diagnosis = diagnose_provider(context_path)
    if os.environ.get("BRAND_OS_LLM_PROVIDER") != "codex_cli":
        raise ReceiptError("Existing codex_cli gateway configuration is required")
    if not diagnosis["executable_available"]:
        raise ReceiptError("UNVERIFIED: current codex executable unavailable")
    frozen = provider_input()
    write(directory / "provider-input.json", frozen)
    once(directory, "provider")
    from app.core import db
    from app.llm import gateway, providers

    started = now()
    import psycopg
    from psycopg.rows import dict_row

    with provider_schema(directory) as (dsn, brand):
        # The default connect generic is TupleRow; app Conn's runtime contract is dict rows.
        with psycopg.connect(dsn, row_factory=cast(Any, dict_row)) as raw_conn:
            conn = db.Conn(raw_conn)
            task = gateway.run_task(
                conn,
                providers.CodexCliProvider(),
                brand_id=brand,
                task_type="ads_strategy",
                prompt_template_id="f53-first-release",
                prompt_template_version="1",
                system=(
                    "Return one JSON strategy with allocation, slots, why, unknowns, alternatives. "
                    "Use only the frozen facts. Keep thin-sample uncertainty. Include an explicit "
                    "none-offer test. Use customer IDs, supplied roles and bound evidence refs. "
                    "Do not invent results, causality or profit. Do not calculate money in prose."
                ),
                messages=[{"role": "user", "content": cases.canonical(frozen)}],
                context=gateway.TaskContext(
                    context_scope={"f53_run": value["run_id"]},
                    knowledge_item_ids=[],
                    brand_version=1,
                ),
                options=gateway.TaskOptions(max_retries=0, timeout_s=60, tools=None),
            )
    receipt = {
        "started_at": started,
        "finished_at": now(),
        "task": task,
        "input": reference(directory / "provider-input.json"),
        "options": {"max_retries": 0, "timeout_s": 60, "tools": None},
        "diagnosis": reference(directory / "provider-diagnosis.json"),
        "validation": validate_provider_output(task),
        "provider_attempts": 1,
    }
    receipt["schema"] = reference(directory / "provider-schema.json")
    write(directory / "provider-receipt.json", receipt)
    return save_gate(
        context_path,
        "G6",
        [directory / "provider-receipt.json"],
        status="unverified",
        limitations=["Independent semantic review is required; no retry"],
        cleanup={"gateway_returned": True},
    )


def ui_evidence(context_path, manifests):
    value = context_at(context_path)
    directory = Path(value["directory"])
    evidence = []
    for screen in ("strategy", "library", "verify"):
        manifest = read(manifests[screen])
        if manifest.get("screen") != screen or manifest.get("ui_hash") != value["hashes"]["ui"]:
            raise ReceiptError("UI evidence is not source matched: " + screen)
        for width in (1024, 1920):
            pair = next((p for p in manifest.get("pairs", []) if p.get("width") == width), None)
            if not pair:
                raise ReceiptError("Missing reference/build width pair")
            for key in ("reference", "built"):
                dereference(pair[key])
        for ref in manifest.get("machine_evidence", []):
            dereference(ref)
        if not manifest.get("machine_evidence") or not manifest.get("states"):
            raise ReceiptError("UI keyboard/state machine proof absent")
        if manifest.get("human_acceptance") not in {None, "pending"}:
            raise ReceiptError("Tool must not prefill human UI acceptance")
        evidence.append(reference(manifests[screen]))
    write(directory / "ui-manifest.json", {"screens": evidence, "human_acceptance": "pending"})
    return save_gate(
        context_path,
        "G5",
        [directory / "ui-manifest.json"],
        status="pass",
        limitations=["Actual human five-question acceptance remains pending"],
        cleanup={"read_only_assembly": True},
    )


def assemble(context_path, output):
    value = context_at(context_path)
    packet = {
        "schema_version": 1,
        "feature": "F53",
        "cases_sha256": cases.CASES_SHA256,
        "hashes": value["hashes"],
        "gates": value["gates"],
        "human_acceptance": "pending",
        "release_eligible": False,
        "G8": {"status": "pending", "sidecar": ".harness/scratch/F53/final"},
        "disposition": {
            "fixed": [],
            "remaining": ["F48-F52 remain open"],
            "unverified": [g for g in GATES if value["gates"].get(g, {}).get("status") != "pass"],
        },
        "provenance": "Synthetic API/market-shaped source fixtures; not live-market proof",
    }
    path = Path(output).resolve()
    allowed = (ROOT / "docs/drills/drill-12/first-release/acceptance-result.json").resolve()
    if path != allowed and not path.is_relative_to(Path(value["directory"])):
        raise ReceiptError("Packet output outside scoped acceptance artifacts")
    write(path, packet)
    return packet


def capture_integration(packet_path, cli_path, log_path, *, exit_code, started_ms, finished_ms):
    """Capture completed actual lead run, never predict or execute an integration."""
    signature, inputs = integration_signature()
    runtime_path = ROOT / ".harness/runtime/integrations/F53.json"
    runtime = read(runtime_path)
    cli = read(cli_path)
    if exit_code != 0 or not cli.get("ok") or runtime.get("signature") != signature:
        raise ReceiptError("Only the actual successful matching integration can be captured")
    if not started_ms <= runtime["at"] <= finished_ms:
        raise ReceiptError("Capture times do not contain this actual integration")
    required = required_integration_steps()
    directory = ROOT / ".harness/scratch/F53/final"
    directory.mkdir(parents=True, exist_ok=True)
    # Preserve all original bytes; only ignored sidecar files are written.
    copies = {}
    for name, path in (
        ("cli_result", cli_path),
        ("log", log_path),
        ("runtime_receipt", runtime_path),
    ):
        target = directory / (name + Path(path).suffix)
        if target.exists():
            raise ReceiptError("Existing final evidence must not be overwritten")
        shutil.copyfile(path, target)
        copies[name] = reference(target)
    receipt = {
        "signature": signature,
        "inputs": inputs,
        "packet": reference(packet_path),
        "runtime_at": runtime["at"],
        "exit_code": exit_code,
        "started_ms": started_ms,
        "finished_ms": finished_ms,
        "hashes": relevant_hashes(),
        "required_steps": required,
        **copies,
    }
    write(directory / "integration-capture.json", receipt)
    return receipt


def source_boundary_checks(conn, org):
    """Existing targeted writer falsifiers on the already owned schema; no pytest init/reset."""
    import io
    import unittest
    from unittest.mock import patch

    from app.core import db
    from app.tests.test_ads_coordinate_learning import CompletedPeriodCoordinateTest
    from app.tests.test_ads_learning_flow import AdsLearningFlowTest
    from app.tests.test_ads_settle import SettleWriteTest
    from app.tests.test_ads_visual_learning import CompletedPeriodVisualTest

    selected = [
        AdsLearningFlowTest("test_automatic_recheck_does_not_duplicate"),
        AdsLearningFlowTest("test_repeated_pause_receipts_never_promote_market_confidence"),
        AdsLearningFlowTest("test_ab_learning_carries_the_campaigns_sell_way"),
        CompletedPeriodCoordinateTest(
            "test_new_coordinate_ledger_excludes_incomplete_day_and_retry_keeps_source_cycle"
        ),
        CompletedPeriodVisualTest(
            "test_adopted_fingerprint_comparison_uses_completed_period_not_old_or_intraday_rows"
        ),
        SettleWriteTest(
            "test_identical_text_and_overlapping_periods_do_not_promote_unknown_conditions"
        ),
    ]
    stream = io.StringIO()
    with patch.object(db, "DEV_ORG_ID", org):
        result = unittest.TextTestRunner(stream=stream, verbosity=2).run(
            unittest.TestSuite(selected)
        )
    raw = conn.execute("SELECT * FROM learning_ledger ORDER BY id").fetchall()
    receipt = {
        "tests": [test.id() for test in selected],
        "raw_log": stream.getvalue(),
        "raw_ledger": [dict(row) for row in raw],
        "status": "pass" if result.wasSuccessful() else "fail",
        "provenance": "synthetic existing writer fixtures, not real observations",
    }
    if not result.wasSuccessful():
        raise AssertionError(receipt)
    return receipt


def fixture_setup(conn, context):
    """Only called inside the owned synthetic child, never a product route/module."""
    from app.brand_intelligence import repository as brands
    from app.core import db

    brand = context["brand_id"]
    product = brands.create_product(conn, brand, name="Synthetic snack", actor="f53")
    way = brands.save_sell_way(
        conn,
        brand,
        product_id=product["id"],
        name="Product A",
        economics={
            "selling_price": 1000,
            "list_price": 1200,
            "unit_variable_cost": 300,
            "shipping_cost": 100,
        },
        free_shipping=True,
        actor="f53",
    )
    groups = brands.save_customer_groups(
        conn,
        brand,
        product["id"],
        [{"who": "A1", "pain_keys": ["effort"]}, {"who": "A2", "pain_keys": ["cost"]}],
        actor="f53",
    )
    other_product = brands.create_product(conn, brand, name="Product B", actor="f53")
    other_way = brands.save_sell_way(
        conn,
        brand,
        product_id=other_product["id"],
        name="B box",
        economics={"selling_price": 1000, "unit_variable_cost": 300},
        actor="f53",
    )
    for dimension, key in (
        ("audience", "cold"),
        ("pain", "effort"),
        ("pain", "cost"),
        ("angle", "convenience"),
        ("hook", "everyday"),
        ("proof", "known_fact"),
        ("format", "image"),
        ("offer", "free_shipping"),
    ):
        conn.execute(
            "INSERT INTO brand_coordinate(id,org_id,brand_id,dimension,key,label) "
            "VALUES(%s,%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING",
            (db.new_id("crd"), context["org_id"], brand, dimension, key, key),
        )
    conn.commit()
    fact = db.new_id("bf")
    conn.execute(
        "INSERT INTO brand_fact(id,org_id,brand_id,fact_type,label,value,status)"
        " VALUES(%s,%s,%s,'custom','Synthetic product fact',"
        "'One box contains individually wrapped snacks.','confirmed')",
        (fact, context["org_id"], brand),
    )
    conn.commit()
    return {
        "product_id": way["id"],
        "knowledge_product_id": product["id"],
        "groups": groups,
        "other_product_id": other_way["id"],
        "brand_fact_id": fact,
    }


def fixture_provider(context):
    """Canned branch choices are frozen before invocation; not model-quality evidence."""
    from app.llm import providers

    class FrozenProvider:
        name = "codex_cli"

        def complete(self, *, messages, **kwargs):
            prompt = messages[-1]["content"]
            with (Path(context["evidence_dir"]) / "consumer-prompts.jsonl").open(
                "a", encoding="utf-8"
            ) as stream:
                stream.write(cases.canonical({"at": now(), "prompt": prompt}) + "\n")
            binding = providers.ScriptedProvider._json_section(prompt, "【可綁定安排】")
            if binding:
                delivery = required(context.get("f53_prompt_delivery"), "Actual prompt delivery")
                if delivery["campaign"] != context["f53_planning_campaign"] or any(
                    fragment not in prompt for fragment in delivery["sections"].values()
                ):
                    raise ReceiptError("Prepared learning sections did not reach this provider")
                chosen = int(
                    any(
                        item["contrary_count"] > 0
                        for item in delivery["items"]
                        if item["use_state"] == "usable"
                    )
                )
                with (Path(context["evidence_dir"]) / "consumer-contexts.jsonl").open(
                    "a", encoding="utf-8"
                ) as stream:
                    stream.write(
                        cases.canonical(
                            {
                                **delivery,
                                "prompt": prompt,
                                "binding": binding,
                                "chosen": chosen,
                            }
                        )
                        + "\n"
                    )
                customers = binding["customers"]
                delivered_ids = {
                    item["id"] for item in delivery["items"] if item["use_state"] == "usable"
                }
                learning_refs = [
                    ref
                    for ref in binding["evidence_refs"]
                    if ref["kind"] == "learning" and ref["id"] in delivered_ids
                ]
                selected_refs = (
                    learning_refs[:1]
                    or [ref for ref in binding["evidence_refs"] if ref["kind"] != "learning"][:1]
                )
                slot = {
                    "id": "synthetic-test",
                    "role": "new",
                    "customer_group_id": customers[chosen]["id"],
                    "offer_key": "none",
                    "carry_from_ad_id": None,
                    "test_intent": "Test another buyer after a comparable contrary observation"
                    if chosen
                    else "Retain a limited buyer hypothesis pending independent support",
                    "evidence_refs": selected_refs,
                    "rationale": "A limited observation supports this test, not causality.",
                }
                carried = binding.get("carried") or binding.get("carry_candidates") or []
                slots = [slot]
                if carried:
                    first = carried[0]
                    slot["role"] = "explore" if first["role"] == "new" else "new"
                    slots.insert(
                        0,
                        {
                            **slot,
                            "id": "synthetic-control",
                            "role": first["role"],
                            "customer_group_id": first.get("customer_group_id"),
                            "offer_key": first["coordinates"]["offer"],
                            "carry_from_ad_id": first["id"],
                            "test_intent": None,
                        },
                    )
                roles = list(dict.fromkeys(s["role"] for s in slots))
                reply = {
                    "allocation": [
                        {
                            "role": r,
                            "label": r,
                            "pct": 100 / len(roles),
                            "rationale": "Keep a limited control and test uncertainty.",
                        }
                        for r in roles
                    ],
                    "slots": slots,
                    "why": ["Do not promote thin samples or claim causality."],
                    "unknowns": ["True market effectiveness remains unknown."],
                    "alternatives": [],
                }
            else:
                accepted = providers.ScriptedProvider._json_section(prompt, "【已確認的新安排】")
                if not accepted:
                    raise ReceiptError("Frozen delivery provider did not receive accepted slots")
                reply = {
                    "groups": [
                        {
                            "role": s["role"],
                            "name": "Synthetic test group",
                            "ads": [
                                {
                                    "name": "Synthetic test",
                                    "slot_id": s["id"],
                                    "customer_group": next(
                                        (
                                            i + 1
                                            for i, row in enumerate(context["f53_setup"]["groups"])
                                            if row["id"] == s["customer_group_id"]
                                        ),
                                        None,
                                    ),
                                    "coordinates": {
                                        "audience": "cold",
                                        "pain": "cost"
                                        if s["customer_group_id"]
                                        == context["f53_setup"]["groups"][1]["id"]
                                        else "effort",
                                        "angle": "convenience",
                                        "hook": "everyday",
                                        "proof": "known_fact",
                                        "offer": s["offer_key"],
                                        "format": "image",
                                    },
                                    "scene": "A buyer sees a snack proposition while shopping.",
                                }
                            ],
                        }
                        for s in accepted
                    ]
                    if accepted
                    else []
                }
            return providers.ProviderResponse(
                output_text=json.dumps(reply),
                structured=None,
                usage=providers.Usage(input_tokens=0, output_tokens=0),
                stop_reason="end_turn",
            )

    return FrozenProvider()


def first_release_child(context_path, port):
    """Existing F13 source/network guard with an owned clock and nonce-only fixture endpoints."""
    import uvicorn
    from fastapi import Request

    from app.tests.fixtures.ads_external import runtime as assembly
    from scripts.drill import clock

    context = read(context_path)
    os.environ["DRILL_CLOCK_PATH"] = context["f53_today"]
    clock.TODAY_PATH = Path(context["f53_today"])
    clock.install()
    thread, stopped, stats = cast(
        tuple[Thread, Event, dict[str, Any]], assembly.install_assembly(context)
    )
    import app.main
    from app.ads import planner_context
    from app.core import db
    from app.llm import providers

    clock.patch_modules()
    original_section = planner_context.section_text

    def delivered_section(ctx, which):
        rendered = original_section(ctx, which)
        if which == "learnings":
            context["f53_prompt_delivery"] = {
                "campaign": context["f53_planning_campaign"],
                "sections": {},
                "items": [],
            }
        if which in {"learnings", "ranked"}:
            delivery = context["f53_prompt_delivery"]
            delivery["sections"][which] = rendered
            rows = (
                ctx["learnings"]["ads"]
                if which == "learnings"
                else [
                    row
                    for campaign in ctx["learnings"]["ranked"].get("campaigns", [])
                    for row in campaign["rows"]
                ]
            )
            by_id = {item["id"]: item for item in delivery["items"]}
            for row in rows:
                evidence = row.get("evidence")
                if evidence:
                    by_id[evidence["id"]] = evidence
            delivery["items"] = list(by_id.values())
        return rendered

    planner_context.section_text = delivered_section
    globals()["Request"] = Request
    original_select = providers.select_provider
    providers.select_provider = lambda provider, task_type=None: (
        fixture_provider(context)
        if (task_type in {"ads_strategy", "ads_delivery_plan"})
        else original_select(provider, task_type)
    )
    app = app.main.app
    server = uvicorn.Server(
        uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning", access_log=False)
    )

    def guard(request):
        if request.headers.get("X-F53-Owner") != context["f53_nonce"]:
            raise ReceiptError("Synthetic fixture ownership mismatch")

    @app.get("/__f13/state")
    def state():
        return {**read(context["state_file"]), **stats}

    @app.post("/__f13/state")
    async def update(request: Request):
        guard(request)
        body = await request.json()
        value = read(context["state_file"])
        if set(body) - {"creative_revision", "fail_next", "paused"}:
            raise ReceiptError("Unsupported source fixture mutation")
        value.update(body)
        write(context["state_file"], value)
        return value

    @app.post("/__f13/stop")
    def stop():
        server.should_exit = True
        return {"stopping": True}

    @app.post("/__f53/setup")
    def setup(request: Request):
        guard(request)
        context["f53_setup"] = fixture_setup(db.current(), context)
        return context["f53_setup"]

    @app.post("/__f53/observe/{campaign_id}/{period_id}")
    def observe(request: Request, campaign_id: str, period_id: str):
        guard(request)
        return fixture_observe(db.current(), context, campaign_id, period_id)

    @app.get("/__f53/source-checks")
    def sources(request: Request):
        guard(request)
        return source_boundary_checks(db.current(), context["org_id"])

    @app.post("/__f53/derivatives/{learning_id}")
    def derivatives(request: Request, learning_id: str):
        guard(request)
        return fixture_derivatives(db.current(), context, learning_id)

    @app.post("/__f53/planning-campaign/{campaign_id}")
    def planning_campaign(request: Request, campaign_id: str):
        from app.ads import repository

        guard(request)
        repository.get_campaign(db.current(), context["org_id"], context["brand_id"], campaign_id)
        context["f53_planning_campaign"] = campaign_id
        return {"campaign": campaign_id}

    @app.post("/__f53/mutate/{campaign_id}/{kind}")
    def mutate(request: Request, campaign_id: str, kind: str):
        guard(request)
        return fixture_mutation(db.current(), context, campaign_id, kind)

    @app.post("/__f53/restore-mutation")
    def restore_mutation(request: Request):
        guard(request)
        return fixture_mutation(db.current(), context, None, "restore")

    @app.get("/__f53/retained/{campaign_id}")
    def retained(request: Request, campaign_id: str):
        from app.ads import repository

        guard(request)
        campaign = repository.get_campaign(
            db.current(), context["org_id"], context["brand_id"], campaign_id
        )
        campaign = required(campaign)
        return retained_input(campaign)

    thread.start()
    try:
        server.run()
    finally:
        stopped.set()
        thread.join(timeout=15)


def fixture_observe(conn, context, campaign_id, period_id):
    """Injected SourcePage observations use the normal retained performance writer."""
    from datetime import date

    from app import storage
    from app.ads import (
        ads_learnings,
        external_repository,
        handoff_assignment,
        live_creative,
        repository,
        user_assets_repository,
    )
    from app.core import db
    from app.tests.fixtures.ads_external import outcome_seed

    period = next(p for p in cases.frozen_cases()["periods"] if p["id"] == period_id)
    org, brand = context["org_id"], context["brand_id"]
    campaign = required(repository.campaign_detail(conn, org, brand, campaign_id))
    ads = [ad for group in campaign["groups"] for ad in group["ads"]]
    raw = []
    for ad in ads:
        if not ad.get("material_placement_id"):
            content = Path(context["media_paths"]["image"]).read_bytes()
            asset = db.new_id("aua")
            key = f"{org}/{asset}/original.png"
            storage.put(
                org_id=org,
                key=key,
                filename="original.png",
                content=content,
                content_type="image/png",
            )
            conn.execute(
                "INSERT INTO ads_user_asset(id,org_id,brand_id,sha256,storage_key,filename,"
                "mime_type,byte_size,status) VALUES(%s,%s,%s,%s,%s,'original.png',"
                "'image/png',%s,'ready')",
                (asset, org, brand, sha(content), key, len(content)),
            )
            placement = user_assets_repository.attach(
                conn,
                org,
                brand,
                campaign_id,
                asset,
                {
                    "headline": "Original synthetic headline",
                    "body": "Original synthetic body",
                    "description": "Known original fixture",
                },
                "f53",
            )
            conn.execute(
                "UPDATE ads_asset_placement SET confirmed_at=now(),confirmed_by='f53' WHERE id=%s",
                (placement["id"],),
            )
            conn.commit()
            handoff_assignment.assign(conn, org, brand, campaign_id, ad["id"], placement["id"], 1)
    campaign = required(repository.campaign_detail(conn, org, brand, campaign_id))
    live_creative.record_launch(
        conn, org, brand, campaign_id, "synthetic-launch-" + period_id, campaign
    )
    bound = outcome_seed.bind_platform(conn, org, brand, campaign)
    for index, ad in enumerate(ads):
        count = period["events"] if index == 0 else 0
        observation = {
            "entity_id": bound[ad["id"]],
            "day": date.fromisoformat(period["end"]),
            "metric_scope": "ad",
            "attribution_key": "fixed-known-fixture",
            "currency": "TWD",
            "spend": period["events"] * period["cost_per_result"] if index == 0 else 0,
            "impressions": 1000,
            "clicks": 30,
            "purchases": count,
            "revenue": None,
            "source": "graph",
        }
        from app.ads.adapters.external import SourcePage

        page = SourcePage([observation])  # Entire injected-reader receipt is synthetic.
        for item in page.items:
            raw.append(
                external_repository.upsert_observation(
                    conn,
                    org,
                    brand,
                    campaign_id,
                    item,
                    result_kind="purchase",
                    result_count=count,
                    result_action="omni_purchase",
                    result_attribution="fixed-known-fixture",
                )
            )
    outcome_seed.set_coverage(
        conn,
        org,
        brand,
        campaign_id,
        date.fromisoformat(period["start"]),
        date.fromisoformat(period["end"]),
    )
    conn.commit()
    fresh = required(repository.campaign_detail(conn, org, brand, campaign_id))
    evidence = [
        ads_learnings.source_evidence(
            conn,
            org,
            brand,
            fresh,
            kind="campaign",
            window={"start": period["start"], "end": period["end"]},
            ad=ad,
            claim_key="convenience",
            direction="support" if period_id != "P3" else "contrary",
        )
        for group in fresh["groups"]
        for ad in group["ads"]
    ]
    originals = []
    for group in fresh["groups"]:
        for ad in group["ads"]:
            material = ads_learnings.bound_material(conn, org, brand, ad)
            asset = conn.execute(
                "SELECT a.storage_key FROM ads_user_asset a "
                "JOIN ads_asset_placement p ON p.asset_id=a.id WHERE p.id=%s",
                (ad["material_placement_id"],),
            ).fetchone()
            asset = required(asset, "Original asset reference")
            content, _ = storage.get(org_id=org, key=asset["storage_key"])
            originals.append(
                {
                    "ad_id": ad["id"],
                    "material": material,
                    "sha256": sha(content),
                    "bytes": len(content),
                }
            )
    from app.brand_intelligence import repository as learning_repo
    from app.workbench import encode_learning_scope

    primary = next(e for e in evidence if e["sample"]["result_events"] == period["events"])
    learning = learning_repo.record_learning(
        conn,
        brand,
        actor="f53-synthetic",
        product_id=context["f53_setup"]["product_id"],
        platform="meta",
        learning_text="Synthetic controlled convenience "
        + primary["direction"]
        + " association, not market proof",
        applicability_scope=encode_learning_scope("ads", primary),
        confidence="observed",
        sample_size=str(period["events"]),
        source_cycle_id="f53:" + campaign_id,
        source_track="ads",
    )
    return {
        "raw_observations": raw,
        "source_evidence": evidence,
        "originals": originals,
        "provenance": "injected-reader-synthetic-not-market-results",
        "controlled_learning": learning,
    }


def fixture_derivatives(conn, context, learning_id):
    """Inject only owned synthetic ledger falsifiers, preserving actual source extraction."""
    from copy import deepcopy

    from app.brand_intelligence import repository
    from app.workbench import encode_learning_scope

    rows = repository.list_learnings(conn, context["brand_id"], limit=500, include_expired=True)
    original = next(row for row in rows if row["id"] == learning_id)
    evidence = json.loads(original["applicability_scope"].split("\n@evidence-v1:")[1])
    injected = []
    for kind in ("coordinate", "visual", "replay", "product-B"):
        raw = deepcopy(evidence)
        product = original["product_id"]
        if kind in {"coordinate", "visual"}:
            raw["source_kind"] = kind
        elif kind == "replay":
            raw["source_version"] += ":replayed"
            raw["period"]["start"] = raw["period"]["end"]
        else:
            product = context["f53_setup"]["other_product_id"]
            raw["scope"]["product_id"] = product
            raw["source_ref"]["trial_id"] = "synthetic-product-B"
        row = repository.record_learning(
            conn,
            context["brand_id"],
            actor="f53-synthetic",
            product_id=product,
            learning_text=original["learning_text"] + "; synthetic " + kind,
            applicability_scope=encode_learning_scope("ads", raw),
            confidence="observed",
            sample_size=str(raw["sample"]["result_events"]),
            source_track="ads",
            source_cycle_id="f53-" + kind + ":" + learning_id,
        )
        injected.append({**row, "fixture_kind": kind, "fixture_evidence": raw})
    return {
        "original": original,
        "original_evidence": evidence,
        "injected": injected,
        "provenance": "synthetic-only",
    }


def fixture_mutation(conn, context, campaign_id, kind):
    """Finite existing-column changes in the admitted owned schema, never shared data."""
    from psycopg import sql
    from psycopg.types.json import Jsonb

    from app.ads import ads_learnings, repository
    from app.brand_intelligence import repository as brands

    org, brand = context["org_id"], context["brand_id"]
    if kind == "restore":
        entry = context.pop("f53_mutation")
        conn.execute(
            sql.SQL("UPDATE {} SET {}=%s WHERE org_id=%s AND brand_id=%s AND id=%s").format(
                sql.Identifier(entry["table"]), sql.Identifier(entry["field"])
            ),
            (
                Jsonb(entry["before"]) if isinstance(entry["before"], dict) else entry["before"],
                org,
                brand,
                entry["id"],
            ),
        )
        conn.commit()
        return {"restored": entry}
    if context.get("f53_mutation"):
        raise ReceiptError("A fixture mutation is already active")
    product = context["f53_setup"]["product_id"]
    if kind == "offer":
        table, field, identity = "product", "free_shipping", product
        before = required(brands.get_product(conn, brand, product))[field]
        after = not before
    elif kind == "price":
        table, field = "product_economics", "selling_price"
        row = conn.execute(
            "SELECT id,selling_price FROM product_economics"
            " WHERE org_id=%s AND brand_id=%s AND product_id=%s"
            " AND status='confirmed' ORDER BY confirmed_at DESC LIMIT 1",
            (org, brand, product),
        ).fetchone()
        row = required(row)
        identity, before = row["id"], row["selling_price"]
        after = before + 1
    elif kind == "target":
        table, field, identity = "ads_campaign", "target_cost", campaign_id
        before = required(repository.get_campaign(conn, org, brand, campaign_id))[field]
        after = float(before or 300) + 1
    elif kind == "material":
        table, field = "ads_asset_placement", "copy_fields"
        campaign = required(repository.get_campaign(conn, org, brand, campaign_id))
        decision = campaign["budget_basis_json"]["strategy"]["decision"]
        relevant = [s["carry_from_ad_id"] for s in decision["slots"] if s["carry_from_ad_id"]]
        learning_ids = {
            r["id"]
            for s in decision["slots"]
            for r in s["evidence_refs"]
            if r["kind"] == "learning"
        }
        for learned in brands.list_learnings(conn, brand, limit=500, include_expired=True):
            if (
                learned["id"] in learning_ids
                and "\n@evidence-v1:" in learned["applicability_scope"]
            ):
                raw = json.loads(learned["applicability_scope"].split("\n@evidence-v1:")[1])
                if raw["source_ref"].get("ad_id"):
                    relevant.append(raw["source_ref"]["ad_id"])
        if not relevant:
            raise ReceiptError("Displayed proposal lacks a relevant served material source")
        row = conn.execute(
            "SELECT p.id,p.copy_fields FROM ads_asset_placement p"
            " JOIN ads_ad a ON a.material_placement_id=p.id"
            " WHERE p.org_id=%s AND p.brand_id=%s AND a.id=ANY(%s)"
            " ORDER BY p.id LIMIT 1",
            (org, brand, relevant),
        ).fetchone()
        row = required(row, "Displayed proposal material binding")
        identity, before = row["id"], row[field]
        after = {**before, "headline": "Explicit changed synthetic material"}
    elif kind == "same-ID-meaning":
        table, field = "learning_ledger", "learning_text"
        decision = required(repository.get_campaign(conn, org, brand, campaign_id))[
            "budget_basis_json"
        ]["strategy"]["decision"]
        referenced = list(
            dict.fromkeys(
                ref["id"]
                for slot in decision["slots"]
                for ref in slot["evidence_refs"]
                if ref["kind"] == "learning"
            )
        )
        row = conn.execute(
            "SELECT id,learning_text FROM learning_ledger WHERE org_id=%s"
            " AND brand_id=%s AND product_id=%s AND id=ANY(%s)"
            " ORDER BY learned_at DESC,id DESC LIMIT 1",
            (org, brand, product, referenced),
        ).fetchone()
        row = required(row)
        identity, before = row["id"], row[field]
        after = before + "; changed meaning under the SAME ID"
    else:
        raise ReceiptError("Unsupported owned stale fixture")
    context["f53_mutation"] = {
        "kind": kind,
        "table": table,
        "field": field,
        "id": identity,
        "before": before,
        "after": after,
        "proposal_refs": [
            r
            for s in required(repository.get_campaign(conn, org, brand, campaign_id))[
                "budget_basis_json"
            ]["strategy"]["decision"]["slots"]
            for r in s["evidence_refs"]
        ],
        "current_conditions_before": ads_learnings.current_conditions(
            conn,
            org,
            brand,
            product,
            campaign=required(repository.get_campaign(conn, org, brand, campaign_id)),
        ),
    }
    conn.execute(
        sql.SQL("UPDATE {} SET {}=%s WHERE org_id=%s AND brand_id=%s AND id=%s").format(
            sql.Identifier(table), sql.Identifier(field)
        ),
        (Jsonb(after) if isinstance(after, dict) else after, org, brand, identity),
    )
    conn.commit()
    return context["f53_mutation"]


def check_adopted_bindings(proposed, adopted, originals=None):
    """Compare concrete accepted and durable executable assignments, including exact carry."""
    decision = adopted["budget_basis_json"]["strategy"]["decision"]
    receipt = decision.get("receipt")
    if not receipt or receipt.get("revision") != proposed["revision"]:
        raise ReceiptError("Accepted decision receipt/revision missing")
    actual = {
        (a.get("coordinates_snapshot_json") or {})["strategy_slot"]["slot_id"]: {
            **a,
            "actual_role": g["role"],
            "actual_group_id": g["id"],
        }
        for g in adopted["groups"]
        for a in g["ads"]
    }
    for slot in proposed["slots"]:
        ad = actual.get(slot["id"])
        if not ad or any(
            ad.get(field) != slot.get(field) for field in ("customer_group_id", "offer_key")
        ):
            raise ReceiptError("Actual audience/offer disagrees with accepted slot")
        snapshot = ad["coordinates_snapshot_json"]
        carried = (snapshot.get("carried_from") or {}).get("ad_id")
        stored = next(s for s in decision["slots"] if s["id"] == slot["id"])
        if (
            ad["actual_role"] != slot["role"]
            or carried != slot["carry_from_ad_id"]
            or stored.get("test_intent") != slot.get("test_intent")
            or snapshot["strategy_slot"]["revision"] != proposed["revision"]
        ):
            raise ReceiptError("Actual carry/test/role disagrees with accepted slot")
        bound = next((r for r in receipt["slots"] if r["slot_id"] == slot["id"]), {})
        if bound.get("ad_id") != ad["id"] or bound.get("group_id") != ad["actual_group_id"]:
            raise ReceiptError("Durable receipt maps to different executable nodes")
        if slot.get("carry_from_ad_id") and originals is not None:
            prior = next((o for o in originals if o["ad_id"] == slot["carry_from_ad_id"]), None)
            if prior is None:
                raise ReceiptError("Original carried creative proof absent")
    return receipt


def fixed_cycle_flow(client, runtime_context, remaining):
    """Actual owned HTTP handlers, with explicitly synthetic reader/provider substitutions."""
    context = runtime_context
    directory = Path(context["evidence_dir"])
    base = f"/api/ads/brands/{context['brand_id']}"
    client.headers["X-F53-Owner"] = context["f53_nonce"]

    def call(method, url, *, expected_status=200, **kwargs):
        response = client.request(method, url, timeout=remaining(), **kwargs)
        raw = {
            "method": method,
            "path": url,
            "status": response.status_code,
            "body": response.json(),
        }
        with (directory / "http-events.jsonl").open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(raw, ensure_ascii=False, default=str) + "\n")
        if response.status_code != expected_status:
            raise ReceiptError("Actual HTTP boundary differs: " + url)
        return raw["body"]

    setup = call("POST", "/__f53/setup")
    qualified = cases.qualification_cases()
    write(directory / "qualification-cases.json", qualified)
    receipts = []
    original = []
    for period in cases.frozen_cases()["periods"]:
        Path(context["f53_today"]).write_text(period["start"], encoding="utf-8")
        write(context["f53_clock"], {"period": period["id"]})
        campaign = call(
            "POST",
            base + "/campaigns",
            json={
                "product_ids": [setup["product_id"]],
                "objective": "購買",
                "budget": 30000,
                "start_date": period["start"],
                "end_date": period["end"],
                "cap": 300,
                "platform": "meta",
                "goal_text": "Synthetic uncertain buyer test",
            },
        )["campaign"]
        call("POST", "/__f53/planning-campaign/" + campaign["id"])
        route = base + "/campaigns/" + campaign["id"]
        proposal = call("POST", route + "/strategy", json={})["campaign"]
        proposal = call(
            "POST",
            route + "/strategy/scenario",
            json={"scenario_key": "custom", "custom_total": 30000},
        )["campaign"]
        decision = proposal["budget_basis_json"]["strategy"]["decision"]
        if period["id"] == "P1" and not any(s["offer_key"] == "none" for s in decision["slots"]):
            raise ReceiptError("Cold start lacks the explicit no-offer test")
        adopted = call(
            "POST",
            route + "/plan",
            json={
                "expected_revision": decision["revision"],
                "operation_id": "f53-adopt-" + period["id"],
            },
        )["campaign"]
        receipt = check_adopted_bindings(decision, adopted, original)
        replay = call(
            "POST",
            route + "/plan",
            json={
                "expected_revision": decision["revision"],
                "operation_id": "f53-adopt-" + period["id"],
            },
        )["campaign"]
        if replay["groups"] != adopted["groups"]:
            raise ReceiptError("Adoption replay changed accepted executable groups")
        observations = call("POST", f"/__f53/observe/{campaign['id']}/{period['id']}")
        derivatives = call(
            "POST", "/__f53/derivatives/" + observations["controlled_learning"]["id"]
        )
        if original:
            for slot in decision["slots"]:
                if not slot.get("carry_from_ad_id"):
                    continue
                old = next(o for o in original if o["ad_id"] == slot["carry_from_ad_id"])
                aid = next(
                    a["id"]
                    for g in adopted["groups"]
                    for a in g["ads"]
                    if a["coordinates_snapshot_json"]["strategy_slot"]["slot_id"] == slot["id"]
                )
                new = next(o for o in observations["originals"] if o["ad_id"] == aid)
                for field in ("sha256", "bytes"):
                    if old[field] != new[field]:
                        raise ReceiptError("Carried image bytes changed")
                if old["material"]["copy"] != new["material"]["copy"]:
                    raise ReceiptError("Original carried copy changed")
        original = observations["originals"]
        Path(context["f53_today"]).write_text(
            {"P1": "2026-08-01", "P2": "2026-09-01", "P3": "2026-10-01"}[period["id"]],
            encoding="utf-8",
        )
        closed = call("POST", route + "/close", json={})["campaign"]
        if closed["verdict_json"].get("actual") != period["cost_per_result"]:
            raise ReceiptError("Actual closed period cost differs from frozen observation")
        view = call("GET", base + "/coordinate-learnings?sell_way_id=" + setup["product_id"])
        receipts.append(
            {
                "period": period,
                "proposal": proposal,
                "accepted": adopted,
                "adoption_receipt": receipt,
                "observations": observations,
                "closed": closed,
                "reader": view,
                "derivatives": derivatives,
            }
        )
    stale = http_stale_cases(call, base, setup)
    source_checks = call("GET", "/__f53/source-checks")
    write(directory / "source-boundaries.json", source_checks)
    cycle = {
        "provenance": "synthetic-only",
        "periods": receipts,
        "expectations_sha256": cases.CASES_SHA256,
        "source_checks": source_checks,
        "stale_cases": stale,
        "consumer_contexts": [
            json.loads(line)
            for line in (directory / "consumer-contexts.jsonl").read_text("utf-8").splitlines()
        ],
        "consumer_prompts": [
            json.loads(line)
            for line in (directory / "consumer-prompts.jsonl").read_text("utf-8").splitlines()
        ],
        "run_id": context["f53_run_id"],
    }
    write(directory / "fixed-cycle.json", cycle)
    verify_http_cycle(cycle)
    return {
        "campaign_id": campaign["id"],
        "originals": [],
        "provenance": "synthetic-only",
        "runtime_seconds": 0,
    }


def http_stale_cases(call, base, setup):
    """All mutations run against actual handlers; each refresh needs a new explicit revision."""
    receipts = []
    for kind in ("offer", "price", "material", "target", "same-ID-meaning"):
        campaign = call(
            "POST",
            base + "/campaigns",
            json={
                "product_ids": [setup["product_id"]],
                "objective": "購買",
                "budget": 30000,
                "start_date": "2026-10-01",
                "end_date": "2026-10-31",
                "cap": 300,
                "platform": "meta",
                "goal_text": "Retained explicit synthetic test input",
            },
        )["campaign"]
        route = base + "/campaigns/" + campaign["id"]
        call("POST", "/__f53/planning-campaign/" + campaign["id"])
        call("POST", route + "/strategy", json={})
        proposal = call(
            "POST",
            route + "/strategy/scenario",
            json={"scenario_key": "custom", "custom_total": 30000},
        )["campaign"]
        old = proposal["budget_basis_json"]["strategy"]["decision"]
        before = call("GET", "/__f53/retained/" + campaign["id"])
        mutation = call("POST", f"/__f53/mutate/{campaign['id']}/{kind}")
        try:
            failed = call(
                "POST",
                route + "/plan",
                expected_status=409,
                json={"expected_revision": old["revision"], "operation_id": "f53-stale-" + kind},
            )
            retained = call("GET", "/__f53/retained/" + campaign["id"])
            served = call("GET", route)["campaign"]
            check = {
                "kind": kind,
                "mutation": mutation,
                "retained_before": before,
                "retained_after": retained,
                "served_after_rejection": served,
            }
            verify_retained_case(check)
            if failed.get("error", {}).get("code") != "strategy_changed" or served["groups"]:
                raise ReceiptError("Rejection is not the guarded stale strategy refusal")
            refreshed = call("POST", route + "/strategy", json={})["campaign"]
            decision = refreshed["budget_basis_json"]["strategy"]["decision"]
            if decision["revision"] == old["revision"]:
                raise ReceiptError("Explicit refresh did not incorporate changed source meaning")
            adopted = call(
                "POST",
                route + "/plan",
                json={
                    "expected_revision": decision["revision"],
                    "operation_id": "f53-reconfirmed-" + kind,
                },
            )["campaign"]
            check_adopted_bindings(decision, adopted)
            receipts.append(
                {
                    "kind": kind,
                    "mutation": mutation,
                    "proposal": proposal,
                    "rejection": {"status": 409, "body": failed},
                    "retained_before": before,
                    "retained_after": retained,
                    "served_after_rejection": served,
                    "refreshed": refreshed,
                    "adopted": adopted,
                }
            )
        finally:
            call("POST", "/__f53/restore-mutation")
    return receipts


def run_cycle(context_path, port, timeout):
    from scripts import verify_existing_campaigns_assets as lifecycle
    from scripts.drill import recovery_probe

    value = context_at(context_path)
    directory = Path(value["directory"])
    if port in PROTECTED_PORTS or not 1024 <= port <= 65535 or not 1 <= timeout <= 300:
        raise ReceiptError("Use a new owned port and a cycle bound of at most 300 seconds")
    with socket.socket() as check:
        check.bind(("127.0.0.1", port))
    once(directory, "fixed-cycle")
    today = directory / "today"
    today.write_text("2026-07-01", encoding="utf-8")
    write(directory / "period.json", {"period": "P1"})
    create_schema = lifecycle.create_schema

    def owned_schema(settings, schema, org, brands, remaining):
        admin, scoped, user = create_schema(
            settings, schema, org, brands, remaining, f53_schema_only=True
        )
        value.update(
            schema=schema,
            org_id=org,
            brand_id=brands[0],
            db_identity={
                k: str(v)
                for k, v in __import__("psycopg").conninfo.conninfo_to_dict(admin).items()
                if k in recovery_probe.DB_IDENTITY_FIELDS
            },
        )
        value["db_identity"]["hostaddr"] = value["db_identity"].get("hostaddr", "127.0.0.1")
        value["db_identity"]["port"] = value["db_identity"].get("port", "5432")
        write(context_path, value)
        return admin, scoped, user

    original_write = lifecycle.write_json
    original_flow = lifecycle.runtime_flow
    original_file = lifecycle.__file__

    def write_context(path, payload):
        if Path(path).name == "runtime-context.json":
            payload.update(
                f53_today=str(today),
                f53_clock=str(directory / "period.json"),
                f53_nonce=value["nonce"],
                f53_run_id=value["run_id"],
            )
        original_write(path, payload)

    lifecycle.create_schema = owned_schema
    lifecycle.write_json = write_context
    lifecycle.runtime_flow = fixed_cycle_flow
    lifecycle.__file__ = __file__
    args = argparse.Namespace(
        isolated=True,
        timeout=timeout,
        env_file=None,
        port=port,
        context=str(directory / "runtime-context.json"),
        runtime_restart=False,
    )
    try:
        lifecycle.main(args)
        cleanup = read(directory / "cleanup.json")
        if cleanup.get("errors") or not all(
            cleanup.get(k) is True
            for k in ("process_stopped", "storage", "schema", "fixture_media")
        ):
            raise ReceiptError("Owned fixed cycle cleanup incomplete")
        for gate in ("G1", "G2", "G3", "G4"):
            save_gate(
                context_path,
                gate,
                [
                    directory / "fixed-cycle.json",
                    directory / "qualification-cases.json",
                    directory / "source-boundaries.json",
                    directory / "http-events.jsonl",
                    directory / "cleanup.json",
                ],
                status="pass",
                limitations=["Canned provider contract only; synthetic reader"],
                cleanup={k: True for k in ("process_stopped", "storage", "schema")},
            )
    except Exception as exc:
        write(
            directory / "cycle-failure.json",
            {
                "at": now(),
                "error_type": type(exc).__name__,
                "details": str(exc) if isinstance(exc, (ReceiptError, AssertionError)) else None,
            },
        )
        raise
    finally:
        lifecycle.create_schema = create_schema
        lifecycle.write_json = original_write
        lifecycle.runtime_flow = original_flow
        lifecycle.__file__ = original_file
    return read(context_path)


def docker_pg_command(
    container, verb, *, database, schema=None, raw=None, env=None, timeout: float = 30
):
    """Credential value travels in inherited env, never argv or public evidence."""
    env = required(env, "Owned PostgreSQL tool environment")
    if not re.fullmatch(r"[a-zA-Z0-9_.-]+", container):
        raise ReceiptError("Invalid PostgreSQL tool container identity")
    argv = [
        "docker",
        "exec",
        "-i",
        "-e",
        "PGPASSWORD",
        container,
        verb,
        "-h",
        "127.0.0.1",
        "-U",
        env["PGUSER"],
        "-d",
        database,
    ]
    if verb == "pg_dump":
        if not re.fullmatch(r"f13_runtime_[a-f0-9]{12}", schema or ""):
            raise ReceiptError("Only the admitted owned schema may be dumped")
        schema = required(schema)
        argv += [
            "--no-owner",
            "--no-privileges",
            "--schema",
            schema,
            "--schema",
            schema + "__queue",
        ]
    elif verb == "psql":
        argv += ["--no-psqlrc", "--set", "ON_ERROR_STOP=1"]
    else:
        raise ReceiptError("Only dump and restore tools are permitted")
    result = command(argv, timeout=timeout, env=env, input=raw)
    if result.returncode:
        raise ReceiptError("Owned PostgreSQL tool failed; credential-bearing stderr withheld")
    return result.stdout


def verify_db_container(container, params):
    """Read actual port mapping before accessing native tools inside an existing container."""
    result = command(["docker", "inspect", container], timeout=5)
    if result.returncode:
        raise ReceiptError("UNVERIFIED: existing PostgreSQL tools/container unavailable")
    values = json.loads(result.stdout)
    if len(values) != 1 or not values[0].get("State", {}).get("Running"):
        raise ReceiptError("PostgreSQL tool container is not running")
    ports = values[0].get("NetworkSettings", {}).get("Ports", {}).get("5432/tcp") or []
    if not any(
        p["HostIp"] in {"0.0.0.0", "127.0.0.1", "::", "::1"}
        and p["HostPort"] == str(params["port"])
        for p in ports
    ):
        raise ReceiptError("Container does not match the pinned local PostgreSQL endpoint")
    return {
        "container_id": values[0]["Id"],
        "image_id": values[0]["Image"],
        "started_at": values[0]["State"]["StartedAt"],
    }


def database_inventory(conn, schema):
    """Actual relation definitions and all rows; tenant partition is compared separately."""
    from psycopg import sql

    relations = conn.execute(
        "SELECT tablename FROM pg_tables WHERE schemaname=%s ORDER BY tablename", (schema,)
    ).fetchall()
    data = {}
    for relation in relations:
        table = relation[0]
        rows = conn.execute(
            sql.SQL("SELECT row_to_json(t) FROM {}.{} t").format(
                sql.Identifier(schema), sql.Identifier(table)
            )
        ).fetchall()
        columns = conn.execute(
            "SELECT column_name,data_type,is_nullable,column_default "
            "FROM information_schema.columns WHERE table_schema=%s AND table_name=%s "
            "ORDER BY ordinal_position",
            (schema, table),
        ).fetchall()
        data[table] = {
            "columns": [list(row) for row in columns],
            "rows": sorted((row[0] for row in rows), key=cases.canonical),
        }
    return data


def restore_probe(context_path, container):
    """Own fixture schema -> dump -> separate disposable DB, plus real restored Storage bytes."""
    import psycopg
    from psycopg import sql
    from psycopg.conninfo import conninfo_to_dict

    from app import storage
    from scripts import verify_existing_campaigns_assets as lifecycle

    value = context_at(context_path)
    directory = Path(value["directory"])
    once(directory, "restore")
    from scripts.drill import recovery_probe

    recovery_probe.admit()
    # Freeze effective host/port/user before any DDL; service/hostaddr indirection rejected.
    schema = "f13_runtime_" + uuid.uuid4().hex[:12]
    owner = "org_" + schema
    params = conninfo_to_dict(recovery_probe.scoped_dsn({"schema": schema}))
    params.pop("options", None)
    admin = dsn_string(params)
    target_db = "f53_restore_" + uuid.uuid4().hex[:12]
    tool_identity = verify_db_container(container, params)
    env = {**os.environ, "PGUSER": params["user"], "PGPASSWORD": params.get("password", "")}
    source_key = owner + "/backup-sample/original.bin"
    destination_key = owner + "/restored-" + value["run_id"] + "/original.bin"
    sample = b"F53 actual owned Storage backup sample\x00\xff\x01"
    target_created = False
    schema_created = False
    objects = []
    result = {
        "started_at": now(),
        "status": "unverified",
        "schema": schema,
        "target_database": target_db,
        "tool_identity": tool_identity,
        "cleanup": {"source_schema": False, "target_database": False, "storage": False},
        "shared_public": "no DDL/DML addressed shared public; audited migration inventory",
    }
    write(
        directory / "restore-ownership.json",
        {
            "nonce": value["nonce"],
            "schema": schema,
            "database": target_db,
            "storage_keys": [source_key, destination_key],
        },
    )
    started = time.monotonic()

    def remaining():
        left = 150 - (time.monotonic() - started)
        if left <= 0:
            raise TimeoutError("Owned restore exceeded its 150-second bound")
        return min(left, 30)

    try:
        schema_created = True  # Ownership persisted before partially successful schema creation.
        lifecycle.create_schema(
            {"DATABASE_URL": admin},
            schema,
            owner,
            ["brd_" + schema, "brd_other_" + schema],
            remaining,
            f53_schema_only=True,
        )
        with psycopg.connect(admin, autocommit=True, connect_timeout=5) as conn:
            conn.execute("SET statement_timeout='10s'")
            conn.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(target_db)))
            target_created = True
            conn.execute(sql.SQL("SET search_path TO {}").format(sql.Identifier(schema)))
            other_org = "org_other_" + schema
            conn.execute(
                "INSERT INTO organisation(id,name,kind) VALUES(%s,%s,'company')",
                (other_org, "Owned isolated other tenant"),
            )
            conn.execute(
                "UPDATE brand SET org_id=%s WHERE id=%s", (other_org, "brd_other_" + schema)
            )
            conn.execute(
                "INSERT INTO ads_user_asset(id,org_id,brand_id,sha256,storage_key,"
                "filename,mime_type,byte_size,status) VALUES(%s,%s,%s,%s,%s,"
                "'original.bin','application/octet-stream',%s,'ready')",
                ("aua_" + schema, owner, "brd_" + schema, sha(sample), source_key, len(sample)),
            )
            source_inventory = database_inventory(conn, schema)
        objects.append(source_key)  # Capture cleanup ownership before partial transport success.
        storage.put(
            org_id=owner,
            key=source_key,
            filename="original.bin",
            content=sample,
            content_type="application/octet-stream",
        )
        downloaded, mime = storage.get(org_id=owner, key=source_key)
        if downloaded != sample:
            raise ReceiptError("Storage export differs from original sample")
        exported = directory / "storage-sample.bin"
        exported.write_bytes(downloaded)
        dump = docker_pg_command(
            container,
            "pg_dump",
            database=params["dbname"],
            schema=schema,
            env=env,
            timeout=remaining(),
        )
        backup = directory / "owned-schema.sql"
        backup.write_bytes(dump)
        docker_pg_command(
            container, "psql", database=target_db, raw=dump, env=env, timeout=remaining()
        )
        restored_params = {**params, "dbname": target_db}
        with psycopg.connect(dsn_string(restored_params), connect_timeout=5) as conn:
            restored_inventory = database_inventory(conn, schema)
            if restored_inventory != source_inventory:
                raise ReceiptError("Restored schema/rows differ from dumped source")
            organisations = restored_inventory["organisation"]["rows"]
            brands = restored_inventory["brand"]["rows"]
            if {b["org_id"] for b in brands} != {owner, other_org} or len(organisations) != 2:
                raise ReceiptError("Restored tenant ownership differs")
            own = conn.execute(
                sql.SQL("SELECT id FROM {}.brand WHERE org_id=%s").format(sql.Identifier(schema)),
                (owner,),
            ).fetchall()
            if own != [("brd_" + schema,)]:
                raise ReceiptError("Restored tenant query leaked the other tenant")
            conn.execute(
                sql.SQL(
                    "UPDATE {}.ads_user_asset SET storage_key=%s WHERE id=%s AND org_id=%s"
                ).format(sql.Identifier(schema)),
                (destination_key, "aua_" + schema, owner),
            )
            restored_ref = required(
                conn.execute(
                    sql.SQL(
                        "SELECT storage_key FROM {}.ads_user_asset WHERE id=%s AND org_id=%s"
                    ).format(sql.Identifier(schema)),
                    ("aua_" + schema, owner),
                ).fetchone()
            )[0]
            conn.commit()
        if restored_ref != destination_key:
            raise ReceiptError("Restored asset reference still addresses the surviving source")
        objects.append(destination_key)
        storage.put(
            org_id=owner,
            key=destination_key,
            filename="restored.bin",
            content=exported.read_bytes(),
            content_type=mime,
        )
        storage.delete(org_id=owner, key=source_key)
        objects.remove(source_key)
        try:
            storage.get(org_id=owner, key=source_key)
        except storage.NotFound:
            source_deleted = True
        else:
            raise ReceiptError("Source survives; cannot claim isolated Storage restoration")
        restored_bytes, _ = storage.get(org_id=owner, key=restored_ref)
        if sha(restored_bytes) != sha(sample):
            raise ReceiptError("Restored destination sample bytes differ")
        result.update(
            status="pass",
            backup=reference(backup),
            storage_export=reference(exported),
            schema_inventory_hash=cases.digest(source_inventory),
            row_inventory=source_inventory,
            asset={
                "source_key": source_key,
                "restored_key": destination_key,
                "source_deleted_before_verify": source_deleted,
                "sha256": sha(restored_bytes),
                "bytes": len(restored_bytes),
                "restored_db_reference": restored_ref,
            },
            tenant_queries={"owner": owner, "other": other_org, "returned_brand_ids": own},
            finished_at=now(),
        )
    finally:
        errors = []
        for key in objects:
            try:
                storage.delete(org_id=owner, key=key)
            except Exception as exc:
                errors.append("storage:" + type(exc).__name__)
        result["cleanup"]["storage"] = not errors
        try:
            with psycopg.connect(admin, autocommit=True, connect_timeout=5) as conn:
                conn.execute("SET statement_timeout='10s'")
                if target_created:
                    # No FORCE/disconnect shortcut; an in-use target is a cleanup failure.
                    conn.execute(sql.SQL("DROP DATABASE {}").format(sql.Identifier(target_db)))
                result["cleanup"]["target_database"] = True
                if schema_created:
                    for name in (schema + "__queue", schema):
                        conn.execute(
                            sql.SQL("DROP SCHEMA IF EXISTS {} CASCADE").format(sql.Identifier(name))
                        )
                result["cleanup"]["source_schema"] = True
        except Exception as exc:
            errors.append("database:" + type(exc).__name__)
        result["cleanup_errors"] = errors
        write(directory / "restore-receipt.json", result)
        if errors:
            raise ReceiptError("Restore cleanup failed; retain the ownership receipt")
    return result


AUTH_IMAGE = "sha256:362659ca70eaa75ba05bbaf963caa84c1c5afe5e8fbf0777e17b830dd5f0f60a"
AUTH_VERSION = "v2.195.0"


def inspect_owned_container(name, nonce, expected_id=None):
    """Discover creation after a timeout by the pre-reserved name AND opaque owner label."""
    result = command(["docker", "inspect", name], timeout=5)
    if result.returncode:
        raise ReceiptError("Container identity unavailable; cleanup remains unverified")
    records = json.loads(result.stdout)
    if len(records) != 1:
        raise ReceiptError("Container identity is not unique")
    actual = records[0]
    if (
        actual.get("Name") != "/" + name
        or actual.get("Image") != AUTH_IMAGE
        or actual.get("Config", {}).get("Labels", {}).get("f53.owner") != nonce
        or expected_id is not None
        and actual.get("Id") != expected_id
        or not actual.get("Id")
        or not actual.get("Created")
    ):
        raise ReceiptError("Container ownership changed; refuse deletion")
    return {
        "id": actual["Id"],
        "name": name,
        "image": actual["Image"],
        "created": actual["Created"],
        "started": actual.get("State", {}).get("StartedAt"),
        "owner": nonce,
    }


def private_file(path, raw):
    """Secrets stay in a fresh ignored private file and are removed in bounded cleanup."""
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as stream:
        stream.write(raw)


def auth_child(context_path, port):
    """Same product guards/build; transparent prefix proxy forwards actual GoTrue responses."""
    import httpx
    import pytest  # noqa: F401 -- prevent main from loading another checkout's dotenv
    import uvicorn
    from fastapi import Request, Response

    import app.main

    value = read(context_path)
    application = app.main.app
    globals()["Request"] = Request

    @application.api_route(
        "/auth/v1/{suffix:path}", methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"]
    )
    async def proxy(request: Request, suffix: str):
        # No token/session fabrication, expiry shortcut or response rewriting.
        headers = {
            k: v
            for k, v in request.headers.items()
            if k.lower() not in {"host", "content-length", "connection"}
        }
        async with httpx.AsyncClient(timeout=10, trust_env=False, follow_redirects=False) as client:
            response = await client.request(
                request.method,
                value["auth_direct_origin"] + "/" + suffix,
                params=request.query_params,
                headers=headers,
                content=await request.body(),
            )
        return Response(
            content=response.content,
            status_code=response.status_code,
            headers={
                k: v
                for k, v in response.headers.items()
                if k.lower()
                not in {"content-length", "connection", "transfer-encoding", "content-encoding"}
            },
        )

    @application.get("/__f53/auth-health")
    def health():
        return {"owner": sha(value["nonce"].encode()), "build": value["build"]}

    # Only the owned child uses the matching independently built frontend output.
    application.router.routes[:] = [
        r for r in application.router.routes if getattr(r, "name", None) != "react-shell"
    ]
    application.mount(
        "/app",
        app.main._SpaStaticFiles(directory=value["frontend_dist"], html=True),
        name="react-shell",
    )
    uvicorn.run(application, host="127.0.0.1", port=port, log_level="warning", access_log=False)


AUTH_BROWSER = r"""
import { createRequire } from "node:module";
import crypto from "node:crypto";
import fs from "node:fs";
const cfg = JSON.parse(fs.readFileSync(process.argv[2], "utf8"));
const { chromium } = createRequire(cfg.frontend_package)("@playwright/test");
const hash = s => crypto.createHash("sha256").update(s).digest("hex");
const containmentDeadline = Date.now() + 10000;
while (!fs.existsSync(cfg.directory + "/browser-contained.json")) {
  if (Date.now() > containmentDeadline) throw Error("Owned containment was not established");
  await new Promise(resolve => setTimeout(resolve, 20));
}
const containment = JSON.parse(fs.readFileSync(cfg.directory + "/browser-contained.json"));
if (containment.pid !== process.pid) throw Error("Browser launcher ownership mismatch");
const browser = await chromium.launch({headless:true});
const page = await browser.newPage();
const events = [], issuances = [], productRequests = [];
let latest = null;
page.on("request", request => {
  const url = new URL(request.url());
  if (url.origin === cfg.origin && url.pathname.startsWith("/api/") &&
      !["GET", "HEAD", "OPTIONS"].includes(request.method())) {
    productRequests.push({at:Date.now(), method:request.method(), path:url.pathname});
  }
});
page.on("response", async response => {
  if (!response.url().startsWith(cfg.origin + "/auth/v1/token")) return;
  const body = await response.json().catch(() => ({}));
  if (response.status() === 200 && body.access_token) {
    latest = body;
    const claims = JSON.parse(Buffer.from(body.access_token.split(".")[1], "base64url"));
    issuances.push({at:Date.now(), status:response.status(), access_sha256:hash(body.access_token),
      refresh_sha256:hash(body.refresh_token), iat:claims.iat, exp:claims.exp,
      sub:claims.sub, session_id:claims.session_id,
      grant:new URL(response.url()).searchParams.get("grant_type")});
  } else {
    events.push({at:Date.now(), status:response.status(), error_code:body.error_code || body.error,
                 boundary:"actual-GoTrue-token-response"});
  }
});
const login = async () => {
  await page.goto(cfg.origin + "/app/login");
  await page.locator('input[type=email]').fill(cfg.email);
  await page.locator('input[type=password]').fill(cfg.password);
  await page.locator('button[type=submit]').click();
  await page.waitForURL(url => !url.pathname.endsWith("/login"), {timeout:15000});
  await page.waitForFunction(() => [...Array(localStorage.length)].some((_, i) =>
    localStorage.key(i)?.endsWith("-auth-token")), {timeout:10000});
};
try {
  await login();
  if (!latest) throw Error("No actual issuer response observed");
  const headers = () => ({Authorization:"Bearer " + latest.access_token, "X-Org-Id":cfg.org});
  const issued = latest;
  const claims = JSON.parse(Buffer.from(issued.access_token.split(".")[1], "base64url"));
  const before = await page.request.get(cfg.origin + cfg.work_path,
    {headers:{Authorization:"Bearer " + issued.access_token, "X-Org-Id":cfg.org}});
  if (before.status() !== 200) throw Error("Saved work unavailable before expiry");
  const saved = await before.json(), savedHash = hash(JSON.stringify(saved)), beforeAt = Date.now();
  const revoke = await page.request.post(cfg.origin + "/auth/v1/logout?scope=local",
    {headers:{Authorization:"Bearer " + issued.access_token}});
  if (revoke.status() !== 204) throw Error("Owned session revocation failed");
  const revokedAt = Date.now();
  const refused = await page.request.post(cfg.origin + "/auth/v1/token?grant_type=refresh_token",
    {data:{refresh_token:issued.refresh_token}});
  const refusal = await refused.json();
  if (![400,401,403,422].includes(refused.status()))
    throw Error("Refresh was not genuinely refused");
  // SDK auto-refresh stays unchanged. Wait on wall time; never modify browser/token clocks.
  const deadline = Date.now() + 75000;
  while (Date.now() <= claims.exp * 1000) {
    if (Date.now() > deadline) throw Error("Genuine issuer expiry exceeded bounded wait");
    await new Promise(resolve => setTimeout(resolve, 100));
  }
  const expired = await page.request.get(cfg.origin + cfg.work_path,
    {headers:{Authorization:"Bearer " + issued.access_token, "X-Org-Id":cfg.org}});
  if (expired.status() !== 401)
    throw Error("Same genuinely issued token was not expired by server");
  const expiryAt = Date.now();
  await page.goto(cfg.origin + cfg.work_route);
  await page.waitForURL(/\/app\/login/, {timeout:15000});
  await page.screenshot({path:cfg.directory + "/auth-expired.png", fullPage:true});
  const loginAt = Date.now();
  await login();
  await page.goto(cfg.origin + cfg.work_route);
  const recovered = await page.request.get(cfg.origin + cfg.work_path, {headers:headers()});
  const restored = await recovered.json();
  if (recovered.status() !== 200 || hash(JSON.stringify(restored)) !== savedHash)
    throw Error("Original saved work changed after ordinary login");
  await page.screenshot({path:cfg.directory + "/auth-recovered.png", fullPage:true});
  const receipt = {status:"pass", auth_js_version:cfg.auth_js_version,
    issuances, actual_refresh_events:events,
    auto_refresh:"unchanged SDK default; all issuances tracked",
    before_status:before.status(), access_expired_status:expired.status(),
    before_access_sha256:hash(issued.access_token), revoked_at:revokedAt,
    revocation_status:revoke.status(), refresh_refused_status:refused.status(),
    refresh_error_code:refusal.error_code || refusal.error,
    same_token_expired_sha256:hash(issued.access_token),
    before_at:beforeAt, expired_at:expiryAt, login_at:loginAt, recovered_at:Date.now(),
    saved_work:{id:saved.campaign?.id, org_id:cfg.org, path:cfg.work_path, sha256:savedHash},
    recovered_work:{id:restored.campaign?.id, org_id:cfg.org,
      sha256:hash(JSON.stringify(restored))},
    browser_login:"ordinary signInWithPassword form; no signOut/event fabrication",
    product_requests:productRequests,
    requests_after_relogin:productRequests.filter(r => r.at >= loginAt)};
  fs.writeFileSync(cfg.directory + "/auth-browser-receipt.json", JSON.stringify(receipt,null,2));
} finally { await browser.close(); }
"""


def postgres_url(params, *, database, search_path):
    user = quote(params["user"], safe="")
    password = quote(params.get("password", ""), safe="")
    # Docker Desktop host bridge connects only to this previously pinned local database port.
    return (
        f"postgresql://{user}:{password}@host.docker.internal:{params['port']}/{database}"
        f"?options={quote('-c search_path=' + search_path, safe='')}"
    )


def auth_probe(context_path, auth_port, web_port):
    """Provision one owned same-version issuer; actual operation belongs to I09, not unit tests."""
    import httpx
    import psycopg
    from psycopg import sql
    from psycopg.conninfo import conninfo_to_dict
    from psycopg.rows import dict_row

    from scripts import verify_existing_campaigns_assets as lifecycle
    from scripts.drill import recovery_probe

    value = context_at(context_path)
    directory = Path(value["directory"])
    recovery_probe.admit()
    for port in (auth_port, web_port):
        if port in PROTECTED_PORTS or not 1024 <= port <= 65535 or auth_port == web_port:
            raise ReceiptError("New distinct owned loopback Auth/backend ports are required")
        with socket.socket() as check:
            check.bind(("127.0.0.1", port))
    secret = os.environ.get("SUPABASE_JWT_SECRET", "")
    anon = os.environ.get("SUPABASE_ANON_KEY") or os.environ.get("VITE_SUPABASE_ANON_KEY")
    if not secret or not anon:
        raise ReceiptError("UNVERIFIED: existing local JWT/anon configuration unavailable")
    image = command(["docker", "image", "inspect", AUTH_IMAGE], timeout=5)
    if image.returncode or json.loads(image.stdout)[0]["Id"] != AUTH_IMAGE:
        raise ReceiptError("UNVERIFIED: audited same-version GoTrue image unavailable")
    package = read(ROOT / "frontend/node_modules/@supabase/auth-js/package.json")
    if package["version"] != "2.112.4":
        raise ReceiptError("Audited SDK short-TTL behavior changed; recheck capability")
    once(directory, "auth")
    schema = "f13_runtime_" + uuid.uuid4().hex[:12]
    database = "f53_auth_" + uuid.uuid4().hex[:12]
    container = "f53_auth_" + value["nonce"][:12]
    params = conninfo_to_dict(recovery_probe.scoped_dsn({"schema": schema}))
    params.pop("options", None)
    admin_dsn = dsn_string(params)
    origin = f"http://127.0.0.1:{web_port}"
    direct = f"http://127.0.0.1:{auth_port}"
    email, password = "f53-" + uuid.uuid4().hex + "@example.test", uuid.uuid4().hex + "Aa1!"
    files = []
    child = None
    container_attempted = False
    database_created = False
    owned_container_id = None
    receipt = {
        "status": "unverified",
        "started_at": now(),
        "auth_version": AUTH_VERSION,
        "auth_image": AUTH_IMAGE,
        "database": database,
        "namespace": "auth",
        "search_path": "auth,pg_catalog",
        "jwt_exp": 45,
        "key_fingerprint": sha(secret.encode()),
        "shared_expiry_policy": "untouched",
        "proxy": "transparent /auth/v1 -> GoTrue root",
        "cleanup": {
            "container": False,
            "database": False,
            "backend": False,
            "browser": False,
            "secrets": False,
        },
    }
    write(
        directory / "auth-ownership.json",
        {
            "nonce": value["nonce"],
            "database": database,
            "container": container,
            "ports": [auth_port, web_port],
        },
    )
    deadline = time.monotonic() + 240

    def remaining(limit: float = 15):
        left = deadline - time.monotonic()
        if left <= 0:
            raise TimeoutError("Auth mode exceeded its 240-second fixture/browser bound")
        return min(left, limit)

    try:
        with psycopg.connect(admin_dsn, autocommit=True, connect_timeout=5) as conn:
            conn.execute("SET statement_timeout='10s'")
            conn.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(database)))
            database_created = True
        fixture_dsn = dsn_string({**params, "dbname": database})
        with psycopg.connect(fixture_dsn, autocommit=True, connect_timeout=5) as conn:
            conn.execute("SET statement_timeout='10s'")
            conn.execute("CREATE SCHEMA auth")
            conn.execute("SET search_path=auth,pg_catalog")
            actual_database, actual_schema, actual_search_path, actual_role = required(
                conn.execute(
                    "SELECT current_database(),current_schema(),current_setting('search_path'),"
                    "current_user"
                ).fetchone()
            )
            if (
                actual_database != database
                or actual_schema != "auth"
                or actual_search_path.replace(" ", "") != "auth,pg_catalog"
            ):
                raise ReceiptError("Disposable issuer database namespace identity mismatch")
            receipt["database_identity"] = {
                "database": actual_database,
                "schema": actual_schema,
                "search_path": actual_search_path,
                "role": actual_role,
            }
        env_file = directory / "gotrue-private.env"
        db_url = postgres_url(params, database=database, search_path="auth,pg_catalog")
        private_file(
            env_file,
            "\n".join(
                [
                    "GOTRUE_API_HOST=0.0.0.0",
                    "PORT=9999",
                    "GOTRUE_API_PORT=9999",
                    "GOTRUE_DB_DRIVER=postgres",
                    "GOTRUE_DB_NAMESPACE=auth",
                    "GOTRUE_DB_DATABASE_URL=" + db_url,
                    "GOTRUE_JWT_SECRET=" + secret,
                    "GOTRUE_JWT_EXP=45",
                    "GOTRUE_JWT_AUD=authenticated",
                    "GOTRUE_JWT_ADMIN_ROLES=service_role",
                    "GOTRUE_SITE_URL=" + origin + "/app",
                    "API_EXTERNAL_URL=" + origin + "/auth/v1",
                    "GOTRUE_MAILER_AUTOCONFIRM=true",
                    "GOTRUE_DISABLE_SIGNUP=false",
                    "GOTRUE_EXTERNAL_EMAIL_ENABLED=true",
                    "",
                ]
            ),
        )
        files.append(env_file)
        container_attempted = True
        started = command(
            [
                "docker",
                "run",
                "--detach",
                "--name",
                container,
                "--label",
                "f53.owner=" + value["nonce"],
                "--publish",
                f"127.0.0.1:{auth_port}:9999",
                "--env-file",
                str(env_file),
                AUTH_IMAGE,
            ],
            timeout=remaining(),
        )
        if started.returncode:
            raise ReceiptError("UNVERIFIED: owned issuer bootstrap failed; output withheld")
        owned_container_id = started.stdout.decode().strip()
        actual_container = inspect_owned_container(container, value["nonce"], owned_container_id)
        receipt["container_identity"] = actual_container
        with httpx.Client(timeout=5, trust_env=False, follow_redirects=False) as client:
            while True:
                try:
                    health = client.get(direct + "/health")
                    if health.status_code == 200:
                        break
                except httpx.HTTPError:
                    pass
                remaining()
                time.sleep(0.1)
            signup = client.post(direct + "/signup", json={"email": email, "password": password})
            if signup.status_code not in {200, 201}:
                raise ReceiptError("UNVERIFIED: genuine owned user signup is unavailable")
            user = signup.json().get("user") or signup.json()
            uuid.UUID(user["id"])
            control = client.post(
                direct + "/token?grant_type=password", json={"email": email, "password": password}
            )
            if control.status_code != 200:
                raise ReceiptError("Genuine password grant control failed")
            refresh = client.post(
                direct + "/token?grant_type=refresh_token",
                json={"refresh_token": control.json()["refresh_token"]},
            )
            if refresh.status_code != 200 or refresh.json()["user"]["id"] != user["id"]:
                raise ReceiptError("Genuine successful refresh control failed")
            receipt["refresh_success_control"] = {
                "status": 200,
                "sub": user["id"],
                "issuance_sha256": sha(refresh.content),
                "at": now(),
            }
        owned_params = {**params, "dbname": database}
        fixture_dsn = dsn_string(owned_params)
        org, brand = "org_" + schema, "brd_" + schema
        _, scoped, _ = lifecycle.create_schema(
            {"DATABASE_URL": fixture_dsn},
            schema,
            org,
            [brand, "brd_other_" + schema],
            lambda: remaining(30),
            f53_schema_only=True,
            auth_identity={"id": user["id"], "email": email},
        )
        # This independent DB has no global Storage bucket. Auth-only admission is separate below.
        from app.core import db

        # Keep native inventory connections tuple-based; only application Conn needs dict rows.
        with psycopg.connect(
            scoped, connect_timeout=5, row_factory=cast(Any, dict_row)
        ) as raw_conn:
            setup = fixture_setup(db.Conn(raw_conn), {"org_id": org, "brand_id": brand})
        dist = directory / "frontend-dist"
        environment = {
            **os.environ,
            "DATABASE_URL": scoped,
            "SUPABASE_URL": origin,
            "VITE_SUPABASE_URL": origin,
            "VITE_SUPABASE_ANON_KEY": anon,
            "BRAND_OS_LLM_PROVIDER": "scripted",
            "IDENTITY_DEV_TOKEN": "",
            "IDENTITY_ALLOW_HS256": "1",
            "DRILL_CLOCK_PATH": str(directory / "unused-today"),
            "DRILL_META_STATE": str(directory / "unused-meta.json"),
        }
        build = command(
            ["npm.cmd" if os.name == "nt" else "npm", "run", "build", "--", "--outDir", str(dist)],
            cwd=ROOT / "frontend",
            timeout=remaining(60),
            env=environment,
        )
        write(
            directory / "auth-build.json",
            {
                "exit": build.returncode,
                "stdout_hash": sha(build.stdout),
                "stderr_hash": sha(build.stderr),
            },
        )
        if build.returncode:
            raise ReceiptError("Matching owned Auth frontend build failed")
        child_context = directory / "auth-child.json"
        write(
            child_context,
            {
                "nonce": value["nonce"],
                "auth_direct_origin": direct,
                "frontend_dist": str(dist),
                "build": fingerprint(
                    directory,
                    [
                        str(p.relative_to(directory)).replace("\\", "/")
                        for p in dist.rglob("*")
                        if p.is_file()
                    ],
                ),
            },
        )
        log = (directory / "auth-backend.log").open("wb")
        try:
            child = subprocess.Popen(
                [
                    sys.executable,
                    __file__,
                    "--auth-child",
                    str(child_context),
                    "--port",
                    str(web_port),
                ],
                cwd=ROOT,
                env=environment,
                stdin=subprocess.DEVNULL,
                stdout=log,
                stderr=log,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            identity = recovery_probe.process_identity(child.pid)
            receipt["backend"] = identity
            with httpx.Client(timeout=3, trust_env=False) as client:
                while True:
                    if child.poll() is not None:
                        raise ReceiptError("Owned matching Auth backend exited")
                    try:
                        response = client.get(origin + "/__f53/auth-health")
                        if response.status_code == 200:
                            break
                    except httpx.HTTPError:
                        pass
                    remaining()
                    time.sleep(0.1)
                if response.json()["owner"] != sha(value["nonce"].encode()):
                    raise ReceiptError("Owned backend identity mismatch")
                created = client.post(
                    origin + f"/api/ads/brands/{brand}/campaigns",
                    headers={
                        "Authorization": "Bearer " + refresh.json()["access_token"],
                        "X-Org-Id": org,
                    },
                    json={
                        "product_ids": [setup["product_id"]],
                        "objective": "購買",
                        "budget": 7000,
                        "start_date": "2026-10-08",
                        "end_date": "2026-10-15",
                        "platform": "meta",
                        "cap": 300,
                    },
                )
                if created.status_code != 200:
                    raise ReceiptError("Supported saved work control could not be created")
                work_id = created.json()["campaign"]["id"]
            script = directory / "auth-browser.mjs"
            private_file(script, AUTH_BROWSER)
            files.append(script)
            config = directory / "browser-private.json"
            private_file(
                config,
                json.dumps(
                    {
                        "origin": origin,
                        "org": org,
                        "email": email,
                        "password": password,
                        "directory": str(directory).replace("\\", "/"),
                        "frontend_package": str(ROOT / "frontend/package.json"),
                        "auth_js_version": package["version"],
                        "work_path": f"/api/ads/brands/{brand}/campaigns/{work_id}",
                        "work_route": f"/app/brands/{brand}/ads/campaigns/{work_id}?tab=strategy",
                    }
                ),
            )
            files.append(config)
            browser = bounded_browser(
                ["node", str(script), str(config)],
                directory,
                timeout=remaining(120),
                env=environment,
            )
            receipt["browser_exit"] = browser.returncode
            receipt["browser_output_hash"] = sha(browser.stdout + browser.stderr)
            if browser.returncode:
                raise ReceiptError("UNVERIFIED: genuine ordinary browser recovery failed")
            receipt["browser"] = reference(directory / "auth-browser-receipt.json")
            receipt["status"] = "pass"
            receipt["finished_at"] = now()
        finally:
            log.close()
    finally:
        errors = []
        if child is not None:
            try:
                lifecycle.stop_process(child)
                receipt["cleanup"]["backend"] = child.poll() is not None
            except Exception as exc:
                errors.append("backend:" + type(exc).__name__)
        else:
            receipt["cleanup"]["backend"] = True
        if container_attempted:
            try:
                current = inspect_owned_container(container, value["nonce"], owned_container_id)
                receipt["container_identity"] = current
                stopped = command(["docker", "rm", "--force", current["id"]], timeout=15)
                receipt["cleanup"]["container"] = stopped.returncode == 0
            except Exception as exc:
                # A timed-out docker run may have created the container. Never infer absence.
                errors.append("container:" + type(exc).__name__)
        else:
            receipt["cleanup"]["container"] = True
        browser_identity = directory / "browser-ownership.json"
        receipt["cleanup"]["browser"] = (
            (
                read(browser_identity).get("cleanup") is True
                and read(browser_identity).get("launcher_ended") is True
            )
            if browser_identity.exists()
            else True
        )
        if browser_identity.exists():
            receipt["browser_ownership"] = reference(browser_identity)
        if database_created and receipt["cleanup"]["container"] and receipt["cleanup"]["backend"]:
            try:
                with psycopg.connect(admin_dsn, autocommit=True, connect_timeout=5) as conn:
                    conn.execute("SET statement_timeout='10s'")
                    conn.execute(sql.SQL("DROP DATABASE {}").format(sql.Identifier(database)))
                receipt["cleanup"]["database"] = True
            except Exception as exc:
                errors.append("database:" + type(exc).__name__)
        elif not database_created:
            receipt["cleanup"]["database"] = True
        for path in files:
            path.unlink(missing_ok=True)
        receipt["cleanup"]["secrets"] = True
        receipt["cleanup_errors"] = errors
        write(directory / "auth-receipt.json", receipt)
        if errors:
            raise ReceiptError("Owned Auth cleanup incomplete; retain ownership receipt")
    return receipt


def record_operations(context_path):
    """Both real operational boundaries are required; neither can substitute for the other."""
    value = context_at(context_path)
    directory = Path(value["directory"])
    paths = [directory / "auth-receipt.json", directory / "restore-receipt.json"]
    limitations = []
    cleanup = {}
    for mode, path, verify in zip(
        ("auth", "restore"), paths, (verify_auth_receipt, verify_restore_receipt), strict=True
    ):
        if not path.exists():
            limitations.append(mode + " receipt missing")
            cleanup[mode + ".receipt_available"] = False
            continue
        try:
            receipt = read(path)
            mode_cleanup = receipt.get("cleanup") or {}
            if not mode_cleanup:
                cleanup[mode + ".cleanup_proved"] = False
            for key, done in mode_cleanup.items():
                cleanup[mode + "." + key] = done is True
            if receipt.get("status") != "pass":
                limitations.append(
                    mode + " receipt remains " + str(receipt.get("status", "missing"))
                )
                continue
            verify(receipt)
        except (ReceiptError, KeyError, TypeError, ValueError, AttributeError, OSError) as exc:
            if not any(key.startswith(mode + ".") for key in cleanup):
                cleanup[mode + ".cleanup_proved"] = False
            limitations.append(mode + " receipt incomplete or invalid (" + type(exc).__name__ + ")")
    if limitations:
        return save_gate(
            context_path,
            "G7",
            [p for p in paths if p.exists()],
            status="unverified",
            limitations=limitations,
            cleanup=cleanup,
        )
    return save_gate(
        context_path,
        "G7",
        paths,
        status="pass",
        limitations=["Private Windows owned fixture; not public deployment proof"],
        cleanup={"auth": True, "restore": True},
    )


def record_provider_review(context_path, review_path):
    value = context_at(context_path)
    directory = Path(value["directory"])
    model = directory / "provider-receipt.json"
    review = directory / "provider-semantic-review.json"
    if review.exists():
        raise ReceiptError("Preserve the previous semantic review; do not overwrite")
    shutil.copyfile(review_path, review)
    probe = {"status": "pass", "evidence": [reference(model), reference(review)]}
    verify_raw_gate("G6", probe)
    return save_gate(
        context_path,
        "G6",
        [model, review],
        status="pass",
        limitations=["One synthetic-context model sample; not market/economic proof"],
        cleanup={"gateway_returned": True},
    )


def merge_contexts(context_path, others):
    """Assemble separately owned G5/G6/G7 runs only when relevant source/config still matches."""
    value = context_at(context_path)
    for other_path in others:
        other = context_at(other_path)
        for gate, record in other.get("gates", {}).items():
            if gate in {"G1", "G2", "G3", "G4"}:
                raise ReceiptError("Fixed cycle gates cannot be replaced by another run")
            if gate in value["gates"] and value["gates"][gate] != record:
                raise ReceiptError("Existing gate cannot silently be replaced")
            value["gates"][gate] = record
    write(context_path, value)
    return value


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    for name in (
        "prepare",
        "run",
        "provider-diagnosis",
        "provider",
        "auth",
        "restore",
        "assemble",
        "check-receipt",
        "capture-integration",
        "auth-child",
        "provider-review",
        "ui-evidence",
    ):
        mode.add_argument("--" + name, type=Path)
    mode.add_argument("--child", action="store_true")
    mode.add_argument("--cleanup-storage")
    parser.add_argument("--port", type=int, default=8758)
    parser.add_argument("--auth-port", type=int, default=8759)
    parser.add_argument("--timeout", type=int, default=240)
    parser.add_argument("--env-file")  # Existing lifecycle child cleanup interface.
    parser.add_argument("--context", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--include-context", type=Path, action="append", default=[])
    parser.add_argument("--ui-manifests", type=Path)
    parser.add_argument("--semantic-review", type=Path)
    parser.add_argument("--pg-container", default="supabase_db_marketing")
    parser.add_argument("--pre-integration", action="store_true")
    parser.add_argument("--cli-result", type=Path)
    parser.add_argument("--integration-log", type=Path)
    parser.add_argument("--exit-code", type=int)
    parser.add_argument("--started-ms", type=int)
    parser.add_argument("--finished-ms", type=int)
    args = parser.parse_args()
    try:
        if args.child:
            if args.context is None:
                raise ReceiptError("Owned child context is required")
            first_release_child(args.context, args.port)
            return
        if args.cleanup_storage:
            if not re.fullmatch(r"org_f13_runtime_[a-f0-9]{12}", args.cleanup_storage):
                raise ReceiptError("Invalid owned Storage cleanup prefix")
            import pytest  # noqa: F401 -- prevent dotenv from another checkout

            from app import storage

            storage.delete_prefix(org_id=args.cleanup_storage, prefix=args.cleanup_storage + "/")
            return
        if args.auth_child:
            auth_child(args.auth_child, args.port)
            return
        if args.prepare:
            result = prepare(args.prepare)
        elif args.run:
            result = run_cycle(args.run, args.port, args.timeout)
        elif args.provider_diagnosis:
            result = diagnose_provider(args.provider_diagnosis)
        elif args.provider:
            result = run_provider(args.provider)
        elif args.auth:
            auth_probe(args.auth, args.auth_port, args.port)
            result = record_operations(args.auth)
        elif args.restore:
            restore_probe(args.restore, args.pg_container)
            result = record_operations(args.restore)
        elif args.provider_review:
            if not args.semantic_review:
                raise ReceiptError("Explicit independent semantic review is required")
            result = record_provider_review(args.provider_review, args.semantic_review)
        elif args.ui_evidence:
            if not args.ui_manifests:
                raise ReceiptError("Three explicit source/build UI manifests are required")
            result = ui_evidence(args.ui_evidence, read(args.ui_manifests))
        elif args.assemble:
            if not args.output:
                raise ReceiptError("Explicit scoped output is required")
            merge_contexts(args.assemble, args.include_context)
            result = assemble(args.assemble, args.output)
        elif args.capture_integration:
            if any(
                v is None
                for v in (
                    args.cli_result,
                    args.integration_log,
                    args.exit_code,
                    args.started_ms,
                    args.finished_ms,
                )
            ):
                raise ReceiptError("Actual completed CLI/log/exit/start/end are required")
            result = capture_integration(
                args.capture_integration,
                args.cli_result,
                args.integration_log,
                exit_code=args.exit_code,
                started_ms=args.started_ms,
                finished_ms=args.finished_ms,
            )
        else:
            result = check_receipt(args.check_receipt, pre_integration=args.pre_integration)
            if not args.pre_integration:
                write(ROOT / ".harness/scratch/F53/final/combined-seal.json", result)
        print(json.dumps(result, ensure_ascii=False, default=str))
    except Exception as exc:
        # Never echo raw provider/HTTP/subprocess error strings: they may contain credentials.
        print(
            json.dumps(
                {
                    "status": "unverified",
                    "error_type": type(exc).__name__,
                    "reason": str(exc)
                    if isinstance(exc, ReceiptError)
                    else "Inspect the owned preserved receipt/log; no retry was started.",
                }
            )
        )
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
