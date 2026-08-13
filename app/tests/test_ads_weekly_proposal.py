# -*- coding: utf-8 -*-
"""票 06：週提案卡、一鍵核可與保守檔執行清單。"""

import atexit
import json
import os
import shutil
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path

_tmpdir = tempfile.mkdtemp(prefix="brand_os_weekly_proposal_")
os.environ["BRAND_OS_DB"] = str(Path(_tmpdir) / "test.db")
os.environ["BRAND_OS_BACKUP_DIR"] = str(Path(_tmpdir) / "backups")
os.environ["BRAND_OS_UPLOADS"] = str(Path(_tmpdir) / "uploads")

from fastapi.testclient import TestClient  # noqa: E402

import app.main as main  # noqa: E402
from app.ads import auto_sync  # noqa: E402
from app.ads import onboarding  # noqa: E402
from app.ads import performance  # noqa: E402
from app.ads import reading  # noqa: E402
from app.ads import repository as ads_repo  # noqa: E402
from app.ads import weekly_proposals  # noqa: E402
from app.brand_intelligence import repository as bi_repo  # noqa: E402
from app.core import interrupts as core_interrupts  # noqa: E402
from app.core.db import new_id, now_iso  # noqa: E402
from app.llm.providers import FakeProvider, ProviderResponse, Usage  # noqa: E402

main.reopen_connection()


def _cleanup():
    try:
        main.conn.close()
    except Exception:
        pass
    shutil.rmtree(_tmpdir, ignore_errors=True)


atexit.register(_cleanup)
ACTOR = "測試員"
TODAY = date(2026, 8, 14)


class WeeklyProposalSelectionTest(unittest.TestCase):
    def test_actionable_readings_become_at_most_three_complete_cards(self):
        readings = [
            {
                "id": "prd_pause",
                "product_id": "prd_slow",
                "product_name": "虛構慢銷品",
                "status": "pause_candidate",
                "result": {"reasons": ["花掉一半預算仍沒有成交"]},
            },
            {
                "id": "prd_scale",
                "product_id": "prd_winner",
                "product_name": "虛構熱銷品",
                "status": "scale_candidate",
                "result": {"reasons": ["投報率已高於加碼門檻"]},
            },
        ]
        budget = {"current_budget": 10000, "proposed_budget": 12000}
        historical_cells = [{
            "experiment_cell_id": "exc_tired",
            "creative_angle": "使用情境切角",
            "spend": 3000,
            "conversions": 0,
            "underperforming": True,
        }]

        cards = weekly_proposals.select_cards(readings, budget, historical_cells)

        self.assertEqual(sum(card["action"] == "停掉" for card in cards), 1)
        self.assertEqual(len(cards), 3)
        self.assertEqual([card["action"] for card in cards], ["停掉", "加碼", "換素材"])
        self.assertIn("增加 NT$2,000", cards[1]["impact"])
        for card in cards:
            self.assertTrue({"action", "target", "reason", "impact"} <= set(card))
            self.assertTrue(all(card[key] for key in ("action", "target", "reason", "impact")))


class WeeklyProposalPersistenceTest(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(main.app)
        brand = bi_repo.create_brand(
            main.conn, name=f"虛構週提案品牌{abs(hash(self.id())) % 100000}",
            client_name=None, actor=ACTOR)
        self.brand_id = brand["id"]

    def _cycle_with_readings(self, statuses):
        product_ids = [
            bi_repo.create_product(main.conn, self.brand_id, name=f"虛構產品{index}", actor=ACTOR)["id"]
            for index, _status in enumerate(statuses, start=1)
        ]
        cycle_id = new_id("ccy")
        ts = now_iso()
        main.conn.execute(
            "INSERT INTO campaign_cycle (id, brand_id, product_scope_json, objective, budget,"
            " currency, start_date, end_date, channels_json, status, archived, plan_version, phase,"
            " created_at, updated_at) VALUES (?, ?, ?, 'sales', 10000, 'TWD', '2026-08-01',"
            " '2026-08-31', '[\"meta\"]', 'EVALUATING', 0, 0, 'normal', ?, ?)",
            (cycle_id, self.brand_id, json.dumps(product_ids), ts, ts),
        )
        main.conn.execute(
            "INSERT INTO performance_reading (id, brand_id, campaign_cycle_id, status,"
            " rule_result_json, created_at) VALUES (?, ?, ?, 'maintain', ?, ?)",
            (new_id("prd"), self.brand_id, cycle_id,
             json.dumps({"reasons": ["整體維持"]}, ensure_ascii=False), ts),
        )
        for index, (product_id, status) in enumerate(zip(product_ids, statuses), start=1):
            main.conn.execute(
                "INSERT INTO performance_reading (id, brand_id, campaign_cycle_id, product_id,"
                " status, rule_result_json, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (new_id("prd"), self.brand_id, cycle_id, product_id, status,
                 json.dumps({"reasons": [f"第 {index} 個既有判讀理由"]}, ensure_ascii=False), ts),
            )
        main.conn.commit()
        return cycle_id

    def test_generate_persists_cards_and_queues_one_ready_interrupt(self):
        cycle_id = self._cycle_with_readings(["pause_candidate", "scale_candidate"])

        cards = weekly_proposals.generate(main.conn, self.brand_id, cycle_id)

        self.assertEqual(len(cards), 2)
        self.assertTrue(all(card["status"] == "GENERATED" for card in cards))
        ready = core_interrupts.list_open(
            main.conn, brand_id=self.brand_id, category="weekly_proposal_ready",
            archive_stale=False)
        self.assertEqual(len(ready), 1)

    def test_one_click_approve_moves_all_cards_into_execution_checklist_and_audits(self):
        cycle_id = self._cycle_with_readings(["pause_candidate", "scale_candidate"])
        generated = weekly_proposals.generate(main.conn, self.brand_id, cycle_id)

        response = self.client.post(
            f"/api/campaigns/{self.brand_id}/{cycle_id}/weekly-proposals/approve")

        self.assertEqual(response.status_code, 200)
        data = response.json()["data"]
        self.assertEqual(data["proposals"], [])
        self.assertEqual(len(data["execution_checklist"]), len(generated))
        self.assertTrue(all(item["status"] == "ACCEPTED" for item in data["execution_checklist"]))
        self.assertTrue(all("Meta 廣告後台" in item["instruction"]
                            for item in data["execution_checklist"]))
        audits = main.conn.execute(
            "SELECT * FROM audit_log WHERE brand_id = ? AND entity_type = 'recommendation'"
            " AND action = 'accept_weekly_proposal'",
            (self.brand_id,),
        ).fetchall()
        self.assertEqual(len(audits), len(generated))

    def test_complete_one_accepted_card_is_idempotent(self):
        cycle_id = self._cycle_with_readings(["pause_candidate"])
        card = weekly_proposals.generate(main.conn, self.brand_id, cycle_id)[0]
        self.client.post(
            f"/api/campaigns/{self.brand_id}/{cycle_id}/weekly-proposals/approve")
        url = (f"/api/campaigns/{self.brand_id}/{cycle_id}/weekly-proposals/"
               f"{card['id']}/complete")

        first = self.client.post(url)
        second = self.client.post(url)

        self.assertEqual(first.status_code, 200)
        self.assertEqual(first.json()["data"]["status"], "APPLIED")
        self.assertEqual(second.status_code, 200)
        self.assertEqual(second.json()["data"]["status"], "APPLIED")
        audits = main.conn.execute(
            "SELECT * FROM audit_log WHERE entity_id = ? AND action = 'apply_weekly_proposal'",
            (card["id"],),
        ).fetchall()
        self.assertEqual(len(audits), 1)

    def test_all_maintain_returns_empty_array_without_filler_cards(self):
        cycle_id = self._cycle_with_readings(["maintain", "maintain"])

        response = self.client.get(
            f"/api/campaigns/{self.brand_id}/{cycle_id}/weekly-proposals")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["data"], {"proposals": [], "execution_checklist": []})
        count = main.conn.execute(
            "SELECT COUNT(*) count FROM recommendation WHERE brand_id = ?"
            " AND campaign_cycle_id = ? AND recommendation_type = 'weekly_proposal'",
            (self.brand_id, cycle_id),
        ).fetchone()["count"]
        self.assertEqual(count, 0)

    def test_due_reading_automatically_generates_weekly_proposal(self):
        product = bi_repo.create_product(
            main.conn, self.brand_id, name="虛構自動加碼品", actor=ACTOR)["id"]
        bi_repo.save_product_economics(
            main.conn, self.brand_id, product, selling_price=1000,
            unit_variable_cost=400, currency="TWD", confirmed_by=ACTOR, actor=ACTOR)
        start, end = TODAY - timedelta(days=8), TODAY + timedelta(days=5)
        cycle = ads_repo.create_cycle(
            main.conn, self.brand_id, product_ids=[product], pain_value=10000,
            objective="sales", actor=ACTOR, start_date=start.isoformat(),
            duration_days=(end - start).days + 1)
        ads_repo.update_cycle_status(
            main.conn, self.brand_id, cycle["id"], status="LIVE", actor=ACTOR)
        onboarding.create_reminders(main.conn, self.brand_id, cycle["id"])
        performance.import_manual(
            main.conn, self.brand_id, cycle["id"],
            {"date_start": start.isoformat(), "date_stop": end.isoformat(),
             "spend": 10000, "impressions": 20000, "clicks": 400,
             "conversions": 10, "revenue": 40000},
            actor=ACTOR, today=TODAY.isoformat())
        main.conn.execute(
            "UPDATE performance_snapshot SET product_id = ? WHERE brand_id = ?"
            " AND campaign_cycle_id = ?", (product, self.brand_id, cycle["id"]))
        main.conn.commit()
        original_provider = reading.PROVIDER
        reading.PROVIDER = FakeProvider(response=ProviderResponse(
            output_text='{"text": "自動判讀測試說明"}', structured=None,
            usage=Usage(input_tokens=100, output_tokens=50), stop_reason="end_turn"))
        try:
            auto_sync.run_due_readings(
                main.conn, self.brand_id, TODAY.isoformat())
        finally:
            reading.PROVIDER = original_provider

        cards = weekly_proposals.list_cards(main.conn, self.brand_id, cycle["id"])
        self.assertEqual(len(cards), 1)
        self.assertEqual(cards[0]["action"], "加碼")


if __name__ == "__main__":
    unittest.main()
