"""app/tests/test_prototype_phase.py — 原型階段結束旗標（修憲落地 A6，決策 0037 第一節）。

判定方式：檔期結算完成且實際花費 > 0（本檔只測旗標本身的判定與副作用；
`reading.finalize()` 真的把實際花費算給它看，由 test_ads_reading.py 的整合測試涵蓋）。
"""

import unittest

from app.core import db, prototype_phase
from app.core import interrupts as core_interrupts


class PrototypePhaseFlagTest(unittest.TestCase):
    def setUp(self):
        self.conn = db.current()
        # 旗標是全系統唯一一份（app_setting 一個固定 key，不分品牌），conftest.py 是
        # 逐模組一個 schema、不是逐測試——不清掉的話，本檔任何一個測試先把旗標翻成
        # 「已結束」，後面斷言「還沒結束」的測試就會看到別的測試留下的狀態。
        self.conn.execute(
            "DELETE FROM app_setting WHERE key = %s", (prototype_phase.FLAG_SETTING,))
        self.conn.execute(
            "DELETE FROM interrupt WHERE dedupe_key = 'prototype_phase_ended'")
        self.conn.execute(
            "DELETE FROM audit_log WHERE entity_type = 'prototype_phase'")
        self.conn.commit()

    def test_not_ended_initially(self):
        self.assertFalse(prototype_phase.has_ended(self.conn))

    def test_zero_spend_does_not_flag(self):
        triggered = prototype_phase.check_and_flag(self.conn, actual_spend=0, actor="測試員")
        self.assertFalse(triggered)
        self.assertFalse(prototype_phase.has_ended(self.conn))

    def test_none_spend_does_not_flag(self):
        triggered = prototype_phase.check_and_flag(self.conn, actual_spend=None, actor="測試員")
        self.assertFalse(triggered)
        self.assertFalse(prototype_phase.has_ended(self.conn))

    def test_real_spend_flags_and_notifies(self):
        triggered = prototype_phase.check_and_flag(
            self.conn, actual_spend=8500.0, actor="測試員", cycle_id="cyc_FAKE")
        self.assertTrue(triggered)
        self.assertTrue(prototype_phase.has_ended(self.conn))

        open_items = core_interrupts.list_open(self.conn)
        matches = [i for i in open_items if i["category"] == "prototype_phase_ended"]
        self.assertEqual(len(matches), 1)
        self.assertLessEqual(len(matches[0]["message"]), core_interrupts.MAX_MESSAGE_LEN)
        self.assertIsNone(matches[0]["brand_id"])  # 系統級事件，不屬於任何一個品牌

        audit_rows = [dict(r) for r in self.conn.execute(
            "SELECT * FROM audit_log WHERE entity_type = 'prototype_phase'")]
        self.assertEqual(len(audit_rows), 1)
        self.assertIsNone(audit_rows[0]["brand_id"])
        self.assertEqual(audit_rows[0]["action"], "ended")

    def test_second_call_after_ended_is_a_no_op(self):
        prototype_phase.check_and_flag(self.conn, actual_spend=100, actor="測試員")
        triggered_again = prototype_phase.check_and_flag(
            self.conn, actual_spend=999, actor="測試員")
        self.assertFalse(triggered_again)

        open_items = core_interrupts.list_open(self.conn)
        matches = [i for i in open_items if i["category"] == "prototype_phase_ended"]
        self.assertEqual(len(matches), 1)  # 沒有被第二次呼叫重複塞一筆

        audit_rows = [dict(r) for r in self.conn.execute(
            "SELECT * FROM audit_log WHERE entity_type = 'prototype_phase'")]
        self.assertEqual(len(audit_rows), 1)


class ExemptionsContentTest(unittest.TestCase):
    """到期提醒的四項豁免內容要反映現況，不是照抄決策 0037 寫下時的舊清單。"""

    def test_exactly_four_exemptions_from_decision_0037(self):
        self.assertEqual(len(prototype_phase.EXEMPTIONS), 4)
        for exemption in prototype_phase.EXEMPTIONS:
            self.assertTrue(exemption["item"])
            self.assertTrue(exemption["status"])

    def test_status_text_reflects_m3_and_m4_not_the_stale_list(self):
        by_item = {e["item"]: e["status"] for e in prototype_phase.EXEMPTIONS}
        self.assertIn("環境變數", by_item["明文 API 金鑰入庫"])
        self.assertIn("M4", by_item["明文 API 金鑰入庫"])
        self.assertIn("M3", by_item["全域單一無鎖連線"])
        self.assertIn("鎖", by_item["全域單一無鎖連線"])
