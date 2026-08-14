# -*- coding: utf-8 -*-
"""app/tests/test_products_api.py — 產品清單＋產品詳情 JSON API（票 B2-products 第二段）。

見 app/brand_intelligence/routes_products.py。全程用 FakeProvider＋假抓取
（monkeypatch product_ai.fetch_url），不發任何真實網路請求。品牌／產品名一律虛構。
"""

import atexit
import json
import os
import shutil
import tempfile
import threading
import time
import unittest
from pathlib import Path

# 先備好暫存 DB 的環境變數，才能 import app.main（它在 import 當下就會連線＋跑 migrations）。
_tmpdir = tempfile.mkdtemp(prefix="brand_os_products_api_")
os.environ.setdefault("ANTHROPIC_API_KEY", "sk-ant-fake-products-api-test")

from fastapi.testclient import TestClient  # noqa: E402

import app.main as main  # noqa: E402
from app.brand_intelligence import product_ai  # noqa: E402
from app.brand_intelligence import repository as repo  # noqa: E402
from app.brand_intelligence import routes_products as rp  # noqa: E402
from app.core import interrupts as core_interrupts  # noqa: E402
from app.core import settings as coresettings  # noqa: E402
from app.llm.providers import FakeProvider, ProviderResponse, Usage  # noqa: E402
from app.shared.web import OPERATOR  # noqa: E402



def _cleanup():
    try:
        main.conn.close()
    except Exception:
        pass
    shutil.rmtree(_tmpdir, ignore_errors=True)


atexit.register(_cleanup)

ACTOR = "測試員"


def _fake_response(text: str) -> ProviderResponse:
    return ProviderResponse(output_text=text, structured=None,
                             usage=Usage(input_tokens=10, output_tokens=10), stop_reason="end_turn")


_GOOD_FACTS = json.dumps({"facts": [
    {"fact_type": "產品線", "label": "單一品項", "value": "目前只有一款 60 錠裝。"},
    {"fact_type": "價格帶", "label": "中價位", "value": "單罐約 690 元，落在市場中段。"},
]}, ensure_ascii=False)


class _BaseProductsApiTest(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(main.app)
        main.conn.execute("DELETE FROM app_setting")
        main.conn.commit()
        rp._research_jobs.clear()
        self._orig_provider = product_ai.PROVIDER
        self._orig_fetch = product_ai.fetch_url
        product_ai.fetch_url = lambda url: (True, "假抓到的產品頁文字節錄。")
        self.brand = repo.create_brand(main.conn, name="虛構茶研所－API測試", client_name="測試客戶",
                                        actor=ACTOR)
        self.bid = self.brand["id"]

    def tearDown(self):
        product_ai.PROVIDER = self._orig_provider
        product_ai.fetch_url = self._orig_fetch
        rp._research_jobs.clear()

    def _create_product(self, name="虛構回甘烏龍"):
        resp = self.client.post(f"/api/products/brands/{self.bid}", json={"name": name, "source_url": ""})
        self.assertEqual(resp.status_code, 200)
        return resp.json()["id"]


class ProductListTest(_BaseProductsApiTest):
    def test_empty_shape(self):
        resp = self.client.get(f"/api/products/brands/{self.bid}")
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertIn("data", body)
        self.assertIn("generated_at", body)
        self.assertEqual(body["data"], [])

    def test_unknown_brand_is_404(self):
        resp = self.client.get("/api/products/brands/brd_不存在")
        self.assertEqual(resp.status_code, 404)

    def test_list_item_shape_and_counts(self):
        pid = self._create_product()
        repo.create_product_fact(main.conn, self.bid, pid, actor=ACTOR, fact_type="core_info",
                                  label="賣點", value="無糖配方", status="confirmed", confirmed_by=ACTOR)
        repo.create_product_fact(main.conn, self.bid, pid, actor=ACTOR, fact_type="core_info",
                                  label="賣點2", value="無糖配方2", status="pending")
        data = self.client.get(f"/api/products/brands/{self.bid}").json()["data"]
        self.assertEqual(len(data), 1)
        item = data[0]
        self.assertEqual(
            set(item.keys()),
            {"id", "name", "status", "fact_count", "pending_fact_count", "economics_status"},
        )
        self.assertEqual(item["fact_count"], 2)
        self.assertEqual(item["pending_fact_count"], 1)
        self.assertEqual(item["economics_status"], "none")


class ProductCreateTest(_BaseProductsApiTest):
    def test_manual_create_returns_id_and_ignores_source_url(self):
        resp = self.client.post(f"/api/products/brands/{self.bid}",
                                 json={"name": "虛構純手動產品", "source_url": "https://ignored.example"})
        self.assertEqual(resp.status_code, 200)
        pid = resp.json()["id"]
        product = repo.get_product(main.conn, self.bid, pid)
        self.assertEqual(product["name"], "虛構純手動產品")
        self.assertEqual(repo.list_product_facts(main.conn, self.bid, pid), [])

    def test_blank_name_is_rejected(self):
        resp = self.client.post(f"/api/products/brands/{self.bid}", json={"name": "", "source_url": ""})
        self.assertEqual(resp.status_code, 400)
        self.assertIn("error", resp.json())
        self.assertEqual(repo.list_products(main.conn, self.bid), [])


class ProductDetailTest(_BaseProductsApiTest):
    def test_bundle_shape(self):
        pid = self._create_product()
        resp = self.client.get(f"/api/products/brands/{self.bid}/products/{pid}")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()["data"]
        self.assertEqual(
            set(data.keys()),
            {"id", "brand_id", "name", "status", "knowledge_version", "cards",
             "latest_source_url", "economics_pending", "facts", "economics", "rules", "claims"},
        )
        self.assertEqual(len(data["cards"]), 4)
        self.assertEqual(data["economics"], None)
        self.assertEqual(data["economics_pending"], False)

    def test_unknown_product_is_404(self):
        resp = self.client.get(f"/api/products/brands/{self.bid}/products/prd_不存在")
        self.assertEqual(resp.status_code, 404)

    def test_fact_shape_fields(self):
        pid = self._create_product()
        repo.create_product_fact(main.conn, self.bid, pid, actor=ACTOR, fact_type="價格帶",
                                  label="定價", value="中價位", status="confirmed", confirmed_by=ACTOR)
        data = self.client.get(f"/api/products/brands/{self.bid}/products/{pid}").json()["data"]
        self.assertEqual(len(data["facts"]), 1)
        fact = data["facts"][0]
        self.assertEqual(
            set(fact.keys()),
            {"id", "fact_type", "fact_type_label", "label", "value", "status",
             "confirmed_by", "confirmed_at", "source_reference"},
        )
        # AI 快掃寫入的中文詞不在六個內建鍵裡，fallback 原樣顯示（S6.22）
        self.assertEqual(fact["fact_type_label"], "價格帶")


class ArchiveTest(_BaseProductsApiTest):
    def test_toggle_archive_and_restore(self):
        pid = self._create_product()
        resp = self.client.post(f"/api/products/brands/{self.bid}/products/{pid}/archive")
        self.assertEqual(resp.status_code, 204)
        self.assertEqual(repo.get_product(main.conn, self.bid, pid)["status"], "archived")
        resp = self.client.post(f"/api/products/brands/{self.bid}/products/{pid}/archive")
        self.assertEqual(resp.status_code, 204)
        self.assertEqual(repo.get_product(main.conn, self.bid, pid)["status"], "active")


class ResearchBackgroundTest(_BaseProductsApiTest):
    """S6.10–S6.11／S6.17／S6.29–S6.31：AI 調研背景工作狀態機（啟動→輪詢→完成落庫，
    或失敗留空產品）。"""

    def _poll(self, pid: str, timeout: float = 5.0) -> dict:
        deadline = time.time() + timeout
        while time.time() < deadline:
            status = self.client.get(
                f"/api/products/brands/{self.bid}/products/{pid}/research-status"
            ).json()["data"]
            if status["status"] != "running":
                return status
            time.sleep(0.05)
        self.fail("背景任務逾時仍未完成，可能是執行緒沒有真的跑")

    def test_start_returns_immediately_and_creates_product_before_research_finishes(self):
        product_ai.PROVIDER = FakeProvider(response=_fake_response(_GOOD_FACTS))
        started = time.time()
        resp = self.client.post(
            f"/api/products/brands/{self.bid}/research",
            json={"name": "虛構回甘烏龍", "source_url": "https://example.com/products/oolong"},
        )
        elapsed = time.time() - started
        self.assertEqual(resp.status_code, 202)
        self.assertLess(elapsed, 1.0, "POST 不該等 AI 調研跑完才回應")
        pid = resp.json()["product_id"]
        # 產品已經同步建好（見「拿不準的點 1」方案 A），不用等背景跑完。
        self.assertIsNotNone(repo.get_product(main.conn, self.bid, pid))
        status = self._poll(pid)
        self.assertEqual(status["status"], "done")
        self.assertEqual(status["added_count"], 2)

    def test_success_stores_pending_facts_and_notifies(self):
        product_ai.PROVIDER = FakeProvider(response=_fake_response(_GOOD_FACTS))
        resp = self.client.post(
            f"/api/products/brands/{self.bid}/research",
            json={"name": "虛構回甘烏龍二號", "source_url": "https://example.com/products/oolong2"},
        )
        pid = resp.json()["product_id"]
        self._poll(pid)
        facts = repo.list_product_facts(main.conn, self.bid, pid)
        self.assertEqual(len(facts), 2)
        for f in facts:
            self.assertEqual(f["status"], "pending")
        open_items = core_interrupts.list_open(main.conn, brand_id=self.bid)
        matches = [r for r in open_items if r["category"] == "product_research_done"]
        self.assertEqual(len(matches), 1)
        self.assertLessEqual(len(matches[0]["message"]), core_interrupts.MAX_MESSAGE_LEN)

    def test_over_budget_leaves_empty_product_not_deleted(self):
        """拿不準的點 1，方案 A：調研失敗時系統留下一個空產品，不像舊版「失敗就什麼都沒發生」。"""
        coresettings.set_setting(main.conn, coresettings.INTAKE_BUDGET_SETTING, "0.1")
        product_ai.PROVIDER = FakeProvider(response=_fake_response("不該被呼叫"))
        resp = self.client.post(
            f"/api/products/brands/{self.bid}/research",
            json={"name": "虛構會失敗的產品", "source_url": "https://example.com/products/x"},
        )
        self.assertEqual(resp.status_code, 202)
        pid = resp.json()["product_id"]
        # 產品已經建立（同步階段），不因背景調研失敗而消失。
        product = repo.get_product(main.conn, self.bid, pid)
        self.assertIsNotNone(product)
        status = self._poll(pid)
        self.assertEqual(status["status"], "failed")
        self.assertIn("花費上限", status["error"])
        self.assertEqual(repo.list_product_facts(main.conn, self.bid, pid), [])
        self.assertEqual(product_ai.PROVIDER.calls, [])  # 花費檢查擋在呼叫 AI 之前
        open_items = core_interrupts.list_open(main.conn, brand_id=self.bid)
        matches = [r for r in open_items if r["category"] == "product_research_done"]
        self.assertEqual(len(matches), 1)

    def test_bad_url_format_rejected_before_creating_product(self):
        resp = self.client.post(
            f"/api/products/brands/{self.bid}/research",
            json={"name": "虛構產品", "source_url": "not-a-url"},
        )
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(repo.list_products(main.conn, self.bid), [])

    def test_rescan_idempotent_same_key_not_restarted_while_running(self):
        pid = self._create_product()
        product_ai.PROVIDER = FakeProvider(response=_fake_response(_GOOD_FACTS))
        # 用 Event 卡住背景執行緒，保證第二次 POST 送達時第一個 job 一定還是 running——
        # 不能靠「兩次 POST 之間隔多快」這種計時賭運氣（FakeProvider 幾乎瞬間跑完，
        # 背景 job 可能在第二次 POST 送達前就已經轉成 done，那樣「再開一個新 job」其實
        # 是合法行為，不算冪等閘失效，測試會偶發假紅）。
        release = threading.Event()
        orig_fetch = product_ai.fetch_url

        def _blocking_fetch(url):
            release.wait(timeout=5)
            return orig_fetch(url)

        product_ai.fetch_url = _blocking_fetch
        try:
            resp1 = self.client.post(
                f"/api/products/brands/{self.bid}/products/{pid}/rescan",
                json={"source_url": "https://example.com/products/oolong"},
            )
            self.assertEqual(resp1.status_code, 202)
            # 立刻再打一次：同一個 key 已經在跑（卡在 fetch_url 裡），不該重新啟動第二條背景執行緒。
            resp2 = self.client.post(
                f"/api/products/brands/{self.bid}/products/{pid}/rescan",
                json={"source_url": "https://example.com/products/oolong"},
            )
            self.assertEqual(resp2.status_code, 202)
        finally:
            release.set()
        status = self._poll(pid)
        self.assertEqual(status["status"], "done")
        # 只跑成功一次的結果：2 條事實，不是被重複觸發後的 4 條。
        facts = repo.list_product_facts(main.conn, self.bid, pid)
        self.assertEqual(len(facts), 2)
        # 冪等閘真正要擋的是「重複打付費 API」——label 去重只是副作用，不能拿來當唯一證據。
        self.assertEqual(len(product_ai.PROVIDER.calls), 1)

    def test_unknown_key_reports_done_steady_state(self):
        pid = self._create_product()
        resp = self.client.get(f"/api/products/brands/{self.bid}/products/{pid}/research-status")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["data"]["status"], "done")


class ProductFactCrudTest(_BaseProductsApiTest):
    def test_create_edit_confirm_delete(self):
        pid = self._create_product()
        resp = self.client.post(
            f"/api/products/brands/{self.bid}/products/{pid}/facts",
            json={"fact_type": "core_info", "label": "賣點", "value": "無糖配方",
                  "status": "pending", "source_reference": ""},
        )
        self.assertEqual(resp.status_code, 204)
        fact_id = repo.list_product_facts(main.conn, self.bid, pid)[0]["id"]

        resp = self.client.post(
            f"/api/products/brands/{self.bid}/products/{pid}/facts/{fact_id}",
            json={"fact_type": "core_info", "label": "賣點修改", "value": "無糖配方修改",
                  "source_reference": ""},
        )
        self.assertEqual(resp.status_code, 204)
        self.assertEqual(repo.get_product_fact(main.conn, self.bid, pid, fact_id)["label"], "賣點修改")

        resp = self.client.post(
            f"/api/products/brands/{self.bid}/products/{pid}/facts/{fact_id}/confirm",
            json={"confirmed_by": "小陳"},
        )
        self.assertEqual(resp.status_code, 204)
        self.assertEqual(repo.get_product_fact(main.conn, self.bid, pid, fact_id)["status"], "confirmed")

        resp = self.client.post(f"/api/products/brands/{self.bid}/products/{pid}/facts/{fact_id}/delete")
        self.assertEqual(resp.status_code, 204)
        self.assertIsNone(repo.get_product_fact(main.conn, self.bid, pid, fact_id))

    def test_missing_label_is_rejected(self):
        pid = self._create_product()
        resp = self.client.post(
            f"/api/products/brands/{self.bid}/products/{pid}/facts",
            json={"fact_type": "core_info", "label": "", "value": "x", "status": "pending"},
        )
        self.assertEqual(resp.status_code, 400)


class EconomicsTest(_BaseProductsApiTest):
    def test_save_and_confirm(self):
        pid = self._create_product()
        resp = self.client.post(
            f"/api/products/brands/{self.bid}/products/{pid}/economics",
            json={"selling_price": 690, "fixed_cost": 0, "unit_variable_cost": 0, "shipping_cost": 0,
                  "currency": "TWD", "cpa_roas_basis": "", "effective_from": "", "confirmed_by": "小陳"},
        )
        self.assertEqual(resp.status_code, 204)
        economics = repo.get_product_economics(main.conn, self.bid, pid)
        self.assertEqual(economics["selling_price"], 690.0)
        self.assertEqual(economics["status"], "confirmed")

        # 用 AI 快掃路徑建一筆 pending，測一鍵確認。
        repo.create_pending_product_economics(main.conn, self.bid, pid, actor=ACTOR,
                                               selling_price=100, currency="TWD", source_reference_id=None)
        resp = self.client.post(f"/api/products/brands/{self.bid}/products/{pid}/economics/confirm")
        self.assertEqual(resp.status_code, 204)
        self.assertEqual(repo.get_product_economics(main.conn, self.bid, pid)["confirmed_by"], OPERATOR)

    def test_non_numeric_selling_price_rejected(self):
        pid = self._create_product()
        resp = self.client.post(
            f"/api/products/brands/{self.bid}/products/{pid}/economics",
            json={"selling_price": "not-a-number", "fixed_cost": 0, "unit_variable_cost": 0,
                  "shipping_cost": 0, "currency": "TWD", "cpa_roas_basis": "", "effective_from": "",
                  "confirmed_by": "小陳"},
        )
        self.assertEqual(resp.status_code, 400)
        self.assertIsNone(repo.get_product_economics(main.conn, self.bid, pid))


class HandoffTest(_BaseProductsApiTest):
    def test_prompt_get(self):
        pid = self._create_product()
        resp = self.client.get(f"/api/products/brands/{self.bid}/products/{pid}/handoff")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("prompt_text", resp.json()["data"])

    def test_direct_parse_success(self):
        pid = self._create_product()
        reply = _GOOD_FACTS
        resp = self.client.post(
            f"/api/products/brands/{self.bid}/products/{pid}/handoff", json={"reply_text": reply},
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["added_count"], 2)
        self.assertEqual(len(repo.list_product_facts(main.conn, self.bid, pid)), 2)

    def test_blank_reply_rejected(self):
        pid = self._create_product()
        resp = self.client.post(
            f"/api/products/brands/{self.bid}/products/{pid}/handoff", json={"reply_text": "  "},
        )
        self.assertEqual(resp.status_code, 400)

    def test_unparseable_reply_falls_back_to_ai_fix(self):
        pid = self._create_product()
        product_ai.PROVIDER = FakeProvider(response=_fake_response(_GOOD_FACTS))
        resp = self.client.post(
            f"/api/products/brands/{self.bid}/products/{pid}/handoff",
            json={"reply_text": "這不是 JSON，格式亂掉了"},
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["added_count"], 2)


class DeleteTest(_BaseProductsApiTest):
    def test_impact_list_and_block_when_not_archived(self):
        pid = self._create_product()
        resp = self.client.get(f"/api/products/brands/{self.bid}/products/{pid}/delete")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["data"], [])

        resp = self.client.post(
            f"/api/products/brands/{self.bid}/products/{pid}/delete",
            json={"confirm_name": "虛構回甘烏龍"},
        )
        self.assertEqual(resp.status_code, 400)
        self.assertIn("先把產品封存", resp.json()["error"])

    def test_name_mismatch_and_success(self):
        pid = self._create_product()
        self.client.post(f"/api/products/brands/{self.bid}/products/{pid}/archive")

        resp = self.client.post(
            f"/api/products/brands/{self.bid}/products/{pid}/delete",
            json={"confirm_name": "打錯的名字"},
        )
        self.assertEqual(resp.status_code, 400)
        self.assertIsNotNone(repo.get_product(main.conn, self.bid, pid))

        resp = self.client.post(
            f"/api/products/brands/{self.bid}/products/{pid}/delete",
            json={"confirm_name": "虛構回甘烏龍"},
        )
        self.assertEqual(resp.status_code, 204)
        self.assertIsNone(repo.get_product(main.conn, self.bid, pid))


if __name__ == "__main__":
    unittest.main()
