"""app/tests/test_intake_prefill.py — brand onboarding step 2: the website/photo prefill (F42-I05).

`POST|GET /api/intake/brands/{b}/onboarding/scan` queue and read `ai.run_prefill` (task type
`intake_prefill`, job `background.intake_scan` with `prefill=True`). FakeProvider only; page
fetches are faked; brand names are fictional.
"""

import io
import json
import os
import unittest
from unittest import mock

from fastapi.testclient import TestClient

import app.background as background_module
import app.intake as intake_module
import app.main as main
import app.shared.web as web
from app import storage
from app.core import db as coredb
from app.core import net
from app.intake import ai as intake_ai
from app.intake import repository as ir
from app.intake import state
from app.llm import gateway, providers
from app.llm.providers import FakeProvider, ProviderResponse, Usage

_SEQ = [0]

_PAGE = "虛構軟糖品牌：給忙到沒空吃飯的人。滿 NT$999 免運。創辦人自己吞不下藥丸才做了軟糖。"

_REPLY = {
    "positioning": {"value": "給忙到沒空吃飯的人的維他命軟糖", "note": "頁面 1"},
    "tone": {"values": ["親切", "神秘"], "note": "頁面 1"},  # 神秘 is not in TONES
    "visual": {"value": "明亮、自然光、暖色系", "note": "品牌照片"},
    "proof": [{"fact_key": "founder_voice", "text": "創辦人自己吞不下藥丸才做了軟糖",
               "note": "about 頁"}],
    "policies": [
        {"key": "ship_threshold", "params": {"threshold": 999}, "note": "頁面 1"},
        {"key": "free_lunch", "params": {}, "note": "頁面 1"},  # not in POLICY_TYPES
    ],
    "products": [{"name": "綜合維他命軟糖", "url": "https://example.com/p/1"}],
    "not_found": ["媒體報導", "銷售數據"],
}


def _response(payload, *, in_tok: int = 10, out_tok: int = 10) -> ProviderResponse:
    text = payload if isinstance(payload, str) else json.dumps(payload, ensure_ascii=False)
    return ProviderResponse(output_text=text, structured=None,
                            usage=Usage(input_tokens=in_tok, output_tokens=out_tok),
                            stop_reason="end_turn")


# A JPEG frame header (1x1): photo uploads are checked by content and header (F47 Contract A).
_JPEG = bytes.fromhex("ffd8ffe000104a46494600010100000100010000ffc0000b080001000101011100ffd9")


class _Base(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(main.app)
        web.conn.execute("DELETE FROM app_setting")
        web.conn.commit()
        intake_module.register(main.app)
        self._envpatch = mock.patch.dict(os.environ, {}, clear=False)
        self._envpatch.start()
        os.environ.pop("ANTHROPIC_API_KEY", None)
        self._orig_provider = intake_ai.PROVIDER
        self._orig_fetch = intake_ai.read_url
        intake_ai.read_url = lambda url: (True, _PAGE, None)
        intake_ai.PROVIDER = FakeProvider(response=_response(_REPLY))

    def tearDown(self):
        intake_ai.PROVIDER = self._orig_provider
        intake_ai.read_url = self._orig_fetch
        self._envpatch.stop()

    def _url(self, bid: str) -> str:
        return f"/api/intake/brands/{bid}/onboarding/scan"

    def _upload(self, name: str) -> str:
        resp = self.client.post("/api/intake/photos",
                                files={"photo": (name, io.BytesIO(_JPEG), "image/jpeg")})
        self.assertEqual(resp.status_code, 200, resp.text)
        token = resp.json()["token"]
        key = state.get_pending_photos(token)[0]["storage_key"]
        self.addCleanup(storage.delete, org_id=coredb.DEV_ORG_ID, key=key)
        return token

    def _create(self, *, photos: int = 1, urls=("https://example.com/about",)) -> str:
        _SEQ[0] += 1
        tokens = [self._upload(f"p{i}.jpg") for i in range(photos)]
        resp = self.client.post("/api/intake/brands", data={
            "brand_name": f"虛構預填測試品牌{_SEQ[0]}", "urls": list(urls),
            "photo_tokens": tokens, "photo_kinds": ["logo"] * len(tokens)})
        self.assertEqual(resp.status_code, 200, resp.text)
        return resp.json()["brand_id"]

    def _scan(self, bid: str) -> dict:
        resp = self.client.post(self._url(bid))
        self.assertEqual(resp.status_code, 200, resp.text)
        web.conn.commit()
        background_module.app().run_worker(wait=False)
        return self._status(bid)

    def _status(self, bid: str) -> dict:
        resp = self.client.get(self._url(bid))
        self.assertEqual(resp.status_code, 200, resp.text)
        return resp.json()["data"]

    def _prefill(self, bid: str):
        return ir.get_active_draft(web.conn, bid)["prefill_json"]


class PrefillScanTest(_Base):
    def test_invalid_entries_are_dropped_and_the_rest_stored(self):
        bid = self._create(photos=1)
        status = self._scan(bid)
        self.assertEqual(status["status"], "done", status)
        prefill = self._prefill(bid)
        self.assertEqual(prefill["tone"], {"values": ["親切"], "note": "頁面 1"})  # 神秘 dropped
        # free_lunch dropped
        self.assertEqual([p["key"] for p in prefill["policies"]], ["ship_threshold"])
        self.assertEqual(prefill["positioning"]["value"], "給忙到沒空吃飯的人的維他命軟糖")
        self.assertEqual(prefill["visual"]["note"], "品牌照片")
        self.assertEqual(prefill["proof"], _REPLY["proof"])
        self.assertEqual(prefill["products"], _REPLY["products"])
        self.assertEqual(prefill["not_found"], ["媒體報導", "銷售數據"])
        self.assertEqual((prefill["pages_read"], prefill["photos_read"]), (1, 1))
        self.assertEqual(len(intake_ai.PROVIDER.calls), 1)

    def test_status_lists_found_rows_in_prototype_order(self):
        bid = self._create(photos=1)
        status = self._scan(bid)
        self.assertEqual([r["area"] for r in status["found"]],
                         ["品牌是誰", "品牌證據", "政策", "可能的商品"])
        self.assertIn("「給忙到沒空吃飯的人的維他命軟糖」", status["found"][0]["text"])
        self.assertIn("語氣親切", status["found"][0]["text"])
        self.assertEqual(status["found"][2]["text"], "滿 NT$999 免運")
        self.assertEqual(status["found"][1]["note"], "about 頁")
        self.assertEqual(status["not_found"], ["媒體報導", "銷售數據"])
        # positioning + tone + visual + 1 proof + 1 policy
        self.assertEqual(status["prefilled"], 5)
        self.assertEqual((status["pages_read"], status["photos_read"]), (1, 1))
        self.assertIsNone(status["error"])
        onboarding = self.client.get(f"/api/intake/brands/{bid}/onboarding").json()["data"]
        self.assertEqual(onboarding["prefill_status"], "done")
        identity = self.client.get(f"/api/intake/brands/{bid}/onboarding/identity").json()["data"]
        self.assertEqual(identity["positioning"]["source"], "ai")  # a proposal, not a fact

    def test_photos_go_as_image_blocks_in_one_call_at_most_five(self):
        bid = self._create(photos=6)
        self._scan(bid)
        calls = intake_ai.PROVIDER.calls
        self.assertEqual(len(calls), 1)
        content = calls[0]["messages"][0]["content"]
        images = [b for b in content if b["type"] == "image"]
        self.assertEqual(len(images), 5)
        self.assertEqual(images[0]["source"]["media_type"], "image/jpeg")
        self.assertEqual(content[-1]["type"], "text")
        self.assertIn("【頁面 1】https://example.com/about", content[-1]["text"])
        self.assertEqual(self._prefill(bid)["photos_read"], 5)
        refs = ir.get_active_draft(web.conn, bid)["llm_task_refs_json"]
        task = gateway.get_task(web.conn, refs[-1]["llm_task_id"])
        self.assertEqual(task["task_type"], "intake_prefill")

    def test_cost_cap_refuses_before_calling(self):
        bid = self._create()
        draft = ir.get_active_draft(web.conn, bid)
        ir.update_draft(web.conn, bid, draft["id"], cost_limit=0.05)
        resp = self.client.post(self._url(bid))
        self.assertEqual(resp.status_code, 409)
        self.assertIn("上限", resp.json()["error"])
        web.conn.commit()
        background_module.app().run_worker(wait=False)
        self.assertEqual(intake_ai.PROVIDER.calls, [])
        self.assertEqual(self._status(bid)["status"], "none")

    def test_unreadable_reply_fails_with_the_parse_message(self):
        bid = self._create()
        intake_ai.PROVIDER = FakeProvider(response=_response("這不是 JSON"))
        status = self._scan(bid)
        self.assertEqual(status["status"], "failed")
        self.assertEqual(status["error"], intake_ai.PARSE_FAIL_MESSAGE)
        self.assertIsNone(self._prefill(bid))

    def test_failed_call_shows_its_error_and_can_be_retried(self):
        bid = self._create()
        intake_ai.PROVIDER = providers.AnthropicProvider()  # no key: refused before any request
        status = self._scan(bid)
        self.assertEqual(status["status"], "failed")
        self.assertEqual(status["error"], providers.MISSING_KEY_MESSAGE)
        intake_ai.PROVIDER = FakeProvider(response=_response(_REPLY))
        self.assertEqual(self._scan(bid)["status"], "done")

    def test_nothing_readable_makes_no_call_and_can_be_started_again(self):
        bid = self._create(photos=0)
        intake_ai.read_url = lambda url: (False, "", "網站 10 秒內沒有回應")
        status = self._scan(bid)
        self.assertEqual(status["status"], "done")
        self.assertEqual((status["pages_read"], status["photos_read"], status["found"]), (0, 0, []))
        self.assertEqual(intake_ai.PROVIDER.calls, [])
        intake_ai.read_url = lambda url: (True, _PAGE, None)
        self.assertEqual(self._scan(bid)["pages_read"], 1)
        self.assertEqual(len(intake_ai.PROVIDER.calls), 1)

    def test_an_unreadable_page_is_kept_with_its_reason(self):
        good, bad, empty = ("https://example.com/about", "https://broken.example/x",
                            "https://example.com/blank")
        bid = self._create(photos=0, urls=(good, bad, empty))
        pages = {good: (True, _PAGE, None), empty: (True, "  ", None)}
        intake_ai.read_url = lambda url: pages.get(url, (False, "", "網站說這一頁不存在（404）"))
        status = self._scan(bid)
        self.assertEqual(status["status"], "done", status)
        self.assertEqual(status["pages_read"], 1)
        self.assertEqual(status["urls_read"], [good, bad, empty])
        self.assertEqual(status["pages_failed"], [
            {"url": bad, "reason": "網站說這一頁不存在（404）"},  # read_url's own reason, kept
            {"url": empty, "reason": net.REASON_EMPTY},
        ])

    def test_every_page_unreadable_reads_nothing_and_says_why(self):
        bid = self._create(photos=0, urls=("https://broken.example/x",))
        intake_ai.read_url = lambda url: (False, "", "網站 10 秒內沒有回應")
        status = self._scan(bid)
        self.assertEqual((status["status"], status["pages_read"]), ("done", 0))
        self.assertEqual(status["pages_failed"],
                         [{"url": "https://broken.example/x", "reason": "網站 10 秒內沒有回應"}])

    def test_a_changed_website_list_makes_the_old_read_stale_and_reads_again(self):
        bid = self._create(photos=0, urls=("https://broken.example/x",))
        intake_ai.read_url = lambda url: (
            (False, "", "網站 10 秒內沒有回應") if "broken" in url else (True, _PAGE, None))
        self.assertEqual(self._scan(bid)["pages_read"], 0)
        resp = self.client.put(f"/api/intake/brands/{bid}/onboarding/basics", json={
            "name": "改過網址的品牌", "urls": ["https://example.com/fixed"]})
        self.assertEqual(resp.status_code, 200, resp.text)
        stale = self._status(bid)
        self.assertEqual((stale["status"], stale["found"], stale["pages_failed"]), ("none", [], []))
        status = self._scan(bid)
        self.assertEqual(status["status"], "done", status)
        self.assertEqual((status["pages_read"], status["urls_read"], status["pages_failed"]),
                         (1, ["https://example.com/fixed"], []))
        self.assertEqual(len(intake_ai.PROVIDER.calls), 1)

    def test_a_stale_read_is_not_offered_to_the_later_steps(self):
        bid = self._create(photos=0)
        self._scan(bid)
        draft = ir.get_active_draft(web.conn, bid)
        ir.update_draft(web.conn, bid, draft["id"], research_urls_json=["https://example.com/new"])
        identity = self.client.get(f"/api/intake/brands/{bid}/onboarding/identity").json()["data"]
        self.assertNotEqual(identity["positioning"].get("source"), "ai")
        onboarding = self.client.get(f"/api/intake/brands/{bid}/onboarding").json()["data"]
        self.assertEqual(onboarding["prefill_status"], "none")

    def test_second_start_after_a_read_is_a_noop(self):
        bid = self._create()
        self._scan(bid)
        self._scan(bid)
        self.assertEqual(len(intake_ai.PROVIDER.calls), 1)

    def test_refuses_without_open_draft_or_anything_to_read(self):
        bid = self._create(photos=0, urls=())
        resp = self.client.post(self._url(bid))
        self.assertEqual(resp.status_code, 400)
        self.client.post(f"/api/intake/brands/{bid}/onboarding/complete")
        resp = self.client.post(self._url(bid))
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(self._status(bid)["status"], "none")


class PrefillContractTest(unittest.TestCase):
    def test_invented_sources_are_dropped(self):
        prefill, dropped = intake_ai.validate_prefill_reply(
            {"visual": {"value": "暖色", "note": "品牌照片"},  # no photo was read
             "proof": [{"fact_key": "lab_report", "text": "SGS 檢驗", "note": "頁面 1"}]},
            pages_read=1, photos_read=0)
        self.assertNotIn("visual", prefill)
        self.assertEqual(len(prefill["proof"]), 1)
        self.assertEqual(dropped, 1)

    def test_unknown_policy_params_are_stripped_and_limits_hold(self):
        prefill, dropped = intake_ai.validate_prefill_reply(
            {"positioning": {"value": "字" * 61, "note": "頁面 1"},
             "policies": [{"key": "ship_threshold", "params": {"threshold": 999, "x": 1},
                           "note": ""}],
             "products": [{"name": f"商品{i}", "url": "ftp://x"} for i in range(21)],
             "not_found": ["不存在的面向", "全店政策"]},
            pages_read=1, photos_read=0)
        self.assertNotIn("positioning", prefill)
        self.assertEqual(prefill["policies"],
                         [{"key": "ship_threshold", "params": {"threshold": 999}, "note": ""}])
        self.assertEqual(len(prefill["products"]), 20)
        self.assertIsNone(prefill["products"][0]["url"])
        self.assertEqual(prefill["not_found"], [])  # unknown area, and 全店政策 was found
        self.assertEqual(dropped, 1 + 1 + 2)

    def test_unreadable_reply(self):
        for data in (None, [], "text", {"other": 1}):
            result = intake_ai.validate_prefill_reply(data, pages_read=1, photos_read=1)
            self.assertEqual(result, (None, 0))

    def test_scripted_reply_passes_the_contract(self):
        reply = providers.SCRIPTED_REPLIES["intake_prefill"]
        prefill, dropped = intake_ai.validate_prefill_reply(
            json.loads(json.dumps(reply)), pages_read=1, photos_read=0)
        self.assertEqual(dropped, 0)
        for key in ("positioning", "tone", "visual"):
            self.assertIn(key, prefill)
        counts = tuple(len(prefill[k]) for k in ("proof", "policies", "products"))
        self.assertEqual(counts, (1, 1, 1))
        self.assertEqual(prefill["not_found"], reply["not_found"])
        self.assertEqual(providers.resolve_thinking(task_type="intake_prefill"), "low")
        self.assertIn("intake_prefill", providers.TASK_TYPE_LABELS)


if __name__ == "__main__":
    unittest.main()
