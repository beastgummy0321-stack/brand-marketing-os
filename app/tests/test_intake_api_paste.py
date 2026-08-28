"""app/tests/test_intake_api_paste.py — 建檔精靈 JSON API：貼回驗證／範圍解析／AI 修格式
背景工作／逐條 review（從 test_intake_api.py 拆出，票 B3 獨立驗證：單檔 <800 行，斷言不變）。

見 app/intake/routes_api.py。全程用 FakeProvider（跟 test_intake.py 同風格），不發任何
真實網路請求；品牌名一律虛構。隔離 DB、假金鑰。
"""

import json
import os
import time
import unittest
from unittest import mock

os.environ.setdefault("ANTHROPIC_API_KEY", "sk-ant-fake-intake-api-test")

from fastapi.testclient import TestClient  # noqa: E402

import app.main as main  # noqa: E402
import app.shared.web as web  # noqa: E402
from app.brand_intelligence import repository as bi_repo  # noqa: E402
from app.core import interrupts as core_interrupts  # noqa: E402
from app.intake import ai as intake_ai  # noqa: E402
from app.intake import routes_api as api  # noqa: E402
from app.intake import script, state  # noqa: E402
from app.llm.providers import FakeProvider, ProviderResponse, Usage  # noqa: E402

_SEQ = [0]



def _fake_response(text: str, structured=None) -> ProviderResponse:
    return ProviderResponse(output_text=text, structured=structured,
                            usage=Usage(input_tokens=10, output_tokens=10), stop_reason="end_turn")


_SCAN_OK = json.dumps({
    "impressions": [{"looks_like": "產品線", "title": "看起來像單一品項",
                     "content": "只有一款主力商品。", "basis": "依業主描述推測"}],
    "products": [],
}, ensure_ascii=False)


def _question_json(i: int = 0, aspect: str = "產品線") -> str:
    q = script.QUESTIONS[i]
    return json.dumps({"done": False, "aspect": aspect, "question": q["question"],
                       "suggested": {"label": q["suggested"]["label"], "desc": q["suggested"]["desc"]},
                       "branches": [{"label": b["label"], "desc": b["desc"]} for b in q["branches"]]},
                      ensure_ascii=False)


class _Base(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(main.app)
        web.conn.execute("DELETE FROM app_setting")
        web.conn.commit()
        api._JOBS.clear()
        # 隔離環境變數：金鑰只看 DB 設定（沒設＝沒金鑰，跟 test_intake.py 同風格）
        self._envpatch = mock.patch.dict(os.environ, {}, clear=False)
        self._envpatch.start()
        os.environ.pop("ANTHROPIC_API_KEY", None)
        self._orig_provider = intake_ai.PROVIDER
        self._orig_fetch = intake_ai.fetch_url
        intake_ai.fetch_url = lambda url: (False, "")

    def tearDown(self):
        intake_ai.PROVIDER = self._orig_provider
        intake_ai.fetch_url = self._orig_fetch
        api._JOBS.clear()
        self._envpatch.stop()

    def _brand_name(self) -> str:
        _SEQ[0] += 1
        return f"虛構建檔API測試品牌{_SEQ[0]}"

    def _create_full(self) -> str:
        """建立一個有草稿（非陽春路徑）的品牌，回傳 brand_id。"""
        resp = self.client.post("/api/intake/brands", data={
            "brand_name": self._brand_name(), "description": "一句測試用的品牌描述文字。",
        })
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertFalse(body["quick"])
        return body["brand_id"]

    def _poll(self, brand_id: str, kind: str, timeout: float = 1.0) -> dict:
        # paste_fix 的 URL 是 .../paste/fix/status（跟 job kind 字串 "paste_fix" 不同，
        # 不能直接拼 kind 進路徑）；scan／question 的 URL 段跟 kind 字串本來就一樣。
        path_segment = "paste/fix" if kind == "paste_fix" else kind
        deadline = time.time() + timeout
        while time.time() < deadline:
            status = self.client.get(f"/api/intake/brands/{brand_id}/{path_segment}/status").json()["data"]
            if status["status"] != "running":
                return status
            time.sleep(0.05)
        self.fail("背景任務逾時仍未完成，可能是執行緒沒有真的跑")


# ---------------------------------------------------------------------------
# 貼回驗證（免費、同步）：三種錯誤樣本、成功落地並推進到步驟 5
# ---------------------------------------------------------------------------

_THREE_ERROR_SAMPLE = (
    "種類 | 分類 | 標題 | 內容 | 適用範圍 | 佐證來源\n"
    "品牌功能 | 定位 | 標題1 | 內容1。 | 整個品牌 | 來源1\n"
    "產品事實 | 核心資訊 | 標題2 | 內容2 只有四欄\n"
    "宣稱 | 可用 | 標題3 | 內容3。 | 神秘產品 | 來源3"
)


class PasteValidateTest(_Base):
    def _brand_with_product(self) -> str:
        bid = self._create_full()
        bi_repo.create_product(web.conn, bid, name=script.MOCK_PRODUCT_NAME, actor="測試員")
        return bid

    def test_success_lands_items_and_bumps_step_to_5(self):
        bid = self._brand_with_product()
        resp = self.client.post(f"/api/intake/brands/{bid}/paste/validate",
                                json={"raw_text": script.PASTE_SAMPLE_SUCCESS})
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertEqual(body["errors"], [])
        self.assertEqual(body["data_line_count"], 24)
        draft = state.get_draft(bid)
        self.assertEqual(draft["step"], 5)
        self.assertEqual(draft["pending_item_count"], 24)

    def test_three_error_kinds_reported_together(self):
        """三種驗證錯誤各自回報，不是短路在第一個：欄數不對／種類不對／適用範圍不認得。"""
        bid = self._brand_with_product()
        resp = self.client.post(f"/api/intake/brands/{bid}/paste/validate",
                                json={"raw_text": _THREE_ERROR_SAMPLE})
        self.assertEqual(resp.status_code, 200)
        errors = resp.json()["errors"]
        self.assertEqual(len(errors), 3)
        self.assertEqual(errors[0]["line"], 1)
        self.assertIn("種類寫成「品牌功能」", errors[0]["msg"])
        self.assertEqual(errors[1]["line"], 2)
        self.assertIn("4 欄", errors[1]["msg"])
        self.assertEqual(errors[2]["line"], 3)
        self.assertEqual(errors[2]["unknown_scope"], "神秘產品")
        # 驗證失敗不落地、也不推進步驟
        draft = state.get_draft(bid)
        self.assertEqual(draft["pending_item_count"], 0)
        self.assertLess(draft["step"], 5)

    def test_empty_text_errors(self):
        bid = self._create_full()
        resp = self.client.post(f"/api/intake/brands/{bid}/paste/validate", json={"raw_text": "  "})
        self.assertEqual(resp.status_code, 400)  # COPY trim：精確中文文案不測

    def test_markdown_outer_pipes_are_accepted(self):
        bid = self._create_full()
        raw_text = (
            "| 種類 | 分類 | 標題 | 內容 | 適用範圍 | 佐證來源 |\n"
            "| 品牌事實 | 定位 | 標題 | 內容 | 整個品牌 | 官網 |"
        )

        resp = self.client.post(f"/api/intake/brands/{bid}/paste/validate",
                                json={"raw_text": raw_text})

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["errors"], [])
        self.assertEqual(resp.json()["data_line_count"], 1)

    def test_markdown_separator_line_is_discarded(self):
        bid = self._create_full()
        raw_text = (
            "| 種類 | 分類 | 標題 | 內容 | 適用範圍 | 佐證來源 |\n"
            "|---|---|---|---|---|---|\n"
            "| 品牌事實 | 定位 | 標題 | 內容 | 整個品牌 | 官網 |"
        )

        resp = self.client.post(f"/api/intake/brands/{bid}/paste/validate",
                                json={"raw_text": raw_text})

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["errors"], [])
        self.assertEqual(resp.json()["data_line_count"], 1)


# ---------------------------------------------------------------------------
# 貼回：不認得的適用範圍——建立成新產品／歸到整個品牌，兩個出口都立即重驗、不用重貼
# ---------------------------------------------------------------------------

_UNKNOWN_SCOPE_SAMPLE = (
    "種類 | 分類 | 標題 | 內容 | 適用範圍 | 佐證來源\n"
    "產品事實 | 核心資訊 | 規格 | 一包十顆、免配水。 | 神秘軟糖 | 官網"
)


class PasteResolveScopeTest(_Base):
    def test_create_product_resolves_and_lands(self):
        bid = self._create_full()
        self.client.post(f"/api/intake/brands/{bid}/paste/validate",
                         json={"raw_text": _UNKNOWN_SCOPE_SAMPLE})
        resp = self.client.post(f"/api/intake/brands/{bid}/paste/resolve-scope",
                                json={"scope_name": "神秘軟糖", "action": "create_product"})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["errors"], [])
        names = {p["name"] for p in bi_repo.list_products(web.conn, bid)}
        self.assertIn("神秘軟糖", names)
        self.assertEqual(state.get_draft(bid)["pending_item_count"], 1)

    def test_assign_to_brand_rewrites_scope_without_creating_product(self):
        bid = self._create_full()
        self.client.post(f"/api/intake/brands/{bid}/paste/validate",
                         json={"raw_text": _UNKNOWN_SCOPE_SAMPLE})
        resp = self.client.post(f"/api/intake/brands/{bid}/paste/resolve-scope",
                                json={"scope_name": "神秘軟糖", "action": "assign_brand"})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["errors"], [])
        self.assertEqual(bi_repo.list_products(web.conn, bid), [])
        row = web.conn.execute(
            "SELECT scope_raw FROM intake_item WHERE brand_id = %s", (bid,)).fetchone()
        self.assertEqual(row["scope_raw"], "整個品牌")


# ---------------------------------------------------------------------------
# 貼回：AI 修格式背景工作（成功、失敗、超限攔截）——ai.run_paste_fix 原樣搬背景
# ---------------------------------------------------------------------------

class PasteFixBackgroundTest(_Base):
    def test_structured_rows_bypass_broken_text_and_land(self):
        bid = self._create_full()
        self.client.post(f"/api/intake/brands/{bid}/paste/validate",
                         json={"raw_text": "沒有表格的原始內容"})
        structured = {"rows": [{
            "kind": "品牌事實", "category": "定位", "title": "虛構定位",
            "content": "只在測試裡存在的定位內容。", "scope": "整個品牌", "evidence": "假官網",
        }]}
        intake_ai.PROVIDER = FakeProvider(
            response=_fake_response("這段文字故意不是表格", structured=structured))

        self.client.post(f"/api/intake/brands/{bid}/paste/fix/start")
        status = self._poll(bid, "paste_fix")

        self.assertEqual(status["status"], "done")
        self.assertEqual(state.get_draft(bid)["pending_item_count"], 1)
        self.assertEqual(intake_ai.PROVIDER.calls[0]["tools"][0]["name"], "submit_paste_rows")
        sent = intake_ai.PROVIDER.calls[0]["messages"][0]["content"]
        self.assertIn("不要用 Markdown 表格語法", sent)
        self.assertIn("顧客原話", sent)

    def test_success_reflows_lands_and_notifies(self):
        bid = self._create_full()
        bi_repo.create_product(web.conn, bid, name=script.MOCK_PRODUCT_NAME, actor="測試員")
        self.client.post(f"/api/intake/brands/{bid}/paste/validate",
                         json={"raw_text": script.PASTE_SAMPLE_ERRORS})
        intake_ai.PROVIDER = FakeProvider(response=_fake_response(script.PASTE_SAMPLE_FIXED))
        resp = self.client.post(f"/api/intake/brands/{bid}/paste/fix/start")
        self.assertEqual(resp.status_code, 200)
        self.assertIsNone(resp.json()["limit_block"])
        status = self._poll(bid, "paste_fix")
        self.assertEqual(status["status"], "done")

        draft = state.get_draft(bid)
        self.assertTrue(draft["paste_fix_used"])
        self.assertEqual(draft["pending_item_count"], 24)
        self.assertEqual(draft["step"], 5)

        matches = [r for r in core_interrupts.list_open(web.conn, brand_id=bid)
                  if r["category"] == "intake_ai_step_done"]
        self.assertTrue(any("貼回格式已修好" in m["message"] for m in matches))

    def test_failure_notifies_with_human_error(self):
        from app.llm.providers import MISSING_KEY_MESSAGE, AnthropicProvider
        bid = self._create_full()
        self.client.post(f"/api/intake/brands/{bid}/paste/validate",
                         json={"raw_text": "沒有表格的內容"})
        intake_ai.PROVIDER = AnthropicProvider()  # 無金鑰：送出前就會擋
        resp = self.client.post(f"/api/intake/brands/{bid}/paste/fix/start")
        self.assertEqual(resp.status_code, 200)
        status = self._poll(bid, "paste_fix")
        self.assertEqual(status["status"], "failed")
        self.assertEqual(status["error"], MISSING_KEY_MESSAGE)
        matches = [r for r in core_interrupts.list_open(web.conn, brand_id=bid)
                  if r["category"] == "intake_ai_step_done"]
        self.assertTrue(any("貼回修格式失敗" in m["message"] for m in matches))

    def test_over_budget_blocks_before_calling_ai(self):
        bid = self._create_full()
        self.client.post(f"/api/intake/brands/{bid}/budget", json={"limit": 0.05})
        intake_ai.PROVIDER = FakeProvider(response=_fake_response("不該被呼叫"))
        resp = self.client.post(f"/api/intake/brands/{bid}/paste/fix/start")
        self.assertEqual(resp.status_code, 200)
        block = resp.json()["limit_block"]
        self.assertIsNotNone(block)
        self.assertEqual(block["kind"], "paste_fix")
        self.assertEqual(intake_ai.PROVIDER.calls, [])


# ---------------------------------------------------------------------------
# AI 帶回的內容清單／逐條處理（三種出口）／「剩餘全部先存成待確認」
# ---------------------------------------------------------------------------

class ReviewTest(_Base):
    def _to_review(self, bid: str) -> None:
        bi_repo.create_product(web.conn, bid, name=script.MOCK_PRODUCT_NAME, actor="測試員")
        resp = self.client.post(f"/api/intake/brands/{bid}/paste/validate",
                                json={"raw_text": script.PASTE_SAMPLE_SUCCESS})
        self.assertEqual(resp.json()["errors"], [])

    def test_list_shape_and_severity_only_for_rule_kind(self):
        bid = self._create_full()
        self._to_review(bid)
        resp = self.client.get(f"/api/intake/brands/{bid}/review")
        self.assertEqual(resp.status_code, 200)
        items = resp.json()["data"]
        self.assertEqual(len(items), 24)
        expected_keys = {"id", "i", "kind", "category", "title", "content", "scope",
                         "evidence", "dup_hint", "severity"}
        self.assertEqual(set(items[0].keys()), expected_keys)
        rule_item = next(it for it in items if it["kind"] == "限制規則")
        self.assertEqual(rule_item["severity"], "soft")
        fact_item = next(it for it in items if it["kind"] == "品牌事實")
        self.assertIsNone(fact_item["severity"])

    def test_item_get_then_confirm_writes_target_table(self):
        bid = self._create_full()
        self._to_review(bid)
        item = self.client.get(f"/api/intake/brands/{bid}/review/1").json()["data"]
        self.assertEqual(item["i"], 1)
        resp = self.client.post(f"/api/intake/brands/{bid}/review/1", json={
            "outcome": "confirm", "kind": item["kind"], "category": item["category"],
            "title": item["title"], "content": item["content"], "scope": item["scope"],
            "severity": "soft",
        })
        self.assertEqual(resp.status_code, 204)
        row = web.conn.execute(
            "SELECT outcome, target_table FROM intake_item WHERE brand_id = %s AND row_no = 1",
            (bid,)).fetchone()
        self.assertEqual(row["outcome"], "confirmed")
        self.assertIsNotNone(row["target_table"])

    def test_customer_quote_confirm_reaches_existing_prompt_consumer(self):
        bid = self._create_full()
        quote = "包裝很漂亮，可是第一次打開時我完全找不到沖泡說明。"
        raw_text = (
            "種類 | 分類 | 標題 | 內容 | 適用範圍 | 佐證來源\n"
            f"顧客原話 | 功能任務 | 找不到使用說明 | {quote} | 整個品牌 | 虛構 Dcard 討論串"
        )
        pasted = self.client.post(f"/api/intake/brands/{bid}/paste/validate",
                                  json={"raw_text": raw_text})
        self.assertEqual(pasted.json()["errors"], [])
        item = self.client.get(f"/api/intake/brands/{bid}/review/1").json()["data"]
        self.assertEqual(item["kind"], "顧客原話")

        confirmed = self.client.post(f"/api/intake/brands/{bid}/review/1", json={
            "outcome": "confirm", "kind": item["kind"], "category": item["category"],
            "title": item["title"], "content": item["content"], "scope": item["scope"],
        })

        self.assertEqual(confirmed.status_code, 204)
        voices = bi_repo.list_customer_voices(web.conn, bid, status="active")
        self.assertEqual(len(voices), 1)
        self.assertEqual(voices[0]["raw_text"], quote)
        self.assertEqual(voices[0]["source_detail"], "虛構 Dcard 討論串")
        self.assertEqual(voices[0]["extraction"][0]["task_layer"], "functional")
        row = web.conn.execute(
            "SELECT target_table FROM intake_item WHERE brand_id = %s AND row_no = 1", (bid,)
        ).fetchone()
        self.assertEqual(row["target_table"], "customer_voice")

    def test_pending_outcome_does_not_write_rule_table(self):
        bid = self._create_full()
        self._to_review(bid)
        rule_item = next(it for it in self.client.get(f"/api/intake/brands/{bid}/review").json()["data"]
                         if it["kind"] == "限制規則")
        before = len(bi_repo.list_rules_for_brand(web.conn, bid))
        resp = self.client.post(f"/api/intake/brands/{bid}/review/{rule_item['i']}", json={
            "outcome": "pending", "kind": "限制規則", "category": rule_item["category"],
            "title": rule_item["title"], "content": rule_item["content"], "scope": rule_item["scope"],
            "severity": "soft",
        })
        self.assertEqual(resp.status_code, 204)
        self.assertEqual(len(bi_repo.list_rules_for_brand(web.conn, bid)), before)

    def test_discard_outcome_ignores_field_validation(self):
        bid = self._create_full()
        self._to_review(bid)
        resp = self.client.post(f"/api/intake/brands/{bid}/review/2", json={"outcome": "discard"})
        self.assertEqual(resp.status_code, 204)
        row = web.conn.execute(
            "SELECT outcome FROM intake_item WHERE brand_id = %s AND row_no = 2", (bid,)).fetchone()
        self.assertEqual(row["outcome"], "discarded")

    def test_missing_title_errors(self):
        bid = self._create_full()
        self._to_review(bid)
        resp = self.client.post(f"/api/intake/brands/{bid}/review/1", json={
            "outcome": "confirm", "title": "", "content": "x", "category": "定位", "scope": "整個品牌",
        })
        self.assertEqual(resp.status_code, 400)  # COPY trim：精確中文文案不測

    def test_product_fact_cannot_stay_whole_brand(self):
        bid = self._create_full()
        self._to_review(bid)
        product_item = next(it for it in self.client.get(f"/api/intake/brands/{bid}/review").json()["data"]
                            if it["kind"] == "產品事實")
        resp = self.client.post(f"/api/intake/brands/{bid}/review/{product_item['i']}", json={
            "outcome": "confirm", "title": product_item["title"], "content": product_item["content"],
            "category": product_item["category"], "scope": "整個品牌",
        })
        self.assertEqual(resp.status_code, 400)  # COPY trim：精確中文文案不測

    def test_review_item_not_found_is_404(self):
        bid = self._create_full()
        self._to_review(bid)
        resp = self.client.get(f"/api/intake/brands/{bid}/review/999")
        self.assertEqual(resp.status_code, 404)

    def test_review_list_after_last_item_resolved_returns_empty_not_404(self):
        """迴歸（B3 第三段）：解決最後一筆會把草稿標成 completed（S4.65），緊接著前端的
        GET /review 若因草稿不再 active 就回 404，會顯示不出「導回品牌頁」的完成訊息。"""
        bid = self._create_full()
        resp = self.client.post(f"/api/intake/brands/{bid}/paste/validate", json={
            "raw_text": "種類 | 分類 | 標題 | 內容 | 適用範圍 | 佐證來源\n"
                        "品牌事實 | 定位 | 定位一句話 | 中高價位的機能軟糖。 | 整個品牌 | 官網",
        })
        self.assertEqual(resp.json()["errors"], [])
        resp = self.client.post(f"/api/intake/brands/{bid}/review/1", json={"outcome": "discard"})
        self.assertEqual(resp.status_code, 204)
        resp = self.client.get(f"/api/intake/brands/{bid}/review")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["data"], [])

    def test_pending_all_skips_product_fact_missing_product_designation(self):
        """S4.62：產品事實缺產品指定的列跳過留在清單，其餘照樣批次存成待確認。"""
        bid = self._create_full()
        text = (
            "種類 | 分類 | 標題 | 內容 | 適用範圍 | 佐證來源\n"
            "品牌事實 | 定位 | 定位一句話 | 中高價位的機能軟糖。 | 整個品牌 | 官網\n"
            "產品事實 | 核心資訊 | 規格 | 一包十顆、免配水。 | 整個品牌 | 官網"
        )
        resp = self.client.post(f"/api/intake/brands/{bid}/paste/validate", json={"raw_text": text})
        self.assertEqual(resp.json()["errors"], [])
        resp = self.client.post(f"/api/intake/brands/{bid}/review/pending-all")
        self.assertEqual(resp.status_code, 204)
        remaining = self.client.get(f"/api/intake/brands/{bid}/review").json()["data"]
        self.assertEqual(len(remaining), 1)
        self.assertEqual(remaining[0]["kind"], "產品事實")
        row = web.conn.execute(
            "SELECT outcome FROM intake_item WHERE brand_id = %s AND row_no = 1", (bid,)).fetchone()
        self.assertEqual(row["outcome"], "pending_saved")


if __name__ == "__main__":
    unittest.main()
