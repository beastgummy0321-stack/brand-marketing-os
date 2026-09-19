"""Single-ad review uses real persistence/gateway and never calls an external provider."""

import json
import unittest
from copy import deepcopy
from datetime import timedelta
from unittest.mock import patch

from app.ads import (
    change_control,
    change_control_data,
    external_repository,
    review_evidence,
    review_jobs,
    review_policy,
    review_rounds,
)
from app.brand_intelligence import repository as brands
from app.core import db, settings
from app.llm import providers


class ReviewCycleTest(unittest.TestCase):
    def setUp(self):
        self.conn, self.org = db.current(), db.DEV_ORG_ID
        self.brand = brands.create_brand(
            self.conn, org_id=self.org, name="檢討品牌", actor="test", client_name=None
        )["id"]
        self.campaign = external_repository.create_imported_campaign(
            self.conn, self.org, self.brand, name="持續活動"
        )["id"]
        self.conn.execute(
            "UPDATE ads_campaign SET goal_text='確認訊息是否吸引關注',"
            "objective='awareness' WHERE id=%s",
            (self.campaign,),
        )
        self.ad = external_repository.upsert_entity(
            self.conn,
            self.org,
            self.brand,
            self.campaign,
            {
                "platform": "fixture",
                "source_account": "account",
                "native_kind": "ad",
                "native_id": "original-B",
                "native_status": "ACTIVE",
                "currency": "TWD",
                "creative": {
                    "kind": "image",
                    "fields": {"title": "原標題", "body": "原文案", "image_hash": "same-picture"},
                },
            },
        )
        self.end = settings.today_for_org(self.conn, org_id=self.org) - timedelta(days=1)
        self.start = self.end - timedelta(days=2)
        self.fake = providers.FakeProvider()
        self.fake.name = "anthropic"
        patch.object(review_rounds, "PROVIDER", self.fake).start()
        patch.object(providers, "resolve_model", return_value="claude-haiku-4-5").start()
        self.enqueue = patch.object(review_jobs, "enqueue").start()
        self.addCleanup(patch.stopall)
        self.conn.commit()

    def observation(self, day=None, **extra):
        external_repository.upsert_observation(
            self.conn,
            self.org,
            self.brand,
            self.campaign,
            {
                "entity_id": self.ad["id"],
                "day": day or self.end,
                "metric_scope": "ad",
                "attribution_key": "click-seven-day",
                "currency": "TWD",
                "source": "fixture",
                "spend": 100,
                "impressions": 1000,
                "clicks": 20,
                "purchases": None,
                "revenue": None,
                **extra,
            },
        )
        self.conn.commit()

    def request(self, **extra):
        return review_rounds.request(
            self.conn,
            self.org,
            self.brand,
            self.campaign,
            self.ad["id"],
            extra.pop("start", self.start),
            extra.pop("end", self.end),
            **extra,
        )

    def reply(self, **extra):
        item = {
            "target_id": self.ad["id"],
            "recommendation": "adjust",
            "evidence_refs": ["current", "conditions"],
            "hypothesis": "可能需要更清楚的訊息",
            "risks": ["觀察資料仍有限"],
            "next_step": "先由人修訂文案再核准清單",
            "suggested_copy": {"body": "了解更多"},
            **extra,
        }
        value = {"recommendations": [item]}
        self.fake.response = providers.ProviderResponse(
            output_text=json.dumps(value, ensure_ascii=False),
            structured=value,
            usage=providers.Usage(input_tokens=100, output_tokens=100),
            stop_reason="end_turn",
        )
        return value

    def run_review(self, row):
        review_jobs.run(self.org, self.brand, self.campaign, row["id"])
        return review_rounds.get(self.conn, self.org, self.brand, self.campaign, row["id"])

    def test_waiting_has_evidence_and_defer_without_model_or_campaign_closure(self):
        row = self.request()
        self.assertEqual(row["status"], "waiting")
        self.assertTrue(row["evidence_json"]["waiting_reasons"])
        self.assertEqual(row["evidence_json"]["commerce"]["current"]["attribution"], "unavailable")
        self.assertIsNone(row["evidence_json"]["commerce"]["current"]["order_summary"]["currency"])
        self.assertEqual(self.request()["id"], row["id"])
        deferred = review_rounds.decide(
            self.conn,
            self.org,
            self.brand,
            self.campaign,
            row["id"],
            "deferred",
            "待補資料",
            (db.now_utc() + timedelta(days=1)).isoformat(),
        )
        self.assertEqual(deferred["status"], "deferred")
        self.enqueue.assert_not_called()
        self.assertEqual(self.fake.calls, [])
        self.assertNotEqual(
            change_control_data.campaign(self.conn, self.org, self.brand, self.campaign)["status"],
            "closed",
        )

    def test_gateway_once_and_proposal_link_human_edit_then_next_review_actual_evidence(self):
        prior_end = self.end - timedelta(days=1)
        self.observation(prior_end)
        self.reply()
        row = self.request(end=prior_end)
        done = self.run_review(row)
        self.assertEqual(done["status"], "ready", done["error"])
        self.assertTrue(done["llm_task_id"])
        self.assertEqual(self.run_review(row)["status"], "ready")
        self.assertEqual(self.request(end=prior_end)["id"], row["id"])
        self.assertEqual(len(self.fake.calls), 1)
        self.assertEqual(self.fake.calls[0]["max_tokens"], 4096)
        self.assertEqual(self.fake.calls[0]["timeout_s"], 120)
        saved = change_control.create(
            self.conn,
            self.org,
            self.brand,
            self.campaign,
            {
                "operation_id": db.new_id("operation"),
                "month": self.end.strftime("%Y-%m"),
                "title": "保留圖片，只修改原廣告文案",
                "review_id": row["id"],
                "recommendation_id": "recommendation-1",
                "items": [
                    {
                        "kind": "copy",
                        "target_id": self.ad["id"],
                        "after": {"body": "由人修改的文案"},
                        "reason": "檢驗假設",
                    }
                ],
            },
            "human",
        )
        self.assertEqual(saved["review_id"], row["id"])
        self.assertEqual(saved["plan_json"]["review_evidence_hash"], row["evidence_hash"])
        self.assertEqual(saved["items"][0]["media_identity"]["platform_media_id"], "same-picture")
        # A previous review may cover an earlier window and preserves real action verification.
        change_control._insert_actions(
            self.conn, self.org, self.brand, self.campaign, saved, "human"
        )
        self.conn.execute(
            "UPDATE ads_action SET verification_state='deviated',evidence_json=%s "
            "WHERE change_set_id=%s",
            (db.jsonb({"setting_matches": False, "message": "平台讀回與計畫不同"}), saved["id"]),
        )
        self.conn.commit()
        next_round = self.request(previous_id=row["id"])
        prior = next_round["evidence_json"]["previous_review"]
        self.assertEqual(prior["actions"][0]["verification_state"], "deviated")
        self.assertFalse(prior["actions"][0]["evidence_json"]["setting_matches"])
        self.assertIn("current", prior["evidence"])

    def test_unknown_purchase_not_zero_and_separate_attribution_currency_source(self):
        self.observation()
        self.observation(self.end - timedelta(days=1), purchases=0, revenue=0)
        self.observation(
            attribution_key="view-one-day", currency="USD", spend=3, purchases=2, revenue=6
        )
        row = self.request()
        evidence = row["evidence_json"]
        self.assertEqual(len(evidence["current"]["series"]), 2)
        series = next(s for s in evidence["current"]["series"] if s["currency"] == "TWD")
        self.assertIsNone(series["metrics"]["purchases"])
        self.assertIsNone(series["metrics"]["roas"])
        self.assertEqual(series["known_counts"]["purchases"], 1)
        self.assertEqual(evidence["current"]["missing_days"], 1)
        self.assertEqual(evidence["conditions"]["history"], "unknown")
        self.assertEqual(evidence["previous"]["row_count"], 0)

    def test_invalid_model_target_refs_numbers_and_copy_rejected_without_resend(self):
        self.observation()
        self.reply(target_id="another-ad")
        row = self.request()
        failed = self.run_review(row)
        self.assertEqual(failed["status"], "failed")
        self.assertEqual(self.request()["id"], row["id"])
        self.run_review(row)
        self.assertEqual(len(self.fake.calls), 1)
        for override in (
            {"evidence_refs": ["fabricated"]},
            {"hypothesis": "營收增加了 999 元"},
            {"hypothesis": "此廣告造成收入改善"},
            {"suggested_copy": {"body": "保證立刻治癒"}},
        ):
            with self.assertRaises(ValueError):
                review_policy.validate(
                    self.conn, self.org, self.brand, row["evidence_json"], self.reply(**override)
                )

    def test_scope_dates_and_non_ad_rejected(self):
        with self.assertRaises(ValueError):
            self.request(end=self.end + timedelta(days=1))
        with self.assertRaises(ValueError):
            review_rounds.get(self.conn, self.org, "other-brand", self.campaign, "unknown")
        self.conn.execute(
            "UPDATE ads_external_entity SET native_kind='campaign' WHERE id=%s", (self.ad["id"],)
        )
        with self.assertRaises(ValueError):
            self.request()

    def test_changed_goal_invalidates_proposal_but_timestamp_does_not(self):
        self.observation()
        self.reply()
        done = self.run_review(self.request())
        items = [{"kind": "copy", "target_id": self.ad["id"]}]
        self.conn.execute(
            "UPDATE ads_external_entity SET updated_at=now() WHERE id=%s", (self.ad["id"],)
        )
        self.assertTrue(
            review_rounds.proposal_reference(
                self.conn,
                self.org,
                self.brand,
                self.campaign,
                done["id"],
                "recommendation-1",
                items,
            )
        )
        self.conn.execute(
            "UPDATE ads_campaign SET goal_text='已改成其他目標' WHERE id=%s", (self.campaign,)
        )
        with self.assertRaisesRegex(ValueError, "目標已改變"):
            review_rounds.proposal_reference(
                self.conn,
                self.org,
                self.brand,
                self.campaign,
                done["id"],
                "recommendation-1",
                items,
            )

    def test_oversized_context_rejected_before_provider(self):
        self.observation()
        with patch.object(
            review_evidence.context_compiler, "compile", return_value=("A" * 12001, [], 1, None)
        ):
            with self.assertRaisesRegex(ValueError, "12,000"):
                self.request()
        self.assertEqual(self.fake.calls, [])

    def test_negative_causal_risk_allowed_but_positive_clause_rejected(self):
        self.observation()
        row = self.request()
        result = review_policy.validate(
            self.conn,
            self.org,
            self.brand,
            row["evidence_json"],
            self.reply(risks=["無法確認文案造成改善"]),
        )
        self.assertEqual(result["causality"], "unavailable")
        self.assertTrue(review_policy.unsupported_claim("無法確認資料，但是此文案已改善營收"))

    def test_provider_timeout_records_unknown_and_holds_reservation_no_retry(self):
        self.observation()
        self.fake.exception = providers.ProviderTimeoutError("fake timeout")
        row = self.request()
        outcome = self.run_review(row)
        self.assertEqual(outcome["status"], "unknown", outcome["error"])
        self.assertEqual(outcome["reservation_state"], "held")
        self.assertTrue(outcome["llm_task_id"])
        self.assertEqual(self.request()["id"], row["id"])
        self.run_review(row)
        self.assertEqual(len(self.fake.calls), 1)

    def test_source_timezone_never_inferred_from_org_and_no_pi_data(self):
        self.observation()
        unknown = self.request()
        self.assertIsNone(unknown["evidence_json"]["window"]["timezone"])
        with patch.object(
            review_evidence.external_sync,
            "account_reader",
            return_value=(None, {"timezone_name": "UTC", "access_token": "private-not-evidence"}),
        ):
            known = self.request(end=self.end - timedelta(days=1))
        self.assertEqual(known["evidence_json"]["window"]["timezone"], "UTC")
        self.assertNotIn("private-not-evidence", json.dumps(known["evidence_json"]))

    def test_waiting_large_context_still_has_exit_and_no_reservation(self):
        with patch.object(
            review_evidence.context_compiler, "compile", return_value=("A" * 12001, [], 1, None)
        ):
            row = self.request()
        self.assertEqual(row["status"], "waiting")
        self.assertEqual(row["reserved_amount"], 0)
        self.assertEqual(row["reservation_state"], "settled")
        self.assertEqual(self.fake.calls, [])

    def test_future_revisit_required_and_completed_does_not_close_campaign(self):
        self.observation()
        self.reply()
        ready = self.run_review(self.request())
        with self.assertRaises(ValueError):
            review_rounds.decide(
                self.conn,
                self.org,
                self.brand,
                self.campaign,
                ready["id"],
                "deferred",
                "延後",
                None,
            )
        done = review_rounds.decide(
            self.conn, self.org, self.brand, self.campaign, ready["id"], "completed", "本回保留觀察"
        )
        self.assertEqual(done["status"], "completed")
        self.assertNotEqual(
            change_control_data.campaign(self.conn, self.org, self.brand, self.campaign)["status"],
            "closed",
        )

    def test_model_cost_ceiling_rejected_before_reservation_or_job(self):
        self.observation()
        with patch.object(providers, "resolve_model", return_value="claude-sonnet-5"):
            with self.assertRaisesRegex(ValueError, r"US\$0.50"):
                self.request()
        self.conn.rollback()
        count = self.conn.execute(
            "SELECT COUNT(*) AS n FROM ads_review_round WHERE brand_id=%s", (self.brand,)
        ).fetchone()["n"]
        self.assertEqual(count, 0)
        self.enqueue.assert_not_called()
        self.assertEqual(self.fake.calls, [])

    def test_api_create_reopen_decide_scope_and_background_registration(self):
        from fastapi.testclient import TestClient

        from app import background
        from app.main import app

        review_jobs.register_tasks()
        self.assertIn(review_jobs.TASK, background.app().tasks)
        client = TestClient(app)
        base = f"/api/ads/brands/{self.brand}/campaigns/{self.campaign}"
        response = client.post(
            base + "/reviews",
            json={
                "entity_id": self.ad["id"],
                "start": self.start.isoformat(),
                "end": self.end.isoformat(),
            },
        )
        self.assertEqual(response.status_code, 200, response.text)
        row = response.json()["review"]
        self.assertEqual(row["status"], "waiting")
        self.assertEqual(client.get(base + "/reviews").json()["targets"][0]["id"], self.ad["id"])
        self.assertEqual(
            client.get(base + "/reviews/" + row["id"]).json()["review"]["id"], row["id"]
        )
        result = client.post(
            base + "/reviews/" + row["id"] + "/decision",
            json={"decision": "unjudgeable", "reason": "目前資料不完整"},
        )
        self.assertEqual(result.status_code, 200, result.text)
        self.assertEqual(result.json()["review"]["status"], "unjudgeable")
        self.assertNotEqual(
            client.get(base.replace(self.brand, "another-brand") + "/reviews").status_code, 200
        )

    def test_window_limit_is_thirty_one_complete_days(self):
        self.observation()
        row = self.request(start=self.end - timedelta(days=30))
        self.assertEqual(row["evidence_json"]["current"]["days_expected"], 31)
        self.assertEqual(row["evidence_json"]["previous"]["days_expected"], 31)
        with self.assertRaisesRegex(ValueError, "31 個已完整過去的日期"):
            self.request(start=self.end - timedelta(days=31))

    def test_reimport_timestamp_reuses_model_result_but_changed_amount_does_not(self):
        self.observation()
        self.reply()
        original = review_evidence.orders.review_evidence
        refreshed, amount = "2026-09-01T00:00:00Z", 10

        def commerce(*args, **kwargs):
            value = original(*args, **kwargs)
            value["order_summary"].update(latest_import_at=refreshed, order_net_amount=amount)
            return value

        with patch.object(review_evidence.orders, "review_evidence", side_effect=commerce):
            first = self.run_review(self.request())
            refreshed = "2026-09-02T00:00:00Z"
            same = self.request()
            self.run_review(same)
            self.assertEqual(same["id"], first["id"])
            self.assertEqual(len(self.fake.calls), 1)
            self.assertEqual(
                first["evidence_json"]["commerce"]["current"]["order_summary"]["latest_import_at"],
                "2026-09-01T00:00:00Z",
            )
            amount = 20
            changed = self.request()
            self.assertNotEqual(changed["id"], first["id"])

    def test_digest_preserves_period_and_actual_action_evidence_dates(self):
        evidence = self.request()["evidence_json"]
        evidence["previous_review"] = {
            "actions": [
                {
                    "verified_at": "2026-09-01T00:00:00Z",
                    "evidence_json": {
                        "observed_at": "2026-09-01T00:00:00Z",
                        "setting_matches": False,
                    },
                }
            ]
        }
        baseline = review_rounds.evidence_digest(evidence)
        for path, value in (
            (["window", "end"], "2026-01-01"),
            (["previous_review", "actions", 0, "verified_at"], "2026-09-02T00:00:00Z"),
            (
                ["previous_review", "actions", 0, "evidence_json", "observed_at"],
                "2026-09-02T00:00:00Z",
            ),
            (["previous_review", "actions", 0, "evidence_json", "setting_matches"], True),
        ):
            changed = deepcopy(evidence)
            target = changed
            for key in path[:-1]:
                target = target[key]
            target[path[-1]] = value
            self.assertNotEqual(review_rounds.evidence_digest(changed), baseline)

    def test_limitations_use_human_readable_conditions(self):
        row = self.request()
        limitations = row["evidence_json"]["limitations"]
        self.assertTrue(any("歷史投放條件未完整確認" in text for text in limitations))
        self.assertFalse(any("conditions_" in text for text in limitations))

    def test_linked_change_http_accepts_persisted_numeric_goal_and_rejects_real_change(self):
        from fastapi.testclient import TestClient

        from app.main import app

        self.conn.execute(
            "UPDATE ads_campaign SET success_metric='roas',success_target=2 WHERE id=%s",
            (self.campaign,),
        )
        self.conn.execute(
            "UPDATE ads_external_entity SET budget_amount=100,start_date=%s WHERE id=%s",
            (self.start, self.ad["id"]),
        )
        self.conn.commit()
        self.observation()
        self.reply()
        ready = self.run_review(self.request())
        self.assertEqual(ready["status"], "ready", ready["error"])
        self.assertEqual(ready["evidence_json"]["premise"]["goal"]["success_target"], 2.0)
        client = TestClient(app)
        base = f"/api/ads/brands/{self.brand}/campaigns/{self.campaign}"
        payload = {
            "operation_id": db.new_id("op"),
            "title": "保留圖片，修改文案",
            "month": self.end.strftime("%Y-%m"),
            "review_id": ready["id"],
            "recommendation_id": "recommendation-1",
            "items": [
                {
                    "kind": "copy",
                    "target_id": self.ad["id"],
                    "after": {"body": "人工調整內容"},
                    "reason": "檢驗本回假設",
                }
            ],
        }
        response = client.post(base + "/change-sets", json=payload)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["change_set"]["review_id"], ready["id"])
        self.conn.execute("UPDATE ads_campaign SET success_target=3 WHERE id=%s", (self.campaign,))
        self.conn.commit()
        payload["operation_id"] = db.new_id("op")
        changed = client.post(base + "/change-sets", json=payload)
        self.assertEqual(changed.status_code, 409)
        self.assertIn("目標已改變", changed.text)
