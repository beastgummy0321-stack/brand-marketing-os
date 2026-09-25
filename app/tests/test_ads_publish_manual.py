"""app/tests/test_ads_publish_manual.py — F03-I09 falsifiers (Meta faked at the `graph`
boundary, the way `app/tools/simulate_meta_spend.py` does it — only the outermost network call
is replaced, `app/ads/adapters/manual.py` and `app/meta/repository.py`'s name-lookup functions
run for real): with no bound account the bind result is exactly the no-account message and
nothing else; a campaign node that does not match means no group or ad is compared and the
message says so; with the campaign matched and two of three group names matching, the two are
bound, the third is named in the message, and the campaign stays `ready`; when all match the
campaign is `live` and there is one `bind` action per row (campaign node included); `auto_meta`
returns 未接上 without raising a 500; the checklist contains the campaign node plus every group
and ad name exactly once; one manual publish writes exactly one `approval` row with
`scope_type = plan.APPROVAL_SCOPE_TYPE`, `scope_ref` = the campaign id and `max_daily_amount` =
the group daily sum, and it still does so for a campaign with no dates; after publishing
campaign A, a group budget edit on campaign B of the same brand is judged by B's own approval
(or by none), never by A's.
"""

import json
import unittest
import uuid
from unittest import mock

import app.shared.web as web
from app.ads import (
    adapters,
    assets,
    change_control_data,
    change_control_launch,
    handoff_assignment,
    plan,
    routes,
)
from app.ads import repository as ads_repo
from app.ads import user_assets_repository as user_assets
from app.ads.adapters import manual as manual_adapter
from app.brand_intelligence import repository as bi_repo
from app.core import approval as approval_mod
from app.core import db as coredb
from app.llm import providers
from app.meta import graph as meta_graph
from app.meta import repository as meta_repo

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
        ]},
        {"role": "retarget", "name": "再行銷組", "ads": [
            {"name": "再行銷-廣告一", "coordinates": _coordinates("rt1")},
        ]},
        {"role": "explore", "name": "探索組", "ads": [
            {"name": "探索-廣告一", "coordinates": _coordinates("ex1")},
        ]},
    ],
}, ensure_ascii=False)


class PublishTestBase(unittest.TestCase):
    def setUp(self):
        self.org_id = coredb.DEV_ORG_ID
        self.brand = bi_repo.create_brand(
            web.conn, org_id=self.org_id, name="測試品牌：投放中心發布", client_name=None,
            actor=ACTOR,
        )
        self.brand_id = self.brand["id"]
        self._orig_provider = plan.PROVIDER

    def tearDown(self):
        plan.PROVIDER = self._orig_provider

    def _publish_with_isolated_budget_evidence(self, campaign_id):
        content_hash = change_control_data.digest(change_control_launch.snapshot(
            web.conn, self.org_id, self.brand_id, campaign_id))
        with mock.patch.object(change_control_launch.month_budget, "preflight",
                               return_value={"can_increase": True}) as preflight:
            result = manual_adapter.publish(web.conn, self.org_id, self.brand_id, campaign_id,
                actor=ACTOR, operation_id=str(uuid.uuid4()), content_hash=content_hash)
        self.assertEqual(preflight.call_args.args[4][0]["kind"], "launch")
        return result

    def _ready_material(self, detail: dict) -> dict:
        """A confirmed material on the first planned ad: a launch needs at least one ad whose
        material is ready (F30, `launch_no_ready_ads`)."""
        asset = coredb.new_id("aua")
        web.conn.execute(
            "INSERT INTO ads_user_asset(id,org_id,brand_id,sha256,storage_key,filename,"
            "mime_type,byte_size,status) VALUES(%s,%s,%s,%s,%s,'ad.png','image/png',1,'ready')",
            (asset, self.org_id, self.brand_id, asset, f"{self.org_id}/{asset}"),
        )
        placement = user_assets.attach(
            web.conn, self.org_id, self.brand_id, detail["id"], asset, {"body": "文案"}, ACTOR,
        )
        web.conn.execute(
            "UPDATE ads_asset_placement SET confirmed_at=now(),confirmed_by=%s WHERE id=%s",
            (ACTOR, placement["id"]),
        )
        web.conn.commit()
        handoff_assignment.assign(
            web.conn, self.org_id, self.brand_id, detail["id"],
            detail["groups"][0]["ads"][0]["id"], placement["id"], 1,
        )
        return detail

    def _create_campaign(self, *, start_date: str | None = "2026-10-01",
                          end_date: str | None = "2026-10-14",
                          budget_planned: float = 3000) -> dict:
        allocation = [
            {"role": "new", "label": "新客", "pct": 50, "rationale": None},
            {"role": "retarget", "label": "再行銷", "pct": 30, "rationale": None},
            {"role": "explore", "label": "探索", "pct": 20, "rationale": None},
        ]
        campaign = {
            "name": "測試 Campaign", "goal_text": "幫產品衝購買",
            "objective": "購買", "target_cost": 300,
            "start_date": start_date, "end_date": end_date, "status": "draft",
            "budget_planned": budget_planned, "budget_scenario": "recommended",
            "budget_basis_json": {"strategy": {"allocation": allocation}},
        }
        return ads_repo.create_campaign(web.conn, self.org_id, self.brand_id, campaign,
                                         created_by=ACTOR)

    def _adopted_campaign(self, **kwargs) -> dict:
        """`draft` -> `ready`，3 個投放組各一支廣告（跟 `test_ads_plan.py` 同一份假回覆）。"""
        campaign = self._create_campaign(**kwargs)
        plan.PROVIDER = _fake(_VALID_PLAN_REPLY)
        return plan.adopt_strategy(
            web.conn, self.org_id, self.brand_id, campaign["id"], actor=ACTOR,
        )

    def _connect_account(self) -> str:
        """跟 `test_schedule.py::BindTreeApiContractTest._connect_account` 同一套：接權杖、
        掛一個假帳號、把它綁進這個品牌。回傳平台端的帳號 id（`graph` 假函式要用它當
        `account_id` 參數）。"""
        meta_repo.save_token(web.conn, self.org_id, "tok")
        external_id = f"act_{uuid.uuid4().hex[:10]}"
        meta_repo.upsert_accounts(web.conn, self.org_id, [
            {"account_id": external_id, "name": "測試廣告帳號", "currency": "TWD"},
        ])
        row = next(a for a in meta_repo.list_accounts(web.conn, self.org_id)
                   if a["account_id"] == external_id)
        meta_repo.bind(web.conn, self.org_id, self.brand_id, row["id"])
        web.conn.commit()
        return external_id

    def _actions(self, campaign_id: str) -> list:
        rows = web.conn.execute(
            "SELECT * FROM ads_action WHERE campaign_id = %s ORDER BY created_at", (campaign_id,),
        ).fetchall()
        return [dict(r) for r in rows]

    def _approvals(self, campaign_id: str) -> list:
        rows = web.conn.execute(
            "SELECT * FROM approval WHERE scope_type = %s AND scope_ref = %s",
            (plan.APPROVAL_SCOPE_TYPE, campaign_id),
        ).fetchall()
        return [dict(r) for r in rows]

    def _patch_campaigns(self, by_account: dict):
        def fake_list_campaigns(_token: str, account_id: str) -> list:
            return [
                {"campaign_id": cid, "name": name, "effective_status": "ACTIVE"}
                for cid, name in by_account.get(account_id, [])
            ]
        return mock.patch.object(meta_graph, "list_campaigns", fake_list_campaigns)

    def _patch_ad_sets(self, by_campaign: dict):
        def fake_list_ad_sets(_token: str, campaign_id: str) -> list:
            return [
                {"adset_id": aid, "name": name, "external_status": "ACTIVE"}
                for aid, name in by_campaign.get(campaign_id, [])
            ]
        return mock.patch.object(meta_graph, "list_ad_sets", fake_list_ad_sets)

    def _patch_ads(self, by_adset: dict):
        def fake_list_ads(_token: str, adset_id: str) -> list:
            return [
                {"ad_id": aid, "name": name, "external_status": "ACTIVE"}
                for aid, name in by_adset.get(adset_id, [])
            ]
        return mock.patch.object(meta_graph, "list_ads", fake_list_ads)


class NoAccountBoundTest(PublishTestBase):
    def test_bind_with_no_bound_account_returns_the_guard_message_alone(self):
        detail = self._adopted_campaign()

        result = manual_adapter.bind(
            web.conn, self.org_id, self.brand_id, detail["id"], actor=ACTOR,
        )

        self.assertEqual(result["message"], manual_adapter.NO_ACCOUNT_BOUND_MESSAGE)
        self.assertEqual(self._actions(detail["id"]), [])
        self.assertEqual(result["campaign"]["local_state"], "unbound")


class CampaignNodeNotMatchedTest(PublishTestBase):
    def test_unmatched_campaign_node_stops_children_from_being_compared(self):
        detail = self._adopted_campaign()
        self._connect_account()

        with self._patch_campaigns({}):  # 平台上完全沒有叫這個名字的活動
            result = manual_adapter.bind(
                web.conn, self.org_id, self.brand_id, detail["id"], actor=ACTOR,
            )

        self.assertIn(f"「{detail['name']}」在 Meta 上找不到", result["message"])
        self.assertIn("名稱要一字不差", result["message"])
        self.assertEqual(result["campaign"]["local_state"], "unbound")
        for group in result["campaign"]["groups"]:
            self.assertEqual(group["local_state"], "unbound")
            for ad in group["ads"]:
                self.assertEqual(ad["local_state"], "unbound")
        self.assertEqual(self._actions(detail["id"]), [])


class PartialMatchTest(PublishTestBase):
    def test_two_of_three_groups_bind_the_third_is_named_campaign_stays_ready(self):
        detail = self._adopted_campaign()
        account_id = self._connect_account()
        campaign_ext = "camp-1"
        with self._patch_campaigns({account_id: [(campaign_ext, detail["name"])]}), \
                self._patch_ad_sets({
                    campaign_ext: [
                        ("as-new", "新客組"), ("as-retarget", "再行銷組"),
                    ],  # 探索組故意不放平台上，逼出零筆的那一種失敗
                }), \
                self._patch_ads({
                    "as-new": [("ad-new", "新客-廣告一")],
                    "as-retarget": [("ad-retarget", "再行銷-廣告一")],
                }):
            result = manual_adapter.bind(
                web.conn, self.org_id, self.brand_id, detail["id"], actor=ACTOR,
            )

        self.assertIn("「探索組」在 Meta 上找不到", result["message"])
        self.assertEqual(result["campaign"]["status"], "ready")

        reloaded_groups = {g["name"]: g for g in result["campaign"]["groups"]}
        self.assertEqual(reloaded_groups["新客組"]["local_state"], "bound")
        self.assertEqual(reloaded_groups["再行銷組"]["local_state"], "bound")
        self.assertEqual(reloaded_groups["探索組"]["local_state"], "unbound")
        self.assertEqual(reloaded_groups["新客組"]["ads"][0]["local_state"], "bound")
        self.assertEqual(reloaded_groups["再行銷組"]["ads"][0]["local_state"], "bound")
        self.assertEqual(reloaded_groups["探索組"]["ads"][0]["local_state"], "unbound")


class FullMatchTest(PublishTestBase):
    def test_all_matched_goes_live_with_one_bind_action_per_row(self):
        detail = self._adopted_campaign()
        account_id = self._connect_account()
        campaign_ext = "camp-1"

        with self._patch_campaigns({account_id: [(campaign_ext, detail["name"])]}), \
                self._patch_ad_sets({
                    campaign_ext: [
                        ("as-new", "新客組"), ("as-retarget", "再行銷組"), ("as-explore", "探索組"),
                    ],
                }), \
                self._patch_ads({
                    "as-new": [("ad-new", "新客-廣告一")],
                    "as-retarget": [("ad-retarget", "再行銷-廣告一")],
                    "as-explore": [("ad-explore", "探索-廣告一")],
                }):
            result = manual_adapter.bind(
                web.conn, self.org_id, self.brand_id, detail["id"], actor=ACTOR,
            )

        self.assertIsNone(result["message"])
        self.assertEqual(result["campaign"]["status"], "live")

        actions = self._actions(detail["id"])
        bind_actions = [a for a in actions if a["kind"] == "bind"]
        # campaign 節點 + 3 個投放組 + 3 支廣告 = 7 列，一列不多一列不少。
        self.assertEqual(len(bind_actions), 7)
        self.assertEqual(len({a["target_id"] for a in bind_actions}), 7)


class ChecklistContentTest(PublishTestBase):
    def test_checklist_names_every_node_exactly_once(self):
        detail = self._adopted_campaign()

        described = manual_adapter.describe(detail)

        names = [node["name"] for node in described["checklist"]]
        expected = {detail["name"]}
        for group in detail["groups"]:
            expected.add(group["name"])
            for ad in group["ads"]:
                expected.add(ad["name"])
        self.assertEqual(set(names), expected)
        self.assertEqual(len(names), len(set(names)))
        self.assertEqual(described["checklist"][0]["level"], "campaign")


class AutoMetaAdapterTest(PublishTestBase):
    def test_auto_meta_describes_not_connected_without_raising(self):
        detail = self._adopted_campaign()
        auto_meta = adapters.get_adapter("auto_meta")

        described = auto_meta.describe(detail)
        self.assertEqual(described["message"], adapters.AUTO_META_NOT_CONNECTED_MESSAGE)

        with self.assertRaises(ValueError) as ctx:
            auto_meta.publish(web.conn, self.org_id, self.brand_id, detail["id"], actor=ACTOR)
        self.assertEqual(str(ctx.exception), "auto_meta_not_connected")

        with self.assertRaises(ValueError) as ctx:
            auto_meta.bind(web.conn, self.org_id, self.brand_id, detail["id"], actor=ACTOR)
        self.assertEqual(str(ctx.exception), "auto_meta_not_connected")


class PublishWritesOneApprovalTest(PublishTestBase):
    def test_missing_approval_hash_and_unknown_budget_cannot_bypass_new_boundary(self):
        detail = self._adopted_campaign()
        self._ready_material(detail)
        with self.assertRaisesRegex(ValueError, "重新檢視"):
            manual_adapter.publish(web.conn, self.org_id, self.brand_id, detail["id"], actor=ACTOR)
        content_hash = change_control_data.digest(change_control_launch.snapshot(
            web.conn, self.org_id, self.brand_id, detail["id"]))
        with self.assertRaisesRegex(ValueError, "餘額尚不確定"):
            manual_adapter.publish(web.conn, self.org_id, self.brand_id, detail["id"], actor=ACTOR,
                                   operation_id="unknown-budget", content_hash=content_hash)
        self.assertEqual(self._approvals(detail["id"]), [])
        self.assertEqual(self._actions(detail["id"]), [])

    def test_launch_lost_response_replays_same_atomic_approval_and_action(self):
        detail = self._adopted_campaign()
        self._ready_material(detail)
        content_hash = change_control_data.digest(change_control_launch.snapshot(
            web.conn, self.org_id, self.brand_id, detail["id"]))
        with mock.patch.object(change_control_launch.month_budget, "preflight", return_value={}):
            first = manual_adapter.publish(web.conn, self.org_id, self.brand_id, detail["id"],
                actor=ACTOR, operation_id="stable-launch", content_hash=content_hash)
            again = manual_adapter.publish(web.conn, self.org_id, self.brand_id, detail["id"],
                actor=ACTOR, operation_id="stable-launch", content_hash=content_hash)
        self.assertEqual(first, again)
        self.assertEqual(len(self._approvals(detail["id"])), 1)
        actions = self._actions(detail["id"])
        self.assertEqual(len(actions), 1)
        self.assertEqual(actions[0]["after_json"]["content_hash"], content_hash)
        self.assertEqual(actions[0]["after_json"]["operation_id"], "stable-launch")
        self.assertEqual(actions[0]["verification_state"], "pending")

    def test_one_manual_publish_writes_exactly_one_approval_row(self):
        detail = self._adopted_campaign()
        self._ready_material(detail)
        daily_sum = ads_repo.group_budget_total(web.conn, self.org_id, self.brand_id, detail["id"])

        self._publish_with_isolated_budget_evidence(detail["id"])

        rows = self._approvals(detail["id"])
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["scope_type"], plan.APPROVAL_SCOPE_TYPE)
        self.assertEqual(rows[0]["scope_ref"], detail["id"])
        self.assertEqual(float(rows[0]["max_daily_amount"]), daily_sum)

        publish_actions = [a for a in self._actions(detail["id"]) if a["kind"] == "publish"]
        self.assertEqual(len(publish_actions), 1)

    def test_publish_writes_an_approval_even_with_no_dates(self):
        # `plan.adopt_strategy` 本身要求日期才展開得出投放組（每日總額 = budget_planned /
        # 天數），所以「沒有排期的 Campaign」是採用之後才清掉日期——bound 之前
        # `local_state == 'unbound'`，PATCH 一路都能改日期（F03-I19 才凍結，見票面）。
        detail = self._adopted_campaign()
        self._ready_material(detail)
        ads_repo.update_campaign(
            web.conn, self.org_id, self.brand_id, detail["id"],
            {"start_date": None, "end_date": None},
        )
        daily_sum = ads_repo.group_budget_total(web.conn, self.org_id, self.brand_id, detail["id"])
        reloaded = ads_repo.campaign_detail(web.conn, self.org_id, self.brand_id, detail["id"])
        self.assertIsNone(reloaded["budget_total"])

        self._publish_with_isolated_budget_evidence(detail["id"])

        rows = self._approvals(detail["id"])
        self.assertEqual(len(rows), 1)
        self.assertEqual(float(rows[0]["max_daily_amount"]), daily_sum)
        self.assertEqual(float(rows[0]["approved_amount"]), daily_sum)


class CrossCampaignApprovalTest(PublishTestBase):
    def test_campaign_bs_budget_edit_is_judged_by_bs_own_approval_not_as(self):
        campaign_a = self._ready_material(self._adopted_campaign())
        campaign_b = self._adopted_campaign()

        self._publish_with_isolated_budget_evidence(campaign_a["id"])
        approval_a = self._approvals(campaign_a["id"])[0]

        # B 從沒被核准過——A 的核准不該拿來判 B 的預算煞車（沒有核准就沒有煞車）。
        group_b = campaign_b["groups"][0]
        huge_raise = float(approval_a["max_daily_amount"]) + 1_000_000
        plan.update_group(
            web.conn, self.org_id, self.brand_id, group_b["id"],
            {"daily_budget": huge_raise}, actor=ACTOR,
        )  # 不該炸——B 沒有自己的核准，煞車是 inert 的

        reloaded_b = ads_repo.get_group(web.conn, self.org_id, self.brand_id, group_b["id"])
        self.assertEqual(float(reloaded_b["daily_budget"]), huge_raise)

        # 現在給 B 自己核准一個比較低的上限，同樣的加碼這次應該被拒絕。
        approval_mod.approve(
            web.conn, org_id=self.org_id, brand_id=self.brand_id,
            scope_type=plan.APPROVAL_SCOPE_TYPE, scope_ref=campaign_b["id"],
            content_hash=campaign_b["id"], amount=10, max_daily_amount=10, actor=ACTOR,
        )
        with self.assertRaises(ValueError) as ctx:
            plan.update_group(
                web.conn, self.org_id, self.brand_id, group_b["id"],
                {"daily_budget": huge_raise + 1}, actor=ACTOR,
            )
        self.assertEqual(str(ctx.exception), "budget_exceeds_approval")


class NoGroupsToPublishTest(PublishTestBase):
    def test_publish_with_no_groups_refuses_writes_nothing_and_group_creation_still_works(self):
        campaign = self._create_campaign()  # draft，`plan.adopt_strategy` 沒跑過，沒有投放組

        with self.assertRaises(ValueError) as ctx:
            manual_adapter.publish(
                web.conn, self.org_id, self.brand_id, campaign["id"], actor=ACTOR,
            )
        self.assertEqual(str(ctx.exception), "no_groups_to_publish")

        self.assertEqual(self._approvals(campaign["id"]), [])
        self.assertEqual(self._actions(campaign["id"]), [])

        group = plan.create_group(
            web.conn, self.org_id, self.brand_id, campaign["id"], name="補一個投放組",
            role="new", daily_budget=100,
        )
        self.assertEqual(group["name"], "補一個投放組")


class ClosedCampaignNotRevivedTest(PublishTestBase):
    def test_full_match_bind_on_a_closed_campaign_stays_closed(self):
        detail = self._adopted_campaign()
        ads_repo.set_campaign_status(
            web.conn, self.org_id, self.brand_id, detail["id"], "closed",
        )
        account_id = self._connect_account()
        campaign_ext = "camp-1"

        with self._patch_campaigns({account_id: [(campaign_ext, detail["name"])]}), \
                self._patch_ad_sets({
                    campaign_ext: [
                        ("as-new", "新客組"), ("as-retarget", "再行銷組"), ("as-explore", "探索組"),
                    ],
                }), \
                self._patch_ads({
                    "as-new": [("ad-new", "新客-廣告一")],
                    "as-retarget": [("ad-retarget", "再行銷-廣告一")],
                    "as-explore": [("ad-explore", "探索-廣告一")],
                }):
            result = manual_adapter.bind(
                web.conn, self.org_id, self.brand_id, detail["id"], actor=ACTOR,
            )

        self.assertIsNone(result["message"])
        self.assertEqual(result["campaign"]["status"], "closed")


# -- F07-I10：手動配對清單的圖片提示詞欄位讀 §5.8 的 `text`，不是舊的 `rendered` -------------

class ImagePromptTextOnManualChecklistTest(PublishTestBase):
    def test_explicit_material_assignment_replaces_legacy_copy_in_checklist(self):
        detail = self._adopted_campaign()
        ad = detail["groups"][0]["ads"][0]
        ad.update(copy_text="舊工作檯文案", image_prompt_text="舊生成提示詞",
                  material_assignment={"filename": "使用者選定.png", "placement_revision": 2,
                    "copy_fields": {"headline": "選定標題", "body": "實際投放文字"},
                    "assignment_status": "confirmed", "reason": None})
        node = next(n for n in manual_adapter.describe(detail)["checklist"] if n["id"] == ad["id"])
        fields = {f["label"]: f["value"] for f in node["fields"]}
        self.assertEqual(fields["指定素材檔案"], "使用者選定.png")
        self.assertEqual(fields["文案"], "實際投放文字")
        self.assertEqual(fields["標題"], "選定標題")
        self.assertNotIn("圖片提示詞", fields)

    def _dispatched_ad(self):
        detail = self._adopted_campaign()
        assets.dispatch_pack(web.conn, self.org_id, self.brand_id, detail["id"])
        ad = detail["groups"][0]["ads"][0]
        return detail, ad

    def _ad_field(self, enriched: dict, ad_id: str) -> dict:
        described = manual_adapter.describe(enriched)
        node = next(n for n in described["checklist"] if n["id"] == ad_id)
        return next((f for f in node["fields"] if f["label"] == "圖片提示詞"), None)

    def test_adopted_row_checklist_value_is_text_not_prompt(self):
        detail, ad = self._dispatched_ad()
        body = {"text": "品牌視覺規範：...\n風格規範：...", "prompt": "舊欄位不該被讀到"}

        def fake_adopted_output(_conn, _org_id, _brand_id, _brief_id, part):
            return {"body_json": body, "is_adopted": True} if part == "image_prompt" else None

        with mock.patch.object(routes.workbench, "adopted_output", fake_adopted_output):
            enriched = routes._enriched_campaign(web.conn, self.org_id, self.brand_id, detail["id"])

        field = self._ad_field(enriched, ad["id"])
        self.assertIsNotNone(field)
        self.assertEqual(field["value"], body["text"])

    def test_non_adopted_row_has_no_field(self):
        detail, ad = self._dispatched_ad()
        body = {"text": "還沒選定這張"}

        def fake_adopted_output(_conn, _org_id, _brand_id, _brief_id, part):
            return {"body_json": body, "is_adopted": False} if part == "image_prompt" else None

        with mock.patch.object(routes.workbench, "adopted_output", fake_adopted_output):
            enriched = routes._enriched_campaign(web.conn, self.org_id, self.brand_id, detail["id"])

        self.assertIsNone(self._ad_field(enriched, ad["id"]))

    def test_text_missing_or_not_a_string_has_no_field(self):
        detail, ad = self._dispatched_ad()
        for body in ({}, {"text": ["not", "a", "string"]}, {"text": ""}):
            with self.subTest(body=body):
                def fake_adopted_output(_conn, _org_id, _brand_id, _brief_id, part, body=body):
                    if part == "image_prompt":
                        return {"body_json": body, "is_adopted": True}
                    return None

                with mock.patch.object(routes.workbench, "adopted_output", fake_adopted_output):
                    enriched = routes._enriched_campaign(
                        web.conn, self.org_id, self.brand_id, detail["id"],
                    )
                self.assertIsNone(self._ad_field(enriched, ad["id"]))

    def test_old_rendered_shape_is_no_longer_read(self):
        detail, ad = self._dispatched_ad()
        body = {"rendered": "舊提示詞（F07 之前的欄位）"}

        def fake_adopted_output(_conn, _org_id, _brand_id, _brief_id, part):
            return {"body_json": body, "is_adopted": True} if part == "image_prompt" else None

        with mock.patch.object(routes.workbench, "adopted_output", fake_adopted_output):
            enriched = routes._enriched_campaign(web.conn, self.org_id, self.brand_id, detail["id"])

        self.assertIsNone(self._ad_field(enriched, ad["id"]))

    def test_no_adopted_output_has_no_field_and_does_not_crash(self):
        detail, ad = self._dispatched_ad()

        with mock.patch.object(routes.workbench, "adopted_output", lambda *a, **k: None):
            enriched = routes._enriched_campaign(web.conn, self.org_id, self.brand_id, detail["id"])

        self.assertIsNone(self._ad_field(enriched, ad["id"]))

    def test_copy_branch_is_unchanged(self):
        detail, ad = self._dispatched_ad()

        def fake_adopted_output(_conn, _org_id, _brand_id, _brief_id, part):
            if part == "copy":
                return {"body_json": {"sets": [{"body": "測試文案"}]}, "is_adopted": True}
            return None

        with mock.patch.object(routes.workbench, "adopted_output", fake_adopted_output):
            enriched = routes._enriched_campaign(web.conn, self.org_id, self.brand_id, detail["id"])

        described = manual_adapter.describe(enriched)
        node = next(n for n in described["checklist"] if n["id"] == ad["id"])
        field = next(f for f in node["fields"] if f["label"] == "文案")
        self.assertEqual(field["value"], "測試文案")


if __name__ == "__main__":
    unittest.main()
