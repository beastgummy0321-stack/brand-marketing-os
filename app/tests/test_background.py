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
from contextlib import contextmanager
from datetime import timedelta
from unittest import mock

import psycopg
from procrastinate import manager
from procrastinate.exceptions import AppNotOpen
from procrastinate.jobs import Status
from psycopg.conninfo import conninfo_to_dict, make_conninfo

import app.background as background_module
from app.background.recovery import FAILED_TASKS
from app.core import config, db
from app.llm import gateway


class BackgroundAppTest(unittest.TestCase):
    def test_dsn_resolves_late_not_at_import(self):
        """`app()` must rebuild when `DATABASE_URL` changes, not keep whatever DSN/queue
        schema was current the first time it ran (the cross-schema/cross-tenant hazard)."""
        schema = db.current().execute("SELECT current_schema() AS s").fetchone()["s"]
        first = background_module.app()
        self.assertIn(
            f'search_path="{schema}__queue"',
            conninfo_to_dict(first.connector._pool_args["conninfo"])["options"],
        )

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
        row = (
            db.current()
            .execute(
                f'SELECT status FROM "{schema}__queue".procrastinate_jobs WHERE id = %s', (job_id,)
            )
            .fetchone()
        )
        self.assertIsNotNone(row)
        self.assertEqual(row["status"], "succeeded")


class WorkerProcessTest(unittest.TestCase):
    """ADR 0063: `python -m app.worker` is the only thing that runs jobs now — this drives the
    real entry point (`app.worker.main`), not a copy of it, against the two things that used to
    be `app/main.py`'s job: draining the queue, and sweeping `llm_task` rows a dead process left
    `running` before the worker takes its first job (see `app/llm/gateway.py`
    `fail_interrupted_tasks()`).

    Contradiction check (ticket 03-worker-own-process): the sweep is unconditional across every
    `running` row, not only the ones a given caller made, so this test creates its own `running`
    row and asserts only on rows it inserted itself. Nothing else in this suite calls
    `worker.main()` today; the day something does, this test stops being safe on its own.

    Round 2 (ADR 0063, amendment "one worker, and the database says so") adds the money case
    the independent review found missing: a second worker process must not mark a *first*
    worker's live, already-paid-for `llm_task` row failed. `test_second_worker_lock_guard_...`
    stands in for "a worker is already running" by taking the schema's advisory lock on a
    separate connection first, then asserts `worker.main()` returns without raising and leaves
    that row exactly as it found it — the sweep must not have run at all.
    """

    def test_worker_drains_the_queue_and_sweeps_interrupted_tasks(self):
        import app.worker  # local import: conftest.py rewrites DATABASE_URL per test module,
        # and app.worker imports app.main — see this module's own docstring for why that
        # can't happen at import time here.

        a = background_module.app()
        with a.open():
            job_id = a.configure_task("background.noop").defer(org_id=db.DEV_ORG_ID)

        task_id = db.new_id("llm")
        db.current().execute(
            "INSERT INTO llm_task (id, org_id, brand_id, task_type, context_scope_json,"
            " input_context_ids_json, input_context_hash, knowledge_item_ids_json,"
            " brand_version, prompt_template_id, prompt_template_version, provider, model,"
            " status, attempt_no, started_at)"
            " VALUES (%s, %s, 'brd_worker_process_test', 'schedule_plan',"
            " '{\"runtime_owner\":\"worker\"}', '[]', '',"
            " '[]', 1, 'p', 'v1', 'seed', 'seed', 'running', 1, %s)",
            (task_id, db.DEV_ORG_ID, db.now_utc()),
        )
        db.current().commit()

        with mock.patch.object(app.worker.ads, "bootstrap_runtime") as bootstrap:
            app.worker.main(wait=False)
        bootstrap.assert_called_once()

        schema = db.current().execute("SELECT current_schema() AS s").fetchone()["s"]
        job_row = (
            db.current()
            .execute(
                f'SELECT status FROM "{schema}__queue".procrastinate_jobs WHERE id = %s', (job_id,)
            )
            .fetchone()
        )
        self.assertIsNotNone(job_row)
        self.assertNotEqual(job_row["status"], "todo", "deferred job must have been picked up")

        task_row = (
            db.current()
            .execute("SELECT status, error FROM llm_task WHERE id = %s", (task_id,))
            .fetchone()
        )
        self.assertEqual(task_row["status"], "failed")
        self.assertEqual(task_row["error"], gateway.INTERRUPTED_TASK_ERROR)

    def test_second_worker_lock_guard_leaves_a_live_running_row_alone(self):
        """Money (round 2, ADR 0063 amendment): a second worker process must not sweep while a
        first worker already holds this schema's advisory lock. `lock_conn` stands in for the
        first worker; `db.current()`'s connection (bound by `_bound_connection`) and the
        connection `app.worker.main()` borrows for itself are two more, distinct connections —
        `pg_try_advisory_lock` is per-session, so only `lock_conn` holding it is what matters."""
        import app.worker  # local import: see the test above for why

        schema = db.current().execute("SELECT current_schema() AS s").fetchone()["s"]
        key = app.worker._advisory_lock_key(schema)

        with db.pool().connection() as lock_conn:
            got = lock_conn.execute("SELECT pg_try_advisory_lock(%s)", (key,)).fetchone()[
                "pg_try_advisory_lock"
            ]
            lock_conn.commit()
            self.assertTrue(got, "test setup: this connection must hold the lock first")

            task_id = db.new_id("llm")
            db.current().execute(
                "INSERT INTO llm_task (id, org_id, brand_id, task_type, context_scope_json,"
                " input_context_ids_json, input_context_hash, knowledge_item_ids_json,"
                " brand_version, prompt_template_id, prompt_template_version, provider, model,"
                " status, attempt_no, started_at)"
                " VALUES (%s, %s, 'brd_worker_lock_test', 'schedule_plan',"
                " '{\"runtime_owner\":\"worker\"}', '[]', '',"
                " '[]', 1, 'p', 'v1', 'seed', 'seed', 'running', 1, %s)",
                (task_id, db.DEV_ORG_ID, db.now_utc()),
            )
            db.current().commit()

            with (
                mock.patch.object(background_module, "recover_interrupted_jobs") as recovery,
                mock.patch.object(app.worker.ads, "bootstrap_runtime") as bootstrap,
            ):
                app.worker.main(wait=False)  # must return quietly, not raise
            recovery.assert_not_called()
            bootstrap.assert_not_called()

            task_row = (
                db.current()
                .execute("SELECT status FROM llm_task WHERE id = %s", (task_id,))
                .fetchone()
            )
            self.assertEqual(
                task_row["status"],
                "running",
                "a second worker must not sweep a live, already-paid-for job while the "
                "first worker's lock is held",
            )

            lock_conn.execute("SELECT pg_advisory_unlock(%s)", (key,))
            lock_conn.commit()

    def test_startup_order_and_worker_context_cover_only_execution(self):
        import app.worker

        calls = []

        def recover(**kwargs):
            calls.append("queue")
            return {
                key: []
                for key in (
                    "retried_ids",
                    "failed_ids",
                    "aborted_ids",
                    "deferred_ids",
                )
            }

        @contextmanager
        def execution():
            calls.append("enter")
            try:
                yield
            finally:
                calls.append("exit")

        with (
            mock.patch.object(
                gateway, "fail_interrupted_tasks", side_effect=lambda _: calls.append("llm")
            ),
            mock.patch.object(
                background_module,
                "recover_interrupted_jobs",
                side_effect=recover,
            ),
            mock.patch.object(
                app.worker.ads,
                "bootstrap_runtime",
                side_effect=lambda *a, **k: calls.append("domain"),
            ),
            mock.patch.object(gateway, "worker_execution", execution),
            mock.patch.object(app.worker, "background_app") as queue,
        ):
            queue.return_value.run_worker.side_effect = lambda **k: calls.append("worker")
            app.worker.main(wait=False)
        self.assertEqual(calls, ["llm", "queue", "domain", "enter", "worker", "exit"])

    def test_startup_recovery_continues_past_first_batch_and_stops_when_drained(self):
        import app.worker

        receipts = [
            {"retried_ids": [1], "failed_ids": [], "aborted_ids": [], "deferred_ids": [2]},
            {"retried_ids": [2], "failed_ids": [], "aborted_ids": [], "deferred_ids": []},
        ]
        with mock.patch.object(
            background_module,
            "recover_interrupted_jobs",
            side_effect=receipts,
        ) as recover:
            receipt = app.worker._recover_queue_backlog()
        self.assertEqual(recover.call_args_list, [mock.call(limit=100), mock.call(limit=100)])
        self.assertEqual(receipt["retried_ids"], [1, 2])
        self.assertEqual(receipt["deferred_ids"], [])

    def test_startup_recovery_has_ten_batch_bound_and_reports_backlog(self):
        import app.worker

        receipts = [
            {"retried_ids": [i], "failed_ids": [], "aborted_ids": [], "deferred_ids": [i + 1]}
            for i in range(10)
        ]
        with (
            mock.patch.object(
                background_module, "recover_interrupted_jobs", side_effect=receipts
            ) as recover,
            mock.patch("builtins.print") as report,
        ):
            receipt = app.worker._recover_queue_backlog()
        self.assertEqual(recover.call_count, 10)
        self.assertEqual(receipt["deferred_ids"], [10])
        self.assertIn("未恢復", report.call_args.args[0])

    def test_startup_recovery_stops_on_no_progress(self):
        import app.worker

        empty = {"retried_ids": [], "failed_ids": [], "aborted_ids": [], "deferred_ids": [1]}
        with mock.patch.object(
            background_module,
            "recover_interrupted_jobs",
            return_value=empty,
        ) as recover:
            receipt = app.worker._recover_queue_backlog()
        recover.assert_called_once_with(limit=100)
        self.assertEqual(receipt["deferred_ids"], [1])

    def test_startup_line_names_each_job_stranded_a_second_time(self):
        import app.worker

        receipt = {
            "retried_ids": [3],
            "failed_ids": [7],
            "aborted_ids": [],
            "deferred_ids": [],
            "stranded_again": [{"id": 7, "task_name": "background.workbench_generate"}],
        }
        with (
            mock.patch.object(background_module, "recover_interrupted_jobs", return_value=receipt),
            mock.patch("builtins.print") as report,
        ):
            recovered = app.worker._recover_queue_backlog()
        self.assertEqual(recovered["stranded_again"], receipt["stranded_again"])
        lines = [call.args[0] for call in report.call_args_list]
        self.assertTrue(any("重送一次" in line for line in lines))
        self.assertFalse(any("付費工作不自動重送" in line for line in lines))
        named = [line for line in lines if "background.workbench_generate" in line]
        self.assertEqual(len(named), 1)
        self.assertIn("7", named[0])
        self.assertIn("失敗", named[0])

    def test_startup_failure_does_not_start_worker_and_releases_lock(self):
        import app.worker

        with (
            mock.patch.object(gateway, "fail_interrupted_tasks"),
            mock.patch.object(
                background_module,
                "recover_interrupted_jobs",
                side_effect=RuntimeError("queue offline"),
            ),
            mock.patch.object(app.worker.ads, "bootstrap_runtime") as bootstrap,
            mock.patch.object(app.worker, "background_app") as queue,
        ):
            with self.assertRaisesRegex(RuntimeError, "queue offline"):
                app.worker.main(wait=False)
        bootstrap.assert_not_called()
        queue.assert_not_called()
        schema = db.current().execute("SELECT current_schema() AS s").fetchone()["s"]
        key = app.worker._advisory_lock_key(schema)
        with db.pool().connection() as conn:
            self.assertTrue(
                conn.execute("SELECT pg_try_advisory_lock(%s) AS got", (key,)).fetchone()["got"]
            )
            conn.execute("SELECT pg_advisory_unlock(%s)", (key,))


class IsActiveTest(unittest.TestCase):
    """Round 2 (ticket 08-standalone-jobs-on-the-queue "Blocked"): `is_active()` is the
    409/400 gate a caller uses to refuse a second press while a job is claimed but not
    finished — the window `llm_task` cannot see, because `app/llm/gateway.py` only writes the
    `running` row immediately before the provider call, not when the worker claims the job.

    Done-check 10: both edges matter. A lock that reads "active" forever after the job
    succeeded would lock a user out of their own feature permanently — worse than the bug
    this round fixes. The 'doing' row below is written directly (not produced by actually
    running the worker on a real task, which finishes a trivial `background.noop` job too
    fast in-process to observe mid-flight) — this is the same style
    `test_worker_runs_one_deferred_job` above already uses to reach into
    `<schema>__queue.procrastinate_jobs` directly."""

    def test_true_for_todo_and_doing_false_after_terminal(self):
        lock = f"is_active_test:{db.new_id('lock')}"
        a = background_module.app()
        with a.open():
            job_id = a.configure_task("background.noop", queueing_lock=lock).defer(
                org_id=db.DEV_ORG_ID
            )
        self.assertTrue(background_module.is_active(lock), "a 'todo' job must read as active")

        # A plain fully-qualified UPDATE isn't enough here (unlike the read-only assertion in
        # `test_worker_runs_one_deferred_job` above): the queue schema's own
        # `procrastinate_trigger_function_status_events_update_v1()` casts to
        # `procrastinate_job_status` unqualified, so it only resolves under a search_path that
        # includes that schema — `SET LOCAL` scopes that to this one transaction.
        schema = db.current().execute("SELECT current_schema() AS s").fetchone()["s"]
        db.current().execute(f'SET LOCAL search_path TO "{schema}__queue"')
        db.current().execute(
            "UPDATE procrastinate_jobs SET status = 'doing' WHERE id = %s",
            (job_id,),
        )
        db.current().commit()
        self.assertTrue(
            background_module.is_active(lock),
            "'doing' (claimed by a worker, not yet finished) must read as active — this is "
            "exactly the window llm_task cannot see",
        )

        db.current().execute(f'SET LOCAL search_path TO "{schema}__queue"')
        db.current().execute(
            "UPDATE procrastinate_jobs SET status = 'succeeded' WHERE id = %s",
            (job_id,),
        )
        db.current().commit()
        self.assertFalse(
            background_module.is_active(lock),
            "a finished job must not block a user from re-running their own feature",
        )


class QueueSnapshotTest(unittest.TestCase):
    """F29-I05 (feature Contract G): `queue_snapshot()` reads the whole queue in pick order —
    running first, then waiting by procrastinate's own fetch order (priority DESC, id ASC),
    then jobs scheduled for later — and never writes."""

    def _queue(self, sql, params=()):
        schema = db.current().execute("SELECT current_schema() AS s").fetchone()["s"]
        db.current().execute(f'SET LOCAL search_path TO "{schema}__queue"')
        db.current().execute(sql, params)
        db.current().commit()

    def setUp(self):
        self._queue("DELETE FROM procrastinate_jobs")
        self._queue("DELETE FROM procrastinate_workers")

    @staticmethod
    def _snapshot():
        # F50 Contract K: `since` is required (the caller's org-day start); an hour back covers
        # every event these tests write.
        return background_module.queue_snapshot(since=db.now_utc() - timedelta(hours=1))

    def test_since_is_required(self):
        """F50 Contract K: no default "00:00 UTC today" -- the caller passes its org's day."""
        with self.assertRaises(TypeError):
            background_module.queue_snapshot()  # type: ignore[call-arg]

    def test_worker_alive_needs_a_fresh_heartbeat(self):
        """F47 Contract C: no worker row, or only a stale one (a killed worker leaves it), is
        not alive; a heartbeat within 60 s is."""
        self.assertFalse(self._snapshot()["worker_alive"], "no worker row")
        self._queue("INSERT INTO procrastinate_workers (last_heartbeat)"
                    " VALUES (now() - interval '2 minutes')")
        self.assertFalse(self._snapshot()["worker_alive"],
                         "a heartbeat older than 60 s is a stopped worker")
        self._queue("INSERT INTO procrastinate_workers (last_heartbeat)"
                    " VALUES (now() - interval '5 seconds')")
        self.assertTrue(self._snapshot()["worker_alive"])

    def test_pick_order_positions_and_waits(self):
        a = background_module.app()
        with a.open():
            first = a.configure_task("background.noop").defer(org_id="org_a")
            later = a.configure_task("background.noop").defer(org_id="org_a")
            urgent = a.configure_task("background.noop", priority=5).defer(org_id="org_b")
            running = a.configure_task("background.noop").defer(org_id="org_b")
        self._queue("UPDATE procrastinate_jobs SET status = 'doing' WHERE id = %s", (running,))
        self._queue(
            "UPDATE procrastinate_jobs SET scheduled_at = now() + interval '1 hour' "
            "WHERE id = %s", (later,),
        )

        snap = self._snapshot()

        self.assertEqual(snap["total"], 4)
        self.assertEqual(
            [(j["id"], j["status"], j["position"], j["org_id"]) for j in snap["jobs"]],
            [(running, "running", 1, "org_b"), (urgent, "queued", 2, "org_b"),
             (first, "queued", 3, "org_a"), (later, "queued", 4, "org_a")],
        )
        waits = [j["waited_seconds"] for j in snap["jobs"]]
        self.assertTrue(all(isinstance(w, int) and w >= 0 for w in waits[:3]))
        self.assertIsNone(waits[3], "a job scheduled for later has not started waiting")
        self.assertEqual(snap["jobs"][0]["args"], {"org_id": "org_b"})

    def test_finished_today_counted_per_org(self):
        a = background_module.app()
        with a.open():
            ids = [a.configure_task("background.noop").defer(org_id=org)
                   for org in ("org_a", "org_a", "org_b")]
        for job_id, end in zip(ids, ("succeeded", "failed", "succeeded"), strict=True):
            self._queue("UPDATE procrastinate_jobs SET status = 'doing' WHERE id = %s", (job_id,))
            self._queue("UPDATE procrastinate_jobs SET status = %s WHERE id = %s", (end, job_id))

        snap = self._snapshot()

        self.assertEqual((snap["jobs"], snap["total"]), ([], 0))
        self.assertEqual(snap["done_today"], {"org_a": 1, "org_b": 1})
        self.assertEqual(snap["failed_today"], {"org_a": 1})

    def test_memory_mode_reads_nothing(self):
        with mock.patch.object(config.settings(), "brand_os_job_queue", "memory"), \
                mock.patch.object(background_module, "_sync_app_for_defer") as queue:
            snap = self._snapshot()
        queue.assert_not_called()
        self.assertEqual(snap, {"jobs": [], "total": 0, "done_today": {}, "failed_today": {},
                                "worker_alive": True})


class WorkerConcurrencyTest(unittest.TestCase):
    def test_worker_runs_three_jobs_at_once(self):
        import app.worker

        with (
            mock.patch.object(gateway, "fail_interrupted_tasks"),
            mock.patch.object(app.worker, "_recover_queue_backlog"),
            mock.patch.object(app.worker.ads, "bootstrap_runtime"),
            mock.patch.object(app.worker, "background_app") as queue,
        ):
            app.worker.main(wait=False)
        queue.return_value.run_worker.assert_called_once_with(wait=False, concurrency=3)


class QueueConninfoTest(unittest.TestCase):
    def test_url_and_keyword_parameters_survive(self):
        for dsn in (
            "postgresql://user:p%40ss@localhost:5432/test?sslmode=require"
            "&connect_timeout=7&application_name=queue-test&options=-c%20statement_timeout%3D321",
            "host=localhost dbname=test user=user password='p ass\\'word' "
            "sslmode=require connect_timeout=7 application_name='queue test' "
            "options='-c statement_timeout=321 -c search_path=old,public'",
        ):
            with self.subTest(kind=dsn.split(":")[0][:10]):
                before = conninfo_to_dict(dsn)
                after = conninfo_to_dict(
                    background_module._with_search_path(dsn, 'queue schema,"q')
                )
                self.assertEqual(
                    {k: v for k, v in before.items() if k != "options"},
                    {k: v for k, v in after.items() if k != "options"},
                )
                self.assertTrue(after["options"].startswith(before["options"]))

    def test_last_search_path_is_one_quoted_schema_and_keeps_other_options(self):
        schema = 'queue schema,"q\\slash'
        original = make_conninfo(
            db.dsn(),
            application_name="recovery-conninfo-test",
            options="-c statement_timeout=321 -c search_path=public",
        )
        with psycopg.connect(background_module._with_search_path(original, schema)) as conn:
            self.assertEqual(
                conn.execute("SHOW search_path").fetchone()[0],
                '"' + schema.replace('"', '""') + '"',
            )
            self.assertEqual(conn.execute("SHOW statement_timeout").fetchone()[0], "321ms")
            self.assertEqual(
                conn.execute("SHOW application_name").fetchone()[0], "recovery-conninfo-test"
            )


class DeferAppConnectionsTest(unittest.TestCase):
    """F31-I15: the module-private defer App (`enqueue()`/`is_active()`/`job_outcome()`) must
    not hold queue connections it does not need. Measured in F31-I11: each process kept the
    pool at psycopg_pool's default four idle connections, and a DSN change orphaned the old
    App (never closed) — together 13 connections per xdist worker, enough to exhaust the shared
    54322 server under the manifest's `pytest -n 4`. Connections are counted on the server
    (`pg_stat_activity`) under an `application_name` only this test uses."""

    def test_dsn_switch_closes_old_defer_app_and_new_one_holds_one_connection(self):
        tag = f"f31i15_{db.new_id('t')}"[:60]
        lock = f"defer_pool_test:{tag}"
        old = background_module._sync_app_for_defer()
        original = os.environ.get("DATABASE_URL")
        os.environ["DATABASE_URL"] = make_conninfo(db.dsn(), application_name=tag)
        try:
            self.assertTrue(
                background_module.enqueue("background.noop", org_id=db.DEV_ORG_ID, lock=lock)
            )
            new = background_module._sync_app_for_defer()
            self.assertIsNot(new, old, "a DSN change must rebuild the defer App")
            with self.assertRaises(AppNotOpen, msg="the replaced defer App must be closed"):
                _ = old.connector.pool

            with psycopg.connect(original or db.dsn()) as conn:
                held = conn.execute(
                    "SELECT count(*) FROM pg_stat_activity WHERE application_name = %s", (tag,)
                ).fetchone()[0]
            self.assertLessEqual(held, 1, "one enqueue must leave at most one idle connection")
            self.assertGreaterEqual(held, 1, "test setup: the tagged pool must be visible")
        finally:
            if original is None:
                os.environ.pop("DATABASE_URL", None)
            else:
                os.environ["DATABASE_URL"] = original
            background_module._sync_app_for_defer()  # back onto this module's own queue
            with psycopg.connect(
                background_module._with_search_path(
                    db.dsn(), background_module._queue_search_path()
                )
            ) as conn:
                conn.execute("DELETE FROM procrastinate_jobs WHERE queueing_lock = %s", (lock,))


class OrphanRecoveryTest(unittest.TestCase):
    def setUp(self):
        self.ids = []
        self.dsn = background_module._with_search_path(
            db.dsn(), background_module._queue_search_path()
        )
        self.lock = "recovery:" + db.new_id("test")

    def tearDown(self):
        with psycopg.connect(self.dsn) as conn:
            conn.execute("DELETE FROM procrastinate_jobs WHERE id=ANY(%s)", (self.ids,))

    def seed(self, task, *, lock=None, doing=True, abort=False):
        queue = background_module._sync_app_for_defer()
        job_id = queue.configure_task(task, queueing_lock=lock).defer(org_id=db.DEV_ORG_ID)
        self.ids.append(job_id)
        if doing:
            with psycopg.connect(self.dsn) as conn:
                conn.execute(
                    "UPDATE procrastinate_jobs SET status='doing',abort_requested=%s WHERE id=%s",
                    (abort, job_id),
                )
        return job_id

    def status(self, job_id):
        return background_module._sync_app_for_defer().job_manager.get_job_status(job_id)

    def strand(self, job_id):
        """A worker picked the re-queued job up and died again."""
        with psycopg.connect(self.dsn) as conn:
            conn.execute("UPDATE procrastinate_jobs SET status='doing' WHERE id=%s", (job_id,))

    def job(self, job_id):
        return background_module._sync_app_for_defer().job_manager.list_jobs(id=job_id)[0]

    def test_every_stranded_task_is_handled_and_same_job_args_are_kept(self):
        read = self.seed("background.ads_external_sync", lock=self.lock)
        (review_task,) = FAILED_TASKS
        review = self.seed(review_task)
        paid = self.seed("background.workbench_generate")
        unknown = self.seed("background.ads_external_sync_paid")
        receipt = background_module.recover_interrupted_jobs()
        self.assertIn(read, receipt["retried_ids"])
        self.assertIn(review, receipt["failed_ids"])
        self.assertEqual(self.status(review), Status.FAILED)
        for job_id in (paid, unknown):
            self.assertIn(job_id, receipt["retried_ids"])
            self.assertEqual(self.status(job_id), Status.TODO)
        self.assertEqual(receipt["stranded_again"], [])
        job = self.job(read)
        self.assertEqual(job.task_kwargs, {"org_id": db.DEV_ORG_ID})
        self.assertEqual(job.queueing_lock, self.lock)
        self.assertEqual(job.attempts, 1)

    def test_requeue_is_scheduled_on_the_queue_clock_not_the_product_clock(self):
        """F50 Contract K exception: the drill worker moves `db.now_utc` to a later drill date;
        a re-queued job must still be due on the queue's own clock (database `now()`), not
        parked until the real clock reaches the drill date."""
        job_id = self.seed("background.ads_external_sync", lock=self.lock)
        drill_day = db.now_utc() + timedelta(days=30)
        with mock.patch.object(db, "now_utc", return_value=drill_day):
            receipt = background_module.recover_interrupted_jobs()
        self.assertIn(job_id, receipt["retried_ids"])
        with psycopg.connect(self.dsn) as conn:
            row = conn.execute(
                "SELECT scheduled_at, scheduled_at <= now() AS due FROM procrastinate_jobs"
                " WHERE id = %s", (job_id,)).fetchone()
        assert row is not None
        self.assertTrue(row[1], f"re-queued job is parked until {row[0]}")
        self.assertLess(row[0], drill_day - timedelta(days=29))

    def test_non_read_only_task_is_requeued_once_then_failed_on_second_strand(self):
        paid = self.seed("background.workbench_generate", lock=self.lock)
        unknown = self.seed("background.unregistered_task")
        first = background_module.recover_interrupted_jobs()
        self.assertEqual(sorted(first["retried_ids"]), sorted([paid, unknown]))
        self.assertEqual(self.job(paid).queueing_lock, self.lock)
        self.strand(paid)
        self.strand(unknown)
        second = background_module.recover_interrupted_jobs()
        self.assertEqual(second["retried_ids"], [])
        self.assertEqual(sorted(second["failed_ids"]), sorted([paid, unknown]))
        self.assertEqual(
            sorted(second["stranded_again"], key=lambda job: job["id"]),
            sorted(
                [
                    {"id": paid, "task_name": "background.workbench_generate"},
                    {"id": unknown, "task_name": "background.unregistered_task"},
                ],
                key=lambda job: job["id"],
            ),
        )
        for job_id in (paid, unknown):
            self.assertEqual(self.status(job_id), Status.FAILED)  # kept, not deleted
        third = background_module.recover_interrupted_jobs()
        self.assertNotIn(paid, third["failed_ids"] + third["retried_ids"])

    def test_read_only_and_review_round_keep_their_paths_on_every_strand(self):
        read = self.seed("background.ads_external_sync")
        (review_task,) = FAILED_TASKS
        review = self.seed(review_task)
        background_module.recover_interrupted_jobs()
        self.strand(read)
        receipt = background_module.recover_interrupted_jobs()
        self.assertIn(read, receipt["retried_ids"])
        self.assertEqual(self.status(read), Status.TODO)
        self.assertEqual(self.job(read).attempts, 2)
        self.assertEqual(receipt["stranded_again"], [])
        self.assertEqual(self.status(review), Status.FAILED)

    def test_abort_is_terminal_and_existing_todo_wins_collision(self):
        aborted = self.seed("background.ads_external_sync", abort=True)
        old = self.seed("background.ads_external_sync", lock=self.lock)
        waiting = self.seed("background.ads_external_sync", lock=self.lock, doing=False)
        receipt = background_module.recover_interrupted_jobs()
        self.assertIn(aborted, receipt["aborted_ids"])
        self.assertEqual(self.status(aborted), Status.ABORTED)
        self.assertIn(old, receipt["failed_ids"])
        self.assertEqual(self.status(waiting), Status.TODO)

    def test_collision_created_after_initial_check_is_reconciled(self):
        old = self.seed("background.ads_external_sync", lock=self.lock)
        original = manager.JobManager.retry_job_by_id_async
        waiting = []

        async def raced(instance, job_id, **kwargs):
            waiting.append(self.seed("background.ads_external_sync", lock=self.lock, doing=False))
            await original(instance, job_id, **kwargs)

        with mock.patch.object(manager.JobManager, "retry_job_by_id_async", raced):
            receipt = background_module.recover_interrupted_jobs()
        self.assertIn(old, receipt["failed_ids"])
        self.assertEqual(self.status(waiting[0]), Status.TODO)

    def test_abort_during_retry_is_never_reported_as_requeued(self):
        old = self.seed("background.ads_external_sync")
        original = manager.JobManager.retry_job_by_id_async

        async def raced(instance, job_id, **kwargs):
            background_module._sync_app_for_defer().job_manager.cancel_job_by_id(job_id, abort=True)
            await original(instance, job_id, **kwargs)

        with mock.patch.object(manager.JobManager, "retry_job_by_id_async", raced):
            receipt = background_module.recover_interrupted_jobs()
        self.assertIn(old, receipt["failed_ids"])
        self.assertEqual(self.status(old), Status.FAILED)

    def test_limit_bounds_changes_and_refuses_unreviewed_paid_task(self):
        first = self.seed("background.ads_external_sync")
        second = self.seed("background.ads_external_sync")
        receipt = background_module.recover_interrupted_jobs(limit=1)
        self.assertEqual(receipt["retried_ids"], [first])
        self.assertEqual(receipt["deferred_ids"], [second])
        with self.assertRaises(ValueError):
            background_module.recover_interrupted_jobs(retry_tasks={"background.paid"})


class MemoryQueueTest(unittest.TestCase):
    """`BRAND_OS_JOB_QUEUE=memory`（F06-I05，e2e 後端專用）：`enqueue()`／`is_active()` 完全
    不碰 procrastinate，job 永遠不會落地在 `<schema>__queue.procrastinate_jobs`。"""

    def setUp(self):
        config.settings.cache_clear()
        self._patcher = mock.patch.dict(os.environ, {"BRAND_OS_JOB_QUEUE": "memory"})
        self._patcher.start()
        config.settings.cache_clear()
        self.addCleanup(self._patcher.stop)
        self.addCleanup(config.settings.cache_clear)
        self.addCleanup(background_module._memory_locks.clear)

    def test_enqueue_and_is_active_never_touch_the_queue(self):
        lock = f"memory_queue_test:{db.new_id('lock')}"

        self.assertTrue(
            background_module.enqueue("background.noop", org_id=db.DEV_ORG_ID, lock=lock)
        )
        self.assertFalse(
            background_module.enqueue("background.noop", org_id=db.DEV_ORG_ID, lock=lock)
        )

        self.assertTrue(background_module.is_active(lock))
        self.assertFalse(background_module.is_active("never-enqueued"))

        schema = db.current().execute("SELECT current_schema() AS s").fetchone()["s"]
        count = (
            db.current()
            .execute(
                f'SELECT count(*) AS c FROM "{schema}__queue".procrastinate_jobs '
                "WHERE queueing_lock = %s",
                (lock,),
            )
            .fetchone()["c"]
        )
        self.assertEqual(count, 0)


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
