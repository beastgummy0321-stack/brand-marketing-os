"""Phase D lifecycle: real PostgreSQL queue, separate web and app.worker processes."""

from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import tempfile
import time
import uuid
from datetime import date, timedelta
from pathlib import Path
from urllib.parse import urlparse

import httpx
import jwt
import psycopg
from psycopg.conninfo import conninfo_to_dict, make_conninfo
from psycopg.rows import dict_row

from app.tests.fixtures.ads_external import runtime as fixture
from app.tests.fixtures.ads_external.worker_runtime import events
from scripts import verify_ads_cycle_evidence as evidence
from scripts import verify_existing_campaigns_assets as lifecycle

ROOT = Path(__file__).resolve().parents[1]
ENTRY = ROOT / "scripts/verify_ads_cycle.py"


class Runtime:
    def __init__(self, args):
        self.args = args
        self.started = time.monotonic()
        self.web = None
        self.worker = None
        self.processes = []
        self.process_keys = {}
        self.logs = []
        self.admin_dsn = None
        self.scoped_dsn = None
        self.client = None
        self.directory = (
            Path(args.context).resolve().parent
            if args.context
            else Path(tempfile.mkdtemp(prefix="f15-d-"))
        )
        self.directory.mkdir(parents=True, exist_ok=True)
        self.context_path = (
            Path(args.context).resolve() if args.context else self.directory / "context.json"
        )
        schema = "f13_runtime_" + uuid.uuid4().hex[:12]
        self.context = {
            "phase": "D",
            "schema": schema,
            "org_id": "org_" + schema,
            "brand_id": "brd_" + schema,
            "second_brand_id": "brd_other_" + schema,
            "brand_ids": ["brd_" + schema, "brd_other_" + schema],
            "base_url": f"http://127.0.0.1:{args.port}",
            "evidence_dir": str(self.directory),
            "state_file": str(self.directory / "source-state.json"),
            "events_file": str(self.directory / "events.jsonl"),
            "media_paths": {},
            "primary_platform": "meta",
            "primary_account_id": fixture.FIXTURE["accounts"][0],
        }
        self.values = lifecycle.safe_env(args)
        params = conninfo_to_dict(self.values["DATABASE_URL"])
        if params.get("host") not in {"127.0.0.1", "localhost", "::1"} or not params.get(
            "dbname", ""
        ).startswith("f15_validation_"):
            raise RuntimeError("D requires a dedicated local F15 validation database")
        if urlparse(self.values.get("SUPABASE_URL", "")).hostname not in {"localhost", "127.0.0.1"}:
            raise RuntimeError("D requires local Supabase")
        params.pop("options", None)
        self.admin_dsn = make_conninfo(**params)
        self.env = {
            key: value
            for key, value in os.environ.items()
            if not any(
                part in key.upper()
                for part in ("API_KEY", "TOKEN", "SECRET", "DATABASE_URL", "BRAND_OS_LLM_PROVIDER")
            )
        }
        self.env.update(self.values)
        self.env.update(
            BRAND_OS_ENV="local",
            BRAND_OS_JOB_QUEUE="",
            BRAND_OS_LLM_PROVIDER="scripted",
            IDENTITY_DEV_TOKEN="",
            IDENTITY_ALLOW_HS256="1",
            PYTHONUTF8="1",
            F15_ACCEPTANCE_PHASE="D",
        )

    def remaining(self):
        value = self.args.timeout - (time.monotonic() - self.started)
        if value <= 0:
            raise TimeoutError("D runtime exceeded bounded deadline")
        return min(value, 15)

    def wait(self, condition, label):
        while True:
            value = condition()
            if value:
                return value
            self.remaining()
            time.sleep(0.05)

    def persist(self):
        fixture.write_json(self.context_path, self.context)

    def setup(self):
        with socket.socket() as port:
            port.bind(("127.0.0.1", self.args.port))
        self.admin_dsn, self.scoped_dsn, user = lifecycle.create_schema(
            self.values,
            self.context["schema"],
            self.context["org_id"],
            self.context["brand_ids"],
            self.remaining,
        )
        self.env["DATABASE_URL"] = self.scoped_dsn
        fixture.write_json(
            self.context["state_file"], {"creative_revision": 1, "fail_next": False, "gate": None}
        )
        Path(self.context["events_file"]).write_text("", encoding="utf-8")
        self.persist()
        token = jwt.encode(
            {
                "sub": user,
                "email": "123@example.com",
                "aud": "authenticated",
                "exp": int(time.time()) + 7200,
            },
            self.values["SUPABASE_JWT_SECRET"],
            algorithm="HS256",
        )
        self.client = httpx.Client(
            base_url=self.context["base_url"],
            headers={"Authorization": "Bearer " + token, "X-Org-Id": self.context["org_id"]},
        )
        self.start_web()

    def spawn(self, kind, *, drain=False):
        process_key = f"{kind}-{len(self.processes)}"
        log = open(self.directory / f"{kind}-{len(self.processes)}.log", "w", encoding="utf-8")
        self.logs.append(log)
        command = [
            sys.executable,
            str(ENTRY),
            "--phase",
            "D",
            "--context",
            str(self.context_path),
            "--port",
            str(self.args.port),
            "--worker" if kind == "worker" else "--child",
        ]
        if drain:
            command.append("--drain")
        proc = subprocess.Popen(
            command,
            cwd=ROOT,
            env={**self.env, "F15_PROCESS_KEY": process_key},
            stdin=subprocess.DEVNULL,
            stdout=log,
            stderr=log,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        self.processes.append(proc)
        self.process_keys[proc.pid] = process_key
        return proc

    def start_web(self):
        self.persist()
        self.web = self.spawn("web")

        def ready():
            if self.web.poll() is not None:
                raise RuntimeError("D web exited; inspect owned web log")
            try:
                return (
                    httpx.get(self.context["base_url"] + "/__f13/state", timeout=0.5).status_code
                    == 200
                )
            except httpx.HTTPError:
                return False

        self.wait(ready, "web ready")

    def stop_web(self):
        if self.web is None or self.web.poll() is not None:
            return
        try:
            httpx.post(self.context["base_url"] + "/__f13/stop", timeout=2)
            self.web.wait(timeout=10)
        except (httpx.HTTPError, subprocess.TimeoutExpired):
            self.stop_owned(self.web)

    def stop_owned(self, proc):
        if proc is None or proc.poll() is not None:
            return
        if os.name == "nt":
            # Windows venv python.exe may be a redirector with a distinct worker
            # child PID. End the complete owned tree, not just that launcher.
            subprocess.run(
                ["taskkill", "/PID", str(proc.pid), "/T", "/F"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=10,
                check=True,
            )
            proc.wait(timeout=5)
        else:
            lifecycle.stop_process(proc)

    def start_worker(self, *, drain=False):
        self.worker = self.spawn("worker", drain=drain)
        return self.worker

    def drain(self):
        # Use the production long-lived worker. Procrastinate's wait=False empty
        # queue path can leave its periodic loop alive on Windows.
        proc = self.start_worker()

        def started():
            if proc.poll() is not None:
                raise RuntimeError("D worker exited before its real queue loop")
            return any(
                row["kind"] == "worker_loop" and row["process_key"] == self.process_keys[proc.pid]
                for row in events(self.context)
            )

        self.wait(started, "worker bootstrap and loop")
        stable = 0

        def idle():
            nonlocal stable
            if proc.poll() is not None:
                raise RuntimeError("D worker exited while processing queue")
            active = any(row["status"] in {"todo", "doing"} for row in self.queue_rows())
            stable = 0 if active else stable + 1
            return stable >= 3

        self.wait(idle, "durable queue idle")
        self.stop_owned(proc)

    def kill_worker(self):
        assert self.worker is not None and self.worker.poll() is None
        self.stop_owned(self.worker)

    def state(self, **values):
        state = fixture.read_json(self.context["state_file"])
        fixture.write_json(self.context["state_file"], {**state, **values})

    def call(self, method, path, **kwargs):
        response = self.client.request(method, path, timeout=self.remaining(), **kwargs)
        if response.is_error:
            raise AssertionError(f"{method} {path}: {response.status_code} {response.text}")
        return response.json()

    def query(self, sql, args=()):
        if not sql.lstrip().upper().startswith("SELECT"):
            raise RuntimeError("Runtime evidence queries must be read only")
        with psycopg.connect(self.scoped_dsn, row_factory=dict_row, connect_timeout=5) as conn:
            conn.execute("SET statement_timeout='5s'")
            return conn.execute(sql, args).fetchall()

    def queue_rows(self):
        return self.query(
            "SELECT id,task_name,status,args,queueing_lock FROM "
            f'"{self.context["schema"]}__queue".procrastinate_jobs ORDER BY id'
        )

    def count_calls(self):
        return sum(row["kind"] == "provider_call" for row in events(self.context))

    def wait_gate(self, name, start):
        return self.wait(
            lambda: next(
                (
                    row
                    for row in events(self.context)[start:]
                    if row["kind"] == "gate" and row["name"] == name
                ),
                None,
            ),
            name,
        )

    def cleanup(self):
        self.stop_web()
        for proc in self.processes:
            self.stop_owned(proc)
        if self.client is not None:
            self.client.close()
        for log in self.logs:
            log.close()
        result = {
            "process_stopped": all(proc.poll() is not None for proc in self.processes),
            "storage": False,
            "schema": False,
            "fixture_media": True,
            "errors": [],
        }
        try:
            subprocess.run(
                [sys.executable, str(ENTRY), "--cleanup-storage", self.context["org_id"]],
                cwd=ROOT,
                env=self.env,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=30,
                check=True,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            result["storage"] = True
        except (OSError, subprocess.SubprocessError) as exc:
            result["errors"].append("storage:" + type(exc).__name__)
        try:
            with psycopg.connect(self.admin_dsn, autocommit=True, connect_timeout=5) as conn:
                conn.execute("SET statement_timeout='30s'")
                conn.execute(
                    f'DROP SCHEMA IF EXISTS "{self.context["schema"]}" CASCADE; '
                    f'DROP SCHEMA IF EXISTS "{self.context["schema"]}__queue" CASCADE'
                )
            result["schema"] = True
        except psycopg.Error as exc:
            result["errors"].append("schema:" + type(exc).__name__)
        for path in self.context["media_paths"].values():
            media = Path(path).resolve()
            if media.parent != self.directory.resolve():
                raise RuntimeError("Refusing cleanup outside owned fixture directory")
            media.unlink(missing_ok=True)
        fixture.write_json(self.directory / "cleanup.json", result)
        if result["errors"]:
            raise RuntimeError("D cleanup failed; inspect cleanup.json")


def source_recovery(run):
    """Queue before worker, close web, then crash worker after a committed page."""
    brand = run.context["brand_id"]
    base = f"/api/ads/brands/{brand}"
    source = {"platform": "meta", "source_account": fixture.FIXTURE["accounts"][0]}
    first = run.call("POST", base + "/existing-campaigns/refresh", json=source)["job"]
    queued = run.queue_rows()
    assert any(
        row["task_name"] == "background.ads_external_sync" and row["status"] == "todo"
        for row in queued
    )
    web_pid = run.web.pid
    run.stop_web()
    run.drain()
    completed = run.query("SELECT status FROM ads_external_sync_job WHERE id=%s", (first["id"],))[0]
    assert completed["status"] == "succeeded"
    assert run.worker.pid != web_pid
    run.start_web()

    run.state(gate="source_page_two")
    second = run.call("POST", base + "/existing-campaigns/refresh", json=source)["job"]
    start = len(events(run.context))
    run.start_worker()
    interrupted = run.wait_gate("source_page_two", start)
    checkpoint = run.query(
        "SELECT tasks,status,revision FROM ads_external_sync_job WHERE id=%s", (second["id"],)
    )[0]
    assert checkpoint["tasks"]["list"]["cursor"] == {"after": "page2"}
    doing = [
        row
        for row in run.queue_rows()
        if row["status"] == "doing" and row["task_name"] == "background.ads_external_sync"
    ]
    assert len(doing) == 1
    second_worker = run.spawn("worker", drain=True)
    run.wait(lambda: second_worker.poll() is not None, "second worker lock refusal")
    assert second_worker.returncode == 0
    assert any(row["id"] == doing[0]["id"] and row["status"] == "doing" for row in run.queue_rows())
    run.kill_worker()
    run.state(gate=None)
    after_crash = len(events(run.context))
    run.drain()
    recovered = run.query("SELECT status FROM ads_external_sync_job WHERE id=%s", (second["id"],))[
        0
    ]
    assert recovered["status"] == "succeeded"
    readbacks = [row for row in events(run.context)[after_crash:] if row["kind"] == "source_page"]
    assert readbacks and readbacks[0]["cursor"] == {"after": "page2"}
    assert readbacks[0]["pid"] != interrupted["pid"], "Resume must use a new real worker PID"
    assert any(
        row["id"] == doing[0]["id"] and row["status"] == "succeeded" for row in run.queue_rows()
    )
    imported = run.call(
        "POST", base + "/imports", json={**source, "native_kind": "campaign", "native_id": "root"}
    )
    run.drain()
    campaign = imported["campaign"]["id"]
    route = base + "/campaigns/" + campaign
    controls = run.call("GET", route + "/change-control")
    ad = next(row for row in controls["targets"] if row["native_kind"] == "ad")
    group = next(row for row in controls["targets"] if row["native_kind"] == "adset")
    run.call(
        "PATCH",
        route,
        json={
            "goal_text": "D隔離恢復與兩輪反證",
            "objective": "購買",
            "success_metric": "roas",
            "success_target": 2,
            "success_basis": "隔離證據門檻",
        },
    )
    run.context.update(
        imported_campaign_id=campaign, ad_entity_id=ad["id"], group_entity_id=group["id"]
    )
    fixture.write_json(
        run.directory / "source-recovery.json",
        {
            "web_closed_job_completed": True,
            "web_pid": web_pid,
            "interrupted_worker_pid": interrupted["pid"],
            "resumed_worker_pid": readbacks[0]["pid"],
            "queue_job_id": doing[0]["id"],
            "saved_cursor": checkpoint["tasks"]["list"]["cursor"],
            "resumed_cursor": readbacks[0]["cursor"],
            "second_worker_no_mutation": True,
        },
    )
    return route


def review_recovery(run, route):
    today = date.today()

    def request(offset):
        return {
            "entity_id": run.context["ad_entity_id"],
            "start": str(today - timedelta(days=14 - offset)),
            "end": str(today - timedelta(days=8 - offset)),
        }

    run.state(gate="saved_output")
    saved = run.call("POST", route + "/reviews", json=request(0))["review"]
    assert saved["status"] == "queued", saved
    start = len(events(run.context))
    run.start_worker()
    output = run.wait_gate("saved_output", start)
    assert output["status"] == "succeeded"
    before = run.count_calls()
    row = run.query("SELECT status,llm_task_id FROM ads_review_round WHERE id=%s", (saved["id"],))[
        0
    ]
    assert row["status"] == "running" and row["llm_task_id"] is None
    run.kill_worker()
    run.state(gate=None)
    run.drain()
    recovered = run.call("GET", route + "/reviews/" + saved["id"])["review"]
    assert recovered["status"] == "ready" and recovered["llm_task_id"] == output["llm_task_id"]
    assert run.count_calls() == before

    run.state(gate="provider_inflight")
    unknown = run.call("POST", route + "/reviews", json=request(1))["review"]
    start = len(events(run.context))
    run.start_worker()
    run.wait_gate("provider_inflight", start)
    before_unknown = run.count_calls()
    run.kill_worker()
    run.state(gate=None)
    run.drain()
    unknown = run.call("GET", route + "/reviews/" + unknown["id"])["review"]
    assert unknown["status"] == "unknown"
    assert unknown["reservation_state"] == "held"
    run.drain()
    assert run.count_calls() == before_unknown

    run.state(gate="enqueue_gap")
    try:
        run.call("POST", route + "/reviews", json=request(2))
        raise AssertionError("Expected web process loss before enqueue")
    except httpx.TransportError:
        pass
    run.wait(lambda: run.web.poll() is not None, "web enqueue-gap exit")
    gap = next(row for row in reversed(events(run.context)) if row["kind"] == "enqueue_gap")
    assert not any(row["args"].get("review_id") == gap["review_id"] for row in run.queue_rows())
    run.state(gate=None)
    run.start_web()
    before_gap = run.count_calls()
    run.drain()
    gap_review = run.call("GET", route + "/reviews/" + gap["review_id"])["review"]
    assert gap_review["status"] == "ready"
    assert run.count_calls() == before_gap + 1
    run.context.update(
        first_review_id=saved["id"],
        unknown_review_id=unknown["id"],
        recovered_gap_review_id=gap_review["id"],
    )
    fixture.write_json(
        run.directory / "review-recovery.json",
        {
            "saved_output_recovered_zero_calls": True,
            "llm_task_id": output["llm_task_id"],
            "unknown_not_resent": True,
            "enqueue_gap_recovered_once": True,
            "first": recovered,
            "unknown": unknown,
            "gap": gap_review,
        },
    )


def main(args):
    if not args.isolated:
        raise RuntimeError("--isolated is required")
    run = Runtime(args)
    try:
        run.setup()
        route = source_recovery(run)
        evidence.import_commerce(run)
        review_recovery(run, route)
        evidence.new_test_source(run, route)
        evidence.monitor_conditions(run, route)
        evidence.next_round(run, route)
        run.persist()
        result = {
            "ok": True,
            "phase": "D",
            "queue": "postgresql",
            "worker_entry": "app.worker.main",
            "provider_calls": run.count_calls(),
            "web_closed_job_completed": True,
            "different_worker_resumed_saved_cursor": True,
            "saved_output_recovered_zero_calls": True,
            "unknown_inflight_not_resent": True,
            "enqueue_gap_recovered_once": True,
            "deferred_revisited_once": True,
            "unchanged_waiting_zero_calls": True,
            "commerce_counterevidence_preserved": True,
            "B2_source_review_distinct_from_previous": True,
            "elapsed_seconds": round(time.monotonic() - run.started, 2),
            "context_path": str(run.context_path),
        }
        fixture.write_json(run.directory / "runtime-result.json", result)
        fixture.write_json(run.directory / "queue-evidence.json", run.queue_rows())
        print(json.dumps(result), flush=True)
    finally:
        run.cleanup()
