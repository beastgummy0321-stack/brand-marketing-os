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
from app.llm import gateway


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
            " VALUES (%s, %s, 'brd_worker_process_test', 'schedule_plan', '{}', '[]', '',"
            " '[]', 1, 'p', 'v1', 'seed', 'seed', 'running', 1, %s)",
            (task_id, db.DEV_ORG_ID, db.now_utc()),
        )
        db.current().commit()

        app.worker.main(wait=False)

        schema = db.current().execute("SELECT current_schema() AS s").fetchone()["s"]
        job_row = db.current().execute(
            f'SELECT status FROM "{schema}__queue".procrastinate_jobs WHERE id = %s', (job_id,)
        ).fetchone()
        self.assertIsNotNone(job_row)
        self.assertNotEqual(job_row["status"], "todo", "deferred job must have been picked up")

        task_row = db.current().execute(
            "SELECT status, error FROM llm_task WHERE id = %s", (task_id,)
        ).fetchone()
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
            got = lock_conn.execute(
                "SELECT pg_try_advisory_lock(%s)", (key,)
            ).fetchone()["pg_try_advisory_lock"]
            lock_conn.commit()
            self.assertTrue(got, "test setup: this connection must hold the lock first")

            task_id = db.new_id("llm")
            db.current().execute(
                "INSERT INTO llm_task (id, org_id, brand_id, task_type, context_scope_json,"
                " input_context_ids_json, input_context_hash, knowledge_item_ids_json,"
                " brand_version, prompt_template_id, prompt_template_version, provider, model,"
                " status, attempt_no, started_at)"
                " VALUES (%s, %s, 'brd_worker_lock_test', 'schedule_plan', '{}', '[]', '',"
                " '[]', 1, 'p', 'v1', 'seed', 'seed', 'running', 1, %s)",
                (task_id, db.DEV_ORG_ID, db.now_utc()),
            )
            db.current().commit()

            app.worker.main(wait=False)  # must return quietly, not raise

            task_row = db.current().execute(
                "SELECT status FROM llm_task WHERE id = %s", (task_id,)
            ).fetchone()
            self.assertEqual(
                task_row["status"], "running",
                "a second worker must not sweep a live, already-paid-for job while the "
                "first worker's lock is held",
            )

            lock_conn.execute("SELECT pg_advisory_unlock(%s)", (key,))
            lock_conn.commit()


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
            "UPDATE procrastinate_jobs SET status = 'doing' WHERE id = %s", (job_id,),
        )
        db.current().commit()
        self.assertTrue(
            background_module.is_active(lock),
            "'doing' (claimed by a worker, not yet finished) must read as active — this is "
            "exactly the window llm_task cannot see",
        )

        db.current().execute(f'SET LOCAL search_path TO "{schema}__queue"')
        db.current().execute(
            "UPDATE procrastinate_jobs SET status = 'succeeded' WHERE id = %s", (job_id,),
        )
        db.current().commit()
        self.assertFalse(
            background_module.is_active(lock),
            "a finished job must not block a user from re-running their own feature",
        )


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
