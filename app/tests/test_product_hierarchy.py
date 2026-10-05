"""app/tests/test_product_hierarchy.py — F05-I02: knowledge lives on the mother product
(ARCHITECTURE.md §8 item 1). `context_compiler.compile()` resolves a sell way's `product_id`
through `bi_repo.knowledge_product_ids()` before reading facts, so a sell way with no facts of
its own still gets the mother product's confirmed facts in the prompt text, and a bundle (F43)
gets every component product's.

This file does not belong to any managed module, so it must not import `app.ads.*` or
`app.workbench.*` internals (the architecture checker would flag it) — only `context_compiler`
and the shared `brand_intelligence` repository.
"""

import unittest

import psycopg

import app.shared.web as web
from app.brand_intelligence import repository as bi_repo
from app.core import db as coredb
from app.core import rule_cards
from app.llm import context_compiler

ACTOR = "測試員"


class ContextCompilerFollowsMotherProductTest(unittest.TestCase):
    def setUp(self):
        self.brand = bi_repo.create_brand(
            web.conn, org_id=coredb.DEV_ORG_ID, name="測試品牌：知識掛母產品", client_name=None,
            actor=ACTOR,
        )
        self.brand_id = self.brand["id"]
        self.mother = bi_repo.create_product(web.conn, self.brand_id, name="薑黃錠", actor=ACTOR)
        self.sell_way = bi_repo.create_product(
            web.conn, self.brand_id, name="薑黃錠 · 單瓶", actor=ACTOR,
            parent_id=self.mother["id"],
        )
        bi_repo.create_product_fact(
            web.conn, self.brand_id, self.mother["id"], actor=ACTOR, fact_type="core_info",
            label="主成分", value="薑黃萃取物", status="confirmed", confirmed_by=ACTOR,
        )

    def test_compile_on_sell_way_includes_mother_products_facts(self):
        text, _ids, _bv, _pv = context_compiler.compile(
            web.conn, self.brand_id, self.sell_way["id"])
        self.assertIn("薑黃萃取物", text)

    def test_compile_on_mother_product_still_includes_its_own_facts(self):
        text, _ids, _bv, _pv = context_compiler.compile(
            web.conn, self.brand_id, self.mother["id"])
        self.assertIn("薑黃萃取物", text)


class ContextCompilerReadsEveryBundleProductTest(unittest.TestCase):
    """F43-I03: a bundle sell-way (several components) gets the facts, claims and rules of every
    knowledge product it sells, under the one shared fact/claim cap (hard rule 6)."""

    def setUp(self):
        self.brand_id = bi_repo.create_brand(
            web.conn, org_id=coredb.DEV_ORG_ID, name="測試品牌：組合讀兩個商品", client_name=None,
            actor=ACTOR,
        )["id"]
        self.gummy, self.tea, self.other = (
            bi_repo.create_product(web.conn, self.brand_id, name=name, actor=ACTOR)["id"]
            for name in ("晨光軟糖", "午後花茶", "別的商品"))
        for product_id, value in ((self.gummy, "每顆含維生素C 60mg"),
                                  (self.tea, "洛神花與玫瑰花瓣"),
                                  (self.other, "別的商品的成分")):
            bi_repo.create_product_fact(
                web.conn, self.brand_id, product_id, actor=ACTOR, fact_type="core_info",
                label="成分", value=value, status="confirmed", confirmed_by=ACTOR,
            )
        bi_repo.create_claim(web.conn, self.brand_id, actor=ACTOR, claim_text="午後花茶冷泡也好喝",
                             claim_type="approved", product_id=self.tea)
        bi_repo.create_claim(web.conn, self.brand_id, actor=ACTOR, claim_text="晨光軟糖治百病",
                             claim_type="forbidden", product_id=self.gummy)
        bi_repo.create_claim(web.conn, self.brand_id, actor=ACTOR, claim_text="台灣製造",
                             claim_type="approved")
        bi_repo.create_rule(web.conn, self.brand_id, actor=ACTOR, rule_type="tone",
                            content="花茶不說能瘦", severity="hard", product_id=self.tea)
        bases = [bi_repo.save_sell_way(web.conn, self.brand_id, name="單件", actor=ACTOR,
                                       product_id=product_id,
                                       economics={"selling_price": 500})["id"]
                 for product_id in (self.gummy, self.tea)]
        self.bundle = bi_repo.save_sell_way(
            web.conn, self.brand_id, name="早午組合", actor=ACTOR,
            components=[{"sell_way_id": base, "qty": 1} for base in bases],
            economics={"selling_price": 999},
        )["id"]

    def test_bundle_reads_both_products(self):
        text, ids, _bv, _pv = context_compiler.compile(web.conn, self.brand_id, self.bundle)
        for expected in ("每顆含維生素C 60mg", "洛神花與玫瑰花瓣", "午後花茶冷泡也好喝",
                         "晨光軟糖治百病", "花茶不說能瘦"):
            self.assertIn(expected, text)
        self.assertNotIn("別的商品的成分", text)
        self.assertEqual(text.count("台灣製造"), 1)  # a brand-wide claim is listed once
        self.assertEqual(len(ids), len(set(ids)))

    def test_bundle_facts_share_one_cap(self):
        rule_cards.set_value(web.conn, self.brand_id, "rule_prompt_cap", "max_active_rules",
                             1.0, actor=ACTOR, org_id=coredb.DEV_ORG_ID)
        text, _ids, _bv, _pv = context_compiler.compile(web.conn, self.brand_id, self.bundle)
        section = text.split("【事實】產品事實\n", 1)[1].split("\n\n", 1)[0]
        # Newest first under one cap of 1: the tea fact stays, the gummy fact is counted, not shown.
        self.assertEqual(section, "- 成分：洛神花與玫瑰花瓣\n（另有 1 筆較舊的產品事實沒有列出）")


class BaseAndComposedSellWayTest(unittest.TestCase):
    """F45 (drill 10 B1 / M1 / O1, drill 9 #9): a quantity has a unit. A base sell-way is the
    unit; a composed one is base × qty, and its empty price / list price / cost is derived from
    its own bases -- never from whichever one-unit sell-way of the product came first."""

    def setUp(self):
        self.brand_id = bi_repo.create_brand(
            web.conn, org_id=coredb.DEV_ORG_ID, name="測試品牌：賣法有單位", client_name=None,
            actor=ACTOR,
        )["id"]
        self.gummy = bi_repo.create_product(web.conn, self.brand_id, name="能量軟糖",
                                            actor=ACTOR)["id"]
        # 體驗包 is created first: the F43 「earliest qty-1 sell-way」 rule would have priced
        # 12 盒 from it (12 × 25 = 300) -- the drill-10 B1 defect.
        self.trial = self._base("體驗包", selling_price=100, unit_variable_cost=25)
        self.box = self._base("單盒", selling_price=180, unit_variable_cost=50)

    def _base(self, name, product_id=None, **economics):
        return bi_repo.save_sell_way(web.conn, self.brand_id, name=name, actor=ACTOR,
                                     product_id=product_id or self.gummy, economics=economics)

    def _composed(self, name, parts, **economics):
        return bi_repo.save_sell_way(
            web.conn, self.brand_id, name=name, actor=ACTOR, economics=economics,
            components=[{"sell_way_id": way["id"], "qty": qty} for way, qty in parts])

    def test_b1_twelve_boxes_cost_is_twelve_of_its_own_base(self):
        twelve = self._composed("12 盒", [(self.box, 12)], selling_price=1980,
                                shipping_cost=60)
        econ = bi_repo.get_product_economics(web.conn, self.brand_id, twelve["id"])
        self.assertEqual(float(econ["selling_price"]), 1980)
        self.assertEqual(float(econ["unit_variable_cost"]), 600)  # 12 × 50, not 12 × 25
        self.assertIn("unit_variable_cost", econ["derived_fields"])
        self.assertNotIn("selling_price", econ["derived_fields"])
        # break-even = 1,980 − 600 − 60 (the one formula reads these effective numbers)
        self.assertEqual(float(econ["selling_price"]) - float(econ["unit_variable_cost"])
                         - float(econ["shipping_cost"]), 1320)
        self.assertEqual((twelve["shape"], twelve["kind"], twelve["parent_id"]),
                         ("composed", "single", self.gummy))
        self.assertEqual(twelve["name"], "能量軟糖 · 12 盒")
        self.assertEqual(bi_repo.knowledge_product_ids(web.conn, self.brand_id, twelve["id"]),
                         [self.gummy])

    def test_five_boxes_and_two_packs_cost_300(self):
        mix = self._composed("5 盒＋2 包", [(self.box, 5), (self.trial, 2)], selling_price=990)
        econ = mix["economics"]
        self.assertEqual(float(econ["unit_variable_cost"]), 300)  # 5 × 50 + 2 × 25
        self.assertEqual(float(econ["list_price"]), 1100)  # 5 × 180 + 2 × 100
        self.assertEqual(econ["derived_fields"], ["list_price", "unit_variable_cost"])
        self.assertEqual(
            [(c["name"], c["qty"], float(c["price"]), float(c["cost"])) for c in mix["components"]],
            [("單盒", 5, 180.0, 50.0), ("體驗包", 2, 100.0, 25.0)],
        )

    def test_empty_composed_price_is_the_sum_of_its_base_prices(self):
        mix = self._composed("5 盒＋2 包", [(self.box, 5), (self.trial, 2)])
        econ = mix["economics"]
        self.assertEqual(float(econ["selling_price"]), 1100)
        self.assertIn("selling_price", econ["derived_fields"])
        raw = bi_repo.get_product_economics(web.conn, self.brand_id, mix["id"], raw=True)
        self.assertIsNone(raw["selling_price"])

    def test_unknown_base_cost_leaves_the_composed_cost_empty(self):
        refill = self._base("補充包", selling_price=150)  # no cost
        mix = self._composed("2 盒＋1 補充", [(self.box, 2), (refill, 1)], selling_price=480)
        econ = mix["economics"]
        self.assertIsNone(econ["unit_variable_cost"])
        self.assertNotIn("unit_variable_cost", econ["derived_fields"])

    def test_refusals(self):
        usd = self._base("美金盒", selling_price=6, currency="USD")
        three = self._composed("3 盒", [(self.box, 3)], selling_price=520)
        with self.assertRaisesRegex(ValueError, "幣別"):
            self._composed("混幣組", [(self.box, 1), (usd, 1)], selling_price=200)
        with self.assertRaisesRegex(ValueError, "數量至少 2"):
            self._composed("一盒", [(self.box, 1)], selling_price=180)
        with self.assertRaisesRegex(ValueError, "不是基本賣法"):
            self._composed("套組", [(three, 2)], selling_price=1000)
        with self.assertRaisesRegex(ValueError, "不是基本賣法"):
            bi_repo.save_sell_way(web.conn, self.brand_id, name="知識", actor=ACTOR,
                                  components=[{"sell_way_id": self.gummy, "qty": 2}],
                                  economics={"selling_price": 300})
        with self.assertRaisesRegex(ValueError, "不能換幣別"):
            self._base("單盒", selling_price=6, currency="USD")

    def test_cross_product_bundle_knowledge_is_each_product_once(self):
        tea = bi_repo.create_product(web.conn, self.brand_id, name="益生菌軟糖",
                                     actor=ACTOR)["id"]
        tea_box = self._base("單盒", product_id=tea, selling_price=220, unit_variable_cost=70)
        duo = self._composed("雙效組", [(self.box, 2), (tea_box, 1), (self.trial, 1)],
                             selling_price=499)
        self.assertEqual((duo["shape"], duo["kind"], duo["parent_id"]),
                         ("composed", "bundle", None))
        self.assertEqual(bi_repo.knowledge_product_ids(web.conn, self.brand_id, duo["id"]),
                         [self.gummy, tea])
        self.assertEqual(
            [s["id"] for s in bi_repo.list_sell_ways(web.conn, self.brand_id, tea)],
            [tea_box["id"], duo["id"]],
        )

    def test_own_offers_name_no_product(self):
        twelve = self._composed("12 盒", [(self.box, 12)], selling_price=1980)
        sale = self._base("限時單盒", selling_price=160, list_price=180)
        self.assertEqual(bi_repo.offer_sources(web.conn, self.brand_id, twelve["id"]), [
            {"offer_key": "bundle", "sentence": "優惠價 NT$1,980（原價 NT$2,160）"}])
        self.assertEqual(bi_repo.offer_sources(web.conn, self.brand_id, sale["id"]), [
            {"offer_key": "discount", "sentence": "優惠價 NT$160（原價 NT$180）"}])

    def test_free_shipping_is_the_sell_ways_own_sentence(self):
        bi_repo.save_brand_policies(web.conn, self.brand_id, [
            {"key": "ship_threshold", "params": {"threshold": 999}},
        ], actor=ACTOR)
        free_box = bi_repo.save_sell_way(
            web.conn, self.brand_id, name="單盒", actor=ACTOR, product_id=self.gummy,
            economics={"selling_price": 180, "unit_variable_cost": 50}, free_shipping=True)
        self.assertTrue(free_box["free_shipping"])
        self.assertEqual(bi_repo.offer_sources(web.conn, self.brand_id, free_box["id"]), [
            {"offer_key": "free_shipping", "sentence": "免運"}])
        self.assertEqual(bi_repo.available_offer_keys(web.conn, self.brand_id, free_box["id"]),
                         {"free_shipping"})
        twelve = bi_repo.save_sell_way(
            web.conn, self.brand_id, name="12 盒", actor=ACTOR, free_shipping=True,
            components=[{"sell_way_id": self.box["id"], "qty": 12}],
            economics={"selling_price": 1980})
        # 1,980 reaches the store-wide 滿 999 免運, but the list carries one free_shipping
        # sentence -- the sell-way's own.
        sources = bi_repo.offer_sources(web.conn, self.brand_id, twelve["id"])
        self.assertEqual(sources, [
            {"offer_key": "bundle", "sentence": "優惠價 NT$1,980（原價 NT$2,160）"},
            {"offer_key": "free_shipping", "sentence": "這組免運"},
        ])
        self.assertEqual(bi_repo.available_offer_keys(web.conn, self.brand_id, twelve["id"]),
                         {"bundle", "free_shipping"})


class SameNameGuardTest(unittest.TestCase):
    """F36-I10 (drill-6 #16, Contract W): `create_product` is get-or-create on a trimmed,
    case-insensitive name within one scope (brand for parents, parent for sell-ways), and the
    two partial unique indexes back it up."""

    def setUp(self):
        self.brand_id = bi_repo.create_brand(
            web.conn, org_id=coredb.DEV_ORG_ID, name="測試品牌：同名守門", client_name=None,
            actor=ACTOR,
        )["id"]

    def _active_parents(self) -> list:
        return [p for p in bi_repo.all_product_rows(web.conn, self.brand_id)
                if p["parent_id"] is None and p["status"] == "active"]

    def test_same_parent_name_twice_returns_one_row(self):
        first = bi_repo.create_product(web.conn, self.brand_id, name="超能特惠組", actor=ACTOR)
        for variant in (" 超能特惠組 ", "超能特惠組", "\t超能特惠組\n"):
            again = bi_repo.create_product(web.conn, self.brand_id, name=variant, actor=ACTOR)
            self.assertEqual(again["id"], first["id"], repr(variant))
            self.assertEqual(again["name"], "超能特惠組")
        self.assertEqual(len(self._active_parents()), 1)
        # Existing row is returned untouched: no second create audit, no update audit.
        audits = web.conn.execute(
            "SELECT action FROM audit_log WHERE entity_type = 'product' AND entity_id = %s",
            (first["id"],),
        ).fetchall()
        self.assertEqual([a["action"] for a in audits], ["create"])

    def test_case_variants_collapse_to_one_row(self):
        first = bi_repo.create_product(web.conn, self.brand_id, name="Omega Plus", actor=ACTOR)
        for variant in ("omega plus", "OMEGA PLUS", " Omega plus "):
            again = bi_repo.create_product(web.conn, self.brand_id, name=variant, actor=ACTOR)
            self.assertEqual(again["id"], first["id"], repr(variant))
        self.assertEqual(len(self._active_parents()), 1)

    def test_created_name_is_stored_trimmed(self):
        row = bi_repo.create_product(web.conn, self.brand_id, name="  薑黃錠  ", actor=ACTOR)
        self.assertEqual(row["name"], "薑黃錠")
        self.assertEqual(bi_repo.get_product(web.conn, self.brand_id, row["id"])["name"], "薑黃錠")

    def test_sell_way_may_share_a_name_with_another_parent(self):
        mother = bi_repo.create_product(web.conn, self.brand_id, name="薑黃錠", actor=ACTOR)
        other = bi_repo.create_product(web.conn, self.brand_id, name="單瓶", actor=ACTOR)
        sell_way = bi_repo.create_product(
            web.conn, self.brand_id, name="單瓶", actor=ACTOR, parent_id=mother["id"])
        self.assertNotEqual(sell_way["id"], other["id"])
        self.assertEqual(sell_way["parent_id"], mother["id"])
        self.assertIsNone(bi_repo.get_product(web.conn, self.brand_id, other["id"])["parent_id"])

    def test_two_sell_ways_with_one_name_under_one_parent_collapse(self):
        mother = bi_repo.create_product(web.conn, self.brand_id, name="薑黃錠", actor=ACTOR)
        first = bi_repo.create_product(
            web.conn, self.brand_id, name="薑黃錠 · 單瓶", actor=ACTOR, parent_id=mother["id"])
        second = bi_repo.create_product(
            web.conn, self.brand_id, name=" 薑黃錠 · 單瓶 ", actor=ACTOR, parent_id=mother["id"])
        self.assertEqual(second["id"], first["id"])
        children = [p for p in bi_repo.all_product_rows(web.conn, self.brand_id)
                    if p["parent_id"] == mother["id"]]
        self.assertEqual(len(children), 1)

    def test_same_sell_way_name_under_two_parents_stays_two_rows(self):
        mother_a = bi_repo.create_product(web.conn, self.brand_id, name="薑黃錠", actor=ACTOR)
        mother_b = bi_repo.create_product(web.conn, self.brand_id, name="魚油", actor=ACTOR)
        child_a = bi_repo.create_product(
            web.conn, self.brand_id, name="單瓶", actor=ACTOR, parent_id=mother_a["id"])
        child_b = bi_repo.create_product(
            web.conn, self.brand_id, name="單瓶", actor=ACTOR, parent_id=mother_b["id"])
        self.assertNotEqual(child_a["id"], child_b["id"])

    def test_index_is_the_backstop_for_a_direct_insert(self):
        """The partial unique index rejects a same-name active parent even when the facade is
        bypassed; an archived same-name row is not in the index."""
        first = bi_repo.create_product(web.conn, self.brand_id, name="守門測試", actor=ACTOR)
        org_id = web.conn.execute(
            "SELECT org_id FROM brand WHERE id = %s", (self.brand_id,)).fetchone()["org_id"]
        insert = (
            "INSERT INTO product (id, org_id, brand_id, name, status, knowledge_version,"
            " created_at, updated_at, parent_id) VALUES (%s, %s, %s, %s, %s, 1, %s, %s, NULL)"
        )
        with self.assertRaises(psycopg.errors.UniqueViolation):
            web.conn.execute(insert, (coredb.new_id("prd"), org_id, self.brand_id, " 守門測試 ",
                                      "active", coredb.now_utc(), coredb.now_utc()))
        web.conn.rollback()
        web.conn.execute(insert, (coredb.new_id("prd"), org_id, self.brand_id, "守門測試",
                                  "archived", coredb.now_utc(), coredb.now_utc()))
        web.conn.commit()
        self.assertEqual(len(self._active_parents()), 1)
        self.assertEqual(self._active_parents()[0]["id"], first["id"])


if __name__ == "__main__":
    unittest.main()
