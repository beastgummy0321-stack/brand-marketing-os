"""Single-ad review uses real persistence/gateway and never calls an external provider."""

import json
import unittest
from copy import deepcopy
from datetime import date, timedelta
from unittest.mock import patch

from app.ads import (
    change_control,
    change_control_data,
    channels,
    external_repository,
    review_evidence,
    review_jobs,
    review_policy,
    review_rounds,
)
from app.brand_intelligence import repository as brands
from app.core import db, settings
from app.llm import providers


class _ZonedReader:
    """The fixture's bound account; `owner.account_zone` is its stored zone (None = no zone)."""

    def __init__(self, owner):
        self.owner = owner

    def accounts(self, conn, org, brand):
        return [{"account_id": "account", "timezone_name": self.owner.account_zone}]


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
        # F36-I06: evidence refuses a window with unsynced days (same coverage rule triage grades
        # with), so the fixture carries the observations coverage a clean sync would have
        # recorded -- broad enough for every window below; the gate tests narrow it themselves.
        # Inlined (not `self.set_coverage`): the monitor/retry tests borrow this setUp alone.
        external_repository.record_sync(
            self.conn,
            self.org,
            self.brand,
            self.campaign,
            section="observations",
            state={
                "last_success_at": db.now_utc().isoformat(),
                "coverage": {
                    "start": (self.end - timedelta(days=90)).isoformat(),
                    "end": self.end.isoformat(),
                },
            },
        )
        # F50 Contract K: the fixture account (`fixture`／`account`) is bound in the org's zone,
        # so its last complete day is the org's yesterday (`coverage.last_complete_day`).
        self.account_zone = str(settings.org_timezone(self.conn, org_id=self.org))
        real_reader = channels.external_reader
        patch.object(
            channels, "external_reader",
            side_effect=lambda platform: _ZonedReader(self) if platform == "fixture"
            else real_reader(platform),
        ).start()
        self.fake = providers.FakeProvider()
        self.fake.name = "anthropic"
        patch.object(review_rounds, "PROVIDER", self.fake).start()
        patch.object(providers, "resolve_model", return_value="claude-haiku-4-5").start()
        self.enqueue = patch.object(review_jobs, "enqueue").start()
        self.addCleanup(patch.stopall)
        self.conn.commit()

    def set_coverage(self, start, end):
        """The recorded read ranges become exactly `[start, end]` (F49 Contract V keeps a union
        in `record_sync`, so the earlier ranges are cleared first)."""
        self.conn.execute(
            "UPDATE ads_campaign SET context_json = context_json "
            "#- '{external_sync,observations,ranges}' WHERE id=%s",
            (self.campaign,),
        )
        external_repository.record_sync(
            self.conn,
            self.org,
            self.brand,
            self.campaign,
            section="observations",
            state={
                "last_success_at": db.now_utc().isoformat(),
                "coverage": {"start": start.isoformat(), "end": end.isoformat()},
            },
        )
        self.conn.commit()

    def observation(
        self,
        day=None,
        *,
        result_kind=None,
        result_count=None,
        result_action=None,
        result_attribution=None,
        **extra,
    ):
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
            result_kind=result_kind,
            result_count=result_count,
            result_action=result_action,
            result_attribution=result_attribution,
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
            db.now_utc() + timedelta(days=1),
        )
        self.assertEqual(deferred["status"], "deferred")
        self.enqueue.assert_not_called()
        self.assertEqual(self.fake.calls, [])
        self.assertNotEqual(
            change_control_data.campaign(self.conn, self.org, self.brand, self.campaign)["status"],
            "closed",
        )

    def test_deferring_the_round_resolves_the_ads_worse_row(self):
        """F49 Contract Q: the deferred round's `worse` row leaves the inbox with the decision."""
        from app.core import interrupts

        row = self.request()
        key = f"ads-triage:worse:{self.ad['id']}:2026-01-07"
        interrupts.enqueue(self.conn, org_id=self.org, brand_id=self.brand,
                           category="ads_triage_worse", dedupe_key=key, message="廣告變貴，待決定")
        self.conn.commit()
        review_rounds.decide(self.conn, self.org, self.brand, self.campaign, row["id"],
                             "deferred", "待補資料",
                             db.now_utc() + timedelta(days=1))
        self.assertNotIn(key, {
            r["dedupe_key"] for r in interrupts.list_open(
                self.conn, org_id=self.org, brand_id=self.brand, category="ads_triage_worse",
                archive_stale=False,
            )
        })

    def test_imported_campaign_target_set_on_target_page_counts_as_a_goal(self):
        # Drill 5: target set on the ads-centre target page, no wizard goal_text/objective.
        goal_missing = "請先補活動目標與目的，再重新建立檢討。"
        self.conn.execute(
            "UPDATE ads_campaign SET goal_text=NULL, objective=NULL WHERE id=%s", (self.campaign,)
        )
        self.assertIn(goal_missing, self.request()["evidence_json"]["waiting_reasons"])
        self.conn.execute(
            "UPDATE ads_campaign SET target_basis='own', target_cost=450 WHERE id=%s",
            (self.campaign,),
        )
        self.conn.execute("DELETE FROM ads_review_round WHERE campaign_id=%s", (self.campaign,))
        row = self.request()
        self.assertNotIn(goal_missing, row["evidence_json"]["waiting_reasons"])
        self.assertEqual(row["evidence_json"]["campaign"]["target"]["value"], 450)

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
        # F51: the round read's figures are not evidence; the next snapshot never carries them.
        self.assertNotIn("ad_spend", prior["evidence"]["current"])
        self.assertNotIn("ad_result_view", prior["evidence"]["current"])

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
        self.assertIsNone(series["metrics"]["roas_platform"])
        self.assertEqual(series["known_counts"]["purchases"], 1)
        self.assertEqual(evidence["current"]["missing_days"], 1)
        self.assertEqual(evidence["conditions"]["history"], "unknown")
        self.assertEqual(evidence["previous"]["row_count"], 0)
        # F51 Contract F: the ad's window spend is served by the round read, and two currencies
        # are never summed -- null, with the view naming the mixed currency.
        self.assertEqual(evidence["current"]["ad_spend"], {"value": None, "currency": None})
        self.assertEqual(evidence["current"]["ad_result_view"]["reason"], "mixed_currency")
        self.assertEqual(evidence["previous"]["ad_spend"], {"value": None, "currency": None})
        self.assertIsNone(evidence["previous"]["ad_result_view"])

    def test_round_read_serves_the_ads_window_spend_and_result_view(self):
        self.observation(result_kind="purchase", result_count=2, result_action="omni_purchase",
                         result_attribution="7d_click", purchases=2)
        self.observation(self.end - timedelta(days=1), spend=50, result_kind="purchase",
                         result_count=1, result_action="omni_purchase",
                         result_attribution="7d_click", purchases=1)
        current = self.request()["evidence_json"]["current"]
        self.assertEqual(current["ad_spend"], {"value": 150, "currency": "TWD"})
        self.assertEqual(
            (current["ad_result_view"]["result_count"], current["ad_result_view"]["reason"]),
            (3, None),
        )
        stored = self.conn.execute(
            "SELECT evidence_json FROM ads_review_round WHERE campaign_id=%s", (self.campaign,)
        ).fetchone()["evidence_json"]
        self.assertNotIn("ad_spend", stored["current"])  # the snapshot is never rewritten

    def test_f48_forbidden_list_is_scoped_to_the_campaigns_products(self):
        """F48 Contract G: the review evidence carries the one 「不能講」 list of the campaign's
        sell-ways (plus brand-level entries); a product outside the campaign never reaches it."""
        a = brands.create_product(self.conn, self.brand, name="晨光軟糖", actor="test")["id"]
        b = brands.create_product(self.conn, self.brand, name="午後花茶", actor="test")["id"]
        way = brands.save_sell_way(self.conn, self.brand, name="單盒", actor="test",
                                   product_id=a, economics={"selling_price": 399})["id"]
        brands.create_rule(self.conn, self.brand, actor="test", rule_type="forbidden_word",
                           content="頻尿", severity="hard")
        brands.create_claim(self.conn, self.brand, actor="test", claim_text="治療",
                            claim_type="forbidden", product_id=a)
        brands.create_claim(self.conn, self.brand, actor="test", claim_text="最便宜",
                            claim_type="forbidden", product_id=b)
        self.conn.commit()
        self.observation()
        self.assertEqual(self.request()["evidence_json"]["forbidden"], ["頻尿"])  # no product
        self.conn.execute(
            # Merged: the sync state lives beside `product_ids` in `context_json`.
            "UPDATE ads_campaign SET context_json=COALESCE(context_json,'{}'::jsonb)||%s "
            "WHERE id=%s",
            (db.jsonb({"product_ids": [way]}), self.campaign),
        )
        self.conn.commit()
        self.assertEqual(self.request()["evidence_json"]["forbidden"], ["治療", "頻尿"])

    def test_result_kind_and_cost_per_result_name_the_campaigns_own_result(self):
        # Previous-vs-current comparison for the campaign's own result reads the result view,
        # not the per-attribution_key series (F16-I03 repair).
        self.observation(result_kind="engagement", result_count=45, spend=90)
        self.observation(
            self.end - timedelta(days=1), result_kind="engagement", result_count=15, spend=30
        )
        row = self.request()
        view = row["evidence_json"]["current"]["result_views"][0]
        self.assertEqual(view["result_kind"], "engagement")
        self.assertEqual(view["result_count"], 60)
        self.assertEqual(view["cost_per_result"], 2.0)
        self.assertIsNone(view["reason"])
        series = row["evidence_json"]["current"]["series"][0]
        self.assertNotIn("result_kind", series)

    def test_unknown_result_count_any_day_keeps_cost_per_result_unknown(self):
        self.observation(result_kind="engagement", result_count=45)
        self.observation(self.end - timedelta(days=1), result_kind="engagement", result_count=None)
        row = self.request()
        view = row["evidence_json"]["current"]["result_views"][0]
        self.assertIsNone(view["result_count"])
        self.assertIsNone(view["cost_per_result"])
        self.assertEqual(view["reason"], "result_unknown_days")

    def test_engagement_result_view_survives_incidental_purchase_attribution_split(self):
        # Probe: an incidental purchase flips `attribution_key` (purchase-derived) on day 2,
        # tearing the per-key series into two — the result view must not be torn by it.
        day1, day2, day3 = self.start, self.start + timedelta(days=1), self.end
        common = {
            "result_kind": "engagement",
            "result_action": "post_engagement",
            "result_attribution": "7d_click+1d_view",
        }
        self.observation(day1, attribution_key="unavailable", result_count=40, spend=40, **common)
        self.observation(
            day2,
            attribution_key="omni_purchase",
            result_count=50,
            spend=50,
            purchases=1,
            revenue=30,
            **common,
        )
        self.observation(day3, attribution_key="unavailable", result_count=60, spend=60, **common)
        row = self.request()
        current = row["evidence_json"]["current"]
        self.assertEqual(len(current["series"]), 2)
        self.assertEqual(len(current["result_views"]), 1)
        view = current["result_views"][0]
        self.assertEqual(view["result_count"], 150)
        self.assertEqual(view["cost_per_result"], 1.0)
        self.assertIsNone(view["reason"])

    def test_mixed_result_action_types_never_summed_under_one_label(self):
        # Meta's `page_engagement` already contains `post_engagement`; summing them under one
        # `result_kind` label is not a real quantity, so the mismatch must fail closed.
        day1, day2, day3 = self.start, self.start + timedelta(days=1), self.end
        common = {"result_kind": "engagement", "result_attribution": "7d_click+1d_view"}
        self.observation(day1, result_action="post_engagement", result_count=40, spend=40, **common)
        self.observation(
            day2, result_action="post_engagement", result_count=50, spend=50, **common
        )
        self.observation(
            day3, result_action="page_engagement", result_count=60, spend=60, **common
        )
        row = self.request()
        view = row["evidence_json"]["current"]["result_views"][0]
        self.assertIsNone(view["result_count"])
        self.assertIsNone(view["cost_per_result"])
        self.assertEqual(view["reason"], "mixed_result_definition")

    def test_sales_result_view_equals_purchase_metrics_when_known(self):
        common = {"result_kind": "purchase", "result_action": "omni_purchase"}
        self.observation(
            result_attribution="7d_click+1d_view",
            result_count=3,
            spend=90,
            purchases=3,
            revenue=300,
            **common,
        )
        self.observation(
            self.end - timedelta(days=1),
            result_attribution="7d_click+1d_view",
            result_count=2,
            spend=30,
            purchases=2,
            revenue=200,
            **common,
        )
        row = self.request()
        current = row["evidence_json"]["current"]
        view = current["result_views"][0]
        series = current["series"][0]
        self.assertEqual(view["result_kind"], "purchase")
        self.assertEqual(view["result_count"], series["metrics"]["purchases"])
        self.assertEqual(view["cost_per_result"], series["metrics"]["cpa"])

    def test_invalid_model_target_refs_numbers_and_copy_rejected_without_resend(self):
        self.observation()
        self.reply(target_id="another-ad")
        row = self.request()
        rejected = self.run_review(row)
        # F30 Contract A: a rejected text leaves the round usable on its evidence alone.
        self.assertEqual(rejected["status"], "ready")
        self.assertIsNone(rejected["error"])
        self.assertEqual(rejected["result_json"]["recommendations"], [])
        self.assertTrue(rejected["result_json"]["rejected"]["reason"])
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
        for hedge in ("不足以判斷", "無法判斷", "無法判定", "未能確認"):
            self.assertFalse(review_policy.unsupported_claim(f"資料{hedge}設定造成成效變化"))
        self.assertTrue(review_policy.unsupported_claim("此文案造成轉換下降"))
        self.assertTrue(review_policy.unsupported_claim("不足以判斷 3 天內造成的變化"))

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
        self.account_zone = None  # the bound account has no stored zone
        # F50 Contract K: an unknown zone fails closed -- the org's yesterday is not yet proven
        # complete for the account (`coverage.account_last_complete_day`).
        with self.assertRaisesRegex(ValueError, "尚未完整結束"):
            self.request()
        unknown = self.request(end=self.end - timedelta(days=1))
        self.assertIsNone(unknown["evidence_json"]["window"]["timezone"])
        with patch.object(
            review_evidence.external_sync,
            "account_reader",
            return_value=(None, {"timezone_name": "UTC", "access_token": "private-not-evidence"}),
        ):
            known = self.request(end=self.end - timedelta(days=2))
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

    def test_api_defer_takes_revisit_on_as_an_org_calendar_date(self):
        """F50 Contract K: today is a 400 with the deferral sentence; tomorrow is stored as
        00:00 of that day in the org's zone."""
        from fastapi.testclient import TestClient

        from app.main import app

        self.observation()
        self.reply()
        ready = self.run_review(self.request())
        self.conn.commit()
        client = TestClient(app)
        url = (f"/api/ads/brands/{self.brand}/campaigns/{self.campaign}/reviews/"
               f"{ready['id']}/decision")
        today = settings.today_for_org(self.conn, org_id=self.org)
        refused = client.post(url, json={
            "decision": "deferred", "reason": "延後", "revisit_on": today.isoformat(),
        })
        self.assertEqual(refused.status_code, 400, refused.text)
        self.assertEqual(refused.json()["error"]["message"],
                         change_control_data.DEFERRAL_DAY_REFUSAL)
        tomorrow = today + timedelta(days=1)
        # F50-I12: the browser-instant input `revisit_at` is gone.
        removed = client.post(url, json={
            "decision": "deferred", "reason": "延後",
            "revisit_at": (db.now_utc() + timedelta(days=3)).isoformat(),
        })
        self.assertEqual(removed.status_code, 422, removed.text)
        accepted = client.post(url, json={
            "decision": "deferred", "reason": "延後", "revisit_on": tomorrow.isoformat(),
        })
        self.assertEqual(accepted.status_code, 200, accepted.text)
        stored = self.conn.execute(
            "SELECT status,revisit_at FROM ads_review_round WHERE id=%s", (ready["id"],)
        ).fetchone()
        self.assertEqual(stored["status"], "deferred")
        self.assertEqual(stored["revisit_at"],
                         settings.org_day_start(self.conn, org_id=self.org, day=tomorrow))

    def test_unsynced_day_inside_window_or_prior_period_is_refused(self):
        prior_start = self.start - timedelta(days=3)
        # A row proves its own day (F49 Contract V): keep it outside the window under test.
        self.observation(prior_start - timedelta(days=1))
        # Last day of the window never synced: refused, and the refusal names that day.
        self.set_coverage(prior_start, self.end - timedelta(days=1))
        with self.assertRaisesRegex(
            ValueError,
            "觀察期間（含前期）有 1 天還沒讀到平台資料："
            + self.end.strftime("%m/%d")
            + "；先重新讀取平台，或改選期間。",
        ):
            self.request()
        # A gap only in the equal-length prior period is still a gap the comparison rests on.
        self.set_coverage(self.start, self.end)
        with self.assertRaisesRegex(ValueError, "有 3 天還沒讀到平台資料"):
            self.request()
        # More than five missing days: the first five are listed, then an ellipsis.
        self.set_coverage(prior_start - timedelta(days=60), prior_start - timedelta(days=30))
        listed = "、".join((prior_start + timedelta(days=i)).strftime("%m/%d") for i in range(5))
        with self.assertRaisesRegex(ValueError, f"有 6 天還沒讀到平台資料：{listed}…；"):
            self.request()
        # Refused like the date guards: nothing was recorded.
        workspace = review_rounds.workspace(self.conn, self.org, self.brand, self.campaign)
        self.assertEqual(workspace["reviews"], [])

    def test_never_synced_campaign_is_refused_not_passed(self):
        # F37 Contract Q (ruling 4): no recorded read is not "nothing missing" (F36 as-built gap).
        # F49 Contract V: nothing read = no recorded range and no row at all.
        self.conn.execute(
            "UPDATE ads_campaign SET context_json = context_json - 'external_sync'"
            " WHERE org_id = %s AND brand_id = %s AND id = %s",
            (self.org, self.brand, self.campaign),
        )
        self.conn.commit()
        with self.assertRaisesRegex(ValueError, "^這個活動還沒讀過平台資料；先重新讀取平台。$"):
            self.request()
        workspace = review_rounds.workspace(self.conn, self.org, self.brand, self.campaign)
        self.assertEqual(workspace["reviews"], [])

    def test_gap_outside_the_window_passes_and_window_reports_no_missing_days(self):
        self.observation()
        prior_start = self.start - timedelta(days=3)
        # Coverage exactly the window plus its prior period; everything before it never synced.
        self.set_coverage(prior_start, self.end)
        row = self.request()
        self.assertEqual(row["evidence_json"]["window"]["missing_days"], [])
        self.assertEqual(row["evidence_json"]["current"]["days_present"], 1)

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

    def test_model_projection_preserves_partial_sample_and_stored_evidence(self):
        evidence = self.request()["evidence_json"]
        decision = {
            "count": None, "known_count": 3, "result_kind": "lead",
            "result_label": "名單", "state": "incomplete", "reasons": ["missing_days"],
            "sample": {"count": None, "result_kind": "lead", "days_known": 2, "days": 7},
            "evidence_refs": ["observed-1"], "evidence_ref_count": 1,
            "scope": {"start": "2026-08-01"},
        }
        evidence["current"]["decision_evidence"] = decision
        stored = deepcopy(evidence)
        projected = json.loads(review_rounds.model_input(evidence))["current"]["decision_evidence"]
        self.assertEqual(evidence, stored)
        self.assertEqual(projected["known_count"], 3)
        self.assertIsNone(projected["count"])
        self.assertEqual(projected["state"], "incomplete")
        self.assertEqual(projected["sample"], {"days_known": 2, "days": 7})
        self.assertEqual(projected["observation_refs_location"], "stored_snapshot")
        self.assertEqual(projected["evidence_ref_count"], 1)
        original_input = review_rounds.model_input(evidence)
        evidence["current"]["ad_spend"] = {"value": 100, "currency": "TWD"}
        evidence["current"]["ad_result_view"] = {"result_count": 3}
        self.assertEqual(review_rounds.model_input(evidence), original_input)
        decision["scope"] = {"start": evidence["window"]["start"],
                             "end": evidence["window"]["end"], "days": 7}
        projected_input = json.loads(review_rounds.model_input(evidence))
        self.assertNotIn("scope", projected_input["current"]["decision_evidence"])
        self.assertEqual(str(projected_input["window"]["end"]), str(evidence["window"]["end"]))

    def test_limitations_use_human_readable_conditions(self):
        row = self.request()
        limitations = row["evidence_json"]["limitations"]
        self.assertTrue(any("歷史投放條件未完整確認" in text for text in limitations))
        self.assertFalse(any("conditions_" in text for text in limitations))

    def test_linked_change_http_accepts_a_cap_edit_and_rejects_a_real_goal_change(self):
        from fastapi.testclient import TestClient

        from app.main import app

        self.conn.execute(
            "UPDATE ads_campaign SET target_basis='own',target_cost=2 WHERE id=%s",
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
        # F28-I01: the cap is not a platform setting, so it is never part of the premise.
        self.assertNotIn("target_cost", ready["evidence_json"]["premise"]["goal"])
        self.assertEqual(
            set(ready["evidence_json"]["premise"]["goal"]), {"goal_text", "objective"},
        )
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
        self.conn.execute("UPDATE ads_campaign SET target_cost=3 WHERE id=%s", (self.campaign,))
        self.conn.execute(
            "UPDATE ads_campaign SET goal_text='改過的目標' WHERE id=%s", (self.campaign,),
        )
        self.conn.commit()
        payload["operation_id"] = db.new_id("op")
        changed = client.post(base + "/change-sets", json=payload)
        self.assertEqual(changed.status_code, 409)
        self.assertIn("目標已改變", changed.text)


def _daily_row(day, attribution_key, spend, *, result_kind=None, result_count=None,
                result_action=None, result_attribution=None, metric_scope="campaign",
                currency="TWD", source="graph", result_count_availability=None):
    """The real `ads_external_daily` row shape (F16-I06), built without any DB round trip --
    `aggregate()` is a pure function over rows, exactly like this. `result_count_availability`
    (F18-I01) lets a case override the default `available`/`unknown` inference to build a
    `"derived_zero"` row, exactly as `app/ads/tracked_zero.py::apply()` writes one."""
    metrics = {"spend": spend, "impressions": None, "clicks": None, "purchases": None,
               "revenue": None}
    return {
        "day": day, "metric_scope": metric_scope, "attribution_key": attribution_key,
        "currency": currency, "source": source, **metrics,
        "availability": {
            **{k: ("available" if v is not None else "unavailable") for k, v in metrics.items()},
            "result_count": result_count_availability
            or ("available" if result_count is not None else "unknown"),
        },
        "result_kind": result_kind, "result_count": result_count,
        "result_action": result_action, "result_attribution": result_attribution,
    }


class AggregateExcludesMonthlyBudgetRowsTest(unittest.TestCase):
    """F16-I06 cause #1: a monthly-budget source row shares entity/day/metric_scope/currency
    with an ordinary observation row -- only `attribution_key` tells them apart. Neither the
    per-`attribution_key` series nor the result view may let it double-count spend or force the
    result unknown."""

    def test_monthly_row_never_pollutes_series_or_result_view(self):
        day = date(2026, 9, 19)
        observation_row = _daily_row(
            day, "7d_click+1d_view:omni_purchase", 1747,
            result_kind="purchase", result_count=5, result_action="omni_purchase",
            result_attribution="7d_click+1d_view",
        )
        monthly_row = _daily_row(day, external_repository.MONTHLY_BUDGET_ATTRIBUTION_KEY, 1900)
        aggregated = review_evidence.aggregate([observation_row, monthly_row], day, day)
        # Only the observation row's own attribution_key series survives.
        self.assertEqual(len(aggregated["series"]), 1)
        self.assertEqual(aggregated["series"][0]["metrics"]["spend"], 1747)
        self.assertEqual(len(aggregated["result_views"]), 1)
        view = aggregated["result_views"][0]
        self.assertIsNone(view["reason"])
        self.assertEqual(view["cost_per_result"], 1747 / 5)


class DerivedZeroResultViewTest(unittest.TestCase):
    """F18-I01: `availability.result_count=="derived_zero"` counts as known on the same footing
    as a platform-reported `"available"` row, and is reported separately via `derived_zero_days`
    so a reader can tell "zero, proven absent" apart from "zero, actually reported"."""

    def test_derived_zero_counts_as_known_and_is_reported_separately(self):
        day1, day2 = date(2026, 9, 19), date(2026, 9, 20)
        reported = _daily_row(
            day1, "7d_click+1d_view:omni_purchase", 100,
            result_kind="purchase", result_count=5, result_action="omni_purchase",
            result_attribution="7d_click+1d_view",
        )
        derived = _daily_row(
            day2, "7d_click+1d_view:unavailable", 50,
            result_kind="purchase", result_count=0, result_action="omni_purchase",
            result_attribution="7d_click+1d_view", result_count_availability="derived_zero",
        )
        aggregated = review_evidence.aggregate([reported, derived], day1, day2)
        view = aggregated["result_views"][0]
        self.assertIsNone(view["reason"])
        self.assertEqual(view["result_count"], 5)
        self.assertEqual(view["cost_per_result"], (100 + 50) / 5)
        self.assertEqual(view["days_known"], 2)
        self.assertEqual(view["derived_zero_days"], 1)

    def test_platform_reported_zero_is_not_counted_as_derived(self):
        day = date(2026, 9, 19)
        row = _daily_row(
            day, "7d_click+1d_view:omni_purchase", 100,
            result_kind="purchase", result_count=0, result_action="omni_purchase",
            result_attribution="7d_click+1d_view",
        )
        aggregated = review_evidence.aggregate([row], day, day)
        view = aggregated["result_views"][0]
        self.assertEqual(view["days_known"], 1)
        self.assertEqual(view["derived_zero_days"], 0)
