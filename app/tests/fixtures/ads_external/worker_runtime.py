"""Cross-process D replacements: fake sources/providers, real queue and worker.

Failure gates pause real execution at durable boundaries. The parent terminates
the owned process; no fixture writes a successful domain or queue state.
"""

from __future__ import annotations

import json
import os
import socket
import time
from pathlib import Path

from app.tests.fixtures.ads_external import runtime


def events(context):
    path = Path(context["events_file"])
    if not path.exists():
        return []
    rows = []
    for line in path.read_text("utf-8").splitlines():
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            continue  # A concurrently appended final line is read on the next poll.
    return rows


def event(context, kind, **values):
    row = {
        "kind": kind,
        "pid": os.getpid(),
        "process_key": os.environ.get("F15_PROCESS_KEY"),
        "time": time.time(),
        **values,
    }
    encoded = (json.dumps(row, ensure_ascii=False) + "\n").encode("utf-8")
    descriptor = os.open(context["events_file"], os.O_CREAT | os.O_APPEND | os.O_WRONLY, 0o600)
    try:
        os.write(descriptor, encoded)
    finally:
        os.close(descriptor)


def gate(context, name, **values):
    if runtime.read_json(context["state_file"]).get("gate") != name:
        return
    event(context, "gate", name=name, **values)
    until = time.monotonic() + 120
    while runtime.read_json(context["state_file"]).get("gate") == name:
        if time.monotonic() >= until:
            raise TimeoutError("Bounded fixture gate was not released")
        time.sleep(0.05)


def install(context):
    from app import background
    from app.ads import channels
    from app.ads.adapters.external import SourcePage
    from app.llm import gateway, providers
    from app.tests.fixtures.ads_external.cycle_reader import CycleReader

    stats = runtime.install_assembly(context, durable=True)
    original_connect = socket.socket.connect

    def local_connect(sock, address):
        if isinstance(address, tuple) and address[0] not in {"localhost", "127.0.0.1", "::1"}:
            event(context, "blocked_external")
            raise RuntimeError("D fixture permits only loopback transport")
        return original_connect(sock, address)

    socket.socket.connect = local_connect

    class Reader(CycleReader):
        def node(self, account, native_id, kind, **fields):
            row = super().node(account, native_id, kind, **fields)
            if native_id in {"root-ad", "B2"}:
                row["name"] = "隔離原廣告 B" if native_id == "root-ad" else "隔離新廣告 B2"
            return row

        def accounts(self, *args):
            return super().accounts(*args)[:1] if self.platform == "meta" else []

        def list_existing(self, conn, org, brand, account, *, cursor=None, **kwargs):
            event(context, "source_page", section="list", cursor=cursor)
            if cursor:
                gate(context, "source_page_two", cursor=cursor)
                return SourcePage([])
            page = super().list_existing(conn, org, brand, account, cursor=None, **kwargs)
            page.cursor = {"after": "page2"}
            return page

        def read_observations(self, *args, **kwargs):
            state = self.state()
            page = super().read_observations(*args, **kwargs)
            if state.get("missing_observations"):
                page.items = []
            return page

    channels.external_reader = lambda platform: (
        Reader(context, platform) if platform == "meta" else None
    )
    original_select = providers.select_provider

    class RecordedProvider:
        def __init__(self, wrapped, task_type):
            self.wrapped, self.task_type = wrapped, task_type
            self.name = wrapped.name

        def complete(self, **kwargs):
            event(context, "provider_call", task_type=self.task_type)
            gate(context, "provider_inflight", task_type=self.task_type)
            response = self.wrapped.complete(**kwargs)
            event(context, "provider_return", task_type=self.task_type)
            return response

    providers.select_provider = lambda provider, task_type=None: RecordedProvider(
        original_select(provider, task_type=task_type), task_type
    )
    original_run = gateway.run_task

    def run_task(*args, **kwargs):
        task = original_run(*args, **kwargs)
        if kwargs.get("task_type") == "ads_ad_review":
            gate(context, "saved_output", llm_task_id=task["id"], status=task["status"])
        return task

    gateway.run_task = run_task
    original_enqueue = background.enqueue

    def enqueue(task_name, *, org_id, lock, **kwargs):
        if org_id != context["org_id"]:
            raise RuntimeError("Unexpected tenant in D isolated queue")
        if (
            task_name == "background.ads_review_round"
            and runtime.read_json(context["state_file"]).get("gate") == "enqueue_gap"
        ):
            event(context, "enqueue_gap", review_id=kwargs["review_id"])
            os._exit(71)  # Real process loss after review commit, before durable defer.
        result = original_enqueue(task_name, org_id=org_id, lock=lock, **kwargs)
        event(context, "enqueue", task=task_name, lock=lock, accepted=result)
        return result

    background.enqueue = enqueue
    event(context, "assembly_ready", queue="postgresql")
    return stats


def child(args):
    context = runtime.read_json(args.context)
    stats = install(context)
    if args.worker:
        from app import background, worker

        queue_app = background.app()
        original_worker = queue_app.run_worker

        def run_worker(**kwargs):
            event(context, "worker_loop", wait=kwargs.get("wait"))
            return original_worker(**kwargs)

        queue_app.run_worker = run_worker

        event(context, "worker_start")
        worker.main(wait=not args.drain)
        event(context, "worker_stop")
        return

    import uvicorn

    from app.main import app

    server = uvicorn.Server(
        uvicorn.Config(app, host="127.0.0.1", port=args.port, log_level="warning", access_log=False)
    )

    @app.get("/__f13/state")
    def state():
        rows = events(context)
        return {
            **runtime.read_json(context["state_file"]),
            **stats,
            "provider_calls": sum(row["kind"] == "provider_call" for row in rows),
            "queue": "postgresql",
            "web_pid": os.getpid(),
        }

    @app.post("/__f13/stop")
    def stop():
        server.should_exit = True
        return {"stopping": True}

    server.run()
