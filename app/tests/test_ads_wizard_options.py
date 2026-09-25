"""app/tests/test_ads_wizard_options.py — F30-I04 (Feature F30 Contracts B, C): the
new-campaign wizard's options read and the one objective catalog.

Falsifiers: an archived product (or a sell way under an archived product) is never offered; a
product with sell ways is offered as its sell ways; a stale or not-yet-effective economics row
never shows as today's price; a confirmed row with no cost is not `has_cost`; the photo of the
product that owns the knowledge is the sell way's thumbnail; reserved objectives are listed but
not available and 加購物車 is accepted but unlisted.
"""

import datetime
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

import app.main as main
import app.shared.web as web
from app.ads import brief, objectives, wizard_options
from app.brand_intelligence import repository as bi_repo
from app.core import db as coredb
from app.core import settings as coresettings

ACTOR = "測試員"


class WizardOptionsTest(unittest.TestCase):
    def setUp(self):
        self.org_id = coredb.DEV_ORG_ID
        self.brand = bi_repo.create_brand(
            web.conn, org_id=self.org_id, name="測試品牌：建立精靈選項", client_name=None,
            actor=ACTOR,
        )
        self.brand_id = self.brand["id"]
        self.today = coresettings.today_for_org(web.conn, org_id=self.org_id)

        def product(name, parent_id=None):
            return bi_repo.create_product(
                web.conn, self.brand_id, name=name, actor=ACTOR, parent_id=parent_id,
            )

        def economics(product_row, **kwargs):
            return bi_repo.save_product_economics(
                web.conn, self.brand_id, product_row["id"], actor=ACTOR, currency="TWD",
                confirmed_by=ACTOR, **kwargs,
            )

        # Standalone product with a cost.
        self.brush = product("A 杯刷三入組")
        economics(self.brush, selling_price=390, unit_variable_cost=120, shipping_cost=0)
        # A product with two sell ways: offered as the sell ways, never as itself.
        self.cup = product("B 晨光隨行杯")
        self.cup_single = product("B 晨光隨行杯 · 單品", parent_id=self.cup["id"])
        economics(self.cup_single, selling_price=1580, unit_variable_cost=900, shipping_cost=160)
        self.cup_fall = product("B 晨光隨行杯 · 秋季新色", parent_id=self.cup["id"])
        # Confirmed economics with no unit cost -> price known, has_cost false.
        economics(self.cup_fall, selling_price=1680)
        # Archived product, and a sell way under an archived product.
        self.old = product("C 舊款")
        economics(self.old, selling_price=500, unit_variable_cost=100)
        bi_repo.update_product(
            web.conn, self.brand_id, self.old["id"], name=self.old["name"], status="archived",
            actor=ACTOR,
        )
        self.gone = product("C 下架系列")
        self.gone_way = product("C 下架系列 · 單品", parent_id=self.gone["id"])
        bi_repo.update_product(
            web.conn, self.brand_id, self.gone["id"], name=self.gone["name"], status="archived",
            actor=ACTOR,
        )
        # No economics at all.
        self.bare = product("D 沒填數字")
        # Expired economics: not current, so no price and no cost.
        self.expired = product("E 過季品")
        economics(
            self.expired, selling_price=800, unit_variable_cost=300,
            effective_to=(self.today - datetime.timedelta(days=1)).isoformat(),
        )
        # Economics that only starts tomorrow: not current yet.
        self.future = product("F 預購品")
        economics(
            self.future, selling_price=990, unit_variable_cost=400,
            effective_from=(self.today + datetime.timedelta(days=1)).isoformat(),
        )
        # Photos hang off the parent (knowledge) product; the newest one wins.
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

    def test_products_are_active_sellable_items_in_name_order(self):
        payload = wizard_options.options(web.conn, self.org_id, self.brand_id)
        self.assertEqual([p["name"] for p in payload["products"]], [
            "A 杯刷三入組", "B 晨光隨行杯 · 單品", "B 晨光隨行杯 · 秋季新色",
            "D 沒填數字", "E 過季品", "F 預購品",
        ])

    def test_price_and_cost_come_from_current_economics_only(self):
        products = self._by_name(wizard_options.options(web.conn, self.org_id, self.brand_id))
        self.assertEqual(products["A 杯刷三入組"], {
            "id": self.brush["id"], "name": "A 杯刷三入組", "price": 390.0, "currency": "TWD",
            "thumbnail_url": None, "has_cost": True,
        })
        self.assertTrue(products["B 晨光隨行杯 · 單品"]["has_cost"])
        fall = products["B 晨光隨行杯 · 秋季新色"]
        self.assertEqual((fall["price"], fall["currency"], fall["has_cost"]), (1680.0, "TWD", False))
        for name in ("D 沒填數字", "E 過季品", "F 預購品"):
            row = products[name]
            self.assertEqual((row["price"], row["currency"], row["has_cost"]), (None, None, False), name)

    def test_sell_way_thumbnail_is_the_parent_products_newest_photo(self):
        products = self._by_name(wizard_options.options(web.conn, self.org_id, self.brand_id))
        expected = f"/brands/{self.brand_id}/assets/file/{self.cup_photo['id']}/cup.jpg"
        self.assertEqual(products["B 晨光隨行杯 · 單品"]["thumbnail_url"], expected)
        self.assertEqual(products["B 晨光隨行杯 · 秋季新色"]["thumbnail_url"], expected)
        self.assertIsNone(products["A 杯刷三入組"]["thumbnail_url"])  # a logo is not a photo

    def test_has_cost_uses_the_organisations_today(self):
        # The expired row ended yesterday in the org's own calendar; on the org's "yesterday"
        # it is still current -- the read follows `today_for_org`, not the machine's date.
        yesterday = self.today - datetime.timedelta(days=1)
        with patch.object(coresettings, "today_for_org", return_value=yesterday):
            products = self._by_name(wizard_options.options(web.conn, self.org_id, self.brand_id))
        self.assertTrue(products["E 過季品"]["has_cost"])
        self.assertEqual(products["E 過季品"]["price"], 800.0)

    def test_route_returns_products_and_objectives(self):
        client = TestClient(main.app)
        res = client.get(f"/api/ads/brands/{self.brand_id}/new-campaign/options")
        self.assertEqual(res.status_code, 200, res.text)
        body = res.json()
        self.assertEqual(set(body), {"products", "objectives"})
        self.assertEqual(len(body["products"]), 6)
        self.assertEqual(body["objectives"], objectives.catalog())

    def test_empty_brand_has_no_products(self):
        empty = bi_repo.create_brand(
            web.conn, org_id=self.org_id, name="測試品牌：沒有商品", client_name=None, actor=ACTOR,
        )
        payload = wizard_options.options(web.conn, self.org_id, empty["id"])
        self.assertEqual(payload["products"], [])
        self.assertTrue(payload["objectives"])


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
        self.assertEqual(brief._OBJECTIVES, frozenset({"購買", "加購物車", "名單", "流量", "知名度"}))

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
