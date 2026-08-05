# -*- coding: utf-8 -*-
"""app/tests/test_product_handoff.py — 產品調研交接包（GitHub issue #7）。

見 app/main.py 的 /brands/{id}/products/{pid}/handoff（GET／POST）、app/intake/ai.py 的
build_product_handoff_prompt／parse_product_handoff_reply／run_product_handoff_fix。
全程用 FakeProvider，不發任何真實網路請求。品牌／產品名一律虛構，絕不可用 Beast Gummy。
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
_tmpdir = tempfile.mkdtemp(prefix="brand_os_product_handoff_")
os.environ["BRAND_OS_DB"] = str(Path(_tmpdir) / "test.db")
os.environ["BRAND_OS_BACKUP_DIR"] = str(Path(_tmpdir) / "backups")
os.environ["BRAND_OS_UPLOADS"] = str(Path(_tmpdir) / "uploads")

from fastapi.testclient import TestClient  # noqa: E402

import app.main as main  # noqa: E402
from app.brand_intelligence import repository as bi_repo  # noqa: E402
from app.core import settings as coresettings  # noqa: E402
from app.brand_intelligence import product_ai  # noqa: E402
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


_GOOD_JSON = json.dumps({"facts": [
    {"fact_type": "產品線", "label": "單一品項", "value": "目前只有一款 60 錠裝。"},
    {"fact_type": "受眾", "label": "上班族", "value": "常見於下午茶時段購買。"},
], "price": {"amount": 690, "currency": "twd"}}, ensure_ascii=False)

# 「含前後廢話」：外部 AI 常會在 JSON 前後多寫幾句話，解析要能忽略它們。
_GOOD_WITH_NOISE = (
    "這是我整理好的深度調研結果，重點都在下面這份 JSON 裡：\n\n"
    + _GOOD_JSON +
    "\n\n以上，如果還需要別的面向我可以再補充。"
)

_GARBLED = "這次調研有點趕，先口頭跟你講重點：單一品項、賣給上班族、大概 690 元。細節之後再補。"


class _BaseHandoffTest(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(main.app)
        main.conn.execute("DELETE FROM app_setting")
        main.conn.commit()
        self._envpatch = mock.patch.dict(os.environ, {}, clear=False)
        self._envpatch.start()
        os.environ.pop("ANTHROPIC_API_KEY", None)
        os.environ.pop("BRAND_OS_LLM_MODEL", None)
        self._orig_provider = product_ai.PROVIDER
        self.brand = bi_repo.create_brand(main.conn, name="虛構茶研所", client_name="測試客戶", actor=ACTOR)
        resp = self.client.post(
            f"/brands/{self.brand['id']}/products/new", data={"name": "虛構回甘烏龍"},
            follow_redirects=False,
        )
        self.product_id = resp.headers["location"].split("/products/")[1].split("?")[0]

    def tearDown(self):
        product_ai.PROVIDER = self._orig_provider
        self._envpatch.stop()

    def _handoff_url(self):
        return f"/brands/{self.brand['id']}/products/{self.product_id}/handoff"

    def _post(self, raw_text: str):
        return self.client.post(self._handoff_url(), data={"raw_text": raw_text}, follow_redirects=False)


class HandoffPageTest(_BaseHandoffTest):
    def test_page_renders_brand_and_product_facts_and_format_spec(self):
        bi_repo.create_brand_fact(main.conn, self.brand["id"], actor=ACTOR, fact_type="positioning",
                                  label="單一產區直送定位", value="主打單一產區的烏龍與紅茶。",
                                  status="confirmed", confirmed_by=ACTOR)
        bi_repo.create_product_fact(main.conn, self.brand["id"], self.product_id, actor=ACTOR,
                                    fact_type="產品線", label="既有規格", value="一包 150 公克。",
                                    status="pending")
        resp = self.client.get(self._handoff_url())
        self.assertEqual(resp.status_code, 200)
        self.assertIn("單一產區直送定位", resp.text)
        self.assertIn("既有規格", resp.text)
        self.assertIn("虛構回甘烏龍", resp.text)
        # 嚴格回覆格式要求：五類 facts、選填 price，跟 run_product_scan 同形狀
        for fact_type in product_ai.PRODUCT_SCAN_FACT_TYPES:
            self.assertIn(fact_type, resp.text)
        self.assertIn("price", resp.text)


class HandoffPasteDirectParseTest(_BaseHandoffTest):
    def test_valid_json_with_surrounding_noise_lands_pending_no_llm_call(self):
        product_ai.PROVIDER = FakeProvider(response=_fake_response("不該被呼叫"))
        resp = self._post(_GOOD_WITH_NOISE)
        self.assertEqual(resp.status_code, 303)
        self.assertEqual(product_ai.PROVIDER.calls, [])  # 直接解析成功，完全不花錢

        facts = bi_repo.list_product_facts(main.conn, self.brand["id"], self.product_id)
        self.assertEqual(len(facts), 2)
        for f in facts:
            self.assertEqual(f["status"], "pending")
            src = bi_repo.get_source_reference(main.conn, self.brand["id"], f["source_reference_id"])
            self.assertIn("外部深研交接包", src["title"])

        economics = bi_repo.get_product_economics(main.conn, self.brand["id"], self.product_id)
        self.assertIsNotNone(economics)
        self.assertEqual(economics["status"], "pending")
        self.assertEqual(economics["selling_price"], 690.0)
        self.assertEqual(economics["currency"], "TWD")

    def test_same_label_deduped_against_existing_fact(self):
        bi_repo.create_product_fact(main.conn, self.brand["id"], self.product_id, actor=ACTOR,
                                    fact_type="產品線", label="單一品項", value="舊資料。",
                                    status="confirmed", confirmed_by=ACTOR)
        product_ai.PROVIDER = FakeProvider(response=_fake_response("不該被呼叫"))
        resp = self._post(_GOOD_JSON)
        self.assertEqual(resp.status_code, 303)
        facts = bi_repo.list_product_facts(main.conn, self.brand["id"], self.product_id)
        # 原本 1 條（已確認）+ 貼回新增 1 條（「上班族」），「單一品項」同標籤已存在被跳過。
        self.assertEqual(len(facts), 2)
        labels = [f["label"] for f in facts]
        self.assertEqual(labels.count("單一品項"), 1)
        self.assertIn("上班族", labels)

    def test_blank_paste_shows_error_creates_nothing(self):
        resp = self._post("   ")
        self.assertEqual(resp.status_code, 400)
        self.assertIn("請先把外部 AI 的回覆貼進來", resp.text)
        self.assertEqual(bi_repo.list_product_facts(main.conn, self.brand["id"], self.product_id), [])


class HandoffPasteFixTest(_BaseHandoffTest):
    def test_garbled_paste_repaired_by_ai_lands_pending(self):
        product_ai.PROVIDER = FakeProvider(response=_fake_response(_GOOD_JSON))
        resp = self._post(_GARBLED)
        self.assertEqual(resp.status_code, 303)
        self.assertEqual(len(product_ai.PROVIDER.calls), 1)  # 直接解析失敗才呼叫一次修復
        facts = bi_repo.list_product_facts(main.conn, self.brand["id"], self.product_id)
        self.assertEqual(len(facts), 2)
        for f in facts:
            self.assertEqual(f["status"], "pending")

    def test_repair_still_garbled_is_honest_failure_creates_nothing(self):
        product_ai.PROVIDER = FakeProvider(response=_fake_response("修復後還是不是 JSON"))
        resp = self._post(_GARBLED)
        self.assertEqual(resp.status_code, 400)
        self.assertIn(product_ai.PARSE_FAIL_MESSAGE, resp.text)
        self.assertEqual(bi_repo.list_product_facts(main.conn, self.brand["id"], self.product_id), [])

    def test_over_budget_blocks_repair_before_any_llm_call(self):
        coresettings.set_setting(main.conn, coresettings.INTAKE_BUDGET_SETTING, "0.1")
        product_ai.PROVIDER = FakeProvider(response=_fake_response("不該被呼叫"))
        resp = self._post(_GARBLED)
        self.assertEqual(resp.status_code, 400)
        self.assertIn("花費上限", resp.text)
        self.assertEqual(bi_repo.list_product_facts(main.conn, self.brand["id"], self.product_id), [])
        self.assertEqual(product_ai.PROVIDER.calls, [])

    def test_missing_key_shows_human_error_creates_nothing(self):
        product_ai.PROVIDER = AnthropicProvider()  # 無金鑰：送網路請求之前就會擋下
        resp = self._post(_GARBLED)
        self.assertEqual(resp.status_code, 400)
        self.assertIn(MISSING_KEY_MESSAGE, resp.text)
        self.assertEqual(bi_repo.list_product_facts(main.conn, self.brand["id"], self.product_id), [])


if __name__ == "__main__":
    unittest.main()
