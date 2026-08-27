# -*- coding: utf-8 -*-
"""T1 批次 A：品牌層週提案行動卡 API、背景重判與每週排程。"""

import json
import time
import unittest
from datetime import datetime, timezone
from unittest import mock

import pytest
from fastapi.testclient import TestClient

import app.main as main
from app.ads import auto_sync
from app.ads import routes as ads_routes
from app.ads import routes_weekly_proposals_api
from app.ads import repository as ads_repo
from app.brand_intelligence import repository as bi_repo
from app.core import db, interrupts as core_interrupts
from app.core.db import new_id, now_iso



ACTOR = "測試員"


class WeeklyActionApiTest(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(main.app)
        self.brand = bi_repo.create_brand(
            main.conn,
            name=f"虛構行動卡品牌{abs(hash(self.id())) % 100000}",
            client_name=None,
            actor=ACTOR,
        )
        cycle = ads_repo.create_cycle(
            main.conn,
            self.brand["id"],
            product_ids=[],
            pain_value=12000,
            objective="sales",
            actor=ACTOR,
            start_date="2026-08-01",
            duration_days=31,
        )
        ads_repo.update_cycle_status(
            main.conn, self.brand["id"], cycle["id"], status="LIVE", actor=ACTOR,
        )
        self.cycle_id = cycle["id"]
        self.base = f"/api/campaigns/brands/{self.brand['id']}/weekly"
        self.card_ids = {
            "save": self._insert_card("停掉", "虛構省錢組", "花費增加但沒有帶來訂單"),
            "spend": self._insert_card(
                "加碼", "虛構成長組", "每筆訂單花費維持穩定", suggested_amount=15000,
            ),
            "asset": self._insert_card("換素材", "虛構開箱切角", "同一批圖片已經看過很多次"),
        }

    def tearDown(self):
        ads_routes._progress_clear(
            ads_routes._progress_key("weekly_rejudge", self.brand["id"], "_")
        )

    def _insert_card(
        self, action: str, target: str, reason: str, suggested_amount: float | None = None,
    ) -> str:
        recommendation_id = new_id("rec")
        content = {
            "action": action,
            "target": target,
            "reason": reason,
            "impact": "這是虛構測試影響",
            "instruction": f"前往 Meta 廣告後台，找到「{target}」並處理。",
        }
        if suggested_amount is not None:
            content["suggested_amount"] = suggested_amount
        ts = now_iso()
        main.conn.execute(
            "INSERT INTO recommendation (id, org_id, brand_id, campaign_cycle_id,"
            " recommendation_type, content_json, status, created_at, updated_at)"
            " VALUES (%s, %s, %s, %s, 'weekly_proposal', %s, 'GENERATED', %s, %s)",
            (
                recommendation_id,
                db.DEV_ORG_ID,
                self.brand["id"],
                self.cycle_id,
                json.dumps(content, ensure_ascii=False),
                ts,
                ts,
            ),
        )
        main.conn.commit()
        return recommendation_id

    def _proposal(self, data: dict, grade: str) -> dict:
        return next(card for card in data["proposals"] if card["grade"] == grade)

    def test_get_exposes_three_grades_plain_copy_and_spend_confirmation(self):
        response = self.client.get(f"{self.base}/proposals")

        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertEqual(set(body), {"data", "generated_at"})
        data = body["data"]
        self.assertEqual(data["cycle_id"], self.cycle_id)
        self.assertEqual({card["grade"] for card in data["proposals"]}, {"save", "spend", "asset"})
        self.assertIn("建議停掉", self._proposal(data, "save")["copy"])
        self.assertEqual(
            self._proposal(data, "spend")["spend_confirmation"],
            {"required": True, "suggested_amount": 15000, "currency": "TWD"},
        )

    def test_individual_approve_returns_action_card_for_all_three_grades(self):
        observed = {}
        for grade, recommendation_id in self.card_ids.items():
            payload = {"confirmed_amount": 16000} if grade == "spend" else {}
            response = self.client.post(
                f"{self.base}/proposals/{recommendation_id}/approve", json=payload,
            )
            self.assertEqual(response.status_code, 200, response.text)
            card = response.json()["data"]["approved"]
            observed[grade] = card["action_card"]

        self.assertIn("廣告後台", observed["save"])
        self.assertIn("NT$16,000", observed["spend"])
        self.assertIn("素材工作檯", observed["asset"])

    def test_spend_approve_without_confirmed_amount_returns_enveloped_400(self):
        response = self.client.post(
            f"{self.base}/proposals/{self.card_ids['spend']}/approve", json={},
        )

        self.assertEqual(response.status_code, 400, response.text)
        self.assertEqual(set(response.json()), {"data", "generated_at"})
        self.assertIn("金額", response.json()["data"]["error"])

    def test_skip_removes_card_from_pending_list(self):
        response = self.client.post(
            f"{self.base}/proposals/{self.card_ids['save']}/skip",
        )

        self.assertEqual(response.status_code, 200, response.text)
        data = response.json()["data"]
        self.assertEqual(data["skipped_id"], self.card_ids["save"])
        self.assertNotIn(self.card_ids["save"], {card["id"] for card in data["proposals"]})

    def test_approve_all_keeps_spend_card_waiting_for_amount(self):
        response = self.client.post(f"{self.base}/proposals/approve-all")

        self.assertEqual(response.status_code, 200, response.text)
        data = response.json()["data"]
        self.assertEqual({card["grade"] for card in data["approved"]}, {"save", "asset"})
        self.assertEqual(
            [card["id"] for card in data["pending_confirmation"]],
            [self.card_ids["spend"]],
        )
        self.assertEqual([card["grade"] for card in data["proposals"]], ["spend"])

    def test_rejudge_runs_in_background_and_queues_completion_interrupt(self):
        status_url = f"{self.base}/rejudge/status"
        with (
            mock.patch.object(routes_weekly_proposals_api.ads_reading, "run", return_value=(True, None)),
            mock.patch.object(routes_weekly_proposals_api.weekly_proposals, "generate", return_value=[]),
        ):
            start = self.client.post(f"{self.base}/rejudge")
            self.assertEqual(start.status_code, 200, start.text)
            status = {"status": "running"}
            for _ in range(100):
                status = self.client.get(status_url).json()["data"]
                if status["status"] != "running":
                    break
                time.sleep(0.02)

        self.assertEqual(status["status"], "done", status)
        queued = core_interrupts.list_open(
            main.conn,
            brand_id=self.brand["id"],
            category="weekly_rejudge_done",
            archive_stale=False,
        )
        self.assertEqual(len(queued), 1)
        self.assertLessEqual(len(queued[0]["message"]), 30)


class WeeklyScheduleGateTest(unittest.TestCase):
    def test_mocked_time_runs_weekly_engine_once_per_iso_week(self):
        original = main._last_weekly_engine_check
        main._last_weekly_engine_check = None
        try:
            with mock.patch.object(auto_sync, "run_weekly_engine") as run:
                main._weekly_engine_if_due(datetime(2026, 8, 17, 1, tzinfo=timezone.utc))
                main._weekly_engine_if_due(datetime(2026, 8, 20, 1, tzinfo=timezone.utc))
                main._weekly_engine_if_due(datetime(2026, 8, 24, 1, tzinfo=timezone.utc))
        finally:
            main._last_weekly_engine_check = original

        self.assertEqual(run.call_count, 2)
        self.assertEqual(run.call_args_list[0].kwargs, {"today": "2026-08-17"})
        self.assertEqual(run.call_args_list[1].kwargs, {"today": "2026-08-24"})


if __name__ == "__main__":
    unittest.main()
