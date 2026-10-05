"""app/tests/test_products_api.py — 產品清單＋產品詳情 JSON API（票 B2-products 第二段）。

見 app/brand_intelligence/routes_products.py。全程用 FakeProvider＋假抓取
（monkeypatch product_ai.fetch_url），不發任何真實網路請求。品牌／產品名一律虛構。
"""

import json
import os
import time
import unittest
from uuid import uuid4

from fastapi.testclient import TestClient

import app.background as background_module
import app.brand_web as brand_web_module
import app.main as main
import app.shared.web as web
from app.brand_intelligence import repository as repo
from app.brand_web import product_ai_calls as product_ai
from app.core import interrupts as core_interrupts
from app.core import settings as coresettings
from app.core.db import DEV_ORG_ID  # noqa: E402
from app.identity import repository as identity_repo
from app.llm.providers import FakeProvider, ProviderResponse, Usage

OPERATOR = "本人"  # 票 03-1：production 端已刪除，測試沿用舊字串值當 actor 名稱
DEV_USER_ID = "00000000-0000-0000-0000-000000000001"  # dev token 種子使用者（conftest.py）
os.environ.setdefault("ANTHROPIC_API_KEY", "sk-ant-fake-products-api-test")

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
        web.conn.execute("DELETE FROM app_setting")
        web.conn.commit()
        # 票 08：這個測試模組自己有一份 schema（見 conftest.py），要重新掛一次
        # `background.product_scan`——DSN 換了 App 整顆重建，跟 `test_schedule.py`
        # `schedule_module.register_tasks()` 同一個理由。
        brand_web_module.register(main.app)
        self._orig_provider = product_ai.PROVIDER
        self._orig_fetch = product_ai.fetch_url
        product_ai.fetch_url = lambda url: (True, "假抓到的產品頁文字節錄。")
        self.brand = repo.create_brand(web.conn, name="虛構茶研所－API測試", client_name="測試客戶",
                                        actor=ACTOR, org_id=DEV_ORG_ID)
        self.bid = self.brand["id"]

    def tearDown(self):
        product_ai.PROVIDER = self._orig_provider
        product_ai.fetch_url = self._orig_fetch

    def _create_product(self, name="虛構回甘烏龍"):
        resp = self.client.post(f"/api/products/brands/{self.bid}", json={"name": name, "source_url": ""})
        self.assertEqual(resp.status_code, 200)
        return resp.json()["id"]

    def _run_worker(self) -> None:
        """票 08：POST 現在只 enqueue，真正打代理在 worker 裡——先 commit 這個 request
        留下的異動，worker 自己開一條新連線，看不到還沒 commit 的交易（比照
        `test_schedule.py` `_run_worker()`）。"""
        web.conn.commit()
        background_module.app().run_worker(wait=False)


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
        repo.create_product_fact(web.conn, self.bid, pid, actor=ACTOR, fact_type="core_info",
                                  label="賣點", value="無糖配方", status="confirmed", confirmed_by=ACTOR)
        repo.create_product_fact(web.conn, self.bid, pid, actor=ACTOR, fact_type="core_info",
                                  label="賣點2", value="無糖配方2", status="pending")
        data = self.client.get(f"/api/products/brands/{self.bid}").json()["data"]
        self.assertEqual(len(data), 1)
        item = data[0]
        self.assertEqual(
            set(item.keys()),
            {"id", "name", "status", "fact_count", "pending_fact_count", "economics_status", "parent_id"},
        )
        self.assertEqual(item["fact_count"], 2)
        self.assertEqual(item["pending_fact_count"], 1)
        self.assertEqual(item["economics_status"], "none")
        self.assertIsNone(item["parent_id"])


class ProductCreateTest(_BaseProductsApiTest):
    def test_manual_create_returns_id_and_ignores_source_url(self):
        resp = self.client.post(f"/api/products/brands/{self.bid}",
                                 json={"name": "虛構純手動產品", "source_url": "https://ignored.example"})
        self.assertEqual(resp.status_code, 200)
        pid = resp.json()["id"]
        product = repo.get_product(web.conn, self.bid, pid)
        self.assertEqual(product["name"], "虛構純手動產品")
        self.assertEqual(repo.list_product_facts(web.conn, self.bid, pid), [])

    def test_blank_name_is_rejected(self):
        resp = self.client.post(f"/api/products/brands/{self.bid}", json={"name": "", "source_url": ""})
        self.assertEqual(resp.status_code, 400)
        self.assertIn("error", resp.json())
        self.assertEqual(repo.list_products(web.conn, self.bid), [])

    def test_manual_create_with_existing_name_lands_on_existing_product(self):
        """F36-I10 (drill-6 #16): a second manual add with the same name (spacing / case
        variants included) returns the existing product's id and creates no row."""
        first = self._create_product("超能特惠組")
        for variant in ("超能特惠組", " 超能特惠組 ", "超能特惠組\t"):
            resp = self.client.post(f"/api/products/brands/{self.bid}",
                                     json={"name": variant, "source_url": ""})
            self.assertEqual(resp.status_code, 200, variant)
            self.assertEqual(resp.json()["id"], first, repr(variant))
        products = repo.list_products(web.conn, self.bid)
        self.assertEqual([p["id"] for p in products], [first])

    def test_manual_create_after_archive_makes_a_new_active_product(self):
        """An archived same-name product does not block a new active one (Contract W)."""
        first = self._create_product("超能特惠組")
        resp = self.client.post(f"/api/products/brands/{self.bid}/products/{first}/archive")
        self.assertEqual(resp.status_code, 204)
        second = self._create_product("超能特惠組")
        self.assertNotEqual(second, first)
        statuses = {p["id"]: p["status"] for p in repo.list_products(web.conn, self.bid)}
        self.assertEqual(statuses, {first: "archived", second: "active"})


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
        repo.create_product_fact(web.conn, self.bid, pid, actor=ACTOR, fact_type="core_info",
                                  label="定價", value="中價位", status="confirmed", confirmed_by=ACTOR)
        data = self.client.get(f"/api/products/brands/{self.bid}/products/{pid}").json()["data"]
        self.assertEqual(len(data["facts"]), 1)
        fact = data["facts"][0]
        self.assertEqual(
            set(fact.keys()),
            {"id", "fact_type", "fact_type_label", "label", "value", "status",
             "confirmed_by", "confirmed_at", "source_reference"},
        )
        # F50 Contract I: every stored type is a vocab key and reads as its label.
        self.assertEqual(fact["fact_type_label"], "核心資訊")
        # F47-I03: a typed confirmer name shows as typed.
        self.assertEqual(fact["confirmed_by"], ACTOR)

    def test_confirmer_user_id_reads_as_the_members_email(self):
        """F47-I03 (drill-10 外觀 #11): 「確認人」 never shows a user id -- a stored member id reads as
        that member's e-mail (facts and economics); an id that is not a member of this org reads as a
        former member, never the raw id."""
        member = uuid4()
        email = f"confirmer-{member.hex[:8]}@example.com"
        identity_repo.create_user(web.conn, member, email)
        identity_repo.create_membership(web.conn, DEV_ORG_ID, member, "member")
        stranger = str(uuid4())
        pid = self._create_product()
        repo.create_product_fact(web.conn, self.bid, pid, actor=ACTOR, fact_type="core_info",
                                  label="成員確認", value="v", status="confirmed", confirmed_by=str(member))
        repo.create_product_fact(web.conn, self.bid, pid, actor=ACTOR, fact_type="core_info",
                                  label="外人確認", value="v", status="confirmed", confirmed_by=stranger)
        repo.save_product_economics(web.conn, self.bid, pid, actor=ACTOR, selling_price=690,
                                    currency="TWD", confirmed_by=str(member))
        data = self.client.get(f"/api/products/brands/{self.bid}/products/{pid}").json()["data"]
        by_label = {f["label"]: f["confirmed_by"] for f in data["facts"]}
        self.assertEqual(by_label["成員確認"], email)
        self.assertEqual(by_label["外人確認"], "已不在這個組織的成員")
        self.assertEqual(data["economics"]["confirmed_by"], email)


class ArchiveTest(_BaseProductsApiTest):
    def test_toggle_archive_and_restore(self):
        pid = self._create_product()
        resp = self.client.post(f"/api/products/brands/{self.bid}/products/{pid}/archive")
        self.assertEqual(resp.status_code, 204)
        self.assertEqual(repo.get_product(web.conn, self.bid, pid)["status"], "archived")
        resp = self.client.post(f"/api/products/brands/{self.bid}/products/{pid}/archive")
        self.assertEqual(resp.status_code, 204)
        self.assertEqual(repo.get_product(web.conn, self.bid, pid)["status"], "active")


class ResearchBackgroundTest(_BaseProductsApiTest):
    """S6.10–S6.11／S6.17／S6.29–S6.31：AI 調研佇列工作狀態機（票 08：從行程內
    dict＋thread 搬上 `app.background` 佇列，啟動→跑 worker→GET 讀最終狀態，或失敗
    留空產品）。"""

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
        # 產品已經同步建好（見「拿不準的點 1」方案 A），不用等 worker 跑完。
        self.assertIsNotNone(repo.get_product(web.conn, self.bid, pid))
        self._run_worker()
        status = self.client.get(
            f"/api/products/brands/{self.bid}/products/{pid}/research-status"
        ).json()["data"]
        self.assertEqual(status["status"], "done")

    def test_success_stores_pending_facts_and_notifies(self):
        product_ai.PROVIDER = FakeProvider(response=_fake_response(_GOOD_FACTS))
        resp = self.client.post(
            f"/api/products/brands/{self.bid}/research",
            json={"name": "虛構回甘烏龍二號", "source_url": "https://example.com/products/oolong2"},
        )
        pid = resp.json()["product_id"]
        self._run_worker()
        facts = repo.list_product_facts(web.conn, self.bid, pid)
        self.assertEqual(len(facts), 2)
        for f in facts:
            self.assertEqual(f["status"], "pending")
        open_items = core_interrupts.list_open(web.conn, org_id=DEV_ORG_ID, brand_id=self.bid)
        matches = [r for r in open_items if r["category"] == "product_research_done"]
        self.assertEqual(len(matches), 1)
        self.assertLessEqual(len(matches[0]["message"]), core_interrupts.MAX_MESSAGE_LEN)

    def test_over_budget_rejected_synchronously_leaves_empty_product_not_deleted(self):
        """拿不準的點 1，方案 A：調研失敗時系統留下一個空產品，不像舊版「失敗就什麼都沒發生」。

        票 08：超預算檢查從背景工作搬到 POST 端點同步做（見 `routes_products.py`
        `product_research_start()` 檔頭）——`gateway.run_task()` 命中花費上限時故意不寫
        任何 llm_task 列，佇列讀法沒有第二個地方能誠實回報這個失敗原因，所以提前到
        enqueue 之前，跟 `customer_voice_submit()`／`app/schedule/routes.py` 的
        `check_spend_cap()` 同一個次序。"""
        coresettings.set_setting(web.conn, coresettings.INTAKE_BUDGET_SETTING, "0.1", org_id=DEV_ORG_ID)
        product_ai.PROVIDER = FakeProvider(response=_fake_response("不該被呼叫"))
        resp = self.client.post(
            f"/api/products/brands/{self.bid}/research",
            json={"name": "虛構會失敗的產品", "source_url": "https://example.com/products/x"},
        )
        self.assertEqual(resp.status_code, 422)
        self.assertIn("US$", resp.json()["error"])
        # 產品已經建立（同步階段），不因超預算而消失——422 的回應本身不帶 product_id
        # （這不是票要保留形狀的三支狀態端點之一），從清單反查剛建立的那一個。
        products = repo.list_products(web.conn, self.bid)
        self.assertEqual(len(products), 1)
        pid = products[0]["id"]
        self.assertEqual(repo.list_product_facts(web.conn, self.bid, pid), [])
        self.assertEqual(product_ai.PROVIDER.calls, [])  # 花費檢查擋在呼叫 AI 之前
        status = self.client.get(
            f"/api/products/brands/{self.bid}/products/{pid}/research-status"
        ).json()["data"]
        self.assertEqual(status["status"], "done")  # 從沒排進佇列，穩態預設

    def test_bad_url_format_rejected_before_creating_product(self):
        resp = self.client.post(
            f"/api/products/brands/{self.bid}/research",
            json={"name": "虛構產品", "source_url": "not-a-url"},
        )
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(repo.list_products(web.conn, self.bid), [])

    def test_a_scheme_alone_is_not_a_product_page(self):
        """F50 Contract I: research and rescan check the address with `input_rules.url`."""
        sentence = "產品頁網址「https://」不是完整的網址，請從 https:// 開始，例如 https://example.com。"
        resp = self.client.post(f"/api/products/brands/{self.bid}/research",
                                json={"name": "虛構產品", "source_url": "https://"})
        self.assertEqual((resp.status_code, resp.json()), (400, {"error": sentence}))
        self.assertEqual(repo.list_products(web.conn, self.bid), [])
        pid = self._create_product()
        resp = self.client.post(f"/api/products/brands/{self.bid}/products/{pid}/rescan",
                                json={"source_url": "https://"})
        self.assertEqual((resp.status_code, resp.json()), (400, {"error": sentence}))

    def test_rescan_blocked_with_409_while_a_scan_is_already_queued(self):
        """票 08：procrastinate 的 `queueing_lock`（`product_scan:{product_id}`）擋
        第二次按下去——不再需要 Event 卡住背景執行緒才能驗證這件事：第一個請求
        enqueue 成功、還沒被 worker 撿走（todo）的當下，第二個請求的 `enqueue()`
        直接回 False，跟 `app/schedule/routes.py` 三支端點同一個 409 語意。"""
        pid = self._create_product()
        product_ai.PROVIDER = FakeProvider(response=_fake_response(_GOOD_FACTS))
        resp1 = self.client.post(
            f"/api/products/brands/{self.bid}/products/{pid}/rescan",
            json={"source_url": "https://example.com/products/oolong"},
        )
        self.assertEqual(resp1.status_code, 202)
        resp2 = self.client.post(
            f"/api/products/brands/{self.bid}/products/{pid}/rescan",
            json={"source_url": "https://example.com/products/oolong"},
        )
        self.assertEqual(resp2.status_code, 409)

        self._run_worker()
        status = self.client.get(
            f"/api/products/brands/{self.bid}/products/{pid}/research-status"
        ).json()["data"]
        self.assertEqual(status["status"], "done")
        # 只跑成功一次的結果：2 條事實，不是被重複觸發後的 4 條。
        facts = repo.list_product_facts(web.conn, self.bid, pid)
        self.assertEqual(len(facts), 2)
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
        fact_id = repo.list_product_facts(web.conn, self.bid, pid)[0]["id"]

        resp = self.client.post(
            f"/api/products/brands/{self.bid}/products/{pid}/facts/{fact_id}",
            json={"fact_type": "core_info", "label": "賣點修改", "value": "無糖配方修改",
                  "source_reference": ""},
        )
        self.assertEqual(resp.status_code, 204)
        self.assertEqual(repo.get_product_fact(web.conn, self.bid, pid, fact_id)["label"], "賣點修改")

        resp = self.client.post(
            f"/api/products/brands/{self.bid}/products/{pid}/facts/{fact_id}/confirm",
            json={"confirmed_by": "小陳"},
        )
        self.assertEqual(resp.status_code, 204)
        self.assertEqual(repo.get_product_fact(web.conn, self.bid, pid, fact_id)["status"], "confirmed")

        resp = self.client.post(f"/api/products/brands/{self.bid}/products/{pid}/facts/{fact_id}/delete")
        self.assertEqual(resp.status_code, 204)
        self.assertIsNone(repo.get_product_fact(web.conn, self.bid, pid, fact_id))

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
                  "currency": "TWD", "effective_from": "", "confirmed_by": "小陳"},
        )
        self.assertEqual(resp.status_code, 204)
        economics = repo.get_product_economics(web.conn, self.bid, pid)
        self.assertEqual(economics["selling_price"], 690.0)
        self.assertEqual(economics["status"], "confirmed")

        # 用 AI 快掃路徑建一筆 pending，測一鍵確認。
        repo.create_pending_product_economics(web.conn, self.bid, pid, actor=ACTOR,
                                               selling_price=100, currency="TWD", source_reference_id=None)
        resp = self.client.post(f"/api/products/brands/{self.bid}/products/{pid}/economics/confirm")
        self.assertEqual(resp.status_code, 204)
        self.assertEqual(repo.get_product_economics(web.conn, self.bid, pid)["confirmed_by"], DEV_USER_ID)

    def test_non_numeric_selling_price_rejected(self):
        pid = self._create_product()
        resp = self.client.post(
            f"/api/products/brands/{self.bid}/products/{pid}/economics",
            json={"selling_price": "not-a-number", "fixed_cost": 0, "unit_variable_cost": 0,
                  "shipping_cost": 0, "currency": "TWD", "effective_from": "",
                  "confirmed_by": "小陳"},
        )
        self.assertEqual(resp.status_code, 400)
        self.assertIsNone(repo.get_product_economics(web.conn, self.bid, pid))

    def _save(self, pid: str, **money):
        body = {"selling_price": 690, "fixed_cost": 0, "unit_variable_cost": 0, "shipping_cost": 0,
                "currency": "TWD", "effective_from": "", "confirmed_by": "小陳", **money}
        return self.client.post(f"/api/products/brands/{self.bid}/products/{pid}/economics", json=body)

    def test_store_keeps_what_was_sent_or_refuses_naming_the_field(self):
        """F47 Contract A (drill-10 V3): price 0 and a negative cost are refused with the field
        sentence (nothing saved); shipping is >= 0 on every path (lead decision) and 0 is kept."""
        pid = self._create_product()
        for field, value, sentence in (("selling_price", 0, "售價要大於 0。"),
                                       ("unit_variable_cost", -1, "單位變動成本不能是負數。"),
                                       ("fixed_cost", -1, "固定成本不能是負數。"),
                                       ("shipping_cost", -20, "運費不能是負數。")):
            resp = self._save(pid, **{field: value})
            # F47-I03: the sentence also comes keyed by its field, so the form shows it under that field.
            self.assertEqual((resp.status_code, resp.json()),
                             (400, {"error": sentence, "field_errors": {field: sentence}}))
        self.assertIsNone(repo.get_product_economics(web.conn, self.bid, pid))

        self.assertEqual(self._save(pid, shipping_cost=0).status_code, 204)
        self.assertEqual(repo.get_product_economics(web.conn, self.bid, pid, raw=True)["shipping_cost"], 0)

    def test_dates_and_close_rate_go_through_the_one_table(self):
        """F50 Contract I: 生效日 is an ISO date (a non-ISO one used to be a 500) and 成交率 keeps
        its 0–1 range through `within`; each refusal is keyed by its field, nothing is saved."""
        pid = self._create_product()
        for field, value, sentence in (
                ("effective_from", "01/06/2026", "生效日請用 YYYY-MM-DD 格式（例如 2026-10-05）。"),
                ("close_rate", 0, "成交率要大於 0、最多 1（例如 0.2＝20%）。"),
                ("close_rate", 20, "成交率要大於 0、最多 1（例如 0.2＝20%）。")):
            resp = self._save(pid, **{field: value})
            self.assertEqual((resp.status_code, resp.json()),
                             (400, {"error": sentence, "field_errors": {field: sentence}}))
        self.assertIsNone(repo.get_product_economics(web.conn, self.bid, pid))
        self.assertEqual(self._save(pid, effective_from="2026-01-06", close_rate=0.2).status_code, 204)
        raw = repo.get_product_economics(web.conn, self.bid, pid, raw=True)
        self.assertEqual((str(raw["effective_from"]), float(raw["close_rate"])), ("2026-01-06", 0.2))

    def test_store_refuses_a_zero_cap_and_a_price_above_the_list_price(self):
        """F50 Contract I: the economics store runs the same rules as product onboarding."""
        pid = self._create_product()
        for money, sentence in (({"cap_per_sale": 0}, "每筆上限要大於 0。"),
                                ({"selling_price": 1280, "list_price": 999},
                                 "售價（1280）不能大於原價（999）。")):
            with self.assertRaises(ValueError) as caught:
                repo.save_product_economics(
                    web.conn, self.bid, pid, actor=ACTOR, currency="TWD", confirmed_by=ACTOR,
                    **{"selling_price": 690, **money})
            self.assertEqual(str(caught.exception), sentence)
        self.assertIsNone(repo.get_product_economics(web.conn, self.bid, pid))

    def test_empty_cost_is_unset_and_empty_price_is_refused(self):
        """F47-I03: the form sends an empty field as null -- a cost left empty is stored unset (never
        0); the selling price is required."""
        pid = self._create_product()
        resp = self._save(pid, selling_price=None)
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.json()["field_errors"], {"selling_price": "售價請填數字。"})
        resp = self._save(pid, fixed_cost=None, unit_variable_cost=None, shipping_cost=None)
        self.assertEqual(resp.status_code, 204)
        raw = repo.get_product_economics(web.conn, self.bid, pid, raw=True)
        self.assertEqual((raw["fixed_cost"], raw["unit_variable_cost"], raw["shipping_cost"]),
                         (None, None, None))


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
        self.assertEqual(len(repo.list_product_facts(web.conn, self.bid, pid)), 2)

    def test_blank_reply_rejected(self):
        pid = self._create_product()
        resp = self.client.post(
            f"/api/products/brands/{self.bid}/products/{pid}/handoff", json={"reply_text": "  "},
        )
        self.assertEqual(resp.status_code, 400)

    def test_reply_that_yields_nothing_is_refused_with_the_reason(self):
        """F47-I03 (drill-10 乙 #6): pasted text whose (repaired) reply carries no fact and no price is
        a 400 with the reason -- not a green 「新增了 0 條」 -- and writes nothing."""
        pid = self._create_product()
        product_ai.PROVIDER = FakeProvider(response=_fake_response(json.dumps({"facts": []})))
        resp = self.client.post(
            f"/api/products/brands/{self.bid}/products/{pid}/handoff", json={"reply_text": "亂打的一串字"},
        )
        self.assertEqual(resp.status_code, 400)
        self.assertIn("讀不出任何產品事實", resp.json()["error"])
        self.assertEqual(repo.list_product_facts(web.conn, self.bid, pid), [])

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
        self.assertIsNotNone(repo.get_product(web.conn, self.bid, pid))

        resp = self.client.post(
            f"/api/products/brands/{self.bid}/products/{pid}/delete",
            json={"confirm_name": "虛構回甘烏龍"},
        )
        self.assertEqual(resp.status_code, 204)
        self.assertIsNone(repo.get_product(web.conn, self.bid, pid))


if __name__ == "__main__":
    unittest.main()
