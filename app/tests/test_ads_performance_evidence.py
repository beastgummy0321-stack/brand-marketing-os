"""Purpose-derived counterexamples for result truth across the supervised loop."""

from datetime import date, timedelta

import pytest

from app.ads import closeout, learning, objectives, outcome, period_grades, targets, triage


def observation(spend=100, count=1, *, kind="purchase", purchases=1, day=date(2026, 10, 1)):
    values = {
        "entity_id": "group", "day": day, "metric_scope": "adset", "source": "fixture",
        "spend": spend, "impressions": 1000, "clicks": 30, "purchases": purchases,
        "revenue": None, "currency": "TWD", "attribution_key": "purchase-window",
        "result_kind": kind, "result_count": count, "result_action": kind,
        "result_attribution": "fixture-window",
    }
    values["availability"] = {
        key: "available" if values[key] is not None else "unknown"
        for key in ("spend", "impressions", "clicks", "purchases", "revenue", "result_count")
    }
    return values


def result(rows, kind="purchase"):
    cap = {"value": 200, "basis": "own", "result_kind": kind}
    start, end = min(r["day"] for r in rows), max(r["day"] for r in rows)
    scope = {"start": start.isoformat(), "end": end.isoformat(), "days": (end - start).days + 1}
    return outcome.result_projection(rows, cap, scope), cap


@pytest.mark.parametrize("objective,kind", [("購買", "purchase"), ("名單", "lead"),
                                          ("流量", "link_click"), ("知名度", None)])
def test_goal_intent_is_not_internal_origin_purchase(objective, kind):
    assert objectives.expected_result_kind(objective) == kind
    assert targets.effective_result_kind({"origin": "internal", "objective": objective}) == kind
    assert targets.effective_result_kind({"origin": "imported", "objective": objective}) is None


def test_incidental_purchase_cannot_judge_a_lead_goal():
    view, cap = result([observation(1000, 10, kind="lead", purchases=1)], "lead")
    assert view["cost_per_result"] == 100
    assert view["result_kind"] == "lead"
    verdict, detail = closeout._judge(cap, {"start_date": None, "end_date": None},
                                     {"result_view": view, "cpa": 1000},
                                     {"bucket": "低"}, {})
    assert verdict == "達成"
    assert detail["metric"] == "cost_per_result"
    assert "名單" in learning._sentence({"name": "Lead"}, verdict, detail)


def test_partial_denominator_is_not_actual_cpa_or_negative_learning():
    view, cap = result([observation(100, 1), observation(500, None, purchases=None,
                                                       day=date(2026, 10, 2))])
    assert view["state"] == "incomplete"
    assert view["count"] is None and view["cost_per_result"] is None
    verdict, detail = closeout._judge(cap, {"start_date": None, "end_date": None},
                                     {"result_view": view, "cpa": 600}, {"bucket": "低"}, {})
    assert verdict == "看不出" and detail["actual"] is None


@pytest.mark.parametrize("spend,grade", [(20, "insufficient"), (1000, "wasted")])
def test_known_zero_keeps_truth_and_separate_spend_risk(spend, grade):
    view, cap = result([observation(spend, 0, purchases=0)])
    assert view["state"] == "known_zero" and view["count"] == 0
    assert view["cost_per_result"] is None
    verdict, detail = closeout._judge(cap, {"start_date": None, "end_date": None},
                                     {"result_view": view}, {"bucket": "低"}, {})
    assert verdict == "看不出"
    assert "未追蹤" not in detail["missing"]
    assert detail["risk"]["grade"] == grade


def test_target_mismatch_is_identical_for_period_and_ad_ruler():
    view, cap = result([observation(1000, 10, kind="lead")])
    assert view["state"] == "incompatible"
    assert "result_kind_mismatch" in view["reasons"]
    raw = {"result_kind": "lead", "result_count": 10, "cost_per_result": 100,
           "reason": None, "currency": "TWD"}
    assert period_grades._grade(raw, 1000, cap, 7)[2] == "result_kind_mismatch"


def test_equal_cost_different_sample_and_time_are_retained():
    small, _ = result([observation(100, 1)])
    rows = [observation(100, 1, day=date(2026, 10, 1) + timedelta(days=i)) for i in range(30)]
    large, _ = result(rows)
    assert small["cost_per_result"] == large["cost_per_result"] == 100
    assert small["sample"]["count"] == 1 and large["sample"]["count"] == 30
    assert small["sample"]["days_present"] == 1 and large["sample"]["days_present"] == 30


@pytest.mark.parametrize("field,value,reason", [("currency", "USD", "mixed_currency"),
    ("result_action", "other-action", "mixed_result_definition"),
    ("result_attribution", "other-window", "mixed_result_definition")])
def test_incompatible_source_definitions_are_not_combined(field, value, reason):
    first, second = observation(), observation(day=date(2026, 10, 2))
    second[field] = value
    view, _ = result([first, second])
    assert view["state"] == "incompatible" and reason in view["reasons"]
    assert view["cost_per_result"] is None


def test_read_failed_availability_cannot_become_zero_or_actual():
    row = observation(100, 0)
    row["availability"]["result_count"] = "unknown"
    view, _ = result([row])
    assert view["state"] == "incomplete" and view["count"] is None


def test_old_purchase_fields_never_relabel_as_goal_results():
    row = observation(1000, 10, kind="lead", purchases=1)
    assert outcome.period_bucket([row])["purchases"] == 1
    view, _ = result([row], "lead")
    assert view["count"] == 10
    assert triage.GRADE_LABELS["on_target"]


def test_known_cost_does_not_require_a_configured_cap():
    cap = {"value": None, "basis": None, "result_kind": "purchase"}
    view = outcome.result_projection([observation()], cap, {"days": 1})
    assert view["data_state"] == "known_positive" and view["cost_per_result"] == 100
    assert view["comparison_state"] == "unconfigured"
    verdict, detail = closeout._judge(cap, {"start_date": None, "end_date": None},
                                     {"result_view": view}, {"bucket": "低"}, {})
    assert verdict == "看不出" and detail["actual"] is None


def test_real_local_http_lead_close_and_learning_keep_the_result_unit():
    from fastapi.testclient import TestClient

    import app.main as main
    from app.ads import coverage, plan, repository
    from app.brand_intelligence import repository as brands
    from app.core import db
    from app.shared import web
    from app.tests.fixtures.ads_external import outcome_seed

    conn, org = web.conn, db.DEV_ORG_ID
    brand = brands.create_brand(conn, org_id=org, name="Unit contract", client_name=None,
                                actor="fixture")["id"]
    day = coverage.last_complete_day(conn, org, brand)
    campaign = repository.create_campaign(conn, org, brand, {
        "name": "Lead goal", "goal_text": "Lead followup", "objective": "名單", "status": "live",
        "start_date": day, "end_date": day,
    })
    repository.save_campaign_target(conn, org, brand, campaign["id"], basis="own", value=200,
                                    expected_revision=0, actor="fixture")
    group = plan.create_group(conn, org, brand, campaign["id"], name="Group", role="new",
                              daily_budget=1000)
    outcome_seed.seed_day(conn, org, brand, campaign["id"], "group", group["id"], day,
                          spend=1000, purchases=1, result_kind="lead", result_count=10)
    outcome_seed.set_coverage(conn, org, brand, campaign["id"], day, day)
    conn.commit()
    client = TestClient(main.app)
    path = f"/api/ads/brands/{brand}/campaigns/{campaign['id']}"
    response = client.get(path + "/performance")
    assert response.status_code == 200
    data = response.json()
    assert data["totals"]["purchases"] == 1 and data["totals"]["cpa"] == 1000
    assert data["result_view"]["count"] == 10 and data["result_view"]["cost_per_result"] == 100
    response = client.post(path + "/close", json={})
    assert response.status_code == 200
    closed = response.json()["campaign"]
    assert closed["verdict"] == "達成" and closed["verdict_json"]["actual"] == 100
    assert closed["verdict_json"]["result_kind"] == "lead"
    sentence = client.get(path).json()["campaign"]["learning_sentence"]
    assert "每次名單成本" in sentence and "實際 100" in sentence


def test_incidental_purchase_attribution_does_not_remove_lead_spend():
    first = observation(100, 1, kind="lead")
    second = observation(100, 1, kind="lead", day=date(2026, 10, 2))
    second["attribution_key"] = "different-incidental-purchase-window"
    totals = outcome.period_bucket([first, second])
    assert totals["spend"] is None
    cap = {"value": 200, "basis": "own", "result_kind": "lead"}
    assert outcome._period_grade(totals, [first, second], cap, 2)["grade"] == "on_target"


def test_partial_purchase_cpa_is_not_a_complete_actual_ratio():
    rows = [observation(), observation(500, None, purchases=None)]
    assert outcome.period_bucket(rows)["cpa"] is None
