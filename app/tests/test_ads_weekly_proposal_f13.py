# -*- coding: utf-8 -*-
"""票 F13：週提案卡點名這期真的漏血的廣告，不是產品；歷史切角卡只在這期還在跑那個
角度時才出，不是另一期留下來的內部代號。

跟 `test_ads_weekly_proposal.py` 分開一個檔案（不是塞進去）：那檔已經 688 行，加這裡
所有新案例會撞 `test_architecture_boundaries.py::FILE_LINE_CAP`（800 行）——先拆再加，
不把它塞進 `KNOWN_OVERSIZED_FILES` 換綠燈（CLAUDE.md 鐵則：不准為了轉綠而放寬容忍清單）。
"""

import unittest
from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient

import app.main as main
from app.ads import performance
from app.ads import reading
from app.ads import repository as ads_repo
from app.ads import weekly_proposals
from app.brand_intelligence import repository as bi_repo
from app.core import db
from app.core.db import new_id, now_iso

ACTOR = "測試員"
TODAY = date(2026, 8, 14)



def _asset(name, *, spend, conversions, revenue, attributable=1, product_id=None):
    """比照 `test_ads_weekly_proposal.py::WeeklyProposalSelectionTest._asset`，多一個
    `product_id`（票 F13：`asset_totals()` 新增這欄，週提案卡要靠它把停掉卡點名到廣告）。"""
    row = {"pkg_id": f"pkg_{name}", "asset_name": name, "impressions": 50000,
           "clicks": 1000, "spend": spend, "conversions": conversions,
           "revenue": revenue, "attributable": attributable, "product_id": product_id}
    row["kpis"] = performance.compute_kpis(row)
    return row


def _seed_historical_cell(conn, brand_id: str, cycle_id: str, *, creative_angle: str,
                          spend: float, conversions: float, revenue: float) -> str:
    """建一條完整的 performance_snapshot → external_ad_mapping → publishing_package →
    experiment_cell 鏈（比照 test_ads_weekly_report_api.py 既有的 `_seed_cell`），讓
    `nextcycle.historical_cell_performance()` 真的讀得到這個切角——票 F13 done-check 4
    要走真的資料庫路徑，不能只靠手寫 dict 餵給 `select_cards()`。回傳 cell id。"""
    cell_id, pkg_id, mapping_id, ts = new_id("exc"), new_id("pkg"), new_id("xam"), now_iso()
    conn.execute(
        "INSERT INTO experiment_cell (id, org_id, campaign_cycle_id, brand_id, creative_angle,"
        " product_id, created_at) VALUES (%s, %s, %s, %s, %s, NULL, %s)",
        (cell_id, db.DEV_ORG_ID, cycle_id, brand_id, creative_angle, ts))
    conn.execute(
        "INSERT INTO publishing_package (id, org_id, brand_id, campaign_cycle_id, experiment_cell_id,"
        " campaign_name, adset_name, ad_name, destination_url, utm_json, status, created_at)"
        " VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, '{}', 'ready', %s)",
        (pkg_id, db.DEV_ORG_ID, brand_id, cycle_id, cell_id, "測試活動", "測試組合", f"{creative_angle}_ad",
         "https://example.test", ts))
    conn.execute(
        "INSERT INTO external_ad_mapping (id, org_id, brand_id, publishing_package_id,"
        " campaign_cycle_id, platform, claim_status, confirmed_by, confirmed_at, created_at)"
        " VALUES (%s, %s, %s, %s, %s, 'meta', 'confirmed', %s, %s, %s)",
        (mapping_id, db.DEV_ORG_ID, brand_id, pkg_id, cycle_id, ACTOR, ts, ts))
    conn.execute(
        "INSERT INTO performance_snapshot (id, org_id, brand_id, campaign_cycle_id, product_id,"
        " external_ad_mapping_id, platform, date_range_start, date_range_end, as_of_date,"
        " snapshot_taken_at, currency, spend, conversions, revenue, source, created_at)"
        " VALUES (%s, %s, %s, %s, NULL, %s, 'meta', '2026-01-01', '2026-01-07', '2026-01-07', %s, 'TWD',"
        " %s, %s, %s, 'manual', %s)",
        (new_id("psn"), db.DEV_ORG_ID, brand_id, cycle_id, mapping_id, ts, spend, conversions, revenue, ts))
    conn.commit()
    return cell_id


class ProductPauseCardNamesLosingAdsTest(unittest.TestCase):
    """done-check 1／2：產品層停掉卡點名底下真的漏血的廣告，且不編造歸屬。"""

    def test_product_pause_card_names_the_losing_ads_under_it(self):
        """B0-43：這張卡以前只點名產品（「Beast Gummy」），使用者在 Meta 後台找不到這個
        物件；現在要點名底下真的觸發停損的廣告，文案跟指示都要換掉。"""
        product_pause = [{"id": "prd_pause", "product_id": "prd_beast",
                          "product_name": "Beast Gummy", "status": "pause_candidate",
                          "result": {"reasons": ["這些產品要投報 1.42 倍才回本，這期是 0.86 倍"]}}]
        budget = {"current_budget": 10000, "proposed_budget": 8000}
        losing_assets = [
            _asset("買二送一_02_ad", spend=4000, conversions=12, revenue=3440,
                  product_id="prd_beast"),
            _asset("節慶禮盒_01_ad", spend=4000, conversions=12, revenue=3440,
                  product_id="prd_beast"),
            _asset("名人代言_03_ad", spend=4000, conversions=12, revenue=3440,
                  product_id="prd_beast"),
        ]

        cards = weekly_proposals.select_cards(
            product_pause, budget, [], losing_assets=losing_assets)

        self.assertEqual(len(cards), 1)
        card = cards[0]
        self.assertEqual(card["target"], "Beast Gummy")
        self.assertEqual(card["bleeding_asset_names"],
                         ["買二送一_02_ad", "節慶禮盒_01_ad", "名人代言_03_ad"])

        presented = weekly_proposals.present({**card, "id": "rec_x", "status": "GENERATED"}, "brd_x")
        self.assertIn("底下 3 支：買二送一_02_ad、節慶禮盒_01_ad、名人代言_03_ad", presented["copy"])
        self.assertIn("Beast Gummy", presented["copy"])

        accepted = weekly_proposals.present({**card, "id": "rec_x", "status": "ACCEPTED"}, "brd_x")
        self.assertIn("「買二送一_02_ad」「節慶禮盒_01_ad」「名人代言_03_ad」", accepted["action_card"])
        self.assertNotIn("找到「Beast Gummy」", accepted["action_card"])

    def test_product_pause_card_excludes_ads_with_no_or_different_product(self):
        """票 F13 反例（鐵則 16：不編造歸屬）：product_id 是 NULL、或屬於別的產品的廣告
        不能被算進這張卡；一支都對不上時，文案要跟今天一模一樣。"""
        product_pause = [{"id": "prd_pause", "product_id": "prd_beast",
                          "product_name": "Beast Gummy", "status": "pause_candidate",
                          "result": {"reasons": ["這些產品要投報 1.42 倍才回本，這期是 0.86 倍"]}}]
        budget = {"current_budget": 10000, "proposed_budget": 8000}
        losing_assets = [
            _asset("別產品_01_ad", spend=4000, conversions=12, revenue=3440, product_id="prd_other"),
            _asset("無歸屬_02_ad", spend=4000, conversions=12, revenue=3440, product_id=None),
        ]

        cards = weekly_proposals.select_cards(
            product_pause, budget, [], losing_assets=losing_assets)

        card = cards[0]
        self.assertNotIn("bleeding_asset_names", card)
        presented = weekly_proposals.present({**card, "id": "rec_x", "status": "GENERATED"}, "brd_x")
        self.assertEqual(presented["copy"],
                         "這些產品要投報 1.42 倍才回本，這期是 0.86 倍——建議停掉「Beast Gummy」。")


class HistoricalAngleCardRelevanceGateTest(unittest.TestCase):
    """done-check 3：歷史切角卡只在這期還在跑那個角度時才出。"""

    def test_historical_angle_card_only_survives_if_this_cycle_still_runs_it(self):
        """B0-42：判準只看這個角度是不是這期 experiment_cell.creative_angle 的其中一個，
        不對字串本身做「看起來像不像內部代號」的猜測（鐵則 16）。"""
        historical_cells = [{
            "experiment_cell_id": "exc_tired",
            "creative_angle": "bad_cvr",
            "spend": 3000,
            "conversions": 0,
            "underperforming": True,
        }]

        gone = weekly_proposals.select_cards(
            [], {}, historical_cells,
            current_cycle_angles={"節慶禮盒", "買二送一", "名人代言"})
        self.assertEqual(gone, [])

        still_running = weekly_proposals.select_cards(
            [], {}, historical_cells, current_cycle_angles={"bad_cvr", "節慶禮盒"})
        self.assertEqual(len(still_running), 1)
        self.assertEqual(still_running[0]["target"], "bad_cvr")


class GenerateEndToEndTest(unittest.TestCase):
    """done-check 4：C4 形狀走真的資料庫路徑，證明 (a)(b)(c) 接得起來。"""

    def setUp(self):
        self.client = TestClient(main.app)
        brand = bi_repo.create_brand(
            main.conn, name=f"虛構F13品牌{abs(hash(self.id())) % 100000}",
            client_name=None, actor=ACTOR)
        self.brand_id = brand["id"]

    def test_generate_end_to_end_names_this_cycles_ads_not_another_cycles_code(self):
        """產品層停掉卡要點名底下三支廣告；另一期留下來的 bad_cvr 這種內部代號一個都不能
        出現在卡片文案，也不能出現在結案確認要唸的名單裡（`unhandled_cards()` →
        ReviewStep.tsx unhandledNote）。"""
        product_id = bi_repo.create_product(
            main.conn, self.brand_id, name="Beast Gummy", actor=ACTOR)["id"]
        bi_repo.save_product_economics(
            main.conn, self.brand_id, product_id, selling_price=1000,
            unit_variable_cost=400, currency="TWD", confirmed_by=ACTOR, actor=ACTOR)

        # 上一期：只留下一個「bad_cvr」內部代號的舊切角，零轉換、花費已達停損門檻。
        prior_start = TODAY - timedelta(days=20)
        prior_cycle = ads_repo.create_cycle(
            main.conn, self.brand_id, product_ids=[], pain_value=2000,
            objective="sales", actor=ACTOR, start_date=prior_start.isoformat(), duration_days=7)
        main.conn.execute("UPDATE campaign_cycle SET budget = 2000 WHERE id = %s",
                          (prior_cycle["id"],))
        main.conn.commit()
        _seed_historical_cell(main.conn, self.brand_id, prior_cycle["id"],
                              creative_angle="bad_cvr", spend=2000, conversions=0, revenue=0)

        # 這期：三支廣告全部觸發停損、同屬一個產品；另外掛一個跟 bad_cvr 無關的這期切角，
        # 證明「這期還在跑的角度」這條線真的是靠這期 experiment_cell 對出來的，不是巧合。
        start, end = TODAY - timedelta(days=8), TODAY + timedelta(days=5)
        cycle = ads_repo.create_cycle(
            main.conn, self.brand_id, product_ids=[product_id], pain_value=12000,
            objective="sales", actor=ACTOR, start_date=start.isoformat(),
            duration_days=(end - start).days + 1)
        cycle_id = cycle["id"]
        main.conn.execute("UPDATE campaign_cycle SET budget = 12000 WHERE id = %s", (cycle_id,))
        ads_repo.update_cycle_status(main.conn, self.brand_id, cycle_id, status="LIVE", actor=ACTOR)
        _seed_historical_cell(main.conn, self.brand_id, cycle_id,
                              creative_angle="節慶禮盒", spend=1, conversions=0, revenue=0)

        # revenue 故意逐支遞減：asset_totals() 用 `ORDER BY revenue DESC`（reading_assets.py），
        # 逼出跟下面斷言相同的順序，不靠並列時剛好同序的巧合。
        ad_rows = [("買二送一_02_ad", 4000, 12, 3442), ("節慶禮盒_01_ad", 4000, 12, 3441),
                  ("名人代言_03_ad", 4000, 12, 3440)]
        ts = now_iso()
        for ad_name, *_rest in ad_rows:
            pkg_id, mapping_id = new_id("pkg"), new_id("xam")
            main.conn.execute(
                "INSERT INTO publishing_package (id, org_id, brand_id, campaign_cycle_id, product_id,"
                " campaign_name, adset_name, ad_name, destination_url, utm_json, status,"
                " created_at) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, '{}', 'ready', %s)",
                (pkg_id, db.DEV_ORG_ID, self.brand_id, cycle_id, product_id, "C4測試活動", "C4測試組合",
                 ad_name, "https://example.test", ts))
            main.conn.execute(
                "INSERT INTO external_ad_mapping (id, org_id, brand_id, publishing_package_id,"
                " campaign_cycle_id, platform, claim_status, confirmed_by, confirmed_at,"
                " created_at) VALUES (%s, %s, %s, %s, %s, 'meta', 'confirmed', %s, %s, %s)",
                (mapping_id, db.DEV_ORG_ID, self.brand_id, pkg_id, cycle_id, ACTOR, ts, ts))
        main.conn.commit()
        csv_text = ("行銷活動名稱,廣告名稱,曝光次數,連結點擊次數,花費金額,購買次數,購買轉換價值,頻率\n"
                    + "".join(f"C4測試活動,{n},50000,1000,{spend},{cv},{rev},1.8\n"
                              for n, spend, cv, rev in ad_rows))
        result = performance.import_csv(main.conn, self.brand_id, cycle_id, csv_text, actor=ACTOR)
        self.assertEqual(result.errors, [])
        # 產品層判讀要吃得到這筆成效才判得出 pause_candidate（比照既有 `_cycle_ready_for_reading`
        # 的既有寫法：CSV 匯入本身不知道要歸給哪個產品，這裡補上）。
        main.conn.execute(
            "UPDATE performance_snapshot SET product_id = %s WHERE brand_id = %s"
            " AND campaign_cycle_id = %s", (product_id, self.brand_id, cycle_id))
        main.conn.commit()

        ok, err = reading.run(main.conn, self.brand_id, cycle_id, ACTOR)
        self.assertEqual((ok, err), (True, None))

        cards = weekly_proposals.generate(main.conn, self.brand_id, cycle_id)

        stop_cards = [card for card in cards if card["action"] == "停掉"]
        self.assertEqual(len(stop_cards), 1)
        self.assertEqual(stop_cards[0]["target"], "Beast Gummy")
        self.assertEqual(stop_cards[0]["bleeding_asset_names"],
                         ["買二送一_02_ad", "節慶禮盒_01_ad", "名人代言_03_ad"])

        copies = "".join(weekly_proposals.present(card, self.brand_id)["copy"] for card in cards)
        self.assertIn("買二送一_02_ad", copies)
        self.assertIn("節慶禮盒_01_ad", copies)
        self.assertIn("名人代言_03_ad", copies)
        self.assertNotIn("bad_cvr", copies)
        self.assertNotIn("normal_", copies)

        summary = weekly_proposals.unhandled_cards(main.conn, self.brand_id, cycle_id)
        self.assertNotIn("bad_cvr", summary["names"])
        self.assertFalse(any(name.startswith("normal_") for name in summary["names"]))


if __name__ == "__main__":
    unittest.main()
