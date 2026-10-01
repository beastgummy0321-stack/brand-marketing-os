"""app/tests/test_ads_plan.py — F03-I06 falsifiers: adopting a strategy writes group daily
budgets that sum exactly to `round(budget_planned / days)` even on an awkward split (proves
`budget.split()`'s remainder rule, not a naive `total / groups`); `budget_planned` survives both
the adopt and a later group edit unchanged; every ad carries all seven coordinates and a name
unique inside the campaign; adopting twice is refused; editing a bound group's budget writes
exactly one `ads_action` row (unbound edits write none); a budget raise above the brand's
approved `max_daily_amount` is refused before anything is written.
"""

import json
import unittest
from unittest import mock

import app.shared.web as web
from app.ads import plan
from app.ads import repository as ads_repo
from app.brand_intelligence import repository as bi_repo
from app.core import approval as approval_mod
from app.core import db as coredb
from app.llm import providers

ACTOR = "測試員"


def _fake(rendered_output: str) -> providers.FakeProvider:
    return providers.FakeProvider(response=providers.ProviderResponse(
        output_text=rendered_output, structured=None,
        usage=providers.Usage(input_tokens=100, output_tokens=50), stop_reason="end_turn",
    ))


def _coordinates(tag: str) -> dict:
    return {
        "audience": f"aud_{tag}", "pain": f"pain_{tag}", "angle": f"angle_{tag}",
        "hook": f"hook_{tag}", "proof": f"proof_{tag}", "offer": f"offer_{tag}",
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
        return plan.adopt_strategy(
            web.conn, self.org_id, self.brand_id, campaign_id, actor=ACTOR,
        )


class GroupBudgetsSumExactlyTest(PlanTestBase):
    def test_awkward_split_sums_exactly_to_rounded_daily_total(self):
        campaign = self._create_adopted_campaign()
        plan.PROVIDER = _fake(_VALID_PLAN_REPLY)

        detail = self._adopt(campaign["id"])

        days = 14
        expected_daily_total = round(30001 / days)  # 2144 — 50/30/20 floors to 2143, +1 remainder
        group_budgets = [float(g["daily_budget"]) for g in detail["groups"]]
        self.assertEqual(sum(group_budgets), expected_daily_total)
        self.assertEqual(len(detail["groups"]), 3)
        self.assertEqual(detail["status"], "ready")


class BudgetPlannedNeverRewrittenTest(PlanTestBase):
    def test_budget_planned_survives_adopt_and_a_later_group_edit(self):
        campaign = self._create_adopted_campaign()
        plan.PROVIDER = _fake(_VALID_PLAN_REPLY)
        detail = self._adopt(campaign["id"])
        self.assertEqual(float(detail["budget_planned"]), 30001)

        group = detail["groups"][0]
        plan.update_group(
            web.conn, self.org_id, self.brand_id, group["id"],
            {"daily_budget": float(group["daily_budget"]) + 10}, actor=ACTOR,
        )
        reloaded = ads_repo.campaign_detail(web.conn, self.org_id, self.brand_id, campaign["id"])
        self.assertEqual(float(reloaded["budget_planned"]), 30001)


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
        self.assertEqual(str(ctx.exception), "plan_already_adopted")


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


_SCOREBOARD_HEADER = "【座標成績表（已結案活動，程式統計；划算＝每筆成本在上限內）】"
_SCOREBOARD_EMPTY = "【座標成績表】（還沒有結案過的廣告，沒有成績表）"


class CoordinateScoreboardInDeliveryPlanPromptTest(PlanTestBase):
    """F39-I02（outcome 2）：展開投放組的 prompt 帶程式統計的【座標成績表】，位置在行事曆之後、
    詞彙表之前（詞彙表永遠最後）；空品牌就寫「還沒有成績表」。成績表列來自 I01 寫的
    `source_track='coordinate'` 學習列——這裡直接用公開的 `record_learning` 種一列。"""

    def _seed_scoreboard(self) -> dict:
        closed = ads_repo.create_campaign(web.conn, self.org_id, self.brand_id, {
            "name": "上一期 Campaign", "goal_text": "上一期衝購買", "objective": "購買",
            "target_cost": 300, "start_date": "2026-09-01", "end_date": "2026-09-14",
            "status": "closed",
        }, created_by=ACTOR)
        group = plan.create_group(
            web.conn, self.org_id, self.brand_id, closed["id"], name="上一期新客組", role="new",
            daily_budget=500,
        )
        ad = plan.create_ad(
            web.conn, self.org_id, self.brand_id, closed["id"], group["id"], name="上一期-免運",
            coordinates=_coordinates("last"),
        )
        keys = _coordinates("last")
        scope = "coord；grade=on_target；" + "；".join(
            f"{dim}={keys[dim]}"
            for dim in ("audience", "pain", "angle", "hook", "proof", "offer", "format")
        )
        return bi_repo.record_learning(
            web.conn, self.brand_id, actor=ACTOR,
            learning_text="「上一期-免運」每筆 200（上限 300）＝划算", applicability_scope=scope,
            confidence="observed", sample_size="1 則廣告",
            source_cycle_id=f"{closed['id']}:{ad['id']}", source_track="coordinate",
        )

    def _prompt(self) -> str:
        campaign = self._create_adopted_campaign()
        provider = _fake(_VALID_PLAN_REPLY)
        plan.PROVIDER = provider
        self._adopt(campaign["id"])
        return provider.calls[0]["messages"][0]["content"]

    def test_section_sits_between_the_calendar_and_the_vocabulary(self):
        self._seed_scoreboard()
        prompt = self._prompt()
        self.assertIn(_SCOREBOARD_HEADER, prompt)
        self.assertIn("- audience｜aud_last｜aud_last：划算 1、偏貴 0、太貴 0、沒賣出 0", prompt)
        self.assertIn(
            "上一期「上一期 Campaign」划算的：「上一期-免運」（aud_last（audience=aud_last）、",
            prompt,
        )
        # 任務檔前面也提到【投放期間內的行事曆】與【座標成績表】，取最後一次出現的才是段落本身。
        calendar_at = prompt.rindex("【投放期間內的行事曆】")
        board_at = prompt.rindex(_SCOREBOARD_HEADER)
        vocabulary_at = prompt.rindex("【座標詞彙")
        self.assertLess(calendar_at, board_at)
        self.assertLess(board_at, vocabulary_at)
        self.assertNotIn(_SCOREBOARD_EMPTY, prompt)

    def test_empty_brand_says_there_is_no_scoreboard(self):
        prompt = self._prompt()
        self.assertIn(_SCOREBOARD_EMPTY, prompt)
        self.assertNotIn(_SCOREBOARD_HEADER, prompt)
        self.assertLess(prompt.rindex("【投放期間內的行事曆】"), prompt.rindex(_SCOREBOARD_EMPTY))
        self.assertLess(prompt.rindex(_SCOREBOARD_EMPTY), prompt.rindex("【座標詞彙"))


class CustomerGroupsInDeliveryPlanPromptTest(PlanTestBase):
    """F43-I02: 【這個賣法的顧客】 sits after the scoreboard and before the vocabulary (the
    vocabulary stays last); its group ids reach the task's `knowledge_item_ids`."""

    def _adopt_capturing(self, campaign_id: str) -> tuple[str, list]:
        provider = _fake(_VALID_PLAN_REPLY)
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

        prompt, knowledge_item_ids = self._adopt_capturing(campaign["id"])

        self.assertIn(
            "第 1 群：下班後夜跑的上班族｜煩惱：怕買錯（pain=uncertainty）"
            "｜顧客會說：晚上跑步車子看不到我｜什麼時候用：下班後在河濱夜跑", prompt,
        )
        customers_at = prompt.rindex("【這個賣法的顧客】")
        self.assertLess(prompt.rindex(_SCOREBOARD_EMPTY), customers_at)
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
        self.assertIn("每支廣告的 `pain` 要從列出的某一群的煩惱", text)
        self.assertIn("`scene` 要合那一群的「什麼時候用」", text)


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
        self.assertEqual(str(ctx.exception), "delivery_plan_failed")

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
    """F38 decision 1/3 + F42: `_prompt_rows` is the model's menu -- proof kinds the brand has
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
        return plan._prompt_rows(self._ROWS, proof, end_date, set(offers), media)

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
        _, prompt = self._prompt_for(self._campaign_with_product(999), _plan_reply("none"))
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


if __name__ == "__main__":
    unittest.main()
