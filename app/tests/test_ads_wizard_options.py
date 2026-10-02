"""app/tests/test_ads_wizard_options.py — F30-I04 (Feature F30 Contracts B, C), re-cut by
F43-I04: the new-campaign wizard's options read and the one objective catalog.

Falsifiers: only finished sell-ways are offered -- never a knowledge product itself, never an
archived sell-way or a sell-way of an archived or 建到一半 (`onboarding_step` set) product, and a
bundle is left out when any of its products is 建到一半; singles are grouped by knowledge product,
bundles last; a stale or not-yet-effective economics row never shows as today's price; a
confirmed row with no cost is not `has_cost`; a bundle's break-even uses its derived cost and its
offer labels name its own 組合價 and the brand's 免運; customer groups, landing and cap are the
sell-way's; the photo of the knowledge product is the thumbnail; reserved objectives are listed
but not available and 加購物車 is accepted but unlisted.
"""

import datetime
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

import app.main as main
import app.shared.web as web
from app.ads import brief, objectives, wizard_options
from app.ads import repository as ads_repo
from app.brand_intelligence import repository as bi_repo
from app.core import db as coredb
from app.core import settings as coresettings

ACTOR = "測試員"


class _OptionsBase(unittest.TestCase):
    def setUp(self):
        self.org_id = coredb.DEV_ORG_ID
        self.brand = bi_repo.create_brand(
            web.conn, org_id=self.org_id, name="測試品牌：建立精靈選項", client_name=None,
            actor=ACTOR,
        )
        self.brand_id = self.brand["id"]
        self.today = coresettings.today_for_org(web.conn, org_id=self.org_id)

        def product(name):
            return bi_repo.create_product(web.conn, self.brand_id, name=name, actor=ACTOR)

        def sell_way(name, components, **money):
            """F45: [(product, 1)] -> a base sell-way of it; else [(base sell-way, qty)] ->
            a composed sell-way."""
            first, qty = components[0]
            if len(components) == 1 and qty == 1 and first["parent_id"] is None:
                return bi_repo.save_sell_way(
                    web.conn, self.brand_id, name=name, actor=ACTOR, economics=money,
                    product_id=first["id"],
                )
            return bi_repo.save_sell_way(
                web.conn, self.brand_id, name=name, actor=ACTOR, economics=money,
                components=[{"sell_way_id": w["id"], "qty": qty} for w, qty in components],
            )

        def economics(way, **kwargs):
            return bi_repo.save_product_economics(
                web.conn, self.brand_id, way["id"], actor=ACTOR, currency="TWD",
                confirmed_by=ACTOR, **kwargs,
            )

        def archive(row):
            bi_repo.update_product(web.conn, self.brand_id, row["id"], name=row["name"],
                                   status="archived", actor=ACTOR)

        # The brand's 滿額免運 (NT$999): an offer of the sell-ways priced at 999 or more.
        bi_repo.save_brand_policies(web.conn, self.brand_id, [
            {"key": "ship_threshold", "params": {"threshold": 999}},
        ], actor=ACTOR)
        # A knowledge product with one sell-way and a cost.
        self.brush = product("A 杯刷")
        self.brush_single = sell_way("單支", [(self.brush, 1)], selling_price=390,
                                     unit_variable_cost=120, shipping_cost=0)
        # A product with two sell-ways: offered as the sell-ways, never as itself.
        self.cup = product("B 晨光隨行杯")
        bi_repo.set_product_page_url(web.conn, self.brand_id, self.cup["id"],
                                     "https://shop.example.test/cup", actor=ACTOR)
        self.cup_single = sell_way("單品", [(self.cup, 1)], selling_price=1580,
                                   unit_variable_cost=900, shipping_cost=160, cap_per_sale=500)
        # Confirmed economics with no unit cost -> price known, has_cost false.
        self.cup_fall = sell_way("秋季新色", [(self.cup, 1)], selling_price=1680)
        self.cup_groups = bi_repo.save_customer_groups(web.conn, self.brand_id, self.cup["id"], [
            {"who": "通勤上班族", "pain_keys": ["effort"]},
            {"who": "登山客", "pain_keys": ["availability", "cost"]},
        ], actor=ACTOR)
        self.brush_groups = bi_repo.save_customer_groups(
            web.conn, self.brand_id, self.brush["id"],
            [{"who": "懶得洗杯的人", "pain_keys": ["effort"]}], actor=ACTOR,
        )
        # A bundle of both: no cost of its own (Σ 900 + 120), list price Σ 1580 + 390 = 1970.
        self.duo = sell_way("雙效組", [(self.cup_single, 1), (self.brush_single, 1)],
                            selling_price=1799,
                            shipping_cost=60)
        # Archived knowledge product (with its sell-way), and an archived sell-way.
        self.old = product("C 舊款")
        sell_way("單品", [(self.old, 1)], selling_price=500, unit_variable_cost=100)
        archive(self.old)
        self.cup_retired = sell_way("舊包裝", [(self.cup, 1)], selling_price=1500)
        archive(self.cup_retired)
        # A product being built (建到一半): neither its sell-way nor a bundle with it is offered.
        self.half = product("G 益生菌")
        half_box = sell_way("單盒", [(self.half, 1)], selling_price=459, unit_variable_cost=110)
        sell_way("半套組", [(half_box, 1), (self.cup_single, 1)], selling_price=1900)
        bi_repo.set_product_onboarding_step(web.conn, self.brand_id, self.half["id"], 2,
                                            actor=ACTOR)
        # A knowledge product with no sell-way at all: nothing to sell.
        self.bare = product("D 沒有賣法")
        # Expired economics: not current, so no price and no cost.
        self.expired = product("E 過季品")
        self.expired_way = sell_way("單品", [(self.expired, 1)], selling_price=800,
                                    unit_variable_cost=300)
        economics(
            self.expired_way, selling_price=800, unit_variable_cost=300,
            effective_to=(self.today - datetime.timedelta(days=1)).isoformat(),
        )
        # Economics that only starts tomorrow: not current yet.
        self.future = product("F 預購品")
        self.future_way = sell_way("單品", [(self.future, 1)], selling_price=990,
                                   unit_variable_cost=400)
        economics(
            self.future_way, selling_price=990, unit_variable_cost=400,
            effective_from=(self.today + datetime.timedelta(days=1)).isoformat(),
        )
        # Photos hang off the knowledge product; the newest one wins.
        bi_repo.create_official_asset(
            web.conn, self.brand_id, actor=ACTOR, asset_kind="product_photo",
            storage_key="brand/x/old.jpg", product_id=self.cup["id"],
        )
        self.cup_photo = bi_repo.create_official_asset(
            web.conn, self.brand_id, actor=ACTOR, asset_kind="product_photo",
            storage_key="brand/x/cup.jpg", product_id=self.cup["id"],
        )
        bi_repo.create_official_asset(
            web.conn, self.brand_id, actor=ACTOR, asset_kind="logo",
            storage_key="brand/x/logo.png", product_id=self.brush["id"],
        )

    def _by_name(self, payload):
        return {p["name"]: p for p in payload["products"]}


class WizardOptionsTest(_OptionsBase):
    def test_only_finished_sell_ways_singles_by_product_then_bundles(self):
        payload = wizard_options.options(web.conn, self.org_id, self.brand_id)
        self.assertEqual([p["name"] for p in payload["products"]], [
            "A 杯刷 · 單支", "B 晨光隨行杯 · 單品", "B 晨光隨行杯 · 秋季新色",
            "E 過季品 · 單品", "F 預購品 · 單品", "雙效組",
        ])
        ids = {p["id"] for p in payload["products"]}
        for knowledge in (self.brush, self.cup, self.bare, self.half):
            self.assertNotIn(knowledge["id"], ids)  # a knowledge product is never pickable
        self.assertNotIn(self.cup_retired["id"], ids)

    def test_single_sell_way_option(self):
        products = self._by_name(wizard_options.options(web.conn, self.org_id, self.brand_id))
        self.assertEqual(products["B 晨光隨行杯 · 單品"], {
            "id": self.cup_single["id"], "name": "B 晨光隨行杯 · 單品", "display_name": "單品",
            "kind": "single", "knowledge_product_id": self.cup["id"],
            "knowledge_product_name": "B 晨光隨行杯", "price": 1580.0, "currency": "TWD",
            "has_cost": True, "break_even": 520.0, "derived_fields": [], "cap_per_sale": 500.0,
            "offer_labels": ["免運"],
            "customer_groups": [{"id": g["id"], "who": g["who"]} for g in self.cup_groups],
            "landing_url": "https://shop.example.test/cup",
            "thumbnail_url": f"/brands/{self.brand_id}/assets/file/{self.cup_photo['id']}/cup.jpg",
            "previous": None, "learned": None,  # F46-I08: never ran
        })
        brush = products["A 杯刷 · 單支"]
        # No own cap -> the break-even; under the 999 threshold -> no 免運; no page -> no landing.
        self.assertEqual((brush["break_even"], brush["cap_per_sale"], brush["offer_labels"],
                          brush["landing_url"]), (270.0, 270.0, [], None))

    def test_bundle_option_uses_derived_cost_its_own_offer_and_every_products_groups(self):
        products = self._by_name(wizard_options.options(web.conn, self.org_id, self.brand_id))
        duo = products["雙效組"]
        self.assertEqual((duo["kind"], duo["display_name"]), ("bundle", "雙效組"))
        self.assertEqual((duo["knowledge_product_id"], duo["knowledge_product_name"]),
                         (self.cup["id"], "B 晨光隨行杯"))
        self.assertTrue(duo["has_cost"])  # Σ component costs
        # F45 (ads §6.49 「Picker」): the derived numbers are named.
        self.assertEqual(duo["derived_fields"], ["list_price", "unit_variable_cost"])
        self.assertEqual(duo["break_even"], 719.0)  # 1799 − (900 + 120) − 60
        self.assertEqual(duo["cap_per_sale"], 719.0)
        self.assertEqual(duo["offer_labels"], ["組合價", "免運"])
        self.assertEqual([g["who"] for g in duo["customer_groups"]],
                         ["通勤上班族", "登山客", "懶得洗杯的人"])
        # The first product's page.
        self.assertEqual(duo["landing_url"], "https://shop.example.test/cup")
        self.assertTrue(duo["thumbnail_url"].endswith("/cup.jpg"))

    def test_price_and_cost_come_from_current_economics_only(self):
        products = self._by_name(wizard_options.options(web.conn, self.org_id, self.brand_id))
        fall = products["B 晨光隨行杯 · 秋季新色"]
        self.assertEqual(
            (fall["price"], fall["currency"], fall["has_cost"], fall["break_even"]),
            (1680.0, "TWD", False, None),
        )
        for name in ("E 過季品 · 單品", "F 預購品 · 單品"):
            row = products[name]
            self.assertEqual(
                (row["price"], row["currency"], row["has_cost"], row["break_even"],
                 row["derived_fields"]),
                (None, None, False, None, []), name,
            )

    def test_a_composed_sell_way_with_an_empty_price_names_its_derived_fields(self):
        """F45 (ads §6.49 「Picker」): 兩支組 = 單支 × 2 with nothing typed -> price, list price
        and cost all derived (2 × 390, 2 × 120), named in `derived_fields`."""
        bi_repo.save_sell_way(
            web.conn, self.brand_id, name="兩支組", actor=ACTOR, economics={"shipping_cost": 0},
            components=[{"sell_way_id": self.brush_single["id"], "qty": 2}],
        )
        products = self._by_name(wizard_options.options(web.conn, self.org_id, self.brand_id))
        pair = products["A 杯刷 · 兩支組"]
        self.assertEqual((pair["price"], pair["break_even"]), (780.0, 540.0))
        self.assertEqual(pair["derived_fields"],
                         ["selling_price", "list_price", "unit_variable_cost"])

    def test_sell_way_thumbnail_is_the_knowledge_products_newest_photo(self):
        products = self._by_name(wizard_options.options(web.conn, self.org_id, self.brand_id))
        expected = f"/brands/{self.brand_id}/assets/file/{self.cup_photo['id']}/cup.jpg"
        self.assertEqual(products["B 晨光隨行杯 · 單品"]["thumbnail_url"], expected)
        self.assertEqual(products["B 晨光隨行杯 · 秋季新色"]["thumbnail_url"], expected)
        self.assertIsNone(products["A 杯刷 · 單支"]["thumbnail_url"])  # a logo is not a photo

    def test_finishing_the_half_built_product_makes_its_sell_ways_pickable(self):
        bi_repo.set_product_onboarding_step(web.conn, self.brand_id, self.half["id"], None,
                                            actor=ACTOR)
        names = [p["name"] for p in wizard_options.options(
            web.conn, self.org_id, self.brand_id)["products"]]
        self.assertIn("G 益生菌 · 單盒", names)
        self.assertEqual(names[-2:], ["雙效組", "半套組"])  # bundles last, in creation order

    def test_has_cost_uses_the_organisations_today(self):
        # The expired row ended yesterday in the org's own calendar; on the org's "yesterday"
        # it is still current -- the read follows `today_for_org`, not the machine's date.
        yesterday = self.today - datetime.timedelta(days=1)
        with patch.object(coresettings, "today_for_org", return_value=yesterday):
            products = self._by_name(wizard_options.options(web.conn, self.org_id, self.brand_id))
        self.assertTrue(products["E 過季品 · 單品"]["has_cost"])
        self.assertEqual(products["E 過季品 · 單品"]["price"], 800.0)

    def test_route_returns_products_and_objectives(self):
        client = TestClient(main.app)
        res = client.get(f"/api/ads/brands/{self.brand_id}/new-campaign/options")
        self.assertEqual(res.status_code, 200, res.text)
        body = res.json()
        self.assertEqual(set(body), {"products", "objectives", "default_objective",
                                     "default_platform"})
        self.assertEqual(len(body["products"]), 6)
        self.assertEqual(body["objectives"], objectives.catalog())
        self.assertIsNone(body["default_objective"])  # the brand has no conversion goal yet

    def test_default_objective_is_the_brands_conversion_goal(self):
        # F43-I18: one table in `objectives`; a booking is a contact, so it maps like a lead.
        for goal, expected in (("purchase", "購買"), ("lead", "名單"), ("booking", "名單"),
                               ("awareness", "知名度"), (None, None)):
            bi_repo.set_brand_switches(web.conn, self.brand_id, market_region=None,
                                       conversion_goal=goal, actor=ACTOR)
            payload = wizard_options.options(web.conn, self.org_id, self.brand_id)
            self.assertEqual(payload["default_objective"], expected, goal)
            if expected is not None:
                self.assertIn(expected, objectives.AVAILABLE)

    def test_a_sell_ways_groups_resolve_from_its_product_ids(self):
        # The campaign PATCH's resolver agrees with the wizard's list for a pickable sell-way.
        products = self._by_name(wizard_options.options(web.conn, self.org_id, self.brand_id))
        bundle = products["雙效組"]
        self.assertEqual(
            [g["id"] for g in wizard_options.product_customer_groups(
                web.conn, self.brand_id, [bundle["id"]])],
            [g["id"] for g in bundle["customer_groups"]],
        )
        self.assertEqual(wizard_options.product_customer_groups(web.conn, self.brand_id, []), [])

    def test_empty_brand_has_no_products(self):
        empty = bi_repo.create_brand(
            web.conn, org_id=self.org_id, name="測試品牌：沒有商品", client_name=None, actor=ACTOR,
        )
        payload = wizard_options.options(web.conn, self.org_id, empty["id"])
        self.assertEqual(payload["products"], [])
        self.assertTrue(payload["objectives"])


class PreviousAndLearnedTest(_OptionsBase):
    """F46-I08 (Contract D): each option's `previous` (the sell-way's newest internal non-draft
    campaign) and `learned` (Contract L over its closed campaigns), and `default_platform`."""

    def _campaign(self, way, name, status, created_at, *, platform="meta", cap=450,
                  budget=10000, closed_at=None):
        campaign = ads_repo.create_campaign(web.conn, self.org_id, self.brand_id, {
            "name": name, "goal_text": "x", "objective": "購買", "target_cost": cap,
            "start_date": "2026-09-05", "end_date": "2026-09-18", "status": status,
            "context_json": {"product_ids": [way["id"]]},
            "constraints_json": {k: v for k, v in (("platform", platform), ("budget", budget))
                                 if v is not None},
        }, created_by=ACTOR)
        web.conn.execute(
            "UPDATE ads_campaign SET created_at = %s, closed_at = %s WHERE id = %s",
            (created_at, closed_at, campaign["id"]),
        )
        return campaign

    def _row(self, campaign, ad_id, *, verdict, rank, of, sales, spend):
        cpr = round(spend / sales) if sales else "none"
        bi_repo.record_learning(
            web.conn, self.brand_id, actor=ACTOR, learning_text=ad_id,
            applicability_scope=(
                f"coord；v=2；verdict={verdict}；rank={rank}；of={of}；sales={sales}；"
                f"spend={spend}；cpr={cpr}；cap=450；few=0；group=none；audience=cold；pain=effort"
                "；angle=box；hook=h；proof=none；offer=none；format=single_image；cur=TWD"
            ),
            confidence="observed", sample_size="高",
            source_cycle_id=f"{campaign['id']}:{ad_id}", source_track="coordinate",
        )

    def _option(self, way):
        return next(p for p in wizard_options.options(web.conn, self.org_id, self.brand_id)
                    ["products"] if p["id"] == way["id"])

    def test_a_sell_way_that_never_ran_has_no_previous_and_no_learning(self):
        option = self._option(self.brush_single)
        self.assertIsNone(option["previous"])
        self.assertIsNone(option["learned"])
        self.assertIsNone(wizard_options.previous_campaign(
            web.conn, self.org_id, self.brand_id, self.brush_single["id"]))

    def test_one_closed_campaign_is_the_previous_with_its_learned_spend(self):
        closed = self._campaign(self.cup_single, "單品・09/05～09/18", "closed",
                                "2026-09-01T00:00:00Z", closed_at="2026-09-19T02:00:00Z")
        self._row(closed, "ad_a", verdict="keep", rank=1, of=2, sales=5, spend=2000)
        self._row(closed, "ad_b", verdict="replace", rank=2, of=2, sales=0, spend=775)

        option = self._option(self.cup_single)

        self.assertEqual(option["previous"], {
            "campaign_id": closed["id"], "campaign_name": "單品・09/05～09/18",
            "platform": "meta", "cap": 450.0, "budget": 10000.0, "spend": 2775,
        })
        self.assertEqual(option["learned"], {
            "campaigns": [{"id": closed["id"], "name": "單品・09/05～09/18"}],
            "keep": 1, "replace": 1,
        })
        # Another sell-way of the same product did not run.
        self.assertIsNone(self._option(self.cup_fall)["previous"])

    def test_two_campaigns_the_newest_is_previous_drafts_and_other_sell_ways_ignored(self):
        older = self._campaign(self.cup_single, "第一期", "closed", "2026-08-01T00:00:00Z",
                               closed_at="2026-08-20T00:00:00Z")
        self._row(older, "ad_a", verdict="keep", rank=1, of=1, sales=6, spend=1800)
        newer = self._campaign(self.cup_single, "第二期", "live", "2026-09-01T00:00:00Z",
                               platform=None, cap=None, budget=None)
        self._campaign(self.cup_single, "草稿", "draft", "2026-09-20T00:00:00Z",
                       platform="google_ads", cap=111)
        self._campaign(self.brush_single, "別的賣法", "live", "2026-09-25T00:00:00Z", cap=222)

        option = self._option(self.cup_single)

        # The newest non-draft campaign, its empty fields stay empty (never the older one's).
        self.assertEqual(option["previous"], {
            "campaign_id": newer["id"], "campaign_name": "第二期",
            "platform": None, "cap": None, "budget": None, "spend": None,
        })
        self.assertEqual(option["learned"], {
            "campaigns": [{"id": older["id"], "name": "第一期"}], "keep": 1, "replace": 0,
        })
        self.assertEqual(self._option(self.brush_single)["previous"]["cap"], 222.0)
        self.assertIsNone(self._option(self.brush_single)["learned"])

    def test_default_platform_is_the_first_connected_channel(self):
        payload = wizard_options.options(web.conn, self.org_id, self.brand_id)
        self.assertIsNone(payload["default_platform"])  # nothing connected
        rows = [{"key": "meta", "label": "Meta", "connected": False, "state_text": "未接上"},
                {"key": "google_ads", "label": "Google", "connected": True, "state_text": "已接上"}]
        with patch.object(wizard_options.channels, "list_channels", return_value=rows):
            payload = wizard_options.options(web.conn, self.org_id, self.brand_id)
        self.assertEqual(payload["default_platform"], "google_ads")


class ObjectiveCatalogTest(unittest.TestCase):
    def test_catalog_is_the_merged_list_in_order(self):
        rows = objectives.catalog()
        self.assertEqual(
            [(r["key"], r["available"]) for r in rows],
            [("購買", True), ("名單", True), ("流量", True), ("知名度", True),
             ("互動", False), ("App 推廣", False), ("來店", False)],
        )
        for row in rows:
            self.assertEqual(set(row), {"key", "label", "description", "available", "platforms"})
            self.assertEqual(set(row["platforms"]), {"meta", "google_ads"})
            self.assertTrue(row["description"])
        by_key = {r["key"]: r for r in rows}
        self.assertEqual(by_key["購買"]["platforms"], {"meta": "銷售業績", "google_ads": "銷售"})
        self.assertEqual(
            by_key["名單"]["platforms"], {"meta": "潛在顧客", "google_ads": "潛在客戶"},
        )
        self.assertEqual(
            by_key["知名度"]["platforms"]["google_ads"], "品牌認知度和觸及率",
        )
        self.assertIsNone(by_key["來店"]["platforms"]["meta"])
        self.assertNotIn("加購物車", by_key)

    def test_brief_accepts_available_objectives_and_add_to_cart_only(self):
        self.assertEqual(
            brief._OBJECTIVES, frozenset({"購買", "加購物車", "名單", "流量", "知名度"}),
        )

    def test_conversion_goal_table_maps_only_to_available_objectives(self):
        self.assertEqual(
            {goal: objectives.for_conversion_goal(goal)
             for goal in ("purchase", "lead", "booking", "awareness")},
            {"purchase": "購買", "lead": "名單", "booking": "名單", "awareness": "知名度"},
        )
        for unset in (None, "", "unknown", 3):
            self.assertIsNone(objectives.for_conversion_goal(unset))

    def test_check_refuses_reserved_and_unknown(self):
        self.assertEqual(objectives.check("加購物車"), "加購物車")
        for key in ("互動", "App 推廣", "來店"):
            with self.assertRaises(ValueError) as ctx:
                objectives.check(key)
            self.assertEqual(str(ctx.exception), "objective_unavailable")
        for bad in (None, "", "OUTCOME_SALES", 3):
            with self.assertRaises(ValueError) as ctx:
                objectives.check(bad)
            self.assertEqual(str(ctx.exception), "objective_unknown")

    def test_catalog_copies_do_not_leak_mutation(self):
        first = objectives.catalog()
        first[0]["platforms"]["google_ads"] = "改掉"
        self.assertEqual(objectives.catalog()[0]["platforms"]["google_ads"], "銷售")


if __name__ == "__main__":
    unittest.main()
