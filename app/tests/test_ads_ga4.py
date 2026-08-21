# -*- coding: utf-8 -*-
"""app/tests/test_ads_ga4.py — 廣告分支票 34：GA4 轉接層＋自動同步＋教學頁。

全程 FakeGA4Client，不發任何真實網路請求（google-analytics-data 套件本機也未安裝，
真實用戶端只在延遲 import 時才會用到，測試從不觸發那一路）。
"""

import atexit
import os
import shutil
import tempfile
import unittest
import uuid
from pathlib import Path

_tmpdir = tempfile.mkdtemp(prefix="brand_os_ads_ga4_")

from fastapi.testclient import TestClient  # noqa: E402

import app.main as main  # noqa: E402
from app.ads import ga4_api  # noqa: E402
from app.ads import ga4_sync  # noqa: E402
from app.brand_intelligence import repository as bi_repo  # noqa: E402
from app.core import settings as coresettings  # noqa: E402



def _cleanup():
    try:
        main.conn.close()
    except Exception:
        pass
    shutil.rmtree(_tmpdir, ignore_errors=True)


atexit.register(_cleanup)

ACTOR = "測試員"
PROPERTY_ID = "123456789"
FAKE_KEY_JSON = '{"client_email": "svc@example.iam.gserviceaccount.com"}'


def _row(source="google", medium="cpc", sessions=100, conversions=5.0, revenue=8000.0):
    return ga4_api.SourceMediumRow(source=source, medium=medium, sessions=sessions,
                                   conversions=conversions, revenue=revenue)


class GA4ApiTest(unittest.TestCase):
    def test_no_credentials_gives_a_plain_message(self):
        with self.assertRaises(ga4_api.GA4ApiError) as ctx:
            ga4_api.GA4Client(None, None)._make_client()
        self.assertIn("還沒有設定", str(ctx.exception))

    def test_missing_property_id_alone_also_refused(self):
        with self.assertRaises(ga4_api.GA4ApiError):
            ga4_api.GA4Client(PROPERTY_ID, None)._make_client()

    def test_fake_client_records_calls(self):
        client = ga4_api.FakeGA4Client(rows=[_row()], purchase_seen=True)
        rows = client.fetch_source_medium("2026-07-01", "2026-07-31")
        seen = client.purchase_event_seen("2026-07-01", "2026-07-31")
        self.assertEqual(len(rows), 1)
        self.assertTrue(seen)
        self.assertEqual(client.calls[0], ("source_medium", "2026-07-01", "2026-07-31"))


class _BaseGA4Test(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(main.app)
        main.conn.execute("DELETE FROM ga4_summary")
        main.conn.execute("DELETE FROM ga4_sync_status")
        # 先子後父：derived_metric 有外鍵指向 performance_snapshot（比照 test_ads_sync.py）
        main.conn.execute("DELETE FROM derived_metric")
        main.conn.execute("DELETE FROM performance_snapshot")
        main.conn.commit()
        # 用 uuid4 不用 hash(self.id())：hash() 受 PYTHONHASHSEED 隨機化，跟 test_ads_sync.py
        # 同前綴同 mod 可能撞名（B4R 收尾包踢出的 flaky 根因）。
        self.brand = bi_repo.create_brand(main.conn, name=f"虛構晨光咖啡{uuid.uuid4().hex[:8]}",
                                          client_name=None, actor=ACTOR)
        self.bid = self.brand["id"]
        coresettings.set_setting(main.conn, ga4_sync.PROPERTY_SETTING, PROPERTY_ID)
        coresettings.set_setting(main.conn, ga4_sync.SERVICE_ACCOUNT_SETTING, FAKE_KEY_JSON)

    def _sync(self, rows=None, purchase_seen=True, error=None, **kwargs):
        client = ga4_api.FakeGA4Client(rows=rows, purchase_seen=purchase_seen, error=error)
        return ga4_sync.sync_brand(main.conn, self.bid, ACTOR, client=client,
                                   today="2026-07-31", **kwargs)


class SyncWriteTest(_BaseGA4Test):
    def test_rows_land_in_ga4_summary_not_performance_snapshot(self):
        result = self._sync(rows=[_row(), _row(source="direct", medium="(none)")])
        self.assertEqual(result.rows, 2)
        self.assertEqual(main.conn.execute(
            "SELECT COUNT(*) c FROM ga4_summary WHERE brand_id = ?", (self.bid,)
        ).fetchone()["c"], 2)
        self.assertEqual(main.conn.execute(
            "SELECT COUNT(*) c FROM performance_snapshot").fetchone()["c"], 0)

    def test_status_records_purchase_event_seen(self):
        result = self._sync(rows=[_row()], purchase_seen=True)
        self.assertTrue(result.purchase_event_seen)
        status = ga4_sync.get_sync_status(main.conn, self.bid)
        self.assertEqual(status["purchase_event_seen"], 1)

    def test_purchase_not_seen_is_reported_honestly(self):
        result = self._sync(rows=[_row()], purchase_seen=False)
        self.assertFalse(result.purchase_event_seen)
        status = ga4_sync.get_sync_status(main.conn, self.bid)
        self.assertEqual(status["purchase_event_seen"], 0)

    def test_empty_rows_still_records_sync_status(self):
        """就算來源／媒介彙總是 0 列，purchase 驗證狀態也要留得住（鐵則 16）。"""
        result = self._sync(rows=[])
        self.assertEqual(result.rows, 0)
        status = ga4_sync.get_sync_status(main.conn, self.bid)
        self.assertIsNotNone(status)
        self.assertEqual(status["row_count"], 0)

    def test_resync_same_period_overwrites_not_duplicates(self):
        self._sync(rows=[_row()])
        self._sync(rows=[_row(), _row(source="direct", medium="(none)")])
        self.assertEqual(main.conn.execute(
            "SELECT COUNT(*) c FROM ga4_summary WHERE brand_id = ?", (self.bid,)
        ).fetchone()["c"], 2)

    def test_error_returns_plain_message_and_writes_nothing(self):
        result = self._sync(error=ga4_api.GA4ApiError("連不上 GA4"))
        self.assertIn("連不上 GA4", result.error)
        self.assertEqual(main.conn.execute(
            "SELECT COUNT(*) c FROM ga4_summary WHERE brand_id = ?", (self.bid,)
        ).fetchone()["c"], 0)

    def test_sync_without_configuration_is_refused_politely(self):
        main.conn.execute("DELETE FROM app_setting WHERE key IN (?, ?)",
                          (ga4_sync.PROPERTY_SETTING, ga4_sync.SERVICE_ACCOUNT_SETTING))
        main.conn.commit()
        self.assertFalse(ga4_sync.is_configured(main.conn))
        result = ga4_sync.sync_brand(main.conn, self.bid, ACTOR,
                                     client=ga4_api.FakeGA4Client(), today="2026-07-31")
        self.assertIn("還沒有設定", result.error)

    def test_on_stage_callback_reports_stages_in_order(self):
        stages = []
        self._sync(rows=[_row()], on_stage=stages.append)
        self.assertEqual(stages, ["connect", "fetch", "save"])


class RouteTest(_BaseGA4Test):
    def test_ga4_result_page_shows_utm_layer_data(self):
        self._sync(rows=[_row(source="google", medium="cpc", sessions=321,
                              conversions=9.0, revenue=54321.0)])
        # 票 T4 脫鉤：改讀舊頁本來就是拿去渲染的那份資料（routes_sync.py 的
        # summary_rows=ga4_sync.latest_summary），驗的還是同一件事：UTM 層資料進得來。
        rows = ga4_sync.latest_summary(main.conn, self.bid)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["source"], "google")
        self.assertEqual(rows[0]["medium"], "cpc")
        self.assertEqual(rows[0]["sessions"], 321)

    def test_sync_progress_page_renders_without_configuration_warning(self):
        main.conn.execute("DELETE FROM app_setting WHERE key IN (?, ?)",
                          (ga4_sync.PROPERTY_SETTING, ga4_sync.SERVICE_ACCOUNT_SETTING))
        main.conn.commit()
        # 票 T4 脫鉤：舊頁用 303＋kind=warn 表達「還沒設定，不給同步」；
        # /api 同一道 is_configured 檢查用 400 表達同一件事。
        resp = self.client.post(f"/api/campaigns/brands/{self.bid}/sync/ga4")
        self.assertEqual(resp.status_code, 400)


if __name__ == "__main__":
    unittest.main()
