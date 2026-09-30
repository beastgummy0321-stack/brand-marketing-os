"""app/tests/test_intake_product_contract.py — F43-I01: the product-side data contract product
onboarding builds on (feature F43 decisions 「Storage」 and 「One resolver each」): sell-ways with
components, effective economics, the sell-way's own offer, product proof keys, customer groups,
the onboarding step and the product prefill. Only the brand_intelligence facade, the intake
repository and `app.core.vocab` are used (plus raw SQL for the DB CHECKs themselves).
"""

import unittest
from decimal import Decimal

import psycopg

from app.brand_intelligence import repository as repo
from app.core import vocab
from app.core.db import DEV_ORG_ID, new_id
from app.core.db import current as db_current
from app.intake import repository as intake_repo

ACTOR = "測試員"
_SEQ = [0]


def _brand(conn) -> str:
    _SEQ[0] += 1
    return repo.create_brand(
        conn, name=f"商品契約品牌{_SEQ[0]}", client_name=None, actor=ACTOR, org_id=DEV_ORG_ID
    )["id"]


def _econ(price, **more) -> dict:
    return {"selling_price": price, **more}


class SellWayTest(unittest.TestCase):
    def setUp(self):
        self.conn = db_current()
        self.bid = _brand(self.conn)
        self.a = repo.create_product(self.conn, self.bid, name="薑黃錠", actor=ACTOR)["id"]
        self.b = repo.create_product(self.conn, self.bid, name="魚油", actor=ACTOR)["id"]

    def _single(self, product_id, name, price, **more):
        return repo.save_sell_way(
            self.conn,
            self.bid,
            name=name,
            components=[{"product_id": product_id, "qty": more.pop("qty", 1)}],
            economics=_econ(price, **more),
            actor=ACTOR,
        )

    def test_single_sell_way_round_trip(self):
        sw = self._single(self.a, "單盒", 399, unit_variable_cost=120, shipping_cost=60)
        self.assertEqual(sw["name"], "薑黃錠 · 單盒")
        self.assertEqual(sw["display_name"], "單盒")
        self.assertEqual(sw["parent_id"], self.a)
        self.assertEqual(sw["kind"], "single")
        self.assertEqual(sw["components"], [{"product_id": self.a, "qty": 1, "name": "薑黃錠"}])
        econ = sw["economics"]
        self.assertEqual(econ["selling_price"], 399)
        self.assertEqual(econ["list_price"], 399)  # own unit: list price defaults to its own price
        self.assertEqual(econ["derived_fields"], ["list_price"])
        self.assertEqual(econ["unit_variable_cost"], 120)
        self.assertIsNone(
            repo.get_product_economics(self.conn, self.bid, sw["id"], raw=True)["list_price"]
        )
        self.assertEqual(repo.knowledge_product_ids(self.conn, self.bid, sw["id"]), [self.a])

        page = repo.set_product_page_url(
            self.conn, self.bid, self.a, " https://shop.example/a ", actor=ACTOR
        )
        self.assertEqual(page["page_url"], "https://shop.example/a")
        again = repo.save_sell_way(
            self.conn,
            self.bid,
            sell_way_id=sw["id"],
            name="單盒",
            components=[{"product_id": self.a, "qty": 1}],
            economics=_econ(379, list_price=399, cap_per_sale=150),
            actor=ACTOR,
        )
        self.assertEqual(again["id"], sw["id"])
        self.assertEqual(again["name"], "薑黃錠 · 單盒")
        self.assertEqual(again["effective_landing_url"], "https://shop.example/a")
        self.assertEqual(
            (
                again["economics"]["selling_price"],
                again["economics"]["list_price"],
                again["economics"]["cap_per_sale"],
            ),
            (379, 399, 150),
        )
        self.assertEqual(again["economics"]["derived_fields"], [])
        self.assertEqual(
            [s["id"] for s in repo.list_sell_ways(self.conn, self.bid, self.a)], [sw["id"]]
        )
        self.assertEqual(repo.list_sell_ways(self.conn, self.bid, self.b), [])

    def test_same_name_new_sell_way_is_the_same_row(self):
        first = self._single(self.a, "單盒", 399)
        second = self._single(self.a, " 單盒 ", 389)
        self.assertEqual(first["id"], second["id"])
        self.assertEqual(second["economics"]["selling_price"], 389)

    def test_bundle_round_trip_and_effective_money(self):
        self._single(self.a, "單盒", 399, unit_variable_cost=120)
        self._single(self.b, "單瓶", 599, unit_variable_cost=200)
        bundle = repo.save_sell_way(
            self.conn,
            self.bid,
            name="護眼雙效組",
            components=[{"product_id": self.b, "qty": 1}, {"product_id": self.a, "qty": 2}],
            economics=_econ(1199, shipping_cost=60),
            landing_url="https://shop.example/set",
            actor=ACTOR,
        )
        self.assertIsNone(bundle["parent_id"])
        self.assertEqual(bundle["kind"], "bundle")
        self.assertEqual(bundle["name"], "護眼雙效組")
        self.assertEqual(
            repo.knowledge_product_ids(self.conn, self.bid, bundle["id"]), [self.b, self.a]
        )
        self.assertEqual(repo.knowledge_product_id(self.conn, self.bid, bundle["id"]), self.b)
        econ = repo.get_product_economics(self.conn, self.bid, bundle["id"])
        self.assertEqual(econ["list_price"], Decimal("1397"))  # 599 + 2 × 399
        self.assertEqual(econ["unit_variable_cost"], Decimal("440"))  # 200 + 2 × 120
        self.assertEqual(econ["derived_fields"], ["list_price", "unit_variable_cost"])
        raw = repo.get_product_economics(self.conn, self.bid, bundle["id"], raw=True)
        self.assertIsNone(raw["list_price"])
        self.assertIsNone(raw["unit_variable_cost"])
        self.assertNotIn("derived_fields", raw)
        for product_id in (self.a, self.b):
            self.assertIn(
                bundle["id"],
                [s["id"] for s in repo.list_sell_ways(self.conn, self.bid, product_id)],
            )
        self.assertEqual(bundle["effective_landing_url"], "https://shop.example/set")

        # Full-list replace: drop 魚油, keep 薑黃錠 (row and order kept) -> the bundle is now a
        # single-product sell-way under 薑黃錠.
        shrunk = repo.save_sell_way(
            self.conn,
            self.bid,
            sell_way_id=bundle["id"],
            name="兩盒組",
            components=[{"product_id": self.a, "qty": 2}],
            economics=_econ(699),
            actor=ACTOR,
        )
        self.assertEqual((shrunk["parent_id"], shrunk["name"]), (self.a, "薑黃錠 · 兩盒組"))
        self.assertEqual(shrunk["components"], [{"product_id": self.a, "qty": 2, "name": "薑黃錠"}])

    def test_unknown_component_part_leaves_the_field_null(self):
        self._single(self.a, "單盒", 399, unit_variable_cost=120)
        bundle = repo.save_sell_way(
            self.conn,
            self.bid,
            name="雙效組",
            components=[{"product_id": self.a, "qty": 1}, {"product_id": self.b, "qty": 1}],
            economics=_econ(899),
            actor=ACTOR,
        )  # 魚油 has no single sell-way
        econ = repo.get_product_economics(self.conn, self.bid, bundle["id"])
        self.assertIsNone(econ["list_price"])
        self.assertIsNone(econ["unit_variable_cost"])
        self.assertEqual(econ["derived_fields"], [])
        self.assertNotIn("bundle", repo.available_offer_keys(self.conn, self.bid, bundle["id"]))

    def test_components_are_this_brands_knowledge_products(self):
        other = _brand(self.conn)
        foreign = repo.create_product(self.conn, other, name="別人的商品", actor=ACTOR)["id"]
        with self.assertRaises(ValueError):
            repo.save_sell_way(
                self.conn,
                self.bid,
                name="混組",
                components=[{"product_id": self.a, "qty": 1}, {"product_id": foreign, "qty": 1}],
                economics=_econ(500),
                actor=ACTOR,
            )
        sw = self._single(self.a, "單盒", 399)
        with self.assertRaises(ValueError):  # a sell-way is not a component
            repo.save_sell_way(
                self.conn,
                self.bid,
                name="套娃",
                components=[{"product_id": sw["id"], "qty": 1}],
                economics=_econ(500),
                actor=ACTOR,
            )
        for bad in (
            [],
            [{"product_id": self.a, "qty": 0}],
            [{"product_id": self.a, "qty": 1}, {"product_id": self.a, "qty": 2}],
        ):
            with self.assertRaises(ValueError, msg=repr(bad)):
                repo.save_sell_way(
                    self.conn,
                    self.bid,
                    name="壞組",
                    components=bad,
                    economics=_econ(500),
                    actor=ACTOR,
                )
        with self.assertRaises(ValueError):
            self._single(self.a, "負價", -1)
        with self.assertRaises(ValueError):
            repo.save_sell_way(
                self.conn,
                self.bid,
                name="怪欄位",
                components=[{"product_id": self.a, "qty": 1}],
                economics=_econ(100, discount=5),
                actor=ACTOR,
            )
        self.assertEqual(
            [s["display_name"] for s in repo.list_sell_ways(self.conn, self.bid)], ["單盒"]
        )

    def test_component_rows_are_checked_by_the_database(self):
        sw = self._single(self.a, "單盒", 399)
        with self.assertRaises(psycopg.errors.CheckViolation):
            self.conn.execute(
                "INSERT INTO product_component"
                " (id, org_id, brand_id, sell_way_id, product_id, qty) "
                "VALUES (%s, %s, %s, %s, %s, 0)",
                (new_id("pco"), DEV_ORG_ID, self.bid, sw["id"], self.b),
            )
        self.conn.rollback()

    def test_legacy_rows_resolve_as_before(self):
        child = repo.create_product(
            self.conn, self.bid, name="薑黃錠 · 舊單品", actor=ACTOR, parent_id=self.a
        )["id"]
        repo.save_product_economics(
            self.conn,
            self.bid,
            child,
            selling_price=399,
            currency="TWD",
            confirmed_by=ACTOR,
            actor=ACTOR,
        )
        self.assertEqual(repo.knowledge_product_ids(self.conn, self.bid, child), [self.a])
        self.assertEqual(repo.knowledge_product_ids(self.conn, self.bid, self.a), [self.a])
        self.assertEqual(
            repo.knowledge_product_ids(self.conn, self.bid, "prd_missing"), ["prd_missing"]
        )
        econ = repo.get_product_economics(self.conn, self.bid, child)
        self.assertIsNone(econ["list_price"])
        self.assertEqual(econ["derived_fields"], [])
        self.assertEqual(
            [s["id"] for s in repo.list_sell_ways(self.conn, self.bid, self.a)], [child]
        )

    def test_old_editors_keep_list_price_and_cap(self):
        sw = self._single(self.a, "單盒", 359, list_price=399, cap_per_sale=120)
        repo.save_product_economics(
            self.conn,
            self.bid,
            sw["id"],
            selling_price=349,
            currency="TWD",
            confirmed_by=ACTOR,
            actor=ACTOR,
        )
        raw = repo.get_product_economics(self.conn, self.bid, sw["id"], raw=True)
        self.assertEqual(
            (raw["selling_price"], raw["list_price"], raw["cap_per_sale"]), (349, 399, 120)
        )
        version = self.conn.execute(
            "SELECT list_price, cap_per_sale FROM product_economics_version WHERE brand_id = %s "
            "AND product_id = %s AND effective_to IS NULL",
            (self.bid, sw["id"]),
        ).fetchone()
        self.assertEqual((version["list_price"], version["cap_per_sale"]), (399, 120))


class SellWayOfferTest(unittest.TestCase):
    def setUp(self):
        self.conn = db_current()
        self.bid = _brand(self.conn)
        self.a = repo.create_product(self.conn, self.bid, name="薑黃錠", actor=ACTOR)["id"]
        self.single = repo.save_sell_way(
            self.conn,
            self.bid,
            name="單盒",
            components=[{"product_id": self.a, "qty": 1}],
            economics=_econ(399),
            actor=ACTOR,
        )

    def test_three_pack_is_a_bundle_offer(self):
        pack = repo.save_sell_way(
            self.conn,
            self.bid,
            name="3 入組",
            components=[{"product_id": self.a, "qty": 3}],
            economics=_econ(999),
            actor=ACTOR,
        )
        self.assertEqual(pack["economics"]["list_price"], Decimal("1197"))
        self.assertEqual(repo.available_offer_keys(self.conn, self.bid, pack["id"]), {"bundle"})
        self.assertEqual(
            repo.offer_sources(self.conn, self.bid, pack["id"]),
            [{"offer_key": "bundle", "sentence": "薑黃錠 · 3 入組優惠價 NT$999（原價 NT$1,197）"}],
        )

    def test_single_below_list_is_a_discount_and_equal_is_none(self):
        self.assertEqual(repo.available_offer_keys(self.conn, self.bid, self.single["id"]), set())
        sale = repo.save_sell_way(
            self.conn,
            self.bid,
            name="限時價",
            components=[{"product_id": self.a, "qty": 1}],
            economics=_econ(359, list_price=399),
            actor=ACTOR,
        )
        self.assertEqual(repo.available_offer_keys(self.conn, self.bid, sale["id"]), {"discount"})
        self.assertEqual(
            repo.offer_sources(self.conn, self.bid, sale["id"])[0]["sentence"],
            "薑黃錠 · 限時價優惠價 NT$359（原價 NT$399）",
        )
        self.assertEqual(repo.available_offer_keys(self.conn, self.bid, None), set())

    def test_brand_policies_and_own_offer_combine(self):
        repo.save_brand_policies(
            self.conn,
            self.bid,
            [{"key": "ship_threshold", "params": {"threshold": 999}}],
            actor=ACTOR,
        )
        pack = repo.save_sell_way(
            self.conn,
            self.bid,
            name="3 入組",
            components=[{"product_id": self.a, "qty": 3}],
            economics=_econ(999),
            actor=ACTOR,
        )
        self.assertEqual(
            repo.available_offer_keys(self.conn, self.bid, pack["id"]), {"free_shipping", "bundle"}
        )
        self.assertEqual(repo.available_offer_keys(self.conn, self.bid, self.single["id"]), set())


class ProductProofTest(unittest.TestCase):
    def setUp(self):
        self.conn = db_current()
        self.bid = _brand(self.conn)
        self.a = repo.create_product(self.conn, self.bid, name="薑黃錠", actor=ACTOR)["id"]
        self.sw = repo.save_sell_way(
            self.conn,
            self.bid,
            name="單盒",
            components=[{"product_id": self.a, "qty": 1}],
            economics=_econ(399),
            actor=ACTOR,
        )["id"]

    def test_product_proof_keys(self):
        self.assertEqual(vocab.product_fact_type_label("proof"), "證據")
        fact = repo.create_product_fact(
            self.conn,
            self.bid,
            self.a,
            fact_type="proof",
            fact_key="lab_report",
            label="檢驗",
            value="SGS 檢驗合格",
            status="confirmed",
            confirmed_by=ACTOR,
            actor=ACTOR,
        )
        repo.create_product_fact(
            self.conn,
            self.bid,
            self.a,
            fact_type="proof",
            fact_key="sales_numbers",
            label="銷量",
            value="賣出一萬盒",
            status="pending",
            actor=ACTOR,
        )
        self.assertEqual(repo.available_proof_keys(self.conn, self.bid, self.sw), {"lab_report"})
        self.assertEqual(repo.available_proof_keys(self.conn, self.bid, self.a), {"lab_report"})
        self.assertEqual(repo.available_proof_keys(self.conn, self.bid), set())
        with self.assertRaises(ValueError):
            repo.create_product_fact(
                self.conn,
                self.bid,
                self.a,
                fact_type="proof",
                label="x",
                value="y",
                status="pending",
                actor=ACTOR,
            )
        other = repo.create_product_fact(
            self.conn,
            self.bid,
            self.a,
            fact_type="core_info",
            fact_key="lab_report",
            label="規格",
            value="60 錠",
            status="pending",
            actor=ACTOR,
        )
        self.assertIsNone(other["fact_key"])
        edited = repo.update_product_fact(
            self.conn,
            self.bid,
            self.a,
            fact["id"],
            fact_type="proof",
            label="檢驗",
            value="SGS 檢驗合格（2026）",
            actor=ACTOR,
        )
        self.assertEqual(edited["fact_key"], "lab_report")
        with self.assertRaises(psycopg.errors.CheckViolation):
            self.conn.execute(
                "UPDATE product_fact SET fact_key = 'rumour' WHERE id = %s AND brand_id = %s",
                (fact["id"], self.bid),
            )
        self.conn.rollback()


class CustomerGroupTest(unittest.TestCase):
    def setUp(self):
        self.conn = db_current()
        self.bid = _brand(self.conn)
        self.a = repo.create_product(self.conn, self.bid, name="薑黃錠", actor=ACTOR)["id"]

    def _group(self, who, pains, **more):
        return {"who": who, "pain_keys": pains, **more}

    def test_full_list_up_to_three(self):
        self.assertEqual(
            vocab.PAIN_KEYS,
            ("cost", "effort", "uncertainty", "availability", "experience", "identity"),
        )
        saved = repo.save_customer_groups(
            self.conn,
            self.bid,
            self.a,
            [
                self._group(
                    "熬夜上班族", ["effort"], quote="每天都好累", when_used="加班後", source="ai"
                ),
                self._group("注重保養的媽媽", ["uncertainty", "cost"]),
                self._group("運動族", ["experience"], source="custom"),
            ],
            actor=ACTOR,
        )
        self.assertEqual(
            [(g["position"], g["who"], g["pain_keys"], g["source"]) for g in saved],
            [
                (1, "熬夜上班族", ["effort"], "ai"),
                (2, "注重保養的媽媽", ["uncertainty", "cost"], "user"),
                (3, "運動族", ["experience"], "custom"),
            ],
        )
        first_id = saved[0]["id"]
        shrunk = repo.save_customer_groups(
            self.conn,
            self.bid,
            self.a,
            [
                self._group(
                    "熬夜上班族", ["effort"], quote="每天都好累", when_used="加班後", source="ai"
                )
            ],
            actor=ACTOR,
        )
        self.assertEqual([(g["id"], g["position"]) for g in shrunk], [(first_id, 1)])
        self.assertEqual(repo.list_customer_groups(self.conn, self.bid, self.a), shrunk)

    def test_validation_saves_nothing(self):
        bad_lists = [
            [self._group(f"第{i}群", ["cost"]) for i in range(4)],
            [self._group("三個痛點", ["cost", "effort", "identity"])],
            [self._group("沒痛點", [])],
            [self._group("怪痛點", ["boredom"])],
            [self._group("  ", ["cost"])],
            [self._group("怪來源", ["cost"], source="robot")],
        ]
        for groups in bad_lists:
            with self.assertRaises(ValueError, msg=repr(groups)):
                repo.save_customer_groups(self.conn, self.bid, self.a, groups, actor=ACTOR)
        self.assertEqual(repo.list_customer_groups(self.conn, self.bid, self.a), [])
        sw = repo.save_sell_way(
            self.conn,
            self.bid,
            name="單盒",
            components=[{"product_id": self.a, "qty": 1}],
            economics=_econ(399),
            actor=ACTOR,
        )
        with self.assertRaises(ValueError):  # groups hang on the product, not on a sell-way
            repo.save_customer_groups(
                self.conn, self.bid, sw["id"], [self._group("誰", ["cost"])], actor=ACTOR
            )

    def test_pain_key_check_in_the_database(self):
        for pains in (["boredom"], ["cost", "effort", "identity"], []):
            with self.assertRaises(psycopg.errors.CheckViolation, msg=repr(pains)):
                self.conn.execute(
                    "INSERT INTO product_customer_group"
                    " (id, org_id, brand_id, product_id, position, who, "
                    "pain_keys, source) VALUES (%s, %s, %s, %s, 1, '誰', %s, 'user')",
                    (new_id("pcg"), DEV_ORG_ID, self.bid, self.a, pains),
                )
            self.conn.rollback()


class OnboardingStepAndPrefillTest(unittest.TestCase):
    def setUp(self):
        self.conn = db_current()
        self.bid = _brand(self.conn)
        self.a = repo.create_product(self.conn, self.bid, name="薑黃錠", actor=ACTOR)["id"]

    def test_onboarding_step(self):
        self.assertIsNone(repo.get_product(self.conn, self.bid, self.a)["onboarding_step"])
        self.assertEqual(
            repo.set_product_onboarding_step(self.conn, self.bid, self.a, 2, actor=ACTOR)[
                "onboarding_step"
            ],
            2,
        )
        self.assertIsNone(
            repo.set_product_onboarding_step(self.conn, self.bid, self.a, None, actor=ACTOR)[
                "onboarding_step"
            ]
        )
        for bad in (0, 6, True):
            with self.assertRaises(ValueError, msg=repr(bad)):
                repo.set_product_onboarding_step(self.conn, self.bid, self.a, bad, actor=ACTOR)

    def test_prefill_round_trip_and_cross_brand(self):
        self.assertIsNone(intake_repo.get_product_prefill(self.conn, self.bid, self.a))
        intake_repo.save_product_prefill(
            self.conn, self.bid, self.a, status="running", llm_task_id="llm_x"
        )
        row = intake_repo.save_product_prefill(
            self.conn,
            self.bid,
            self.a,
            status="done",
            prefill_json={"intro": {"value": "薑黃萃取", "note": "商品頁"}},
            llm_task_id="llm_x",
        )
        self.assertEqual(
            (row["status"], row["prefill_json"]["intro"]["value"]), ("done", "薑黃萃取")
        )
        other = _brand(self.conn)
        self.assertIsNone(intake_repo.get_product_prefill(self.conn, other, self.a))
        with self.assertRaises(ValueError):
            intake_repo.save_product_prefill(self.conn, other, self.a, status="running")


if __name__ == "__main__":
    unittest.main()
