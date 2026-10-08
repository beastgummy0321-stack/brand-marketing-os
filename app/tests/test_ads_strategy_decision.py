"""F52 Contract S: an accepted assignment must survive adoption unchanged."""

import json
import unittest
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from threading import Barrier
from unittest import mock

import app.shared.web as web
from app.ads import plan, planner_context, sell_way, strategy
from app.ads import repository as ads_repo
from app.brand_intelligence import repository as bi_repo
from app.core import db as coredb
from app.llm import providers


def fixture_provider(rendered_output):
    """Upgrade deliberate fixture assignments, without repairing invalid tested semantics."""

    class BoundFixtureProvider(providers.FakeProvider):
        def complete(self, **kwargs):
            response = super().complete(**kwargs)
            try:
                reply = json.loads(response.output_text)
            except (ValueError, TypeError):
                return response
            prompt = kwargs["messages"][-1]["content"]
            if isinstance(reply, dict) and "allocation" in reply and "slots" not in reply:
                binding = providers.ScriptedProvider._json_section(prompt, "【可綁定安排】")
                if binding:
                    customers = binding["customers"]
                    reply["slots"] = [
                        {
                            "id": f"slot-{row.get('role')}-0",
                            "role": row.get("role"),
                            "customer_group_id": customers[0]["id"] if customers else None,
                            "offer_key": binding["offers"][0]["key"]
                            if binding["offers"] and n == 0
                            else "none",
                            "carry_from_ad_id": None,
                            "test_intent": "Test a buyer proposition",
                            "evidence_refs": binding["evidence_refs"][:1],
                            "rationale": (
                                "Prepared evidence supports this buyer test; "
                                "samples remain limited."
                            ),
                        }
                        for n, row in enumerate(reply["allocation"])
                        if isinstance(row, dict)
                    ]
            elif isinstance(reply, dict) and "groups" in reply:
                bound = providers.ScriptedProvider._json_section(prompt, "【已確認的新安排】")
                if bound:
                    for group in reply["groups"]:
                        slots = [s for s in bound if s["role"] == group.get("role")]
                        for n, ad in enumerate(group.get("ads") or []):
                            if n < len(slots):
                                ad.setdefault("slot_id", slots[n]["id"])
            response.output_text = json.dumps(reply, ensure_ascii=False)
            return response

    return BoundFixtureProvider(
        response=providers.ProviderResponse(
            output_text=rendered_output,
            structured=None,
            usage=providers.Usage(input_tokens=100, output_tokens=50),
            stop_reason="end_turn",
        )
    )


def bind_fixture(conn, org, brand, campaign_id, reply=None):
    """Explicitly prepare a confirmed fixture decision; legacy rejection tests do not call it."""
    campaign = ads_repo.get_campaign(conn, org, brand, campaign_id)
    ctx = planner_context.planner_context(
        conn, org, brand, sell_way.of_campaign(campaign), campaign=campaign
    )
    _, ctx["brand_facts"] = strategy._brand_facts_section(conn, brand)
    refs = strategy.decision_context(ctx, campaign)["evidence_refs"][:1]
    basis = deepcopy(campaign["budget_basis_json"])
    payload = basis["strategy"]
    groups = {g["role"]: g for g in (reply or {}).get("groups", [])}
    eligible = [
        i
        for i in ctx["carried_candidates"]
        if i["creative"] is not None and (i.get("eligibility") or {}).get("state") != "blocked"
    ]
    carried = plan._select_carried(
        eligible, [r["role"] for r in payload["allocation"]], plan._ceiling(ctx["capacity"])
    )
    proposed = []
    for item in carried:
        if item["creative"] is not None:
            proposed.append(
                {
                    "id": f"carry-{item['ad']['id']}",
                    "role": item["target"],
                    "customer_group_id": item["ad"].get("customer_group_id"),
                    "offer_key": item["ad"].get("offer_key"),
                    "carry_from_ad_id": item["ad"]["id"],
                    "test_intent": None,
                    "evidence_refs": refs,
                    "rationale": (
                        "Carry the observed original; relative results do not establish an optimum."
                    ),
                }
            )
    for role_row in payload["allocation"]:
        role = role_row["role"]
        planned = groups.get(role, {}).get("ads")
        if (
            ctx["capacity"]
            and len(proposed) >= ctx["capacity"]["ceiling"]
            and not any(s["carry_from_ad_id"] is None for s in proposed)
        ):
            continue
        if planned is None and any(s["role"] == role for s in proposed):
            continue
        first_number = (planned or [{}])[0].get("customer_group")
        for n, ad in enumerate((planned or [{}])[: plan._MAX_ADS_PER_GROUP]):
            number = first_number
            listed = ctx["customer_groups"]
            first = listed[0]["id"] if listed else None
            gid = (
                listed[number - 1]["id"]
                if (
                    isinstance(number, int)
                    and not isinstance(number, bool)
                    and 1 <= number <= len(listed)
                )
                else first
            )
            offer = (ad.get("coordinates") or {}).get("offer", "none")
            if offer not in {o["key"] for o in ctx["offers"]}:
                offer = "none"
            proposed.append(
                {
                    "id": f"slot-{role}-{n}",
                    "role": role,
                    "customer_group_id": gid,
                    "offer_key": offer,
                    "carry_from_ad_id": None,
                    "test_intent": "Test a buyer proposition",
                    "evidence_refs": refs,
                    "rationale": (
                        "Test this buyer proposition against the prepared evidence; "
                        "samples are limited."
                    ),
                }
            )
    payload["slots"] = proposed
    payload["decision"] = strategy.executable_decision(ctx, campaign, payload)
    payload.pop("slots")
    ads_repo.save_strategy(conn, org, brand, campaign_id, budget_basis_json=basis)
    return payload["decision"]["revision"]


class DecisionRegressionTest(unittest.TestCase):
    def test_provider_acceptance_requires_a_ready_production_decision(self):
        from scripts.drill import first_release_acceptance as runner

        frozen = runner.provider_input()
        original = frozen["output_shape"]
        valid = {"status": "succeeded", "rendered_output": json.dumps(original)}
        checked = runner.validate_provider_output(valid)
        self.assertEqual(checked["status"], "contract-pass")
        self.assertEqual(checked["decision"]["feasibility"]["state"], "ready")
        self.assertEqual(frozen["capacity"], planner_context.capacity_of(300, 300))
        for mutation in ("role-audience", "duplicate-id", "unallocated-role", "missing-role",
                         "over-capacity", "blank-rationale", "blank-intent", "missing-nullable"):
            with self.subTest(mutation=mutation):
                reply = deepcopy(original)
                slot = reply["slots"][0]
                if mutation in ("role-audience", "duplicate-id"):
                    reply["slots"].append({**slot, "id": "another", "customer_group_id": "A2"
                                           if mutation == "role-audience" else "A1"})
                    if mutation == "duplicate-id":
                        reply["slots"][1]["id"] = slot["id"]
                elif mutation == "unallocated-role":
                    slot["role"] = "explore"
                elif mutation == "missing-role":
                    reply["allocation"][0]["pct"] = 50
                    reply["allocation"].append({"role": "explore", "pct": 50,
                                                "rationale": "Distinct test."})
                elif mutation == "over-capacity":
                    reply["slots"] += [{**slot, "id": "another"}, {**slot, "id": "extra"}]
                elif mutation == "blank-rationale":
                    slot["rationale"] = " "
                elif mutation == "blank-intent":
                    slot["test_intent"] = " "
                else:
                    del slot["carry_from_ad_id"]
                task = {"status": "succeeded", "rendered_output": json.dumps(reply)}
                self.assertEqual(runner.validate_provider_output(task)["status"], "unverified")

    def test_preserved_provider_invalid_number_and_object_alternative_shapes_stay_refused(self):
        from scripts.drill import first_release_acceptance as runner

        for mutation in ("number", "alternative-object", "both"):
            with self.subTest(mutation=mutation):
                reply = deepcopy(runner.provider_input()["output_shape"])
                if mutation in ("number", "both"):
                    reply["unknowns"] = ["觀測到的 2 個 result events 是否可重現未知。"]
                if mutation in ("alternative-object", "both"):
                    reply["alternatives"] = [{"offer_key": "shipping", "status": "尚未測試"}]
                self.assertIsNone(strategy._validate_reply(reply, frozenset({"new", "explore"})))
                task = {"status": "succeeded", "rendered_output": json.dumps(reply)}
                self.assertEqual(runner.validate_provider_output(task)["status"], "unverified")

    def test_strategy_keeps_explicit_slots(self):
        slot = {
            "id": "slot-explore",
            "role": "explore",
            "customer_group_id": None,
            "offer_key": "none",
            "carry_from_ad_id": None,
            "test_intent": "Test a buyer proposition",
            "evidence_refs": [],
            "rationale": "Test a buyer proposition; no observed results are available.",
        }
        payload = strategy._validate_reply(
            {
                "allocation": [{"role": "explore", "pct": 100}],
                "slots": [slot],
                "why": [],
                "unknowns": [],
                "alternatives": [],
            },
            frozenset({"explore"}),
        )
        self.assertEqual(payload["slots"], [slot])

    def test_carry_never_silently_changes_a_role(self):
        with self.assertRaises(ValueError):
            plan._target_role("explore", ["new"])

    def test_display_keeps_observed_sample_limits_on_result_and_learning_refs(self):
        ctx = {
            "customer_groups": [], "offers": [], "carried_candidates": [],
            "ranked_ids": ["learn"], "brand_facts": [], "calendar_evidence": [],
            "learnings": {"ads": [], "ranked": {"campaigns": [{
                "campaign_name": "Earlier period", "rows": [{
                    "ad_id": "ad", "ad_name": "Original", "learning_id": "learn",
                    "verdict_label": "留下", "flags": ["樣本少", "相對最好，仍高於上限"],
                }],
            }]}},
        }
        display = strategy._slot_display(ctx, {
            "customer_group_id": None, "offer_key": "none", "carry_from_ad_id": None,
            "evidence_refs": [{"kind": "result", "id": "ad"}, {"kind": "learning", "id": "learn"}],
        })
        self.assertEqual(display["customer_group_label"], "尚未指定顧客群")
        for reference in display["evidence"]:
            self.assertEqual(
                reference["label"], "Earlier period／Original（留下・樣本少・相對最好，仍高於上限）"
            )


class ExecutableDecisionAcceptanceTest(unittest.TestCase):
    def setUp(self):
        self.org = coredb.DEV_ORG_ID
        self.brand = bi_repo.create_brand(
            web.conn, org_id=self.org, name="Decision contract", client_name=None, actor="tester"
        )["id"]
        product = bi_repo.create_product(web.conn, self.brand, name="Fuel", actor="tester")
        self.way = bi_repo.save_sell_way(
            web.conn,
            self.brand,
            name="One box",
            actor="tester",
            product_id=product["id"],
            free_shipping=True,
            economics={
                "selling_price": 1000,
                "list_price": 1200,
                "unit_variable_cost": 300,
                "shipping_cost": 100,
            },
        )
        self.people = bi_repo.save_customer_groups(
            web.conn,
            self.brand,
            product["id"],
            [
                {"who": "Fitness buyers", "pain_keys": ["effort"]},
                {"who": "Students", "pain_keys": ["cost"]},
            ],
            actor="tester",
        )
        for key in ("free_shipping", "discount"):
            web.conn.execute(
                "INSERT INTO brand_coordinate(id,org_id,brand_id,dimension,key,label) "
                "VALUES(%s,%s,%s,'offer',%s,%s)",
                (coredb.new_id("crd"), self.org, self.brand, key, key),
            )
        self.original = (strategy.PROVIDER, plan.PROVIDER)
        plan.PROVIDER = providers.ScriptedProvider(providers.SCRIPTED_REPLIES["ads_delivery_plan"])

    def tearDown(self):
        strategy.PROVIDER, plan.PROVIDER = self.original

    def campaign(self, daily=600):
        return ads_repo.create_campaign(
            web.conn,
            self.org,
            self.brand,
            {
                "name": "Decision period",
                "goal_text": "Test a buying proposition",
                "objective": "購買",
                "target_cost": 300,
                "start_date": "2026-10-01",
                "end_date": "2026-10-10",
                "status": "draft",
                "budget_planned": daily * 10,
                "budget_scenario": "custom",
                "context_json": {"product_ids": [self.way["id"]]},
            },
            created_by="tester",
        )

    def slot(self, role, group, offer="free_shipping", carry=None, sid=None):
        return {
            "id": sid or f"slot-{role}",
            "role": role,
            "customer_group_id": group,
            "offer_key": offer,
            "carry_from_ad_id": carry,
            "test_intent": None if carry else "Test why this audience would buy",
            "evidence_refs": [],
            "rationale": (
                "Use the cited prepared evidence to test this audience; samples are limited."
            ),
        }

    def propose(self, campaign, slots, pcts=None):
        current = ads_repo.get_campaign(web.conn, self.org, self.brand, campaign["id"])
        ctx = planner_context.planner_context(
            web.conn, self.org, self.brand, self.way["id"], campaign=current
        )
        _, ctx["brand_facts"] = strategy._brand_facts_section(web.conn, self.brand)
        refs = strategy.decision_context(ctx, current)["evidence_refs"][:1]
        slots = deepcopy(slots)
        for slot in slots:
            slot["evidence_refs"] = refs
        roles = list(dict.fromkeys(s["role"] for s in slots))
        pcts = pcts or [100 / len(roles)] * len(roles)
        payload = {
            "allocation": [
                {
                    "role": role,
                    "label": role,
                    "pct": pct,
                    "rationale": "A recommendation with limited samples",
                }
                for role, pct in zip(roles, pcts, strict=True)
            ],
            "why": [],
            "unknowns": [],
            "alternatives": [],
            "slots": slots,
        }
        decision = strategy.executable_decision(ctx, current, payload)
        payload["decision"] = decision
        payload.pop("slots")
        ads_repo.save_strategy(
            web.conn,
            self.org,
            self.brand,
            campaign["id"],
            budget_basis_json={
                "strategy": payload,
                "scenarios": {
                    "mode": "cold_start",
                    "recommended": "custom",
                    "basis": {},
                    "scenarios": [
                        {
                            "key": "custom",
                            "label": "Custom",
                            "caption": "",
                            "daily": int(current["budget_planned"]) // 10,
                            "total": int(current["budget_planned"]),
                        }
                    ],
                },
            },
        )
        web.conn.commit()
        return decision

    def adopt(self, campaign, decision, operation="acceptance-adopt", conn=None):
        return plan.adopt_strategy(
            conn or web.conn,
            self.org,
            self.brand,
            campaign["id"],
            actor="tester",
            expected_revision=decision["revision"],
            operation_id=operation,
        )

    def test_same_learning_id_changed_meaning_blocks_before_adoption_and_reconfirmation_works(self):
        campaign = self.campaign()
        learned = bi_repo.record_learning(
            web.conn, self.brand, actor="tester", learning_text="Original limited observation",
            product_id=self.way["id"], applicability_scope="brand", source_track="ads",
            confidence="validated", sample_size="10",
        )
        decision = self.propose(campaign, [self.slot("new", self.people[0]["id"], "none")])
        read = bi_repo.list_learnings

        def changed(*args, **kwargs):
            return [{**row, "learning_text": "Changed observation under the same ID",
                     "needs_revalidation": True} if row["id"] == learned["id"] else row
                    for row in read(*args, **kwargs)]

        with mock.patch.object(bi_repo, "list_learnings", side_effect=changed):
            detail = ads_repo.campaign_detail(web.conn, self.org, self.brand, campaign["id"])
            shown = detail["budget_basis_json"]["strategy"]["decision"]
            self.assertIn("strategy_changed", {r["code"] for r in shown["feasibility"]["reasons"]})
            with self.assertRaises(plan.StrategyConflict) as failure:
                self.adopt(campaign, decision)
            self.assertEqual(str(failure.exception), "strategy_changed")
            self.assert_empty(campaign)
            again = self.propose(campaign, [self.slot("new", self.people[0]["id"], "none")])
            self.assertNotEqual(again["revision"], decision["revision"])
            self.adopt(campaign, again, operation="reconfirmed-meaning")
        groups = ads_repo.campaign_detail(web.conn, self.org, self.brand, campaign["id"])["groups"]
        self.assertEqual(groups[0]["ads"][0]["offer_key"], "none")

    def test_served_labels_follow_each_binding_without_mutating_saved_decision(self):
        prior, _ = self.previous()
        campaign = self.campaign()
        accepted = self.propose(campaign, [
            self.slot("new", self.people[1]["id"]),
            self.slot("explore", self.people[0]["id"], "none", prior["id"]),
        ])
        current = ads_repo.get_campaign(web.conn, self.org, self.brand, campaign["id"])
        original = deepcopy(current)
        served = strategy.served_decision(web.conn, self.org, self.brand, current, [])
        self.assertEqual(served["revision"], accepted["revision"])
        self.assertEqual(served["slots"][0]["display"]["customer_group_label"], "Students")
        self.assertIn("免運", served["slots"][0]["display"]["offer_label"])
        self.assertEqual(served["slots"][1]["display"]["customer_group_label"], "Fitness buyers")
        self.assertEqual(served["slots"][1]["display"]["offer_label"], "不使用優惠")
        self.assertEqual(served["slots"][1]["display"]["carried_ad_label"], prior["name"])
        self.assertEqual(current, original)
        served["slots"][0]["evidence_refs"].append({"kind": "result", "id": "modified-read"})
        self.assertEqual(current, original)
        self.assertEqual(
            ads_repo.get_campaign(web.conn, self.org, self.brand, campaign["id"]), original
        )

    def test_served_unknown_labels_do_not_invent_an_audience_or_original(self):
        campaign = self.campaign()
        self.propose(campaign, [self.slot("new", None, "none")])
        current = ads_repo.get_campaign(web.conn, self.org, self.brand, campaign["id"])
        slot = current["budget_basis_json"]["strategy"]["decision"]["slots"][0]
        slot.update(customer_group_id="deleted", offer_key="deleted", carry_from_ad_id="deleted")
        slot["evidence_refs"] = [{"kind": "learning", "id": "deleted"}] * 5
        original = deepcopy(current)
        served = strategy.served_decision(web.conn, self.org, self.brand, current, [])
        display = served["slots"][0]["display"]
        self.assertEqual(display["customer_group_label"], "已刪除或不在本期的顧客群")
        self.assertEqual(display["offer_label"], "已失效或不在本期的優惠")
        self.assertEqual(display["carried_ad_label"], "原廣告已不在可保留資料中")
        self.assertEqual(display["evidence"][0]["label"], "依據已不在本期資料中")
        self.assertEqual(display["evidence_omitted"], 2)
        self.assertEqual(len(served["slots"][0]["evidence_refs"]), 5)
        self.assertEqual(served["feasibility"]["state"], "blocked")
        self.assertEqual(current, original)

    def assert_empty(self, campaign):
        detail = ads_repo.campaign_detail(web.conn, self.org, self.brand, campaign["id"])
        self.assertEqual(detail["groups"], [])
        self.assertEqual(detail["status"], "draft")

    def previous(self, role="explore", offer="none"):
        from app.tests.test_ads_plan import _seed_previous_with_creatives

        previous, ads, assets = _seed_previous_with_creatives(
            self.org, self.brand, [("Kept fitness", "kept", "keep_relative", True)]
        )
        web.conn.execute(
            "UPDATE ads_campaign SET context_json=%s WHERE id=%s",
            (coredb.jsonb({"product_ids": [self.way["id"]]}), previous["id"]),
        )
        ads_repo.update_group_fields(
            web.conn, self.org, self.brand, ads[0]["group_id"], {"role": role}
        )
        web.conn.execute(
            "UPDATE ads_ad SET customer_group_id=%s WHERE id=%s",
            (self.people[0]["id"], ads[0]["id"]),
        )
        if offer != "none":
            web.conn.execute("UPDATE ads_ad SET offer_key=%s WHERE id=%s", (offer, ads[0]["id"]))
            web.conn.execute(
                "UPDATE ads_asset_placement SET copy_fields=jsonb_set(copy_fields,"
                "'{body}',to_jsonb((copy_fields->>'body') || '；免運')) WHERE asset_id=%s",
                (assets[0],),
            )
        web.conn.commit()
        return ads[0], assets[0]

    def test_ceiling_two_preserves_explore_and_tests_student_with_exact_offer(self):
        prior, asset = self.previous()
        campaign = self.campaign()
        decision = self.propose(
            campaign,
            [
                self.slot("explore", self.people[0]["id"], "none", prior["id"]),
                self.slot("new", self.people[1]["id"], "free_shipping"),
            ],
            [60, 40],
        )
        self.assertEqual(decision["feasibility"]["state"], "ready")
        detail = self.adopt(campaign, decision)
        actual = {g["role"]: g for g in detail["groups"]}
        self.assertEqual(
            {r: int(g["daily_budget"]) for r, g in actual.items()}, {"explore": 360, "new": 240}
        )
        self.assertEqual(actual["explore"]["ads"][0]["customer_group_id"], self.people[0]["id"])
        self.assertEqual(actual["new"]["ads"][0]["customer_group_id"], self.people[1]["id"])
        self.assertEqual(actual["new"]["ads"][0]["offer_key"], "free_shipping")
        carried = actual["explore"]["ads"][0]
        material = web.conn.execute(
            "SELECT asset_id,copy_fields FROM ads_asset_placement WHERE id=%s AND revision=%s",
            (carried["material_placement_id"], carried["material_placement_revision"]),
        ).fetchone()
        self.assertEqual(material["asset_id"], asset)
        self.assertEqual(material["copy_fields"]["headline"], "上一期的標題")
        receipt = detail["budget_basis_json"]["strategy"]["decision"]["receipt"]
        self.assertEqual({s["slot_id"] for s in receipt["slots"]}, {"slot-explore", "slot-new"})
        self.assertEqual(receipt["revision"], decision["revision"])
        facts = detail["budget_basis_json"]["strategy"]["decision"]["facts"]
        self.assertEqual(
            (facts["actual"]["customer_groups"], facts["actual"]["delivery_groups"]), (2, 2)
        )
        replay = self.adopt(campaign, decision)
        self.assertEqual(replay["groups"], detail["groups"])

    def test_atomic_carry_failure_writes_no_plan_or_receipt_and_retry_succeeds(self):
        from app.ads import handoff_assignment

        prior, _ = self.previous()
        campaign = self.campaign()
        decision = self.propose(
            campaign,
            [
                self.slot("explore", self.people[0]["id"], "none", prior["id"]),
                self.slot("new", self.people[1]["id"]),
            ],
        )
        before = ads_repo.get_campaign(web.conn, self.org, self.brand, campaign["id"])
        original_placements = web.conn.execute(
            "SELECT * FROM ads_asset_placement WHERE asset_id IN "
            "(SELECT asset_id FROM ads_asset_placement WHERE campaign_id=%s)",
            (prior["campaign_id"],),
        ).fetchall()

        def refuse_after_confirmation(conn, org, brand, cid, adid, placement, revision, **kwargs):
            created = conn.execute(
                "SELECT * FROM ads_asset_placement WHERE id=%s", (placement,)
            ).fetchone()
            self.assertIsNotNone(created["confirmed_at"])
            self.assertFalse(kwargs["commit"])
            raise ValueError("carry failed")

        with mock.patch.object(handoff_assignment, "assign", side_effect=refuse_after_confirmation):
            with self.assertRaisesRegex(ValueError, "carry failed"):
                self.adopt(campaign, decision)
        self.assert_empty(campaign)
        stored = ads_repo.get_campaign(web.conn, self.org, self.brand, campaign["id"])
        self.assertNotIn("receipt", stored["budget_basis_json"]["strategy"]["decision"])
        rows = web.conn.execute(
            "SELECT id FROM ads_asset_placement WHERE campaign_id=%s", (campaign["id"],)
        ).fetchall()
        self.assertEqual(rows, [])
        self.assertEqual(
            web.conn.execute(
                "SELECT id FROM ads_ad WHERE campaign_id=%s", (campaign["id"],)
            ).fetchall(),
            [],
        )
        self.assertEqual(stored["budget_planned"], before["budget_planned"])
        self.assertEqual(stored["budget_basis_json"], before["budget_basis_json"])
        tasks = web.conn.execute(
            "SELECT status,cost FROM llm_task WHERE brand_id=%s AND "
            "context_scope_json->>'campaign_id'=%s",
            (self.brand, campaign["id"]),
        ).fetchall()
        # The completed model call remains billed; the plan transaction must not undo it.
        self.assertEqual(len(tasks), 1)
        self.assertEqual(tasks[0]["status"], "succeeded")
        self.assertGreaterEqual(tasks[0]["cost"], 0)
        self.assertEqual(
            web.conn.execute(
                "SELECT * FROM ads_asset_placement WHERE asset_id IN "
                "(SELECT asset_id FROM ads_asset_placement WHERE campaign_id=%s)",
                (prior["campaign_id"],),
            ).fetchall(),
            original_placements,
        )
        self.assertEqual(self.adopt(campaign, decision)["status"], "ready")

    def test_strict_carry_confirmation_refusal_is_atomic_and_standalone_default_remains(self):
        from app.ads import asset_suggestions

        prior, _ = self.previous()
        campaign = self.campaign()
        decision = self.propose(
            campaign,
            [
                self.slot("explore", self.people[0]["id"], "none", prior["id"]),
                self.slot("new", self.people[1]["id"]),
            ],
        )
        original = asset_suggestions._result

        def blocked(*args, **kwargs):
            return {
                **original(*args, **kwargs),
                "pending_reasons": ["A changed confirmation premise"],
            }

        with mock.patch.object(asset_suggestions, "_result", side_effect=blocked):
            with mock.patch.object(
                asset_suggestions, "_refused", wraps=asset_suggestions._refused
            ) as refusal:
                with self.assertRaisesRegex(ValueError, "changed confirmation"):
                    self.adopt(campaign, decision)
                refusal.assert_not_called()
        self.assert_empty(campaign)
        self.assertEqual(
            web.conn.execute(
                "SELECT id FROM ads_asset_placement WHERE campaign_id=%s", (campaign["id"],)
            ).fetchall(),
            [],
        )

    def test_ceiling_one_and_bad_bindings_refuse_before_creation(self):
        for transform, reason in [
            (lambda ss: ss, "capacity_exceeded"),
            (
                lambda ss: [dict(ss[0], customer_group_id="other-brand")],
                "customer_group_unavailable",
            ),
            (lambda ss: [dict(ss[0], offer_key="deleted_offer")], "offer_unavailable"),
            (
                lambda ss: [dict(ss[0], carry_from_ad_id="deleted-ad", test_intent=None)],
                "carry_unavailable",
            ),
            (lambda ss: [ss[0], dict(ss[0])], "slot_id_invalid"),
        ]:
            with self.subTest(reason=reason):
                campaign = self.campaign(daily=300)
                slots = transform(
                    [
                        self.slot("new", self.people[0]["id"]),
                        self.slot("explore", self.people[1]["id"]),
                    ]
                )
                decision = self.propose(campaign, slots)
                self.assertIn(reason, {r["code"] for r in decision["feasibility"]["reasons"]})
                with self.assertRaises(plan.StrategyConflict):
                    self.adopt(campaign, decision)
                self.assert_empty(campaign)

    def test_invalid_slot_shapes_remain_readable_and_blocked(self):
        campaign = self.campaign()
        decision = self.propose(
            campaign,
            [dict(self.slot("new", self.people[0]["id"]), customer_group_id=["bad-shape"])],
        )
        view = ads_repo.campaign_detail(web.conn, self.org, self.brand, campaign["id"])
        shown = view["budget_basis_json"]["strategy"]["decision"]
        self.assertEqual(shown["feasibility"]["state"], "blocked")
        self.assertIn("slot_invalid", {r["code"] for r in shown["feasibility"]["reasons"]})
        with self.assertRaises(plan.StrategyConflict):
            self.adopt(campaign, decision)
        self.assert_empty(campaign)

    def test_each_slot_requires_its_own_rationale_and_rationale_changes_revision(self):
        campaign = self.campaign()
        slot = self.slot("new", self.people[0]["id"])
        original = self.propose(campaign, [slot])
        changed = self.propose(
            campaign,
            [
                dict(
                    slot, rationale="A different evidence-based hypothesis; samples remain limited."
                )
            ],
        )
        self.assertNotEqual(changed["revision"], original["revision"])
        for rationale in (None, "", "   ", 100):
            with self.subTest(rationale=rationale):
                blocked = self.propose(campaign, [dict(slot, rationale=rationale)])
                self.assertEqual(blocked["feasibility"]["state"], "blocked")
                self.assertIn(
                    "slot_rationale_missing", {r["code"] for r in blocked["feasibility"]["reasons"]}
                )
                with self.assertRaises(plan.StrategyConflict):
                    self.adopt(campaign, blocked)
                self.assert_empty(campaign)

    def test_changed_inputs_and_budget_revision_cannot_be_adopted(self):
        campaign = self.campaign()
        decision = self.propose(campaign, [self.slot("new", self.people[0]["id"])])
        ads_repo.update_campaign(
            web.conn, self.org, self.brand, campaign["id"], {"end_date": "2026-10-11"}
        )
        with self.assertRaisesRegex(plan.StrategyConflict, "strategy_changed"):
            self.adopt(campaign, decision)
        self.assert_empty(campaign)

    def test_customer_semantics_changed_before_adoption_refuse_without_gateway(self):
        for field in ("who", "quote", "when_used", "source"):
            with self.subTest(field=field):
                campaign = self.campaign()
                decision = self.propose(campaign, [self.slot("new", self.people[0]["id"])])
                value = "custom" if field == "source" else f"Changed {field}"
                web.conn.execute(
                    f"UPDATE product_customer_group SET {field}=%s WHERE id=%s",
                    (value, self.people[0]["id"]),
                )
                web.conn.commit()
                with mock.patch.object(
                    plan, "ask_with_one_retry", wraps=plan.ask_with_one_retry
                ) as gateway:
                    with self.assertRaisesRegex(plan.StrategyConflict, "strategy_changed"):
                        self.adopt(campaign, decision)
                    gateway.assert_not_called()
                self.assert_empty(campaign)

    def test_customer_semantics_changed_during_gateway_refuse_without_plan_writes(self):
        campaign = self.campaign()
        decision = self.propose(campaign, [self.slot("new", self.people[0]["id"])])
        original = plan.ask_with_one_retry

        def while_away(conn, *args, **kwargs):
            result = original(conn, *args, **kwargs)
            conn.execute(
                "UPDATE product_customer_group SET who=%s WHERE id=%s",
                ("A different buying audience", self.people[0]["id"]),
            )
            conn.commit()
            return result

        with mock.patch.object(plan, "ask_with_one_retry", side_effect=while_away):
            with self.assertRaisesRegex(plan.StrategyConflict, "strategy_changed"):
                self.adopt(campaign, decision)
        self.assert_empty(campaign)

    def test_slot_numeric_prose_is_blocked_using_existing_name_exception(self):
        campaign = self.campaign()
        for field in ("rationale", "test_intent"):
            for text in ("CPA is NT$1", "Expect 99% conversion"):
                with self.subTest(field=field, text=text):
                    slot = self.slot("new", self.people[0]["id"])
                    slot[field] = text
                    decision = self.propose(campaign, [slot])
                    self.assertIn(
                        "number_in_prose", {r["code"] for r in decision["feasibility"]["reasons"]}
                    )
                    with self.assertRaises(plan.StrategyConflict):
                        self.adopt(campaign, decision)
                    self.assert_empty(campaign)
                    payload, code = strategy._check_reply(
                        {
                            "allocation": [{"role": "new", "pct": 100}],
                            "slots": [slot],
                        },
                        frozenset({"new"}),
                    )
                    self.assertIsNone(payload)
                    self.assertEqual(code, "number_in_prose")
        web.conn.execute(
            "UPDATE product_customer_group SET who=%s WHERE id=%s",
            ("Buyers of caffeine 150mg", self.people[0]["id"]),
        )
        slot = self.slot("new", self.people[0]["id"])
        slot["rationale"] = "Test Buyers of caffeine 150mg; samples are limited."
        self.assertEqual(self.propose(campaign, [slot])["feasibility"]["state"], "ready")
        payload, code = strategy._check_reply(
            {
                "allocation": [{"role": "new", "pct": 100}],
                "slots": [slot],
            },
            frozenset({"new"}),
            ["Buyers of caffeine 150mg"],
        )
        self.assertIsNotNone(payload)
        self.assertIsNone(code)

    def test_nullable_slot_keys_are_required_before_adoption(self):
        campaign = self.campaign()
        for field in ("customer_group_id", "carry_from_ad_id", "test_intent"):
            with self.subTest(field=field):
                slot = self.slot("new", self.people[0]["id"])
                del slot[field]
                decision = self.propose(campaign, [slot])
                self.assertIn(
                    "slot_invalid", {r["code"] for r in decision["feasibility"]["reasons"]}
                )
                with self.assertRaises(plan.StrategyConflict):
                    self.adopt(campaign, decision)
                self.assert_empty(campaign)

    def test_explicit_no_offer_tests_are_legal_when_offers_exist(self):
        campaign = self.campaign()
        slot = self.slot("new", self.people[0]["id"], "none")
        slot["test_intent"] = "Test the buyer proposition without an offer"
        slot["rationale"] = "Use prepared evidence without a discount; samples are limited."
        decision = self.propose(campaign, [slot])
        self.assertEqual(decision["feasibility"]["state"], "ready")
        detail = self.adopt(campaign, decision)
        self.assertEqual(detail["groups"][0]["ads"][0]["offer_key"], "none")
        self.assertEqual(
            detail["budget_basis_json"]["strategy"]["decision"]["receipt"]["revision"],
            decision["revision"],
        )

    def test_binding_projection_caps_choices_without_bulk_creative_or_revision_loss(self):
        prior, _ = self.previous()
        campaign = self.campaign()
        ctx = planner_context.planner_context(
            web.conn, self.org, self.brand, self.way["id"], campaign=campaign
        )
        original = deepcopy(ctx["carried_candidates"][0])
        ctx["carried_candidates"] = [deepcopy(original) for _ in range(30)]
        for index, candidate in enumerate(ctx["carried_candidates"]):
            candidate["ad"]["id"] = f"carry-{index}"
        before = deepcopy(strategy.decision_context(ctx, campaign))
        slot = self.slot("new", self.people[0]["id"])
        slot["evidence_refs"] = before["evidence_refs"][:1]
        payload = {"allocation": [{"role": "new", "pct": 100}], "slots": [slot]}
        accepted = strategy.executable_decision(ctx, campaign, payload)
        self.assertEqual(accepted["feasibility"]["state"], "ready")
        projection = strategy.decision_prompt_context(ctx, campaign)
        self.assertEqual(len(projection["carried"]), 24)
        self.assertEqual(projection["omitted"]["carried"], 6)
        self.assertEqual(
            projection["menu"],
            [{k: row[k] for k in ("dimension", "key", "label")} for row in ctx["menu"][:24]],
        )
        self.assertNotIn("copy_fields", json.dumps(projection))
        self.assertNotIn("asset_id", json.dumps(projection))
        self.assertEqual(len(before["carried"]), 30)
        ctx["carried_candidates"][-1]["creative"]["copy_fields"]["body"] = "Changed omitted copy"
        self.assertNotEqual(before, strategy.decision_context(ctx, campaign))
        self.assertNotEqual(accepted["revision"],
                            strategy.executable_decision(ctx, campaign, payload)["revision"])
        self.assertEqual(projection, strategy.decision_prompt_context(ctx, campaign))
        self.assertEqual(prior["id"], original["ad"]["id"])

    def test_generated_offer_cannot_replace_accepted_none_or_selected_offer(self):
        original = plan.PROVIDER._reply_for
        for accepted, replacement in (("none", "free_shipping"), ("free_shipping", "none")):
            with self.subTest(accepted=accepted, replacement=replacement):
                campaign = self.campaign()
                decision = self.propose(
                    campaign, [self.slot("new", self.people[0]["id"], accepted)]
                )

                def substitute(messages, replacement=replacement):
                    reply = deepcopy(original(messages))
                    reply["groups"][0]["ads"][0]["coordinates"]["offer"] = replacement
                    return reply

                with mock.patch.object(plan.PROVIDER, "_reply_for", side_effect=substitute):
                    with self.assertRaises(plan.StrategyConflict) as failure:
                        self.adopt(campaign, decision)
                self.assertIn(
                    "delivery_binding_changed", {r["code"] for r in failure.exception.reasons}
                )
                self.assert_empty(campaign)

    def test_customer_timestamps_and_coordinate_labels_do_not_change_revision(self):
        campaign = self.campaign()
        ctx = planner_context.planner_context(
            web.conn, self.org, self.brand, self.way["id"], campaign=campaign
        )
        before = strategy.decision_context(ctx, campaign)
        ctx["customer_groups"][0]["updated_at"] = "A render timestamp"
        ctx["menu"][0]["label"] = "A different display label"
        self.assertEqual(before, strategy.decision_context(ctx, campaign))

    def test_inputs_changed_during_gateway_io_refuse_before_any_plan_writes(self):
        original = plan.ask_with_one_retry
        for changed_input in ("budget", "source_copy"):
            with self.subTest(changed_input=changed_input):
                prior, _ = self.previous()
                campaign = self.campaign()
                decision = self.propose(
                    campaign,
                    [
                        self.slot("explore", self.people[0]["id"], "none", prior["id"]),
                        self.slot("new", self.people[1]["id"]),
                    ],
                )

                def while_away(
                    conn,
                    *args,
                    changed_input=changed_input,
                    campaign=campaign,
                    prior=prior,
                    **kwargs,
                ):
                    result = original(conn, *args, **kwargs)
                    if changed_input == "budget":
                        ads_repo.set_budget_planned(
                            conn, self.org, self.brand, campaign["id"], budget_planned=6001
                        )
                    else:
                        conn.execute(
                            "UPDATE ads_asset_placement SET copy_fields=jsonb_set(copy_fields,"
                            "'{body}',to_jsonb('A changed original copy'::text)) "
                            "WHERE campaign_id=%s",
                            (prior["campaign_id"],),
                        )
                    conn.commit()
                    return result

                with mock.patch.object(plan, "ask_with_one_retry", side_effect=while_away):
                    with self.assertRaisesRegex(plan.StrategyConflict, "strategy_changed"):
                        self.adopt(campaign, decision)
                self.assert_empty(campaign)

    def test_reduced_budget_revises_decision_and_refuses_old_approval(self):
        campaign = self.campaign()
        decision = self.propose(
            campaign,
            [self.slot("new", self.people[0]["id"]), self.slot("explore", self.people[1]["id"])],
        )
        changed = strategy.select_scenario(
            web.conn,
            self.org,
            self.brand,
            campaign["id"],
            scenario_key="custom",
            custom_total=3000,
            actor="tester",
        )
        new = changed["budget_basis_json"]["strategy"]["decision"]
        self.assertNotEqual(new["revision"], decision["revision"])
        self.assertEqual(new["feasibility"]["state"], "blocked")
        with self.assertRaisesRegex(plan.StrategyConflict, "strategy_changed"):
            self.adopt(campaign, decision)
        self.assert_empty(campaign)

    def test_unknown_zero_and_negative_cap_never_promises_executable_slots(self):
        campaign = self.campaign()
        ctx = planner_context.planner_context(
            web.conn, self.org, self.brand, self.way["id"], campaign=campaign
        )
        slots = [self.slot("new", self.people[0]["id"])]
        for cap in (None, 0, -300, float("inf"), float("nan")):
            with self.subTest(cap=cap):
                ctx["capacity"] = planner_context.capacity_of(600, cap)
                proposal = strategy.executable_decision(
                    ctx, campaign, {"slots": slots, "allocation": [{"role": "new", "pct": 100}]}
                )
                self.assertEqual(proposal["feasibility"]["state"], "blocked")
                self.assertIn(
                    "capacity_unknown", {r["code"] for r in proposal["feasibility"]["reasons"]}
                )

    def test_deleted_group_and_cross_brand_ids_refuse_without_writes(self):
        campaign = self.campaign()
        decision = self.propose(campaign, [self.slot("new", self.people[0]["id"])])
        web.conn.execute("DELETE FROM product_customer_group WHERE id=%s", (self.people[0]["id"],))
        with self.assertRaises(plan.StrategyConflict) as failure:
            self.adopt(campaign, decision)
        self.assertIn("customer_group_unavailable", {r["code"] for r in failure.exception.reasons})
        self.assert_empty(campaign)
        foreign_brand = bi_repo.create_brand(
            web.conn, org_id=self.org, name="Foreign", client_name=None, actor="tester"
        )["id"]
        foreign_product = bi_repo.create_product(
            web.conn, foreign_brand, name="Foreign", actor="tester"
        )
        foreign_group = bi_repo.save_customer_groups(
            web.conn,
            foreign_brand,
            foreign_product["id"],
            [{"who": "Foreign group", "pain_keys": ["cost"]}],
            actor="tester",
        )[0]
        decision = self.propose(campaign, [self.slot("new", foreign_group["id"])])
        with self.assertRaises(plan.StrategyConflict):
            self.adopt(campaign, decision)
        self.assert_empty(campaign)
        with self.assertRaisesRegex(ValueError, "campaign_unknown"):
            plan.adopt_strategy(
                web.conn,
                "foreign-org",
                self.brand,
                campaign["id"],
                actor="tester",
                expected_revision=decision["revision"],
                operation_id="foreign",
            )

    def test_explicit_role_reassignment_preserves_creative_and_original_identity(self):
        prior, asset = self.previous("explore")
        campaign = self.campaign()
        decision = self.propose(
            campaign,
            [
                self.slot("new", self.people[0]["id"], "none", prior["id"]),
                self.slot("explore", self.people[1]["id"]),
            ],
            [70, 30],
        )
        detail = self.adopt(campaign, decision)
        carried = next(a for g in detail["groups"] if g["role"] == "new" for a in g["ads"])
        self.assertEqual(carried["coordinates_snapshot_json"]["carried_from"]["ad_id"], prior["id"])
        row = web.conn.execute(
            "SELECT asset_id FROM ads_asset_placement WHERE id=%s",
            (carried["material_placement_id"],),
        ).fetchone()
        self.assertEqual(row["asset_id"], asset)
        self.assertEqual(sum(int(g["daily_budget"]) for g in detail["groups"]), 600)

    def test_two_following_periods_reuse_the_same_original_without_generation(self):
        from app.tests.test_ads_plan import _ranked_scope

        prior, asset = self.previous(offer="free_shipping")
        for period in range(2):
            campaign = self.campaign()
            decision = self.propose(
                campaign, [self.slot("explore", self.people[0]["id"], "free_shipping", prior["id"])]
            )
            provider = mock.Mock()
            plan.PROVIDER = provider
            detail = self.adopt(campaign, decision, operation=f"period-{period}")
            provider.complete.assert_not_called()
            carried = detail["groups"][0]["ads"][0]
            material = web.conn.execute(
                "SELECT asset_id,copy_fields FROM ads_asset_placement WHERE id=%s",
                (carried["material_placement_id"],),
            ).fetchone()
            self.assertEqual(material["asset_id"], asset)
            self.assertEqual(material["copy_fields"]["headline"], "上一期的標題")
            self.assertEqual(
                carried["coordinates_snapshot_json"]["carried_from"]["ad_id"], prior["id"]
            )
            bi_repo.record_learning(
                web.conn,
                self.brand,
                actor="tester",
                learning_text=carried["name"],
                applicability_scope=_ranked_scope(
                    verdict="keep_relative",
                    rank=1,
                    of=1,
                    sales=5,
                    spend=1200,
                    group=self.people[0]["id"],
                    angle="angle_kept",
                ),
                confidence="observed",
                sample_size="高",
                source_cycle_id=f"{campaign['id']}:{carried['id']}",
                source_track="coordinate",
            )
            web.conn.execute(
                "UPDATE ads_campaign SET status='closed',closed_at=now() WHERE id=%s",
                (campaign["id"],),
            )
            web.conn.commit()
            prior = carried

    def test_structure_edit_marks_decision_modified_and_preserves_original_receipt(self):
        campaign = self.campaign()
        decision = self.propose(campaign, [self.slot("new", self.people[0]["id"])])
        detail = self.adopt(campaign, decision)
        receipt = detail["budget_basis_json"]["strategy"]["decision"]["receipt"]
        plan.update_group(
            web.conn,
            self.org,
            self.brand,
            detail["groups"][0]["id"],
            {"daily_budget": 500},
            actor="tester",
        )
        view = ads_repo.campaign_detail(web.conn, self.org, self.brand, campaign["id"])
        modified = view["budget_basis_json"]["strategy"]["decision"]
        self.assertEqual(modified["state"], "modified")
        self.assertNotEqual(modified["revision"], decision["revision"])
        self.assertEqual(modified["receipt"], receipt)
        with self.assertRaises(plan.StrategyConflict):
            self.adopt(campaign, decision)

    def test_api_requires_displayed_revision_and_returns_structured_infeasibility(self):
        from fastapi.testclient import TestClient

        from app import main

        campaign = self.campaign(daily=300)
        decision = self.propose(
            campaign,
            [self.slot("new", self.people[0]["id"]), self.slot("explore", self.people[1]["id"])],
        )
        endpoint = f"/api/ads/brands/{self.brand}/campaigns/{campaign['id']}/plan"
        client = TestClient(main.app)
        missing = client.post(endpoint)
        self.assertEqual(missing.status_code, 409)
        self.assertEqual(missing.json()["error"]["code"], "strategy_confirmation_required")
        rejected = client.post(
            endpoint, json={"expected_revision": decision["revision"], "operation_id": "api-adopt"}
        )
        self.assertEqual(rejected.status_code, 409)
        error = rejected.json()["error"]
        self.assertEqual(error["code"], "strategy_infeasible")
        self.assertIn("capacity_exceeded", {r["code"] for r in error["details"]["reasons"]})
        self.assert_empty(campaign)

    def test_legacy_is_readable_but_requires_confirmation(self):
        campaign = self.campaign()
        ads_repo.save_strategy(
            web.conn,
            self.org,
            self.brand,
            campaign["id"],
            budget_basis_json={
                "strategy": {"allocation": [{"role": "new", "pct": 100, "label": "new"}]}
            },
        )
        view = ads_repo.campaign_detail(web.conn, self.org, self.brand, campaign["id"])
        self.assertEqual(
            view["budget_basis_json"]["strategy"]["decision"]["state"], "legacy_unbound"
        )
        with self.assertRaisesRegex(plan.StrategyConflict, "strategy_confirmation_required"):
            plan.adopt_strategy(web.conn, self.org, self.brand, campaign["id"], actor="tester")
        self.assert_empty(campaign)

    def test_api_same_operation_different_revision_refuses_and_receipt_replays(self):
        from fastapi.testclient import TestClient

        from app import main

        client = TestClient(main.app)
        campaign = self.campaign()
        decision = self.propose(campaign, [self.slot("new", self.people[0]["id"])])
        endpoint = f"/api/ads/brands/{self.brand}/campaigns/{campaign['id']}/plan"
        approval = {"expected_revision": decision["revision"], "operation_id": "same-operation"}
        accepted = client.post(endpoint, json=approval)
        self.assertEqual(accepted.status_code, 200)
        receipt = accepted.json()["campaign"]["budget_basis_json"]["strategy"]["decision"][
            "receipt"
        ]
        self.assertEqual(receipt["operation_id"], "same-operation")
        replay = client.post(endpoint, json=approval)
        self.assertEqual(replay.status_code, 200)
        self.assertEqual(
            replay.json()["campaign"]["budget_basis_json"]["strategy"]["decision"]["receipt"],
            receipt,
        )
        wrong = client.post(endpoint, json={**approval, "expected_revision": "different-revision"})
        self.assertEqual(wrong.status_code, 409)
        self.assertEqual(wrong.json()["error"]["code"], "strategy_changed")
        changed = client.post(endpoint, json={**approval, "operation_id": "different-operation"})
        self.assertEqual(changed.status_code, 409)
        self.assertEqual(changed.json()["error"]["code"], "strategy_changed")

    def test_adopted_budget_cap_and_cost_cap_changes_invalidate_rationale(self):
        for edit in ("budget", "cost", "resplit"):
            with self.subTest(edit=edit):
                campaign = self.campaign()
                decision = self.propose(campaign, [self.slot("new", self.people[0]["id"])])
                detail = self.adopt(campaign, decision)
                receipt = detail["budget_basis_json"]["strategy"]["decision"]["receipt"]
                if edit == "budget":
                    strategy.set_budget_cap(
                        web.conn,
                        self.org,
                        self.brand,
                        campaign["id"],
                        budget_cap=12000,
                        actor="tester",
                    )
                elif edit == "cost":
                    ads_repo.save_campaign_target(
                        web.conn,
                        self.org,
                        self.brand,
                        campaign["id"],
                        basis="own",
                        value=400,
                        expected_revision=0,
                        actor="tester",
                    )
                else:
                    strategy.select_scenario(
                        web.conn,
                        self.org,
                        self.brand,
                        campaign["id"],
                        scenario_key="custom",
                        custom_total=5000,
                        actor="tester",
                    )
                actual = ads_repo.campaign_detail(web.conn, self.org, self.brand, campaign["id"])
                payload = actual["budget_basis_json"]["strategy"]
                self.assertEqual(payload["decision"]["state"], "modified")
                self.assertNotEqual(payload["decision"]["revision"], decision["revision"])
                self.assertEqual(payload["decision"]["receipt"], receipt)
                self.assertEqual(payload["rationale_state"], "stale")
                with self.assertRaisesRegex(plan.StrategyConflict, "strategy_changed"):
                    self.adopt(campaign, decision)

    def test_simultaneous_same_operation_has_one_receipt_and_one_plan(self):
        campaign = self.campaign()
        decision = self.propose(campaign, [self.slot("new", self.people[0]["id"])])
        barrier = Barrier(2)
        original = plan.ask_with_one_retry

        def together(*args, **kwargs):
            result = original(*args, **kwargs)
            barrier.wait(timeout=15)
            return result

        def execute():
            with coredb.connection() as conn:
                return self.adopt(campaign, decision, conn=conn)

        with mock.patch.object(plan, "ask_with_one_retry", side_effect=together):
            with ThreadPoolExecutor(max_workers=2) as pool:
                futures = [pool.submit(execute) for _ in range(2)]
                results = [f.result(timeout=30) for f in futures]
        receipts = [r["budget_basis_json"]["strategy"]["decision"]["receipt"] for r in results]
        self.assertEqual(receipts[0], receipts[1])
        self.assertEqual(
            len(ads_repo.list_groups(web.conn, self.org, self.brand, campaign["id"])), 1
        )
