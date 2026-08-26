# -*- coding: utf-8 -*-
"""票 05：到期提醒由既有自動同步排程觸發判讀與期末結算。"""

import unittest
from datetime import date, timedelta

import pytest

import app.main as main
from app.ads import auto_sync
from app.ads import onboarding
from app.ads import performance
from app.ads import reading
from app.ads import repository as ads_repo
from app.brand_intelligence import repository as bi_repo
from app.llm.providers import FakeProvider, ProviderResponse, Usage

ACTOR = "測試員"
TODAY = date(2026, 8, 14)
NO_NETWORK = lambda _url: True

_BUG_INTERRUPT_IS_PARAM = pytest.mark.xfail(
    strict=True,
    reason='BUG app/core/interrupts.py:99 — enqueue() dedup 查詢用 "brand_id IS %s"，'
           "Postgres 的 IS 不接受綁參數，一律 psycopg.errors.SyntaxError（這裡經"
           "onboarding.create_reminders() -> core_interrupts.enqueue() 觸發，_live_cycle() "
           "是每個測試的共用 setup 路徑）",
)


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
            "UPDATE campaign_cycle SET status = 'CLOSED', archived = true WHERE brand_id = %s",
            (self.brand["id"],),
        )
        main.conn.execute("DELETE FROM interrupt WHERE brand_id = %s", (self.brand["id"],))
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
            "SELECT COUNT(*) AS c FROM performance_reading WHERE campaign_cycle_id = %s",
            (cycle_id,),
        ).fetchone()["c"]

    def _version_count(self, cycle_id: str) -> int:
        return main.conn.execute(
            "SELECT COUNT(*) AS c FROM settlement_version WHERE campaign_cycle_id = %s",
            (cycle_id,),
        ).fetchone()["c"]

    def _reminder(self, cycle_id: str, kind: str):
        return main.conn.execute(
            "SELECT * FROM interrupt WHERE campaign_cycle_id = %s AND kind = %s",
            (cycle_id, kind),
        ).fetchone()

    @_BUG_INTERRUPT_IS_PARAM
    def test_due_day7_runs_reading_without_http_and_resolves_reminder(self):
        cycle_id = self._live_cycle(TODAY - timedelta(days=8), TODAY + timedelta(days=5))
        reminder = self._reminder(cycle_id, "day7_report")
        self.assertEqual(reminder["visible_from"], (TODAY - timedelta(days=1)).isoformat())
        self.assertEqual(self._reading_count(cycle_id), 0)

        auto_sync.run_due_readings(main.conn, self.brand["id"], TODAY.isoformat())

        self.assertEqual(self._reading_count(cycle_id), 1)
        self.assertEqual(self._reminder(cycle_id, "day7_report")["status"], "resolved")

    @_BUG_INTERRUPT_IS_PARAM
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
            "SELECT trigger_reason FROM settlement_version WHERE campaign_cycle_id = %s"
            " ORDER BY version DESC LIMIT 1",
            (cycle_id,),
        ).fetchone()
        self.assertEqual(latest["trigger_reason"], "final_settlement")
        self.assertEqual(self._reminder(cycle_id, "final_settlement")["status"], "resolved")

    @_BUG_INTERRUPT_IS_PARAM
    def test_not_due_does_not_create_reading(self):
        cycle_id = self._live_cycle(TODAY, TODAY + timedelta(days=13))
        before = self._reading_count(cycle_id)

        auto_sync.run_due_readings(main.conn, self.brand["id"], TODAY.isoformat())

        self.assertEqual(self._reading_count(cycle_id), before)

    @_BUG_INTERRUPT_IS_PARAM
    def test_repeated_same_day_does_not_duplicate_reading(self):
        cycle_id = self._live_cycle(TODAY - timedelta(days=8), TODAY + timedelta(days=5))

        auto_sync.run_due_readings(main.conn, self.brand["id"], TODAY.isoformat())
        auto_sync.run_due_readings(main.conn, self.brand["id"], TODAY.isoformat())

        self.assertEqual(self._reading_count(cycle_id), 1)
        self.assertEqual(self._version_count(cycle_id), 1)

    @_BUG_INTERRUPT_IS_PARAM
    def test_existing_cycle_check_hook_runs_due_reading(self):
        cycle_id = self._live_cycle(TODAY - timedelta(days=8), TODAY + timedelta(days=5))

        auto_sync.run_cycle_checks(
            main.conn, self.brand["id"], TODAY.isoformat(), url_probe=NO_NETWORK,
        )

        self.assertEqual(self._reading_count(cycle_id), 1)


if __name__ == "__main__":
    unittest.main()
