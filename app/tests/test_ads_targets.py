"""app/tests/test_ads_targets.py — F16-I04 falsifiers: `targets.resolve()` never returns a
default number, a fallback constant, or a zero. Priority is fixed: a user-set value always wins;
else break-even from product economics when this campaign's own result is a purchase and a
product is known; else this campaign's own trailing-30-day actual cost per result; else
unresolved with a `missing` reason naming what is blocking it.
"""

import unittest
from datetime import timedelta

import app.shared.web as web
from app.ads import external_repository as external
from app.ads import repository, targets
from app.brand_intelligence import repository as bi_repo
from app.core import db as coredb
from app.core import settings as coresettings


class ResolveTargetTest(unittest.TestCase):
    def setUp(self):
        self.org_id = coredb.DEV_ORG_ID
        self.brand_id = bi_repo.create_brand(
            web.conn, org_id=self.org_id, name="測試品牌：目標成本", client_name=None,
            actor="測試員",
        )["id"]
        web.conn.commit()

    def _product(self, *, unit_variable_cost=None):
        product_id = bi_repo.create_product(
            web.conn, self.brand_id, name="測試商品", actor="測試員",
        )["id"]
        bi_repo.save_product_economics(
            web.conn, self.brand_id, product_id, selling_price=500, currency="TWD",
            confirmed_by="測試員", actor="測試員", unit_variable_cost=unit_variable_cost,
            shipping_cost=50,
        )
        web.conn.commit()
        return product_id

    def _imported_campaign_with_days(self, rows):
        """`rows` is a list of `(day_offset_before_end, spend, result_kind, result_count,
        result_action, result_attribution)` tuples. `day_offset_before_end=0` is yesterday (the
        last complete day) -- matches `targets._trailing_30`'s own window exactly."""
        campaign_id = external.create_imported_campaign(
            web.conn, self.org_id, self.brand_id, name="既有活動",
        )["id"]
        entity = external.upsert_entity(
            web.conn, self.org_id, self.brand_id, campaign_id,
            {"platform": "meta", "source_account": "act_1", "native_kind": "campaign",
             "native_id": "c1"},
        )
        today = coresettings.today_for_org(web.conn, org_id=self.org_id)
        end = today - timedelta(days=1)
        for offset, spend, result_kind, result_count, result_action, result_attribution in rows:
            external.upsert_observation(
                web.conn, self.org_id, self.brand_id, campaign_id,
                {
                    "entity_id": entity["id"], "day": end - timedelta(days=offset),
                    "metric_scope": "campaign", "attribution_key": "unused",
                    "currency": "TWD", "source": "meta", "spend": spend,
                },
                result_kind=result_kind, result_count=result_count,
                result_action=result_action, result_attribution=result_attribution,
            )
        web.conn.commit()
        return campaign_id

    # -- sales, with/without product cost ------------------------------------------------------

    def test_sales_with_cost_resolves_break_even(self):
        product_id = self._product(unit_variable_cost=150)
        campaign = {
            "id": "nonexistent", "origin": "internal", "result_kind": None,
            "success_metric": None, "success_basis": None, "success_target": None,
            "context_json": {"product_ids": [product_id]},
        }
        result = targets.resolve(web.conn, self.org_id, self.brand_id, campaign)
        self.assertEqual(result["value"], 300)  # 500 - 150 - 50
        self.assertEqual(result["basis"], "break_even")
        self.assertEqual(result["result_kind"], "purchase")
        self.assertEqual(result["missing"], [])

    def test_sales_without_cost_never_guesses_falls_to_missing(self):
        product_id = self._product(unit_variable_cost=None)
        campaign = {
            "id": "nonexistent", "origin": "internal", "result_kind": None,
            "success_metric": None, "success_basis": None, "success_target": None,
            "context_json": {"product_ids": [product_id]},
        }
        result = targets.resolve(web.conn, self.org_id, self.brand_id, campaign)
        self.assertIsNone(result["value"])
        self.assertIsNone(result["basis"])
        self.assertIn("product_cost", result["missing"])

    # -- non-sales objective: trailing-30 only, never break-even --------------------------------

    def test_engagement_uses_trailing_30_actual(self):
        campaign_id = self._imported_campaign_with_days([
            (0, 100, "engagement", 10, "post_engagement", "7d_click+1d_view"),
            (5, 200, "engagement", 10, "post_engagement", "7d_click+1d_view"),
            (10, 300, "engagement", 20, "post_engagement", "7d_click+1d_view"),
        ])
        campaign = repository.get_campaign(web.conn, self.org_id, self.brand_id, campaign_id)
        result = targets.resolve(web.conn, self.org_id, self.brand_id, campaign)
        self.assertEqual(result["basis"], "trailing_30")
        self.assertEqual(result["result_kind"], "engagement")
        self.assertAlmostEqual(result["value"], (100 + 200 + 300) / (10 + 10 + 20))
        self.assertEqual(result["missing"], [])

    def test_no_data_is_missing_never_zero(self):
        campaign_id = external.create_imported_campaign(
            web.conn, self.org_id, self.brand_id, name="還沒同步過",
        )["id"]
        web.conn.commit()
        campaign = repository.get_campaign(web.conn, self.org_id, self.brand_id, campaign_id)
        result = targets.resolve(web.conn, self.org_id, self.brand_id, campaign)
        self.assertIsNone(result["value"])
        self.assertIsNone(result["basis"])
        self.assertIn("trailing_30", result["missing"])

    def test_imported_sales_without_product_is_missing_product(self):
        campaign_id = external.create_imported_campaign(
            web.conn, self.org_id, self.brand_id, name="已知是購買但沒選商品",
        )["id"]
        web.conn.commit()
        campaign = {
            **repository.get_campaign(web.conn, self.org_id, self.brand_id, campaign_id),
            "result_kind": "purchase",
        }
        result = targets.resolve(web.conn, self.org_id, self.brand_id, campaign)
        self.assertIsNone(result["value"])
        self.assertIn("product", result["missing"])

    # -- user override always wins ---------------------------------------------------------------

    def test_own_value_always_wins(self):
        product_id = self._product(unit_variable_cost=150)  # would otherwise break-even to 300
        campaign = {
            "id": "nonexistent", "origin": "internal", "result_kind": "lead",
            "success_metric": "cost_per_result", "success_basis": "own",
            "success_target": 999,
            "context_json": {"product_ids": [product_id]},
        }
        result = targets.resolve(web.conn, self.org_id, self.brand_id, campaign)
        self.assertEqual(result["value"], 999)
        self.assertEqual(result["basis"], "own")
        self.assertEqual(result["result_kind"], "lead")
        self.assertEqual(result["missing"], [])

    # -- rows written before the F16-I03 result migrations -----------------------------------

    def test_pre_migration_null_result_rows_need_resync_not_zero(self):
        campaign_id = self._imported_campaign_with_days([
            (0, 100, None, None, None, None),
            (5, 200, None, None, None, None),
            (10, 300, None, None, None, None),
        ])
        campaign = repository.get_campaign(web.conn, self.org_id, self.brand_id, campaign_id)
        result = targets.resolve(web.conn, self.org_id, self.brand_id, campaign)
        self.assertIsNone(result["value"])
        self.assertIn("needs_resync", result["missing"])


if __name__ == "__main__":
    unittest.main()
