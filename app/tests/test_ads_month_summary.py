"""app/tests/test_ads_month_summary.py — F27-I07 Contract G falsifiers: calendar-month spend/
results (active AND closed ads), currency-mix honesty, verdicts, the like-for-like orders
comparison (and its own null-on-failure case), `closed_this_month` vs tracking start, the
suggestion kinds (F46-I05 adds `next_plan`), and dismissal per month.

Fixture style follows `test_ads_triage_queue.py`: real `ads_external_entity`/`ads_external_daily`
rows through `external_repository`'s public writers, no adapter/platform patching needed --
`triage._account_cutoff` falls back to `today - 2 days` on its own whenever a campaign's bound
account can't actually be read (`channels.external_reader("meta")` finds no bound account for a
brand that never connected one), the same safe path every campaign below relies on.
"""

import unittest
from datetime import UTC, date, datetime, timedelta

from app.ads import external_repository as external
from app.ads import month_summary, plan, repository, triage, triage_scale
from app.brand_intelligence import repository as brands
from app.core import db
from app.core import settings as coresettings
from app.orders import repository as orders_repo


def _month(conn, org):
    return coresettings.today_for_org(conn, org_id=org).strftime("%Y-%m")


def _month_start(conn, org):
    return date.fromisoformat(_month(conn, org) + "-01")


def _campaign(conn, org, brand, *, name, native_id, objective=None):
    campaign_id = external.create_imported_campaign(conn, org, brand, name=name)["id"]
    root = {"platform": "meta", "source_account": "act_1", "native_kind": "campaign",
            "native_id": native_id}
    if objective is not None:
        root["objective"] = objective
    external.upsert_entity(conn, org, brand, campaign_id, root)
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
        # F27-I27: 根 entity 的 `objective` 帶 Meta 銷售類值，驗證 `campaign_objective` 走
        # `repository.campaign_objective_family` 這一條規則，不再是前端自己猜的關鍵字。
        self.met = _campaign(
            self.conn, self.org, self.brand, name="達標活動", native_id="cmet",
            objective="OUTCOME_SALES",
        )
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
        # F27-I27: `campaign_objective` is the SAME family `repository.campaign_objective_family`
        # already serves campaign cards/triage items with -- not a second, frontend-side guess.
        self.assertEqual(met_row["campaign_objective"], "sales")

        missed_row = by_id[self.missed]
        self.assertEqual(missed_row["spend"], 200)
        self.assertEqual(missed_row["cost_per_result"], 20)
        self.assertEqual(missed_row["verdict"], "missed")
        # No objective was ever synced for this campaign's root entity -> "other", never a guess.
        self.assertEqual(missed_row["campaign_objective"], "other")

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
        self._save("this", 1000, self.month_start)
        previous_start = (self.month_start - timedelta(days=1)).replace(day=1)
        self._save("previous", 500, previous_start)

        summary = month_summary.get_summary(self.conn, self.org, self.brand, self.month)
        orders_view = summary["orders"]
        self.assertIsNotNone(orders_view)
        self.assertEqual(orders_view["this_net"], 1000)
        self.assertEqual(orders_view["this_count"], 1)
        self.assertEqual(orders_view["previous_net"], 500)
        self.assertEqual(orders_view["previous_count"], 1)
        # Import default is not currency/coverage proof.
        self.assertIsNone(orders_view["change_pct"])

    def test_unknown_net_amount_nulls_change_pct_without_failing(self):
        self._save("unknown", None, self.month_start, financial_status=None)

        summary = month_summary.get_summary(self.conn, self.org, self.brand, self.month)
        orders_view = summary["orders"]
        self.assertIsNotNone(orders_view)
        self.assertIsNone(orders_view["this_net"])
        self.assertEqual(orders_view["this_count"], 0)  # No known paid amount.
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
        # F27-I27: `objective="OUTCOME_TRAFFIC"` so the suggestion's `campaign_objective` can be
        # told apart from the other two campaigns below (both left unset -> "other").
        self.refresh_campaign = _campaign(
            self.conn, self.org, self.brand, name="待補素材活動", native_id="cref",
            objective="OUTCOME_TRAFFIC",
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
        # F28-I02: graded against the cap 100 -- 沒賣出 (350 spent, 0 purchases), 太貴 (150 a
        # purchase), 划算 (50 a purchase). Two over capacity: the 沒賣出 and the 太貴 close.
        for idx, (daily_spend, daily_count) in enumerate(((50, 0), (150, 1), (50, 1))):
            ad = _ad(self.conn, self.org, self.brand, self.cleanup_campaign, f"ad_cln{idx}",
                     campaign_native_id="ccln")
            for offset in range(7):
                _obs(self.conn, self.org, self.brand, self.cleanup_campaign, ad["id"],
                     self.cutoff - timedelta(days=offset), spend=daily_spend, count=daily_count,
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
        # F27-I27: reused `campaign_objective_family`, not a frontend keyword guess.
        self.assertEqual(refresh["campaign_objective"], "traffic")

        self.assertIn("cleanup", by_kind)
        cleanup = by_kind["cleanup"]
        self.assertEqual(cleanup["campaign_id"], self.cleanup_campaign)
        self.assertEqual(cleanup["title"], "關掉 2 則花錢沒效的廣告")
        self.assertEqual(cleanup["why"], "同時 3 則，預算約撐 1 則")
        self.assertEqual(cleanup["key"], f"cleanup:{self.cleanup_campaign}")
        self.assertEqual(cleanup["campaign_objective"], "other")

        self.assertIn("no_target", by_kind)
        no_target = by_kind["no_target"]
        self.assertEqual(no_target["campaign_id"], self.no_target_campaign)
        self.assertEqual(no_target["title"], "替「沒目標活動」設目標")
        self.assertEqual(no_target["key"], f"no_target:{self.no_target_campaign}")
        self.assertEqual(no_target["campaign_objective"], "other")

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


class MonthSummaryWastedOnlyCleanupTest(unittest.TestCase):
    def test_wasted_ad_without_a_daily_budget_owner_names_the_waste_not_capacity(self):
        # F28-I02: a 沒賣出 ad raises the cleanup even when capacity is unknown (no daily budget
        # owner -> `can_support` null) -- the reason must not print a null capacity.
        conn, org = db.current(), db.DEV_ORG_ID
        brand = brands.create_brand(
            conn, org_id=org, name="每月回顧白花清理測試", actor="test", client_name=None,
        )["id"]
        month = _month(conn, org)
        cutoff = coresettings.today_for_org(conn, org_id=org) - timedelta(days=2)
        campaign = _campaign(conn, org, brand, name="白花活動", native_id="cwaste")
        external.record_sync(
            conn, org, brand, campaign, section="observations",
            state={"last_success_at": db.now_utc().isoformat(),
                   "coverage": {"start": (cutoff - timedelta(days=90)).isoformat(),
                                "end": cutoff.isoformat()}},
        )
        repository.save_campaign_target(
            conn, org, brand, campaign, result_kind="purchase", basis="own", value=100,
            expected_revision=0, actor="test",
        )
        ad = _ad(conn, org, brand, campaign, "ad_waste", campaign_native_id="cwaste")
        for offset in range(7):
            _obs(conn, org, brand, campaign, ad["id"], cutoff - timedelta(days=offset),
                 spend=50, count=0, key=f"w{offset}")
        triage.refresh_queue(conn, org, brand)

        summary = month_summary.get_summary(conn, org, brand, month)
        cleanup = next(s for s in summary["suggestions"] if s["kind"] == "cleanup")
        self.assertEqual(cleanup["title"], "關掉 1 則花錢沒效的廣告")
        self.assertEqual(cleanup["why"], "1 則花了上限 3 倍以上還沒有成果")


class MonthSummaryGradesTest(unittest.TestCase):
    """F29-I01 Contract C `grades`: the month's spend split by the one ruler (`grade_period`);
    有效 = 划算 only; the month edges are exact calendar days."""

    def test_buckets_rows_and_exact_month_edges(self):
        conn, org = db.current(), db.DEV_ORG_ID
        brand = brands.create_brand(
            conn, org_id=org, name="每月回顧分級測試", actor="test", client_name=None,
        )["id"]
        campaign = _campaign(conn, org, brand, name="分級活動", native_id="cgrade")
        repository.save_campaign_target(
            conn, org, brand, campaign, result_kind="purchase", basis="own", value=100,
            expected_revision=0, actor="test",
        )
        good = _ad(conn, org, brand, campaign, "ad_good", campaign_native_id="cgrade",
                   name="划算的")
        waste = _ad(conn, org, brand, campaign, "ad_waste", campaign_native_id="cgrade",
                    name="沒賣的", status="PAUSED")
        start = date(2026, 8, 1)
        for offset in range(10):
            _obs(conn, org, brand, campaign, good["id"], start + timedelta(days=offset),
                 spend=50, count=1, key=f"g{offset}")
        for offset in range(7):
            _obs(conn, org, brand, campaign, waste["id"], start + timedelta(days=offset),
                 spend=50, count=0, key=f"w{offset}")
        # One day either side of August belongs to another month -- never counted here.
        _obs(conn, org, brand, campaign, good["id"], date(2026, 7, 31), spend=999, count=0,
             key="before")
        _obs(conn, org, brand, campaign, good["id"], date(2026, 9, 1), spend=999, count=0,
             key="after")

        grades = month_summary.get_summary(conn, org, brand, "2026-08")["grades"]
        self.assertEqual(grades["spent"], 850)
        by_grade = {b["grade"]: b for b in grades["buckets"]}
        self.assertEqual((by_grade["on_target"]["count"], by_grade["on_target"]["amount"]),
                         (1, 500))
        self.assertEqual(by_grade["on_target"]["ads"][0]["name"], "划算的")
        self.assertEqual((by_grade["wasted"]["count"], by_grade["wasted"]["amount"]), (1, 350))
        self.assertEqual({r["name"]: r["grade_label"] for r in grades["rows"]},
                         {"划算的": "划算", "沒賣的": "沒賣出"})
        self.assertIsInstance(grades["missing"], list)


class MonthSummaryRejectedTest(unittest.TestCase):
    """F29-I01 Contract C `rejected`: a remembered "no" is listed again only when one of its ads
    now ranks worse; every other one only counts in `same_count`; the cleanup suggestion never
    re-proposes an ad the memory still holds."""

    def test_worse_same_and_held_suggestion(self):
        conn, org = db.current(), db.DEV_ORG_ID
        brand = brands.create_brand(
            conn, org_id=org, name="每月回顧拒絕記憶測試", actor="test", client_name=None,
        )["id"]
        month = _month(conn, org)
        cutoff = coresettings.today_for_org(conn, org_id=org) - timedelta(days=2)
        campaign = _campaign(conn, org, brand, name="拒絕過的活動", native_id="crej")
        external.record_sync(
            conn, org, brand, campaign, section="observations",
            state={"last_success_at": db.now_utc().isoformat(),
                   "coverage": {"start": (cutoff - timedelta(days=90)).isoformat(),
                                "end": cutoff.isoformat()}},
        )
        repository.save_campaign_target(
            conn, org, brand, campaign, result_kind="purchase", basis="own", value=100,
            expected_revision=0, actor="test",
        )
        ads = {}
        for name, (spend, count) in {"變更貴": (150, 1), "一樣貴": (150, 1),
                                      "還是沒賣": (50, 0)}.items():
            ads[name] = _ad(conn, org, brand, campaign, f"ad_{len(ads)}",
                            campaign_native_id="crej", name=name)["id"]
            for offset in range(7):
                _obs(conn, org, brand, campaign, ads[name], cutoff - timedelta(days=offset),
                     spend=spend, count=count, key=f"{name}{offset}")
        gone = _ad(conn, org, brand, campaign, "ad_gone", campaign_native_id="crej",
                   status="PAUSED")["id"]

        def rejected(entries, reason, at):
            set_id = db.new_id("acs")
            conn.execute(
                "INSERT INTO ads_change_set(id,org_id,brand_id,campaign_id,operation_id,"
                "request_hash,content_hash,title,month,status,plan_json,created_by,"
                "decision_reason,decision_grades) "
                "VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                (set_id, org, brand, campaign, set_id, set_id, set_id, "清理：拒絕過的活動",
                 month, "rejected", db.jsonb({"source": "cleanup", "items": []}), "test",
                 reason, db.jsonb({eid: {"grade": grade, "cost_per_result": None, "cap": 100,
                                         "at": at} for eid, grade in entries.items()})),
            )
            conn.commit()
            return set_id

        worse_set = rejected({ads["變更貴"]: "watch", ads["一樣貴"]: "over"}, "季節性",
                             "2026-09-20T02:00:00+00:00")
        rejected({ads["還是沒賣"]: "wasted"}, "等新素材", "2026-09-21T02:00:00+00:00")
        rejected({gone: "over"}, "已關", "2026-09-22T02:00:00+00:00")  # closed since

        summary = month_summary.get_summary(conn, org, brand, month)
        self.assertEqual(summary["rejected"]["same_count"], 1)
        [card] = summary["rejected"]["worse"]
        self.assertEqual(card["change_set_id"], worse_set)
        self.assertEqual(card["campaign_name"], "拒絕過的活動")
        self.assertEqual(card["reason"], "季節性")
        self.assertEqual(card["at"], "2026-09-20T02:00:00+00:00")
        self.assertEqual(
            [(ad["name"], ad["was"], ad["now"]) for ad in card["ads"]],
            [("變更貴", "watch", "over")],
        )
        # The 沒賣出 ad remembered as 沒賣出 is held: no cleanup suggestion re-proposes it.
        self.assertNotIn("cleanup", {s["kind"] for s in summary["suggestions"]})

        # F29-I15: 先不要 on the worse card is the month's `cleanup:<campaign>` dismissal -- the
        # card stays gone for this month only, and it is not counted as "did not get worse".
        month_summary.dismiss_suggestion(conn, org, brand, month, f"cleanup:{campaign}")
        dismissed = month_summary.get_summary(conn, org, brand, month)
        self.assertEqual(dismissed["rejected"]["worse"], [])
        self.assertEqual(dismissed["rejected"]["same_count"], 1)
        next_month = (date.fromisoformat(month + "-01") + timedelta(days=32)).strftime("%Y-%m")
        later = month_summary.get_summary(conn, org, brand, next_month)
        self.assertEqual([c["change_set_id"] for c in later["rejected"]["worse"]], [worse_set])


class MonthSummaryNextPlanTest(unittest.TestCase):
    """F46-I05 `next_plan`: one per sell-way from the newest system-built campaign closed inside
    the month (org-local date) that has ranked rows; numbers and link from the learnings view."""

    def setUp(self):
        self.conn, self.org = db.current(), db.DEV_ORG_ID
        self.brand = brands.create_brand(
            self.conn, org_id=self.org, name="每月回顧下一期測試", actor="test", client_name=None,
        )["id"]
        self.box = brands.create_product(self.conn, self.brand, name="三盒組", actor="test")["id"]
        self.single = brands.create_product(self.conn, self.brand, name="單盒", actor="test")["id"]
        self.conn.commit()

    def _closed(self, name, closed_at, product_id):
        campaign = repository.create_campaign(self.conn, self.org, self.brand, {
            "name": name, "goal_text": "x", "objective": "購買", "target_cost": 450,
            "start_date": "2026-09-01", "end_date": "2026-09-14", "status": "closed",
            # F48 Contract M: a non-draft campaign's sell-way is fixed (no PATCH after adoption).
            "context_json": {"product_ids": [product_id]} if product_id is not None else {},
        }, created_by="test")
        self.conn.execute("UPDATE ads_campaign SET closed_at=%s WHERE id=%s",
                          (closed_at, campaign["id"]))
        self.conn.commit()
        return campaign["id"]

    def _ranked(self, campaign_id, name, *, verdict, rank, of, sales, spend):
        group = plan.create_group(self.conn, self.org, self.brand, campaign_id,
                                  name=f"組 {name}", role="new", daily_budget=500)
        ad = plan.create_ad(
            self.conn, self.org, self.brand, campaign_id, group["id"], name=name,
            coordinates={"audience": "cold", "pain": "effort", "angle": "box", "hook": "h",
                         "proof": "none", "offer": "none", "format": "single_image"},
        )
        cpr = round(spend / sales) if sales else "none"
        few = 1 if 0 < sales < 5 else 0
        brands.record_learning(
            self.conn, self.brand, actor="test", learning_text=name,
            applicability_scope=(
                f"coord；v=2；verdict={verdict}；rank={rank}；of={of}；sales={sales}；spend={spend}"
                f"；cpr={cpr}；cap=450；few={few}；group=none；audience=cold；pain=effort；angle=box"
                "；hook=h；proof=none；offer=none；format=single_image；cur=TWD"
            ),
            confidence="observed", sample_size="高",
            source_cycle_id=f"{campaign_id}:{ad['id']}", source_track="coordinate",
        )
        self.conn.commit()

    def _next_plans(self, month):
        summary = month_summary.get_summary(self.conn, self.org, self.brand, month)
        return [s for s in summary["suggestions"] if s["kind"] == "next_plan"]

    def test_newest_closed_with_rows_per_sell_way_in_the_org_local_month(self):
        older = self._closed("三盒組・第一期", datetime(2026, 9, 5, 2, 0, tzinfo=UTC), self.box)
        self._ranked(older, "舊的", verdict="keep", rank=1, of=1, sales=6, spend=1200)
        newer = self._closed("三盒組・第二期", datetime(2026, 9, 20, 2, 0, tzinfo=UTC), self.box)
        self._ranked(newer, "考前一週・書包一盒", verdict="keep", rank=1, of=3, sales=6,
                     spend=2400)
        self._ranked(newer, "第二好", verdict="keep", rank=2, of=3, sales=2, spend=880)
        self._ranked(newer, "通勤族", verdict="replace", rank=3, of=3, sales=0, spend=700)
        # Newest of the sell-way but nothing ranked (missing days) -> the one before it wins.
        self._closed("三盒組・缺天", datetime(2026, 9, 25, 2, 0, tzinfo=UTC), self.box)
        # No sell-way: nothing to prefill, no suggestion even with rows.
        orphan = self._closed("沒有賣法", datetime(2026, 9, 21, 2, 0, tzinfo=UTC), None)
        self._ranked(orphan, "孤兒", verdict="keep", rank=1, of=1, sales=6, spend=600)
        # 2026-10-01 00:30 in Taipei is 2026-09-30 16:30 UTC: October's, not September's.
        edge = self._closed("單盒・第一期", datetime(2026, 9, 30, 16, 30, tzinfo=UTC),
                            self.single)
        self._ranked(edge, "單盒・早餐", verdict="replace", rank=1, of=2, sales=0, spend=300)
        self._ranked(edge, "單盒・宵夜", verdict="replace", rank=2, of=2, sales=0, spend=500)

        [september] = self._next_plans("2026-09")
        self.assertEqual(september, {
            "key": f"next_plan:{newer}", "kind": "next_plan", "campaign_id": newer,
            "campaign_name": "三盒組・第二期", "objective": "購買", "campaign_objective": "sales",
            "title": "用「三盒組・第二期」學到的排下一期",
            "why": "留下 2 則（最好的「考前一週・書包一盒」每筆 400）、換掉 1 則",
            "action_url": f"/brands/{self.brand}/ads/new?sell_way={self.box}",
        })

        [october] = self._next_plans("2026-10")
        self.assertEqual(october["campaign_id"], edge)
        self.assertEqual(october["why"], "留下 0 則、換掉 2 則，沒有一則賣出")
        self.assertEqual(october["action_url"],
                         f"/brands/{self.brand}/ads/new?sell_way={self.single}")
        self.assertEqual(self._next_plans("2026-08"), [])

    def test_absent_without_rows_and_dismissal_holds_for_that_month(self):
        empty = self._closed("三盒組・沒花錢", datetime(2026, 9, 10, 2, 0, tzinfo=UTC), self.box)
        self.assertEqual(self._next_plans("2026-09"), [])

        self._ranked(empty, "後來有排名", verdict="keep", rank=1, of=1, sales=6, spend=1200)
        [suggestion] = self._next_plans("2026-09")
        month_summary.dismiss_suggestion(self.conn, self.org, self.brand, "2026-09",
                                         suggestion["key"])
        self.assertEqual(self._next_plans("2026-09"), [])
        campaign = repository.get_campaign(self.conn, self.org, self.brand, empty)
        self.assertEqual(campaign["context_json"]["month_dismissed"],
                         {"2026-09": [f"next_plan:{empty}"]})


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
