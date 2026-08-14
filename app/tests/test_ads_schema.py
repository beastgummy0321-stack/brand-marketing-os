# -*- coding: utf-8 -*-
"""app/tests/test_ads_schema.py — 廣告模組 schema 的承重點測試（票 2）。

只測「壞掉會出事」的結構保證，不逐表覆誦欄位：
1. migration 可重複套用（idempotent）。
2. 廣告模組的表都確實存在（schema 完整性；不含 brand_id NOT NULL 的稽核——那是全站範圍，
   已升格進 app/tests/test_brand_isolation_all_tables.py，本檔不重複維護第二份表清單）。
3. 安全邊界（鐵則 4）：沒有具名授權就建不出投放啟動。
4. 外鍵真的生效：孤兒列插不進去。
5. 唯一索引擋得住重複（一期一產品一列、一個廣告帳號一個 Campaign 一列）。

測試一律用虛構品牌 id，不碰真實品牌資料。
"""

import sqlite3
import tempfile
import unittest
from pathlib import Path

from app.core import db

# 廣告模組應存在的資料表（schema 完整性檢查用；品牌隔離的 brand_id 稽核見
# test_brand_isolation_all_tables.py，兩邊不重複維護同一份「哪些表要有 brand_id」名單）。
ADS_MODULE_TABLES = [
    "campaign_cycle", "campaign_cycle_product", "marketing_goal", "success_criterion",
    "campaign_cycle_goal", "campaign_cycle_hypothesis", "offer", "experiment_cell",
    "campaign_plan", "campaign_plan_option", "creative_brief", "creative_variant", "final_asset",
    "adoption_decision", "creative_rule_card", "publishing_package",
    "creative_theme", "creative_theme_component",  # 票 02-theme-tables：主題與主題元件
    "activation_authorization", "external_ad_mapping", "campaign_activation",
    "performance_snapshot", "derived_metric", "performance_reading", "recommendation",
    "finding", "rule_dissent", "cycle_checkpoint",
    # learning_ledger 修憲落地 A3（決策 0037）已遷入品牌永久層 app/brand_intelligence，
    # 不再是廣告模組表，這裡不重複列（表本身仍存在，schema 完整性由
    # test_migration_runner.py／test_architecture_boundaries.py 涵蓋）。
    "brand_checklist_item", "cycle_checklist_item",
    "ga4_summary", "ga4_sync_status",  # 票 34：GA4 彙總表，掛品牌層（決策 0025 第 4 點）
    "cycle_voucher_code", "cycle_code_verification",  # 票 35：期別配碼＋上線前校驗
    "ad_revenue_coefficient", "ad_revenue_coefficient_error_log",  # 票 36：灌水係數＋事後誤差
    "settlement_version", "reading_snapshot", "reading_snapshot_input",  # 票 37：結算版次＋判讀快照
    "ad_account", "discovered_campaign",  # 刻意不帶 brand_id（決策 0022 第 6、7 點）
]


class AdsSchemaTest(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.db_path = Path(self._tmpdir.name) / "test.db"
        self.conn = db.connect_and_migrate(self.db_path)

    def tearDown(self):
        self.conn.close()
        self._tmpdir.cleanup()

    def _columns(self, table):
        return {row["name"]: row for row in self.conn.execute(f"PRAGMA table_info({table})")}

    def test_migration_is_idempotent(self):
        """重跑 migration 不炸、不重複套用（每次開 app 都會跑一次）。"""
        db.migrate_all(self.conn)
        db.migrate_all(self.conn)
        versions = [
            row["version"]
            for row in self.conn.execute(
                "SELECT version FROM schema_migrations WHERE module = 'ads'"
            )
        ]
        self.assertEqual(versions, [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18])

    def test_all_expected_tables_exist(self):
        names = {
            row["name"]
            for row in self.conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
        }
        for table in ADS_MODULE_TABLES:
            self.assertIn(table, names, f"缺少資料表：{table}")

    def test_named_authorization_is_structurally_required(self):
        """鐵則 4：授權必須具名，且投放啟動必須引用授權——兩者都由 NOT NULL 保證。"""
        self.assertEqual(self._columns("activation_authorization")["authorized_by"]["notnull"], 1)
        self.assertEqual(self._columns("campaign_activation")["authorization_id"]["notnull"], 1)

        # 沒有授權列可引用時，campaign_activation 插不進去（外鍵擋下）
        self.conn.execute(
            "INSERT INTO campaign_cycle (id, brand_id, product_scope_json, objective, currency,"
            " start_date, end_date, channels_json, status, phase, created_at, updated_at)"
            " VALUES ('ccy_T1','brn_FAKE','[]','測試','TWD','2026-01-01','2026-01-14',"
            " '[]','PLANNING','normal','2026-01-01T00:00:00Z','2026-01-01T00:00:00Z')"
        )
        with self.assertRaises(sqlite3.IntegrityError):
            self.conn.execute(
                "INSERT INTO campaign_activation (id, brand_id, campaign_cycle_id,"
                " authorization_id, activated_by, activated_at, created_at)"
                " VALUES ('act_T1','brn_FAKE','ccy_T1','ath_DOES_NOT_EXIST','測試員',"
                " '2026-01-02T00:00:00Z','2026-01-02T00:00:00Z')"
            )

    def test_foreign_keys_are_enforced(self):
        """PRAGMA foreign_keys=ON 生效：孤兒列插不進去。"""
        with self.assertRaises(sqlite3.IntegrityError):
            self.conn.execute(
                "INSERT INTO campaign_cycle_product (id, campaign_cycle_id, brand_id, product_id,"
                " allocation_basis, created_at, updated_at)"
                " VALUES ('ccp_T1','ccy_DOES_NOT_EXIST','brn_FAKE','prd_FAKE','even',"
                " '2026-01-01T00:00:00Z','2026-01-01T00:00:00Z')"
            )

    def test_one_row_per_cycle_product(self):
        """同一期同一產品只能有一列，否則預算會被分配兩次。"""
        self.conn.execute(
            "INSERT INTO campaign_cycle (id, brand_id, product_scope_json, objective, currency,"
            " start_date, end_date, channels_json, status, phase, created_at, updated_at)"
            " VALUES ('ccy_T2','brn_FAKE','[]','測試','TWD','2026-01-01','2026-01-14',"
            " '[]','PLANNING','normal','2026-01-01T00:00:00Z','2026-01-01T00:00:00Z')"
        )
        insert = (
            "INSERT INTO campaign_cycle_product (id, campaign_cycle_id, brand_id, product_id,"
            " allocation_basis, created_at, updated_at)"
            " VALUES (?, 'ccy_T2','brn_FAKE','prd_FAKE','even',"
            " '2026-01-01T00:00:00Z','2026-01-01T00:00:00Z')"
        )
        self.conn.execute(insert, ("ccp_T2",))
        with self.assertRaises(sqlite3.IntegrityError):
            self.conn.execute(insert, ("ccp_T3",))

    def test_one_row_per_discovered_campaign(self):
        """同一個廣告帳號的同一個 Campaign 只能有一列，重複同步不會長出第二筆待認領。"""
        self.conn.execute(
            "INSERT INTO ad_account (id, platform, external_account_id, status,"
            " created_at, updated_at)"
            " VALUES ('adc_T1','meta','act_123','active',"
            " '2026-01-01T00:00:00Z','2026-01-01T00:00:00Z')"
        )
        insert = (
            "INSERT INTO discovered_campaign (id, ad_account_id, platform, meta_campaign_id,"
            " first_seen_at, last_seen_at, claim_status, created_at, updated_at)"
            " VALUES (?, 'adc_T1','meta','23851234','2026-01-01T00:00:00Z',"
            " '2026-01-01T00:00:00Z','unclaimed','2026-01-01T00:00:00Z','2026-01-01T00:00:00Z')"
        )
        self.conn.execute(insert, ("dsc_T1",))
        with self.assertRaises(sqlite3.IntegrityError):
            self.conn.execute(insert, ("dsc_T2",))

    def test_performance_snapshot_has_normalised_columns(self):
        """決策 0016 硬性原則 2：三個來源都轉成同一組實欄位，下游只認這一種格式。"""
        cols = self._columns("performance_snapshot")
        for col in ["impressions", "clicks", "spend", "conversions", "revenue", "frequency",
                    "reach"]:
            self.assertIn(col, cols, f"performance_snapshot 缺正規化欄位 {col}")
        self.assertIn("quarantined", cols)


if __name__ == "__main__":
    unittest.main()
