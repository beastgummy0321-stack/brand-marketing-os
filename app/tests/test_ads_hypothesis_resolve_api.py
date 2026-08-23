# -*- coding: utf-8 -*-
"""app/tests/test_ads_hypothesis_resolve_api.py — 票 L1-01：覆盤頁假設結案 API。

`POST .../hypotheses/resolve` 這條路由本身只做一件事：把請求接進
`ads_reading.resolve_hypotheses()`（唯讀檔，業務邏輯全在那裡，不得改）。這裡驗證的是接線
本身，以及 `closing-review` GET 新增的 `pending`／`preselected` 兩個欄位讀得到既有的
預選裁決——不重算任何判讀邏輯（決策 0035 第三節第 6 點：入帳前必須經人確認）。
"""

import json
import unittest

from fastapi.testclient import TestClient

import app.main as main
from app.ads import performance as perf
from app.ads import reading
from app.brand_intelligence import repository as bi_repo
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
            "INSERT OR IGNORE INTO campaign_cycle_hypothesis (campaign_cycle_id,"
            " strategy_hypothesis_id, brand_id, role) VALUES (?, ?, ?, ?)",
            (self.cycle_id, hyp["id"], self.bid, "audience"),
        )
        main.conn.commit()
        return hyp

    def _spend(self, **values):
        perf.import_manual(main.conn, self.bid, self.cycle_id, values, actor=ACTOR)

    def _resolve_url(self):
        return f"/api/campaigns/{self.bid}/{self.cycle_id}/hypotheses/resolve"

    def test_supported_writes_ledger(self):
        hyp = self._link_hypothesis("通勤族比在家工作者更會下單")
        self._spend(spend=10000, impressions=20000, clicks=400, conversions=10, revenue=40000)
        reading.run(main.conn, self.bid, self.cycle_id, ACTOR)
        resp = self.client.post(self._resolve_url(), json={"verdicts": {hyp["id"]: "supported"}})
        self.assertEqual(resp.status_code, 200, resp.text)
        data = resp.json()
        self.assertTrue(data["ok"])
        self.assertEqual(data["updated"], 1)
        rows = [dict(r) for r in main.conn.execute(
            "SELECT * FROM learning_ledger WHERE brand_id = ?", (self.bid,))]
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
            "SELECT * FROM learning_ledger WHERE brand_id = ?", (self.bid,)).fetchall()
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
        self._spend(spend=10000, impressions=20000, clicks=400, conversions=10, revenue=40000)
        ok, err = reading.finalize(main.conn, self.bid, self.cycle_id, ACTOR)
        self.assertTrue(ok, err)

        review = self.client.get(
            f"/api/campaigns/{self.bid}/{self.cycle_id}/closing-review").json()["data"]
        before = {h["id"]: h for h in review["learning"]["hypotheses"]}[hyp["id"]]
        self.assertTrue(before["pending"])
        self.assertIsNotNone(before["preselected"])

        resp = self.client.post(self._resolve_url(), json={"verdicts": {hyp["id"]: "supported"}})
        self.assertEqual(resp.status_code, 200, resp.text)

        review2 = self.client.get(
            f"/api/campaigns/{self.bid}/{self.cycle_id}/closing-review").json()["data"]
        after = {h["id"]: h for h in review2["learning"]["hypotheses"]}[hyp["id"]]
        self.assertFalse(after["pending"])
        self.assertIsNone(after["preselected"])
        self.assertEqual(after["verdict"], "supported")

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
