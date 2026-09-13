"""app/tests/test_workbench_product_line.py — F05-I02: sell ways have no photo of their own,
they borrow the mother product's (ARCHITECTURE.md §8 item 1: knowledge lives on the mother
product). This file is workbench code (owns `app/tests/test_workbench*.py`); it obeys
`workbench.may_depend_on == []`.
"""

import unittest

import app.shared.web as web
from app.brand_intelligence import repository as bi_repo
from app.core import db as coredb
from app.workbench import jobs as workbench_jobs

ACTOR = "測試員"


class SellWayBorrowsMotherPhotoTest(unittest.TestCase):
    def setUp(self):
        self.brand = bi_repo.create_brand(
            web.conn, org_id=coredb.DEV_ORG_ID, name="測試品牌：賣法商品照", client_name=None,
            actor=ACTOR,
        )
        self.mother = bi_repo.create_product(
            web.conn, self.brand["id"], name="薑黃錠", actor=ACTOR,
        )
        self.sell_way = bi_repo.create_product(
            web.conn, self.brand["id"], name="薑黃錠 · 單瓶", actor=ACTOR,
            parent_id=self.mother["id"],
        )

    def test_sell_way_reports_has_photo_when_mother_has_one(self):
        bi_repo.create_official_asset(
            web.conn, self.brand["id"], actor=ACTOR, asset_kind="product_photo",
            storage_key="test/mother.jpg", product_id=self.mother["id"],
        )
        line = workbench_jobs._product_line(
            web.conn, self.brand["id"], self.sell_way["id"], self.sell_way,
        )
        self.assertIn("見參考商品照", line)

    def test_sell_way_has_no_photo_line_when_mother_has_none(self):
        line = workbench_jobs._product_line(
            web.conn, self.brand["id"], self.sell_way["id"], self.sell_way,
        )
        self.assertEqual(line, workbench_jobs.NO_PHOTO_LINE)


if __name__ == "__main__":
    unittest.main()
