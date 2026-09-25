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
            "objective": "購買", "target_cost": 300,
            "start_date": "2026-10-01", "end_date": "2026-10-14", "status": "draft",
            "budget_planned": 1400, "budget_scenario": "recommended",
            "budget_basis_json": {"strategy": {"allocation": allocation}},
            "context_json": {"product_ids": product_ids or []},
        }
        row = ads_repo.create_campaign(web.conn, self.org_id, self.brand_id, campaign,
                                        created_by=ACTOR)
        plan.PROVIDER = _fake(_VALID_PLAN_REPLY)
        return plan.adopt_strategy(web.conn, self.org_id, self.brand_id, row["id"], actor=ACTOR)

    def _direct_campaign(self, *, campaign_start, campaign_end, group_role: str = "new",
                          group_start=None, group_end=None,
                          format_key: str | None = "single_image"):
        """F07-I10：繞過 LLM 展開，直接建一個 Campaign／一個投放組／一支廣告，讓天數與
        format_key 完全可控（`_variant_count` 的落點測試用）。"""
        campaign = {
            "name": "測試 Campaign", "goal_text": "衝購買", "objective": "購買",
            "target_cost": 300,
            "start_date": campaign_start, "end_date": campaign_end, "status": "draft",
            "budget_planned": 1400, "budget_scenario": "recommended",
            "budget_basis_json": {"strategy": {"allocation": [
                {"role": "new", "label": "新客", "pct": 100, "rationale": None},
            ]}},
        }
        campaign_row = ads_repo.create_campaign(
            web.conn, self.org_id, self.brand_id, campaign, created_by=ACTOR,
        )
        group = ads_repo.create_group(
            web.conn, self.org_id, self.brand_id, campaign_row["id"], channel_key="meta",
            name="投放組", role=group_role, daily_budget=100,
            start_date=group_start, end_date=group_end,
        )
        coordinates = {"format": format_key} if format_key is not None else {}
        ad = ads_repo.create_ad(
            web.conn, self.org_id, self.brand_id, campaign_row["id"], group["id"],
            name="廣告", coordinates=coordinates, coordinates_snapshot={},
        )
        web.conn.commit()
        return campaign_row, group, ad

    def _dispatched_set(self, campaign_id: str) -> dict:
        with mock.patch.object(
            assets.workbench, "submit_pack", wraps=assets.workbench.submit_pack,
        ) as submit_pack:
            assets.dispatch_pack(web.conn, self.org_id, self.brand_id, campaign_id)
        return submit_pack.call_args.args[-1]["sets"][0]

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
        current_pack_id = assets.pack_id(web.conn, self.org_id, self.brand_id, campaign["id"])
        summary = assets.readiness_summary(after, current_pack_id)
        self.assertEqual(summary, {"ready_count": 2, "total": 2, "pack_id": pack_id})


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
        self.assertIsNone(assets.pack_id(web.conn, self.org_id, self.brand_id, campaign["id"]))

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


# -- 案例 7：交棒後新增的廣告沒有自己的 set，但 pack 本身還在——asset_readiness.pack_id
# 要從 pack 讀，不是從逐列 briefs 推（§6.2 決議 15） ------------------------------------------

class PackIdSurvivesRebuiltAdsTest(AssetsTestBase):
    def test_pack_id_survives_deleting_and_recreating_every_ad(self):
        campaign = self._adopted_campaign()
        group_id = campaign["groups"][0]["id"]
        ad_ids = [ad["id"] for ad in campaign["groups"][0]["ads"]]

        pack_id = assets.dispatch_pack(web.conn, self.org_id, self.brand_id, campaign["id"])

        for ad_id in ad_ids:
            plan.delete_ad(web.conn, self.org_id, self.brand_id, ad_id)
        plan.create_ad(
            web.conn, self.org_id, self.brand_id, campaign["id"], group_id,
            name="新廣告-交棒後才加", coordinates=_coordinates("later"),
        )
        web.conn.commit()

        resp = self.client.get(f"/api/ads/brands/{self.brand_id}/campaigns/{campaign['id']}")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(
            resp.json()["campaign"]["asset_readiness"],
            {"ready_count": 0, "total": 1, "pack_id": pack_id},
        )


# -- 案例 8：F07-I10 派工不再送 style_key／image_prompt_count -----------------------------------

class NoStyleOrCountKeyTest(AssetsTestBase):
    def test_sets_carry_no_style_key_or_image_prompt_count(self):
        campaign = self._adopted_campaign()

        with mock.patch.object(
            assets.workbench, "submit_pack", wraps=assets.workbench.submit_pack,
        ) as submit_pack:
            assets.dispatch_pack(web.conn, self.org_id, self.brand_id, campaign["id"])

        pack = submit_pack.call_args.args[-1]
        for s in pack["sets"]:
            self.assertNotIn("style_key", s)
            self.assertNotIn("image_prompt_count", s["request"])


# -- 案例 9：單圖 ② 變體張數依排程天數（D03-D09, D12） --------------------------------------------

class VariantCountByDaySpanTest(AssetsTestBase):
    def test_new_group_variant_count_by_campaign_day_span(self):
        cases = [
            ("2026-10-01", "2026-10-07", 3),   # 7 天（含頭尾）→ 3
            ("2026-10-01", "2026-10-08", 6),   # 8 天 → 6
            ("2026-10-01", "2026-10-21", 6),   # 21 天 → 6
            ("2026-10-01", "2026-10-22", 9),   # 22 天 → 9
        ]
        for start, end, expected in cases:
            with self.subTest(start=start, end=end):
                campaign_row, _group, _ad = self._direct_campaign(
                    campaign_start=start, campaign_end=end,
                )
                target_set = self._dispatched_set(campaign_row["id"])
                self.assertEqual(target_set["request"]["variant_count"], expected)

    def test_retarget_group_adds_three_and_caps_at_nine(self):
        cases = [
            ("2026-10-01", "2026-10-07", 6),   # 3 + 3
            ("2026-10-01", "2026-10-08", 9),   # 6 + 3
            ("2026-10-01", "2026-10-21", 9),   # 6 + 3
            ("2026-10-01", "2026-10-22", 9),   # 9 + 3 = 12，封頂 9
        ]
        for start, end, expected in cases:
            with self.subTest(start=start, end=end):
                campaign_row, _group, _ad = self._direct_campaign(
                    campaign_start=start, campaign_end=end, group_role="retarget",
                )
                target_set = self._dispatched_set(campaign_row["id"])
                self.assertEqual(target_set["request"]["variant_count"], expected)

    def test_no_dates_anywhere_defaults_to_six_new_nine_retarget(self):
        campaign_row, _group, _ad = self._direct_campaign(
            campaign_start=None, campaign_end=None,
        )
        self.assertEqual(self._dispatched_set(campaign_row["id"])["request"]["variant_count"], 6)

        campaign_row, _group, _ad = self._direct_campaign(
            campaign_start=None, campaign_end=None, group_role="retarget",
        )
        self.assertEqual(self._dispatched_set(campaign_row["id"])["request"]["variant_count"], 9)


# -- 案例 10：投放組自己的天數贏過 Campaign 的天數（D10、D11） ------------------------------------

class GroupDatesWinOverCampaignDatesTest(AssetsTestBase):
    def test_group_dates_win_over_campaign_dates(self):
        # 投放組只有 7 天，Campaign 開了 30 天——結果要照投放組的 7 天算（3），不是 30 天。
        campaign_row, _group, _ad = self._direct_campaign(
            campaign_start="2026-10-01", campaign_end="2026-10-30",
            group_start="2026-11-01", group_end="2026-11-07",
        )
        self.assertEqual(self._dispatched_set(campaign_row["id"])["request"]["variant_count"], 3)

    def test_group_with_only_one_date_falls_back_to_campaign_dates(self):
        # 投放組只填了開始日期——`plan._days` 兩邊缺一是 0，退回 Campaign 的 30 天 → 9。
        campaign_row, _group, _ad = self._direct_campaign(
            campaign_start="2026-10-01", campaign_end="2026-10-30",
            group_start="2026-11-01", group_end=None,
        )
        self.assertEqual(self._dispatched_set(campaign_row["id"])["request"]["variant_count"], 9)


# -- 案例 11：每支廣告用自己那個投放組的天數與角色（D13） -----------------------------------------

class EachAdUsesItsOwnGroupTest(AssetsTestBase):
    def test_each_ad_uses_its_own_groups_dates_and_role(self):
        campaign = {
            "name": "測試 Campaign", "goal_text": "衝購買", "objective": "購買",
            "target_cost": 300,
            "start_date": "2026-10-01", "end_date": "2026-10-01", "status": "draft",
            "budget_planned": 1400, "budget_scenario": "recommended",
            "budget_basis_json": {"strategy": {"allocation": [
                {"role": "new", "label": "新客", "pct": 50, "rationale": None},
                {"role": "retarget", "label": "再行銷", "pct": 50, "rationale": None},
            ]}},
        }
        campaign_row = ads_repo.create_campaign(
            web.conn, self.org_id, self.brand_id, campaign, created_by=ACTOR,
        )
        group_new = ads_repo.create_group(
            web.conn, self.org_id, self.brand_id, campaign_row["id"], channel_key="meta",
            name="新客組", role="new", daily_budget=100,
            start_date="2026-10-01", end_date="2026-10-07",  # 7 天 → 3
        )
        group_rt = ads_repo.create_group(
            web.conn, self.org_id, self.brand_id, campaign_row["id"], channel_key="meta",
            name="再行銷組", role="retarget", daily_budget=100,
            start_date="2026-10-01", end_date="2026-10-22",  # 22 天 +3 封頂 → 9
        )
        ad_new = ads_repo.create_ad(
            web.conn, self.org_id, self.brand_id, campaign_row["id"], group_new["id"],
            name="新客廣告", coordinates={"format": "single_image"}, coordinates_snapshot={},
        )
        ad_rt = ads_repo.create_ad(
            web.conn, self.org_id, self.brand_id, campaign_row["id"], group_rt["id"],
            name="再行銷廣告", coordinates={"format": "single_image"}, coordinates_snapshot={},
        )
        web.conn.commit()

        with mock.patch.object(
            assets.workbench, "submit_pack", wraps=assets.workbench.submit_pack,
        ) as submit_pack:
            assets.dispatch_pack(web.conn, self.org_id, self.brand_id, campaign_row["id"])
        pack = submit_pack.call_args.args[-1]
        sets_by_ad_id = {s["source_ref"]["ads_ad_id"]: s for s in pack["sets"]}
        self.assertEqual(sets_by_ad_id[ad_new["id"]]["request"]["variant_count"], 3)
        self.assertEqual(sets_by_ad_id[ad_rt["id"]]["request"]["variant_count"], 9)


# -- 案例 12：格式決定 required_outputs／request（D14-D17） --------------------------------------

class FormatKeyDrivesRequiredOutputsTest(AssetsTestBase):
    def test_carousel_gets_no_image_variants(self):
        campaign_row, _group, _ad = self._direct_campaign(
            campaign_start="2026-10-01", campaign_end="2026-10-07", format_key="carousel",
        )
        target_set = self._dispatched_set(campaign_row["id"])
        self.assertEqual(target_set["required_outputs"], {"copy": 1, "image_prompt": 1})
        self.assertEqual(target_set["request"]["variant_count"], 0)

    def test_video_gets_copy_and_video_script_no_image(self):
        campaign_row, _group, _ad = self._direct_campaign(
            campaign_start="2026-10-01", campaign_end="2026-10-07", format_key="video",
        )
        target_set = self._dispatched_set(campaign_row["id"])
        self.assertEqual(target_set["required_outputs"], {"copy": 1, "video_script": 1})
        self.assertEqual(target_set["request"]["video_script_count"], 3)
        self.assertNotIn("variant_count", target_set["request"])
        self.assertNotIn("image_prompt", target_set["required_outputs"])

    def test_stored_flexible_follows_single_image_rule(self):
        campaign_row, _group, _ad = self._direct_campaign(
            campaign_start="2026-10-01", campaign_end="2026-10-07", format_key="flexible",
        )
        target_set = self._dispatched_set(campaign_row["id"])
        self.assertEqual(target_set["required_outputs"], {"copy": 1, "image_prompt": 1})
        self.assertEqual(target_set["request"]["variant_count"], 3)

    def test_none_format_and_brand_made_key_follow_single_image_rule(self):
        for format_key in (None, "brand_made_key"):
            with self.subTest(format_key=format_key):
                campaign_row, _group, _ad = self._direct_campaign(
                    campaign_start="2026-10-01", campaign_end="2026-10-07", format_key=format_key,
                )
                target_set = self._dispatched_set(campaign_row["id"])
                self.assertEqual(target_set["required_outputs"], {"copy": 1, "image_prompt": 1})
                self.assertEqual(target_set["request"]["variant_count"], 3)

    def test_dispatch_pack_succeeds_end_to_end_for_video(self):
        # 工作檯要接得住 video_script_count=3、沒有 image_prompt_count（D19）。
        campaign_row, _group, _ad = self._direct_campaign(
            campaign_start="2026-10-01", campaign_end="2026-10-07", format_key="video",
        )
        pack_id = assets.dispatch_pack(web.conn, self.org_id, self.brand_id, campaign_row["id"])
        self.assertIsNotNone(pack_id)


if __name__ == "__main__":
    unittest.main()
