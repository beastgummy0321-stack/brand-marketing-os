# -*- coding: utf-8 -*-
"""R5/R6：短碼反解、追蹤鏈、告警與前端契約端點。全程假用戶端。"""

import atexit
import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

_tmpdir = tempfile.mkdtemp(prefix="brand_os_ads_tracking_")

from fastapi.testclient import TestClient  # noqa: E402

import app.main as main  # noqa: E402
from app.ads import handoff, meta_api, sync as ads_sync, tracking  # noqa: E402
from app.brand_intelligence import repository as bi_repo  # noqa: E402
from app.core import interrupts as core_interrupts  # noqa: E402
from app.core.db import new_id, now_iso  # noqa: E402



def _cleanup():
    try:
        main.conn.close()
    except Exception:
        pass
    shutil.rmtree(_tmpdir, ignore_errors=True)


atexit.register(_cleanup)
ACTOR = "測試員"


class TrackingBase(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(main.app)
        self.brand = bi_repo.create_brand(
            main.conn, name=f"虛構追蹤茶行{abs(hash(self.id())) % 100000}",
            client_name=None, actor=ACTOR)
        self.bid = self.brand["id"]

    def cycle(self, *, cycle_id=None, start="2026-08-01", status="PRODUCTION"):
        cycle_id = cycle_id or new_id("ccy")
        ts = now_iso()
        main.conn.execute(
            "INSERT INTO campaign_cycle (id, brand_id, product_scope_json, objective, currency,"
            " start_date, end_date, channels_json, status, archived, plan_version, phase,"
            " created_at, updated_at) VALUES (?, ?, '[]', 'sales', 'TWD', ?, '2026-08-31',"
            " '[\"meta\"]', ?, 0, 0, 'normal', ?, ?)",
            (cycle_id, self.bid, start, status, ts, ts),
        )
        main.conn.commit()
        return cycle_id

    def package(self, cycle_id, *, objective="sales", destination="https://example.test"):
        package_id = new_id("pkg")
        name = f"{handoff._slug(self.brand['name'])}_20260801_sales_{cycle_id[-4:]}"
        main.conn.execute(
            "INSERT INTO publishing_package (id, brand_id, campaign_cycle_id, campaign_name,"
            " adset_name, ad_name, destination_url, utm_json, objective, daily_budget, status,"
            " created_at) VALUES (?, ?, ?, ?, 'set_01', 'ad_01', ?, ?, ?, 300, 'ready', ?)",
            (package_id, self.bid, cycle_id, name, destination, json.dumps({
                "utm_source": "facebook", "utm_medium": "paid",
                "utm_campaign": "{{campaign.name}}", "utm_content": "cell_1",
            }), objective, now_iso()),
        )
        main.conn.commit()
        return package_id, name

    def sync(self, campaign_id, name, *, objective="sales", insights=None):
        fake = meta_api.FakeMetaClient(
            campaigns=[meta_api.Campaign(campaign_id, name, objective, "ACTIVE")],
            insights=insights or [],
        )
        return ads_sync.sync_account(
            main.conn, ACTOR, client=fake, account_id="act_tracking", today="2026-08-13")


class ShortCodeAndAlertTest(TrackingBase):
    def test_short_code_creates_suggested_cycle_mapping(self):
        cycle_id = self.cycle()
        _pkg, name = self.package(cycle_id)
        self.sync("cmp_match", name)
        row = main.conn.execute(
            "SELECT * FROM external_ad_mapping WHERE brand_id = ? AND meta_campaign_id = ?"
            " AND claim_status = 'suggested'", (self.bid, "cmp_match")).fetchone()
        self.assertEqual(row["campaign_cycle_id"], cycle_id)

    def test_same_short_code_on_two_cycles_warns_without_suggestion(self):
        unique = str(abs(hash(self.id())))
        self.cycle(cycle_id=f"ccy_first_{unique}ABCD")
        self.cycle(cycle_id=f"ccy_second_{unique}ABCD")
        name = f"{handoff._slug(self.brand['name'])}_20260801_sales_ABCD"
        self.sync("cmp_conflict", name)
        suggested = main.conn.execute(
            "SELECT COUNT(*) c FROM external_ad_mapping WHERE meta_campaign_id = ?"
            " AND claim_status = 'suggested'", ("cmp_conflict",)).fetchone()["c"]
        alerts = core_interrupts.list_open(main.conn, brand_id=self.bid, archive_stale=False)
        self.assertEqual(suggested, 0)
        broken = next(a for a in alerts if a["category"] == "tracking_broken")
        self.assertEqual(broken["severity"], "informational")

    def test_confirmed_campaign_cannot_be_suggested_into_a_second_cycle(self):
        first = self.cycle()
        first_package, first_name = self.package(first)
        self.sync("cmp_cross_cycle", first_name)
        handoff.authorize_and_map(
            main.conn, self.bid, first, first_package,
            meta_ids={"meta_campaign_id": "cmp_cross_cycle", "meta_account_id": "act_tracking"},
            actor=ACTOR)
        second = self.cycle()
        _second_package, second_name = self.package(second)
        self.sync("cmp_cross_cycle", second_name)
        suggested = main.conn.execute(
            "SELECT 1 FROM external_ad_mapping WHERE meta_campaign_id = ?"
            " AND campaign_cycle_id = ? AND claim_status = 'suggested'",
            ("cmp_cross_cycle", second),
        ).fetchone()
        alerts = core_interrupts.list_open(main.conn, brand_id=self.bid, archive_stale=False)
        self.assertIsNone(suggested)
        self.assertTrue(any(a["dedupe_key"].startswith("tracking_conflict:") for a in alerts))

    def test_spend_without_cycle_and_rename_enqueue_registered_categories(self):
        insight = meta_api.Insight(
            campaign_id="cmp_burn", campaign_name=None, adset_id="set", ad_id="ad",
            date_start="2026-08-13", date_stop="2026-08-13", impressions=100, clicks=10,
            spend=321, conversions=0, revenue=0)
        original = f"{handoff._slug(self.brand['name'])}_20260801_sales_NONE"
        self.sync("cmp_burn", original, insights=[insight])
        self.sync("cmp_burn", f"{handoff._slug(self.brand['name'])}_改名了")
        alerts = core_interrupts.list_open(main.conn, brand_id=self.bid, archive_stale=False)
        categories = {a["category"] for a in alerts}
        self.assertIn("burn_no_cycle", categories)
        self.assertIn("campaign_renamed", categories)
        burn = next(a for a in alerts if a["category"] == "burn_no_cycle")
        renamed = next(a for a in alerts if a["category"] == "campaign_renamed")
        self.assertIn("321", burn["message"])
        self.assertEqual(burn["severity"], "rule_warning")
        self.assertEqual(renamed["severity"], "informational")

    def test_spend_with_no_recognizable_brand_still_warns_globally(self):
        insight = meta_api.Insight(
            campaign_id="cmp_orphan", campaign_name=None, adset_id="set", ad_id="ad",
            date_start="2026-08-13", date_stop="2026-08-13", impressions=10, clicks=1,
            spend=88, conversions=0, revenue=0)
        self.sync("cmp_orphan", "完全不符合品牌命名", insights=[insight])
        alerts = core_interrupts.list_open(main.conn, archive_stale=False)
        burn = next(a for a in alerts if a["dedupe_key"].startswith("burn_no_cycle:cmp_orphan"))
        self.assertIsNone(burn["brand_id"])
        self.assertEqual(burn["action_url"], "/app/settings")


class TrackingChainApiTest(TrackingBase):
    def setUp(self):
        super().setUp()
        self.cycle_id = self.cycle()
        self.package_id, self.campaign_name = self.package(self.cycle_id)
        self.meta_campaign_id = f"cmp_chain_{abs(hash(self.id()))}"
        self.sync(self.meta_campaign_id, self.campaign_name)

    def test_get_contract_has_exact_four_nodes_and_fields(self):
        with mock.patch.object(tracking, "probe_url", return_value=True):
            response = self.client.get(
                f"/api/campaigns/{self.bid}/{self.cycle_id}/tracking-chain")
        self.assertEqual(response.status_code, 200, response.text)
        data = response.json()["data"]
        self.assertEqual(set(data), {"naming", "mapping", "codes", "landing_utm"})
        for node in data.values():
            self.assertEqual(set(node), {"status", "message", "action"})
            self.assertIn(node["status"], {"green", "yellow", "red"})
        self.assertEqual(data["mapping"]["status"], "yellow")

    def test_confirm_endpoint_uses_authorize_and_map_and_turns_mapping_green(self):
        with mock.patch.object(
                tracking.ads_handoff, "authorize_and_map",
                wraps=handoff.authorize_and_map) as authorize:
            response = self.client.post(
                f"/api/campaigns/{self.bid}/{self.cycle_id}/tracking-chain/mapping/confirm")
        self.assertEqual(response.status_code, 204, response.text)
        authorize.assert_called_once()
        with mock.patch.object(tracking, "probe_url", return_value=True):
            data = self.client.get(
                f"/api/campaigns/{self.bid}/{self.cycle_id}/tracking-chain").json()["data"]
        self.assertEqual(data["mapping"]["status"], "green")

    def test_objective_mismatch_is_red(self):
        main.conn.execute(
            "UPDATE discovered_campaign SET objective = 'traffic' WHERE meta_campaign_id = ?",
            (self.meta_campaign_id,))
        main.conn.commit()
        chain = tracking.tracking_chain(
            main.conn, self.bid, self.cycle_id, today="2026-08-02", url_probe=lambda _url: True)
        self.assertEqual(chain["naming"]["status"], "red")
        self.assertEqual(chain["landing_utm"]["status"], "red")


class PostLaunchChainTest(TrackingBase):
    def setUp(self):
        super().setUp()
        self.cycle_id = self.cycle(start="2026-08-01", status="LIVE")
        self.package_id, self.name = self.package(self.cycle_id)
        self.sync("cmp_live", self.name)
        handoff.authorize_and_map(
            main.conn, self.bid, self.cycle_id, self.package_id,
            meta_ids={"meta_campaign_id": "cmp_live", "meta_account_id": "act_tracking"},
            actor=ACTOR)

    def snapshot(self, *, clicks=20, conversions=0):
        ts = now_iso()
        main.conn.execute(
            "INSERT INTO performance_snapshot (id, brand_id, campaign_cycle_id, platform,"
            " meta_campaign_id, date_range_start, date_range_end, as_of_date, snapshot_taken_at,"
            " currency, impressions, clicks, spend, conversions, revenue, reconciled, source,"
            " quarantined, created_at) VALUES (?, ?, ?, 'meta', 'cmp_live', '2026-08-01',"
            " '2026-08-04', '2026-08-04', ?, 'TWD', 100, ?, 100, ?, 0, 1, 'meta_api', 0, ?)",
            (new_id("psn"), self.bid, self.cycle_id, ts, clicks, conversions, ts),
        )
        main.conn.commit()

    def ga4_paid(self, sessions):
        ts = now_iso()
        main.conn.execute(
            "INSERT INTO ga4_summary (id, brand_id, date_range_start, date_range_end, source,"
            " medium, sessions, conversions, revenue, synced_at, created_at) VALUES (?, ?,"
            " '2026-08-01', '2026-08-04', 'facebook', 'paid', ?, 0, 0, ?, ?)",
            (new_id("ga4"), self.bid, sessions, ts, ts),
        )
        main.conn.execute(
            "INSERT INTO ga4_sync_status (brand_id, date_range_start, date_range_end, row_count,"
            " purchase_event_seen, synced_at, updated_at) VALUES (?, '2026-08-01', '2026-08-04',"
            " 1, 1, ?, ?) ON CONFLICT(brand_id) DO UPDATE SET synced_at=excluded.synced_at",
            (self.bid, ts, ts),
        )
        main.conn.commit()

    def test_post_72h_red_and_green_results(self):
        self.snapshot()
        self.ga4_paid(0)
        broken = tracking.tracking_chain(
            main.conn, self.bid, self.cycle_id, today="2026-08-05", url_probe=lambda _url: True)
        self.assertEqual(broken["landing_utm"]["status"], "red")
        tracking.run_post_sync_checks(main.conn, self.bid, today="2026-08-05",
                                      url_probe=lambda _url: True)
        alerts = core_interrupts.list_open(main.conn, brand_id=self.bid, archive_stale=False)
        self.assertTrue(any(a["category"] == "tracking_broken" for a in alerts))

        main.conn.execute("UPDATE ga4_summary SET sessions = 18 WHERE brand_id = ?", (self.bid,))
        main.conn.commit()
        healthy = tracking.tracking_chain(
            main.conn, self.bid, self.cycle_id, today="2026-08-05", url_probe=lambda _url: True)
        self.assertEqual(healthy["landing_utm"]["status"], "green")


if __name__ == "__main__":
    unittest.main()
