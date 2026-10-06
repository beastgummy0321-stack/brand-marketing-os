"""app/tests/test_ads_plan.py — F03-I06 falsifiers: adopting a strategy writes group daily
budgets that sum exactly to `budget.daily_of(budget_planned, days)` even on an awkward split
(proves `budget.split()`'s remainder rule, not a naive `total / groups`); adopt rounds
`budget_planned` to `total_of(Σ group daily, days)` (F48 Contract M) and a later group edit leaves
it unchanged; every ad carries all seven coordinates and a name
unique inside the campaign; adopting twice is refused; editing a bound group's budget writes
exactly one `ads_action` row (unbound edits write none); a budget raise above the brand's
approved `max_daily_amount` is refused before anything is written.
"""

import datetime
import json
import unittest
from unittest import mock

import app.shared.web as web
from app.ads import plan, planner_context
from app.ads import repository as ads_repo
from app.brand_intelligence import repository as bi_repo
from app.core import approval as approval_mod
from app.core import db as coredb
from app.llm import gateway, providers
from app.tests.test_ads_strategy_decision import bind_fixture, fixture_provider

ACTOR = "測試員"
OFFERS_HEADER = planner_context.OFFERS_HEADER


def _fake(rendered_output: str) -> providers.FakeProvider:
    return fixture_provider(rendered_output)


def _coordinates(tag: str) -> dict:
    return {
        "audience": f"aud_{tag}", "pain": f"pain_{tag}", "angle": f"angle_{tag}",
        "hook": f"hook_{tag}", "proof": f"proof_{tag}", "offer": "none",
        "format": f"format_{tag}",
    }


_VALID_PLAN_REPLY = json.dumps({
    "groups": [
        {"role": "new", "name": "新客組", "ads": [
            {"name": "新客-廣告一", "coordinates": _coordinates("new1"),
             "scene": "上班族午休在辦公室滑手機找點心"},
        ]},
        {"role": "retarget", "name": "再行銷組", "ads": [
            {"name": "再行銷-廣告一", "coordinates": _coordinates("rt1"),
             "scene": "看過商品頁的人晚上在家猶豫要不要下單"},
        ]},
        {"role": "explore", "name": "探索組", "ads": [
            {"name": "探索-廣告一", "coordinates": _coordinates("ex1"),
             "scene": "健身房的人運動完在櫃檯看補給品"},
        ]},
    ],
}, ensure_ascii=False)


class PlanTestBase(unittest.TestCase):
    def setUp(self):
        self.org_id = coredb.DEV_ORG_ID
        self.brand = bi_repo.create_brand(
            web.conn, org_id=self.org_id, name="測試品牌：投放中心展開", client_name=None,
            actor=ACTOR,
        )
        self.brand_id = self.brand["id"]
        self._orig_provider = plan.PROVIDER

    def tearDown(self):
        plan.PROVIDER = self._orig_provider

    def _create_adopted_campaign(
        self, *, budget_planned: float = 30001, start_date: str = "2026-10-01",
        end_date: str = "2026-10-14", platform: str | None = None,
    ) -> dict:
        """14 天（含頭尾）、50／30／20 的角色分配——刻意選 30001／14 這種除不整的數字：
        naive `total / groups` 會漏掉餘數，`budget.split()` 才會精準加總（Done 第一句）。"""
        allocation = [
            {"role": "new", "label": "新客", "pct": 50, "rationale": None},
            {"role": "retarget", "label": "再行銷", "pct": 30, "rationale": None},
            {"role": "explore", "label": "探索", "pct": 20, "rationale": None},
        ]
        campaign = {
            "name": "測試 Campaign", "goal_text": "幫產品衝購買",
            "objective": "購買", "target_cost": 300,
            "start_date": start_date, "end_date": end_date, "status": "draft",
            "budget_planned": budget_planned, "budget_scenario": "recommended",
            "budget_basis_json": {"strategy": {"allocation": allocation}},
        }
        if platform is not None:
            campaign["constraints_json"] = {"platform": platform}
        return ads_repo.create_campaign(web.conn, self.org_id, self.brand_id, campaign,
                                         created_by=ACTOR)

    def _adopt(self, campaign_id: str) -> dict:
        campaign = ads_repo.get_campaign(web.conn, self.org_id, self.brand_id, campaign_id)
        decision = campaign["budget_basis_json"]["strategy"].get("decision")
        if not decision:
            try:
                reply = json.loads(plan.PROVIDER.response.output_text)
            except (AttributeError, ValueError):
                reply = None
            revision = bind_fixture(web.conn, self.org_id, self.brand_id, campaign_id, reply)
        else:
            revision = decision["revision"]
        return plan.adopt_strategy(
            web.conn, self.org_id, self.brand_id, campaign_id, actor=ACTOR,
            expected_revision=revision, operation_id=f"fixture-{campaign_id}-{campaign['status']}",
        )

    def _assert_refusal(self, exc: Exception, code: str) -> None:
        """F50 Contract J: the refusal names its rule, keeps `delivery_plan_failed` as `str()`,
        and is written on the judged task row."""
        assert isinstance(exc, plan.PlannerRefused)
        reason = plan.REFUSALS[code]
        self.assertEqual((str(exc), exc.code, exc.reason), ("delivery_plan_failed", code, reason))
        row = gateway.get_task(web.conn, exc.task_id)
        assert row is not None
        self.assertEqual((row["error_code"], row["error"]),
                         ("program_refused", f"{code}: {reason}"))


class GroupBudgetsSumExactlyTest(PlanTestBase):
    def test_awkward_split_sums_exactly_to_rounded_daily_total(self):
        campaign = self._create_adopted_campaign()
        plan.PROVIDER = _fake(_VALID_PLAN_REPLY)

        detail = self._adopt(campaign["id"])

        # F48 Contract M: `floor(30001 / 14)` = 2142 -- 50/30/20 floors to 1071／642／428, the +1
        # remainder goes to the largest share.
        expected_daily_total = 2142
        group_budgets = [float(g["daily_budget"]) for g in detail["groups"]]
        self.assertEqual(sum(group_budgets), expected_daily_total)
        self.assertEqual(len(detail["groups"]), 3)
        self.assertEqual(detail["status"], "ready")


class BudgetPlannedNeverRewrittenTest(PlanTestBase):
    def test_adopt_rounds_budget_planned_and_a_later_group_edit_leaves_it(self):
        campaign = self._create_adopted_campaign()
        plan.PROVIDER = _fake(_VALID_PLAN_REPLY)
        detail = self._adopt(campaign["id"])
        # F48 Contract M: adopt rounds the total -- 2142 a day x 14 days.
        self.assertEqual(float(detail["budget_planned"]), 29988)
        self.assertEqual(float(detail["budget_total"]), float(detail["budget_planned"]))

        group = detail["groups"][0]
        plan.update_group(
            web.conn, self.org_id, self.brand_id, group["id"],
            {"daily_budget": float(group["daily_budget"]) + 10}, actor=ACTOR,
        )
        reloaded = ads_repo.campaign_detail(web.conn, self.org_id, self.brand_id, campaign["id"])
        self.assertEqual(float(reloaded["budget_planned"]), 29988)


class AdCoordinatesAndNamesTest(PlanTestBase):
    def test_every_ad_has_seven_coordinates_and_a_unique_name(self):
        campaign = self._create_adopted_campaign()
        plan.PROVIDER = _fake(_VALID_PLAN_REPLY)

        detail = self._adopt(campaign["id"])

        names = []
        for group in detail["groups"]:
            for ad in group["ads"]:
                names.append(ad["name"])
                for dim in ("audience", "pain", "angle", "hook", "proof", "offer", "format"):
                    self.assertTrue(ad[f"{dim}_key"], f"{dim} 不該是空的")
        self.assertEqual(len(names), len(set(names)))


class DeclaredPlatformDrivesChannelKeyTest(PlanTestBase):
    def test_adopt_uses_the_campaigns_declared_platform_not_meta(self):
        """F05-I05：`constraints_json.platform = "google_ads"` 的 Campaign 採用策略後，
        投放組的 channel_key 是 google_ads，不是寫死的 meta（§0「不預設」）。"""
        campaign = self._create_adopted_campaign(platform="google_ads")
        plan.PROVIDER = _fake(_VALID_PLAN_REPLY)

        detail = self._adopt(campaign["id"])

        self.assertTrue(detail["groups"])
        for group in detail["groups"]:
            self.assertEqual(group["channel_key"], "google_ads")


class AdoptTwiceRefusedTest(PlanTestBase):
    def test_adopting_a_second_time_is_refused(self):
        campaign = self._create_adopted_campaign()
        plan.PROVIDER = _fake(_VALID_PLAN_REPLY)
        self._adopt(campaign["id"])

        with self.assertRaises(ValueError) as ctx:
            self._adopt(campaign["id"])
        self.assertEqual(str(ctx.exception), "strategy_changed")


class LastGroupDeleteRefusedTest(PlanTestBase):
    def test_deleting_the_last_group_is_refused(self):
        """Adopt refuses a second run, so an adopted plan with zero groups is a dead end."""
        campaign = self._create_adopted_campaign()
        plan.PROVIDER = _fake(_VALID_PLAN_REPLY)
        groups = self._adopt(campaign["id"])["groups"]

        for group in groups[:-1]:
            plan.delete_group(web.conn, self.org_id, self.brand_id, group["id"])
        with self.assertRaises(ValueError) as ctx:
            plan.delete_group(web.conn, self.org_id, self.brand_id, groups[-1]["id"])
        self.assertEqual(str(ctx.exception), "last_group")
        self.assertIsNotNone(ads_repo.get_group(web.conn, self.org_id, self.brand_id,
                                                groups[-1]["id"]))


class GroupEditActionTraceTest(PlanTestBase):
    def test_editing_a_bound_group_writes_one_action_unbound_writes_none(self):
        campaign = self._create_adopted_campaign()
        plan.PROVIDER = _fake(_VALID_PLAN_REPLY)
        detail = self._adopt(campaign["id"])
        bound_group, unbound_group = detail["groups"][0], detail["groups"][1]

        web.conn.execute(
            "UPDATE ads_delivery_group SET local_state = 'bound' WHERE id = %s",
            (bound_group["id"],),
        )
        web.conn.commit()

        before_budget = float(bound_group["daily_budget"])
        after_budget = before_budget + 5
        plan.update_group(
            web.conn, self.org_id, self.brand_id, bound_group["id"],
            {"daily_budget": after_budget}, actor=ACTOR,
        )
        actions = list(web.conn.execute(
            "SELECT * FROM ads_action WHERE target_id = %s", (bound_group["id"],),
        ))
        self.assertEqual(len(actions), 1)
        action = dict(actions[0])
        self.assertEqual(action["kind"], "budget")
        self.assertEqual(action["sync_state"], "pending_manual")
        self.assertEqual(float(action["before_json"]["daily_budget"]), before_budget)
        self.assertEqual(float(action["after_json"]["daily_budget"]), after_budget)

        plan.update_group(
            web.conn, self.org_id, self.brand_id, unbound_group["id"],
            {"name": "改個名字"}, actor=ACTOR,
        )
        unbound_actions = list(web.conn.execute(
            "SELECT * FROM ads_action WHERE target_id = %s", (unbound_group["id"],),
        ))
        self.assertEqual(len(unbound_actions), 0)


class GroupDateOrderTest(PlanTestBase):
    """F47-I06 (Contract A, drill-10 V5): a group's end never lands before its start; when only
    one side is patched the stored other side counts. Nothing is written on a refusal."""

    def test_patching_only_the_end_checks_it_against_the_stored_start(self):
        campaign = self._create_adopted_campaign()
        plan.PROVIDER = _fake(_VALID_PLAN_REPLY)
        group = self._adopt(campaign["id"])["groups"][0]
        plan.update_group(web.conn, self.org_id, self.brand_id, group["id"],
                          {"start_date": "2026-10-05"}, actor=ACTOR)

        with self.assertRaises(ValueError) as ctx:
            plan.update_group(web.conn, self.org_id, self.brand_id, group["id"],
                              {"end_date": "2026-10-04"}, actor=ACTOR)
        self.assertEqual(str(ctx.exception), "dates_reversed")
        stored = ads_repo.get_group(web.conn, self.org_id, self.brand_id, group["id"])
        self.assertIsNone(stored["end_date"])

        plan.update_group(web.conn, self.org_id, self.brand_id, group["id"],
                          {"end_date": "2026-10-05"}, actor=ACTOR)  # same day is fine

    def test_create_refuses_a_reversed_pair_and_the_route_says_why(self):
        campaign = self._create_adopted_campaign()
        plan.PROVIDER = _fake(_VALID_PLAN_REPLY)
        self._adopt(campaign["id"])
        with self.assertRaises(ValueError) as ctx:
            plan.create_group(web.conn, self.org_id, self.brand_id, campaign["id"], name="新組",
                              role="new", daily_budget=100, start_date="2026-10-10",
                              end_date="2026-10-01")
        self.assertEqual(str(ctx.exception), "dates_reversed")
        web.conn.commit()

        from fastapi.testclient import TestClient

        from app import main

        response = TestClient(main.app).post(
            f"/api/ads/brands/{self.brand_id}/campaigns/{campaign['id']}/groups",
            json={"name": "新組", "role": "new", "daily_budget": 100,
                  "start_date": "2026-10-10", "end_date": "2026-10-01"},
        )
        self.assertEqual(response.status_code, 400, response.text)
        self.assertEqual(response.json()["error"]["message"], "結束日不能早於開始日。")


class GroupInsideCampaignWindowTest(PlanTestBase):
    """F50 Contract I (c1-08, R6 A9): an ad set's dates lie inside its campaign's dates
    (`input_rules.date_within`); a group dated before the campaign is a 400
    `group_dates_outside` naming the window, and nothing is written."""

    def test_a_group_dated_outside_the_campaign_is_refused_with_the_window(self):
        campaign = self._create_adopted_campaign()
        plan.PROVIDER = _fake(_VALID_PLAN_REPLY)
        group = self._adopt(campaign["id"])["groups"][0]
        detail = ads_repo.get_campaign(web.conn, self.org_id, self.brand_id, campaign["id"])
        start, end = detail["start_date"], detail["end_date"]
        before = (start - datetime.timedelta(days=1)).isoformat()
        sentence = f"投放組日期要在活動期間（{start.isoformat()}～{end.isoformat()}）內。"

        with self.assertRaises(plan.GroupDatesOutside) as ctx:
            plan.update_group(web.conn, self.org_id, self.brand_id, group["id"],
                              {"start_date": before}, actor=ACTOR)
        self.assertEqual(str(ctx.exception), "group_dates_outside")
        self.assertEqual(ctx.exception.sentence, sentence)
        stored = ads_repo.get_group(web.conn, self.org_id, self.brand_id, group["id"])
        self.assertIsNone(stored["start_date"])
        web.conn.commit()

        from fastapi.testclient import TestClient

        from app import main

        client = TestClient(main.app)
        created = client.post(
            f"/api/ads/brands/{self.brand_id}/campaigns/{campaign['id']}/groups",
            json={"name": "新組", "role": "new", "daily_budget": 100, "start_date": before},
        )
        self.assertEqual(created.status_code, 400, created.text)
        self.assertEqual(created.json()["error"],
                         {"code": "group_dates_outside", "message": sentence, "details": None})
        after = (end + datetime.timedelta(days=1)).isoformat()
        patched = client.patch(f"/api/ads/brands/{self.brand_id}/groups/{group['id']}",
                               json={"end_date": after})
        self.assertEqual(patched.status_code, 400, patched.text)
        self.assertEqual(patched.json()["error"]["code"], "group_dates_outside")
        inside = client.patch(f"/api/ads/brands/{self.brand_id}/groups/{group['id']}",
                              json={"start_date": start.isoformat(), "end_date": end.isoformat()})
        self.assertEqual(inside.status_code, 200, inside.text)


class BudgetCeilingTest(PlanTestBase):
    def test_a_raise_above_the_approved_ceiling_is_refused(self):
        campaign = self._create_adopted_campaign()  # daily_total 2144 > 核准上限 100
        approval_mod.approve(
            web.conn, org_id=self.org_id, brand_id=self.brand_id,
            scope_type=plan.APPROVAL_SCOPE_TYPE, scope_ref=campaign["id"],
            content_hash="whatever", amount=100, max_daily_amount=100, actor=ACTOR,
        )
        plan.PROVIDER = _fake(_VALID_PLAN_REPLY)

        with self.assertRaises(ValueError) as ctx:
            self._adopt(campaign["id"])
        self.assertEqual(str(ctx.exception), "budget_exceeds_approval")

        groups = list(web.conn.execute(
            "SELECT id FROM ads_delivery_group WHERE campaign_id = %s", (campaign["id"],),
        ))
        self.assertEqual(groups, [])  # 拒絕在寫任何列之前發生


class CalendarInDeliveryPlanPromptTest(PlanTestBase):
    """F33-I02（Contract Q）：展開投放組的 prompt 也帶【投放期間內的行事曆】——預設 Campaign
    2026-10-01～10-14 跨國慶日；已採用的角色分配那幾行（Contract P）不動。"""

    def _prompt(self, **overrides) -> str:
        campaign = self._create_adopted_campaign(**overrides)
        provider = _fake(_VALID_PLAN_REPLY)
        plan.PROVIDER = provider
        self._adopt(campaign["id"])
        return provider.calls[0]["messages"][0]["content"]

    def test_prompt_lists_the_calendar_rows_overlapping_the_period(self):
        prompt = self._prompt()
        self.assertIn("【投放期間內的行事曆】\n", prompt)
        self.assertIn("國慶日", prompt)
        self.assertNotIn("雙 11 檔", prompt)
        self.assertIn("- new（新客）：50%", prompt)
        # 任務檔前面也提到這個標題，取最後一次出現的位置才是真正的段落。
        self.assertLess(
            prompt.index("- explore（探索）：20%"), prompt.rindex("【投放期間內的行事曆】"),
        )

    def test_period_outside_the_table_gets_the_coverage_note(self):
        prompt = self._prompt(start_date="2028-03-01", end_date="2028-03-14")
        self.assertIn("【投放期間內的行事曆】\n期間內沒有登記的假日、考季或檔期\n", prompt)
        self.assertIn("2028 年的假日與考季沒有資料，不要假設沒有活動", prompt)


_RANKED_HEADER = "【上幾期的排名（程式排的；每筆＝花費÷成交）】"
_RANKED_EMPTY = "【上幾期的排名】（還沒有結案過的廣告）"


def _ranked_scope(*, verdict: str, rank: int, of: int, sales: int, spend: int, group: str | None,
                  angle: str, few: int = 0) -> str:
    """The `v=2` scope the closeout writes (`learning_rank.scope`; proven in
    test_ads_coordinate_learning.py)."""
    cpr = round(spend / sales) if sales else "none"
    keys = {**_coordinates("last"), "angle": angle}
    return (
        f"coord；v=2；verdict={verdict}；rank={rank}；of={of}；sales={sales}；spend={spend}"
        f"；cpr={cpr}；cap=300；few={few}；group={group or 'none'}；"
        + "；".join(f"{dim}={keys[dim]}"
                   for dim in ("audience", "pain", "angle", "hook", "proof", "offer", "format"))
        + "；cur=TWD"
    )


def _seed_closed(org_id: str, brand_id: str, rows: list[dict], *,
                 product_id: str | None = None, name: str = "上一期 Campaign") -> list[dict]:
    """A closed campaign with one ad and one ranked learning row per `rows` item."""
    closed = ads_repo.create_campaign(web.conn, org_id, brand_id, {
        "name": name, "goal_text": "上一期衝購買", "objective": "購買",
        "target_cost": 300, "start_date": "2026-09-01", "end_date": "2026-09-14",
        "status": "closed",
        # F48 Contract M: a non-draft campaign's sell-way is fixed (no PATCH after adoption).
        "context_json": {"product_ids": [product_id]} if product_id is not None else {},
    }, created_by=ACTOR)
    web.conn.execute("UPDATE ads_campaign SET closed_at = now() WHERE id = %s", (closed["id"],))
    group = plan.create_group(
        web.conn, org_id, brand_id, closed["id"], name="上一期新客組", role="new",
        daily_budget=500,
    )
    learnings = []
    for row in rows:
        ad = plan.create_ad(
            web.conn, org_id, brand_id, closed["id"], group["id"], name=row["name"],
            coordinates={**_coordinates("last"), "angle": row["angle"]},
        )
        scope_fields = {k: v for k, v in row.items() if k != "name"}
        learnings.append(bi_repo.record_learning(
            web.conn, brand_id, actor=ACTOR, learning_text=row["name"],
            applicability_scope=_ranked_scope(**scope_fields),
            confidence="observed", sample_size="高",
            source_cycle_id=f"{closed['id']}:{ad['id']}", source_track="coordinate",
        ))
    web.conn.commit()
    return learnings


class RankedLearningsInDeliveryPlanPromptTest(PlanTestBase):
    """F46-I04 (Contract G): 展開投放組的 prompt 帶程式排好的【上幾期的排名】
    （取代【座標成績表】），位置在行事曆之後、詞彙表之前（詞彙表永遠最後）；空品牌就寫「還沒有結案過的廣告」；用到的
    學習列 id 進 `knowledge_item_ids`。"""

    def _prompt(self) -> tuple[str, list]:
        campaign = self._create_adopted_campaign()
        provider = _fake(_VALID_PLAN_REPLY)
        plan.PROVIDER = provider
        with mock.patch.object(plan.gateway, "run_task", wraps=plan.gateway.run_task) as spy:
            self._adopt(campaign["id"])
        return (provider.calls[0]["messages"][0]["content"],
                spy.call_args.kwargs["context"].knowledge_item_ids)

    def test_section_sits_between_the_calendar_and_the_vocabulary(self):
        (learning,) = _seed_closed(self.org_id, self.brand_id, [
            {"name": "上一期-免運", "verdict": "keep", "rank": 1, "of": 1, "sales": 6,
             "spend": 1200, "group": None, "angle": "angle_last"},
        ])
        prompt, knowledge_item_ids = self._prompt()
        self.assertIn(_RANKED_HEADER, prompt)
        self.assertIn(
            "- 上一期 Campaign第 1／1 名｜留下｜顧客群 未指定｜「上一期-免運」｜每筆 200｜賣 6 筆"
            "｜花 1,200｜aud_last（audience=aud_last）、",
            prompt,
        )
        self.assertIn(learning["id"], knowledge_item_ids)
        # 任務檔前面也提到【投放期間內的行事曆】與【上幾期的排名】，取最後一次出現的才是段落本身。
        calendar_at = prompt.rindex("【投放期間內的行事曆】")
        board_at = prompt.rindex(_RANKED_HEADER)
        vocabulary_at = prompt.rindex("【座標詞彙")
        self.assertLess(calendar_at, board_at)
        self.assertLess(board_at, vocabulary_at)
        self.assertNotIn(_RANKED_EMPTY, prompt)
        self.assertNotIn("座標成績表", prompt)

    def test_empty_brand_says_there_is_nothing_ranked(self):
        prompt, _ = self._prompt()
        self.assertIn(_RANKED_EMPTY, prompt)
        self.assertNotIn(_RANKED_HEADER, prompt)
        self.assertLess(prompt.rindex("【投放期間內的行事曆】"), prompt.rindex(_RANKED_EMPTY))
        self.assertLess(prompt.rindex(_RANKED_EMPTY), prompt.rindex("【座標詞彙"))

    def test_the_department_file_builds_on_kept_and_leaves_replaced(self):
        text = plan.DEPARTMENT_PATH.read_text(encoding="utf-8")
        # F48 Contract K: 留下 ads are carried in by the program; the model writes the rest.
        self.assertNotIn("至少要有一支廣告沿用一個「留下」的顧客群＋角度", text)
        self.assertIn("【已沿用的廣告】是上一期「留下」的廣告，程式已經連同圖片和文案放進投放組",
                      text)
        self.assertIn("有寫「請再規劃 K 則」時，你的回覆總共寫 K 則廣告", text)
        self.assertIn("整份計畫的廣告超過「最多」，整份回覆會被退回", text)
        self.assertIn("廣告名稱、`scene` 都不能出現這些字", text)
        self.assertIn("「換掉」的顧客群＋角度不要原樣再用", text)
        self.assertIn("標「樣本少」的留下只賣了幾筆，值得再驗一次", text)
        self.assertNotIn("座標成績表", text)


def _pair_reply(pairs: dict) -> str:
    """Three roles, one ad each; `pairs` maps role -> (customer_group number, angle key)."""
    groups = []
    for role in ("new", "retarget", "explore"):
        number, angle = pairs[role]
        coords = {**_coordinates(role), "angle": angle}
        groups.append({"role": role, "name": f"{role} 組", "ads": [{
            "name": f"{role}-廣告", "coordinates": coords, "customer_group": number,
            "scene": f"{role} 這支廣告的受眾晚上在家滑手機",
        }]})
    return json.dumps({"groups": groups}, ensure_ascii=False)


class RankedLearningGateTest(PlanTestBase):
    """F46-I04 (Contract G gate, after the customer-group checks): a plan re-running a 換掉
    (customer group, angle) of the newest closed campaign, or reusing none of the 留下 pairs, is
    refused with nothing written; a plan reusing a 留下 pair with other coordinates changed
    passes. Pairs count only for groups listed this time."""

    def setUp(self):
        super().setUp()
        product = bi_repo.create_product(web.conn, self.brand_id, name="三盒組", actor=ACTOR)
        self.groups = bi_repo.save_customer_groups(web.conn, self.brand_id, product["id"], [
            {"who": "學生備考", "pain_keys": ["effort"]},
            {"who": "通勤上班族", "pain_keys": ["experience"]},
        ], actor=ACTOR)
        students, commuters = self.groups[0]["id"], self.groups[1]["id"]
        _seed_closed(self.org_id, self.brand_id, [
            {"name": "考前一週・書包一盒", "verdict": "keep_relative", "rank": 1, "of": 2,
             "sales": 6, "spend": 3330, "group": students, "angle": "box"},
            {"name": "通勤族・地鐵十分鐘", "verdict": "replace", "rank": 2, "of": 2, "sales": 2,
             "spend": 3286, "group": commuters, "angle": "metro", "few": 1},
        ], product_id=product["id"])
        self.campaign = self._create_adopted_campaign()
        ads_repo.update_campaign(web.conn, self.org_id, self.brand_id, self.campaign["id"],
                                 {"product_ids": [product["id"]]})
        web.conn.commit()

    def _adopt_reply(self, reply: str) -> dict:
        plan.PROVIDER = _fake(reply)
        return self._adopt(self.campaign["id"])

    def _assert_refused(self, reply: str) -> None:
        with self.assertRaises(ValueError) as ctx:
            self._adopt_reply(reply)
        self._assert_refusal(ctx.exception, "replace_rerun")
        reloaded = ads_repo.campaign_detail(
            web.conn, self.org_id, self.brand_id, self.campaign["id"])
        self.assertEqual(reloaded["status"], "draft")
        self.assertEqual(reloaded["groups"], [])

    def test_the_prompt_numbers_the_kept_row_by_this_campaigns_groups(self):
        provider = _fake(_pair_reply(
            {"new": (1, "box"), "retarget": (2, "fresh"), "explore": (1, "other")},
        ))
        plan.PROVIDER = provider
        self._adopt(self.campaign["id"])
        prompt = provider.calls[0]["messages"][0]["content"]
        self.assertIn(
            "｜留下・相對最好，仍高於上限｜顧客群 1｜「考前一週・書包一盒」｜每筆 555", prompt,
        )
        self.assertIn("｜換掉・樣本少｜顧客群 2｜「通勤族・地鐵十分鐘」｜每筆 1,643", prompt)

    def test_reusing_a_replaced_group_and_angle_is_refused(self):
        self._assert_refused(_pair_reply(
            {"new": (1, "box"), "retarget": (2, "metro"), "explore": (1, "other")},
        ))

    def test_a_plan_can_explicitly_test_when_a_kept_ad_has_no_reusable_creative(self):
        # Contract S: an unavailable original is not silently copied as a missing-material ad.
        detail = self._adopt_reply(_pair_reply(
            {"new": (2, "box"), "retarget": (1, "fresh"), "explore": (2, "other")},
        ))
        self.assertEqual(detail["status"], "ready")
        names = [ad["name"] for g in detail["groups"] for ad in g["ads"]]
        self.assertNotIn("考前一週・書包一盒", names)
        self.assertIn("new-廣告", names)
        self.assertNotIn("通勤族・地鐵十分鐘", names)  # 換掉 is never carried

    def test_a_kept_pair_with_other_coordinates_changed_passes(self):
        detail = self._adopt_reply(_pair_reply(
            {"new": (1, "box"), "retarget": (2, "fresh"), "explore": (1, "other")},
        ))
        self.assertEqual(detail["status"], "ready")
        by_name = {ad["name"]: ad for g in detail["groups"] for ad in g["ads"]}
        self.assertEqual(by_name["new-廣告"]["angle_key"], "box")
        self.assertEqual(by_name["new-廣告"]["audience_key"], "aud_new")
        self.assertEqual(by_name["new-廣告"]["customer_group_id"], self.groups[0]["id"])

    def test_pairs_of_groups_not_listed_this_time_do_not_count(self):
        # A campaign of another product lists other groups: the old pairs neither bind nor block.
        other = bi_repo.create_product(web.conn, self.brand_id, name="單盒", actor=ACTOR)
        bi_repo.save_customer_groups(web.conn, self.brand_id, other["id"], [
            {"who": "送禮的人", "pain_keys": ["identity"]},
        ], actor=ACTOR)
        campaign = self._create_adopted_campaign()
        ads_repo.update_campaign(web.conn, self.org_id, self.brand_id, campaign["id"],
                                 {"product_ids": [other["id"]]})
        web.conn.commit()
        plan.PROVIDER = _fake(_pair_reply(
            {"new": (1, "metro"), "retarget": (1, "x"), "explore": (1, "y")},
        ))
        detail = self._adopt(campaign["id"])
        self.assertEqual(detail["status"], "ready")


class CustomerGroupsInDeliveryPlanPromptTest(PlanTestBase):
    """F43-I02: 【這個賣法的顧客】 sits after the scoreboard and before the vocabulary (the
    vocabulary stays last); its group ids reach the task's `knowledge_item_ids`."""

    def _adopt_capturing(
        self, campaign_id: str, reply: str = _VALID_PLAN_REPLY,
    ) -> tuple[str, list]:
        provider = _fake(reply)
        plan.PROVIDER = provider
        with mock.patch.object(plan.gateway, "run_task", wraps=plan.gateway.run_task) as spy:
            self._adopt(campaign_id)
        context = spy.call_args.kwargs["context"]
        return provider.calls[0]["messages"][0]["content"], context.knowledge_item_ids

    def test_groups_sit_before_the_vocabulary_and_reach_the_knowledge_items(self):
        product = bi_repo.create_product(web.conn, self.brand_id, name="夜跑背心", actor=ACTOR)
        groups = bi_repo.save_customer_groups(web.conn, self.brand_id, product["id"], [
            {"who": "下班後夜跑的上班族", "pain_keys": ["uncertainty"],
             "quote": "晚上跑步車子看不到我", "when_used": "下班後在河濱夜跑"},
            {"who": "帶小孩散步的爸媽", "pain_keys": ["effort"]},
        ], actor=ACTOR)
        campaign = self._create_adopted_campaign()
        ads_repo.update_campaign(web.conn, self.org_id, self.brand_id, campaign["id"],
                                 {"product_ids": [product["id"]]})

        # F46 Contract A: with groups listed every ad names one (第 1 群 here).
        prompt, knowledge_item_ids = self._adopt_capturing(
            campaign["id"], _group_reply({"new": [1], "retarget": [1], "explore": [1]}),
        )

        self.assertIn(
            "第 1 群：下班後夜跑的上班族｜煩惱：怕買錯（pain=uncertainty）"
            "｜顧客會說：晚上跑步車子看不到我｜什麼時候用：下班後在河濱夜跑", prompt,
        )
        # F48-I06: the planner_context order -- product, forbidden, customers, offers, ranking.
        customers_at = prompt.rindex("【這個賣法的顧客】")
        self.assertLess(prompt.rindex("【不能講】"), customers_at)
        self.assertLess(customers_at, prompt.rindex(_RANKED_EMPTY))
        self.assertLess(customers_at, prompt.rindex("【座標詞彙"))
        for group in groups:
            self.assertIn(group["id"], knowledge_item_ids)

    def test_campaign_whose_product_has_no_groups_says_so(self):
        product = bi_repo.create_product(web.conn, self.brand_id, name="夜跑背心", actor=ACTOR)
        campaign = self._create_adopted_campaign()
        ads_repo.update_campaign(web.conn, self.org_id, self.brand_id, campaign["id"],
                                 {"product_ids": [product["id"]]})

        prompt, _ = self._adopt_capturing(campaign["id"])

        self.assertIn("【這個賣法的顧客】（這個商品還沒有建顧客群）", prompt)

    def test_the_department_file_takes_pain_and_scene_from_a_listed_group(self):
        text = plan.DEPARTMENT_PATH.read_text(encoding="utf-8")
        self.assertIn("每支廣告要填 `customer_group`＝它寫給的那一群的編號", text)
        self.assertIn("`pain` 要從那一群的煩惱", text)
        self.assertIn("`scene` 是那一群", text)
        self.assertIn("同一個投放組的廣告都寫給同一群", text)
        self.assertIn("廣告總數不要超過照片張數", text)
        self.assertIn('"customer_group": 1', text)


def _group_reply(bindings: dict, pains: dict | None = None) -> str:
    """Three roles; `bindings` maps role -> one `customer_group` value per ad (a role's list
    length = its ad count; `...` leaves the key out). `pains` maps (role, ad index) -> pain key
    (default `pain_<role><n>`). Each ad gets its own audience and scene."""
    groups = []
    for role in ("new", "retarget", "explore"):
        ads = []
        for n, number in enumerate(bindings.get(role, [...]), start=1):
            coords = _coordinates(f"{role}{n}")
            if pains and (role, n) in pains:
                coords["pain"] = pains[(role, n)]
            ad = {"name": f"{role}-廣告{n}", "coordinates": coords,
                  "scene": f"{role} 第 {n} 支廣告的受眾晚上在家滑手機"}
            if number is not ...:
                ad["customer_group"] = number
            ads.append(ad)
        groups.append({"role": role, "name": f"{role} 組", "ads": ads})
    return json.dumps({"groups": groups}, ensure_ascii=False)


class CustomerGroupBindingTest(PlanTestBase):
    """F46-I01 (Contract A): with customer groups listed, every ad names 第 N 群 (1..N), its pain
    is one of that group's pains when that set meets the menu's pain keys, and one delivery group
    speaks to one customer group; any failure refuses the whole plan with nothing written. No
    group listed -> the key is ignored and `customer_group_id` is NULL."""

    def setUp(self):
        super().setUp()
        product = bi_repo.create_product(web.conn, self.brand_id, name="夜跑背心", actor=ACTOR)
        self.groups = bi_repo.save_customer_groups(web.conn, self.brand_id, product["id"], [
            {"who": "下班後夜跑的上班族", "pain_keys": ["uncertainty"],
             "quote": "晚上跑步車子看不到我", "when_used": "下班後在河濱夜跑"},
            {"who": "帶小孩散步的爸媽", "pain_keys": ["effort"]},
        ], actor=ACTOR)
        self.campaign = self._create_adopted_campaign()
        ads_repo.update_campaign(web.conn, self.org_id, self.brand_id, self.campaign["id"],
                                 {"product_ids": [product["id"]]})

    def _add_pain_vocabulary(self, *keys: str) -> None:
        for key in keys:
            web.conn.execute(
                "INSERT INTO brand_coordinate(id,org_id,brand_id,dimension,key,label) "
                "VALUES(%s,%s,%s,'pain',%s,%s)",
                (coredb.new_id("crd"), self.org_id, self.brand_id, key, f"痛點 {key}"),
            )
        web.conn.commit()

    def _adopt_reply(self, reply: str, campaign_id: str | None = None) -> dict:
        plan.PROVIDER = _fake(reply)
        return self._adopt(campaign_id or self.campaign["id"])

    def _assert_refused(self, reply: str) -> None:
        with self.assertRaises(ValueError) as ctx:
            self._adopt_reply(reply)
        self._assert_refusal(ctx.exception, "group_unbound")
        reloaded = ads_repo.campaign_detail(
            web.conn, self.org_id, self.brand_id, self.campaign["id"])
        self.assertEqual(reloaded["status"], "draft")  # nothing was written
        self.assertEqual(reloaded["groups"], [])

    def test_valid_group_numbers_store_the_id_and_the_snapshot(self):
        self._add_pain_vocabulary("uncertainty", "effort")
        detail = self._adopt_reply(_group_reply(
            {"new": [1, 1], "retarget": [2], "explore": [1]},
            pains={("new", 1): "uncertainty", ("new", 2): "uncertainty",
                   ("retarget", 1): "effort", ("explore", 1): "uncertainty"},
        ))
        by_name = {ad["name"]: ad for g in detail["groups"] for ad in g["ads"]}
        first, second = self.groups[0], self.groups[1]
        self.assertEqual(by_name["new-廣告1"]["customer_group_id"], first["id"])
        self.assertEqual(by_name["new-廣告2"]["customer_group_id"], first["id"])
        self.assertEqual(by_name["retarget-廣告1"]["customer_group_id"], second["id"])
        stored = ads_repo.get_ad(
            web.conn, self.org_id, self.brand_id, by_name["retarget-廣告1"]["id"])
        assert stored is not None
        self.assertEqual(stored["customer_group_id"], second["id"])
        snapshot = stored["coordinates_snapshot_json"]
        self.assertEqual(
            snapshot["customer_group"], {"id": second["id"], "who": "帶小孩散步的爸媽"},
        )
        self.assertEqual(snapshot["pain"]["key"], "effort")
        self.assertEqual(stored["pain_key"], "effort")

    def test_missing_or_out_of_range_or_non_integer_number_is_refused(self):
        for bad in (..., 0, 3, -1, "1", 1.0, True, None):
            with self.subTest(bad=bad):
                self._assert_refused(_group_reply({"new": [bad], "retarget": [2], "explore": [1]}))

    def test_pain_outside_the_groups_pains_is_refused(self):
        self._add_pain_vocabulary("uncertainty", "effort")
        self._assert_refused(_group_reply(
            {"new": [1], "retarget": [2], "explore": [1]},
            pains={("new", 1): "effort", ("retarget", 1): "effort",
                   ("explore", 1): "uncertainty"},
        ))

    def test_pain_is_not_checked_when_the_groups_pains_are_not_on_the_menu(self):
        # This brand's menu has no pain rows at all: the group's pains cannot be met, so the
        # reply's own pain keys stand.
        detail = self._adopt_reply(_group_reply({"new": [1], "retarget": [2], "explore": [1]}))
        pains = {g["role"]: g["ads"][0]["pain_key"] for g in detail["groups"]}
        self.assertEqual(pains["new"], "pain_new1")

    def test_two_customer_groups_inside_one_delivery_group_are_refused(self):
        self._assert_refused(_group_reply({"new": [1, 2], "retarget": [2], "explore": [1]}))

    def test_no_group_listed_ignores_the_key_and_stores_null(self):
        campaign = self._create_adopted_campaign()  # no product -> no 【這個賣法的顧客】 groups
        detail = self._adopt_reply(
            _group_reply({"new": [7], "retarget": ["x"], "explore": [...]}), campaign["id"],
        )
        for group in detail["groups"]:
            for ad in group["ads"]:
                self.assertIsNone(ad["customer_group_id"])
                self.assertNotIn("customer_group", ad["coordinates_snapshot_json"])

    def test_bind_helper_skips_the_pain_check_for_an_empty_menu(self):
        listed = [{"id": "pcg_1", "who": "甲", "pain_keys": ["effort"]}]
        groups = [{"role": "new", "ads": [
            {"coordinates": {"pain": "cost"}, "customer_group": 1},
        ]}]
        self.assertTrue(plan._bind_customer_groups(groups, listed, set()))
        self.assertEqual(groups[0]["ads"][0]["customer_group"]["id"], "pcg_1")
        groups[0]["ads"][0]["customer_group"] = 1
        self.assertFalse(plan._bind_customer_groups(groups, listed, {"effort", "cost"}))


class MaterialsInDeliveryPlanPromptTest(PlanTestBase):
    """F46-I01 (Contract P): 【手上的素材】「照片 N 張、影片 M 支」 sits after the customers and
    before the offers／vocabulary. Photos = active non-logo official assets + ready user assets
    with a non-video mime; videos = ready `video/*` user assets; unready or mime-less ones are
    not counted."""

    def _prompt(self) -> str:
        provider = _fake(_VALID_PLAN_REPLY)
        plan.PROVIDER = provider
        self._adopt(self._create_adopted_campaign()["id"])
        return provider.calls[0]["messages"][0]["content"]

    def _user_asset(self, mime: str, status: str) -> None:
        asset = coredb.new_id("aua")
        web.conn.execute(
            "INSERT INTO ads_user_asset(id,org_id,brand_id,sha256,storage_key,filename,"
            "mime_type,byte_size,status) VALUES(%s,%s,%s,%s,%s,'a.bin',%s,1,%s)",
            (asset, self.org_id, self.brand_id, asset, f"{self.org_id}/{asset}", mime, status),
        )
        web.conn.commit()

    def test_brand_without_assets_prints_zero_and_zero_in_place(self):
        prompt = self._prompt()
        # F48-I06: the capacity line follows the materials (the vocabulary stays last).
        self.assertIn(
            f"\n\n{plan.MATERIALS_HEADER}照片 0 張、影片 0 支\n\n【這期撐得起幾則】", prompt,
        )
        materials_at = prompt.rindex(plan.MATERIALS_HEADER)
        self.assertLess(prompt.rindex("【這個賣法的顧客】"), materials_at)

    def test_counts_photos_and_videos_by_kind_status_and_mime(self):
        for kind in ("product_photo", "lifestyle", "logo"):
            bi_repo.create_official_asset(
                web.conn, self.brand_id, actor=ACTOR, asset_kind=kind,
                storage_key=f"{self.brand_id}/{kind}.png",
            )
        archived = bi_repo.create_official_asset(
            web.conn, self.brand_id, actor=ACTOR, asset_kind="product_photo",
            storage_key=f"{self.brand_id}/old.png",
        )
        web.conn.execute("UPDATE official_asset SET status='archived' WHERE id=%s",
                         (archived["id"],))
        web.conn.commit()
        self._user_asset("image/jpeg", "ready")
        self._user_asset("video/mp4", "ready")
        self._user_asset("video/quicktime", "ready")
        self._user_asset("image/png", "pending")
        self._user_asset("", "ready")

        prompt = self._prompt()

        # 2 official (logo and archived left out) + 1 ready image = 3; 2 ready videos.
        self.assertIn(f"{plan.MATERIALS_HEADER}照片 3 張、影片 2 支", prompt)


def _plan_reply(proof: str, offer: str = "none") -> str:
    def coords(tag: str) -> dict:
        return {**_coordinates(tag), "proof": proof, "offer": offer}
    return json.dumps({"groups": [
        {"role": role, "name": f"{role} 組", "ads": [
            {"name": f"{role}-廣告一", "coordinates": coords(role),
             "scene": f"{role} 受眾晚上在家滑手機看到這支廣告"},
        ]}
        for role in ("new", "retarget", "explore")
    ]}, ensure_ascii=False)


def _scene_reply(scenes: dict, *, audiences: dict | None = None) -> str:
    """Three roles, one ad each. `scenes` maps role -> scene (a missing role leaves the key
    out); `audiences` maps role -> audience key (default: one distinct key per role)."""
    groups = []
    for role in ("new", "retarget", "explore"):
        coords = _coordinates(role)
        if audiences and role in audiences:
            coords["audience"] = audiences[role]
        ad = {"name": f"{role}-廣告一", "coordinates": coords}
        if role in scenes:
            ad["scene"] = scenes[role]
        groups.append({"role": role, "name": f"{role} 組", "ads": [ad]})
    return json.dumps({"groups": groups}, ensure_ascii=False)


_SCENES = {
    "new": "上班族午休在辦公室滑手機找點心",
    "retarget": "看過商品頁的人晚上在家猶豫要不要下單",
    "explore": "健身房的人運動完在櫃檯看補給品",
}


class SceneRuleTest(PlanTestBase):
    """F39-I03 (outcome 3): every ad needs one `scene` of 6–60 chars; ads of different
    audiences must not share a scene; the same audience may. An accepted plan stores the scene
    on `ads_ad.scene` and `campaign_detail` returns it."""

    def _adopt_reply(self, reply: str) -> dict:
        campaign = self._create_adopted_campaign()
        plan.PROVIDER = _fake(reply)
        return self._adopt(campaign["id"])

    def _assert_failed(self, reply: str) -> None:
        with self.assertRaises(ValueError) as ctx:
            self._adopt_reply(reply)
        self._assert_refusal(ctx.exception, "reply_invalid")

    def test_reply_without_a_scene_fails(self):
        self._assert_failed(_scene_reply({k: v for k, v in _SCENES.items() if k != "retarget"}))

    def test_scene_outside_6_to_60_chars_fails(self):
        self._assert_failed(_scene_reply({**_SCENES, "new": "太短了"}))
        self._assert_failed(_scene_reply({**_SCENES, "new": "很長" * 31}))
        self._assert_failed(_scene_reply({**_SCENES, "new": "   "}))

    def test_two_audiences_sharing_one_scene_fails(self):
        self._assert_failed(_scene_reply({**_SCENES, "retarget": _SCENES["new"]}))
        # Exact match after strip: surrounding whitespace does not make it a different scene.
        self._assert_failed(_scene_reply({**_SCENES, "retarget": "  " + _SCENES["new"] + " "}))

    def test_same_audience_sharing_a_scene_is_accepted(self):
        detail = self._adopt_reply(_scene_reply(
            {**_SCENES, "retarget": _SCENES["new"]},
            audiences={"new": "aud_shared", "retarget": "aud_shared"},
        ))
        scenes = {ad["name"]: ad["scene"] for g in detail["groups"] for ad in g["ads"]}
        self.assertEqual(scenes["new-廣告一"], _SCENES["new"])
        self.assertEqual(scenes["retarget-廣告一"], _SCENES["new"])

    def test_accepted_plan_stores_the_scene_on_each_ad(self):
        detail = self._adopt_reply(_scene_reply({**_SCENES, "new": "  " + _SCENES["new"] + " "}))
        by_role = {g["role"]: g["ads"][0] for g in detail["groups"]}
        self.assertEqual(by_role["new"]["scene"], _SCENES["new"])  # stripped
        self.assertEqual(by_role["retarget"]["scene"], _SCENES["retarget"])
        self.assertEqual(by_role["explore"]["scene"], _SCENES["explore"])
        stored = ads_repo.get_ad(web.conn, self.org_id, self.brand_id, by_role["explore"]["id"])
        assert stored is not None
        self.assertEqual(stored["scene"], _SCENES["explore"])

    def test_hand_made_ad_has_no_scene(self):
        campaign = self._create_adopted_campaign()
        group = plan.create_group(
            web.conn, self.org_id, self.brand_id, campaign["id"], name="手動組", role="new",
            daily_budget=100,
        )
        ad = plan.create_ad(
            web.conn, self.org_id, self.brand_id, campaign["id"], group["id"], name="手動廣告",
            coordinates=_coordinates("hand"),
        )
        self.assertIsNone(ad["scene"])


class PromptRowsTest(unittest.TestCase):
    """F38 decision 1/3 + F42: `planner_context.prompt_rows` (F48-I06: moved out of plan.py, one
    menu for the planner and the hand edits) is the model's menu -- proof kinds the brand has
    evidence for (+ none), offers the brand can honour (+ none), `limited_time` only with an end
    date, no `video` for a photo-only brand, everything else untouched."""

    _ROWS = [
        {"dimension": "proof", "key": "customer_review", "label": "顧客評論原話"},
        {"dimension": "proof", "key": "lab_report", "label": "檢驗報告／認證"},
        {"dimension": "proof", "key": "none", "label": "無證明"},
        {"dimension": "offer", "key": "free_shipping", "label": "免運"},
        {"dimension": "offer", "key": "limited_time", "label": "限時限量"},
        {"dimension": "offer", "key": "none", "label": "無優惠"},
        {"dimension": "format", "key": "single_image", "label": "單圖"},
        {"dimension": "format", "key": "video", "label": "影片"},
        {"dimension": "hook", "key": "lab_report", "label": "同名但不同維度"},
        {"dimension": "audience", "key": "moms", "label": "媽媽"},
    ]

    def _keys(self, rows: list) -> list:
        return [(r["dimension"], r["key"]) for r in rows]

    def _menu(self, proof: set, end_date: bool, offers: set = frozenset({"limited_time"}),
              media: str | None = None) -> list:
        return planner_context.prompt_rows(self._ROWS, proof, end_date, set(offers), media)

    def test_proof_rows_filtered_to_available_plus_none(self):
        kept = self._keys(self._menu({"customer_review"}, True))
        self.assertIn(("proof", "customer_review"), kept)
        self.assertIn(("proof", "none"), kept)
        self.assertNotIn(("proof", "lab_report"), kept)

    def test_no_evidence_leaves_only_none_proof(self):
        kept = self._keys(self._menu(set(), True))
        self.assertEqual([k for k in kept if k[0] == "proof"], [("proof", "none")])

    def test_limited_time_dropped_without_end_date(self):
        self.assertIn(("offer", "limited_time"), self._keys(self._menu(set(), True)))
        kept = self._keys(self._menu(set(), False))
        self.assertNotIn(("offer", "limited_time"), kept)
        self.assertIn(("offer", "none"), kept)

    def test_offer_rows_filtered_to_available_plus_none(self):
        kept = self._keys(self._menu(set(), True, offers={"free_shipping"}))
        self.assertEqual([k for k in kept if k[0] == "offer"],
                         [("offer", "free_shipping"), ("offer", "none")])
        kept = self._keys(self._menu(set(), True, offers=set()))
        self.assertEqual([k for k in kept if k[0] == "offer"], [("offer", "none")])

    def test_video_dropped_only_for_a_photo_only_brand(self):
        def formats(media):
            return [k for k in self._keys(self._menu(set(), True, media=media)) if k[0] == "format"]

        self.assertEqual(formats("photo"), [("format", "single_image")])
        self.assertIn(("format", "video"), formats("photo_video"))
        self.assertIn(("format", "video"), formats(None))  # never asked -> no format filter

    def test_other_dimensions_untouched(self):
        kept = self._menu(set(), False, media="photo")
        gated = ("proof", "offer", "format")
        others = [r for r in self._ROWS if r["dimension"] not in gated]
        self.assertEqual([r for r in kept if r["dimension"] not in gated], others)


class ProofGateInPlanTest(PlanTestBase):
    """F38 decision 1: the plan prompt offers only evidenced proof kinds; a reply naming a
    proof kind the brand has no evidence for is stored as `none`, an evidenced one is kept."""

    # The seeded six-dimension vocabulary's proof rows (migration 20260904000002), inserted the
    # way test_ads_launch_view seeds audience rows -- a brand made here has no vocabulary yet.
    _PROOF_ROWS = (
        ("customer_review", "顧客評論原話"), ("expert_endorsement", "專家背書"),
        ("lab_report", "檢驗報告／認證"), ("media_coverage", "媒體報導"), ("none", "無證明"),
    )

    def setUp(self):
        super().setUp()
        for key, label in self._PROOF_ROWS:
            web.conn.execute(
                "INSERT INTO brand_coordinate(id,org_id,brand_id,dimension,key,label) "
                "VALUES(%s,%s,%s,'proof',%s,%s)",
                (coredb.new_id("crd"), self.org_id, self.brand_id, key, label),
            )

    def _run(self, proof: str) -> tuple[dict, str]:
        campaign = self._create_adopted_campaign()
        provider = _fake(_plan_reply(proof))
        plan.PROVIDER = provider
        detail = self._adopt(campaign["id"])
        return detail, provider.calls[0]["messages"][0]["content"]

    def _proof_keys(self, detail: dict) -> set:
        return {ad["proof_key"] for g in detail["groups"] for ad in g["ads"]}

    def test_unevidenced_proof_is_stored_as_none_and_not_offered(self):
        detail, prompt = self._run("lab_report")
        self.assertEqual(self._proof_keys(detail), {"none"})
        self.assertIn("proof｜none｜無證明", prompt)
        self.assertNotIn("檢驗報告／認證", prompt)

    def test_evidenced_proof_is_offered_and_kept(self):
        bi_repo.create_brand_fact(
            web.conn, self.brand_id, actor=ACTOR, fact_type="proof", label="顧客評論",
            value="「吃了三週真的有感」—— 王小姐", status="confirmed", confirmed_by=ACTOR,
            fact_key="customer_review",
        )
        detail, prompt = self._run("customer_review")
        self.assertEqual(self._proof_keys(detail), {"customer_review"})
        self.assertIn("proof｜customer_review｜", prompt)
        self.assertNotIn("檢驗報告／認證", prompt)


def _format_reply(fmt: str) -> str:
    return json.dumps({"groups": [
        {"role": role, "name": f"{role} 組", "ads": [
            {"name": f"{role}-廣告一",
             "coordinates": {**_coordinates(role), "proof": "none", "offer": "none",
                             "format": fmt},
             "scene": f"{role} 受眾晚上在家滑手機看到這支廣告"},
        ]}
        for role in ("new", "retarget", "explore")
    ]}, ensure_ascii=False)


class BrandDataGatesInPlanTest(PlanTestBase):
    """F42 (drill-8 red #1 #2): the plan's menu offers an `offer` key only when a confirmed store
    policy supports it for the campaign's product (a threshold policy needs the product's price
    to reach it), and a photo-only brand never gets a `video` format -- a stray `video` reply is
    stored as the menu's first allowed format."""

    # The seeded offer/format rows (app/schedule/repository.py::_SEED_COORDINATES), inserted the
    # way ProofGateInPlanTest seeds proof rows -- a brand made here has no vocabulary yet.
    _ROWS = (
        ("offer", "free_shipping", "免運"), ("offer", "discount", "折扣"),
        ("offer", "none", "無優惠"),
        ("format", "single_image", "單圖"), ("format", "carousel", "輪播"),
        ("format", "video", "影片"),
    )

    def setUp(self):
        super().setUp()
        for dimension, key, label in self._ROWS:
            web.conn.execute(
                "INSERT INTO brand_coordinate(id,org_id,brand_id,dimension,key,label) "
                "VALUES(%s,%s,%s,%s,%s,%s)",
                (coredb.new_id("crd"), self.org_id, self.brand_id, dimension, key, label),
            )
        web.conn.commit()

    def _campaign_with_product(self, price: float) -> dict:
        product_id = bi_repo.create_product(
            web.conn, self.brand_id, name="綜合維他命軟糖", actor=ACTOR,
        )["id"]
        bi_repo.save_product_economics(
            web.conn, self.brand_id, product_id, selling_price=price, currency="TWD",
            confirmed_by=ACTOR, actor=ACTOR, unit_variable_cost=150, shipping_cost=50,
        )
        campaign = self._create_adopted_campaign()
        ads_repo.update_campaign(web.conn, self.org_id, self.brand_id, campaign["id"],
                                 {"product_ids": [product_id]})
        return campaign

    def _prompt_for(self, campaign: dict, reply: str) -> tuple[dict, str]:
        provider = _fake(reply)
        plan.PROVIDER = provider
        detail = self._adopt(campaign["id"])
        return detail, provider.calls[0]["messages"][0]["content"]

    def _save_free_shipping_999(self) -> None:
        bi_repo.save_brand_policies(web.conn, self.brand_id, [
            {"key": "ship_threshold", "params": {"threshold": 999}},
        ], actor=ACTOR)

    def test_threshold_policy_reached_by_the_product_price_offers_free_shipping(self):
        self._save_free_shipping_999()
        # F44: an offer in the menu must be used by at least one ad, so the reply takes it.
        _, prompt = self._prompt_for(
            self._campaign_with_product(999), _plan_reply("none", offer="free_shipping"),
        )
        self.assertIn("offer｜free_shipping｜免運", prompt)
        self.assertNotIn("offer｜discount｜", prompt)
        self.assertIn("offer｜none｜無優惠", prompt)

    def test_product_price_below_the_threshold_leaves_free_shipping_out(self):
        self._save_free_shipping_999()
        detail, prompt = self._prompt_for(
            self._campaign_with_product(998), _plan_reply("none", offer="free_shipping"),
        )
        self.assertNotIn("offer｜free_shipping｜", prompt)
        self.assertEqual({ad["offer_key"] for g in detail["groups"] for ad in g["ads"]}, {"none"})

    def test_brand_without_policies_is_offered_no_offer(self):
        _, prompt = self._prompt_for(self._campaign_with_product(999), _plan_reply("none"))
        self.assertNotIn("offer｜free_shipping｜", prompt)
        self.assertNotIn("offer｜discount｜", prompt)
        self.assertIn("offer｜none｜無優惠", prompt)

    def test_photo_only_brand_gets_no_video_and_a_stray_video_becomes_an_allowed_format(self):
        bi_repo.set_media_capability(web.conn, self.brand_id, "photo", actor=ACTOR)
        detail, prompt = self._prompt_for(self._create_adopted_campaign(), _format_reply("video"))
        self.assertNotIn("format｜video｜", prompt)
        allowed = {"single_image", "carousel"}
        for key in allowed:
            self.assertIn(f"format｜{key}｜", prompt)
        formats = {ad["format_key"] for g in detail["groups"] for ad in g["ads"]}
        self.assertEqual(len(formats), 1)
        self.assertLessEqual(formats, allowed)

    def test_photo_and_video_brand_keeps_video(self):
        bi_repo.set_media_capability(web.conn, self.brand_id, "photo_video", actor=ACTOR)
        detail, prompt = self._prompt_for(self._create_adopted_campaign(), _format_reply("video"))
        self.assertIn("format｜video｜影片", prompt)
        self.assertEqual({ad["format_key"] for g in detail["groups"] for ad in g["ads"]}, {"video"})

    def test_media_never_asked_keeps_video(self):
        detail, prompt = self._prompt_for(self._create_adopted_campaign(), _format_reply("video"))
        self.assertIn("format｜video｜影片", prompt)
        self.assertEqual({ad["format_key"] for g in detail["groups"] for ad in g["ads"]}, {"video"})


def _offer_reply(offers: dict) -> str:
    """Three roles, one ad each; `offers` maps role -> offer key (a missing role uses `none`)."""
    return json.dumps({"groups": [
        {"role": role, "name": f"{role} 組", "ads": [
            {"name": f"{role}-廣告一",
             "coordinates": {**_coordinates(role), "proof": "none",
                             "offer": offers.get(role, "none")},
             "scene": f"{role} 受眾晚上在家滑手機看到這支廣告"},
        ]}
        for role in ("new", "retarget", "explore")
    ]}, ensure_ascii=False)


class OffersInDeliveryPlanPromptTest(PlanTestBase):
    """F44-I02 (drill-9 red #1): the prompt prints the registered sentence of every offer the
    filtered menu kept under 【這期可用的優惠】 (after the customers, before the vocabulary), leaves
    the section out when the menu has no offer, and a plan in which no ad uses an offered key is
    refused whole. Fixture: a three-pack sell-way with a list price (`bundle`)."""

    _ROWS = (
        ("offer", "bundle", "組合優惠"), ("offer", "free_shipping", "免運"),
        ("offer", "none", "無優惠"),
    )
    _BUNDLE_LINE = "- offer=bundle｜優惠價 NT$999（原價 NT$1,197）"

    def setUp(self):
        super().setUp()
        for dimension, key, label in self._ROWS:
            web.conn.execute(
                "INSERT INTO brand_coordinate(id,org_id,brand_id,dimension,key,label) "
                "VALUES(%s,%s,%s,%s,%s,%s)",
                (coredb.new_id("crd"), self.org_id, self.brand_id, dimension, key, label),
            )
        web.conn.commit()

    def _bundle_campaign(self) -> dict:
        product_id = bi_repo.create_product(
            web.conn, self.brand_id, name="綜合維他命軟糖", actor=ACTOR,
        )["id"]
        box_id = bi_repo.save_sell_way(
            web.conn, self.brand_id, name="單盒", actor=ACTOR, product_id=product_id,
            economics={"selling_price": 399},
        )["id"]
        sell_way_id = bi_repo.save_sell_way(
            web.conn, self.brand_id, name="三盒組", actor=ACTOR,
            components=[{"sell_way_id": box_id, "qty": 3}],
            economics={"selling_price": 999, "list_price": 1197, "unit_variable_cost": 300,
                       "shipping_cost": 60},
        )["id"]
        campaign = self._create_adopted_campaign()
        ads_repo.update_campaign(web.conn, self.org_id, self.brand_id, campaign["id"],
                                 {"product_ids": [sell_way_id]})
        return campaign

    def _adopt_reply(self, campaign: dict, reply: str) -> tuple[dict, str]:
        provider = _fake(reply)
        plan.PROVIDER = provider
        detail = self._adopt(campaign["id"])
        return detail, provider.calls[0]["messages"][0]["content"]

    def _offer_keys(self, detail: dict) -> dict:
        return {g["role"]: g["ads"][0]["offer_key"] for g in detail["groups"]}

    def test_section_prints_the_offer_sentence_between_customers_and_vocabulary(self):
        _, prompt = self._adopt_reply(self._bundle_campaign(), _offer_reply({"new": "bundle"}))
        # F48-I06: offers come right after the customers, then the ranking.
        self.assertIn(f"\n\n{OFFERS_HEADER}\n{self._BUNDLE_LINE}\n\n【上幾期的排名", prompt)
        # The department file names the header too; the last occurrence is the section itself.
        offers_at = prompt.rindex(OFFERS_HEADER)
        self.assertLess(prompt.rindex("【這個賣法的顧客】"), offers_at)
        self.assertLess(offers_at, prompt.rindex("【座標詞彙"))
        self.assertIn("offer｜bundle｜組合優惠", prompt)
        # 【手上的素材】 after the ranking, then the capacity line.
        self.assertIn(
            f"{plan.MATERIALS_HEADER}照片 0 張、影片 0 支\n\n【這期撐得起幾則】", prompt,
        )

    def test_section_lists_only_the_offers_the_menu_kept_each_once(self):
        # 首購禮 maps to `discount`, which this brand's vocabulary does not have: its sentence
        # must not be printed. 滿額免運 999 is reached by the three-pack's price.
        bi_repo.save_brand_policies(web.conn, self.brand_id, [
            {"key": "first_order", "params": {"content": "首購 9 折"}},
            {"key": "ship_threshold", "params": {"threshold": 999}},
        ], actor=ACTOR)
        _, prompt = self._adopt_reply(self._bundle_campaign(), _offer_reply({"new": "bundle"}))
        section = prompt[prompt.rindex(OFFERS_HEADER):prompt.rindex("【上幾期的排名")]
        lines = section.strip().splitlines()[1:]
        self.assertEqual(len(lines), 2)
        self.assertTrue(lines[0].startswith("- offer=free_shipping｜"), lines[0])
        self.assertIn("999", lines[0])
        self.assertEqual(lines[1], self._BUNDLE_LINE)
        self.assertNotIn("首購 9 折", prompt)

    def test_section_says_so_when_the_menu_has_no_offer(self):
        # No product, no policy: the menu's only offer row is `none`; an all-`none` plan passes.
        # F48-I06: planner_context's section says there is none (it is no longer left out).
        detail, prompt = self._adopt_reply(self._create_adopted_campaign(), _offer_reply({}))
        self.assertIn(f"\n\n{OFFERS_HEADER}（這期沒有可用的優惠）\n\n", prompt)
        self.assertNotIn("- offer=", prompt)
        self.assertEqual(set(self._offer_keys(detail).values()), {"none"})

    def test_explicit_all_none_plan_is_accepted_when_the_menu_has_an_offer(self):
        # `free_shipping` is not in this menu, so `_gate_reply` turns it into `none` first.
        for reply in (_offer_reply({}), _offer_reply({"new": "free_shipping"})):
            detail, _ = self._adopt_reply(self._bundle_campaign(), reply)
            self.assertEqual(set(self._offer_keys(detail).values()), {"none"})
            self.assertEqual(detail["status"], "ready")

    def test_one_ad_using_the_offer_passes_and_the_others_keep_none(self):
        detail, _ = self._adopt_reply(self._bundle_campaign(), _offer_reply({"retarget": "bundle"}))
        self.assertEqual(
            self._offer_keys(detail), {"new": "none", "retarget": "bundle", "explore": "none"},
        )

    def test_department_preserves_each_accepted_offer_including_none(self):
        text = plan.DEPARTMENT_PATH.read_text(encoding="utf-8")
        self.assertIn("Use each accepted slot's exact offer key", text)
        self.assertIn("An accepted `none` is legal even when offers are", text)
        self.assertIn("never replace it with an available discount", text)
        self.assertIn("For an accepted offer, the ad name", text)


# -- F48-I06: Contracts K (留下 carries the creative), C (ceiling), P (one menu, 不能講) ---------

_KEEP_COPY = {"headline": "上一期的標題", "body": "上一期跑過的內文", "description": "說明"}


def _two_role_reply(*, names=("再行銷-補位", "探索-補位"), roles=("retarget", "explore")) -> str:
    """One ad per role in `roles` (the roles no carried ad covers)."""
    return json.dumps({"groups": [
        {"role": role, "name": f"{role} 組", "ads": [{
            "name": name, "coordinates": _coordinates(role),
            "scene": f"{role} 這支廣告的受眾晚上在家滑手機",
        }]}
        for role, name in zip(roles, names, strict=True)
    ]}, ensure_ascii=False)


def _seed_previous_with_creatives(org_id: str, brand_id: str, rows: list) -> tuple:
    """A closed campaign (no sell-way) with one `new` group and one ad per `(name, tag, verdict,
    with_creative)`; an ad with a creative gets its own ready original with `_KEEP_COPY`,
    confirmed and assigned; every ad gets its ranked `coordinate` learning row. Returns
    (campaign, ads, asset id or None per ad)."""
    from app.ads import handoff_assignment
    from app.ads import user_assets_repository as user_assets

    previous = ads_repo.create_campaign(web.conn, org_id, brand_id, {
        "name": "上一期 Campaign", "goal_text": "上一期衝購買", "objective": "購買",
        "target_cost": 300, "start_date": "2026-09-01", "end_date": "2026-09-14",
        "status": "ready",
    }, created_by=ACTOR)
    group = plan.create_group(web.conn, org_id, brand_id, previous["id"],
                              name="上一期新客組", role="new", daily_budget=500)
    ads, assets = [], []
    for name, tag, _, with_creative in rows:
        ad = plan.create_ad(web.conn, org_id, brand_id, previous["id"], group["id"],
                            name=name, coordinates=_coordinates(tag))
        ads.append(ad)
        asset = None
        if with_creative:
            asset = coredb.new_id("aua")
            web.conn.execute(
                "INSERT INTO ads_user_asset(id,org_id,brand_id,sha256,storage_key,filename,"
                "mime_type,byte_size,status) VALUES(%s,%s,%s,%s,%s,'keep.png','image/png',1,"
                "'ready')",
                (asset, org_id, brand_id, asset, f"{org_id}/{asset}"),
            )
            placement = user_assets.attach(web.conn, org_id, brand_id, previous["id"], asset,
                                           _KEEP_COPY, ACTOR)
            web.conn.execute(
                "UPDATE ads_asset_placement SET confirmed_at=now(),confirmed_by='human'"
                " WHERE id=%s", (placement["id"],),
            )
            web.conn.commit()
            handoff_assignment.assign(web.conn, org_id, brand_id, previous["id"], ad["id"],
                                      placement["id"], 1)
        assets.append(asset)
    for rank, (ad, row) in enumerate(zip(ads, rows, strict=True), start=1):
        bi_repo.record_learning(
            web.conn, brand_id, actor=ACTOR, learning_text=ad["name"],
            applicability_scope=_ranked_scope(
                verdict=row[2], rank=rank, of=len(rows), sales=6 - rank, spend=1200, group=None,
                angle=f"angle_{rank}"),
            confidence="observed", sample_size="高",
            source_cycle_id=f"{previous['id']}:{ad['id']}", source_track="coordinate",
        )
    web.conn.execute(
        "UPDATE ads_campaign SET status='closed', closed_at=now() WHERE id=%s",
        (previous["id"],),
    )
    web.conn.commit()
    return previous, ads, assets


class CarriedKeepAdsTest(PlanTestBase):
    """Contract K: adopting the next plan of a sell-way carries the newest closed campaign's 留下
    ads in (same name, seven keys, scene, customer group, `carried_from`) before the model is
    asked; a carried ad whose creative is found gets the same original with the same copy and
    its slot reads ready; one whose creative is gone carries `carry_note` and its slot reads
    missing; 換掉 rows are never carried. The model plans only 「請再規劃 K 則」 more
    (Contract C)."""

    def setUp(self):
        super().setUp()
        self.previous, ads, assets = _seed_previous_with_creatives(
            self.org_id, self.brand_id,
            [("留下-有素材", "keep1", "keep", True),
             ("留下-沒素材", "keep2", "keep_relative", False),
             ("換掉-這則", "cut", "replace", False)],
        )
        self.kept, self.bare, self.cut = ads
        self.asset = assets[0]
        self.campaign = self._create_adopted_campaign()  # 2142 a day at cap 300 -> ceiling 4

    def _adopt_reply(self, reply: str) -> tuple[dict, str]:
        provider = _fake(reply)
        plan.PROVIDER = provider
        detail = self._adopt(self.campaign["id"])
        return detail, provider.calls[0]["messages"][0]["content"]

    def _ads(self, detail: dict) -> dict:
        return {ad["name"]: ad for group in detail["groups"] for ad in group["ads"]}

    def test_kept_ads_are_carried_with_their_creative_and_the_model_plans_the_rest(self):
        from app.ads import slots

        detail, prompt = self._adopt_reply(_two_role_reply())
        ads = self._ads(detail)
        self.assertEqual(set(ads), {"留下-有素材", "再行銷-補位", "探索-補位"})
        self.assertNotIn("留下-沒素材", ads)
        carried = ads["留下-有素材"]
        for dim in ("audience", "pain", "angle", "hook", "proof", "offer", "format"):
            self.assertEqual(carried[f"{dim}_key"], self.kept[f"{dim}_key"])
        source = carried["coordinates_snapshot_json"]["carried_from"]
        self.assertEqual({k: source[k] for k in ("campaign_id", "ad_id")},
                         {"campaign_id": self.previous["id"], "ad_id": self.kept["id"]})
        self.assertIsNotNone(source["placement_id"])
        self.assertEqual(source["placement_revision"], 1)
        self.assertEqual(carried["carried_label"], "沿用上一期")
        self.assertIsNone(carried["carry_note"])
        self.assertIsNone(ads["再行銷-補位"]["carried_label"])
        by_group = {g["role"]: [ad["name"] for ad in g["ads"]] for g in detail["groups"]}
        self.assertEqual(by_group["new"], ["留下-有素材"])

        # Same original, same copy, confirmed and assigned: the slot reads ready.
        material = carried["material_placement_id"]
        self.assertIsNotNone(material)
        row = web.conn.execute(
            "SELECT asset_id, copy_fields, ad_id FROM ads_asset_placement WHERE id=%s"
            " AND is_current", (material,)).fetchone()
        self.assertEqual((row["asset_id"], row["copy_fields"], row["ad_id"]),
                         (self.asset, _KEEP_COPY, carried["id"]))
        view = slots.read(web.conn, self.org_id, self.brand_id, self.campaign["id"])
        states = {s["name"]: s["state"] for g in view["groups"] for s in g["slots"]}
        self.assertEqual(states["留下-有素材"], "ready")

        self.assertIn("【已沿用的廣告】", prompt)
        self.assertIn("- 「留下-有素材」｜投放組 new｜顧客群 未指定｜audience=aud_keep1、", prompt)
        self.assertIn("請再規劃 2 則", prompt)
        self.assertLess(prompt.rindex("【已沿用的廣告】"), prompt.rindex("【座標詞彙"))
        self.assertNotIn("換掉-這則", set(ads))

    def test_a_reply_above_the_ceiling_is_refused_with_nothing_written(self):
        # One eligible carried + four planned = 5 > ceiling 4; refuse before adoption.
        reply = json.loads(_VALID_PLAN_REPLY)
        reply["groups"][0]["ads"].append({**reply["groups"][0]["ads"][0], "name": "extra"})
        with self.assertRaises(ValueError) as ctx:
            self._adopt_reply(json.dumps(reply, ensure_ascii=False))
        self.assertIsInstance(ctx.exception, plan.StrategyConflict)
        self.assertIn("capacity_exceeded", {r["code"] for r in ctx.exception.reasons})
        reloaded = ads_repo.campaign_detail(web.conn, self.org_id, self.brand_id,
                                            self.campaign["id"])
        self.assertEqual((reloaded["status"], reloaded["groups"]), ("draft", []))

    def test_a_reply_leaving_out_an_uncovered_role_or_reusing_a_carried_name_is_refused(self):
        for reply, code in (
            (_two_role_reply(names=("再行銷-補位",), roles=("retarget",)), "menu_violation"),
            (_two_role_reply(names=("留下-有素材", "探索-補位")), "reply_invalid"),
        ):
            with self.subTest(reply=reply), self.assertRaises(ValueError) as ctx:
                self._adopt_reply(reply)
            self._assert_refusal(ctx.exception, code)

    def test_a_carried_ready_ad_stays_out_of_the_pack(self):
        from app import workbench
        from app.ads import assets

        detail, _ = self._adopt_reply(_two_role_reply())
        ads = self._ads(detail)
        workbench.register_tasks()
        assets.dispatch_pack(web.conn, self.org_id, self.brand_id, self.campaign["id"])
        web.conn.commit()
        packed = {
            (brief.get("source_ref") or {}).get("ads_ad_id")
            for brief in workbench.briefs_for_source(
                web.conn, self.org_id, self.brand_id, assets.PACK_SOURCE_KIND,
                {"ads_campaign_id": self.campaign["id"]})
        }
        self.assertNotIn(ads["留下-有素材"]["id"], packed)
        self.assertNotIn("留下-沒素材", ads)
        self.assertIn(ads["探索-補位"]["id"], packed)

    def test_the_payload_serves_capacity_and_menu(self):
        from fastapi.testclient import TestClient

        from app import main

        web.conn.execute(
            "INSERT INTO brand_coordinate(id,org_id,brand_id,dimension,key,label) "
            "VALUES(%s,%s,%s,'proof','lab_report','檢驗報告')",
            (coredb.new_id("crd"), self.org_id, self.brand_id),
        )
        self._adopt_reply(_two_role_reply())
        web.conn.commit()
        response = TestClient(main.app).get(
            f"/api/ads/brands/{self.brand_id}/campaigns/{self.campaign['id']}")
        self.assertEqual(response.status_code, 200, response.text)
        campaign = response.json()["campaign"]
        self.assertEqual(campaign["capacity"],
                         {"daily": 2142, "cap": 300, "can_support": 3, "ceiling": 4,
                          "carried": 1})
        menu = {(row["dimension"], row["key"]) for row in campaign["menu"]}
        self.assertNotIn(("proof", "lab_report"), menu)  # no evidence registered


class EveryAdCarriedTest(PlanTestBase):
    """Lead review (F48-I06 item 5): a period where every ad is a carried 留下 ad with its
    creative is a normal case. One adopted role, 600 a day at cap 300 -> can_support 1, ceiling
    2; two 留下 ads with creatives fill it, so K = 0: no model call, the structure is ready, both
    slots read 已確認, and dispatching the pack makes no workbench pack ("nothing to prepare",
    no error) while the readiness read counts every ad ready."""

    def test_two_ready_carried_ads_need_no_model_and_no_pack(self):
        from fastapi.testclient import TestClient

        from app import main, workbench
        from app.ads import assets, slots

        _seed_previous_with_creatives(self.org_id, self.brand_id, [
            ("留下-甲", "keep1", "keep", True), ("留下-乙", "keep2", "keep_relative", True),
        ])
        campaign = ads_repo.create_campaign(web.conn, self.org_id, self.brand_id, {
            "name": "這一期", "goal_text": "續投留下的", "objective": "購買", "target_cost": 300,
            "start_date": "2026-10-01", "end_date": "2026-10-14", "status": "draft",
            "budget_planned": 8400, "budget_scenario": "recommended",
            "budget_basis_json": {"strategy": {"allocation": [
                {"role": "new", "label": "新客", "pct": 100, "rationale": None}]}},
        }, created_by=ACTOR)
        provider = _fake(_VALID_PLAN_REPLY)
        plan.PROVIDER = provider

        detail = self._adopt(campaign["id"])

        self.assertEqual(provider.calls, [])  # K = 0: the model is not asked
        self.assertEqual(detail["status"], "ready")
        ads = [ad for group in detail["groups"] for ad in group["ads"]]
        self.assertEqual([ad["name"] for ad in ads], ["留下-甲", "留下-乙"])
        view = slots.read(web.conn, self.org_id, self.brand_id, campaign["id"])
        tiles = [s for g in view["groups"] for s in g["slots"]]
        self.assertEqual([(s["state"], s["confirmed"]) for s in tiles],
                         [("ready", True), ("ready", True)])

        with mock.patch.object(workbench, "submit_pack") as submit:
            self.assertIsNone(
                assets.dispatch_pack(web.conn, self.org_id, self.brand_id, campaign["id"]))
            web.conn.commit()
            response = TestClient(main.app).post(
                f"/api/ads/brands/{self.brand_id}/campaigns/{campaign['id']}/pack")
        submit.assert_not_called()
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json(), {"pack_id": None, "nothing_to_prepare": True})
        rows = assets.readiness(web.conn, self.org_id, self.brand_id, campaign["id"])
        self.assertEqual(assets.readiness_summary(rows, None),
                         {"ready_count": 2, "total": 2, "pack_id": None})
        self.assertNotIn("in_progress", {row["state"] for row in rows})


class HandEditsObeyTheMenuTest(PlanTestBase):
    """Contract P: a hand-made or edited ad may not take a vocabulary key this period's menu
    leaves out (400 `coordinate_unavailable`, naming the dimension and why) nor a name carrying
    a 「不能講」 entry (400 `name_forbidden`); keys outside the vocabulary pass as before, and the
    delivery plan's reply is refused for a forbidden name too."""

    def setUp(self):
        super().setUp()
        web.conn.execute(
            "INSERT INTO brand_coordinate(id,org_id,brand_id,dimension,key,label) "
            "VALUES(%s,%s,%s,'proof','lab_report','檢驗報告')",
            (coredb.new_id("crd"), self.org_id, self.brand_id),
        )
        bi_repo.create_claim(web.conn, self.brand_id, actor=ACTOR, claim_text="保證治癒",
                             claim_type="forbidden")
        self.campaign = self._create_adopted_campaign()
        plan.PROVIDER = _fake(_VALID_PLAN_REPLY)
        self.group = self._adopt(self.campaign["id"])["groups"][0]
        web.conn.commit()

    def _post(self, body: dict):
        from fastapi.testclient import TestClient

        from app import main

        return TestClient(main.app).post(
            f"/api/ads/brands/{self.brand_id}/campaigns/{self.campaign['id']}/ads",
            json={"group_id": self.group["id"], **body})

    def test_an_unevidenced_proof_key_is_refused_with_its_reason(self):
        response = self._post({"name": "手動廣告",
                               "coordinates": {**_coordinates("hand"), "proof": "lab_report"}})
        self.assertEqual(response.status_code, 400, response.text)
        error = response.json()["error"]
        self.assertEqual(error["code"], "coordinate_unavailable")
        self.assertEqual(error["message"], "這期不能用這個證據：沒有登記證據")
        ok = self._post({"name": "手動廣告", "coordinates": _coordinates("hand")})
        self.assertEqual(ok.status_code, 200, ok.text)  # keys outside the vocabulary pass

    def test_a_forbidden_word_in_the_name_is_refused(self):
        response = self._post({"name": "保證 治癒的夜跑背心", "coordinates": _coordinates("hand")})
        self.assertEqual(response.status_code, 400, response.text)
        error = response.json()["error"]
        self.assertEqual(error["code"], "name_forbidden")
        self.assertEqual(error["message"], "廣告名稱寫了「保證治癒」，這是你標了不能講的話")
        ad = self.group["ads"][0]
        with self.assertRaises(plan.NameForbidden):
            plan.update_ad(web.conn, self.org_id, self.brand_id, ad["id"],
                           {"name": "保證治癒"}, actor=ACTOR)

    def test_an_edit_keeping_an_excluded_key_the_ad_holds_passes(self):
        ad = self.group["ads"][0]
        web.conn.execute("UPDATE ads_ad SET proof_key='lab_report' WHERE id=%s", (ad["id"],))
        updated = plan.update_ad(
            web.conn, self.org_id, self.brand_id, ad["id"],
            {"coordinates": {"proof": "lab_report", "hook": "hook_new"}}, actor=ACTOR)
        self.assertEqual(updated["hook_key"], "hook_new")
        plan.update_ad(web.conn, self.org_id, self.brand_id, ad["id"],
                       {"coordinates": {"proof": "none"}}, actor=ACTOR)
        with self.assertRaises(plan.CoordinateUnavailable) as ctx:
            plan.update_ad(web.conn, self.org_id, self.brand_id, ad["id"],
                           {"coordinates": {"proof": "lab_report"}}, actor=ACTOR)
        self.assertEqual((ctx.exception.dimension_label, ctx.exception.reason),
                         ("證據", "沒有登記證據"))

    def test_the_plan_reply_naming_a_forbidden_word_is_refused(self):
        campaign = self._create_adopted_campaign()
        reply = json.loads(_VALID_PLAN_REPLY)
        reply["groups"][0]["ads"][0]["name"] = "保證治癒・新客"
        plan.PROVIDER = _fake(json.dumps(reply, ensure_ascii=False))
        with self.assertRaises(ValueError) as ctx:
            self._adopt(campaign["id"])
        self._assert_refusal(ctx.exception, "name_forbidden")


# -- F50 Contract J (R7 B3): refusal codes, and the one automatic retry (user ruling 2026-10-04) --


class _Replies:
    """A provider answering `texts` in order (the last one repeats); `error` -> every call fails."""

    name = "fake"

    def __init__(self, *texts: str, error: Exception | None = None):
        self.texts, self.error, self.calls = list(texts), error, []

    def complete(self, *, model, system, messages, max_tokens, timeout_s=120.0, effort=None,
                 tools=None, org_id=None):
        self.calls.append({"messages": messages})
        if self.error is not None:
            raise self.error
        return fixture_provider(self.texts[min(len(self.calls), len(self.texts)) - 1]).complete(
            model=model, system=system, messages=messages, max_tokens=max_tokens)

    def prompt(self, n: int) -> str:
        return self.calls[n]["messages"][0]["content"]


def _forbidden_name_reply() -> str:
    reply = json.loads(_VALID_PLAN_REPLY)
    reply["groups"][0]["ads"][0]["name"] = "保證治癒・新客"
    return json.dumps(reply, ensure_ascii=False)


class PlanRefusalTest(PlanTestBase):
    """Contract J: each refusal names its rule (on the exception, the task row and the 502); a
    rule's refusal is asked once more with the refusal in the prompt, a second refusal is raised;
    a provider failure is not retried and keeps the provider's own error."""

    def setUp(self):
        super().setUp()
        bi_repo.create_claim(web.conn, self.brand_id, actor=ACTOR, claim_text="保證治癒",
                             claim_type="forbidden")
        self.campaign = self._create_adopted_campaign()
        web.conn.commit()

    def _rows(self) -> list:
        return gateway.find_tasks_for_scope(
            web.conn, org_id=self.org_id, brand_id=self.brand_id, task_type="ads_delivery_plan",
            context_scope={"campaign_id": self.campaign["id"]},
        )

    def test_the_nine_rules_of_contract_j(self):
        self.assertEqual(list(plan.REFUSALS), [
            "llm_failed", "reply_unreadable", "reply_invalid", "menu_violation", "offer_unused",
            "name_forbidden", "group_unbound", "carried_changed", "replace_rerun",
        ])
        self.assertEqual(plan.REFUSALS["offer_unused"], "這期有優惠，AI 排的廣告都沒用上")
        self.assertEqual(plan.REFUSALS["replace_rerun"], "又排了上一期要換掉的組合")

    def test_a_refused_reply_is_asked_once_more_with_the_refusal_and_the_retry_is_used(self):
        provider = _Replies(_forbidden_name_reply(), _VALID_PLAN_REPLY)
        plan.PROVIDER = provider
        detail = self._adopt(self.campaign["id"])
        self.assertEqual(detail["status"], "ready")
        self.assertEqual(len(provider.calls), 2)
        self.assertNotIn(plan.RETRY_HEADER, provider.prompt(0))
        retry = provider.prompt(1)
        self.assertIn(f"{plan.RETRY_HEADER}（這次請改掉下面的問題，其他規則照舊）\n"
                      f"- name_forbidden：{plan.REFUSALS['name_forbidden']}", retry)
        self.assertLess(retry.rindex(plan.RETRY_HEADER), retry.rindex("【座標詞彙"))
        first, second = self._rows()
        self.assertEqual((first["error_code"], first["error"]),
                         ("program_refused", f"name_forbidden: {plan.REFUSALS['name_forbidden']}"))
        self.assertEqual((second["status"], second["error_code"], second["error"]),
                         ("succeeded", None, None))

    def test_a_second_refusal_is_raised_with_its_code_and_no_third_call(self):
        provider = _Replies(_forbidden_name_reply(), "這不是 JSON")
        plan.PROVIDER = provider
        with self.assertRaises(ValueError) as ctx:
            self._adopt(self.campaign["id"])
        self._assert_refusal(ctx.exception, "reply_unreadable")
        self.assertEqual(len(provider.calls), 2)
        self.assertEqual([row["error"].split(":")[0] for row in self._rows()],
                         ["name_forbidden", "reply_unreadable"])
        reloaded = ads_repo.campaign_detail(web.conn, self.org_id, self.brand_id,
                                            self.campaign["id"])
        self.assertEqual((reloaded["status"], reloaded["groups"]), ("draft", []))

    def test_a_provider_failure_is_not_retried_and_keeps_its_own_error(self):
        provider = _Replies(error=providers.ProviderTimeoutError("模型逾時（60 秒）"))
        plan.PROVIDER = provider
        with self.assertRaises(plan.PlannerRefused) as ctx:
            self._adopt(self.campaign["id"])
        self.assertEqual((ctx.exception.code, ctx.exception.reason),
                         ("llm_failed", "AI 這次沒有回覆（等太久沒有回應）"))
        self.assertEqual(len(provider.calls), 1)
        (row,) = self._rows()
        self.assertEqual((row["status"], row["error_code"], row["error"]),
                         ("timeout", "timeout", "模型逾時（60 秒）"))

    def test_a_reply_moving_a_carried_group_to_other_people_is_carried_changed(self):
        listed = [{"id": "grp_1", "pain_keys": []}, {"id": "grp_2", "pain_keys": []}]
        groups = [{"role": "new", "name": "新客組", "ads": [{
            "name": "新客-廣告", "coordinates": _coordinates("x"), "scene": "下班後在捷運上滑手機",
            "customer_group": 2,
        }]}]
        carried = [{"target": "new", "ad": {"customer_group_id": "grp_1", "offer_key": "none"}}]
        with self.assertRaises(plan.PlannerRefused) as ctx:
            plan._checked_groups(  # noqa: SLF001
                groups, None, vocabulary_rows=[], ctx={"forbidden": []}, carried=carried,
                listed_groups=listed, replace_pairs=set(),
            )
        self.assertEqual((str(ctx.exception), ctx.exception.code),
                         ("delivery_plan_failed", "carried_changed"))

    def test_the_route_answers_502_naming_the_rule(self):
        from fastapi.testclient import TestClient

        from app import main

        plan.PROVIDER = _Replies(_forbidden_name_reply())
        revision = bind_fixture(web.conn, self.org_id, self.brand_id, self.campaign["id"])
        web.conn.commit()
        response = TestClient(main.app).post(
            f"/api/ads/brands/{self.brand_id}/campaigns/{self.campaign['id']}/plan",
            json={"expected_revision": revision, "operation_id": "refusal-route-fixture"})
        self.assertEqual(response.status_code, 502)
        reason = plan.REFUSALS["name_forbidden"]
        self.assertEqual(response.json()["error"], {
            "code": "delivery_plan_failed", "message": f"{plan.PLAN_FAILED_MESSAGE}（{reason}）",
            "details": {"refusal": "name_forbidden", "reason": reason},
        })
        self.assertEqual([row["error"] for row in self._rows()],
                         [f"name_forbidden: {reason}"] * 2)

    def test_every_rule_reaches_the_502_body(self):
        from fastapi.testclient import TestClient

        from app import main

        client = TestClient(main.app)
        for code, reason in plan.REFUSALS.items():
            refusal = plan.PlannerRefused("delivery_plan_failed", code, reason, None)
            with self.subTest(code=code), mock.patch.object(plan, "adopt_strategy",
                                                            side_effect=refusal):
                response = client.post(
                    f"/api/ads/brands/{self.brand_id}/campaigns/{self.campaign['id']}/plan")
                self.assertEqual(response.status_code, 502)
                self.assertEqual(response.json()["error"]["details"],
                                 {"refusal": code, "reason": reason})

if __name__ == "__main__":
    unittest.main()
