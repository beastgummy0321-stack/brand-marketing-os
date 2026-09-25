"""app/tests/test_ads_data_status.py — F29-I02 (Contract D) falsifiers for the read additions:
the one per-campaign `data_status` (`repository.campaign_data_status`, shared by triage
`data.status` and the home row `data_status`) and the home row `handoff` state.

Counterexamples: a draft (never synced -> `never`), synced with zero ad rows (`no_rows`), missing
days only outside the judged window (`ready`), `auth_expired` beating `partial`, two approved sets
(the newest wins), a `deviated` item (`check`), a stale launch (null -- the F28 exit owns it).
"""

import unittest
from datetime import UTC, date, datetime, timedelta
from unittest import mock
from zoneinfo import ZoneInfo

from app.ads import change_control_launch, channels, home_overview, repository, triage
from app.ads import external_repository as external
from app.brand_intelligence import repository as bi_repo
from app.core import db
from app.core import settings as coresettings

TODAY = date(2026, 9, 23)
MONTH = "2026-09"
ACCOUNT_TZ = "Asia/Taipei"


class _Reader:
    """One bound account `act_1` (so a campaign on it is not `disconnected`) with a known
    timezone (so `triage._account_cutoff` resolves deterministically)."""

    def accounts(self, conn, org, brand):
        return [{"account_id": "act_1", "currency": "TWD", "name": "來源",
                 "timezone_name": ACCOUNT_TZ}]


def _brand(conn, org, name):
    brand = bi_repo.create_brand(conn, org_id=org, name=name, actor="test", client_name=None)
    conn.commit()
    return brand["id"]


def _imported(conn, org, brand, name, native_id):
    campaign_id = external.create_imported_campaign(conn, org, brand, name=name)["id"]
    external.upsert_entity(conn, org, brand, campaign_id, {
        "platform": "meta", "source_account": "act_1", "native_kind": "campaign",
        "native_id": native_id,
    })
    ad = external.upsert_entity(conn, org, brand, campaign_id, {
        "platform": "meta", "source_account": "act_1", "native_kind": "ad",
        "native_id": f"{native_id}_ad", "name": "廣告", "native_status": "ACTIVE",
        "parent_native_kind": "campaign", "parent_native_id": native_id,
    })
    conn.commit()
    return campaign_id, ad["id"]


def _obs(conn, org, brand, campaign_id, ad_id, day, *, spend=100, count=1):
    external.upsert_observation(
        conn, org, brand, campaign_id,
        {"entity_id": ad_id, "day": day, "metric_scope": "ad", "attribution_key": "a",
         "currency": "TWD", "source": "meta", "spend": spend, "impressions": 100,
         "purchases": None},
        result_kind="purchase", result_count=count, result_action="omni_purchase",
        result_attribution="7d_click+1d_view",
    )
    conn.commit()


def _synced(conn, org, brand, campaign_id, start, end):
    external.record_sync(
        conn, org, brand, campaign_id, section="observations",
        state={"status": "success", "last_success_at": db.now_utc().isoformat(),
               "coverage": {"start": start.isoformat(), "end": end.isoformat()}},
    )
    conn.commit()


def _auth_expired(conn, org, brand, campaign_id):
    external.record_sync(
        conn, org, brand, campaign_id, section="observations",
        state={"status": "error", "error": "沒有讀取權限", "error_code": "permission_denied",
               "last_attempt_at": db.now_utc().isoformat()},
    )
    conn.commit()


class _WithReader(unittest.TestCase):
    def setUp(self):
        self.conn, self.org = db.current(), db.DEV_ORG_ID
        patcher = mock.patch.object(channels, "external_reader", return_value=_Reader())
        patcher.start()
        self.addCleanup(patcher.stop)


# ---------------------------------------------------------------------------
# The one function
# ---------------------------------------------------------------------------


class DataStatusFunctionTest(unittest.TestCase):
    """`campaign_data_status` given a sync state it does not have to read."""

    def status(self, sync_state, *, has_rows, missing_days=()):
        sync = {"state": sync_state, "error": None, "last_success_at": "2026-09-22T01:00:00+00:00"}
        return repository.campaign_data_status(
            None, "org", "brd", {"id": "cmp"}, sync=sync, has_rows=has_rows,
            missing_days=list(missing_days),
        )

    def test_every_state_has_one_plain_sentence(self):
        self.assertEqual(set(repository.DATA_STATUS_LABELS), {
            "ready", "partial", "no_rows", "syncing", "never", "disconnected", "auth_expired",
            "failed",
        })
        for label in repository.DATA_STATUS_LABELS.values():
            self.assertTrue(label.endswith("。"), label)

    def test_ok_sync_splits_into_ready_partial_and_no_rows(self):
        self.assertEqual(self.status("ok", has_rows=True)["state"], "ready")
        self.assertEqual(self.status("ok", has_rows=False)["state"], "no_rows")
        partial = self.status("ok", has_rows=True, missing_days=["2026-09-01"])
        self.assertEqual(partial["state"], "partial")
        self.assertEqual(partial["label"], repository.DATA_STATUS_LABELS["partial"])
        self.assertEqual(partial["missing_days"], ["2026-09-01"])
        self.assertEqual(partial["last_success_at"], "2026-09-22T01:00:00+00:00")

    def test_a_gap_with_no_rows_reads_partial_not_no_rows(self):
        # An unread day could be exactly where the spend is: never claim "nothing spent".
        self.assertEqual(
            self.status("ok", has_rows=False, missing_days=["2026-09-01"])["state"], "partial",
        )

    def test_a_broken_sync_beats_a_gap_and_keeps_the_days(self):
        for state in ("never", "disconnected", "auth_expired", "failed", "syncing"):
            with self.subTest(state=state):
                status = self.status(state, has_rows=True, missing_days=["2026-09-01"])
                self.assertEqual(status["state"], state)
                self.assertEqual(status["missing_days"], ["2026-09-01"])


# ---------------------------------------------------------------------------
# Triage `data.status`
# ---------------------------------------------------------------------------


class TriageDataStatusTest(_WithReader):
    def setUp(self):
        super().setUp()
        self.brand = _brand(self.conn, self.org, "資料狀態：分級")
        self.campaign, self.ad = _imported(self.conn, self.org, self.brand, "分級活動", "t1")
        self.cutoff = (db.now_utc().astimezone(ZoneInfo(ACCOUNT_TZ)) - timedelta(days=1)).date()
        self.window_start = self.cutoff - timedelta(days=triage.WINDOW_STEPS[-1] - 1)

    def data(self):
        return triage.classify(self.conn, self.org, self.brand, self.campaign)["data"]

    def test_synced_with_zero_ad_rows_is_no_rows(self):
        _synced(self.conn, self.org, self.brand, self.campaign,
                self.cutoff - timedelta(days=90), self.cutoff)
        status = self.data()["status"]
        self.assertEqual(status["state"], "no_rows")
        self.assertEqual(status["missing_days"], [])

    def test_missing_days_only_outside_the_window_is_ready(self):
        # Coverage starts exactly at the judged window: every earlier day is unread, none of the
        # window's days are.
        _synced(self.conn, self.org, self.brand, self.campaign, self.window_start, self.cutoff)
        _obs(self.conn, self.org, self.brand, self.campaign, self.ad, self.cutoff)
        data = self.data()
        self.assertEqual(data["missing_days"], [])
        self.assertEqual(data["status"]["state"], "ready")

    def test_a_row_outside_the_window_only_is_no_rows(self):
        _synced(self.conn, self.org, self.brand, self.campaign,
                self.cutoff - timedelta(days=90), self.cutoff)
        _obs(self.conn, self.org, self.brand, self.campaign, self.ad,
             self.window_start - timedelta(days=1))
        self.assertEqual(self.data()["status"]["state"], "no_rows")

    def test_a_gap_inside_the_window_is_partial(self):
        _synced(self.conn, self.org, self.brand, self.campaign,
                self.cutoff - timedelta(days=3), self.cutoff)
        _obs(self.conn, self.org, self.brand, self.campaign, self.ad, self.cutoff)
        data = self.data()
        self.assertEqual(data["status"]["state"], "partial")
        self.assertEqual(data["status"]["missing_days"], data["missing_days"])
        self.assertTrue(data["missing_days"])

    def test_auth_expired_beats_partial(self):
        _synced(self.conn, self.org, self.brand, self.campaign,
                self.cutoff - timedelta(days=3), self.cutoff)
        _obs(self.conn, self.org, self.brand, self.campaign, self.ad, self.cutoff)
        _auth_expired(self.conn, self.org, self.brand, self.campaign)
        data = self.data()
        self.assertTrue(data["missing_days"])  # the old coverage still leaves a gap
        self.assertEqual(data["sync"]["state"], "auth_expired")
        self.assertEqual(data["status"]["state"], "auth_expired")
        self.assertEqual(data["status"]["label"], repository.DATA_STATUS_LABELS["auth_expired"])

    def test_status_is_the_function_over_the_same_inputs(self):
        _synced(self.conn, self.org, self.brand, self.campaign,
                self.cutoff - timedelta(days=90), self.cutoff)
        _obs(self.conn, self.org, self.brand, self.campaign, self.ad, self.cutoff)
        data = self.data()
        campaign = repository.get_campaign(self.conn, self.org, self.brand, self.campaign)
        self.assertEqual(data["status"], repository.campaign_data_status(
            self.conn, self.org, self.brand, campaign, has_rows=True,
            missing_days=data["missing_days"],
        ))


# ---------------------------------------------------------------------------
# Home rows: `data_status`, `handoff`, `cap.break_even`
# ---------------------------------------------------------------------------


class _Home(_WithReader):
    def setUp(self):
        super().setUp()
        today = mock.patch.object(coresettings, "today_for_org", return_value=TODAY)
        classify = mock.patch.object(triage, "classify", return_value={"items": []})
        today.start()
        classify.start()
        self.addCleanup(today.stop)
        self.addCleanup(classify.stop)

    def rows(self, brand):
        home = home_overview.get_overview(self.conn, self.org, brand, MONTH)
        return {row["campaign_id"]: row for row in home["campaigns"]}

    def draft(self, brand, name="草稿活動"):
        campaign_id = repository.create_campaign(self.conn, self.org, brand, {
            "name": name, "goal_text": "g", "objective": "購買",
            "start_date": date(2026, 10, 1), "end_date": date(2026, 10, 31),
        })["id"]
        self.conn.commit()
        return campaign_id

    def approved_set(self, brand, campaign_id, states, *, minutes, launch_snapshot=None):
        """An approved change set whose items carry `states` (`ads_action.verification_state`),
        approved `minutes` after a fixed instant -- so two sets have a known order."""
        set_id = db.new_id("acs")
        plan = {"items": []}
        if launch_snapshot is not None:
            plan["launch_snapshot"] = launch_snapshot
        self.conn.execute(
            "INSERT INTO ads_change_set(id,org_id,brand_id,campaign_id,operation_id,request_hash,"
            "content_hash,title,month,plan_json,created_by,status,approved_at) "
            "VALUES(%s,%s,%s,%s,%s,'h','h','t',%s,%s,'test','approved',%s)",
            (set_id, self.org, brand, campaign_id, db.new_id("op"), MONTH, db.jsonb(plan),
             datetime(2026, 9, 20, tzinfo=UTC) + timedelta(minutes=minutes)),
        )
        for state in states:
            self.conn.execute(
                "INSERT INTO ads_action(id,org_id,brand_id,campaign_id,target_kind,target_id,"
                "kind,change_set_id,verification_state) "
                "VALUES(%s,%s,%s,%s,'campaign',%s,%s,%s,%s)",
                (db.new_id("adx"), self.org, brand, campaign_id, campaign_id,
                 "publish" if launch_snapshot is not None else "budget", set_id, state),
            )
        self.conn.commit()
        return set_id


class HomeDataStatusTest(_Home):
    def test_a_draft_is_never(self):
        brand = _brand(self.conn, self.org, "資料狀態：草稿")
        draft = self.draft(brand)
        status = self.rows(brand)[draft]["data_status"]
        self.assertEqual(status["state"], "never")
        self.assertEqual(status["missing_days"], [])
        self.assertIsNone(status["last_success_at"])

    def test_synced_with_zero_rows_this_month_is_no_rows(self):
        brand = _brand(self.conn, self.org, "資料狀態：零列")
        campaign, _ad = _imported(self.conn, self.org, brand, "零列", "h0")
        _synced(self.conn, self.org, brand, campaign, date(2026, 8, 1), date(2026, 9, 22))
        row = self.rows(brand)[campaign]
        self.assertEqual(row["data_status"]["state"], "no_rows")
        self.assertEqual(row["sync_state"], "ok")

    def test_missing_days_only_before_the_month_is_ready(self):
        brand = _brand(self.conn, self.org, "資料狀態：月外缺日")
        campaign, ad = _imported(self.conn, self.org, brand, "月外缺日", "h1")
        _synced(self.conn, self.org, brand, campaign, date(2026, 9, 1), date(2026, 9, 22))
        _obs(self.conn, self.org, brand, campaign, ad, date(2026, 9, 10))
        row = self.rows(brand)[campaign]
        self.assertEqual(row["missing_days"], [])
        self.assertEqual(row["data_status"]["state"], "ready")

    def test_auth_expired_beats_partial_and_matches_the_row_fields(self):
        brand = _brand(self.conn, self.org, "資料狀態：授權過期")
        campaign, ad = _imported(self.conn, self.org, brand, "授權過期", "h2")
        _synced(self.conn, self.org, brand, campaign, date(2026, 9, 15), date(2026, 9, 22))
        _obs(self.conn, self.org, brand, campaign, ad, date(2026, 9, 16))
        _auth_expired(self.conn, self.org, brand, campaign)
        row = self.rows(brand)[campaign]
        self.assertEqual(row["data_status"]["state"], "auth_expired")
        self.assertEqual(row["sync_state"], "auth_expired")
        self.assertEqual(row["data_status"]["missing_days"], row["missing_days"])
        self.assertEqual(row["missing_days"][0], "2026-09-01")

    def test_a_failed_spend_read_never_reads_as_no_rows(self):
        brand = _brand(self.conn, self.org, "資料狀態：讀取失敗")
        _imported(self.conn, self.org, brand, "讀取失敗", "h3")
        with mock.patch.object(home_overview, "_ad_rows", side_effect=RuntimeError("boom")):
            home = home_overview.get_overview(self.conn, self.org, brand, MONTH)
        self.assertIsNone(home["campaigns"])


class HomeCapBreakEvenTest(_Home):
    def test_row_cap_carries_break_even(self):
        brand = _brand(self.conn, self.org, "首頁：打平線")
        product = bi_repo.create_product(self.conn, brand, name="商品", actor="test")["id"]
        bi_repo.save_product_economics(
            self.conn, brand, product, selling_price=500, currency="TWD", confirmed_by="test",
            actor="test", unit_variable_cost=150, shipping_cost=50,
        )
        self.conn.commit()
        own, _ = _imported(self.conn, self.org, brand, "自己的上限", "b1")
        be, _ = _imported(self.conn, self.org, brand, "暫用打平", "b2")
        bare, _ = _imported(self.conn, self.org, brand, "沒商品", "b3")
        repository.save_campaign_target(self.conn, self.org, brand, own, result_kind="purchase",
                                        basis="own", value=250, product_id=product,
                                        expected_revision=0, actor="test")
        repository.save_campaign_target(self.conn, self.org, brand, be, result_kind="purchase",
                                        product_id=product, expected_revision=0, actor="test")
        repository.save_campaign_target(self.conn, self.org, brand, bare, result_kind="purchase",
                                        basis="own", value=90, expected_revision=0, actor="test")
        self.conn.commit()
        rows = self.rows(brand)
        self.assertEqual(rows[own]["cap"], {"value": 250, "basis": "own", "break_even": 300})
        self.assertEqual(rows[be]["cap"], {"value": 300, "basis": "break_even", "break_even": 300})
        self.assertEqual(rows[bare]["cap"], {"value": 90, "basis": "own", "break_even": None})


class HomeHandoffTest(_Home):
    def setUp(self):
        super().setUp()
        self.brand = _brand(self.conn, self.org, "首頁：交接狀態")
        self.campaign, _ad = _imported(self.conn, self.org, self.brand, "交接", "k1")

    def handoff(self, campaign_id=None):
        return self.rows(self.brand)[campaign_id or self.campaign]["handoff"]

    def test_no_approved_set_is_null(self):
        self.assertIsNone(self.handoff())

    def test_pending_item_is_platform(self):
        set_id = self.approved_set(self.brand, self.campaign, ["confirmed", "pending"], minutes=1)
        self.assertEqual(self.handoff(), {"state": "platform", "change_set_id": set_id})

    def test_pending_beats_reported_in_the_same_set(self):
        set_id = self.approved_set(self.brand, self.campaign, ["reported", "pending"], minutes=1)
        self.assertEqual(self.handoff()["state"], "platform")
        self.assertEqual(self.handoff()["change_set_id"], set_id)

    def test_deviated_item_is_check(self):
        set_id = self.approved_set(self.brand, self.campaign, ["confirmed", "deviated"], minutes=1)
        self.assertEqual(self.handoff(), {"state": "check", "change_set_id": set_id})

    def test_reported_and_unknown_are_check(self):
        for state in ("reported", "unknown"):
            with self.subTest(state=state):
                brand = _brand(self.conn, self.org, f"首頁：交接 {state}")
                campaign, _ad = _imported(self.conn, self.org, brand, "交接", f"k_{state}")
                set_id = self.approved_set(brand, campaign, [state], minutes=1)
                row = self.rows(brand)[campaign]
                self.assertEqual(row["handoff"], {"state": "check", "change_set_id": set_id})

    def test_all_confirmed_or_stale_is_null(self):
        self.approved_set(self.brand, self.campaign, ["confirmed", "stale", "legacy"], minutes=1)
        self.assertIsNone(self.handoff())

    def test_two_approved_sets_the_newest_wins(self):
        self.approved_set(self.brand, self.campaign, ["pending"], minutes=1)
        newest = self.approved_set(self.brand, self.campaign, ["confirmed"], minutes=2)
        self.assertIsNone(self.handoff())  # the older unfinished set is not the newest
        newer = self.approved_set(self.brand, self.campaign, ["reported"], minutes=3)
        self.assertNotEqual(newer, newest)
        self.assertEqual(self.handoff(), {"state": "check", "change_set_id": newer})

    def test_non_approved_sets_are_ignored(self):
        set_id = self.approved_set(self.brand, self.campaign, ["pending"], minutes=1)
        self.conn.execute("UPDATE ads_change_set SET status='superseded' WHERE id=%s", (set_id,))
        self.conn.commit()
        self.assertIsNone(self.handoff())

    def test_one_query_for_every_row(self):
        for i in range(3):
            campaign, _ad = _imported(self.conn, self.org, self.brand, f"多列{i}", f"m{i}")
            self.approved_set(self.brand, campaign, ["pending"], minutes=i)
        with mock.patch.object(home_overview, "_handoff_sets",
                               wraps=home_overview._handoff_sets) as spy:
            rows = self.rows(self.brand)
        self.assertEqual(spy.call_count, 1)
        self.assertEqual(sum(1 for r in rows.values() if r["handoff"]), 3)


class HomeLaunchHandoffTest(_Home):
    """The approved launch: its unfinished items count unless its plan changed after approval
    (stale -- the F28 exit owns it), and it counts beside a newer non-launch set."""

    def setUp(self):
        super().setUp()
        self.brand = _brand(self.conn, self.org, "首頁：上架交接")
        self.campaign = self.draft(self.brand, "上架交接")
        frozen = change_control_launch.snapshot(self.conn, self.org, self.brand, self.campaign)
        self.launch = self.approved_set(self.brand, self.campaign, ["pending"], minutes=1,
                                        launch_snapshot=frozen)

    def test_a_current_launch_with_a_pending_item_is_platform(self):
        self.assertFalse(change_control_launch.is_stale(
            self.conn, self.org, self.brand, self.campaign))
        row = self.rows(self.brand)[self.campaign]
        self.assertEqual(row["handoff"], {"state": "platform", "change_set_id": self.launch})

    def test_the_launch_still_counts_beside_a_newer_confirmed_set(self):
        self.approved_set(self.brand, self.campaign, ["confirmed"], minutes=2)
        row = self.rows(self.brand)[self.campaign]
        self.assertEqual(row["handoff"], {"state": "platform", "change_set_id": self.launch})

    def test_a_stale_launch_is_null(self):
        self.conn.execute("UPDATE ads_campaign SET name='改過的名稱' WHERE id=%s",
                          (self.campaign,))
        self.conn.commit()
        self.assertTrue(change_control_launch.is_stale(
            self.conn, self.org, self.brand, self.campaign))
        self.assertIsNone(self.rows(self.brand)[self.campaign]["handoff"])

    def test_a_stale_launch_does_not_hide_a_newer_unfinished_set(self):
        self.conn.execute("UPDATE ads_campaign SET name='改過的名稱' WHERE id=%s",
                          (self.campaign,))
        self.conn.commit()
        newer = self.approved_set(self.brand, self.campaign, ["deviated"], minutes=2)
        row = self.rows(self.brand)[self.campaign]
        self.assertEqual(row["handoff"], {"state": "check", "change_set_id": newer})


if __name__ == "__main__":
    unittest.main()
