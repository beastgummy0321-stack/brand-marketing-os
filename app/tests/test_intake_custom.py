"""app/tests/test_intake_custom.py — 「自訂：用自己的話說」 of brand onboarding (F42-I05).

`POST /api/intake/brands/{b}/onboarding/custom {block, text}` → one proposal, contract-checked,
nothing saved. FakeProvider only; brand names are fictional.
"""

import json
import os
import unittest
from unittest import mock

from fastapi.testclient import TestClient

import app.intake as intake_module
import app.main as main
import app.shared.web as web
from app.brand_intelligence import repository as bi_repo
from app.core import db as coredb
from app.core import vocab
from app.intake import custom
from app.intake import repository as ir
from app.llm import providers
from app.llm.providers import FakeProvider, ProviderResponse, Usage

_SEQ = [0]


def _response(payload) -> ProviderResponse:
    text = payload if isinstance(payload, str) else json.dumps(payload, ensure_ascii=False)
    return ProviderResponse(output_text=text, structured=None,
                            usage=Usage(input_tokens=10, output_tokens=10), stop_reason="end_turn")


class CustomRouteTest(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(main.app)
        web.conn.execute("DELETE FROM app_setting")
        web.conn.commit()
        intake_module.register(main.app)
        self._envpatch = mock.patch.dict(os.environ, {}, clear=False)
        self._envpatch.start()
        os.environ.pop("ANTHROPIC_API_KEY", None)
        self._orig_provider = custom.PROVIDER

    def tearDown(self):
        custom.PROVIDER = self._orig_provider
        self._envpatch.stop()

    def _create(self) -> str:
        _SEQ[0] += 1
        resp = self.client.post("/api/intake/brands",
                                data={"brand_name": f"虛構自訂測試品牌{_SEQ[0]}"})
        self.assertEqual(resp.status_code, 200, resp.text)
        return resp.json()["brand_id"]

    def _post(self, bid: str, block: str, text: str, reply=None):
        if reply is not None:
            custom.PROVIDER = FakeProvider(response=_response(reply))
        return self.client.post(f"/api/intake/brands/{bid}/onboarding/custom",
                                json={"block": block, "text": text})

    def _saved(self, bid: str) -> tuple:
        return (len(bi_repo.list_brand_facts(web.conn, bid)),
                len(bi_repo.list_rules_for_brand(web.conn, bid)))

    def test_each_block_returns_a_proposal_and_saves_nothing(self):
        bid = self._create()
        before = self._saved(bid)
        cases = [
            ("positioning", "給上班族吃的維他命", {"value": "給忙碌上班族的維他命軟糖"},
             {"block": "positioning", "kind": "value", "value": "給忙碌上班族的維他命軟糖"}),
            ("visual", "想要很乾淨的白色背景", {"value": "白色背景、乾淨明亮"},
             {"block": "visual", "kind": "value", "value": "白色背景、乾淨明亮"}),
            ("tone", "像朋友一樣隨便聊", {"label": "像朋友"},
             {"block": "tone", "kind": "option", "option": {"label": "像朋友"}}),
            ("brand_proof", "很多客人說吃了三個月氣色變好",
             {"fact_key": "customer_review", "text": "客人說氣色變好"},
             {"block": "brand_proof", "kind": "option",
              "option": {"fact_key": "customer_review", "label": "顧客評論原話",
                         "text": "客人說氣色變好"}}),
            ("policy", "買 3 盒就送 1 盒",
             {"label": "買三送一", "offer_key": "bundle", "sentence": "買 3 送 1"},
             {"block": "policy", "kind": "option",
              "option": {"key": "custom", "label": "買三送一", "offer_key": "bundle",
                         "offer_label": "組合加贈", "sentence": "買 3 送 1",
                         "params": {"label": "買三送一", "offer_key": "bundle"}}}),
            ("forbidden", "不要說可以減肥", {"text": "減肥"},
             {"block": "forbidden", "kind": "option", "option": {"text": "減肥"}}),
        ]
        for block, text, reply, expected in cases:
            with self.subTest(block=block):
                resp = self._post(bid, block, text, reply)
                self.assertEqual(resp.status_code, 200, resp.text)
                self.assertEqual(resp.json()["data"], expected)
                call = custom.PROVIDER.calls[0]
                self.assertEqual(len(custom.PROVIDER.calls), 1)
                self.assertLessEqual(call["max_tokens"], 600)
                self.assertIn(text, call["messages"][0]["content"])
        self.assertEqual(self._saved(bid), before)

    def test_tone_input_carries_the_current_options(self):
        bid = self._create()
        self._post(bid, "tone", "像朋友一樣", {"label": "像朋友"})
        prompt = custom.PROVIDER.calls[0]["messages"][0]["content"]
        self.assertIn("已有的選項：" + "、".join(vocab.TONES), prompt)

    def test_out_of_vocabulary_keys_are_422(self):
        bid = self._create()
        before = self._saved(bid)
        for block, reply in (
                ("brand_proof", {"fact_key": "celebrity", "text": "明星推薦"}),
                ("policy", {"label": "免運", "offer_key": "free_lunch", "sentence": "全館免運"})):
            with self.subTest(block=block):
                resp = self._post(bid, block, "一句話", reply)
                self.assertEqual(resp.status_code, 422)
                self.assertEqual(resp.json()["error"], "AI 整理不出來，換個說法再試一次")
        self.assertEqual(self._saved(bid), before)

    def test_contract_failures_are_422(self):
        bid = self._create()
        for block, text, reply in (
                ("positioning", "一句話", "不是 JSON"),
                ("tone", "一句話", {"label": "超過八個字的口氣名稱喔"}),
                # a number the user never said
                ("policy", "滿千免運", {"label": "免運", "offer_key": "free_shipping",
                                       "sentence": "滿 NT$1000 免運"}),
                ("forbidden", "一句話", {"text": ""})):
            with self.subTest(block=block, reply=reply):
                self.assertEqual(self._post(bid, block, text, reply).status_code, 422)

    def test_bad_input_is_400_without_a_call(self):
        bid = self._create()
        custom.PROVIDER = FakeProvider(response=_response({"value": "x"}))
        bad = (("persona", "一句話"), ("positioning", "  "), ("positioning", "字" * 201))
        for block, text in bad:
            with self.subTest(block=block, text=text[:5]):
                resp = self.client.post(f"/api/intake/brands/{bid}/onboarding/custom",
                                        json={"block": block, "text": text})
                self.assertEqual(resp.status_code, 400)
        self.assertEqual(custom.PROVIDER.calls, [])

    def test_draft_cost_cap_refuses_before_calling(self):
        bid = self._create()
        draft = ir.get_active_draft(web.conn, bid)
        ir.update_draft(web.conn, bid, draft["id"], cost_limit=0.01)
        resp = self._post(bid, "positioning", "一句話", {"value": "定位"})
        self.assertEqual(resp.status_code, 409)
        self.assertEqual(custom.PROVIDER.calls, [])

    def test_failed_call_is_502_with_its_message(self):
        bid = self._create()
        custom.PROVIDER = providers.AnthropicProvider()  # no key: refused before any request
        resp = self.client.post(f"/api/intake/brands/{bid}/onboarding/custom",
                                json={"block": "positioning", "text": "一句話"})
        self.assertEqual(resp.status_code, 502)
        self.assertEqual(resp.json()["error"], providers.MISSING_KEY_MESSAGE)

    def test_works_in_reentry_mode_without_a_draft(self):
        _SEQ[0] += 1
        brand = bi_repo.create_brand(web.conn, org_id=coredb.DEV_ORG_ID,
                                     name=f"虛構自訂測試品牌{_SEQ[0]}", client_name=None,
                                     actor="test")
        resp = self._post(brand["id"], "forbidden", "不要說治療", {"text": "治療"})
        self.assertEqual(resp.status_code, 200, resp.text)
        self.assertEqual(resp.json()["data"]["option"], {"text": "治療"})


class ScriptedReplyContractTest(unittest.TestCase):
    def test_scripted_reply_passes_every_block(self):
        reply = json.loads(json.dumps(providers.SCRIPTED_REPLIES["intake_custom"]))
        for block in custom.BLOCKS:
            with self.subTest(block=block):
                result = custom.check_reply(block, reply, "任何一句 3 個數字的話")
                self.assertIn(result["kind"], ("value", "option"))
        self.assertEqual(providers.resolve_thinking(task_type="intake_custom"), "low")
        self.assertIn("intake_custom", providers.TASK_TYPE_LABELS)


if __name__ == "__main__":
    unittest.main()
