# -*- coding: utf-8 -*-
"""app/tests/test_ads_reading_hypotheses.py — 票 10-split-reading-py：假設結案週邊測試。

從 app/tests/test_ads_reading.py 搬過來，原樣不改——鏡射 app/ads/reading_hypotheses.py
的拆檔（見該檔開頭說明：`resolve_hypotheses`／`_ledger_confidence` 本身留在 reading.py，
但這裡的測試照樣經 `reading.resolve_hypotheses(...)` 呼叫，搬檔不影響呼叫端）。
"""

import atexit
import json
import shutil
import tempfile
import unittest

_tmpdir = tempfile.mkdtemp(prefix="brand_os_ads_reading_hypotheses_")

from fastapi.testclient import TestClient  # noqa: E402

import app.main as main  # noqa: E402
from app.ads import performance as perf  # noqa: E402
from app.ads import reading  # noqa: E402
from app.ads import repository as ads_repo  # noqa: E402
from app.brand_intelligence import repository as bi_repo  # noqa: E402
from app.core import interrupts as core_interrupts  # noqa: E402
from app.llm import context_compiler  # noqa: E402
from app.llm.providers import FakeProvider, ProviderError, ProviderResponse, Usage  # noqa: E402
from app.shared.web import OPERATOR  # noqa: E402


def _cleanup():
    try:
        main.conn.close()
    except Exception:
        pass
    shutil.rmtree(_tmpdir, ignore_errors=True)


atexit.register(_cleanup)

ACTOR = "測試員"


def _fake(text):
    return ProviderResponse(output_text=text, structured=None,
                            usage=Usage(input_tokens=300, output_tokens=150),
                            stop_reason="end_turn")


class _HypothesisReviewBase(unittest.TestCase):
    """票 #53 判讀頁假設結案共用的建置。"""

    def setUp(self):
        self.client = TestClient(main.app)
        self.brand = bi_repo.create_brand(main.conn, name="虛構晨露茶行",
                                          client_name=None, actor=ACTOR)
        self.bid = self.brand["id"]
        self.product = bi_repo.create_product(main.conn, self.bid, name="虛構烏龍茶包",
                                              actor=ACTOR)["id"]
        bi_repo.save_product_economics(main.conn, self.bid, self.product, selling_price=1000,
                                       unit_variable_cost=400, currency="TWD",
                                       confirmed_by=ACTOR, actor=ACTOR)
        resp = self.client.post(f"/api/campaigns/{self.bid}",
                                json={"product_ids": [self.product], "budget": 10000,
                                      "objective": "sales"})
        self.cycle_id = resp.json()["cycle_id"]
        self._orig = reading.PROVIDER
        reading.PROVIDER = FakeProvider(response=_fake(
            json.dumps({"reasons": {}}, ensure_ascii=False)))

    def tearDown(self):
        reading.PROVIDER = self._orig

    def _link_hypothesis(self, statement, hypothesis_type="audience", product_id=None):
        hyp = bi_repo.create_strategy_hypothesis(
            main.conn, self.bid, hypothesis_type=hypothesis_type, statement=statement,
            created_by=ACTOR, actor=ACTOR, product_id=product_id, source_cycle_id=self.cycle_id)
        main.conn.execute(
            "INSERT OR IGNORE INTO campaign_cycle_hypothesis (campaign_cycle_id,"
            " strategy_hypothesis_id, brand_id, role) VALUES (?, ?, ?, ?)",
            (self.cycle_id, hyp["id"], self.bid, hypothesis_type),
        )
        main.conn.commit()
        return hyp

    def _spend(self, **values):
        perf.import_manual(main.conn, self.bid, self.cycle_id, values, actor=ACTOR)


class HypothesisReviewTest(_HypothesisReviewBase):
    """票 #53：判讀頁假設結案（三選一，AI 預選）＋入帳 learning_ledger＋打斷佇列補網。"""

    def test_ai_preselects_supported_when_scale_candidate(self):
        """判讀結論偏正向 → 三選一預選「成立」，AI 只負責寫理由，不決定選哪個（決策 0016）。"""
        hyp = self._link_hypothesis("通勤族比在家工作者更會下單")
        self._spend(spend=10000, impressions=20000, clicks=400, conversions=10, revenue=40000)
        ok, err = reading.run(main.conn, self.bid, self.cycle_id, ACTOR)
        self.assertTrue(ok, err)
        reviews = reading.load(main.conn, self.bid, self.cycle_id)["cycle"]["hypothesis_reviews"]
        self.assertEqual(len(reviews), 1)
        self.assertEqual(reviews[0]["id"], hyp["id"])
        self.assertEqual(reviews[0]["preselect"], "supported")
        self.assertTrue(reviews[0]["ai_reason"])

    def test_ai_preselects_rejected_when_pause_candidate(self):
        self._link_hypothesis("這群受眾在意價格")
        self._spend(spend=10000, impressions=20000, clicks=400, conversions=0, revenue=0)
        reading.run(main.conn, self.bid, self.cycle_id, ACTOR)
        reviews = reading.load(main.conn, self.bid, self.cycle_id)["cycle"]["hypothesis_reviews"]
        self.assertEqual(reviews[0]["preselect"], "rejected")

    def test_ai_preselects_inconclusive_when_maintain(self):
        """修憲落地 G4（決策 0035 第三節第 6 點）：`maintain`（只是打平）不算「程式算出
        方向」，預選改看不出來，不是成立——橡皮圖章的產物不該被貼上「已驗證」標籤。"""
        self._link_hypothesis("通勤族比在家工作者更會下單")
        # 這個品牌的產品毛利率固定（售價1000／變動成本400 → 打平線約1.667），
        # ROAS=1.8 落在 [打平線, 打平線*1.3) → maintain。
        self._spend(spend=10000, impressions=20000, clicks=400, conversions=10, revenue=18000)
        reading.run(main.conn, self.bid, self.cycle_id, ACTOR)
        reviews = reading.load(main.conn, self.bid, self.cycle_id)["cycle"]["hypothesis_reviews"]
        self.assertEqual(reviews[0]["preselect"], "inconclusive")

    def test_llm_failure_falls_back_to_program_generated_reason(self):
        """AI 講不出話不擋清單顯示——理由退回程式產生的版本，選項本身不受影響。"""
        self._link_hypothesis("通勤族比在家工作者更會下單")
        reading.PROVIDER = FakeProvider(exception=ProviderError("暫時無法回應"))
        self._spend(spend=10000, impressions=20000, clicks=400, conversions=10, revenue=40000)
        reading.run(main.conn, self.bid, self.cycle_id, ACTOR)
        review = reading.load(main.conn, self.bid, self.cycle_id)["cycle"]["hypothesis_reviews"][0]
        self.assertIn("這期判讀結論是", review["ai_reason"])

    def test_zero_operation_submit_uses_ai_preselect(self):
        """使用者零操作也能過：直接照 AI 預選送出，status 隨之更新。"""
        hyp = self._link_hypothesis("通勤族比在家工作者更會下單")
        self._spend(spend=10000, impressions=20000, clicks=400, conversions=10, revenue=40000)
        reading.run(main.conn, self.bid, self.cycle_id, ACTOR)
        preselect = reading.load(main.conn, self.bid,
                                 self.cycle_id)["cycle"]["hypothesis_reviews"][0]["preselect"]
        updated_count = reading.resolve_hypotheses(
            main.conn, self.bid, self.cycle_id, {hyp["id"]: preselect}, actor=OPERATOR)
        self.assertEqual(updated_count, 1)
        updated = bi_repo.get_strategy_hypothesis(main.conn, self.bid, hyp["id"])
        self.assertEqual(updated["status"], preselect)

    def test_supported_confirmation_writes_learning_ledger(self):
        hyp = self._link_hypothesis("通勤族比在家工作者更會下單")
        self._spend(spend=10000, impressions=20000, clicks=400, conversions=10, revenue=40000)
        reading.run(main.conn, self.bid, self.cycle_id, ACTOR)
        reading.resolve_hypotheses(
            main.conn, self.bid, self.cycle_id, {hyp["id"]: "supported"}, actor=OPERATOR)
        rows = [dict(r) for r in main.conn.execute(
            "SELECT * FROM learning_ledger WHERE brand_id = ?", (self.bid,))]
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["learning_text"], "通勤族比在家工作者更會下單")
        self.assertEqual(rows[0]["source_cycle_id"], self.cycle_id)
        self.assertEqual(rows[0]["source_hypothesis_id"], hyp["id"])
        self.assertEqual(rows[0]["created_by"], OPERATOR)
        self.assertEqual(rows[0]["sample_size"], "10")
        self.assertIsNotNone(rows[0]["confidence"])
        self.assertIsNotNone(rows[0]["source_reading_id"])

    def test_ledger_confidence_is_its_own_scale_not_the_data_grade_label(self):
        """修憲落地 G4（決策 0035 第三節第 8 點）：ledger 的 confidence 是「樣本數＋是否
        重測過」自己一套，不是資料成色標籤（那個標籤講的是資料有沒有對過帳，不是這條
        學習可不可信）——這裡的品牌沒有接 GA4／Meta 對帳，成色標籤會是「Meta 視角判讀」，
        跟 confidence 欄位的值必須不同。"""
        hyp = self._link_hypothesis("通勤族比在家工作者更會下單")
        self._spend(spend=10000, impressions=20000, clicks=400, conversions=10, revenue=40000)
        reading.run(main.conn, self.bid, self.cycle_id, ACTOR)
        reading.resolve_hypotheses(
            main.conn, self.bid, self.cycle_id, {hyp["id"]: "supported"}, actor=OPERATOR)
        row = main.conn.execute(
            "SELECT confidence FROM learning_ledger WHERE brand_id = ?", (self.bid,)).fetchone()
        self.assertNotEqual(row["confidence"], "Meta 視角判讀")
        self.assertEqual(row["confidence"], "moderate")

    def test_small_sample_manual_override_gets_preliminary_confidence(self):
        """使用者手動把還在學習期的假設硬結案「成立」，系統不擋（決策 0013）；
        樣本只有 5 筆、不是重測，confidence 該誠實標「初步」。"""
        hyp = self._link_hypothesis("通勤族比在家工作者更會下單")
        self._spend(spend=10000, impressions=20000, clicks=400, conversions=5, revenue=9000)
        reading.run(main.conn, self.bid, self.cycle_id, ACTOR)
        reading.resolve_hypotheses(
            main.conn, self.bid, self.cycle_id, {hyp["id"]: "supported"}, actor=OPERATOR)
        row = main.conn.execute(
            "SELECT confidence FROM learning_ledger WHERE brand_id = ?", (self.bid,)).fetchone()
        self.assertEqual(row["confidence"], "preliminary")

    def test_repeated_learning_text_gets_reinforced_confidence(self):
        """同一個品牌、同一個範圍、同一句學習文字，不同期別各自被判定「成立」——不是同一次
        判讀的巧合，是獨立重測，第二次入帳的 confidence 要標「已加強」。"""
        statement = "通勤族比在家工作者更會下單"
        hyp1 = self._link_hypothesis(statement)
        self._spend(spend=10000, impressions=20000, clicks=400, conversions=10, revenue=40000)
        reading.run(main.conn, self.bid, self.cycle_id, ACTOR)
        reading.resolve_hypotheses(
            main.conn, self.bid, self.cycle_id, {hyp1["id"]: "supported"}, actor=OPERATOR)

        cycle2_id = ads_repo.create_cycle(
            main.conn, self.bid, product_ids=[self.product], pain_value=10000,
            objective="sales", actor=ACTOR)["id"]
        hyp2 = bi_repo.create_strategy_hypothesis(
            main.conn, self.bid, hypothesis_type="audience", statement=statement,
            created_by=ACTOR, actor=ACTOR, product_id=None, source_cycle_id=cycle2_id)
        main.conn.execute(
            "INSERT OR IGNORE INTO campaign_cycle_hypothesis (campaign_cycle_id,"
            " strategy_hypothesis_id, brand_id, role) VALUES (?, ?, ?, 'audience')",
            (cycle2_id, hyp2["id"], self.bid))
        main.conn.commit()
        perf.import_manual(main.conn, self.bid, cycle2_id,
                           {"spend": 10000, "impressions": 20000, "clicks": 400,
                            "conversions": 10, "revenue": 40000}, actor=ACTOR)
        reading.run(main.conn, self.bid, cycle2_id, ACTOR)
        reading.resolve_hypotheses(
            main.conn, self.bid, cycle2_id, {hyp2["id"]: "supported"}, actor=OPERATOR)

        rows = [dict(r) for r in main.conn.execute(
            "SELECT * FROM learning_ledger WHERE brand_id = ? ORDER BY created_at", (self.bid,))]
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["confidence"], "moderate")
        self.assertEqual(rows[1]["confidence"], "reinforced")

    def _later_cycle(self):
        """比照 DualBaselineTest 直接用 repository 開一期，只用來造「後面又開過幾期」的
        時間序（`mark_stale_learnings_for_revalidation` 依 `campaign_cycle.created_at`
        排序，不必真的填成效資料）。"""
        return ads_repo.create_cycle(
            main.conn, self.bid, product_ids=[self.product], pain_value=10000,
            objective="sales", actor=ACTOR)["id"]

    def test_ledger_entry_flagged_for_revalidation_after_window_of_later_cycles(self):
        """修憲落地 G4（決策 0035 第三節第 5 點）：`needs_revalidation` 欄位在表上但全庫
        沒有任何一行寫入過。「第 N 期再驗一次」＝這個品牌又開過幾期（依建立順序），
        超過門檻期數還沒被下架，就標記需要複查——只提醒，不擋路、不自動下架。"""
        hyp = self._link_hypothesis("通勤族比在家工作者更會下單")
        self._spend(spend=10000, impressions=20000, clicks=400, conversions=10, revenue=40000)
        reading.run(main.conn, self.bid, self.cycle_id, ACTOR)
        reading.resolve_hypotheses(
            main.conn, self.bid, self.cycle_id, {hyp["id"]: "supported"}, actor=OPERATOR)
        entry_id = main.conn.execute(
            "SELECT id FROM learning_ledger WHERE brand_id = ?", (self.bid,)).fetchone()["id"]

        for _ in range(reading.LEDGER_REVALIDATION_WINDOW_CYCLES - 1):
            self._later_cycle()
        reading.mark_stale_learnings_for_revalidation(main.conn, self.bid)
        row = main.conn.execute(
            "SELECT needs_revalidation FROM learning_ledger WHERE id = ?", (entry_id,)).fetchone()
        self.assertEqual(row["needs_revalidation"], 0, "還沒滿門檻期數，不該標記")

        self._later_cycle()
        reading.mark_stale_learnings_for_revalidation(main.conn, self.bid)
        row = main.conn.execute(
            "SELECT needs_revalidation FROM learning_ledger WHERE id = ?", (entry_id,)).fetchone()
        self.assertEqual(row["needs_revalidation"], 1)

    def test_revalidation_check_is_wired_into_next_cycle_build(self):
        """驗證真的掛進判讀後的下期準備流程（nextcycle.build()），不是孤兒函式沒人呼叫。"""
        hyp = self._link_hypothesis("通勤族比在家工作者更會下單")
        self._spend(spend=10000, impressions=20000, clicks=400, conversions=10, revenue=40000)
        reading.run(main.conn, self.bid, self.cycle_id, ACTOR)
        reading.resolve_hypotheses(
            main.conn, self.bid, self.cycle_id, {hyp["id"]: "supported"}, actor=OPERATOR)

        for _ in range(reading.LEDGER_REVALIDATION_WINDOW_CYCLES):
            self._later_cycle()

        reading.run(main.conn, self.bid, self.cycle_id, ACTOR)  # 重判同一期，順手觸發 nextcycle.build()
        row = main.conn.execute(
            "SELECT needs_revalidation FROM learning_ledger WHERE brand_id = ?",
            (self.bid,)).fetchone()
        self.assertEqual(row["needs_revalidation"], 1)

    def test_learning_flows_into_next_cycle_prompt_via_context_compiler(self):
        """端到端實測（GitHub issue #54 驗收條件）：建虛構品牌 → 開期產假設 → 判讀 → 結案入帳
        → 下一期生成的 prompt（context_compiler.compile）內確實出現該學習。"""
        hyp = self._link_hypothesis("通勤族比在家工作者更會下單")
        self._spend(spend=10000, impressions=20000, clicks=400, conversions=10, revenue=40000)
        reading.run(main.conn, self.bid, self.cycle_id, ACTOR)
        reading.resolve_hypotheses(
            main.conn, self.bid, self.cycle_id, {hyp["id"]: "supported"}, actor=OPERATOR)

        # 模擬下一期生成計畫時 plan.py／creative.py 呼叫 compile() 的方式（brand-level）
        text, knowledge_item_ids, _brand_version, _product_version = context_compiler.compile(
            main.conn, self.bid)

        self.assertIn("【已驗證的學習】", text)
        self.assertIn("通勤族比在家工作者更會下單", text)
        self.assertIn(f"來源期別 {self.cycle_id}", text)
        learning_row = main.conn.execute(
            "SELECT id FROM learning_ledger WHERE brand_id = ?", (self.bid,)).fetchone()
        self.assertIn(learning_row["id"], knowledge_item_ids)

    def test_rejected_confirmation_does_not_write_ledger(self):
        hyp = self._link_hypothesis("通勤族比在家工作者更會下單")
        self._spend(spend=10000, impressions=20000, clicks=400, conversions=0, revenue=0)
        reading.run(main.conn, self.bid, self.cycle_id, ACTOR)
        reading.resolve_hypotheses(
            main.conn, self.bid, self.cycle_id, {hyp["id"]: "rejected"}, actor=OPERATOR)
        rows = main.conn.execute(
            "SELECT COUNT(*) c FROM learning_ledger WHERE brand_id = ?", (self.bid,)).fetchone()
        self.assertEqual(rows["c"], 0)
        updated = bi_repo.get_strategy_hypothesis(main.conn, self.bid, hyp["id"])
        self.assertEqual(updated["status"], "rejected")

    def test_resolved_hypothesis_disappears_from_page_after_confirm(self):
        hyp = self._link_hypothesis("通勤族比在家工作者更會下單")
        self._spend(spend=10000, impressions=20000, clicks=400, conversions=10, revenue=40000)
        reading.run(main.conn, self.bid, self.cycle_id, ACTOR)
        reading.resolve_hypotheses(
            main.conn, self.bid, self.cycle_id, {hyp["id"]: "supported"}, actor=OPERATOR)
        reviews = reading.load(main.conn, self.bid, self.cycle_id)["cycle"]["hypothesis_reviews"]
        self.assertEqual(reviews, [])

    def test_unresolved_hypothesis_flagged_at_finalize(self):
        self._link_hypothesis("通勤族比在家工作者更會下單")
        self._spend(spend=10000, impressions=20000, clicks=400, conversions=10, revenue=40000)
        reading.finalize(main.conn, self.bid, self.cycle_id, ACTOR)
        open_items = core_interrupts.list_open(main.conn, brand_id=self.bid)
        self.assertTrue(any(i["category"] == "hypothesis_unresolved" for i in open_items))

    def test_resolved_before_finalize_does_not_flag(self):
        hyp = self._link_hypothesis("通勤族比在家工作者更會下單")
        self._spend(spend=10000, impressions=20000, clicks=400, conversions=10, revenue=40000)
        reading.run(main.conn, self.bid, self.cycle_id, ACTOR)
        reading.resolve_hypotheses(
            main.conn, self.bid, self.cycle_id, {hyp["id"]: "supported"}, actor=OPERATOR)
        reading.finalize(main.conn, self.bid, self.cycle_id, ACTOR)
        open_items = core_interrupts.list_open(main.conn, brand_id=self.bid)
        self.assertFalse(any(i["category"] == "hypothesis_unresolved" for i in open_items))

    def test_ignores_unknown_hypothesis_id_and_invalid_verdict_value(self):
        """防偽造 id、防非法 verdict 值：忽略不處理，不拋例外。"""
        hyp = self._link_hypothesis("通勤族比在家工作者更會下單")
        self._spend(spend=10000, impressions=20000, clicks=400, conversions=10, revenue=40000)
        reading.run(main.conn, self.bid, self.cycle_id, ACTOR)
        updated = reading.resolve_hypotheses(
            main.conn, self.bid, self.cycle_id,
            {"hyp_not_real": "supported", hyp["id"]: "not_a_real_verdict"}, actor=ACTOR)
        self.assertEqual(updated, 0)


class HypothesisLedgerHaltTest(_HypothesisReviewBase):
    """修憲落地 G4（決策 0035 第三節第 6 點）：假設結案入帳原本是確認偏誤幫浦——AI 預選加
    一路下一步等於橡皮圖章，只有「成立」單向累積、產物貼「已驗證的學習」標籤永久寫進
    prompt。統計缺陷（橡皮圖章式的預選、`maintain` 誤算正面、小樣本喊加碼停損）修好後，
    選「成立」照樣入帳，這裡驗證使用者實際會遇到的預設狀態。"""

    def test_supported_confirmation_writes_ledger_even_though_the_flag_is_on(self):
        hyp = self._link_hypothesis("通勤族比在家工作者更會下單")
        self._spend(spend=10000, impressions=20000, clicks=400, conversions=10, revenue=40000)
        reading.run(main.conn, self.bid, self.cycle_id, ACTOR)
        reading.resolve_hypotheses(
            main.conn, self.bid, self.cycle_id, {hyp["id"]: "supported"}, actor=OPERATOR)
        rows = main.conn.execute(
            "SELECT COUNT(*) c FROM learning_ledger WHERE brand_id = ?", (self.bid,)).fetchone()
        self.assertEqual(rows["c"], 1)
        updated = bi_repo.get_strategy_hypothesis(main.conn, self.bid, hyp["id"])
        self.assertEqual(updated["status"], "supported")


if __name__ == "__main__":
    unittest.main()
