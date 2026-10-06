"""F52-I20: merchant return text uses the public policy facade without offer eligibility."""

import unittest

from app.brand_intelligence import repository as repo
from app.core import vocab
from app.core.db import DEV_ORG_ID, current


class MerchantReturnPolicyTest(unittest.TestCase):
    def setUp(self):
        self.conn = current()
        self.bid = repo.create_brand(self.conn, name="虛構商家政策測試", client_name=None,
                                     actor="test", org_id=DEV_ORG_ID)["id"]

    def test_merchant_text_and_provenance_are_not_an_offer(self):
        key = "merchant_return_conditions"
        params = {"conditions": "商家要求未拆封並附原包裝。", "source_note": "商家客服提供"}
        [row] = repo.save_brand_policies(self.conn, self.bid, [{"key": key, "params": params}], actor="test")
        self.assertEqual((row["params"], row["sentence"], row["offer_key"]),
                         (params, params["conditions"], None))
        self.assertEqual(repo.available_offer_keys(self.conn, self.bid), set())
        self.assertEqual(repo.offer_sources(self.conn, self.bid), [])
        self.assertNotIn(key, {p["key"] for p in vocab.POLICY_TYPES})
        self.assertEqual(vocab.require("policy", key), key)
        self.assertEqual(repo.list_brand_policies(self.conn, self.bid), [row])

    def test_source_only_and_existing_custom_full_list_semantics(self):
        custom = {"key": "custom", "params": {"label": "回購禮", "offer_key": "bundle"},
                  "sentence": "第三次購買附贈隨身包"}
        merchant = {"key": "merchant_return_conditions", "params": {"source_note": "客服口述"}}
        saved = repo.save_brand_policies(self.conn, self.bid, [custom, merchant], actor="test")
        self.assertEqual(saved[1]["sentence"], "")
        self.assertEqual(repo.offer_sources(self.conn, self.bid),
                         [{"offer_key": "bundle", "sentence": custom["sentence"]}])
        version = repo.get_brand(self.conn, self.bid)["knowledge_version"]
        self.assertEqual(repo.save_brand_policies(self.conn, self.bid, [custom, merchant], actor="test"), saved)
        self.assertEqual(repo.get_brand(self.conn, self.bid)["knowledge_version"], version)
        self.assertEqual([p["key"] for p in repo.save_brand_policies(
            self.conn, self.bid, [custom], actor="test")], ["custom"])

    def test_limits_and_unknown_params_are_owned_by_policy_registry(self):
        key = "merchant_return_conditions"
        for field in ("conditions", "source_note"):
            with self.subTest(field=field):
                self.assertEqual(vocab.normalize_policy_params(key, {field: "文" * 200}), {field: "文" * 200})
                with self.assertRaises(ValueError):
                    repo.save_brand_policies(self.conn, self.bid,
                                             [{"key": key, "params": {field: "文" * 201}}], actor="test")
        with self.assertRaises(ValueError):
            repo.save_brand_policies(self.conn, self.bid,
                                     [{"key": key, "params": {"offer_key": "refund"}}], actor="test")
        self.assertEqual(repo.list_brand_policies(self.conn, self.bid), [])
        # The merchant limit does not silently expand restrictions on existing offers.
        self.assertEqual(vocab.normalize_policy_params("first_order", {"content": "文" * 201}),
                         {"content": "文" * 201})
