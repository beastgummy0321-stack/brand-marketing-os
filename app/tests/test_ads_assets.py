"""app/tests/test_ads_assets.py — F03-I08 falsifiers: dispatching a Campaign's ads creates one
workbench pack with one set per ad (the set's `source_ref` carries the ad id, the pack `summary`
情境 key is a non-empty sentence); approving the pack in the workbench flips those ads to
`ready_workbench`, an unapproved pack reads `in_progress`; a hand tick on an ad outside any pack
gives `ready_manual` with actor and timestamp, untick returns it to `not_started`; neither an
approved pack nor a manual tick counts toward `ready_count` -- only a confirmed material binding
does, the launch batch's `ready_material` rule (F30-I16); readiness
never reads a `workbench_*` table directly (this test's own setup only ever calls the workbench's
public entries — `pack_for_source`/`briefs_for_source`/`submit_pack` — never raw SQL against
`workbench_*`); dispatching twice is refused.
"""

import json
import threading
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from unittest import mock

from fastapi.testclient import TestClient

import app.main as main
import app.shared.web as web
from app import workbench
from app.ads import assets, handoff_assignment, plan
from app.ads import repository as ads_repo
from app.ads import user_assets_repository as user_assets
from app.brand_intelligence import repository as bi_repo
from app.core import db as coredb
from app.llm import providers
from app.tests.test_ads_strategy_decision import bind_fixture, fixture_provider

ACTOR = "測試員"


def _fake(rendered_output: str) -> providers.FakeProvider:
    return fixture_provider(rendered_output)


def _coordinates(tag: str) -> dict:
    return {
        "audience": f"aud_{tag}", "pain": f"pain_{tag}", "angle": f"angle_{tag}",
        "hook": f"hook_{tag}", "proof": f"proof_{tag}", "offer": "none",
        "format": f"format_{tag}",
    }


_VALID_PLAN_REPLY = json.dumps({
    "groups": [
        {"role": "new", "name": "新客組", "ads": [
            {"name": "新客-廣告一", "coordinates": _coordinates("new1"),
             "scene": "上班族午休在辦公室滑手機找點心"},
            {"name": "新客-廣告二", "coordinates": _coordinates("new2"),
             "scene": "媽媽晚上哄睡小孩後在客廳看手機"},
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
        # F48 Contract C: 600 a day at cap 300 carries 1 ad + 1 explore = the two planned ads.
        campaign = {
            "name": "測試 Campaign", "goal_text": "幫新品衝第一波購買",
            "objective": "購買", "target_cost": 300,
            "start_date": "2026-10-01", "end_date": "2026-10-14", "status": "draft",
            "budget_planned": 8400, "budget_scenario": "recommended",
            "budget_basis_json": {"strategy": {"allocation": allocation}},
            "context_json": {"product_ids": product_ids or []},
        }
        row = ads_repo.create_campaign(web.conn, self.org_id, self.brand_id, campaign,
                                        created_by=ACTOR)
        plan.PROVIDER = _fake(_VALID_PLAN_REPLY)
        revision = bind_fixture(
            web.conn, self.org_id, self.brand_id, row["id"], json.loads(_VALID_PLAN_REPLY)
        )
        return plan.adopt_strategy(web.conn, self.org_id, self.brand_id, row["id"], actor=ACTOR,
                                  expected_revision=revision, operation_id=f"assets-{row['id']}")

    def _direct_campaign(self, *, campaign_start, campaign_end, group_role: str = "new",
                          group_start=None, group_end=None,
                          format_key: str | None = "single_image",
                          offer_key: str | None = None):
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
        if offer_key is not None:
            coordinates["offer"] = offer_key
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

    def _assign_confirmed(self, campaign_id: str, ad_id: str) -> None:
        """Bind a confirmed brand original to the planned ad (the launch batch's "ready")."""
        asset = coredb.new_id("aua")
        web.conn.execute(
            "INSERT INTO ads_user_asset(id,org_id,brand_id,sha256,storage_key,filename,"
            "mime_type,byte_size,status) VALUES(%s,%s,%s,%s,%s,'a.png','image/png',1,'ready')",
            (asset, self.org_id, self.brand_id, asset, f"{self.org_id}/{asset}"),
        )
        placement = user_assets.attach(
            web.conn, self.org_id, self.brand_id, campaign_id, asset,
            {"headline": "標題", "body": "文案", "description": "說明"}, ACTOR,
        )
        web.conn.execute(
            "UPDATE ads_asset_placement SET confirmed_at=now(),confirmed_by=%s WHERE id=%s",
            (ACTOR, placement["id"]),
        )
        web.conn.commit()
        handoff_assignment.assign(
            web.conn, self.org_id, self.brand_id, campaign_id, ad_id, placement["id"], 1,
        )


# -- 案例 1：交棒建一個 pack、一支廣告一個 set，摘要的「情境」是一句非空的話 --------------------

class CreativeBriefContractTest(AssetsTestBase):
    def test_display_projection_cannot_change_the_stored_accepted_identity(self):
        campaign = self._adopted_campaign()
        decision = campaign["budget_basis_json"]["strategy"]["decision"]
        original = ads_repo.campaign_detail

        def displayed(*args):
            detail = original(*args)
            detail["budget_basis_json"]["strategy"]["decision"] = {
                "state": "modified",
                "revision": "display-only-label-version",
                "receipt": {"revision": "display-only-receipt"},
            }
            return detail

        with mock.patch.object(assets.ads_repo, "campaign_detail", side_effect=displayed):
            creative = self._dispatched_set(campaign["id"])["request"]["creative_brief"]
        self.assertEqual(creative["provenance"]["current_revision"], decision["revision"])
        self.assertEqual(creative["provenance"]["accepted_receipt"], decision["receipt"])
        self.assertTrue(creative["test_intent"])

    def test_calendar_comparison_uses_this_delivery_groups_window(self):
        campaign, group, ad = self._direct_campaign(
            campaign_start="2026-10-01",
            campaign_end="2026-10-31",
            group_start="2026-10-01",
            group_end="2026-10-07",
        )
        ctx = {
            "product": None,
            "learnings": {"ads": [], "ranked": {"campaigns": []}},
            "calendar_evidence": [
                {"id": "in-window", "start": "2026-10-02", "end": "2026-10-02"},
                {"id": "later-event", "start": "2026-10-10", "end": "2026-10-10"},
            ],
        }
        creative = assets.creative_brief(
            ad, group, campaign, assets.planner_context.creative_basis(ctx)
        )
        self.assertEqual([e["id"] for e in creative["comparison"]["calendar"]], ["in-window"])
        self.assertEqual(creative["comparison"]["omitted"]["calendar_outside_window"], 1)
        self.assertEqual(
            creative["comparison"]["calendar_window"], {"start": "2026-10-01", "end": "2026-10-07"}
        )

    def test_calendar_partial_group_dates_fall_back_per_field_and_unknown_stays_unknown(self):
        events = [
            {"id": day, "start": day, "end": day}
            for day in ("2026-10-06", "2026-10-07", "2026-10-10", "2026-10-14", "2026-10-15")
        ]
        cases = (
            (
                "2026-10-10",
                None,
                "2026-10-07",
                "2026-10-14",
                "2026-10-10",
                "2026-10-14",
                ["2026-10-10", "2026-10-14"],
            ),
            (
                None,
                "2026-10-10",
                "2026-10-07",
                "2026-10-14",
                "2026-10-07",
                "2026-10-10",
                ["2026-10-07", "2026-10-10"],
            ),
            (
                None,
                None,
                "2026-10-07",
                "2026-10-14",
                "2026-10-07",
                "2026-10-14",
                ["2026-10-07", "2026-10-10", "2026-10-14"],
            ),
            (None, None, None, None, None, None, []),
        )
        for group_start, group_end, campaign_start, campaign_end, start, end, eligible in cases:
            with self.subTest(
                group_start=group_start,
                group_end=group_end,
                campaign_start=campaign_start,
                campaign_end=campaign_end,
            ):
                campaign, group, ad = self._direct_campaign(
                    campaign_start=campaign_start,
                    campaign_end=campaign_end,
                    group_start=group_start,
                    group_end=group_end,
                )
                basis = assets.planner_context.creative_basis(
                    {
                        "product": None,
                        "learnings": {"ads": [], "ranked": {"campaigns": []}},
                        "calendar_evidence": events,
                    }
                )
                comparison = assets.creative_brief(ad, group, campaign, basis)["comparison"]
                self.assertEqual(comparison["calendar_window"], {"start": start, "end": end})
                self.assertEqual([e["id"] for e in comparison["calendar"]], eligible)
                self.assertEqual(
                    comparison["omitted"]["calendar_outside_window"], len(events) - len(eligible)
                )

    def test_public_dispatch_calendar_note_matches_partial_group_comparison_window(self):
        for group_start, group_end, start, end, selected, excluded in (
            ("2026-10-12", None, "2026-10-12", "2026-10-14", "國高中第一次段考週", "國慶日"),
            (None, "2026-10-11", "2026-10-01", "2026-10-11", "國慶日", "國高中第一次段考週"),
        ):
            with self.subTest(group_start=group_start, group_end=group_end):
                campaign, _group, ad = self._direct_campaign(
                    campaign_start="2026-10-01",
                    campaign_end="2026-10-14",
                    group_start=group_start,
                    group_end=group_end,
                )
                response = self.client.post(
                    f"/api/ads/brands/{self.brand_id}/campaigns/{campaign['id']}/pack"
                )
                self.assertEqual(response.status_code, 200)
                self.assertTrue(response.json()["pack_id"])
                briefs = workbench.briefs_for_source(
                    web.conn,
                    self.org_id,
                    self.brand_id,
                    assets.PACK_SOURCE_KIND,
                    {"ads_campaign_id": campaign["id"]},
                )
                request = next(
                    b["request_json"] for b in briefs if b["source_ref"]["ads_ad_id"] == ad["id"]
                )
                comparison = request["creative_brief"]["comparison"]
                self.assertEqual(comparison["calendar_window"], {"start": start, "end": end})
                self.assertEqual([e["name"] for e in comparison["calendar"]], [selected])
                self.assertEqual(comparison["omitted"]["calendar_outside_window"], 1)
                self.assertIn(selected, request["calendar_note"])
                self.assertNotIn(excluded, request["calendar_note"])
                self.assertEqual(len(request["calendar_note"].splitlines()), 1)

    def _wait_for_blocked_writer(self, pid):
        until = time.monotonic() + 5
        while time.monotonic() < until:
            n = web.conn.execute(
                "SELECT cardinality(pg_blocking_pids(%s)) AS n", (pid,)
            ).fetchone()["n"]
            if n:
                return
            time.sleep(0.01)
        self.fail("The real competing writer did not wait on the dispatch locks")

    def test_real_writers_wait_until_coherent_pack_is_committed(self):
        for kind in ("ad_edit", "group_edit", "ad_insert", "group_insert"):
            with self.subTest(kind=kind):
                campaign = self._adopted_campaign()
                detail = ads_repo.campaign_detail(
                    web.conn, self.org_id, self.brand_id, campaign["id"]
                )
                group = detail["groups"][0]
                ad = group["ads"][0]
                web.conn.commit()
                initial = ads_repo.dispatch_snapshot(
                    web.conn, self.org_id, self.brand_id, campaign["id"]
                )
                started = threading.Event()
                writer_pid = []

                def write(
                    kind=kind,
                    campaign=campaign,
                    group=group,
                    ad=ad,
                    writer_pid=writer_pid,
                    started=started,
                ):
                    with coredb.connection() as conn:
                        writer_pid.append(
                            conn.execute("SELECT pg_backend_pid() AS pid").fetchone()["pid"]
                        )
                        started.set()
                        if kind == "ad_edit":
                            plan.update_ad(
                                conn,
                                self.org_id,
                                self.brand_id,
                                ad["id"],
                                {"coordinates": {"angle": "after-dispatch"}},
                                actor=ACTOR,
                            )
                        elif kind == "group_edit":
                            plan.update_group(
                                conn,
                                self.org_id,
                                self.brand_id,
                                group["id"],
                                {"role": "explore"},
                                actor=ACTOR,
                            )
                        elif kind == "ad_insert":
                            ads_repo.create_ad(
                                conn,
                                self.org_id,
                                self.brand_id,
                                campaign["id"],
                                group["id"],
                                name="Later ad",
                                coordinates={},
                                coordinates_snapshot={},
                            )
                        else:
                            ads_repo.create_group(
                                conn,
                                self.org_id,
                                self.brand_id,
                                campaign["id"],
                                channel_key="meta",
                                name="Later group",
                                role="explore",
                                daily_budget=1,
                            )

                with ThreadPoolExecutor(max_workers=1) as pool:
                    pending = pool.submit(write)
                    try:
                        self.assertTrue(started.wait(5))
                        self._wait_for_blocked_writer(writer_pid[0])
                        self.assertFalse(pending.done())
                        with mock.patch.object(
                            assets.workbench, "submit_pack", wraps=assets.workbench.submit_pack
                        ) as submit:
                            assets.dispatch_pack(
                                web.conn, self.org_id, self.brand_id, campaign["id"]
                            )
                        prepared = submit.call_args.args[-1]["sets"]
                        self.assertEqual(len(prepared), len(initial["groups"][0]["ads"]))
                        own = next(s for s in prepared if s["source_ref"]["ads_ad_id"] == ad["id"])
                        self.assertEqual(
                            own["request"]["creative_brief"]["assignment"]["role"], group["role"]
                        )
                        self.assertEqual(own["coordinates"]["angle"], ad["angle_key"])
                        self.assertEqual(
                            own["request"]["creative_brief"]["provenance"]["current_revision"],
                            campaign["budget_basis_json"]["strategy"]["decision"]["revision"],
                        )
                    finally:
                        web.conn.rollback()
                    pending.result(timeout=5)

    def test_lock_refusal_preserves_caller_work_and_allows_reload_retry(self):
        campaign = self._adopted_campaign()
        detail = ads_repo.campaign_detail(web.conn, self.org_id, self.brand_id, campaign["id"])
        ad = detail["groups"][0]["ads"][0]
        other, _, _ = self._direct_campaign(campaign_start="2026-10-01", campaign_end="2026-10-02")
        ads_repo.update_campaign(
            web.conn, self.org_id, self.brand_id, other["id"], {"name": "Caller work"}
        )
        ready, release = threading.Event(), threading.Event()

        def hold_edit():
            with coredb.connection() as conn:
                plan.update_ad(
                    conn,
                    self.org_id,
                    self.brand_id,
                    ad["id"],
                    {"coordinates": {"angle": "completed-edit"}},
                    actor=ACTOR,
                )
                ready.set()
                if not release.wait(5):
                    raise AssertionError("Writer release was not received")

        with ThreadPoolExecutor(max_workers=1) as pool:
            pending = pool.submit(hold_edit)
            try:
                self.assertTrue(ready.wait(5))
                with mock.patch.object(assets.workbench, "submit_pack") as submit:
                    with self.assertRaisesRegex(ValueError, "campaign_changed"):
                        assets.dispatch_pack(web.conn, self.org_id, self.brand_id, campaign["id"])
                    submit.assert_not_called()
                self.assertIsNone(
                    assets.pack_id(web.conn, self.org_id, self.brand_id, campaign["id"])
                )
                self.assertEqual(
                    ads_repo.get_campaign(web.conn, self.org_id, self.brand_id, other["id"])[
                        "name"
                    ],
                    "Caller work",
                )
            finally:
                release.set()
            pending.result(timeout=5)
        prepared = self._dispatched_set(campaign["id"])
        self.assertEqual(prepared["request"]["creative_brief"]["provenance"]["state"], "modified")
        self.assertEqual(
            ads_repo.get_campaign(web.conn, self.org_id, self.brand_id, other["id"])["name"],
            "Caller work",
        )

    def test_public_dispatch_collision_returns_reload_reason_without_a_pack(self):
        campaign = self._adopted_campaign()
        with mock.patch.object(
            assets.ads_repo, "dispatch_snapshot", side_effect=ValueError("campaign_changed")
        ):
            response = self.client.post(
                f"/api/ads/brands/{self.brand_id}/campaigns/{campaign['id']}/pack"
            )
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["error"]["code"], "campaign_changed")
        self.assertIn("重新載入", response.json()["error"]["message"])
        self.assertIsNone(assets.pack_id(web.conn, self.org_id, self.brand_id, campaign["id"]))

    def test_accepted_receipt_and_slot_survive_dispatch_and_readback(self):
        campaign = self._adopted_campaign()
        decision = campaign["budget_basis_json"]["strategy"]["decision"]
        receipt = decision["receipt"]
        dispatched = self._dispatched_set(campaign["id"])
        creative = dispatched["request"]["creative_brief"]
        self.assertEqual(creative["provenance"]["accepted_receipt"], receipt)
        self.assertEqual(creative["provenance"]["current_revision"], decision["revision"])
        self.assertEqual(creative["provenance"]["slot_id"], receipt["slots"][0]["slot_id"])
        self.assertEqual(creative["assignment"]["ad_id"], dispatched["source_ref"]["ads_ad_id"])
        self.assertTrue(creative["test_intent"])
        briefs = workbench.briefs_for_source(
            web.conn,
            self.org_id,
            self.brand_id,
            assets.PACK_SOURCE_KIND,
            {"ads_campaign_id": campaign["id"]},
        )
        own = next(
            b
            for b in briefs
            if b["source_ref"]["ads_ad_id"] == dispatched["source_ref"]["ads_ad_id"]
        )
        self.assertEqual(own["request_json"]["creative_brief"], creative)

    def test_modified_arrangement_keeps_receipt_but_expires_old_intent(self):
        campaign = self._adopted_campaign()
        detail = ads_repo.campaign_detail(web.conn, self.org_id, self.brand_id, campaign["id"])
        ad = detail["groups"][0]["ads"][0]
        plan.update_ad(
            web.conn,
            self.org_id,
            self.brand_id,
            ad["id"],
            {"coordinates": {"angle": "current-buyer-test"}},
            actor=ACTOR,
        )
        creative = self._dispatched_set(campaign["id"])["request"]["creative_brief"]
        self.assertEqual(creative["provenance"]["state"], "modified")
        self.assertNotEqual(
            creative["provenance"]["current_revision"],
            creative["provenance"]["accepted_receipt"]["revision"],
        )
        self.assertEqual(creative["assignment"]["coordinates"]["angle"], "current-buyer-test")
        self.assertIsNone(creative["test_intent"])
        self.assertTrue(creative["expired_reason"])

    def test_dispatch_rejects_an_edit_between_campaign_and_structure_reads(self):
        campaign = self._adopted_campaign()
        read_detail = ads_repo.campaign_detail

        def edit_before_detail(*args):
            detail = read_detail(*args)
            ad = detail["groups"][0]["ads"][0]
            plan.update_ad(
                web.conn,
                self.org_id,
                self.brand_id,
                ad["id"],
                {"coordinates": {"angle": "concurrent-test"}},
                actor=ACTOR,
            )
            return read_detail(*args)

        with mock.patch.object(assets.ads_repo, "campaign_detail", side_effect=edit_before_detail):
            with mock.patch.object(assets.workbench, "submit_pack") as submit:
                with self.assertRaisesRegex(ValueError, "campaign_changed"):
                    assets.dispatch_pack(web.conn, self.org_id, self.brand_id, campaign["id"])
                submit.assert_not_called()


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
        # F30-I16: an approved pack is progress, not launchable material -- the launch batch
        # would defer both ads, so 下一步 must not say 素材都就位了.
        self.assertEqual(summary, {"ready_count": 0, "total": 2, "pack_id": pack_id})

        ad_ids = [row["ad_id"] for row in after]
        self._assign_confirmed(campaign["id"], ad_ids[0])
        bound = assets.readiness(web.conn, self.org_id, self.brand_id, campaign["id"])
        self.assertEqual(
            {row["ad_id"]: row["material_ready"] for row in bound},
            {ad_ids[0]: True, ad_ids[1]: False},
        )
        self.assertEqual(
            assets.readiness_summary(bound, current_pack_id),
            {"ready_count": 1, "total": 2, "pack_id": pack_id},
        )


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
        # F30-I16: the tick records progress; without a confirmed material it is not ready.
        self.assertIs(row["material_ready"], False)
        self.assertEqual(assets.readiness_summary(rows, None)["ready_count"], 0)
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


# -- F45 §6.49: a photo-only brand's sets need no image prompt -----------------------------------

class PhotoOnlyBrandSetsRequireOnlyCopyTest(AssetsTestBase):
    def _set_for(self, media: str | None, format_key: str | None) -> dict:
        if media is not None:
            bi_repo.set_media_capability(web.conn, self.brand_id, media, actor=ACTOR)
            web.conn.commit()
        campaign_row, _group, _ad = self._direct_campaign(
            campaign_start="2026-10-01", campaign_end="2026-10-07", format_key=format_key,
        )
        return self._dispatched_set(campaign_row["id"])

    def test_photo_only_single_image_and_carousel_sets_require_only_copy(self):
        for format_key in ("single_image", "carousel", None):
            with self.subTest(format_key=format_key):
                target_set = self._set_for("photo", format_key)
                self.assertEqual(target_set["required_outputs"], {"copy": 1})

    def test_photo_only_set_is_accepted_by_the_workbench(self):
        bi_repo.set_media_capability(web.conn, self.brand_id, "photo", actor=ACTOR)
        web.conn.commit()
        campaign_row, _group, ad = self._direct_campaign(
            campaign_start="2026-10-01", campaign_end="2026-10-07", format_key="single_image",
        )
        assets.dispatch_pack(web.conn, self.org_id, self.brand_id, campaign_row["id"])
        briefs = workbench.briefs_for_source(
            web.conn, self.org_id, self.brand_id, assets.PACK_SOURCE_KIND,
            {"ads_campaign_id": campaign_row["id"], "ads_ad_id": ad["id"]},
        )
        self.assertEqual(len(briefs), 1)
        self.assertEqual(briefs[0]["request_json"]["parts"], ["copy"])

    def test_photo_video_and_unasked_brands_still_require_the_image_prompt(self):
        for media in (None, "photo_video"):  # never asked first: the brand starts unasked
            with self.subTest(media=media):
                target_set = self._set_for(media, "single_image")
                self.assertEqual(
                    target_set["required_outputs"], {"copy": 1, "image_prompt": 1}
                )


# -- F38 decision 3：限時限量的截止日＝投放組（否則 Campaign）的結束日 ----------------------

class OfferDeadlineTest(AssetsTestBase):
    def test_limited_time_ad_carries_the_campaign_end_date(self):
        campaign_row, _group, _ad = self._direct_campaign(
            campaign_start="2026-10-01", campaign_end="2026-10-14", offer_key="limited_time",
        )
        request = self._dispatched_set(campaign_row["id"])["request"]
        self.assertEqual(request["offer_deadline"], "2026-10-14")

    def test_group_end_date_wins_over_campaign_end_date(self):
        campaign_row, _group, _ad = self._direct_campaign(
            campaign_start="2026-10-01", campaign_end="2026-10-30",
            group_start="2026-10-01", group_end="2026-10-07", offer_key="limited_time",
        )
        request = self._dispatched_set(campaign_row["id"])["request"]
        self.assertEqual(request["offer_deadline"], "2026-10-07")

    def test_other_offers_carry_no_deadline(self):
        for offer_key in ("none", None):
            with self.subTest(offer_key=offer_key):
                campaign_row, _group, _ad = self._direct_campaign(
                    campaign_start="2026-10-01", campaign_end="2026-10-14",
                    offer_key=offer_key,
                )
                request = self._dispatched_set(campaign_row["id"])["request"]
                self.assertNotIn("offer_deadline", request)

    def test_limited_time_without_any_end_date_carries_no_deadline(self):
        campaign_row, _group, _ad = self._direct_campaign(
            campaign_start=None, campaign_end=None, offer_key="limited_time",
        )
        request = self._dispatched_set(campaign_row["id"])["request"]
        self.assertNotIn("offer_deadline", request)


# -- F39-I03（outcome 3／4）：情境與行事曆走 request 進工作檯工單 ----------------------------

class SceneAndCalendarNoteTest(AssetsTestBase):
    _NATIONAL_DAY_LINE = "- 10/09～10/11 國慶日（假日）"
    _DOUBLE_11_LINE = "- 11/01～11/11 雙 11 檔（檔期）：概略檔期，各校／各平台不同"

    def _sets_by_name(self, campaign_id: str) -> dict:
        with mock.patch.object(
            assets.workbench, "submit_pack", wraps=assets.workbench.submit_pack,
        ) as submit_pack:
            assets.dispatch_pack(web.conn, self.org_id, self.brand_id, campaign_id)
        return {s["name"]: s for s in submit_pack.call_args.args[-1]["sets"]}

    def test_adopted_ads_hand_their_scene_and_the_calendar_to_the_brief(self):
        campaign = self._adopted_campaign()  # 2026-10-01～10-14 covers 國慶日
        sets = self._sets_by_name(campaign["id"])
        self.assertEqual(
            sets["新客-廣告一"]["request"]["scene"], "上班族午休在辦公室滑手機找點心",
        )
        self.assertEqual(
            sets["新客-廣告二"]["request"]["scene"], "媽媽晚上哄睡小孩後在客廳看手機",
        )
        for s in sets.values():
            self.assertIn(self._NATIONAL_DAY_LINE, s["request"]["calendar_note"].split("\n"))

    def test_campaign_inside_a_calendar_row_gets_that_line(self):
        campaign_row, _group, _ad = self._direct_campaign(
            # Ends 10-11: from 10-12 the 國高中第一次段考週 row (F46) overlaps too.
            campaign_start="2026-10-08", campaign_end="2026-10-11",
        )
        request = self._dispatched_set(campaign_row["id"])["request"]
        self.assertEqual(request["calendar_note"], self._NATIONAL_DAY_LINE)
        self.assertNotIn("scene", request)  # hand-made ad: no scene, no key

    def test_group_window_wins_over_the_campaign_window(self):
        campaign_row, _group, _ad = self._direct_campaign(
            campaign_start="2026-10-01", campaign_end="2026-11-30",
            group_start="2026-11-01", group_end="2026-11-05",
        )
        request = self._dispatched_set(campaign_row["id"])["request"]
        self.assertEqual(request["calendar_note"], self._DOUBLE_11_LINE)

    def test_bound_customer_group_rides_the_request_and_a_gone_group_is_omitted(self):
        """F46-I01 (Contract A): an ad bound to a customer group hands
        「〈who〉｜煩惱：〈labels〉｜顧客會說：〈quote〉｜什麼時候用：〈when〉」
        (missing parts omitted); no group, or an id that no longer resolves, leaves the key
        out."""
        product = bi_repo.create_product(web.conn, self.brand_id, name="夜跑背心", actor=ACTOR)
        groups = bi_repo.save_customer_groups(web.conn, self.brand_id, product["id"], [
            {"who": "下班後夜跑的上班族", "pain_keys": ["uncertainty"],
             "quote": "晚上跑步車子看不到我", "when_used": "下班後在河濱夜跑"},
            {"who": "帶小孩散步的爸媽", "pain_keys": ["effort"]},
        ], actor=ACTOR)
        campaign_row, group, ad = self._direct_campaign(
            campaign_start="2026-07-20", campaign_end="2026-07-25",
        )
        ads_repo.update_campaign(web.conn, self.org_id, self.brand_id, campaign_row["id"],
                                 {"product_ids": [product["id"]]})
        coordinates = {"format": "single_image"}
        for name, group_id in (("全的", groups[0]["id"]), ("缺的", groups[1]["id"]),
                               ("刪掉的", "pcg_gone")):
            ads_repo.create_ad(
                web.conn, self.org_id, self.brand_id, campaign_row["id"], group["id"],
                name=name, coordinates=coordinates, coordinates_snapshot={},
                customer_group_id=group_id,
            )
        web.conn.commit()

        sets = self._sets_by_name(campaign_row["id"])

        self.assertEqual(
            sets["全的"]["request"]["customer_group"],
            "下班後夜跑的上班族｜煩惱：怕買錯｜顧客會說：晚上跑步車子看不到我"
            "｜什麼時候用：下班後在河濱夜跑",
        )
        missing = sets["缺的"]["request"]["customer_group"]
        self.assertTrue(missing.startswith("帶小孩散步的爸媽｜煩惱："), missing)
        self.assertNotIn("顧客會說", missing)
        self.assertNotIn("什麼時候用", missing)
        self.assertNotIn("customer_group", sets["刪掉的"]["request"])
        self.assertNotIn("customer_group", sets[ad["name"]]["request"])  # hand-made, no group

    def test_quiet_window_or_no_dates_omits_the_note(self):
        for start, end in (("2026-07-20", "2026-07-25"), (None, None)):
            with self.subTest(start=start, end=end):
                campaign_row, _group, _ad = self._direct_campaign(
                    campaign_start=start, campaign_end=end,
                )
                request = self._dispatched_set(campaign_row["id"])["request"]
                self.assertNotIn("calendar_note", request)


if __name__ == "__main__":
    unittest.main()
