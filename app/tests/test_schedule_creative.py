"""app/tests/test_schedule_creative.py — `_valid_creative_fields` 資料正確性。

小債（T1 收尾記下、2026-09-04 收掉）：`all(isinstance(v, str) for v in value)` 對空清單
與全空字串清單都真值——`value: []`、`value: ["", ""]` 都會通過驗證，讓畫面出現看得到、
點不出東西的空欄位。守的是資料正確性（全域 CLAUDE.md 測試四類之一）。
"""
import unittest

from app.schedule.creative import _valid_creative_fields


class CreativeFieldsRejectEmptyValuesTest(unittest.TestCase):
    def test_empty_list_value_is_rejected(self):
        self.assertIsNone(_valid_creative_fields([{"label": "賣點", "value": []}]))

    def test_all_blank_strings_value_is_rejected(self):
        self.assertIsNone(_valid_creative_fields([{"label": "賣點", "value": ["", ""]}]))

    def test_non_empty_value_still_accepted(self):
        fields = _valid_creative_fields([{"label": "賣點", "value": ["省時", "省力"]}])
        self.assertEqual(fields, [{"label": "賣點", "value": ["省時", "省力"]}])


if __name__ == "__main__":
    unittest.main()
