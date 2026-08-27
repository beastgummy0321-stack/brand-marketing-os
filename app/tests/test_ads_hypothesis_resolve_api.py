# -*- coding: utf-8 -*-
"""app/tests/test_ads_hypothesis_resolve_api.py — 票 L1-01：覆盤頁假設結案 API。

`POST .../hypotheses/resolve` 這條路由本身只做一件事：把請求接進
`ads_reading.resolve_hypotheses()`（唯讀檔，業務邏輯全在那裡，不得改）。這裡驗證的是接線
本身，以及 `closing-review` GET 新增的 `pending`／`preselected` 兩個欄位讀得到既有的
預選裁決——不重算任何判讀邏輯（決策 0035 第三節第 6 點：入帳前必須經人確認）。
"""

import json
import unittest

import pytest
from fastapi.testclient import TestClient

import app.main as main
from app.ads import performance as perf
from app.ads import reading
from app.brand_intelligence import repository as bi_repo
from app.core import db
from app.llm.providers import FakeProvider, ProviderResponse, Usage

ACTOR = "測試員"


def _fake(text):
    return ProviderResponse(output_text=text, structured=None,
                            usage=Usage(input_tokens=300, output_tokens=150),
                            stop_reason="end_turn")




class HypothesisResolveApiTest(unittest.TestCase):
    """票 L1-01：POST 結案接線＋GET closing-review 加欄位。"""

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

    def _link_hypothesis(self, statement):
        hyp = bi_repo.create_strategy_hypothesis(
            main.conn, self.bid, hypothesis_type="audience", statement=statement,
            created_by=ACTOR, actor=ACTOR, product_id=self.product, source_cycle_id=self.cycle_id)
        main.conn.execute(
            "INSERT INTO campaign_cycle_hypothesis (org_id, campaign_cycle_id,"
            " strategy_hypothesis_id, brand_id, role) VALUES (%s, %s, %s, %s, %s)"
            " ON CONFLICT (campaign_cycle_id, strategy_hypothesis_id) DO NOTHING",
            (db.DEV_ORG_ID, self.cycle_id, hyp["id"], self.bid, "audience"),
        )
        main.conn.commit()
        return hyp

    def _spend(self, **values):
        perf.import_manual(main.conn, self.bid, self.cycle_id, values, actor=ACTOR)

    def _ab_spend(self, *, spend, conversions, revenue, impressions=20000, clicks=400):
        """R2-learning-honesty：兩個真的投放過、掛在 `self.product` 底下的切角，比照
        `test_ads_reading_hypotheses.py::_HypothesisReviewBase._ab_spend` 同一套寫法
        （這裡的假設是 product-scoped，package 額外標 product_id 才對得回
        `comparison_cells(product_id=self.product)` 的篩選）。"""
        ad_names, angles, ts = ("角度A_ad", "角度B_ad"), ("情感痛點開場", "功能宣稱開場"), db.now_utc()
        for name, angle in zip(ad_names, angles):
            cell_id, pkg_id = db.new_id("exc"), db.new_id("pkg")
            main.conn.execute(
                "INSERT INTO experiment_cell (id, org_id, campaign_cycle_id, brand_id,"
                " creative_angle, product_id, created_at) VALUES (%s, %s, %s, %s, %s, %s, %s)",
                (cell_id, db.DEV_ORG_ID, self.cycle_id, self.bid, angle, self.product, ts))
            main.conn.execute(
                "INSERT INTO publishing_package (id, org_id, brand_id, campaign_cycle_id,"
                " experiment_cell_id, product_id, campaign_name, adset_name, ad_name,"
                " destination_url, utm_json, status, created_at)"
                " VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, '{}', 'ready', %s)",
                (pkg_id, db.DEV_ORG_ID, self.bid, self.cycle_id, cell_id, self.product,
                 "測試活動", "測試組合", name, "https://example.test", ts))
            main.conn.execute(
                "INSERT INTO external_ad_mapping (id, org_id, brand_id, publishing_package_id,"
                " campaign_cycle_id, platform, claim_status, confirmed_by, confirmed_at,"
                " created_at) VALUES (%s, %s, %s, %s, %s, 'meta', 'confirmed', %s, %s, %s)",
                (db.new_id("xam"), db.DEV_ORG_ID, self.bid, pkg_id, self.cycle_id, ACTOR, ts, ts))
        main.conn.commit()

        def _half(total):
            h = total // 2
            return total - h, h
        (spend_a, spend_b), (conv_a, conv_b) = _half(spend), _half(conversions)
        (rev_a, rev_b), (imp_a, imp_b) = _half(revenue), _half(impressions)
        (click_a, click_b) = _half(clicks)
        csv_text = (
            "行銷活動名稱,廣告名稱,曝光次數,連結點擊次數,花費金額,購買次數,購買轉換價值\n"
            f"測試活動,{ad_names[0]},{imp_a},{click_a},{spend_a},{conv_a},{rev_a}\n"
            f"測試活動,{ad_names[1]},{imp_b},{click_b},{spend_b},{conv_b},{rev_b}\n"
        )
        result = perf.import_csv(main.conn, self.bid, self.cycle_id, csv_text, actor=ACTOR)
        assert result.matched_assets == 2, result.errors

    def _resolve_url(self):
        return f"/api/campaigns/{self.bid}/{self.cycle_id}/hypotheses/resolve"

    def test_supported_writes_ledger(self):
        hyp = self._link_hypothesis("通勤族比在家工作者更會下單")
        self._ab_spend(spend=10000, conversions=10, revenue=40000)
        reading.run(main.conn, self.bid, self.cycle_id, ACTOR)
        resp = self.client.post(self._resolve_url(), json={"verdicts": {hyp["id"]: "supported"}})
        self.assertEqual(resp.status_code, 200, resp.text)
        data = resp.json()
        self.assertTrue(data["ok"])
        self.assertEqual(data["updated"], 1)
        rows = [dict(r) for r in main.conn.execute(
            "SELECT * FROM learning_ledger WHERE brand_id = %s", (self.bid,))]
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["source_hypothesis_id"], hyp["id"])

    def test_rejected_does_not_write_ledger(self):
        hyp = self._link_hypothesis("這群受眾在意價格")
        self._spend(spend=10000, impressions=20000, clicks=400, conversions=0, revenue=0)
        reading.run(main.conn, self.bid, self.cycle_id, ACTOR)
        resp = self.client.post(self._resolve_url(), json={"verdicts": {hyp["id"]: "rejected"}})
        self.assertEqual(resp.status_code, 200, resp.text)
        self.assertEqual(resp.json()["updated"], 1)
        rows = main.conn.execute(
            "SELECT * FROM learning_ledger WHERE brand_id = %s", (self.bid,)).fetchall()
        self.assertEqual(len(rows), 0)

    def test_same_id_resolved_twice_is_ignored_second_time(self):
        """防重複入帳：第一次結案後 status 不再是 pending，第二次送同一個 id 不能再更新一次。"""
        hyp = self._link_hypothesis("通勤族比在家工作者更會下單")
        self._spend(spend=10000, impressions=20000, clicks=400, conversions=10, revenue=40000)
        reading.run(main.conn, self.bid, self.cycle_id, ACTOR)
        self.client.post(self._resolve_url(), json={"verdicts": {hyp["id"]: "supported"}})
        resp = self.client.post(self._resolve_url(), json={"verdicts": {hyp["id"]: "supported"}})
        self.assertEqual(resp.status_code, 200, resp.text)
        self.assertEqual(resp.json()["updated"], 0)

    def test_fake_id_is_ignored_without_error(self):
        self._spend(spend=10000, impressions=20000, clicks=400, conversions=10, revenue=40000)
        reading.run(main.conn, self.bid, self.cycle_id, ACTOR)
        resp = self.client.post(self._resolve_url(),
                                json={"verdicts": {"hyp_not_real": "supported"}})
        self.assertEqual(resp.status_code, 200, resp.text)
        self.assertEqual(resp.json()["updated"], 0)

    def test_closing_review_pending_then_resolved(self):
        """GET closing-review 加的三個欄位：結案前 pending/preselected 有值，結案後翻面。"""
        hyp = self._link_hypothesis("通勤族比在家工作者更會下單")
        self._ab_spend(spend=10000, conversions=10, revenue=40000)
        ok, err = reading.finalize(main.conn, self.bid, self.cycle_id, ACTOR)
        self.assertTrue(ok, err)

        review = self.client.get(
            f"/api/campaigns/{self.bid}/{self.cycle_id}/closing-review").json()["data"]
        before = {h["id"]: h for h in review["learning"]["hypotheses"]}[hyp["id"]]
        self.assertTrue(before["pending"])
        self.assertIsNotNone(before["preselected"])
        # R2-learning-honesty 契約第 2 點：GET closing-review 也要透出並排證據，
        # 不是只有內部的 reading.load() 看得到。
        self.assertEqual(len(before["comparison_cells"]), 2)

        resp = self.client.post(self._resolve_url(), json={"verdicts": {hyp["id"]: "supported"}})
        self.assertEqual(resp.status_code, 200, resp.text)

        review2 = self.client.get(
            f"/api/campaigns/{self.bid}/{self.cycle_id}/closing-review").json()["data"]
        after = {h["id"]: h for h in review2["learning"]["hypotheses"]}[hyp["id"]]
        self.assertFalse(after["pending"])
        self.assertIsNone(after["preselected"])
        self.assertEqual(after["verdict"], "supported")

    def test_closing_review_no_real_comparison_preselects_none_and_supported_downgrades(self):
        """R2-learning-honesty 契約第 1／3 點端到端：這期沒有真的做過對照（`_spend()`
        是純手動彙總、不對回任何切角）——closing-review 的預選是 None，就算直接對 API
        送「成立」，也會被程式端擋下降級成「看不出來」，不寫進 learning_ledger。"""
        hyp = self._link_hypothesis("通勤族比在家工作者更會下單")
        self._spend(spend=10000, impressions=20000, clicks=400, conversions=10, revenue=40000)
        ok, err = reading.finalize(main.conn, self.bid, self.cycle_id, ACTOR)
        self.assertTrue(ok, err)

        review = self.client.get(
            f"/api/campaigns/{self.bid}/{self.cycle_id}/closing-review").json()["data"]
        before = {h["id"]: h for h in review["learning"]["hypotheses"]}[hyp["id"]]
        self.assertIsNone(before["preselected"])
        self.assertEqual(before["comparison_cells"], [])

        resp = self.client.post(self._resolve_url(), json={"verdicts": {hyp["id"]: "supported"}})
        self.assertEqual(resp.status_code, 200, resp.text)
        self.assertEqual(resp.json()["updated"], 1)
        rows = main.conn.execute(
            "SELECT COUNT(*) c FROM learning_ledger WHERE brand_id = %s", (self.bid,)).fetchone()
        self.assertEqual(rows["c"], 0)

        review2 = self.client.get(
            f"/api/campaigns/{self.bid}/{self.cycle_id}/closing-review").json()["data"]
        after = {h["id"]: h for h in review2["learning"]["hypotheses"]}[hyp["id"]]
        self.assertEqual(after["verdict"], "inconclusive")

    def test_closing_review_hypothesis_gets_stale_note_after_late_data_flips_verdict_basis(self):
        """票 R4-late-data-downstream（B0-34）端到端：GET closing-review 透出
        `stale_note`——簽核後補件真的重判、數字真的變了才有值，簽核的 verdict 不因此改變。"""
        hyp = self._link_hypothesis("通勤族比在家工作者更會下單")
        self._spend(spend=10000, impressions=20000, clicks=400, conversions=10, revenue=40000)
        ok, err = reading.finalize(main.conn, self.bid, self.cycle_id, ACTOR)
        self.assertTrue(ok, err)
        self.client.post(self._resolve_url(), json={"verdicts": {hyp["id"]: "rejected"}})

        before = {h["id"]: h for h in self.client.get(
            f"/api/campaigns/{self.bid}/{self.cycle_id}/closing-review"
        ).json()["data"]["learning"]["hypotheses"]}[hyp["id"]]
        self.assertIsNone(before["stale_note"])

        self._spend(spend=0, impressions=0, clicks=0, conversions=0, revenue=12000)
        outcome = reading.rerun_for_late_data(main.conn, self.bid, self.cycle_id, actor=ACTOR)
        self.assertIsNotNone(outcome)

        after = {h["id"]: h for h in self.client.get(
            f"/api/campaigns/{self.bid}/{self.cycle_id}/closing-review"
        ).json()["data"]["learning"]["hypotheses"]}[hyp["id"]]
        self.assertTrue(after["stale_note"])  # 有提示文字，不比對確切文案
        self.assertEqual(after["verdict"], "rejected")  # 已簽核結論本身沒被自動改動

    def test_closing_review_recommendation_gets_delta_reason_after_late_data_rerun(self):
        """票 R4-late-data-downstream（B0-25）端到端：下期建議金額因補件而變時，
        `recommendation.delta_reason` 要說哪裡變了；還沒補件過（只有一版）時是 None。"""
        self._spend(spend=10000, impressions=20000, clicks=400, conversions=10, revenue=8000)
        ok, err = reading.finalize(main.conn, self.bid, self.cycle_id, ACTOR)
        self.assertTrue(ok, err)

        review = self.client.get(
            f"/api/campaigns/{self.bid}/{self.cycle_id}/closing-review").json()["data"]
        self.assertIsNone(review["recommendation"]["delta_reason"])

        self._spend(spend=0, impressions=0, clicks=0, conversions=0, revenue=12000)
        outcome = reading.rerun_for_late_data(main.conn, self.bid, self.cycle_id, actor=ACTOR)
        self.assertIsNotNone(outcome)

        review2 = self.client.get(
            f"/api/campaigns/{self.bid}/{self.cycle_id}/closing-review").json()["data"]
        reason = review2["recommendation"]["delta_reason"]
        self.assertIsNotNone(reason)
        self.assertIn("+150%", reason)  # 營收 8000→20000，成長率 (20000-8000)/8000
        self.assertIn("0.80→2.00", reason)  # ROAS 前後對照（spend 全期都是 10000 沒變）

    def test_malformed_body_is_400_not_500(self):
        """信任邊界：body 不是物件、verdicts 不是字典、完全沒有 JSON——三種都回 400 白話，
        不能一路炸成 500（審查發現 1）。"""
        for payload in ({"verdicts": "not-a-dict"}, {"verdicts": None}, {}, [1, 2, 3]):
            with self.subTest(payload=payload):
                resp = self.client.post(self._resolve_url(), json=payload)
                self.assertEqual(resp.status_code, 400, resp.text)
                self.assertIn("detail", resp.json())

    def test_non_json_body_is_400_not_500(self):
        resp = self.client.post(self._resolve_url(), content=b"not json at all",
                                headers={"Content-Type": "application/json"})
        self.assertEqual(resp.status_code, 400, resp.text)


if __name__ == "__main__":
    unittest.main()
