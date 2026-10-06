"""app/tests/test_intake_brand_contract.py — F42-I01: the brand-side data contract brand onboarding
builds on (feature F42 decisions 「where each brand fact lives」, 「policy registry」, 「offer
availability」). Only the brand_intelligence facade and `app.core.vocab` are used.
"""

import unittest

import psycopg

from app.brand_intelligence import repository as repo
from app.core import vocab
from app.core.db import DEV_ORG_ID, new_id
from app.core.db import current as db_current

ACTOR = "測試員"
_SEQ = [0]


def _brand(conn) -> str:
    _SEQ[0] += 1
    return repo.create_brand(conn, name=f"建檔契約品牌{_SEQ[0]}", client_name=None,
                             actor=ACTOR, org_id=DEV_ORG_ID)["id"]


class PolicyRegistryTest(unittest.TestCase):
    def test_registry_matches_prototype(self):
        """The prototype's 26 `POLICIES`; offer keys are OFFER_LABELS keys; the four threshold
        types name their threshold param."""
        self.assertEqual(len(vocab.POLICY_TYPES), 26)
        self.assertEqual(len(vocab.POLICY_TYPES_BY_KEY), 27)
        self.assertEqual(sum(1 for p in vocab.POLICY_TYPES if p["common"]), 8)
        for p in vocab.POLICY_TYPES:
            self.assertIn(p["offer_key"], vocab.OFFER_LABELS, p["key"])
            for param in p["params"]:
                self.assertIn(param["kind"], ("money", "text", "number", "percent"), p["key"])
        thresholds = {p["key"]: p["threshold"] for p in vocab.POLICY_TYPES if p["threshold"]}
        self.assertEqual(thresholds, {"ship_threshold": "threshold", "ship_cvs": "threshold",
                                      "spend_off": "threshold", "spend_gift": "threshold"})
        self.assertEqual(vocab.TONES, ["親切", "專業", "直接", "幽默", "溫柔", "熱血"])
        self.assertEqual(vocab.brand_fact_type_label("policy"), "全店政策")
        brand_photos = (("store", "門市／工作室"), ("team", "團隊／創辦人"),
                        ("brand_image", "品牌形象"))
        for key, label in brand_photos:
            self.assertEqual(vocab.asset_kind_label(key), label)

    def test_policy_sentence(self):
        cases = [
            ("ship_threshold", {"threshold": 999}, "滿 NT$999 免運"),
            ("ship_threshold", {"threshold": "1,200"}, "滿 NT$1,200 免運"),
            ("ship_cvs", {}, "超商取貨免運"),
            ("ship_cvs", {"threshold": "0"}, "超商取貨免運"),
            ("ship_cvs", {"threshold": 499}, "超商取貨滿 NT$499 免運"),
            ("spend_gift", {"threshold": 1500, "gift": "隨身包"}, "滿 NT$1,500 送隨身包"),
            ("ship_all", {}, "全館免運"),
        ]
        for key, params, sentence in cases:
            self.assertEqual(vocab.policy_sentence(key, params), sentence)
        # every registry type composes a sentence from filled-in params
        samples = {"money": "100", "text": "樣本", "number": "3", "percent": "5"}
        for p in vocab.POLICY_TYPES:
            params = {x["name"]: samples[x["kind"]] for x in p["params"]}
            sentence = vocab.policy_sentence(p["key"], params)
            self.assertTrue(sentence and "{" not in sentence, p["key"])

    def test_policy_sentence_refuses_bad_input(self):
        with self.assertRaises(ValueError):
            vocab.policy_sentence("no_such_policy", {})
        with self.assertRaises(ValueError):
            vocab.policy_sentence("ship_threshold", {})  # required param missing
        with self.assertRaises(ValueError):
            vocab.policy_sentence("ship_threshold", {"threshold": "很多"})
        with self.assertRaises(ValueError):
            vocab.policy_sentence("ship_threshold", {"threshold": 999, "extra": 1})
        with self.assertRaises(ValueError):
            vocab.policy_sentence("points", {"rate": 150})


class BrandPoliciesTest(unittest.TestCase):
    def setUp(self):
        self.conn = db_current()
        self.bid = _brand(self.conn)

    def test_save_and_list_incl_custom(self):
        saved = repo.save_brand_policies(self.conn, self.bid, [
            {"key": "ship_threshold", "params": {"threshold": "999"}},
            {"key": "custom", "params": {"label": "回購禮", "offer_key": "bundle"},
             "sentence": "連續訂三個月，第四個月送一包隨身包"},
        ], actor=ACTOR)
        self.assertEqual([p["key"] for p in saved], ["ship_threshold", "custom"])
        ship, custom = saved
        self.assertEqual((ship["label"], ship["sentence"], ship["params"], ship["offer_key"]),
                         ("滿額免運", "滿 NT$999 免運", {"threshold": 999}, "free_shipping"))
        self.assertEqual((custom["label"], custom["sentence"], custom["offer_key"]),
                         ("回購禮", "連續訂三個月，第四個月送一包隨身包", "bundle"))
        self.assertTrue(all(p["status"] == "confirmed" for p in saved))
        self.assertEqual(repo.list_brand_policies(self.conn, self.bid), saved)

    def test_full_list_semantics_update_and_delete(self):
        first = repo.save_brand_policies(self.conn, self.bid, [
            {"key": "ship_threshold", "params": {"threshold": 999}},
            {"key": "first_order", "params": {"content": "首購 9 折"}},
        ], actor=ACTOR)
        ship_id = first[0]["id"]
        version = repo.get_brand(self.conn, self.bid)["knowledge_version"]

        again = repo.save_brand_policies(self.conn, self.bid, [
            {"key": "ship_threshold", "params": {"threshold": 1200}},
        ], actor=ACTOR)
        self.assertEqual([(p["id"], p["sentence"]) for p in again], [(ship_id, "滿 NT$1,200 免運")])
        self.assertGreater(repo.get_brand(self.conn, self.bid)["knowledge_version"], version)
        deleted = self.conn.execute(
            "SELECT count(*) AS n FROM audit_log WHERE brand_id = %s AND entity_type = 'brand_fact'"
            " AND action = 'delete'", (self.bid,)).fetchone()["n"]
        self.assertEqual(deleted, 1)

        # an unchanged list writes nothing (no version bump)
        version = repo.get_brand(self.conn, self.bid)["knowledge_version"]
        repo.save_brand_policies(self.conn, self.bid, [
            {"key": "ship_threshold", "params": {"threshold": "1200"}}], actor=ACTOR)
        self.assertEqual(repo.get_brand(self.conn, self.bid)["knowledge_version"], version)

        self.assertEqual(repo.save_brand_policies(self.conn, self.bid, [], actor=ACTOR), [])

    def test_bad_items_refused_and_nothing_written(self):
        bad_lists = [
            [{"key": "no_such_policy", "params": {}}],
            [{"key": "ship_threshold", "params": {"threshold": 999, "color": "red"}}],
            [{"key": "ship_threshold", "params": {}}],
            [{"key": "custom", "params": {"label": "x", "offer_key": "cashback"}, "sentence": "y"}],
            [{"key": "custom", "params": {"label": "x", "offer_key": "discount"}}],  # no sentence
            [{"key": "cooling_off_exempt", "params": {"disclosure": "太短"}}],
            [{"key": "ship_all"}, {"key": "ship_all"}],
            [{"key": "ship_all"}, {"key": "ship_threshold", "params": {"threshold": -1}}],
        ]
        for policies in bad_lists:
            with self.subTest(policies=policies), self.assertRaises(ValueError):
                repo.save_brand_policies(self.conn, self.bid, policies, actor=ACTOR)
        self.assertEqual(repo.list_brand_policies(self.conn, self.bid), [])

    def test_cooling_off_exemption(self):
        disclosure = "本店商品為易腐敗之食品，依法不適用七天猶豫期。"
        [row] = repo.save_brand_policies(self.conn, self.bid, [
            {"key": "cooling_off_exempt", "params": {"disclosure": disclosure}}], actor=ACTOR)
        self.assertEqual((row["key"], row["sentence"], row["params"], row["offer_key"]),
                         ("cooling_off_exempt", disclosure, {"disclosure": disclosure}, None))
        self.assertEqual(repo.available_offer_keys(self.conn, self.bid), set())

    def test_generic_fact_writers_refuse_policy(self):
        with self.assertRaises(ValueError):
            repo.create_brand_fact(self.conn, self.bid, actor=ACTOR, fact_type="policy",
                                   label="x", value="y", status="confirmed", confirmed_by=ACTOR,
                                   fact_key="ship_all")


class BrandFactParamsTest(unittest.TestCase):
    """F42-I04: the generic fact writers take an optional `params_json` (a tone fact's tones)."""

    def setUp(self):
        self.conn = db_current()
        self.bid = _brand(self.conn)

    def _audit_after(self, fact_id: str, action: str):
        row = self.conn.execute(
            "SELECT after_json FROM audit_log WHERE entity_id = %s AND action = %s"
            " ORDER BY created_at DESC LIMIT 1", (fact_id, action)).fetchone()
        return row["after_json"]

    def test_create_and_update_write_params_and_audit_them(self):
        row = repo.create_brand_fact(self.conn, self.bid, actor=ACTOR, fact_type="tone",
                                     label="語調", value="親切、直接", status="confirmed",
                                     confirmed_by=ACTOR, params_json={"tones": ["親切", "直接"]})
        fact = repo.get_brand_fact(self.conn, self.bid, row["id"])
        self.assertEqual(fact["params_json"], {"tones": ["親切", "直接"]})
        self.assertEqual(self._audit_after(row["id"], "create")["params_json"],
                         {"tones": ["親切", "直接"]})
        after = repo.update_brand_fact(self.conn, self.bid, row["id"], actor=ACTOR,
                                       fact_type="tone", label="語調", value="溫柔",
                                       params_json={"tones": ["溫柔"]})
        self.assertEqual(after["params_json"], {"tones": ["溫柔"]})
        self.assertEqual(self._audit_after(row["id"], "update")["params_json"], {"tones": ["溫柔"]})

    def test_edit_without_params_clears_them(self):
        row = repo.create_brand_fact(self.conn, self.bid, actor=ACTOR, fact_type="tone",
                                     label="語調", value="親切", status="confirmed",
                                     confirmed_by=ACTOR, params_json={"tones": ["親切"]})
        after = repo.update_brand_fact(self.conn, self.bid, row["id"], actor=ACTOR,
                                       fact_type="tone", label="語調", value="專業而親切")
        self.assertIsNone(after["params_json"])

    def test_params_must_be_an_object_and_policy_still_refused(self):
        with self.assertRaises(ValueError):
            repo.create_brand_fact(self.conn, self.bid, actor=ACTOR, fact_type="tone",
                                   label="語調", value="親切", status="confirmed",
                                   confirmed_by=ACTOR, params_json=["親切"])  # type: ignore[arg-type]
        with self.assertRaises(ValueError):
            repo.create_brand_fact(self.conn, self.bid, actor=ACTOR, fact_type="policy",
                                   label="x", value="y", status="confirmed", confirmed_by=ACTOR,
                                   fact_key="ship_all", params_json={})


class BrandFactChecksTest(unittest.TestCase):
    """The DB CHECKs of 20261001000001_brand_intelligence_brand_onboarding.sql."""

    def setUp(self):
        self.conn = db_current()
        self.bid = _brand(self.conn)

    def _insert(self, fact_type: str, fact_key: str | None) -> None:
        self.conn.execute(
            "INSERT INTO brand_fact (id, org_id, brand_id, fact_type, fact_key, label, value,"
            " status) VALUES (%s, %s, %s, %s, %s, 'x', 'y', 'confirmed')",
            (new_id("bft"), DEV_ORG_ID, self.bid, fact_type, fact_key))

    def test_policy_without_key_refused(self):
        with self.assertRaises(psycopg.errors.CheckViolation):
            self._insert("policy", None)
        self.conn.rollback()

    def test_key_on_positioning_refused(self):
        with self.assertRaises(psycopg.errors.CheckViolation):
            self._insert("positioning", "ship_all")
        self.conn.rollback()

    def test_proof_key_still_validated_and_policy_key_allowed(self):
        with self.assertRaises(psycopg.errors.CheckViolation):
            self._insert("proof", "ship_all")
        self.conn.rollback()
        self._insert("policy", "ship_all")
        self._insert("proof", "founder_voice")
        self.conn.commit()


class OfferAvailabilityTest(unittest.TestCase):
    def setUp(self):
        self.conn = db_current()
        self.bid = _brand(self.conn)

    def _product(self, name: str, price: float | None, currency: str = "TWD") -> str:
        pid = repo.create_product(self.conn, self.bid, name=name, actor=ACTOR)["id"]
        if price is not None:
            repo.save_product_economics(self.conn, self.bid, pid, actor=ACTOR, selling_price=price,
                                        currency=currency, confirmed_by=ACTOR)
        return pid

    def test_threshold_against_product_price(self):
        repo.save_brand_policies(self.conn, self.bid, [
            {"key": "ship_threshold", "params": {"threshold": 999}}], actor=ACTOR)
        p998 = self._product("軟糖 998", 998)
        p999 = self._product("軟糖 999", 999)
        unknown = self._product("軟糖 未定價", None)
        usd = self._product("軟糖 美金", 1200, currency="USD")
        self.assertEqual(repo.available_offer_keys(self.conn, self.bid, p998), set())
        self.assertEqual(repo.available_offer_keys(self.conn, self.bid, p999), {"free_shipping"})
        self.assertEqual(repo.available_offer_keys(self.conn, self.bid, unknown), set())
        self.assertEqual(repo.available_offer_keys(self.conn, self.bid, usd), set())
        self.assertEqual(repo.available_offer_keys(self.conn, self.bid), {"free_shipping"})

    def test_custom_none_and_non_threshold(self):
        repo.save_brand_policies(self.conn, self.bid, [
            {"key": "cod"},                                     # offer none -> nothing
            {"key": "ship_cvs", "params": {"threshold": ""}},  # no threshold -> always
            {"key": "custom", "params": {"label": "回購禮", "offer_key": "bundle"},
             "sentence": "第四個月送一包隨身包"},
            {"key": "custom", "params": {"label": "門市體驗", "offer_key": "none"},
             "sentence": "可到門市試吃"},
        ], actor=ACTOR)
        cheap = self._product("便宜貨", 10)
        expected = {"free_shipping", "bundle"}
        self.assertEqual(repo.available_offer_keys(self.conn, self.bid), expected)
        self.assertEqual(repo.available_offer_keys(self.conn, self.bid, cheap), expected)

    def test_offer_sources_pair_key_and_sentence(self):
        repo.save_brand_policies(self.conn, self.bid, [
            {"key": "ship_threshold", "params": {"threshold": 999}},
            {"key": "first_order", "params": {"content": "首購 9 折"}},
            {"key": "spend_off", "params": {"threshold": 2000, "off": "200"}},
            {"key": "fast", "params": {"cutoff": "下午 3 點"}},
        ], actor=ACTOR)
        p1500 = self._product("軟糖 1500", 1500)
        self.assertEqual(repo.offer_sources(self.conn, self.bid, p1500), [
            {"offer_key": "free_shipping", "sentence": "滿 NT$999 免運"},
            {"offer_key": "discount", "sentence": "新會員首購禮：首購 9 折"},
        ])
        self.assertEqual({s["offer_key"] for s in repo.offer_sources(self.conn, self.bid)},
                         repo.available_offer_keys(self.conn, self.bid))
        self.assertEqual(len(repo.offer_sources(self.conn, self.bid)), 3)


class MediaCapabilityTest(unittest.TestCase):
    def test_round_trip(self):
        conn = db_current()
        bid = _brand(conn)
        self.assertIsNone(repo.get_brand(conn, bid)["media_capability"])
        version = repo.get_brand(conn, bid)["knowledge_version"]
        after = repo.set_media_capability(conn, bid, "photo", actor=ACTOR)
        self.assertEqual(after["media_capability"], "photo")
        self.assertGreater(after["knowledge_version"], version)
        repo.set_media_capability(conn, bid, "photo_video", actor=ACTOR)
        self.assertEqual(repo.get_brand(conn, bid)["media_capability"], "photo_video")
        for bad in ("video", None, ""):
            with self.assertRaises(ValueError):
                repo.set_media_capability(conn, bid, bad, actor=ACTOR)
        self.assertEqual(repo.get_brand(conn, bid)["media_capability"], "photo_video")
        audited = conn.execute(
            "SELECT count(*) AS n FROM audit_log WHERE brand_id = %s"
            " AND action = 'media_capability'",
            (bid,)).fetchone()["n"]
        self.assertEqual(audited, 2)


if __name__ == "__main__":
    unittest.main()
