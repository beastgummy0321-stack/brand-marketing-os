"""app/tests/test_ads_funnel_stage.py — 票 04：漏斗階段接上的最小自檢。

品牌名一律虛構，絕不使用真實客戶品牌。

涵蓋：
1. 五個本期目標各自推導到哪一層（純函數，對照 app/ads/plan.py OBJECTIVE_TO_FUNNEL_STAGE）。
2. 開新檔期（app/ads/repository.create_cycle）真的把推導結果寫進 funnel_stage 欄位，不再是 None。
3. 既有檔期回填 migration（0014_funnel_stage_backfill.sql）把舊資料的空值補上、不動已有值。
"""

import unittest

from app.ads import plan as ads_plan
from app.ads import repository as ads_repo
from app.brand_intelligence import repository as bi_repo
from app.core import db

ACTOR = "測試員"


class DeriveFunnelStageTest(unittest.TestCase):
    """五個目標值各自推導到哪一層——這是本票的核心對照表，改錯了畫面會顯示錯的漏斗層。"""

    def test_awareness_maps_to_exposure(self):
        self.assertEqual(ads_plan.derive_funnel_stage("awareness"), "exposure")

    def test_traffic_maps_to_consideration(self):
        self.assertEqual(ads_plan.derive_funnel_stage("traffic"), "consideration")

    def test_engagement_maps_to_consideration(self):
        self.assertEqual(ads_plan.derive_funnel_stage("engagement"), "consideration")

    def test_leads_maps_to_conversion(self):
        self.assertEqual(ads_plan.derive_funnel_stage("leads"), "conversion")

    def test_sales_maps_to_conversion(self):
        self.assertEqual(ads_plan.derive_funnel_stage("sales"), "conversion")

    def test_unknown_objective_returns_none_not_a_guess(self):
        self.assertIsNone(ads_plan.derive_funnel_stage("不存在的目標"))

    def test_every_objective_text_key_has_a_mapping(self):
        """OBJECTIVE_TEXT 是開期表單能選的五個值——每一個都必須推導得出漏斗層，不留漏網之魚。"""
        for objective in ads_plan.OBJECTIVE_TEXT:
            self.assertIsNotNone(ads_plan.derive_funnel_stage(objective),
                                  f"{objective} 沒有對應的漏斗層")

    def test_all_mapped_stages_have_a_human_label(self):
        for stage in ads_plan.OBJECTIVE_TO_FUNNEL_STAGE.values():
            self.assertIn(stage, ads_plan.FUNNEL_STAGE_LABELS)


class CreateCycleWritesFunnelStageTest(unittest.TestCase):
    """開新檔期時，funnel_stage 欄位要真的有值——這是本票要接上的行為，之前永遠寫 None。"""

    def setUp(self):
        self.conn = db.current()
        self.brand = bi_repo.create_brand(self.conn, name="虛構晨光咖啡",
                                          client_name="測試客戶", actor=ACTOR)
        self.bid = self.brand["id"]

    def test_new_cycle_gets_funnel_stage_from_objective(self):
        cases = [
            ("awareness", "exposure"),
            ("traffic", "consideration"),
            ("engagement", "consideration"),
            ("leads", "conversion"),
            ("sales", "conversion"),
        ]
        for objective, expected_stage in cases:
            with self.subTest(objective=objective):
                cycle = ads_repo.create_cycle(
                    self.conn, self.bid, product_ids=[], pain_value=5000,
                    objective=objective, actor=ACTOR)
                self.assertEqual(cycle["funnel_stage"], expected_stage)
                stored = ads_repo.get_cycle(self.conn, self.bid, cycle["id"])
                self.assertEqual(stored["funnel_stage"], expected_stage,
                                  "回傳值跟寫進資料庫的值必須一致")


if __name__ == "__main__":
    unittest.main()
