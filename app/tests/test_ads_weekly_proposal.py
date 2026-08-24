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

    def test_replace_asset_reason_follows_the_triggering_path(self):
        """驗收 A 第 4 節 6c：有成交但投報率低於停損線的切角，理由要寫實際投報率，
        不能沿用零成交那句。零成交的切角則維持零成交的說法。"""
        budget = {"current_budget": 10000, "proposed_budget": 12000}
        low_roas = [{
            "experiment_cell_id": "exc_bad_cvr",
            "creative_angle": "虛構切角：有成交但沒回本",
            "spend": 3000, "conversions": 12, "revenue": 2580,
            "breakeven_roas": 1.4,
            "underperforming": True,
            "underperforming_reason": "roas_below_stop_loss",
        }]
        reason = weekly_proposals.select_cards([], budget, low_roas)[0]["reason"]
        self.assertIn("0.86", reason)          # 實際投報率 2580 / 3000
        self.assertIn("0.98", reason)          # 停損線 1.4 × PAUSE_MARGIN
        self.assertNotIn("沒有帶來成交", reason)
        self.assertNotIn("零成交", reason)

        zero = [{**low_roas[0], "conversions": 0, "revenue": 0,
                 "underperforming_reason": "zero_conversion"}]
        self.assertIn("零成交", weekly_proposals.select_cards([], budget, zero)[0]["reason"])



class WeeklyProposalPersistenceTest(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(main.app)
        brand = bi_repo.create_brand(
            main.conn, name=f"虛構週提案品牌{abs(hash(self.id())) % 100000}",
            client_name=None, actor=ACTOR)
        self.brand_id = brand["id"]
        self._original_provider = reading.PROVIDER
        reading.PROVIDER = FakeProvider(response=ProviderResponse(
            output_text='{"text": "重判測試說明"}', structured=None,
            usage=Usage(input_tokens=100, output_tokens=50), stop_reason="end_turn"))

    def tearDown(self):
        reading.PROVIDER = self._original_provider

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

    def _cycle_ready_for_reading(self, product_name):
        product_id = bi_repo.create_product(
            main.conn, self.brand_id, name=product_name, actor=ACTOR)["id"]
        bi_repo.save_product_economics(
            main.conn, self.brand_id, product_id, selling_price=1000,
            unit_variable_cost=400, currency="TWD", confirmed_by=ACTOR, actor=ACTOR)
        start, end = TODAY - timedelta(days=8), TODAY + timedelta(days=5)
        cycle = ads_repo.create_cycle(
            main.conn, self.brand_id, product_ids=[product_id], pain_value=10000,
            objective="sales", actor=ACTOR, start_date=start.isoformat(),
            duration_days=(end - start).days + 1)
        ads_repo.update_cycle_status(
            main.conn, self.brand_id, cycle["id"], status="LIVE", actor=ACTOR)
        result = performance.import_manual(
            main.conn, self.brand_id, cycle["id"],
            {"date_start": start.isoformat(), "date_stop": end.isoformat(),
             "spend": 10000, "impressions": 20000, "clicks": 400,
             "conversions": 10, "revenue": 40000},
            actor=ACTOR, today=TODAY.isoformat())
        self.assertEqual(result.errors, [])
        main.conn.execute(
            "UPDATE performance_snapshot SET product_id = ? WHERE brand_id = ?"
            " AND campaign_cycle_id = ?", (product_id, self.brand_id, cycle["id"]))
        main.conn.commit()
        return cycle["id"]

    def _approved_real_card(self, status):
        cycle_id = self._cycle_ready_for_reading(f"虛構重判產品{status}")
        ok, err = reading.run(main.conn, self.brand_id, cycle_id, ACTOR)
        self.assertEqual((ok, err), (True, None))
        card = weekly_proposals.generate(main.conn, self.brand_id, cycle_id)[0]
        weekly_proposals.approve_card(
            main.conn,
            self.brand_id,
            cycle_id,
            card["id"],
            actor=ACTOR,
            confirmed_amount=12000 if card["action"] == "加碼" else None,
        )
        if status == "APPLIED":
            weekly_proposals.complete(
                main.conn, self.brand_id, cycle_id, card["id"], actor=ACTOR)
        return cycle_id, card["id"]

    def test_generate_persists_cards_and_queues_one_ready_interrupt(self):
        cycle_id = self._cycle_with_readings(["pause_candidate", "scale_candidate"])

        cards = weekly_proposals.generate(main.conn, self.brand_id, cycle_id)

        self.assertEqual(len(cards), 2)
        self.assertTrue(all(card["status"] == "GENERATED" for card in cards))
        ready = core_interrupts.list_open(
            main.conn, brand_id=self.brand_id, category="weekly_proposal_ready",
            archive_stale=False)
        self.assertEqual(len(ready), 1)

    def test_one_click_approve_keeps_spend_card_waiting_for_amount(self):
        cycle_id = self._cycle_with_readings(["pause_candidate", "scale_candidate"])
        generated = weekly_proposals.generate(main.conn, self.brand_id, cycle_id)

        response = self.client.post(
            f"/api/campaigns/{self.brand_id}/{cycle_id}/weekly-proposals/approve")

        self.assertEqual(response.status_code, 200)
        data = response.json()["data"]
        self.assertEqual([card["grade"] for card in data["proposals"]], ["spend"])
        self.assertEqual(len(data["execution_checklist"]), len(generated) - 1)
        self.assertTrue(all(item["status"] == "ACCEPTED" for item in data["execution_checklist"]))
        self.assertTrue(all("Meta 廣告後台" in item["instruction"]
                            for item in data["execution_checklist"]))
        self.assertEqual([card["grade"] for card in data["pending_confirmation"]], ["spend"])
        audits = main.conn.execute(
            "SELECT * FROM audit_log WHERE brand_id = ? AND entity_type = 'recommendation'"
            " AND action = 'accept_weekly_proposal'",
            (self.brand_id,),
        ).fetchall()
        self.assertEqual(len(audits), len(generated) - 1)

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

    def test_late_data_rerun_preserves_applied_weekly_proposal(self):
        cycle_id, card_id = self._approved_real_card("APPLIED")

        reading.rerun_for_late_data(
            main.conn, self.brand_id, cycle_id, actor=ACTOR)

        row = main.conn.execute(
            "SELECT status FROM recommendation WHERE id = ?", (card_id,)).fetchone()
        self.assertIsNotNone(row)
        self.assertEqual(row["status"], "APPLIED")

    def test_manual_route_rerun_preserves_accepted_and_applied_weekly_proposals(self):
        """原本打 HTTP 判讀等待頁路由 `/reading/progress?run=1`；那條路由（連同它借用的
        等待頁機制）已隨 T4 大清倉刪除——判讀本來就沒有分階段可回報，路由唯一做的事就是
        呼叫 `reading.run()`，見已刪除的 routes_performance.py 檔頭說明。改直測業務層，
        斷言意義不變：重判不會讓已核可／已套用的週提案卡跑掉。"""
        observed = []
        for status in ("ACCEPTED", "APPLIED"):
            cycle_id, card_id = self._approved_real_card(status)
            ok, err = reading.run(main.conn, self.brand_id, cycle_id, ACTOR)
            row = main.conn.execute(
                "SELECT status FROM recommendation WHERE id = ?", (card_id,)).fetchone()
            observed.append(((ok, err), row["status"] if row else None))

        self.assertEqual(observed, [((True, None), "ACCEPTED"), ((True, None), "APPLIED")])

    def test_generate_skips_approved_duplicate_and_keeps_unrelated_new_signal(self):
        cycle_id = self._cycle_with_readings(["pause_candidate", "scale_candidate"])
        ts = now_iso()
        main.conn.execute(
            "INSERT INTO recommendation (id, brand_id, campaign_cycle_id,"
            " recommendation_type, content_json, status, created_at, updated_at)"
            " VALUES (?, ?, ?, 'weekly_proposal', ?, 'APPLIED', ?, ?)",
            (new_id("rec"), self.brand_id, cycle_id,
             json.dumps({"action": "停掉", "target": "虛構產品1", "reason": "已處理",
                         "impact": "已完成", "instruction": "已完成"}, ensure_ascii=False),
             ts, ts),
        )
        main.conn.commit()

        cards = weekly_proposals.generate(main.conn, self.brand_id, cycle_id)

        identities = {(card["action"], card["target"], card["status"]) for card in cards}
        self.assertEqual(identities, {
            ("停掉", "虛構產品1", "APPLIED"),
            ("加碼", "虛構產品2", "GENERATED"),
        })

    def test_day7_and_final_reruns_do_not_duplicate_applied_card(self):
        observed = []
        for trigger in ("day7", "final"):
            cycle_id, card_id = self._approved_real_card("APPLIED")
            if trigger == "final":
                ok, err = reading.finalize(main.conn, self.brand_id, cycle_id, ACTOR)
            else:
                ok, err = reading.run(main.conn, self.brand_id, cycle_id, ACTOR)
            self.assertEqual((ok, err), (True, None))

            cards = weekly_proposals.generate(main.conn, self.brand_id, cycle_id)
            preserved = next(card for card in cards if card["id"] == card_id)
            same_action_target = [
                card for card in cards
                if (card["action"], card["target"])
                == (preserved["action"], preserved["target"])
            ]
            observed.append((trigger, preserved["status"], len(same_action_target)))

        self.assertEqual(observed, [
            ("day7", "APPLIED", 1),
            ("final", "APPLIED", 1),
        ])

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
