"""app/tests/test_isolation.py — 品牌隔離必備測試：任何查詢絕不出現另一品牌的任何一列。

見 docs/design/03-data-model.md §7.6、build.md §14.7／§25.2。
"""

import unittest

from app.brand_intelligence import repository as repo
from app.core import db


class BrandIsolationTest(unittest.TestCase):
    def setUp(self):
        self.conn = db.current()

    def _seed_brand(self, name):
        brand = repo.create_brand(self.conn, name=name, client_name="測試客戶", actor="測試員",
            org_id=db.DEV_ORG_ID)
        bid = brand["id"]
        product = repo.create_product(self.conn, bid, name=f"{name}-產品", actor="測試員")
        pid = product["id"]
        fact = repo.create_brand_fact(
            self.conn, bid, fact_type="positioning", label="定位", value="測試內容",
            status="pending", actor="測試員",
        )
        pfact = repo.create_product_fact(
            self.conn, bid, pid, fact_type="core_info", label="規格", value="測試",
            status="pending", actor="測試員",
        )
        rule = repo.create_rule(
            self.conn, bid, rule_type="tone", content="測試規則", severity="soft", actor="測試員",
        )
        claim = repo.create_claim(
            self.conn, bid, claim_text="測試宣稱", claim_type="approved", actor="測試員",
        )
        channel = repo.create_channel(
            self.conn, bid, channel_type="website", name="測試官網", actor="測試員",
                org_id=db.DEV_ORG_ID,
        )
        economics = repo.save_product_economics(
            self.conn, bid, pid, selling_price=100, currency="TWD",
            confirmed_by="測試員", actor="測試員",
        )
        source = repo.create_source_reference(
            self.conn, bid, title="測試來源", source_type="web", captured_date="2026-01-01",
            actor="測試員",
        )
        asset = repo.create_official_asset(
            self.conn, bid, asset_kind="logo", file_path="C:/tmp/logo.png", actor="測試員",
        )
        hyp = repo.create_strategy_hypothesis(
            self.conn, bid, hypothesis_type="audience", statement="測試假設",
            created_by="測試員", actor="測試員",
        )
        baseline = repo.create_brand_performance_baseline(
            self.conn, bid, metric="典型CTR", value=1.2, as_of_date="2026-01-01",
            created_by="測試員", actor="測試員",
        )
        return {
            "brand": brand, "product": product, "fact": fact, "pfact": pfact, "rule": rule,
            "claim": claim, "channel": channel, "economics": economics, "source": source,
            "asset": asset, "hyp": hyp, "baseline": baseline,
        }

    def test_no_cross_brand_leakage_in_lists(self):
        a = self._seed_brand("品牌A（隔離測試）")
        b = self._seed_brand("品牌B（隔離測試）")
        b_id = b["brand"]["id"]

        checks = [
            (a["product"]["id"], [p["id"] for p in repo.list_products(self.conn, b_id)]),
            (a["fact"]["id"], [x["id"] for x in repo.list_brand_facts(self.conn, b_id)]),
            (a["rule"]["id"], [x["id"] for x in repo.list_rules_for_brand(self.conn, b_id)]),
            (a["claim"]["id"], [x["id"] for x in repo.list_claims_for_brand(self.conn, b_id)]),
            (a["channel"]["id"], [x["id"] for x in repo.list_channels(self.conn, b_id)]),
            (a["source"]["id"], [x["id"] for x in repo.list_source_references(self.conn, b_id)]),
            (a["asset"]["id"], [x["id"] for x in repo.list_official_assets(self.conn, b_id)]),
            (a["hyp"]["id"], [x["id"] for x in repo.list_strategy_hypotheses(self.conn, b_id)]),
            (a["baseline"]["id"],
             [x["id"] for x in repo.list_brand_performance_baselines(self.conn, b_id)]),
        ]
        for leaked_id, other_brand_ids in checks:
            self.assertNotIn(leaked_id, other_brand_ids)

        # 品牌 B 查自己的 product_fact 清單，不能看到品牌 A 的
        self.assertNotIn(
            a["pfact"]["id"],
            [x["id"] for x in repo.list_product_facts(self.conn, b_id, b["product"]["id"])],
        )

        # 品牌 B 自己的資料應該還在（過濾邏輯不是「全部擋掉」）
        self.assertEqual(len(repo.list_brand_facts(self.conn, b_id)), 1)
        self.assertEqual(len(repo.list_products(self.conn, b_id)), 1)

    def test_cross_brand_direct_lookup_returns_none(self):
        a = self._seed_brand("品牌A（直接存取測試）")
        b = self._seed_brand("品牌B（直接存取測試）")
        b_id = b["brand"]["id"]

        self.assertIsNone(repo.get_product(self.conn, b_id, a["product"]["id"]))
        self.assertIsNone(repo.get_brand_fact(self.conn, b_id, a["fact"]["id"]))
        self.assertIsNone(
            repo.get_product_fact(self.conn, b_id, a["product"]["id"], a["pfact"]["id"])
        )
        self.assertIsNone(repo.get_product_economics(self.conn, b_id, a["product"]["id"]))
        self.assertIsNone(repo.get_source_reference(self.conn, b_id, a["source"]["id"]))

        # 用品牌 A 自己的 id 查得到，證明過濾條件本身沒有寫錯（不是永遠回 None）
        self.assertIsNotNone(
            repo.get_product(self.conn, a["brand"]["id"], a["product"]["id"])
        )
        self.assertIsNotNone(
            repo.get_brand_fact(self.conn, a["brand"]["id"], a["fact"]["id"])
        )


if __name__ == "__main__":
    unittest.main()
