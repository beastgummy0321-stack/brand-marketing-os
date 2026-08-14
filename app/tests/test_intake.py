# -*- coding: utf-8 -*-
"""app/tests/test_intake.py — 建檔精靈接真：草稿持久化、LLM 串接、花費、R10 出口。

見 docs/design/07-settings-and-intake-contract.md §4、docs/design/03-data-model.md §3A。
全程用 FakeProvider（跟 test_llm_gateway 同風格），不發任何真實網路請求；
「無金鑰人話錯誤」那條用真的 AnthropicProvider——它在打出網路請求之前就會擋下。
"""

import atexit
import io
import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

# 先備好暫存 DB 的環境變數，才能 import app.main（它在 import 當下就會連線＋跑 migrations）。
_tmpdir = tempfile.mkdtemp(prefix="brand_os_intake_")

from fastapi.testclient import TestClient  # noqa: E402

import app.main as main  # noqa: E402
from app.brand_intelligence import repository as bi_repo  # noqa: E402
from app.intake import ai as intake_ai  # noqa: E402
from app.intake import card_test, script, state  # noqa: E402
from app.intake import repository as ir  # noqa: E402
from app.llm import pricing  # noqa: E402
from app.llm.providers import (  # noqa: E402
    MISSING_KEY_MESSAGE, AnthropicProvider, FakeProvider, ProviderResponse, Usage,
)



def _cleanup():
    try:
        main.conn.close()
    except Exception:
        pass
    shutil.rmtree(_tmpdir, ignore_errors=True)


atexit.register(_cleanup)

_BRAND_SEQ = [0]


def _fake_response(text: str, in_tok: int = 100, out_tok: int = 50) -> ProviderResponse:
    return ProviderResponse(output_text=text, structured=None,
                            usage=Usage(input_tokens=in_tok, output_tokens=out_tok),
                            stop_reason="end_turn")


def _question_json(i: int = 0) -> str:
    q = script.QUESTIONS[i]
    return json.dumps({"done": False, "question": q["question"],
                       "suggested": {"label": q["suggested"]["label"], "desc": q["suggested"]["desc"]},
                       "branches": [{"label": b["label"], "desc": b["desc"]} for b in q["branches"]]},
                      ensure_ascii=False)


class IntakeWizardTest(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(main.app)
        main.conn.execute("DELETE FROM app_setting")
        main.conn.commit()
        # 隔離環境變數：金鑰／模型只看 DB 設定（沒設＝沒金鑰、預設模型 opus）
        self._envpatch = mock.patch.dict(os.environ, {}, clear=False)
        self._envpatch.start()
        os.environ.pop("ANTHROPIC_API_KEY", None)
        os.environ.pop("BRAND_OS_LLM_MODEL", None)
        self._orig_provider = intake_ai.PROVIDER
        self._orig_fetch = intake_ai.fetch_url
        intake_ai.fetch_url = lambda url: (False, "")

    def tearDown(self):
        intake_ai.PROVIDER = self._orig_provider
        intake_ai.fetch_url = self._orig_fetch
        self._envpatch.stop()

    # -- helpers ------------------------------------------------------------

    def _new_wizard_brand(self) -> str:
        _BRAND_SEQ[0] += 1
        name = f"精靈測試品牌{_BRAND_SEQ[0]}"
        resp = self.client.post("/brands/intake/new", data={
            "name": name, "client_name": "", "description": "測試品牌的描述文字，超過十個字。",
            "url_1": "", "url_2": "", "url_3": "", "url_4": "", "url_5": "",
        }, files=[("photos", ("t.jpg", io.BytesIO(b"x" * 100), "image/jpeg"))],
            follow_redirects=False)
        assert resp.status_code == 303
        return resp.headers["location"].split("/brands/")[1].split("/")[0]

    def _run_scan(self, brand_id: str):
        intake_ai.PROVIDER = FakeProvider(response=_fake_response(
            json.dumps({"impressions": script.SCAN_IMPRESSIONS}, ensure_ascii=False)))
        return self.client.get(f"/brands/{brand_id}/intake/scan/progress?run=1",
                                follow_redirects=False)

    # -- 草稿持久化 ----------------------------------------------------------

    def test_draft_persisted_and_survives_restart(self):
        brand_id = self._new_wizard_brand()
        row = ir.get_active_draft(main.conn, brand_id)
        self.assertIsNotNone(row)
        self.assertEqual(row["status"], "draft")
        self.assertEqual(row["cost_limit"], script.DEFAULT_BUDGET)

        # 等同重啟伺服器：重開連線後草稿仍在、可續接
        main.reopen_connection()
        draft = state.get_draft(brand_id)
        self.assertIsNotNone(draft)
        self.assertEqual(draft["step"], 2)
        self.assertIn("/intake/scan", draft["resume_path"])

    def test_budget_limit_default_reads_setting(self):
        from app.core import settings as coresettings
        coresettings.set_setting(main.conn, "intake_budget_limit", "55")
        brand_id = self._new_wizard_brand()
        self.assertEqual(ir.get_active_draft(main.conn, brand_id)["cost_limit"], 55.0)

    # -- 初掃 ----------------------------------------------------------------

    def test_scan_success_stores_impressions_and_real_cost(self):
        brand_id = self._new_wizard_brand()
        resp = self._run_scan(brand_id)
        self.assertEqual(resp.status_code, 303)
        self.assertTrue(resp.headers["location"].endswith("/intake/scan"))

        draft = state.get_draft(brand_id)
        self.assertTrue(draft["scan_done"])
        self.assertEqual(len(draft["scan_impressions"]), len(script.SCAN_IMPRESSIONS))
        # 花費＝真實 token 成本（usage × pricing），即時 SUM llm_task.cost
        expected = pricing.calculate_cost("claude-opus-5", 100, 50)
        self.assertAlmostEqual(draft["cost_spent"], expected, places=9)
        self.assertEqual(draft["cost_items"][0]["label"], "讀取網址與整理初步印象")
        # scan_llm_task_id 回填
        row = ir.get_active_draft(main.conn, brand_id)
        self.assertIsNotNone(row["scan_llm_task_id"])

    def test_missing_key_shows_human_error_not_crash(self):
        brand_id = self._new_wizard_brand()
        intake_ai.PROVIDER = AnthropicProvider()  # 無金鑰：送網路請求之前就會擋下
        resp = self.client.get(f"/brands/{brand_id}/intake/scan/progress?run=1",
                                follow_redirects=False)
        self.assertEqual(resp.status_code, 303)
        self.assertIn("ai_failed=1", resp.headers["location"])
        page = self.client.get(resp.headers["location"])
        self.assertEqual(page.status_code, 200)
        self.assertIn(MISSING_KEY_MESSAGE, page.text)
        self.assertIn("前往設定頁", page.text)
        # 失敗呼叫不計入花費，但留有失敗記錄可看
        draft = state.get_draft(brand_id)
        self.assertEqual(draft["cost_spent"], 0.0)
        self.assertTrue(any(it["failed"] for it in draft["cost_items"]))

    def test_unparseable_reply_is_honest_failure(self):
        brand_id = self._new_wizard_brand()
        intake_ai.PROVIDER = FakeProvider(response=_fake_response("這不是 JSON"))
        resp = self.client.get(f"/brands/{brand_id}/intake/scan/progress?run=1",
                                follow_redirects=False)
        self.assertEqual(resp.status_code, 303)
        self.assertIn("ai_failed=1", resp.headers["location"])
        self.assertFalse(state.get_draft(brand_id)["scan_done"])

    # -- 引導問答 ------------------------------------------------------------

    def test_question_generate_answer_and_done(self):
        brand_id = self._new_wizard_brand()
        self._run_scan(brand_id)

        # 還沒有題目：question 頁導去進度頁；?run=1 讓 AI 出第一題
        resp = self.client.get(f"/brands/{brand_id}/intake/question", follow_redirects=False)
        self.assertEqual(resp.status_code, 303)
        self.assertIn("/question/progress", resp.headers["location"])
        intake_ai.PROVIDER = FakeProvider(response=_fake_response(_question_json(0)))
        self.client.get(f"/brands/{brand_id}/intake/question/progress?run=1",
                         follow_redirects=False)
        page = self.client.get(f"/brands/{brand_id}/intake/question")
        self.assertIn(script.QUESTIONS[0]["question"], page.text)

        # 作答後把回答存進 qa_json；下一輪 AI 說 done -> 沒有需要再問的問題了
        resp = self.client.post(f"/brands/{brand_id}/intake/question",
                                 data={"action": "answer", "choice": "suggested", "note": "補充"},
                                 follow_redirects=False)
        self.assertEqual(resp.status_code, 303)
        draft = state.get_draft(brand_id)
        self.assertEqual(len(draft["answers"]), 1)
        self.assertEqual(draft["answers"][0]["choice_label"], script.QUESTIONS[0]["suggested"]["label"])
        self.assertEqual(draft["answers"][0]["note"], "補充")

        intake_ai.PROVIDER = FakeProvider(response=_fake_response(json.dumps({"done": True})))
        self.client.get(f"/brands/{brand_id}/intake/question/progress?run=1",
                         follow_redirects=False)
        draft = state.get_draft(brand_id)
        self.assertTrue(draft["qa_done"])
        page = self.client.get(f"/brands/{brand_id}/intake/question")
        self.assertIn("沒有需要再問的問題了", page.text)

    # -- W12 超限攔截 ---------------------------------------------------------

    def test_budget_gate_blocks_before_call_and_raise_continues(self):
        brand_id = self._new_wizard_brand()
        draft = state.get_draft(brand_id)
        draft["budget_limit"] = 0.2  # 初掃預估 0.30 > 0.2 -> 呼叫前攔下（預估值已依實測校準）
        state.save(draft)
        intake_ai.PROVIDER = FakeProvider(response=_fake_response("不該被呼叫"))
        resp = self.client.get(f"/brands/{brand_id}/intake/scan/progress?run=1",
                                follow_redirects=False)
        self.assertEqual(resp.status_code, 303)
        self.assertIn("/intake/limit?kind=scan", resp.headers["location"])
        self.assertEqual(intake_ai.PROVIDER.calls, [])  # 真的沒送出呼叫

        page = self.client.get(f"/brands/{brand_id}/intake/limit?kind=scan")
        self.assertEqual(page.status_code, 200)
        resp = self.client.post(f"/brands/{brand_id}/intake/limit/raise",
                                 data={"kind": "scan"}, follow_redirects=False)
        self.assertEqual(resp.status_code, 303)
        self.assertEqual(state.get_draft(brand_id)["budget_limit"], 30.2)

    # -- 貼回、R10、完成 -------------------------------------------------------

    def _to_review(self, brand_id: str):
        self._run_scan(brand_id)
        bi_repo.create_product(main.conn, brand_id, name=script.MOCK_PRODUCT_NAME, actor="測試員")
        resp = self.client.post(f"/brands/{brand_id}/intake/paste",
                                 data={"action": "validate", "raw_text": script.PASTE_SAMPLE_SUCCESS},
                                 follow_redirects=False)
        assert "/intake/review" in resp.headers["location"]

    def test_paste_lands_items_and_r10_and_completion(self):
        brand_id = self._new_wizard_brand()
        self._to_review(brand_id)
        draft = state.get_draft(brand_id)
        items = ir.list_pending_items(main.conn, brand_id, draft["id"])
        self.assertEqual(len(items), 24)
        # raw_row 一字不動保留
        row = main.conn.execute(
            "SELECT raw_row, kind, category FROM intake_item WHERE brand_id = ? AND row_no = 1",
            (brand_id,)).fetchone()
        self.assertEqual(row["raw_row"], script._SUCCESS_ROWS[0])
        self.assertEqual(row["kind"], "brand_fact")
        self.assertEqual(row["category"], "positioning")

        # 決策 0013：宣稱不再強制客戶證實來源——不填一樣可以確認，不擋
        resp = self.client.post(f"/brands/{brand_id}/intake/review/20",
                                 data={"action": "confirm", "title": "幫助代謝",
                                       "content": "商品頁目前有這句話，但查不到具體依據。",
                                       "category": "高風險", "scope": "整個品牌"},
                                 follow_redirects=False)
        self.assertEqual(resp.status_code, 303)
        item_row = main.conn.execute(
            "SELECT * FROM intake_item WHERE brand_id = ? AND row_no = 20", (brand_id,)).fetchone()
        self.assertEqual(item_row["outcome"], "confirmed")
        self.assertEqual(item_row["target_table"], "claim")
        self.assertIsNotNone(item_row["target_id"])
        audit = main.conn.execute(
            "SELECT * FROM audit_log WHERE entity_type = 'intake_item' AND entity_id = ?",
            (item_row["id"],)).fetchone()
        self.assertIsNotNone(audit)

        # 其餘全部捨棄 -> 草稿完成（status=completed），品牌總覽不再顯示進行中
        for it in ir.list_pending_items(main.conn, brand_id, draft["id"]):
            self.client.post(f"/brands/{brand_id}/intake/review/{it['i']}",
                              data={"action": "discard"}, follow_redirects=False)
        self.assertIsNone(state.get_draft(brand_id))
        row = ir.get_draft(main.conn, brand_id, draft["id"])
        self.assertEqual(row["status"], "completed")
        self.assertIsNotNone(row["completed_at"])

    def test_pending_saved_rule_stays_in_intake_item(self):
        brand_id = self._new_wizard_brand()
        self._to_review(brand_id)
        # 第 16 筆是限制規則：先存成待確認 -> 不寫 rule 表，留在 intake_item
        before = len(bi_repo.list_rules_for_brand(main.conn, brand_id))
        resp = self.client.post(f"/brands/{brand_id}/intake/review/16",
                                 data={"action": "pending", "title": "不得使用療效相關字眼",
                                       "content": "文案不得出現療效字樣。",
                                       "category": "禁用字詞", "scope": "整個品牌"},
                                 follow_redirects=False)
        self.assertEqual(resp.status_code, 303)
        self.assertEqual(len(bi_repo.list_rules_for_brand(main.conn, brand_id)), before)
        row = main.conn.execute(
            "SELECT outcome, target_id FROM intake_item WHERE brand_id = ? AND row_no = 16",
            (brand_id,)).fetchone()
        self.assertEqual(row["outcome"], "pending_saved")
        self.assertIsNone(row["target_id"])

    def test_paste_fix_uses_llm_and_can_retry(self):
        brand_id = self._new_wizard_brand()
        self._run_scan(brand_id)
        bi_repo.create_product(main.conn, brand_id, name=script.MOCK_PRODUCT_NAME, actor="測試員")
        self.client.post(f"/brands/{brand_id}/intake/paste",
                          data={"action": "validate", "raw_text": script.PASTE_SAMPLE_ERRORS},
                          follow_redirects=False)
        intake_ai.PROVIDER = FakeProvider(response=_fake_response(script.PASTE_SAMPLE_FIXED))
        resp = self.client.post(f"/brands/{brand_id}/intake/paste",
                                 data={"action": "fix", "raw_text": ""}, follow_redirects=False)
        self.assertIn("/paste/progress", resp.headers["location"])
        resp = self.client.get(f"/brands/{brand_id}/intake/paste/progress?run=1",
                                follow_redirects=False)
        self.assertIn("/intake/review", resp.headers["location"])

        draft = state.get_draft(brand_id)
        self.assertTrue(draft["paste_fix_used"])
        row = ir.get_active_draft(main.conn, brand_id)
        self.assertIsNotNone(row["repair_llm_task_id"])
        # issue #1：不限次數——再按一次照樣進進度頁（每次計費、受 W12 攔截）
        resp = self.client.post(f"/brands/{brand_id}/intake/paste",
                                 data={"action": "fix", "raw_text": ""}, follow_redirects=False)
        self.assertIn("/paste/progress", resp.headers["location"])

    # -- 操作卡實測工具 --------------------------------------------------------

    def test_card_test_without_key_exits_zero_with_human_message(self):
        # 無金鑰：印人話提示、exit code 0、不發任何請求
        with mock.patch("builtins.print") as fake_print:
            code = card_test.main()
        self.assertEqual(code, 0)
        printed = " ".join(str(c) for c in fake_print.call_args_list)
        self.assertIn("金鑰", printed)


class CardV2AndScopeToleranceTest(unittest.TestCase):
    """操作卡 v2（Beast Gummy 事件修正）：目的宣言、法規降級、合法值枚舉、貼回容錯。"""

    # 借用精靈測試的環境隔離與流程 helper，不繼承（避免父類測試重跑一遍）
    setUp = IntakeWizardTest.setUp
    tearDown = IntakeWizardTest.tearDown
    _new_wizard_brand = IntakeWizardTest._new_wizard_brand
    _run_scan = IntakeWizardTest._run_scan

    @staticmethod
    def _paste_text(scope: str) -> str:
        return (
            "種類 | 分類 | 標題 | 內容 | 適用範圍 | 佐證來源\n"
            "品牌事實 | 定位 | 定位一句話 | 中高價位的機能軟糖。 | 整個品牌 | 官網\n"
            f"產品事實 | 核心資訊 | 規格 | 一包十顆、免配水。 | {scope} | 官網"
        )

    def test_card_v2_prompt_contents(self):
        draft = {"brand_name": "測試品牌", "description": "描述", "scan_impressions": [], "answers": []}
        prompt = script.build_prompt(draft, "deep", known_products=["產品A", "產品B"])
        # 目的宣言與風險定位鐵則
        self.assertIn("品牌事實庫", prompt)
        self.assertIn("風險標記的定位", prompt)
        self.assertIn("不得因法規疑慮而否決", prompt)
        # 合法「適用範圍」值直接枚舉
        self.assertIn("「整個品牌」、「產品A」、「產品B」", prompt)
        # 刪掉的章節與嚴苛措辭不得殘留
        self.assertNotIn("品牌現況健檢", prompt)
        self.assertNotIn("宣稱稽核", prompt)
        self.assertNotIn("一律當高風險", prompt)
        # 新競品三軸與法規備忘
        self.assertIn("搶同一個需求", prompt)
        self.assertIn("法規備忘", prompt)
        # v2.1：標點指示、市場數據不入表、複製方式指引
        self.assertIn("正常的標點符號", prompt)
        self.assertIn("不要塞進表", prompt)
        self.assertIn("不要用滑鼠框選", script._CARD_SHARED_STEP_5)
        # 標準版同樣收斂
        std = script.build_prompt(draft, "standard", known_products=[])
        self.assertIn("法規備忘", std)
        self.assertNotIn("有沒有踩到", std)

    def test_paste_scope_written_as_brand_name_maps_to_whole_brand(self):
        brand_id = self._new_wizard_brand()
        self._run_scan(brand_id)
        brand_name = state.get_draft(brand_id)["brand_name"]
        resp = self.client.post(f"/brands/{brand_id}/intake/paste",
                                 data={"action": "validate",
                                       "raw_text": self._paste_text(brand_name)},
                                 follow_redirects=False)
        self.assertIn("/intake/review", resp.headers["location"])
        # 品牌名稱被自動歸成「整個品牌」，兩列都讀進來
        scopes = [r["scope_raw"] for r in main.conn.execute(
            "SELECT scope_raw FROM intake_item WHERE brand_id = ?", (brand_id,)).fetchall()]
        self.assertEqual(scopes, ["整個品牌", "整個品牌"])

    def test_unknown_scope_offers_two_exits_create_product(self):
        brand_id = self._new_wizard_brand()
        self._run_scan(brand_id)
        resp = self.client.post(f"/brands/{brand_id}/intake/paste",
                                 data={"action": "validate",
                                       "raw_text": self._paste_text("神秘軟糖")},
                                 follow_redirects=False)
        self.assertEqual(resp.status_code, 303)
        page = self.client.get(f"/brands/{brand_id}/intake/paste")
        self.assertIn("神秘軟糖", page.text)
        self.assertIn("建立成新產品", page.text)
        self.assertIn("歸到「整個品牌」", page.text)
        # 出口一：建立成新產品 -> 產品真的建立、整批讀進來
        resp = self.client.post(f"/brands/{brand_id}/intake/paste",
                                 data={"action": "resolve_scope", "scope_name": "神秘軟糖",
                                       "resolve_as": "create"},
                                 follow_redirects=False)
        self.assertIn("/intake/review", resp.headers["location"])
        names = {p["name"] for p in bi_repo.list_products(main.conn, brand_id)}
        self.assertIn("神秘軟糖", names)

    def test_unknown_scope_resolve_to_whole_brand(self):
        brand_id = self._new_wizard_brand()
        self._run_scan(brand_id)
        self.client.post(f"/brands/{brand_id}/intake/paste",
                          data={"action": "validate", "raw_text": self._paste_text("神秘軟糖")},
                          follow_redirects=False)
        # 出口二：歸到整個品牌 -> 貼回文字被改寫、讀進來且不建立產品
        resp = self.client.post(f"/brands/{brand_id}/intake/paste",
                                 data={"action": "resolve_scope", "scope_name": "神秘軟糖",
                                       "resolve_as": "brand"},
                                 follow_redirects=False)
        self.assertIn("/intake/review", resp.headers["location"])
        self.assertEqual(bi_repo.list_products(main.conn, brand_id), [])
        draft = state.get_draft(brand_id)
        self.assertNotIn("神秘軟糖", draft["paste_raw"])

    def test_collapsed_single_line_table_is_reflowed(self):
        """換行被剪貼簿吃掉（Beast Gummy 二次實測的根因）：整張表黏成一行也要讀得進來。"""
        brand_id = self._new_wizard_brand()
        self._run_scan(brand_id)
        brand_name = state.get_draft(brand_id)["brand_name"]
        collapsed = self._paste_text(brand_name).replace("\n", " ")
        self.assertNotIn("\n", collapsed)
        resp = self.client.post(f"/brands/{brand_id}/intake/paste",
                                 data={"action": "validate", "raw_text": collapsed},
                                 follow_redirects=False)
        self.assertIn("/intake/review", resp.headers["location"])
        # 存回草稿的是重組後的多行版本（畫面顯示的就是系統讀懂的樣子）
        draft = state.get_draft(brand_id)
        self.assertEqual(len(draft["paste_raw"].splitlines()), 3)

    def test_upload_md_file_instead_of_paste(self):
        brand_id = self._new_wizard_brand()
        self._run_scan(brand_id)
        content = ("# 報告\n\n一些報告文字。\n\n" + self._paste_text("整個品牌")).encode("utf-8")
        resp = self.client.post(
            f"/brands/{brand_id}/intake/paste", data={"action": "validate", "raw_text": ""},
            files={"upload": ("研究.md", io.BytesIO(content), "text/markdown")},
            follow_redirects=False)
        self.assertIn("/intake/review", resp.headers["location"])
        # 不支援的副檔名給人話錯誤
        resp = self.client.post(
            f"/brands/{brand_id}/intake/paste", data={"action": "validate", "raw_text": ""},
            files={"upload": ("研究.pdf", io.BytesIO(b"x"), "application/pdf")},
            follow_redirects=False)
        page = self.client.get(f"/brands/{brand_id}/intake/paste")
        self.assertIn("請上傳 .md 或 .txt 檔", page.text)

    def test_review_edit_lands_edited_values_and_product_scope(self):
        """決策 0013：逐條頁欄位可編輯；產品事實必須掛真產品（不再偷建「整個品牌」假產品）。"""
        brand_id = self._new_wizard_brand()
        self._run_scan(brand_id)
        self.client.post(f"/brands/{brand_id}/intake/paste",
                          data={"action": "validate", "raw_text": self._paste_text("整個品牌")},
                          follow_redirects=False)
        # 第 2 筆是產品事實：scope 留「整個品牌」要被擋（人話錯誤，400）
        resp = self.client.post(f"/brands/{brand_id}/intake/review/2",
                                 data={"action": "confirm", "title": "規格", "content": "十顆",
                                       "category": "核心資訊", "scope": "整個品牌"})
        self.assertEqual(resp.status_code, 400)
        self.assertIn("需要掛在一個產品下", resp.text)
        # 建立新產品出口＋人工修改內容 → 落地的是修改後的值
        resp = self.client.post(f"/brands/{brand_id}/intake/review/2",
                                 data={"action": "confirm", "title": "規格（人工修正）",
                                       "content": "一包十二顆，免配水。", "category": "核心資訊",
                                       "scope": "__new__", "new_product": "虛構軟糖"},
                                 follow_redirects=False)
        self.assertEqual(resp.status_code, 303)
        products = {p["name"]: p["id"] for p in bi_repo.list_products(main.conn, brand_id)}
        self.assertIn("虛構軟糖", products)
        facts = main.conn.execute(
            "SELECT label, value FROM product_fact WHERE brand_id = ? AND product_id = ?",
            (brand_id, products["虛構軟糖"])).fetchall()
        self.assertEqual([(f["label"], f["value"]) for f in facts],
                         [("規格（人工修正）", "一包十二顆，免配水。")])
        # 假產品「整個品牌」絕不存在
        self.assertNotIn("整個品牌", products)

    def test_brand_fact_edit_stays_confirmed_and_delete_works(self):
        """決策 0013：品牌頁人工編輯直接生效；刪除記 audit。"""
        brand_id = self._new_wizard_brand()
        fact = bi_repo.create_brand_fact(
            main.conn, brand_id, actor="測試員", fact_type="positioning",
            label="測試定位", value="原內容", status="confirmed", confirmed_by="測試員")
        resp = self.client.post(f"/brands/{brand_id}/facts/{fact['id']}/edit",
                                 data={"fact_type": "positioning", "label": "測試定位",
                                       "value": "人工改過的內容", "source_reference": ""},
                                 follow_redirects=False)
        self.assertEqual(resp.status_code, 303)
        after = bi_repo.get_brand_fact(main.conn, brand_id, fact["id"])
        self.assertEqual(after["value"], "人工改過的內容")
        self.assertEqual(after["status"], "confirmed")  # 不退回待確認
        resp = self.client.post(f"/brands/{brand_id}/facts/{fact['id']}/delete",
                                 follow_redirects=False)
        self.assertEqual(resp.status_code, 303)
        self.assertIsNone(bi_repo.get_brand_fact(main.conn, brand_id, fact["id"]))
        audit = main.conn.execute(
            "SELECT * FROM audit_log WHERE entity_type = 'brand_fact' AND entity_id = ? "
            "AND action = 'delete'", (fact["id"],)).fetchone()
        self.assertIsNotNone(audit)

    def test_handoff_page_reminds_when_no_products(self):
        brand_id = self._new_wizard_brand()
        self._run_scan(brand_id)
        page = self.client.get(f"/brands/{brand_id}/intake/handoff")
        self.assertIn("還沒建立任何產品", page.text)
        bi_repo.create_product(main.conn, brand_id, name="某產品", actor="測試員")
        page = self.client.get(f"/brands/{brand_id}/intake/handoff")
        self.assertNotIn("還沒建立任何產品", page.text)


class ReintakeLoopTest(unittest.TestCase):
    """issue #1 重新調研迴圈：重跑入口、交接包帶已確認事實、重複提示、批次待確認、規則嚴重度。"""

    setUp = IntakeWizardTest.setUp
    tearDown = IntakeWizardTest.tearDown
    _new_wizard_brand = IntakeWizardTest._new_wizard_brand
    _run_scan = IntakeWizardTest._run_scan

    @staticmethod
    def _table(*rows) -> str:
        return "種類 | 分類 | 標題 | 內容 | 適用範圍 | 佐證來源\n" + "\n".join(rows)

    def _paste(self, brand_id: str, text: str):
        return self.client.post(f"/brands/{brand_id}/intake/paste",
                                 data={"action": "validate", "raw_text": text},
                                 follow_redirects=False)

    def test_restart_creates_new_round_and_prefills(self):
        brand_id = self._new_wizard_brand()
        self._run_scan(brand_id)
        self._paste(brand_id, self._table(
            "品牌事實 | 定位 | 虛構定位 | 一個虛構品牌的定位描述。 | 整個品牌 | 官網"))
        resp = self.client.post(f"/brands/{brand_id}/intake/review/pending-all",
                                 follow_redirects=False)
        self.assertEqual(resp.status_code, 303)
        self.assertIsNone(state.get_draft(brand_id))  # 第一輪完成

        # 重新調研入口：預帶上一輪描述與照片
        page = self.client.get(f"/brands/{brand_id}/intake/restart")
        self.assertEqual(page.status_code, 200)
        self.assertIn("測試品牌的描述文字", page.text)
        self.assertIn("t.jpg", page.text)
        self.assertIn("重新調研", page.text)

        resp = self.client.post(f"/brands/{brand_id}/intake/restart",
                                 data={"description": "第二輪調研的新描述，超過十個字。",
                                       "url_1": "", "url_2": "", "url_3": "", "url_4": "", "url_5": ""},
                                 follow_redirects=False)
        self.assertEqual(resp.status_code, 303)
        self.assertIn("/intake/scan/progress", resp.headers["location"])
        draft = state.get_draft(brand_id)
        self.assertIsNotNone(draft)  # 第二輪草稿
        self.assertEqual(draft["description"], "第二輪調研的新描述，超過十個字。")
        self.assertTrue(any(p["name"] == "t.jpg" for p in draft["photos"]))  # 照片沿用
        # 第一輪草稿保留可查
        completed = main.conn.execute(
            "SELECT COUNT(*) FROM intake_draft WHERE brand_id = ? AND status = 'completed'",
            (brand_id,)).fetchone()[0]
        self.assertEqual(completed, 1)

    def test_restart_redirects_when_round_in_progress(self):
        brand_id = self._new_wizard_brand()  # 進行中草稿
        resp = self.client.get(f"/brands/{brand_id}/intake/restart", follow_redirects=False)
        self.assertEqual(resp.status_code, 303)

    def test_handoff_includes_confirmed_data_block(self):
        brand_id = self._new_wizard_brand()
        bi_repo.create_brand_fact(main.conn, brand_id, actor="測試員", fact_type="positioning",
                                   label="虛構單一產區定位", value="主打虛構產區。",
                                   status="confirmed", confirmed_by="測試員")
        bi_repo.create_rule(main.conn, brand_id, actor="測試員", rule_type="forbidden_words",
                             content="禁用字詞：不得使用療效字樣", severity="hard", product_id=None)
        self._run_scan(brand_id)
        self.client.get(f"/brands/{brand_id}/intake/question/skip")
        resp = self.client.post(f"/brands/{brand_id}/intake/handoff",
                                 data={"depth": "standard"}, follow_redirects=False)
        self.assertEqual(resp.status_code, 303)
        prompt = ir.get_active_draft(main.conn, brand_id)["handoff_prompt"]
        self.assertIn("既成事實，不用重查", prompt)
        self.assertIn("虛構單一產區定位", prompt)
        self.assertIn("禁用字詞", prompt)

    def test_dup_hint_shown_but_not_blocking(self):
        brand_id = self._new_wizard_brand()
        bi_repo.create_brand_fact(main.conn, brand_id, actor="測試員", fact_type="positioning",
                                   label="虛構定位一句話", value="舊的內容。",
                                   status="confirmed", confirmed_by="測試員")
        self._run_scan(brand_id)
        self._paste(brand_id, self._table(
            "品牌事實 | 定位 | 虛構定位一句話 | 新一輪查到的內容。 | 整個品牌 | 官網"))
        page = self.client.get(f"/brands/{brand_id}/intake/review")
        self.assertIn("可能與既有的", page.text)
        item_page = self.client.get(f"/brands/{brand_id}/intake/review/1")
        self.assertIn("不會擋你", item_page.text)
        # 照樣可以確認（不阻擋）
        resp = self.client.post(f"/brands/{brand_id}/intake/review/1",
                                 data={"action": "confirm", "title": "虛構定位一句話",
                                       "content": "新一輪查到的內容。", "category": "定位",
                                       "scope": "整個品牌"}, follow_redirects=False)
        self.assertEqual(resp.status_code, 303)

    def test_pending_all_saves_and_skips_unresolved_product_rows(self):
        brand_id = self._new_wizard_brand()
        self._run_scan(brand_id)
        self._paste(brand_id, self._table(
            "品牌事實 | 定位 | 虛構定位 | 內容一。 | 整個品牌 | 官網",
            "產品事實 | 核心資訊 | 虛構規格 | 內容二。 | 整個品牌 | 官網"))
        before = len(bi_repo.list_brand_facts(main.conn, brand_id, status="pending"))
        resp = self.client.post(f"/brands/{brand_id}/intake/review/pending-all",
                                 follow_redirects=False)
        # 產品事實沒指定產品 -> 留在清單，其他存成待確認
        self.assertIn("/intake/review", resp.headers["location"])
        self.assertEqual(len(bi_repo.list_brand_facts(main.conn, brand_id, status="pending")),
                         before + 1)
        remaining = ir.list_pending_items(main.conn, brand_id, state.get_draft(brand_id)["id"])
        self.assertEqual([it["kind"] for it in remaining], ["產品事實"])
        # 沒有偷建任何產品
        self.assertEqual(bi_repo.list_products(main.conn, brand_id), [])

    def test_scan_detects_products_and_one_click_create(self):
        """決策 0014：初掃偵測產品名單 → 勾選一鍵建立 → 交接包能正確枚舉。"""
        brand_id = self._new_wizard_brand()
        intake_ai.PROVIDER = FakeProvider(response=_fake_response(json.dumps(
            {"impressions": script.SCAN_IMPRESSIONS,
             "products": ["虛構軟糖A", "虛構錠B", ""]}, ensure_ascii=False)))
        self.client.get(f"/brands/{brand_id}/intake/scan/progress?run=1", follow_redirects=False)
        draft = state.get_draft(brand_id)
        self.assertEqual(draft["scan_products"], ["虛構軟糖A", "虛構錠B"])

        page = self.client.get(f"/brands/{brand_id}/intake/scan")
        self.assertIn("我在資料裡看到這些產品", page.text)
        self.assertIn("虛構軟糖A", page.text)

        resp = self.client.post(f"/brands/{brand_id}/intake/scan/products",
                                 data={"product_names": ["虛構軟糖A", "沒在名單裡的名字"]},
                                 follow_redirects=False)
        self.assertEqual(resp.status_code, 303)
        names = {p["name"] for p in bi_repo.list_products(main.conn, brand_id)}
        self.assertEqual(names, {"虛構軟糖A"})  # 名單外的名字不建（防表單注入）

        # 交接包枚舉建立好的產品
        self.client.get(f"/brands/{brand_id}/intake/question/skip")
        self.client.post(f"/brands/{brand_id}/intake/handoff", data={"depth": "standard"},
                          follow_redirects=False)
        prompt = ir.get_active_draft(main.conn, brand_id)["handoff_prompt"]
        self.assertIn("「整個品牌」、「虛構軟糖A」", prompt)
        # v2.2 通用收錄規則
        self.assertIn("現況快照", prompt)
        self.assertIn("自家產品的事實", prompt)
        self.assertIn("宣稱語句本身", prompt)

    def test_rule_severity_choice_lands_as_hard(self):
        brand_id = self._new_wizard_brand()
        self._run_scan(brand_id)
        self._paste(brand_id, self._table(
            "限制規則 | 禁用字詞 | 虛構禁語 | 不得使用某些字樣。 | 整個品牌 | 官網"))
        resp = self.client.post(f"/brands/{brand_id}/intake/review/1",
                                 data={"action": "confirm", "title": "虛構禁語",
                                       "content": "不得使用某些字樣。", "category": "禁用字詞",
                                       "scope": "整個品牌", "severity": "hard"},
                                 follow_redirects=False)
        self.assertEqual(resp.status_code, 303)
        rules = bi_repo.list_rules_for_brand(main.conn, brand_id)
        self.assertEqual([r["severity"] for r in rules], ["hard"])


if __name__ == "__main__":
    unittest.main()
