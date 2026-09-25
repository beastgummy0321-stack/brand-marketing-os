"""app/tests/test_background_job_outcome.py — F31-I02, feature Contract J.

`app.background.job_outcome(lock)` answers "how did the newest job carrying this
`queueing_lock` end?" for every status reader in `app/intake` and `app/brand_web`. Real
procrastinate against this test module's own queue schema (see conftest.py); a job whose task
the worker does not know is the real-world "worker never picked it up properly" case (an old
worker process started before a new task type existed) and ends `failed`.
"""

import os
import unittest
from unittest import mock

import app.background as background_module
from app.core import config, db


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


if __name__ == "__main__":
    unittest.main()
