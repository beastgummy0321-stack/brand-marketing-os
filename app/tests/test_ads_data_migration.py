# -*- coding: utf-8 -*-
"""app/tests/test_ads_data_migration.py — F7：把舊資料搬進來（決策 0039 第一節，GitHub #66）。

四格狀態、部分基線小結、成熟門檻報告全部從既有資料查詢推導（app/ads/data_onboarding.py），
這裡驗證：①路由沒被 `/ads/{cycle_id}` 萬用路由吃掉 ②空狀態誠實顯示 ③每格完成狀態
（not_started／in_progress／done）判定正確 ④成熟門檻表逐項數字與「還缺什麼」
⑤connections 頁新增第 4 張入口卡＋容量規則 ⑥前朝教訓訪談 `next` 跳轉參數。

fixture 一律虛構品牌，嚴禁真實品牌名稱。
"""

import atexit
import os
import shutil
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path

_tmpdir = tempfile.mkdtemp(prefix="brand_os_ads_data_migration_")

from fastapi.testclient import TestClient  # noqa: E402

import pytest  # noqa: E402

import app.main as main  # noqa: E402
from app.ads import data_onboarding  # noqa: E402
from app.ads import performance as ads_performance  # noqa: E402
from app.brand_intelligence import repository as bi_repo  # noqa: E402
from app.core import db as coredb  # noqa: E402
from app.core.db import new_id, now_utc  # noqa: E402

# BUG app/ads/performance.py:613 — `(row["date_range_start"] or "")[:7]` slices a
# datetime.date object (psycopg auto-decodes `date` columns to `date`, not str),
# always TypeError. Same BUG the orders group already found.
_BUG_DATE_SLICE = pytest.mark.xfail(
    strict=True,
    reason='BUG app/ads/performance.py:613 — (row["date_range_start"] or "")[:7] '
           "slices a datetime.date object, not a str — TypeError",
)


ACTOR = "測試員"
TODAY = "2026-08-04"


def _cleanup():
    try:
        main.conn.close()
    except Exception:
        pass
    shutil.rmtree(_tmpdir, ignore_errors=True)


atexit.register(_cleanup)


def _insert_order(brand_id: str, order_date: str):
    main.conn.execute(
        "INSERT INTO order_record (id, org_id, brand_id, order_number, order_date,"
        " total_amount, refunded_amount, source, created_at, updated_at) VALUES"
        " (%s, %s, %s, %s, %s, 500, 0, 'easystore_xlsx', %s, %s)",
        (new_id("ord"), coredb.DEV_ORG_ID, brand_id, new_id("on"),
         date.fromisoformat(order_date), now_utc(), now_utc()),
    )
    main.conn.commit()


def _insert_ga4_summary(brand_id: str, start: str, end: str):
    ts = now_utc()
    main.conn.execute(
        "INSERT INTO ga4_summary (id, org_id, brand_id, date_range_start, date_range_end,"
        " source, medium, sessions, conversions, revenue, synced_at, created_at)"
        " VALUES (%s, %s, %s, %s, %s, 'google', 'organic', 100, 5, 1000, %s, %s)",
        (new_id("ga4"), coredb.DEV_ORG_ID, brand_id, date.fromisoformat(start),
         date.fromisoformat(end), ts, ts),
    )
    main.conn.commit()


def _import_brand_level_meta(brand_id: str, *, clicks: int, conversions: int, spend: float):
    rows = [{"date_start": TODAY, "date_stop": TODAY, "clicks": clicks,
             "conversions": conversions, "spend": spend, "impressions": clicks * 10}]
    ads_performance.import_rows(main.conn, brand_id, None, rows, source="csv", actor=ACTOR,
                                today=TODAY)


class _BaseTest(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(main.app)
        self.brand = bi_repo.create_brand(main.conn, name=f"虛構搬家茶行{self.id()[-8:]}",
                                          client_name=None, actor=ACTOR)
        self.bid = self.brand["id"]

    def _onboarding(self):
        """同一份四格清單／完成度／成熟門檻，改從 React 新殼用的 JSON 端點取。"""
        resp = self.client.get(f"/api/campaigns/brands/{self.bid}/data-onboarding")
        self.assertEqual(resp.status_code, 200)
        return resp.json()["data"]


class EmptyStateTest(_BaseTest):
    def test_nothing_done_shows_not_started_and_empty_maturity(self):
        data = self._onboarding()
        required = [i for i in data["checklist"] if not i["optional"]]
        # 「完成度：0 / 3」
        self.assertEqual((data["progress"]["done"], data["progress"]["total"]), (0, 3))
        # 三格都掛「尚未開始」徽章
        self.assertEqual([i["badge_label"] for i in required], ["尚未開始"] * 3)
        # 「建議下一步：Meta 認領」
        self.assertEqual(data["progress"]["next_item"]["label"], "Meta 認領")
        # 一格資料都沒有＝成熟門檻整段換成「還沒有足夠資料可以判斷」空狀態（頁面 any_data 條件）
        self.assertFalse(any(i["has_data"] for i in required))

    def test_each_tile_has_independent_action_link_no_blocking(self):
        """①四格各自可獨立完成／跳過，任一格未完成不阻擋其他格操作。"""
        urls = [i["action_url"] for i in self._onboarding()["checklist"]]
        self.assertIn("/app/settings", urls)
        self.assertIn(f"/app/brands/{self.bid}/orders", urls)
        self.assertIn(f"/app/brands/{self.bid}/campaigns", urls)


class TileStatusTest(_BaseTest):
    """四格狀態判定：not_started／in_progress／done 三態，直接呼叫 data_onboarding 驗證，
    比 HTTP 層更精準地鎖定各邊界（不用湊出整頁字串）。"""

    def test_order_backfill_not_started_without_any_order(self):
        checklist = data_onboarding.build_checklist(main.conn, self.bid, today=TODAY)
        order_tile = next(i for i in checklist if i["key"] == "order_backfill")
        self.assertEqual(order_tile["status"], "not_started")
        self.assertFalse(order_tile["has_data"])
        self.assertIsNone(order_tile["baseline"])

    def test_order_backfill_in_progress_below_180_days(self):
        recent = (date.fromisoformat(TODAY) - timedelta(days=50)).isoformat()
        _insert_order(self.bid, recent)
        checklist = data_onboarding.build_checklist(main.conn, self.bid, today=TODAY)
        order_tile = next(i for i in checklist if i["key"] == "order_backfill")
        self.assertEqual(order_tile["status"], "in_progress")
        self.assertIsNotNone(order_tile["baseline"])

    def test_order_backfill_done_at_180_days_or_more(self):
        old = (date.fromisoformat(TODAY) - timedelta(days=200)).isoformat()
        _insert_order(self.bid, old)
        checklist = data_onboarding.build_checklist(main.conn, self.bid, today=TODAY)
        order_tile = next(i for i in checklist if i["key"] == "order_backfill")
        self.assertEqual(order_tile["status"], "done")

    def test_ga4_backfill_done_when_coverage_reaches_three_months(self):
        start = (date.fromisoformat(TODAY) - timedelta(days=100)).isoformat()
        _insert_ga4_summary(self.bid, start, TODAY)
        checklist = data_onboarding.build_checklist(main.conn, self.bid, today=TODAY)
        ga4_tile = next(i for i in checklist if i["key"] == "ga4_backfill")
        self.assertEqual(ga4_tile["status"], "done")

    def test_ga4_backfill_in_progress_below_three_months(self):
        start = (date.fromisoformat(TODAY) - timedelta(days=40)).isoformat()
        _insert_ga4_summary(self.bid, start, TODAY)
        checklist = data_onboarding.build_checklist(main.conn, self.bid, today=TODAY)
        ga4_tile = next(i for i in checklist if i["key"] == "ga4_backfill")
        self.assertEqual(ga4_tile["status"], "in_progress")

    @_BUG_DATE_SLICE
    def test_meta_claim_in_progress_below_statistical_sample(self):
        _import_brand_level_meta(self.bid, clicks=100, conversions=5, spend=1000)
        checklist = data_onboarding.build_checklist(main.conn, self.bid, today=TODAY)
        meta_tile = next(i for i in checklist if i["key"] == "meta_claim")
        self.assertEqual(meta_tile["status"], "in_progress")
        self.assertIsNotNone(meta_tile["baseline"])

    @_BUG_DATE_SLICE
    def test_meta_claim_done_when_sample_reaches_statistical_tier(self):
        # cvr = 900/4500 = 20%，門檻查表 baseline_20pct 預設 4000，4500 ≥ 4000 → 統計等級
        _import_brand_level_meta(self.bid, clicks=4500, conversions=900, spend=5000)
        checklist = data_onboarding.build_checklist(main.conn, self.bid, today=TODAY)
        meta_tile = next(i for i in checklist if i["key"] == "meta_claim")
        self.assertEqual(meta_tile["status"], "done")

    def test_interview_excluded_from_completion_denominator(self):
        checklist = data_onboarding.build_checklist(main.conn, self.bid, today=TODAY)
        progress = data_onboarding.completion(checklist)
        self.assertEqual(progress["total"], 3)  # 訪談不算進分母
        interview_tile = next(i for i in checklist if i["key"] == "interview")
        self.assertTrue(interview_tile["optional"])


class MaturityReportTest(_BaseTest):
    def test_gap_text_present_when_not_met(self):
        rows = data_onboarding.maturity_report(main.conn, self.bid, today=TODAY)
        order_row = next(r for r in rows if r["label"] == "訂單史天數")
        self.assertFalse(order_row["met"])
        self.assertIn("訂單回填", order_row["gap"])

    def test_order_history_gate_met_and_page_shows_it(self):
        old = (date.fromisoformat(TODAY) - timedelta(days=200)).isoformat()
        _insert_order(self.bid, old)
        rows = data_onboarding.maturity_report(main.conn, self.bid, today=TODAY)
        order_row = next(r for r in rows if r["label"] == "訂單史天數")
        self.assertTrue(order_row["met"])
        self.assertIsNone(order_row["gap"])
        self.assertEqual(order_row["value_label"], "200 天")

        maturity = self._onboarding()["maturity"]
        self.assertTrue(any(r["met"] for r in maturity["rows"]))  # 有列掛「已達標」
        # 還沒開始的格繼續誠實顯示未達標，不因為訂單史過了就整批蓋成已成熟
        self.assertTrue(any(not r["met"] for r in maturity["rows"]))
        self.assertFalse(maturity["all_met"])


if __name__ == "__main__":
    unittest.main()
