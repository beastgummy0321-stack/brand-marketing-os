"""app/tests/test_ads_brief.py — F03-I03: one sentence becomes a draft Campaign
(`app/ads/brief.py::create_draft`). FakeProvider only, no real network request (same pattern as
`app/tests/test_workbench_free_parse.py`). Falsifiers named in the ticket's `# Done`: the draft
never loses the user's sentence, never invents a `success_target`, never dead-ends on a provider
error, and refuses dates outside `start <= end` with a readable message.
"""

import datetime
import json
import unittest
from unittest.mock import patch

import app.shared.web as web
from app.ads import brief
from app.ads import repository as ads_repo
from app.ads import routes as ads_routes
from app.brand_intelligence import repository as bi_repo
from app.core import db as coredb
from app.core import settings as coresettings
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
    def test_saved_goal_and_connected_channels_reach_prompt_and_evidence_without_overriding_request(self):
        bi_repo.set_brand_switches(web.conn, self.brand_id, market_region=None, conversion_goal="lead", actor=ACTOR)
        provider = _fake(json.dumps({"objective": "名單", "success_metric": "cpa", "success_target": None, "product_ids": []}))
        brief.PROVIDER = provider
        channel = {"key": "connected-fixture", "label": "已綁平台", "connected": True}
        with patch.object(brief.channels, "list_channels", return_value=[channel, {"key": "disconnected-fixture", "label": "未綁平台", "connected": False}]) as read_channels:
            detail = self._create(constraints={"budget": "1200", "platform": "user-choice"})
        read_channels.assert_called_once_with(web.conn, self.org_id, self.brand_id)
        prompt = provider.calls[0]["messages"][0]["content"]
        self.assertIn('"conversion_goal": "lead"', prompt)
        self.assertIn("留資料", prompt)
        self.assertIn("connected-fixture", prompt)
        self.assertNotIn("disconnected-fixture", prompt)
        self.assertIn("不證明權限仍有效", prompt)
        self.assertIn("品牌月額度不是本次活動預算", prompt)
        self.assertEqual(detail["context_json"]["brand_setup"], {"conversion_goal": "lead", "connected_channels": [{"key": "connected-fixture", "label": "已綁平台"}]})
        self.assertEqual(detail["constraints_json"], {"budget": "1200", "platform": "user-choice"})
        self.assertEqual(len(provider.calls), 1)

    def test_missing_saved_setup_stays_unknown_and_does_not_fabricate_a_platform_or_budget(self):
        provider = _fake(json.dumps({"objective": "購買", "success_metric": "cpa", "success_target": None, "product_ids": []}))
        brief.PROVIDER = provider
        detail = self._create()
        prompt = provider.calls[0]["messages"][0]["content"]
        self.assertIn('"conversion_goal": null', prompt)
        self.assertIn('"connected_channels": []', prompt)
        self.assertIn("尚未設定", prompt)
        self.assertEqual(detail["constraints_json"], {})

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


class OnlyOneDateGivenTest(_BriefTestBase):
    def test_only_start_date_given_is_refused(self):
        brief.PROVIDER = _fake("{}")
        with self.assertRaises(ValueError) as ctx:
            self._create(start_date="2026-10-01", end_date="")
        self.assertEqual(str(ctx.exception), "dates_required")
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


class ManyProductsCappedTest(_BriefTestBase):
    """F04-I03: 30 個商品的品牌只送前 20 個進 prompt，但白名單仍是全部 30 個——第 25 個商品
    的 id 是模型「瞎掰」也照樣被接受，因為它其實存在，只是沒被列進 prompt。"""

    def test_prompt_lists_only_20_but_whitelist_keeps_all_products(self):
        extra_products = [
            bi_repo.create_product(web.conn, self.brand_id, name=f"商品{i:02d}", actor=ACTOR)
            for i in range(30)
        ]
        provider = _fake("{}")
        brief.PROVIDER = provider

        detail = self._create()

        sent_prompt = provider.calls[0]["messages"][0]["content"]
        # `list_products` 依名稱排序（app/brand_intelligence/repository.py）；補零讓字串排序
        # 等於數字排序，前 20 個是「商品00」~「商品19」，其餘 11 個（「商品20」~「商品29」
        # 加上 setUp 建的「夜跑背心」）都被截掉。
        self.assertIn("（這個品牌另有 11 個商品沒有列出）", sent_prompt)

        beyond_cap_id = extra_products[24]["id"]
        reply = json.dumps({
            "objective": "購買", "success_metric": "cpa", "success_target": 500,
            "success_basis": "測試", "product_ids": [beyond_cap_id],
            "audience_hint": None, "notes": None,
        }, ensure_ascii=False)
        brief.PROVIDER = _fake(reply)
        detail = self._create()
        self.assertEqual(detail["context_json"]["product_ids"], [beyond_cap_id])


class ResolvePeriodTest(unittest.TestCase):
    """F04-I11: pure function, no DB — day-of-month arithmetic belongs in the program (R7),
    not in the model's reply."""

    def test_month_in_the_past_rolls_to_next_year(self):
        start, end = brief._resolve_period(
            {"kind": "month", "month": 3}, today=datetime.date(2026, 9, 13),
        )
        self.assertEqual(start, datetime.date(2027, 3, 1))
        self.assertEqual(end, datetime.date(2027, 3, 31))

    def test_month_still_ahead_this_year_stays_this_year(self):
        start, end = brief._resolve_period(
            {"kind": "month", "month": 12}, today=datetime.date(2026, 9, 13),
        )
        self.assertEqual(start, datetime.date(2026, 12, 1))
        self.assertEqual(end, datetime.date(2026, 12, 31))

    def test_none_period_resolves_to_none(self):
        self.assertEqual(
            brief._resolve_period(None, today=datetime.date(2026, 9, 13)), (None, None),
        )


class BriefBudgetTargetFromSentenceTest(_BriefTestBase):
    """F04-I11 (backlog: `docs/backlog/issue-brief-parse-drops-explicit-target.md`, verbatim):
    「9 月推 Beast Gummy 高咖啡因軟糖給上班族，目標是購買，希望 CPA 在 300 以內，預算三萬。」
    used to lose both `success_target` and the budget — this locks the fix in."""

    GOAL_TEXT = (
        "9 月推 Beast Gummy 高咖啡因軟糖給上班族，目標是購買，希望 CPA 在 300 以內，預算三萬。"
    )

    def test_numbers_land_on_the_fields_they_modify_and_period_resolves(self):
        reply = json.dumps({
            "objective": "購買", "success_metric": "cpa", "success_target": 300,
            "success_basis": "使用者直接說出的 CPA 上限", "product_ids": [self.product["id"]],
            "budget_cap": 30000, "platform": None,
            "period": {"kind": "month", "month": 9},
            "audience_hint": "上班族", "notes": None,
        }, ensure_ascii=False)
        brief.PROVIDER = _fake(reply)
        today = coresettings.today_for_org(web.conn, org_id=self.org_id)
        expected_start, expected_end = brief._resolve_period(
            {"kind": "month", "month": 9}, today=today,
        )

        detail = self._create(goal_text=self.GOAL_TEXT, start_date="", end_date="")

        self.assertEqual(detail["success_target"], 300)
        self.assertEqual(detail["constraints_json"]["budget"], 30000)
        self.assertEqual(detail["start_date"], expected_start)
        self.assertEqual(detail["end_date"], expected_end)
        self.assertEqual(detail["context_json"]["field_sources"]["dates"], "user")
        self.assertEqual(detail["context_json"]["field_sources"]["budget"], "user")

    def test_unparseable_period_falls_back_to_today_plus_30_and_is_system(self):
        reply = json.dumps({
            "objective": "購買", "success_metric": "cpa", "success_target": 300,
            "success_basis": "使用者直接說出的 CPA 上限", "product_ids": [],
            "budget_cap": 30000, "platform": None, "period": None,
            "audience_hint": None, "notes": None,
        }, ensure_ascii=False)
        brief.PROVIDER = _fake(reply)
        today = coresettings.today_for_org(web.conn, org_id=self.org_id)

        detail = self._create(goal_text=self.GOAL_TEXT, start_date="", end_date="")

        self.assertEqual(detail["start_date"], today)
        self.assertEqual(detail["end_date"], today + datetime.timedelta(days=30))
        self.assertEqual(detail["context_json"]["field_sources"]["dates"], "system")


class UserBudgetChipBeatsModelTest(_BriefTestBase):
    def test_user_supplied_constraint_wins_over_model_parsed_budget(self):
        reply = json.dumps({
            "objective": "購買", "success_metric": "cpa", "success_target": 300,
            "success_basis": "測試", "product_ids": [], "budget_cap": 30000,
            "platform": None, "period": None, "audience_hint": None, "notes": None,
        }, ensure_ascii=False)
        brief.PROVIDER = _fake(reply)

        detail = self._create(constraints={"budget": "5000"})

        self.assertEqual(detail["constraints_json"]["budget"], "5000")
        self.assertEqual(detail["context_json"]["field_sources"]["budget"], "user")


class UpdateCampaignFlipsFieldSourceToUserTest(_BriefTestBase):
    def test_patching_a_system_sourced_field_flips_it_to_user(self):
        brief.PROVIDER = _fake("{}")
        detail = self._create()
        self.assertEqual(detail["context_json"]["field_sources"]["budget"], "system")
        before_sources = dict(detail["context_json"]["field_sources"])

        updated = ads_repo.update_campaign(
            web.conn, self.org_id, self.brand_id, detail["id"],
            {"constraints_json": {**detail["constraints_json"], "budget": 30000}},
        )

        after_sources = updated["context_json"]["field_sources"]
        self.assertEqual(after_sources["budget"], "user")
        for key, value in before_sources.items():
            if key != "budget":
                self.assertEqual(after_sources[key], value)


class ScriptedReplyParsesTest(_BriefTestBase):
    """形狀絆線（F06-I05）：`providers.SCRIPTED_REPLIES["ads_brief_parse"]` 必須通過
    `brief.create_draft` 自己的驗證，e2e 才不會在這裡默默掉進 parsed=False。"""

    def test_scripted_reply_parses(self):
        reply = json.dumps(providers.SCRIPTED_REPLIES["ads_brief_parse"], ensure_ascii=False)
        brief.PROVIDER = _fake(reply)

        detail = self._create()

        self.assertTrue(detail["parsed"])


if __name__ == "__main__":
    unittest.main()
