"""app/tests/test_ads_month_summary.py — F27-I07 Contract G falsifiers: calendar-month spend/
results (active AND closed ads), currency-mix honesty, verdicts, the like-for-like orders
comparison (and its own null-on-failure case), `closed_this_month` vs tracking start, the three
suggestion kinds, and dismissal per month.

Fixture style follows `test_ads_triage_queue.py`: real `ads_external_entity`/`ads_external_daily`
rows through `external_repository`'s public writers, no adapter/platform patching needed --
`triage._account_cutoff` falls back to `today - 2 days` on its own whenever a campaign's bound
account can't actually be read (`channels.external_reader("meta")` finds no bound account for a
brand that never connected one), the same safe path every campaign below relies on.
"""

import unittest
from datetime import UTC, date, datetime, timedelta

from app.ads import external_repository as external
from app.ads import month_summary, repository, triage, triage_scale
from app.brand_intelligence import repository as brands
from app.core import db
from app.core import settings as coresettings
from app.orders import repository as orders_repo


def _month(conn, org):
    return coresettings.today_for_org(conn, org_id=org).strftime("%Y-%m")


def _month_start(conn, org):
    return date.fromisoformat(_month(conn, org) + "-01")


def _campaign(conn, org, brand, *, name, native_id):
    campaign_id = external.create_imported_campaign(conn, org, brand, name=name)["id"]
    external.upsert_entity(
        conn, org, brand, campaign_id,
        {"platform": "meta", "source_account": "act_1", "native_kind": "campaign",
         "native_id": native_id},
    )
    return campaign_id


def _ad(conn, org, brand, campaign_id, native_id, *, campaign_native_id, status="ACTIVE",
        name=None):
    return external.upsert_entity(
        conn, org, brand, campaign_id,
        {"platform": "meta", "source_account": "act_1", "native_kind": "ad",
         "native_id": native_id, "name": name or native_id, "native_status": status,
         "parent_native_kind": "campaign", "parent_native_id": campaign_native_id},
    )


def _obs(conn, org, brand, campaign_id, ad_id, day, *, spend, count, key):
    external.upsert_observation(
        conn, org, brand, campaign_id,
        {"entity_id": ad_id, "day": day, "metric_scope": "ad", "attribution_key": key,
         "currency": "TWD", "source": "meta", "spend": spend, "impressions": 100,
         "purchases": None},
        result_kind="purchase", result_count=count, result_action="omni_purchase",
        result_attribution="7d_click+1d_view",
    )
    conn.commit()


class MonthSummarySpendVerdictTest(unittest.TestCase):
    def setUp(self):
        self.conn, self.org = db.current(), db.DEV_ORG_ID
        self.brand = brands.create_brand(
            self.conn, org_id=self.org, name="每月回顧金額測試", actor="test", client_name=None,
        )["id"]
        self.month = _month(self.conn, self.org)
        self.day = _month_start(self.conn, self.org)

        # 達標：一則主廣告 + 一則已關閉廣告，兩則都要算進整月合計（Contract G）。
        self.met = _campaign(self.conn, self.org, self.brand, name="達標活動", native_id="cmet")
        ad_met = _ad(self.conn, self.org, self.brand, self.met, "ad_met",
                     campaign_native_id="cmet")
        ad_met_closed = _ad(self.conn, self.org, self.brand, self.met, "ad_met_closed",
                             campaign_native_id="cmet", status="PAUSED")
        _obs(self.conn, self.org, self.brand, self.met, ad_met["id"], self.day,
             spend=50, count=10, key="a")
        _obs(self.conn, self.org, self.brand, self.met, ad_met_closed["id"], self.day,
             spend=20, count=0, key="b")
        repository.save_campaign_target(
            self.conn, self.org, self.brand, self.met, result_kind="purchase", basis="own",
            value=10, expected_revision=0, actor="test",
        )

        # 未達標。
        self.missed = _campaign(
            self.conn, self.org, self.brand, name="未達標活動", native_id="cmiss",
        )
        ad_missed = _ad(self.conn, self.org, self.brand, self.missed, "ad_missed",
                         campaign_native_id="cmiss")
        _obs(self.conn, self.org, self.brand, self.missed, ad_missed["id"], self.day,
             spend=200, count=10, key="a")
        repository.save_campaign_target(
            self.conn, self.org, self.brand, self.missed, result_kind="purchase", basis="own",
            value=10, expected_revision=0, actor="test",
        )

        # 尚未判斷：花費／成果都有，但沒有目標可比。
        self.unjudged = _campaign(
            self.conn, self.org, self.brand, name="沒目標活動", native_id="cnotarget",
        )
        ad_unjudged = _ad(self.conn, self.org, self.brand, self.unjudged, "ad_unjudged",
                           campaign_native_id="cnotarget")
        _obs(self.conn, self.org, self.brand, self.unjudged, ad_unjudged["id"], self.day,
             spend=30, count=3, key="a")

    def test_calendar_month_includes_closed_ads_and_verdicts(self):
        summary = month_summary.get_summary(self.conn, self.org, self.brand, self.month)
        by_id = {row["campaign_id"]: row for row in summary["campaigns"]}

        met_row = by_id[self.met]
        self.assertEqual(met_row["spend"], 70)  # 50（主廣告）+ 20（已關閉廣告）
        self.assertEqual(met_row["result_count"], 10)
        self.assertEqual(met_row["cost_per_result"], 7)
        self.assertEqual(met_row["result_label"], "購買")
        self.assertEqual(met_row["target"], 10)
        self.assertEqual(met_row["verdict"], "met")

        missed_row = by_id[self.missed]
        self.assertEqual(missed_row["spend"], 200)
        self.assertEqual(missed_row["cost_per_result"], 20)
        self.assertEqual(missed_row["verdict"], "missed")

        unjudged_row = by_id[self.unjudged]
        self.assertEqual(unjudged_row["spend"], 30)
        self.assertIsNone(unjudged_row["target"])
        self.assertEqual(unjudged_row["verdict"], "unjudged")

        self.assertEqual(summary["currency"], "TWD")
        self.assertEqual(summary["total_spend"], 70 + 200 + 30)
        self.assertEqual(summary["month"], self.month)
        self.assertGreaterEqual(summary["days_elapsed"], 1)
        self.assertGreaterEqual(summary["days_covered"], summary["days_elapsed"])


class MonthSummaryCurrencyMixTest(unittest.TestCase):
    def test_mixed_currency_nulls_spend_and_verdict(self):
        conn, org = db.current(), db.DEV_ORG_ID
        brand = brands.create_brand(
            conn, org_id=org, name="每月回顧混幣測試", actor="test", client_name=None,
        )["id"]
        month = _month(conn, org)
        day = _month_start(conn, org)
        campaign = _campaign(conn, org, brand, name="混幣活動", native_id="cmix")
        ad = _ad(conn, org, brand, campaign, "ad_mix", campaign_native_id="cmix")
        external.upsert_observation(
            conn, org, brand, campaign,
            {"entity_id": ad["id"], "day": day, "metric_scope": "ad", "attribution_key": "a",
             "currency": "TWD", "source": "meta", "spend": 50, "impressions": 100,
             "purchases": None},
            result_kind="purchase", result_count=5, result_action="omni_purchase",
            result_attribution="7d_click+1d_view",
        )
        external.upsert_observation(
            conn, org, brand, campaign,
            {"entity_id": ad["id"], "day": day + timedelta(days=1), "metric_scope": "ad",
             "attribution_key": "b", "currency": "USD", "source": "meta", "spend": 5,
             "impressions": 100, "purchases": None},
            result_kind="purchase", result_count=1, result_action="omni_purchase",
            result_attribution="7d_click+1d_view",
        )
        conn.commit()
        repository.save_campaign_target(
            conn, org, brand, campaign, result_kind="purchase", basis="own", value=10,
            expected_revision=0, actor="test",
        )

        summary = month_summary.get_summary(conn, org, brand, month)
        row = summary["campaigns"][0]
        self.assertIsNone(row["spend"])
        self.assertIsNone(row["cost_per_result"])
        self.assertEqual(row["verdict"], "unjudged")
        self.assertIsNone(summary["currency"])
        self.assertIsNone(summary["total_spend"])


class MonthSummaryOrdersTest(unittest.TestCase):
    def setUp(self):
        self.conn, self.org = db.current(), db.DEV_ORG_ID
        self.brand = brands.create_brand(
            self.conn, org_id=self.org, name="每月回顧訂單測試", actor="test", client_name=None,
        )["id"]
        self.month = _month(self.conn, self.org)
        self.today = coresettings.today_for_org(self.conn, org_id=self.org)
        self.month_start = self.today.replace(day=1)

    def _save(self, number, amount, day, **changes):
        orders_repo.save_orders(self.conn, self.brand, [{
            "order_number": number, "order_date": day.isoformat(), "total_amount": amount,
            "refunded_amount": 0, "financial_status": "paid", "order_status": "open",
            "billing_email": "fictional-sensitive@example.invalid", **changes,
        }], source="easystore_xlsx", actor="test")

    def test_like_for_like_comparison_and_change_pct(self):
        self._save("this", 1000, self.today)
        previous_start = (self.month_start - timedelta(days=1)).replace(day=1)
        self._save("previous", 500, previous_start)

        summary = month_summary.get_summary(self.conn, self.org, self.brand, self.month)
        orders_view = summary["orders"]
        self.assertIsNotNone(orders_view)
        self.assertEqual(orders_view["this_net"], 1000)
        self.assertEqual(orders_view["this_count"], 1)
        self.assertEqual(orders_view["previous_net"], 500)
        self.assertEqual(orders_view["previous_count"], 1)
        self.assertEqual(orders_view["change_pct"], 1.0)

    def test_unknown_net_amount_nulls_change_pct_without_failing(self):
        self._save("unknown", None, self.today, financial_status=None)

        summary = month_summary.get_summary(self.conn, self.org, self.brand, self.month)
        orders_view = summary["orders"]
        self.assertIsNotNone(orders_view)
        self.assertIsNone(orders_view["this_net"])
        self.assertEqual(orders_view["this_count"], 1)
        self.assertIsNone(orders_view["change_pct"])

    def test_future_month_has_no_orders_window(self):
        future_month = f"{self.today.year + 1}-01"
        summary = month_summary.get_summary(self.conn, self.org, self.brand, future_month)
        self.assertIsNone(summary["orders"])
        self.assertEqual(summary["days_elapsed"], 0)


class MonthSummaryClosedTrackingTest(unittest.TestCase):
    def setUp(self):
        self.conn, self.org = db.current(), db.DEV_ORG_ID
        self.brand = brands.create_brand(
            self.conn, org_id=self.org, name="每月回顧關閉追蹤測試", actor="test", client_name=None,
        )["id"]
        self.month = _month(self.conn, self.org)
        self.campaign = _campaign(self.conn, self.org, self.brand, name="關閉追蹤活動",
                                   native_id="cclosed")

    def test_null_before_tracking_started(self):
        # 直接改寫 `status_changed_at`，不依賴測試當下真正的日期跟遷移檔日期常數是否還吻合
        # （那顆常數只在品牌完全沒有任何轉換紀錄時才會被讀到，見 `_closed_tracking_since`）。
        _ad(self.conn, self.org, self.brand, self.campaign, "ad_old",
            campaign_native_id="cclosed")
        closed = _ad(self.conn, self.org, self.brand, self.campaign, "ad_old",
                      campaign_native_id="cclosed", status="PAUSED")
        self.assertIsNotNone(closed["status_changed_at"])
        self.conn.execute(
            "UPDATE ads_external_entity SET status_changed_at=%s "
            "WHERE org_id=%s AND brand_id=%s AND id=%s",
            (datetime(2026, 5, 15, tzinfo=UTC), self.org, self.brand, closed["id"]),
        )
        self.conn.commit()

        summary = month_summary.get_summary(self.conn, self.org, self.brand, "2026-04")
        self.assertIsNone(summary["closed_this_month"])
        self.assertEqual(summary["closed_tracking_since"], "2026-05-15")

    def test_counts_a_real_transition_this_month(self):
        ad = _ad(self.conn, self.org, self.brand, self.campaign, "ad_transition",
                  campaign_native_id="cclosed")
        self.assertIsNone(ad["status_changed_at"])
        closed = _ad(self.conn, self.org, self.brand, self.campaign, "ad_transition",
                      campaign_native_id="cclosed", status="PAUSED")
        self.assertIsNotNone(closed["status_changed_at"])

        summary = month_summary.get_summary(self.conn, self.org, self.brand, self.month)
        self.assertEqual(summary["closed_this_month"], 1)
        today = coresettings.today_for_org(self.conn, org_id=self.org)
        self.assertEqual(summary["closed_tracking_since"], today.isoformat())

    def test_falls_back_to_migration_date_when_never_tracked(self):
        # 這個品牌從沒有任何廣告轉換過狀態——`closed_tracking_since` 退回遷移檔本身的日期
        # （`supabase/migrations/20260922000001_ads_runtime_events.sql`），不是「今天」算出來的。
        summary = month_summary.get_summary(self.conn, self.org, self.brand, self.month)
        self.assertEqual(summary["closed_tracking_since"], "2026-09-22")


class MonthSummarySuggestionsTest(unittest.TestCase):
    def setUp(self):
        self.conn, self.org = db.current(), db.DEV_ORG_ID
        self.brand = brands.create_brand(
            self.conn, org_id=self.org, name="每月回顧建議測試", actor="test", client_name=None,
        )["id"]
        self.month = _month(self.conn, self.org)
        self.cutoff = coresettings.today_for_org(self.conn, org_id=self.org) - timedelta(days=2)

        # --- 活動 A：素材待補（refresh）——3 則活躍廣告，可讀出結果的只剩 1 則。
        self.refresh_campaign = _campaign(
            self.conn, self.org, self.brand, name="待補素材活動", native_id="cref",
        )
        external.record_sync(
            self.conn, self.org, self.brand, self.refresh_campaign, section="observations",
            state={
                "last_success_at": db.now_utc().isoformat(),
                "coverage": {"start": (self.cutoff - timedelta(days=90)).isoformat(),
                             "end": self.cutoff.isoformat()},
            },
        )
        repository.save_campaign_target(
            self.conn, self.org, self.brand, self.refresh_campaign, result_kind="purchase",
            basis="own", value=100, expected_revision=0, actor="test",
        )
        ad_worse = _ad(self.conn, self.org, self.brand, self.refresh_campaign, "ad_worse",
                        campaign_native_id="cref")
        for offset in range(7):
            _obs(self.conn, self.org, self.brand, self.refresh_campaign, ad_worse["id"],
                 self.cutoff - timedelta(days=7 + offset), spend=100, count=10,
                 key=f"prev{offset}")
        for offset in range(7):
            _obs(self.conn, self.org, self.brand, self.refresh_campaign, ad_worse["id"],
                 self.cutoff - timedelta(days=offset), spend=150, count=10, key=f"cur{offset}")
        _ad(self.conn, self.org, self.brand, self.refresh_campaign, "ad_thin1",
            campaign_native_id="cref")
        _ad(self.conn, self.org, self.brand, self.refresh_campaign, "ad_thin2",
            campaign_native_id="cref")

        # --- 活動 B：廣告過多（cleanup）——每日預算 300、目標 100，撐得起 1 則，卻有 3 則在投。
        self.cleanup_campaign = _campaign(
            self.conn, self.org, self.brand, name="廣告過多活動", native_id="ccln",
        )
        external.upsert_entity(
            self.conn, self.org, self.brand, self.cleanup_campaign,
            {"platform": "meta", "source_account": "act_1", "native_kind": "campaign",
             "native_id": "ccln", "budget_type": "daily", "budget_amount": 300,
             "currency": "TWD"},
        )
        external.record_sync(
            self.conn, self.org, self.brand, self.cleanup_campaign, section="observations",
            state={
                "last_success_at": db.now_utc().isoformat(),
                "coverage": {"start": (self.cutoff - timedelta(days=90)).isoformat(),
                             "end": self.cutoff.isoformat()},
            },
        )
        repository.save_campaign_target(
            self.conn, self.org, self.brand, self.cleanup_campaign, result_kind="purchase",
            basis="own", value=100, expected_revision=0, actor="test",
        )
        for idx, daily_spend in enumerate((10, 20, 30)):
            ad = _ad(self.conn, self.org, self.brand, self.cleanup_campaign, f"ad_cln{idx}",
                     campaign_native_id="ccln")
            for offset in range(7):
                _obs(self.conn, self.org, self.brand, self.cleanup_campaign, ad["id"],
                     self.cutoff - timedelta(days=offset), spend=daily_spend, count=None,
                     key=f"cln{idx}-{offset}")

        # --- 活動 C：沒有目標（no_target）——有一則活躍廣告，從沒設過目標。
        self.no_target_campaign = _campaign(
            self.conn, self.org, self.brand, name="沒目標活動", native_id="cnt",
        )
        _ad(self.conn, self.org, self.brand, self.no_target_campaign, "ad_nt",
            campaign_native_id="cnt")

        # Contract I: the daily periodic job keeps the queue fresh; `month_summary.py` only ever
        # reads it back (`triage.get_queue`, never writes) -- the fixture stands in for "today's
        # refresh already ran" the same way production relies on the periodic job having run.
        triage.refresh_queue(self.conn, self.org, self.brand)

    def test_three_suggestion_kinds(self):
        summary = month_summary.get_summary(self.conn, self.org, self.brand, self.month)
        by_kind = {s["kind"]: s for s in summary["suggestions"]}

        self.assertIn("refresh", by_kind)
        refresh = by_kind["refresh"]
        self.assertEqual(refresh["campaign_id"], self.refresh_campaign)
        needed = max(triage_scale.MIN_ACTIVE_ADS_FOR_REFRESH_GATE - 1, 1)
        self.assertEqual(refresh["title"], f"補 {needed} 則新素材")
        self.assertEqual(refresh["key"], f"refresh:{self.refresh_campaign}")

        self.assertIn("cleanup", by_kind)
        cleanup = by_kind["cleanup"]
        self.assertEqual(cleanup["campaign_id"], self.cleanup_campaign)
        self.assertEqual(cleanup["title"], "清掉 2 則沒被投放的廣告")
        self.assertEqual(cleanup["key"], f"cleanup:{self.cleanup_campaign}")

        self.assertIn("no_target", by_kind)
        no_target = by_kind["no_target"]
        self.assertEqual(no_target["campaign_id"], self.no_target_campaign)
        self.assertEqual(no_target["title"], "替「沒目標活動」設目標")
        self.assertEqual(no_target["key"], f"no_target:{self.no_target_campaign}")

        # correction 4: cleanup 活動同時具備 refresh 的資格條件，但佇列先讓 cleanup 蓋過。
        self.assertFalse(
            any(s["kind"] == "refresh" and s["campaign_id"] == self.cleanup_campaign
                for s in summary["suggestions"])
        )

    def test_dismiss_removes_only_that_suggestion_for_that_month(self):
        key = f"no_target:{self.no_target_campaign}"
        month_summary.dismiss_suggestion(self.conn, self.org, self.brand, self.month, key)
        # 冪等：再叫一次不噴錯。
        month_summary.dismiss_suggestion(self.conn, self.org, self.brand, self.month, key)

        summary = month_summary.get_summary(self.conn, self.org, self.brand, self.month)
        kinds = {s["kind"] for s in summary["suggestions"]}
        self.assertNotIn("no_target", kinds)
        self.assertIn("refresh", kinds)
        self.assertIn("cleanup", kinds)

        other_month = (
            date.fromisoformat(self.month + "-01") - timedelta(days=32)
        ).strftime("%Y-%m")
        campaign = repository.get_campaign(
            self.conn, self.org, self.brand, self.no_target_campaign,
        )
        dismissed = (campaign["context_json"] or {}).get("month_dismissed") or {}
        self.assertEqual(dismissed.get(self.month), [key])
        self.assertNotIn(other_month, dismissed)

    def test_dismiss_rejects_unknown_key_shape(self):
        with self.assertRaises(ValueError):
            month_summary.dismiss_suggestion(
                self.conn, self.org, self.brand, self.month, "not-a-real-key",
            )
        with self.assertRaises(ValueError):
            month_summary.dismiss_suggestion(
                self.conn, self.org, self.brand, self.month, "refresh:unknown-campaign",
            )


class MonthSummaryRouteTest(unittest.TestCase):
    def test_get_and_dismiss_routes_are_wired(self):
        from fastapi.testclient import TestClient

        from app import main

        conn, org = db.current(), db.DEV_ORG_ID
        brand = brands.create_brand(
            conn, org_id=org, name="每月回顧路由測試", actor="test", client_name=None,
        )["id"]
        month = _month(conn, org)
        campaign = _campaign(conn, org, brand, name="路由測試活動", native_id="croute")
        _ad(conn, org, brand, campaign, "ad_route", campaign_native_id="croute")
        conn.commit()  # `TestClient` 走另一條連線（`_db_connection_middleware`），要先落地。

        client = TestClient(main.app)
        response = client.get(f"/api/ads/brands/{brand}/month-summary?month={month}")
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertEqual(body["month"], month)
        self.assertEqual(len(body["campaigns"]), 1)

        key = f"no_target:{campaign}"
        dismiss = client.post(
            f"/api/ads/brands/{brand}/month-summary/suggestions/{key}/dismiss?month={month}"
        )
        self.assertEqual(dismiss.status_code, 200, dismiss.text)

        bad = client.post(
            f"/api/ads/brands/{brand}/month-summary/suggestions/bad-key/dismiss?month={month}"
        )
        self.assertEqual(bad.status_code, 422, bad.text)


if __name__ == "__main__":
    unittest.main()
