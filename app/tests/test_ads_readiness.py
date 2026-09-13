"""app/tests/test_ads_readiness.py — F05-I04 falsifiers: a brand new brand is red on all three
rows with a `secondary` action; real offering numbers + a set conversion_goal + a fully-pulled
bound account turns all three green; an economics row carrying `assumptions_json` turns
`offering` yellow (never red) with "假設" named in the reason and `fix_label == "去改"`; a bound
account whose backfill hasn't finished turns `channel` yellow and the overall state follows the
worst row; `notes[0]` always names the confirmed fact count, including 0 (which never blocks
green).
"""

import unittest
import uuid
from unittest import mock

import app.shared.web as web
from app.ads import channels, readiness
from app.brand_intelligence import repository as bi_repo
from app.core import db as coredb
from app.meta import repository as meta_repo

ACTOR = "測試員"


class ReadinessTestBase(unittest.TestCase):
    def setUp(self):
        self.org_id = coredb.DEV_ORG_ID
        self.brand = bi_repo.create_brand(
            web.conn, org_id=self.org_id, name="測試品牌：可投放檢查表", client_name=None,
            actor=ACTOR,
        )
        self.brand_id = self.brand["id"]
        web.conn.commit()

    def _connect_account(self, *, backfill_done: bool) -> None:
        meta_repo.save_token(web.conn, self.org_id, "tok")
        external_id = f"act_{uuid.uuid4().hex[:10]}"
        meta_repo.upsert_accounts(web.conn, self.org_id, [
            {"account_id": external_id, "name": "測試廣告帳號", "currency": "TWD"},
        ])
        row = next(a for a in meta_repo.list_accounts(web.conn, self.org_id)
                   if a["account_id"] == external_id)
        meta_repo.bind(web.conn, self.org_id, self.brand_id, row["id"])
        if backfill_done:
            meta_repo.upsert_entity_spend(web.conn, self.org_id, row["id"], [{
                "level": "ad", "entity_id": "ad-1", "entity_name": "ad-1",
                "campaign_id": "camp-1", "adset_id": "as-1", "ad_id": "ad-1",
                "spend_date": coresettings_today(self.org_id), "spend": 100.0,
                "impressions": 1000, "clicks": 20, "roas": None,
                "actions": None, "action_values": None, "attribution_window": "7d_click,1d_view",
            }])
        web.conn.commit()


def coresettings_today(org_id):
    from app.core import settings as coresettings
    return coresettings.today_for_org(web.conn, org_id=org_id)


class BrandNewBrandTest(ReadinessTestBase):
    def test_all_three_rows_are_red_with_a_secondary_action(self):
        result = readiness.launch_readiness(web.conn, self.org_id, self.brand_id)
        self.assertEqual(result["state"], "red")
        self.assertTrue(all(item["state"] == "red" for item in result["items"]))
        self.assertEqual(result["primary"]["label"], "先補齊地基")
        self.assertIsNotNone(result["secondary"])
        self.assertEqual(result["secondary"]["label"], "還是要先建立")

    def test_notes_report_zero_confirmed_facts_without_blocking(self):
        result = readiness.launch_readiness(web.conn, self.org_id, self.brand_id)
        self.assertIn("0", result["notes"][0]["text"])


class OfferingTest(ReadinessTestBase):
    def _add_product(self):
        return bi_repo.create_product(web.conn, self.brand_id, name="測試商品", actor=ACTOR)["id"]

    def test_real_numbers_make_offering_green(self):
        product_id = self._add_product()
        bi_repo.save_product_economics(
            web.conn, self.brand_id, product_id, selling_price=500, currency="TWD",
            confirmed_by=ACTOR, actor=ACTOR, unit_variable_cost=150, shipping_cost=50,
        )
        result = readiness.launch_readiness(web.conn, self.org_id, self.brand_id)
        offering = next(i for i in result["items"] if i["key"] == "offering")
        self.assertEqual(offering["state"], "green")

    def test_assumptions_make_offering_yellow_not_red(self):
        product_id = self._add_product()
        bi_repo.save_product_economics(
            web.conn, self.brand_id, product_id, selling_price=500, currency="TWD",
            confirmed_by=ACTOR, actor=ACTOR, unit_variable_cost=150, shipping_cost=50,
            assumptions=["cost"],
        )
        result = readiness.launch_readiness(web.conn, self.org_id, self.brand_id)
        offering = next(i for i in result["items"] if i["key"] == "offering")
        self.assertEqual(offering["state"], "yellow")
        self.assertIn("假設", offering["reason"])
        self.assertEqual(offering["fix_label"], "去改")

    def test_assumption_reason_names_the_assumed_product_not_the_real_one(self):
        real_id = bi_repo.create_product(web.conn, self.brand_id, name="A商品", actor=ACTOR)["id"]
        bi_repo.save_product_economics(
            web.conn, self.brand_id, real_id, selling_price=500, currency="TWD",
            confirmed_by=ACTOR, actor=ACTOR, unit_variable_cost=150, shipping_cost=50,
        )
        assumed_id = bi_repo.create_product(
            web.conn, self.brand_id, name="B商品", actor=ACTOR,
        )["id"]
        bi_repo.save_product_economics(
            web.conn, self.brand_id, assumed_id, selling_price=500, currency="TWD",
            confirmed_by=ACTOR, actor=ACTOR, unit_variable_cost=150, shipping_cost=50,
            assumptions=["close_rate"],
        )
        result = readiness.launch_readiness(web.conn, self.org_id, self.brand_id)
        offering = next(i for i in result["items"] if i["key"] == "offering")
        self.assertEqual(offering["state"], "yellow")
        self.assertIn("B商品", offering["reason"])
        self.assertIn("成交率", offering["reason"])
        self.assertNotIn("A商品的", offering["reason"])


class GoalTest(ReadinessTestBase):
    def test_setting_conversion_goal_makes_it_green(self):
        bi_repo.set_brand_switches(
            web.conn, self.brand_id, market_region="TW", conversion_goal="purchase", actor=ACTOR,
        )
        web.conn.commit()
        result = readiness.launch_readiness(web.conn, self.org_id, self.brand_id)
        goal = next(i for i in result["items"] if i["key"] == "goal")
        self.assertEqual(goal["state"], "green")


class ChannelTest(ReadinessTestBase):
    def _make_offering_and_goal_green(self):
        product_id = bi_repo.create_product(
            web.conn, self.brand_id, name="測試商品", actor=ACTOR,
        )["id"]
        bi_repo.save_product_economics(
            web.conn, self.brand_id, product_id, selling_price=500, currency="TWD",
            confirmed_by=ACTOR, actor=ACTOR, unit_variable_cost=150, shipping_cost=50,
        )
        bi_repo.set_brand_switches(
            web.conn, self.brand_id, market_region="TW", conversion_goal="purchase", actor=ACTOR,
        )
        web.conn.commit()

    def test_bound_but_not_backfilled_is_yellow_and_overall_state_follows(self):
        self._make_offering_and_goal_green()
        self._connect_account(backfill_done=False)
        with mock.patch.object(channels, "background_is_active", return_value=False):
            result = readiness.launch_readiness(web.conn, self.org_id, self.brand_id)
        channel = next(i for i in result["items"] if i["key"] == "channel")
        self.assertEqual(channel["state"], "yellow")
        self.assertEqual(result["state"], "yellow")
        self.assertEqual(result["primary"]["label"], "進入投放中心（有假設值）")
        self.assertIsNone(result["secondary"])
        self.assertIn("還沒有任何花費紀錄", channel["reason"])

    def test_backfill_still_running_is_yellow(self):
        self._make_offering_and_goal_green()
        self._connect_account(backfill_done=True)
        with mock.patch.object(channels, "background_is_active", return_value=True):
            result = readiness.launch_readiness(web.conn, self.org_id, self.brand_id)
        channel = next(i for i in result["items"] if i["key"] == "channel")
        self.assertEqual(channel["state"], "yellow")
        self.assertIn("花費還在拉", channel["reason"])


class AllGreenTest(ReadinessTestBase):
    def test_real_numbers_goal_and_finished_backfill_are_all_green(self):
        product_id = bi_repo.create_product(
            web.conn, self.brand_id, name="測試商品", actor=ACTOR,
        )["id"]
        bi_repo.save_product_economics(
            web.conn, self.brand_id, product_id, selling_price=500, currency="TWD",
            confirmed_by=ACTOR, actor=ACTOR, unit_variable_cost=150, shipping_cost=50,
        )
        bi_repo.set_brand_switches(
            web.conn, self.brand_id, market_region="TW", conversion_goal="purchase", actor=ACTOR,
        )
        web.conn.commit()
        self._connect_account(backfill_done=True)
        with mock.patch.object(channels, "background_is_active", return_value=False):
            result = readiness.launch_readiness(web.conn, self.org_id, self.brand_id)
        self.assertEqual(result["state"], "green")
        self.assertTrue(all(item["state"] == "green" for item in result["items"]))
        self.assertEqual(result["primary"]["label"], "進入投放中心")
        self.assertIsNone(result["secondary"])
