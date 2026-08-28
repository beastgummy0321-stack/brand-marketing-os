"""app/tests/test_methodology.py — 方法論載入器（票 11）。

驗對照表解析、缺檔優雅缺席＋稽核紀錄、改對照表後行為跟著變（程式不寫死清單）。
不打真實網路請求；不涉及品牌資料，直接用 core db 即可。
"""

import re
import tempfile
import unittest
from datetime import date
from pathlib import Path

from app.brand_intelligence import repository as repo
from app.core import db, vocab
from app.llm import methodology

REPO_ROOT = Path(__file__).resolve().parents[2]
METHODOLOGY_DIR = REPO_ROOT / "app" / "methodology"


class MethodologyTableParseTest(unittest.TestCase):
    """對真實 app/methodology/README.md 的解析——回歸鎖定既有對照表內容。"""

    def test_real_readme_parses_known_task_labels(self):
        table = methodology.load_table()
        # load_table() 回傳純檔名清單（條件由 compile() 處理），所以帶（需要：X）的檔名也在裡面
        self.assertEqual(
            table["檔期計畫生成"],
            ["ads-core.md", "ads-commerce.md", "ads-health.md", "ab-testing.md", "customer-voice.md"],
        )
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
        self.conn = db.current()
        # conftest.py 現在是逐模組一個 schema（不是逐測試）：_audit_rows() 查全表，
        # 上一個測試方法（test_missing_file_gracefully_skipped_and_audited）留下的
        # audit_log 列會被這裡的「應該零筆」斷言誤讀成失敗，先清乾淨。
        self.conn.execute("DELETE FROM audit_log")
        self._tmpdir = tempfile.TemporaryDirectory()
        self.meth_dir = Path(self._tmpdir.name) / "methodology"
        self.meth_dir.mkdir()

    def tearDown(self):
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


class MethodologyConditionalFileTest(unittest.TestCase):
    """票 A：檔名後可選加（需要：X）條件，只有品牌對應開關成立才載入。"""

    def setUp(self):
        self.conn = db.current()
        self._tmpdir = tempfile.TemporaryDirectory()
        self.meth_dir = Path(self._tmpdir.name) / "methodology"
        self.meth_dir.mkdir()

    def tearDown(self):
        self._tmpdir.cleanup()

    def _write_readme(self, table_rows: str) -> Path:
        readme = self.meth_dir / "README.md"
        readme.write_text(
            "# 索引\n\n## 任務型別 → 必讀方法論檔對照表\n\n"
            "| 任務型別 | 必讀方法論檔 |\n|---|---|\n" + table_rows + "\n## 維護規則\n之後的段落。\n",
            encoding="utf-8",
        )
        return readme

    def _write_files(self, *names):
        for name in names:
            (self.meth_dir / name).write_text(f"{name} 內容", encoding="utf-8")

    def test_load_table_raw_parses_condition_and_load_table_strips_it(self):
        readme = self._write_readme("| 測試任務 | `a.md`、`b.md`（需要：有商品）、`c.md` |\n")
        raw = methodology.load_table_raw(readme)
        self.assertEqual(raw["測試任務"], [("a.md", None), ("b.md", "有商品"), ("c.md", None)])
        flat = methodology.load_table(readme)  # 向後相容：不含條件，純檔名清單
        self.assertEqual(flat["測試任務"], ["a.md", "b.md", "c.md"])

    def test_compile_brand_id_none_loads_conditional_file_unfiltered(self):
        readme = self._write_readme("| 測試任務 | `a.md`（需要：有商品） |\n")
        self._write_files("a.md")
        result = methodology.compile(self.conn, ["測試任務"], brand_id=None, actor="測試員",
                                     methodology_dir=self.meth_dir, readme_path=readme)
        self.assertIn("a.md 內容", result.text)

    def test_compile_filters_out_conditional_file_when_switch_off(self):
        readme = self._write_readme("| 測試任務 | `a.md`（需要：有商品） |\n")
        self._write_files("a.md")
        bid = repo.create_brand(self.conn, name="虛構品牌無商品", client_name=None, actor="測試員")["id"]
        result = methodology.compile(self.conn, ["測試任務"], brand_id=bid, actor="測試員",
                                     methodology_dir=self.meth_dir, readme_path=readme)
        self.assertNotIn("a.md 內容", result.text)
        self.assertEqual(result.missing_files, [])  # 條件不成立不是缺檔，不該進 missing_files

    def test_compile_includes_conditional_file_when_switch_on(self):
        readme = self._write_readme("| 測試任務 | `a.md`（需要：有商品） |\n")
        self._write_files("a.md")
        bid = repo.create_brand(self.conn, name="虛構品牌有商品", client_name=None, actor="測試員")["id"]
        repo.create_product(self.conn, bid, name="虛構產品", actor="測試員")
        result = methodology.compile(self.conn, ["測試任務"], brand_id=bid, actor="測試員",
                                     methodology_dir=self.meth_dir, readme_path=readme)
        self.assertIn("a.md 內容", result.text)

    def test_loaded_files_records_exactly_what_went_into_the_prompt(self):
        """ADR 0009：同一份對照表，不同品牌的開關會載入不同的檔，事後回推不出來。
        loaded_files 必須只含真的組進 prompt 的檔——條件擋掉的、缺檔的都不算。"""
        readme = self._write_readme(
            "| 測試任務 | `a.md`、`b.md`（需要：有商品）、`c.md`（需要：健康類法規）、`missing.md` |\n")
        self._write_files("a.md", "b.md", "c.md")  # 故意不寫 missing.md
        bid = repo.create_brand(self.conn, name="虛構品牌只有商品", client_name=None,
                                actor="測試員")["id"]
        repo.create_product(self.conn, bid, name="虛構產品", actor="測試員")  # 有商品、無法規

        result = methodology.compile(self.conn, ["測試任務"], brand_id=bid, actor="測試員",
                                     methodology_dir=self.meth_dir, readme_path=readme)
        # a 無條件、b 開關成立 → 載入；c 開關不成立 → 不載入；missing 檔案不在 → 不載入
        self.assertEqual(result.loaded_files, ["a.md", "b.md"])
        self.assertEqual(result.missing_files, ["missing.md"])

    def test_unconditional_file_always_loads_regardless_of_switch(self):
        readme = self._write_readme("| 測試任務 | `a.md`、`b.md`（需要：健康類法規） |\n")
        self._write_files("a.md", "b.md")
        bid = repo.create_brand(self.conn, name="虛構品牌無法規", client_name=None, actor="測試員")["id"]
        result = methodology.compile(self.conn, ["測試任務"], brand_id=bid, actor="測試員",
                                     methodology_dir=self.meth_dir, readme_path=readme)
        self.assertIn("a.md 內容", result.text)
        self.assertNotIn("b.md 內容", result.text)


class MethodologySwitchComputationTest(unittest.TestCase):
    """app.brand_intelligence.repository.compute_methodology_switches 四個開關各自的判定條件。"""

    def setUp(self):
        self.conn = db.current()

    def test_all_switches_off_by_default(self):
        bid = repo.create_brand(self.conn, name="虛構品牌空白", client_name=None, actor="測試員")["id"]
        self.assertEqual(
            repo.compute_methodology_switches(self.conn, bid),
            {"有商品": False, "站內交易": False, "有自有網站": False, "健康類法規": False},
        )

    def test_has_product_switch(self):
        bid = repo.create_brand(self.conn, name="虛構品牌有貨", client_name=None, actor="測試員")["id"]
        repo.create_product(self.conn, bid, name="虛構產品", actor="測試員")
        self.assertTrue(repo.compute_methodology_switches(self.conn, bid)["有商品"])

    def test_purchase_conversion_goal_triggers_transaction_switch(self):
        bid = repo.create_brand(self.conn, name="虛構品牌購買轉換", client_name=None, actor="測試員")["id"]
        repo.set_brand_switches(self.conn, bid, market_region="TW", conversion_goal="purchase",
                                 actor="測試員")
        self.assertTrue(repo.compute_methodology_switches(self.conn, bid)["站內交易"])

    def test_lead_conversion_goal_does_not_trigger_transaction_switch(self):
        bid = repo.create_brand(self.conn, name="虛構品牌名單", client_name=None, actor="測試員")["id"]
        repo.set_brand_switches(self.conn, bid, market_region=None, conversion_goal="lead",
                                 actor="測試員")
        self.assertFalse(repo.compute_methodology_switches(self.conn, bid)["站內交易"])

    def test_website_channel_triggers_switch(self):
        bid = repo.create_brand(self.conn, name="虛構品牌有官網", client_name=None, actor="測試員")["id"]
        repo.create_channel(self.conn, bid, channel_type="website", name="虛構官網", actor="測試員")
        self.assertTrue(repo.compute_methodology_switches(self.conn, bid)["有自有網站"])

    def test_non_website_channel_type_does_not_trigger_switch(self):
        bid = repo.create_brand(self.conn, name="虛構品牌只有粉專", client_name=None, actor="測試員")["id"]
        repo.create_channel(self.conn, bid, channel_type="fb_page", name="虛構粉專", actor="測試員")
        self.assertFalse(repo.compute_methodology_switches(self.conn, bid)["有自有網站"])

    def test_confirmed_regulatory_fact_triggers_switch(self):
        bid = repo.create_brand(self.conn, name="虛構品牌法規", client_name=None, actor="測試員")["id"]
        repo.create_brand_fact(self.conn, bid, fact_type="regulatory", label="法規限制",
                                value="測試內容", status="confirmed", confirmed_by="測試員",
                                actor="測試員")
        self.assertTrue(repo.compute_methodology_switches(self.conn, bid)["健康類法規"])

    def test_pending_regulatory_fact_does_not_trigger_switch(self):
        bid = repo.create_brand(self.conn, name="虛構品牌法規待確認", client_name=None,
                                 actor="測試員")["id"]
        repo.create_brand_fact(self.conn, bid, fact_type="regulatory", label="法規限制",
                                value="測試內容", status="pending", actor="測試員")
        self.assertFalse(repo.compute_methodology_switches(self.conn, bid)["健康類法規"])


class BrandSwitchesWriteTest(unittest.TestCase):
    """app.brand_intelligence.repository.set_brand_switches：寫入 market_region／conversion_goal。"""

    def setUp(self):
        self.conn = db.current()

    def test_set_brand_switches_writes_both_fields(self):
        bid = repo.create_brand(self.conn, name="虛構品牌設定", client_name=None, actor="測試員")["id"]
        after = repo.set_brand_switches(self.conn, bid, market_region="TW",
                                         conversion_goal="purchase", actor="測試員")
        self.assertEqual(after["market_region"], "TW")
        self.assertEqual(after["conversion_goal"], "purchase")

    def test_set_brand_switches_rejects_unknown_conversion_goal(self):
        bid = repo.create_brand(self.conn, name="虛構品牌壞值", client_name=None, actor="測試員")["id"]
        with self.assertRaises(ValueError):
            repo.set_brand_switches(self.conn, bid, market_region="TW", conversion_goal="checkout",
                                     actor="測試員")


class PersonaSwitchDefaultsTest(unittest.TestCase):
    """app.core.vocab.persona_switch_defaults：人設展開成開關預設值的填表捷徑，不進 DB。"""

    def test_every_persona_expands_to_all_four_switches(self):
        for code, _label in vocab.PERSONA_TYPES:
            defaults = vocab.persona_switch_defaults(code)
            self.assertEqual(set(defaults.keys()), {"有商品", "站內交易", "有自有網站", "健康類法規"})

    def test_unknown_persona_raises(self):
        with self.assertRaises(ValueError):
            vocab.persona_switch_defaults("不存在的人設")


class MethodologyLastVerifiedDateTest(unittest.TestCase):
    """每份方法論檔的 frontmatter 都要記錄最後查證日：改完內容忘了更新日期，
    下次沒人知道這份檔上次跟來源核對是什麼時候。

    只驗「有、且是合法的過去日期」，不設到期紅燈——方法論重萃取要開發環境才做得到，
    到期提醒放這裡會在無關的 commit 上突然變紅（維護規則第 1 條）。"""

    MIN_FILES = 7  # 拆檔／新增檔不必回來改這裡；掉到門檻以下代表有檔案被誤刪

    def test_every_methodology_file_has_a_last_verified_date(self):
        today = date.today()
        paths = sorted(METHODOLOGY_DIR.glob("*.md"))
        self.assertGreaterEqual(len(paths), self.MIN_FILES, "方法論檔數量異常，可能被誤刪")
        for path in paths:
            frontmatter = path.read_text(encoding="utf-8").split("---")[1]
            match = re.search(r"最後查證日:\s*(\d{4}-\d{2}-\d{2})", frontmatter)
            self.assertIsNotNone(match, f"{path.name} frontmatter 缺最後查證日")
            verified = date.fromisoformat(match.group(1))
            self.assertLessEqual(verified, today, f"{path.name} 最後查證日是未來日期：{verified}")


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
