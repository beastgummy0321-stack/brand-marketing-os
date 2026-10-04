"""F49-I03 Contract V: "which days were read" -- one answer whatever order the reads finished in,
clipped to the campaign. `data` = a row that day; `empty` = no row inside a clean read range;
`missing` = anything else."""

import unittest
from datetime import date, timedelta

from app.ads import coverage, triage
from app.ads import external_repository as external
from app.brand_intelligence import repository as brands
from app.core import db, settings

D = date(2026, 8, 1)


def _day(offset):
    return D + timedelta(days=offset)


class CoverageTestBase(unittest.TestCase):
    def setUp(self):
        self.conn, self.org = db.current(), db.DEV_ORG_ID
        self.brand = brands.create_brand(
            self.conn, org_id=self.org, name="讀取天數測試", actor="test", client_name=None,
        )["id"]
        self.campaign = external.create_imported_campaign(
            self.conn, self.org, self.brand, name="讀取天數",
        )["id"]
        self.ad = external.upsert_entity(
            self.conn, self.org, self.brand, self.campaign,
            {"platform": "fake", "source_account": "account", "native_kind": "ad",
             "native_id": "ad1", "name": "廣告一"},
        )
        self.conn.commit()

    def campaign_row(self):
        return dict(self.conn.execute(
            "SELECT * FROM ads_campaign WHERE id=%s", (self.campaign,),
        ).fetchone())

    def set_dates(self, start, end):
        self.conn.execute(
            "UPDATE ads_campaign SET start_date=%s, end_date=%s WHERE id=%s",
            (start, end, self.campaign),
        )
        self.conn.commit()

    def read(self, start, end, **state):
        external.record_sync(
            self.conn, self.org, self.brand, self.campaign, section="observations",
            state={"status": "success", "last_success_at": db.now_utc().isoformat(),
                   "coverage": {"start": start.isoformat(), "end": end.isoformat()}, **state},
        )
        self.conn.commit()

    def fail_read(self):
        external.record_sync(
            self.conn, self.org, self.brand, self.campaign, section="observations",
            state={"status": "error", "error": "讀取失敗", "error_code": "source_error",
                   "coverage": None, "last_success_at": None},
        )
        self.conn.commit()

    def row(self, day, *, attribution_key="click"):
        external.upsert_observation(
            self.conn, self.org, self.brand, self.campaign,
            {"entity_id": self.ad["id"], "day": day, "metric_scope": "ad",
             "attribution_key": attribution_key, "currency": "TWD", "source": "meta",
             "spend": 10, "impressions": 100},
        )
        self.conn.commit()

    def states(self, start, end):
        return coverage.day_states(self.conn, self.org, self.brand, self.campaign_row(), start, end)


class DayStatesTest(CoverageTestBase):
    def test_two_disjoint_ranges_in_either_order_stay_covered(self):
        for order in ((0, 1), (1, 0)):
            with self.subTest(order=order):
                self.conn.execute(
                    "UPDATE ads_campaign SET context_json = context_json - 'external_sync' "
                    "WHERE id=%s", (self.campaign,),
                )
                ranges = [(_day(0), _day(4)), (_day(10), _day(14))]
                for index in order:
                    self.read(*ranges[index])
                campaign = self.campaign_row()
                self.assertEqual(coverage.recorded(campaign), ranges)
                self.assertTrue(coverage.covered(
                    self.conn, self.org, self.brand, campaign, _day(0), _day(4)))
                self.assertTrue(coverage.covered(
                    self.conn, self.org, self.brand, campaign, _day(10), _day(14)))
                self.assertEqual(
                    coverage.missing_days(
                        self.conn, self.org, self.brand, campaign, _day(0), _day(14)),
                    [_day(i).isoformat() for i in range(5, 10)],
                )

    def test_adjacent_and_overlapping_ranges_merge(self):
        self.read(_day(0), _day(4))
        self.read(_day(5), _day(7))
        self.read(_day(6), _day(9))
        self.assertEqual(coverage.served(self.campaign_row()),
                         [{"start": _day(0).isoformat(), "end": _day(9).isoformat()}])
        # The legacy single `coverage` key is folded into `ranges` and no longer stored.
        observations = self.campaign_row()["context_json"]["external_sync"]["observations"]
        self.assertNotIn("coverage", observations)

    def test_a_day_with_rows_and_no_recorded_range_is_data(self):
        self.row(_day(3))
        states = self.states(_day(2), _day(4))
        self.assertEqual(states, {_day(2): "missing", _day(3): "data", _day(4): "missing"})

    def test_a_cleanly_read_day_with_no_row_is_empty(self):
        self.read(_day(0), _day(2))
        self.row(_day(1))
        self.assertEqual(self.states(_day(0), _day(3)), {
            _day(0): "empty", _day(1): "data", _day(2): "empty", _day(3): "missing",
        })

    def test_a_monthly_budget_row_never_proves_a_day(self):
        self.row(_day(1), attribution_key=external.MONTHLY_BUDGET_ATTRIBUTION_KEY)
        self.assertEqual(self.states(_day(1), _day(1)), {_day(1): "missing"})
        self.assertTrue(coverage.gap(
            self.conn, self.org, self.brand, self.campaign_row(), _day(1), _day(1),
        )["never_synced"])

    def test_a_failed_read_keeps_earlier_ranges(self):
        self.read(_day(0), _day(4))
        self.fail_read()
        campaign = self.campaign_row()
        self.assertEqual(coverage.recorded(campaign), [(_day(0), _day(4))])
        self.assertTrue(coverage.covered(self.conn, self.org, self.brand, campaign,
                                         _day(0), _day(4)))

    def test_the_legacy_single_range_is_read_as_one_range(self):
        self.conn.execute(
            "UPDATE ads_campaign SET context_json = jsonb_set(context_json, '{external_sync}', "
            "%s::jsonb) WHERE id=%s",
            (db.jsonb({"observations": {"coverage": {"start": _day(0).isoformat(),
                                                     "end": _day(3).isoformat()}}}),
             self.campaign),
        )
        self.conn.commit()
        self.assertEqual(coverage.recorded(self.campaign_row()), [(_day(0), _day(3))])
        self.read(_day(6), _day(8))
        self.assertEqual(coverage.recorded(self.campaign_row()),
                         [(_day(0), _day(3)), (_day(6), _day(8))])

    def test_never_read_is_its_own_answer(self):
        gap = coverage.gap(self.conn, self.org, self.brand, self.campaign_row(), _day(0), _day(9))
        self.assertEqual(gap, {"never_synced": True, "missing_days": []})


class ClippedWindowTest(CoverageTestBase):
    def test_window_ends_at_the_end_date_and_starts_no_earlier_than_the_start(self):
        campaign = {"start_date": _day(0), "end_date": _day(9)}
        self.assertEqual(coverage.window(campaign, _day(11), 28), (_day(0), _day(9)))
        self.assertEqual(coverage.window(campaign, _day(5), 7), (_day(0), _day(5)))
        self.assertEqual(coverage.window({}, _day(30), 7), (_day(24), _day(30)))
        # Not started by the cutoff: an empty window, never a window before the start.
        start, end = coverage.window({"start_date": _day(20)}, _day(11), 7)
        self.assertGreater(start, end)

    def test_a_ten_day_campaign_judged_on_day_twelve_has_no_missing_day_before_its_start(self):
        self.set_dates(_day(0), _day(9))
        self.read(_day(0), _day(9))
        campaign = self.campaign_row()
        # The old 28-day window counted every day before the start as 缺.
        self.assertEqual(
            coverage.missing_days(self.conn, self.org, self.brand, campaign,
                                  _day(11) - timedelta(days=27), _day(11)), [],
        )
        # A gap inside the campaign is still missing.
        self.row(_day(2))
        self.conn.execute(
            "UPDATE ads_campaign SET context_json = context_json - 'external_sync' "
            "WHERE id=%s", (self.campaign,),
        )
        self.read(_day(0), _day(1))
        self.read(_day(3), _day(8))
        self.assertEqual(
            coverage.missing_days(self.conn, self.org, self.brand, self.campaign_row(),
                                  _day(11) - timedelta(days=27), _day(11)),
            [_day(9).isoformat()],
        )


class TriageJudgedWindowTest(CoverageTestBase):
    """Triage judges the window `coverage.window` gives: clipped to the start, ended at the end."""

    def test_an_ended_campaign_is_judged_up_to_its_end_date(self):
        # No account timezone for this platform: triage's cutoff falls back to today - 2 days.
        today = settings.today_for_org(self.conn, org_id=self.org)
        start = today - timedelta(days=13)
        end = start + timedelta(days=9)  # a ten-day campaign, judged on its day twelve
        self.set_dates(start, end)
        self.read(start, end)
        data = triage.classify(self.conn, self.org, self.brand, self.campaign)["data"]
        self.assertEqual(data["missing_days"], [])
        self.assertEqual(data["days"][0], {"day": start.isoformat(), "state": "empty"})
        self.assertEqual(data["days"][-1], {"day": end.isoformat(), "state": "empty"})
        self.assertEqual(len(data["days"]), 10)
        self.assertEqual(data["coverage"], {"start": start.isoformat(), "end": end.isoformat()})


if __name__ == "__main__":
    unittest.main()
