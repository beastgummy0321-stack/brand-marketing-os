"""app/tests/test_workbench_product_line.py — F07-I07 (ARCHITECTURE.md §5.7 Decision 13):
`repository.reference_line()` — the pure, DB-free rule for the worksheet's `商品參考` line.
No DB, no model call.
"""

import unittest

from app.workbench import repository


def _asset(product_id, title=None, asset_kind="product_photo"):
    return {"product_id": product_id, "title": title, "asset_kind": asset_kind}


class ReferenceLineTest(unittest.TestCase):
    def test_own_product_photo_with_title_wins(self):
        assets = [
            _asset("prd_brand", title="品牌形象照"),
            _asset("prd_1", title="這顆商品的照片"),
        ]
        line = repository.reference_line(assets, "prd_1", "晨光咖啡豆")
        self.assertEqual(line, "商品參考：這顆商品的照片（有參考照）")

    def test_falls_back_to_brand_level_photo_when_product_has_none(self):
        assets = [_asset(None, title="品牌形象照"), _asset("prd_other", title="別顆商品")]
        line = repository.reference_line(assets, "prd_1", "晨光咖啡豆")
        self.assertEqual(line, "商品參考：品牌形象照（有參考照）")

    def test_no_photo_at_all(self):
        none = repository.NO_REFERENCE_LINE
        self.assertEqual(repository.reference_line([], "prd_1", "晨光咖啡豆"), none)
        self.assertEqual(repository.reference_line([], None, None), none)

    def test_missing_title_falls_back_to_product_name(self):
        assets = [_asset("prd_1", title=None)]
        line = repository.reference_line(assets, "prd_1", "晨光咖啡豆")
        self.assertEqual(line, "商品參考：晨光咖啡豆（有參考照）")

    def test_missing_title_and_product_name_falls_back_to_generic_word(self):
        assets = [_asset("prd_1", title=None)]
        line = repository.reference_line(assets, "prd_1", None)
        self.assertEqual(line, "商品參考：參考照（有參考照）")

    def test_up_to_three_titles_newest_first_order_preserved(self):
        assets = [_asset("prd_1", title=f"照片{i}") for i in range(1, 6)]
        line = repository.reference_line(assets, "prd_1", None)
        self.assertEqual(line, "商品參考：照片1、照片2、照片3（有參考照）")

    def test_non_product_photo_assets_are_ignored(self):
        assets = [_asset("prd_1", title="Logo", asset_kind="logo")]
        line = repository.reference_line(assets, "prd_1", None)
        self.assertEqual(line, repository.NO_REFERENCE_LINE)

    def test_no_knowledge_product_id_goes_straight_to_brand_level(self):
        assets = [_asset(None, title="品牌形象照")]
        line = repository.reference_line(assets, None, None)
        self.assertEqual(line, "商品參考：品牌形象照（有參考照）")

    def test_four_photos_lists_three(self):
        assets = [_asset("prd_1", title=f"照片{i}") for i in range(1, 5)]
        line = repository.reference_line(assets, "prd_1", None)
        self.assertEqual(line, "商品參考：照片1、照片2、照片3（有參考照）")

    def test_product_level_photo_wins_over_brand_level(self):
        assets = [_asset(None, title="品牌形象照"), _asset("prd_1", title="商品照")]
        line = repository.reference_line(assets, "prd_1", None)
        self.assertEqual(line, "商品參考：商品照（有參考照）")


if __name__ == "__main__":
    unittest.main()
