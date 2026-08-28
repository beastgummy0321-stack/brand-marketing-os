"""票 06：週提案卡、一鍵核可與保守檔執行清單。"""

import json
import unittest
from datetime import date, timedelta

from fastapi.testclient import TestClient

import app.main as main
from app.ads import auto_sync, onboarding, performance, reading, weekly_proposals
from app.ads import repository as ads_repo
from app.brand_intelligence import repository as bi_repo
from app.core import db
from app.core import interrupts as core_interrupts
from app.core.db import new_id, now_iso
from app.llm.providers import FakeProvider, ProviderResponse, Usage

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

    def test_historical_angle_card_does_not_pass_off_an_angle_as_an_ad_name(self):
        """B0-11：這張卡的 target 是切角名（可能橫跨好幾支廣告、也可能是別期留下來的舊
        方向），不是某一支廣告的名字——文案不能寫成「建議換素材『bad_cvr』」讓人誤以為
        bad_cvr 是這期匯入的廣告，要老實說這是舊方向、不是本期廣告（ADR 0025 決定 8：
        target 命名空間本來就是切角，不動這個既有行為，只改使用者看到的措辭）。"""
        historical_cells = [{
            "experiment_cell_id": "exc_tired",
            "creative_angle": "bad_cvr",
            "spend": 3000,
            "conversions": 0,
            "underperforming": True,
        }]
        cards = weekly_proposals.select_cards([], {}, historical_cells)
        self.assertEqual(len(cards), 1)
        card = cards[0]
        self.assertTrue(card.get("is_historical_angle"))

        presented = weekly_proposals.present({**card, "id": "rec_x", "status": "GENERATED"}, "brd_x")
        self.assertNotIn("建議換素材「bad_cvr」", presented["copy"])
        self.assertIn("投放方向", presented["copy"])
        self.assertIn("不是這期的廣告", presented["copy"])

        accepted = weekly_proposals.present({**card, "id": "rec_x", "status": "ACCEPTED"}, "brd_x")
        self.assertIn("舊方向", accepted["action_card"])
        self.assertNotIn("為「bad_cvr」準備新素材", accepted["action_card"])

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

    # --- ADR 0025：停掉卡下沉到廣告層 -----------------------------------------
    @staticmethod
    def _asset(name, *, spend, conversions, revenue, attributable=1):
        row = {"pkg_id": f"pkg_{name}", "asset_name": name, "impressions": 50000,
               "clicks": 1000, "spend": spend, "conversions": conversions,
               "revenue": revenue, "attributable": attributable}
        row["kpis"] = performance.compute_kpis(row)
        return row

    def _loaded(self, assets, breakeven=1.67):
        return {"cycle": {"id": "prd_cycle",
                          "result": {"breakeven": breakeven, "asset_breakdown": assets}}}

    def test_losing_ad_gets_a_stop_card_naming_that_ad(self):
        """ADR 0025 決定 1／3／6：整檔還在賺，但有一支低於停損線 → 點名那一支。"""
        assets = [self._asset("虧損_01_ad", spend=12000, conversions=12, revenue=10320)]
        assets += [self._asset(f"賺錢_{i}_ad", spend=4500, conversions=30, revenue=25830)
                   for i in range(1, 5)]

        card = weekly_proposals.bleeding_asset(
            None, "brd_x", "ccy_x", self._loaded(assets), {"current_budget": 30000})

        self.assertEqual(card["target"], "虧損_01_ad")
        self.assertIn("0.86", card["reason"])       # 實際投報率 10320 / 12000
        self.assertIn("1.17", card["reason"])       # 停損線 1.67 × PAUSE_MARGIN
        self.assertIsNone(card["product_id"])
        self.assertEqual(card["performance_reading_id"], "prd_cycle")

    def test_stop_card_stays_silent_below_the_directional_call_guard(self):
        """ADR 0025 決定 5：3–10 筆成交不准斷言停損，這道護欄不得被繞過。"""
        assets = [self._asset("虧損_01_ad", spend=12000, conversions=8, revenue=6880)]
        assets += [self._asset(f"賺錢_{i}_ad", spend=4500, conversions=30, revenue=25830)
                   for i in range(1, 5)]

        self.assertIsNone(weekly_proposals.bleeding_asset(
            None, "brd_x", "ccy_x", self._loaded(assets), {"current_budget": 30000}))

    def test_stop_card_stays_silent_when_attribution_is_not_per_ad(self):
        """ADR 0025 決定 9：歸屬對不準的廣告不參加，也不代它說話。"""
        assets = [self._asset("虧損_01_ad", spend=12000, conversions=12, revenue=10320,
                              attributable=0)]

        self.assertIsNone(weekly_proposals.bleeding_asset(
            None, "brd_x", "ccy_x", self._loaded(assets), {"current_budget": 30000}))

    def test_product_level_pause_suppresses_the_ad_level_one(self):
        """ADR 0025 決定 4：上位動作已涵蓋下位，不叫使用者把同一件事做兩次。"""
        bleeding = {"action": "停掉", "target": "虧損_01_ad", "reason": "理由",
                    "impact": "先止住這支的花費，另外幾支照跑", "product_id": None,
                    "performance_reading_id": "prd_cycle", "pkg_id": "pkg_bad"}
        budget = {"current_budget": 10000, "proposed_budget": 12000}
        product_pause = [{"id": "prd_pause", "product_id": "prd_slow",
                          "product_name": "虛構慢銷品", "status": "pause_candidate",
                          "result": {"reasons": ["花掉一半預算仍沒有成交"]}}]

        with_product = weekly_proposals.select_cards(product_pause, budget, [], None, bleeding)
        self.assertEqual([card["target"] for card in with_product], ["虛構慢銷品"])

        without_product = weekly_proposals.select_cards([], budget, [], None, bleeding)
        self.assertEqual([card["target"] for card in without_product], ["虧損_01_ad"])

    def test_fatigue_card_yields_to_the_stop_card_on_the_same_ad(self):
        """ADR 0025 決定 8：同一支廣告該停又疲勞時只留停掉，認同一支要比 pkg_id。"""
        bleeding = {"action": "停掉", "target": "虧損_01_ad", "reason": "理由",
                    "impact": "先止住這支的花費，另外幾支照跑", "product_id": None,
                    "performance_reading_id": "prd_cycle", "pkg_id": "pkg_bad"}
        fatigue = {"pkg_id": "pkg_bad", "target": "使用情境切角", "frequency": 4.2}
        budget = {"current_budget": 10000, "proposed_budget": 12000}

        cards = weekly_proposals.select_cards([], budget, [], fatigue, bleeding)

        self.assertEqual([card["action"] for card in cards], ["停掉"])

        # 沒有 pkg_id 的疲勞卡（對不回交接包）不得被「兩邊都是 None」誤判成同一支而吃掉。
        anonymous = {"target": "使用情境切角", "frequency": 4.2}
        product_only = weekly_proposals.select_cards([], budget, [], anonymous, None)
        self.assertEqual([card["action"] for card in product_only], ["換素材"])



class WeeklyProposalPersistenceTest(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(main.app)
        brand = bi_repo.create_brand(
            main.conn, name=f"虛構週提案品牌{abs(hash(self.id())) % 100000}",
            client_name=None, actor=ACTOR, org_id=db.DEV_ORG_ID)
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
            "INSERT INTO campaign_cycle (id, org_id, brand_id, product_scope_json, objective, budget,"
            " currency, start_date, end_date, channels_json, status, archived, plan_version, phase,"
            " created_at, updated_at) VALUES (%s, %s, %s, %s, 'sales', 10000, 'TWD', '2026-08-01',"
            " '2026-08-31', '[\"meta\"]', 'EVALUATING', false, 0, 'normal', %s, %s)",
            (cycle_id, db.DEV_ORG_ID, self.brand_id, json.dumps(product_ids), ts, ts),
        )
        main.conn.execute(
            "INSERT INTO performance_reading (id, org_id, brand_id, campaign_cycle_id, status,"
            " rule_result_json, created_at) VALUES (%s, %s, %s, %s, 'maintain', %s, %s)",
            (new_id("prd"), db.DEV_ORG_ID, self.brand_id, cycle_id,
             json.dumps({"reasons": ["整體維持"]}, ensure_ascii=False), ts),
        )
        for index, (product_id, status) in enumerate(zip(product_ids, statuses), start=1):
            main.conn.execute(
                "INSERT INTO performance_reading (id, org_id, brand_id, campaign_cycle_id, product_id,"
                " status, rule_result_json, created_at) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
                (new_id("prd"), db.DEV_ORG_ID, self.brand_id, cycle_id, product_id, status,
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
            "UPDATE performance_snapshot SET product_id = %s WHERE brand_id = %s"
            " AND campaign_cycle_id = %s", (product_id, self.brand_id, cycle["id"]))
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

    def _imported_ad(self, cycle_id, ad_name, frequency):
        """把一支對得回交接包的廣告連同頻率匯進這期（比照 test_ads_reading.py 的既有寫法）。"""
        pkg_id, mapping_id, ts = new_id("pkg"), new_id("xam"), now_iso()
        main.conn.execute(
            "INSERT INTO publishing_package (id, org_id, brand_id, campaign_cycle_id, campaign_name,"
            " adset_name, ad_name, destination_url, utm_json, status, created_at)"
            " VALUES (%s, %s, %s, %s, %s, %s, %s, %s, '{}', 'ready', %s)",
            (pkg_id, db.DEV_ORG_ID, self.brand_id, cycle_id, "疲勞測試活動", "疲勞測試組合", ad_name,
             "https://example.test", ts))
        main.conn.execute(
            "INSERT INTO external_ad_mapping (id, org_id, brand_id, publishing_package_id,"
            " campaign_cycle_id, platform, claim_status, confirmed_by, confirmed_at,"
            " created_at) VALUES (%s, %s, %s, %s, %s, 'meta', 'confirmed', %s, %s, %s)",
            (mapping_id, db.DEV_ORG_ID, self.brand_id, pkg_id, cycle_id, ACTOR, ts, ts))
        main.conn.commit()
        csv_text = ("行銷活動名稱,廣告名稱,曝光次數,連結點擊次數,花費金額,購買次數,購買轉換價值,頻率\n"
                    f"疲勞測試活動,{ad_name},12500,340,5000,12,18600,{frequency}\n")
        result = performance.import_csv(
            main.conn, self.brand_id, cycle_id, csv_text, actor=ACTOR)
        self.assertEqual(result.errors, [])

    def _cycle_with_five_ads(self):
        """驗收 A 第 4 節第 2 題的實況：五支廣告，一支 ROAS 0.86、四支 5.74、整檔 3.79。"""
        product_id = bi_repo.create_product(
            main.conn, self.brand_id, name="虛構五支廣告產品", actor=ACTOR)["id"]
        bi_repo.save_product_economics(
            main.conn, self.brand_id, product_id, selling_price=1000,
            unit_variable_cost=400, currency="TWD", confirmed_by=ACTOR, actor=ACTOR)
        start, end = TODAY - timedelta(days=8), TODAY + timedelta(days=5)
        cycle = ads_repo.create_cycle(
            main.conn, self.brand_id, product_ids=[product_id], pain_value=30000,
            objective="sales", actor=ACTOR, start_date=start.isoformat(),
            duration_days=(end - start).days + 1)
        cycle_id = cycle["id"]
        main.conn.execute("UPDATE campaign_cycle SET budget = 30000 WHERE id = %s", (cycle_id,))
        ads_repo.update_cycle_status(
            main.conn, self.brand_id, cycle_id, status="LIVE", actor=ACTOR)

        rows = [("虧損_01_ad", 50000, 1000, 12000, 12, 10320)]
        rows += [(f"賺錢_{i}_ad", 30000, 800, 4500, 30, 25830) for i in range(1, 5)]
        ts = now_iso()
        for ad_name, *_ in rows:
            pkg_id, mapping_id = new_id("pkg"), new_id("xam")
            main.conn.execute(
                "INSERT INTO publishing_package (id, org_id, brand_id, campaign_cycle_id, campaign_name,"
                " adset_name, ad_name, destination_url, utm_json, status, created_at)"
                " VALUES (%s, %s, %s, %s, %s, %s, %s, %s, '{}', 'ready', %s)",
                (pkg_id, db.DEV_ORG_ID, self.brand_id, cycle_id, "五支廣告活動", "五支廣告組合", ad_name,
                 "https://example.test", ts))
            main.conn.execute(
                "INSERT INTO external_ad_mapping (id, org_id, brand_id, publishing_package_id,"
                " campaign_cycle_id, platform, claim_status, confirmed_by, confirmed_at,"
                " created_at) VALUES (%s, %s, %s, %s, %s, 'meta', 'confirmed', %s, %s, %s)",
                (mapping_id, db.DEV_ORG_ID, self.brand_id, pkg_id, cycle_id, ACTOR, ts, ts))
        main.conn.commit()
        csv_text = ("行銷活動名稱,廣告名稱,曝光次數,連結點擊次數,花費金額,購買次數,購買轉換價值,頻率\n"
                    + "".join(f"五支廣告活動,{n},{imp},{clk},{spend},{cv},{rev},1.8\n"
                              for n, imp, clk, spend, cv, rev in rows))
        result = performance.import_csv(
            main.conn, self.brand_id, cycle_id, csv_text, actor=ACTOR)
        self.assertEqual(result.errors, [])
        return cycle_id

    def test_one_losing_ad_in_a_profitable_cycle_gets_a_stop_card(self):
        """驗收 A 第 4 節 (a)：整檔 ROAS 3.79 還在賺，週卡仍要點名該停的那一支廣告。

        這一題以前只出現在 AI 白話裡——規則層看得到 asset_breakdown 卻一句話都沒說
        （ADR 0025 起因）。"""
        cycle_id = self._cycle_with_five_ads()
        ok, err = reading.run(main.conn, self.brand_id, cycle_id, ACTOR)
        self.assertEqual((ok, err), (True, None))

        cards = weekly_proposals.generate(main.conn, self.brand_id, cycle_id)

        stop_cards = [card for card in cards if card["action"] == "停掉"]
        self.assertEqual(len(stop_cards), 1)
        self.assertEqual(stop_cards[0]["target"], "虧損_01_ad")
        self.assertIn("0.86", stop_cards[0]["reason"])

    def test_red_fatigue_light_gets_a_replace_asset_card_naming_that_ad(self):
        """驗收 A 第 4 節 1b：頻率 4.2 過冷受眾危險門檻（3.5），週卡不能只出加碼。"""
        cycle_id = self._cycle_with_readings(["scale_candidate"])
        self._imported_ad(cycle_id, "疲勞測試_01_ad", 4.2)

        cards = weekly_proposals.generate(main.conn, self.brand_id, cycle_id)

        asset_cards = [card for card in cards if card["action"] == "換素材"]
        self.assertEqual(len(asset_cards), 1)
        self.assertEqual(asset_cards[0]["target"], "疲勞測試_01_ad")
        self.assertIn("頻率 4.2", asset_cards[0]["reason"])
        self.assertIn("4 次以上", asset_cards[0]["reason"])

    def test_safe_frequency_gets_no_replace_asset_card(self):
        cycle_id = self._cycle_with_readings(["scale_candidate"])
        self._imported_ad(cycle_id, "正常頻率_01_ad", 1.8)

        cards = weekly_proposals.generate(main.conn, self.brand_id, cycle_id)

        self.assertEqual([card for card in cards if card["action"] == "換素材"], [])

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
            "SELECT * FROM audit_log WHERE brand_id = %s AND entity_type = 'recommendation'"
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
            "SELECT * FROM audit_log WHERE entity_id = %s AND action = 'apply_weekly_proposal'",
            (card["id"],),
        ).fetchall()
        self.assertEqual(len(audits), 1)

    def test_late_data_rerun_preserves_applied_weekly_proposal(self):
        cycle_id, card_id = self._approved_real_card("APPLIED")

        reading.rerun_for_late_data(
            main.conn, self.brand_id, cycle_id, actor=ACTOR)

        row = main.conn.execute(
            "SELECT status FROM recommendation WHERE id = %s", (card_id,)).fetchone()
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
                "SELECT status FROM recommendation WHERE id = %s", (card_id,)).fetchone()
            observed.append(((ok, err), row["status"] if row else None))

        self.assertEqual(observed, [((True, None), "ACCEPTED"), ((True, None), "APPLIED")])

    def test_generate_skips_approved_duplicate_and_keeps_unrelated_new_signal(self):
        cycle_id = self._cycle_with_readings(["pause_candidate", "scale_candidate"])
        ts = now_iso()
        main.conn.execute(
            "INSERT INTO recommendation (id, org_id, brand_id, campaign_cycle_id,"
            " recommendation_type, content_json, status, created_at, updated_at)"
            " VALUES (%s, %s, %s, %s, 'weekly_proposal', %s, 'APPLIED', %s, %s)",
            (new_id("rec"), db.DEV_ORG_ID, self.brand_id, cycle_id,
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
            "SELECT COUNT(*) count FROM recommendation WHERE brand_id = %s"
            " AND campaign_cycle_id = %s AND recommendation_type = 'weekly_proposal'",
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
            "UPDATE performance_snapshot SET product_id = %s WHERE brand_id = %s"
            " AND campaign_cycle_id = %s", (product, self.brand_id, cycle["id"]))
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


class SettleArchivesUnhandledCardsTest(unittest.TestCase):
    """票 F9：結案時還沒被使用者處理的 GENERATED 週提案卡不能悄悄消失（原本
    `reading.run()` 的重判清空邏輯會把它們整批 DELETE 掉）。

    不繼承 WeeklyProposalPersistenceTest——繼承整個 TestCase 只為了借兩個 helper，
    會連它既有的 12 個測試方法一起重跑一遍。setUp／`_cycle_ready_for_reading` 照抄
    一份（跟本檔其他測試類別彼此不互相繼承是同一個既有慣例）。"""

    def setUp(self):
        self.client = TestClient(main.app)
        brand = bi_repo.create_brand(
            main.conn, name=f"虛構結案歸檔品牌{abs(hash(self.id())) % 100000}",
            client_name=None, actor=ACTOR, org_id=db.DEV_ORG_ID)
        self.brand_id = brand["id"]
        self._original_provider = reading.PROVIDER
        reading.PROVIDER = FakeProvider(response=ProviderResponse(
            output_text='{"text": "結案測試說明"}', structured=None,
            usage=Usage(input_tokens=100, output_tokens=50), stop_reason="end_turn"))

    def tearDown(self):
        reading.PROVIDER = self._original_provider

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
            "UPDATE performance_snapshot SET product_id = %s WHERE brand_id = %s"
            " AND campaign_cycle_id = %s", (product_id, self.brand_id, cycle["id"]))
        main.conn.commit()
        return cycle["id"]

    def _settle_url(self, cycle_id):
        return f"/api/campaigns/{self.brand_id}/{cycle_id}/settle-now"

    def _generated_card(self, product_name):
        cycle_id = self._cycle_ready_for_reading(product_name)
        ok, err = reading.run(main.conn, self.brand_id, cycle_id, ACTOR)
        self.assertEqual((ok, err), (True, None))
        card = weekly_proposals.generate(main.conn, self.brand_id, cycle_id)[0]
        return cycle_id, card

    def test_finalize_archives_unhandled_generated_cards_instead_of_deleting(self):
        cycle_id, card = self._generated_card("虛構結案未處理品")

        ok, err = reading.finalize(main.conn, self.brand_id, cycle_id, ACTOR)

        self.assertEqual((ok, err), (True, None))
        row = main.conn.execute(
            "SELECT status FROM recommendation WHERE id = %s", (card["id"],)).fetchone()
        self.assertIsNotNone(row)  # 沒被下面那段 DELETE 悄悄清掉
        self.assertNotEqual(row["status"], "GENERATED")
        self.assertEqual(row["status"], "ARCHIVED_ON_CLOSE")
        done = core_interrupts.list_done(main.conn, brand_id=self.brand_id)
        self.assertEqual([d["category"] for d in done], ["weekly_proposal_archived_on_close"])
        self.assertIn("歸檔", done[0]["message"])

    def test_settle_now_get_reports_unhandled_cards_before_settling(self):
        cycle_id, card = self._generated_card("虛構結案回報品")

        resp = self.client.get(self._settle_url(cycle_id))

        data = resp.json()["data"]
        self.assertEqual(data["unhandled_cards"], {"count": 1, "names": [card["target"]]})

    def test_settle_now_post_reports_archived_cards(self):
        cycle_id, card = self._generated_card("虛構結案歸檔品")

        resp = self.client.post(self._settle_url(cycle_id))

        self.assertEqual(resp.status_code, 200, resp.text)
        body = resp.json()
        self.assertEqual(body["message"], "收帳完成，覆盤可以看了。")
        self.assertEqual(body["archived_cards"], {"count": 1, "names": [card["target"]]})

    def test_settle_now_with_no_unhandled_cards_makes_no_archive_claim(self):
        cycle_id = self._cycle_ready_for_reading("虛構結案無卡品")  # 沒呼叫 generate()

        get_resp = self.client.get(self._settle_url(cycle_id))
        self.assertEqual(get_resp.json()["data"]["unhandled_cards"], {"count": 0, "names": []})

        post_resp = self.client.post(self._settle_url(cycle_id))
        body = post_resp.json()
        self.assertEqual(body["archived_cards"], {"count": 0, "names": []})
        self.assertNotIn("歸檔", body["message"])
        touched = main.conn.execute(
            "SELECT COUNT(*) c FROM recommendation WHERE brand_id = %s AND campaign_cycle_id = %s"
            " AND recommendation_type = 'weekly_proposal'", (self.brand_id, cycle_id),
        ).fetchone()["c"]
        self.assertEqual(touched, 0)


if __name__ == "__main__":
    unittest.main()
