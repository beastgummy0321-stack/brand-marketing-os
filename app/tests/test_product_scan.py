# -*- coding: utf-8 -*-
"""app/tests/test_product_scan.py — 產品快掃（GitHub issue #6）。

見 app/main.py 的 /brands/{id}/products/new/research 路由、app/intake/ai.py 的
run_product_scan。全程用 FakeProvider＋假抓取（monkeypatch product_ai.fetch_url），
不發任何真實網路請求。品牌／產品名一律虛構，絕不可用 Beast Gummy。
"""

import atexit
import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

# 先備好暫存 DB 的環境變數，才能 import app.main（它在 import 當下就會連線＋跑 migrations）。
_tmpdir = tempfile.mkdtemp(prefix="brand_os_product_scan_")
os.environ["BRAND_OS_DB"] = str(Path(_tmpdir) / "test.db")
os.environ["BRAND_OS_BACKUP_DIR"] = str(Path(_tmpdir) / "backups")
os.environ["BRAND_OS_UPLOADS"] = str(Path(_tmpdir) / "uploads")

from fastapi.testclient import TestClient  # noqa: E402

import app.main as main  # noqa: E402
from app.brand_intelligence import repository as bi_repo  # noqa: E402
from app.core import settings as coresettings  # noqa: E402
from app.brand_intelligence import product_ai  # noqa: E402
from app.shared.web import OPERATOR  # noqa: E402
from app.llm.providers import (  # noqa: E402
    MISSING_KEY_MESSAGE, AnthropicProvider, FakeProvider, ProviderResponse, Usage,
)

main.reopen_connection()


def _cleanup():
    try:
        main.conn.close()
    except Exception:
        pass
    shutil.rmtree(_tmpdir, ignore_errors=True)


atexit.register(_cleanup)

ACTOR = "測試員"


def _fake_response(text: str, in_tok: int = 100, out_tok: int = 50) -> ProviderResponse:
    return ProviderResponse(output_text=text, structured=None,
                            usage=Usage(input_tokens=in_tok, output_tokens=out_tok),
                            stop_reason="end_turn")


_GOOD_FACTS = json.dumps({"facts": [
    {"fact_type": "產品線", "label": "單一品項", "value": "目前只有一款 60 錠裝。"},
    {"fact_type": "價格帶", "label": "中價位", "value": "單罐約 690 元，落在市場中段。"},
]}, ensure_ascii=False)

_FACTS_WITH_PRICE = json.dumps({"facts": [
    {"fact_type": "產品線", "label": "單一品項", "value": "目前只有一款 60 錠裝。"},
]}, ensure_ascii=False)
_FACTS_WITH_PRICE_OBJ = json.loads(_FACTS_WITH_PRICE)
_FACTS_WITH_PRICE_OBJ["price"] = {"amount": 690, "currency": "twd"}
_FACTS_WITH_PRICE = json.dumps(_FACTS_WITH_PRICE_OBJ, ensure_ascii=False)

_RESCAN_ONE_OVERLAP_ONE_NEW = json.dumps({"facts": [
    {"fact_type": "產品線", "label": "單一品項", "value": "重複標籤，這條不該再入庫。"},
    {"fact_type": "受眾", "label": "上班族", "value": "常見於下午茶時段購買。"},
]}, ensure_ascii=False)


class _BaseProductScanTest(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(main.app)
        main.conn.execute("DELETE FROM app_setting")
        main.conn.commit()
        self._envpatch = mock.patch.dict(os.environ, {}, clear=False)
        self._envpatch.start()
        os.environ.pop("ANTHROPIC_API_KEY", None)
        os.environ.pop("BRAND_OS_LLM_MODEL", None)
        self._orig_provider = product_ai.PROVIDER
        self._orig_fetch = product_ai.fetch_url
        product_ai.fetch_url = lambda url: (True, "假抓到的產品頁文字節錄。")
        self.brand = bi_repo.create_brand(main.conn, name="虛構茶研所", client_name="測試客戶", actor=ACTOR)

    def tearDown(self):
        product_ai.PROVIDER = self._orig_provider
        product_ai.fetch_url = self._orig_fetch
        self._envpatch.stop()

    def _post(self, name="虛構回甘烏龍", url="https://example.com/products/oolong"):
        return self.client.post(
            f"/brands/{self.brand['id']}/products/new/research",
            data={"name": name, "url": url}, follow_redirects=False,
        )


class ProductScanTest(_BaseProductScanTest):
    def test_scan_success_creates_product_and_pending_facts_with_source(self):
        product_ai.PROVIDER = FakeProvider(response=_fake_response(_GOOD_FACTS))
        resp = self._post()
        self.assertEqual(resp.status_code, 303)
        product_id = resp.headers["location"].split("/products/")[1].split("?")[0]
        products = bi_repo.list_products(main.conn, self.brand["id"])
        self.assertEqual(len(products), 1)
        self.assertEqual(products[0]["id"], product_id)
        self.assertEqual(products[0]["name"], "虛構回甘烏龍")

        facts = bi_repo.list_product_facts(main.conn, self.brand["id"], product_id)
        self.assertEqual(len(facts), 2)
        for f in facts:
            self.assertEqual(f["status"], "pending")
            self.assertIsNotNone(f["source_reference_id"])
            src = bi_repo.get_source_reference(main.conn, self.brand["id"], f["source_reference_id"])
            self.assertEqual(src["title"], "https://example.com/products/oolong")

    def test_missing_key_shows_human_error_and_creates_nothing(self):
        product_ai.PROVIDER = AnthropicProvider()  # 無金鑰：送網路請求之前就會擋下
        resp = self._post()
        self.assertEqual(resp.status_code, 400)
        self.assertIn(MISSING_KEY_MESSAGE, resp.text)
        self.assertEqual(bi_repo.list_products(main.conn, self.brand["id"]), [])

    def test_unparseable_reply_is_honest_failure_and_creates_nothing(self):
        product_ai.PROVIDER = FakeProvider(response=_fake_response("這不是 JSON，也不是允許的分類"))
        resp = self._post()
        self.assertEqual(resp.status_code, 400)
        self.assertIn(product_ai.PARSE_FAIL_MESSAGE, resp.text)
        self.assertEqual(bi_repo.list_products(main.conn, self.brand["id"]), [])

    def test_over_budget_blocks_before_any_llm_call(self):
        coresettings.set_setting(main.conn, coresettings.INTAKE_BUDGET_SETTING, "0.1")
        product_ai.PROVIDER = FakeProvider(response=_fake_response("不該被呼叫"))
        resp = self._post()
        self.assertEqual(resp.status_code, 400)
        self.assertIn("花費上限", resp.text)
        self.assertEqual(bi_repo.list_products(main.conn, self.brand["id"]), [])
        self.assertEqual(product_ai.PROVIDER.calls, [])

    def test_blank_url_manual_create_untouched(self):
        """不填網址：原本的「新增這個產品」（純手動）行為完全不變，走 /products/new。"""
        resp = self.client.post(
            f"/brands/{self.brand['id']}/products/new",
            data={"name": "虛構純手動產品"}, follow_redirects=False,
        )
        self.assertEqual(resp.status_code, 303)
        products = bi_repo.list_products(main.conn, self.brand["id"])
        self.assertEqual(len(products), 1)
        self.assertEqual(bi_repo.list_product_facts(main.conn, self.brand["id"], products[0]["id"]), [])


class ProductRescanTest(_BaseProductScanTest):
    """AI 再次調研（issue 擴充）：/brands/{id}/products/{pid}/rescan、快掃同時抽 price、
    產品經濟數字的 pending 一鍵確認。"""

    def _create_product(self, name="虛構回甘烏龍"):
        resp = self.client.post(
            f"/brands/{self.brand['id']}/products/new",
            data={"name": name}, follow_redirects=False,
        )
        product_id = resp.headers["location"].split("/products/")[1].split("?")[0]
        return product_id

    def _rescan(self, product_id, url="https://example.com/products/oolong-v2"):
        return self.client.post(
            f"/brands/{self.brand['id']}/products/{product_id}/rescan",
            data={"url": url}, follow_redirects=False,
        )

    def test_url_prefilled_from_latest_product_source_reference(self):
        product_ai.PROVIDER = FakeProvider(response=_fake_response(_GOOD_FACTS))
        resp = self._post()
        product_id = resp.headers["location"].split("/products/")[1].split("?")[0]
        page = self.client.get(f"/brands/{self.brand['id']}/products/{product_id}")
        self.assertIn('value="https://example.com/products/oolong"', page.text)

    def test_rescan_success_adds_facts_and_skips_same_label(self):
        product_ai.PROVIDER = FakeProvider(response=_fake_response(_GOOD_FACTS))
        resp = self._post()
        product_id = resp.headers["location"].split("/products/")[1].split("?")[0]
        self.assertEqual(len(bi_repo.list_product_facts(main.conn, self.brand["id"], product_id)), 2)

        product_ai.PROVIDER = FakeProvider(response=_fake_response(_RESCAN_ONE_OVERLAP_ONE_NEW))
        resp = self._rescan(product_id)
        self.assertEqual(resp.status_code, 303)
        facts = bi_repo.list_product_facts(main.conn, self.brand["id"], product_id)
        # 原本 2 條 + 重跑新增 1 條（「上班族」），「單一品項」同 label 已存在被跳過。
        self.assertEqual(len(facts), 3)
        labels = [f["label"] for f in facts]
        self.assertEqual(labels.count("單一品項"), 1)
        self.assertIn("上班族", labels)

    def test_rescan_missing_key_shows_human_error_and_adds_nothing(self):
        product_id = self._create_product()
        product_ai.PROVIDER = AnthropicProvider()
        resp = self._rescan(product_id)
        self.assertEqual(resp.status_code, 303)
        page = self.client.get(resp.headers["location"], follow_redirects=True)
        self.assertIn(MISSING_KEY_MESSAGE, page.text)
        self.assertEqual(bi_repo.list_product_facts(main.conn, self.brand["id"], product_id), [])

    def test_rescan_over_budget_blocks_before_any_llm_call(self):
        product_id = self._create_product()
        coresettings.set_setting(main.conn, coresettings.INTAKE_BUDGET_SETTING, "0.1")
        product_ai.PROVIDER = FakeProvider(response=_fake_response("不該被呼叫"))
        resp = self._rescan(product_id)
        self.assertEqual(resp.status_code, 303)
        page = self.client.get(resp.headers["location"], follow_redirects=True)
        self.assertIn("花費上限", page.text)
        self.assertEqual(bi_repo.list_product_facts(main.conn, self.brand["id"], product_id), [])
        self.assertEqual(product_ai.PROVIDER.calls, [])

    def test_price_found_creates_pending_economics_with_source(self):
        product_id = self._create_product()
        product_ai.PROVIDER = FakeProvider(response=_fake_response(_FACTS_WITH_PRICE))
        resp = self._rescan(product_id)
        self.assertEqual(resp.status_code, 303)
        economics = bi_repo.get_product_economics(main.conn, self.brand["id"], product_id)
        self.assertIsNotNone(economics)
        self.assertEqual(economics["status"], "pending")
        self.assertEqual(economics["selling_price"], 690.0)
        self.assertEqual(economics["currency"], "TWD")  # LLM 給小寫，存進去要正規化成大寫
        self.assertIsNotNone(economics["source_reference_id"])
        src = bi_repo.get_source_reference(main.conn, self.brand["id"], economics["source_reference_id"])
        self.assertEqual(src["title"], "https://example.com/products/oolong-v2")

    def test_price_missing_leaves_economics_untouched(self):
        product_id = self._create_product()
        product_ai.PROVIDER = FakeProvider(response=_fake_response(_GOOD_FACTS))  # 沒有 price 欄位
        resp = self._rescan(product_id)
        self.assertEqual(resp.status_code, 303)
        self.assertIsNone(bi_repo.get_product_economics(main.conn, self.brand["id"], product_id))

    def test_existing_economics_not_overwritten_by_scan(self):
        product_id = self._create_product()
        bi_repo.save_product_economics(
            main.conn, self.brand["id"], product_id, actor=ACTOR,
            selling_price=999.0, currency="USD", confirmed_by=ACTOR,
        )
        product_ai.PROVIDER = FakeProvider(response=_fake_response(_FACTS_WITH_PRICE))
        resp = self._rescan(product_id)
        self.assertEqual(resp.status_code, 303)
        economics = bi_repo.get_product_economics(main.conn, self.brand["id"], product_id)
        # 既有數字是使用者資產：售價、幣別、狀態都不能被快掃結果覆蓋或新建第二筆。
        self.assertEqual(economics["selling_price"], 999.0)
        self.assertEqual(economics["currency"], "USD")
        self.assertEqual(economics["status"], "confirmed")

    def test_pending_economics_one_click_confirm(self):
        product_id = self._create_product()
        product_ai.PROVIDER = FakeProvider(response=_fake_response(_FACTS_WITH_PRICE))
        self._rescan(product_id)
        economics = bi_repo.get_product_economics(main.conn, self.brand["id"], product_id)
        self.assertEqual(economics["status"], "pending")

        resp = self.client.post(
            f"/brands/{self.brand['id']}/products/{product_id}/economics/confirm",
            follow_redirects=False,
        )
        self.assertEqual(resp.status_code, 303)
        economics = bi_repo.get_product_economics(main.conn, self.brand["id"], product_id)
        self.assertEqual(economics["status"], "confirmed")
        self.assertEqual(economics["confirmed_by"], OPERATOR)


if __name__ == "__main__":
    unittest.main()
