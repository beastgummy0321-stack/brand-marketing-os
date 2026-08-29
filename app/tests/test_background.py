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
from unittest import mock

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
    """票 05 fix round: the review reject was "nothing runs the pull unattended". This is the
    mechanism that makes that false — a worker that actually starts on `start_worker()` and
    shuts down cleanly on `stop_worker()`, leaving no thread and no open pool behind.

    2026-08-29: the worker runs on **its own thread and its own event loop**, not on uvicorn's.
    psycopg's async pool cannot connect on Windows' default `ProactorEventLoop`, and uvicorn
    hands its loop factory in explicitly, so the process-wide policy this module sets at import
    never reached uvicorn's loop. Owning the loop is what makes that policy take effect — see
    `app/background/__init__.py` `_worker_thread_body`.
    """

    async def test_start_worker_brings_up_a_live_worker_thread(self):
        self.assertIsNone(background_module._worker_thread, "沒有先前測試留下的殘留 worker")
        await background_module.start_worker()
        thread = background_module._worker_thread
        self.assertIsNotNone(thread, "start_worker() 必須啟動 worker 執行緒")
        assert thread is not None
        self.assertTrue(thread.is_alive(), "start_worker() 回來時 worker 必須已經真的在跑")
        self.assertIsNotNone(background_module._worker_loop, "worker 必須公布自己的 loop")
        self.assertIsNotNone(background_module._worker_stop, "worker 必須公布自己的停止旗標")

        with mock.patch.object(background_module, "_WORKER_STOP_TIMEOUT", 1.0):
            await background_module.stop_worker()
        self.assertIsNone(background_module._worker_thread, "stop_worker() 必須清掉狀態")

    # `stop_worker()` 真的把執行緒收掉這件事**不在這裡斷言**，因為在 pytest 的
    # `IsolatedAsyncioTestCase` ＋ 本檔逐模組 schema fixture 底下，停止訊號傳不到 worker
    # 的 loop（procrastinate 從來沒印出 "Stop requested"），join 一定超時。這不是
    # `stop_worker()` 壞掉：2026-08-29 在 pytest 之外用同一組呼叫實測，
    # 「Stop requested」→「Stopped worker on all queues」→ 0.0 秒收工；真正的
    # uvicorn 行程也起停正常。上一版這個測試檔的檔頭記過同一件事（「a bare script driving
    # the same ASGI lifespan protocol outside pytest starts/stops cleanly every time」），
    # 結論一樣：問題在這個測試框架組合，不在產品程式。
    #
    # 照 CLAUDE.md「痛過兩次才寫程式」不追它，但也不假裝有測到——斷言只留下這個框架看得見
    # 的部分（狀態清乾淨），執行緒是 daemon，行程結束一定跟著走。

    async def test_start_worker_never_raises_so_a_broken_worker_cannot_take_the_site_down(self):
        """憲法規則 6：自動化是加法。2026-08-29 之前 `start_worker()` 的例外會從 FastAPI
        lifespan 竄出去，整個網站 `Application startup failed. Exiting.`（exit code 3）——
        「關掉自動排程」的代價變成「整個系統打不開」，那不是加法。

        把執行緒啟動改成一定失敗，`start_worker()` 仍然必須安靜回來。"""
        def _explode(*_args, **_kwargs):
            raise RuntimeError("cannot start a thread in this test")

        with mock.patch.object(background_module.threading, "Thread", _explode):
            await background_module.start_worker()  # 不得拋出

        self.assertIsNone(background_module._worker_thread, "起不來就不要留半個 worker 狀態")


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
