"""app/tests/test_rule_cards.py — 規則卡通用機制（issue #12；分品牌：設定中心票 01）。

驗：門檻值有預設種子、改值落庫後判定純函數立即用新值、重設回預設值、
示範卡（素材疲勞頻率門檻）數值與 app/methodology/ads-core.md 一致、
分品牌覆寫互不干擾（A 品牌改值不影響 B 品牌、沒覆寫時繼續拿系統預設值）。
"""

import os
import unittest

import psycopg
from psycopg.rows import dict_row

from app.core import db, rule_cards

BID_A = "brand_a"
BID_B = "brand_b"


class RuleCardValueTest(unittest.TestCase):
    def setUp(self):
        self.conn = db.current()
        # ADR 0027：conftest.py 逐「模組」一個 schema，不是逐「測試」——這個檔案的三個
        # TestCase 類別全部共用同一個 schema，BID_A／BID_B 又是整檔共用的固定字面值，
        # 任何一個測試對它們的 set_value() 不清乾淨，就會滲漏進同一檔案其他測試方法
        # （甚至別的 class）。每個測試開始前把這兩個品牌的規則卡覆寫值全部清空，回到
        # 「沒有任何覆寫，全部拿系統預設值」的乾淨起點。
        self.conn.execute("DELETE FROM rule_card_value WHERE brand_id IN (%s, %s)", (BID_A, BID_B))
        self.conn.execute(
            "DELETE FROM audit_log WHERE entity_type = 'rule_card_value' AND brand_id IN (%s, %s)",
            (BID_A, BID_B),
        )
        self.conn.commit()

    def _audit_rows(self):
        return [dict(r) for r in
                self.conn.execute("SELECT * FROM audit_log ORDER BY created_at, id").fetchall()]

    # -- 種子與預設值 -------------------------------------------------------

    def test_seed_values_match_methodology_ads_md(self):
        """app/methodology/ads-core.md 第 5 節「疲勞頻率門檻」表：
        冷受眾開發 警示2.5/危險4.0；再行銷 警示4.0/危險6.0；小眾／精準受眾 警示5.0/危險8.0。
        品牌沒有任何覆寫時，一律拿系統預設值（分品牌後的既有行為延續）。

        cold_danger 例外：CARDS 常數已於 2026-08-08 業界體檢調降為 3.5（見 rule_cards.py
        該欄位註解），methodology 文件尚未同步更新——這個落差在分品牌之前被舊版全域表裡
        沒再更新過的 migration 種子值（4.0）遮住；分品牌新表不留舊種子，直接反映現在的
        CARDS default，這裡改成斷言現況，不是本票要修的文件落差。"""
        self.assertEqual(rule_cards.get_value(self.conn, BID_A, "ad_creative_fatigue", "cold_warning"), 2.5)
        self.assertEqual(rule_cards.get_value(self.conn, BID_A, "ad_creative_fatigue", "cold_danger"), 3.5)
        self.assertEqual(rule_cards.get_value(self.conn, BID_A, "ad_creative_fatigue", "retargeting_warning"), 4.0)
        self.assertEqual(rule_cards.get_value(self.conn, BID_A, "ad_creative_fatigue", "retargeting_danger"), 6.0)
        self.assertEqual(rule_cards.get_value(self.conn, BID_A, "ad_creative_fatigue", "niche_warning"), 5.0)
        self.assertEqual(rule_cards.get_value(self.conn, BID_A, "ad_creative_fatigue", "niche_danger"), 8.0)

    def test_get_value_falls_back_to_default_without_db(self):
        """conn=None 或表還沒建起來時（例如全新 schema 還沒跑 migrations），優雅回程式
        常數預設值，不噴錯（principles 16）。「表還沒建起來」在 Postgres 世界模擬成一個
        全新、沒跑過任何 migration 的 schema（跟 conftest.py 逐模組建的正常 schema不同）。"""
        self.assertEqual(rule_cards.get_value(None, BID_A, "ad_creative_fatigue", "cold_warning"), 2.5)

        bare_schema = f"t_bare_rule_cards_{os.getpid()}"
        base_dsn = db.dsn().split("?", 1)[0]
        admin = psycopg.connect(base_dsn, autocommit=True, row_factory=dict_row)
        admin.execute(f'DROP SCHEMA IF EXISTS "{bare_schema}" CASCADE')
        admin.execute(f'CREATE SCHEMA "{bare_schema}"')
        admin.execute(f'SET search_path TO "{bare_schema}"')
        bare = db.Conn(admin)
        try:
            self.assertEqual(
                rule_cards.get_value(bare, BID_A, "ad_creative_fatigue", "cold_warning"), 2.5)
        finally:
            admin.execute(f'DROP SCHEMA IF EXISTS "{bare_schema}" CASCADE')
            admin.close()

    def test_unknown_card_or_field_raises(self):
        with self.assertRaises(ValueError):
            rule_cards.get_value(self.conn, BID_A, "沒這張卡", "x")
        with self.assertRaises(ValueError):
            rule_cards.get_value(self.conn, BID_A, "ad_creative_fatigue", "沒這個欄位")

    def test_list_cards_includes_human_readable_metadata(self):
        cards = rule_cards.list_cards(self.conn, BID_A)
        self.assertEqual(len(cards), 10)  # 票 07 新增 schedule_budget，票 08 新增 schedule_plan_count
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
        self.assertEqual(rule_cards.get_value(self.conn, BID_A, "sample_size", "baseline_1pct"), 97000.0)
        self.assertEqual(rule_cards.get_value(self.conn, BID_A, "sample_size", "baseline_3pct"), 31000.0)
        self.assertEqual(rule_cards.get_value(self.conn, BID_A, "sample_size", "baseline_5pct"), 18000.0)
        self.assertEqual(rule_cards.get_value(self.conn, BID_A, "sample_size", "baseline_10pct"), 8700.0)
        self.assertEqual(rule_cards.get_value(self.conn, BID_A, "sample_size", "baseline_20pct"), 4000.0)

    def test_budget_structure_seed_values_match_methodology_ads_md(self):
        """app/methodology/ads-core.md 第 3 節：每組日預算下限約 NT$300、測試期 70/30、放大期 80/20。"""
        self.assertEqual(
            rule_cards.get_value(self.conn, BID_A, "budget_structure", "min_daily_per_group"), 300.0)
        self.assertEqual(
            rule_cards.get_value(self.conn, BID_A, "budget_structure", "medium_tier_floor"), 600.0)
        self.assertEqual(
            rule_cards.get_value(self.conn, BID_A, "budget_structure", "large_tier_floor"), 1200.0)
        self.assertEqual(
            rule_cards.get_value(self.conn, BID_A, "budget_structure", "medium_validation_ratio"), 0.7)
        self.assertEqual(
            rule_cards.get_value(self.conn, BID_A, "budget_structure", "large_scaling_ratio"), 0.8)

    def test_pacing_seed_value_matches_migration(self):
        """票 08-pacing-alert：步調偏差門檻種子值（migrations/0009_pacing_card.sql）。"""
        self.assertEqual(
            rule_cards.get_value(self.conn, BID_A, "pacing", "deviation_threshold_ratio"), 0.15)

    def test_rule_prompt_cap_default_matches_adr_0012(self):
        """票 02-prompt-cap-and-overflow-list：進生成提示詞的規則上限，系統預設 20 條
        （ADR 0012 第二節），沒有種子 migration，靠 CARDS default 落地就夠。"""
        self.assertEqual(
            rule_cards.get_value(self.conn, BID_A, "rule_prompt_cap", "max_active_rules"), 20.0)

    def test_rule_expiry_default_matches_adr_0012(self):
        """票 01-rule-expiry-reconfirm：規則重新確認門檻，系統預設 6 期（ADR 0012 第一節），
        沒有種子 migration，靠 CARDS default 落地就夠。"""
        self.assertEqual(
            rule_cards.get_value(self.conn, BID_A, "rule_expiry", "reconfirm_cycles"), 6.0)

    # -- 改值即時生效 ---------------------------------------------------------

    def test_set_value_persists_and_classify_uses_new_value_immediately(self):
        """改值落庫後，判定純函數立即用新值——不用重開程式、不用清快取。"""
        # 改之前：頻率 3.0 在冷受眾門檻下是「警示」（警示 2.5–4.0）
        self.assertEqual(rule_cards.classify_ad_frequency(self.conn, BID_A, "cold", 3.0), "warning")

        rule_cards.set_value(self.conn, BID_A, "ad_creative_fatigue", "cold_warning", 5.0, actor="測試員", org_id=db.DEV_ORG_ID)
        # 改完：警示門檻拉高到 5.0，同樣頻率 3.0 現在落在安全區
        self.assertEqual(rule_cards.classify_ad_frequency(self.conn, BID_A, "cold", 3.0), "safe")
        self.assertEqual(rule_cards.get_value(self.conn, BID_A, "ad_creative_fatigue", "cold_warning"), 5.0)

        rows = self._audit_rows()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["entity_type"], "rule_card_value")
        self.assertEqual(rows[0]["entity_id"], "ad_creative_fatigue.cold_warning")
        self.assertEqual(rows[0]["action"], "update")
        self.assertEqual(rows[0]["actor"], "測試員")
        self.assertEqual(rows[0]["brand_id"], BID_A)  # 分品牌後是真正的品牌事件（不再是 None）

    def test_set_value_upserts_without_duplicating_row(self):
        rule_cards.set_value(self.conn, BID_A, "ad_creative_fatigue", "cold_warning", 3.0, actor="A", org_id=db.DEV_ORG_ID)
        rule_cards.set_value(self.conn, BID_A, "ad_creative_fatigue", "cold_warning", 3.3, actor="B", org_id=db.DEV_ORG_ID)
        count = self.conn.execute(
            "SELECT COUNT(*) AS n FROM rule_card_value WHERE brand_id = %s AND card_key = 'ad_creative_fatigue'"
            " AND field_key = 'cold_warning'", (BID_A,)
        ).fetchone()["n"]
        self.assertEqual(count, 1)
        self.assertEqual(rule_cards.get_value(self.conn, BID_A, "ad_creative_fatigue", "cold_warning"), 3.3)

    # -- 分品牌隔離（設定中心票 01） -------------------------------------------

    def test_brand_override_does_not_leak_into_other_brand(self):
        """A 品牌改規則卡值，B 品牌完全不受影響——各自一份覆寫值。"""
        rule_cards.set_value(self.conn, BID_A, "ad_creative_fatigue", "cold_warning", 9.9, actor="測試員", org_id=db.DEV_ORG_ID)
        self.assertEqual(rule_cards.get_value(self.conn, BID_A, "ad_creative_fatigue", "cold_warning"), 9.9)
        self.assertEqual(rule_cards.get_value(self.conn, BID_B, "ad_creative_fatigue", "cold_warning"), 2.5)

    def test_brand_without_override_falls_back_to_system_default(self):
        """B 品牌從沒改過這個欄位——就算 A 品牌已經改過，B 品牌繼續拿系統預設值。"""
        rule_cards.set_value(self.conn, BID_A, "budget_structure", "min_daily_per_group", 500.0,
                             actor="測試員", org_id=db.DEV_ORG_ID)
        self.assertEqual(
            rule_cards.get_value(self.conn, BID_B, "budget_structure", "min_daily_per_group"), 300.0)

    # -- 重設 -----------------------------------------------------------------

    def test_reset_card_restores_defaults(self):
        rule_cards.set_value(self.conn, BID_A, "ad_creative_fatigue", "cold_warning", 9.9, actor="測試員", org_id=db.DEV_ORG_ID)
        rule_cards.set_value(self.conn, BID_A, "ad_creative_fatigue", "niche_danger", 1.0, actor="測試員", org_id=db.DEV_ORG_ID)
        rule_cards.reset_card(self.conn, BID_A, "ad_creative_fatigue", actor="測試員", org_id=db.DEV_ORG_ID)

        self.assertEqual(rule_cards.get_value(self.conn, BID_A, "ad_creative_fatigue", "cold_warning"), 2.5)
        self.assertEqual(rule_cards.get_value(self.conn, BID_A, "ad_creative_fatigue", "niche_danger"), 8.0)

    def test_reset_skips_fields_already_at_default_no_noise_audit(self):
        rule_cards.set_value(self.conn, BID_A, "ad_creative_fatigue", "cold_warning", 9.9, actor="測試員", org_id=db.DEV_ORG_ID)
        before = len(self._audit_rows())
        rule_cards.reset_card(self.conn, BID_A, "ad_creative_fatigue", actor="測試員", org_id=db.DEV_ORG_ID)
        after_rows = self._audit_rows()
        # 只有 cold_warning 被測試改過；分品牌新表沒有殘留的舊 migration 種子值，其餘 5 個
        # 欄位（含 cold_danger）本來就是 CARDS 現在的 default，reset 不該產生額外稽核噪音。
        self.assertEqual(len(after_rows) - before, 1)
        touched = {r["entity_id"] for r in after_rows[-1:]}
        self.assertEqual(touched, {"ad_creative_fatigue.cold_warning"})

    def test_reset_unknown_card_raises(self):
        with self.assertRaises(ValueError):
            rule_cards.reset_card(self.conn, BID_A, "沒這張卡", actor="測試員", org_id=db.DEV_ORG_ID)


class ClassifyAdFrequencyTest(unittest.TestCase):
    """三種受眾類型的安全／警示／危險邊界，對照 app/methodology/ads-core.md 第 5 節的表。"""

    def setUp(self):
        self.conn = db.current()
        # ADR 0027：conftest.py 逐「模組」一個 schema，不是逐「測試」——這個檔案的三個
        # TestCase 類別全部共用同一個 schema，BID_A／BID_B 又是整檔共用的固定字面值，
        # 任何一個測試對它們的 set_value() 不清乾淨，就會滲漏進同一檔案其他測試方法
        # （甚至別的 class）。每個測試開始前把這兩個品牌的規則卡覆寫值全部清空，回到
        # 「沒有任何覆寫，全部拿系統預設值」的乾淨起點。
        self.conn.execute("DELETE FROM rule_card_value WHERE brand_id IN (%s, %s)", (BID_A, BID_B))
        self.conn.execute(
            "DELETE FROM audit_log WHERE entity_type = 'rule_card_value' AND brand_id IN (%s, %s)",
            (BID_A, BID_B),
        )
        self.conn.commit()

    def test_cold_audience_boundaries(self):
        # danger 門檻現行 CARDS default 是 3.5（2026-08-08 業界體檢調降，見 rule_cards.py
        # cold_danger 欄位註解），不是 methodology 文件仍寫著的 4.0——同一個落差說明見
        # test_rule_cards.py 的 test_seed_values_match_methodology_ads_md。
        self.assertEqual(rule_cards.classify_ad_frequency(self.conn, BID_A, "cold", 1.0), "safe")
        self.assertEqual(rule_cards.classify_ad_frequency(self.conn, BID_A, "cold", 2.4), "safe")
        self.assertEqual(rule_cards.classify_ad_frequency(self.conn, BID_A, "cold", 2.5), "warning")
        self.assertEqual(rule_cards.classify_ad_frequency(self.conn, BID_A, "cold", 3.5), "warning")
        self.assertEqual(rule_cards.classify_ad_frequency(self.conn, BID_A, "cold", 3.6), "danger")

    def test_retargeting_audience_boundaries(self):
        self.assertEqual(rule_cards.classify_ad_frequency(self.conn, BID_A, "retargeting", 3.9), "safe")
        self.assertEqual(rule_cards.classify_ad_frequency(self.conn, BID_A, "retargeting", 4.0), "warning")
        self.assertEqual(rule_cards.classify_ad_frequency(self.conn, BID_A, "retargeting", 6.1), "danger")

    def test_niche_audience_boundaries(self):
        self.assertEqual(rule_cards.classify_ad_frequency(self.conn, BID_A, "niche", 4.9), "safe")
        self.assertEqual(rule_cards.classify_ad_frequency(self.conn, BID_A, "niche", 5.0), "warning")
        self.assertEqual(rule_cards.classify_ad_frequency(self.conn, BID_A, "niche", 8.1), "danger")

    def test_unknown_audience_type_raises(self):
        with self.assertRaises(ValueError):
            rule_cards.classify_ad_frequency(self.conn, BID_A, "熱門到爆", 3.0)


class SampleSizeTierTest(unittest.TestCase):
    """票 8：樣本數統計等級——邊界案例對照 ab-testing.md 速查表的門檻值。"""

    def setUp(self):
        self.conn = db.current()
        # ADR 0027：conftest.py 逐「模組」一個 schema，不是逐「測試」——這個檔案的三個
        # TestCase 類別全部共用同一個 schema，BID_A／BID_B 又是整檔共用的固定字面值，
        # 任何一個測試對它們的 set_value() 不清乾淨，就會滲漏進同一檔案其他測試方法
        # （甚至別的 class）。每個測試開始前把這兩個品牌的規則卡覆寫值全部清空，回到
        # 「沒有任何覆寫，全部拿系統預設值」的乾淨起點。
        self.conn.execute("DELETE FROM rule_card_value WHERE brand_id IN (%s, %s)", (BID_A, BID_B))
        self.conn.execute(
            "DELETE FROM audit_log WHERE entity_type = 'rule_card_value' AND brand_id IN (%s, %s)",
            (BID_A, BID_B),
        )
        self.conn.commit()

    def test_no_observed_rate_is_directional_not_a_guess(self):
        """沒有轉換率可比對（例如還沒有點擊）——查不了表，一律方向性判讀，不假裝。"""
        result = rule_cards.sample_size_tier(self.conn, BID_A, 100000, None)
        self.assertEqual(result["level"], "directional")
        self.assertIsNone(result["required"])

    def test_zero_sample_count_is_directional(self):
        result = rule_cards.sample_size_tier(self.conn, BID_A, 0, 0.05)
        self.assertEqual(result["level"], "directional")

    def test_boundary_exact_threshold_is_statistical(self):
        """剛好達到門檻（>=）才算統計等級——差一點就不算，不能寬鬆處理。"""
        result = rule_cards.sample_size_tier(self.conn, BID_A, 18000, 0.05)
        self.assertEqual(result["level"], "statistical")
        self.assertEqual(result["required"], 18000.0)

    def test_boundary_one_below_threshold_is_directional(self):
        result = rule_cards.sample_size_tier(self.conn, BID_A, 17999, 0.05)
        self.assertEqual(result["level"], "directional")

    def test_small_budget_typical_sample_stays_directional(self):
        """小預算帳戶常見的樣本量（幾百次點擊）——連最寬鬆的 20% 基準列都收不到，
        必須誠實顯示方向性判讀，不能包裝成統計顯著。"""
        result = rule_cards.sample_size_tier(self.conn, BID_A, 400, 0.10)
        self.assertEqual(result["level"], "directional")

    def test_picks_nearest_baseline_row(self):
        """觀察到的轉換率會找最接近的那一列基準轉換率去查表，不是隨便挑一列。"""
        near_20pct = rule_cards.sample_size_tier(self.conn, BID_A, 4000, 0.18)
        self.assertEqual(near_20pct["baseline"], 0.20)
        self.assertEqual(near_20pct["required"], 4000.0)

        near_1pct = rule_cards.sample_size_tier(self.conn, BID_A, 97000, 0.012)
        self.assertEqual(near_1pct["baseline"], 0.01)
        self.assertEqual(near_1pct["required"], 97000.0)

    def test_custom_rule_card_value_takes_effect_immediately(self):
        """改規則卡數值後，統計等級判定立即用新值——跟其他規則卡同一套機制。"""
        rule_cards.set_value(self.conn, BID_A, "sample_size", "baseline_5pct", 100.0, actor="測試員", org_id=db.DEV_ORG_ID)
        result = rule_cards.sample_size_tier(self.conn, BID_A, 150, 0.05)
        self.assertEqual(result["level"], "statistical")
        self.assertEqual(result["required"], 100.0)

    def test_brand_override_does_not_leak_into_other_brand(self):
        """A 品牌改過的樣本數門檻不影響 B 品牌的統計等級判定。"""
        rule_cards.set_value(self.conn, BID_A, "sample_size", "baseline_5pct", 100.0, actor="測試員", org_id=db.DEV_ORG_ID)
        result = rule_cards.sample_size_tier(self.conn, BID_B, 150, 0.05)
        self.assertEqual(result["level"], "directional")  # B 品牌仍用系統預設 18000


if __name__ == "__main__":
    unittest.main()
