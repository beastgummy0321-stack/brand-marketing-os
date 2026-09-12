"""app/tests/test_ads_routes_guard.py — F03-I20 falsifier: the tenant boundary runs before field
validation on every `/api/ads/*` route. Walks `main.app`'s route table (never a hand-written path
list, so a route added later is covered automatically) and asserts, for every method except
HEAD/OPTIONS: no `Authorization` header -> 401 envelope; a valid token for org A against a brand
belonging to org B -> 404; plus three targeted cases proving the field validation that used to live
in Pydantic (no default) still fires from inside the handler, against a real campaign of the
caller's own brand.
"""

import re
import unittest
from uuid import uuid4

from fastapi.testclient import TestClient

import app.main as main
import app.shared.web as web
from app.ads import repository as ads_repo
from app.brand_intelligence import repository as bi_repo

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
            "objective": "購買", "success_metric": "cpa", "success_target": 300,
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


if __name__ == "__main__":
    unittest.main()
