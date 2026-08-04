# -*- coding: utf-8 -*-
"""app/tests/test_orders_identity.py — 訂單票（issue #33）：顧客單向雜湊正規化。"""

import unittest

from app.orders import identity


class NormalizeTest(unittest.TestCase):
    def test_phone_plus886_and_0_prefix_are_the_same_person(self):
        self.assertEqual(identity.normalize_phone("0912345678"),
                         identity.normalize_phone("+886912345678"))

    def test_phone_886_without_plus_is_the_same_person(self):
        self.assertEqual(identity.normalize_phone("0912345678"),
                         identity.normalize_phone("886912345678"))

    def test_phone_strips_separators(self):
        self.assertEqual(identity.normalize_phone("0912-345-678"), "0912345678")

    def test_email_case_insensitive(self):
        self.assertEqual(identity.normalize_email("A@Example.com"),
                         identity.normalize_email("a@example.com"))

    def test_blank_input_is_none(self):
        self.assertIsNone(identity.normalize_email(""))
        self.assertIsNone(identity.normalize_phone(None))


class IdentityKeyTest(unittest.TestCase):
    def test_email_normalization_variants_hash_to_same_person(self):
        h1, t1 = identity.identity_key(billing_email="A@Example.com")
        h2, t2 = identity.identity_key(billing_email=" a@example.com ")
        self.assertEqual(h1, h2)
        self.assertEqual((t1, t2), ("email", "email"))

    def test_phone_variants_hash_to_same_person(self):
        h1, _ = identity.identity_key(billing_phone="0912345678")
        h2, _ = identity.identity_key(billing_phone="+886 912 345 678")
        self.assertEqual(h1, h2)

    def test_email_wins_over_phone_when_both_present(self):
        by_email, kind = identity.identity_key(billing_email="a@example.com",
                                                billing_phone="0912345678")
        by_phone_only, _ = identity.identity_key(billing_phone="0912345678")
        self.assertEqual(kind, "email")
        self.assertNotEqual(by_email, by_phone_only)

    def test_falls_back_to_phone_when_no_email(self):
        h, kind = identity.identity_key(billing_email=None, billing_phone="0912345678")
        self.assertEqual(kind, "phone")
        self.assertIsNotNone(h)

    def test_no_usable_identity_returns_none(self):
        self.assertEqual(identity.identity_key(billing_email=None, billing_phone=None),
                         (None, None))

    def test_recipient_fields_are_not_part_of_this_api(self):
        """收件人欄位一律不用於顧客識別（決策 0025 補遺第 2 點）：identity_key 的參數
        只認 billing_email／billing_phone，函式簽章本身就是這條規則的落地。"""
        import inspect
        params = list(inspect.signature(identity.identity_key).parameters)
        self.assertEqual(params, ["billing_email", "billing_phone"])


class ConsistencySelfCheckTest(unittest.TestCase):
    def test_self_check_passes_on_current_rules(self):
        identity.consistency_self_check()  # 不該炸

    def test_self_check_catches_broken_normalization(self):
        """規則本身壞掉時要能被抓到——用壞掉的正規化函式驗證自檢真的在檢查東西，
        不是空氣斷言（避免自檢本身變成一條假鐵則）。"""
        original = identity.normalize_phone
        identity.normalize_phone = lambda raw: raw  # 蓄意壞掉：不做任何正規化
        try:
            with self.assertRaises(AssertionError):
                identity.consistency_self_check()
        finally:
            identity.normalize_phone = original


if __name__ == "__main__":
    unittest.main()
