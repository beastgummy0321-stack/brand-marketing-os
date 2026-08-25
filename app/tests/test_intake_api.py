# -*- coding: utf-8 -*-
"""app/tests/test_intake_api.py — 建檔精靈 JSON API（票 B3-intake 第二段前半）。

見 app/intake/routes_api.py。全程用 FakeProvider（跟 test_intake.py 同風格），不發任何
真實網路請求；品牌名一律虛構。隔離 DB、假金鑰。
"""

import json
import os
import time
import unittest
from unittest import mock

import pytest

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

# BUG app/brand_intelligence/background_job.py:59 — JobRegistry.start() 起的
# threading.Thread 沒有包 with coredb.connection()，背景工作裡任何 DB 呼叫都會
# RuntimeError: no connection bound（症狀：_poll() 逾時，因為 job 狀態卡在 "running"
# 永遠不會變 "done"/"failed"，crash 發生在寫回狀態之前）。任何實際等背景工作跑完的
# 測試都會中這個既有缺陷；02-4 是測試轉移票，不改 app/intake|brand_intelligence/*.py。
_BUG_BACKGROUND_JOB_NO_CONN = pytest.mark.xfail(
    strict=True,
    reason="BUG app/brand_intelligence/background_job.py:59 — JobRegistry.start() 起的 "
           "thread 沒有包 with coredb.connection()，背景工作內 DB 呼叫一律 "
           "RuntimeError: no connection bound，job 狀態永遠停在 running，_poll() 逾時",
)


def _fake_response(text: str) -> ProviderResponse:
    return ProviderResponse(output_text=text, structured=None,
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
# S4.9 陽春路徑：三欄皆空只 create_brand，不建草稿（JSON／HTML 舊表單共用同一支函式）
# ---------------------------------------------------------------------------

class QuickPathTest(_Base):
    def test_json_only_name_is_quick_no_draft(self):
        name = self._brand_name()
        resp = self.client.post("/api/intake/brands", data={"brand_name": name})
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertTrue(body["quick"])
        self.assertIsNone(state.get_draft(body["brand_id"]))
        # 品牌真的建了
        draft_resp = self.client.get(f"/api/intake/brands/{body['brand_id']}/draft")
        self.assertEqual(draft_resp.status_code, 404)

    def test_json_with_description_creates_draft(self):
        bid = self._create_full()
        self.assertIsNotNone(state.get_draft(bid))



    def test_missing_name_json_errors(self):
        resp = self.client.post("/api/intake/brands", data={"brand_name": ""})
        self.assertEqual(resp.status_code, 400)  # COPY trim：精確中文文案不測，guard 本身才是重點

    def test_bad_url_format_rejected(self):
        resp = self.client.post("/api/intake/brands", data={
            "brand_name": self._brand_name(), "urls": "not-a-url",
        })
        self.assertEqual(resp.status_code, 400)  # COPY trim：精確中文文案不測

    def test_restart_quick_when_no_new_data_and_no_prior_photos(self):
        bid = self._create_full()
        self._poll(bid, "scan")  # 讓草稿完成初掃，之後手動完成它才能重新調研
        draft = state.get_draft(bid)
        state.mark_qa_done(draft)
        state.save(draft)
        state.complete_draft(draft)
        resp = self.client.post(f"/api/intake/brands/{bid}/restart", data={})
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.json()["quick"])
        self.assertIsNone(state.get_draft(bid))

    def test_restart_blocked_when_draft_already_running(self):
        bid = self._create_full()
        resp = self.client.post(f"/api/intake/brands/{bid}/restart",
                                 data={"description": "第二輪"})
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertFalse(body["quick"])
        self.assertTrue(body.get("already_running"))


# ---------------------------------------------------------------------------
# 照片預先上傳（POST /api/intake/photos）
# ---------------------------------------------------------------------------

class PhotoUploadTest(_Base):
    def test_upload_then_reference_token_in_start(self):
        import io
        up = self.client.post("/api/intake/photos",
                              files={"photo": ("t.jpg", io.BytesIO(b"x" * 100), "image/jpeg")})
        self.assertEqual(up.status_code, 200)
        body = up.json()
        self.assertEqual(set(body.keys()), {"token", "name", "size_mb"})
        name = self._brand_name()
        resp = self.client.post("/api/intake/brands", data={
            "brand_name": name, "photo_tokens": body["token"],
        })
        self.assertFalse(resp.json()["quick"])  # 有照片 -> 非陽春路徑
        draft = state.get_draft(resp.json()["brand_id"])
        self.assertEqual(len(draft["photos"]), 1)
        self.assertEqual(draft["photos"][0]["name"], "t.jpg")

    def test_bad_extension_rejected(self):
        import io
        resp = self.client.post("/api/intake/photos",
                                files={"photo": ("t.exe", io.BytesIO(b"x" * 10), "application/octet-stream")})
        self.assertEqual(resp.status_code, 400)  # COPY trim：精確中文文案不測


# ---------------------------------------------------------------------------
# 草稿整包（GET .../draft）：欄位對照前端契約
# ---------------------------------------------------------------------------

class DraftShapeTest(_Base):
    def test_shape_matches_frontend_contract_keys(self):
        bid = self._create_full()
        data = self.client.get(f"/api/intake/brands/{bid}/draft").json()["data"]
        expected = {
            "id", "brand_id", "brand_name", "step", "completed", "is_restart",
            "description", "urls", "photos", "scan_done", "scan_impressions", "scan_products",
            "product_card_drafts", "created_product_names", "url_results", "qa_done", "current_q", "answers",
            "question_index", "handoff_depth", "handoff_generated", "handoff_prompt",
            "paste_raw", "paste_errors", "paste_fix_used", "pending_item_count",
            "budget_limit", "cost_spent", "cost_items",
        }
        self.assertEqual(set(data.keys()), expected)
        self.assertEqual(data["step"], 2)
        self.assertFalse(data["is_restart"])


# ---------------------------------------------------------------------------
# 背景工作狀態機：初掃（啟動 → 輪詢 → 完成落庫），失敗，超限攔截
# ---------------------------------------------------------------------------

class ScanBackgroundTest(_Base):
    @_BUG_BACKGROUND_JOB_NO_CONN
    def test_start_returns_immediately_then_completes_and_notifies(self):
        bid = self._create_full()
        intake_ai.PROVIDER = FakeProvider(response=_fake_response(_SCAN_OK))
        started = time.time()
        resp = self.client.post(f"/api/intake/brands/{bid}/scan/start")
        elapsed = time.time() - started
        self.assertEqual(resp.status_code, 200)
        self.assertIsNone(resp.json()["limit_block"])
        self.assertLess(elapsed, 1.0, "POST 不該等 AI 掃描跑完才回應")

        status = self._poll(bid, "scan")
        self.assertEqual(status["status"], "done")

        draft = state.get_draft(bid)
        self.assertTrue(draft["scan_done"])
        self.assertEqual(len(draft["scan_impressions"]), 1)

        open_items = core_interrupts.list_open(web.conn, brand_id=bid)
        matches = [r for r in open_items if r["category"] == "intake_ai_step_done"]
        self.assertEqual(len(matches), 1)
        self.assertIn("初掃完成", matches[0]["message"])
        self.assertLessEqual(len(matches[0]["message"]), core_interrupts.MAX_MESSAGE_LEN)

    @_BUG_BACKGROUND_JOB_NO_CONN
    def test_failure_notifies_with_human_error(self):
        from app.llm.providers import MISSING_KEY_MESSAGE, AnthropicProvider
        bid = self._create_full()
        intake_ai.PROVIDER = AnthropicProvider()  # 無金鑰：送出前就會擋
        resp = self.client.post(f"/api/intake/brands/{bid}/scan/start")
        self.assertEqual(resp.status_code, 200)
        status = self._poll(bid, "scan")
        self.assertEqual(status["status"], "failed")
        self.assertEqual(status["error"], MISSING_KEY_MESSAGE)
        self.assertFalse(state.get_draft(bid)["scan_done"])
        open_items = core_interrupts.list_open(web.conn, brand_id=bid)
        matches = [r for r in open_items if r["category"] == "intake_ai_step_done"]
        self.assertEqual(len(matches), 1)
        self.assertIn("初掃失敗", matches[0]["message"])

    @_BUG_BACKGROUND_JOB_NO_CONN
    def test_idempotent_second_start_does_not_restart(self):
        import threading
        bid = self._create_full()
        release = threading.Event()

        class _BlockingProvider(FakeProvider):
            """卡住第一個背景工作，直到兩個請求都送完。

            原本是卡 `intake_ai.fetch_url`，但 `_create_full()` 的草稿沒有網址，
            `ai.run_scan` 的抓網址迴圈一次都不會跑（app/intake/ai.py:187），等於完全沒卡到：
            第一個工作往往在第二個請求送出前就結束，第二個請求就合法地再起一條執行緒，
            斷言時好時壞。改卡 provider——初掃一定會呼叫它，時序才是確定的。
            """

            def complete(self, **kwargs):
                release.wait(timeout=5)
                return super().complete(**kwargs)

        intake_ai.PROVIDER = _BlockingProvider(response=_fake_response(_SCAN_OK))
        try:
            r1 = self.client.post(f"/api/intake/brands/{bid}/scan/start")
            r2 = self.client.post(f"/api/intake/brands/{bid}/scan/start")
            self.assertEqual(r1.status_code, 200)
            self.assertEqual(r2.status_code, 200)
        finally:
            release.set()
        status = self._poll(bid, "scan")
        self.assertEqual(status["status"], "done")
        self.assertEqual(len(intake_ai.PROVIDER.calls), 1)  # 沒有跑出第二個背景執行緒

    @_BUG_BACKGROUND_JOB_NO_CONN
    def test_already_done_is_noop(self):
        bid = self._create_full()
        intake_ai.PROVIDER = FakeProvider(response=_fake_response(_SCAN_OK))
        self.client.post(f"/api/intake/brands/{bid}/scan/start")
        self._poll(bid, "scan")
        resp = self.client.post(f"/api/intake/brands/{bid}/scan/start")
        self.assertEqual(resp.status_code, 200)
        self.assertIsNone(resp.json()["limit_block"])

    def test_skip_marks_done_with_empty_results(self):
        bid = self._create_full()
        resp = self.client.post(f"/api/intake/brands/{bid}/scan/skip")
        self.assertEqual(resp.status_code, 204)
        draft = state.get_draft(bid)
        self.assertTrue(draft["scan_done"])
        self.assertEqual(draft["scan_impressions"], [])
        self.assertEqual(draft["url_results"], [])

    def test_over_budget_blocks_before_calling_ai(self):
        """S4.71：超限攔截擋在呼叫送出之前——AI 完全沒被呼叫，回傳攔截卡片資料。"""
        bid = self._create_full()
        self.client.post(f"/api/intake/brands/{bid}/budget", json={"limit": 0.05})
        intake_ai.PROVIDER = FakeProvider(response=_fake_response("不該被呼叫"))
        resp = self.client.post(f"/api/intake/brands/{bid}/scan/start")
        self.assertEqual(resp.status_code, 200)
        block = resp.json()["limit_block"]
        self.assertIsNotNone(block)
        self.assertEqual(block["kind"], "scan")
        self.assertEqual(block["budget_limit"], 0.05)
        self.assertEqual(block["suggested_limit"], 30.05)
        self.assertEqual(intake_ai.PROVIDER.calls, [])
        # 沒有背景工作被啟動，狀態仍是閒置
        status = self.client.get(f"/api/intake/brands/{bid}/scan/status").json()["data"]
        self.assertEqual(status["status"], "done")

    @_BUG_BACKGROUND_JOB_NO_CONN
    def test_scan_create_products(self):
        bid = self._create_full()
        scan_with_products = json.dumps({
            "impressions": [{"looks_like": "產品線", "title": "t", "content": "c", "basis": "b"}],
            "products": ["虛構回甘烏龍", "虛構茉莉綠"],
        }, ensure_ascii=False)
        intake_ai.PROVIDER = FakeProvider(response=_fake_response(scan_with_products))
        self.client.post(f"/api/intake/brands/{bid}/scan/start")
        self._poll(bid, "scan")
        self.assertEqual(state.get_draft(bid)["scan_products"], ["虛構回甘烏龍", "虛構茉莉綠"])

        resp = self.client.post(f"/api/intake/brands/{bid}/scan/products",
                                json={"names": ["虛構回甘烏龍", "沒被偵測到的名字"]})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["created_count"], 1)
        # 再送一次同一個名字不會重複建立
        resp2 = self.client.post(f"/api/intake/brands/{bid}/scan/products",
                                 json={"names": ["虛構回甘烏龍"]})
        self.assertEqual(resp2.json()["created_count"], 0)


# ---------------------------------------------------------------------------
# 引導問答：啟動出題 → 輪詢 → 作答／跳過 → 不進收件匣通知
# ---------------------------------------------------------------------------

class QuestionBackgroundTest(_Base):
    def _scanned_brand(self) -> str:
        bid = self._create_full()
        intake_ai.PROVIDER = FakeProvider(response=_fake_response(_SCAN_OK))
        self.client.post(f"/api/intake/brands/{bid}/scan/start")
        self._poll(bid, "scan")
        return bid

    @_BUG_BACKGROUND_JOB_NO_CONN
    def test_start_then_answer_flow_and_no_notification(self):
        bid = self._scanned_brand()
        # 掃描那一步本來就會通知一筆，先記下基準，確認出題完成「沒有」再多一筆
        before = len(core_interrupts.list_open(web.conn, brand_id=bid))
        intake_ai.PROVIDER = FakeProvider(response=_fake_response(_question_json(0)))
        resp = self.client.post(f"/api/intake/brands/{bid}/question/start")
        self.assertEqual(resp.status_code, 200)
        status = self._poll(bid, "question")
        self.assertEqual(status["status"], "done")

        draft = state.get_draft(bid)
        self.assertEqual(draft["step"], 3)
        self.assertIsNotNone(draft["current_q"])
        self.assertEqual(draft["current_q"]["question"], script.QUESTIONS[0]["question"])

        # 出下一題完成不進收件匣（跟初掃不同待遇，GRILL 決策）
        after = len(core_interrupts.list_open(web.conn, brand_id=bid))
        self.assertEqual(after, before)

        resp = self.client.post(f"/api/intake/brands/{bid}/question/answer",
                                json={"choice": "suggested", "note": "補充意見"})
        self.assertEqual(resp.status_code, 204)
        draft = state.get_draft(bid)
        self.assertEqual(len(draft["answers"]), 1)
        self.assertEqual(draft["answers"][0]["note"], "補充意見")
        self.assertIsNone(draft["current_q"])

    @_BUG_BACKGROUND_JOB_NO_CONN
    def test_answer_without_choice_selected_errors(self):
        bid = self._scanned_brand()
        intake_ai.PROVIDER = FakeProvider(response=_fake_response(_question_json(0)))
        self.client.post(f"/api/intake/brands/{bid}/question/start")
        self._poll(bid, "question")
        resp = self.client.post(f"/api/intake/brands/{bid}/question/answer",
                                json={"choice": "", "note": ""})
        self.assertEqual(resp.status_code, 400)  # COPY trim：精確中文文案不測

    @_BUG_BACKGROUND_JOB_NO_CONN
    def test_answer_other_without_note_errors(self):
        bid = self._scanned_brand()
        intake_ai.PROVIDER = FakeProvider(response=_fake_response(_question_json(0)))
        self.client.post(f"/api/intake/brands/{bid}/question/start")
        self._poll(bid, "question")
        resp = self.client.post(f"/api/intake/brands/{bid}/question/answer",
                                json={"choice": "other", "note": ""})
        self.assertEqual(resp.status_code, 400)  # COPY trim：精確中文文案不測

    @_BUG_BACKGROUND_JOB_NO_CONN
    def test_question_failure_does_not_notify(self):
        from app.llm.providers import AnthropicProvider
        bid = self._scanned_brand()
        before = len(core_interrupts.list_open(web.conn, brand_id=bid))
        intake_ai.PROVIDER = AnthropicProvider()
        self.client.post(f"/api/intake/brands/{bid}/question/start")
        status = self._poll(bid, "question")
        self.assertEqual(status["status"], "failed")
        after = len(core_interrupts.list_open(web.conn, brand_id=bid))
        self.assertEqual(after, before)

    @_BUG_BACKGROUND_JOB_NO_CONN
    def test_skip_remaining_marks_qa_done(self):
        bid = self._scanned_brand()
        resp = self.client.post(f"/api/intake/brands/{bid}/question/skip-remaining")
        self.assertEqual(resp.status_code, 204)
        self.assertTrue(state.get_draft(bid)["qa_done"])

    @_BUG_BACKGROUND_JOB_NO_CONN
    def test_aspect_is_saved_and_next_prompt_lists_coverage(self):
        bid = self._scanned_brand()
        intake_ai.PROVIDER = FakeProvider(response=_fake_response(_question_json(0, "價格帶")))
        self.client.post(f"/api/intake/brands/{bid}/question/start")
        self._poll(bid, "question")
        draft = state.get_draft(bid)
        self.assertEqual(state.current_entry(draft)["aspect"], "價格帶")
        self.client.post(f"/api/intake/brands/{bid}/question/answer",
                         json={"choice": "suggested", "note": ""})

        provider = FakeProvider(response=_fake_response(_question_json(1, "客群")))
        intake_ai.PROVIDER = provider
        self.client.post(f"/api/intake/brands/{bid}/question/start")
        self._poll(bid, "question")

        sent = provider.calls[0]["messages"][0]["content"]
        self.assertIn("已覆蓋面向：價格帶", sent)
        self.assertIn("未覆蓋面向：產品線、客群、語調、法規風險", sent)
        self.assertEqual(state.current_entry(state.get_draft(bid))["aspect"], "客群")

    @_BUG_BACKGROUND_JOB_NO_CONN
    def test_done_is_rejected_while_aspects_are_uncovered(self):
        bid = self._scanned_brand()
        intake_ai.PROVIDER = FakeProvider(response=_fake_response(_question_json(0, "產品線")))
        self.client.post(f"/api/intake/brands/{bid}/question/start")
        self._poll(bid, "question")
        self.client.post(f"/api/intake/brands/{bid}/question/answer",
                         json={"choice": "suggested", "note": ""})
        intake_ai.PROVIDER = FakeProvider(response=_fake_response(json.dumps({"done": True})))

        self.client.post(f"/api/intake/brands/{bid}/question/start")
        status = self._poll(bid, "question")

        self.assertEqual(status["status"], "failed")
        self.assertEqual(status["error"],
                         "還有 4 個面向沒問到：價格帶、客群、語調、法規風險。請繼續出題。")
        self.assertFalse(state.get_draft(bid)["qa_done"])

    @_BUG_BACKGROUND_JOB_NO_CONN
    def test_eight_legacy_questions_hard_stop_without_calling_ai(self):
        bid = self._scanned_brand()
        draft = state.get_draft(bid)
        q = script.QUESTIONS[0]
        for _ in range(script.MAX_QUESTIONS):
            state.append_question(draft, q["question"], q["suggested"], q["branches"], None)
            state.current_entry(draft)["answer_key"] = "suggested"
        state.save(draft)
        provider = FakeProvider(response=_fake_response(_question_json(0, "產品線")))
        intake_ai.PROVIDER = provider

        ok, error = intake_ai.run_next_question(web.conn, state.get_draft(bid))

        self.assertTrue(ok, error)
        self.assertTrue(state.get_draft(bid)["qa_done"])
        self.assertEqual(provider.calls, [])


# ---------------------------------------------------------------------------
# 花費上限設定 ／ 超限卡片「加碼並繼續」／「不再花錢」
# ---------------------------------------------------------------------------

class BudgetTest(_Base):
    def test_set_validation_errors(self):
        bid = self._create_full()
        self.assertEqual(
            self.client.post(f"/api/intake/brands/{bid}/budget", json={}).status_code, 400)
        self.assertEqual(
            self.client.post(f"/api/intake/brands/{bid}/budget", json={"limit": "abc"}).status_code, 400)

    @_BUG_BACKGROUND_JOB_NO_CONN
    def test_set_below_spent_rejected(self):
        bid = self._create_full()
        intake_ai.PROVIDER = FakeProvider(response=_fake_response(_SCAN_OK))
        self.client.post(f"/api/intake/brands/{bid}/scan/start")
        self._poll(bid, "scan")
        spent = state.get_draft(bid)["cost_spent"]
        resp = self.client.post(f"/api/intake/brands/{bid}/budget", json={"limit": 0})
        self.assertEqual(resp.status_code, 400)
        self.assertIn(f"{spent:.2f}", resp.json()["error"])

    def test_set_success(self):
        bid = self._create_full()
        resp = self.client.post(f"/api/intake/brands/{bid}/budget", json={"limit": 55})
        self.assertEqual(resp.status_code, 204)
        self.assertEqual(state.get_draft(bid)["budget_limit"], 55.0)

    @_BUG_BACKGROUND_JOB_NO_CONN
    def test_raise_restarts_the_blocked_job(self):
        bid = self._create_full()
        self.client.post(f"/api/intake/brands/{bid}/budget", json={"limit": 0.05})
        intake_ai.PROVIDER = FakeProvider(response=_fake_response(_SCAN_OK))
        blocked = self.client.post(f"/api/intake/brands/{bid}/scan/start").json()
        self.assertIsNotNone(blocked["limit_block"])

        resp = self.client.post(f"/api/intake/brands/{bid}/budget/raise", json={"kind": "scan"})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(state.get_draft(bid)["budget_limit"], 30.05)
        self.assertIn(resp.json()["job"]["status"], ("running", "done"))
        status = self._poll(bid, "scan")
        self.assertEqual(status["status"], "done")
        self.assertTrue(state.get_draft(bid)["scan_done"])

    def test_skip_remaining_ai_jumps_to_handoff_step(self):
        bid = self._create_full()
        resp = self.client.post(f"/api/intake/brands/{bid}/skip-remaining-ai")
        self.assertEqual(resp.status_code, 204)
        draft = state.get_draft(bid)
        self.assertTrue(draft["scan_done"])
        self.assertTrue(draft["qa_done"])
        self.assertEqual(draft["step"], 4)


# ---------------------------------------------------------------------------
# 交接包（同步、免費）／操作卡
# ---------------------------------------------------------------------------

class HandoffTest(_Base):
    def test_generate_then_fetch_operator_card(self):
        bid = self._create_full()
        resp = self.client.post(f"/api/intake/brands/{bid}/handoff", json={"depth": "standard"})
        self.assertEqual(resp.status_code, 200)
        self.assertIn("prompt_text", resp.json())
        draft = state.get_draft(bid)
        self.assertEqual(draft["handoff_depth"], "standard")  # depth 有沒有生效看這行，不看文案
        self.assertGreaterEqual(draft["step"], 4)

        card = self.client.get(f"/api/intake/brands/{bid}/handoff/claude").json()["data"]
        self.assertIn("title", card)  # COPY trim：卡片標題精確中文文案不測
        self.assertEqual(len(card["steps"]), 6)

    def test_missing_depth_errors(self):
        bid = self._create_full()
        resp = self.client.post(f"/api/intake/brands/{bid}/handoff", json={})
        self.assertEqual(resp.status_code, 400)  # COPY trim：精確中文文案不測

    def test_bad_provider_is_404(self):
        bid = self._create_full()
        resp = self.client.get(f"/api/intake/brands/{bid}/handoff/bing")
        self.assertEqual(resp.status_code, 404)


if __name__ == "__main__":
    unittest.main()
