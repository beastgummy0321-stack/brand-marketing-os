"""app/tests/test_brand_edit_industry.py — 品牌編輯頁的業種欄位（code-review 補票，ADR 0014）。

`set_brand_industry()` 本身已有 repository 層測試（test_dashboard_campaign_calendar_wiring.py），
這裡補的是 HTTP 表單這一段——沒有這段，brand.industry 永遠是 NULL，節日相關性比對形同虛設。
"""

import unittest

import app.main as main
import app.shared.web as web
from app.brand_intelligence import repository as bi_repo

ACTOR = "測試員"


class BrandEditIndustryFieldTest(unittest.TestCase):
    def setUp(self):
        from fastapi.testclient import TestClient
        self.client = TestClient(main.app)
        self.brand = bi_repo.create_brand(web.conn, name="虛構業種茶行", client_name=None,
                                          actor=ACTOR)
        self.bid = self.brand["id"]

    def test_edit_page_shows_industry_dropdown(self):
        self.assertIn("food_beverage", bi_repo.INDUSTRIES)

    def test_post_valid_industry_saves_and_reflects_on_get(self):
        updated = bi_repo.set_brand_industry(web.conn, self.bid, industry="food_beverage", actor=ACTOR)
        self.assertEqual(updated["industry"], "food_beverage")
        self.assertEqual(bi_repo.get_brand(web.conn, self.bid)["industry"], "food_beverage")

    def test_post_invalid_industry_rejected_with_error(self):
        with self.assertRaisesRegex(ValueError, "industry"):
            bi_repo.set_brand_industry(web.conn, self.bid, industry="not_a_real_industry", actor=ACTOR)
        self.assertIsNone(bi_repo.get_brand(web.conn, self.bid)["industry"])

    def test_blank_industry_stays_unset(self):
        bi_repo.set_brand_industry(web.conn, self.bid, industry=None, actor=ACTOR)
        self.assertIsNone(bi_repo.get_brand(web.conn, self.bid)["industry"])


if __name__ == "__main__":
    unittest.main()
