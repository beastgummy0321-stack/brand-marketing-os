# -*- coding: utf-8 -*-
"""app/tests/test_learning_ledger_track.py — learning_ledger 遷入品牌永久層（修憲落地 A3）。

見 docs/architecture-rules.md A1（三層地界）／A4（跨分支知識可見性）、決策 0037 第三節。

1. Schema：表已遷入 app/brand_intelligence（migration 0004），`source_track` 欄位存在、
   NOT NULL；既有資料（比照舊表寫法直接 INSERT）不因遷移遺失。
2. A4：`context_compiler.compile()` 預設（`include_cross_track=False`）只取呼叫端自己
   分支的學習，跨分支條目不會外洩；明文開啟後才會出現，且標示來源分支。
3. `app/ads/repository.py` 的薄封裝固定寫入 `source_track='ads'`。
"""

import tempfile
import unittest
from pathlib import Path

from app.ads import repository as ads_repo
from app.brand_intelligence import repository as bi_repo
from app.core import db
from app.llm import context_compiler


class LearningLedgerSchemaTest(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.conn = db.connect_and_migrate(Path(self._tmpdir.name) / "test.db")

    def tearDown(self):
        self.conn.close()
        self._tmpdir.cleanup()

    def test_source_track_column_exists_and_not_null(self):
        columns = {row["name"]: row for row in self.conn.execute("PRAGMA table_info(learning_ledger)")}
        self.assertIn("source_track", columns)
        self.assertEqual(columns["source_track"]["notnull"], 1)

    def test_ads_wrapper_writes_source_track_ads(self):
        brand = bi_repo.create_brand(self.conn, name="虛構遷移測試品牌", client_name=None, actor="測試員")
        entry = ads_repo.create_learning_ledger_entry(
            self.conn, brand["id"], learning_text="遷移後寫入仍正常",
            applicability_scope="brand", created_by="測試員", actor="測試員",
        )
        row = self.conn.execute(
            "SELECT source_track FROM learning_ledger WHERE id = ?", (entry["id"],)
        ).fetchone()
        self.assertEqual(row["source_track"], "ads")

    def test_bi_layer_requires_explicit_source_track(self):
        """A4：來源分支不給預設值，呼叫端必須明確交代（防止日後新分支忘記標註）。"""
        brand = bi_repo.create_brand(self.conn, name="虛構遷移測試品牌二號", client_name=None, actor="測試員")
        with self.assertRaises(TypeError):
            bi_repo.create_learning_ledger_entry(
                self.conn, brand["id"], learning_text="沒帶 source_track",
                applicability_scope="brand", created_by="測試員", actor="測試員",
            )

    def test_legacy_style_insert_without_source_track_falls_back_to_default(self):
        """既有資料（遷移前用舊欄位清單寫入的列）不因新增欄位而遺失或炸掉——DEFAULT 'ads'
        原地補值，這是「不重建空表、原地補欄位」的機制證明。"""
        brand = bi_repo.create_brand(self.conn, name="虛構遷移測試品牌三號", client_name=None, actor="測試員")
        self.conn.execute(
            "INSERT INTO learning_ledger (id, brand_id, learning_text, applicability_scope,"
            " learned_at, created_by, created_at) VALUES"
            " ('lrn_legacy1', ?, '遷移前風格寫入的舊資料', 'brand', '2026-01-01T00:00:00',"
            " '測試員', '2026-01-01T00:00:00')",
            (brand["id"],),
        )
        self.conn.commit()
        row = self.conn.execute(
            "SELECT * FROM learning_ledger WHERE id = 'lrn_legacy1'"
        ).fetchone()
        self.assertEqual(row["learning_text"], "遷移前風格寫入的舊資料")
        self.assertEqual(row["source_track"], "ads")


class ContextCompilerCrossTrackTest(unittest.TestCase):
    """A4：組裝 prompt 時，預設只取本分支產生的知識；跨分支引用須明文開啟並標示來源分支。"""

    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.conn = db.connect_and_migrate(Path(self._tmpdir.name) / "test.db")
        self.brand = bi_repo.create_brand(self.conn, name="虛構跨分支測試品牌", client_name=None, actor="測試員")
        self.ads_entry = ads_repo.create_learning_ledger_entry(
            self.conn, self.brand["id"], learning_text="廣告分支學到：早鳥優惠有效",
            applicability_scope="brand", created_by="測試員", actor="測試員",
        )
        # 直接呼叫品牌永久層公開函式，模擬「內容分支」寫入自己的學習（該分支本身尚未上線，
        # 這裡只驗證資料層的分支隔離，不需要真的把整條內容分支建出來——YAGNI）。
        self.content_entry = bi_repo.create_learning_ledger_entry(
            self.conn, self.brand["id"], learning_text="內容分支學到：長文開箱轉換較好",
            applicability_scope="brand", created_by="測試員", actor="測試員", source_track="content",
        )

    def tearDown(self):
        self.conn.close()
        self._tmpdir.cleanup()

    def test_default_only_includes_own_track(self):
        text, ids, _bv, _pv = context_compiler.compile(self.conn, self.brand["id"])
        self.assertIn("早鳥優惠有效", text)
        self.assertIn(self.ads_entry["id"], ids)
        self.assertNotIn("長文開箱轉換較好", text, "未開啟跨分支時，不該出現他分支來源的條目")
        self.assertNotIn(self.content_entry["id"], ids)

    def test_explicit_track_param_scopes_to_that_track(self):
        text, ids, _bv, _pv = context_compiler.compile(self.conn, self.brand["id"], track="content")
        self.assertIn("長文開箱轉換較好", text)
        self.assertNotIn("早鳥優惠有效", text)
        self.assertIn(self.content_entry["id"], ids)
        self.assertNotIn(self.ads_entry["id"], ids)

    def test_cross_track_opt_in_includes_both_and_labels_foreign_source(self):
        text, ids, _bv, _pv = context_compiler.compile(
            self.conn, self.brand["id"], track="ads", include_cross_track=True)
        self.assertIn("早鳥優惠有效", text)
        self.assertIn("長文開箱轉換較好", text)
        self.assertIn(self.ads_entry["id"], ids)
        self.assertIn(self.content_entry["id"], ids)
        # 跨分支條目要標示來源；本分支自己的不必多此一舉。
        self.assertIn("來源分支：content", text)
        ads_line = next(line for line in text.splitlines() if "早鳥優惠有效" in line)
        self.assertNotIn("來源分支", ads_line)


if __name__ == "__main__":
    unittest.main()
