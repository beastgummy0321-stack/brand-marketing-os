"""app/tests/test_background_job_outcome.py — F31-I02, feature Contract J; F50-I07 (feature F50
Contract J: stored outcomes through `background.register`, `outcome()`, `job_state()`).

`app.background.job_outcome(lock)` answers "how did the newest job carrying this
`queueing_lock` end?" for every status reader in `app/intake` and `app/brand_web`. Real
procrastinate against this test module's own queue schema (see conftest.py); a job whose task
the worker does not know is the real-world "worker never picked it up properly" case (an old
worker process started before a new task type existed) and ends `failed`.
"""

import inspect
import os
import unittest
from datetime import UTC, datetime
from unittest import mock

import app.background as background_module
from app.core import config, db

_EPOCH = datetime(2000, 1, 1, tzinfo=UTC)


# F50-I07 (Contract J): handlers registered through `background.register` for the tests below.
def _returns_empty(org_id: str) -> background_module.Empty:
    return background_module.Empty("no_rows", "這段期間沒有資料。")


def _returns_failed(org_id: str) -> background_module.Failed:
    return background_module.Failed("account_failed", "有一個帳號沒拉成。")


def _raises_job_failed(org_id: str) -> None:
    raise background_module.JobFailed("pack_failed", "素材包沒送成。")


def _raises_value_error(org_id: str) -> None:
    raise ValueError("boom")


def _returns_plainly(org_id: str) -> None:
    return None


_TEST_TASKS = {
    "background.outcome_test_empty": _returns_empty,
    "background.outcome_test_failed": _returns_failed,
    "background.outcome_test_job_failed": _raises_job_failed,
    "background.outcome_test_value_error": _raises_value_error,
    "background.outcome_test_done": _returns_plainly,
}


def _register_test_tasks() -> None:
    for name, func in _TEST_TASKS.items():
        background_module.register(name, func)


def _lock(tag: str) -> str:
    return f"job_outcome_test:{tag}:{db.new_id('lock')}"


def _run_worker() -> None:
    db.current().commit()
    background_module.app().run_worker(wait=False)


class JobOutcomeTest(unittest.TestCase):
    def test_none_when_no_job_ever_carried_the_lock(self):
        self.assertIsNone(background_module.job_outcome(_lock("never")))

    def test_active_while_queued_then_succeeded_after_the_worker_ran_it(self):
        lock = _lock("noop")
        self.assertTrue(
            background_module.enqueue("background.noop", org_id=db.DEV_ORG_ID, lock=lock))
        self.assertEqual(background_module.job_outcome(lock), "active")

        _run_worker()

        self.assertEqual(background_module.job_outcome(lock), "succeeded")

    def test_failed_when_the_worker_cannot_run_the_job(self):
        lock = _lock("unknown")
        self.assertTrue(background_module.enqueue(
            "background.job_outcome_test_not_registered", org_id=db.DEV_ORG_ID, lock=lock,
        ))

        _run_worker()

        self.assertEqual(background_module.job_outcome(lock), "failed")

    def test_newest_job_wins_over_an_older_finished_one(self):
        lock = _lock("newest")
        background_module.enqueue("background.job_outcome_test_not_registered",
                                  org_id=db.DEV_ORG_ID, lock=lock)
        _run_worker()
        self.assertEqual(background_module.job_outcome(lock), "failed")

        background_module.enqueue("background.noop", org_id=db.DEV_ORG_ID, lock=lock)

        self.assertEqual(background_module.job_outcome(lock), "active")


class StoredOutcomeTest(unittest.TestCase):
    """Contract J: the wrapper stores failed／empty／done + code; a failure fails the job."""

    def setUp(self):
        _register_test_tasks()

    def _run(self, task_name: str, tag: str) -> str:
        lock = _lock(tag)
        self.assertTrue(background_module.enqueue(task_name, org_id=db.DEV_ORG_ID, lock=lock))
        _run_worker()
        return lock

    def _stored(self, lock: str):
        return db.current().execute(
            "SELECT state, code, text FROM background_job_result WHERE org_id = %s AND lock = %s",
            (db.DEV_ORG_ID, lock),
        ).fetchone()

    def _failed_today(self) -> int:
        return background_module.queue_snapshot(since=_EPOCH)["failed_today"].get(db.DEV_ORG_ID, 0)

    def test_empty_is_stored_and_the_job_succeeds(self):
        lock = self._run("background.outcome_test_empty", "empty")
        self.assertEqual(dict(self._stored(lock)),
                         {"state": "empty", "code": "no_rows", "text": "這段期間沒有資料。"})
        self.assertEqual(background_module.job_outcome(lock), "succeeded")
        found = background_module.outcome(lock)
        self.assertEqual((found["state"], found["code"]), ("empty", "no_rows"))

    def test_returned_failed_fails_the_job_and_the_bell_counts_it(self):
        before = self._failed_today()
        lock = self._run("background.outcome_test_failed", "failed")
        self.assertEqual(dict(self._stored(lock)), {"state": "failed", "code": "account_failed",
                                                     "text": "有一個帳號沒拉成。"})
        found = background_module.outcome(lock)
        self.assertEqual((found["state"], found["code"], found["text"]),
                         ("failed", "account_failed", "有一個帳號沒拉成。"))
        self.assertEqual(self._failed_today(), before + 1)

    def test_raised_job_failed_keeps_its_code(self):
        lock = self._run("background.outcome_test_job_failed", "job_failed")
        self.assertEqual(self._stored(lock)["code"], "pack_failed")
        self.assertEqual(background_module.outcome(lock)["state"], "failed")
        self.assertEqual(background_module.job_outcome(lock), "failed")

    def test_an_uncaught_exception_is_stored_as_unexpected(self):
        before = self._failed_today()
        lock = self._run("background.outcome_test_value_error", "value_error")
        self.assertEqual(dict(self._stored(lock)),
                         {"state": "failed", "code": background_module.UNEXPECTED_CODE,
                          "text": background_module.JOB_FAILED_MESSAGE})
        self.assertEqual(background_module.outcome(lock)["code"], "unexpected")
        self.assertEqual(self._failed_today(), before + 1)

    def test_a_plain_return_is_done(self):
        lock = self._run("background.outcome_test_done", "done")
        self.assertEqual(self._stored(lock)["state"], "done")
        self.assertEqual(background_module.outcome(lock)["state"], "done")

    def test_failed_job_without_a_stored_row_reads_job_failed(self):
        lock = self._run("background.job_outcome_test_not_registered", "no_row")
        self.assertIsNone(self._stored(lock))
        found = background_module.outcome(lock)
        self.assertEqual((found["state"], found["code"], found["text"]),
                         ("failed", background_module.JOB_FAILED_CODE,
                          background_module.JOB_FAILED_MESSAGE))

    def test_an_older_jobs_row_does_not_speak_for_the_newest_job(self):
        lock = self._run("background.outcome_test_empty", "older")
        background_module.enqueue("background.job_outcome_test_not_registered",
                                  org_id=db.DEV_ORG_ID, lock=lock)
        _run_worker()
        self.assertEqual(background_module.outcome(lock)["code"], background_module.JOB_FAILED_CODE)

    def test_the_handler_keeps_its_own_signature(self):
        task = background_module.app().tasks["background.outcome_test_empty"]
        self.assertTrue(background_module.is_registered_through_register(task))
        self.assertEqual(list(inspect.signature(task.func).parameters), ["org_id"])
        # A direct call without a job context runs the handler and records nothing.
        self.assertIsNone(task.func(org_id=db.DEV_ORG_ID))


class JobStateTest(unittest.TestCase):
    """Contract J `job_state(lock, llm_row)`: the one status read every screen uses."""

    def test_never_queued_and_no_row_is_unknown_without_a_made_up_time(self):
        self.assertEqual(background_module.job_state(_lock("never"), None),
                         {"status": "unknown", "started_at": None, "error": None})

    def test_queued_job_reads_running_with_its_real_queue_time(self):
        lock = _lock("queued")
        background_module.enqueue("background.noop", org_id=db.DEV_ORG_ID, lock=lock)
        state = background_module.job_state(lock, None)
        self.assertEqual(state["status"], "running")
        self.assertIsInstance(state["started_at"], datetime)
        again = background_module.job_state(lock, None)
        self.assertEqual(again["started_at"], state["started_at"])  # not re-made per read

    def test_failed_job_quotes_its_own_llm_error_never_a_generic_sentence(self):
        _register_test_tasks()
        lock = _lock("own_error")
        background_module.enqueue("background.outcome_test_failed", org_id=db.DEV_ORG_ID,
                                  lock=lock)
        _run_worker()
        row = {"status": "failed", "error": "AI 服務逾時未回應，請再試一次。",
               "started_at": _EPOCH}
        state = background_module.job_state(lock, row)
        self.assertEqual((state["status"], state["error"]),
                         ("failed", "AI 服務逾時未回應，請再試一次。"))
        self.assertEqual(background_module.job_state(lock, None)["error"], "有一個帳號沒拉成。")

    def test_no_queue_outcome_falls_back_to_the_row(self):
        lock = _lock("row_only")
        failed = {"status": "failed", "error": "provider 掛了", "started_at": _EPOCH}
        self.assertEqual(background_module.job_state(lock, failed),
                         {"status": "failed", "started_at": _EPOCH, "error": "provider 掛了"})
        done = {"status": "succeeded", "error": None, "started_at": _EPOCH}
        self.assertEqual(background_module.job_state(lock, done)["status"], "done")


class JobOutcomeMemoryModeTest(unittest.TestCase):
    """Memory queue mode (e2e): jobs never run, so there is no outcome to report."""

    def setUp(self):
        config.settings.cache_clear()
        self._patcher = mock.patch.dict(os.environ, {"BRAND_OS_JOB_QUEUE": "memory"})
        self._patcher.start()
        config.settings.cache_clear()
        self.addCleanup(self._patcher.stop)
        self.addCleanup(config.settings.cache_clear)
        self.addCleanup(background_module._memory_locks.clear)

    def test_always_none(self):
        lock = _lock("memory")
        background_module.enqueue("background.noop", org_id=db.DEV_ORG_ID, lock=lock)
        self.assertIsNone(background_module.job_outcome(lock))
        self.assertIsNone(background_module.outcome(lock))
        self.assertEqual(background_module.job_state(lock, None)["status"], "unknown")


if __name__ == "__main__":
    unittest.main()
