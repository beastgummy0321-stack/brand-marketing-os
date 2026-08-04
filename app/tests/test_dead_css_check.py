# -*- coding: utf-8 -*-
"""app/tests/test_dead_css_check.py — 修憲落地票 V7：死碼掃描腳本自檢
（決策 0031 第 1 條「無檢查不成規則」，腳本本身也要有檢查證明真的在抓死碼、
真的不會誤刪動態組名）。

用臨時目錄造一份假的 app.css＋假模板，不碰真正的 `app/static/app.css`／`app/templates`
（跟 `app/tools/capacity_check.py` 自檢用真實檔案內容不同，這裡刻意隔離，才能控制
「已知有死碼」「已知動態前綴」這兩種情境各自的期望值）。
"""

import tempfile
import unittest
from pathlib import Path

from app.tools import dead_css_check as dc


class FindDeadClassesTest(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        root = Path(self._tmpdir.name)
        (root / "app" / "static").mkdir(parents=True)
        (root / "app" / "templates").mkdir(parents=True)
        self.root = root
        self._orig_css = dc.CSS_PATH
        self._orig_tpl_dir = dc.TEMPLATE_DIR
        self._orig_app_dir = dc.APP_DIR
        dc.CSS_PATH = root / "app" / "static" / "app.css"
        dc.TEMPLATE_DIR = root / "app" / "templates"
        dc.APP_DIR = root / "app"

    def tearDown(self):
        dc.CSS_PATH = self._orig_css
        dc.TEMPLATE_DIR = self._orig_tpl_dir
        dc.APP_DIR = self._orig_app_dir
        self._tmpdir.cleanup()

    def _write(self, css: str, template: str) -> None:
        dc.CSS_PATH.write_text(css, encoding="utf-8")
        (dc.TEMPLATE_DIR / "page.html").write_text(template, encoding="utf-8")

    def test_class_used_in_template_is_not_dead(self):
        self._write(".used { color: red; }", '<div class="used">x</div>')
        self.assertEqual(dc.find_dead_classes(), [])

    def test_class_never_referenced_anywhere_is_dead(self):
        self._write(".orphan { color: red; }", '<div class="other">x</div>')
        self.assertEqual(dc.find_dead_classes(), ["orphan"])

    def test_dynamic_prefix_class_is_not_flagged_dead(self):
        """`class="badge badge-{{ kind }}"` 這種前綴＋Jinja 變數組出來的 class，
        原始碼裡不會出現 `badge-warn` 完整字面，但不能被誤判成死碼（票面硬規則：
        動態組名要排除，不要誤刪）。"""
        css = ".badge-warn { color: orange; }\n.badge-ok { color: green; }"
        template = '<span class="badge badge-{{ kind }}">x</span>'
        self._write(css, template)
        self.assertEqual(dc.find_dead_classes(), [])

    def test_class_defined_only_in_comment_is_still_dead(self):
        """CSS 註解裡提到的 class 名稱不算「有定義」，也不算「有用到」。"""
        css = "/* 範例：.example { display: none; } */\n.real { color: red; }"
        self._write(css, '<div class="other">x</div>')
        self.assertEqual(dc.find_dead_classes(), ["real"])

    def test_python_source_counts_as_usage_but_tests_do_not(self):
        """正式程式碼裡出現 class 字面算有用到；`app/tests/` 底下的斷言字面
        （常見 assertNotIn 這種『不該出現』的寫法）不算，避免死碼被誤判成活的。"""
        (self.root / "app" / "tests").mkdir()
        css = ".from-py { color: red; }\n.only-in-test { color: blue; }"
        (dc.TEMPLATE_DIR / "page.html").write_text('<div class="x">x</div>', encoding="utf-8")
        dc.CSS_PATH.write_text(css, encoding="utf-8")
        (self.root / "app" / "views.py").write_text(
            'CLASS = "from-py"\n', encoding="utf-8")
        (self.root / "app" / "tests" / "test_x.py").write_text(
            'self.assertNotIn(\'class="only-in-test"\', html)\n', encoding="utf-8")
        self.assertEqual(dc.find_dead_classes(), ["only-in-test"])

    def test_main_reports_nonzero_exit_when_dead_classes_found(self):
        self._write(".orphan { color: red; }", '<div class="other">x</div>')
        self.assertEqual(dc.main(), 1)

    def test_main_reports_zero_exit_when_clean(self):
        self._write(".used { color: red; }", '<div class="used">x</div>')
        self.assertEqual(dc.main(), 0)


if __name__ == "__main__":
    unittest.main()
