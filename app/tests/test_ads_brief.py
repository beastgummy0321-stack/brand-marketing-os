"""app/tests/test_ads_brief.py — F03-I03: one sentence becomes a draft Campaign
(`app/ads/brief.py::create_draft`). FakeProvider only, no real network request (same pattern as
`app/tests/test_workbench_free_parse.py`). Falsifiers named in the ticket's `# Done`: the draft
never loses the user's sentence, never invents a `success_target`, never dead-ends on a provider
error, and refuses dates outside `start <= end` with a readable message.
"""

import json
import unittest

import app.shared.web as web
from app.ads import brief
from app.ads import repository as ads_repo
from app.ads import routes as ads_routes
from app.brand_intelligence import repository as bi_repo
from app.core import db as coredb
from app.llm import providers

ACTOR = "測試員"


def _fake(rendered_output: str) -> providers.FakeProvider:
    return providers.FakeProvider(response=providers.ProviderResponse(
        output_text=rendered_output, structured=None,
        usage=providers.Usage(input_tokens=100, output_tokens=50), stop_reason="end_turn",
    ))


class _BriefTestBase(unittest.TestCase):
    def setUp(self):
        self.org_id = coredb.DEV_ORG_ID
        self.brand = bi_repo.create_brand(
            web.conn, org_id=self.org_id, name="測試品牌：投放中心 brief", client_name=None,
            actor=ACTOR,
        )
        self.brand_id = self.brand["id"]
        self.product = bi_repo.create_product(web.conn, self.brand_id, name="夜跑背心", actor=ACTOR)
        self.economics = bi_repo.save_product_economics(
            web.conn, self.brand_id, self.product["id"], actor=ACTOR,
            selling_price=1000, currency="TWD", confirmed_by=ACTOR,
            unit_variable_cost=300, shipping_cost=100,
        )
        self._orig_provider = brief.PROVIDER

    def tearDown(self):
        brief.PROVIDER = self._orig_provider

    def _task_count(self) -> int:
        row = web.conn.execute(
            "SELECT COUNT(*) AS c FROM llm_task WHERE brand_id = %s"
            " AND task_type = 'ads_brief_parse'",
            (self.brand_id,),
        ).fetchone()
        return row["c"]

    def _create(self, **overrides):
        kwargs = {
            "org_id": self.org_id, "brand_id": self.brand_id,
            "goal_text": "幫夜跑背心做一波購買導向的投放，這個月衝業績",
            "start_date": "2026-10-01", "end_date": "2026-10-31",
            "constraints": None, "actor": ACTOR,
        }
        kwargs.update(overrides)
        return brief.create_draft(web.conn, kwargs.pop("org_id"), kwargs.pop("brand_id"), **kwargs)


class ValidReplyTest(_BriefTestBase):
    def test_parsed_reply_preserves_sentence_and_names_products_used(self):
        goal_text = "幫夜跑背心做一波購買導向的投放，這個月衝業績"
        reply = json.dumps({
            "objective": "購買", "success_metric": "cpa", "success_target": 500,
            "success_basis": f"依 {self.product['id']} 打平 CPA 推算",
            "product_ids": [self.product["id"]], "audience_hint": "夜跑愛好者", "notes": None,
        }, ensure_ascii=False)
        brief.PROVIDER = _fake(reply)

        detail = self._create(goal_text=goal_text)

        self.assertTrue(detail["parsed"])
        self.assertEqual(detail["goal_text"], goal_text)
        self.assertEqual(detail["objective"], "購買")
        self.assertEqual(detail["success_metric"], "cpa")
        self.assertEqual(detail["success_target"], 500)
        self.assertEqual(detail["status"], "draft")
        self.assertEqual(detail["context_json"]["product_ids"], [self.product["id"]])
        self.assertEqual(detail["context_json"]["economics_ids"], [self.economics["id"]])
        self.assertEqual(self._task_count(), 1)


class ProviderFailureTest(_BriefTestBase):
    def test_provider_failure_still_produces_usable_draft(self):
        brief.PROVIDER = providers.FakeProvider(
            exception=providers.ProviderTimeoutError("AI 服務逾時未回應，請再試一次。"),
        )

        goal_text = "幫夜跑背心做一波投放"
        detail = self._create(goal_text=goal_text)

        self.assertFalse(detail["parsed"])
        self.assertEqual(detail["goal_text"], goal_text)
        self.assertEqual(detail["objective"], "購買")
        self.assertEqual(detail["success_metric"], "roas")
        self.assertIsNone(detail["success_target"])
        self.assertIsNotNone(detail["success_basis"])
        self.assertEqual(detail["status"], "draft")
        self.assertEqual(self._task_count(), 1)


class NullTargetSurvivesTest(_BriefTestBase):
    def test_model_returned_null_target_survives_as_null(self):
        reply = json.dumps({
            "objective": "知名度", "success_metric": "roas", "success_target": None,
            "success_basis": "沒有足夠的價格資料推算目標值",
            "product_ids": [], "audience_hint": None, "notes": None,
        }, ensure_ascii=False)
        brief.PROVIDER = _fake(reply)

        detail = self._create()

        self.assertTrue(detail["parsed"])
        self.assertIsNone(detail["success_target"])
        self.assertEqual(detail["success_basis"], "沒有足夠的價格資料推算目標值")


class BadDatesTest(_BriefTestBase):
    def test_end_before_start_is_refused_with_readable_message(self):
        brief.PROVIDER = _fake("{}")
        with self.assertRaises(ValueError) as ctx:
            self._create(start_date="2026-10-31", end_date="2026-10-01")
        # F03-I19: brief.py raises the machine token now; `ads_routes` is where the token turns
        # into the readable sentence — still `brief.END_BEFORE_START_MESSAGE`, asserted here.
        self.assertEqual(str(ctx.exception), "end_before_start")
        self.assertEqual(
            ads_routes._CREATE_CAMPAIGN_ERRORS[str(ctx.exception)],
            (400, brief.END_BEFORE_START_MESSAGE),
        )
        self.assertEqual(self._task_count(), 0)  # 沒過驗證就不該打模型、不該花錢


class PatchEndBeforeStartOnMergedRowTest(_BriefTestBase):
    def test_moving_only_end_date_before_stored_start_is_refused(self):
        brief.PROVIDER = _fake("{}")
        detail = self._create(start_date="2026-10-01", end_date="2026-10-31")

        with self.assertRaises(ValueError) as ctx:
            ads_repo.update_campaign(
                web.conn, self.org_id, self.brand_id, detail["id"],
                {"end_date": "2026-09-01"},
            )
        self.assertEqual(str(ctx.exception), "end_before_start")

        unchanged = ads_repo.get_campaign(web.conn, self.org_id, self.brand_id, detail["id"])
        self.assertEqual(unchanged["end_date"].isoformat(), "2026-10-31")


class PatchBoundCampaignTest(_BriefTestBase):
    def test_bound_campaign_refuses_name_but_accepts_success_target(self):
        brief.PROVIDER = _fake("{}")
        detail = self._create()
        web.conn.execute(
            "UPDATE ads_campaign SET local_state = 'bound' WHERE id = %s", (detail["id"],),
        )
        web.conn.commit()

        with self.assertRaises(ValueError) as ctx:
            ads_repo.update_campaign(
                web.conn, self.org_id, self.brand_id, detail["id"], {"name": "改個名字"},
            )
        self.assertEqual(str(ctx.exception), "campaign_bound")

        updated = ads_repo.update_campaign(
            web.conn, self.org_id, self.brand_id, detail["id"], {"success_target": 250},
        )
        self.assertEqual(updated["success_target"], 250)


class ForeignProductIdDroppedOnParseTest(_BriefTestBase):
    def test_model_named_product_id_not_in_brand_is_dropped_silently(self):
        reply = json.dumps({
            "objective": "購買", "success_metric": "cpa", "success_target": 500,
            "success_basis": "AI 掰的商品 id",
            "product_ids": ["prd_not_this_brand"], "audience_hint": None, "notes": None,
        }, ensure_ascii=False)
        brief.PROVIDER = _fake(reply)

        detail = self._create()

        self.assertTrue(detail["parsed"])
        self.assertEqual(detail["context_json"]["product_ids"], [])


class PatchForeignProductIdRefusedTest(_BriefTestBase):
    def test_patch_with_foreign_product_id_is_refused(self):
        brief.PROVIDER = _fake("{}")
        detail = self._create()

        with self.assertRaises(ValueError) as ctx:
            ads_repo.update_campaign(
                web.conn, self.org_id, self.brand_id, detail["id"],
                {"product_ids": ["prd_not_this_brand"]},
            )
        self.assertEqual(str(ctx.exception), "product_unknown")


if __name__ == "__main__":
    unittest.main()
