"""app/tests/test_ads_sell_way.py — F44 (Contract A) falsifiers: a campaign's sell-way is the
first of its `context_json.product_ids`; an ad's own `product_id` overrides it; a campaign
without a product has none (`None`, judged at brand level by the readers).
"""

import unittest

from app.ads import sell_way


class SellWayOfCampaignTest(unittest.TestCase):
    def test_campaign_sells_the_first_of_its_product_ids(self):
        campaign = {"context_json": {"product_ids": ["prd_first", "prd_second"]}}
        self.assertEqual(sell_way.of_campaign(campaign), "prd_first")

    def test_campaign_without_a_product_has_no_sell_way(self):
        for campaign in ({}, {"context_json": None}, {"context_json": {}},
                         {"context_json": {"product_ids": []}},
                         {"context_json": {"product_ids": None}}):
            self.assertIsNone(sell_way.of_campaign(campaign))


class SellWayOfAdTest(unittest.TestCase):
    _CAMPAIGN = {"context_json": {"product_ids": ["prd_campaign"]}}

    def test_ad_with_its_own_product_overrides_the_campaign(self):
        self.assertEqual(sell_way.of_ad({"product_id": "prd_ad"}, self._CAMPAIGN), "prd_ad")

    def test_ad_without_a_product_falls_back_to_the_campaign(self):
        self.assertEqual(sell_way.of_ad({"product_id": None}, self._CAMPAIGN), "prd_campaign")
        self.assertEqual(sell_way.of_ad({}, self._CAMPAIGN), "prd_campaign")

    def test_no_product_anywhere_is_none(self):
        self.assertIsNone(sell_way.of_ad({"product_id": None}, {"context_json": {}}))


if __name__ == "__main__":
    unittest.main()
