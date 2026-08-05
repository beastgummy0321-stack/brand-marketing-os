# -*- coding: utf-8 -*-
"""app/tests/test_ads_auto_sync.py — 票 07-auto-sync：每日自動同步觸發器。

全程 FakeMetaClient／FakeGA4Client，不發任何真實網路請求；時間一律用注入的 `today`，
不讀真實系統時鐘。同步失敗要進打斷佇列（`auto_sync_failed`）；一個品牌的 GA4 失敗
不擋住其他品牌。另外驗證背景排程只掛在 FastAPI `startup` 事件底下——TestClient(app)
（不用 `with` context manager，本 repo 所有測試都是這樣用）不會觸發它，這是防止自動
同步在其他測試檔（設定 Meta／GA4 假連線）裡意外打真實外部 API 的關鍵防線。
"""

import atexit
import os
import shutil
import tempfile
import unittest
from pathlib import Path

_tmpdir = tempfile.mkdtemp(prefix="brand_os_ads_auto_sync_")
os.environ["BRAND_OS_DB"] = str(Path(_tmpdir) / "test.db")
os.environ["BRAND_OS_BACKUP_DIR"] = str(Path(_tmpdir) / "backups")
os.environ["BRAND_OS_UPLOADS"] = str(Path(_tmpdir) / "uploads")

from fastapi.testclient import TestClient  # noqa: E402

import app.main as main  # noqa: E402
from app.ads import auto_sync as ads_auto_sync  # noqa: E402
from app.ads import ga4_api  # noqa: E402
from app.ads import ga4_sync  # noqa: E402
from app.ads import meta_api  # noqa: E402
from app.ads import sync as ads_sync  # noqa: E402
from app.brand_intelligence import repository as bi_repo  # noqa: E402
from app.core import interrupts as core_interrupts  # noqa: E402
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
TODAY = "2026-08-05"


class _BaseAutoSyncTest(unittest.TestCase):
    def setUp(self):
        main.conn.execute("DELETE FROM app_setting")
        main.conn.execute("DELETE FROM interrupt")
        main.conn.execute("DELETE FROM discovered_campaign")
        main.conn.execute("DELETE FROM ga4_sync_status")
        main.conn.commit()
        self.brand = bi_repo.create_brand(
            main.conn, name=f"虛構自動同步茶行{abs(hash(self.id())) % 100000}",
            client_name=None, actor=ACTOR)


class MetaAutoSyncTest(_BaseAutoSyncTest):
    def test_not_configured_skips_without_error(self):
        outcome = ads_auto_sync.run(main.conn, today=TODAY)
        self.assertIsNone(outcome["meta"])
        self.assertEqual(core_interrupts.list_open(main.conn), [])

    def test_configured_calls_sync_account_with_injected_today(self):
        coresettings.set_setting(main.conn, ads_sync.ACCOUNT_SETTING, "act_123")
        coresettings.set_setting(main.conn, ads_sync.TOKEN_SETTING, "fake-token")
        fake = meta_api.FakeMetaClient(campaigns=[], insights=[])
        outcome = ads_auto_sync.run(main.conn, today=TODAY, meta_client=fake)
        self.assertIsNotNone(outcome["meta"])
        self.assertIsNone(outcome["meta"].error)
        # sync_account 沒收到 since 就自己往回推 30 天；驗證真的用了注入的 today，
        # 不是讀系統時鐘（最後一段月度區間的 until 要等於注入的 today——sync_account
        # 把整段期間拆成逐月請求，見 app/ads/sync.py _month_windows）。
        insight_calls = [c for c in fake.calls if c[0] == "insights"]
        self.assertTrue(insight_calls)
        self.assertEqual(insight_calls[-1][3], TODAY)

    def test_sync_failure_enqueues_interrupt(self):
        coresettings.set_setting(main.conn, ads_sync.ACCOUNT_SETTING, "act_123")
        coresettings.set_setting(main.conn, ads_sync.TOKEN_SETTING, "fake-token")
        fake = meta_api.FakeMetaClient(error=meta_api.MetaApiError("模擬 Meta 連線失敗"))
        outcome = ads_auto_sync.run(main.conn, today=TODAY, meta_client=fake)
        self.assertEqual(outcome["meta"].error, "模擬 Meta 連線失敗")
        rows = core_interrupts.list_open(main.conn)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["category"], "auto_sync_failed")

    def test_sync_success_does_not_enqueue_interrupt(self):
        coresettings.set_setting(main.conn, ads_sync.ACCOUNT_SETTING, "act_123")
        coresettings.set_setting(main.conn, ads_sync.TOKEN_SETTING, "fake-token")
        fake = meta_api.FakeMetaClient(campaigns=[], insights=[])
        ads_auto_sync.run(main.conn, today=TODAY, meta_client=fake)
        self.assertEqual(core_interrupts.list_open(main.conn), [])

    def test_repeated_same_day_failure_does_not_duplicate_interrupt(self):
        """去重鍵含日期：同一天重複跑（例如背景執行緒又檢查了一次）只留一筆，
        不會洗版打斷佇列。"""
        coresettings.set_setting(main.conn, ads_sync.ACCOUNT_SETTING, "act_123")
        coresettings.set_setting(main.conn, ads_sync.TOKEN_SETTING, "fake-token")
        fake = meta_api.FakeMetaClient(error=meta_api.MetaApiError("模擬 Meta 連線失敗"))
        ads_auto_sync.run(main.conn, today=TODAY, meta_client=fake)
        ads_auto_sync.run(main.conn, today=TODAY, meta_client=fake)
        self.assertEqual(len(core_interrupts.list_open(main.conn)), 1)


class GA4AutoSyncTest(_BaseAutoSyncTest):
    def test_not_configured_skips_without_error(self):
        outcome = ads_auto_sync.run(main.conn, today=TODAY)
        self.assertEqual(outcome["ga4"], {})

    def test_configured_syncs_each_active_brand(self):
        brand_2 = bi_repo.create_brand(
            main.conn, name=f"虛構自動同步二號店{abs(hash(self.id())) % 100000}",
            client_name=None, actor=ACTOR)
        coresettings.set_setting(main.conn, ga4_sync.PROPERTY_SETTING, "123456789")
        coresettings.set_setting(main.conn, ga4_sync.SERVICE_ACCOUNT_SETTING,
                                 '{"type": "service_account"}')
        fake = ga4_api.FakeGA4Client(rows=[])
        outcome = ads_auto_sync.run(main.conn, today=TODAY, ga4_client=fake)
        # 跨測試共用同一顆 conn，先前測試建的品牌還在（既有慣例不整表清空，見同檔
        # 其他測試），只斷言「這兩個品牌都有跑到」，不要求剛好等於全部 active 品牌。
        self.assertIn(self.brand["id"], outcome["ga4"])
        self.assertIn(brand_2["id"], outcome["ga4"])
        for result in outcome["ga4"].values():
            self.assertIsNone(result.error)

    def test_one_brand_ga4_failure_does_not_block_the_other(self):
        brand_2 = bi_repo.create_brand(
            main.conn, name=f"虛構自動同步三號店{abs(hash(self.id())) % 100000}",
            client_name=None, actor=ACTOR)
        coresettings.set_setting(main.conn, ga4_sync.PROPERTY_SETTING, "123456789")
        coresettings.set_setting(main.conn, ga4_sync.SERVICE_ACCOUNT_SETTING,
                                 '{"type": "service_account"}')
        fake = ga4_api.FakeGA4Client(error=ga4_api.GA4ApiError("模擬 GA4 連線失敗"))
        outcome = ads_auto_sync.run(main.conn, today=TODAY, ga4_client=fake)
        self.assertEqual(outcome["ga4"][self.brand["id"]].error, "模擬 GA4 連線失敗")
        self.assertEqual(outcome["ga4"][brand_2["id"]].error, "模擬 GA4 連線失敗")
        rows = [r for r in core_interrupts.list_open(main.conn)
               if r["brand_id"] in (self.brand["id"], brand_2["id"])]
        self.assertEqual(len(rows), 2)
        for row in rows:
            self.assertEqual(row["category"], "auto_sync_failed")


class AutoSyncScheduleSafetyTest(unittest.TestCase):
    """背景排程只掛在 FastAPI startup 事件底下；TestClient(app)（不用 `with`）不會
    觸發它——這是「測試絕不打真外部 API」的關鍵防線，這裡當場驗證過。"""

    def setUp(self):
        main.conn.execute("DELETE FROM app_setting")
        main.conn.commit()

    def test_testclient_without_context_manager_never_triggers_auto_sync(self):
        coresettings.set_setting(main.conn, ads_sync.ACCOUNT_SETTING, "act_123")
        coresettings.set_setting(main.conn, ads_sync.TOKEN_SETTING, "fake-token")
        main.conn.commit()
        before = main._last_auto_sync_check
        client = TestClient(main.app)  # 刻意不用 with：比照全 repo 既有測試寫法
        client.get("/")
        client.get("/settings")
        self.assertEqual(main._last_auto_sync_check, before)


if __name__ == "__main__":
    unittest.main()
