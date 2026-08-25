# -*- coding: utf-8 -*-
"""票 T0：品牌層追蹤健檢（契約 1.1-1.8／2.1／2.4／2.6）。全程假 fetch，不打真網路。"""

import time
import unittest
from datetime import date, timedelta
from unittest import mock

import pytest
from fastapi.testclient import TestClient

import app.main as main
from app.ads import ga4_api
from app.ads import ga4_sync
from app.ads import meta_api
from app.ads import tracking
from app.brand_intelligence import repository as bi_repo
from app.core import settings as coresettings
from app.orders import channel as orders_channel

ACTOR = "測試員"

# 特徵字串比照 app/ads/tracking.py 檔頭查證出處：GA4 script src + gtag('config'；
# Meta Pixel script src + fbq('init'。
_GA4_HTML = ("<html><head><script src='https://www.googletagmanager.com/gtag/js?id=G-XXX'>"
             "</script><script>gtag('config', 'G-XXX');</script></head></html>")
_PIXEL_HTML = ("<html><head><script src='https://connect.facebook.net/en_US/fbevents.js'>"
               "</script><script>fbq('init', '123');</script></head></html>")
_BOTH_HTML = _GA4_HTML + _PIXEL_HTML
_NEITHER_HTML = "<html><head><title>虛構茶行</title></head></html>"
# 只有 script 標籤、沒有真的呼叫 config／init——兩個特徵字串缺一，不能算裝好
# （關進兩條斷言：AND 判定被誤改成 OR 時，這兩條會紅）。
_GA4_SCRIPT_ONLY_HTML = "<html><script src='https://www.googletagmanager.com/gtag/js?id=G-XXX'></script></html>"
_PIXEL_SCRIPT_ONLY_HTML = "<html><script src='https://connect.facebook.net/en_US/fbevents.js'></script></html>"


# BUG app/orders/channel.py:164 — pharmacy_latest_batch() 宣告回傳 Optional[str]，
# 但 row["batch_date"] 現在是 psycopg 自動轉出的 date 物件，不是字串（同一類 BUG，orders
# 群組已在 channel.py:183 標過一次，這是同一個檔案的另一個函式）。
_BUG_PHARMACY_DATE_NOT_STR = pytest.mark.xfail(
    strict=True,
    reason="BUG app/orders/channel.py:164 — pharmacy_latest_batch() 宣告 Optional[str]"
           "卻回傳 date 物件，比對字串時 AssertionError",
)

# BUG app/ads/routes_progress.py:96 — _progress_run() 在自己開的 threading.Thread 裡執行
# work()，contextvar 綁定的連線不會被子執行緒繼承，背景任務裡任何 DB 呼叫都炸
# RuntimeError: no connection bound（同一個 BUG，ads 群組已標過）。
_BUG_PROGRESS_THREAD_NO_CONNECTION = pytest.mark.xfail(
    strict=True,
    reason="BUG app/ads/routes_progress.py:96 — 背景 thread 沒繼承 contextvar 綁定的連線，"
           "work() 裡任何 DB 呼叫都是 RuntimeError: no connection bound",
)


class TrackingHealthBase(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(main.app)
        self.brand = bi_repo.create_brand(
            main.conn, name=f"虛構健檢茶行{abs(hash(self.id())) % 100000}",
            client_name=None, actor=ACTOR)
        self.bid = self.brand["id"]

    def add_channel(self, channel_type, identifier=None, name="通路"):
        return bi_repo.create_channel(
            main.conn, self.bid, actor=ACTOR, channel_type=channel_type, name=name,
            identifier=identifier)

    def sync_ga4(self, *, sessions=10, days_ago=0):
        """訊號②測試小工具：跑一次假 GA4 同步，讓 ga4_sync_status／ga4_summary 有資料列。
        全程 FakeGA4Client，不打真 GA4 API（比照 app/tests/test_ads_ga4.py 既有寫法）。
        days_ago>0 用來造「同步過但已經不新鮮」的情境，直接改寫 synced_at
        （sync_brand 一律用當下真實時間戳，測試要驗過期只能事後覆寫）。"""
        coresettings.set_setting(main.conn, ga4_sync.PROPERTY_SETTING, "123456789")
        coresettings.set_setting(main.conn, ga4_sync.SERVICE_ACCOUNT_SETTING,
                                 '{"client_email": "svc@example.iam.gserviceaccount.com"}')
        row = ga4_api.SourceMediumRow(source="google", medium="organic", sessions=sessions,
                                      conversions=0.0, revenue=0.0)
        client = ga4_api.FakeGA4Client(rows=[row], purchase_seen=False)
        ga4_sync.sync_brand(main.conn, self.bid, ACTOR, client=client)
        if days_ago:
            stale = (date.today() - timedelta(days=days_ago)).isoformat() + "T00:00:00+00:00"
            main.conn.execute(
                "UPDATE ga4_sync_status SET synced_at = %s WHERE brand_id = %s", (stale, self.bid))
            main.conn.commit()

    def configure_meta(self):
        coresettings.set_setting(main.conn, "meta_access_token", "測試唯讀金鑰")
        coresettings.set_setting(main.conn, "meta_ad_account_id", "act_999")


class WebsiteDetectionTest(TrackingHealthBase):
    """GA4／Pixel 特徵偵測：找到／找不到／壞頁面三種情境，假 HTML 字串，不碰真網路。"""

    def test_no_url_is_gray_off_without_network_call(self):
        fetch = mock.Mock()
        node = tracking.check_website_now(main.conn, self.bid, fetch=fetch)
        self.assertEqual(node["status"], "off")
        self.assertIsNone(node["checked_at"])
        fetch.assert_not_called()

    def test_both_found_is_ok(self):
        self.add_channel("website", identifier="https://example.test")
        node = tracking.check_website_now(
            main.conn, self.bid, fetch=lambda _url: (True, _BOTH_HTML))
        self.assertEqual(node["status"], "ok")
        self.assertEqual(node["action"], {"kind": "none", "missing": []})
        self.assertIsNotNone(node["checked_at"])

    def test_only_ga4_found_is_warn_missing_pixel(self):
        self.add_channel("website", identifier="https://example.test")
        node = tracking.check_website_now(
            main.conn, self.bid, fetch=lambda _url: (True, _GA4_HTML),
            meta_client=meta_api.FakeMetaClient())
        self.assertEqual(node["status"], "warn")
        self.assertEqual(node["action"], {"kind": "install", "missing": ["pixel"]})

    def test_only_pixel_found_is_warn_missing_ga4(self):
        self.add_channel("website", identifier="https://example.test")
        node = tracking.check_website_now(
            main.conn, self.bid, fetch=lambda _url: (True, _PIXEL_HTML))
        self.assertEqual(node["status"], "warn")
        self.assertEqual(node["action"], {"kind": "install", "missing": ["ga4"]})

    def test_neither_found_by_scan_is_warn_not_bad(self):
        """契約 1.3 修訂（2026-08-14）核心迴歸案例：EasyStore 這類動態注入追蹤碼的平台，
        原始碼掃描必然掃不到——這不再等於「連不上」，紅燈只留給網站真的連不上。掃描沒掃到、
        又沒有其他訊號確認時，燈號要是黃（還沒驗到），不是紅（之前的誤判行為）。"""
        self.add_channel("website", identifier="https://example.test")
        node = tracking.check_website_now(
            main.conn, self.bid, fetch=lambda _url: (True, _NEITHER_HTML),
            meta_client=meta_api.FakeMetaClient())
        self.assertEqual(node["status"], "warn")
        self.assertEqual(set(node["action"]["missing"]), {"ga4", "pixel"})
        self.assertNotIn("沒安裝", node["message"])
        self.assertNotIn("沒偵測到", node["message"])
        self.assertIn("還沒驗到", node["message"])
        self.assertIn("EasyStore", node["message"])

    def test_script_tag_without_config_call_is_not_confirmed(self):
        """只載入 gtag.js／fbevents.js 函式庫、沒有真的呼叫 config／init，兩個特徵字串
        缺一不可（AND，不是 OR）——這是裝了函式庫但沒設定測量 ID 的常見半吊子情況。
        契約 1.3 修訂後這仍然不算確認，但燈號降級成黃（沒有其他訊號時），不是紅。"""
        self.add_channel("website", identifier="https://example.test")
        node = tracking.check_website_now(
            main.conn, self.bid, fetch=lambda _url: (True, _GA4_SCRIPT_ONLY_HTML),
            meta_client=meta_api.FakeMetaClient())
        self.assertEqual(node["status"], "warn")
        self.assertEqual(set(node["action"]["missing"]), {"ga4", "pixel"})

        node = tracking.check_website_now(
            main.conn, self.bid, fetch=lambda _url: (True, _PIXEL_SCRIPT_ONLY_HTML),
            meta_client=meta_api.FakeMetaClient())
        self.assertEqual(node["status"], "warn")

    def test_broken_page_fetch_failure_is_bad_not_exception(self):
        """紅燈只留給這一種情境（契約 1.3 修訂）：網站真的連不上。"""
        self.add_channel("website", identifier="https://example.test")
        node = tracking.check_website_now(
            main.conn, self.bid, fetch=lambda _url: (False, ""))
        self.assertEqual(node["status"], "bad")
        self.assertIn("連不上", node["message"])
        self.assertNotIn("沒安裝", node["message"])

    def test_ga4_data_signal_confirms_when_scan_misses(self):
        """訊號②：掃描沒掃到（模擬 EasyStore），但既有 GA4 同步資料新鮮＝GA4 確認，
        只剩 Pixel 還沒驗到。全程只讀本地表，不打真 GA4 API（見 sync_ga4 用 FakeGA4Client）。"""
        self.add_channel("website", identifier="https://example.test")
        self.sync_ga4()
        node = tracking.check_website_now(
            main.conn, self.bid, fetch=lambda _url: (True, _NEITHER_HTML),
            meta_client=meta_api.FakeMetaClient())
        self.assertEqual(node["status"], "warn")
        self.assertEqual(node["action"]["missing"], ["pixel"])

    def test_ga4_data_signal_ignored_when_stale(self):
        """同步過，但距上次同步太久（超過新鮮天數）——不算確認，跟從沒同步過一樣誠實。"""
        self.add_channel("website", identifier="https://example.test")
        self.sync_ga4(days_ago=30)
        node = tracking.check_website_now(
            main.conn, self.bid, fetch=lambda _url: (True, _NEITHER_HTML),
            meta_client=meta_api.FakeMetaClient())
        self.assertEqual(node["status"], "warn")
        self.assertIn("ga4", node["action"]["missing"])

    def test_pixel_api_signal_confirms_when_scan_misses(self):
        """訊號③：掃描沒掃到，但 Meta 唯讀連線查到這個廣告帳號的 Pixel 近期有開火＝Pixel
        確認，只剩 GA4 還沒驗到。全程 FakeMetaClient，不打真 Meta API。"""
        self.add_channel("website", identifier="https://example.test")
        self.configure_meta()
        fake_meta = meta_api.FakeMetaClient(
            pixels=[meta_api.Pixel(pixel_id="pix_1", name="測試 Pixel",
                                   last_fired_time=date.today().isoformat() + "T09:00:00-0700")])
        node = tracking.check_website_now(
            main.conn, self.bid, fetch=lambda _url: (True, _NEITHER_HTML), meta_client=fake_meta)
        self.assertEqual(node["status"], "warn")
        self.assertEqual(node["action"]["missing"], ["ga4"])
        self.assertEqual(fake_meta.calls, [("pixels", "act_999")])

    def test_pixel_api_signal_ignores_stale_fire(self):
        """Pixel 存在但最近一次開火太久以前——不算確認。"""
        self.add_channel("website", identifier="https://example.test")
        self.configure_meta()
        old = (date.today() - timedelta(days=60)).isoformat() + "T09:00:00-0700"
        fake_meta = meta_api.FakeMetaClient(
            pixels=[meta_api.Pixel(pixel_id="pix_1", name="測試 Pixel", last_fired_time=old)])
        node = tracking.check_website_now(
            main.conn, self.bid, fetch=lambda _url: (True, _NEITHER_HTML), meta_client=fake_meta)
        self.assertIn("pixel", node["action"]["missing"])

    def test_pixel_api_signal_skipped_gracefully_when_meta_not_configured(self):
        """沒接 Meta 連線＝這個訊號跳過（回 None），不是錯誤、不擋人，也不誤判成「沒有」。
        先明確清掉 Meta 設定：這兩把是全站設定，不分品牌，其他測試方法（同一支模組共用
        一條隔離 DB連線）可能已經設過，這裡強制回到「沒接」的前提，不依賴測試執行順序。"""
        coresettings.set_setting(main.conn, "meta_access_token", "")
        coresettings.set_setting(main.conn, "meta_ad_account_id", "")
        self.add_channel("website", identifier="https://example.test")
        node = tracking.check_website_now(
            main.conn, self.bid, fetch=lambda _url: (True, _NEITHER_HTML))
        self.assertEqual(node["status"], "warn")
        self.assertIn("pixel", node["action"]["missing"])

    def test_pixel_api_signal_skipped_gracefully_on_meta_error(self):
        """Meta 連線設定了，但查詢失敗（權限不夠／連不上）——訊號跳過，不拋例外、不擋人
        （契約 2.4），不誤判成「確認沒有」。"""
        self.add_channel("website", identifier="https://example.test")
        self.configure_meta()
        fake_meta = meta_api.FakeMetaClient(error=meta_api.MetaApiError("模擬 Meta 連線失敗"))
        node = tracking.check_website_now(
            main.conn, self.bid, fetch=lambda _url: (True, _NEITHER_HTML), meta_client=fake_meta)
        self.assertEqual(node["status"], "warn")
        self.assertIn("pixel", node["action"]["missing"])

    def test_all_three_signals_confirm_is_ok(self):
        """掃描漏抓，但 GA4 數據與 Pixel API 兩個訊號都確認＝綠燈（契約：兩樣都被任一訊號
        確認）。"""
        self.add_channel("website", identifier="https://example.test")
        self.sync_ga4()
        self.configure_meta()
        fake_meta = meta_api.FakeMetaClient(
            pixels=[meta_api.Pixel(pixel_id="pix_1", name="測試 Pixel",
                                   last_fired_time=date.today().isoformat() + "T09:00:00-0700")])
        node = tracking.check_website_now(
            main.conn, self.bid, fetch=lambda _url: (True, _NEITHER_HTML), meta_client=fake_meta)
        self.assertEqual(node["status"], "ok")
        self.assertEqual(node["action"], {"kind": "none", "missing": []})

    def test_result_persists_for_next_read(self):
        self.add_channel("website", identifier="https://example.test")
        tracking.check_website_now(main.conn, self.bid, fetch=lambda _url: (True, _BOTH_HTML))
        health = tracking.tracking_health(main.conn, self.bid)
        website = next(c for c in health["channels"] if c["key"] == "website")
        self.assertEqual(website["status"], "ok")
        self.assertIsNotNone(website["checked_at"])


class TrackingHealthAssemblyTest(TrackingHealthBase):
    """五路健檢組裝：固定順序、灰燈、hidden。"""

    def test_five_channels_fixed_order_default_ready_zero(self):
        health = tracking.tracking_health(main.conn, self.bid)
        keys = [c["key"] for c in health["channels"]]
        self.assertEqual(keys, ["website", "fb_page", "ig_account", "shopee", "pharmacy"])
        self.assertEqual(health["total"], 5)
        self.assertEqual(health["ready"], 0)
        self.assertEqual(health["channels"][0]["status"], "off")  # 沒填官網網址＝灰燈

    def test_fb_ig_ready_when_identifier_filled(self):
        self.add_channel("fb_page", identifier="@example")
        self.add_channel("ig_account", identifier="@example_ig")
        health = tracking.tracking_health(main.conn, self.bid)
        fb = next(c for c in health["channels"] if c["key"] == "fb_page")
        ig = next(c for c in health["channels"] if c["key"] == "ig_account")
        self.assertEqual(fb["status"], "ok")
        self.assertEqual(ig["status"], "ok")
        self.assertEqual(health["ready"], 2)

    @_BUG_PHARMACY_DATE_NOT_STR
    def test_shopee_pharmacy_ready_after_import_with_latest_date(self):
        orders_channel.save_shopee_rows(
            main.conn, self.bid,
            [{"order_sn": "SN1", "order_date": "2026-08-01", "revenue": 100, "voucher_code": None}],
            source="manual", actor=ACTOR)
        orders_channel.record_pharmacy_batch(
            main.conn, self.bid, batch_date="2026-08-05", quantity=10, actor=ACTOR)
        health = tracking.tracking_health(main.conn, self.bid)
        shopee = next(c for c in health["channels"] if c["key"] == "shopee")
        pharmacy = next(c for c in health["channels"] if c["key"] == "pharmacy")
        self.assertEqual(shopee["status"], "ok")
        self.assertTrue(shopee["sub"])  # 匯入時間戳，非固定值
        self.assertEqual(pharmacy["status"], "ok")
        self.assertEqual(pharmacy["sub"], "2026-08-05")
        self.assertEqual(health["ready"], 2)

    def test_shopee_pharmacy_never_imported_is_off(self):
        health = tracking.tracking_health(main.conn, self.bid)
        shopee = next(c for c in health["channels"] if c["key"] == "shopee")
        pharmacy = next(c for c in health["channels"] if c["key"] == "pharmacy")
        self.assertEqual(shopee["status"], "off")
        self.assertEqual(pharmacy["status"], "off")

    def test_hidden_channel_excluded_from_ready_and_total_but_still_listed(self):
        tracking.set_channel_hidden(main.conn, self.bid, "pharmacy", True)
        health = tracking.tracking_health(main.conn, self.bid)
        self.assertEqual(health["total"], 4)
        keys = [c["key"] for c in health["channels"]]
        self.assertIn("pharmacy", keys)  # 仍在清單裡，只是 hidden=True，前端可收合可恢復
        pharmacy = next(c for c in health["channels"] if c["key"] == "pharmacy")
        self.assertTrue(pharmacy["hidden"])

    def test_hidden_can_be_restored(self):
        tracking.set_channel_hidden(main.conn, self.bid, "pharmacy", True)
        tracking.set_channel_hidden(main.conn, self.bid, "pharmacy", False)
        health = tracking.tracking_health(main.conn, self.bid)
        self.assertEqual(health["total"], 5)

    def test_set_channel_hidden_rejects_unknown_key(self):
        with self.assertRaises(ValueError):
            tracking.set_channel_hidden(main.conn, self.bid, "line", True)


class TrackingHealthApiTest(TrackingHealthBase):
    def test_get_endpoint_contract_shape(self):
        response = self.client.get(f"/api/campaigns/brands/{self.bid}/tracking-health")
        self.assertEqual(response.status_code, 200, response.text)
        data = response.json()["data"]
        self.assertEqual(set(data), {"channels", "ready", "total"})
        for node in data["channels"]:
            self.assertEqual(
                set(node), {"key", "status", "message", "sub", "checked_at", "hidden", "action"})
            self.assertIn(node["status"], {"ok", "warn", "bad", "off"})
            self.assertEqual(set(node["action"]), {"kind", "missing"})
            self.assertIn(node["action"]["kind"], {"install", "fill", "none"})

    def test_hidden_toggle_endpoint(self):
        response = self.client.post(
            f"/api/campaigns/brands/{self.bid}/tracking-health/shopee/hidden", json={"hidden": True})
        self.assertEqual(response.status_code, 204, response.text)
        data = self.client.get(f"/api/campaigns/brands/{self.bid}/tracking-health").json()["data"]
        self.assertEqual(data["total"], 4)

    def test_hidden_toggle_rejects_unknown_channel(self):
        response = self.client.post(
            f"/api/campaigns/brands/{self.bid}/tracking-health/line/hidden", json={"hidden": True})
        self.assertEqual(response.status_code, 404)

    def test_website_check_endpoint_is_synchronous_and_returns_node(self):
        fake_node = {"key": "website", "status": "bad", "message": "抓不到",
                     "sub": "https://example.test", "checked_at": None, "hidden": False,
                     "action": {"kind": "install", "missing": ["ga4", "pixel"]}}
        with mock.patch.object(tracking, "check_website_now", return_value=fake_node):
            response = self.client.post(
                f"/api/campaigns/brands/{self.bid}/tracking-health/website/check")
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["data"], fake_node)

    @_BUG_PROGRESS_THREAD_NO_CONNECTION
    def test_recheck_runs_in_background_and_updates_stored_state(self):
        """契約 1.7：背景執行，完成後 GET tracking-health 原地反映新結果。"""
        self.add_channel("website", identifier="https://example.test")
        with mock.patch.object(tracking.net, "fetch_raw_html", return_value=(True, _BOTH_HTML)):
            start = self.client.post(f"/api/campaigns/brands/{self.bid}/tracking-health/recheck")
            self.assertEqual(start.status_code, 204, start.text)
            status = {"status": "running"}
            for _ in range(50):
                status = self.client.get(
                    f"/api/campaigns/brands/{self.bid}/tracking-health/recheck/status"
                ).json()["data"]
                if status["status"] != "running":
                    break
                time.sleep(0.05)
        self.assertEqual(status["status"], "done", status)
        health = self.client.get(f"/api/campaigns/brands/{self.bid}/tracking-health").json()["data"]
        website = next(c for c in health["channels"] if c["key"] == "website")
        self.assertEqual(website["status"], "ok")


if __name__ == "__main__":
    unittest.main()
