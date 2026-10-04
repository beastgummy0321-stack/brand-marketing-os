"""app/tests/test_ads_connections.py — F30-I14 (Feature F30 Contract H): the connections read.

Falsifiers: every bound account is its own row (a never-synced one is `never`, never folded into
a min or read as ok); an auth failure after a good read is `auth_expired` with only the unread
days missing and its campaign named; a covered day with no spend row is `ok`; orders are `none`
before the first order and missing after the later of the latest order and the day before the
latest import (F31-I07: a zero-order day an import covered is `ok`); costless products are
named; platforms without a reader are `unsupported`; the month and today follow the org
timezone at a month edge; the route never requests a sync.
"""

import unittest
from datetime import UTC, date, datetime, time, timedelta
from unittest.mock import patch

from fastapi.testclient import TestClient

from app import main
from app.ads import channels, connections
from app.ads import external_repository as external
from app.ads import external_sync as sync
from app.ads.adapters.external import SourceReadError
from app.brand_intelligence import repository as brands
from app.core import db
from app.core import settings as coresettings

TODAY = date(2026, 9, 19)
ACTOR = "test"


class _Reader:
    def accounts(self, conn, org, brand):
        return [
            {"account_id": "act_main", "name": "主帳戶", "currency": "TWD",
             "timezone_name": "Asia/Taipei"},
            {"account_id": "act_mid", "name": "中秋活動帳戶", "currency": "TWD",
             "timezone_name": "Asia/Taipei"},
            {"account_id": "act_new", "name": "新帳戶", "currency": "TWD",
             "timezone_name": "Asia/Taipei"},
        ]


class _Revoked(_Reader):
    """The platform now refuses every read of the account (its authorization was revoked)."""

    def list_existing(self, *args, **kwargs):
        raise SourceReadError("沒有讀取權限", "permission_denied")

    def read_monthly(self, *args, **kwargs):
        raise SourceReadError("沒有讀取權限", "permission_denied")


def _only_meta(reader):
    return lambda platform: reader if platform == "meta" else None


class ConnectionsTest(unittest.TestCase):
    def setUp(self):
        self.conn, self.org = db.current(), db.DEV_ORG_ID
        self.brand = brands.create_brand(
            self.conn, org_id=self.org, name="F30-I14 資料連線測試", actor=ACTOR, client_name=None,
        )["id"]
        self.conn.commit()
        reader = patch.object(channels, "external_reader", side_effect=_only_meta(_Reader()))
        reader.start()
        self.addCleanup(reader.stop)
        self.today = patch.object(coresettings, "today_for_org", return_value=TODAY)
        self.today.start()
        self.addCleanup(self.today.stop)

    # --- fixtures -------------------------------------------------------------------------

    def _campaign(self, account, native_id, name):
        campaign_id = external.create_imported_campaign(
            self.conn, self.org, self.brand, name=name,
        )["id"]
        entity = external.upsert_entity(
            self.conn, self.org, self.brand, campaign_id,
            {"platform": "meta", "source_account": account, "native_kind": "campaign",
             "native_id": native_id},
        )
        self.conn.commit()
        return campaign_id, entity["id"]

    def _observed(self, campaign_id, start, end, *, at="2026-09-19T01:00:00+00:00"):
        external.record_sync(
            self.conn, self.org, self.brand, campaign_id, section="observations",
            state={"status": "success", "last_success_at": at,
                   "coverage": {"start": start, "end": end}},
        )
        self.conn.commit()

    def _spend(self, campaign_id, entity_id, day, spend):
        external.upsert_observation(
            self.conn, self.org, self.brand, campaign_id,
            {"entity_id": entity_id, "day": day, "metric_scope": "campaign",
             "attribution_key": "7d_click", "currency": "TWD", "spend": spend, "source": "graph"},
        )
        self.conn.commit()

    def _job(self, account, tasks, *, last_success_at=None):
        self.conn.execute(
            "INSERT INTO ads_external_sync_job(id,org_id,brand_id,platform,source_account,status,"
            "tasks,last_success_at) VALUES (%s,%s,%s,'meta',%s,'partial',%s,%s)",
            (db.new_id("aes"), self.org, self.brand, account, db.jsonb(tasks), last_success_at),
        )
        self.conn.commit()

    def _local(self, day, hour=12):
        """A moment on `day` in the org's own timezone."""
        zone = coresettings.org_timezone(self.conn, org_id=self.org)
        return datetime.combine(day, time(hour, 0), tzinfo=zone)

    def _order(self, number, day, *, imported_at=None):
        """One order row as an import leaves it; by default imported at noon of its own order
        day (an undated one on the 1st), so the import never reaches past the latest order."""
        imported_at = imported_at or self._local(day or date(2026, 9, 1))
        self.conn.execute(
            "INSERT INTO order_record(id,org_id,brand_id,order_number,order_date,source,"
            "created_at,updated_at) VALUES (%s,%s,%s,%s,%s,'test',%s,%s)",
            (db.new_id("ord"), self.org, self.brand, number, day, imported_at, imported_at),
        )
        self.conn.commit()

    def _read(self):
        return connections.get_connections(self.conn, self.org, self.brand)

    @staticmethod
    def _source(result, key):
        return next(s for s in result["sources"] if s["key"] == key)

    @staticmethod
    def _days(result, key):
        row = next(r for r in result["calendar"]["rows"] if r["source_key"] == key)
        return {d["date"]: d["state"] for d in row["days"]}

    def _three_accounts(self):
        # act_main: read cleanly through today; 09/10 has no spend row at all (a zero-spend day).
        main_id, main_entity = self._campaign("act_main", "c_main", "日常投放")
        self._observed(main_id, "2026-08-21", "2026-09-19")
        self._spend(main_id, main_entity, "2026-09-09", 120)
        self._spend(main_id, main_entity, "2026-09-11", 80)
        self._job("act_main", {
            "list": {"section": "list", "status": "succeeded",
                     "completed_at": "2026-09-19T01:00:00+00:00"},
            "monthly:2026-09": {"section": "monthly", "status": "succeeded",
                                "start": "2026-09-01", "end": "2026-09-19",
                                "completed_at": "2026-09-19T01:02:00+00:00"},
        })
        # act_mid: last read on the morning of 09/17 (so 09/16 is its last whole day), then its
        # authorization expired (09/17 and 09/18 unread).
        mid_id, _ = self._campaign("act_mid", "c_mid", "中秋限定活動")
        self._observed(mid_id, "2026-08-18", "2026-09-17", at="2026-09-17T01:00:00+00:00")
        external.record_sync(
            self.conn, self.org, self.brand, mid_id, section="observations",
            state={"status": "error", "error": "沒有讀取權限", "error_code": "permission_denied"},
        )
        self.conn.commit()
        self._job("act_mid", {
            "list": {"section": "list", "status": "failed", "error_code": "permission_denied",
                     "errors": ["沒有讀取權限"]},
            "monthly:2026-09": {"section": "monthly", "status": "failed",
                                "start": "2026-09-01", "end": "2026-09-19",
                                "error_code": "permission_denied", "errors": ["沒有讀取權限"]},
            "monthly:2026-08": {"section": "monthly", "status": "succeeded",
                                "start": "2026-08-01", "end": "2026-08-31",
                                "completed_at": "2026-09-01T01:00:00+00:00"},
        })
        # act_new: bound, never read (no sync job at all).
        return main_id, mid_id

    # --- accounts ---------------------------------------------------------------------------

    def test_each_bound_account_is_its_own_row(self):
        _, mid_id = self._three_accounts()
        result = self._read()
        main, mid, new = (self._source(result, f"meta:{a}")
                          for a in ("act_main", "act_mid", "act_new"))

        self.assertEqual(main["state"], "ok")
        self.assertEqual(main["kind"], "ad_account")
        self.assertEqual(main["missing_days"], [])
        self.assertEqual(main["affected_campaigns"], [])
        self.assertEqual(main["last_success_at"], datetime(2026, 9, 19, 1, 2, tzinfo=UTC))
        self.assertIn("主帳戶", main["name"])

        self.assertEqual(mid["state"], "auth_expired")
        self.assertEqual(mid["missing_days"], ["2026-09-17", "2026-09-18"])
        self.assertEqual(mid["affected_campaigns"], [{"id": mid_id, "name": "中秋限定活動"}])
        self.assertEqual(
            mid["note"],
            "授權已失效，重新授權後才能讀資料；09/17、09/18 讀不到・中秋限定活動先不判斷",
        )
        self.assertEqual(mid["action"]["label"], "重新授權")
        self.assertEqual(mid["last_success_at"], datetime(2026, 9, 17, 1, 0, tzinfo=UTC))

        self.assertEqual(new["state"], "never")
        self.assertEqual(new["note"], "還沒讀取過")
        self.assertIsNone(new["last_success_at"])
        self.assertEqual(result["attention_count"], 4)  # mid, new, orders (none), products

    def test_account_calendar_is_pull_coverage_not_spend_rows(self):
        self._three_accounts()
        result = self._read()
        main = self._days(result, "meta:act_main")
        self.assertEqual(main["2026-09-10"], "ok")  # read, no spend row: not missing
        self.assertEqual(main["2026-09-09"], "ok")
        self.assertEqual(main["2026-09-18"], "ok")
        self.assertEqual(main["2026-09-19"], "future")  # read this morning: today is not over
        self.assertEqual(main["2026-09-20"], "future")
        self.assertEqual(len(main), 30)

        mid = self._days(result, "meta:act_mid")
        self.assertEqual(mid["2026-09-16"], "ok")
        self.assertEqual([mid["2026-09-17"], mid["2026-09-18"]], ["missing", "missing"])
        self.assertEqual(mid["2026-09-19"], "future")  # today, not read yet: not a gap

        new = self._days(result, "meta:act_new")
        self.assertEqual({new[f"2026-09-{d:02d}"] for d in range(1, 19)}, {"missing"})

    def test_account_with_only_monthly_reads_and_a_later_gap(self):
        self._job("act_main", {"monthly:2026-09": {
            "section": "monthly", "status": "succeeded", "start": "2026-09-05",
            "end": "2026-09-15", "completed_at": "2026-09-16T01:00:00+00:00"}})
        source = self._source(self._read(), "meta:act_main")
        self.assertEqual(source["state"], "missing_days")
        self.assertEqual(source["missing_days"], ["2026-09-16", "2026-09-17", "2026-09-18"])
        days = self._days(self._read(), "meta:act_main")
        self.assertEqual(days["2026-09-04"], "none")  # before the first read
        self.assertEqual(days["2026-09-05"], "ok")

    def test_a_day_read_while_it_was_running_is_not_proven(self):
        # Both reads cover up to 09/18. act_main finished at 09:00 on 09/18 (Taipei), so 09/18
        # was not over yet; act_mid finished at 04:00 on 09/19 (Taipei), after 09/18 ended.
        for account, finished in (("act_main", "2026-09-18T01:00:00+00:00"),
                                  ("act_mid", "2026-09-18T20:00:00+00:00")):
            self._job(account, {"monthly:2026-09": {
                "section": "monthly", "status": "succeeded", "start": "2026-09-01",
                "end": "2026-09-18", "completed_at": finished}})
        campaign_id, _ = self._campaign("act_new", "c_new", "新活動")
        self._observed(campaign_id, "2026-08-20", "2026-09-18", at="2026-09-18T01:00:00+00:00")
        result = self._read()
        self.assertEqual(self._source(result, "meta:act_main")["missing_days"], ["2026-09-18"])
        self.assertEqual(self._days(result, "meta:act_main")["2026-09-17"], "ok")
        self.assertEqual(self._source(result, "meta:act_mid")["state"], "ok")
        self.assertEqual(self._source(result, "meta:act_new")["missing_days"], ["2026-09-18"])

    def test_resync_in_flight_or_failed_keeps_already_read_days(self):
        self._job("act_main", {"monthly:2026-09": {
            "section": "monthly", "status": "succeeded", "start": "2026-09-01",
            "end": "2026-09-17", "completed_at": "2026-09-18T01:00:00+00:00"}})
        with (
            patch.object(sync.background, "enqueue"),
            patch.object(sync.background, "is_active", return_value=False),
        ):
            job = sync.request_sync(self.conn, self.org, self.brand, "meta", "act_main")
        self.assertEqual(job["tasks"]["monthly:2026-09"]["status"], "pending")
        in_flight = self._read()
        self.assertEqual(self._source(in_flight, "meta:act_main")["missing_days"], ["2026-09-18"])
        self.assertEqual(self._days(in_flight, "meta:act_main")["2026-09-17"], "ok")

        with (
            patch.object(channels, "external_reader", side_effect=_only_meta(_Revoked())),
            patch.object(sync.background, "enqueue"),
            patch.object(sync.background, "is_active", return_value=False),
        ):
            for _ in range(4):
                sync.run_sync(self.org, self.brand, job["id"])
            failed = self._read()
        task = sync.repo.get_job(self.conn, self.org, self.brand, job["id"])["tasks"]
        self.assertEqual(task["monthly:2026-09"]["status"], "failed")
        source = self._source(failed, "meta:act_main")
        self.assertEqual(source["state"], "auth_expired")
        self.assertEqual(source["missing_days"], ["2026-09-18"])
        self.assertEqual(self._days(failed, "meta:act_main")["2026-09-17"], "ok")

    def test_newest_month_task_failure_counts_at_the_month_start(self):
        self._job("act_main", {
            "list": {"section": "list", "status": "succeeded",
                     "completed_at": "2026-09-30T01:00:00+00:00"},
            "monthly:2026-08": {"section": "monthly", "status": "succeeded",
                                "start": "2026-08-01", "end": "2026-08-31",
                                "completed_at": "2026-09-01T01:00:00+00:00"},
            "monthly:2026-09": {"section": "monthly", "status": "failed", "start": "2026-09-01",
                                "end": "2026-09-30", "error_code": "permission_denied",
                                "errors": ["沒有讀取權限"]},
        })
        with patch.object(coresettings, "today_for_org", return_value=date(2026, 10, 1)):
            source = self._source(self._read(), "meta:act_main")
        self.assertEqual(source["state"], "auth_expired")

    def test_failed_read_that_is_not_auth_is_failed(self):
        self._job("act_main", {"list": {"section": "list", "status": "failed",
                                        "error_code": "source_error", "errors": ["來源讀取失敗"]}})
        source = self._source(self._read(), "meta:act_main")
        self.assertEqual(source["state"], "failed")
        self.assertEqual(source["action"]["label"], "查看連線")

    # --- F47 Contract H: re-read ---------------------------------------------------------------

    def test_reread_is_the_missing_range_or_the_window_and_only_where_it_can_help(self):
        self._three_accounts()
        result = self._read()
        main, mid, new = (self._source(result, f"meta:{a}")
                          for a in ("act_main", "act_mid", "act_new"))
        self.assertIsNone(main["reread"])  # ok
        self.assertIsNone(mid["reread"])  # auth_expired: fixed by 重新授權, not a re-read
        # never: the page's whole window (the last 28 days reach before the 1st) up to yesterday.
        self.assertEqual(new["reread"], {"platform": "meta", "source_account": "act_new",
                                         "start": "2026-08-22", "end": "2026-09-18"})
        for key in ("orders", "product_costs"):
            self.assertIsNone(self._source(result, key)["reread"])

    def test_reread_of_missing_days_is_the_gap(self):
        self._job("act_main", {"monthly:2026-09": {
            "section": "monthly", "status": "succeeded", "start": "2026-09-05",
            "end": "2026-09-15", "completed_at": "2026-09-16T01:00:00+00:00"}})
        source = self._source(self._read(), "meta:act_main")
        self.assertEqual(source["state"], "missing_days")
        self.assertEqual(source["reread"], {"platform": "meta", "source_account": "act_main",
                                            "start": "2026-09-16", "end": "2026-09-18"})

    def test_a_failed_read_says_its_reason_then_its_gap_and_can_be_reread(self):
        self._job("act_main", {
            "list": {"section": "list", "status": "failed", "error_code": "source_error",
                     "errors": ["Meta 暫時讀不到"]},
            "monthly:2026-09": {"section": "monthly", "status": "succeeded",
                                "start": "2026-09-01", "end": "2026-09-16",
                                "completed_at": "2026-09-17T01:00:00+00:00"},
        })
        source = self._source(self._read(), "meta:act_main")
        self.assertEqual(source["state"], "failed")
        # F49 Contract O: the reason is the one sync outcome's sentence (the list failed, the
        # month read: partial), never a task's own error text.
        reason = f"{sync.SYNC_TEXT['partial']}：{sync.SYNC_REASONS['source_error']}"
        self.assertEqual(source["note"], f"{reason}；09/17、09/18 讀不到")
        self.assertEqual(source["reread"], {"platform": "meta", "source_account": "act_main",
                                            "start": "2026-09-17", "end": "2026-09-18"})

    def test_a_failed_read_without_a_gap_rereads_the_window(self):
        self._job("act_main", {"list": {"section": "list", "status": "failed",
                                        "error_code": "source_error", "errors": ["來源讀取失敗"]}})
        source = self._source(self._read(), "meta:act_main")
        self.assertEqual(
            source["note"], f"{sync.SYNC_TEXT['failed']}：{sync.SYNC_REASONS['source_error']}",
        )
        self.assertEqual((source["reread"]["start"], source["reread"]["end"]),
                         ("2026-08-22", "2026-09-18"))

    def test_every_reread_body_is_one_the_refresh_accepts(self):
        self._three_accounts()
        reread = self._source(self._read(), "meta:act_new")["reread"]
        with (
            patch.object(sync.background, "enqueue"),
            patch.object(sync.background, "is_active", return_value=False),
        ):
            job = sync.request_sync(
                self.conn, self.org, self.brand, reread["platform"], reread["source_account"],
                start=date.fromisoformat(reread["start"]), end=date.fromisoformat(reread["end"]),
            )
        self.assertEqual(job["source_account"], "act_new")

    def test_platform_with_reader_but_no_account_and_unsupported_platforms(self):
        with patch.object(_Reader, "accounts", return_value=[]):
            result = self._read()
        platform = self._source(result, "platform:meta")
        self.assertEqual((platform["kind"], platform["state"]), ("platform", "never"))
        unsupported = [s for s in result["sources"] if s["state"] == "unsupported"]
        self.assertEqual(
            [s["platform"] for s in unsupported],
            [c["key"] for c in channels.CHANNELS if c["key"] != "meta"],
        )
        self.assertEqual(result["sources"][-len(unsupported):], unsupported)
        rows = {r["source_key"] for r in result["calendar"]["rows"]}
        self.assertNotIn("platform:google_ads", rows)

    # --- orders and product costs -------------------------------------------------------------

    def test_orders_are_none_before_the_first_import(self):
        result = self._read()
        source = self._source(result, "orders")
        self.assertEqual(source["state"], "never")
        days = self._days(result, "orders")
        self.assertEqual(days["2026-09-01"], "none")
        self.assertEqual(days["2026-09-25"], "future")

    def test_orders_missing_after_the_latest_order(self):
        self._order("A-1", date(2026, 9, 5))
        self._order("A-2", date(2026, 9, 12))
        self._order("A-3", None)  # an undated order never counts as the latest
        result = self._read()
        source = self._source(result, "orders")
        self.assertEqual(source["state"], "missing_days")
        self.assertEqual(source["missing_days"][0], "2026-09-13")
        self.assertEqual(source["missing_days"][-1], "2026-09-18")
        self.assertEqual(source["note"], "最新到 09/12，缺 09/13 之後")
        self.assertEqual(source["action"]["label"], "補報表")
        days = self._days(result, "orders")
        self.assertEqual(days["2026-09-04"], "none")
        self.assertEqual(days["2026-09-08"], "ok")  # no order that day, but inside the import
        self.assertEqual(days["2026-09-13"], "missing")
        self.assertEqual(days["2026-09-19"], "future")

    def test_orders_up_to_yesterday_are_ok(self):
        self._order("B-1", TODAY - timedelta(days=1))
        self.assertEqual(self._source(self._read(), "orders")["state"], "ok")

    def test_days_an_import_covered_are_ok_without_orders(self):
        # F31-I07 (item 10): orders on the 1st and the 3rd, exported at 01:00 on the 6th (org
        # time; still the 5th in UTC). The import covers up to the 5th, so the zero-order 4th
        # and 5th are read, not missing; the 6th onwards is.
        self._order("C-1", date(2026, 9, 1))
        self._order("C-2", date(2026, 9, 3), imported_at=self._local(date(2026, 9, 6), hour=1))
        result = self._read()
        source = self._source(result, "orders")
        self.assertEqual(source["state"], "missing_days")
        self.assertEqual(source["missing_days"][0], "2026-09-06")
        self.assertEqual(source["missing_days"][-1], "2026-09-18")
        self.assertEqual(source["note"], "最新匯入 09/06，缺 09/06 之後")
        days = self._days(result, "orders")
        self.assertEqual([days["2026-09-04"], days["2026-09-05"]], ["ok", "ok"])
        self.assertEqual(days["2026-09-06"], "missing")

    def test_an_import_on_the_last_order_day_covers_nothing_later(self):
        self._order("D-1", date(2026, 9, 1))
        self._order("D-2", date(2026, 9, 3), imported_at=self._local(date(2026, 9, 3), hour=23))
        result = self._read()
        source = self._source(result, "orders")
        self.assertEqual(source["missing_days"][0], "2026-09-04")
        self.assertEqual(source["note"], "最新到 09/03，缺 09/04 之後")
        days = self._days(result, "orders")
        self.assertEqual(days["2026-09-03"], "ok")
        self.assertEqual(days["2026-09-04"], "missing")

    def test_an_import_today_covers_through_yesterday(self):
        self._order("E-1", date(2026, 9, 10), imported_at=self._local(TODAY, hour=9))
        result = self._read()
        source = self._source(result, "orders")
        self.assertEqual((source["state"], source["missing_days"]), ("ok", []))
        self.assertEqual(source["note"], "最新匯入 09/19")
        self.assertIsNone(source["action"])
        days = self._days(result, "orders")
        self.assertEqual(days["2026-09-18"], "ok")
        self.assertEqual(days["2026-09-19"], "future")

    def test_costless_sell_ways_are_named(self):
        # F43-I04: judged on the finished sell-ways the wizard offers; a knowledge product
        # without a sell-way is not counted.
        product = brands.create_product(self.conn, self.brand, name="經典款", actor=ACTOR)
        brands.create_product(self.conn, self.brand, name="還沒有賣法", actor=ACTOR)
        for name, economics in (("單瓶", {"selling_price": 500, "unit_variable_cost": 200}),
                                ("秋季新色", {"selling_price": 520})):
            brands.save_sell_way(
                self.conn, self.brand, name=name, actor=ACTOR, economics=economics,
                product_id=product["id"],
            )
        self.conn.commit()
        source = self._source(self._read(), "product_costs")
        self.assertEqual(source["state"], "missing_cost")
        self.assertEqual(source["note"], "2 個賣法，1 個有成本；經典款 · 秋季新色缺成本")
        self.assertEqual(source["action"]["href"], f"/brands/{self.brand}/products")

    def test_no_finished_sell_way_is_never_and_opens_product_onboarding(self):
        brands.create_product(self.conn, self.brand, name="還沒有賣法", actor=ACTOR)
        self.conn.commit()
        source = self._source(self._read(), "product_costs")
        self.assertEqual((source["state"], source["note"]), ("never", "還沒有商品"))
        self.assertEqual(source["action"]["href"], f"/brands/{self.brand}/products/new")

    # --- org timezone and the route ---------------------------------------------------------

    def test_month_and_today_follow_the_org_timezone_at_a_month_edge(self):
        zone = coresettings.org_timezone(self.conn, org_id=self.org)
        local = datetime.combine(date(2026, 10, 1), time(0, 30), tzinfo=zone)

        class _Clock(datetime):
            @classmethod
            def now(cls, tz=None):
                return local.astimezone(tz) if tz else local.replace(tzinfo=None)

        self._job("act_main", {"monthly:2026-09": {
            "section": "monthly", "status": "succeeded", "start": "2026-09-01",
            "end": "2026-09-28", "completed_at": "2026-09-29T01:00:00+00:00"}})
        self.today.stop()  # the real `today_for_org`, on a clock at 00:30 of the 1st locally
        try:
            with patch.object(db, "now_utc", return_value=local.astimezone(UTC)):
                result = self._read()
        finally:
            self.today.start()
        self.assertEqual(result["calendar"]["month"], "2026-10")
        self.assertEqual(result["calendar"]["today"], "2026-10-01")
        days = self._days(result, "meta:act_main")
        self.assertEqual(len(days), 31)
        self.assertEqual(days["2026-10-01"], "future")
        # The gap just before the 1st still counts on the 1st.
        source = self._source(result, "meta:act_main")
        self.assertEqual(source["missing_days"], ["2026-09-29", "2026-09-30"])

    def test_route_is_read_only(self):
        self._three_accounts()
        client = TestClient(main.app)
        with patch.object(sync.background, "enqueue") as enqueue, \
                patch.object(sync, "request_sync") as request_sync:
            response = client.get(f"/api/ads/brands/{self.brand}/connections")
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertEqual(body["calendar"]["month"], "2026-09")
        self.assertEqual(self._source(body, "meta:act_mid")["state"], "auth_expired")
        enqueue.assert_not_called()
        request_sync.assert_not_called()


if __name__ == "__main__":
    unittest.main()
