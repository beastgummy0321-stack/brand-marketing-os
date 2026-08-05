# -*- coding: utf-8 -*-
"""app/tests/test_ads_connections.py — D線票2（GitHub issue #44）：資料與連線頁＋薄匯入路由。

嗅探與匯入邏輯本身不重寫、不重測——沿用 app/tests/test_orders_dispatch.py 已驗證過的
app.orders.dispatch.import_dropped_file()。這裡只驗證：
1. 新頁面直達＋容量規則（票 1 腳本）。
2. 薄路由把同一支分派函式的結果導回本頁（而非訂單頁），三種訊息條（成功／警告／錯誤）。
3. 金鑰只留深連結，頁面本身沒有金鑰輸入欄位。
4. 空狀態（尚未連 Meta／尚無訂單資料）與待認領入口。

fixture 一律虛構品牌，嚴禁真實品牌名稱。
"""

import atexit
import io
import os
import shutil
import tempfile
import unittest
from pathlib import Path
from urllib.parse import unquote

_tmpdir = tempfile.mkdtemp(prefix="brand_os_ads_connections_")
os.environ["BRAND_OS_DB"] = str(Path(_tmpdir) / "test.db")
os.environ["BRAND_OS_BACKUP_DIR"] = str(Path(_tmpdir) / "backups")
os.environ["BRAND_OS_UPLOADS"] = str(Path(_tmpdir) / "uploads")

import openpyxl  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

import app.main as main  # noqa: E402
from app.ads import meta_api  # noqa: E402
from app.ads import repository as ads_repo  # noqa: E402
from app.ads import sync as ads_sync  # noqa: E402
from app.ads import ga4_sync  # noqa: E402
from app.brand_intelligence import repository as bi_repo  # noqa: E402
from app.core import settings as coresettings  # noqa: E402
from app.tools import capacity_check  # noqa: E402

main.reopen_connection()

_TEMPLATE_PATH = Path(__file__).resolve().parents[2] / "app" / "templates" / "ads_connections.html"


def _cleanup():
    try:
        main.conn.close()
    except Exception:
        pass
    shutil.rmtree(_tmpdir, ignore_errors=True)


atexit.register(_cleanup)

ACTOR = "測試員"
META_ACCOUNT = "act_1234567890"
GA4_PROPERTY_ID = "123456789"
GA4_FAKE_KEY_JSON = '{"client_email": "svc@example.iam.gserviceaccount.com"}'

_EASYSTORE_HEADERS = ["Order Number", "Date", "Total Amount", "Refunded Amount",
                      "Financial Status", "Fulfillment Status", "Order Status",
                      "Voucher Code", "Billing Email", "Billing Phone", "Item SKU",
                      "Item Price", "Quantity"]

_SHOPEE_CSV = "Order SN,Order creation date,Order amount,Voucher code\nSN010,2026-06-03,999,\n"

_META_CSV = ("Reporting starts,Reporting ends,Campaign name,Amount spent (TWD),"
            "Impressions,Link clicks,Purchases,Purchases conversion value\n"
            "{start},{end},虛構檔期,3000,8000,210,5,9000\n")


def _easystore_xlsx_bytes():
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(_EASYSTORE_HEADERS)
    ws.append(["ORD1", "2026-06-01", 1000, 0, "paid", "fulfilled", "completed", None,
              "buyer@example.com", None, "SKU-A", 500, 2])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


class CapacityTest(unittest.TestCase):
    """驗收條件：新頁面主欄區塊數符合容量規則（票 1 腳本通過）。"""

    def test_connections_page_passes_capacity_script(self):
        counts, problems = capacity_check.check_file(_TEMPLATE_PATH)
        self.assertEqual(problems, [])
        self.assertLessEqual(counts["card_count"], capacity_check.CARD_LIMIT)
        self.assertLessEqual(counts["nav_link_count"], capacity_check.NAV_LINK_LIMIT)
        self.assertEqual(counts["illegal_detail_count"], 0)


class ConnectionsRouteTest(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(main.app)
        main.conn.execute("DELETE FROM discovered_campaign")
        main.conn.execute("DELETE FROM app_setting WHERE key IN (?, ?, ?, ?)",
                          (ads_sync.ACCOUNT_SETTING, ads_sync.TOKEN_SETTING,
                           ga4_sync.PROPERTY_SETTING, ga4_sync.SERVICE_ACCOUNT_SETTING))
        main.conn.commit()
        self.brand_name = f"虛構晨光茶行{abs(hash(self.id())) % 100000}"
        self.brand = bi_repo.create_brand(main.conn, name=self.brand_name,
                                          client_name=None, actor=ACTOR)
        self.bid = self.brand["id"]

    # ---- 頁面直達＋空狀態＋金鑰深連結 --------------------------------------

    def test_page_reachable_and_shows_empty_states(self):
        resp = self.client.get(f"/brands/{self.bid}/ads/connections")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("還沒有任何訂單資料", resp.text)
        self.assertIn("還沒連上 Meta", resp.text)
        self.assertIn("/settings#settings-meta-title", resp.text)
        self.assertIn("還沒設定 GA4", resp.text)
        self.assertIn("/settings#settings-ga4-title", resp.text)

    def test_page_has_no_key_input_fields(self):
        """決策 0028 硬規則：本頁不得出現金鑰輸入欄位。"""
        resp = self.client.get(f"/brands/{self.bid}/ads/connections")
        self.assertNotIn('type="password"', resp.text)

    def test_page_folds_pixel_and_ga4_guide_links_into_detail(self):
        resp = self.client.get(f"/brands/{self.bid}/ads/connections")
        self.assertIn(f"/brands/{self.bid}/ads/pixel-guide", resp.text)
        self.assertIn(f"/brands/{self.bid}/ads/ga4-guide", resp.text)
        self.assertIn('class="field-details"', resp.text)

    def test_meta_connected_shows_sync_button_not_empty_state(self):
        coresettings.set_setting(main.conn, ads_sync.ACCOUNT_SETTING, META_ACCOUNT)
        coresettings.set_setting(main.conn, ads_sync.TOKEN_SETTING, "fake-token")
        resp = self.client.get(f"/brands/{self.bid}/ads/connections")
        self.assertIn(f'action="/brands/{self.bid}/ads/sync"', resp.text)
        self.assertNotIn("還沒連上 Meta", resp.text)

    def test_ga4_configured_shows_sync_link_not_empty_state(self):
        coresettings.set_setting(main.conn, ga4_sync.PROPERTY_SETTING, GA4_PROPERTY_ID)
        coresettings.set_setting(main.conn, ga4_sync.SERVICE_ACCOUNT_SETTING, GA4_FAKE_KEY_JSON)
        resp = self.client.get(f"/brands/{self.bid}/ads/connections")
        self.assertIn(f"/brands/{self.bid}/ads/ga4/sync", resp.text)
        self.assertNotIn("還沒設定 GA4", resp.text)

    def test_pending_claims_banner_links_to_claims_page(self):
        coresettings.set_setting(main.conn, ads_sync.ACCOUNT_SETTING, META_ACCOUNT)
        coresettings.set_setting(main.conn, ads_sync.TOKEN_SETTING, "fake-token")
        client = meta_api.FakeMetaClient(campaigns=[
            meta_api.Campaign(campaign_id="999", name="某個沒歸屬的活動",
                              objective="OUTCOME_SALES", effective_status="ACTIVE")])
        ads_sync.sync_account(main.conn, ACTOR, client=client, today="2026-07-31")
        resp = self.client.get(f"/brands/{self.bid}/ads/connections")
        self.assertIn("還沒確認是不是這個品牌的", resp.text)
        self.assertIn(f"/brands/{self.bid}/ads/claims", resp.text)

    # ---- 薄匯入路由：三種格式皆正確入庫，且導回本頁而非訂單頁 ----------------

    def test_upload_easystore_xlsx_lands_orders_and_stays_on_connections_page(self):
        resp = self.client.post(
            f"/brands/{self.bid}/ads/connections/import",
            files={"drop_file": ("Export_Orders.xlsx", _easystore_xlsx_bytes(),
                                 "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
            follow_redirects=False,
        )
        self.assertEqual(resp.status_code, 303)
        location = resp.headers["location"]
        self.assertTrue(location.startswith(f"/brands/{self.bid}/ads/connections?"))
        self.assertIn("kind=ok", location)
        count = main.conn.execute(
            "SELECT COUNT(*) c FROM order_record WHERE brand_id = ?", (self.bid,)
        ).fetchone()["c"]
        self.assertEqual(count, 1)

    def test_upload_shopee_csv_lands_and_stays_on_connections_page(self):
        resp = self.client.post(
            f"/brands/{self.bid}/ads/connections/import",
            files={"drop_file": ("shopee.csv", _SHOPEE_CSV.encode("utf-8"), "text/csv")},
            follow_redirects=False,
        )
        self.assertEqual(resp.status_code, 303)
        location = resp.headers["location"]
        self.assertTrue(location.startswith(f"/brands/{self.bid}/ads/connections?"))
        self.assertIn("kind=ok", location)
        count = main.conn.execute(
            "SELECT COUNT(*) c FROM shopee_report_row WHERE brand_id = ?", (self.bid,)
        ).fetchone()["c"]
        self.assertEqual(count, 1)

    def test_upload_meta_csv_matching_cycle_lands_and_stays_on_connections_page(self):
        cycle = ads_repo.create_cycle(main.conn, self.bid, product_ids=[], pain_value=5000,
                                      objective="流量", actor=ACTOR, start_date="2026-06-01",
                                      duration_days=14)
        content = _META_CSV.format(start="2026-06-01", end="2026-06-14").encode("utf-8")
        resp = self.client.post(
            f"/brands/{self.bid}/ads/connections/import",
            files={"drop_file": ("meta_export.csv", content, "text/csv")},
            follow_redirects=False,
        )
        self.assertEqual(resp.status_code, 303)
        location = resp.headers["location"]
        self.assertTrue(location.startswith(f"/brands/{self.bid}/ads/connections?"))
        self.assertIn("kind=ok", location)
        row = main.conn.execute(
            "SELECT campaign_cycle_id FROM performance_snapshot WHERE brand_id = ?",
            (self.bid,)).fetchone()
        self.assertEqual(row["campaign_cycle_id"], cycle["id"])

    def test_upload_meta_csv_outside_any_cycle_gives_warning_not_ok(self):
        content = _META_CSV.format(start="2020-01-01", end="2020-01-14").encode("utf-8")
        resp = self.client.post(
            f"/brands/{self.bid}/ads/connections/import",
            files={"drop_file": ("meta_export.csv", content, "text/csv")},
            follow_redirects=False,
        )
        location = resp.headers["location"]
        self.assertTrue(location.startswith(f"/brands/{self.bid}/ads/connections?"))
        self.assertIn("kind=warn", location)

    def test_upload_unrecognisable_file_gives_error_lists_headers_stays_on_page(self):
        resp = self.client.post(
            f"/brands/{self.bid}/ads/connections/import",
            files={"drop_file": ("mystery.csv", b"foo,bar\n1,2\n", "text/csv")},
            follow_redirects=False,
        )
        self.assertEqual(resp.status_code, 303)
        location = resp.headers["location"]
        # 認不出格式時留在本頁，不是被導去訂單頁
        self.assertTrue(location.startswith(f"/brands/{self.bid}/ads/connections?"))
        self.assertIn("kind=danger", location)
        message = unquote(location)
        self.assertIn("foo", message)
        self.assertIn("bar", message)

    def test_upload_empty_file_gives_error(self):
        resp = self.client.post(
            f"/brands/{self.bid}/ads/connections/import",
            files={"drop_file": ("empty.csv", b"", "text/csv")},
            follow_redirects=False,
        )
        self.assertEqual(resp.status_code, 303)
        location = resp.headers["location"]
        self.assertTrue(location.startswith(f"/brands/{self.bid}/ads/connections?"))
        self.assertIn("kind=danger", location)
        self.assertIn("空的", unquote(location))

    def test_upload_success_message_is_visible_back_on_the_page(self):
        self.client.post(
            f"/brands/{self.bid}/ads/connections/import",
            files={"drop_file": ("Export_Orders.xlsx", _easystore_xlsx_bytes(),
                                 "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
        )
        page = self.client.get(f"/brands/{self.bid}/ads/connections")
        # 匯完之後空狀態訊息不再出現
        self.assertNotIn("還沒有任何訂單資料", page.text)


if __name__ == "__main__":
    unittest.main()
