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


def test_recorded_read_gap_keeps_known_subtotal_but_not_complete_cost():
    from app.ads import performance_evidence

    view = {"result_kind": "purchase", "result_action": "purchase", "result_attribution": "same",
            "result_count": 1, "cost_per_result": 100, "reason": None}
    projection = performance_evidence.project(view, 100, {"value": 200, "result_kind": "purchase"},
                                              {"days": 7}, reason="needs_resync")
    assert projection["data_state"] == "incomplete"
    assert projection["known_count"] == 1 and projection["count"] is None
    assert projection["cost_per_result"] is None


def test_real_period_read_gap_cannot_be_graded_or_ranked_as_complete():
    from app.ads import coverage, external_repository, repository
    from app.brand_intelligence import repository as brands
    from app.core import db
    from app.shared import web

    conn, org = web.conn, db.DEV_ORG_ID
    brand = brands.create_brand(conn, org_id=org, name="Gap", client_name=None,
                                actor="fixture")["id"]
    end = coverage.last_complete_day(conn, org, brand)
    start = end - timedelta(days=2)
    campaign = repository.create_campaign(conn, org, brand, {"name": "Incomplete window",
        "goal_text": "Purchase", "objective": "購買", "status": "live", "start_date": start,
        "end_date": end})
    repository.save_campaign_target(conn, org, brand, campaign["id"], basis="own", value=200,
                                    expected_revision=0, actor="fixture")
    entity = external_repository.upsert_entity(conn, org, brand, campaign["id"], {
        "platform": "test", "source_account": "test", "native_kind": "ad", "native_id": "gap",
        "name": "Gap ad", "native_status": "ACTIVE"})
    for day in (start, end):
        raw = observation(day=day)
        external_repository.upsert_observation(conn, org, brand, campaign["id"], {
            k: raw[k] for k in ("day", "metric_scope", "spend", "purchases", "currency", "source",
                               "attribution_key")
        } | {"entity_id": entity["id"], "metric_scope": "ad"}, result_kind="purchase",
            result_count=1, result_action="purchase", result_attribution="same")
    conn.commit()
    row = period_grades.grade_period(conn, org, brand, start, end)[0]
    assert row["grade"] == "insufficient" and row["reason_code"] == "needs_resync"
    assert row["results"] is None and row["cost_per_result"] is None
    assert row["result_view"]["known_count"] == 2


def test_incompatible_result_cannot_enter_the_shared_ranking():
    from app.ads import learning_rank

    view, _ = result([observation(1000, 10, kind="lead")])
    assert view["count"] == 10 and view["data_state"] == "known_positive"
    assert view["state"] == "incompatible"
    row = {"results": 10, "spend": 1000, "currency": "TWD", "cap": 200, "result_view": view}
    assert learning_rank.rank([row]) == []


def test_evidence_navigation_refs_are_bounded_without_hiding_the_count():
    from app.ads import performance_evidence

    view = performance_evidence.project(None, None, {}, {}, evidence_refs=range(100))
    assert len(view["evidence_refs"]) == 32
    assert view["evidence_ref_count"] == 100 and view["evidence_refs_omitted"] == 68


def test_fractional_reported_result_is_positive_not_a_zero_sale():
    from app.ads import learning_rank

    row = {"name": "Weighted result", "results": 0.5, "spend": 1500, "currency": "TWD", "cap": 450}
    ranked = learning_rank.rank([row])[0]
    assert ranked["sales"] == 0.5 and ranked["cost_per_sale"] == 3000
    assert ranked["few"] is True
    assert not learning_rank.waiting({**row, "spend": 100})
    assert triage._sales({"reason": None, "result_count": 0.5}) == 0.5
    scope = learning_rank.scope(ranked, {d: "none" for d in learning_rank.DIMENSIONS}, None)
    assert learning_rank.parse_scope(scope)["sales"] == 0.5
    assert outcome.period_bucket([observation(1500, 0.5, purchases=0.5)])["purchases"] == 0.5


def test_native_scope_projection_preserves_goal_and_does_not_add_measurement_grains():
    rows = [{**observation(1000, 10, kind="lead", purchases=1), "id": "adset-row"},
            {**observation(200, 2, kind="lead", purchases=0), "id": "ad-row", "metric_scope": "ad"}]
    target = {"value": 100, "basis": "own", "result_kind": "lead"}
    scope = {"start": "2026-10-01", "end": "2026-10-01", "days": 1}
    views = outcome.native_result_views(rows, target, scope,
        {"never_synced": False, "missing_days": []}, {"basis": "own", "currency": "TWD"})
    assert len(views) == 2
    assert sorted(v["count"] for v in views) == [2, 10]
    assert all(v["cost_per_result"] == 100 and v["result_kind"] == "lead" for v in views)
    assert all(v["state"] == "known_positive" for v in views)
    assert {v["scope_key"] for v in views} == {
        '["ad","TWD","purchase-window"]', '["adset","TWD","purchase-window"]'}


def test_native_read_gap_or_wrong_goal_keeps_eligibility_unknown():
    rows = [{**observation(1000, 10, kind="lead", purchases=1), "id": "native-row"}]
    scope = {"start": "2026-10-01", "end": "2026-10-02", "days": 2}
    target = {"value": 100, "basis": "own", "result_kind": "lead"}
    view = outcome.native_result_views(rows, target, scope,
        {"never_synced": False, "missing_days": ["2026-10-02"]},
        {"basis": "own", "currency": "TWD"})[0]
    assert view["count"] is None and view["known_count"] == 10
    assert view["cost_per_result"] is None and view["state"] == "incomplete"
    view = outcome.native_result_views(rows, {**target, "result_kind": "purchase"}, scope,
        {"never_synced": False, "missing_days": []}, {"basis": "own", "currency": "TWD"})[0]
    assert view["state"] == "incompatible" and "result_kind_mismatch" in view["reasons"]


def test_real_http_imported_performance_serves_scoped_lead_results():
    from fastapi.testclient import TestClient

    import app.main as main
    from app.ads import coverage, external_repository, repository
    from app.brand_intelligence import repository as brands
    from app.core import db, settings
    from app.tests.fixtures.ads_external import outcome_seed

    conn, org = db.current(), db.DEV_ORG_ID
    brand = brands.create_brand(conn, org_id=org, name="Native result route",
                                client_name=None, actor="fixture")["id"]
    campaign = external_repository.create_imported_campaign(conn, org, brand, name="Native lead")
    conn.execute("UPDATE ads_campaign SET result_kind='lead',target_cost=100,target_basis='own' "
                 "WHERE id=%s", (campaign["id"],))
    campaign = repository.get_campaign(conn, org, brand, campaign["id"])
    assert campaign is not None
    day = coverage.last_complete_day(conn, org, brand, campaign["id"])
    entity = external_repository.upsert_entity(conn, org, brand, campaign["id"], {
        "platform": "fixture", "source_account": "account", "native_kind": "adset",
        "native_id": "native-set", "name": "Native set", "native_status": "ACTIVE"})
    row = observation(1000, 10, kind="lead", purchases=1, day=day)
    row["entity_id"] = entity["id"]
    external_repository.upsert_observation(conn, org, brand, campaign["id"],
        {k: v for k, v in row.items() if not k.startswith("result_")},
        result_kind="lead", result_count=10, result_action="lead", result_attribution="fixture-window")
    start = settings.today_for_org(conn, org_id=org) - timedelta(days=29)
    outcome_seed.set_coverage(conn, org, brand, campaign["id"], start, day)
    conn.commit()
    response = TestClient(main.app).get(
        f"/api/ads/brands/{brand}/campaigns/{campaign['id']}/performance")
    assert response.status_code == 200, response.text
    view = response.json()["external_view"]
    assert view["observations"][0]["purchases"] == 1
    assert view["result_views"][0]["result_kind"] == "lead"
    assert view["result_views"][0]["count"] == 10
    assert view["result_views"][0]["cost_per_result"] == 100
