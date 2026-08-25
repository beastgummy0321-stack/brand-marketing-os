# -*- coding: utf-8 -*-
"""app/tests/test_learning_ledger_track.py — learning_ledger 遷入品牌永久層（修憲落地 A3）。

見 docs/architecture-rules.md A1（三層地界）／A4（跨分支知識可見性）、決策 0037 第三節。

1. Schema：表已遷入 app/brand_intelligence（migration 0004），`source_track` 欄位存在、
   NOT NULL；既有資料（比照舊表寫法直接 INSERT）不因遷移遺失。
2. A4：`context_compiler.compile()` 預設（`include_cross_track=False`）只取呼叫端自己
   分支的學習，跨分支條目不會外洩；明文開啟後才會出現，且標示來源分支。
3. `app/ads/repository.py` 的薄封裝固定寫入 `source_track='ads'`。
4. 票 L2（ADR 0026 決定 1、4、5）：`collapse_learnings()` 把同一條學習的多列收斂成一列，
   分組鍵是（正規化文字, product_id）兩項，一項不多一項不少。
"""

import tempfile
import unittest
from pathlib import Path

from app.ads import repository as ads_repo
from app.brand_intelligence import repository as bi_repo
from app.brand_intelligence.repository_learning_text import collapse_learnings
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


def _row(id_, learning_text, *, product_id=None, source_cycle_id=None,
         sample_size=None, learned_at="2026-01-01T00:00:00+00:00"):
    """組一列最小化的 learning_ledger 假資料——`collapse_learnings()` 是純函式，不吃 conn，
    不需要真的入庫。"""
    return {
        "id": id_, "learning_text": learning_text, "product_id": product_id,
        "source_cycle_id": source_cycle_id, "sample_size": sample_size,
        "learned_at": learned_at, "confidence": "moderate",
    }


class CollapseLearningsTest(unittest.TestCase):
    """票 L2（ADR 0026 決定 1、4、5）：同一條學習在讀取面只留一列。"""

    def test_three_synonymous_rows_collapse_to_one_with_longest_text_as_representative(self):
        rows = [
            _row("lrn_a", "拿證據說話的切角比純促銷更能拉高轉換率",
                 source_cycle_id="ccy_1", sample_size="132", learned_at="2026-06-01T00:00:00+00:00"),
            _row("lrn_b", "拿證據說話的切角（實證成分／成分對比）比純促銷更能拉高轉換率",
                 sample_size="99", learned_at="2026-07-01T00:00:00+00:00"),
            _row("lrn_c", "拿證據說話的切角比純促銷更能拉高轉換率",
                 source_cycle_id="ccy_2", sample_size="99", learned_at="2026-08-01T00:00:00+00:00"),
            _row("lrn_d", "價格切角轉換率比早鳥優惠低", sample_size="50"),
        ]

        result = collapse_learnings(rows)

        self.assertEqual(len(result), 2)
        merged = result[0]
        self.assertEqual(merged["learning_text"],
                          "拿證據說話的切角（實證成分／成分對比）比純促銷更能拉高轉換率")
        self.assertEqual(merged["verified_cycles"], 3)
        self.assertEqual(merged["sample_sizes"], ["132", "99", "99"])
        self.assertEqual(merged["member_ids"], ["lrn_a", "lrn_b", "lrn_c"])
        self.assertEqual(result[1]["learning_text"], "價格切角轉換率比早鳥優惠低")
        self.assertEqual(result[1]["verified_cycles"], 1)

    def test_same_text_different_product_id_does_not_merge(self):
        """ADR 決定 1：分組鍵含 product_id，同一句話掛不同產品是各自範圍內的結論。"""
        rows = [
            _row("lrn_p1", "早鳥優惠轉換率最高", product_id="prd_1", sample_size="10"),
            _row("lrn_p2", "早鳥優惠轉換率最高", product_id="prd_2", sample_size="20"),
        ]

        result = collapse_learnings(rows)

        self.assertEqual(len(result), 2)
        self.assertEqual({r["id"] for r in result}, {"lrn_p1", "lrn_p2"})
        self.assertTrue(all(r["verified_cycles"] == 1 for r in result))


class ContextCompilerLearningCollapseTest(unittest.TestCase):
    """票 L2（ADR 0026 決定 1、4、5）：企劃 prompt 讀回學習後先收斂，不逐行輸出同義結論。"""

    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.conn = db.connect_and_migrate(Path(self._tmpdir.name) / "test.db")
        self.brand = bi_repo.create_brand(self.conn, name="收斂測試品牌", client_name=None, actor="測試員")

    def tearDown(self):
        self.conn.close()
        self._tmpdir.cleanup()

    def test_three_synonymous_learnings_collapse_to_one_line_in_prompt(self):
        """三列同義的學習讀回後只組成一行，不是三行同義結論重複轟炸 prompt（B0-36 污染鏈
        溫床）。RED first：今天會是三行。"""
        for text, sample_size in (
            ("拿證據說話的切角比純促銷更能拉高轉換率", "132"),
            ("拿證據說話的切角（實證成分／成分對比）比純促銷更能拉高轉換率", "99"),
            ("拿證據說話的切角比純促銷更能拉高轉換率", "99"),
        ):
            ads_repo.create_learning_ledger_entry(
                self.conn, self.brand["id"], learning_text=text, applicability_scope="brand",
                created_by="測試員", actor="測試員", sample_size=sample_size,
            )

        text, _ids, _bv, _pv = context_compiler.compile(self.conn, self.brand["id"])

        section = next(s for s in text.split("\n\n") if s.startswith("【已驗證的學習】"))
        lines = [line for line in section.splitlines() if line.startswith("- ")]
        self.assertEqual(len(lines), 1)
        self.assertIn("實證成分", lines[0])


if __name__ == "__main__":
    unittest.main()
