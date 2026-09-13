"""app/tests/test_ads_assets.py — F03-I08 falsifiers: dispatching a Campaign's ads creates one
workbench pack with one set per ad (the set's `source_ref` carries the ad id, the pack `summary`
情境 key is a non-empty sentence); approving the pack in the workbench flips those ads to
`ready_workbench`, an unapproved pack reads `in_progress`; a hand tick on an ad outside any pack
gives `ready_manual` with actor and timestamp, untick returns it to `not_started`; readiness
never reads a `workbench_*` table directly (this test's own setup only ever calls the workbench's
public entries — `pack_for_source`/`briefs_for_source`/`submit_pack` — never raw SQL against
`workbench_*`); dispatching twice is refused.
"""

import json
import unittest
from unittest import mock

from fastapi.testclient import TestClient

import app.main as main
import app.shared.web as web
from app import workbench
from app.ads import assets, plan
from app.ads import repository as ads_repo
from app.brand_intelligence import repository as bi_repo
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
            {"name": "新客-廣告一", "coordinates": _coordinates("new1")},
            {"name": "新客-廣告二", "coordinates": _coordinates("new2")},
        ]},
    ],
}, ensure_ascii=False)


class AssetsTestBase(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(main.app)
        workbench.register_tasks()
        self.org_id = coredb.DEV_ORG_ID
        self.brand = bi_repo.create_brand(
            web.conn, org_id=self.org_id, name="測試品牌：投放中心素材", client_name=None,
            actor=ACTOR,
        )
        self.brand_id = self.brand["id"]
        self._orig_provider = plan.PROVIDER
        web.conn.commit()

    def tearDown(self):
        plan.PROVIDER = self._orig_provider

    def _adopted_campaign(self, product_ids: list | None = None) -> dict:
        allocation = [{"role": "new", "label": "新客", "pct": 100, "rationale": None}]
        campaign = {
            "name": "測試 Campaign", "goal_text": "幫新品衝第一波購買",
            "objective": "購買", "success_metric": "cpa", "success_target": 300,
            "start_date": "2026-10-01", "end_date": "2026-10-14", "status": "draft",
            "budget_planned": 1400, "budget_scenario": "recommended",
            "budget_basis_json": {"strategy": {"allocation": allocation}},
            "context_json": {"product_ids": product_ids or []},
        }
        row = ads_repo.create_campaign(web.conn, self.org_id, self.brand_id, campaign,
                                        created_by=ACTOR)
        plan.PROVIDER = _fake(_VALID_PLAN_REPLY)
        return plan.adopt_strategy(web.conn, self.org_id, self.brand_id, row["id"], actor=ACTOR)

    def _tick_all(self, pack_id: str) -> None:
        for key in ("required_outputs_met", "brand_rules_checked", "ready_to_report"):
            resp = self.client.post(
                f"/api/workbench/brands/{self.brand_id}/packs/{pack_id}/completion",
                json={"key": key, "checked": True},
            )
            self.assertEqual(resp.status_code, 200)

    def _approve(self, pack_id: str):
        return self.client.post(f"/api/workbench/brands/{self.brand_id}/packs/{pack_id}/approve")


# -- 案例 1：交棒建一個 pack、一支廣告一個 set，摘要的「情境」是一句非空的話 --------------------

class DispatchCreatesOneSetPerAdTest(AssetsTestBase):
    def test_dispatch_creates_one_pack_one_set_per_ad_with_sentence_summary(self):
        campaign = self._adopted_campaign()
        ad_ids = {ad["id"] for group in campaign["groups"] for ad in group["ads"]}
        self.assertEqual(len(ad_ids), 2)

        pack_id = assets.dispatch_pack(web.conn, self.org_id, self.brand_id, campaign["id"])

        resp = self.client.get(f"/api/workbench/brands/{self.brand_id}/packs/{pack_id}")
        self.assertEqual(resp.status_code, 200)
        pack = resp.json()["pack"]
        self.assertTrue(pack["summary"]["situation"])
        self.assertIsInstance(pack["summary"]["situation"], str)

        briefs = workbench.briefs_for_source(
            web.conn, self.org_id, self.brand_id, assets.PACK_SOURCE_KIND,
            {"ads_campaign_id": campaign["id"]},
        )
        self.assertEqual(len(briefs), 2)
        brief_ad_ids = {b["source_ref"]["ads_ad_id"] for b in briefs}
        self.assertEqual(brief_ad_ids, ad_ids)


# -- 案例 2：核准前 in_progress，核准後這個 pack 底下的廣告全部變 ready_workbench --------------

class ApprovalFlipsReadinessTest(AssetsTestBase):
    def test_approving_pack_flips_dispatched_ads_to_ready_workbench(self):
        campaign = self._adopted_campaign()
        pack_id = assets.dispatch_pack(web.conn, self.org_id, self.brand_id, campaign["id"])

        before = assets.readiness(web.conn, self.org_id, self.brand_id, campaign["id"])
        self.assertEqual({row["state"] for row in before}, {"in_progress"})
        self.assertTrue(all(row["pack_id"] == pack_id for row in before))

        self._tick_all(pack_id)
        approved = self._approve(pack_id)
        self.assertEqual(approved.status_code, 200)

        after = assets.readiness(web.conn, self.org_id, self.brand_id, campaign["id"])
        self.assertEqual({row["state"] for row in after}, {"ready_workbench"})
        summary = assets.readiness_summary(after)
        self.assertEqual(summary, {"ready_count": 2, "total": 2})


# -- 案例 3：手動勾「素材已就位」——不進工作檯的廣告一樣可以就緒 -------------------------------

class ManualTickTest(AssetsTestBase):
    def test_manual_tick_gives_ready_manual_untick_returns_not_started(self):
        campaign = self._adopted_campaign()
        ad = campaign["groups"][0]["ads"][0]

        before = assets.readiness(web.conn, self.org_id, self.brand_id, campaign["id"])
        self.assertTrue(all(row["state"] == "not_started" for row in before))

        ticked = assets.mark_ready(
            web.conn, self.org_id, self.brand_id, ad["id"], actor=ACTOR, ready=True,
        )
        self.assertEqual(ticked["asset_ready_source"], "manual")
        self.assertEqual(ticked["asset_ready_by"], ACTOR)
        self.assertIsNotNone(ticked["asset_ready_at"])

        rows = assets.readiness(web.conn, self.org_id, self.brand_id, campaign["id"])
        row = next(r for r in rows if r["ad_id"] == ad["id"])
        self.assertEqual(row["state"], "ready_manual")
        self.assertEqual(row["by"], ACTOR)
        self.assertIsNotNone(row["at"])

        untucked = assets.mark_ready(
            web.conn, self.org_id, self.brand_id, ad["id"], actor=ACTOR, ready=False,
        )
        self.assertIsNone(untucked["asset_ready_source"])
        rows_after = assets.readiness(web.conn, self.org_id, self.brand_id, campaign["id"])
        row_after = next(r for r in rows_after if r["ad_id"] == ad["id"])
        self.assertEqual(row_after["state"], "not_started")


# -- 案例 4：交棒兩次被拒 --------------------------------------------------------------------

class DoubleDispatchRefusedTest(AssetsTestBase):
    def test_dispatching_twice_is_refused(self):
        campaign = self._adopted_campaign()
        assets.dispatch_pack(web.conn, self.org_id, self.brand_id, campaign["id"])

        with self.assertRaises(ValueError) as ctx:
            assets.dispatch_pack(web.conn, self.org_id, self.brand_id, campaign["id"])
        self.assertEqual(str(ctx.exception), "pack_already_exists")


# -- 案例 5：交棒但未核准時手動勾其中一支廣告——那支 ready_manual，其餘仍 in_progress；
# 送出的 set 帶著 use_brand_knowledge／product_ids（讀 briefs_for_source，不查原生 SQL）------

class DispatchedUnapprovedManualTickTest(AssetsTestBase):
    def test_manual_tick_wins_over_unapproved_pack_and_brand_knowledge_is_requested(self):
        product = bi_repo.create_product(web.conn, self.brand_id, name="測試商品", actor=ACTOR)
        web.conn.commit()
        campaign = self._adopted_campaign(product_ids=[product["id"]])
        ads = [ad for group in campaign["groups"] for ad in group["ads"]]
        ticked_ad, other_ad = ads[0], ads[1]

        pack_id = assets.dispatch_pack(web.conn, self.org_id, self.brand_id, campaign["id"])
        assets.mark_ready(
            web.conn, self.org_id, self.brand_id, ticked_ad["id"], actor=ACTOR, ready=True,
        )

        rows = assets.readiness(web.conn, self.org_id, self.brand_id, campaign["id"])
        by_ad_id = {r["ad_id"]: r for r in rows}
        self.assertEqual(by_ad_id[ticked_ad["id"]]["state"], "ready_manual")
        self.assertEqual(by_ad_id[other_ad["id"]]["state"], "in_progress")

        briefs = workbench.briefs_for_source(
            web.conn, self.org_id, self.brand_id, assets.PACK_SOURCE_KIND,
            {"ads_campaign_id": campaign["id"]},
        )
        self.assertEqual(len(briefs), 2)
        for brief in briefs:
            self.assertIs(brief["request_json"]["use_brand_knowledge"], True)
            self.assertEqual(brief["request_json"]["product_ids"], [product["id"]])
        self.assertTrue(all(b.get("pack_id") == pack_id for b in briefs))


# -- 案例 6：派工只送那一則廣告自己的商品，不送整個 Campaign 的商品目錄（F04-I04）------------

class DispatchSendsOnlyTheAdsOwnProductTest(AssetsTestBase):
    def _set_ad_product_id(self, ad_id: str, product_id: str | None) -> None:
        web.conn.execute(
            "UPDATE ads_ad SET product_id = %s WHERE org_id = %s AND brand_id = %s AND id = %s",
            (product_id, self.org_id, self.brand_id, ad_id),
        )

    def test_ad_with_its_own_product_id_sends_only_that_one(self):
        products = [
            bi_repo.create_product(web.conn, self.brand_id, name=f"商品{i}", actor=ACTOR)
            for i in range(3)
        ]
        web.conn.commit()
        product_ids = [p["id"] for p in products]
        campaign = self._adopted_campaign(product_ids=product_ids)
        ads = [ad for group in campaign["groups"] for ad in group["ads"]]
        self._set_ad_product_id(ads[0]["id"], product_ids[1])
        web.conn.commit()

        with mock.patch.object(
            assets.workbench, "submit_pack", wraps=assets.workbench.submit_pack,
        ) as submit_pack:
            assets.dispatch_pack(web.conn, self.org_id, self.brand_id, campaign["id"])

        pack = submit_pack.call_args.args[-1]
        target_set = next(s for s in pack["sets"] if s["source_ref"]["ads_ad_id"] == ads[0]["id"])
        self.assertEqual(target_set["request"]["product_ids"], [product_ids[1]])
        self.assertEqual(len(target_set["request"]["product_ids"]), 1)

    def test_ad_without_product_id_falls_back_to_campaigns_first_product(self):
        products = [
            bi_repo.create_product(web.conn, self.brand_id, name=f"商品{i}", actor=ACTOR)
            for i in range(2)
        ]
        web.conn.commit()
        product_ids = [p["id"] for p in products]
        campaign = self._adopted_campaign(product_ids=product_ids)
        ads = [ad for group in campaign["groups"] for ad in group["ads"]]
        # ads_ad.product_id 沒被寫過（create_ad 從不寫這欄），這裡確認它確實是 None。
        self._set_ad_product_id(ads[0]["id"], None)
        web.conn.commit()

        with mock.patch.object(
            assets.workbench, "submit_pack", wraps=assets.workbench.submit_pack,
        ) as submit_pack:
            assets.dispatch_pack(web.conn, self.org_id, self.brand_id, campaign["id"])

        pack = submit_pack.call_args.args[-1]
        target_set = next(s for s in pack["sets"] if s["source_ref"]["ads_ad_id"] == ads[0]["id"])
        self.assertEqual(target_set["request"]["product_ids"], [product_ids[0]])
        self.assertEqual(len(target_set["request"]["product_ids"]), 1)


if __name__ == "__main__":
    unittest.main()
