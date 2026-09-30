"""app/tests/test_ads_materials_in_hand.py — F42-I02 falsifiers for the strategy tab's
「這期會用：…」 data: offers are the store policies that make an offer available for the
campaign's product (a 滿額免運 above the product's price is left out; a policy that is not an
offer never shows), each with its sentence and the brand's own label; proof is the confirmed
proof facts plus a customer review taken from customer voices; media is the brand's capability.
"""

import unittest

import app.shared.web as web
from app.ads import materials_in_hand
from app.brand_intelligence import repository as bi_repo
from app.core import db as coredb

ACTOR = "測試員"


class MaterialsInHandTest(unittest.TestCase):
    def setUp(self):
        self.org_id = coredb.DEV_ORG_ID
        self.brand_id = bi_repo.create_brand(
            web.conn, org_id=self.org_id, name="測試品牌：這期會用", client_name=None, actor=ACTOR,
        )["id"]
        web.conn.commit()

    def _seed(self) -> str:
        """Brand-like the drill-8 brand: two offer policies + one reassurance, one confirmed and
        one pending proof, one customer voice, photo only, a product priced under the 999 bar."""
        # The brand's own word for free shipping (differs from the shared 「免運」 on purpose).
        web.conn.execute(
            "INSERT INTO brand_coordinate(id,org_id,brand_id,dimension,key,label) "
            "VALUES(%s,%s,%s,'offer','free_shipping','免運門檻')",
            (coredb.new_id("crd"), self.org_id, self.brand_id),
        )
        web.conn.commit()
        bi_repo.save_brand_policies(web.conn, self.brand_id, [
            {"key": "ship_threshold", "params": {"threshold": 999}},
            {"key": "first_order", "params": {"content": "全館 9 折"}},
            {"key": "cod", "params": {}},
        ], actor=ACTOR)
        bi_repo.create_brand_fact(
            web.conn, self.brand_id, actor=ACTOR, fact_type="proof", label="創辦人",
            value="創辦人自己每天吃，吃了三年", status="confirmed", confirmed_by=ACTOR,
            fact_key="founder_voice",
        )
        bi_repo.create_brand_fact(
            web.conn, self.brand_id, actor=ACTOR, fact_type="proof", label="檢驗",
            value="SGS 檢驗合格", status="pending", fact_key="lab_report",
        )
        bi_repo.create_customer_voice(
            web.conn, self.brand_id, actor=ACTOR, raw_text="吃了三週真的有感",
            source_channel="LINE", source_type="manual", extraction=[],
        )
        bi_repo.set_media_capability(web.conn, self.brand_id, "photo", actor=ACTOR)
        product_id = bi_repo.create_product(
            web.conn, self.brand_id, name="綜合維他命軟糖", actor=ACTOR,
        )["id"]
        bi_repo.save_product_economics(
            web.conn, self.brand_id, product_id, selling_price=880, currency="TWD",
            confirmed_by=ACTOR, actor=ACTOR, unit_variable_cost=150, shipping_cost=50,
        )
        return product_id

    def _read(self, product_ids: list) -> dict:
        return materials_in_hand.read(web.conn, self.org_id, self.brand_id, product_ids)

    def test_brand_level_lists_every_offer_with_its_sentence_and_the_brands_label(self):
        self._seed()
        materials = self._read([])
        self.assertEqual(materials["offers"], [
            {"key": "free_shipping", "label": "免運門檻", "sentence": "滿 NT$999 免運"},
            {"key": "discount", "label": "折扣", "sentence": "新會員首購禮：全館 9 折"},
        ])

    def test_product_below_the_threshold_drops_the_threshold_offer(self):
        product_id = self._seed()
        self.assertEqual([o["key"] for o in self._read([product_id])["offers"]], ["discount"])

    def test_proof_is_confirmed_facts_plus_a_customer_review_from_voices(self):
        product_id = self._seed()
        self.assertEqual(self._read([product_id])["proof"], [
            {"key": "founder_voice", "label": "創辦人第一手", "text": "創辦人自己每天吃，吃了三年"},
            {"key": "customer_review", "label": "顧客評論原話", "text": "吃了三週真的有感"},
        ])

    def test_media_is_the_brands_capability(self):
        product_id = self._seed()
        self.assertEqual(self._read([product_id])["media"], "photo")

    def test_empty_brand_has_nothing_in_hand(self):
        self.assertEqual(self._read([]), {"offers": [], "proof": [], "media": None})


if __name__ == "__main__":
    unittest.main()
