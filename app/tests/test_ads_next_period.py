"""Completed-period preparation and atomic, idempotent continuation."""

import hashlib
import json
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from unittest.mock import patch
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app import main
from app.ads import (
    ads_learnings,
    asset_binding_repository,
    brief,
    busy,
    channels,
    learning_rank,
    next_period,
    plan,
    planner_context,
    repository,
    settle,
    strategy,
)
from app.ads import external_repository as external
from app.ads import user_assets_repository as assets
from app.brand_intelligence import repository as brands
from app.core import db
from app.llm import providers
from app.workbench import encode_learning_scope


def test_relative_best_is_not_absolute_success():
    row = {
        "entity_id": "native",
        "name": "Relative best",
        "spend": 500,
        "results": 1,
        "currency": "TWD",
        "cap": 100,
        "grade": "over",
        "thumbnail_url": None,
    }
    ranked = learning_rank.rank([row])[0]
    assert ranked["verdict"] == learning_rank.KEEP_RELATIVE
    assert settle._fate(row, ranked) == ("ineffective", None)
    summary = settle._totals([{**row, **ranked, "fate": "ineffective"}], (1000, "TWD"))
    assert summary["on_target_results"] == 0
    assert summary["on_target_spend_share"] == 0


def test_preparation_accepts_only_completed_org_month_without_angle_jobs():
    conn = db.current()
    brand = brands.create_brand(
        conn, org_id=db.DEV_ORG_ID, name="Next period", client_name=None, actor="test"
    )["id"]
    conn.commit()
    with (
        patch("app.core.settings.today_for_org", return_value=date(2026, 10, 1)),
        patch("app.ads.angles.enqueue") as enqueue,
    ):
        response = TestClient(main.app).get(f"/api/ads/brands/{brand}/next-period?month=2026-09")
        assert response.status_code == 200, response.text
        assert response.json()["window"] == {"start": "2026-09-01", "end": "2026-09-30"}
        assert response.json()["source_campaigns"] == []
        current = TestClient(main.app).get(f"/api/ads/brands/{brand}/next-period?month=2026-10")
        assert current.status_code == 409
        enqueue.assert_not_called()


class Reader:
    def accounts(self, conn, org, brand):
        return [{"account_id": "account", "currency": "TWD", "timezone_name": "Asia/Taipei"}]


@pytest.fixture
def source(monkeypatch):
    conn, org = db.current(), db.DEV_ORG_ID
    monkeypatch.setattr(channels, "external_reader", lambda *args, **kwargs: Reader())
    monkeypatch.setattr(
        next_period.coresettings, "today_for_org", lambda *a, **kw: date(2026, 10, 8)
    )
    brand = brands.create_brand(
        conn, org_id=org, name="Continuation source", client_name=None, actor="test"
    )["id"]
    knowledge = brands.create_product(conn, brand, name="Selected product", actor="test")["id"]
    product = brands.create_product(
        conn, brand, name="Selected product · Single", parent_id=knowledge, actor="test"
    )["id"]
    groups = brands.save_customer_groups(
        conn, brand, knowledge, [{"who": "Source buyer", "pain_keys": ["effort"]}], actor="test"
    )
    brands.save_product_economics(
        conn,
        brand,
        product,
        selling_price=500,
        currency="TWD",
        unit_variable_cost=150,
        shipping_cost=0,
        actor="test",
        confirmed_by="test",
        effective_from="2026-09-01",
    )
    campaign = external.create_imported_campaign(conn, org, brand, name="Still live native")["id"]
    native_campaign, native_ad = f"native-campaign-{brand}", f"native-ad-{brand}"
    external.upsert_entity(
        conn,
        org,
        brand,
        campaign,
        {
            "platform": "meta",
            "source_account": "account",
            "native_kind": "campaign",
            "native_id": native_campaign,
            "objective": "OUTCOME_SALES",
            "native_status": "ACTIVE",
        },
    )
    entity = external.upsert_entity(
        conn,
        org,
        brand,
        campaign,
        {
            "platform": "meta",
            "source_account": "account",
            "native_kind": "ad",
            "native_id": native_ad,
            "name": "Owned original",
            "parent_native_kind": "campaign",
            "parent_native_id": native_campaign,
            "native_status": "ACTIVE",
            "creative": {
                "kind": "image",
                "fields": {"image_hash": "verified", "body": "Source copy"},
            },
        },
    )
    repository.save_campaign_target(
        conn,
        org,
        brand,
        campaign,
        result_kind="purchase",
        basis="own",
        value=100,
        expected_revision=0,
        actor="test",
    )
    external.upsert_observation(
        conn,
        org,
        brand,
        campaign,
        {
            "entity_id": entity["id"],
            "metric_scope": "ad",
            "day": "2026-09-30",
            "spend": 400,
            "purchases": 20,
            "attribution_key": "7d",
            "currency": "TWD",
            "source": "graph",
        },
        result_kind="purchase",
        result_count=20,
        result_action="omni_purchase",
        result_attribution="7d_click",
    )
    external.record_sync(
        conn,
        org,
        brand,
        campaign,
        section="observations",
        state={
            "last_success_at": db.now_utc().isoformat(),
            "coverage": {"start": "2026-09-01", "end": "2026-09-30"},
        },
    )
    content = (
        b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
        b"\x08\x00\x00\x00\x00:~\x9bU\x00\x00\x00\nIDATx\x9cc`\x00\x00\x00\x02\x00\x01"
        b"H\xaf\xa4q\x00\x00\x00\x00IEND\xaeB`\x82"
    )
    upload = assets.create_batch(
        conn, org, brand, [{"filename": "original.png", "size": len(content)}], "test"
    )["uploads"][0]
    assets.set_upload(
        conn,
        org,
        brand,
        upload["id"],
        storage_key=f"{org}/brands/{brand}/original.png",
        sha256=hashlib.sha256(content).hexdigest(),
        mime_type="image/png",
        byte_size=len(content),
        status="complete",
    )
    original = assets.finalize_original(conn, org, brand, upload["id"])
    conn.execute(
        "UPDATE ads_user_asset SET status='ready' WHERE org_id=%s AND brand_id=%s AND id=%s",
        (org, brand, original["id"]),
    )
    copy = {"headline": "Source title", "body": "Source copy", "description": "Source detail"}
    placement = assets.attach(conn, org, brand, campaign, original["id"], copy, "test")
    conn.execute(
        "UPDATE ads_asset_placement SET confirmed_at=now() WHERE org_id=%s AND"
        " brand_id=%s AND id=%s",
        (org, brand, placement["id"]),
    )
    binding = asset_binding_repository.report(
        conn, org, brand, campaign, placement["id"], 1, "test"
    )
    conn.execute(
        "UPDATE ads_asset_binding SET entity_id=%s,platform='meta',source_account='account',"
        "native_kind='ad',native_id=%s,existence_status='platform_confirmed',creative_hash=%s"
        " WHERE org_id=%s AND brand_id=%s AND id=%s",
        (
            entity["id"],
            native_ad,
            asset_binding_repository.creative_hash(entity["creative"]),
            org,
            brand,
            binding["id"],
        ),
    )
    campaign_row = repository.get_campaign(conn, org, brand, campaign)
    conditions = ads_learnings.condition_snapshot(conn, org, brand, campaign_row, product)
    material = ads_learnings.material_version(
        {"material_evidence": {"sha256": original["sha256"], "copy": copy}}, {}
    )
    evidence = {
        "schema_version": 1,
        "source_kind": "coordinate",
        "source_version": "retained",
        "source_ref": {
            "campaign_id": campaign,
            "entity_id": entity["id"],
            "ad_id": entity["id"],
            "trial_id": campaign,
        },
        "provenance": "platform_observation",
        "period": {"start": "2026-09-01", "end": "2026-09-30"},
        "scope": {
            "product_id": None,
            "audience_key": "cold",
            "customer_group_id": groups[0]["id"],
            "claim_key": "message:retained",
            "claim_family": "performance",
            "objective_family": repository.campaign_objective_family(
                conn, org, brand, campaign_row
            ),
            "result_kind": "purchase",
            "currency": "TWD",
            "attribution": json.dumps(
                {"key": "7d", "action": "omni_purchase", "result_attribution": "7d_click"},
                sort_keys=True,
                separators=(",", ":"),
            ),
        },
        "conditions": {
            "price_version": conditions["price_version"],
            "target_version": conditions["target_version"],
            "offer_key": "none",
            "material_version": material,
        },
        "sample": {"result_events": 20},
        "direction": "support",
        "limits": [],
    }
    ranked = learning_rank.rank(
        [
            {
                "entity_id": entity["id"],
                "name": "Owned original",
                "spend": 400,
                "results": 20,
                "currency": "TWD",
                "cap": 100,
            }
        ]
    )[0]
    keys = {
        "audience": "cold",
        "pain": "effort",
        "angle": "convenience",
        "hook": "question",
        "proof": "none",
        "offer": "none",
        "format": "single_image",
    }
    for dimension, key in keys.items():
        conn.execute(
            "INSERT INTO brand_coordinate(id,org_id,brand_id,dimension,key,label)"
            " VALUES(%s,%s,%s,%s,%s,%s)",
            (db.new_id("crd"), org, brand, dimension, key, key),
        )
    brands.record_learning(
        conn,
        brand,
        actor="test",
        learning_text="Retained native observation",
        applicability_scope=encode_learning_scope(
            learning_rank.scope(ranked, keys, groups[0]["id"]), evidence
        ),
        confidence="observed",
        sample_size="20",
        product_id=None,
        source_track="ads",
        source_cycle_id=f"native:{campaign}:{entity['id']}",
    )
    monkeypatch.setattr(next_period.storage, "get", lambda **kwargs: (content, "image/png"))
    monkeypatch.setattr(
        brief,
        "PROVIDER",
        providers.FakeProvider(
            response=providers.ProviderResponse(
                output_text="{}",
                structured=None,
                usage=providers.Usage(input_tokens=1, output_tokens=1),
                stop_reason="end_turn",
            )
        ),
    )
    conn.commit()
    return {
        "conn": conn,
        "org": org,
        "brand": brand,
        "product": product,
        "campaign": campaign,
        "entity": entity,
        "asset": original,
        "placement": placement,
        "content": content,
        "group": groups[0],
        "keys": keys,
    }


def payload(source, **continuation):
    prepared = next_period.prepare(source["conn"], source["org"], source["brand"], "2026-09")
    return {
        "product_ids": [source["product"]],
        "objective": "購買",
        "budget": 7000,
        "cap": 100,
        "start_date": "2026-10-09",
        "end_date": "2026-10-15",
        "continuation": {
            "month": "2026-09",
            "campaign_ids": [source["campaign"]],
            "revision": prepared["revision"],
            "request_id": str(uuid4()),
            "product_mapping_confirmed": True,
            **continuation,
        },
    }


def create(source, body):
    return TestClient(main.app).post(f"/api/ads/brands/{source['brand']}/campaigns", json=body)


def test_imported_only_sources_enter_actual_planner_without_fabricated_prior_ad(source):
    response = create(source, payload(source))
    assert response.status_code == 200, response.text
    draft = response.json()["campaign"]
    campaign = repository.get_campaign(source["conn"], source["org"], source["brand"], draft["id"])
    ctx = planner_context.planner_context(
        source["conn"], source["org"], source["brand"], source["product"], campaign=campaign
    )
    assert ctx["previous"]["campaign_id"] == source["campaign"]
    assert [c["campaign_id"] for c in ctx["learnings"]["ranked"]["campaigns"]] == [
        source["campaign"]
    ]
    assert len(ctx["carried_candidates"]) == 1, json.dumps(ctx["continuation"], ensure_ascii=False)
    carried = ctx["carried_candidates"][0]
    assert carried["ad"]["id"] == source["entity"]["id"]
    assert carried["ad"]["native_ref"]["native_id"] == source["entity"]["native_id"]
    assert carried["creative"]["asset_id"] == source["asset"]["id"]
    assert (
        source["conn"]
        .execute("SELECT COUNT(*) AS n FROM ads_ad WHERE campaign_id=%s", (source["campaign"],))
        .fetchone()["n"]
        == 0
    )


def test_timeout_replay_precedes_changed_deleted_source_and_model(source, monkeypatch):
    body = payload(source)
    first = create(source, body)
    assert first.status_code == 200, first.text
    source["conn"].execute(
        "DELETE FROM ads_asset_binding WHERE org_id=%s AND brand_id=%s AND campaign_id=%s",
        (source["org"], source["brand"], source["campaign"]),
    )
    source["conn"].execute(
        "DELETE FROM ads_campaign WHERE org_id=%s AND brand_id=%s AND id=%s",
        (source["org"], source["brand"], source["campaign"]),
    )
    source["conn"].commit()
    monkeypatch.setattr(
        brief.gateway, "run_task", lambda *a, **kw: pytest.fail("Replay called model")
    )
    replay = create(source, body)
    assert replay.status_code == 200, replay.text
    assert replay.json()["campaign"]["id"] == first.json()["campaign"]["id"]
    conflict = create(source, {**body, "budget": 8000})
    assert conflict.status_code == 409, conflict.text
    assert conflict.json()["error"]["code"] == "continuation_request_conflict"


@pytest.mark.parametrize("change", ["metrics", "currency", "mapping", "asset", "target"])
def test_fresh_request_rejects_changed_source_without_partial_draft(source, change):
    body = payload(source)
    conn, org, brand, campaign = (source[k] for k in ("conn", "org", "brand", "campaign"))
    if change == "metrics":
        conn.execute(
            "UPDATE ads_external_daily SET spend=500 WHERE org_id=%s AND brand_id=%s"
            " AND campaign_id=%s",
            (org, brand, campaign),
        )
    elif change == "currency":
        conn.execute(
            "UPDATE ads_external_daily SET currency='USD' WHERE org_id=%s AND"
            " brand_id=%s AND campaign_id=%s",
            (org, brand, campaign),
        )
    elif change == "mapping":
        conn.execute(
            "UPDATE ads_campaign SET context_json=%s WHERE org_id=%s AND brand_id=%s AND id=%s",
            (db.jsonb({"product_ids": [source["product"]]}), org, brand, campaign),
        )
    elif change == "asset":
        conn.execute(
            "UPDATE ads_user_asset SET status='failed' WHERE org_id=%s AND brand_id=%s AND id=%s",
            (org, brand, source["asset"]["id"]),
        )
    else:
        repository.save_campaign_target(
            conn,
            org,
            brand,
            campaign,
            result_kind="purchase",
            basis="own",
            value=90,
            expected_revision=1,
            actor="test",
        )
    conn.commit()
    before = len(repository.list_campaigns(conn, org, brand))
    response = create(source, body)
    assert response.status_code == 409, response.text
    assert response.json()["error"]["code"] == "continuation_source_changed"
    assert len(repository.list_campaigns(conn, org, brand)) == before


@pytest.mark.parametrize("confirmation", [False, True])
def test_unbound_product_confirmation_does_not_rewrite_native_history(source, confirmation):
    response = create(source, payload(source, product_mapping_confirmed=confirmation))
    assert response.status_code == 200, response.text
    draft = response.json()["campaign"]
    scope = draft["context_json"]["next_period_source"]
    assert bool(scope["eligible_learning_refs"]) is confirmation
    if not confirmation:
        assert "mapping_required" in {e["reason_code"] for e in scope["excluded"]}
    original = repository.get_campaign(
        source["conn"], source["org"], source["brand"], source["campaign"]
    )
    assert original["origin"] == "imported"
    assert original["context_json"].get("product_ids") is None
    entity = (
        source["conn"]
        .execute(
            "SELECT native_id,native_status FROM ads_external_entity WHERE id=%s",
            (source["entity"]["id"],),
        )
        .fetchone()
    )
    assert entity == {"native_id": source["entity"]["native_id"], "native_status": "ACTIVE"}


@pytest.mark.parametrize("invalid", [None, "last month", {"month": "2026-09"}])
def test_malformed_continuation_never_falls_back_to_sentence_create(source, invalid):
    response = create(source, {"goal_text": "Try a buyer test", "continuation": invalid})
    assert response.status_code == 422, response.text
    assert response.json()["error"]["code"] == "continuation_invalid"


def test_continuation_missing_month_is_rejected_before_draft_write(source):
    body = payload(source)
    del body["continuation"]["month"]
    response = create(source, body)
    assert response.status_code == 422, response.text
    assert response.json()["error"]["code"] == "continuation_invalid"
    assert source["conn"].execute(
        "SELECT count(*) AS n FROM ads_campaign WHERE brand_id=%s AND origin='internal'",
        (source["brand"],),
    ).fetchone()["n"] == 0


def _oversize(source):
    conn, org, brand = (source[k] for k in ("conn", "org", "brand"))
    campaign = external.create_imported_campaign(conn, org, brand, name="Large unselected source")[
        "id"
    ]
    entity = external.upsert_entity(
        conn,
        org,
        brand,
        campaign,
        {
            "platform": "meta",
            "source_account": "account",
            "native_kind": "ad",
            "native_id": f"oversize-{brand}",
            "name": "Many readings",
        },
    )
    conn.execute(
        "INSERT INTO ads_external_daily SELECT (jsonb_populate_record(NULL::ads_external_daily,"
        " to_jsonb(d)||jsonb_build_object('id','oversize-'||%s||'-'||n::text,"
        " 'campaign_id',%s::text,"
        " 'entity_id',%s::text,'attribution_key','sample-'||n::text))).*"
        " FROM ads_external_daily d CROSS JOIN generate_series(1,3001) n WHERE d.entity_id=%s",
        (brand, campaign, entity["id"], source["entity"]["id"]),
    )
    conn.commit()
    return campaign


def test_unselected_oversize_source_is_narrowable_without_silent_qualification(source):
    large = _oversize(source)
    response = TestClient(main.app).get(
        f"/api/ads/brands/{source['brand']}/next-period?month=2026-09"
    )
    assert response.status_code == 200, response.text
    assert large in {r["campaign_id"] for r in response.json()["source_campaigns"]}
    assert {
        "owner": "campaign",
        "ref": large,
        "reason_code": "source_scope_too_large",
    } in response.json()["excluded"]
    result = create(source, payload(source))
    assert result.status_code == 200, result.text
    assert result.json()["campaign"]["context_json"]["next_period_source"]["campaign_ids"] == [
        source["campaign"]
    ]


def test_selected_oversize_is_refused_without_draft(source):
    large = _oversize(source)
    before = len(repository.list_campaigns(source["conn"], source["org"], source["brand"]))
    response = create(source, payload(source, campaign_ids=[large]))
    assert response.status_code == 409, response.text
    assert response.json()["error"]["code"] == "continuation_scope_too_large"
    assert len(repository.list_campaigns(source["conn"], source["org"], source["brand"])) == before


def test_unseen_late_correction_invalidates_revision_even_outside_prompt(source):
    large = _oversize(source)
    body = payload(source)
    source["conn"].execute(
        "UPDATE ads_external_daily SET spend=999 WHERE campaign_id=%s AND"
        " attribution_key='sample-3001'",
        (large,),
    )
    source["conn"].commit()
    result = create(source, body)
    assert result.status_code == 409, result.text
    assert result.json()["error"]["code"] == "continuation_source_changed"


def test_new_request_preserves_brief_busy_but_replay_ignores_busy(source):
    body = payload(source)
    first = create(source, body)
    assert first.status_code == 200, first.text
    with db.connection() as observer:
        with busy.claim(observer, source["brand"], "brief"):
            replay = create(source, body)
            assert replay.status_code == 200
            blocked = create(
                source,
                {**body, "continuation": {**body["continuation"], "request_id": str(uuid4())}},
            )
            assert blocked.status_code == 409, blocked.text
            assert blocked.json()["error"]["code"] == "campaign_busy"


def _generated(source, monkeypatch):
    class NativeCarryProvider(providers.ScriptedProvider):
        def _reply_for(self, messages):
            reply = super()._reply_for(messages)
            binding = self._json_section(self._last_user_text(messages), "【可綁定安排】")
            if binding and binding["carried"]:
                prior = binding["carried"][0]
                reply["slots"][0].update(
                    carry_from_ad_id=prior["id"],
                    test_intent=None,
                    customer_group_id=prior["customer_group_id"],
                    offer_key=prior["coordinates"]["offer"],
                )
            return reply

    monkeypatch.setattr(
        strategy, "PROVIDER", NativeCarryProvider(providers.SCRIPTED_REPLIES["ads_strategy"])
    )
    monkeypatch.setattr(
        plan,
        "PROVIDER",
        providers.ScriptedProvider(providers.SCRIPTED_REPLIES["ads_delivery_plan"]),
    )
    result = create(source, payload(source))
    assert result.status_code == 200, result.text
    campaign_id = result.json()["campaign"]["id"]
    generated = strategy.generate(
        source["conn"], source["org"], source["brand"], campaign_id, actor="test"
    )
    strategy.select_scenario(
        source["conn"],
        source["org"],
        source["brand"],
        campaign_id,
        scenario_key="cap",
        actor="test",
    )
    campaign = repository.get_campaign(source["conn"], source["org"], source["brand"], campaign_id)
    decision = campaign["budget_basis_json"]["strategy"]["decision"]
    assert decision["feasibility"]["state"] == "ready", decision
    return campaign_id, decision["revision"], generated


def test_imported_only_public_generate_select_adopt_reuses_actual_original(source, monkeypatch):
    campaign_id, revision, generated = _generated(source, monkeypatch)
    assert (
        generated["budget_basis_json"]["basis"]["planner_context"]["continuation"][
            "source_campaigns"
        ][0]["campaign_id"]
        == source["campaign"]
    )
    result = plan.adopt_strategy(
        source["conn"],
        source["org"],
        source["brand"],
        campaign_id,
        actor="test",
        expected_revision=revision,
        operation_id="native-adopt",
    )
    carried = [
        a
        for g in result["groups"]
        for a in g["ads"]
        if a["coordinates_snapshot_json"].get("carried_from")
    ]
    assert len(carried) == 1
    provenance = carried[0]["coordinates_snapshot_json"]["carried_from"]
    assert provenance["native_ref"]["native_id"] == source["entity"]["native_id"]
    assert "ad_id" not in provenance
    placement = assets.placement(
        source["conn"],
        source["org"],
        source["brand"],
        campaign_id,
        carried[0]["material_placement_id"],
    )
    assert placement["asset_id"] == source["asset"]["id"]
    assert asset_binding_repository.effective_copy(
        placement
    ) == asset_binding_repository.effective_copy(source["placement"])
    assert (
        source["conn"]
        .execute("SELECT count(*) AS n FROM ads_ad WHERE campaign_id=%s", (source["campaign"],))
        .fetchone()["n"]
        == 0
    )
    source["conn"].execute(
        "UPDATE ads_user_asset SET status='failed' WHERE id=%s", (source["asset"]["id"],)
    )
    source["conn"].commit()
    replay = plan.adopt_strategy(
        source["conn"],
        source["org"],
        source["brand"],
        campaign_id,
        actor="test",
        expected_revision=revision,
        operation_id="native-adopt",
    )
    assert replay["id"] == campaign_id


def test_adoption_rejects_changed_asset_before_writing_any_slot(source, monkeypatch):
    campaign_id, revision, _ = _generated(source, monkeypatch)
    source["conn"].execute(
        "UPDATE ads_user_asset SET status='failed' WHERE id=%s", (source["asset"]["id"],)
    )
    source["conn"].commit()
    with pytest.raises(plan.StrategyConflict):
        plan.adopt_strategy(
            source["conn"],
            source["org"],
            source["brand"],
            campaign_id,
            actor="test",
            expected_revision=revision,
            operation_id="changed-asset",
        )
    assert (
        source["conn"]
        .execute(
            "SELECT count(*) AS n FROM ads_delivery_group WHERE campaign_id=%s", (campaign_id,)
        )
        .fetchone()["n"]
        == 0
    )


@pytest.mark.parametrize("spend, expected", [(400, 1), (10000, 0)])
def test_ordinary_planner_carries_only_real_absolute_qualified_winner(source, spend, expected):
    conn, org, brand, campaign = (source[k] for k in ("conn", "org", "brand", "campaign"))
    conn.execute(
        "UPDATE ads_campaign SET"
        " origin='internal',status='closed',objective='購買',goal_text='Historical buyer test',"
        " closed_at=now(),start_date='2026-09-01',end_date='2026-09-30',"
        " context_json=context_json||%s WHERE id=%s",
        (db.jsonb({"product_ids": [source["product"]]}), campaign),
    )
    group = repository.create_group(
        conn,
        org,
        brand,
        campaign,
        channel_key="meta",
        name="Prior group",
        role="new",
        daily_budget=100,
    )
    ad = repository.create_ad(
        conn,
        org,
        brand,
        campaign,
        group["id"],
        name="Actual prior ad",
        coordinates=source["keys"],
        coordinates_snapshot={},
        customer_group_id=source["group"]["id"],
    )
    old = brands.list_learnings(conn, brand, include_expired=True)[0]
    evidence = ads_learnings.stored_evidence(old)
    evidence["scope"]["product_id"] = source["product"]
    evidence["source_ref"]["ad_id"] = ad["id"]
    frozen = {"evidence_conditions": {**evidence["conditions"], "materials": []}}
    conn.execute(
        "UPDATE ads_ad SET external_id=%s,material_placement_id=%s,"
        " material_placement_revision=1,live_creative_json=%s WHERE id=%s",
        (source["entity"]["native_id"], source["placement"]["id"], db.jsonb(frozen), ad["id"]),
    )
    ranked = learning_rank.rank(
        [{"entity_id": ad["id"], "spend": spend, "results": 20, "currency": "TWD", "cap": 100}]
    )[0]
    brands.record_learning(
        conn,
        brand,
        actor="test",
        learning_text="Actual source",
        applicability_scope=encode_learning_scope(
            learning_rank.scope(ranked, source["keys"], source["group"]["id"]), evidence
        ),
        confidence="observed",
        source_track="coordinate",
        sample_size="20",
        product_id=source["product"],
        source_cycle_id=f"{campaign}:{ad['id']}",
    )
    conn.execute("UPDATE ads_external_daily SET spend=%s WHERE campaign_id=%s", (spend, campaign))
    conn.commit()
    body = payload(source)
    body.pop("continuation")
    response = create(source, body)
    assert response.status_code == 200, response.text
    draft = repository.get_campaign(conn, org, brand, response.json()["campaign"]["id"])
    ctx = planner_context.planner_context(conn, org, brand, source["product"], campaign=draft)
    assert len(ctx["carried_candidates"]) == expected
    if not expected:
        assert ranked["verdict"] == learning_rank.KEEP_RELATIVE
        decision = strategy.executable_decision(
            ctx,
            draft,
            {
                "allocation": [{"role": "new", "pct": 100}],
                "slots": [
                    {
                        "id": "forged-carry",
                        "role": "new",
                        "customer_group_id": source["group"]["id"],
                        "offer_key": "none",
                        "carry_from_ad_id": ad["id"],
                        "test_intent": None,
                        "rationale": "Retain original",
                        "evidence_refs": [],
                    }
                ],
            },
        )
        assert "carry_unavailable" in {r["code"] for r in decision["feasibility"]["reasons"]}


def test_preparation_has_no_database_writes_or_model_calls(source, monkeypatch):
    conn = source["conn"]
    tables = (
        "ads_campaign",
        "ads_ad",
        "ads_asset_placement",
        "ads_asset_binding",
        "learning_ledger",
        "llm_task",
    )
    before = {
        t: conn.execute(
            f"SELECT count(*) AS n FROM {t} WHERE brand_id=%s", (source["brand"],)
        ).fetchone()["n"]
        for t in tables
    }
    monkeypatch.setattr(brief.gateway, "run_task", lambda *a, **kw: pytest.fail("GET called model"))
    with patch("app.ads.angles.enqueue") as enqueue:
        response = TestClient(main.app).get(
            f"/api/ads/brands/{source['brand']}/next-period?month=2026-09"
        )
        assert response.status_code == 200
        enqueue.assert_not_called()
    after = {
        t: conn.execute(
            f"SELECT count(*) AS n FROM {t} WHERE brand_id=%s", (source["brand"],)
        ).fetchone()["n"]
        for t in tables
    }
    assert after == before


@pytest.mark.parametrize(
    "change, reason",
    [
        ("over", "above_target"),
        ("definition", "measurement_changed"),
        ("asset", "material_unavailable"),
        ("bytes", "material_bytes_changed"),
        ("format", "material_format_incompatible"),
        ("placement", "material_permission_unknown"),
        ("expired", "superseded"),
        ("objective", "objective_unknown"),
    ],
)
def test_unqualified_selected_source_remains_new_test_context_without_proven_carry(
    source, monkeypatch, change, reason
):
    conn, campaign, entity = source["conn"], source["campaign"], source["entity"]["id"]
    if change == "over":
        conn.execute("UPDATE ads_external_daily SET spend=10000 WHERE entity_id=%s", (entity,))
    elif change == "definition":
        conn.execute(
            "UPDATE ads_external_daily SET result_attribution='1d_click' WHERE entity_id=%s",
            (entity,),
        )
    elif change == "asset":
        conn.execute(
            "UPDATE ads_user_asset SET status='failed' WHERE id=%s", (source["asset"]["id"],)
        )
    elif change == "bytes":
        monkeypatch.setattr(next_period.storage, "get", lambda **kwargs: (b"changed", "image/png"))
    elif change == "format":
        creative = {"kind": "video", "fields": {"video_id": "native-video"}}
        external.upsert_entity(
            conn,
            source["org"],
            source["brand"],
            campaign,
            {**{k: source["entity"][k] for k in (
                "platform", "source_account", "native_kind", "native_id",
                "parent_native_kind", "parent_native_id", "native_status", "name",
            )}, "creative": creative},
        )
        conn.execute(
            "UPDATE ads_asset_binding SET creative_hash=%s WHERE entity_id=%s",
            (asset_binding_repository.creative_hash(creative), entity),
        )
    elif change == "placement":
        conn.execute(
            "UPDATE ads_asset_placement SET confirmed_at=NULL WHERE id=%s",
            (source["placement"]["id"],),
        )
    elif change == "expired":
        learning = brands.list_learnings(conn, source["brand"], include_expired=True)[0]
        brands.expire_learning(conn, source["brand"], learning["id"], actor="test")
    else:
        conn.execute(
            "UPDATE ads_external_entity SET objective=NULL WHERE campaign_id=%s"
            " AND native_kind='campaign'",
            (campaign,),
        )
    conn.commit()
    response = create(source, payload(source))
    assert response.status_code == 200, response.text
    draft = repository.get_campaign(
        conn, source["org"], source["brand"], response.json()["campaign"]["id"]
    )
    ctx = planner_context.planner_context(
        conn, source["org"], source["brand"], source["product"], campaign=draft
    )
    assert ctx["carried_candidates"] == []
    assert ctx["continuation"]["eligible_learning_refs"] == []
    assert reason in {r["reason_code"] for r in ctx["continuation"]["excluded"]}
    assert all(
        "retain_control" not in r["evidence"]["allowed_uses"]
        for c in ctx["learnings"]["ranked"]["campaigns"]
        for r in c["rows"]
    )


def test_same_request_concurrent_http_calls_create_one_draft(source):
    body = payload(source)
    with ThreadPoolExecutor(max_workers=2) as pool:
        replies = list(pool.map(lambda _: create(source, body), range(2)))
    assert [r.status_code for r in replies] == [200, 200], [r.text for r in replies]
    assert len({r.json()["campaign"]["id"] for r in replies}) == 1
    rows = (
        source["conn"]
        .execute(
            "SELECT id FROM ads_campaign WHERE brand_id=%s"
            " AND context_json->'next_period_source'->>'request_id'=%s",
            (source["brand"], body["continuation"]["request_id"]),
        )
        .fetchall()
    )
    assert len(rows) == 1


def test_source_changes_during_model_io_roll_back_all_new_draft_writes(source, monkeypatch):
    original = brief.PROVIDER.complete

    def changed(**kwargs):
        with db.connection() as observer:
            observer.execute(
                "UPDATE ads_external_daily SET spend=600 WHERE entity_id=%s",
                (source["entity"]["id"],),
            )
            observer.commit()
        return original(**kwargs)

    monkeypatch.setattr(brief.PROVIDER, "complete", changed)
    before = len(repository.list_campaigns(source["conn"], source["org"], source["brand"]))
    reply = create(source, payload(source))
    assert reply.status_code == 409, reply.text
    assert reply.json()["error"]["code"] == "continuation_source_changed"
    assert len(repository.list_campaigns(source["conn"], source["org"], source["brand"])) == before


def test_selected_other_brand_is_rejected_without_partial_draft(source):
    another = brands.create_brand(
        source["conn"], org_id=source["org"], name="Other brand", client_name=None, actor="test"
    )["id"]
    other = external.create_imported_campaign(
        source["conn"], source["org"], another, name="Foreign source"
    )["id"]
    source["conn"].commit()
    reply = create(source, payload(source, campaign_ids=[other]))
    assert reply.status_code == 409, reply.text
    assert reply.json()["error"]["code"] == "continuation_source_missing"


def test_legacy_relative_written_scope_does_not_claim_absolute_success():
    row = {
        "created_at": db.now_utc(),
        "created_by": "test",
        "learning_text": "Legacy effective",
        "applicability_scope": "ads;campaign=old;settle_fate=effective",
    }
    result = settle._written_view({"ad": row})
    assert result["effective"] == result["ineffective"] == 0
    assert result["unknown"] == 1


def test_small_sample_retains_existing_allowed_uses_and_sample_warning(source):
    conn, entity = source["conn"], source["entity"]["id"]
    conn.execute(
        "UPDATE ads_external_daily SET spend=20,result_count=1,purchases=1 WHERE entity_id=%s",
        (entity,),
    )
    conn.commit()
    result = create(source, payload(source))
    assert result.status_code == 200, result.text
    draft = repository.get_campaign(
        conn, source["org"], source["brand"], result.json()["campaign"]["id"]
    )
    ctx = planner_context.planner_context(
        conn, source["org"], source["brand"], source["product"], campaign=draft
    )
    assert len(ctx["carried_candidates"]) == 1
    row = ctx["carried_candidates"][0]["row"]
    assert row["few"] is True
    assert "insufficient_sample" in row["evidence"]["reason_codes"]
    assert "retain_control" in row["evidence"]["allowed_uses"]
    assert "market_support" not in row["evidence"]["allowed_uses"]
