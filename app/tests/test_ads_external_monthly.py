"""Account-month evidence uses fake source pages and isolated PostgreSQL only."""

import unittest
from datetime import date
from unittest.mock import patch

from app.ads import adapters, month_budget
from app.ads import external_repository as repo
from app.ads import external_sync as sync
from app.ads.adapters import meta_read
from app.ads.adapters.external import SourcePage, SourceReadError
from app.ads.adapters.meta_read import MetaReader
from app.core import db
from app.tests.test_ads_external_sync import setup_brand


class MonthlyReader:
    def __init__(self, account_id):
        self.account = {"account_id": account_id, "currency": "TWD", "timezone_name": "Asia/Taipei"}
        self.pages = [[]]
        self.calls = []
        self.fail = None
        self.connected = True

    def accounts(self, *args):
        return [self.account] if self.connected else []

    def list_existing(self, *args, **kwargs):
        return SourcePage([])

    read_structure = list_existing
    read_creatives = list_existing
    read_observations = list_existing

    def read_monthly(self, *args, start, end, cursor=None, **kwargs):
        self.calls.append(cursor)
        index = cursor["index"] if cursor else 0
        if self.fail and index == 1:
            raise self.fail
        proof = {"scope": "account_campaign_day", "start": start, "end": end, **self.account}
        return SourcePage(
            self.pages[index],
            {"index": index + 1} if index + 1 < len(self.pages) else None,
            coverage=proof,
        )


def row(native="one", day="2026-09-01", spend=10):
    return {
        "native_kind": "campaign",
        "native_id": native,
        "day": day,
        "metric_scope": "campaign",
        "attribution_key": "monthly",
        "currency": "TWD",
        "spend": spend,
        "source": "fixture",
    }


class MonthlySyncTest(unittest.TestCase):
    def setUp(self):
        self.conn = db.current()
        self.org, self.brand = setup_brand(self.conn)
        self.reader = MonthlyReader(self.brand)
        for mock in (
            patch.object(
                sync.channels,
                "external_reader",
                side_effect=lambda key: self.reader if key == "fixture" else None,
            ),
            patch.object(sync.background, "enqueue", return_value=True),
            patch.object(sync.background, "is_active", return_value=False),
            patch.object(sync.settings, "today_for_org", return_value=date(2026, 9, 19)),
            patch.object(sync.settings, "org_timezone", return_value="Asia/Taipei"),
        ):
            mock.start()
            self.addCleanup(mock.stop)

    def root(self, native="one", brand=None):
        brand = brand or self.brand
        campaign = repo.create_imported_campaign(self.conn, self.org, brand, name="Monthly")
        entity = repo.upsert_entity(
            self.conn,
            self.org,
            brand,
            campaign["id"],
            {
                "platform": "fixture",
                "source_account": self.brand,
                "native_kind": "campaign",
                "native_id": native,
                "native_status": "PAUSED",
                "currency": "TWD",
            },
        )
        self.conn.commit()
        return campaign, entity

    def request(self, **kwargs):
        return sync.request_sync(self.conn, self.org, self.brand, "fixture", self.brand, **kwargs)

    def finish(self, job):
        for _ in range(30):
            sync.run_sync(self.org, self.brand, job["id"])
            job = repo.get_job(self.conn, self.org, self.brand, job["id"])
            if job["status"] not in {"pending", "running"}:
                return job
        self.fail("bounded pages did not finish")

    def inventory(self, month=date(2026, 9, 1)):
        with patch.object(sync.channels, "CHANNELS", [{"key": "fixture"}]):
            return month_budget._inventory(
                self.conn, self.org, self.brand, month, date(2026, 9, 19)
            )

    def test_all_pages_and_full_month_replace_short_import_coverage(self):
        self.root()
        self.reader.pages = [[row()], [row(day="2026-09-18", spend=25)]]
        job = self.finish(self.request())
        task = job["tasks"]["monthly:2026-09"]
        self.assertEqual(task["status"], "succeeded")
        self.assertIsNotNone(task["completed_at"])
        self.assertEqual(task["coverage"]["unassigned_native_ids"], [])
        entities, observations, issues = self.inventory()
        self.assertEqual(issues, [])
        self.assertEqual(sum(r["spend"] for r in observations), 35)
        # A fresh list failure does not invalidate a separately completed monthly receipt.
        self.conn.execute(
            "UPDATE ads_external_sync_job SET status='partial',last_success_at=NULL WHERE id=%s",
            (job["id"],),
        )
        self.conn.commit()
        self.assertEqual(self.inventory()[2], [])

    def test_network_failure_is_bounded_and_resumes_same_page(self):
        self.root()
        self.reader.pages = [[row()], [row(day="2026-09-02")]]
        self.reader.fail = SourceReadError("暫時失敗", "source_error")
        job = self.finish(self.request())
        task = job["tasks"]["monthly:2026-09"]
        self.assertEqual(task["attempts"], 3)
        self.assertEqual(task["cursor"], {"index": 1})
        self.assertEqual(len(self.reader.calls), 4)
        self.assertTrue(self.inventory()[2])
        self.reader.fail = None
        resumed = self.request()
        self.assertEqual(resumed["tasks"]["monthly:2026-09"]["started_at"], task["started_at"])
        self.assertEqual(self.finish(resumed)["tasks"]["monthly:2026-09"]["status"], "succeeded")
        self.assertEqual(self.reader.calls[-1], {"index": 1})
        self.assertEqual(len(self.inventory()[1]), 2)

    def test_invalid_page_restarts_entire_range(self):
        self.root()
        self.reader.pages = [[row()], [row(day="2026-09-02")]]
        self.reader.fail = SourceReadError("壞列", "invalid_source_page")
        task = self.finish(self.request())["tasks"]["monthly:2026-09"]
        self.assertTrue(task["restart_required"])
        self.reader.fail = None
        retry = self.request()["tasks"]["monthly:2026-09"]
        self.assertIsNone(retry["cursor"])
        self.assertNotEqual(retry["generation"], task["generation"])
        self.assertNotIn("seen_native_ids", retry)

    def test_next_day_resets_incomplete_cursor_and_old_receipt_survives(self):
        self.reader.pages = [[], []]
        job = self.request()
        for _ in range(2):
            sync.run_sync(self.org, self.brand, job["id"])
        before = repo.get_job(self.conn, self.org, self.brand, job["id"])["tasks"][
            "monthly:2026-09"
        ]
        self.assertIsNotNone(before["cursor"])
        with patch.object(sync.settings, "today_for_org", return_value=date(2026, 9, 20)):
            changed = self.request()["tasks"]["monthly:2026-09"]
        self.assertIsNone(changed["cursor"])
        self.assertEqual(changed["end"], "2026-09-20")
        self.assertNotEqual(changed["generation"], before["generation"])
        historical = self.finish(self.request(start=date(2026, 8, 1), end=date(2026, 8, 31)))
        self.assertIn("monthly:2026-08", historical["tasks"])
        self.assertIn("monthly:2026-08", self.request()["tasks"])

    def test_cross_brand_and_unimported_ids_are_all_reported(self):
        self.root("ambiguous")
        _, other = setup_brand(self.conn)
        self.root("ambiguous", other)
        self.root("foreign", other)
        self.reader.pages = [[row("ambiguous"), row("foreign")] + [row(str(i)) for i in range(25)]]
        task = self.finish(self.request())["tasks"]["monthly:2026-09"]
        self.assertEqual(len(task["coverage"]["unassigned_native_ids"]), 27)
        self.assertEqual(self.inventory()[1], [])
        self.assertTrue(self.inventory()[2])

    def test_import_midway_does_not_erase_unassigned_spend(self):
        self.reader.pages = [[row("late")], []]
        job = self.request()
        sync.run_sync(self.org, self.brand, job["id"])
        sync.run_sync(self.org, self.brand, job["id"])
        self.root("late")
        task = self.finish(job)["tasks"]["monthly:2026-09"]
        self.assertEqual(task["coverage"]["unassigned_native_ids"], ["late"])
        self.assertTrue(self.inventory()[2])
        task = self.finish(self.request())["tasks"]["monthly:2026-09"]
        self.assertEqual(task["coverage"]["unassigned_native_ids"], [])
        self.assertEqual(len(self.inventory()[1]), 1)

    def test_duplicate_source_rows_do_not_silently_replace_spend(self):
        self.root()
        self.reader.pages = [[row()], [row(spend=99)]]
        task = self.finish(self.request())["tasks"]["monthly:2026-09"]
        self.assertEqual(task["status"], "failed")
        self.assertTrue(task["restart_required"])

    def test_empty_complete_read_removes_stale_spend_from_month_total(self):
        self.root()
        self.reader.pages = [[row()]]
        self.finish(self.request())
        self.assertEqual(len(self.inventory()[1]), 1)
        self.reader.pages = [[]]
        self.finish(self.request())
        self.assertEqual(self.inventory()[1], [])
        self.assertEqual(self.inventory()[2], [])

    def test_historical_month_requires_month_end_not_today(self):
        self.root()
        self.reader.pages = [[row(day="2026-08-31")]]
        self.finish(self.request(start=date(2026, 8, 1), end=date(2026, 8, 31)))
        self.assertEqual(self.inventory(date(2026, 8, 1))[2], [])

    def test_stale_month_receipt_and_currency_mismatch_remain_unknown(self):
        job = self.finish(self.request())
        self.conn.execute(
            "UPDATE ads_external_sync_job SET tasks=jsonb_set(tasks, "
            "'{monthly:2026-09,completed_at}', %s::jsonb), last_success_at=now() WHERE id=%s",
            (db.jsonb("2020-01-01T00:00:00+00:00"), job["id"]),
        )
        self.conn.commit()
        self.assertTrue(self.inventory()[2])
        self.finish(self.request())
        self.conn.execute(
            "INSERT INTO ads_month_budget(id,org_id,brand_id,month,currency,amount,confirmed_by) "
            "VALUES(%s,%s,%s,%s,'USD',1000,'test')",
            (db.new_id("amb"), self.org, self.brand, date(2026, 9, 1)),
        )
        self.conn.commit()
        self.assertTrue(any("幣別" in issue for issue in self.inventory()[2]))

    def test_permission_revocation_has_no_automatic_retry(self):
        self.reader.pages = [[], []]
        self.reader.fail = SourceReadError("權限失效", "permission_denied")
        task = self.finish(self.request())["tasks"]["monthly:2026-09"]
        self.assertEqual(task["attempts"], 1)
        self.assertEqual(task["status"], "failed")
        self.assertEqual(len(self.reader.calls), 2)

    def test_daily_dispatch_includes_account_without_import(self):
        scopes = [{"org_id": self.org, "brand_id": self.brand, "source_account": self.brand}]
        with (
            patch.object(self.reader, "sync_scopes", return_value=scopes, create=True),
            patch.object(sync.channels, "CHANNELS", [{"key": "fixture"}]),
            patch.object(sync, "request_sync") as request,
        ):
            sync.dispatch_daily(None)
        self.assertTrue(
            any(
                call.args[1:] == (self.org, self.brand, "fixture", self.brand)
                for call in request.call_args_list
            )
        )


class AboMonthDelegationTest(unittest.TestCase):
    """F25-I01 "ABO without a schema change" (2026-09-22): `meta_read.py::_entity` marks a
    verified-ABO campaign's `budget_raw.owner="children_verified"` while keeping
    `budget_type="unknown"` (the schema has no spare `None`); `month_budget.py`'s delegation
    condition widened to accept `budget_type in (None, "unknown")`. Proves the two ends actually
    meet through a real `month_budget.view()` call (not just `calculate()`'s pure-fixture path,
    already covered elsewhere) -- same working sync recipe as `MonthlySyncTest` above (fixture
    channel reader, a real completed monthly sync job), plus a confirmed `ads_month_budget` row
    so `available` has an `amount` to compute against at all."""

    def setUp(self):
        self.conn = db.current()
        self.org, self.brand = setup_brand(self.conn)
        self.reader = MonthlyReader(self.brand)
        # This isolated reader owns a status vocabulary, like a real platform adapter.
        status_table = adapters._status_table
        delivery_patch = patch.object(
            adapters, "_status_table",
            side_effect=lambda platform: {"ACTIVE": ("running", "Running")}
            if platform == "fixture" else status_table(platform),
        )
        delivery_patch.start()
        self.addCleanup(delivery_patch.stop)
        for mock in (
            patch.object(
                sync.channels, "external_reader",
                side_effect=lambda key: self.reader if key == "fixture" else None,
            ),
            patch.object(sync.channels, "CHANNELS", [{"key": "fixture"}]),
            patch.object(sync.background, "enqueue", return_value=True),
            patch.object(sync.background, "is_active", return_value=False),
            patch.object(sync.settings, "today_for_org", return_value=date(2026, 9, 19)),
            patch.object(sync.settings, "org_timezone", return_value="Asia/Taipei"),
        ):
            mock.start()
            self.addCleanup(mock.stop)
        self.conn.execute(
            "INSERT INTO ads_month_budget(id,org_id,brand_id,month,currency,amount,confirmed_by) "
            "VALUES(%s,%s,%s,%s,'TWD',1000000,'test')",
            (db.new_id("amb"), self.org, self.brand, date(2026, 9, 1)),
        )
        self.conn.commit()

    def _campaign(self, native_id, **fields):
        campaign = repo.create_imported_campaign(self.conn, self.org, self.brand, name="月預算測試")
        entity = repo.upsert_entity(
            self.conn, self.org, self.brand, campaign["id"],
            {
                "platform": "fixture", "source_account": self.brand, "native_kind": "campaign",
                "native_id": native_id, "native_status": "ACTIVE", "currency": "TWD",
                **fields,
            },
        )
        self.conn.commit()
        return campaign, entity

    def _sync(self):
        job = sync.request_sync(self.conn, self.org, self.brand, "fixture", self.brand)
        for _ in range(10):
            sync.run_sync(self.org, self.brand, job["id"])
            job = repo.get_job(self.conn, self.org, self.brand, job["id"])
            if job["status"] not in {"pending", "running"}:
                return job
        self.fail("bounded pages did not finish")

    def test_abo_campaign_with_daily_budget_adset_yields_non_null_available(self):
        # Campaign carries no budget of its own -- ACTIVE, not PAUSED, so it actually reaches the
        # delegation check below rather than being skipped as a non-contributor either way.
        campaign, _ = self._campaign(
            "abo1", budget_type="unknown", budget_raw={"owner": "children_verified"},
        )
        repo.upsert_entity(
            self.conn, self.org, self.brand, campaign["id"],
            {
                "platform": "fixture", "source_account": self.brand, "native_kind": "adset",
                "native_id": "as1", "native_status": "ACTIVE", "currency": "TWD",
                "budget_type": "daily", "budget_amount": 100,
                "parent_native_kind": "campaign", "parent_native_id": "abo1",
            },
        )
        self.conn.commit()
        self.reader.pages = [[row("abo1")]]
        self._sync()
        budget = month_budget.view(self.conn, self.org, self.brand, "2026-09")
        self.assertEqual(budget["uncertainties"], [])
        self.assertIsNotNone(budget["available"])

    def test_cbo_campaign_unchanged(self):
        self._campaign("cbo1", budget_type="daily", budget_amount=100)
        self.reader.pages = [[row("cbo1")]]
        self._sync()
        budget = month_budget.view(self.conn, self.org, self.brand, "2026-09")
        self.assertEqual(budget["uncertainties"], [])
        self.assertIsNotNone(budget["available"])

    def test_unknown_budget_without_the_owner_marker_still_reads_uncertain(self):
        """The widened `budget_type in (None, "unknown")` clause alone is not the escape hatch --
        an ordinary "never synced" `unknown` row (no `budget_raw.owner` marker) still falls
        through to the existing uncertainty, same as before this issue."""
        self._campaign("plain1", budget_type="unknown")
        self.reader.pages = [[row("plain1")]]
        self._sync()
        budget = month_budget.view(self.conn, self.org, self.brand, "2026-09")
        self.assertTrue(budget["uncertainties"])
        self.assertIsNone(budget["available"])


class MetaMonthlyContractTest(unittest.TestCase):
    def setUp(self):
        self.reader = MetaReader()
        self.account = {"account_id": "1", "currency": "TWD", "timezone_name": "Asia/Taipei"}
        self.raw = {
            "account_id": "1",
            "account_currency": "TWD",
            "campaign_id": "2",
            "date_start": "2026-09-01",
            "date_stop": "2026-09-01",
            "spend": "12",
        }

    def read(self, **kwargs):
        return self.reader.read_monthly(
            None, "org", "brand", self.account, start="2026-09-01", end="2026-09-19", **kwargs
        )

    def test_cursor_repeats_original_query_and_rejects_changed_conditions(self):
        with patch.object(
            self.reader, "_page", return_value={"data": [self.raw], "cursor": "next"}
        ):
            page = self.read()
        self.assertEqual(page.items[0]["spend"], 12)
        self.assertEqual(page.cursor["query"]["end"], "2026-09-19")
        self.account["currency"] = "USD"
        with patch.object(self.reader, "_page") as fetch, self.assertRaises(SourceReadError):
            self.read(cursor=page.cursor)
        fetch.assert_not_called()

    def test_missing_currency_bad_spend_and_date_never_become_zero(self):
        for changes in (
            {"account_currency": None},
            {"spend": "NaN"},
            {"spend": None},
            {"date_stop": "2026-09-02"},
            {"date_start": "2026-08-31"},
        ):
            with (
                self.subTest(changes=changes),
                patch.object(
                    self.reader,
                    "_page",
                    return_value={"data": [self.raw | changes], "cursor": None},
                ),
                self.assertRaises(ValueError),
            ):
                self.read()
        self.account["timezone_name"] = None
        with patch.object(self.reader, "_page") as fetch, self.assertRaises(SourceReadError):
            self.read()
        fetch.assert_not_called()

    def test_verify_campaign_and_adset_resolves_budget_for_documented_currency_else_stays_unknown(
        self,
    ):
        from app.meta import repository as source

        for kind in ("campaign", "adset"):
            raw = {
                "id": "2" if kind == "campaign" else "3",
                "account_id": "1",
                "campaign_id": "2",
                "daily_budget": "1000",
                "effective_status": "PAUSED",
            }
            with patch.object(source, "read_external_object", return_value=raw):
                result = self.reader.verify_native(
                    None,
                    "org",
                    "brand",
                    self.account,
                    native_kind=kind,
                    native_id=raw["id"],
                    root_kind="campaign",
                    root_id="2",
                    original={},
                )
            # self.account currency is TWD (offset 1, docs/architecture/ads.md §6.12): resolved.
            self.assertEqual(result["entity"]["budget_amount"], 1000.0)
            self.assertEqual(result["entity"]["budget_raw"]["unit"], "minor_units")
            self.assertEqual(result["entity"]["budget_raw"]["conversion"], "offset_table:1")
            self.assertEqual(result["continuous_intervals"], [])

        # A currency absent from both documented offset tables stays None with a reason,
        # never a guessed division.
        self.account["currency"] = "XXX"
        raw = {
            "id": "2",
            "account_id": "1",
            "campaign_id": "2",
            "daily_budget": "1000",
            "effective_status": "PAUSED",
        }
        with patch.object(source, "read_external_object", return_value=raw):
            result = self.reader.verify_native(
                None,
                "org",
                "brand",
                self.account,
                native_kind="campaign",
                native_id=raw["id"],
                root_kind="campaign",
                root_id="2",
                original={},
            )
        self.assertIsNone(result["entity"]["budget_amount"])
        self.assertEqual(result["entity"]["budget_raw"]["unit"], "unknown")
        self.assertEqual(
            result["entity"]["budget_raw"]["conversion"], "currency_not_in_offset_table"
        )
        self.assertEqual(result["continuous_intervals"], [])

    def test_campaign_with_neither_budget_field_marks_children_verified_ad_sets_unchanged(self):
        """F25-I01 "ABO without a schema change": a campaign whose raw payload carries neither
        `daily_budget` nor `lifetime_budget` is, by Meta's own API semantics, an ad-set-budget
        (ABO) campaign -- `budget_type` stays `"unknown"` (the schema has no spare `None`), but
        `budget_raw.owner` gets the `"children_verified"` marker `month_budget.py` now reads. An
        ad set in the exact same shape is NEVER marked (this signal only ever concerns a
        campaign's own missing budget). `_entity()` directly -- the real structure-sync write
        path (`read_structure` -> `_entity()` -> `upsert_entity`); `verify_native()`'s own
        partial-read filter (`_verified_snapshot`) strips every budget field whenever the raw
        payload carries neither `daily_budget` nor `lifetime_budget` (by design: a partial read
        must never erase a previously-known value), so it is never the right seam to prove this
        signal actually reaches `ads_external_entity`."""
        campaign_raw = {"id": "2", "account_id": "1", "campaign_id": "2"}
        campaign_entity = meta_read._entity(campaign_raw, "campaign", self.account)
        self.assertEqual(campaign_entity["budget_type"], "unknown")
        self.assertIsNone(campaign_entity["budget_amount"])
        self.assertEqual(campaign_entity["budget_raw"]["owner"], "children_verified")

        adset_raw = {"id": "3", "account_id": "1", "campaign_id": "2"}
        adset_entity = meta_read._entity(adset_raw, "adset", self.account)
        self.assertEqual(adset_entity["budget_type"], "unknown")
        self.assertNotIn("owner", adset_entity["budget_raw"])

        # A campaign that DOES carry a budget field is CBO -- never marked either.
        cbo_raw = {"id": "4", "account_id": "1", "campaign_id": "2", "daily_budget": "1000"}
        cbo_entity = meta_read._entity(cbo_raw, "campaign", self.account)
        self.assertEqual(cbo_entity["budget_type"], "daily")
        self.assertNotIn("owner", cbo_entity["budget_raw"])
