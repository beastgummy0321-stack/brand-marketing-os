"""F30 Contract A: a fact-check rejection keeps the round usable, and a round can be re-run."""

import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

import app.tests.test_ads_review_cycle as _cycle
from app.ads import review_jobs, review_monitor, review_policy, review_rounds, triage
from app.core import db, interrupts
from app.main import app

# The two model texts the dev DB rejected on 2026-09-25 (Feature F30 Evidence).
REAL_HEDGES = (
    "目前可見的購買歸因資料顯示本期仍有成果，但前後期素材與完整投放條件未能確認相同，"
    "且部分日期歸因未知，因此不足以判斷素材或設定造成成效變化。品牌商務訂單屬品牌層級，"
    "無法歸因至本廣告；幣別與期間涵蓋也有限制。",
    "目前購買成本符合活動目標，但相較前期表現較弱；購買樣本有限，且商務訂單無法歸因至本廣告，"
    "暫不足以判定素材或設定造成變化。",
)


class ReviewRetryTest(unittest.TestCase):
    # Borrow fixture methods via the module: a TestCase bound here would be collected twice.
    setUp = _cycle.ReviewCycleTest.setUp
    observation = _cycle.ReviewCycleTest.observation
    request = _cycle.ReviewCycleTest.request
    reply = _cycle.ReviewCycleTest.reply
    run_review = _cycle.ReviewCycleTest.run_review

    def tearDown(self):
        self.conn.rollback()
        self.conn.execute("DELETE FROM ads_review_monitor WHERE brand_id=%s", (self.brand,))
        self.conn.execute("DELETE FROM ads_review_round WHERE brand_id=%s", (self.brand,))
        self.conn.commit()

    def get(self, review_id):
        return review_rounds.get(self.conn, self.org, self.brand, self.campaign, review_id)

    def retry(self, review_id):
        return review_rounds.retry(self.conn, self.org, self.brand, self.campaign, review_id)

    def rejected_round(self):
        self.observation()
        self.reply(hypothesis="此廣告造成收入改善")
        row = review_rounds.request_manual(
            self.conn, self.org, self.brand, self.campaign, self.ad["id"], self.start, self.end
        )
        return self.run_review(row)

    def test_real_hedges_pass_and_positive_cause_or_digit_still_fail(self):
        for text in REAL_HEDGES:
            self.assertFalse(review_policy.unsupported_claim(text), text)
        self.assertTrue(review_policy.unsupported_claim("造成轉換下降"))
        self.assertTrue(review_policy.unsupported_claim("不足以判斷，本期 2 筆購買"))

    def test_rejected_text_is_ready_without_recommendation_and_settles_cost(self):
        review = self.rejected_round()
        self.assertEqual(review["status"], "ready")
        self.assertIsNone(review["error"])
        self.assertEqual(
            review["result_json"],
            {
                "recommendations": [],
                "limitations": review["evidence_json"]["limitations"],
                "causality": "unavailable",
                "rejected": {"reason": "模型包含未允許的數字或因果斷言；請依原始證據人工判讀。"},
            },
        )
        self.assertEqual(review["reservation_state"], "settled")
        self.assertEqual(float(review["failed_cost"]), 0)
        self.assertEqual(len(self.fake.calls), 1)

    def test_unparseable_and_oversized_output_are_rejected_not_failed(self):
        self.observation()
        self.reply()
        self.fake.response.output_text = "not json at all"
        review = self.run_review(self.request())
        self.assertEqual(review["status"], "ready")
        self.assertTrue(review["result_json"]["rejected"]["reason"])
        self.observation(clicks=21)
        self.fake.response.output_text = "{" + "x" * 50000
        review = self.run_review(self.request())
        self.assertEqual(review["status"], "ready")
        self.assertIn("上限", review["result_json"]["rejected"]["reason"])

    def test_saved_rejected_output_recovers_as_recovered(self):
        self.observation()
        self.reply(hypothesis="此廣告造成收入改善")
        row = self.request()
        with patch.object(review_jobs, "apply_saved_task", side_effect=RuntimeError("crash")):
            self.assertEqual(self.run_review(row)["status"], "unknown")
        result = review_jobs.recover(self.conn, int(db.now_utc().timestamp()), bootstrap=True)
        self.assertGreaterEqual(result["reviews_recovered"], 1)
        review = self.get(row["id"])
        self.assertEqual(review["status"], "ready")
        self.assertTrue(review["result_json"]["rejected"])
        self.assertEqual(len(self.fake.calls), 1)

    def test_provider_failure_keeps_unknown_and_is_not_retryable(self):
        from app.llm import providers

        self.observation()
        self.fake.exception = providers.ProviderTimeoutError("fake timeout")
        review = self.run_review(self.request())
        self.assertEqual(review["status"], "unknown")
        self.assertNotIn("rejected", review["result_json"])
        with self.assertRaises(ValueError):
            self.retry(review["id"])

    def test_retry_reruns_same_evidence_once_and_becomes_current(self):
        old = self.rejected_round()
        self.assertEqual(
            review_monitor.get(self.conn, self.org, self.brand, self.campaign, self.ad["id"])[
                "review_id"
            ],
            old["id"],
        )
        again = self.retry(old["id"])
        self.assertNotEqual(again["id"], old["id"])
        self.assertNotEqual(again["evidence_hash"], old["evidence_hash"])
        self.assertEqual(again["evidence_json"]["retry_of"], old["id"])
        self.assertEqual(again["status"], "queued")
        self.assertEqual(again["reservation_state"], "held")
        self.assertGreater(float(again["reserved_amount"]), 0)
        self.assertEqual(
            (again["entity_id"], again["window_start"], again["window_end"], again["previous_id"]),
            (old["entity_id"], old["window_start"], old["window_end"], old["previous_id"]),
        )
        # A repeated call returns the same retry round and reserves nothing more.
        self.assertEqual(self.retry(old["id"])["id"], again["id"])
        count = self.conn.execute(
            "SELECT COUNT(*) AS n FROM ads_review_round WHERE brand_id=%s", (self.brand,)
        ).fetchone()["n"]
        self.assertEqual(count, 2)
        # The monitor, the review workspace and triage all read the retry round as current.
        monitor = review_monitor.get(self.conn, self.org, self.brand, self.campaign, self.ad["id"])
        self.assertEqual(monitor["review_id"], again["id"])
        self.assertEqual(monitor["state"], "queued")
        workspace = review_rounds.workspace(self.conn, self.org, self.brand, self.campaign)
        self.assertEqual(workspace["reviews"][0]["id"], again["id"])
        rounds = triage._brand_review_rounds(self.conn, self.org, self.brand)
        current = triage._matching_review_round(
            rounds, self.campaign, self.ad["id"], {"start": self.start, "end": self.end}
        )
        self.assertEqual(current["id"], again["id"])
        # The model reads exactly the old evidence: `retry_of` never reaches it.
        self.reply()
        done = self.run_review(again)
        self.assertEqual(done["status"], "ready", done["error"])
        self.assertNotIn("rejected", done["result_json"])
        self.assertEqual(len(self.fake.calls), 2)
        self.assertNotIn("retry_of", self.fake.calls[1]["messages"][0]["content"])
        self.assertEqual(self.fake.calls[1]["messages"], self.fake.calls[0]["messages"])

    def test_failed_round_is_retryable(self):
        self.observation()
        self.reply()
        row = self.request()
        with patch("app.llm.providers.resolve_model", return_value="another-model"):
            failed = self.run_review(row)
        self.assertEqual(failed["status"], "failed")
        self.assertEqual(self.fake.calls, [])
        again = self.retry(row["id"])
        self.assertEqual(again["evidence_json"]["retry_of"], row["id"])
        self.assertEqual(self.run_review(again)["status"], "ready")

    def test_completed_on_rejected_round_and_reference_without_pair(self):
        old = self.rejected_round()
        self.assertEqual(
            review_rounds.proposal_reference(
                self.conn, self.org, self.brand, self.campaign, None, None, []
            ),
            {},
        )
        with self.assertRaises(ValueError):
            review_rounds.proposal_reference(
                self.conn, self.org, self.brand, self.campaign, old["id"], "recommendation-1", []
            )
        done = review_rounds.decide(
            self.conn, self.org, self.brand, self.campaign, old["id"], "completed", "人工判讀完成"
        )
        self.assertEqual(done["status"], "completed")
        monitor = review_monitor.get(self.conn, self.org, self.brand, self.campaign, self.ad["id"])
        self.assertIsNone(monitor["review_id"])
        self.assertEqual(monitor["window"], None)
        with self.assertRaises(ValueError):
            self.retry(old["id"])

    def test_closed_campaign_refuses_retry_without_cost_or_monitor_write(self):
        old = self.rejected_round()
        self.conn.execute("UPDATE ads_campaign SET status='closed' WHERE id=%s", (self.campaign,))
        self.conn.commit()
        before, enqueued = self.monitor_row(), self.enqueue.call_count
        with self.assertRaisesRegex(ValueError, "已結案"):
            self.retry(old["id"])
        self.conn.rollback()
        client = TestClient(app)
        base = f"/api/ads/brands/{self.brand}/campaigns/{self.campaign}/reviews/"
        response = client.post(base + old["id"] + "/retry")
        self.assertEqual(response.status_code, 409, response.text)
        self.assertEqual(response.json()["error"]["code"], "review_unavailable")
        rounds = self.conn.execute(
            "SELECT id FROM ads_review_round WHERE brand_id=%s", (self.brand,)
        ).fetchall()
        self.assertEqual([r["id"] for r in rounds], [old["id"]])
        self.assertEqual(self.monitor_row(), before)
        self.assertEqual(self.enqueue.call_count, enqueued)

    def test_retry_returning_a_decided_round_leaves_the_monitor_alone(self):
        old = self.rejected_round()
        again = self.retry(old["id"])
        self.reply()
        self.run_review(again)
        review_rounds.decide(
            self.conn, self.org, self.brand, self.campaign, again["id"], "completed", "採用"
        )
        advanced = self.monitor_row()
        self.assertIsNone(advanced["review_id"])
        self.assertEqual(advanced["previous_id"], again["id"])
        # A stale screen still offers retry on A: it dedupes to decided B and must not repoint
        # the monitor at B, reopen its window or replay on_decision.
        with patch.object(review_monitor, "on_decision") as replay:
            same = self.retry(old["id"])
        self.assertEqual(same["id"], again["id"])
        self.assertEqual(same["decision"], "completed")
        replay.assert_not_called()
        self.assertEqual(self.monitor_row(), advanced)

    def monitor_row(self):
        row = self.conn.execute(
            "SELECT review_id,previous_id,window_start,window_end,state,next_check_at,revision "
            "FROM ads_review_monitor WHERE brand_id=%s AND entity_id=%s",
            (self.brand, self.ad["id"]),
        ).fetchone()
        return dict(row) if row else None

    def test_http_retry_shape_and_conflicts(self):
        client = TestClient(app)
        base = f"/api/ads/brands/{self.brand}/campaigns/{self.campaign}/reviews/"
        old = self.rejected_round()
        response = client.post(base + old["id"] + "/retry")
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertEqual(set(body), {"review", "monitor"})
        self.assertEqual(body["review"]["evidence_json"]["retry_of"], old["id"])
        self.assertEqual(body["monitor"]["review_id"], body["review"]["id"])
        repeat = client.post(base + old["id"] + "/retry")
        self.assertEqual(repeat.json()["review"]["id"], body["review"]["id"])
        # A normal ready round (the retry, now accepted) is not retryable.
        self.reply()
        self.run_review(body["review"])
        conflict = client.post(base + body["review"]["id"] + "/retry")
        self.assertEqual(conflict.status_code, 409, conflict.text)
        self.assertEqual(conflict.json()["error"]["code"], "review_unavailable")
        # The superseded round is closed: it takes no decision, and a stale retry dedupes.
        decided = client.post(
            base + old["id"] + "/decision", json={"decision": "unjudgeable", "reason": "改看新一回"}
        )
        self.assertEqual(decided.status_code, 409, decided.text)
        stale = client.post(base + old["id"] + "/retry")
        self.assertEqual(stale.json()["review"]["id"], body["review"]["id"])
        # A decided round is not retryable either.
        client.post(
            base + body["review"]["id"] + "/decision",
            json={"decision": "completed", "reason": "採用"},
        )
        self.assertEqual(client.post(base + body["review"]["id"] + "/retry").status_code, 409)

    def test_retry_closes_superseded_round_and_decide_ends_its_notice(self):
        self.addCleanup(self.conn.commit)
        self.addCleanup(
            self.conn.execute, "DELETE FROM interrupt WHERE brand_id=%s", (self.brand,)
        )

        def notice(review_id):
            # The same notice `runtime` raises for every ready round.
            interrupts.enqueue(
                self.conn, org_id=self.org, brand_id=self.brand, category="ads_review_ready",
                dedupe_key="ads-review:" + review_id, message="廣告檢討已備妥，請決定下一步",
            )
            self.conn.commit()

        def open_keys():
            return {r["dedupe_key"] for r in interrupts.list_open(
                self.conn, org_id=self.org, brand_id=self.brand, category="ads_review_ready",
                archive_stale=False,
            )}

        old = self.rejected_round()
        notice(old["id"])
        again = self.retry(old["id"])
        closed = self.get(old["id"])
        self.assertEqual((closed["status"], closed["decision"]), ("unjudgeable", "unjudgeable"))
        self.assertNotIn("ads-review:" + old["id"], open_keys())
        with self.assertRaises(ValueError):
            review_rounds.decide(
                self.conn, self.org, self.brand, self.campaign, old["id"], "deferred", "x",
                "2999-01-01T00:00:00+00:00",
            )
        self.reply()
        self.run_review(again)
        notice(again["id"])
        review_rounds.decide(
            self.conn, self.org, self.brand, self.campaign, again["id"], "completed", "採用"
        )
        self.assertEqual(open_keys(), set())
