"""R6: choices cannot revive a suppressed recommendation."""

from datetime import date, timedelta
from unittest import mock

import pytest

from app.ads import budget, channels, external_repository, month_budget, plan, repository, strategy
from app.brand_intelligence import repository as bi_repo
from app.core import db
from app.llm import providers
from app.tests.test_ads_home_overview import _ad, _brand, _imported, _obs, _pinned, _product


@pytest.fixture
def evidence():
    conn, org = db.current(), db.DEV_ORG_ID

    class Reader:
        def accounts(self, conn, org, brand):
            return [{"account_id": "act_1", "currency": "TWD", "timezone_name": "Asia/Taipei"}]

    with (_pinned(date(2026, 9, 23)), mock.patch.object(channels, "external_reader",
                side_effect=lambda key: Reader() if key == "meta" else None)):
        brand = _brand(conn, org, "Budget advice counterexample")
        product = _product(conn, brand, unit_variable_cost=150)
        current = repository.create_campaign(conn, org, brand, {
            "name": "Next period", "goal_text": "Buyer test", "objective": "購買",
            "target_cost": 100, "start_date": date(2026, 9, 24), "end_date": date(2026, 9, 30),
            "context_json": {"product_ids": [product], "field_sources": {"cap": "user"}},
            "constraints_json": {"budget": 1400},
        })
        prior = _imported(conn, org, brand, "Prior", "prior", cap=100, product_id=product)
        external_repository.upsert_entity(conn, org, brand, prior, {
            "platform": "meta", "source_account": "act_1", "native_kind": "campaign",
            "native_id": "prior", "objective": "OUTCOME_SALES", "budget_type": "daily",
            "budget_amount": 200, "currency": "TWD",
        })
        external_repository.record_sync(conn, org, brand, prior, section="observations", state={
            "status": "success", "coverage": {"start": "2026-09-15", "end": "2026-09-22"},
        })
        ad = _ad(conn, org, brand, prior, "prior-ad", "prior")
        external_repository.upsert_entity(conn, org, brand, prior, {
            "platform": "meta", "source_account": "act_1", "native_kind": "adset",
            "native_id": "prior-adset", "native_status": "ACTIVE", "budget_type": "daily",
            "budget_amount": 200, "currency": "TWD",
        })
        conn.commit()
        yield conn, org, brand, current, prior, ad


@pytest.mark.parametrize("cost,state,key", [
    (20, "retain", "retain"), (500, "repair_before_budget", None),
    (120, "repair_before_budget", None),
])
def test_same_history_different_current_cost(evidence, cost, state, key):
    conn, org, brand, current, prior, ad = evidence
    _obs(conn, org, brand, prior, ad, date(2026, 9, 21), spend=cost, count=1)
    result = budget.advice(conn, org, brand, current)
    assert result["state"] == state
    assert result["recommended_key"] == key
    assert result["evidence"]["cost_per_result"] == cost
    assert result["evidence"]["sample_flag"]["few"] is True


@pytest.mark.parametrize("available,expected", [(1400, "retain"),
                                                (None, "insufficient_evidence"),
                                                (-1, "unaffordable")])
def test_verified_funds_are_an_alternative_to_campaign_cap(evidence, available, expected):
    conn, org, brand, current, prior, ad = evidence
    _obs(conn, org, brand, prior, ad, date(2026, 9, 21), spend=20, count=1)
    current = {**current, "constraints_json": {}}
    funds = {"amount": 10000, "currency": "TWD", "available": available,
             "uncertainties": [], "revision": 2, "confirmed_at": "2026-09-20"}
    with mock.patch.object(month_budget, "view", return_value=funds):
        result = budget.advice(conn, org, brand, current)
    assert result["state"] == expected


def test_mixed_currency_and_action_cannot_become_healthy(evidence):
    conn, org, brand, current, prior, ad = evidence
    _obs(conn, org, brand, prior, ad, date(2026, 9, 21), spend=20, count=1)
    _obs(conn, org, brand, prior, ad, date(2026, 9, 20), spend=20, count=1, currency="USD")
    assert budget.advice(conn, org, brand, current)["state"] == "insufficient_evidence"


def test_changed_product_and_stale_evidence_never_use_brand_history(evidence):
    conn, org, brand, current, prior, ad = evidence
    _obs(conn, org, brand, prior, ad, date(2026, 8, 21), spend=20, count=1)
    assert budget.advice(conn, org, brand, current)["recommended_key"] is None
    _obs(conn, org, brand, prior, ad, date(2026, 9, 21), spend=20, count=1)
    other = bi_repo.create_product(conn, brand, name="Different sell-way", actor="test")["id"]
    current["context_json"]["product_ids"] = [other]
    assert budget.advice(conn, org, brand, current)["recommended_key"] is None


def test_revisions_change_with_target_dates_budget_and_evidence(evidence):
    conn, org, brand, current, prior, ad = evidence
    _obs(conn, org, brand, prior, ad, date(2026, 9, 21), spend=20, count=1)
    initial = budget.advice(conn, org, brand, current)
    assert initial["revision"] == budget.advice(conn, org, brand, current)["revision"]
    for update in ({"target_cost": 10}, {"end_date": date(2026, 9, 29)},
                   {"constraints_json": {"budget": 100}}, {"budget_planned": 100}):
        revised = budget.advice(conn, org, brand, {**current, **update})
        assert initial["revision"] != revised["revision"]
    _obs(conn, org, brand, prior, ad, date(2026, 9, 21), spend=500, count=1)
    assert initial["revision"] != budget.advice(conn, org, brand, current)["revision"]


def test_known_cap_shortfall_does_not_use_larger_brand_funds(evidence):
    conn, org, brand, current, prior, ad = evidence
    _obs(conn, org, brand, prior, ad, date(2026, 9, 21), spend=20, count=1)
    current["constraints_json"] = {"budget": 100}
    with mock.patch.object(month_budget, "view") as read:
        result = budget.advice(conn, org, brand, current)
    read.assert_not_called()
    assert result["state"] == "unaffordable"
    assert result["recommended_key"] is None


def test_cross_month_never_backs_entire_period_with_single_month(evidence):
    conn, org, brand, current, prior, ad = evidence
    _obs(conn, org, brand, prior, ad, date(2026, 9, 21), spend=20, count=1)
    current = {**current, "end_date": date(2026, 10, 4), "constraints_json": {}}
    with mock.patch.object(month_budget, "view") as read:
        result = budget.advice(conn, org, brand, current)
    read.assert_not_called()
    assert result["state"] == "insufficient_evidence"
    current["constraints_json"] = {"budget": 3000}
    assert budget.advice(conn, org, brand, current)["state"] == "retain"


def test_partial_read_does_not_establish_comparable_cohort(evidence):
    conn, org, brand, current, prior, ad = evidence
    _obs(conn, org, brand, prior, ad, date(2026, 9, 21), spend=20, count=1)
    conn.execute("UPDATE ads_campaign SET context_json=context_json-'external_sync' "
                 "WHERE org_id=%s AND brand_id=%s AND id=%s", (org, brand, prior))
    result = budget.advice(conn, org, brand, current)
    assert result["state"] == "insufficient_evidence"
    assert result["reason_codes"] == ["coverage_unverified"]


def test_account_cutoff_requires_its_last_complete_day_to_be_read(evidence):
    conn, org, brand, current, prior, ad = evidence
    _obs(conn, org, brand, prior, ad, date(2026, 9, 21), spend=500, count=1)
    conn.execute("UPDATE ads_campaign SET context_json=context_json-'external_sync' "
                 "WHERE org_id=%s AND brand_id=%s AND id=%s", (org, brand, prior))
    external_repository.record_sync(conn, org, brand, prior, section="observations", state={
        "status": "success", "coverage": {"start": "2026-09-15", "end": "2026-09-21"},
    })
    incomplete = budget.advice(conn, org, brand, current)
    assert incomplete["evidence"]["window"]["end"] == "2026-09-22"
    assert incomplete["reason_codes"] == ["coverage_unverified"]
    external_repository.record_sync(conn, org, brand, prior, section="observations", state={
        "status": "success", "coverage": {"start": "2026-09-15", "end": "2026-09-22"},
    })
    assert budget.advice(conn, org, brand, current)["state"] == "repair_before_budget"


def test_missing_other_judged_ad_does_not_get_hidden_by_one_good_ad(evidence):
    conn, org, brand, current, prior, ad = evidence
    _obs(conn, org, brand, prior, ad, date(2026, 9, 21), spend=20, count=1)
    _ad(conn, org, brand, prior, "missing-ad", "prior", status="FUTURE_STATUS")
    assert budget.advice(conn, org, brand, current)["state"] == "insufficient_evidence"


def test_unknown_or_mismatched_economics_unit_never_healthy(evidence):
    conn, org, brand, current, prior, ad = evidence
    _obs(conn, org, brand, prior, ad, date(2026, 9, 21), spend=20, count=1)
    current = {**current, "target_cost": None, "target_basis": "break_even"}
    product = current["context_json"]["product_ids"][0]
    conn.execute(
        "UPDATE product_economics SET status='pending' WHERE brand_id=%s AND product_id=%s",
        (brand, product),
    )
    assert budget.advice(conn, org, brand, current)["state"] == "insufficient_evidence"
    conn.execute("UPDATE product_economics SET status='confirmed',currency='USD' "
                 "WHERE brand_id=%s AND product_id=%s", (brand, product))
    assert budget.advice(conn, org, brand, current)["state"] == "insufficient_evidence"
    current.update(target_cost=100, target_basis="own")
    assert budget.advice(conn, org, brand, current)["state"] == "retain"


def test_confirmed_usd_keeps_cost_grade_but_cannot_enter_twd_planning(evidence):
    conn, org, brand, current, prior, ad = evidence
    product = current["context_json"]["product_ids"][0]
    conn.execute("UPDATE product_economics SET currency='USD' WHERE brand_id=%s AND product_id=%s",
                 (brand, product))
    external_repository.upsert_entity(conn, org, brand, prior, {
        "platform": "meta", "source_account": "act_1", "native_kind": "campaign",
        "native_id": "prior", "budget_type": "daily", "budget_amount": 20, "currency": "USD",
    })
    _obs(conn, org, brand, prior, ad, date(2026, 9, 21), spend=20, count=1, currency="USD")
    current = {**current, "target_cost": None, "target_basis": "break_even", "constraints_json": {}}
    funds = {"amount": 1000, "currency": "USD", "available": 140,
             "uncertainties": [], "revision": 1, "confirmed_at": "2026-09-20"}
    with mock.patch.object(month_budget, "view", return_value=funds):
        result = budget.advice(conn, org, brand, current)
    assert result["state"] == "insufficient_evidence"
    assert result["reason_codes"] == ["planning_currency_mismatch"]
    assert result["evidence"]["grade"] == "on_target"
    assert result["evidence"]["currency"] == "USD"
    assert result["recommended_key"] is None
    assert result["retain"] is None


@pytest.mark.parametrize("owner_currency,reason", [
    ("USD", "planning_currency_mismatch"), (None, "planning_currency_unverified"),
])
def test_foreign_or_unknown_owner_cannot_select_or_adopt_retain(evidence, owner_currency, reason):
    conn, org, brand, current, prior, ad = evidence
    product = current["context_json"]["product_ids"][0]
    conn.execute("UPDATE product_economics SET currency='USD' WHERE brand_id=%s AND product_id=%s",
                 (brand, product))
    external_repository.upsert_entity(conn, org, brand, prior, {
        "platform": "meta", "source_account": "act_1", "native_kind": "campaign",
        "native_id": "prior", "budget_type": "daily", "budget_amount": 2000,
        "currency": owner_currency,
    })
    conn.execute("UPDATE ads_campaign SET target_cost=NULL,target_basis='break_even',"
                 "constraints_json='{}' WHERE org_id=%s AND brand_id=%s AND id=%s",
                 (org, brand, current["id"]))
    _obs(conn, org, brand, prior, ad, date(2026, 9, 21), spend=20, count=1, currency="USD")
    funds = {"amount": 14000, "currency": "USD", "available": 14000,
             "uncertainties": [], "revision": 1, "confirmed_at": "2026-09-20"}
    provider = providers.ScriptedProvider(providers.SCRIPTED_REPLIES["ads_strategy"])
    with (mock.patch.object(month_budget, "view", return_value=funds),
          mock.patch.object(strategy, "PROVIDER", provider)):
        generated = strategy.generate(conn, org, brand, current["id"], actor="test")
        scenarios = generated["budget_basis_json"]["scenarios"]
        assert scenarios["recommended"] is None
        assert scenarios["advice"]["reason_codes"] == [reason]
        assert scenarios["advice"]["evidence"]["grade"] == "on_target"
        assert all(row["key"] != "retain" for row in scenarios["scenarios"])
        assert all(row["amount"] is None
                   for row in generated["budget_basis_json"]["strategy"]["allocation"])
        for custom_total in (None, 14000):
            with pytest.raises(ValueError, match="scenario_unknown"):
                strategy.select_scenario(conn, org, brand, current["id"], scenario_key="retain",
                                         custom_total=custom_total, actor="test")
        assert repository.get_campaign(conn, org, brand, current["id"])["budget_planned"] is None
        # A pre-fix persisted foreign retain is not authority to create NT$ groups.
        basis = generated["budget_basis_json"]
        basis["scenarios"]["scenarios"].append({
            "key": "retain", "daily": 2000, "total": 14000, "currency": "USD",
            "label": "Legacy retain", "caption": "Legacy", "over_cap": None,
        })
        revision = basis["strategy"]["decision"]["revision"]
        repository.select_scenario(conn, org, brand, current["id"], scenario_key="retain",
                                   budget_planned=14000, budget_basis_json=basis)
        with mock.patch.object(plan, "PROVIDER", side_effect=AssertionError("No model call")):
            with pytest.raises(plan.StrategyConflict, match="strategy_changed"):
                plan.adopt_strategy(conn, org, brand, current["id"], actor="test",
                                     expected_revision=revision, operation_id="foreign-retain")
        assert repository.campaign_detail(conn, org, brand, current["id"])["groups"] == []
        basis["scenarios"]["mode"] = "history"
        basis["scenarios"]["scenarios"].append({
            "key": "conservative", "daily": 20, "total": 140, "currency": "USD",
            "label": "Foreign comparison", "caption": "Known USD", "over_cap": None,
        })
        repository.select_scenario(conn, org, brand, current["id"], scenario_key="conservative",
                                   budget_planned=140, budget_basis_json=basis)
        with pytest.raises(ValueError, match="scenario_amount_unknown"):
            strategy.select_scenario(conn, org, brand, current["id"],
                                     scenario_key="conservative", actor="test")
        with mock.patch.object(plan, "PROVIDER", side_effect=AssertionError("No model call")):
            with pytest.raises(plan.StrategyConflict, match="strategy_changed"):
                plan.adopt_strategy(conn, org, brand, current["id"], actor="test",
                                     expected_revision=revision, operation_id="foreign-comparison")


@pytest.mark.parametrize("status,currency", [("confirmed", "USD"), ("pending", None)])
def test_cold_start_foreign_or_unverified_cap_is_not_a_twd_amount(evidence, status, currency):
    conn, org, brand, current, _prior, _ad_id = evidence
    product = current["context_json"]["product_ids"][0]
    conn.execute("UPDATE product_economics SET currency='USD',status=%s "
                 "WHERE brand_id=%s AND product_id=%s", (status, brand, product))
    conn.execute("UPDATE ads_campaign SET target_cost=NULL,target_basis='break_even' "
                 "WHERE org_id=%s AND brand_id=%s AND id=%s", (org, brand, current["id"]))
    provider = providers.ScriptedProvider(providers.SCRIPTED_REPLIES["ads_strategy"])
    with mock.patch.object(strategy, "PROVIDER", provider):
        generated = strategy.generate(conn, org, brand, current["id"], actor="test")
    scenarios = generated["budget_basis_json"]["scenarios"]
    assert scenarios["mode"] == "cold_start"
    assert scenarios["recommended"] is None
    choices = [row for row in scenarios["scenarios"] if row["key"] != budget.CAP_KEY]
    assert len(choices) == 3
    assert all("測試" in row["label"] and row["daily"] is None and row["total"] is None
               and row["over_cap"] is None
               and row["currency"] == currency for row in choices)
    assert all(row["reason"] == ("planning_currency_mismatch" if currency
                                else "planning_currency_unverified") for row in choices)
    for custom_total in (None, 14000):
        with pytest.raises(ValueError, match="scenario_amount_unknown"):
            strategy.select_scenario(conn, org, brand, current["id"],
                                     scenario_key="minimum", custom_total=custom_total,
                                     actor="test")
    chosen = strategy.select_scenario(conn, org, brand, current["id"],
                                      scenario_key="cap", actor="test")
    assert chosen["budget_planned"] == 1400
    with pytest.raises(strategy.OverCapUnconfirmed):
        strategy.select_scenario(conn, org, brand, current["id"],
                                 scenario_key="custom", custom_total=14000, actor="test")
    chosen = strategy.select_scenario(conn, org, brand, current["id"],
                                      scenario_key="custom", custom_total=14000,
                                      confirm_over_cap=True, actor="test")
    assert chosen["budget_planned"] == 14000


def test_twd_retain_remains_selectable(evidence):
    conn, org, brand, current, prior, ad = evidence
    _obs(conn, org, brand, prior, ad, date(2026, 9, 21), spend=20, count=1)
    provider = providers.ScriptedProvider(providers.SCRIPTED_REPLIES["ads_strategy"])
    with mock.patch.object(strategy, "PROVIDER", provider):
        generated = strategy.generate(conn, org, brand, current["id"], actor="test")
    assert generated["budget_basis_json"]["scenarios"]["recommended"] == "retain"
    chosen = strategy.select_scenario(conn, org, brand, current["id"], scenario_key="retain",
                                      actor="test")
    assert chosen["budget_planned"] == 1400
    assert chosen["budget_scenario"] == "retain"


@pytest.mark.parametrize("amount,state", [(5800, "retain"), (5799, "unaffordable")])
def test_existing_owner_commitment_is_not_charged_twice(amount, state):
    conn, org = db.current(), db.DEV_ORG_ID
    with _pinned(date(2026, 9, 23)):
        brand = _brand(conn, org, "Existing commitment")
        product = _product(conn, brand, unit_variable_cost=150)
        current = repository.create_campaign(conn, org, brand, {
            "name": "Running", "goal_text": "Buyer test", "objective": "購買",
            "target_cost": 100, "start_date": date(2026, 9, 1), "end_date": date(2026, 9, 30),
            "context_json": {"product_ids": [product], "field_sources": {"cap": "user"}},
        })
        native, account, stamp = "root-" + brand, "account-" + brand, db.now_utc()
        root = external_repository.upsert_entity(conn, org, brand, current["id"], {
            "platform": "meta", "source_account": account, "native_kind": "campaign",
            "native_id": native, "objective": "OUTCOME_SALES", "budget_type": "daily",
            "budget_amount": 200, "currency": "TWD", "native_status": "ACTIVE",
            "start_date": date(2026, 9, 1), "end_date": date(2026, 9, 30),
            "sync_status": "success", "last_success_at": stamp,
        })
        ad = external_repository.upsert_entity(conn, org, brand, current["id"], {
            "platform": "meta", "source_account": account, "native_kind": "ad",
            "native_id": "ad-" + brand, "native_status": "ACTIVE",
            "parent_native_kind": "campaign", "parent_native_id": native,
        })
        _obs(conn, org, brand, current["id"], ad["id"], date(2026, 9, 21), spend=200, count=10)
        external_repository.upsert_observation(conn, org, brand, current["id"], {
            "entity_id": root["id"], "day": date(2026, 9, 22), "metric_scope": "campaign",
            "attribution_key": external_repository.MONTHLY_BUDGET_ATTRIBUTION_KEY,
            "currency": "TWD", "source": "meta", "spend": 4200,
        })
        for section in ("structure", "observations"):
            external_repository.record_sync(conn, org, brand, current["id"], section=section,
                state={"status": "success", "last_success_at": stamp,
                       "coverage": {"start": "2026-09-01", "end": "2026-09-22"}})
        tasks = {
            "structure": {"section": "structure", "campaign_id": current["id"],
                          "status": "succeeded", "errors": [],
                          "started_at": stamp - timedelta(minutes=1), "completed_at": stamp},
            "monthly:2026-09": {"status": "succeeded", "started_at": stamp - timedelta(minutes=1),
                "completed_at": stamp, "coverage": {"scope": "account_campaign_day",
                    "start": "2026-09-01", "end": "2026-09-23", "currency": "TWD",
                    "timezone_name": "Asia/Taipei", "unassigned_native_ids": []}},
        }
        conn.execute(
            "INSERT INTO ads_external_sync_job(id,org_id,brand_id,platform,source_account,tasks) "
            "VALUES(%s,%s,%s,'meta',%s,%s)",
            (db.new_id("asj"), org, brand, account, db.jsonb(tasks)),
        )
        conn.commit()

        class Reader:
            def accounts(self, conn, org, brand):
                return [{"account_id": account, "currency": "TWD", "timezone_name": "Asia/Taipei"}]

        with (mock.patch.object(channels, "external_reader",
                                side_effect=lambda key: Reader() if key == "meta" else None),
              mock.patch.object(month_budget, "now_utc", return_value=stamp)):
            funds = month_budget.save(conn, org, brand, month="2026-09", currency="TWD",
                                      amount=amount, expected_revision=0, actor="test")
            assert funds["uncertainties"] == []
            assert funds["available"] == amount - 5800
            assert funds["ongoing_estimate"] == 1600
            result = budget.advice(conn, org, brand, current)
            assert result["state"] == state
            extended = {**current, "end_date": date(2026, 10, 1)}
            assert budget.advice(conn, org, brand, extended)["state"] == "insufficient_evidence"


def test_repair_null_survives_generate_read_and_explicit_choice_rechecks(evidence):
    conn, org, brand, current, prior, ad = evidence
    _obs(conn, org, brand, prior, ad, date(2026, 9, 21), spend=500, count=1)
    provider = providers.ScriptedProvider(providers.SCRIPTED_REPLIES["ads_strategy"])
    with mock.patch.object(strategy, "PROVIDER", provider):
        generated = strategy.generate(conn, org, brand, current["id"], actor="test")
    scenarios = generated["budget_basis_json"]["scenarios"]
    decision = generated["budget_basis_json"]["strategy"]["decision"]
    assert scenarios["recommended"] is None
    assert scenarios["advice"]["state"] == "repair_before_budget", scenarios["advice"]
    assert decision["budget_advice"] == generated["budget_advice"] == scenarios["advice"]
    assert all(row["amount"] is None
               for row in generated["budget_basis_json"]["strategy"]["allocation"])
    with pytest.raises(strategy.OverCapUnconfirmed):
        strategy.select_scenario(conn, org, brand, current["id"], scenario_key="custom",
                                 custom_total=14000, actor="test")
    chosen = strategy.select_scenario(conn, org, brand, current["id"], scenario_key="custom",
                                      custom_total=14000, confirm_over_cap=True, actor="test")
    assert chosen["budget_planned"] == 14000
    assert chosen["budget_basis_json"]["scenarios"]["recommended"] is None
    revision = chosen["budget_basis_json"]["strategy"]["decision"]["revision"]
    fresh = repository.get_campaign(conn, org, brand, current["id"])
    plan._checked_decision(conn, org, brand, fresh, revision)
    provider = providers.ScriptedProvider(providers.SCRIPTED_REPLIES["ads_delivery_plan"])
    with mock.patch.object(plan, "PROVIDER", provider):
        adopted = plan.adopt_strategy(conn, org, brand, current["id"], actor="test",
                                     expected_revision=revision, operation_id="advice-adopt")
    receipt = adopted["budget_basis_json"]["strategy"]["decision"]["receipt"]
    _obs(conn, org, brand, prior, ad, date(2026, 9, 21), spend=20, count=1)
    fresh = repository.get_campaign(conn, org, brand, current["id"])
    with pytest.raises(plan.StrategyConflict, match="strategy_changed"):
        plan._checked_decision(conn, org, brand, fresh, revision)
    with mock.patch.object(plan, "PROVIDER", side_effect=AssertionError("No replay model call")):
        replay = plan.adopt_strategy(conn, org, brand, current["id"], actor="test",
                                    expected_revision=revision, operation_id="advice-adopt")
    assert replay["budget_basis_json"]["strategy"]["decision"]["receipt"] == receipt


def test_null_recommendation_survives_cap_and_known_choices():
    result = {"mode": "history", "recommended": None, "basis": {}, "scenarios": [
        {"key": "recommended", "daily": 100, "total": 1000},
    ]}
    projected = budget.current_scenarios(result, {
        "start_date": date(2026, 9, 1), "end_date": date(2026, 9, 10),
        "constraints_json": {"budget": 500},
    })
    assert projected["recommended"] is None
    assert budget._recommended_with_amount(projected) is None


def test_invalid_recommendation_does_not_choose_first_known_amount():
    result = {"recommended": "obsolete", "scenarios": [
        {"key": "conservative", "total": 600},
    ]}
    assert budget._recommended_with_amount(result) is None
