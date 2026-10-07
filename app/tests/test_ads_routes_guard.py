"""app/tests/test_ads_routes_guard.py — F03-I20 falsifier: the tenant boundary runs before field
validation on every `/api/ads/*` route. Walks `main.app`'s route table (never a hand-written path
list, so a route added later is covered automatically) and asserts, for every method except
HEAD/OPTIONS: no `Authorization` header -> 401 envelope; a valid token for org A against a brand
belonging to org B -> 404; plus three targeted cases proving the field validation that used to live
in Pydantic (no default) still fires from inside the handler, against a real campaign of the
caller's own brand.
"""

import json
import re
import unittest
from uuid import uuid4

from fastapi.testclient import TestClient

import app.main as main
import app.shared.web as web
from app.ads import adapters as ads_adapters
from app.ads import brief as ads_brief
from app.ads import plan as ads_plan
from app.ads import repository as ads_repo
from app.ads import strategy as ads_strategy
from app.brand_intelligence import repository as bi_repo
from app.llm import providers
from app.tests.test_ads_strategy_decision import fixture_provider

from .identity_test_helpers import flatten_routes, mint_hs256

ACTOR = "測試員"

_PATH_PARAM = re.compile(r"\{[^}]+\}")
_FILLER_CANDIDATES = ("x", "1", "00000000-0000-0000-0000-000000000099")


def _filled_paths(template: str) -> list:
    return [_PATH_PARAM.sub(filler, template) for filler in _FILLER_CANDIDATES]


def _ads_routes() -> list:
    return [r for r in flatten_routes(main.app) if r.path.startswith("/api/ads/")]


class AdsRoutesNoAuthTest(unittest.TestCase):
    """No `Authorization` header -> 401 envelope, never 422 (F03-I20)."""

    def setUp(self):
        self.client = TestClient(main.app)
        self.client.headers.pop("Authorization", None)

    def test_every_ads_route_401s_without_authorization(self):
        failures = []
        checked = 0
        for route in _ads_routes():
            for method in route.methods or ():
                if method in ("HEAD", "OPTIONS"):
                    continue
                checked += 1
                passed = False
                attempts = []
                for filled in _filled_paths(route.path):
                    response = self.client.request(method, filled, json={})
                    if response.status_code == 401 and set(response.json()) == {"error"}:
                        passed = True
                        break
                    attempts.append((filled, response.status_code))
                if not passed:
                    failures.append(f"{method} {route.path} -> {attempts}")
        self.assertGreater(checked, 0, "沒掃到任何 /api/ads/ route，掃描本身壞了？")
        self.assertEqual(failures, [], "以下 ads route 沒有在缺 Authorization 時回 401 信封：\n"
                          + "\n".join(failures))


class AdsRoutesWrongTenantTest(unittest.TestCase):
    """A valid token for org A against a brand belonging to org B -> 404 (F03-I20)."""

    def setUp(self):
        self.client = TestClient(main.app)
        a_user = uuid4()
        self.a_token = mint_hs256(sub=str(a_user), email=f"adsa-{a_user.hex[:8]}@example.com")
        me_a = self.client.get(
            "/api/identity/me", headers={"Authorization": f"Bearer {self.a_token}"},
        )
        self.org_a = me_a.json()["org"]["id"]

        b_user = uuid4()
        b_token = mint_hs256(sub=str(b_user), email=f"adsb-{b_user.hex[:8]}@example.com")
        me_b = self.client.get("/api/identity/me", headers={"Authorization": f"Bearer {b_token}"})
        self.org_b = me_b.json()["org"]["id"]
        self.brand_b = bi_repo.create_brand(
            web.conn, org_id=self.org_b, name="組織B的品牌：投放中心守門", client_name=None,
            actor=ACTOR,
        )["id"]
        web.conn.commit()

    def test_every_ads_route_404s_for_wrong_tenant(self):
        failures = []
        checked = 0
        for route in _ads_routes():
            path_template = route.path.replace("{brand_id}", self.brand_b)
            for method in route.methods or ():
                if method in ("HEAD", "OPTIONS"):
                    continue
                checked += 1
                passed = False
                attempts = []
                for filled in _filled_paths(path_template):
                    response = self.client.request(
                        method, filled, json={},
                        headers={"Authorization": f"Bearer {self.a_token}"},
                    )
                    if response.status_code == 404:
                        passed = True
                        break
                    attempts.append((filled, response.status_code, response.text[:120]))
                if not passed:
                    failures.append(f"{method} {route.path} -> {attempts}")
        self.assertGreater(checked, 0, "沒掃到任何 /api/ads/ route，掃描本身壞了？")
        self.assertEqual(failures, [], "以下 ads route 沒有在跨組織品牌時回 404：\n"
                          + "\n".join(failures))


class AdsRoutesValidationStillFiresTest(unittest.TestCase):
    """The field validation that used to live in Pydantic still fires from inside the handler,
    now as 400/404 with a snake_case `code`, against a real campaign of the caller's own brand."""

    def setUp(self):
        self.client = TestClient(main.app)
        user = uuid4()
        self.token = mint_hs256(sub=str(user), email=f"adsc-{user.hex[:8]}@example.com")
        me = self.client.get("/api/identity/me", headers={"Authorization": f"Bearer {self.token}"})
        self.org_id = me.json()["org"]["id"]
        self.brand_id = bi_repo.create_brand(
            web.conn, org_id=self.org_id, name="測試品牌：投放中心守門驗證", client_name=None,
            actor=ACTOR,
        )["id"]
        campaign = {
            "name": "守門測試 Campaign", "goal_text": "驗證欄位守門",
            "objective": "購買", "target_cost": 300,
            "start_date": "2026-10-01", "end_date": "2026-10-14", "status": "draft",
            "budget_planned": 1400, "budget_scenario": "recommended",
            "budget_basis_json": {"strategy": {"allocation": []}},
            "context_json": {"product_ids": []},
        }
        self.campaign_id = ads_repo.create_campaign(
            web.conn, self.org_id, self.brand_id, campaign, created_by=ACTOR,
        )["id"]
        web.conn.commit()
        self.headers = {"Authorization": f"Bearer {self.token}"}

    def test_create_group_empty_body_is_daily_budget_invalid(self):
        response = self.client.post(
            f"/api/ads/brands/{self.brand_id}/campaigns/{self.campaign_id}/groups",
            json={}, headers=self.headers,
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["error"]["code"], "daily_budget_invalid")

    def test_create_ad_empty_body_is_not_a_pydantic_422(self):
        # `app.ads.plan.create_ad` (do_not_touch) checks `name` before `group_id`, so an
        # entirely empty body actually surfaces `name_unknown` first — the point this test
        # proves is that a 400 with a domain `code` still comes back instead of a bare
        # Pydantic 422, not the exact ordering of the two checks.
        response = self.client.post(
            f"/api/ads/brands/{self.brand_id}/campaigns/{self.campaign_id}/ads",
            json={}, headers=self.headers,
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["error"]["code"], "name_unknown")

    def test_create_ad_named_body_with_unknown_group_is_group_unknown(self):
        response = self.client.post(
            f"/api/ads/brands/{self.brand_id}/campaigns/{self.campaign_id}/ads",
            json={"name": "廣告一"}, headers=self.headers,
        )
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json()["error"]["code"], "group_unknown")

    def test_asset_ready_empty_body_is_ready_invalid(self):
        response = self.client.post(
            f"/api/ads/brands/{self.brand_id}/ads/some-ad-id/asset-ready",
            json={}, headers=self.headers,
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["error"]["code"], "ready_invalid")

    def test_slot_recheck_is_in_the_walked_table_and_answers_with_domain_codes(self):
        # F44-I04: the route the two walks above must reach, and -- past the tenant boundary --
        # its own refusals for the caller's real campaign (no body is read).
        template = "/api/ads/brands/{brand_id}/campaigns/{campaign_id}/slots/{ad_id}/recheck"
        self.assertEqual(
            [sorted(r.methods - {"HEAD", "OPTIONS"}) for r in _ads_routes() if r.path == template],
            [["POST"]],
        )
        prefix = f"/api/ads/brands/{self.brand_id}/campaigns"
        unknown_ad = self.client.post(
            f"{prefix}/{self.campaign_id}/slots/some-ad-id/recheck", headers=self.headers,
        )
        self.assertEqual(unknown_ad.status_code, 409, unknown_ad.text)
        self.assertEqual(unknown_ad.json()["error"]["code"], "user_asset_unavailable")
        unknown_campaign = self.client.post(
            f"{prefix}/adc_missing/slots/some-ad-id/recheck", headers=self.headers,
        )
        self.assertEqual(unknown_campaign.status_code, 404, unknown_campaign.text)
        self.assertEqual(unknown_campaign.json()["error"]["code"], "campaign_unknown")

    def test_coordinate_learnings_is_in_the_walked_table_and_filters_without_404(self):
        # F46-I05 Contract L: the two walks above reach the learnings read; past the tenant
        # boundary an unknown campaign / sell-way of the caller's own brand is an empty list.
        template = "/api/ads/brands/{brand_id}/coordinate-learnings"
        self.assertEqual(
            [sorted(r.methods - {"HEAD", "OPTIONS"}) for r in _ads_routes() if r.path == template],
            [["GET"]],
        )
        response = self.client.get(
            f"/api/ads/brands/{self.brand_id}/coordinate-learnings"
            "?campaign_id=adc_missing&sell_way_id=prd_missing",
            headers=self.headers,
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["campaigns"], [])

    def test_pause_view_is_in_the_walked_table_and_reads_unknown_ads_as_gone(self):
        # F45-I05 Contract P: the two walks above reach the pause read; past the tenant boundary
        # an unknown campaign is the only 404 and an unknown ad is a `gone` answer, not an error.
        template = "/api/ads/brands/{brand_id}/campaigns/{campaign_id}/triage/{entity_id}/pause"
        self.assertEqual(
            [sorted(r.methods - {"HEAD", "OPTIONS"}) for r in _ads_routes() if r.path == template],
            [["GET"]],
        )
        prefix = f"/api/ads/brands/{self.brand_id}/campaigns"
        unknown_ad = self.client.get(
            f"{prefix}/{self.campaign_id}/triage/some-ad-id/pause", headers=self.headers,
        )
        self.assertEqual(unknown_ad.status_code, 200, unknown_ad.text)
        self.assertEqual(unknown_ad.json()["pause"]["state"], "gone")
        unknown_campaign = self.client.get(
            f"{prefix}/adc_missing/triage/some-ad-id/pause", headers=self.headers,
        )
        self.assertEqual(unknown_campaign.status_code, 404, unknown_campaign.text)
        self.assertEqual(unknown_campaign.json()["error"]["code"], "campaign_unknown")


class NameMatchBindRemovedTest(unittest.TestCase):
    """F31-I08 (item 11): the ads-center name-match bind had no screen calling it and launch
    readback replaced it, so the route and every adapter's `bind` verb are gone -- not kept with
    a better message. Same real campaign of the caller's own brand as the class above."""

    setUp = AdsRoutesValidationStillFiresTest.setUp

    def test_bind_route_is_gone_for_a_real_campaign(self):
        response = self.client.post(
            f"/api/ads/brands/{self.brand_id}/campaigns/{self.campaign_id}/bind",
            json={}, headers=self.headers,
        )
        self.assertIn(response.status_code, (404, 405), response.text)
        self.assertEqual(
            [r.path for r in _ads_routes() if r.path.endswith("/bind")], [],
        )

    def test_no_adapter_has_a_bind_verb(self):
        for name in ("manual", "auto_meta", "simulated"):
            with self.subTest(adapter=name):
                adapter = ads_adapters.get_adapter(name)
                self.assertIsNotNone(adapter)
                self.assertFalse(hasattr(adapter, "bind"))


def _fake(rendered_output: str) -> providers.FakeProvider:
    return fixture_provider(rendered_output)


_BRIEF_REPLY = json.dumps({
    "objective": "購買", "cap": 500, "product_ids": [], "audience_hint": None, "notes": None,
}, ensure_ascii=False)

_STRATEGY_REPLY = json.dumps({
    "allocation": [
        {"role": "new", "label": "新客", "pct": 50, "rationale": "打平 CPA 還沒驗證過新客"},
        {"role": "retarget", "label": "再行銷", "pct": 30, "rationale": "有過去購買資料"},
        {"role": "explore", "label": "探索", "pct": 20, "rationale": "測試新素材角度"},
    ],
    "why": ["依品牌事實與過去學習分配"], "unknowns": ["新受眾的實際轉換率"], "alternatives": [],
}, ensure_ascii=False)


def _coordinates(tag: str) -> dict:
    return {
        "audience": f"aud_{tag}", "pain": f"pain_{tag}", "angle": f"angle_{tag}",
        "hook": f"hook_{tag}", "proof": f"proof_{tag}", "offer": f"offer_{tag}",
        "format": f"format_{tag}",
    }


_PLAN_REPLY = json.dumps({
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


class AdsRoutesShapeStaysConsistentTest(unittest.TestCase):
    """F04-I24 falsifier: every route that returns `{"campaign": ...}` returns the same shape as
    GET — `campaign_detail` + `asset_readiness` (+ F42-I02 `materials`) — never a bare
    `campaign_detail` missing the field `StrategyTab.tsx` reads unconditionally (drill 4,
    custom-budget scenario -> white screen)."""

    def setUp(self):
        self.client = TestClient(main.app)
        user = uuid4()
        self.token = mint_hs256(sub=str(user), email=f"adsd-{user.hex[:8]}@example.com")
        me = self.client.get("/api/identity/me", headers={"Authorization": f"Bearer {self.token}"})
        self.org_id = me.json()["org"]["id"]
        self.brand_id = bi_repo.create_brand(
            web.conn, org_id=self.org_id, name="測試品牌：投放中心形狀守門", client_name=None,
            actor=ACTOR,
        )["id"]
        # F33-I01：`_STRATEGY_REPLY` 分了 `retarget`，品牌要先合格（Contract P 可用角色）。
        bi_repo.set_advertising_history(
            web.conn, self.brand_id, "has_history", actor=ACTOR,
        )
        web.conn.commit()
        self.headers = {"Authorization": f"Bearer {self.token}"}

        self._orig_brief_provider = ads_brief.PROVIDER
        self._orig_strategy_provider = ads_strategy.PROVIDER
        self._orig_plan_provider = ads_plan.PROVIDER
        ads_brief.PROVIDER = _fake(_BRIEF_REPLY)
        ads_strategy.PROVIDER = _fake(_STRATEGY_REPLY)
        ads_plan.PROVIDER = _fake(_PLAN_REPLY)

    def tearDown(self):
        ads_brief.PROVIDER = self._orig_brief_provider
        ads_strategy.PROVIDER = self._orig_strategy_provider
        ads_plan.PROVIDER = self._orig_plan_provider

    def _assert_shape(self, response):
        self.assertEqual(response.status_code, 200, response.text)
        readiness = response.json()["campaign"]["asset_readiness"]
        self.assertIsInstance(readiness["total"], int)
        self.assertIsInstance(readiness["ready_count"], int)
        # F42-I02: the strategy tab reads 「這期會用」 from the same shape.
        materials = response.json()["campaign"]["materials"]
        self.assertEqual(set(materials), {"offers", "proof", "media"})

    def test_every_route_back_to_campaign_carries_asset_readiness(self):
        create = self.client.post(
            f"/api/ads/brands/{self.brand_id}/campaigns",
            json={
                "goal_text": "幫夜跑背心做一波購買導向的投放",
                "start_date": "2026-10-01", "end_date": "2026-10-31",
            },
            headers=self.headers,
        )
        self._assert_shape(create)
        campaign_id = create.json()["campaign"]["id"]

        patch = self.client.patch(
            f"/api/ads/brands/{self.brand_id}/campaigns/{campaign_id}",
            json={"goal_text": "幫夜跑背心衝購買"}, headers=self.headers,
        )
        self._assert_shape(patch)

        generate = self.client.post(
            f"/api/ads/brands/{self.brand_id}/campaigns/{campaign_id}/strategy",
            headers=self.headers,
        )
        self._assert_shape(generate)

        # 阿明走查白畫面的那一下：自訂總額情境。
        scenario = self.client.post(
            f"/api/ads/brands/{self.brand_id}/campaigns/{campaign_id}/strategy/scenario",
            json={"scenario_key": "custom", "custom_total": 28000}, headers=self.headers,
        )
        self._assert_shape(scenario)

        allocation = self.client.post(
            f"/api/ads/brands/{self.brand_id}/campaigns/{campaign_id}/strategy/allocation",
            json={"allocation": [
                {"role": "new", "pct": 50}, {"role": "retarget", "pct": 30},
                {"role": "explore", "pct": 20},
            ]},
            headers=self.headers,
        )
        self._assert_shape(allocation)

        # The original 28,000 custom branch is already covered above. The three explicit
        # fixture slots need enough daily budget before their confirmed adoption.
        feasible_scenario = self.client.post(
            f"/api/ads/brands/{self.brand_id}/campaigns/{campaign_id}/strategy/scenario",
            json={"scenario_key": "custom", "custom_total": 93000}, headers=self.headers,
        )
        self._assert_shape(feasible_scenario)
        # Structure edits invalidate the previous Contract S proposal. Display a fresh
        # revision and explicitly confirm it before testing the adoption response shape.
        regenerated = self.client.post(
            f"/api/ads/brands/{self.brand_id}/campaigns/{campaign_id}/strategy",
            headers=self.headers,
        )
        self._assert_shape(regenerated)
        decision = regenerated.json()["campaign"]["budget_basis_json"]["strategy"]["decision"]
        revision = decision["revision"]
        adopt = self.client.post(
            f"/api/ads/brands/{self.brand_id}/campaigns/{campaign_id}/plan",
            json={"expected_revision": revision, "operation_id": "route-shape-adopt"},
            headers=self.headers,
        )
        self._assert_shape(adopt)

        get = self.client.get(
            f"/api/ads/brands/{self.brand_id}/campaigns/{campaign_id}", headers=self.headers,
        )
        self._assert_shape(get)


if __name__ == "__main__":
    unittest.main()
