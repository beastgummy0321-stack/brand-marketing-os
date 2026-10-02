"""app/tests/test_ads_queue_done.py — F47 Contract D: `queue_done.done` is the one owner of a queue
row's done-ness (the rule `home/status.ts::isQueueItemDone` used to hold), and `open_count` counts
what the home board counts."""

import unittest

from app.ads import queue_done


def _set(status, verification_state="pending", kind="cleanup"):
    return {"kind": kind, "change_set_id": "acs_1", "campaign_id": "cmp_1", "status": status,
            "verification_state": verification_state, "reason": None, "revisit_at": None,
            "multi": kind == "cleanup"}


def _review(status, change_set_status=None, verification_state=None):
    return {"kind": "review", "review_id": "rvw_1", "status": status, "decision": None,
            "reason": None, "revisit_at": None, "recommendation_id": None,
            "change_set_id": "acs_1" if change_set_status else None,
            "change_set_status": change_set_status, "verification_state": verification_state,
            "multi": False}


def _row(kind, proposal):
    return {"kind_key": kind, "proposal": proposal}


class DoneRuleTest(unittest.TestCase):
    def test_no_proposal_is_never_done(self):
        for kind in ("cleanup", "scale_budget", "worse", "stop_loss", "refresh_creative",
                     "insufficient_data", "settle"):
            with self.subTest(kind=kind):
                self.assertFalse(queue_done.done(_row(kind, None)))

    def test_change_set_rows_follow_the_set(self):
        cases = {
            ("draft", "pending"): False,
            ("rejected", "pending"): True,
            ("deferred", "pending"): True,
            ("approved", "pending"): False,
            ("approved", "reported"): False,
            ("approved", "unknown"): False,
            ("approved", "deviated"): False,
            ("approved", "stale"): False,
            ("approved", "confirmed"): True,
        }
        for kind in ("cleanup", "scale_budget", "stop_loss"):
            for (status, state), expected in cases.items():
                with self.subTest(kind=kind, status=status, state=state):
                    row = _row(kind, _set(status, state, kind="budget" if kind == "scale_budget"
                                          else kind))
                    self.assertIs(queue_done.done(row), expected)

    def test_worse_rows_follow_the_review_round_then_its_copy_set(self):
        cases = [
            (_review("queued"), False),
            (_review("running"), False),
            (_review("waiting"), False),
            (_review("failed"), False),
            (_review("unknown"), False),
            (_review("ready"), False),
            (_review("completed"), False),
            (_review("deferred"), True),
            (_review("unjudgeable"), True),
            (_review("completed", "draft", "pending"), False),
            (_review("completed", "deferred", "pending"), True),
            (_review("completed", "rejected", "pending"), True),
            (_review("completed", "approved", "reported"), False),
            (_review("completed", "approved", "confirmed"), True),
        ]
        for proposal, expected in cases:
            with self.subTest(proposal=proposal):
                self.assertIs(queue_done.done(_row("worse", proposal)), expected)

    def test_rows_without_a_proposal_flow_are_never_done(self):
        for kind in ("refresh_creative", "insufficient_data", "settle"):
            with self.subTest(kind=kind):
                self.assertFalse(queue_done.done(_row(kind, _set("deferred"))))


class OpenCountTest(unittest.TestCase):
    def test_counts_open_rows_of_the_home_board_kinds_only(self):
        rows = [
            {"kind_key": "cleanup", "done": True},
            {"kind_key": "worse", "done": False},
            {"kind_key": "refresh_creative", "done": False},
            {"kind_key": "settle", "done": False},
            {"kind_key": "scale_budget", "done": False},
            {"kind_key": "insufficient_data", "done": False},
        ]
        self.assertEqual(queue_done.open_count(rows), 3)

    def test_empty_queue_is_zero(self):
        self.assertEqual(queue_done.open_count([]), 0)


if __name__ == "__main__":
    unittest.main()
