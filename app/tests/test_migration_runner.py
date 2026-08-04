# -*- coding: utf-8 -*-
"""app/tests/test_migration_runner.py — migration runner 交易包裹＋資料保留（修憲落地 A5）。

見 docs/architecture-rules.md A5（資料保留）、A6（Schema 演進）：
1. migration runner 失敗回滾：中途失敗不得留半套 schema、不得前進版本號。
2. 已落地 migration 檔的內容雜湊鎖：改動即 FAIL。
3. audit_log 補 (brand_id, created_at) 複合索引。
4. llm_task 保留策略：超過保留期的舊列，大欄位清空但 usage/cost/hash 仍在。
"""

import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from app.core import db, retention


class MigrationTransactionRollbackTest(unittest.TestCase):
    """修憲落地前：executescript 讓 DDL 逐句自動 commit，中途失敗留半套 schema、
    版本號不前進、重跑會從檔頭撞上已建好的物件。修憲落地後：整份 migration 檔包在
    一個交易裡，失敗整包 rollback。"""

    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.db_path = Path(self._tmpdir.name) / "test.db"
        self.mig_dir = Path(self._tmpdir.name) / "migrations"
        self.mig_dir.mkdir()
        self.conn = db.connect(self.db_path)

    def tearDown(self):
        self.conn.close()
        self._tmpdir.cleanup()

    def _write(self, name: str, sql: str) -> None:
        (self.mig_dir / name).write_text(sql, encoding="utf-8")

    def test_mid_file_failure_leaves_no_half_schema_and_does_not_advance_version(self):
        self._write("0001_good.sql", "CREATE TABLE demo (id TEXT PRIMARY KEY);\n")
        db.run_migrations(self.conn, "testmod", self.mig_dir)  # 0001 先成功套用

        self._write(
            "0002_bad.sql",
            "ALTER TABLE demo ADD COLUMN extra_col TEXT;\n"
            "CREATE TABLEX broken (id TEXT);\n",  # 故意打錯關鍵字，讓第二句失敗
        )
        with self.assertRaises(sqlite3.OperationalError):
            db.run_migrations(self.conn, "testmod", self.mig_dir)  # 0002 中途失敗

        versions = [
            row["version"] for row in
            self.conn.execute("SELECT version FROM schema_migrations WHERE module = 'testmod'")
        ]
        self.assertEqual(versions, [1], "0002 失敗不得記版本號，即使它的第一句成功了")

        columns = [row["name"] for row in self.conn.execute("PRAGMA table_info(demo)")]
        self.assertEqual(columns, ["id"], "0002 第一句的 ALTER 效果必須被整包 rollback，不留半套")

        tables = {row["name"] for row in
                   self.conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
        self.assertNotIn("broken", tables, "失敗那句本身自然沒建成，但也不該有任何殘留")

    def test_retry_after_fix_succeeds_without_colliding_with_the_first_statement(self):
        """修復後重跑：因為失敗那次整包 rollback，第一句（ALTER）沒有半套殘留，
        重跑不會撞上「欄位已存在」這種因半套殘留造成的二次錯誤。"""
        self._write("0001_good.sql", "CREATE TABLE demo (id TEXT PRIMARY KEY);\n")
        db.run_migrations(self.conn, "testmod", self.mig_dir)

        self._write(
            "0002_bad.sql",
            "ALTER TABLE demo ADD COLUMN extra_col TEXT;\n"
            "CREATE TABLEX broken (id TEXT);\n",
        )
        with self.assertRaises(sqlite3.OperationalError):
            db.run_migrations(self.conn, "testmod", self.mig_dir)

        self._write(
            "0002_bad.sql",
            "ALTER TABLE demo ADD COLUMN extra_col TEXT;\n"
            "CREATE TABLE broken (id TEXT);\n",
        )
        db.run_migrations(self.conn, "testmod", self.mig_dir)  # 這次不該再炸

        versions = [
            row["version"] for row in
            self.conn.execute("SELECT version FROM schema_migrations WHERE module = 'testmod'")
        ]
        self.assertEqual(versions, [1, 2])
        columns = [row["name"] for row in self.conn.execute("PRAGMA table_info(demo)")]
        self.assertEqual(columns, ["id", "extra_col"])


class MigrationHashLockTest(unittest.TestCase):
    """已落地 migration 檔不得再編輯：內容雜湊比對，改動即 FAIL（A6）。"""

    def test_landed_migrations_match_recorded_manifest_hashes(self):
        manifest_path = db.migration_manifest_path()
        self.assertTrue(
            manifest_path.exists(),
            f"{manifest_path} 不存在——每次新增 migration 檔都必須在同一個 commit 補上雜湊",
        )
        recorded = json.loads(manifest_path.read_text(encoding="utf-8"))
        current = db.compute_migration_hashes()
        self.assertEqual(
            current, recorded,
            "migration 檔的內容雜湊與 manifest 不符：要嘛是編輯了已落地的檔案（禁止，"
            "修正請開新的 migration），要嘛是新增檔案忘記同步 manifest",
        )


class AuditLogCompositeIndexTest(unittest.TestCase):
    """audit_log 補 (brand_id, created_at) 複合索引（A5，成效中樞跨分支月報的本職查詢）。"""

    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.conn = db.connect_and_migrate(Path(self._tmpdir.name) / "test.db")

    def tearDown(self):
        self.conn.close()
        self._tmpdir.cleanup()

    def test_composite_index_on_brand_id_and_created_at_exists(self):
        indexes = self.conn.execute("PRAGMA index_list(audit_log)").fetchall()
        matched = None
        for idx in indexes:
            cols = [r["name"] for r in self.conn.execute(f"PRAGMA index_info({idx['name']})")]
            if cols == ["brand_id", "created_at"]:
                matched = idx["name"]
                break
        self.assertIsNotNone(matched, "audit_log 缺 (brand_id, created_at) 複合索引")


class LlmTaskRetentionTest(unittest.TestCase):
    """超過保留期的 llm_task 舊列，大欄位清空但 usage/cost/hash 仍留供對帳（A5）。"""

    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.conn = db.connect_and_migrate(Path(self._tmpdir.name) / "test.db")

    def tearDown(self):
        self.conn.close()
        self._tmpdir.cleanup()

    def _insert_task(self, task_id, *, finished_at):
        started_at = finished_at or db.now_iso()  # started_at 為 NOT NULL，跑中的任務仍要有起始時間
        self.conn.execute(
            """INSERT INTO llm_task (
                id, brand_id, task_type, context_scope_json, input_context_ids_json,
                input_context_hash, knowledge_item_ids_json, brand_version, product_version,
                campaign_plan_version, prompt_template_id, prompt_template_version, provider,
                model, status, attempt_no, structured_output_json, rendered_output,
                validation_result_json, usage_json, cost, started_at, finished_at, error
            ) VALUES (?, 'brand_x', 'draft', '{}', '[]', 'hash123', '[]', 1, NULL, NULL,
                       'tmpl', 'v1', 'anthropic', 'sonnet', 'succeeded', 1,
                       '{"a":1}', '很長的模型輸出內容', '{"ok":true}', '{"input_tokens":10}', 0.5,
                       ?, ?, NULL)""",
            (task_id, started_at, finished_at),
        )
        self.conn.commit()

    def test_expired_row_has_large_columns_cleared_but_keeps_reconciliation_fields(self):
        cutoff = retention._cutoff_iso()
        old_dt = _shift_iso(cutoff, days=-1)  # 保留期外一天
        recent_dt = _shift_iso(cutoff, days=+1)  # 保留期內一天

        self._insert_task("llm_old", finished_at=old_dt)
        self._insert_task("llm_recent", finished_at=recent_dt)
        self._insert_task("llm_running", finished_at=None)

        purged = retention.purge_expired_llm_task_content(self.conn)
        self.assertEqual(purged, 1, "只有真正過期的那一列該被動到")

        old_row = dict(self.conn.execute(
            "SELECT * FROM llm_task WHERE id = 'llm_old'").fetchone())
        self.assertIsNone(old_row["structured_output_json"])
        self.assertIsNone(old_row["rendered_output"])
        self.assertIsNone(old_row["validation_result_json"])
        # 對帳用欄位必須留著
        self.assertEqual(old_row["usage_json"], '{"input_tokens":10}')
        self.assertEqual(old_row["cost"], 0.5)
        self.assertEqual(old_row["input_context_hash"], "hash123")
        self.assertEqual(old_row["status"], "succeeded")
        self.assertEqual(old_row["provider"], "anthropic")

        recent_row = dict(self.conn.execute(
            "SELECT * FROM llm_task WHERE id = 'llm_recent'").fetchone())
        self.assertEqual(recent_row["rendered_output"], "很長的模型輸出內容")

        running_row = dict(self.conn.execute(
            "SELECT * FROM llm_task WHERE id = 'llm_running'").fetchone())
        self.assertIsNone(running_row["finished_at"])

    def test_purge_is_idempotent(self):
        cutoff = retention._cutoff_iso()
        old_dt = _shift_iso(cutoff, days=-1)
        self._insert_task("llm_old", finished_at=old_dt)

        first = retention.purge_expired_llm_task_content(self.conn)
        second = retention.purge_expired_llm_task_content(self.conn)
        self.assertEqual(first, 1)
        self.assertEqual(second, 0, "已經清過的列不該重複計入，重跑要安全")


def _shift_iso(iso_str: str, *, days: int) -> str:
    from datetime import datetime, timedelta
    return (datetime.fromisoformat(iso_str) + timedelta(days=days)).isoformat()


if __name__ == "__main__":
    unittest.main()
