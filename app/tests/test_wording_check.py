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

# 已知違例（修憲落地 A6 首次盤點，2026-08-03；狀態見 docs/rule-checks.md）。
# 這份清單本身有 test_known_violations_list_is_not_stale 把關，修好了要記得同步刪除兩邊。
# 都是「深色模式本階段不做」／「停用期間暫時沒有學習能力」這類既有文件裡的舊措辭，
# 需要的是產品判斷（什麼時候該有深色模式／學習迴路何時恢復），不是本票能替決定的事，
# 不在本票範圍內改寫這些文件的實質內容。
KNOWN_WORDING_VIOLATIONS = {
    ("DESIGN.md", 93),
    ("DESIGN.md", 321),
    ("DESIGN.md", 358),
    ("docs/design-spec/tokens.md", 11),
    ("docs/decisions/0035-learning-loop-halt-and-rebuild.md", 87),
}


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
            "以下用詞違例未被記錄，先確認過再加進 KNOWN_WORDING_VIOLATIONS 並同步"
            " docs/rule-checks.md，或直接修正該文件附上結束條件：\n"
            + "\n".join(f"{f}:{n}" for f, n in sorted(unexpected)),
        )

    def test_known_violations_list_is_not_stale(self):
        """清單裡的每一項，檔案裡真的還踩得到——避免修好了卻忘記從清單刪掉。"""
        found = {(v.file, v.line) for v in wording_check.check_all()}
        for entry in KNOWN_WORDING_VIOLATIONS:
            self.assertIn(
                entry, found,
                f"{entry[0]}:{entry[1]} 已經不再違例，KNOWN_WORDING_VIOLATIONS 該清掉這項了"
                "（順手修好了記得同步更新 docs/rule-checks.md）",
            )

    def test_decision_0037_itself_is_fully_compliant(self):
        """這批修憲自己寫的定義文（0037）——已附結束條件的用法要能通過，不是意外過關。"""
        self.assertEqual(
            wording_check.check_file("docs/decisions/0037-prototype-phase-and-architecture.md"),
            [],
        )

    def test_agents_md_rule_13_itself_is_compliant(self):
        self.assertEqual(
            [v for v in wording_check.check_file("AGENTS.md") if v.line == 43], [],
        )
