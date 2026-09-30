"""app/tests/test_ads_brief.py — F03-I03: one sentence becomes a draft Campaign
(`app/ads/brief.py::create_draft`). FakeProvider only, no real network request (same pattern as
`app/tests/test_workbench_free_parse.py`). Falsifiers named in the ticket's `# Done`: the draft
never loses the user's sentence, never invents a cap, never dead-ends on a provider error, and
refuses dates outside `start <= end` with a readable message. F28-I01: the reply carries one
cost-per-purchase `cap` (stored as the campaign's own cap); a reply without `cap` still parses,
and a ROAS in the reply never becomes a cap.
"""

import datetime
import json
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

import app.main as main
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
    def test_saved_goal_and_connected_channels_reach_prompt_and_evidence_without_overriding_request(
        self,
    ):
        bi_repo.set_brand_switches(
            web.conn, self.brand_id, market_region=None, conversion_goal="lead", actor=ACTOR,
        )
        provider = _fake(json.dumps({
            "objective": "名單", "cap": None, "product_ids": [],
        }))
        brief.PROVIDER = provider
        channel = {"key": "connected-fixture", "label": "已綁平台", "connected": True}
        with patch.object(brief.channels, "list_channels", return_value=[
            channel, {"key": "disconnected-fixture", "label": "未綁平台", "connected": False},
        ]) as read_channels:
            detail = self._create(constraints={"budget": "1200", "platform": "user-choice"})
        read_channels.assert_called_once_with(web.conn, self.org_id, self.brand_id)
        prompt = provider.calls[0]["messages"][0]["content"]
        self.assertIn('"conversion_goal": "lead"', prompt)
        self.assertIn("留資料", prompt)
        self.assertIn("connected-fixture", prompt)
        self.assertNotIn("disconnected-fixture", prompt)
        self.assertIn("不證明權限仍有效", prompt)
        self.assertIn("品牌月額度不是本次活動預算", prompt)
        self.assertEqual(detail["context_json"]["brand_setup"], {
            "conversion_goal": "lead",
            "connected_channels": [{"key": "connected-fixture", "label": "已綁平台"}],
        })
        self.assertEqual(detail["constraints_json"], {"budget": "1200", "platform": "user-choice"})
        self.assertEqual(len(provider.calls), 1)

    def test_missing_saved_setup_stays_unknown_and_does_not_fabricate_a_platform_or_budget(self):
        provider = _fake(json.dumps({
            "objective": "購買", "cap": None, "product_ids": [],
        }))
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
            "objective": "購買", "cap": 500,
            "product_ids": [self.product["id"]], "audience_hint": "夜跑愛好者", "notes": None,
        }, ensure_ascii=False)
        brief.PROVIDER = _fake(reply)

        detail = self._create(goal_text=goal_text)

        self.assertTrue(detail["parsed"])
        self.assertEqual(detail["goal_text"], goal_text)
        self.assertEqual(detail["objective"], "購買")
        self.assertEqual(detail["cap"]["value"], 500)
        self.assertEqual(detail["cap"]["basis"], "own")
        self.assertEqual(detail["cap"]["break_even"], 600)  # 1000 - 300 - 100
        self.assertFalse([key for key in detail if key.startswith("success_")])
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
        self.assertIsNone(detail["cap"]["own_value"])
        self.assertIsNone(detail["cap"]["value"])  # no product named yet -> nothing to resolve
        self.assertEqual(detail["cap"]["missing"], ["product"])
        self.assertEqual(detail["status"], "draft")
        self.assertEqual(self._task_count(), 1)


class NullTargetSurvivesTest(_BriefTestBase):
    def test_model_returned_null_cap_survives_as_no_cap(self):
        reply = json.dumps({
            "objective": "知名度", "cap": None,
            "product_ids": [], "audience_hint": None, "notes": "使用者希望 ROAS 3",
        }, ensure_ascii=False)
        brief.PROVIDER = _fake(reply)

        detail = self._create()

        self.assertTrue(detail["parsed"])
        self.assertIsNone(detail["cap"]["own_value"])

    def test_reply_without_cap_still_parses_and_a_roas_never_becomes_a_cap(self):
        # The pre-F28 reply shape (and the legacy e2e scripted reply) carries a ROAS target and
        # no `cap` at all: it parses, and the ROAS is never converted into a cost cap.
        reply = json.dumps({
            "objective": "購買", "success_metric": "roas", "success_target": 3,
            "product_ids": [], "audience_hint": None, "notes": None,
        }, ensure_ascii=False)
        brief.PROVIDER = _fake(reply)

        detail = self._create()

        self.assertTrue(detail["parsed"])
        self.assertIsNone(detail["cap"]["own_value"])
        row = web.conn.execute(
            "SELECT target_cost, target_basis FROM ads_campaign WHERE id=%s", (detail["id"],),
        ).fetchone()
        self.assertIsNone(row["target_cost"])
        self.assertIsNone(row["target_basis"])

    def test_non_positive_or_non_numeric_cap_is_no_cap(self):
        for bad in (0, -5, "450", True):
            reply = json.dumps({"objective": "購買", "cap": bad, "product_ids": []})
            brief.PROVIDER = _fake(reply)
            detail = self._create()
            self.assertTrue(detail["parsed"])
            self.assertIsNone(detail["cap"]["own_value"], bad)


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
    def test_bound_campaign_refuses_name_but_accepts_goal_text(self):
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
            web.conn, self.org_id, self.brand_id, detail["id"], {"objective": "名單"},
        )
        self.assertEqual(updated["objective"], "名單")


class ForeignProductIdDroppedOnParseTest(_BriefTestBase):
    def test_model_named_product_id_not_in_brand_is_dropped_silently(self):
        reply = json.dumps({
            "objective": "購買", "cap": 500,
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
            "objective": "購買", "cap": 500,
            "product_ids": [beyond_cap_id],
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
    used to lose both the cost cap (`cap` since F28-I01) and the budget — this locks the fix in."""

    GOAL_TEXT = (
        "9 月推 Beast Gummy 高咖啡因軟糖給上班族，目標是購買，希望 CPA 在 300 以內，預算三萬。"
    )

    def test_numbers_land_on_the_fields_they_modify_and_period_resolves(self):
        reply = json.dumps({
            "objective": "購買", "cap": 300,
            "product_ids": [self.product["id"]],
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

        self.assertEqual(detail["cap"]["value"], 300)
        self.assertEqual(detail["constraints_json"]["budget"], 30000)
        self.assertEqual(detail["start_date"], expected_start)
        self.assertEqual(detail["end_date"], expected_end)
        self.assertEqual(detail["context_json"]["field_sources"]["dates"], "user")
        self.assertEqual(detail["context_json"]["field_sources"]["budget"], "user")

    def test_unparseable_period_falls_back_to_today_plus_30_and_is_system(self):
        reply = json.dumps({
            "objective": "購買", "cap": 300,
            "product_ids": [],
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
            "objective": "購買", "cap": 300,
            "product_ids": [], "budget_cap": 30000,
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


class StructuredCreateTest(_BriefTestBase):
    """F30-I04 (Contract D): the wizard creates a campaign from picks -- product, objective,
    dates and this campaign's spending cap -- with no sentence typed. The picks are the user's
    own and the model's parse never overrides them."""

    def _picks(self, **overrides):
        picks = {"product_ids": [self.product["id"]], "objective": "名單", "budget": 30000}
        picks.update(overrides)
        return picks

    def _create_picks(self, picks=None, **overrides):
        return self._create(goal_text="", picks=picks or self._picks(), **overrides)

    def test_create_without_text_composes_goal_and_keeps_every_pick(self):
        # The model reads the composed sentence back as a different objective and product --
        # the picks still win; only its audience guess is kept (the one field it adds).
        provider = _fake(json.dumps({
            "objective": "購買", "cap": None, "product_ids": [],
            "audience_hint": "夜跑族", "notes": None,
        }, ensure_ascii=False))
        brief.PROVIDER = provider

        detail = self._create_picks()

        self.assertTrue(detail["parsed"])
        self.assertIn("夜跑背心", detail["goal_text"])
        self.assertIn("名單", detail["goal_text"])
        self.assertIn("30000", detail["goal_text"])
        self.assertIn(detail["goal_text"], provider.calls[0]["messages"][0]["content"])
        self.assertEqual(detail["objective"], "名單")
        self.assertEqual(detail["context_json"]["product_ids"], [self.product["id"]])
        self.assertEqual(detail["start_date"], datetime.date(2026, 10, 1))
        self.assertEqual(detail["end_date"], datetime.date(2026, 10, 31))
        budget = detail["constraints_json"]["budget"]
        self.assertNotIsInstance(budget, str)
        self.assertEqual(budget, 30000)
        self.assertEqual(detail["context_json"]["audience_hint"], "夜跑族")
        sources = detail["context_json"]["field_sources"]
        for key in ("product", "objective", "budget", "dates"):
            self.assertEqual(sources[key], "user", key)
        self.assertEqual(self._task_count(), 1)  # parsing stays synchronous, one call

    # -- F41-I03 (drill-8 #5): the default name keeps its dates ----------------------------------

    def _named_product(self, name):
        return bi_repo.create_product(web.conn, self.brand_id, name=name, actor=ACTOR)

    def test_structured_create_is_named_product_then_dates(self):
        brief.PROVIDER = _fake("{}")
        product = self._named_product("Beast Gummy 超能特惠組 · 單品")
        detail = self._create_picks(
            picks=self._picks(product_ids=[product["id"]]),
            start_date="2026-10-10", end_date="2026-10-16",
        )
        self.assertEqual(detail["name"], "Beast Gummy 超能特惠組 · 單品・10/10～10/16")

    def test_a_long_product_name_is_shortened_but_the_dates_never_are(self):
        brief.PROVIDER = _fake("{}")
        long_name = "超" * 60
        product = self._named_product(long_name)
        detail = self._create_picks(
            picks=self._picks(product_ids=[product["id"]]),
            start_date="2026-10-10", end_date="2026-10-16",
        )
        self.assertEqual(detail["name"], "超" * 30 + "…・10/10～10/16")

    def test_sentence_create_names_the_sentence_with_its_dates(self):
        brief.PROVIDER = _fake("{}")
        detail = self._create(goal_text="  秋天主打通勤族  ")
        self.assertEqual(detail["name"], "秋天主打通勤族・10/01～10/31")

    def test_draft_name_without_dates_is_the_base_alone(self):
        self.assertEqual(brief._draft_name("  夜跑背心 "), "夜跑背心")
        self.assertEqual(brief._draft_name("跑" * 31), "跑" * 30 + "…")

    def test_typed_goal_text_is_kept_verbatim(self):
        brief.PROVIDER = _fake("{}")
        detail = self._create(goal_text="秋天主打通勤族", picks=self._picks())
        self.assertEqual(detail["goal_text"], "秋天主打通勤族")
        self.assertEqual(detail["objective"], "名單")

    def test_picks_survive_a_provider_failure(self):
        brief.PROVIDER = providers.FakeProvider(
            exception=providers.ProviderTimeoutError("AI 服務逾時未回應，請再試一次。"),
        )
        detail = self._create_picks()
        self.assertFalse(detail["parsed"])
        self.assertEqual(detail["objective"], "名單")
        self.assertEqual(detail["context_json"]["product_ids"], [self.product["id"]])
        self.assertEqual(detail["constraints_json"]["budget"], 30000)
        self.assertEqual(detail["context_json"]["field_sources"]["objective"], "user")

    def test_budget_pick_beats_a_budget_in_constraints_and_the_model(self):
        brief.PROVIDER = _fake(json.dumps({
            "objective": "名單", "cap": None, "product_ids": [], "budget_cap": 99999,
        }))
        detail = self._create_picks(picks=self._picks(budget=1234.5),
                                    constraints={"budget": "5000"})
        self.assertEqual(detail["constraints_json"]["budget"], 1234.5)

    def test_reserved_objective_is_refused_before_any_model_call(self):
        brief.PROVIDER = _fake("{}")
        for key in ("互動", "App 推廣", "來店"):
            with self.assertRaises(ValueError) as ctx:
                self._create_picks(picks=self._picks(objective=key))
            self.assertEqual(str(ctx.exception), "objective_unavailable", key)
        with self.assertRaises(ValueError) as ctx:
            self._create_picks(picks=self._picks(objective="OUTCOME_SALES"))
        self.assertEqual(str(ctx.exception), "objective_unknown")
        self.assertEqual(self._task_count(), 0)

    def test_budget_must_be_a_positive_number(self):
        brief.PROVIDER = _fake("{}")
        for bad in ("30000", "abc", True, 0, -10, float("nan"), float("inf"), None, [30000]):
            with self.assertRaises(ValueError) as ctx:
                self._create_picks(picks=self._picks(budget=bad))
            self.assertEqual(str(ctx.exception), "budget_invalid", repr(bad))
        self.assertEqual(self._task_count(), 0)

    def test_composed_goal_never_carries_a_model_cap(self):
        brief.PROVIDER = _fake(json.dumps({"objective": "名單", "cap": 30000, "product_ids": []}))
        detail = self._create_picks()
        self.assertTrue(detail["parsed"])
        self.assertIsNone(detail["cap"]["own_value"])
        row = web.conn.execute(
            "SELECT target_cost, target_basis FROM ads_campaign WHERE id=%s", (detail["id"],),
        ).fetchone()
        self.assertIsNone(row["target_cost"])
        self.assertIsNone(row["target_basis"])

    def test_products_must_be_one_the_wizard_lists(self):
        brief.PROVIDER = _fake("{}")
        other = bi_repo.create_product(web.conn, self.brand_id, name="反光臂帶", actor=ACTOR)
        archived = bi_repo.create_product(web.conn, self.brand_id, name="舊款背心", actor=ACTOR)
        bi_repo.update_product(
            web.conn, self.brand_id, archived["id"], name=archived["name"], status="archived",
            actor=ACTOR,
        )
        parent = bi_repo.create_product(web.conn, self.brand_id, name="夜跑套組", actor=ACTOR)
        sell_way = bi_repo.create_product(
            web.conn, self.brand_id, name="夜跑套組 · 單品", actor=ACTOR, parent_id=parent["id"],
        )
        for bad, code in (
            ([], "products_required"), (None, "products_required"),
            ("prd_x", "products_required"),
            ([self.product["id"], other["id"]], "products_required"),
            (["prd_not_this_brand"], "product_unknown"), ([archived["id"]], "product_unknown"),
            ([parent["id"]], "product_unknown"),
        ):
            with self.assertRaises(ValueError) as ctx:
                self._create_picks(picks=self._picks(product_ids=bad))
            self.assertEqual(str(ctx.exception), code, repr(bad))
        self.assertEqual(self._task_count(), 0)
        detail = self._create_picks(picks=self._picks(product_ids=[sell_way["id"]]))
        self.assertEqual(detail["context_json"]["product_ids"], [sell_way["id"]])

    def test_default_dates_start_from_the_organisations_today(self):
        brief.PROVIDER = _fake(json.dumps({
            "objective": "名單", "cap": None, "product_ids": [],
            "period": {"kind": "month", "month": 12},
        }))
        org_today = datetime.date(2031, 1, 31)  # not the machine's date
        with patch.object(coresettings, "today_for_org", return_value=org_today) as today:
            detail = self._create_picks(start_date="", end_date="")
        today.assert_any_call(web.conn, org_id=self.org_id)
        # The picks path never takes the model's period: no dates -> org today + 30 days.
        self.assertEqual(detail["start_date"], org_today)
        self.assertEqual(detail["end_date"], org_today + datetime.timedelta(days=30))
        self.assertEqual(detail["context_json"]["field_sources"]["dates"], "system")
        self.assertIn("2031-01-31", detail["goal_text"])

    def test_only_one_date_is_still_refused(self):
        brief.PROVIDER = _fake("{}")
        with self.assertRaises(ValueError) as ctx:
            self._create_picks(start_date="2026-10-01", end_date="")
        self.assertEqual(str(ctx.exception), "dates_required")


class StructuredCreateRouteTest(_BriefTestBase):
    def setUp(self):
        super().setUp()
        self.client = TestClient(main.app)
        self.url = f"/api/ads/brands/{self.brand_id}/campaigns"

    def _post(self, **body):
        payload = {"product_ids": [self.product["id"]], "objective": "購買",
                   "start_date": "2026-10-01", "end_date": "2026-10-31", "budget": 30000}
        payload.update(body)
        return self.client.post(self.url, json=payload)

    def test_create_from_picks_without_goal_text(self):
        brief.PROVIDER = _fake("{}")
        res = self._post()
        self.assertEqual(res.status_code, 200, res.text)
        campaign = res.json()["campaign"]
        self.assertEqual(campaign["objective"], "購買")
        self.assertEqual(campaign["constraints_json"]["budget"], 30000)
        self.assertTrue(campaign["goal_text"])
        self.assertIn("asset_readiness", campaign)
        # F42-I02: a brand with no policies, proof or media answer has nothing in hand.
        self.assertEqual(campaign["materials"], {"offers": [], "proof": [], "media": None})

    def test_refusals_are_400_with_their_codes_not_422(self):
        brief.PROVIDER = _fake("{}")
        for body, code in (
            ({"objective": "互動"}, "objective_unavailable"),
            ({"budget": "abc"}, "budget_invalid"),
            ({"budget": "30000"}, "budget_invalid"),
            ({"budget": 0}, "budget_invalid"),
            ({"product_ids": "prd_x"}, "products_required"),
            ({"product_ids": ["prd_not_this_brand"]}, "product_unknown"),
        ):
            res = self._post(**body)
            self.assertEqual(res.status_code, 400, (body, res.text))
            self.assertEqual(res.json()["error"]["code"], code, body)
        self.assertEqual(self._task_count(), 0)

    def test_free_text_create_still_works(self):
        brief.PROVIDER = _fake(json.dumps({"objective": "流量", "cap": None, "product_ids": []}))
        res = self.client.post(self.url, json={
            "goal_text": "導流量到新頁面", "start_date": "2026-10-01", "end_date": "2026-10-31",
        })
        self.assertEqual(res.status_code, 200, res.text)
        self.assertEqual(res.json()["campaign"]["objective"], "流量")
        res = self.client.post(self.url, json={"goal_text": ""})
        self.assertEqual(res.status_code, 400)
        self.assertEqual(res.json()["error"]["code"], "goal_text_required")


class PatchObjectiveFollowsCatalogTest(_BriefTestBase):
    def test_patch_refuses_what_create_refuses(self):
        brief.PROVIDER = _fake("{}")
        detail = self._create()
        for value, code in (("互動", "objective_unavailable"), ("來店", "objective_unavailable"),
                            ("awareness", "objective_unknown"), ("", "objective_unknown"),
                            (None, "objective_unknown")):
            with self.assertRaises(ValueError) as ctx:
                ads_repo.update_campaign(
                    web.conn, self.org_id, self.brand_id, detail["id"], {"objective": value},
                )
            self.assertEqual(str(ctx.exception), code, value)
            self.assertIn(code, ads_routes._PATCH_CAMPAIGN_ERRORS)
        for value in ("流量", "加購物車"):
            updated = ads_repo.update_campaign(
                web.conn, self.org_id, self.brand_id, detail["id"], {"objective": value},
            )
            self.assertEqual(updated["objective"], value)

    def test_patch_route_answers_400_objective_unavailable(self):
        brief.PROVIDER = _fake("{}")
        detail = self._create()
        web.conn.commit()  # the request reads through its own connection
        res = TestClient(main.app).patch(
            f"/api/ads/brands/{self.brand_id}/campaigns/{detail['id']}", json={"objective": "互動"},
        )
        self.assertEqual(res.status_code, 400, res.text)
        self.assertEqual(res.json()["error"]["code"], "objective_unavailable")


class PatchAudienceHintTest(_BriefTestBase):
    def test_patch_sets_and_clears_audience_hint_as_the_users(self):
        brief.PROVIDER = _fake("{}")
        detail = self._create()
        self.assertEqual(detail["context_json"]["field_sources"]["audience"], "system")
        web.conn.commit()  # the request reads through its own connection
        client = TestClient(main.app)
        url = f"/api/ads/brands/{self.brand_id}/campaigns/{detail['id']}"

        res = client.patch(url, json={"audience_hint": "  上班族・通勤族 "})
        self.assertEqual(res.status_code, 200, res.text)
        context = res.json()["campaign"]["context_json"]
        self.assertEqual(context["audience_hint"], "上班族・通勤族")
        self.assertEqual(context["field_sources"]["audience"], "user")
        self.assertEqual(context["product_ids"], detail["context_json"]["product_ids"])

        res = client.patch(url, json={"audience_hint": "   "})
        self.assertEqual(res.status_code, 200, res.text)
        self.assertIsNone(res.json()["campaign"]["context_json"]["audience_hint"])

    def test_imported_campaign_refuses_audience_hint(self):
        brief.PROVIDER = _fake("{}")
        detail = self._create()
        web.conn.execute(
            "UPDATE ads_campaign SET origin = 'imported' WHERE id = %s", (detail["id"],),
        )
        web.conn.commit()
        with self.assertRaises(ValueError):
            ads_repo.update_campaign(
                web.conn, self.org_id, self.brand_id, detail["id"], {"audience_hint": "上班族"},
            )


class CopyFromPreviousTest(_BriefTestBase):
    """F40-I04 (drill-7 #10): a new campaign starts from the previous one. The four values the
    request did not supply -- platform, audience direction, cap, landing URL -- are copied from
    the brand's latest non-draft campaign and named in `context_json.copied_from`; request
    values always win; a first campaign copies nothing."""

    _EMPTY = json.dumps({"objective": "購買", "cap": None, "product_ids": []})
    _FOUR = {
        "platform": "meta", "audience_hint": "夜跑愛好者", "cap": 450,
        "landing_url": "https://shop.example.test/vest",
    }

    def _previous(self, picks=None, **overrides):
        """A campaign that went past draft: the source the next campaign copies from."""
        brief.PROVIDER = _fake(self._EMPTY)
        detail = self._create(picks=picks if picks is not None else dict(self._FOUR),
                              **overrides)
        web.conn.execute(
            "UPDATE ads_campaign SET status = 'live' WHERE id = %s", (detail["id"],),
        )
        return detail

    def test_first_campaign_copies_nothing(self):
        brief.PROVIDER = _fake(self._EMPTY)
        detail = self._create()
        self.assertNotIn("copied_from", detail["context_json"])
        self.assertIsNone(detail["context_json"]["landing_url"])
        self.assertEqual(detail["context_json"]["field_sources"]["landing_url"], "system")
        self.assertEqual(detail["context_json"]["field_sources"]["cap"], "system")

    def test_request_values_land_on_the_first_campaign(self):
        detail = self._previous()
        self.assertEqual(detail["constraints_json"]["platform"], "meta")
        self.assertEqual(detail["context_json"]["audience_hint"], "夜跑愛好者")
        self.assertEqual(detail["context_json"]["landing_url"], "https://shop.example.test/vest")
        self.assertEqual(detail["cap"]["own_value"], 450)
        sources = detail["context_json"]["field_sources"]
        for key in ("platform", "audience", "cap", "landing_url"):
            self.assertEqual(sources[key], "user", key)

    def test_second_campaign_copies_the_four_values_and_names_them(self):
        previous = self._previous()
        brief.PROVIDER = _fake(self._EMPTY)

        detail = self._create(goal_text="再推一波夜跑背心")

        self.assertEqual(detail["context_json"]["copied_from"], {
            "campaign_id": previous["id"], "name": previous["name"],
            "fields": ["platform", "audience_hint", "cap", "landing_url"],
        })
        self.assertEqual(detail["constraints_json"]["platform"], "meta")
        self.assertEqual(detail["context_json"]["audience_hint"], "夜跑愛好者")
        self.assertEqual(detail["context_json"]["landing_url"], "https://shop.example.test/vest")
        self.assertEqual(detail["cap"]["own_value"], 450)
        self.assertEqual(detail["cap"]["basis"], "own")
        sources = detail["context_json"]["field_sources"]
        for key in ("platform", "audience", "cap", "landing_url"):
            self.assertEqual(sources[key], "copied", key)
        self.assertEqual(detail["status"], "draft")

    def test_request_value_overrides_the_copy(self):
        self._previous()
        brief.PROVIDER = _fake(self._EMPTY)

        detail = self._create(
            goal_text="再推一波夜跑背心",
            picks={"platform": "google_ads", "landing_url": "https://shop.example.test/new"},
        )

        self.assertEqual(detail["constraints_json"]["platform"], "google_ads")
        self.assertEqual(detail["context_json"]["landing_url"], "https://shop.example.test/new")
        self.assertEqual(detail["context_json"]["audience_hint"], "夜跑愛好者")
        self.assertEqual(detail["cap"]["own_value"], 450)
        self.assertEqual(detail["context_json"]["copied_from"]["fields"],
                         ["audience_hint", "cap"])
        sources = detail["context_json"]["field_sources"]
        self.assertEqual(sources["platform"], "user")
        self.assertEqual(sources["landing_url"], "user")
        self.assertEqual(sources["audience"], "copied")
        self.assertEqual(sources["cap"], "copied")

    def test_what_the_sentence_said_also_beats_the_copy(self):
        self._previous()
        brief.PROVIDER = _fake(json.dumps({
            "objective": "購買", "cap": 380, "product_ids": [], "audience_hint": "通勤族",
            "platform": "tiktok",
        }, ensure_ascii=False))

        detail = self._create(goal_text="每筆 380 以內，TikTok 推給通勤族")

        self.assertEqual(detail["constraints_json"]["platform"], "tiktok")
        self.assertEqual(detail["context_json"]["audience_hint"], "通勤族")
        self.assertEqual(detail["cap"]["own_value"], 380)
        self.assertEqual(detail["context_json"]["copied_from"]["fields"], ["landing_url"])

    def test_a_draft_is_never_the_source_and_the_latest_non_draft_wins(self):
        older = self._previous()
        newer = self._previous(picks={**self._FOUR, "audience_hint": "晨跑族"})
        web.conn.execute(
            "UPDATE ads_campaign SET created_at = created_at - interval '1 day' WHERE id = %s",
            (older["id"],),
        )
        brief.PROVIDER = _fake(self._EMPTY)
        self._create(goal_text="一份沒送出的草稿", picks={"audience_hint": "草稿受眾"})

        detail = self._create(goal_text="再推一波")

        self.assertEqual(detail["context_json"]["copied_from"]["campaign_id"], newer["id"])
        self.assertEqual(detail["context_json"]["audience_hint"], "晨跑族")

    def test_break_even_cap_and_missing_values_are_not_copied(self):
        previous = self._previous(picks={"platform": "meta"})
        web.conn.execute(
            "UPDATE ads_campaign SET target_basis = 'break_even', target_cost = NULL"
            " WHERE id = %s", (previous["id"],),
        )
        brief.PROVIDER = _fake(self._EMPTY)

        detail = self._create(goal_text="再推一波")

        self.assertEqual(detail["context_json"]["copied_from"]["fields"], ["platform"])
        self.assertIsNone(detail["cap"]["own_value"])
        self.assertIsNone(detail["context_json"]["audience_hint"])
        self.assertIsNone(detail["context_json"]["landing_url"])
        self.assertEqual(detail["context_json"]["field_sources"]["cap"], "system")

    def test_landing_url_falls_back_to_the_previous_first_groups_manual_setting(self):
        previous = self._previous(picks={"platform": "meta"})
        first = ads_repo.create_group(
            web.conn, self.org_id, self.brand_id, previous["id"], channel_key="meta",
            name="新客", role="new", daily_budget=100,
        )
        second = ads_repo.create_group(
            web.conn, self.org_id, self.brand_id, previous["id"], channel_key="meta",
            name="再行銷", role="retarget", daily_budget=100,
        )
        web.conn.execute(
            "UPDATE ads_campaign SET context_json = context_json || %s WHERE id = %s",
            (coredb.jsonb({"manual_delivery": {
                second["id"]: {"values": {"landing_url": "https://shop.example.test/second"}},
                first["id"]: {"values": {"landing_url": "https://shop.example.test/first"}},
            }}), previous["id"]),
        )
        brief.PROVIDER = _fake(self._EMPTY)

        detail = self._create(goal_text="再推一波")

        self.assertEqual(detail["context_json"]["landing_url"], "https://shop.example.test/first")
        self.assertIn("landing_url", detail["context_json"]["copied_from"]["fields"])

    def test_extras_are_refused_before_any_model_call(self):
        brief.PROVIDER = _fake(self._EMPTY)
        for picks, code in (
            ({"platform": "line"}, "platform_unknown"),
            ({"audience_hint": 12}, "audience_hint_unknown"),
            ({"cap": "450"}, "target_value_unknown"),
            ({"cap": 0}, "target_value_unknown"),
            ({"landing_url": "javascript:alert(1)"}, "landing_url_invalid"),
            ({"landing_url": "https://user:pw@shop.example.test/"}, "landing_url_invalid"),
            ({"landing_url": ["https://shop.example.test/"]}, "landing_url_unknown"),
        ):
            with self.assertRaises(ValueError) as ctx:
                self._create(picks=picks)
            self.assertEqual(str(ctx.exception), code, picks)
        self.assertEqual(self._task_count(), 0)


class CopyFromPreviousRouteTest(_BriefTestBase):
    def setUp(self):
        super().setUp()
        self.client = TestClient(main.app)
        self.url = f"/api/ads/brands/{self.brand_id}/campaigns"

    def _post(self, **body):
        payload = {"goal_text": "幫夜跑背心衝購買", "start_date": "2026-10-01",
                   "end_date": "2026-10-31"}
        payload.update(body)
        return self.client.post(self.url, json=payload)

    def test_create_passes_the_four_keys_through_and_the_next_create_copies_them(self):
        brief.PROVIDER = _fake("{}")
        res = self._post(platform="meta", audience_hint="夜跑愛好者", cap=450,
                         landing_url="https://shop.example.test/vest",
                         product_ids=[self.product["id"]], objective="購買", budget=30000)
        self.assertEqual(res.status_code, 200, res.text)
        first = res.json()["campaign"]
        self.assertEqual(first["constraints_json"]["platform"], "meta")
        self.assertEqual(first["context_json"]["landing_url"], "https://shop.example.test/vest")
        self.assertEqual(first["cap"]["own_value"], 450)
        self.assertNotIn("copied_from", first["context_json"])
        web.conn.execute(
            "UPDATE ads_campaign SET status = 'live' WHERE id = %s", (first["id"],),
        )
        web.conn.commit()  # the request reads through its own connection

        res = self._post(cap=500)
        self.assertEqual(res.status_code, 200, res.text)
        second = res.json()["campaign"]
        self.assertEqual(second["context_json"]["copied_from"], {
            "campaign_id": first["id"], "name": first["name"],
            "fields": ["platform", "audience_hint", "landing_url"],
        })
        self.assertEqual(second["cap"]["own_value"], 500)
        self.assertEqual(second["context_json"]["field_sources"]["cap"], "user")
        self.assertEqual(second["context_json"]["field_sources"]["platform"], "copied")
        self.assertEqual(second["manual_handoff"]["groups"], [])

    def test_refusals_are_400_with_their_codes(self):
        brief.PROVIDER = _fake("{}")
        for body, code in (
            ({"platform": "line"}, "platform_unknown"),
            ({"cap": "abc"}, "target_value_unknown"),
            ({"audience_hint": ["x"]}, "audience_hint_unknown"),
            ({"landing_url": "ftp://shop.example.test/"}, "landing_url_invalid"),
        ):
            res = self._post(**body)
            self.assertEqual(res.status_code, 400, (body, res.text))
            self.assertEqual(res.json()["error"]["code"], code, body)
        self.assertEqual(self._task_count(), 0)


class PatchLandingUrlTest(_BriefTestBase):
    def test_patch_sets_validates_and_clears_landing_url_as_the_users(self):
        brief.PROVIDER = _fake("{}")
        detail = self._create()
        self.assertEqual(detail["context_json"]["field_sources"]["landing_url"], "system")
        web.conn.commit()  # the request reads through its own connection
        client = TestClient(main.app)
        url = f"/api/ads/brands/{self.brand_id}/campaigns/{detail['id']}"

        res = client.patch(url, json={"landing_url": " https://shop.example.test/vest "})
        self.assertEqual(res.status_code, 200, res.text)
        context = res.json()["campaign"]["context_json"]
        self.assertEqual(context["landing_url"], "https://shop.example.test/vest")
        self.assertEqual(context["field_sources"]["landing_url"], "user")
        self.assertEqual(context["product_ids"], detail["context_json"]["product_ids"])

        res = client.patch(url, json={"landing_url": "javascript:alert(1)"})
        self.assertEqual(res.status_code, 400, res.text)
        self.assertEqual(res.json()["error"]["code"], "landing_url_invalid")

        res = client.patch(url, json={"landing_url": None, "audience_hint": "通勤族"})
        self.assertEqual(res.status_code, 200, res.text)
        context = res.json()["campaign"]["context_json"]
        self.assertIsNone(context["landing_url"])
        self.assertEqual(context["audience_hint"], "通勤族")

    def test_imported_campaign_refuses_landing_url(self):
        brief.PROVIDER = _fake("{}")
        detail = self._create()
        web.conn.execute(
            "UPDATE ads_campaign SET origin = 'imported' WHERE id = %s", (detail["id"],),
        )
        web.conn.commit()
        res = TestClient(main.app).patch(
            f"/api/ads/brands/{self.brand_id}/campaigns/{detail['id']}",
            json={"landing_url": "https://shop.example.test/vest"},
        )
        self.assertEqual(res.status_code, 409, res.text)


if __name__ == "__main__":
    unittest.main()
