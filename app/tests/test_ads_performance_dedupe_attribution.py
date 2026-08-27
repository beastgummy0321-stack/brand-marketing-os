# -*- coding: utf-8 -*-
"""app/tests/test_ads_performance_dedupe_attribution.py — 票 11：檔期層去重與產品歸因。

獨立成檔而不是塞進 test_ads_performance.py：那個檔案已經頂到單檔行數上限（見
test_architecture_boundaries.py 的 FILE_LINE_CAP），加這兩個類別會超標。共用夾具
（_BaseImportTest／_CSV_ZH／ACTOR）直接從 test_ads_performance 匯入，不重寫一份
（比照 test_ads_sync_product_attribution.py 借用 test_ads_sync 夾具的先例）。
"""

import pytest

import app.main as main  # noqa: E402
from app.ads import performance as perf  # noqa: E402
from app.brand_intelligence import repository as bi_repo  # noqa: E402
from app.core import db  # noqa: E402
from app.tests.test_ads_performance import ACTOR, _CSV_ZH, _BaseImportTest  # noqa: E402




class CycleLevelDuplicateImportTest(_BaseImportTest):
    """票 11：檔期層快照過去不做重複匯入判斷。去重識別碼比照品牌層 issue #68，多帶
    「廣告名稱」——否則兩支還沒出量、數字都是 0 的不同廣告會被誤判成同一列而漏收一支。"""

    def test_duplicate_predicate_uses_ad_identity(self):
        first = perf.import_csv(main.conn, self.bid, self.cycle_id, _CSV_ZH, actor=ACTOR)
        self.assertEqual(first.imported, 1)
        second = perf.import_csv(main.conn, self.bid, self.cycle_id, _CSV_ZH, actor=ACTOR)
        self.assertEqual(second.imported, 0)
        self.assertEqual(second.skipped, 1)  # 誠實列出略過幾列
        self.assertEqual(len(perf.list_snapshots(main.conn, self.bid, self.cycle_id)), 1)

        # 澄清 1：另外兩支廣告數字一模一樣（都還沒出量），廣告名稱不同就不算重複。
        csv_text = ("行銷活動名稱,廣告名稱,曝光次數,連結點擊次數,花費金額,購買次數,購買轉換價值\n"
                   "測試活動,廣告A,0,0,0,0,0\n測試活動,廣告B,0,0,0,0,0\n")
        result = perf.import_csv(main.conn, self.bid, self.cycle_id, csv_text, actor=ACTOR)
        self.assertEqual(result.imported, 2)
        self.assertEqual(result.skipped, 0)

    def test_reimport_of_matched_ad_is_skipped(self):
        """對得回已授權素材的廣告（external_ad_mapping_id 不是 NULL）重複匯入也要擋——
        跟下一則「對不到素材」對照，證明兩種情況都不再靠 LEFT JOIN 反查名稱。"""
        pkg_id, ts = db.new_id("pkg"), db.now_utc()
        main.conn.execute(
            "INSERT INTO publishing_package (id, org_id, brand_id, campaign_cycle_id,"
            " campaign_name, adset_name, ad_name, destination_url, utm_json, status,"
            " created_at) VALUES (%s, %s, %s, %s, '測試活動', '測試組合', '廣告A',"
            " 'https://example.test', '{}', 'ready', %s)",
            (pkg_id, db.DEV_ORG_ID, self.bid, self.cycle_id, ts))
        main.conn.execute(
            "INSERT INTO external_ad_mapping (id, org_id, brand_id, publishing_package_id,"
            " campaign_cycle_id, platform, meta_campaign_id, claim_status, confirmed_by,"
            " confirmed_at, created_at) VALUES (%s, %s, %s, %s, %s, 'meta', 'c1', 'confirmed',"
            " %s, %s, %s)",
            (db.new_id("eam"), db.DEV_ORG_ID, self.bid, pkg_id, self.cycle_id, ACTOR, ts, ts))
        main.conn.commit()

        csv_text = "行銷活動名稱,廣告名稱,花費金額\n測試活動,廣告A,1000\n"
        first = perf.import_csv(main.conn, self.bid, self.cycle_id, csv_text, actor=ACTOR)
        self.assertEqual(first.imported, 1)
        self.assertIsNotNone(
            perf.list_snapshots(main.conn, self.bid, self.cycle_id)[0]["external_ad_mapping_id"])
        second = perf.import_csv(main.conn, self.bid, self.cycle_id, csv_text, actor=ACTOR)
        self.assertEqual((second.imported, second.skipped), (0, 1))
        self.assertEqual(len(perf.list_snapshots(main.conn, self.bid, self.cycle_id)), 1)

    def test_reimport_of_unmatched_ad_is_skipped(self):
        """票 11 blocker 1 就是修這個：對不到素材的廣告（external_ad_mapping_id 是
        NULL）過去靠 LEFT JOIN 反查名稱，這種列全部塌成空字串，兩次匯入永遠判不重複，
        灌水會一直持續下去。"""
        csv_text = "行銷活動名稱,廣告名稱,花費金額\n測試活動,廣告不存在,1000\n"
        first = perf.import_csv(main.conn, self.bid, self.cycle_id, csv_text, actor=ACTOR)
        self.assertEqual(first.imported, 1)
        self.assertIsNone(
            perf.list_snapshots(main.conn, self.bid, self.cycle_id)[0]["external_ad_mapping_id"])
        second = perf.import_csv(main.conn, self.bid, self.cycle_id, csv_text, actor=ACTOR)
        self.assertEqual((second.imported, second.skipped), (0, 1))
        self.assertEqual(len(perf.list_snapshots(main.conn, self.bid, self.cycle_id)), 1)


class ManualEntryDuplicateImportTest(_BaseImportTest):
    """票 11 覆審：手動填寫的豁免被使用者推翻——manual 走跟 CSV 一樣的去重判斷，
    不再整批跳過。剩餘缺口誠實留著：manual 沒有廣告名稱可比對，同一天填兩筆數字
    剛好相同的「不同」資料會被判成重複而略過；緩解是畫面把 skipped 秀出來
    （見 ManualRouteSkippedCountTest），不是假裝能分辨身分。"""

    def test_same_day_same_numbers_second_entry_is_skipped(self):
        first = perf.import_manual(main.conn, self.bid, self.cycle_id,
                                   {"spend": 5000, "impressions": 10000, "clicks": 200,
                                    "conversions": 5, "revenue": 20000}, actor=ACTOR)
        self.assertEqual((first.imported, first.skipped), (1, 0))

        second = perf.import_manual(main.conn, self.bid, self.cycle_id,
                                    {"spend": 5000, "impressions": 10000, "clicks": 200,
                                     "conversions": 5, "revenue": 20000}, actor=ACTOR)
        self.assertEqual((second.imported, second.skipped), (0, 1))
        rows = main.conn.execute(
            "SELECT COUNT(*) c FROM performance_snapshot WHERE brand_id = %s"
            " AND campaign_cycle_id = %s", (self.bid, self.cycle_id)).fetchone()
        self.assertEqual(rows["c"], 1)  # 資料庫裡只有一筆，沒有靜默疊加

    def test_different_dates_both_entries_land(self):
        """票 11 刪掉的豁免說詞本身就錯：manual 一定帶明確的 date_start/date_stop
        （見 routes_campaigns_performance_api.performance_manual），兩期日期不同，
        簽章自然不同，不需要豁免就能兩筆都收。"""
        first = perf.import_manual(main.conn, self.bid, self.cycle_id,
                                   {"spend": 5000, "date_start": "2026-01-01",
                                    "date_stop": "2026-01-07"}, actor=ACTOR)
        self.assertEqual((first.imported, first.skipped), (1, 0))

        second = perf.import_manual(main.conn, self.bid, self.cycle_id,
                                    {"spend": 5000, "date_start": "2026-01-08",
                                     "date_stop": "2026-01-14"}, actor=ACTOR)
        self.assertEqual((second.imported, second.skipped), (1, 0))
        rows = main.conn.execute(
            "SELECT COUNT(*) c FROM performance_snapshot WHERE brand_id = %s"
            " AND campaign_cycle_id = %s", (self.bid, self.cycle_id)).fetchone()
        self.assertEqual(rows["c"], 2)




class ManualRouteSkippedCountTest(_BaseImportTest):
    """票 11 D2：手動路由回應要跟 CSV 路由同一個形狀，讓面板能秀出跳過幾筆。"""

    def test_manual_route_reports_skipped_count_in_json_body(self):
        body = {"spend": "5000", "date_start": "2026-01-01", "date_stop": "2026-01-07"}
        first = self.client.post(
            f"/api/campaigns/{self.bid}/{self.cycle_id}/performance/manual", json=body)
        self.assertEqual(first.status_code, 200)
        self.assertEqual(first.json()["skipped"], 0)
        self.assertEqual(first.json()["imported"], 1)

        second = self.client.post(
            f"/api/campaigns/{self.bid}/{self.cycle_id}/performance/manual", json=body)
        self.assertEqual(second.status_code, 200)
        self.assertEqual(second.json()["skipped"], 1)
        self.assertEqual(second.json()["imported"], 0)


class ProductAttributionTest(_BaseImportTest):
    """票 11 D3：匯入時能確定產品才寫 product_id，模稜兩可一律 None（鐵則 16）。
    解析順序 a→b→NULL——選項 c「檔期只賣一個產品就算那個的」複審後拿掉了
    （見 performance.resolve_product_id 的說明），這裡不再測它。"""

    def _insert_package(self, ad_name: str, *, product_id=None, experiment_cell_id=None) -> str:
        pkg_id, ts = db.new_id("pkg"), db.now_utc()
        main.conn.execute(
            "INSERT INTO publishing_package (id, org_id, brand_id, campaign_cycle_id,"
            " experiment_cell_id, product_id, campaign_name, adset_name, ad_name,"
            " destination_url, utm_json, status, created_at)"
            " VALUES (%s, %s, %s, %s, %s, %s, '測試活動', '測試組合', %s, 'https://example.test',"
            " '{}', 'ready', %s)",
            (pkg_id, db.DEV_ORG_ID, self.bid, self.cycle_id, experiment_cell_id, product_id,
             ad_name, ts),
        )
        main.conn.commit()
        return pkg_id

    def _insert_experiment_cell(self, product_id: str) -> str:
        cell_id, ts = db.new_id("exc"), db.now_utc()
        main.conn.execute(
            "INSERT INTO experiment_cell (id, org_id, campaign_cycle_id, brand_id, product_id,"
            " created_at) VALUES (%s, %s, %s, %s, %s, %s)",
            (cell_id, db.DEV_ORG_ID, self.cycle_id, self.bid, product_id, ts),
        )
        main.conn.commit()
        return cell_id

    @staticmethod
    def _csv_for(ad_name: str, spend: int = 1000) -> str:
        return f"行銷活動名稱,廣告名稱,花費金額\n測試活動,{ad_name},{spend}\n"

    def test_option_a_packages_own_product_id_wins(self):
        product = bi_repo.create_product(main.conn, self.bid, name="虛構商品", actor=ACTOR)
        self._insert_package("廣告A", product_id=product["id"])
        perf.import_csv(main.conn, self.bid, self.cycle_id, self._csv_for("廣告A"), actor=ACTOR)
        row = perf.list_snapshots(main.conn, self.bid, self.cycle_id)[0]
        self.assertEqual(row["product_id"], product["id"])

    def test_option_b_falls_back_to_experiment_cell_product_id(self):
        """package 自己沒標 product_id，退回它掛的 experiment_cell 的 product_id。"""
        product = bi_repo.create_product(main.conn, self.bid, name="虛構商品二", actor=ACTOR)
        cell_id = self._insert_experiment_cell(product["id"])
        self._insert_package("廣告B", product_id=None, experiment_cell_id=cell_id)
        perf.import_csv(main.conn, self.bid, self.cycle_id, self._csv_for("廣告B"), actor=ACTOR)
        row = perf.list_snapshots(main.conn, self.bid, self.cycle_id)[0]
        self.assertEqual(row["product_id"], product["id"])

    def test_unmatched_ad_name_lands_null_and_import_still_succeeds(self):
        result = perf.import_csv(main.conn, self.bid, self.cycle_id,
                                 self._csv_for("廣告不存在"), actor=ACTOR)
        self.assertEqual(result.imported, 1)
        row = perf.list_snapshots(main.conn, self.bid, self.cycle_id)[0]
        self.assertIsNone(row["product_id"])
