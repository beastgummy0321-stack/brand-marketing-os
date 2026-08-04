# -*- coding: utf-8 -*-
"""app/tests/test_settings.py — app_setting 存取層與 intake 兩張表的 migration。

見 docs/design/03-data-model.md §3A、docs/design/07-settings-and-intake-contract.md。
"""

import os
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from app.core import db, settings


class SettingsTest(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.db_path = Path(self._tmpdir.name) / "test.db"
        self.conn = db.connect_and_migrate(self.db_path)

    def tearDown(self):
        self.conn.close()
        self._tmpdir.cleanup()

    def test_get_set_roundtrip(self):
        self.assertIsNone(settings.get_setting(self.conn, "不存在的鍵"))
        self.assertEqual(settings.get_setting(self.conn, "不存在的鍵", "預設"), "預設")
        settings.set_setting(self.conn, "llm_model", "claude-sonnet-5")
        self.assertEqual(settings.get_setting(self.conn, "llm_model"), "claude-sonnet-5")
        settings.set_setting(self.conn, "llm_model", "claude-haiku-4-5")  # 覆蓋不重複建列
        self.assertEqual(settings.get_setting(self.conn, "llm_model"), "claude-haiku-4-5")
        self.assertEqual(
            self.conn.execute("SELECT COUNT(*) FROM app_setting").fetchone()[0], 1
        )

    def test_get_setting_tolerates_missing_table(self):
        """表還沒建起來時回 default，不噴 SQL 錯誤（principles 16 優雅缺席）。"""
        bare = sqlite3.connect(":memory:")
        bare.row_factory = sqlite3.Row
        self.assertIsNone(settings.get_setting(bare, "anthropic_api_key"))
        bare.close()

    def test_api_key_priority(self):
        """修憲落地 M4：環境變數優先、DB 只當回退——不是反過來（決策 0008：backups/
        會同步進雲端硬碟，DB 明文金鑰不該贏過環境變數）。"""
        with mock.patch.dict(os.environ, {}, clear=True):
            self.assertIsNone(settings.get_api_key(self.conn))
            settings.set_setting(self.conn, "anthropic_api_key", "db-key")
            self.assertEqual(settings.get_api_key(self.conn), "db-key")  # 沒環境變數才回退 DB
        with mock.patch.dict(os.environ, {"ANTHROPIC_API_KEY": "env-key"}, clear=True):
            self.assertEqual(settings.get_api_key(self.conn), "env-key")  # 環境變數贏過 DB 裡的舊值

    def test_api_key_source(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            self.assertIsNone(settings.api_key_source(self.conn))
            settings.set_setting(self.conn, "anthropic_api_key", "db-key")
            self.assertEqual(settings.api_key_source(self.conn), "db")
        with mock.patch.dict(os.environ, {"ANTHROPIC_API_KEY": "env-key"}, clear=True):
            self.assertEqual(settings.api_key_source(self.conn), "env")  # DB 仍有值，但來源要誠實回報 env

    def test_clear_api_key_from_db(self):
        settings.set_setting(self.conn, "anthropic_api_key", "db-key")
        with mock.patch.dict(os.environ, {}, clear=True):
            self.assertEqual(settings.get_api_key(self.conn), "db-key")
            settings.clear_api_key_from_db(self.conn)
            self.assertIsNone(settings.get_api_key(self.conn))
        # 清掉 DB 值不影響環境變數來源
        settings.set_setting(self.conn, "anthropic_api_key", "db-key-2")
        with mock.patch.dict(os.environ, {"ANTHROPIC_API_KEY": "env-key"}, clear=True):
            settings.clear_api_key_from_db(self.conn)
            self.assertEqual(settings.get_api_key(self.conn), "env-key")

    def test_llm_model_priority(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            self.assertEqual(settings.get_llm_model(self.conn), "claude-opus-5")
        with mock.patch.dict(os.environ, {"BRAND_OS_LLM_MODEL": "claude-haiku-4-5"}, clear=True):
            self.assertEqual(settings.get_llm_model(self.conn), "claude-haiku-4-5")
            settings.set_setting(self.conn, "llm_model", "claude-sonnet-5")
            self.assertEqual(settings.get_llm_model(self.conn), "claude-sonnet-5")

    def test_intake_budget_limit(self):
        from app.intake import script

        self.assertEqual(settings.get_intake_budget_limit(self.conn), script.DEFAULT_BUDGET)
        settings.set_setting(self.conn, "intake_budget_limit", "12.5")
        self.assertEqual(settings.get_intake_budget_limit(self.conn), 12.5)
        settings.set_setting(self.conn, "intake_budget_limit", "壞掉的值")
        self.assertEqual(settings.get_intake_budget_limit(self.conn), script.DEFAULT_BUDGET)


class BudgetExceededMessageTest(unittest.TestCase):
    """票 M2：品牌智庫調研、廣告分支計畫／素材生成共用的花費上限檢查。"""

    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.conn = db.connect_and_migrate(Path(self._tmpdir.name) / "test.db")
        self.brand_id = "brd_test"

    def tearDown(self):
        self.conn.close()
        self._tmpdir.cleanup()

    def _spend(self, cost: float, brand_id: str = None) -> None:
        from app.core.db import new_id, now_iso
        self.conn.execute(
            "INSERT INTO llm_task (id, brand_id, task_type, context_scope_json,"
            " input_context_ids_json, input_context_hash, knowledge_item_ids_json,"
            " brand_version, prompt_template_id, prompt_template_version, provider, model,"
            " status, attempt_no, cost, started_at, finished_at)"
            " VALUES (?, ?, 't', '{}', '[]', '', '[]', 1, 'p', 'v1', 'seed', 'seed',"
            " 'succeeded', 1, ?, ?, ?)",
            (new_id("llm"), brand_id or self.brand_id, cost, now_iso(), now_iso()),
        )
        self.conn.commit()

    def test_no_spend_yet_no_message(self):
        self.assertIsNone(settings.budget_exceeded_message(self.conn, self.brand_id, 1.0))

    def test_over_limit_returns_message_with_explicit_usd(self):
        settings.set_setting(self.conn, "intake_budget_limit", "10")
        self._spend(9.5)
        msg = settings.budget_exceeded_message(self.conn, self.brand_id, 1.0)
        self.assertIsNotNone(msg)
        # 三個數字（已花費／這次預估／上限）都要明確標幣別，不能是裸的 $
        self.assertEqual(msg.count("US$"), 3)
        self.assertNotIn("NT$", msg)

    def test_failed_calls_do_not_count(self):
        settings.set_setting(self.conn, "intake_budget_limit", "1")
        from app.core.db import new_id, now_iso
        self.conn.execute(
            "INSERT INTO llm_task (id, brand_id, task_type, context_scope_json,"
            " input_context_ids_json, input_context_hash, knowledge_item_ids_json,"
            " brand_version, prompt_template_id, prompt_template_version, provider, model,"
            " status, attempt_no, cost, started_at, finished_at)"
            " VALUES (?, ?, 't', '{}', '[]', '', '[]', 1, 'p', 'v1', 'seed', 'seed',"
            " 'failed', 1, NULL, ?, ?)",
            (new_id("llm"), self.brand_id, now_iso(), now_iso()),
        )
        self.conn.commit()
        self.assertIsNone(settings.budget_exceeded_message(self.conn, self.brand_id, 0.9))

    def test_spend_is_scoped_per_brand(self):
        """跨品牌不共用額度：另一個品牌燒光額度不該波及這個品牌。"""
        settings.set_setting(self.conn, "intake_budget_limit", "1")
        self._spend(5.0, brand_id="brd_other")
        self.assertIsNone(settings.budget_exceeded_message(self.conn, self.brand_id, 0.5))

    def test_brand_llm_spent_sums_only_succeeded(self):
        self._spend(1.5)
        self._spend(2.5)
        self.assertAlmostEqual(settings.brand_llm_spent(self.conn, self.brand_id), 4.0)


class IntakeMigrationTest(unittest.TestCase):
    """03 §3A.2–§3A.4：兩張表 ＋ 三個索引 ＋ 部分唯一索引。"""

    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.db_path = Path(self._tmpdir.name) / "test.db"
        self.conn = db.connect_and_migrate(self.db_path)

    def tearDown(self):
        self.conn.close()
        self._tmpdir.cleanup()

    def _insert_draft(self, brand_id, status="draft"):
        draft_id = db.new_id("idr")
        now = db.now_iso()
        self.conn.execute(
            """INSERT INTO intake_draft (id, brand_id, status, current_step, current_question_no,
                   description, photos_json, research_urls_json, cost_limit, llm_task_refs_json,
                   created_at, updated_at)
               VALUES (?, ?, ?, 1, 0, '描述', '[]', '[]', 30.0, '[]', ?, ?)""",
            (draft_id, brand_id, status, now, now),
        )
        self.conn.commit()
        return draft_id

    def test_one_active_draft_per_brand(self):
        self._insert_draft("brd_A")
        with self.assertRaises(sqlite3.IntegrityError):
            self._insert_draft("brd_A")
        # 已完成的草稿不佔名額，同品牌可再開新的
        self.conn.execute("UPDATE intake_draft SET status = 'completed' WHERE brand_id = 'brd_A'")
        self.conn.commit()
        self._insert_draft("brd_A")
        self._insert_draft("brd_B")

    def test_intake_item_foreign_key_and_indexes(self):
        draft_id = self._insert_draft("brd_A")
        self.conn.execute(
            """INSERT INTO intake_item (id, intake_draft_id, brand_id, row_no, raw_row, kind,
                   category, title, content, scope_raw, outcome, created_at)
               VALUES (?, ?, 'brd_A', 1, '原文', 'brand_fact', 'positioning', '標題', '內容',
                   '整個品牌', 'pending', ?)""",
            (db.new_id("iit"), draft_id, db.now_iso()),
        )
        self.conn.commit()
        row = self.conn.execute("SELECT * FROM intake_item").fetchone()
        self.assertEqual(row["outcome"], "pending")
        self.assertIsNone(row["target_id"])

        # 同模組外鍵確實生效（PRAGMA foreign_keys = ON）
        with self.assertRaises(sqlite3.IntegrityError):
            self.conn.execute(
                """INSERT INTO intake_item (id, intake_draft_id, brand_id, row_no, raw_row, kind,
                       category, title, content, scope_raw, outcome, created_at)
                   VALUES (?, 'idr_不存在', 'brd_A', 2, 'x', 'rule', 'tone', 't', 'c', '整個品牌',
                       'pending', ?)""",
                (db.new_id("iit"), db.now_iso()),
            )
        self.conn.rollback()

        indexes = {r["name"] for r in self.conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'index' AND tbl_name = 'intake_item'"
        )}
        self.assertIn("idx_intake_item_draft_row", indexes)
        self.assertIn("idx_intake_item_brand_outcome", indexes)

    def test_migration_is_idempotent_on_existing_db(self):
        """既有資料庫再跑一次 migrate_all 不重複套用、不動既有資料。"""
        self._insert_draft("brd_A")
        db.migrate_all(self.conn)
        db.migrate_all(self.conn)
        self.assertEqual(
            self.conn.execute("SELECT COUNT(*) FROM intake_draft").fetchone()[0], 1
        )
        versions = self.conn.execute(
            "SELECT COUNT(*) FROM schema_migrations WHERE module = 'intake'"
        ).fetchone()[0]
        self.assertEqual(versions, 2)  # 0001_intake + 0002_scan_products（決策 0014）

    def test_upgrade_from_pre_existing_db(self):
        """既有（只套過 core 0001）的資料庫升級：補上 app_setting 與 intake 兩張表，舊資料留著。"""
        old_path = Path(self._tmpdir.name) / "old.db"
        conn = db.connect(old_path)
        db.run_migrations(conn, "core", db.APP_DIR / "core" / "migrations")
        conn.execute("DELETE FROM schema_migrations WHERE module = 'core' AND version = 2")
        conn.execute("DROP TABLE app_setting")
        conn.execute(
            "INSERT INTO audit_log (id, entity_type, entity_id, action, actor, created_at)"
            " VALUES ('aud_1', 'brand', 'brd_A', 'create', '小陳', ?)",
            (db.now_iso(),),
        )
        conn.commit()

        db.migrate_all(conn)
        settings.set_setting(conn, "llm_model", "claude-sonnet-5")
        self.assertEqual(settings.get_llm_model(conn), "claude-sonnet-5")
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM intake_draft").fetchone()[0], 0)
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM audit_log").fetchone()[0], 1)
        conn.close()


if __name__ == "__main__":
    unittest.main()
