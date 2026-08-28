"""app/tests/test_intake.py — 建檔精靈接真：草稿持久化、LLM 串接、花費、R10 出口。

見 docs/design/07-settings-and-intake-contract.md §4、docs/design/03-data-model.md §3A。
全程用 FakeProvider（跟 test_llm_gateway 同風格），不發任何真實網路請求；
「無金鑰人話錯誤」那條用真的 AnthropicProvider——它在打出網路請求之前就會擋下。
"""

import io
import json
import os
import time
import unittest
from unittest import mock

from fastapi.testclient import TestClient

import app.main as main
import app.shared.web as web
from app.core import db as coredb
from app.intake import ai as intake_ai
from app.intake import card_test, script, state
from app.intake import repository as ir
from app.llm import pricing
from app.llm.providers import (
    FakeProvider,
    ProviderResponse,
    Usage,
)

_BRAND_SEQ = [0]


def _fake_response(text: str, in_tok: int = 100, out_tok: int = 50) -> ProviderResponse:
    return ProviderResponse(output_text=text, structured=None,
                            usage=Usage(input_tokens=in_tok, output_tokens=out_tok),
                            stop_reason="end_turn")


def _question_json(i: int = 0, aspect: str = "產品線") -> str:
    q = script.QUESTIONS[i]
    return json.dumps({"done": False, "aspect": aspect, "question": q["question"],
                       "suggested": {"label": q["suggested"]["label"], "desc": q["suggested"]["desc"]},
                       "branches": [{"label": b["label"], "desc": b["desc"]} for b in q["branches"]]},
                      ensure_ascii=False)


class IntakeWizardTest(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(main.app)
        web.conn.execute("DELETE FROM app_setting")
        web.conn.commit()
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
        photo = self.client.post(
            "/api/intake/photos", files={"photo": ("t.jpg", io.BytesIO(b"x" * 100), "image/jpeg")})
        assert photo.status_code == 200
        resp = self.client.post("/api/intake/brands", data={
            "brand_name": name, "description": "測試品牌的描述文字，超過十個字。",
            "photo_tokens": photo.json()["token"],
        })
        assert resp.status_code == 200
        return resp.json()["brand_id"]

    def _run_scan(self, brand_id: str, in_tok: int = 100, out_tok: int = 50):
        intake_ai.PROVIDER = FakeProvider(response=_fake_response(
            json.dumps({"impressions": script.SCAN_IMPRESSIONS}, ensure_ascii=False),
            in_tok=in_tok, out_tok=out_tok))
        resp = self.client.post(f"/api/intake/brands/{brand_id}/scan/start")
        assert resp.status_code == 200
        for _ in range(100):
            status = self.client.get(f"/api/intake/brands/{brand_id}/scan/status")
            if status.json()["data"]["status"] != "running":
                return status
            time.sleep(0.05)
        self.fail("初掃背景任務逾時")

    # -- 草稿持久化 ----------------------------------------------------------

    def test_draft_persisted_and_survives_restart(self):
        brand_id = self._new_wizard_brand()
        row = ir.get_active_draft(web.conn, brand_id)
        self.assertIsNotNone(row)
        self.assertEqual(row["status"], "draft")
        self.assertEqual(row["cost_limit"], script.DEFAULT_BUDGET)

        # 等同重啟伺服器：跟連線池借一條全新連線讀回，證明草稿是真的落了 DB，
        # 不是只活在某一條連線的交易裡（ADR 0027：沒有「reopen」這回事，每個
        # request／背景工作各自跟池子借一條，見 app/core/db.py connection()）。
        with coredb.connection() as fresh:
            draft = state.get_draft(brand_id, conn=fresh)
        self.assertIsNotNone(draft)
        self.assertEqual(draft["step"], 2)
        self.assertEqual(draft["resume_path"], f"/app/brands/{brand_id}/intake")

    def test_budget_limit_default_reads_setting(self):
        from app.core import settings as coresettings
        coresettings.set_setting(web.conn, "intake_budget_limit", "55", org_id=coredb.DEV_ORG_ID)
        brand_id = self._new_wizard_brand()
        self.assertEqual(ir.get_active_draft(web.conn, brand_id)["cost_limit"], 55.0)

    # -- 初掃 ----------------------------------------------------------------

    def test_scan_success_stores_impressions_and_real_cost(self):
        brand_id = self._new_wizard_brand()
        # in_tok/out_tok 選會湊出整數分的數字（llm_task.cost 是 numeric(14,2)，02-2
        # 決策：金額欄一律存到分——100/50 token 算出來的 $0.0035 連一分錢都不到，存進去
        # 四捨五入變 $0，不是這條測試想驗的東西，02-3c 前就一直是這個舊 SQLite 殘留數字）。
        resp = self._run_scan(brand_id, in_tok=1_000_000, out_tok=1_000_000)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["data"]["status"], "done")

        draft = state.get_draft(brand_id)
        self.assertTrue(draft["scan_done"])
        self.assertEqual(len(draft["scan_impressions"]), len(script.SCAN_IMPRESSIONS))
        # 花費＝真實 token 成本（usage × pricing），即時 SUM llm_task.cost
        # T2：同一批背景流程會再讀一張上傳照片，因此網址掃描＋照片各記一筆成本。
        expected = pricing.calculate_cost("claude-opus-5", 1_000_000, 1_000_000) * 2
        self.assertAlmostEqual(draft["cost_spent"], expected, places=2)
        # COPY trim：兩筆成本項目各自的中文文案不測，測「確實各記一筆」這件事
        self.assertEqual(len(draft["cost_items"]), 2)
        # scan_llm_task_id 回填
        row = ir.get_active_draft(web.conn, brand_id)
        self.assertIsNotNone(row["scan_llm_task_id"])



    # -- 引導問答 ------------------------------------------------------------


    # -- W12 超限攔截 ---------------------------------------------------------


    # -- 貼回、R10、完成 -------------------------------------------------------


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










class ReintakeLoopTest(unittest.TestCase):
    """issue #1 重新調研迴圈：重跑入口、交接包帶已確認事實、重複提示、批次待確認、規則嚴重度。"""

    setUp = IntakeWizardTest.setUp
    tearDown = IntakeWizardTest.tearDown
    _new_wizard_brand = IntakeWizardTest._new_wizard_brand
    _run_scan = IntakeWizardTest._run_scan

    @staticmethod
    def _table(*rows) -> str:
        return "種類 | 分類 | 標題 | 內容 | 適用範圍 | 佐證來源\n" + "\n".join(rows)








if __name__ == "__main__":
    unittest.main()
