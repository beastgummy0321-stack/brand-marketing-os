"""app/tests/test_fact_staleness.py — issue #5：事實鮮度標示（純顯示，不動資料庫）。

驗收：確認超過 FACT_STALE_DAYS（180 天）才提示「上次確認 N 個月前」；
門檻內、以及 pending 事實一律不提示。
"""

import unittest
from datetime import UTC, datetime, timedelta

import app.shared.web as web


class FactStalenessTest(unittest.TestCase):
    def _confirmed_fact(self, days_ago):
        confirmed_at = datetime.now(UTC) - timedelta(days=days_ago)
        return {"status": "confirmed", "confirmed_at": confirmed_at}

    def test_over_threshold_shows_hint(self):
        fact = self._confirmed_fact(400)
        self.assertEqual(web.fact_staleness(fact), "上次確認 13 個月前")

    def test_within_threshold_no_hint(self):
        fact = self._confirmed_fact(90)
        self.assertIsNone(web.fact_staleness(fact))

    def test_pending_fact_no_hint(self):
        fact = {"status": "pending", "confirmed_at": None}
        self.assertIsNone(web.fact_staleness(fact))


if __name__ == "__main__":
    unittest.main()
