# -*- coding: utf-8 -*-
"""app/tests/test_wording_check.py — 「暫時／本階段／原型階段」用詞檢查
（修憲落地 A6，AGENTS.md 硬性規則 13、決策 0037 第一節第 3 條）。

先用暫存檔證明檢查邏輯本身抓得到真違例、也放得過已附結束條件與引號引用的合法用法，
再對全部規範文件跑一次，斷言結果不超出明文記錄的既有違例清單。
"""

import tempfile
import unittest
from pathlib import Path

from app.tools import wording_check

# 已知違例清單。原本記錄的那幾筆都在已刪除的規範文件裡，清空重來。
KNOWN_WORDING_VIOLATIONS = set()


class DetectionLogicTest(unittest.TestCase):
    """先證明檢查邏輯本身正確，不是只靠現有文件的巧合過關。"""

    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()

    def tearDown(self):
        self._tmpdir.cleanup()

    def _write(self, text: str) -> str:
        path = Path(self._tmpdir.name) / "fixture.md"
        path.write_text(text, encoding="utf-8")
        return str(path)

    def test_bare_usage_without_end_condition_is_flagged(self):
        rel = self._write("本階段先不做深色模式。")
        violations = wording_check.check_file(rel)
        self.assertEqual(len(violations), 1)
        self.assertEqual(violations[0].line, 1)

    def test_usage_with_inline_end_condition_passes(self):
        rel = self._write("「原型階段」＝第一次用真錢跑完一期即結束。")
        self.assertEqual(wording_check.check_file(rel), [])

    def test_usage_citing_a_decision_passes(self):
        rel = self._write("本階段先用 CSV 匯入（決策 0025 定案，屆時改走 API）。")
        self.assertEqual(wording_check.check_file(rel), [])

    def test_word_quoted_as_a_citation_is_exempt(self):
        rel = self._write("紅隊發現「本階段」這個詞被拿來豁免了好幾個危險簡化。")
        self.assertEqual(wording_check.check_file(rel), [])

    def test_end_condition_on_adjacent_line_still_passes(self):
        rel = self._write("本階段先不做深色模式。\n直到正式排上規劃才會動工。\n")
        self.assertEqual(wording_check.check_file(rel), [])

    def test_far_away_decision_reference_does_not_leak_across_paragraphs(self):
        rel = self._write(
            "本階段先不做深色模式。\n\n"
            "（以下完全無關的段落）某功能沿用決策 0025 的既定做法。\n"
        )
        violations = wording_check.check_file(rel)
        self.assertEqual(len(violations), 1)


class RegulationFilesTest(unittest.TestCase):
    """全部規範文件掃過一次：不超出明文記錄的既有違例清單。"""

    def test_no_undocumented_wording_violations(self):
        found = {(v.file, v.line) for v in wording_check.check_all()}
        unexpected = found - KNOWN_WORDING_VIOLATIONS
        self.assertEqual(
            unexpected, set(),
            "以下用詞違例未被記錄，先確認過再加進 KNOWN_WORDING_VIOLATIONS，"
            "或直接修正該文件附上結束條件：\n"
            + "\n".join(f"{f}:{n}" for f, n in sorted(unexpected)),
        )
