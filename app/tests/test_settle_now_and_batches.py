# -*- coding: utf-8 -*-
"""app/tests/test_settle_now_and_batches.py — 票 S1-01：檔期「現在結算」＋匯入整批撤銷
（`.scratch/s1/issues/01-settle-now-and-batch-undo.md`）。

Shares `_BaseImportTest`／`ACTOR`／`_CSV_ZH` with test_ads_performance.py (same convention
as test_ads_performance_routes.py). LLM stubbed the same way as
PerformanceGetAssetBreakdownTest in that file: swap `reading.PROVIDER` for a FakeProvider
that always returns `{"text": "..."}` — the only shape every LLM call site in reading.py
(``_explain``／``_explain_diff``／``_explain_hypotheses``) needs.
"""

import json
import unittest

import app.main as main
from app.ads import performance as perf
from app.ads import reading
from app.llm.providers import FakeProvider, ProviderResponse, Usage
from app.tests.test_ads_performance import ACTOR, _CSV_ZH, _BaseImportTest


def _fake(text):
    return ProviderResponse(output_text=text, structured=None,
                            usage=Usage(input_tokens=300, output_tokens=150),
                            stop_reason="end_turn")


class SettleNowAndBatchesTest(_BaseImportTest):
    def setUp(self):
        super().setUp()
        self._orig_provider = reading.PROVIDER
        reading.PROVIDER = FakeProvider(response=_fake(
            json.dumps({"text": "說明文字"}, ensure_ascii=False)))

    def tearDown(self):
        reading.PROVIDER = self._orig_provider

    def _settle_url(self):
        return f"/api/campaigns/{self.bid}/{self.cycle_id}/settle-now"

    def _batches_url(self):
        return f"/api/campaigns/{self.bid}/{self.cycle_id}/performance/batches"

    def _post_csv(self, text):
        return self.client.post(
            f"/api/campaigns/{self.bid}/{self.cycle_id}/performance/csv",
            files={"perf_file": ("perf.csv", text, "text/csv")})

    # a. 無成效列
    def test_a_no_rows_cannot_settle(self):
        resp = self.client.get(self._settle_url())
        self.assertEqual(resp.status_code, 200)
        data = resp.json()["data"]
        self.assertFalse(data["can_settle"])
        self.assertFalse(data["already_closed"])
        self.assertTrue(data["reason"])

        post_resp = self.client.post(self._settle_url())
        self.assertEqual(post_resp.status_code, 400)

    # b. 匯一筆 CSV 後 settle-now
    def test_b_settle_now_closes_cycle_and_closing_review_available(self):
        perf.import_csv(main.conn, self.bid, self.cycle_id, _CSV_ZH, actor=ACTOR)

        get_resp = self.client.get(self._settle_url())
        self.assertTrue(get_resp.json()["data"]["can_settle"])

        post_resp = self.client.post(self._settle_url())
        self.assertEqual(post_resp.status_code, 200, post_resp.text)
        self.assertTrue(post_resp.json()["ok"])

        cycle = main.conn.execute(
            "SELECT status FROM campaign_cycle WHERE id = ?", (self.cycle_id,)).fetchone()
        self.assertEqual(cycle["status"], "CLOSED")

        review = self.client.get(f"/api/campaigns/{self.bid}/{self.cycle_id}/closing-review")
        self.assertEqual(review.status_code, 200)

    # c. 已 CLOSED 再 POST
    def test_c_already_closed_cannot_settle_again(self):
        perf.import_csv(main.conn, self.bid, self.cycle_id, _CSV_ZH, actor=ACTOR)
        self.client.post(self._settle_url())

        get_resp = self.client.get(self._settle_url())
        self.assertTrue(get_resp.json()["data"]["already_closed"])
        self.assertFalse(get_resp.json()["data"]["can_settle"])

        post_resp = self.client.post(self._settle_url())
        self.assertEqual(post_resp.status_code, 400)

    # d. 匯兩批（兩次 POST csv）
    def test_d_batches_listed_newest_first_with_row_counts(self):
        self._post_csv(_CSV_ZH)
        self._post_csv("行銷活動名稱,花費金額\n第二批,2000\n")

        resp = self.client.get(self._batches_url())
        self.assertEqual(resp.status_code, 200)
        items = resp.json()["data"]["items"]
        self.assertEqual(len(items), 2)
        self.assertEqual(items[0]["rows"], 1)
        self.assertEqual(items[1]["rows"], 1)
        self.assertGreaterEqual(items[0]["imported_at"], items[1]["imported_at"])  # 新到舊

    # e. DELETE 第一批
    def test_e_delete_batch_removes_only_its_rows_and_no_orphans(self):
        self._post_csv(_CSV_ZH)  # spend 5000.5
        self._post_csv("行銷活動名稱,花費金額\n第二批,2000\n")

        items = self.client.get(self._batches_url()).json()["data"]["items"]
        oldest_batch_id = items[-1]["batch_id"]  # _CSV_ZH 批，先匯入

        resp = self.client.delete(
            f"/api/campaigns/{self.bid}/{self.cycle_id}/performance/batches/{oldest_batch_id}")
        self.assertEqual(resp.status_code, 200, resp.text)
        self.assertEqual(resp.json()["deleted"], 1)

        totals = perf.totals(main.conn, self.bid, self.cycle_id)
        self.assertEqual(totals["spend"], 2000)

        orphans = main.conn.execute(
            "SELECT COUNT(*) AS n FROM derived_metric WHERE performance_snapshot_id NOT IN"
            " (SELECT id FROM performance_snapshot)").fetchone()
        self.assertEqual(orphans["n"], 0)

    # f. DELETE 不存在 batch_id
    def test_f_delete_missing_batch_404(self):
        resp = self.client.delete(
            f"/api/campaigns/{self.bid}/{self.cycle_id}/performance/batches/import_nope")
        self.assertEqual(resp.status_code, 404)
        self.assertEqual(resp.json(), {"detail": "找不到這批匯入"})

    # g. CLOSED 後 DELETE
    def test_g_delete_after_closed_reruns_late_data(self):
        self._post_csv(_CSV_ZH)
        self.client.post(self._settle_url())  # cycle 進 CLOSED，結算版含 _CSV_ZH 這批

        self._post_csv("行銷活動名稱,花費金額\n晚到,3000\n")  # 補件，第二批

        items = self.client.get(self._batches_url()).json()["data"]["items"]
        settled_batch_id = items[-1]["batch_id"]  # 結算當下就在的那批，刪掉才會有真差異

        resp = self.client.delete(
            "/api/campaigns/%s/%s/performance/batches/%s" % (self.bid, self.cycle_id, settled_batch_id))
        self.assertEqual(resp.status_code, 200, resp.text)
        self.assertEqual(resp.json()["rerun"], "late_data")

        cycle = main.conn.execute(
            "SELECT status FROM campaign_cycle WHERE id = ?", (self.cycle_id,)).fetchone()
        self.assertEqual(cycle["status"], "CLOSED")  # D2：不可降級


if __name__ == "__main__":
    unittest.main()
