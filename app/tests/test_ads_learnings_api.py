"""app/tests/test_ads_learnings_api.py — F46-I05 Contract L route falsifiers:
`GET /api/ads/brands/{b}/coordinate-learnings` serves `learning_view.learnings_view` as is, its
`campaign_id` / `sell_way_id` query params filter it, and an unknown id of this brand is an empty
list (a filter, never a 404). The tenant guard is walked by `test_ads_routes_guard.py`.

Rows are seeded with the public `record_learning` (the view's own shape is proven in
`test_ads_learning_view.py`).
"""

import unittest
from datetime import UTC, datetime

from fastapi.encoders import jsonable_encoder
from fastapi.testclient import TestClient

import app.main as main
from app.ads import learning_view, plan
from app.ads import repository as ads_repo
from app.brand_intelligence import repository as bi_repo
from app.core import db as coredb
from app.shared import web

ACTOR = "測試員"


class CoordinateLearningsRouteTest(unittest.TestCase):
    def setUp(self):
        self.conn = web.conn
        self.org_id = coredb.DEV_ORG_ID
        self.brand_id = bi_repo.create_brand(
            self.conn, org_id=self.org_id, name="測試品牌：學到的路由", client_name=None,
            actor=ACTOR,
        )["id"]
        self.box = bi_repo.create_product(self.conn, self.brand_id, name="三盒組", actor=ACTOR)
        self.single = bi_repo.create_product(self.conn, self.brand_id, name="單盒", actor=ACTOR)
        self.groups = bi_repo.save_customer_groups(
            self.conn, self.brand_id, self.box["id"],
            [{"who": "學生備考", "pain_keys": ["effort"]}], actor=ACTOR,
        )
        self.conn.commit()

        self.first = self._closed("三盒組・第一期", datetime(2026, 9, 19, 2, 0, tzinfo=UTC),
                                  self.box["id"])
        self._ranked(self.first, "備考生・讀到深夜", verdict="keep", rank=1, of=2, sales=4,
                     spend=1160, few=1)
        self._ranked(self.first, "會議前・午休", verdict="replace", rank=2, of=2, sales=0,
                     spend=1420)
        self.other = self._closed("單盒・第一期", datetime(2026, 9, 25, 2, 0, tzinfo=UTC),
                                  self.single["id"])
        self._ranked(self.other, "單盒・早餐", verdict="keep", rank=1, of=1, sales=6, spend=1800)
        self.conn.commit()  # `TestClient` reads on its own connection
        self.client = TestClient(main.app)

    def _closed(self, name: str, closed_at: datetime, product_id: str) -> dict:
        campaign = ads_repo.create_campaign(self.conn, self.org_id, self.brand_id, {
            "name": name, "goal_text": "x", "objective": "購買", "target_cost": 450,
            "start_date": "2026-09-05", "end_date": "2026-09-18", "status": "closed",
            # F48 Contract M: a non-draft campaign's sell-way is fixed (no PATCH after adoption).
            "context_json": {"product_ids": [product_id]},
        }, created_by=ACTOR)
        self.conn.execute("UPDATE ads_campaign SET closed_at = %s WHERE id = %s",
                          (closed_at, campaign["id"]))
        return campaign

    def _ranked(self, campaign: dict, name: str, *, verdict: str, rank: int, of: int,
                sales: int, spend: int, few: int = 0) -> None:
        group = plan.create_group(
            self.conn, self.org_id, self.brand_id, campaign["id"], name=f"組 {name}",
            role="new", daily_budget=500,
        )
        ad = plan.create_ad(
            self.conn, self.org_id, self.brand_id, campaign["id"], group["id"], name=name,
            coordinates={"audience": "cold", "pain": "effort", "angle": "box", "hook": "h",
                         "proof": "none", "offer": "none", "format": "single_image"},
        )
        cpr = round(spend / sales) if sales else "none"
        scope = (
            f"coord；v=2；verdict={verdict}；rank={rank}；of={of}；sales={sales}；spend={spend}"
            f"；cpr={cpr}；cap=450；few={few}；group={self.groups[0]['id']}；audience=cold"
            "；pain=effort；angle=box；hook=h；proof=none；offer=none；format=single_image；cur=TWD"
        )
        bi_repo.record_learning(
            self.conn, self.brand_id, actor=ACTOR, learning_text=name,
            applicability_scope=scope, confidence="observed", sample_size="高",
            source_cycle_id=f"{campaign['id']}:{ad['id']}", source_track="coordinate",
        )

    def _get(self, query: str = ""):
        response = self.client.get(
            f"/api/ads/brands/{self.brand_id}/coordinate-learnings{query}",
        )
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def test_unfiltered_route_is_the_view_as_is(self):
        body = self._get()
        self.assertEqual(body, jsonable_encoder(
            learning_view.learnings_view(self.conn, self.org_id, self.brand_id),
        ))
        self.assertEqual([c["campaign_name"] for c in body["campaigns"]],
                         ["單盒・第一期", "三盒組・第一期"])
        self.assertEqual(set(body), {"campaigns", "groups", "next", "evidence_context"})
        self.assertEqual(body["evidence_context"]["scope_product_id"], self.single["id"])
        self.assertEqual(body["evidence_context"]["eligible_count"], 0)
        for campaign in body["campaigns"]:
            for row in campaign["rows"]:
                self.assertEqual(row["evidence"]["id"], row["learning_id"])
                self.assertEqual(row["evidence"]["provenance"], "unknown")

    def test_campaign_filter(self):
        body = self._get(f"?campaign_id={self.first['id']}")
        [campaign] = body["campaigns"]
        self.assertEqual(campaign["campaign_id"], self.first["id"])
        self.assertEqual(
            [(r["rank"], r["ad_name"], r["verdict_label"], r["cost_per_sale"], r["flags"])
             for r in campaign["rows"]],
            [(1, "備考生・讀到深夜", "留下", 290, ["樣本少"]),
             (2, "會議前・午休", "換掉", None, [])],
        )
        self.assertEqual(campaign["counts"], {"keep": 1, "replace": 1})
        self.assertEqual(body["next"], {
            "sell_way_id": self.box["id"],
            "new_campaign_href": f"/brands/{self.brand_id}/ads/new?sell_way={self.box['id']}",
        })

    def test_sell_way_filter_and_both_filters(self):
        body = self._get(f"?sell_way_id={self.single['id']}")
        self.assertEqual([c["campaign_name"] for c in body["campaigns"]], ["單盒・第一期"])
        both = self._get(f"?campaign_id={self.first['id']}&sell_way_id={self.single['id']}")
        self.assertEqual(both["campaigns"], [])

    def test_unknown_ids_of_this_brand_are_an_empty_list_not_a_404(self):
        unknown_campaign = self._get("?campaign_id=adc_missing")
        self.assertEqual((unknown_campaign["campaigns"], unknown_campaign["groups"]), ([], []))
        self.assertIsNone(unknown_campaign["next"])
        unknown_sell_way = self._get("?sell_way_id=prd_missing")
        self.assertEqual((unknown_sell_way["campaigns"], unknown_sell_way["groups"]), ([], []))

    def test_empty_query_values_read_as_no_filter(self):
        body = self._get("?campaign_id=&sell_way_id=")
        self.assertEqual(len(body["campaigns"]), 2)


if __name__ == "__main__":
    unittest.main()
