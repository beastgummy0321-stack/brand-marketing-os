"""app/tests/test_ads_period_grades.py — F29-I01 Contract A falsifiers for
`period_grades.grade_period`: every ad that spent inside a date window, graded by the one ruler
(`triage.grade_window`) against its own campaign's cap -- closed ads included, unknown never 0,
two currencies never summed, the window edges exact, and the missing-days list honest.
"""

import unittest
from datetime import date, timedelta
from unittest.mock import patch
from zoneinfo import ZoneInfo

from app.ads import channels, period_grades, repository, triage
from app.ads import external_repository as external
from app.brand_intelligence import repository as brands
from app.core import db

ACCOUNT_TZ = "Asia/Taipei"
START, END = date(2026, 8, 1), date(2026, 8, 31)


class _Reader:
    def accounts(self, conn, org, brand):
        return [{"account_id": "act_1", "currency": "TWD", "name": "來源",
                  "timezone_name": ACCOUNT_TZ}]


class GradePeriodTest(unittest.TestCase):
    def setUp(self):
        self.conn, self.org = db.current(), db.DEV_ORG_ID
        self.brand = brands.create_brand(
            self.conn, org_id=self.org, name="期間分級測試", actor="test", client_name=None,
        )["id"]
        patcher = patch.object(channels, "external_reader", return_value=_Reader())
        patcher.start()
        self.addCleanup(patcher.stop)
        self.campaign = self.make_campaign("活動一", "c1", cap=100)
        external.upsert_entity(
            self.conn, self.org, self.brand, self.campaign,
            {"platform": "meta", "source_account": "act_1", "native_kind": "adset",
             "native_id": "s1", "name": "組一", "parent_native_kind": "campaign",
             "parent_native_id": "c1"},
        )
        self.conn.commit()

    def make_campaign(self, name, native_id, *, cap):
        campaign = external.create_imported_campaign(
            self.conn, self.org, self.brand, name=name,
        )["id"]
        external.upsert_entity(
            self.conn, self.org, self.brand, campaign,
            {"platform": "meta", "source_account": "act_1", "native_kind": "campaign",
             "native_id": native_id},
        )
        if cap is not None:
            repository.save_campaign_target(
                self.conn, self.org, self.brand, campaign, result_kind="purchase", basis="own",
                value=cap, expected_revision=0, actor="測試員",
            )
        self.conn.commit()
        return campaign

    def ad(self, native_id, *, name, campaign=None, parent=("campaign", "c1"), status=None):
        return external.upsert_entity(
            self.conn, self.org, self.brand, campaign or self.campaign,
            {"platform": "meta", "source_account": "act_1", "native_kind": "ad",
             "native_id": native_id, "name": name, "native_status": status,
             "parent_native_kind": parent[0], "parent_native_id": parent[1]},
        )["id"]

    def obs(self, entity_id, day, *, spend, result_count, currency="TWD", campaign=None):
        external.upsert_observation(
            self.conn, self.org, self.brand, campaign or self.campaign,
            {"entity_id": entity_id, "day": day, "metric_scope": "ad",
             "attribution_key": f"{day}", "currency": currency, "source": "meta",
             "spend": spend, "impressions": 100, "purchases": None},
            result_kind="purchase", result_count=result_count, result_action="omni_purchase",
            result_attribution="7d_click+1d_view",
        )
        self.conn.commit()

    def days(self, entity_id, n, *, spend, result_count, first=START, **kwargs):
        for offset in range(n):
            self.obs(entity_id, first + timedelta(days=offset), spend=spend,
                     result_count=result_count, **kwargs)

    def rows(self, start=START, end=END):
        return {row["name"]: row for row in period_grades.grade_period(
            self.conn, self.org, self.brand, start, end)}

    # -- grades ---------------------------------------------------------------------------------

    def test_observed_definition_is_preserved_and_target_kind_mismatch_is_not_graded(self):
        ad = self.ad("definition", name="Definition")
        self.days(ad, 10, spend=20, result_count=1)
        repository.save_campaign_target(
            self.conn, self.org, self.brand, self.campaign, result_kind="lead", basis="own",
            value=100, expected_revision=1, actor="test",
        )
        self.conn.commit()
        row = self.rows()["Definition"]
        self.assertEqual((row["grade"], row["reason_code"]),
                         ("insufficient", "result_kind_mismatch"))
        self.assertEqual((row["result_kind"], row["result_action"], row["result_attribution"]),
                         ("purchase", "omni_purchase", "7d_click+1d_view"))
        self.assertEqual(row["result_window"], {"start": START.isoformat(), "end": END.isoformat()})
        self.assertEqual((row["results"], row["cost_per_result"], row["spend"]), (10, 20, 200))
        self.assertIsNone(row["result_reason"])

    def test_matched_definition_remains_on_target(self):
        ad = self.ad("matched", name="Matched")
        self.days(ad, 10, spend=20, result_count=1)
        row = self.rows()["Matched"]
        self.assertEqual(row["grade"], "on_target")
        self.assertEqual((row["result_kind"], row["result_action"], row["result_attribution"]),
                         ("purchase", "omni_purchase", "7d_click+1d_view"))
        self.assertIsNone(row["result_reason"])

    def test_every_spending_ad_is_graded_closed_ones_included(self):
        cheap = self.ad("a1", name="便宜", parent=("adset", "s1"))
        wasted = self.ad("a2", name="沒賣", status="PAUSED")
        self.days(cheap, 10, spend=50, result_count=1)          # 500 / 10 = 50 <= 100
        self.days(wasted, 7, spend=50, result_count=0)          # 350 >= 3 x 100, 0 sold
        rows = self.rows()
        self.assertEqual(set(rows), {"便宜", "沒賣"})
        self.assertEqual(
            {k: rows["便宜"][k] for k in ("grade", "grade_label", "spend", "results",
                                           "cost_per_result", "cap", "group_name", "origin")},
            {"grade": "on_target", "grade_label": "划算", "spend": 500.0, "results": 10.0,
             "cost_per_result": 50.0, "cap": 100.0, "group_name": "組一", "origin": "imported"},
        )
        self.assertEqual((rows["沒賣"]["grade"], rows["沒賣"]["grade_label"]),
                         ("wasted", "沒賣出"))
        self.assertIsNone(rows["沒賣"]["group_name"])
        self.assertEqual(rows["沒賣"]["campaign_name"], "活動一")
        self.assertEqual(rows["便宜"]["currency"], "TWD")

    def test_the_same_ruler_as_triage(self):
        # Watch band and over: the grade comes from `triage.grade_window`, never a copy.
        watch = self.ad("a1", name="偏貴")
        over = self.ad("a2", name="太貴")
        self.days(watch, 4, spend=110, result_count=1)          # 110 <= 120
        self.days(over, 4, spend=130, result_count=1)           # 130 > 120
        rows = self.rows()
        self.assertEqual(rows["偏貴"]["grade_label"], "偏貴")
        self.assertEqual(rows["太貴"]["grade_label"], "太貴")
        with patch.object(triage, "grade_window", return_value=("over", "太貴", None)) as spy:
            period_grades.grade_period(self.conn, self.org, self.brand, START, END)
        self.assertEqual(spy.call_count, 2)

    def test_thin_sold_ad_is_graded_with_its_sample_shown(self):
        # F48 Contract R: a known cost is always graded; the sample size is a shown flag.
        thin = self.ad("a1", name="賣得少")
        self.days(thin, 2, spend=50, result_count=1)            # 100 spent, 2 results
        row = self.rows()["賣得少"]
        self.assertEqual((row["grade"], row["grade_label"], row["reason_code"]),
                         ("on_target", "划算", None))
        self.assertEqual(row["spend"], 100.0)
        self.assertEqual({k: row["sample"][k] for k in ("sales", "few", "too_new")},
                         {"sales": 2, "few": True, "too_new": True})

    def test_the_four_ruler_cases(self):
        one_sale = self.ad("a1", name="一筆")
        too_new = self.ad("a2", name="剛開始")
        wasted = self.ad("a3", name="沒賣出")
        mixed = self.ad("a4", name="兩種幣")
        self.days(one_sale, 1, spend=60, result_count=1)        # 60 <= 100, 1 sale
        self.days(too_new, 4, spend=50, result_count=0)         # 200 = 2 x cap, 0 sold
        self.days(wasted, 6, spend=50, result_count=0)          # 300 = 3 x cap, 0 sold
        self.days(mixed, 2, spend=50, result_count=1)
        self.days(mixed, 2, spend=5, result_count=1, first=START + timedelta(days=5),
                  currency="USD")
        rows = self.rows()

        def seen(name):
            row = rows[name]
            return row["grade"], row["grade_label"], row["reason_code"]

        self.assertEqual(seen("一筆"), ("on_target", "划算", None))
        self.assertTrue(rows["一筆"]["sample"]["few"])
        self.assertEqual(seen("剛開始"), ("insufficient", "剛開始、數字還不夠", "too_new"))
        self.assertEqual(rows["剛開始"]["sample"]["sales"], 0)
        self.assertFalse(rows["剛開始"]["sample"]["few"])
        self.assertEqual(seen("沒賣出"), ("wasted", "沒賣出", "spend_over_target_no_result"))
        self.assertEqual(seen("兩種幣"), ("insufficient", "資料不足", "mixed_currency"))
        self.assertIsNone(rows["兩種幣"]["sample"]["sales"])

    def test_unknown_results_read_no_data_never_zero(self):
        unknown = self.ad("a1", name="不知道")
        self.days(unknown, 5, spend=100, result_count=None)     # 500 spent, results unknown
        row = self.rows()["不知道"]
        self.assertEqual((row["grade"], row["grade_label"]), ("insufficient", "資料不足"))
        self.assertIsNone(row["results"])
        self.assertIsNone(row["cost_per_result"])
        self.assertEqual(row["spend"], 500.0)

    def test_mixed_currencies_read_no_data_and_are_never_summed(self):
        mixed = self.ad("a1", name="兩種幣")
        self.days(mixed, 5, spend=100, result_count=2)
        self.days(mixed, 5, spend=10, result_count=2, first=START + timedelta(days=10),
                  currency="USD")
        row = self.rows()["兩種幣"]
        self.assertEqual((row["grade"], row["grade_label"]), ("insufficient", "資料不足"))
        self.assertIsNone(row["spend"])
        self.assertIsNone(row["results"])
        self.assertIsNone(row["currency"])
        summary = period_grades.summarize(list(self.rows().values()))
        self.assertIsNone(summary["spent"])

    def test_two_ads_in_two_currencies_never_sum_the_month(self):
        other = self.make_campaign("美金活動", "c2", cap=10)
        twd = self.ad("a1", name="台幣")
        usd = self.ad("b1", name="美金", campaign=other, parent=("campaign", "c2"))
        self.days(twd, 10, spend=50, result_count=1)
        self.days(usd, 10, spend=5, result_count=1, currency="USD", campaign=other)
        rows = self.rows()
        self.assertEqual(rows["台幣"]["spend"], 500.0)
        self.assertEqual(rows["美金"]["spend"], 50.0)
        self.assertEqual(rows["美金"]["cap"], 10.0)  # each ad against its own campaign's cap
        self.assertEqual(rows["台幣"]["currency"], "TWD")
        self.assertEqual(rows["美金"]["currency"], "USD")
        self.assertEqual(rows["台幣"]["grade"], "on_target")
        self.assertEqual(rows["美金"]["grade"], "insufficient")
        self.assertEqual(rows["美金"]["reason_code"], "cap_currency_mismatch")
        self.assertEqual(rows["美金"]["cap_comparison"]["currency"], "TWD")
        self.assertEqual(rows["美金"]["cap_comparison"]["source"], "user")
        summary = period_grades.summarize(list(rows.values()))
        self.assertIsNone(summary["spent"])
        on_target = next(b for b in summary["buckets"] if b["grade"] == "on_target")
        self.assertEqual(on_target["count"], 1)
        self.assertEqual(on_target["amount"], 500.0)
        insufficient = next(b for b in summary["buckets"] if b["grade"] == "insufficient")
        self.assertEqual(insufficient["count"], 1)
        self.assertEqual(insufficient["amount"], 50.0)

    def test_no_cap_is_not_judged(self):
        uncapped = self.make_campaign("沒上限", "c3", cap=None)
        ad = self.ad("x1", name="沒上限廣告", campaign=uncapped, parent=("campaign", "c3"))
        self.days(ad, 7, spend=500, result_count=0, campaign=uncapped)
        row = self.rows()["沒上限廣告"]
        self.assertEqual((row["grade"], row["grade_label"]), ("no_target", "未判斷"))
        self.assertIsNone(row["cap"])

    # -- window -----------------------------------------------------------------------------------

    def test_window_edges_are_exact(self):
        inside = self.ad("a1", name="月內")
        outside = self.ad("a2", name="月外")
        self.obs(inside, START, spend=40, result_count=1)
        self.obs(inside, END, spend=60, result_count=1)
        self.obs(inside, START - timedelta(days=1), spend=999, result_count=0)
        self.obs(inside, END + timedelta(days=1), spend=999, result_count=0)
        self.obs(outside, START - timedelta(days=1), spend=500, result_count=0)
        rows = self.rows()
        self.assertEqual(set(rows), {"月內"})
        self.assertEqual(rows["月內"]["spend"], 100.0)
        self.assertEqual(rows["月內"]["results"], 2.0)

    def test_an_ad_with_rows_but_no_spend_is_not_listed(self):
        idle = self.ad("a1", name="沒花錢")
        self.days(idle, 3, spend=0, result_count=0)
        self.assertEqual(self.rows(), {})

    # -- summary / missing ----------------------------------------------------------------------

    def test_summarize_keeps_every_bucket_in_order(self):
        cheap = self.ad("a1", name="便宜")
        wasted = self.ad("a2", name="沒賣")
        self.days(cheap, 10, spend=50, result_count=1)
        self.days(wasted, 7, spend=50, result_count=0)
        summary = period_grades.summarize(
            period_grades.grade_period(self.conn, self.org, self.brand, START, END),
        )
        self.assertEqual([b["grade"] for b in summary["buckets"]], list(period_grades.BUCKET_ORDER))
        self.assertEqual(summary["spent"], 850.0)
        by_grade = {b["grade"]: b for b in summary["buckets"]}
        self.assertEqual((by_grade["on_target"]["count"], by_grade["on_target"]["amount"]),
                         (1, 500.0))
        self.assertEqual(by_grade["wasted"]["ads"][0]["name"], "沒賣")
        self.assertEqual((by_grade["watch"]["count"], by_grade["watch"]["amount"]), (0, 0))

    def test_summarize_with_no_rows_is_unknown_not_zero(self):
        self.assertIsNone(period_grades.summarize([])["spent"])

    def test_missing_days_are_unsynced_gaps_only(self):
        ad = self.ad("a1", name="缺天")
        for offset in (0, 1, 4):  # rows on 08-01, 08-02, 08-05
            self.obs(ad, START + timedelta(days=offset), spend=50, result_count=1)
        # Synced coverage covers 08-04 onward: 08-03 has no row and was never synced -> missing;
        # 08-06.. have no row but were synced (no delivery) -> not missing.
        external.record_sync(
            self.conn, self.org, self.brand, self.campaign, section="observations",
            state={"last_success_at": db.now_utc().isoformat(),
                   "coverage": {"start": "2026-08-04", "end": "2026-08-31"}},
        )
        self.conn.commit()
        self.assertEqual(
            period_grades.missing(self.conn, self.org, self.brand, START, END),
            [{"campaign_id": self.campaign, "name": "活動一", "missing_days": ["2026-08-03"]}],
        )

    def test_missing_days_stop_at_the_last_complete_day(self):
        cutoff = (db.now_utc().astimezone(ZoneInfo(ACCOUNT_TZ)) - timedelta(days=1)).date()
        month_start = cutoff.replace(day=1)
        month_end = (month_start + timedelta(days=32)).replace(day=1) - timedelta(days=1)
        ad = self.ad("a1", name="本月")
        self.obs(ad, month_start, spend=50, result_count=1)
        gaps = period_grades.missing(self.conn, self.org, self.brand, month_start, month_end)
        expected = [(month_start + timedelta(days=i)).isoformat()
                    for i in range(1, (cutoff - month_start).days + 1)]
        self.assertEqual(gaps[0]["missing_days"] if gaps else [], expected)


if __name__ == "__main__":
    unittest.main()
