"""Bounded F53 tooling. Run through Harness; receipt checks never execute a probe.

Modes: --prepare, --run, --provider-diagnosis, --provider, --auth, --restore,
--assemble, --capture-integration, --check-receipt [--pre-integration].
Every execution uses a fresh ignored owned directory, freezes inputs before work,
and preserves failed evidence. Synthetic source/contract proof is never market proof.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
import uuid
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from scripts.drill import first_release_cases as cases  # noqa: E402

GLOBAL_BOOTSTRAPS = {
    "20260830000002_core_storage_assets_bucket.sql":
        "ca11be1800f6d3e0f7301be55d1455454bafcad929d46e3f081571dcc06573bd",
    "20260905000001_core_storage_assets_bucket_size_limit.sql":
        "1b9839f2e3121c744566142991464d7476947bbf611d9fe84e9f7657e7651e50",
}
PROTECTED_PORTS = {8710, 8720, 8764}
GATES = tuple(f"G{n}" for n in range(1, 8))
PROBE_PATHS = ["scripts/drill/first_release_acceptance.py", "scripts/drill/first_release_cases.py",
               "scripts/drill/recovery_probe.py", "scripts/drill/serve.py",
               "scripts/drill/clock.py", "scripts/verify_existing_campaigns_assets.py",
               "scripts/verify_ads_cycle.py"]
CONFIG_KEYS = ("BRAND_OS_ENV", "BRAND_OS_LLM_PROVIDER", "IDENTITY_ALLOW_HS256",
               "SUPABASE_URL", "VITE_SUPABASE_URL", "VITE_SUPABASE_ANON_KEY",
               "SUPABASE_ANON_KEY", "SUPABASE_SERVICE_ROLE_KEY", "SUPABASE_JWT_SECRET",
               "DATABASE_URL", "BRAND_OS_JOB_QUEUE", "IDENTITY_DEV_TOKEN")


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
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2, default=str) + "\n",
                         encoding="utf-8")
    temporary.replace(path)


def command(argv, *, cwd=ROOT, timeout=15, env=None, input=None):
    return subprocess.run(argv, cwd=cwd, timeout=timeout, env=env, input=input,
                          capture_output=True,
                          creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0), check=False)


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


def relevant_hashes(root=ROOT, environment=None):
    paths = [p for p in git(root, "ls-files", "-z").decode().split("\0") if p]
    environment = os.environ if environment is None else environment
    product = [p for p in paths if p.startswith(("app/ads/", "app/workbench/", "app/core/",
               "app/identity/", "app/llm/", "app/storage/", "app/brand_intelligence/",
               "supabase/migrations/", "frontend/src/", "frontend/package"))
               and not p.endswith((".test.ts", ".test.tsx"))]
    return {"product": fingerprint(root, product), "probe": fingerprint(root, PROBE_PATHS),
            "runtime_config": cases.digest({k: sha(environment.get(k, "").encode())
                                            for k in CONFIG_KEYS})}


def integration_signature(root=ROOT):
    value = hashlib.sha256()
    value.update(source_fingerprint(root).encode())
    value.update(git(root, "rev-parse", "HEAD").strip())
    feature = Path(root) / ".work/features/F53.md"
    value.update(feature.read_bytes())
    inputs = {"head": git(root, "rev-parse", "HEAD").decode().strip(),
              "source": source_fingerprint(root), "feature_sha256": sha(feature.read_bytes()),
              "issues": []}
    for state in ("ready", "doing", "blocked", "done"):
        for path in sorted((Path(root) / ".work" / state).glob("F53-*.md")):
            identity = path.stem
            value.update((state + identity).encode())
            value.update(path.read_bytes())
            inputs["issues"].append({"state": state, "id": identity,
                                     "sha256": sha(path.read_bytes())})
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
        sql = re.sub(r"--[^\n]*", "", raw.decode("utf-8"))
        if re.search(r"\b(?:INSERT\s+INTO|UPDATE|DELETE\s+FROM|ALTER\s+TABLE|DROP\s+TABLE|"
                     r"CREATE\s+TABLE)\s+(?:public|auth|storage)\s*\.", sql, re.I):
            raise ReceiptError("Unapproved global migration write: " + path.name)
        included.append({"path": path.name, "sha256": sha(raw)})
    return {"included": included, "skipped_global_bootstraps": skipped}


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
    context = {"schema_version": 1, "feature": "F53", "run_id": uuid.uuid4().hex,
               "created_at": now(), "directory": str(directory), "nonce": uuid.uuid4().hex,
               "cases": reference(cases.CASES), "expectations_hash": cases.digest(value),
               "hashes": relevant_hashes(), "migration_audit": migration_audit(),
               "provenance": "synthetic-fixtures-not-market-results", "processes": [],
               "resources": [], "gates": {}, "human_acceptance": "pending"}
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
    record = {"status": status, "evidence": [reference(p) for p in evidence],
              "finished_at": now(), "hashes": value["hashes"],
              "limitations": limitations, "cleanup": cleanup, "run_id": value["run_id"]}
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
        return {"machine": "G1-G7 verified", "G8": "pending actual integration",
                "human": packet.get("human_acceptance", "pending"), "release_eligible": False}
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
    if seal.get("hashes") != current or seal.get("packet") != reference(path):
        raise ReceiptError("Integration capture source/config/packet changed")
    if not (seal["started_ms"] <= runtime["at"] <= seal["finished_ms"]):
        raise ReceiptError("Runtime stamp is outside the captured integration run")
    if not log or not cli.get("steps"):
        raise ReceiptError("Actual integration log/steps absent")
    expected = seal.get("required_steps")
    actual = {step["step"] for step in cli["steps"] if step.get("ok") is True}
    if not expected or set(expected) - actual or any(s.get("ok") is not True for s in cli["steps"]):
        raise ReceiptError("Required actual integration steps missing or failed")
    return {"machine": "G1-G8 verified", "signature": signature, "pre_close_inputs": inputs,
            "human": packet.get("human_acceptance", "pending"), "release_eligible": False,
            "F48_F52": "open; original F52 drill remains paused"}
