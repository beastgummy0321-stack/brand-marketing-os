"""Single-call suggestions, conserved originals, budgets and confirmation freshness."""

import json
import unittest
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch

import psycopg

from app import background, workbench
from app.ads import asset_suggestion_policy as policy
from app.ads import asset_suggestions as suggestions
from app.ads import external_repository as external
from app.ads import user_assets_repository as assets
from app.brand_intelligence import repository as brands
from app.core import db, settings
from app.llm import providers


class SuggestionsTest(unittest.TestCase):
    def setUp(self):
        self.conn = db.current()
        self.org = db.DEV_ORG_ID
        self.brand = brands.create_brand(
            self.conn, org_id=self.org, name="品牌", actor="test", client_name=None
        )["id"]
        self.campaign = external.create_imported_campaign(
            self.conn, self.org, self.brand, name="native"
        )["id"]
        self.conn.execute(
            "UPDATE ads_campaign SET goal_text='認識品牌',objective='awareness' WHERE id=%s",
            (self.campaign,),
        )
        self.conn.commit()
        self.fake = providers.FakeProvider()
        self.fake.name = "anthropic"
        patch.object(suggestions, "PROVIDER", self.fake).start()
        patch.object(suggestions, "enqueue").start()
        patch.object(providers, "resolve_model", return_value="claude-haiku-4-5").start()
        self.addCleanup(patch.stopall)

    def placement(self, copy=None, status="ready"):
        asset_id = db.new_id("aua")
        self.conn.execute(
            "INSERT INTO ads_user_asset(id,org_id,brand_id,sha256,storage_key,filename,"
            "mime_type,byte_size,status) VALUES(%s,%s,%s,%s,%s,'original.png','image/png',1,%s)",
            (
                asset_id,
                self.org,
                self.brand,
                asset_id,
                self.org + "/brands/" + self.brand + "/" + asset_id,
                status,
            ),
        )
        row = assets.attach(
            self.conn,
            self.org,
            self.brand,
            self.campaign,
            asset_id,
            copy or {"headline": " 原標題 ", "body": " 原文\n照留 ", "description": "原說明"},
            "test",
        )
        self.conn.commit()
        return row

    def request(self, rows, key="one", summary=""):
        return suggestions.request(
            self.conn,
            self.org,
            self.brand,
            self.campaign,
            [{"id": r["id"], "revision": r["revision"]} for r in rows],
            key,
            summary,
        )

    def reply(self, rows, copy=None):
        data = {
            "items": [
                {
                    "id": r["id"],
                    "copy_fields": copy
                    or {"headline": "了解更多", "body": "查看商品資訊", "description": "立即查看"},
                    "purpose": "認識品牌",
                }
                for r in rows
            ]
        }
        self.fake.response = providers.ProviderResponse(
            output_text=json.dumps(data, ensure_ascii=False),
            structured=data,
            usage=providers.Usage(input_tokens=100, output_tokens=100),
            stop_reason="end_turn",
        )

    def run_batch(self, batch):
        suggestions.run(self.org, self.brand, self.campaign, batch["id"])
        return suggestions.get_batch(self.conn, self.org, self.brand, self.campaign, batch["id"])

    def test_original_preserved_unknown_budget_allowed_and_success_reused(self):
        # F34 Contract S: a `food_tw` brand gets the 食安法 note in `notes` only (ruling 2B).
        brands.set_regulatory_regime(self.conn, self.brand, "food_tw", actor="test")
        row = self.placement(
            {
                "headline": " 原標題 ",
                "body": " 原文\n照留，十分鐘內治療疲勞 ",
                "description": "原說明",
            }
        )
        self.reply([row])
        batch = self.request([row])
        done = self.run_batch(batch)
        self.assertEqual(done["status"], "succeeded", done.get("error"))
        result = done["results"][0]
        self.assertEqual(result["original_copy"], row["copy_fields"])
        self.assertEqual(result["suggested_copy"], {})
        self.assertEqual(result["status"], "awaiting_confirmation")
        self.assertEqual(result["pending_reasons"], [])
        self.assertTrue(result["notes"])
        statutory = [n for n in result["notes"] if n.startswith("食安法提醒：")]
        self.assertEqual(len(statutory), 1)
        self.assertIn("治療", statutory[0])
        self.assertIn("食安法第 28 條", statutory[0])
        self.assertIsNone(
            policy.statutory_note(self.conn, self.org, self.brand, {"body": "了解更多"})
        )
        same = self.request([row], "new-button")
        self.assertEqual(same["id"], batch["id"])
        confirmed = suggestions.confirm(
            self.conn, self.org, self.brand, self.campaign, row["id"], 1, batch["id"], "human"
        )
        self.assertEqual(confirmed["status"], "manual_ready")
        self.assertEqual(confirmed["copy_fields"], row["copy_fields"])
        self.assertEqual(len(self.fake.calls), 1)
        self.assertEqual(self.fake.calls[0]["max_tokens"], 4096)
        self.assertEqual(self.fake.calls[0]["timeout_s"], 120)

    def test_multiple_confirmations_and_stale_revision(self):
        rows = [self.placement(), self.placement()]
        self.reply(rows)
        batch = self.request(rows)
        self.run_batch(batch)
        for row in rows:
            out = suggestions.confirm(
                self.conn, self.org, self.brand, self.campaign, row["id"], 1, batch["id"], "human"
            )
            self.assertEqual(out["status"], "manual_ready")
            self.conn.commit()
        changed = assets.revise(
            self.conn,
            self.org,
            self.brand,
            self.campaign,
            rows[0]["id"],
            1,
            {"purpose": "新用途"},
            "test",
        )
        self.conn.commit()
        self.assertEqual(changed["revision"], 2)
        with self.assertRaises(ValueError):
            suggestions.confirm(
                self.conn,
                self.org,
                self.brand,
                self.campaign,
                rows[0]["id"],
                1,
                batch["id"],
                "human",
            )
        self.assertEqual(
            assets.placement(self.conn, self.org, self.brand, self.campaign, rows[0]["id"], 1)[
                "confirmed_by"
            ],
            "human",
        )

    def test_media_pending_and_unverified_original_are_not_confirmed(self):
        row = self.placement(
            {"headline": "免費試飲", "body": "原文", "description": "原說明"}, status="pending"
        )
        self.reply([row])
        batch = self.request([row])
        done = self.run_batch(batch)
        self.assertTrue(done["results"][0]["pending_reasons"])
        confirmed = suggestions.confirm(
            self.conn, self.org, self.brand, self.campaign, row["id"], 1, batch["id"], "human"
        )
        self.assertEqual(confirmed["status"], "pending")
        self.assertIsNone(confirmed["confirmed_at"])
        self.assertEqual(confirmed["copy_fields"]["headline"], "免費試飲")
        # F44 Contract C: the refusal carries its details beside the sentences, same order.
        details = confirmed["pending_details"]
        self.assertEqual(details, done["results"][0]["pending_details"])
        self.assertEqual(
            details,
            [
                {
                    "kind": "copy",
                    "text": "文案寫了「試飲」，品牌資料裡沒有登記這個優惠或背書。",
                    "terms": ["試飲"],
                },
                {"kind": "wait", "text": "原檔預覽尚未完成，請先完成媒體處理。", "terms": []},
            ],
        )
        self.assertEqual(confirmed["pending_reasons"], [d["text"] for d in details])

    def test_generated_unsupported_facts_rejected(self):
        row = self.placement({"headline": "原標題"})
        self.reply([row], {"body": "有機認證效果保證", "description": "免費試飲"})
        done = self.run_batch(self.request([row]))
        self.assertEqual(done["status"], "succeeded")
        self.assertEqual(done["results"][0]["suggested_copy"], {})
        self.assertTrue(done["results"][0]["pending_reasons"])

    def test_generated_copy_may_cite_the_sell_ways_own_claims(self):
        """F44-I03: the approved claims of the campaign's sell-way are sources (and knowledge
        ids) of the batch; another product's claims are not."""
        product = brands.create_product(self.conn, self.brand, name="晨光軟糖", actor="test")["id"]
        claim = brands.create_claim(
            self.conn, self.brand, actor="test", claim_text="晨光軟糖一天兩顆",
            claim_type="approved", product_id=product,
        )
        other = brands.create_product(self.conn, self.brand, name="別的商品", actor="test")["id"]
        brands.create_claim(
            self.conn, self.brand, actor="test", claim_text="別的商品的說法",
            claim_type="approved", product_id=other,
        )
        box = brands.save_sell_way(
            self.conn, self.brand, name="單盒", actor="test", product_id=product,
            economics={"selling_price": 500},
        )["id"]
        way = brands.save_sell_way(
            self.conn, self.brand, name="三盒組", actor="test",
            components=[{"sell_way_id": box, "qty": 3}],
            economics={
                "selling_price": 999, "list_price": 1500, "unit_variable_cost": 300,
                "shipping_cost": 60,
            },
        )["id"]
        self.conn.execute(
            "UPDATE ads_campaign SET context_json=%s WHERE id=%s",
            (db.jsonb({"product_ids": [way]}), self.campaign),
        )
        self.conn.commit()
        row = self.placement({"headline": "原標題"})
        answer = {"body": "晨光軟糖一天兩顆", "description": "了解更多"}
        self.reply([row], answer)
        batch = self.request([row])
        data = batch["input_json"]
        self.assertEqual(data["campaign"]["sell_way"], way)
        self.assertIn(claim["id"], data["knowledge_ids"])
        self.assertIn({"id": claim["id"], "text": "晨光軟糖一天兩顆"}, data["sources"])
        self.assertNotIn("別的商品的說法", [s["text"] for s in data["sources"]])
        done = self.run_batch(batch)
        self.assertEqual(done["status"], "succeeded", done.get("error"))
        result = done["results"][0]
        self.assertEqual(result["suggested_copy"], answer)
        self.assertEqual((result["pending_reasons"], result["pending_details"]), ([], []))

    def test_missing_and_wrong_ids_are_not_applied_or_retried(self):
        row = self.placement()
        self.reply([row])
        self.fake.response.structured["items"][0]["id"] = "other-brand"
        self.fake.response.output_text = json.dumps(self.fake.response.structured)
        batch = self.request([row])
        done = self.run_batch(batch)
        self.assertEqual(done["status"], "failed")
        self.assertEqual(self.request([row], "different-key")["id"], batch["id"])
        self.run_batch(batch)
        self.assertEqual(len(self.fake.calls), 1)
        self.assertIsNone(
            assets.placement(self.conn, self.org, self.brand, self.campaign, row["id"])[
                "confirmed_at"
            ]
        )

    def test_timeout_preserves_reservation_and_no_resend(self):
        row = self.placement()
        self.fake.exception = providers.ProviderTimeoutError("timeout")
        batch = self.request([row])
        self.run_batch(batch)
        self.run_batch(batch)
        self.assertEqual(len(self.fake.calls), 1)
        reserve = self.conn.execute(
            "SELECT * FROM ads_asset_suggestion_reservation WHERE batch_id=%s", (batch["id"],)
        ).fetchone()
        self.assertEqual(reserve["settlement"], "held")
        self.assertAlmostEqual(float(reserve["amount"]), 0.22048)

    def test_failed_known_cost_is_supplement_not_lost(self):
        row = self.placement()
        self.reply([row])
        self.fake.response.stop_reason = "max_tokens"
        batch = self.request([row])
        self.run_batch(batch)
        reserve = self.conn.execute(
            "SELECT * FROM ads_asset_suggestion_reservation WHERE batch_id=%s", (batch["id"],)
        ).fetchone()
        self.assertEqual(reserve["settlement"], "settled")
        self.assertGreater(reserve["known_failed_cost"], 0)

    def test_budget_and_input_reject_before_call(self):
        rows = [self.placement() for _ in range(11)]
        with self.assertRaises(ValueError):
            self.request(rows)
        with (
            patch.object(providers, "resolve_model", return_value="claude-sonnet-5"),
            self.assertRaises(ValueError),
        ):
            self.request(rows[:1])
        with (
            patch.object(settings, "get_ai_monthly_cost_limit", return_value=0.01),
            self.assertRaises(ValueError),
        ):
            self.request(rows[:1])
        self.conn.rollback()
        self.assertEqual(len(self.fake.calls), 0)
        self.assertEqual(
            len(assets.list_placements(self.conn, self.org, self.brand, self.campaign)), 11
        )

    def test_parallel_same_input_has_one_batch_and_reservation(self):
        row = self.placement()

        def request(key):
            with db.connection() as conn:
                return suggestions.request(
                    conn,
                    self.org,
                    self.brand,
                    self.campaign,
                    [{"id": row["id"], "revision": 1}],
                    key,
                )

        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(request, ["a", "b"]))
        self.assertEqual(results[0]["id"], results[1]["id"])
        self.assertEqual(
            self.conn.execute(
                "SELECT COUNT(*) n FROM ads_asset_suggestion_reservation WHERE brand_id=%s",
                (self.brand,),
            ).fetchone()["n"],
            1,
        )

    def test_claim_facade_rejects_other_org_and_product(self):
        with self.assertRaises(ValueError):
            workbench.validate_claims(self.conn, "other", self.brand, None, {"body": "x"})
        with self.assertRaises(ValueError):
            workbench.validate_claims(self.conn, self.org, self.brand, "other", {})
        self.assertEqual(
            workbench.validate_claims(self.conn, self.org, self.brand, None, {"body": "免費試飲"})[
                "unsupported_promises"
            ],
            ["試飲"],
        )

    def test_batch_fk_rejects_other_campaign(self):
        row = self.placement()
        batch = self.request([row])
        other = external.create_imported_campaign(self.conn, self.org, self.brand, name="other")[
            "id"
        ]
        self.conn.commit()
        with self.assertRaises(psycopg.errors.ForeignKeyViolation):
            self.conn.execute(
                "INSERT INTO ads_asset_placement(id,revision,org_id,brand_id,campaign_id,"
                "asset_id,suggestion_batch_id) VALUES('cross',1,%s,%s,%s,%s,%s)",
                (self.org, self.brand, other, row["asset_id"], batch["id"]),
            )
        self.conn.rollback()

    def test_brand_cleanup_removes_placement_before_batch(self):
        from app.core import cleanup

        row = self.placement()
        self.reply([row])
        batch = self.request([row])
        self.run_batch(batch)
        suggestions.confirm(
            self.conn, self.org, self.brand, self.campaign, row["id"], 1, batch["id"], "human"
        )
        self.conn.commit()
        cleanup.delete_all(self.conn, self.brand)
        self.conn.commit()
        for table in (
            "ads_asset_placement",
            "ads_asset_suggestion_batch",
            "ads_asset_suggestion_reservation",
        ):
            self.assertEqual(
                self.conn.execute(
                    "SELECT COUNT(*) n FROM " + table + " WHERE brand_id=%s", (self.brand,)
                ).fetchone()["n"],
                0,
            )

    def test_provider_return_length_and_full_input_limits(self):
        row = self.placement()
        self.reply([row])
        self.fake.response.output_text = "x" * (policy.OUTPUT_CHARS + 1)
        done = self.run_batch(self.request([row]))
        self.assertEqual(done["status"], "failed")
        self.assertIn("16,384", done["error"])
        other = self.placement({"body": "原" * 12000})
        with self.assertRaises(ValueError):
            self.request([other], "large")
        self.assertEqual(len(self.fake.calls), 1)

    def test_fact_version_and_media_change_conflict(self):
        row = self.placement()
        self.reply([row])
        batch = self.request([row])
        self.run_batch(batch)
        self.conn.execute(
            "UPDATE ads_user_asset SET status='error' WHERE id=%s", (row["asset_id"],)
        )
        self.conn.commit()
        with self.assertRaises(ValueError):
            suggestions.confirm(
                self.conn, self.org, self.brand, self.campaign, row["id"], 1, batch["id"], "human"
            )
        self.assertIsNone(
            assets.placement(self.conn, self.org, self.brand, self.campaign, row["id"])[
                "confirmed_at"
            ]
        )

    def test_parallel_budget_reservations_never_overbook(self):
        rows = [self.placement(), self.placement()]

        def reserve(row):
            with db.connection() as conn:
                try:
                    suggestions.request(
                        conn,
                        self.org,
                        self.brand,
                        self.campaign,
                        [{"id": row["id"], "revision": 1}],
                        row["id"],
                    )
                    return True
                except ValueError:
                    return False

        held = self.conn.execute(
            "SELECT COALESCE(SUM(amount),0) n FROM ads_asset_suggestion_reservation WHERE "
            "org_id=%s AND settlement='held'",
            (self.org,),
        ).fetchone()["n"]
        failed = self.conn.execute(
            "SELECT COALESCE(SUM(known_failed_cost),0) n FROM "
            "ads_asset_suggestion_reservation WHERE org_id=%s",
            (self.org,),
        ).fetchone()["n"]
        spent = settings.org_ai_spent_this_month(
            self.conn, org_id=self.org, since=db.now_utc().strftime("%Y-%m-01T00:00:00")
        )
        with (
            patch.object(
                settings,
                "get_ai_monthly_cost_limit",
                return_value=spent + float(held) + float(failed) + 0.3,
            ),
            ThreadPoolExecutor(max_workers=2) as pool,
        ):
            results = list(pool.map(reserve, rows))
        self.assertEqual(sorted(results), [False, True])

    def test_api_reports_remaining_and_confirmation(self):
        from fastapi.testclient import TestClient

        from app.main import app

        client = TestClient(app)
        row = self.placement()
        self.placement()
        self.reply([row])
        prefix = f"/api/ads/brands/{self.brand}/campaigns/{self.campaign}"
        response = client.post(
            prefix + "/asset-suggestions",
            json={"placements": [{"id": row["id"], "revision": 1}], "idempotency_key": "api"},
        )
        self.assertEqual(response.status_code, 200, response.text)
        batch = response.json()["batch"]
        self.assertEqual(batch["remaining_count"], 1)
        self.run_batch(batch)
        reply = client.post(
            prefix + f"/placements/{row['id']}/confirm",
            json={"expected_revision": 1, "batch_id": batch["id"]},
        )
        self.assertEqual(reply.status_code, 200, reply.text)
        self.assertEqual(reply.json()["placement"]["status"], "manual_ready")

    def test_abandoned_running_becomes_unknown_and_settles_its_reservation(self):
        # Slots #7: a batch marked `unknown` releases its hold (a stuck batch never keeps eating
        # the org's AI budget); nothing is sent again.
        row = self.placement()
        batch = self.request([row])
        self.conn.execute(
            "UPDATE ads_asset_suggestion_batch SET status='running',"
            "updated_at=now()-interval '11 minutes' WHERE id=%s",
            (batch["id"],),
        )
        self.conn.commit()
        suggestions.dispatch_pending(0)
        result = suggestions.get_batch(self.conn, self.org, self.brand, self.campaign, batch["id"])
        self.assertEqual(result["status"], "unknown")
        self.assertEqual(result["error"], suggestions.UNKNOWN_ERROR)
        reserve = self.conn.execute(
            "SELECT settlement,known_failed_cost FROM ads_asset_suggestion_reservation "
            "WHERE batch_id=%s",
            (batch["id"],),
        ).fetchone()
        self.assertEqual((reserve["settlement"], float(reserve["known_failed_cost"])),
                         ("settled", 0.0))
        self.assertEqual(len(self.fake.calls), 0)

    def test_a_provider_refusal_reaches_the_batch_with_its_own_words_and_kind(self):
        # Slots #7 / F50 Contract J: the call's own error and `error_code` are the batch's, never
        # a generic sentence; the job fails with that kind.
        row = self.placement()
        self.fake.exception = providers.ProviderError("模型婉拒本次請求：內容不適合")
        batch = self.request([row])
        result = suggestions.run(self.org, self.brand, self.campaign, batch["id"])
        self.assertEqual(result, background.Failed("refused", "模型婉拒本次請求：內容不適合"))
        done = suggestions.get_batch(self.conn, self.org, self.brand, self.campaign, batch["id"])
        self.assertEqual((done["status"], done["error"], done["error_code"]),
                         ("failed", "模型婉拒本次請求：內容不適合", "refused"))
        # A timed-out call says so, with its kind.
        other = self.placement()
        self.fake.exception = providers.ProviderTimeoutError("AI 服務逾時未回應")
        timed = self.request([other], "timeout")
        result = suggestions.run(self.org, self.brand, self.campaign, timed["id"])
        assert isinstance(result, background.Failed)
        self.assertEqual(result.code, "timeout")
        done = suggestions.get_batch(self.conn, self.org, self.brand, self.campaign, timed["id"])
        self.assertEqual((done["error"], done["error_code"]), ("AI 服務逾時未回應", "timeout"))

    def test_a_refused_reply_and_a_clean_batch_report_their_outcome(self):
        row = self.placement()
        self.reply([row])
        self.fake.response.output_text = "x" * (policy.OUTPUT_CHARS + 1)
        batch = self.request([row])
        result = suggestions.run(self.org, self.brand, self.campaign, batch["id"])
        assert isinstance(result, background.Failed)
        self.assertEqual(result.code, suggestions.REPLY_INVALID)
        done = suggestions.get_batch(self.conn, self.org, self.brand, self.campaign, batch["id"])
        # The program's own refusal stays the batch's sentence; the call row says why.
        self.assertIn("16,384", done["error"])
        self.assertEqual(done["error_code"], "program_refused")
        ok = self.placement()
        self.reply([ok])
        clean = self.request([ok], "clean")
        self.assertIsNone(suggestions.run(self.org, self.brand, self.campaign, clean["id"]))
        done = suggestions.get_batch(self.conn, self.org, self.brand, self.campaign, clean["id"])
        self.assertEqual((done["status"], done["error_code"]), ("succeeded", None))

    def test_text_only_provider_reply_is_parsed(self):
        row = self.placement()
        self.reply([row])
        self.fake.response.structured = None
        done = self.run_batch(self.request([row]))
        self.assertEqual(done["status"], "succeeded", done["error"])
        self.assertEqual(done["results"][0]["id"], row["id"])

    def test_manual_confirmation_requires_no_model_batch(self):
        row = self.placement()
        revised = assets.revise(
            self.conn,
            self.org,
            self.brand,
            self.campaign,
            row["id"],
            1,
            {"purpose": "品牌介紹"},
            "test",
        )
        self.conn.commit()
        result = suggestions.confirm(
            self.conn,
            self.org,
            self.brand,
            self.campaign,
            row["id"],
            revised["revision"],
            None,
            "human",
        )
        self.assertEqual(result["status"], "manual_ready")
        self.assertIsNone(result["suggestion_batch_id"])
        self.assertEqual(result["copy_fields"], row["copy_fields"])
        self.assertEqual(len(self.fake.calls), 0)

    def test_manual_api_success_risk_pending_and_version_conflict(self):
        from fastapi.testclient import TestClient

        from app.main import app

        client = TestClient(app)
        for risky in (False, True):
            row = self.placement(
                {
                    "headline": "免費試飲" if risky else "原標題",
                    "body": "原文",
                    "description": "原說明",
                }
            )
            changed = assets.revise(
                self.conn,
                self.org,
                self.brand,
                self.campaign,
                row["id"],
                1,
                {"purpose": "品牌介紹"},
                "test",
            )
            self.conn.commit()
            url = (
                f"/api/ads/brands/{self.brand}/campaigns/{self.campaign}"
                f"/placements/{row['id']}/confirm"
            )
            self.assertEqual(client.post(url, json={"expected_revision": 1}).status_code, 409)
            result = client.post(url, json={"expected_revision": changed["revision"]})
            self.assertEqual(result.status_code, 200, result.text)
            self.assertEqual(
                result.json()["placement"]["status"], "pending" if risky else "manual_ready"
            )
        self.assertEqual(len(self.fake.calls), 0)

    def test_batch_history_is_paginated_and_campaign_scoped(self):
        from fastapi.testclient import TestClient

        from app.main import app

        rows = [self.placement(), self.placement(), self.placement()]
        for index, row in enumerate(rows):
            self.request([row], str(index))
        page = suggestions.list_batches(self.conn, self.org, self.brand, self.campaign, limit=2)
        self.assertEqual(len(page["batches"]), 2)
        rest = suggestions.list_batches(
            self.conn, self.org, self.brand, self.campaign, after=page["next_cursor"], limit=2
        )
        self.assertEqual(len(rest["batches"]), 1)
        self.assertIsNone(rest["next_cursor"])
        with self.assertRaises(ValueError):
            suggestions.list_batches(self.conn, "other", self.brand, self.campaign)
        response = TestClient(app).get(
            f"/api/ads/brands/{self.brand}/campaigns/{self.campaign}/asset-suggestions?limit=2"
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(len(response.json()["batches"]), 2)
