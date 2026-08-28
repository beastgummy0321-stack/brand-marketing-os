"""app/tests/test_ads_auto_sync.py — 票 07-auto-sync：每日自動同步觸發器。

全程 FakeMetaClient／FakeGA4Client，不發任何真實網路請求；時間一律用注入的 `today`，
不讀真實系統時鐘。同步失敗要進打斷佇列（`auto_sync_failed`）；一個品牌的 GA4 失敗
不擋住其他品牌。另外驗證背景排程只掛在 FastAPI `startup` 事件底下——TestClient(app)
（不用 `with` context manager，本 repo 所有測試都是這樣用）不會觸發它，這是防止自動
同步在其他測試檔（設定 Meta／GA4 假連線）裡意外打真實外部 API 的關鍵防線。
"""

import unittest
from datetime import UTC, datetime, timedelta
from unittest import mock

from fastapi.testclient import TestClient

import app.main as main
from app.ads import auto_sync as ads_auto_sync
from app.ads import ga4_api, ga4_sync, meta_api
from app.ads import sync as ads_sync
from app.brand_intelligence import repository as bi_repo
from app.core import db
from app.core import interrupts as core_interrupts
from app.core import settings as coresettings

ACTOR = "測試員"
TODAY = "2026-08-05"
NO_NETWORK = lambda _url: True




class _BaseAutoSyncTest(unittest.TestCase):
    def setUp(self):
        main.conn.execute("DELETE FROM app_setting")
        main.conn.execute("DELETE FROM interrupt")
        main.conn.execute("DELETE FROM discovered_campaign")
        main.conn.execute("DELETE FROM ga4_sync_status")
        main.conn.commit()
        self.brand = bi_repo.create_brand(
            main.conn, name=f"虛構自動同步茶行{abs(hash(self.id())) % 100000}",
            client_name=None, actor=ACTOR, org_id=db.DEV_ORG_ID)


class MetaAutoSyncTest(_BaseAutoSyncTest):
    def test_not_configured_skips_without_error(self):
        outcome = ads_auto_sync.run(main.conn, today=TODAY, url_probe=NO_NETWORK)
        self.assertIsNone(outcome["meta"])
        self.assertEqual(core_interrupts.list_open(main.conn), [])

    def test_configured_calls_sync_account_with_injected_today(self):
        coresettings.set_setting(main.conn, ads_sync.ACCOUNT_SETTING, "act_123", org_id=db.DEV_ORG_ID)
        coresettings.set_setting(main.conn, ads_sync.TOKEN_SETTING, "fake-token", org_id=db.DEV_ORG_ID)
        fake = meta_api.FakeMetaClient(campaigns=[], insights=[])
        outcome = ads_auto_sync.run(
            main.conn, today=TODAY, meta_client=fake, url_probe=NO_NETWORK)
        self.assertIsNotNone(outcome["meta"])
        self.assertIsNone(outcome["meta"].error)
        # sync_account 沒收到 since 就自己往回推 30 天；驗證真的用了注入的 today，
        # 不是讀系統時鐘（最後一段月度區間的 until 要等於注入的 today——sync_account
        # 把整段期間拆成逐月請求，見 app/ads/sync.py _month_windows）。
        insight_calls = [c for c in fake.calls if c[0] == "insights"]
        self.assertTrue(insight_calls)
        self.assertEqual(insight_calls[-1][3], TODAY)

    def test_sync_failure_enqueues_interrupt(self):
        coresettings.set_setting(main.conn, ads_sync.ACCOUNT_SETTING, "act_123", org_id=db.DEV_ORG_ID)
        coresettings.set_setting(main.conn, ads_sync.TOKEN_SETTING, "fake-token", org_id=db.DEV_ORG_ID)
        fake = meta_api.FakeMetaClient(error=meta_api.MetaApiError("模擬 Meta 連線失敗"))
        outcome = ads_auto_sync.run(
            main.conn, today=TODAY, meta_client=fake, url_probe=NO_NETWORK)
        self.assertEqual(outcome["meta"].error, "模擬 Meta 連線失敗")
        rows = core_interrupts.list_open(main.conn)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["category"], "auto_sync_failed")

    def test_sync_success_does_not_enqueue_interrupt(self):
        coresettings.set_setting(main.conn, ads_sync.ACCOUNT_SETTING, "act_123", org_id=db.DEV_ORG_ID)
        coresettings.set_setting(main.conn, ads_sync.TOKEN_SETTING, "fake-token", org_id=db.DEV_ORG_ID)
        fake = meta_api.FakeMetaClient(campaigns=[], insights=[])
        ads_auto_sync.run(main.conn, today=TODAY, meta_client=fake, url_probe=NO_NETWORK)
        self.assertEqual(core_interrupts.list_open(main.conn), [])

    def test_repeated_same_day_failure_does_not_duplicate_interrupt(self):
        """去重鍵含日期：同一天重複跑（例如背景執行緒又檢查了一次）只留一筆，
        不會洗版打斷佇列。"""
        coresettings.set_setting(main.conn, ads_sync.ACCOUNT_SETTING, "act_123", org_id=db.DEV_ORG_ID)
        coresettings.set_setting(main.conn, ads_sync.TOKEN_SETTING, "fake-token", org_id=db.DEV_ORG_ID)
        fake = meta_api.FakeMetaClient(error=meta_api.MetaApiError("模擬 Meta 連線失敗"))
        ads_auto_sync.run(main.conn, today=TODAY, meta_client=fake, url_probe=NO_NETWORK)
        ads_auto_sync.run(main.conn, today=TODAY, meta_client=fake, url_probe=NO_NETWORK)
        self.assertEqual(len(core_interrupts.list_open(main.conn)), 1)


class GA4AutoSyncTest(_BaseAutoSyncTest):
    def test_not_configured_skips_without_error(self):
        outcome = ads_auto_sync.run(main.conn, today=TODAY, url_probe=NO_NETWORK)
        self.assertEqual(outcome["ga4"], {})

    def test_configured_syncs_each_active_brand(self):
        brand_2 = bi_repo.create_brand(
            main.conn, name=f"虛構自動同步二號店{abs(hash(self.id())) % 100000}",
            client_name=None, actor=ACTOR, org_id=db.DEV_ORG_ID)
        coresettings.set_setting(main.conn, ga4_sync.PROPERTY_SETTING, "123456789", org_id=db.DEV_ORG_ID)
        coresettings.set_setting(main.conn, ga4_sync.SERVICE_ACCOUNT_SETTING,
                                 '{"type": "service_account"}', org_id=db.DEV_ORG_ID)
        fake = ga4_api.FakeGA4Client(rows=[])
        outcome = ads_auto_sync.run(
            main.conn, today=TODAY, ga4_client=fake, url_probe=NO_NETWORK)
        # 跨測試共用同一顆 conn，先前測試建的品牌還在（既有慣例不整表清空，見同檔
        # 其他測試），只斷言「這兩個品牌都有跑到」，不要求剛好等於全部 active 品牌。
        self.assertIn(self.brand["id"], outcome["ga4"])
        self.assertIn(brand_2["id"], outcome["ga4"])
        for result in outcome["ga4"].values():
            self.assertIsNone(result.error)

    def test_one_brand_ga4_failure_does_not_block_the_other(self):
        brand_2 = bi_repo.create_brand(
            main.conn, name=f"虛構自動同步三號店{abs(hash(self.id())) % 100000}",
            client_name=None, actor=ACTOR, org_id=db.DEV_ORG_ID)
        coresettings.set_setting(main.conn, ga4_sync.PROPERTY_SETTING, "123456789", org_id=db.DEV_ORG_ID)
        coresettings.set_setting(main.conn, ga4_sync.SERVICE_ACCOUNT_SETTING,
                                 '{"type": "service_account"}', org_id=db.DEV_ORG_ID)
        fake = ga4_api.FakeGA4Client(error=ga4_api.GA4ApiError("模擬 GA4 連線失敗"))
        outcome = ads_auto_sync.run(
            main.conn, today=TODAY, ga4_client=fake, url_probe=NO_NETWORK)
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
        coresettings.set_setting(main.conn, ads_sync.ACCOUNT_SETTING, "act_123", org_id=db.DEV_ORG_ID)
        coresettings.set_setting(main.conn, ads_sync.TOKEN_SETTING, "fake-token", org_id=db.DEV_ORG_ID)
        main.conn.commit()
        before = main._last_auto_sync_check
        TestClient(main.app)  # 不進 context manager，不觸發 startup 排程
        self.assertEqual(main._last_auto_sync_check, before)

    def test_live_cycle_runs_every_four_hours(self):
        brand = bi_repo.create_brand(main.conn, name="虛構四小時排程", client_name=None, actor=ACTOR, org_id=db.DEV_ORG_ID)
        ts = db.now_utc()
        main.conn.execute(
            "INSERT INTO campaign_cycle (id, org_id, brand_id, product_scope_json, objective,"
            " currency, start_date, end_date, channels_json, status, phase, created_at,"
            " updated_at) VALUES (%s, %s, %s, '[]', 'sales', 'TWD', '2026-08-01', '2026-08-31', '[\"meta\"]',"
            " 'LIVE', 'normal', %s, %s)",
            (db.new_id("ccy"), db.DEV_ORG_ID, brand["id"], ts, ts),
        )
        main.conn.commit()
        main._last_auto_sync_check = None
        start = datetime(2026, 8, 13, 0, 0, tzinfo=UTC)
        with mock.patch.object(ads_auto_sync, "run") as run:
            main._auto_sync_if_due(start)
            main._auto_sync_if_due(start + timedelta(hours=3, minutes=59))
            main._auto_sync_if_due(start + timedelta(hours=4))
        self.assertEqual(run.call_count, 2)

    def test_without_live_cycle_runs_once_per_calendar_day(self):
        main.conn.execute("UPDATE campaign_cycle SET status = 'CLOSED'")
        main.conn.commit()
        main._last_auto_sync_check = None
        start = datetime(2026, 8, 13, 1, 0, tzinfo=UTC)
        with mock.patch.object(ads_auto_sync, "run") as run:
            main._auto_sync_if_due(start)
            main._auto_sync_if_due(start + timedelta(hours=22))
            main._auto_sync_if_due(start + timedelta(days=1))
        self.assertEqual(run.call_count, 2)

    def test_cycle_checks_run_live_reminder_and_post_sync_chain(self):
        brand = bi_repo.create_brand(main.conn, name="虛構同步檢查", client_name=None, actor=ACTOR, org_id=db.DEV_ORG_ID)
        ts = db.now_utc()
        cycle_id = db.new_id("ccy")
        main.conn.execute(
            "INSERT INTO campaign_cycle (id, org_id, brand_id, product_scope_json, objective,"
            " currency, start_date, end_date, channels_json, status, phase, created_at,"
            " updated_at) VALUES (%s, %s, %s, '[]', 'sales', 'TWD', '2026-08-01', '2026-08-31', '[\"meta\"]',"
            " 'LIVE', 'normal', %s, %s)",
            (cycle_id, db.DEV_ORG_ID, brand["id"], ts, ts),
        )
        main.conn.commit()
        with (mock.patch.object(ads_auto_sync, "check_schedule_reminder") as reminder,
              mock.patch.object(ads_auto_sync.tracking, "run_post_sync_checks") as post_check):
            ads_auto_sync.run_cycle_checks(
                main.conn, brand["id"], TODAY, url_probe=NO_NETWORK)
        reminder.assert_called_once_with(main.conn, brand["id"], cycle_id, TODAY)
        post_check.assert_called_once_with(
            main.conn, brand["id"], today=TODAY, url_probe=NO_NETWORK)


class ImmediateSyncTest(_BaseAutoSyncTest):
    def setUp(self):
        super().setUp()
        ads_auto_sync._immediate_sync_cache.clear()
        coresettings.set_setting(main.conn, ads_sync.ACCOUNT_SETTING, "act_123", org_id=db.DEV_ORG_ID)
        coresettings.set_setting(main.conn, ads_sync.TOKEN_SETTING, "fake-token", org_id=db.DEV_ORG_ID)
        coresettings.set_setting(main.conn, ga4_sync.PROPERTY_SETTING, "123456789", org_id=db.DEV_ORG_ID)
        coresettings.set_setting(main.conn, ga4_sync.SERVICE_ACCOUNT_SETTING,
                                 '{"type": "service_account"}', org_id=db.DEV_ORG_ID)

    def test_immediate_sync_debounces_repeated_clicks(self):
        meta = meta_api.FakeMetaClient(campaigns=[], insights=[])
        ga4 = ga4_api.FakeGA4Client(rows=[])
        start = datetime(2026, 8, 13, 8, 0, tzinfo=UTC)
        first = ads_auto_sync.sync_brand_now(
            main.conn, self.brand["id"], ACTOR, meta_client=meta, ga4_client=ga4, now=start,
            url_probe=NO_NETWORK)
        second = ads_auto_sync.sync_brand_now(
            main.conn, self.brand["id"], ACTOR, meta_client=meta, ga4_client=ga4,
            now=start + timedelta(seconds=5), url_probe=NO_NETWORK)
        self.assertEqual(first, second)
        self.assertEqual(len([c for c in meta.calls if c[0] == "campaigns"]), 1)
        self.assertEqual(len([c for c in ga4.calls if c[0] == "source_medium"]), 1)

    def test_dashboard_sync_endpoint_returns_frontend_timestamp_shape(self):
        timestamp = "2026-08-13T08:00:00+00:00"
        with mock.patch.object(ads_auto_sync, "sync_brand_now", return_value=timestamp):
            response = TestClient(main.app).post(f"/api/dashboard/brands/{self.brand['id']}/sync")
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["data"], {"updated_at": timestamp})

    def test_dashboard_sync_endpoint_reports_sync_failure(self):
        with mock.patch.object(ads_auto_sync, "sync_brand_now", side_effect=ValueError("同步失敗")):
            response = TestClient(main.app).post(f"/api/dashboard/brands/{self.brand['id']}/sync")
        self.assertEqual(response.status_code, 502, response.text)
        self.assertEqual(response.json(), {"error": "同步失敗"})


if __name__ == "__main__":
    unittest.main()
