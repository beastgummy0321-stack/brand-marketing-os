"""app/tests/test_ads_planner_context.py — F48-I05 (Contracts P and S).

`planner_context` carries, for one sell-way, the product (name, 單品／組合, facts, price), the
「不能講」 list, the offers the menu keeps with their sentences, the customer groups, this
sell-way's learnings (never another product's), last period's learning goals and the capacity
line. The strategy prompt prints every block; its prose may carry no number (the program prints
the facts above it), and the facts' groups line names the listed groups before adoption and the
ads' bound groups after it.

Machine check: every module in `app/ads` that calls `gateway.run_task` with an `ads_*` task type
calls `planner_context(` too -- except the listed non-planners -- and the hand edits
(`plan.create_ad`／`update_ad`) read the same menu (`planner_context.menu`).
"""

import ast
import json
import unittest
from pathlib import Path

import app.shared.web as web
from app.ads import plan, planner_context, strategy
from app.ads import repository as ads_repo
from app.brand_intelligence import repository as bi_repo
from app.core import db as coredb
from app.llm import providers
from app.tests.test_ads_strategy_decision import fixture_provider

ACTOR = "測試員"
ADS_DIR = Path(__file__).resolve().parent.parent / "ads"

_HEADERS = (
    "【這個賣法】", "【不能講】", "【這個賣法的顧客】", "【這期可用的優惠】", "【過去的學習】",
    "【上幾期的排名", "【上一期想學的】", "【這期撐得起幾則】",
)


def _fake(reply) -> providers.FakeProvider:
    text = reply if isinstance(reply, str) else json.dumps(reply, ensure_ascii=False)
    return fixture_provider(text)


def _reply(**overrides) -> dict:
    reply = {
        "allocation": [
            {"role": "new", "pct": 60, "rationale": "先打下班後夜跑的上班族"},
            {"role": "explore", "pct": 40, "rationale": "試一個新角度"},
        ],
        "why": ["沿用上一期留下的廣告"], "unknowns": ["新角度的反應"],
        "alternatives": [], "learning_goals": ["哪一群比較便宜"],
    }
    reply.update(overrides)
    return reply


class CreativeComparisonTest(unittest.TestCase):
    def test_bounded_comparison_keeps_full_input_for_changes_outside_prompt(self):
        ctx = {
            "product": {"id": "own"},
            "learnings": {
                "ads": [],
                "ranked": {
                    "campaigns": [
                        {
                            "sell_way_id": "own",
                            "campaign_id": "closed",
                            "currency": "TWD",
                            "rows": [
                                {
                                    "ad_id": f"a-{n}",
                                    "rank": n + 1,
                                    "flags": ["樣本少"],
                                    "sales": n,
                                    "spend": n * 10,
                                }
                                for n in range(30)
                            ],
                        },
                        {
                            "sell_way_id": "other",
                            "campaign_id": "foreign",
                            "rows": [{"ad_id": "other", "body": "other-product-secret"}],
                        },
                    ]
                },
            },
            "carried_candidates": [
                {
                    "ad": {"id": "control"},
                    "role": "new",
                    "creative": {
                        "asset_id": "original-image",
                        "placement_id": "original-placement",
                        "placement_revision": 3,
                        "copy_fields": {"body": "exact original copy"},
                    },
                    "eligibility": {"state": "ready", "reasons": []},
                },
            ],
            "calendar_evidence": [{"id": "event", "name": "exam week"}],
            "offers": [
                {"key": "discount", "sentence": "registered discount"},
                {"key": "free_shipping", "sentence": "unselected offer"},
            ],
            "previous": {"learning_goals": ["test buyer situation"]},
        }
        full = planner_context.creative_basis(ctx)
        shown = planner_context.creative_projection(full, "discount")
        self.assertLess(len(shown["results"]), 30)
        self.assertEqual(shown["omitted"]["results"], 30 - len(shown["results"]))
        self.assertEqual(
            shown["controls"][0]["creative"]["copy_fields"]["body"], "exact original copy"
        )
        self.assertEqual(shown["selected_offer"]["sentence"], "registered discount")
        self.assertNotIn("other-product-secret", json.dumps(full))
        self.assertNotIn("unselected offer", json.dumps(shown))
        before = json.dumps(full, sort_keys=True)
        ctx["learnings"]["ranked"]["campaigns"][0]["rows"][-1]["sales"] = 999
        after = planner_context.creative_basis(ctx)
        self.assertNotEqual(before, json.dumps(after, sort_keys=True))
        self.assertEqual(shown, planner_context.creative_projection(after, "discount"))
        self.assertEqual(full["results"][-1]["sales"], 29)


class _Fixture(unittest.TestCase):
    """A brand with one sell-way 「夜跑背心 · 單件」 (NT$1000, list price 1200 -> a `discount`
    offer), one fact, one forbidden claim, one customer group, one 「優惠」 vocabulary row."""

    def setUp(self):
        self.org_id = coredb.DEV_ORG_ID
        self.brand_id = bi_repo.create_brand(
            web.conn, org_id=self.org_id, name="測試品牌：planner context", client_name=None,
            actor=ACTOR,
        )["id"]
        self.product = bi_repo.create_product(web.conn, self.brand_id, name="夜跑背心", actor=ACTOR)
        self.way = bi_repo.save_sell_way(
            web.conn, self.brand_id, name="單件", actor=ACTOR, product_id=self.product["id"],
            economics={"selling_price": 1000, "list_price": 1200, "unit_variable_cost": 300,
                       "shipping_cost": 100},
        )
        bi_repo.create_product_fact(
            web.conn, self.brand_id, self.product["id"], actor=ACTOR, fact_type="core_info",
            label="材質", value="3M 反光條", status="confirmed", confirmed_by=ACTOR,
        )
        bi_repo.create_claim(
            web.conn, self.brand_id, actor=ACTOR, claim_text="保證不被車撞",
            claim_type="forbidden", product_id=self.product["id"],
        )
        (self.group,) = bi_repo.save_customer_groups(
            web.conn, self.brand_id, self.product["id"],
            [{"who": "下班後夜跑的上班族", "pain_keys": ["uncertainty"]}], actor=ACTOR,
        )
        web.conn.execute(
            "INSERT INTO brand_coordinate(id,org_id,brand_id,dimension,key,label) "
            "VALUES(%s,%s,%s,'offer','discount','限定優惠價')",
            (coredb.new_id("crd"), self.org_id, self.brand_id),
        )
        self._orig = (strategy.PROVIDER, plan.PROVIDER)

    def tearDown(self):
        strategy.PROVIDER, plan.PROVIDER = self._orig

    def _campaign(self, **overrides) -> dict:
        campaign = {
            "name": "夜跑背心・這一期", "goal_text": "夜跑背心衝購買", "objective": "購買",
            "target_cost": 300, "start_date": "2026-10-01", "end_date": "2026-10-10",
            "status": "draft", "context_json": {
                "product_ids": [self.way["id"]], "field_sources": {"cap": "user"},
            },
        }
        campaign.update(overrides)
        row = ads_repo.create_campaign(web.conn, self.org_id, self.brand_id, campaign,
                                       created_by=ACTOR)
        found = ads_repo.get_campaign(web.conn, self.org_id, self.brand_id, row["id"])
        assert found is not None
        return found

    def _context(self, campaign=None) -> dict:
        return planner_context.planner_context(
            web.conn, self.org_id, self.brand_id, self.way["id"], campaign=campaign,
        )


class PlannerContextTest(_Fixture):
    def test_context_carries_every_part_for_the_sell_way(self):
        other = bi_repo.create_product(web.conn, self.brand_id, name="登山背心", actor=ACTOR)
        bi_repo.record_learning(
            web.conn, self.brand_id, actor=ACTOR, learning_text="夜跑背心：反光角度有效",
            applicability_scope="brand", confidence="likely", sample_size="中",
            product_id=self.way["id"],
        )
        bi_repo.record_learning(
            web.conn, self.brand_id, actor=ACTOR, learning_text="登山背心：輕量角度有效",
            applicability_scope="brand", confidence="likely", sample_size="中",
            product_id=other["id"],
        )
        previous = self._campaign(
            name="夜跑背心・上一期", status="closed",
            budget_basis_json={"strategy": {"learning_goals": ["哪一群比較便宜"]}},
        )
        allocation = [{"role": "new", "pct": 60}, {"role": "explore", "pct": 40}]
        campaign = self._campaign(
            budget_planned=18000, budget_basis_json={"strategy": {"allocation": allocation}},
        )

        ctx = self._context(campaign)

        product = ctx["product"]
        self.assertEqual((product["id"], product["name"]), (self.way["id"], "夜跑背心 · 單件"))
        self.assertEqual((product["kind"], product["kind_label"]), ("base", "單品"))
        self.assertEqual(product["knowledge"][0]["facts"], ["材質：3M 反光條"])
        self.assertEqual(product["price"], 1000)
        self.assertEqual(ctx["forbidden"], ["保證不被車撞"])
        (offer,) = ctx["offers"]
        self.assertEqual((offer["key"], offer["label"]), ("discount", "限定優惠價"))
        self.assertIn("1,200", offer["sentence"])
        self.assertEqual([g["id"] for g in ctx["customer_groups"]], [self.group["id"]])
        self.assertEqual([r["learning_text"] for r in ctx["learnings"]["ads"]],
                         ["夜跑背心：反光角度有效"])
        self.assertEqual(ctx["previous"]["campaign_id"], previous["id"])
        self.assertEqual(ctx["previous"]["learning_goals"], ["哪一群比較便宜"])
        # 18000 over 10 days = 1800 a day; at cap 300 that carries floor(1800 / 600) = 3 ads.
        self.assertEqual(ctx["capacity"],
                         {"daily": 1800, "cap": 300.0, "can_support": 3, "ceiling": 4})

        texts = {which: planner_context.section_text(ctx, which) for which in (
            "product", "forbidden", "offers", "customers", "learnings", "ranked", "previous",
            "capacity")}
        self.assertIn("單件 NT$1000.00｜單品", texts["product"])
        self.assertEqual(texts["forbidden"], "【不能講】\n- 保證不被車撞")
        self.assertTrue(texts["offers"].startswith("【這期可用的優惠】\n- offer=discount｜"))
        self.assertIn("- 哪一群比較便宜", texts["previous"])
        self.assertIn("這期每天 1,800，撐得起 3 則（另加 1 則探索）；最多 4 則", texts["capacity"])
        self.assertNotIn("登山背心", texts["learnings"])

    def test_without_a_campaign_there_is_no_capacity_and_nothing_previous(self):
        ctx = self._context()
        self.assertIsNone(ctx["capacity"])
        self.assertIsNone(ctx["previous"])
        self.assertIn("還算不出", planner_context.section_text(ctx, "capacity"))
        self.assertIn("還沒有結案過", planner_context.section_text(ctx, "previous"))

    def test_a_bundle_reads_as_a_combination(self):
        bundle = bi_repo.save_sell_way(
            web.conn, self.brand_id, name="雙件組", actor=ACTOR,
            components=[{"sell_way_id": self.way["id"], "qty": 2}],
            economics={"selling_price": 1800},
        )
        ctx = planner_context.planner_context(web.conn, self.org_id, self.brand_id, bundle["id"])
        self.assertEqual(ctx["product"]["kind_label"], "組合")
        self.assertIn("NT$1800.00｜組合", planner_context.section_text(ctx, "product"))


class StrategyPromptAndFactsTest(_Fixture):
    def _generate(self, campaign: dict, reply) -> tuple[dict, str]:
        provider = _fake(reply)
        strategy.PROVIDER = provider
        detail = strategy.generate(web.conn, self.org_id, self.brand_id, campaign["id"],
                                   actor=ACTOR)
        return detail, provider.calls[0]["messages"][0]["content"]

    def test_prompt_prints_every_planner_block_in_order(self):
        detail, prompt = self._generate(self._campaign(), _reply())
        # The department file names these headers too: the last occurrence is the section.
        positions = [prompt.rindex(header) for header in _HEADERS]
        self.assertEqual(positions, sorted(positions))
        self.assertLess(prompt.rindex("【品牌事實】"), positions[0])
        self.assertLess(positions[-1], prompt.rindex("【程式算好的預算情境"))
        self.assertIn("- 保證不被車撞", prompt)
        basis = detail["budget_basis_json"]["basis"]["planner_context"]
        self.assertEqual(basis, {"product_id": self.way["id"], "forbidden_count": 1,
                                 "offers": ["discount"], "previous_campaign_id": None})

    def test_a_number_in_the_prose_is_refused(self):
        campaign = self._campaign()
        reply = _reply()
        reply["allocation"][0]["rationale"] = "上一期每筆 392 最便宜"
        with self.assertRaisesRegex(ValueError, "strategy_failed"):
            self._generate(campaign, reply)
        for key, value in (("why", ["省下 20%"]), ("unknowns", ["NT$ 多少才夠"]),
                           ("learning_goals", ["第 2 群的反應"]), ("alternatives", [1])):
            with self.subTest(key=key):
                self.assertIsNone(strategy._validate_reply(  # noqa: SLF001
                    _reply(**{key: value}), frozenset({"new", "explore"})))
        self.assertIsNotNone(strategy._validate_reply(  # noqa: SLF001
            _reply(), frozenset({"new", "explore"})))
        stored = ads_repo.get_campaign(web.conn, self.org_id, self.brand_id, campaign["id"])
        assert stored is not None
        self.assertEqual(stored["budget_basis_json"], {})

    def test_a_name_from_the_context_may_be_quoted_but_no_other_digit(self):
        """Lead review: a registered name with a digit (「咖啡因 150mg」) is stripped before the
        number check; 「每筆 392」 and a digit in a name the context never gave still refuse."""
        coffee = bi_repo.create_product(web.conn, self.brand_id, name="咖啡因 150mg", actor=ACTOR)
        way = bi_repo.save_sell_way(web.conn, self.brand_id, name="單盒", actor=ACTOR,
                                    product_id=coffee["id"], economics={"selling_price": 500})
        context = {"product_ids": [way["id"]]}
        ctx = planner_context.planner_context(web.conn, self.org_id, self.brand_id, way["id"])
        self.assertIn("咖啡因 150mg", planner_context.quoted_names(ctx))

        quoted = _reply()
        quoted["allocation"][0]["rationale"] = "先推咖啡因 150mg 給加班的上班族"
        quoted["why"] = ["「咖啡因 150mg」是這個賣法唯一的商品"]
        detail, _ = self._generate(self._campaign(context_json=context), quoted)
        self.assertEqual(detail["budget_basis_json"]["strategy"]["allocation"][0]["rationale"],
                         "先推咖啡因 150mg 給加班的上班族")

        for rationale in ("咖啡因 150mg 每筆 392 最便宜", "改推維他命 C 1000mg"):
            with self.subTest(rationale=rationale):
                reply = _reply()
                reply["allocation"][0]["rationale"] = rationale
                with self.assertRaisesRegex(ValueError, "strategy_failed"):
                    self._generate(self._campaign(context_json=context), reply)

    def test_facts_are_the_programs_before_and_after_adoption(self):
        campaign = self._campaign()
        detail, _ = self._generate(campaign, _reply())
        facts = {f["kind"]: f["text"] for f in detail["budget_basis_json"]["strategy"]["facts"]}
        self.assertEqual(list(facts), ["groups", "offers", "numbers", "capacity", "learnings"])
        self.assertEqual(facts["groups"], "可選顧客群：下班後夜跑的上班族")
        self.assertTrue(facts["offers"].startswith("可用的優惠：〈限定優惠價〉"), facts["offers"])
        self.assertIn("上限每筆 300", facts["numbers"])
        self.assertIn("這個賣法還沒有結案過", facts["numbers"])
        self.assertIn("撐得起", facts["capacity"])

        strategy.select_scenario(web.conn, self.org_id, self.brand_id, campaign["id"],
                                 scenario_key="custom", custom_total=18000, actor=ACTOR)
        coordinates = dict.fromkeys(
            ("audience", "pain", "angle", "hook", "proof", "offer", "format"), "x")
        plan.PROVIDER = _fake({"groups": [
            {"role": role, "name": f"{role} 組", "ads": [{
                "name": f"{role} 廣告", "customer_group": 1,
                "scene": f"{role} 晚上下班後在河濱夜跑",
                "coordinates": {**coordinates, "offer": "discount" if role == "new" else "none"},
            }]} for role in ("new", "explore")
        ]})
        current = ads_repo.get_campaign(web.conn, self.org_id, self.brand_id, campaign["id"])
        plan.adopt_strategy(web.conn, self.org_id, self.brand_id, campaign["id"], actor=ACTOR,
                            expected_revision=current["budget_basis_json"]["strategy"]["decision"]["revision"],
                            operation_id="context-fixture-adopt")

        detail = ads_repo.campaign_detail(web.conn, self.org_id, self.brand_id, campaign["id"])
        assert detail is not None
        facts = {f["kind"]: f["text"] for f in detail["budget_basis_json"]["strategy"]["facts"]}
        self.assertEqual(facts["groups"], "這期打 1 群：下班後夜跑的上班族")
        self.assertEqual(facts["offers"], "用了〈限定優惠價〉 1 則")
        self.assertIn("這期每天 1,800，撐得起 3 則（另加 1 則探索）；最多 4 則", facts["capacity"])


# -- machine check ---------------------------------------------------------------------------------

# Modules that call the model with an `ads_*` task but plan nothing -- each with why.
NOT_A_PLANNER = {
    "angles.py": "three angle candidates for one ad's existing copy, not a plan",
    "asset_suggestions.py": "copy suggestions for an uploaded asset; its guard is workbench's",
    "review_jobs.py": "a review round over a closed period's evidence, not a plan",
}
# module -> the issue that wires it to planner_context and deletes the entry (F48-I06 emptied it).
PENDING: dict = {}


def _constants(tree) -> dict:
    return {
        target.id: node.value.value
        for node in tree.body if isinstance(node, ast.Assign)
        and isinstance(node.value, ast.Constant) and isinstance(node.value.value, str)
        for target in node.targets if isinstance(target, ast.Name)
    }


def _task_type(node, constants: dict):
    """The literal task type of a `task_type=` argument: a string, a module constant, or another
    ads module's constant (`review_rounds.TASK_TYPE`); `None` when it cannot be read."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.Name):
        return constants.get(node.id)
    if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name):
        other = ADS_DIR / f"{node.value.id}.py"
        if other.exists():
            return _constants(ast.parse(other.read_text(encoding="utf-8"))).get(node.attr)
    return None


def _ads_task_modules() -> dict:
    """`{file: calls planner_context}` for every app/ads module calling `run_task` with an
    `ads_*` task type. A `task_type` this check cannot read fails, naming file and line."""
    found = {}
    for path in sorted(ADS_DIR.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        constants = _constants(tree)
        calls = [n for n in ast.walk(tree) if isinstance(n, ast.Call)]
        names = {getattr(c.func, "attr", getattr(c.func, "id", None)) for c in calls}
        for call in calls:
            if getattr(call.func, "attr", None) != "run_task":
                continue
            arg = next((k.value for k in call.keywords if k.arg == "task_type"), None)
            task_type = _task_type(arg, constants)
            if task_type is None:
                raise AssertionError(f"{path.name}:{call.lineno}: run_task task_type unreadable")
            if task_type.startswith("ads_"):
                found[path.name] = "planner_context" in names
    return found


class EveryPlannerReadsThePlannerContextTest(unittest.TestCase):
    def test_every_ads_model_call_reads_planner_context(self):
        found = _ads_task_modules()
        self.assertLessEqual({"brief.py", "strategy.py"}, set(found))
        missing = sorted(
            name for name, reads in found.items()
            if not reads and name not in NOT_A_PLANNER and name not in PENDING
        )
        self.assertEqual(missing, [], "call planner_context(...) before the model (Contract P)")
        stale = sorted(name for name in {**NOT_A_PLANNER, **PENDING} if name not in found)
        self.assertEqual(stale, [], "allowlist entries that no longer call an ads_ task")
        done = sorted(name for name in PENDING if found.get(name))
        self.assertEqual(done, [], "pending entries that now read planner_context: delete them")

    def test_hand_edits_read_the_planners_menu(self):
        """`plan.create_ad`／`update_ad` call `planner_context.menu` -- the filter the delivery
        plan's prompt is built from -- and plan.py keeps no menu filter of its own."""
        tree = ast.parse((ADS_DIR / "plan.py").read_text(encoding="utf-8"))
        functions = {n.name: n for n in tree.body if isinstance(n, ast.FunctionDef)}
        for name in ("create_ad", "update_ad"):
            calls = {
                (c.func.value.id, c.func.attr) for c in ast.walk(functions[name])
                if isinstance(c, ast.Call) and isinstance(c.func, ast.Attribute)
                and isinstance(c.func.value, ast.Name)
            }
            self.assertIn(("planner_context", "menu"), calls, name)
        self.assertNotIn("_prompt_rows", functions)


if __name__ == "__main__":
    unittest.main()
