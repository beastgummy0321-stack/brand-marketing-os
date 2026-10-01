"""app/tests/test_intake_product_prefill.py — product onboarding 「✦ AI 從商品頁讀到」 (F43-I06).

`app/intake/product_prefill.py`: the read queued on product creation with a page URL
(`POST …/products`) and on `POST …/products/{p}/onboarding/scan`, job
`background.intake_product_prefill`, task type `intake_product_prefill`; the status is
`GET …/products/{p}/onboarding`. FakeProvider only; the page fetch and photo downloads are faked;
brand and product names are fictional.
"""

import json
import os
import unittest
from unittest import mock

from fastapi.testclient import TestClient

import app.background as background_module
import app.intake as intake_module
import app.main as main
import app.shared.web as web
from app.brand_intelligence import repository as bi_repo
from app.core import db as coredb
from app.core import settings as coresettings
from app.intake import ai as intake_ai
from app.intake import product_prefill
from app.intake import repository as ir
from app.llm import gateway, providers
from app.llm.providers import FakeProvider, ProviderResponse, Usage

_SEQ = [0]
_URL = "https://shop.example/vit"

_PAGE = (
    "綜合維他命軟糖 一天一顆，12 種維生素。單盒 NT$399，三盒組 NT$999（原價 1,197）。"
    "顧客評論： 每天吞藥丸好麻煩，這個好吃多了 。SGS 重金屬檢驗合格。"
)

_GROUP = {"who": "常加班的上班族", "pain_keys": ["effort"],
          "quote": "每天吞藥丸好麻煩，這個好吃多了", "when_used": "早上出門前",
          "note": "商品頁評論"}
_REPLY = {
    "intro": {"value": "一天一顆，12 種維生素", "note": "商品頁"},
    "mechanism": {"value": "維生素做成軟糖", "note": "商品頁"},
    "difference": {"value": "不用吞藥丸", "note": "商品照片"},  # no photo was read: invented
    "groups": [
        # made_up is outside the six pain keys: dropped, the group stays
        {**_GROUP, "pain_keys": ["effort", "made_up"]},
        # a quote that is not on the page: blanked, the group stays
        {"who": "怕買錯的新手爸媽", "pain_keys": ["uncertainty"], "quote": "我自己編的一句話",
         "when_used": "", "note": "商品頁"},
        {"who": "只有煩惱不存在的人", "pain_keys": ["made_up"], "quote": "", "when_used": "",
         "note": "商品頁"},  # no pain key left: dropped
        {"who": "第三群", "pain_keys": ["cost"], "quote": "", "when_used": "", "note": "商品頁"},
        {"who": "第四群", "pain_keys": ["cost"], "quote": "", "when_used": "", "note": "商品頁"},
        {"who": "第五群", "pain_keys": ["cost"], "quote": "", "when_used": "", "note": "商品頁"},
    ],
    "proof": [
        {"fact_key": "lab_report", "text": "SGS 重金屬檢驗合格", "note": "商品頁"},
        {"fact_key": "celebrity", "text": "明星推薦", "note": "商品頁"},  # unknown kind
    ],
    "claims": [{"text": f"說法 {i}", "note": "商品頁"} for i in range(10)],
    "sell_ways": [
        {"name": "單盒", "qty": 1, "price": 399, "list_price": 399, "note": "商品頁"},
        {"name": "三盒組", "qty": 3, "price": 999, "list_price": 1197, "note": "商品頁"},
        {"name": "壞的", "qty": 0, "price": 1, "list_price": None, "note": "商品頁"},
        {"name": "四", "qty": 4, "price": 1200, "list_price": None, "note": "商品頁"},
        {"name": "五", "qty": 5, "price": 1500, "list_price": None, "note": "商品頁"},
        {"name": "六", "qty": 6, "price": 1800, "list_price": None, "note": "商品頁"},
    ],
}


def _response(payload) -> ProviderResponse:
    text = payload if isinstance(payload, str) else json.dumps(payload, ensure_ascii=False)
    return ProviderResponse(output_text=text, structured=None,
                            usage=Usage(input_tokens=10, output_tokens=10), stop_reason="end_turn")


class _Base(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(main.app)
        web.conn.execute("DELETE FROM app_setting")
        web.conn.commit()
        intake_module.register(main.app)
        self._envpatch = mock.patch.dict(os.environ, {}, clear=False)
        self._envpatch.start()
        os.environ.pop("ANTHROPIC_API_KEY", None)
        self._orig = (product_prefill.PROVIDER, product_prefill.fetch_url)
        product_prefill.fetch_url = lambda url: (True, _PAGE)
        product_prefill.PROVIDER = FakeProvider(response=_response(_REPLY))
        _SEQ[0] += 1
        resp = self.client.post("/api/intake/brands",
                                data={"brand_name": f"虛構商品預填品牌{_SEQ[0]}"})
        self.assertEqual(resp.status_code, 200, resp.text)
        self.bid = resp.json()["brand_id"]

    def tearDown(self):
        product_prefill.PROVIDER, product_prefill.fetch_url = self._orig
        self._envpatch.stop()

    def _base(self, path: str = "") -> str:
        return f"/api/intake/brands/{self.bid}{path}"

    def _step(self, pid: str, path: str = "") -> str:
        return self._base(f"/products/{pid}/onboarding{path}")

    def _create(self, name: str = "綜合維他命軟糖", page_url: str | None = _URL) -> str:
        body = {"name": name} if page_url is None else {"name": name, "page_url": page_url}
        resp = self.client.post(self._base("/products"), json=body)
        self.assertEqual(resp.status_code, 200, resp.text)
        return resp.json()["data"]["product_id"]

    def _work(self) -> None:
        web.conn.commit()
        background_module.app().run_worker(wait=False)

    def _status(self, pid: str) -> dict:
        resp = self.client.get(self._step(pid))
        self.assertEqual(resp.status_code, 200, resp.text)
        return resp.json()["data"]

    def _row(self, pid: str) -> dict:
        row = ir.get_product_prefill(web.conn, self.bid, pid)
        assert row is not None
        return row

    def _calls(self) -> list:
        provider = product_prefill.PROVIDER
        return provider.calls if isinstance(provider, FakeProvider) else []

    def _photos(self, pid: str, n: int) -> None:
        for i in range(n):
            bi_repo.create_official_asset(
                web.conn, self.bid, actor="test", asset_kind="product_photo",
                storage_key=f"{coredb.DEV_ORG_ID}/fake/p{i}.jpg", product_id=pid)
        web.conn.commit()


class ProductPrefillTest(_Base):
    def test_create_with_page_url_reads_the_page_and_stores_the_checked_proposal(self):
        pid = self._create()
        self.assertEqual(self._status(pid)["prefill_status"], "running")
        self._work()
        status = self._status(pid)
        self.assertEqual((status["prefill_status"], status["prefill_error"]), ("done", None))
        prefill = self._row(pid)["prefill_json"]
        self.assertEqual(prefill["intro"], _REPLY["intro"])
        self.assertNotIn("difference", prefill)  # 「商品照片」 but no photo was read
        # out-of-vocabulary pain key dropped; a group without any pain key dropped; the 5th and
        # 6th groups beyond three dropped; an invented quote blanked, a verbatim one kept
        self.assertEqual([g["who"] for g in prefill["groups"]],
                         ["常加班的上班族", "怕買錯的新手爸媽", "第三群"])
        self.assertEqual(prefill["groups"][0], _GROUP)
        self.assertEqual(prefill["groups"][1]["quote"], "")
        self.assertEqual(prefill["proof"], [_REPLY["proof"][0]])
        self.assertEqual(len(prefill["claims"]), 8)
        self.assertEqual([w["name"] for w in prefill["sell_ways"]], ["單盒", "三盒組", "四", "五"])
        self.assertIsNone(prefill["sell_ways"][0]["list_price"])  # not above the price
        self.assertEqual(prefill["sell_ways"][1]["list_price"], 1197)
        self.assertEqual((prefill["pages_read"], prefill["photos_read"]), (1, 0))

        calls = self._calls()
        self.assertEqual(len(calls), 1)
        self.assertIsNone(calls[0]["tools"])  # no web search
        content = calls[0]["messages"][0]["content"]
        self.assertIn(f"【商品頁】{_URL}", content[-1]["text"])
        task = gateway.get_task(web.conn, self._row(pid)["llm_task_id"])
        assert task is not None
        self.assertEqual(task["task_type"], "intake_product_prefill")

    def test_steps_show_the_proposal_as_ai_not_saved(self):
        pid = self._create()
        self._work()
        what = self.client.get(self._step(pid, "/what")).json()["data"]
        self.assertEqual(what["intro"]["source"], "ai")
        who = self.client.get(self._step(pid, "/who")).json()["data"]
        self.assertEqual([g["source"] for g in who["groups"]], ["ai", "ai", "ai"])
        self.assertEqual(bi_repo.list_customer_groups(web.conn, self.bid, pid), [])

    def test_product_photos_go_as_image_blocks_at_most_three(self):
        pid = self._create(page_url=None)
        self._photos(pid, 4)
        with mock.patch.object(product_prefill.storage, "get",
                               return_value=(b"x" * 100, "image/jpeg")):
            resp = self.client.post(self._step(pid, "/scan"))
            self.assertEqual(resp.status_code, 200, resp.text)
            self.assertEqual(resp.json()["data"]["prefill_status"], "running")
            self._work()
        content = self._calls()[0]["messages"][0]["content"]
        self.assertEqual([b["type"] for b in content], ["image"] * 3 + ["text"])
        self.assertNotIn("【商品頁】", content[-1]["text"])
        prefill = self._row(pid)["prefill_json"]
        self.assertEqual((prefill["pages_read"], prefill["photos_read"]), (0, 3))
        self.assertEqual(prefill["difference"]["note"], "商品照片")  # a photo was read now
        self.assertNotIn("intro", prefill)  # 「商品頁」 but no page was read this time

    def test_cost_cap_refuses_before_calling(self):
        coresettings.set_setting(web.conn, "intake_budget_limit", "0.1", org_id=coredb.DEV_ORG_ID)
        web.conn.commit()
        pid = self._create()  # the product is still created; the read is refused
        status = self._status(pid)
        self.assertEqual(status["prefill_status"], "failed")
        self.assertIn("上限", status["prefill_error"])
        resp = self.client.post(self._step(pid, "/scan"))
        self.assertEqual(resp.status_code, 409)
        self.assertIn("上限", resp.json()["error"])
        self._work()
        self.assertEqual(self._calls(), [])

    def test_unreadable_reply_fails_with_the_parse_message_and_can_be_reread(self):
        product_prefill.PROVIDER = FakeProvider(response=_response("這不是 JSON"))
        pid = self._create()
        self._work()
        status = self._status(pid)
        self.assertEqual(status["prefill_status"], "failed")
        self.assertEqual(status["prefill_error"], intake_ai.PARSE_FAIL_MESSAGE)
        product_prefill.PROVIDER = FakeProvider(response=_response(_REPLY))
        self.client.post(self._step(pid, "/scan"))
        self._work()
        self.assertEqual(self._status(pid)["prefill_status"], "done")

    def test_failed_call_shows_its_own_error(self):
        product_prefill.PROVIDER = providers.AnthropicProvider()  # no key: refused before sending
        pid = self._create()
        self._work()
        status = self._status(pid)
        self.assertEqual((status["prefill_status"], status["prefill_error"]),
                         ("failed", providers.MISSING_KEY_MESSAGE))

    def test_nothing_readable_fails_without_a_call(self):
        product_prefill.fetch_url = lambda url: (False, "")
        pid = self._create()
        self._work()
        status = self._status(pid)
        self.assertEqual((status["prefill_status"], status["prefill_error"]),
                         ("failed", product_prefill.NOTHING_READ_MESSAGE))
        self.assertEqual(self._calls(), [])

    def test_create_without_page_url_does_not_read(self):
        pid = self._create(page_url=None)
        self._work()
        self.assertEqual(self._status(pid)["prefill_status"], "none")
        self.assertEqual(self._calls(), [])

    def test_scan_refusals(self):
        pid = self._create(page_url=None)
        self.assertEqual(self.client.post(self._step(pid, "/scan")).status_code, 400)  # nothing
        self.assertEqual(self.client.post(self._step("prd_missing", "/scan")).status_code, 404)
        done = self._create("益生菌軟糖")
        resp = self.client.put(self._step(done, "/sell-ways"),
                               json={"sell_ways": [{"name": "單盒", "qty": 1, "price": 399}]})
        self.assertEqual(resp.status_code, 200, resp.text)
        self.assertEqual(self.client.post(self._step(done, "/complete")).status_code, 200)
        self.assertEqual(self.client.post(self._step(done, "/scan")).status_code, 400)  # finished

    def test_running_row_whose_job_never_ran_reads_failed(self):
        pid = self._create(page_url=None)
        ir.save_product_prefill(web.conn, self.bid, pid, status="running")
        status = self._status(pid)
        self.assertEqual((status["prefill_status"], status["prefill_error"]),
                         ("failed", background_module.JOB_FAILED_MESSAGE))


class ProductPrefillContractTest(unittest.TestCase):
    def _check(self, data, **kw):
        args = {"page_text": _PAGE, "pages_read": 1, "photos_read": 0, **kw}
        return product_prefill.validate_reply(data, **args)

    def test_unreadable_reply(self):
        for data in (None, [], "text", {"other": 1}):
            self.assertEqual(self._check(data), (None, 0))

    def test_pain_keys_are_capped_at_two_and_limits_hold(self):
        prefill, dropped = self._check({
            "intro": {"value": "字" * 201, "note": "商品頁"},
            "groups": [{"who": "上班族", "pain_keys": ["effort", "cost", "identity"], "note": ""}],
            "sell_ways": [{"name": "單盒", "qty": True, "price": 399, "note": "商品頁"},
                          {"name": "單盒", "qty": 1, "price": "399", "note": "商品頁"}],
        })
        assert prefill is not None
        self.assertNotIn("intro", prefill)
        self.assertEqual(prefill["groups"][0]["pain_keys"], ["effort", "cost"])
        self.assertEqual(prefill["groups"][0]["quote"], "")
        self.assertEqual(prefill["sell_ways"], [])
        self.assertEqual(dropped, 1 + 1 + 2)

    def test_scripted_reply_passes_the_contract(self):
        reply = json.loads(json.dumps(providers.SCRIPTED_REPLIES["intake_product_prefill"]))
        prefill, dropped = self._check(reply, page_text="任何商品頁文字")
        assert prefill is not None
        self.assertEqual(dropped, 0)
        for key in ("intro", "mechanism", "difference"):
            self.assertIn(key, prefill)
        counts = tuple(len(prefill[k]) for k in ("groups", "proof", "claims", "sell_ways"))
        self.assertEqual(counts, (1, 1, 1, 1))
        self.assertEqual(providers.resolve_thinking(task_type="intake_product_prefill"), "low")
        self.assertIn("intake_product_prefill", providers.TASK_TYPE_LABELS)


if __name__ == "__main__":
    unittest.main()
