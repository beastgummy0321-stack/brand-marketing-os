# -*- coding: utf-8 -*-
"""app/tests/test_rule_cards.py — 規則卡通用機制（issue #12）。

驗：門檻值有預設種子、改值落庫後判定純函數立即用新值、重設回預設值、
示範卡（素材疲勞頻率門檻）數值與 app/methodology/ads-core.md 一致。
"""

import tempfile
import unittest
from pathlib import Path

from app.core import db, rule_cards


class RuleCardValueTest(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.conn = db.connect_and_migrate(Path(self._tmpdir.name) / "test.db")

    def tearDown(self):
        self.conn.close()
        self._tmpdir.cleanup()

    def _audit_rows(self):
        return [dict(r) for r in
                self.conn.execute("SELECT * FROM audit_log ORDER BY created_at, id").fetchall()]

    # -- 種子與預設值 -------------------------------------------------------

    def test_seed_values_match_methodology_ads_md(self):
        """app/methodology/ads-core.md 第 5 節「疲勞頻率門檻」表：
        冷受眾開發 警示2.5/危險4.0；再行銷 警示4.0/危險6.0；小眾／精準受眾 警示5.0/危險8.0。"""
        self.assertEqual(rule_cards.get_value(self.conn, "ad_creative_fatigue", "cold_warning"), 2.5)
        self.assertEqual(rule_cards.get_value(self.conn, "ad_creative_fatigue", "cold_danger"), 4.0)
        self.assertEqual(rule_cards.get_value(self.conn, "ad_creative_fatigue", "retargeting_warning"), 4.0)
        self.assertEqual(rule_cards.get_value(self.conn, "ad_creative_fatigue", "retargeting_danger"), 6.0)
        self.assertEqual(rule_cards.get_value(self.conn, "ad_creative_fatigue", "niche_warning"), 5.0)
        self.assertEqual(rule_cards.get_value(self.conn, "ad_creative_fatigue", "niche_danger"), 8.0)

    def test_get_value_falls_back_to_default_without_db(self):
        """conn=None 或表還沒建起來時，優雅回程式常數預設值，不噴錯（principles 16）。"""
        self.assertEqual(rule_cards.get_value(None, "ad_creative_fatigue", "cold_warning"), 2.5)
        bare = db.connect(Path(self._tmpdir.name) / "bare.db")
        self.assertEqual(rule_cards.get_value(bare, "ad_creative_fatigue", "cold_warning"), 2.5)
        bare.close()

    def test_unknown_card_or_field_raises(self):
        with self.assertRaises(ValueError):
            rule_cards.get_value(self.conn, "沒這張卡", "x")
        with self.assertRaises(ValueError):
            rule_cards.get_value(self.conn, "ad_creative_fatigue", "沒這個欄位")

    def test_list_cards_includes_human_readable_metadata(self):
        cards = rule_cards.list_cards(self.conn)
        self.assertEqual(len(cards), 4)
        by_key = {c["key"]: c for c in cards}
        card = by_key["ad_creative_fatigue"]
        self.assertIn("素材疲勞", card["title"])
        for c in cards:
            self.assertTrue(c["description"])  # 「這個門檻管什麼」說明不可空
            for f in c["fields"]:
                self.assertTrue(f["label"])
                self.assertTrue(f["help"])

    def test_sample_size_seed_values_match_methodology_ab_testing_md(self):
        """app/methodology/ab-testing.md 第 3 節樣本數速查表，20% 提升幅度欄：
        基準轉換率 1%→97000、3%→31000、5%→18000、10%→8700、20%→4000（每變體樣本數）。"""
        self.assertEqual(rule_cards.get_value(self.conn, "sample_size", "baseline_1pct"), 97000.0)
        self.assertEqual(rule_cards.get_value(self.conn, "sample_size", "baseline_3pct"), 31000.0)
        self.assertEqual(rule_cards.get_value(self.conn, "sample_size", "baseline_5pct"), 18000.0)
        self.assertEqual(rule_cards.get_value(self.conn, "sample_size", "baseline_10pct"), 8700.0)
        self.assertEqual(rule_cards.get_value(self.conn, "sample_size", "baseline_20pct"), 4000.0)

    def test_budget_structure_seed_values_match_methodology_ads_md(self):
        """app/methodology/ads-core.md 第 3 節：每組日預算下限約 NT$300、測試期 70/30、放大期 80/20。"""
        self.assertEqual(
            rule_cards.get_value(self.conn, "budget_structure", "min_daily_per_group"), 300.0)
        self.assertEqual(
            rule_cards.get_value(self.conn, "budget_structure", "medium_tier_floor"), 600.0)
        self.assertEqual(
            rule_cards.get_value(self.conn, "budget_structure", "large_tier_floor"), 1200.0)
        self.assertEqual(
            rule_cards.get_value(self.conn, "budget_structure", "medium_validation_ratio"), 0.7)
        self.assertEqual(
            rule_cards.get_value(self.conn, "budget_structure", "large_scaling_ratio"), 0.8)

    def test_pacing_seed_value_matches_migration(self):
        """票 08-pacing-alert：步調偏差門檻種子值（migrations/0009_pacing_card.sql）。"""
        self.assertEqual(
            rule_cards.get_value(self.conn, "pacing", "deviation_threshold_ratio"), 0.15)

    # -- 改值即時生效 ---------------------------------------------------------

    def test_set_value_persists_and_classify_uses_new_value_immediately(self):
        """改值落庫後，判定純函數立即用新值——不用重開程式、不用清快取。"""
        # 改之前：頻率 3.0 在冷受眾門檻下是「警示」（警示 2.5–4.0）
        self.assertEqual(rule_cards.classify_ad_frequency(self.conn, "cold", 3.0), "warning")

        rule_cards.set_value(self.conn, "ad_creative_fatigue", "cold_warning", 5.0, actor="測試員")
        # 改完：警示門檻拉高到 5.0，同樣頻率 3.0 現在落在安全區
        self.assertEqual(rule_cards.classify_ad_frequency(self.conn, "cold", 3.0), "safe")
        self.assertEqual(rule_cards.get_value(self.conn, "ad_creative_fatigue", "cold_warning"), 5.0)

        rows = self._audit_rows()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["entity_type"], "rule_card_value")
        self.assertEqual(rows[0]["entity_id"], "ad_creative_fatigue.cold_warning")
        self.assertEqual(rows[0]["action"], "update")
        self.assertEqual(rows[0]["actor"], "測試員")
        self.assertIsNone(rows[0]["brand_id"])  # 平台層級門檻，不是品牌資料

    def test_set_value_upserts_without_duplicating_row(self):
        rule_cards.set_value(self.conn, "ad_creative_fatigue", "cold_warning", 3.0, actor="A")
        rule_cards.set_value(self.conn, "ad_creative_fatigue", "cold_warning", 3.3, actor="B")
        count = self.conn.execute(
            "SELECT COUNT(*) FROM rule_card_value WHERE card_key = 'ad_creative_fatigue'"
            " AND field_key = 'cold_warning'"
        ).fetchone()[0]
        self.assertEqual(count, 1)
        self.assertEqual(rule_cards.get_value(self.conn, "ad_creative_fatigue", "cold_warning"), 3.3)

    # -- 重設 -----------------------------------------------------------------

    def test_reset_card_restores_defaults(self):
        rule_cards.set_value(self.conn, "ad_creative_fatigue", "cold_warning", 9.9, actor="測試員")
        rule_cards.set_value(self.conn, "ad_creative_fatigue", "niche_danger", 1.0, actor="測試員")
        rule_cards.reset_card(self.conn, "ad_creative_fatigue", actor="測試員")

        self.assertEqual(rule_cards.get_value(self.conn, "ad_creative_fatigue", "cold_warning"), 2.5)
        self.assertEqual(rule_cards.get_value(self.conn, "ad_creative_fatigue", "niche_danger"), 8.0)

    def test_reset_skips_fields_already_at_default_no_noise_audit(self):
        rule_cards.set_value(self.conn, "ad_creative_fatigue", "cold_warning", 9.9, actor="測試員")
        before = len(self._audit_rows())
        rule_cards.reset_card(self.conn, "ad_creative_fatigue", actor="測試員")
        after_rows = self._audit_rows()
        # 只有 cold_warning 被改過，reset 應該只再多寫一筆（把它改回 2.5），
        # 其餘 5 個本來就是預設值的欄位不該產生稽核噪音。
        self.assertEqual(len(after_rows) - before, 1)
        self.assertEqual(after_rows[-1]["entity_id"], "ad_creative_fatigue.cold_warning")

    def test_reset_unknown_card_raises(self):
        with self.assertRaises(ValueError):
            rule_cards.reset_card(self.conn, "沒這張卡", actor="測試員")


class ClassifyAdFrequencyTest(unittest.TestCase):
    """三種受眾類型的安全／警示／危險邊界，對照 app/methodology/ads-core.md 第 5 節的表。"""

    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.conn = db.connect_and_migrate(Path(self._tmpdir.name) / "test.db")

    def tearDown(self):
        self.conn.close()
        self._tmpdir.cleanup()

    def test_cold_audience_boundaries(self):
        self.assertEqual(rule_cards.classify_ad_frequency(self.conn, "cold", 1.0), "safe")
        self.assertEqual(rule_cards.classify_ad_frequency(self.conn, "cold", 2.4), "safe")
        self.assertEqual(rule_cards.classify_ad_frequency(self.conn, "cold", 2.5), "warning")
        self.assertEqual(rule_cards.classify_ad_frequency(self.conn, "cold", 4.0), "warning")
        self.assertEqual(rule_cards.classify_ad_frequency(self.conn, "cold", 4.1), "danger")

    def test_retargeting_audience_boundaries(self):
        self.assertEqual(rule_cards.classify_ad_frequency(self.conn, "retargeting", 3.9), "safe")
        self.assertEqual(rule_cards.classify_ad_frequency(self.conn, "retargeting", 4.0), "warning")
        self.assertEqual(rule_cards.classify_ad_frequency(self.conn, "retargeting", 6.1), "danger")

    def test_niche_audience_boundaries(self):
        self.assertEqual(rule_cards.classify_ad_frequency(self.conn, "niche", 4.9), "safe")
        self.assertEqual(rule_cards.classify_ad_frequency(self.conn, "niche", 5.0), "warning")
        self.assertEqual(rule_cards.classify_ad_frequency(self.conn, "niche", 8.1), "danger")

    def test_unknown_audience_type_raises(self):
        with self.assertRaises(ValueError):
            rule_cards.classify_ad_frequency(self.conn, "熱門到爆", 3.0)


class SampleSizeTierTest(unittest.TestCase):
    """票 8：樣本數統計等級——邊界案例對照 ab-testing.md 速查表的門檻值。"""

    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.conn = db.connect_and_migrate(Path(self._tmpdir.name) / "test.db")

    def tearDown(self):
        self.conn.close()
        self._tmpdir.cleanup()

    def test_no_observed_rate_is_directional_not_a_guess(self):
        """沒有轉換率可比對（例如還沒有點擊）——查不了表，一律方向性判讀，不假裝。"""
        result = rule_cards.sample_size_tier(self.conn, 100000, None)
        self.assertEqual(result["level"], "directional")
        self.assertIsNone(result["required"])

    def test_zero_sample_count_is_directional(self):
        result = rule_cards.sample_size_tier(self.conn, 0, 0.05)
        self.assertEqual(result["level"], "directional")

    def test_boundary_exact_threshold_is_statistical(self):
        """剛好達到門檻（>=）才算統計等級——差一點就不算，不能寬鬆處理。"""
        result = rule_cards.sample_size_tier(self.conn, 18000, 0.05)
        self.assertEqual(result["level"], "statistical")
        self.assertEqual(result["required"], 18000.0)

    def test_boundary_one_below_threshold_is_directional(self):
        result = rule_cards.sample_size_tier(self.conn, 17999, 0.05)
        self.assertEqual(result["level"], "directional")

    def test_small_budget_typical_sample_stays_directional(self):
        """小預算帳戶常見的樣本量（幾百次點擊）——連最寬鬆的 20% 基準列都收不到，
        必須誠實顯示方向性判讀，不能包裝成統計顯著。"""
        result = rule_cards.sample_size_tier(self.conn, 400, 0.10)
        self.assertEqual(result["level"], "directional")

    def test_picks_nearest_baseline_row(self):
        """觀察到的轉換率會找最接近的那一列基準轉換率去查表，不是隨便挑一列。"""
        near_20pct = rule_cards.sample_size_tier(self.conn, 4000, 0.18)
        self.assertEqual(near_20pct["baseline"], 0.20)
        self.assertEqual(near_20pct["required"], 4000.0)

        near_1pct = rule_cards.sample_size_tier(self.conn, 97000, 0.012)
        self.assertEqual(near_1pct["baseline"], 0.01)
        self.assertEqual(near_1pct["required"], 97000.0)

    def test_custom_rule_card_value_takes_effect_immediately(self):
        """改規則卡數值後，統計等級判定立即用新值——跟其他規則卡同一套機制。"""
        rule_cards.set_value(self.conn, "sample_size", "baseline_5pct", 100.0, actor="測試員")
        result = rule_cards.sample_size_tier(self.conn, 150, 0.05)
        self.assertEqual(result["level"], "statistical")
        self.assertEqual(result["required"], 100.0)


if __name__ == "__main__":
    unittest.main()
