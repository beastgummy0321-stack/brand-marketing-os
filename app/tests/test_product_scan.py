"""app/tests/test_product_scan.py — 產品快掃（GitHub issue #6）。

見產品調研 API、app/intake/ai.py 的
run_product_scan。全程用 FakeProvider＋假抓取（monkeypatch product_ai.fetch_url），
不發任何真實網路請求。品牌／產品名一律虛構，絕不可用 Beast Gummy。
"""

import json
import os
import time
import unittest
from unittest import mock

from fastapi.testclient import TestClient

import app.main as main
import app.shared.web as web
from app.brand_intelligence import repository as bi_repo
from app.brand_web import product_ai_calls as product_ai
from app.core import settings as coresettings
from app.llm.providers import (
    MISSING_KEY_MESSAGE,
    AnthropicProvider,
    FakeProvider,
    ProviderResponse,
    Usage,
)

OPERATOR = "本人"  # 票 03-1：production 端已刪除，測試沿用舊字串值當 actor 名稱
DEV_USER_ID = "00000000-0000-0000-0000-000000000001"  # dev token 種子使用者（conftest.py）
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
        web.conn.execute("DELETE FROM app_setting")
        web.conn.commit()
        self._envpatch = mock.patch.dict(os.environ, {}, clear=False)
        self._envpatch.start()
        os.environ.pop("ANTHROPIC_API_KEY", None)
        os.environ.pop("BRAND_OS_LLM_MODEL", None)
        self._orig_provider = product_ai.PROVIDER
        self._orig_fetch = product_ai.fetch_url
        product_ai.fetch_url = lambda url: (True, "假抓到的產品頁文字節錄。")
        self.brand = bi_repo.create_brand(web.conn, name="虛構茶研所", client_name="測試客戶", actor=ACTOR)

    def tearDown(self):
        product_ai.PROVIDER = self._orig_provider
        product_ai.fetch_url = self._orig_fetch
        self._envpatch.stop()

    def _post(self, name="虛構回甘烏龍", url="https://example.com/products/oolong"):
        response = self.client.post(
            f"/api/products/brands/{self.brand['id']}/research",
            json={"name": name, "source_url": url},
        )
        self.assertEqual(response.status_code, 202)
        product_id = response.json()["product_id"]
        return product_id, self._wait_for_research(product_id)

    def _wait_for_research(self, product_id):
        deadline = time.time() + 5
        while time.time() < deadline:
            response = self.client.get(
                f"/api/products/brands/{self.brand['id']}/products/{product_id}/research-status"
            )
            state = response.json()["data"]
            if state["status"] != "running":
                return state
            time.sleep(0.02)
        self.fail("產品調研背景任務逾時")


class ProductScanTest(_BaseProductScanTest):
    def test_scan_success_creates_product_and_pending_facts_with_source(self):
        product_ai.PROVIDER = FakeProvider(response=_fake_response(_GOOD_FACTS))
        product_id, state = self._post()
        self.assertEqual(state["status"], "done")
        products = bi_repo.list_products(web.conn, self.brand["id"])
        self.assertEqual(len(products), 1)
        self.assertEqual(products[0]["id"], product_id)
        self.assertEqual(products[0]["name"], "虛構回甘烏龍")

        facts = bi_repo.list_product_facts(web.conn, self.brand["id"], product_id)
        self.assertEqual(len(facts), 2)
        for f in facts:
            self.assertEqual(f["status"], "pending")
            self.assertIsNotNone(f["source_reference_id"])
            src = bi_repo.get_source_reference(web.conn, self.brand["id"], f["source_reference_id"])
            self.assertEqual(src["title"], "https://example.com/products/oolong")

    def test_missing_key_shows_human_error_and_creates_nothing(self):
        product_ai.PROVIDER = AnthropicProvider()  # 無金鑰：送網路請求之前就會擋下
        _product_id, state = self._post()
        self.assertEqual(state["status"], "failed")
        self.assertIn(MISSING_KEY_MESSAGE, state["error"])

    def test_unparseable_reply_is_honest_failure_and_creates_nothing(self):
        product_ai.PROVIDER = FakeProvider(response=_fake_response("這不是 JSON，也不是允許的分類"))
        _product_id, state = self._post()
        self.assertEqual(state["status"], "failed")
        self.assertIn(product_ai.PARSE_FAIL_MESSAGE, state["error"])

    def test_over_budget_blocks_before_any_llm_call(self):
        coresettings.set_setting(web.conn, coresettings.INTAKE_BUDGET_SETTING, "0.1")
        product_ai.PROVIDER = FakeProvider(response=_fake_response("不該被呼叫"))
        _product_id, state = self._post()
        self.assertEqual(state["status"], "failed")
        self.assertIn("花費上限", state["error"])
        self.assertEqual(product_ai.PROVIDER.calls, [])

    def test_blank_url_manual_create_untouched(self):
        """不填網址：原本的「新增這個產品」（純手動）行為完全不變，走 /products/new。"""
        resp = self.client.post(f"/api/products/brands/{self.brand['id']}",
                                json={"name": "虛構純手動產品"})
        self.assertEqual(resp.status_code, 200)
        products = bi_repo.list_products(web.conn, self.brand["id"])
        self.assertEqual(len(products), 1)
        self.assertEqual(bi_repo.list_product_facts(web.conn, self.brand["id"], products[0]["id"]), [])


class ProductRescanTest(_BaseProductScanTest):
    """AI 再次調研（issue 擴充）：快掃同時抽 price、
    產品經濟數字的 pending 一鍵確認。"""

    def _create_product(self, name="虛構回甘烏龍"):
        return bi_repo.create_product(web.conn, self.brand["id"], name=name, actor=ACTOR)["id"]

    def _rescan(self, product_id, url="https://example.com/products/oolong-v2"):
        response = self.client.post(
            f"/api/products/brands/{self.brand['id']}/products/{product_id}/rescan",
            json={"source_url": url},
        )
        self.assertEqual(response.status_code, 202)
        return self._wait_for_research(product_id)

    def test_url_prefilled_from_latest_product_source_reference(self):
        product_ai.PROVIDER = FakeProvider(response=_fake_response(_GOOD_FACTS))
        product_id, state = self._post()
        self.assertEqual(state["status"], "done")
        detail = self.client.get(f"/api/products/brands/{self.brand['id']}/products/{product_id}").json()["data"]
        self.assertEqual(detail["latest_source_url"], "https://example.com/products/oolong")

    def test_rescan_success_adds_facts_and_skips_same_label(self):
        product_ai.PROVIDER = FakeProvider(response=_fake_response(_GOOD_FACTS))
        product_id, state = self._post()
        self.assertEqual(state["status"], "done")
        self.assertEqual(len(bi_repo.list_product_facts(web.conn, self.brand["id"], product_id)), 2)

        product_ai.PROVIDER = FakeProvider(response=_fake_response(_RESCAN_ONE_OVERLAP_ONE_NEW))
        state = self._rescan(product_id)
        self.assertEqual(state["status"], "done")
        facts = bi_repo.list_product_facts(web.conn, self.brand["id"], product_id)
        # 原本 2 條 + 重跑新增 1 條（「上班族」），「單一品項」同 label 已存在被跳過。
        self.assertEqual(len(facts), 3)
        labels = [f["label"] for f in facts]
        self.assertEqual(labels.count("單一品項"), 1)
        self.assertIn("上班族", labels)

    def test_rescan_missing_key_shows_human_error_and_adds_nothing(self):
        product_id = self._create_product()
        product_ai.PROVIDER = AnthropicProvider()
        state = self._rescan(product_id)
        self.assertEqual(state["status"], "failed")
        self.assertIn(MISSING_KEY_MESSAGE, state["error"])
        self.assertEqual(bi_repo.list_product_facts(web.conn, self.brand["id"], product_id), [])

    def test_rescan_over_budget_blocks_before_any_llm_call(self):
        product_id = self._create_product()
        coresettings.set_setting(web.conn, coresettings.INTAKE_BUDGET_SETTING, "0.1")
        product_ai.PROVIDER = FakeProvider(response=_fake_response("不該被呼叫"))
        state = self._rescan(product_id)
        self.assertEqual(state["status"], "failed")
        self.assertIn("花費上限", state["error"])
        self.assertEqual(bi_repo.list_product_facts(web.conn, self.brand["id"], product_id), [])
        self.assertEqual(product_ai.PROVIDER.calls, [])

    def test_price_found_creates_pending_economics_with_source(self):
        product_id = self._create_product()
        product_ai.PROVIDER = FakeProvider(response=_fake_response(_FACTS_WITH_PRICE))
        state = self._rescan(product_id)
        self.assertEqual(state["status"], "done")
        economics = bi_repo.get_product_economics(web.conn, self.brand["id"], product_id)
        self.assertIsNotNone(economics)
        self.assertEqual(economics["status"], "pending")
        self.assertEqual(economics["selling_price"], 690.0)
        self.assertEqual(economics["currency"], "TWD")  # LLM 給小寫，存進去要正規化成大寫
        self.assertIsNotNone(economics["source_reference_id"])
        src = bi_repo.get_source_reference(web.conn, self.brand["id"], economics["source_reference_id"])
        self.assertEqual(src["title"], "https://example.com/products/oolong-v2")

    def test_price_missing_leaves_economics_untouched(self):
        product_id = self._create_product()
        product_ai.PROVIDER = FakeProvider(response=_fake_response(_GOOD_FACTS))  # 沒有 price 欄位
        state = self._rescan(product_id)
        self.assertEqual(state["status"], "done")
        self.assertIsNone(bi_repo.get_product_economics(web.conn, self.brand["id"], product_id))

    def test_existing_economics_not_overwritten_by_scan(self):
        product_id = self._create_product()
        bi_repo.save_product_economics(
            web.conn, self.brand["id"], product_id, actor=ACTOR,
            selling_price=999.0, currency="USD", confirmed_by=ACTOR,
        )
        product_ai.PROVIDER = FakeProvider(response=_fake_response(_FACTS_WITH_PRICE))
        state = self._rescan(product_id)
        self.assertEqual(state["status"], "done")
        economics = bi_repo.get_product_economics(web.conn, self.brand["id"], product_id)
        # 既有數字是使用者資產：售價、幣別、狀態都不能被快掃結果覆蓋或新建第二筆。
        self.assertEqual(economics["selling_price"], 999.0)
        self.assertEqual(economics["currency"], "USD")
        self.assertEqual(economics["status"], "confirmed")

    def test_pending_economics_one_click_confirm(self):
        product_id = self._create_product()
        product_ai.PROVIDER = FakeProvider(response=_fake_response(_FACTS_WITH_PRICE))
        self.assertEqual(self._rescan(product_id)["status"], "done")
        economics = bi_repo.get_product_economics(web.conn, self.brand["id"], product_id)
        self.assertEqual(economics["status"], "pending")

        resp = self.client.post(
            f"/api/products/brands/{self.brand['id']}/products/{product_id}/economics/confirm",
        )
        self.assertEqual(resp.status_code, 204)
        economics = bi_repo.get_product_economics(web.conn, self.brand["id"], product_id)
        self.assertEqual(economics["status"], "confirmed")
        self.assertEqual(economics["confirmed_by"], DEV_USER_ID)


if __name__ == "__main__":
    unittest.main()
