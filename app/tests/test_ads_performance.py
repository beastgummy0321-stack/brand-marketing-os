"""app/tests/test_ads_performance.py — 廣告分支票 10：成效兩軌（CSV／手動）與 KPI。

決策 0016 硬性原則 2：兩軌正規化為同一格式，下游只認這一種。
⚠ CSV 別名表尚未用真實 Meta 匯出檔驗證（鐵則 11），使用者提供後要再校準。
"""

import unittest

from fastapi.testclient import TestClient

import app.main as main
from app.ads import performance as perf
from app.ads import reading
from app.brand_intelligence import repository as bi_repo
from app.core import db

ACTOR = "測試員"

# 繁體中文介面匯出的樣子（欄名帶幣別、數字帶千分位）
_CSV_ZH = """行銷活動名稱,報告開始,報告結束,曝光次數,連結點擊次數,花費金額 (TWD),購買次數,購買轉換價值
虛構檔期,2026-07-01,2026-07-14,"12,500",340,"5,000.50",12,"18,600"
"""

# 英文介面匯出的樣子（欄位順序不同）
_CSV_EN = """Reporting starts,Reporting ends,Campaign name,Amount spent (TWD),Impressions,Link clicks,Purchases,Purchases conversion value
2026-07-01,2026-07-14,Fictional cycle,3000,8000,210,5,9000
"""







class CsvParsingTest(unittest.TestCase):
    def test_reads_traditional_chinese_export(self):
        rows, result = perf.parse_csv(_CSV_ZH)
        self.assertEqual(result.errors, [])
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row["impressions"], 12500)
        self.assertEqual(row["clicks"], 340)
        self.assertEqual(row["spend"], 5000.5)
        self.assertEqual(row["conversions"], 12)
        self.assertEqual(row["revenue"], 18600)

    def test_reads_english_export_regardless_of_column_order(self):
        """認欄位的意思，不認順序——Meta 匯出的欄位順序會隨你勾什麼而變。"""
        rows, result = perf.parse_csv(_CSV_EN)
        self.assertEqual(result.errors, [])
        self.assertEqual(rows[0]["spend"], 3000)
        self.assertEqual(rows[0]["clicks"], 210)

    def test_currency_suffix_in_header_still_matches(self):
        mapping, _ = perf.match_columns(["花費金額 (TWD)", "Amount spent (USD)"])
        self.assertIn("spend", mapping)

    def test_bom_does_not_break_first_column(self):
        rows, result = perf.parse_csv("﻿" + _CSV_ZH)
        self.assertEqual(result.errors, [])
        self.assertEqual(len(rows), 1)

    def test_missing_spend_column_says_what_the_file_actually_has(self):
        """認不出必要欄位時不猜——告訴使用者檔案裡實際有什麼（鐵則 16）。"""
        rows, result = perf.parse_csv("行銷活動名稱,曝光次數\n測試,100\n")
        self.assertEqual(rows, [])
        self.assertIn("找不到「花費」欄位", result.errors[0])
        self.assertIn("曝光次數", result.errors[0])

    def test_empty_file_is_reported_plainly(self):
        _, result = perf.parse_csv("")
        self.assertIn("檔案是空的", result.errors[0])

    def test_summary_rows_without_campaign_are_skipped(self):
        csv_text = _CSV_ZH + ',,,,,,,\n'
        rows, result = perf.parse_csv(csv_text)
        self.assertEqual(len(rows), 1)
        self.assertEqual(result.errors, [])

    def test_dashes_and_blanks_become_none_not_zero(self):
        """空白不等於 0——沒有資料就是沒有資料，不能假裝成 0 拉低平均。"""
        csv_text = ("行銷活動名稱,花費金額,購買次數\n" "測試,1000,-\n")
        rows, _ = perf.parse_csv(csv_text)
        self.assertIsNone(rows[0]["conversions"])
        self.assertEqual(rows[0]["spend"], 1000)

    def test_result_type_text_column_does_not_steal_conversions_match(self):
        """「成果類型」是文字欄，「成果」才是轉換數的數字欄。單階段前綴比對會讓表頭順序
        一到「成果類型」排在「成果」前面時被誤配成 conversions（issue #23 bug 1）。"""
        headers = ["行銷活動名稱", "成果類型", "花費金額", "成果"]
        mapping, _ = perf.match_columns(headers)
        self.assertEqual(mapping["conversions"], "成果")
        self.assertNotIn("成果類型", mapping.values())

    def test_result_type_column_end_to_end(self):
        csv_text = "行銷活動名稱,成果類型,花費金額,成果\n測試,轉換,1000,25\n"
        rows, result = perf.parse_csv(csv_text)
        self.assertEqual(result.errors, [])
        self.assertEqual(rows[0]["conversions"], 25)

    def test_date_aliases_include_analysis_report_wording(self):
        """issue #23 bug 3：補「分析報告開始／結束」別名。"""
        mapping, _ = perf.match_columns(["分析報告開始", "分析報告結束", "花費金額"])
        self.assertEqual(mapping["date_start"], "分析報告開始")
        self.assertEqual(mapping["date_stop"], "分析報告結束")

    def test_duplicate_header_names_do_not_scramble_data(self):
        """Meta 匯出檔「廣告組合名稱」曾重複出現兩次；csv.DictReader 預設後蓋前，
        其中一欄的資料會整批消失（issue #23 bug 5）。"""
        csv_text = ("廣告組合名稱,花費金額,廣告組合名稱\n"
                    "第一欄的組合名,1000,第二欄的組合名\n")
        rows, result = perf.parse_csv(csv_text)
        self.assertEqual(result.errors, [])
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["spend"], 1000)
        self.assertIsNotNone(rows[0]["adset_name"])

    def test_roas_direct_column_is_recognised_and_does_not_steal_conversions(self):
        """真實檔驗證回饋：有些樣板沒有 revenue 欄，只有算好的「成果 ROAS」欄。
        要認得這欄，但不能讓它或「成果」互搶（兩階段完全相等優先）。"""
        mapping, _ = perf.match_columns(["成果類型", "成果", "成果 ROAS", "花費金額"])
        self.assertEqual(mapping["conversions"], "成果")
        self.assertEqual(mapping["roas_direct"], "成果 ROAS")

    def test_reach_count_is_not_stolen_by_impressions(self):
        """自檢（票 03-add-reach-metric）：「觸及次數」曾被誤列為 impressions 的別名，
        加了 reach 概念欄之後必須配到 reach，不能再把觸及資料算成曝光。"""
        headers = ["行銷活動名稱", "曝光次數", "觸及次數", "花費金額"]
        mapping, unmatched = perf.match_columns(headers)
        self.assertEqual(mapping["impressions"], "曝光次數")
        self.assertEqual(mapping["reach"], "觸及次數")
        self.assertEqual(unmatched, [])

    def test_reach_alone_is_not_stolen_by_impressions(self):
        """自檢（票 03 收尾）：上面那條「兩欄並存」的測試只驗『各歸各位』，
        不會重現真 bug——「曝光次數」排在別名清單較前面，掃到「觸及次數」之前就先
        配對成功跳出，「觸及次數」根本沒機會被搶。真正重現搶配的組合是「只有
        觸及次數、沒有曝光次數」：若「觸及次數」被誤列回 impressions 別名，
        impressions 會先搶到它，reach 完全配不到。"""
        headers = ["行銷活動名稱", "觸及次數", "花費金額"]
        mapping, unmatched = perf.match_columns(headers)
        self.assertEqual(mapping.get("reach"), "觸及次數")
        self.assertNotIn("impressions", mapping)

    def test_column_aliases_have_no_cross_concept_collisions(self):
        """結構性防線：同一個別名字串不得同時出現在兩個以上的概念欄清單裡。
        擋的是整類問題，不只 reach／impressions 這一組——別名表本身違反了
        「一個表頭只能是一個概念」的前提，才會讓誰先搶到全看 dict 掃描順序。"""
        seen = {}
        collisions = []
        for concept, aliases in perf.COLUMN_ALIASES.items():
            for alias in aliases:
                norm = perf._norm(alias)
                if norm in seen and seen[norm] != concept:
                    collisions.append((norm, seen[norm], concept))
                else:
                    seen[norm] = concept
        self.assertEqual(collisions, [])

    def test_reach_official_export_alias_is_recognised(self):
        """Meta 正式匯出欄名是「觸及人數」。"""
        mapping, _ = perf.match_columns(["觸及人數", "花費金額"])
        self.assertEqual(mapping["reach"], "觸及人數")

    def test_reach_column_parses_as_integer(self):
        csv_text = "行銷活動名稱,花費金額,觸及人數\n測試,1000,\"8,500\"\n"
        rows, result = perf.parse_csv(csv_text)
        self.assertEqual(result.errors, [])
        self.assertEqual(rows[0]["reach"], 8500)


class KpiTest(unittest.TestCase):
    def test_computes_the_four_numbers(self):
        kpis = perf.compute_kpis({"impressions": 10000, "clicks": 200, "spend": 4000,
                                  "conversions": 10, "revenue": 12000})
        self.assertEqual(kpis["ctr"], 0.02)
        self.assertEqual(kpis["cpc"], 20.0)
        self.assertEqual(kpis["cpa"], 400.0)
        self.assertEqual(kpis["roas"], 3.0)

    def test_zero_denominator_gives_none_not_zero(self):
        """「算不出來」跟「等於 0」是兩件事，混為一談會讓人誤判。"""
        kpis = perf.compute_kpis({"impressions": 0, "clicks": 0, "spend": 1000,
                                  "conversions": 0, "revenue": 0})
        self.assertIsNone(kpis["ctr"])
        self.assertIsNone(kpis["cpa"])
        self.assertEqual(kpis["roas"], 0.0)  # 有花費、沒營收 → 投報率確實是 0

    def test_roas_is_none_without_any_revenue_data(self):
        """完全沒收集到營收資料（revenue 是 None）時 roas 要回 None，不能假裝算成 0——
        「沒收集」跟「收集到是 0」是兩回事（issue #23 bug 2）。"""
        kpis = perf.compute_kpis({"spend": 1000, "clicks": 10})
        self.assertIsNone(kpis["roas"])

    def test_cpm_and_cvr_are_computed(self):
        """票 C2-01：瓶頸判斷樹要拆 CPA 恆等式，缺這兩個 KPI 就拿不到基線。"""
        kpis = perf.compute_kpis({"impressions": 10000, "clicks": 200, "spend": 4000,
                                  "conversions": 10, "revenue": 12000})
        self.assertEqual(kpis["cpm"], 400.0)
        self.assertEqual(kpis["cvr"], 0.05)

    def test_cpm_and_cvr_zero_denominator_gives_none_not_zero(self):
        """分母為 0 一律回 None，跟既有四個同一條規則（鐵則 16）。"""
        kpis = perf.compute_kpis({"impressions": 0, "clicks": 0, "spend": 1000,
                                  "conversions": 0, "revenue": 0})
        self.assertIsNone(kpis["cpm"])
        self.assertIsNone(kpis["cvr"])


class _BaseImportTest(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(main.app)
        self.brand = bi_repo.create_brand(main.conn, name="虛構晨光咖啡",
                                          client_name=None, actor=ACTOR, org_id=db.DEV_ORG_ID)
        self.bid = self.brand["id"]
        resp = self.client.post(f"/api/campaigns/{self.bid}",
                                json={"product_ids": [], "budget": 10000, "objective": "sales"})
        self.cycle_id = resp.json()["cycle_id"]


class CsvImportTest(_BaseImportTest):
    def test_import_lands_in_the_shared_normalised_columns(self):
        result = perf.import_csv(main.conn, self.bid, self.cycle_id, _CSV_ZH, actor=ACTOR)
        self.assertEqual(result.imported, 1)
        row = perf.list_snapshots(main.conn, self.bid, self.cycle_id)[0]
        self.assertEqual(row["source"], "csv")
        self.assertEqual(row["spend"], 5000.5)
        self.assertEqual(row["clicks"], 340)
        # 票 11：raw_json 現在存原始解析列（去重判斷要用），判讀仍然只讀正規化欄位，
        # 不受影響（module docstring 那句話說的是判讀，不是匯入不寫）。
        self.assertEqual(row["raw_json"]["campaign_name"], "虛構檔期")  # psycopg 已自動解 jsonb

    def test_reach_column_lands_separately_from_impressions(self):
        csv_text = ("行銷活動名稱,曝光次數,觸及人數,花費金額\n"
                    "測試,12500,9800,5000\n")
        result = perf.import_csv(main.conn, self.bid, self.cycle_id, csv_text, actor=ACTOR)
        self.assertEqual(result.imported, 1)
        row = perf.list_snapshots(main.conn, self.bid, self.cycle_id)[0]
        self.assertEqual(row["impressions"], 12500)
        self.assertEqual(row["reach"], 9800)  # 兩個概念欄各自落地，觸及沒有蓋掉曝光

    def test_missing_reach_column_does_not_block_import(self):
        """缺觸及欄不擋匯入——只有花費是必填。"""
        result = perf.import_csv(main.conn, self.bid, self.cycle_id, _CSV_ZH, actor=ACTOR)
        self.assertEqual(result.errors, [])
        row = perf.list_snapshots(main.conn, self.bid, self.cycle_id)[0]
        self.assertIsNone(row["reach"])  # 沒收到跟收到 0 是兩件事（鐵則 16）

    def test_import_succeeds_without_errors(self):
        """原本打「上傳頁」POST /csv；那頁與這條路由已隨 T4 大清倉刪除（改直測業務層
        `perf.import_csv`），斷言意義不變：成功匯入不出錯，落地一筆快照。"""
        result = perf.import_csv(main.conn, self.bid, self.cycle_id, _CSV_ZH, actor=ACTOR)
        self.assertEqual(result.errors, [])
        self.assertEqual(len(perf.list_snapshots(main.conn, self.bid, self.cycle_id)), 1)

    def test_bom_prefixed_csv_imports_without_errors(self):
        """原本測「Excel 匯出的 UTF-8 BOM 檔案上傳」；上傳頁已刪，改直測完整匯入流程
        （parse_csv 本身的 BOM 處理已有 CsvParsingTest.test_bom_does_not_break_first_column
        覆蓋，這條額外驗證 BOM 前綴的文字一路匯入落地也不出錯）。"""
        result = perf.import_csv(main.conn, self.bid, self.cycle_id, "﻿" + _CSV_ZH,
                                 actor=ACTOR)
        self.assertEqual(result.errors, [])
        self.assertEqual(len(perf.list_snapshots(main.conn, self.bid, self.cycle_id)), 1)

    def test_bad_file_gives_plain_message_and_imports_nothing(self):
        """原本打 HTTP 表單看轉址 kind=warn；表單已刪，改直測業務層回傳的錯誤訊息。"""
        result = perf.import_csv(main.conn, self.bid, self.cycle_id, "這不是 CSV", actor=ACTOR)
        self.assertTrue(result.errors)
        self.assertEqual(perf.list_snapshots(main.conn, self.bid, self.cycle_id), [])

    def test_snapshots_accumulate_never_overwrite(self):
        """票 11 改了契約：檔期層現在也做內容去重（理由見 CycleLevelDuplicateImportTest）。
        這份 CSV 沒有廣告名稱欄，兩次匯入內容完全相同，第二次視為重複整批略過。"""
        first = perf.import_csv(main.conn, self.bid, self.cycle_id, _CSV_ZH, actor=ACTOR)
        self.assertEqual(first.imported, 1)
        second = perf.import_csv(main.conn, self.bid, self.cycle_id, _CSV_ZH, actor=ACTOR)
        self.assertEqual((second.imported, second.skipped), (0, 1))
        self.assertEqual(len(perf.list_snapshots(main.conn, self.bid, self.cycle_id)), 1)

    def test_csv_upload_without_date_columns_uses_today_not_blank(self):
        """匯入時 CSV 沒有日期欄，退回今天的日期，而不是空字串（issue #23 bug 4）。
        原本打 HTTP 上傳表單（route 本身就是原樣呼叫 perf.import_csv 並帶入
        today=date.today()，見已刪除的 ads_performance_csv）；表單已刪，改直測業務層，
        照樣帶入 today 參數，斷言意義不變。"""
        from datetime import date
        csv_text = "行銷活動名稱,花費金額\n測試,1000\n"
        result = perf.import_csv(main.conn, self.bid, self.cycle_id, csv_text, actor=ACTOR,
                                 today=date.today().isoformat())
        self.assertEqual(result.errors, [])
        row = perf.list_snapshots(main.conn, self.bid, self.cycle_id)[0]
        self.assertEqual(row["date_range_start"], date.today())

    def test_totals_roas_is_none_when_no_revenue_data_at_all(self):
        """匯入的資料完全沒有營收欄時，加總後的 roas 要回 None（issue #23 bug 2）。"""
        csv_text = "行銷活動名稱,花費金額\n測試,1000\n"
        perf.import_csv(main.conn, self.bid, self.cycle_id, csv_text, actor=ACTOR)
        summary = perf.totals(main.conn, self.bid, self.cycle_id)
        self.assertIsNone(summary["kpis"]["roas"])
        self.assertEqual(summary["revenue"], 0)  # 顯示總額仍是 0，不是 None（避免模板格式化炸掉）


class MixedGranularityTotalsTest(_BaseImportTest):
    def _snapshot(self, start: str, end: str, spend: float, clicks: int):
        ts = db.now_utc()
        main.conn.execute(
            "INSERT INTO performance_snapshot (id, org_id, brand_id, campaign_cycle_id, platform,"
            " account_id, meta_campaign_id, meta_adset_id, meta_ad_id, date_range_start,"
            " date_range_end, as_of_date, snapshot_taken_at, currency, impressions, clicks,"
            " spend, conversions, revenue, reconciled, source, quarantined, created_at)"
            " VALUES (%s, %s, %s, %s, 'meta', 'act_1', 'cmp_1', 'set_1', 'ad_1', %s, %s, %s, %s,"
            " 'TWD', 100, %s, %s, 1, 1000, true, 'meta_api', false, %s)",
            (db.new_id("psn"), db.DEV_ORG_ID, self.bid, self.cycle_id, start, end, end, ts,
             clicks, spend, ts),
        )
        main.conn.commit()

    def test_daily_rows_supersede_overlapping_old_aggregate(self):
        self._snapshot("2026-08-01", "2026-08-02", 300, 30)
        self._snapshot("2026-08-01", "2026-08-01", 100, 10)
        self._snapshot("2026-08-02", "2026-08-02", 200, 20)

        totals = perf.totals(main.conn, self.bid, self.cycle_id)

        self.assertEqual(totals["rows"], 2)
        self.assertEqual(totals["spend"], 300)
        self.assertEqual(totals["clicks"], 30)


class RoasDirectImportTest(_BaseImportTest):
    """真實檔驗證回饋：使用者的 Meta 樣板沒有 revenue 欄，只有算好的「成果 ROAS」欄。"""

    def test_revenue_is_derived_from_roas_direct_when_missing(self):
        csv_text = "行銷活動名稱,花費金額,購買次數,成果 ROAS\n虛構檔期,1000,5,1.342\n"
        result = perf.import_csv(main.conn, self.bid, self.cycle_id, csv_text, actor=ACTOR)
        self.assertEqual(result.imported, 1)
        row = perf.list_snapshots(main.conn, self.bid, self.cycle_id)[0]
        self.assertAlmostEqual(row["revenue"], 1342.0, places=2)  # 1000 * 1.342 反推
        kpis = perf.compute_kpis({"spend": row["spend"], "revenue": row["revenue"]})
        self.assertAlmostEqual(kpis["roas"], 1.342, places=2)  # 算回去要等於原始 ROAS

    def test_row_without_roas_direct_value_stays_none(self):
        csv_text = "行銷活動名稱,花費金額,購買次數,成果 ROAS\n虛構檔期,2000,0,\n"
        perf.import_csv(main.conn, self.bid, self.cycle_id, csv_text, actor=ACTOR)
        row = perf.list_snapshots(main.conn, self.bid, self.cycle_id)[0]
        self.assertIsNone(row["revenue"])  # ROAS 欄也空，誠實維持 None，不硬塞 0

    def test_actual_revenue_column_takes_priority_over_roas_direct(self):
        csv_text = "行銷活動名稱,花費金額,購買轉換價值,成果 ROAS\n虛構檔期,1000,5000,1.342\n"
        perf.import_csv(main.conn, self.bid, self.cycle_id, csv_text, actor=ACTOR)
        row = perf.list_snapshots(main.conn, self.bid, self.cycle_id)[0]
        self.assertEqual(row["revenue"], 5000)  # 真的 revenue 欄優先，roas_direct 不覆蓋


class SanityGateTest(_BaseImportTest):
    def test_impossible_row_is_quarantined_not_counted(self):
        csv_text = ("行銷活動名稱,曝光次數,連結點擊次數,花費金額\n" "測試,100,500,1000\n")
        result = perf.import_csv(main.conn, self.bid, self.cycle_id, csv_text, actor=ACTOR)
        self.assertEqual(result.quarantined, 1)
        summary = perf.totals(main.conn, self.bid, self.cycle_id)
        self.assertEqual(summary["rows"], 0)          # 不列入計算
        self.assertEqual(len(perf.list_snapshots(main.conn, self.bid, self.cycle_id)), 1)  # 但看得到

    def test_negative_spend_is_quarantined(self):
        csv_text = "行銷活動名稱,花費金額\n測試,-500\n"
        result = perf.import_csv(main.conn, self.bid, self.cycle_id, csv_text, actor=ACTOR)
        self.assertEqual(result.quarantined, 1)

    def test_api_reports_how_many_were_set_aside(self):
        """原本打 HTTP 舊頁斷言 page.text 含「擱在一旁」；那頁已刪，改打取代它的 React
        資料來源 `/api/campaigns/.../performance`——`discarded_rows` 就是同一個數字
        （前端 PerformanceStep.tsx 用它顯示「已被系統擱置不列入計算」，措辭不同但意義
        相同：使用者看得到有幾筆被擱置）。搭一筆正常列，讓 summary 不因為全數被擱置而
        整包回 null（那是另一種「資料不足」空狀態，不是本測試要驗的東西）。"""
        csv_text = ("行銷活動名稱,曝光次數,連結點擊次數,花費金額\n"
                   "正常,1000,50,500\n異常,100,500,1000\n")
        perf.import_csv(main.conn, self.bid, self.cycle_id, csv_text, actor=ACTOR)
        resp = self.client.get(f"/api/campaigns/{self.bid}/{self.cycle_id}/performance")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["data"]["summary"]["discarded_rows"], 1)


class ManualEntryTest(_BaseImportTest):
    """原本每個測試都打 HTTP 表單 POST /manual；那條路由（連同成效頁）已隨 T4 大清倉
    刪除（React 沒有手動填寫入口，見 PerformanceStep.tsx 檔頭註解），改直測業務層
    `perf.import_manual`（表單路由本來就只是原樣轉呼叫這個函式），斷言意義不變。"""

    def test_manual_entry_shares_the_same_format(self):
        result = perf.import_manual(
            main.conn, self.bid, self.cycle_id,
            {"spend": 3000, "clicks": 120, "impressions": 9000, "conversions": 4,
             "revenue": 7200}, actor=ACTOR)
        self.assertEqual(result.errors, [])
        row = perf.list_snapshots(main.conn, self.bid, self.cycle_id)[0]
        self.assertEqual(row["source"], "manual")
        self.assertEqual(row["spend"], 3000)
        summary = perf.totals(main.conn, self.bid, self.cycle_id)
        self.assertEqual(summary["kpis"]["roas"], 2.4)

    def test_manual_entry_accepts_reach(self):
        result = perf.import_manual(
            main.conn, self.bid, self.cycle_id,
            {"spend": 3000, "impressions": 9000, "reach": 6500}, actor=ACTOR)
        self.assertEqual(result.errors, [])
        row = perf.list_snapshots(main.conn, self.bid, self.cycle_id)[0]
        self.assertEqual(row["reach"], 6500)
        self.assertEqual(row["impressions"], 9000)

    def test_spend_is_required(self):
        result = perf.import_manual(main.conn, self.bid, self.cycle_id,
                                    {"clicks": 10}, actor=ACTOR)
        self.assertTrue(result.errors)
        self.assertEqual(perf.list_snapshots(main.conn, self.bid, self.cycle_id), [])

    def test_non_numeric_input_is_refused_politely(self):
        """原本打 HTTP 表單驗證非數字輸入；那條表單路由已刪，真正做這件事的驗證函式是
        `main_mod.parse_number`（表單提交前呼叫，仍在用——見 app/orders/routes_api.py
        等其他 /api 端點），直測它政策不變：非數字輸入回報 ok=False。"""
        value, ok = main.parse_number("五千")
        self.assertFalse(ok)
        self.assertIsNone(value)

    def test_derived_metrics_are_stored_for_traceability(self):
        """表單路由做兩件事：import_manual 落地快照，再呼叫 save_derived_metrics 存
        derived_metric——直測業務層要照樣做這兩步，才是同一件事的重寫而不是少測一半。"""
        perf.import_manual(
            main.conn, self.bid, self.cycle_id,
            {"spend": 3000, "clicks": 120, "impressions": 9000, "conversions": 4,
             "revenue": 7200}, actor=ACTOR)
        perf.save_derived_metrics(main.conn, self.bid, self.cycle_id)
        rows = main.conn.execute(
            "SELECT metric, value FROM derived_metric WHERE campaign_cycle_id = %s",
            (self.cycle_id,)).fetchall()
        metrics = {r["metric"]: r["value"] for r in rows}
        self.assertEqual(metrics["roas"], 2.4)
        self.assertEqual(metrics["cpa"], 750.0)

    def test_api_reports_insufficient_kpis_as_none_rather_than_zero(self):
        """原本打 HTTP 舊頁斷言 page.text 含「資料不足」；那頁已刪，改打取代它的 React
        資料來源 `/api/campaigns/.../performance`——`kpis.*` 算不出來時回 None，前端
        PerformanceStep.tsx 的 `value ?? "資料不足"` 正是靠這個 None 才顯示「資料不足」
        而不是 0，斷言意義不變。"""
        perf.import_manual(main.conn, self.bid, self.cycle_id, {"spend": 3000}, actor=ACTOR)
        resp = self.client.get(f"/api/campaigns/{self.bid}/{self.cycle_id}/performance")
        kpis = resp.json()["data"]["summary"]["kpis"]
        self.assertIsNone(kpis["ctr"])
        self.assertIsNone(kpis["cpa"])
        self.assertIsNone(kpis["roas"])


class AssetAttributionTest(_BaseImportTest):
    """修憲落地 G2（決策 0035 第二節第 4 點）：CSV 的「廣告名稱」欄對回交接包的 ad_name，
    對得上且已完成關卡三具名授權才寫 external_ad_mapping_id；對不上就誠實降級成檔期層，
    不得用相似字串猜。"""

    def _insert_package(self, ad_name: str) -> str:
        pkg_id = db.new_id("pkg")
        ts = db.now_utc()
        main.conn.execute(
            "INSERT INTO publishing_package (id, org_id, brand_id, campaign_cycle_id,"
            " campaign_name, adset_name, ad_name, destination_url, utm_json, status,"
            " created_at) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, '{}', 'ready', %s)",
            (pkg_id, db.DEV_ORG_ID, self.bid, self.cycle_id, "測試活動", "測試組合", ad_name,
             "https://example.test", ts),
        )
        main.conn.commit()
        return pkg_id

    def _insert_mapping(self, pkg_id: str) -> str:
        mapping_id = db.new_id("xam")
        ts = db.now_utc()
        main.conn.execute(
            "INSERT INTO external_ad_mapping (id, org_id, brand_id, publishing_package_id,"
            " campaign_cycle_id, platform, claim_status, confirmed_by, confirmed_at,"
            " created_at) VALUES (%s, %s, %s, %s, %s, 'meta', 'confirmed', %s, %s, %s)",
            (mapping_id, db.DEV_ORG_ID, self.bid, pkg_id, self.cycle_id, ACTOR, ts, ts),
        )
        main.conn.commit()
        return mapping_id

    def test_matching_ad_name_attributes_to_the_authorised_asset(self):
        pkg_id = self._insert_package("拿證據說話_01_ad")
        mapping_id = self._insert_mapping(pkg_id)
        csv_text = ("行銷活動名稱,廣告名稱,曝光次數,連結點擊次數,花費金額,購買次數,購買轉換價值\n"
                   "測試活動,拿證據說話_01_ad,12500,340,5000,12,18600\n")
        result = perf.import_csv(main.conn, self.bid, self.cycle_id, csv_text, actor=ACTOR)
        self.assertEqual(result.imported, 1)
        row = perf.list_snapshots(main.conn, self.bid, self.cycle_id)[0]
        self.assertEqual(row["external_ad_mapping_id"], mapping_id)

    def test_ad_name_not_yet_authorised_downgrades_honestly(self):
        """對回的交接包還沒走過關卡三具名授權（沒有 external_ad_mapping），不得假造一筆
        授權——誠實降級成檔期層（external_ad_mapping_id 留空）。"""
        self._insert_package("拿證據說話_01_ad")
        csv_text = ("行銷活動名稱,廣告名稱,曝光次數,連結點擊次數,花費金額,購買次數,購買轉換價值\n"
                   "測試活動,拿證據說話_01_ad,12500,340,5000,12,18600\n")
        perf.import_csv(main.conn, self.bid, self.cycle_id, csv_text, actor=ACTOR)
        row = perf.list_snapshots(main.conn, self.bid, self.cycle_id)[0]
        self.assertIsNone(row["external_ad_mapping_id"])

    def test_renamed_ad_name_does_not_get_guessed(self):
        """使用者在 Meta 上手改過廣告名稱，對不上就是對不上，不做相似字串猜測。"""
        pkg_id = self._insert_package("拿證據說話_01_ad")
        self._insert_mapping(pkg_id)
        csv_text = ("行銷活動名稱,廣告名稱,曝光次數,連結點擊次數,花費金額,購買次數,購買轉換價值\n"
                   "測試活動,拿證據說話_01_ad（改過）,12500,340,5000,12,18600\n")
        perf.import_csv(main.conn, self.bid, self.cycle_id, csv_text, actor=ACTOR)
        row = perf.list_snapshots(main.conn, self.bid, self.cycle_id)[0]
        self.assertIsNone(row["external_ad_mapping_id"])

    def test_missing_ad_name_column_still_imports_at_cycle_level(self):
        """沒有廣告名稱欄的舊格式檔案照樣匯得進來，只是沒有素材層資料（既有行為不變）。"""
        result = perf.import_csv(main.conn, self.bid, self.cycle_id, _CSV_ZH, actor=ACTOR)
        self.assertEqual(result.imported, 1)
        row = perf.list_snapshots(main.conn, self.bid, self.cycle_id)[0]
        self.assertIsNone(row["external_ad_mapping_id"])


class PerformanceIsolationTest(_BaseImportTest):
    def test_other_brand_sees_nothing(self):
        perf.import_csv(main.conn, self.bid, self.cycle_id, _CSV_ZH, actor=ACTOR)
        other = bi_repo.create_brand(main.conn, name="虛構隔壁烘焙2", client_name=None,
                                     actor=ACTOR, org_id=db.DEV_ORG_ID)["id"]
        self.assertEqual(perf.list_snapshots(main.conn, other, self.cycle_id), [])
        self.assertEqual(perf.totals(main.conn, other, self.cycle_id)["rows"], 0)


class BrandLevelHistoryTest(_BaseImportTest):
    """票 F2（決策 0039 第 7、8、10 條）：舊廣告／CSV 對不到檔期的成效轉品牌層
    （campaign_cycle_id=NULL），只算點擊面，粒度＝每月一列。"""

    def _insert_brand_level_snapshot(self, as_of_date, *, clicks, impressions, spend,
                                     conversions):
        sid = db.new_id("psn")
        ts = db.now_utc()
        main.conn.execute(
            "INSERT INTO performance_snapshot (id, org_id, brand_id, campaign_cycle_id,"
            " platform, date_range_start, date_range_end, as_of_date, snapshot_taken_at,"
            " currency, impressions, clicks, spend, conversions, reconciled, source,"
            " quarantined, created_at)"
            " VALUES (%s, %s, %s, NULL, 'meta', %s, %s, %s, %s, 'TWD', %s, %s, %s, %s, true,"
            " 'meta_api', false, %s)",
            (sid, db.DEV_ORG_ID, self.bid, as_of_date, as_of_date, as_of_date, ts,
             impressions, clicks, spend, conversions, ts),
        )
        main.conn.commit()
        return sid

    def test_brand_level_rows_feed_the_baseline_median(self):
        """①認領後（或任何品牌層寫入之後）brand_baseline() 要看得到舊資料的中位數
        （測試造 12 個月假資料）。"""
        for i in range(1, 13):
            self._insert_brand_level_snapshot(
                f"2025-{i:02d}-15", clicks=100 + i, impressions=10000,
                spend=1000 + i * 10, conversions=5 + (i % 3))
        written = perf.save_brand_level_derived_metrics(main.conn, self.bid)
        self.assertEqual(written, 36)  # 12 個月 × 3 項指標

        baseline = reading.brand_baseline(main.conn, self.bid)
        self.assertIn("cpc", baseline)
        self.assertIn("ctr", baseline)
        self.assertIn("cvr", baseline)

    def test_amount_metrics_are_excluded_from_the_median(self):
        """②金額面（roas/revenue）中位數不含品牌層列——這裡根本不寫這兩個 metric。"""
        self._insert_brand_level_snapshot("2025-01-15", clicks=100, impressions=10000,
                                          spend=1000, conversions=5)
        perf.save_brand_level_derived_metrics(main.conn, self.bid)
        rows = main.conn.execute(
            "SELECT metric FROM derived_metric WHERE brand_id = %s AND campaign_cycle_id IS NULL",
            (self.bid,)).fetchall()
        metrics = {r["metric"] for r in rows}
        self.assertEqual(metrics, {"cpc", "ctr", "cvr"})

    def test_brand_level_totals_labels_roas_as_unreconciled_reference(self):
        """⑤舊廣告 ROAS／營收在其檢視處標示「未對帳參考值」。"""
        self._insert_brand_level_snapshot("2025-01-15", clicks=100, impressions=10000,
                                          spend=1000, conversions=5)
        totals = perf.brand_level_totals(main.conn, self.bid)
        self.assertIn("未對帳", totals["unreconciled_note"])
        self.assertEqual(totals["spend"], 1000)

    def test_recompute_is_idempotent(self):
        """全量重算：重複呼叫不會疊加出重複列。"""
        self._insert_brand_level_snapshot("2025-01-15", clicks=100, impressions=10000,
                                          spend=1000, conversions=5)
        perf.save_brand_level_derived_metrics(main.conn, self.bid)
        perf.save_brand_level_derived_metrics(main.conn, self.bid)
        count = main.conn.execute(
            "SELECT COUNT(*) c FROM derived_metric WHERE brand_id = %s AND campaign_cycle_id IS NULL",
            (self.bid,)).fetchone()["c"]
        self.assertEqual(count, 3)

    def test_cycle_scoped_pages_never_see_brand_level_rows(self):
        """④無檔期列在檔期相關頁面不出現。"""
        self._insert_brand_level_snapshot("2025-01-15", clicks=100, impressions=10000,
                                          spend=1000, conversions=5)
        self.assertEqual(perf.list_snapshots(main.conn, self.bid, self.cycle_id), [])
        self.assertEqual(perf.totals(main.conn, self.bid, self.cycle_id)["rows"], 0)

    def test_monthly_key_uses_data_period_not_as_of_date(self):
        """issue #70②：分月鍵用資料期間（date_range），不是 as_of_date——即使
        as_of_date 被誤植成別的月份，分組仍要照 date_range_end 走。"""
        sid = db.new_id("psn")
        ts = db.now_utc()
        main.conn.execute(
            "INSERT INTO performance_snapshot (id, org_id, brand_id, campaign_cycle_id,"
            " platform, date_range_start, date_range_end, as_of_date, snapshot_taken_at,"
            " currency, impressions, clicks, spend, conversions, reconciled, source,"
            " quarantined, created_at)"
            " VALUES (%s, %s, %s, NULL, 'meta', %s, %s, %s, %s, 'TWD', %s, %s, %s, %s, true,"
            " 'meta_api', false, %s)",
            (sid, db.DEV_ORG_ID, self.bid, "2025-03-05", "2025-03-05", "2026-08-01", ts,
             10000, 100, 1000, 5, ts),
        )
        main.conn.commit()
        perf.save_brand_level_derived_metrics(main.conn, self.bid)
        rows = main.conn.execute(
            "SELECT calc_basis FROM derived_metric WHERE brand_id = %s"
            " AND campaign_cycle_id IS NULL", (self.bid,)).fetchall()
        self.assertTrue(rows)
        for r in rows:
            self.assertIn("2025-03", r["calc_basis"])
            self.assertNotIn("2026-08", r["calc_basis"])

    def test_cross_month_range_row_is_attributed_once_to_its_end_month(self):
        """③跨月彙總列（例如舊資料一次性回填、未逐月拆分）明確歸屬到資料期間的末月，
        不重複算進它涵蓋到的其他月份，calc_basis 誠實揭露這一組含跨月彙總（issue #70）。"""
        self._insert_brand_level_snapshot("2025-01-15", clicks=100, impressions=10000,
                                          spend=1000, conversions=5)  # 乾淨單月列
        sid = db.new_id("psn")
        ts = db.now_utc()
        main.conn.execute(
            "INSERT INTO performance_snapshot (id, org_id, brand_id, campaign_cycle_id,"
            " platform, date_range_start, date_range_end, as_of_date, snapshot_taken_at,"
            " currency, impressions, clicks, spend, conversions, reconciled, source,"
            " quarantined, created_at)"
            " VALUES (%s, %s, %s, NULL, 'meta', %s, %s, %s, %s, 'TWD', %s, %s, %s, %s, true,"
            " 'meta_api', false, %s)",
            (sid, db.DEV_ORG_ID, self.bid, "2025-02-01", "2025-04-30", "2025-04-30", ts,
             10000, 100, 1000, 5, ts),
        )
        main.conn.commit()

        perf.save_brand_level_derived_metrics(main.conn, self.bid)
        rows = main.conn.execute(
            "SELECT calc_basis FROM derived_metric WHERE brand_id = %s"
            " AND campaign_cycle_id IS NULL", (self.bid,)).fetchall()
        months_seen = {r["calc_basis"][6:13] for r in rows}
        self.assertEqual(months_seen, {"2025-01", "2025-04"})  # 沒有出現 2025-02／03
        cross_month_notes = [r["calc_basis"] for r in rows if "跨月" in r["calc_basis"]]
        self.assertTrue(cross_month_notes)
        self.assertIn("2025-02-01", cross_month_notes[0])
        self.assertIn("2025-04-30", cross_month_notes[0])

    def _insert_api_snapshot(self, date_start, date_stop, *, clicks, impressions, spend,
                             conversions, account="act_1", campaign="cid1", adset="aid1",
                             ad="adid1"):
        sid = db.new_id("psn")
        ts = db.now_utc()
        main.conn.execute(
            "INSERT INTO performance_snapshot (id, org_id, brand_id, campaign_cycle_id, platform,"
            " account_id, meta_campaign_id, meta_adset_id, meta_ad_id, date_range_start,"
            " date_range_end, as_of_date, snapshot_taken_at, currency, impressions, clicks,"
            " spend, conversions, reconciled, source, quarantined, created_at)"
            " VALUES (%s, %s, %s, NULL, 'meta', %s, %s, %s, %s, %s, %s, %s, %s, 'TWD', %s, %s, %s,"
            " %s, true, 'meta_api', false, %s)",
            (sid, db.DEV_ORG_ID, self.bid, account, campaign, adset, ad, date_start, date_stop,
             date_stop, ts, impressions, clicks, spend, conversions, ts),
        )
        main.conn.commit()

    def test_stale_full_year_row_superseded_by_monthly_backfill_of_the_same_ad(self):
        """票 F13（GitHub #72）：#70 之前整段一次回填留下的跨全年混合列，跟 #70 之後
        對同一支廣告逐月回填的新月列並存時，重算不能把兩邊都算進去——混合列被同一支廣告的
        逐月資料覆蓋，整列排除，只用逐月資料，總量跟各月數字都不能翻倍。"""
        self._insert_api_snapshot("2025-01-01", "2025-12-31", clicks=1200, impressions=120000,
                                  spend=12000.0, conversions=60)  # 舊：整年一列
        for i in range(1, 13):
            last_day = 28 if i == 2 else (30 if i in (4, 6, 9, 11) else 31)
            self._insert_api_snapshot(f"2025-{i:02d}-01", f"2025-{i:02d}-{last_day:02d}",
                                      clicks=100, impressions=10000, spend=1000.0,
                                      conversions=5)  # 新：逐月回填

        written = perf.save_brand_level_derived_metrics(main.conn, self.bid)
        self.assertEqual(written, 36)  # 12 個月 × 3 項指標，沒有第 13 組（整年列已被排除）

        rows = main.conn.execute(
            "SELECT calc_basis, metric, value FROM derived_metric WHERE brand_id = %s"
            " AND campaign_cycle_id IS NULL", (self.bid,)).fetchall()
        months_seen = {r["calc_basis"][6:13] for r in rows}
        self.assertEqual(months_seen, {f"2025-{i:02d}" for i in range(1, 13)})
        self.assertFalse(any("跨月" in r["calc_basis"] for r in rows))  # 混合列整列排除，不進任何一組
        cpcs = {r["value"] for r in rows if r["metric"] == "cpc"}
        self.assertEqual(cpcs, {10.0})  # 1000/100，不是被混合列拉高的兩倍數字

        totals = perf.brand_level_totals(main.conn, self.bid)
        self.assertEqual(totals["spend"], 12000.0)  # 12 個月各 1000，不是舊列＋新列的 24000
        self.assertEqual(totals["clicks"], 1200)


class BrandLevelDuplicateImportTest(_BaseImportTest):
    """票 F9（GitHub #68，F8 破壞者 Persona 發現）：同一份 Meta 品牌層歷史 CSV 匯入兩次，
    第二次要 0 新增、誠實列出略過幾列，基線中位數不能被靜默重複累計。"""

    def test_same_csv_imported_twice_second_time_adds_nothing(self):
        first = perf.import_csv(main.conn, self.bid, None, _CSV_ZH, actor=ACTOR)
        self.assertEqual(first.imported, 1)
        self.assertEqual(first.skipped, 0)

        second = perf.import_csv(main.conn, self.bid, None, _CSV_ZH, actor=ACTOR)
        self.assertEqual(second.imported, 0)
        self.assertEqual(second.skipped, 1)  # 誠實列出略過幾列，不是靜默吞掉
        rows = main.conn.execute(
            "SELECT COUNT(*) c FROM performance_snapshot WHERE brand_id = %s"
            " AND campaign_cycle_id IS NULL", (self.bid,)).fetchone()
        self.assertEqual(rows["c"], 1)  # 資料庫裡只有一筆，不是兩筆

    def test_same_csv_imported_twice_baseline_median_unchanged(self):
        """重匯同檔後，品牌基準中位數與樣本數要跟只匯一次時一模一樣。"""
        perf.import_csv(main.conn, self.bid, None, _CSV_ZH, actor=ACTOR)
        written_once = perf.save_brand_level_derived_metrics(main.conn, self.bid)
        baseline_once = reading.brand_baseline(main.conn, self.bid)

        perf.import_csv(main.conn, self.bid, None, _CSV_ZH, actor=ACTOR)
        written_twice = perf.save_brand_level_derived_metrics(main.conn, self.bid)
        baseline_twice = reading.brand_baseline(main.conn, self.bid)

        self.assertEqual(written_once, written_twice)
        self.assertEqual(baseline_once, baseline_twice)

    def test_different_rows_on_the_same_day_both_still_import(self):
        """去重比的是內容完全相同，不是同一天就擋——同一天兩則不同數字的舊廣告都該進得去。"""
        rows = [
            {"date_start": "2025-01-15", "date_stop": "2025-01-15", "clicks": 100,
             "impressions": 10000, "spend": 1000, "conversions": 5},
            {"date_start": "2025-01-15", "date_stop": "2025-01-15", "clicks": 200,
             "impressions": 20000, "spend": 2000, "conversions": 9},
        ]
        result = perf.import_rows(main.conn, self.bid, None, rows, source="csv", actor=ACTOR,
                                  today="2025-01-16")
        self.assertEqual(result.imported, 2)
        self.assertEqual(result.skipped, 0)

    def test_cycle_scoped_import_still_accumulates_not_affected_by_dedupe(self):
        """票 11 改了契約：「檔期層去重不介入」已不成立，改驗證真正的邊界——品牌層與
        檔期層去重範圍各自獨立，同一份內容在品牌層匯過不會讓檔期層誤判成也匯過。"""
        perf.import_csv(main.conn, self.bid, None, _CSV_ZH, actor=ACTOR)  # 品牌層先匯一次
        cycle_result = perf.import_csv(main.conn, self.bid, self.cycle_id, _CSV_ZH, actor=ACTOR)
        self.assertEqual((cycle_result.imported, cycle_result.skipped), (1, 0))
        self.assertEqual(len(perf.list_snapshots(main.conn, self.bid, self.cycle_id)), 1)


# 票 11 CycleLevelDuplicateImportTest／ProductAttributionTest 兩個類別搬到
# test_ads_performance_dedupe_attribution.py（本檔頂到 FILE_LINE_CAP，見該檔開頭說明）。


if __name__ == "__main__":
    unittest.main()
