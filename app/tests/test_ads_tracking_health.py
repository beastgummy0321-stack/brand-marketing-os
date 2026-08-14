# -*- coding: utf-8 -*-
"""票 T0：品牌層追蹤健檢（契約 1.1-1.8／2.1／2.4／2.6）。全程假 fetch，不打真網路。"""

import atexit
import shutil
import tempfile
import time
import unittest
from unittest import mock

_tmpdir = tempfile.mkdtemp(prefix="brand_os_tracking_health_")

from fastapi.testclient import TestClient  # noqa: E402

import app.main as main  # noqa: E402
from app.ads import tracking  # noqa: E402
from app.brand_intelligence import repository as bi_repo  # noqa: E402
from app.orders import channel as orders_channel  # noqa: E402


def _cleanup():
    try:
        main.conn.close()
    except Exception:
        pass
    shutil.rmtree(_tmpdir, ignore_errors=True)


atexit.register(_cleanup)
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
            main.conn, self.bid, fetch=lambda _url: (True, _GA4_HTML))
        self.assertEqual(node["status"], "warn")
        self.assertEqual(node["action"], {"kind": "install", "missing": ["pixel"]})

    def test_only_pixel_found_is_warn_missing_ga4(self):
        self.add_channel("website", identifier="https://example.test")
        node = tracking.check_website_now(
            main.conn, self.bid, fetch=lambda _url: (True, _PIXEL_HTML))
        self.assertEqual(node["status"], "warn")
        self.assertEqual(node["action"], {"kind": "install", "missing": ["ga4"]})

    def test_neither_found_is_bad_red(self):
        self.add_channel("website", identifier="https://example.test")
        node = tracking.check_website_now(
            main.conn, self.bid, fetch=lambda _url: (True, _NEITHER_HTML))
        self.assertEqual(node["status"], "bad")
        self.assertEqual(set(node["action"]["missing"]), {"ga4", "pixel"})

    def test_script_tag_without_config_call_is_not_found(self):
        """只載入 gtag.js／fbevents.js 函式庫、沒有真的呼叫 config／init，兩個特徵字串
        缺一不可（AND，不是 OR）——這是裝了函式庫但沒設定測量 ID 的常見半吊子情況。"""
        self.add_channel("website", identifier="https://example.test")
        node = tracking.check_website_now(
            main.conn, self.bid, fetch=lambda _url: (True, _GA4_SCRIPT_ONLY_HTML))
        self.assertEqual(node["status"], "bad")
        self.assertEqual(set(node["action"]["missing"]), {"ga4", "pixel"})

        node = tracking.check_website_now(
            main.conn, self.bid, fetch=lambda _url: (True, _PIXEL_SCRIPT_ONLY_HTML))
        self.assertEqual(node["status"], "bad")

    def test_broken_page_fetch_failure_is_bad_not_exception(self):
        self.add_channel("website", identifier="https://example.test")
        node = tracking.check_website_now(
            main.conn, self.bid, fetch=lambda _url: (False, ""))
        self.assertEqual(node["status"], "bad")

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
