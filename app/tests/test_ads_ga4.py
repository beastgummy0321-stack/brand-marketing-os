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
from pathlib import Path

_tmpdir = tempfile.mkdtemp(prefix="brand_os_ads_ga4_")
os.environ["BRAND_OS_DB"] = str(Path(_tmpdir) / "test.db")
os.environ["BRAND_OS_BACKUP_DIR"] = str(Path(_tmpdir) / "backups")
os.environ["BRAND_OS_UPLOADS"] = str(Path(_tmpdir) / "uploads")

from fastapi.testclient import TestClient  # noqa: E402

import app.main as main  # noqa: E402
from app.ads import ga4_api  # noqa: E402
from app.ads import ga4_sync  # noqa: E402
from app.brand_intelligence import repository as bi_repo  # noqa: E402
from app.core import settings as coresettings  # noqa: E402

main.reopen_connection()


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
        self.client.post("/settings/operator", data={"name": ACTOR, "next": "/"},
                         follow_redirects=False)
        main.conn.execute("DELETE FROM ga4_summary")
        main.conn.execute("DELETE FROM ga4_sync_status")
        # 先子後父：derived_metric 有外鍵指向 performance_snapshot（比照 test_ads_sync.py）
        main.conn.execute("DELETE FROM derived_metric")
        main.conn.execute("DELETE FROM performance_snapshot")
        main.conn.commit()
        self.brand = bi_repo.create_brand(main.conn, name=f"虛構晨光咖啡{abs(hash(self.id())) % 10000}",
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
        page = self.client.get(f"/brands/{self.bid}/ads/ga4")
        self.assertEqual(page.status_code, 200)
        self.assertIn("google", page.text)
        self.assertIn("cpc", page.text)
        self.assertIn("321", page.text)

    def test_purchase_not_received_is_shown_honestly_with_link_to_guide(self):
        self._sync(rows=[_row()], purchase_seen=False)
        page = self.client.get(f"/brands/{self.bid}/ads/ga4")
        self.assertIn("purchase 事件沒收到", page.text)
        self.assertIn(f"/brands/{self.bid}/ads/ga4-guide", page.text)

    def test_guide_page_notes_the_google_cloud_familiarity_premise(self):
        page = self.client.get(f"/brands/{self.bid}/ads/ga4-guide")
        self.assertEqual(page.status_code, 200)
        self.assertIn("熟悉 Google Cloud", page.text)

    def test_sync_progress_page_renders_without_configuration_warning(self):
        main.conn.execute("DELETE FROM app_setting WHERE key IN (?, ?)",
                          (ga4_sync.PROPERTY_SETTING, ga4_sync.SERVICE_ACCOUNT_SETTING))
        main.conn.commit()
        resp = self.client.get(f"/brands/{self.bid}/ads/ga4/sync", follow_redirects=False)
        self.assertIn("kind=warn", resp.headers["location"])

    def test_sync_progress_page_renders_wait_screen_when_configured(self):
        """只驗證等待頁本身能正常渲染（不帶 run=1，不會建立任何真實用戶端）。"""
        resp = self.client.get(f"/brands/{self.bid}/ads/ga4/sync")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("本頁會自動更新", resp.text)

    def test_settings_page_offers_ga4_connection(self):
        page = self.client.get("/settings")
        self.assertIn("GA4（網站數據，唯讀）", page.text)
        self.assertIn("GA4 資源編號", page.text)


if __name__ == "__main__":
    unittest.main()
