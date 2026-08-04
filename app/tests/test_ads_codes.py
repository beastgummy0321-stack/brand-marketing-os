# -*- coding: utf-8 -*-
"""app/tests/test_ads_codes.py — 配碼歸因＋交接包擴充＋上線前校驗（GitHub issue #35）。

驗收重點（決策 0025 補遺第 2、3、7 點）：
1. 期別自動配碼：廣告碼／口播碼各一組，字碼期期換碼不重用，重複產生不洗掉既有碼。
2. 上線前逐欄校驗：規劃碼 vs 後台實際設定，不符鎖住**僅該期**的開跑動作，通過留紀錄、不擋路。
3. 訂單依碼匹配歸因：廣告碼→淨歸因；口播碼／手動排除→排除；無碼→自然／未歸因。
4. 用碼暴增但曝光沒動時進打斷佇列（嚴重度：規則警示）。

fixture 一律虛構品牌，嚴禁真實客戶資料（規範第八節）。
"""

import atexit
import os
import shutil
import tempfile
import unittest
from pathlib import Path

_tmpdir = tempfile.mkdtemp(prefix="brand_os_ads_codes_")
os.environ["BRAND_OS_DB"] = str(Path(_tmpdir) / "test.db")
os.environ["BRAND_OS_BACKUP_DIR"] = str(Path(_tmpdir) / "backups")
os.environ["BRAND_OS_UPLOADS"] = str(Path(_tmpdir) / "uploads")

import app.main as main  # noqa: E402
from app.ads import codes as ads_codes  # noqa: E402
from app.ads import handoff as ads_handoff  # noqa: E402
from app.ads import performance as ads_performance  # noqa: E402
from app.ads import repository as ads_repo  # noqa: E402
from app.brand_intelligence import repository as bi_repo  # noqa: E402
from app.core import db as core_db  # noqa: E402
from app.core import interrupts as core_interrupts  # noqa: E402
from app.orders import repository as orders_repo  # noqa: E402

main.reopen_connection()


def _cleanup():
    try:
        main.conn.close()
    except Exception:
        pass
    shutil.rmtree(_tmpdir, ignore_errors=True)


atexit.register(_cleanup)

ACTOR = "測試員"


def _order(order_number, order_date, total_amount, voucher_code=None, order_status="paid",
          refunded_amount=0):
    return {
        "order_number": order_number, "order_date": order_date, "total_amount": total_amount,
        "refunded_amount": refunded_amount, "financial_status": "paid",
        "fulfillment_status": "fulfilled", "order_status": order_status,
        "voucher_code": voucher_code, "billing_email": f"{order_number}@example.test",
        "billing_phone": None, "items": [],
    }


class _BaseCodesTest(unittest.TestCase):
    def setUp(self):
        self.brand_name = f"虛構晨露茶行{abs(hash(self.id())) % 100000}"
        self.brand = bi_repo.create_brand(main.conn, name=self.brand_name,
                                          client_name=None, actor=ACTOR)
        self.bid = self.brand["id"]
        self.cycle = ads_repo.create_cycle(
            main.conn, self.bid, product_ids=[], pain_value=5000, objective="流量",
            actor=ACTOR, start_date="2026-06-01", duration_days=14)
        self.cid = self.cycle["id"]

    def _generate(self, discount_value=10, discount_type="percent"):
        return ads_codes.generate_codes(
            main.conn, self.bid, self.cid, discount_type=discount_type,
            discount_value=discount_value, actor=ACTOR)


class GenerateCodesTest(_BaseCodesTest):
    def test_generates_one_ad_code_and_one_word_of_mouth_code(self):
        codes = self._generate()
        sources = sorted(c["source_type"] for c in codes)
        self.assertEqual(sources, ["ad", "word_of_mouth"])
        ad = next(c for c in codes if c["source_type"] == "ad")
        wom = next(c for c in codes if c["source_type"] == "word_of_mouth")
        self.assertNotEqual(ad["code"], wom["code"])

    def test_short_validity_defaults_to_cycle_dates(self):
        codes = self._generate()
        for c in codes:
            self.assertEqual(c["valid_from"], self.cycle["start_date"])
            self.assertEqual(c["valid_to"], self.cycle["end_date"])

    def test_usage_limit_defaults_to_conservative_constant(self):
        codes = self._generate()
        for c in codes:
            self.assertEqual(c["usage_limit"], ads_codes.DEFAULT_USAGE_LIMIT)

    def test_regenerating_does_not_change_existing_codes(self):
        """碼一旦配出去可能已經在 EasyStore 後台建好，重新產生不能中途換碼字。"""
        first = self._generate()
        first_codes = {c["source_type"]: c["code"] for c in first}
        second = self._generate(discount_value=20)  # 折數不同也不該洗掉既有碼
        second_codes = {c["source_type"]: c["code"] for c in second}
        self.assertEqual(first_codes, second_codes)

    def test_codes_never_reused_across_cycles(self):
        """期期換碼不重用：不同檔期各自的碼字不同（結構性保證，非查重）。"""
        codes_a = self._generate()
        other_cycle = ads_repo.create_cycle(
            main.conn, self.bid, product_ids=[], pain_value=5000, objective="流量",
            actor=ACTOR, start_date="2026-07-01", duration_days=14)
        codes_b = ads_codes.generate_codes(
            main.conn, self.bid, other_cycle["id"], discount_type="percent",
            discount_value=10, actor=ACTOR)
        self.assertEqual(
            {c["code"] for c in codes_a} & {c["code"] for c in codes_b}, set())

    def test_discount_value_must_be_positive(self):
        with self.assertRaises(ValueError):
            ads_codes.generate_codes(main.conn, self.bid, self.cid, discount_type="percent",
                                     discount_value=0, actor=ACTOR)


class VerificationTest(_BaseCodesTest):
    def _actual_matching(self, codes):
        return {c["source_type"]: {
            "code": c["code"], "discount_type": c["discount_type"],
            "discount_value": c["discount_value"], "usage_limit": c["usage_limit"],
            "valid_from": c["valid_from"], "valid_to": c["valid_to"],
        } for c in codes}

    def test_matching_values_pass_and_leave_a_record(self):
        codes = self._generate()
        result = ads_codes.verify(main.conn, self.bid, self.cid,
                                  actual=self._actual_matching(codes), actor=ACTOR)
        self.assertTrue(result["passed"])
        self.assertEqual(result["mismatches"], [])
        row = main.conn.execute(
            "SELECT * FROM cycle_code_verification WHERE campaign_cycle_id = ?",
            (self.cid,)).fetchone()
        self.assertIsNotNone(row)
        self.assertEqual(row["passed"], 1)
        self.assertEqual(row["checked_by"], ACTOR)

    def test_mismatched_discount_is_caught_and_reported(self):
        codes = self._generate()
        actual = self._actual_matching(codes)
        actual["ad"]["discount_value"] = 99
        result = ads_codes.verify(main.conn, self.bid, self.cid, actual=actual, actor=ACTOR)
        self.assertFalse(result["passed"])
        self.assertTrue(any("折數不符" in m for m in result["mismatches"]))

    def test_mismatch_locks_only_this_cycle_activation(self):
        codes = self._generate()
        actual = self._actual_matching(codes)
        actual["ad"]["code"] = "WRONGCODE"
        ads_codes.verify(main.conn, self.bid, self.cid, actual=actual, actor=ACTOR)
        self.assertIsNotNone(ads_codes.is_activation_locked(main.conn, self.bid, self.cid))

        other_cycle = ads_repo.create_cycle(
            main.conn, self.bid, product_ids=[], pain_value=5000, objective="流量",
            actor=ACTOR, start_date="2026-07-01", duration_days=14)
        self.assertIsNone(
            ads_codes.is_activation_locked(main.conn, self.bid, other_cycle["id"]))

    def test_passing_after_a_failure_unlocks(self):
        codes = self._generate()
        actual = self._actual_matching(codes)
        actual["ad"]["code"] = "WRONGCODE"
        ads_codes.verify(main.conn, self.bid, self.cid, actual=actual, actor=ACTOR)
        self.assertIsNotNone(ads_codes.is_activation_locked(main.conn, self.bid, self.cid))

        ads_codes.verify(main.conn, self.bid, self.cid,
                         actual=self._actual_matching(codes), actor=ACTOR)
        self.assertIsNone(ads_codes.is_activation_locked(main.conn, self.bid, self.cid))

    def test_never_verified_does_not_lock(self):
        """校驗本身可跳過（老手暗門）：從沒校驗過不算「不符」，不擋路。"""
        self._generate()
        self.assertIsNone(ads_codes.is_activation_locked(main.conn, self.bid, self.cid))


class ActivationLockIntegrationTest(_BaseCodesTest):
    def _insert_package(self):
        pid = core_db.new_id("pkg")
        main.conn.execute(
            "INSERT INTO publishing_package (id, brand_id, campaign_cycle_id, campaign_name,"
            " adset_name, ad_name, destination_url, utm_json, status, created_at)"
            " VALUES (?, ?, ?, 'c', 'a', 'ad', 'https://example.test', '{}', 'ready', ?)",
            (pid, self.bid, self.cid, core_db.now_iso()),
        )
        main.conn.commit()
        return pid

    def test_authorize_and_map_is_blocked_when_codes_do_not_match(self):
        codes = self._generate()
        actual = {c["source_type"]: {
            "code": "WRONGCODE", "discount_type": c["discount_type"],
            "discount_value": c["discount_value"], "usage_limit": c["usage_limit"],
            "valid_from": c["valid_from"], "valid_to": c["valid_to"],
        } for c in codes}
        ads_codes.verify(main.conn, self.bid, self.cid, actual=actual, actor=ACTOR)

        package_id = self._insert_package()
        with self.assertRaises(ValueError) as ctx:
            ads_handoff.authorize_and_map(
                main.conn, self.bid, self.cid, package_id,
                meta_ids={"meta_campaign_id": "123"}, actor=ACTOR)
        self.assertIn("校驗", str(ctx.exception))
        self.assertIsNone(main.conn.execute(
            "SELECT 1 FROM activation_authorization WHERE scope_ref = ?", (package_id,)
        ).fetchone())

    def test_authorize_and_map_succeeds_without_verification(self):
        """校驗可跳過，沒校驗過不擋開跑（不擋路原則）。"""
        package_id = self._insert_package()
        result = ads_handoff.authorize_and_map(
            main.conn, self.bid, self.cid, package_id,
            meta_ids={"meta_campaign_id": "123"}, actor=ACTOR)
        self.assertIn("authorization_id", result)


class AttributionTest(_BaseCodesTest):
    def test_three_way_classification_and_revenue(self):
        codes = self._generate()
        ad_code = next(c["code"] for c in codes if c["source_type"] == "ad")
        wom_code = next(c["code"] for c in codes if c["source_type"] == "word_of_mouth")

        rows = [
            _order("O1", "2026-06-02", 1000, voucher_code=ad_code),
            _order("O2", "2026-06-03", 500, voucher_code=ad_code, refunded_amount=100),
            _order("O3", "2026-06-04", 300, voucher_code=wom_code),
            _order("O4", "2026-06-05", 200, voucher_code=None),
            _order("O5", "2026-06-06", 400, voucher_code="SOME-OTHER-PROMO"),
        ]
        orders_repo.save_orders(main.conn, self.bid, rows, source="easystore_xlsx", actor=ACTOR)

        summary = ads_codes.attribution_summary(main.conn, self.bid, self.cid)
        self.assertEqual(summary["gross"]["count"], 2)
        self.assertEqual(summary["net"]["count"], 2)
        self.assertEqual(summary["net"]["net_revenue"], 1000 + (500 - 100))
        self.assertEqual(summary["excluded"]["count"], 1)
        self.assertEqual(summary["natural"]["count"], 2)  # 無碼一筆＋非本期配碼一筆

    def test_manual_exclude_moves_order_from_net_to_excluded_but_stays_in_gross(self):
        codes = self._generate()
        ad_code = next(c["code"] for c in codes if c["source_type"] == "ad")
        orders_repo.save_orders(
            main.conn, self.bid, [_order("O1", "2026-06-02", 1000, voucher_code=ad_code)],
            source="easystore_xlsx", actor=ACTOR)
        order_id = main.conn.execute(
            "SELECT id FROM order_record WHERE brand_id = ? AND order_number = 'O1'",
            (self.bid,)).fetchone()["id"]

        before = ads_codes.attribution_summary(main.conn, self.bid, self.cid)
        self.assertEqual(before["net"]["count"], 1)
        self.assertEqual(before["excluded"]["count"], 0)

        orders_repo.set_attribution_override(main.conn, self.bid, order_id, True, actor=ACTOR)
        after = ads_codes.attribution_summary(main.conn, self.bid, self.cid)
        self.assertEqual(after["gross"]["count"], 1, "毛歸因含存疑，手動排除的訂單仍留著供對照")
        self.assertEqual(after["net"]["count"], 0)
        self.assertEqual(after["excluded"]["count"], 1)

    def test_voided_orders_are_not_counted(self):
        codes = self._generate()
        ad_code = next(c["code"] for c in codes if c["source_type"] == "ad")
        orders_repo.save_orders(
            main.conn, self.bid,
            [_order("O1", "2026-06-02", 1000, voucher_code=ad_code, order_status="cancelled")],
            source="easystore_xlsx", actor=ACTOR)
        summary = ads_codes.attribution_summary(main.conn, self.bid, self.cid)
        self.assertEqual(summary["gross"]["count"], 0)
        self.assertEqual(summary["natural"]["count"], 0)


class SurgeAlertTest(_BaseCodesTest):
    def _use_code(self, n, ad_code):
        rows = [_order(f"S{i}", "2026-06-02", 100, voucher_code=ad_code) for i in range(n)]
        orders_repo.save_orders(main.conn, self.bid, rows, source="easystore_xlsx", actor=ACTOR)

    def test_high_usage_with_no_impressions_triggers_rule_warning(self):
        codes = self._generate()
        ad_code = next(c["code"] for c in codes if c["source_type"] == "ad")
        ads_repo.update_cycle_status(main.conn, self.bid, self.cid, status="LIVE", actor=ACTOR)
        self._use_code(ads_codes.MIN_USAGE_FOR_SURGE_CHECK, ad_code)

        interrupt_id = ads_codes.check_surge(main.conn, self.bid, self.cid)
        self.assertIsNotNone(interrupt_id)
        row = main.conn.execute("SELECT * FROM interrupt WHERE id = ?", (interrupt_id,)).fetchone()
        self.assertEqual(row["severity"], "rule_warning")
        self.assertEqual(row["category"], "code_surge_alert")

        # 去重：再檢查一次不會重複排
        self.assertIsNone(ads_codes.check_surge(main.conn, self.bid, self.cid))

    def test_usage_in_line_with_impressions_does_not_trigger(self):
        codes = self._generate()
        ad_code = next(c["code"] for c in codes if c["source_type"] == "ad")
        ads_repo.update_cycle_status(main.conn, self.bid, self.cid, status="LIVE", actor=ACTOR)
        self._use_code(ads_codes.MIN_USAGE_FOR_SURGE_CHECK, ad_code)
        ads_performance.import_manual(
            main.conn, self.bid, self.cid,
            {"spend": 1000, "impressions": 100000, "clicks": 500, "conversions": 5,
             "revenue": 1000}, actor=ACTOR)

        self.assertIsNone(ads_codes.check_surge(main.conn, self.bid, self.cid))

    def test_below_minimum_sample_does_not_trigger(self):
        codes = self._generate()
        ad_code = next(c["code"] for c in codes if c["source_type"] == "ad")
        ads_repo.update_cycle_status(main.conn, self.bid, self.cid, status="LIVE", actor=ACTOR)
        self._use_code(ads_codes.MIN_USAGE_FOR_SURGE_CHECK - 1, ad_code)
        self.assertIsNone(ads_codes.check_surge(main.conn, self.bid, self.cid))


class CascadeDeleteTest(_BaseCodesTest):
    def test_codes_and_verification_are_removed_with_the_cycle(self):
        codes = self._generate()
        ads_codes.verify(main.conn, self.bid, self.cid,
                         actual={c["source_type"]: {
                             "code": c["code"], "discount_type": c["discount_type"],
                             "discount_value": c["discount_value"], "usage_limit": c["usage_limit"],
                             "valid_from": c["valid_from"], "valid_to": c["valid_to"],
                         } for c in codes}, actor=ACTOR)

        ads_repo.set_cycle_archived(main.conn, self.bid, self.cid, archived=True, actor=ACTOR)
        ads_repo.delete_cycle(main.conn, self.bid, self.cid, actor=ACTOR)

        self.assertEqual(main.conn.execute(
            "SELECT COUNT(*) c FROM cycle_voucher_code WHERE campaign_cycle_id = ?",
            (self.cid,)).fetchone()["c"], 0)
        self.assertEqual(main.conn.execute(
            "SELECT COUNT(*) c FROM cycle_code_verification WHERE campaign_cycle_id = ?",
            (self.cid,)).fetchone()["c"], 0)


if __name__ == "__main__":
    unittest.main()
