"""app/tests/test_ads_targets.py — F16-I04 falsifiers: `targets.resolve()` never returns a
default number, a fallback constant, or a zero. Priority is fixed: a user-set value always wins;
else break-even from product economics when this campaign's own result is a purchase and a
product is known; else this campaign's own trailing-30-day actual cost per result; else
unresolved with a `missing` reason naming what is blocking it.
"""

import unittest
from datetime import timedelta

import app.shared.web as web
from app.ads import channels, repository, targets, tracked_zero
from app.ads import external_repository as external
from app.ads.external_repository import MONTHLY_BUDGET_ATTRIBUTION_KEY
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

    def _imported_campaign_with_days(self, rows, *, objective=None):
        """`rows` is a list of `(day_offset_before_end, spend, result_kind, result_count,
        result_action, result_attribution)` tuples. `day_offset_before_end=0` is yesterday (the
        last complete day) -- matches `targets._trailing_30`'s own window exactly.

        `objective` (F16-I04), when given, is a Meta campaign objective string put on the
        campaign-level entity exactly as a real sync would see it; `result_kind` is derived from
        it through the real adapter mapping (`MetaReader.result_kind()`) and saved through the
        real write path (`repository.save_campaign_target`) -- never hand-set on a campaign dict.
        """
        campaign_id = external.create_imported_campaign(
            web.conn, self.org_id, self.brand_id, name="既有活動",
        )["id"]
        entity_fields = {
            "platform": "meta", "source_account": "act_1", "native_kind": "campaign",
            "native_id": "c1",
        }
        if objective is not None:
            entity_fields["objective"] = objective
        entity = external.upsert_entity(
            web.conn, self.org_id, self.brand_id, campaign_id, entity_fields,
        )
        if objective is not None:
            result_kind = channels.external_reader("meta").result_kind(entity)
            repository.save_campaign_target(
                web.conn, self.org_id, self.brand_id, campaign_id,
                result_kind=result_kind, expected_revision=0, actor="測試員",
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

    def _imported_campaign_with_objective(self, objective, *, product_id=None):
        """Same real-adapter-mapping + real-write-path shape as `_imported_campaign_with_days`,
        for tests that only need the objective -> `result_kind` provenance, not trailing-30 data.
        """
        campaign_id = external.create_imported_campaign(
            web.conn, self.org_id, self.brand_id, name="既有活動：" + objective,
        )["id"]
        entity = external.upsert_entity(
            web.conn, self.org_id, self.brand_id, campaign_id,
            {"platform": "meta", "source_account": "act_1", "native_kind": "campaign",
             "native_id": "c1", "objective": objective},
        )
        web.conn.commit()
        result_kind = channels.external_reader("meta").result_kind(entity)
        repository.save_campaign_target(
            web.conn, self.org_id, self.brand_id, campaign_id,
            result_kind=result_kind, product_id=product_id, expected_revision=0, actor="測試員",
        )
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
            "target_basis": "own", "target_cost": 999,
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
        # `upsert_observation` (F16-I03 onward) always records an `availability.result_count`
        # entry, even "unknown" -- a genuine pre-migration row (written before that bookkeeping
        # existed) has no such entry at all. Simulate that historical shape directly: this is the
        # only thing `needs_resync` may key off (F16-I06), never a date guess.
        web.conn.execute(
            "UPDATE ads_external_daily SET availability = availability - 'result_count' "
            "WHERE campaign_id=%s",
            (campaign_id,),
        )
        web.conn.commit()
        campaign = repository.get_campaign(web.conn, self.org_id, self.brand_id, campaign_id)
        result = targets.resolve(web.conn, self.org_id, self.brand_id, campaign)
        self.assertIsNone(result["value"])
        self.assertIn("needs_resync", result["missing"])

    def test_known_result_kind_without_a_count_is_unknown_not_needs_resync(self):
        # F16-I06: a row a result mapping already ran against, but that simply had no purchase/
        # engagement/etc that day, keeps its `availability.result_count == "unknown"` entry --
        # this is genuinely unknown, never a stand-in for "needs a re-sync".
        campaign_id = self._imported_campaign_with_days([
            (0, 100, "engagement", None, None, None),
            (5, 200, "engagement", 10, "post_engagement", "7d_click+1d_view"),
        ])
        campaign = repository.get_campaign(web.conn, self.org_id, self.brand_id, campaign_id)
        result = targets.resolve(web.conn, self.org_id, self.brand_id, campaign)
        self.assertIsNone(result["value"])
        self.assertIn("result_unknown_days", result["missing"])
        self.assertNotIn("needs_resync", result["missing"])

    # -- account-month budget source rows must never pollute this campaign's own result --------

    def test_trailing_30_ignores_monthly_budget_rows_sharing_the_same_day(self):
        campaign_id = external.create_imported_campaign(
            web.conn, self.org_id, self.brand_id, name="混有月讀列",
        )["id"]
        entity = external.upsert_entity(
            web.conn, self.org_id, self.brand_id, campaign_id,
            {
                "platform": "meta", "source_account": "act_1", "native_kind": "campaign",
                "native_id": "c1",
            },
        )
        today = coresettings.today_for_org(web.conn, org_id=self.org_id)
        day = today - timedelta(days=1)
        external.upsert_observation(
            web.conn, self.org_id, self.brand_id, campaign_id,
            {
                "entity_id": entity["id"], "day": day, "metric_scope": "campaign",
                "attribution_key": "7d_click+1d_view:omni_purchase", "currency": "TWD",
                "source": "meta", "spend": 1747,
            },
            result_kind="purchase", result_count=5, result_action="omni_purchase",
            result_attribution="7d_click+1d_view",
        )
        # Same entity, day, metric_scope and currency as the row above -- only `attribution_key`
        # tells this monthly-budget source row apart (F16-I06's real production shape).
        external.upsert_observation(
            web.conn, self.org_id, self.brand_id, campaign_id,
            {
                "entity_id": entity["id"], "day": day, "metric_scope": "campaign",
                "attribution_key": MONTHLY_BUDGET_ATTRIBUTION_KEY, "currency": "TWD",
                "source": "meta", "spend": 1900,
            },
        )
        web.conn.commit()
        campaign = {
            **repository.get_campaign(web.conn, self.org_id, self.brand_id, campaign_id),
            "result_kind": "purchase",
        }
        result = targets.resolve(web.conn, self.org_id, self.brand_id, campaign)
        self.assertEqual(result["basis"], "trailing_30")
        self.assertAlmostEqual(result["value"], 1747 / 5)
        self.assertEqual(result["missing"], [])

    def test_trailing_30_resolves_on_a_window_blocked_only_by_derivable_zeros(self):
        # F18-I01: a day the campaign has demonstrated a result on, plus a day with known spend
        # and no result reported yet, both within trailing-30 -- `tracked_zero.apply()` derives
        # the absent day to a rule-marked zero, and `_trailing_30` resolves through it.
        campaign_id = self._imported_campaign_with_days([
            (0, 200, "purchase", None, None, None),
            (5, 100, "purchase", 5, "omni_purchase", "7d_click+1d_view"),
        ])
        end = coresettings.today_for_org(web.conn, org_id=self.org_id) - timedelta(days=1)
        start = end - timedelta(days=6)
        derived = tracked_zero.apply(
            web.conn, self.org_id, self.brand_id, campaign_id, start, end, end,
        )
        self.assertEqual(derived["derived"], 1)
        web.conn.commit()
        campaign = {
            **repository.get_campaign(web.conn, self.org_id, self.brand_id, campaign_id),
            "result_kind": "purchase",
        }
        result = targets.resolve(web.conn, self.org_id, self.brand_id, campaign)
        self.assertEqual(result["basis"], "trailing_30")
        self.assertAlmostEqual(result["value"], (200 + 100) / 5)
        self.assertEqual(result["missing"], [])

    def test_trailing_30_excludes_todays_partial_day(self):
        campaign_id = self._imported_campaign_with_days([
            (0, 100, "engagement", 10, "post_engagement", "7d_click+1d_view"),
        ])
        entity = web.conn.execute(
            "SELECT id FROM ads_external_entity WHERE campaign_id=%s AND native_kind='campaign'",
            (campaign_id,),
        ).fetchone()
        today = coresettings.today_for_org(web.conn, org_id=self.org_id)
        external.upsert_observation(
            web.conn, self.org_id, self.brand_id, campaign_id,
            {
                "entity_id": entity["id"], "day": today, "metric_scope": "campaign",
                "attribution_key": "unused-today", "currency": "TWD", "source": "meta",
                "spend": 999999,
            },
            result_kind="engagement", result_count=1, result_action="post_engagement",
            result_attribution="7d_click+1d_view",
        )
        web.conn.commit()
        campaign = repository.get_campaign(web.conn, self.org_id, self.brand_id, campaign_id)
        result = targets.resolve(web.conn, self.org_id, self.brand_id, campaign)
        self.assertEqual(result["basis"], "trailing_30")
        self.assertAlmostEqual(result["value"], 100 / 10)

    # -- result_kind provenance: the real Meta adapter mapping, never a dict literal ------------

    def test_imported_sales_objective_from_meta_resolves_break_even(self):
        product_id = self._product(unit_variable_cost=150)
        campaign_id = self._imported_campaign_with_objective("OUTCOME_SALES", product_id=product_id)
        campaign = repository.get_campaign(web.conn, self.org_id, self.brand_id, campaign_id)
        self.assertEqual(campaign["result_kind"], "purchase")
        result = targets.resolve(web.conn, self.org_id, self.brand_id, campaign)
        self.assertEqual(result["basis"], "break_even")
        self.assertEqual(result["value"], 300)  # 500 - 150 - 50
        self.assertEqual(result["result_kind"], "purchase")

    def test_imported_engagement_objective_from_meta_resolves_trailing_30(self):
        campaign_id = self._imported_campaign_with_days([
            (0, 100, "engagement", 10, "post_engagement", "7d_click+1d_view"),
            (5, 200, "engagement", 10, "post_engagement", "7d_click+1d_view"),
        ], objective="OUTCOME_ENGAGEMENT")
        campaign = repository.get_campaign(web.conn, self.org_id, self.brand_id, campaign_id)
        self.assertEqual(campaign["result_kind"], "engagement")
        result = targets.resolve(web.conn, self.org_id, self.brand_id, campaign)
        self.assertEqual(result["basis"], "trailing_30")
        self.assertAlmostEqual(result["value"], (100 + 200) / (10 + 10))

    def test_imported_unmapped_objective_from_meta_is_missing_not_zero(self):
        campaign_id = self._imported_campaign_with_days([], objective="OUTCOME_AWARENESS")
        campaign = repository.get_campaign(web.conn, self.org_id, self.brand_id, campaign_id)
        self.assertIsNone(campaign["result_kind"])
        result = targets.resolve(web.conn, self.org_id, self.brand_id, campaign)
        self.assertIsNone(result["value"])
        self.assertIsNone(result["basis"])
        self.assertIn("trailing_30", result["missing"])

    # -- regression: PUT .../target never touches the legacy success_* triple -------------------

    def test_put_target_leaves_legacy_success_fields_byte_identical(self):
        campaign = repository.create_campaign(web.conn, self.org_id, self.brand_id, {
            "name": "既有 CPA 活動", "goal_text": "衝一波", "objective": "購買",
            "success_metric": "cpa", "success_target": 300, "success_basis": "手動輸入",
        }, created_by="測試員")
        web.conn.commit()
        before = web.conn.execute(
            "SELECT success_metric, success_target, success_basis FROM ads_campaign WHERE id=%s",
            (campaign["id"],),
        ).fetchone()
        repository.save_campaign_target(
            web.conn, self.org_id, self.brand_id, campaign["id"],
            basis="own", value=250, expected_revision=0, actor="測試員",
        )
        after = web.conn.execute(
            "SELECT success_metric, success_target, success_basis FROM ads_campaign WHERE id=%s",
            (campaign["id"],),
        ).fetchone()
        self.assertEqual(dict(before), dict(after))


if __name__ == "__main__":
    unittest.main()
