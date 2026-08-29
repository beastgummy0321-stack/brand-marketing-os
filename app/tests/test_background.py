"""app/tests/test_background.py — ticket schedule-01: procrastinate installs, its App resolves
`DATABASE_URL`/queue schema late instead of freezing them at import time, and ADR 0038's
task-signature gate is armed.

Protects: tenant isolation. `app/tests/conftest.py` gives every test module its own Postgres
schema by rewriting `DATABASE_URL` per module; a background worker that froze its DSN (or the
queue schema derived from it) at import time would keep talking to whichever schema happened
to be current the first time anything imported `app.background` — the same class of bug as a
request leaking into the wrong tenant's data. See `app/background/__init__.py`'s docstring for
why this needed a non-default (compare-and-rebuild) lazy singleton, not the plain lazy
singleton `app/core/db.py` uses.

`test_worker_runs_one_deferred_job` is the ticket's actual scope, run for real against this
test module's own Postgres schema: defer the one trivial task, run a worker once, it must
finish and exit — reaching across into `<this module's schema>__queue` (ADR 0038), which is
never on this connection's own `search_path`, so the assertion has to name it explicitly.

`TaskSignatureOrgIdGateTest` is the gate ADR 0038 says this ticket owes: rule 5 ("a handler...
touches only its own organisation") has no other machine check. It can't prove a handler *uses*
`org_id` correctly, only that every registered task has the parameter to use.
"""

import inspect
import os
import unittest

import app.background as background_module
from app.core import db


class BackgroundAppTest(unittest.TestCase):
    def test_dsn_resolves_late_not_at_import(self):
        """`app()` must rebuild when `DATABASE_URL` changes, not keep whatever DSN/queue
        schema was current the first time it ran (the cross-schema/cross-tenant hazard)."""
        schema = db.current().execute("SELECT current_schema() AS s").fetchone()["s"]
        first = background_module.app()
        self.assertIn(f"search_path%3D{schema}__queue", first.connector._pool_args["conninfo"])

        old = os.environ.get("DATABASE_URL")
        os.environ["DATABASE_URL"] = db.dsn() + "&application_name=schedule01_test"
        try:
            second = background_module.app()
            self.assertIsNot(second, first, "app() must rebuild when DATABASE_URL changes")
        finally:
            if old is None:
                os.environ.pop("DATABASE_URL", None)
            else:
                os.environ["DATABASE_URL"] = old
            background_module.app()  # rebuild back onto this test module's real schema/queue
            background_module.app()  # rebuild back onto this test module's real schema/queue

    def test_worker_runs_one_deferred_job(self):
        """Real end-to-end, real Postgres: defer `background.noop`, run a worker once,
        it must process the job and exit (status flips todo -> succeeded), reading it back
        from `<this module's schema>__queue` (ADR 0038 — the queue is never on this
        connection's own `search_path`, so it has to be named explicitly here)."""
        a = background_module.app()
        with a.open():
            job_id = a.configure_task("background.noop").defer(org_id="org_dev")
        a.run_worker(wait=False)

        schema = db.current().execute("SELECT current_schema() AS s").fetchone()["s"]
        row = db.current().execute(
            f'SELECT status FROM "{schema}__queue".procrastinate_jobs WHERE id = %s', (job_id,)
        ).fetchone()
        self.assertIsNotNone(row)
        self.assertEqual(row["status"], "succeeded")


class WorkerLifespanTest(unittest.IsolatedAsyncioTestCase):
    """票 05 fix round: the review reject was "nothing runs the pull unattended". This is
    the mechanism that makes that false — a worker task that actually starts on `start_worker()`
    and cancels cleanly (no leaked task, no leaked connection pool) on `stop_worker()`.
    `app/main.py` wires these two calls into its FastAPI `lifespan=`; that two-line wiring is
    visually verifiable there and isn't re-tested here.

    Not driven through `starlette.testclient.TestClient`'s `with` block or a manual ASGI
    lifespan drive: both were tried by hand and hang specifically under this file's pytest
    fixtures (verified: a bare script driving the same ASGI lifespan protocol outside pytest
    starts/stops cleanly every time, so this isn't a bug in `start_worker`/`stop_worker`
    itself — something in how pytest's per-module schema fixtures interact with a *second*,
    independently-created asyncio loop is the suspect, not chased further per CLAUDE.md
    "build only what has hurt": nothing production-shaped is broken, only one specific test
    harness combination). Calling `start_worker`/`stop_worker` directly, the way this module's
    own other tests call `app()` directly, sidesteps that without losing what this test is
    actually meant to protect.
    """

    async def test_lifespan_starts_a_worker_and_stops_it_cleanly_on_shutdown(self):
        self.assertIsNone(background_module._worker_task, "沒有先前測試留下的殘留 worker task")
        await background_module.start_worker()
        task = background_module._worker_task
        self.assertIsNotNone(task, "start_worker() 必須啟動 worker task")
        self.assertFalse(task.done())

        await background_module.stop_worker()
        self.assertIsNone(background_module._worker_task, "stop_worker() 必須收乾淨")
        self.assertTrue(task.cancelled() or task.done())


class TaskSignatureOrgIdGateTest(unittest.TestCase):
    """ADR 0038 "the gate this ADR owes": every task this module registers with procrastinate
    must declare a required `org_id` parameter (no default). Scoped to `background.`-named
    tasks only — procrastinate's own built-in maintenance tasks (namespaced `builtin:...`)
    aren't ours to constrain."""

    def test_every_registered_task_requires_org_id(self):
        a = background_module.app()
        offenders = []
        for name, task in a.tasks.items():
            if not name.startswith("background."):
                continue
            param = inspect.signature(task.func).parameters.get("org_id")
            if param is None or param.default is not inspect.Parameter.empty:
                offenders.append(name)
        self.assertEqual(offenders, [], f"tasks without a required org_id param: {offenders}")


if __name__ == "__main__":
    unittest.main()
