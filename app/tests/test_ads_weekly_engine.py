# -*- coding: utf-8 -*-
"""票 05：到期提醒由既有自動同步排程觸發判讀與期末結算。"""

import atexit
import os
import shutil
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path

_tmpdir = tempfile.mkdtemp(prefix="brand_os_ads_weekly_engine_")
os.environ["BRAND_OS_DB"] = str(Path(_tmpdir) / "test.db")
os.environ["BRAND_OS_BACKUP_DIR"] = str(Path(_tmpdir) / "backups")
os.environ["BRAND_OS_UPLOADS"] = str(Path(_tmpdir) / "uploads")

import app.main as main  # noqa: E402
from app.ads import auto_sync  # noqa: E402
from app.ads import onboarding  # noqa: E402
from app.ads import performance  # noqa: E402
from app.ads import reading  # noqa: E402
from app.ads import repository as ads_repo  # noqa: E402
from app.brand_intelligence import repository as bi_repo  # noqa: E402
from app.llm.providers import FakeProvider, ProviderResponse, Usage  # noqa: E402

main.reopen_connection()


def _cleanup():
    try:
        main.conn.close()
    except Exception:
        pass
    shutil.rmtree(_tmpdir, ignore_errors=True)


atexit.register(_cleanup)

ACTOR = "測試員"
TODAY = date(2026, 8, 14)
NO_NETWORK = lambda _url: True


def _fake_reading_response():
    return ProviderResponse(
        output_text='{"text": "自動判讀測試說明"}', structured=None,
        usage=Usage(input_tokens=100, output_tokens=50), stop_reason="end_turn",
    )


class WeeklyEngineScheduleTest(unittest.TestCase):
    def setUp(self):
        self.brand = bi_repo.create_brand(
            main.conn, name=f"虛構週引擎品牌{abs(hash(self.id())) % 100000}",
            client_name=None, actor=ACTOR,
        )
        self._original_provider = reading.PROVIDER
        reading.PROVIDER = FakeProvider(response=_fake_reading_response())

    def tearDown(self):
        reading.PROVIDER = self._original_provider
        main.conn.execute(
            "UPDATE campaign_cycle SET status = 'CLOSED', archived = 1 WHERE brand_id = ?",
            (self.brand["id"],),
        )
        main.conn.execute("DELETE FROM interrupt WHERE brand_id = ?", (self.brand["id"],))
        main.conn.commit()
        bi_repo.update_brand(
            main.conn, self.brand["id"], name=self.brand["name"],
            client_name=self.brand["client_name"], status="archived", actor=ACTOR,
        )

    def _live_cycle(self, start: date, end: date) -> str:
        cycle = ads_repo.create_cycle(
            main.conn, self.brand["id"], product_ids=[], pain_value=10000,
            objective="sales", actor=ACTOR, start_date=start.isoformat(),
            duration_days=(end - start).days + 1,
        )
        ads_repo.update_cycle_status(
            main.conn, self.brand["id"], cycle["id"], status="LIVE", actor=ACTOR,
        )
        onboarding.create_reminders(main.conn, self.brand["id"], cycle["id"])
        result = performance.import_manual(
            main.conn, self.brand["id"], cycle["id"],
            {
                "date_start": start.isoformat(),
                "date_stop": end.isoformat(),
                "spend": 10000,
                "impressions": 20000,
                "clicks": 400,
                "conversions": 10,
                "revenue": 40000,
            },
            actor=ACTOR, today=TODAY.isoformat(),
        )
        self.assertEqual(result.errors, [])
        return cycle["id"]

    def _reading_count(self, cycle_id: str) -> int:
        return main.conn.execute(
            "SELECT COUNT(*) AS c FROM performance_reading WHERE campaign_cycle_id = ?",
            (cycle_id,),
        ).fetchone()["c"]

    def _version_count(self, cycle_id: str) -> int:
        return main.conn.execute(
            "SELECT COUNT(*) AS c FROM settlement_version WHERE campaign_cycle_id = ?",
            (cycle_id,),
        ).fetchone()["c"]

    def _reminder(self, cycle_id: str, kind: str):
        return main.conn.execute(
            "SELECT * FROM interrupt WHERE campaign_cycle_id = ? AND kind = ?",
            (cycle_id, kind),
        ).fetchone()

    def test_due_day7_runs_reading_without_http_and_resolves_reminder(self):
        cycle_id = self._live_cycle(TODAY - timedelta(days=8), TODAY + timedelta(days=5))
        reminder = self._reminder(cycle_id, "day7_report")
        self.assertEqual(reminder["visible_from"], (TODAY - timedelta(days=1)).isoformat())
        self.assertEqual(self._reading_count(cycle_id), 0)

        auto_sync.run_due_readings(main.conn, self.brand["id"], TODAY.isoformat())

        self.assertEqual(self._reading_count(cycle_id), 1)
        self.assertEqual(self._reminder(cycle_id, "day7_report")["status"], "resolved")

    def test_due_final_settlement_closes_cycle_with_final_trigger_reason(self):
        end = TODAY - timedelta(days=15)
        cycle_id = self._live_cycle(end - timedelta(days=29), end)
        reminder = self._reminder(cycle_id, "final_settlement")
        self.assertEqual(reminder["visible_from"], (TODAY - timedelta(days=1)).isoformat())

        auto_sync.run_due_readings(main.conn, self.brand["id"], TODAY.isoformat())

        self.assertEqual(
            ads_repo.get_cycle(main.conn, self.brand["id"], cycle_id)["status"], "CLOSED",
        )
        latest = main.conn.execute(
            "SELECT trigger_reason FROM settlement_version WHERE campaign_cycle_id = ?"
            " ORDER BY version DESC LIMIT 1",
            (cycle_id,),
        ).fetchone()
        self.assertEqual(latest["trigger_reason"], "final_settlement")
        self.assertEqual(self._reminder(cycle_id, "final_settlement")["status"], "resolved")

    def test_not_due_does_not_create_reading(self):
        cycle_id = self._live_cycle(TODAY, TODAY + timedelta(days=13))
        before = self._reading_count(cycle_id)

        auto_sync.run_due_readings(main.conn, self.brand["id"], TODAY.isoformat())

        self.assertEqual(self._reading_count(cycle_id), before)

    def test_repeated_same_day_does_not_duplicate_reading(self):
        cycle_id = self._live_cycle(TODAY - timedelta(days=8), TODAY + timedelta(days=5))

        auto_sync.run_due_readings(main.conn, self.brand["id"], TODAY.isoformat())
        auto_sync.run_due_readings(main.conn, self.brand["id"], TODAY.isoformat())

        self.assertEqual(self._reading_count(cycle_id), 1)
        self.assertEqual(self._version_count(cycle_id), 1)

    def test_existing_cycle_check_hook_runs_due_reading(self):
        cycle_id = self._live_cycle(TODAY - timedelta(days=8), TODAY + timedelta(days=5))

        auto_sync.run_cycle_checks(
            main.conn, self.brand["id"], TODAY.isoformat(), url_probe=NO_NETWORK,
        )

        self.assertEqual(self._reading_count(cycle_id), 1)


if __name__ == "__main__":
    unittest.main()
