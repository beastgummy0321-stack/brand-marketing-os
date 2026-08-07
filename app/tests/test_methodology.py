# -*- coding: utf-8 -*-
"""app/tests/test_methodology.py — 方法論載入器（票 11）。

驗對照表解析、缺檔優雅缺席＋稽核紀錄、改對照表後行為跟著變（程式不寫死清單）。
不打真實網路請求；不涉及品牌資料，直接用 core db 即可。
"""

import re
import tempfile
import unittest
from datetime import date
from pathlib import Path

from app.core import db
from app.llm import methodology

REPO_ROOT = Path(__file__).resolve().parents[2]
METHODOLOGY_DIR = REPO_ROOT / "app" / "methodology"


class MethodologyTableParseTest(unittest.TestCase):
    """對真實 app/methodology/README.md 的解析——回歸鎖定既有對照表內容。"""

    def test_real_readme_parses_known_task_labels(self):
        table = methodology.load_table()
        self.assertEqual(table["檔期計畫生成"], ["ads.md", "ab-testing.md", "customer-voice.md"])
        self.assertEqual(
            table["Hook／文案生成"],
            ["ad-creative.md", "copywriting.md", "creative-matrix.md", "customer-voice.md"],
        )
        self.assertEqual(table["圖片 Prompt 生成"], ["creative-matrix.md", "ad-creative.md"])
        # 檔案索引表（另一張表）不能被誤吃進來
        self.assertNotIn("檔案", table)

    def test_missing_readme_returns_empty_table(self):
        self.assertEqual(methodology.load_table(Path("不存在/README.md")), {})


class MethodologyCompileTest(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.conn = db.connect_and_migrate(Path(self._tmpdir.name) / "test.db")
        self.meth_dir = Path(self._tmpdir.name) / "methodology"
        self.meth_dir.mkdir()

    def tearDown(self):
        self.conn.close()
        self._tmpdir.cleanup()

    def _write_readme(self, table_rows: str) -> Path:
        readme = self.meth_dir / "README.md"
        readme.write_text(
            "# 索引\n\n## 任務型別 → 必讀方法論檔對照表\n\n"
            "| 任務型別 | 必讀方法論檔 |\n|---|---|\n" + table_rows + "\n## 維護規則\n之後的段落。\n",
            encoding="utf-8",
        )
        return readme

    def _audit_rows(self):
        return [dict(r) for r in
                self.conn.execute("SELECT * FROM audit_log ORDER BY created_at, id").fetchall()]

    def test_compile_includes_file_content(self):
        readme = self._write_readme("| 測試任務 | `a.md`、`b.md` |\n")
        (self.meth_dir / "a.md").write_text("A 檔內容：先講重點。", encoding="utf-8")
        (self.meth_dir / "b.md").write_text("B 檔內容：再講重點。", encoding="utf-8")

        result = methodology.compile(self.conn, ["測試任務"], brand_id=None, actor="測試員",
                                     methodology_dir=self.meth_dir, readme_path=readme)
        self.assertIn("A 檔內容：先講重點。", result.text)
        self.assertIn("B 檔內容：再講重點。", result.text)
        self.assertIn("a.md", result.text)
        self.assertEqual(result.missing_files, [])
        self.assertEqual(self._audit_rows(), [])  # 檔案都在，不該有缺席稽核

    def test_missing_file_gracefully_skipped_and_audited(self):
        readme = self._write_readme("| 測試任務 | `a.md`、`missing.md` |\n")
        (self.meth_dir / "a.md").write_text("A 檔內容", encoding="utf-8")

        result = methodology.compile(self.conn, ["測試任務"], brand_id="brd_虛構",
                                     actor="測試員", methodology_dir=self.meth_dir,
                                     readme_path=readme)
        self.assertIn("A 檔內容", result.text)  # 流程照走，沒缺席的檔案照樣進 prompt
        self.assertNotIn("missing.md 內容", result.text)
        self.assertEqual(result.missing_files, ["missing.md"])  # 頁面誠實標注用

        rows = self._audit_rows()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["entity_type"], "methodology_file")
        self.assertEqual(rows[0]["entity_id"], "missing.md")
        self.assertEqual(rows[0]["action"], "missing")
        self.assertEqual(rows[0]["brand_id"], "brd_虛構")
        self.assertIn("missing.md", rows[0]["reason"])

    def test_unknown_task_label_returns_empty_no_audit(self):
        readme = self._write_readme("| 測試任務 | `a.md` |\n")
        (self.meth_dir / "a.md").write_text("A 檔內容", encoding="utf-8")

        result = methodology.compile(self.conn, ["查無此任務型別"], actor="測試員",
                                     methodology_dir=self.meth_dir, readme_path=readme)
        self.assertEqual(result.text, "")
        self.assertEqual(result.missing_files, [])
        self.assertEqual(self._audit_rows(), [])

    def test_multiple_task_labels_union_dedup_preserve_order(self):
        readme = self._write_readme(
            "| 任務甲 | `a.md`、`b.md` |\n| 任務乙 | `b.md`、`c.md` |\n"
        )
        (self.meth_dir / "a.md").write_text("A", encoding="utf-8")
        (self.meth_dir / "b.md").write_text("B", encoding="utf-8")
        (self.meth_dir / "c.md").write_text("C", encoding="utf-8")

        result = methodology.compile(self.conn, ["任務甲", "任務乙"], actor="測試員",
                                     methodology_dir=self.meth_dir, readme_path=readme)
        # b.md 只該出現一次（聯集去重）
        self.assertEqual(result.text.count("【方法論：b.md】"), 1)
        self.assertIn("【方法論：a.md】", result.text)
        self.assertIn("【方法論：c.md】", result.text)

    def test_changing_table_changes_output_without_touching_code(self):
        """改對照表（同一份 README，不同內容），輸出跟著變——程式完全沒改。"""
        (self.meth_dir / "a.md").write_text("A 檔內容", encoding="utf-8")
        (self.meth_dir / "b.md").write_text("B 檔內容", encoding="utf-8")

        readme_v1 = self._write_readme("| 測試任務 | `a.md` |\n")
        result_v1 = methodology.compile(self.conn, ["測試任務"], actor="測試員",
                                        methodology_dir=self.meth_dir, readme_path=readme_v1)
        self.assertIn("A 檔內容", result_v1.text)
        self.assertNotIn("B 檔內容", result_v1.text)

        readme_v2 = self._write_readme("| 測試任務 | `a.md`、`b.md` |\n")
        result_v2 = methodology.compile(self.conn, ["測試任務"], actor="測試員",
                                        methodology_dir=self.meth_dir, readme_path=readme_v2)
        self.assertIn("A 檔內容", result_v2.text)
        self.assertIn("B 檔內容", result_v2.text)  # 對照表多列一個檔，內容就跟著多出來


class MethodologyLastVerifiedDateTest(unittest.TestCase):
    """每份方法論檔的 frontmatter 都要記錄最後查證日：改完內容忘了更新日期，
    下次沒人知道這份檔上次跟來源核對是什麼時候。

    只驗「有、且是合法的過去日期」，不設到期紅燈——方法論重萃取要開發環境才做得到，
    到期提醒放這裡會在無關的 commit 上突然變紅（維護規則第 1 條）。"""

    EXPECTED_FILES = [
        "ads.md", "ad-creative.md", "ab-testing.md", "copywriting.md",
        "creative-matrix.md", "customer-voice.md", "README.md",
    ]

    def test_every_methodology_file_has_a_last_verified_date(self):
        today = date.today()
        for name in self.EXPECTED_FILES:
            path = METHODOLOGY_DIR / name
            self.assertTrue(path.is_file(), f"{path} 不存在")
            frontmatter = path.read_text(encoding="utf-8").split("---")[1]
            match = re.search(r"最後查證日:\s*(\d{4}-\d{2}-\d{2})", frontmatter)
            self.assertIsNotNone(match, f"{name} frontmatter 缺最後查證日")
            verified = date.fromisoformat(match.group(1))
            self.assertLessEqual(verified, today, f"{name} 最後查證日是未來日期：{verified}")


class MethodologyLineCapTest(unittest.TestCase):
    """方法論檔是無條件整份注入 prompt 的程式零件（ADR 0001），每一行每次生成都要付 token。
    這裡是唯一沒有 progressive disclosure 可用的地方，所以上限卡死。"""

    LINE_CAP = 150

    def test_no_methodology_file_exceeds_the_line_cap(self):
        for path in sorted(METHODOLOGY_DIR.glob("*.md")):
            lines = len(path.read_text(encoding="utf-8").splitlines())
            self.assertLessEqual(
                lines, self.LINE_CAP,
                f"{path.name} 有 {lines} 行，超過 {self.LINE_CAP} 行上限。"
                "請精簡內容，不要放寬上限——這個檔每次生成都會被整份塞進 prompt。",
            )


if __name__ == "__main__":
    unittest.main()
