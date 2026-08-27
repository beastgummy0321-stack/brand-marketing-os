# -*- coding: utf-8 -*-
"""T3 提案書組裝、核可與開檔管道計畫的可判定驗收。"""

import atexit
import json
import re
import shutil
import tempfile
import unittest
from unittest import mock

_tmpdir = tempfile.mkdtemp(prefix="brand_os_proposal_")

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

import app.main as main  # noqa: E402
from app.ads import proposal  # noqa: E402
from app.ads import plan as ads_plan  # noqa: E402
from app.ads import repository as ads_repo  # noqa: E402
from app.ads import repository_channel_plan as channel_repo  # noqa: E402
from app.ads import theme_repository  # noqa: E402
from app.ads import tracking as ads_tracking  # noqa: E402
from app.brand_intelligence import repository as bi_repo  # noqa: E402
from app.core import db as coredb  # noqa: E402
from app.core.db import new_id, now_utc  # noqa: E402


def _cleanup():
    try:
        main.conn.close()
    except Exception:
        pass
    shutil.rmtree(_tmpdir, ignore_errors=True)


atexit.register(_cleanup)
ACTOR = "測試員"
FORBIDDEN_WORDS = ("受眾", "漏斗", "CPA", "CTR", "CPC", "ROAS", "KPI")
# 掃術語前先把 id 拿掉：id 是 Crockford Base32 亂數（app/core/db.py:30），
# 「CPA」「CPC」「CTR」這些字母組合會隨機出現在 id 裡，讓斷言隨機變紅。
_ID_RE = re.compile(r"[a-z]+_[0-9A-HJKMNP-TV-Z]{26}")




class ProposalTest(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(main.app)
        self.brand = bi_repo.create_brand(
            main.conn, name=f"提案書測試品牌{abs(hash(self.id())) % 100000}", client_name=None, actor=ACTOR)
        self.bid = self.brand["id"]

    def _cycle(self):
        product = bi_repo.create_product(main.conn, self.bid, name="提案測試商品", actor=ACTOR)
        bi_repo.save_product_economics(
            main.conn, self.bid, product["id"], actor=ACTOR, selling_price=1000,
            unit_variable_cost=400, currency="TWD", confirmed_by=ACTOR,
        )
        cycle = ads_repo.create_cycle(
            main.conn, self.bid, product_ids=[product["id"]], pain_value=5000,
            objective="sales", actor=ACTOR)
        proposal.seed_channel_plans(main.conn, self.bid, cycle["id"])
        return cycle

    def _plan(self, cycle_id: str):
        plan = {
            "summary": "先用一個清楚方向開始", "difference": "",
            "audience": {"tiers": {}, "exclusions": []},
            "angles": [{"title": "商品亮點", "message": "說明商品能帶來的改變", "why": "先做基本測試",
                        "product_id": None}],
            "hypotheses": [], "grounding": {"facts": [], "inferences": [], "to_verify": []},
        }
        main.conn.execute(
            "INSERT INTO campaign_plan (id, org_id, campaign_cycle_id, brand_id, plan_version,"
            " plan_json, status, created_at) VALUES (%s, %s, %s, %s, 1, %s, 'draft', %s)",
            (new_id("cpl"), coredb.DEV_ORG_ID, cycle_id, self.bid, coredb.jsonb(plan), now_utc()),
        )
        main.conn.execute(
            "UPDATE campaign_cycle SET plan_version = 1, status = 'REVIEW' WHERE id = %s", (cycle_id,))
        main.conn.commit()

    def _theme(self, cycle_id: str):
        cell_id = new_id("exc")
        main.conn.execute(
            "INSERT INTO experiment_cell (id, org_id, campaign_cycle_id, brand_id,"
            " creative_angle, created_at) VALUES (%s, %s, %s, %s, '真實素材切角', %s)",
            (cell_id, coredb.DEV_ORG_ID, cycle_id, self.bid, now_utc()),
        )
        main.conn.commit()
        return theme_repository.create_theme(
            main.conn, self.bid, campaign_cycle_id=cycle_id, experiment_cell_id=cell_id,
            format_key="single_image", name="真實素材主題", folder_code="real-theme", actor=ACTOR,
            components=[{"component_type": "body", "content": "真實素材內容"}],
        )

    def test_ready_proposal_has_six_blocks_and_existing_fields(self):
        cycle = self._cycle()
        self._plan(cycle["id"])
        theme = self._theme(cycle["id"])
        expected_tracking = ads_tracking.tracking_health(main.conn, self.bid)

        response = self.client.get(f"/api/campaigns/brands/{self.bid}/cycles/{cycle['id']}/proposal")

        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertEqual(body["status"], "ready")
        self.assertEqual(set(body["blocks"]), {"channels", "budget", "creatives", "tracking", "brakes", "schedule"})
        self.assertEqual(len(body["blocks"]["channels"]), 5)
        self.assertEqual(set(body["blocks"]["budget"]), {"budget", "allocations", "forecast"})
        self.assertEqual(body["blocks"]["budget"]["budget"], cycle["budget"])
        self.assertIsInstance(body["blocks"]["budget"]["forecast"], str)
        self.assertIn("筆訂單", body["blocks"]["budget"]["forecast"])
        self.assertEqual(body["blocks"]["creatives"][0]["name"], theme["name"])
        self.assertEqual(body["blocks"]["creatives"][0]["components"][0]["content"], "真實素材內容")
        self.assertEqual(body["blocks"]["tracking"], expected_tracking)
        self.assertIn("NT$", body["blocks"]["brakes"][0])
        self.assertIn("前 3 到 7 天", body["blocks"]["schedule"])
        # 票 13：核可前多帶一個預估花費欄位，跟矩陣頁同一個 cost_ceiling 天花板，見
        # test_proposal_approve_progress.py::EstimatedCostMatchesMatrixTest 逐項驗證來源。
        self.assertEqual(body["approval"]["approved"], False)
        self.assertEqual(body["approval"]["warning"], None)
        self.assertIn("estimated_generation_cost", body["approval"])

    def test_missing_plan_is_assembling(self):
        cycle = self._cycle()

        body = self.client.get(f"/api/campaigns/brands/{self.bid}/cycles/{cycle['id']}/proposal").json()

        self.assertEqual(body["status"], "assembling")
        self.assertEqual(body["reason"], None)

    def test_block_error_is_failed_with_human_reason(self):
        cycle = self._cycle()
        self._plan(cycle["id"])
        with mock.patch.object(proposal.tracking, "tracking_health", side_effect=RuntimeError("boom")):
            body = proposal.proposal(main.conn, self.bid, cycle["id"])

        self.assertEqual(body["status"], "failed")
        self.assertIn("資料都還在", body["reason"])

    def test_plan_read_error_is_also_failed_with_human_reason(self):
        cycle = self._cycle()
        with mock.patch.object(proposal.ads_plan, "get_latest_plan", side_effect=RuntimeError("boom")):
            body = proposal.proposal(main.conn, self.bid, cycle["id"])

        self.assertEqual(body["status"], "failed")
        self.assertIn("資料都還在", body["reason"])

    def test_tracking_red_warns_but_approval_creates_only_enabled_non_social_cards(self):
        cycle = self._cycle()
        self._plan(cycle["id"])
        plans = channel_repo.list_channel_plans(main.conn, self.bid, cycle["id"])
        disabled = next(plan for plan in plans if plan["channel"] == "kol_media")
        channel_repo.update_channel_plan(
            main.conn, self.bid, disabled["id"], job=disabled["job"], pct=disabled["pct"],
            expected=disabled["expected"], enabled=False, depth=disabled["depth"])
        red_tracking = {"channels": [{"status": "bad"}], "ready": 0, "total": 1}
        with mock.patch.object(proposal.tracking, "tracking_health", return_value=red_tracking):
            self.assertIsNotNone(proposal.proposal(main.conn, self.bid, cycle["id"])["approval"]["warning"])

        cards = proposal.approve(main.conn, self.bid, cycle["id"], ACTOR)

        self.assertEqual(ads_repo.get_cycle(main.conn, self.bid, cycle["id"])["budget"], cycle["budget"])
        self.assertTrue(all(card["channel"] not in ("social", "kol_media") for card in cards))
        self.assertEqual({card["channel"] for card in cards}, {"google_search", "line_email", "website_landing"})

    def test_return_restores_opening_status_and_keeps_values(self):
        cycle = self._cycle()
        self._plan(cycle["id"])
        original_budget = cycle["budget"]
        proposal.approve(main.conn, self.bid, cycle["id"], ACTOR)

        proposal.return_to_opening(main.conn, self.bid, cycle["id"], ACTOR)

        after = ads_repo.get_cycle(main.conn, self.bid, cycle["id"])
        self.assertEqual(after["status"], "PLANNING")
        self.assertEqual(after["budget"], original_budget)

    def test_approve_adds_immutable_proposal_snapshot_to_plan_json(self):
        cycle = self._cycle()
        self._plan(cycle["id"])
        self._theme(cycle["id"])
        before = proposal.proposal(main.conn, self.bid, cycle["id"])

        proposal.approve(main.conn, self.bid, cycle["id"], ACTOR)

        saved = ads_plan.get_latest_plan(main.conn, self.bid, cycle["id"])["plan"]
        self.assertIn("proposal_snapshot", saved)
        # proposal_snapshot 是寫進 jsonb 欄位的快照：datetime/Decimal 這種值經過 jsonb
        # 序列化／讀回會變成字串／float（db.jsonb() 的既有轉換規則，見 app/core/db.py
        # _json_default），跟直接查 channel_plan／campaign_cycle_product 拿到的即時
        # datetime/Decimal 物件型別不同、值相同——比較前用同一套規則正規化 before，
        # 才是同一件事的公平比較（不是 production bug，是 jsonb 快照本來就會做的
        # 正常序列化）。
        before_blocks = json.loads(json.dumps(before["blocks"], default=coredb._json_default,
                                              ensure_ascii=False))
        self.assertEqual(saved["proposal_snapshot"]["channels"], before_blocks["channels"])
        self.assertEqual(saved["proposal_snapshot"]["budget"], before_blocks["budget"])
        self.assertEqual(saved["proposal_snapshot"]["brakes"], before["blocks"]["brakes"])
        self.assertEqual(saved["proposal_snapshot"]["schedule"], before["blocks"]["schedule"])
        changed = channel_repo.list_channel_plans(main.conn, self.bid, cycle["id"])[0]
        channel_repo.update_channel_plan(
            main.conn, self.bid, changed["id"], job="事後調整的分工", pct=changed["pct"],
            expected=changed["expected"], enabled=bool(changed["enabled"]), depth=changed["depth"])
        after_change = ads_plan.get_latest_plan(main.conn, self.bid, cycle["id"])["plan"]
        self.assertEqual(after_change["proposal_snapshot"]["channels"], before_blocks["channels"])

    def test_opening_creates_five_channels_and_next_cycle_inherits_enabled_choices(self):
        response = self.client.post(
            f"/api/campaigns/{self.bid}",
            json={"product_ids": [], "budget": 5000, "objective": "sales", "duration_days": 14},
        )
        self.assertEqual(response.status_code, 200, response.text)
        first_id = response.json()["cycle_id"]
        first = channel_repo.list_channel_plans(main.conn, self.bid, first_id)
        self.assertEqual({plan["channel"] for plan in first}, set(channel_repo.CHANNELS))
        social = next(plan for plan in first if plan["channel"] == "social")
        channel_repo.update_channel_plan(
            main.conn, self.bid, social["id"], job=social["job"], pct=social["pct"],
            expected=social["expected"], enabled=False, depth=social["depth"])

        second = self.client.post(
            f"/api/campaigns/{self.bid}",
            json={"product_ids": [], "budget": 5000, "objective": "sales", "duration_days": 14},
        )
        self.assertEqual(second.status_code, 200, second.text)
        next_plans = channel_repo.list_channel_plans(main.conn, self.bid, second.json()["cycle_id"])
        self.assertFalse(next(plan for plan in next_plans if plan["channel"] == "social")["enabled"])

    def test_user_visible_proposal_strings_do_not_use_forbidden_terms(self):
        cycle = self._cycle()
        self._plan(cycle["id"])
        self._theme(cycle["id"])
        body = proposal.proposal(main.conn, self.bid, cycle["id"])
        # default=str：body 裡讀回的 datetime/date（02-3b 起 DB 讀取端不再是字串）在這裡
        # 只是拿去掃禁用術語的文字，不需要精確格式，str() 夠用。
        rendered = _ID_RE.sub("", json.dumps(body, ensure_ascii=False, default=str))
        self.assertIn("真實素材內容", rendered)
        for word in FORBIDDEN_WORDS:
            self.assertNotIn(word, rendered)


if __name__ == "__main__":
    unittest.main()
