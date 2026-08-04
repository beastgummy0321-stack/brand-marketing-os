# -*- coding: utf-8 -*-
"""app/tests/test_rule_checks.py — 決策 0031 第1條「無檢查不成規則」的檢查。

`docs/rule-checks.md` 是硬規則 → 檢查對照表。這份測試不要求表裡的規則都真的有檢查
（多數目前是「補檢查欠帳」，老實記債），只要求：

1. 表格式正確（每列欄數與表頭一致）。
2. 每一列「檢查方式」欄非空——不能連「無」都不寫。
3. 「檢查方式」欄裡凡是寫成 `app/tests/xxx.py`、`app/tools/xxx.py`、`docs/xxx.md`
   或 `.gitignore` 這種看起來像「測試檔或腳本路徑」的反引號片段，該檔案必須真的存在
   ——宣稱有檢查就要指得到東西，不能是空話。
4. 「狀態」欄只能是已配檢查／補檢查欠帳／豁免三種之一（含豁免的附註變體）。
"""

import re
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
RULE_CHECKS_PATH = REPO_ROOT / "docs" / "rule-checks.md"

# 只認「看起來像真實檢查位置」的片段：測試檔、工具腳本、docs 底下的 md、.gitignore。
# 不吃只是文中提到的檔名（例如「現況無 package.json」那種反面陳述）。
CHECK_PATH_RE = re.compile(
    r"^(app/(?:tests|tools)/[\w./-]+\.py|docs/[\w./-]+\.md|\.gitignore)$"
)

ALLOWED_STATUS_PREFIXES = ("已配檢查", "補檢查欠帳", "豁免")


def _parse_tables(text):
    """回傳 [(header_cells, [row_cells, ...]), ...]。極簡 GFM 表格解析器，
    只認「表頭列 + 分隔列（全是 -/:/|/空白）+ 資料列」這個標準形狀。"""
    lines = text.splitlines()
    tables = []
    i = 0

    def _is_row(line):
        s = line.strip()
        return s.startswith("|") and s.endswith("|") and len(s) >= 2

    def _cells(line):
        s = line.strip()[1:-1]  # 去掉頭尾的 |
        return [c.strip() for c in s.split("|")]

    def _is_separator(line):
        s = line.strip()
        return _is_row(line) and set(s) <= set("|-: ")

    while i < len(lines):
        if _is_row(lines[i]) and i + 1 < len(lines) and _is_separator(lines[i + 1]):
            header = _cells(lines[i])
            j = i + 2
            rows = []
            while j < len(lines) and _is_row(lines[j]):
                rows.append(_cells(lines[j]))
                j += 1
            tables.append((header, rows))
            i = j
        else:
            i += 1
    return tables


class RuleChecksDocExistsTest(unittest.TestCase):
    def test_file_exists_and_readable(self):
        self.assertTrue(RULE_CHECKS_PATH.is_file(), f"{RULE_CHECKS_PATH} 不存在")


class RuleChecksTableFormatTest(unittest.TestCase):
    """驗證所有帶「檢查方式」欄的表格：格式正確＋檢查方式欄非空＋狀態欄合法。"""

    @classmethod
    def setUpClass(cls):
        text = RULE_CHECKS_PATH.read_text(encoding="utf-8")
        cls.tables = _parse_tables(text)
        cls.rule_tables = [
            (header, rows) for header, rows in cls.tables if "檢查方式" in header
        ]

    def test_has_at_least_one_rule_table(self):
        self.assertGreaterEqual(
            len(self.rule_tables), 1, "docs/rule-checks.md 裡找不到含「檢查方式」欄的表格"
        )

    def test_every_row_matches_header_column_count(self):
        for header, rows in self.rule_tables:
            for idx, row in enumerate(rows):
                self.assertEqual(
                    len(row), len(header),
                    f"表頭 {header} 第 {idx} 列欄數 {len(row)} 與表頭欄數 {len(header)} 不符：{row}",
                )

    def test_check_method_column_is_never_empty(self):
        for header, rows in self.rule_tables:
            check_idx = header.index("檢查方式")
            for row in rows:
                self.assertTrue(
                    row[check_idx].strip(),
                    f"「檢查方式」欄不得空白：{row}",
                )

    def test_status_column_uses_allowed_values(self):
        for header, rows in self.rule_tables:
            self.assertIn("狀態", header, f"表頭缺「狀態」欄：{header}")
            status_idx = header.index("狀態")
            for row in rows:
                status = row[status_idx].strip()
                self.assertTrue(
                    status.startswith(ALLOWED_STATUS_PREFIXES),
                    f"「狀態」欄值不合法（只能是已配檢查／補檢查欠帳／豁免其中之一）：{row}",
                )

    def test_referenced_check_paths_actually_exist(self):
        """凡「檢查方式」欄裡寫成測試檔／腳本路徑的反引號片段，該檔案必須存在。"""
        checked_any = False
        for header, rows in self.rule_tables:
            check_idx = header.index("檢查方式")
            for row in rows:
                for token in re.findall(r"`([^`]+)`", row[check_idx]):
                    if CHECK_PATH_RE.match(token):
                        checked_any = True
                        path = REPO_ROOT / token
                        self.assertTrue(
                            path.is_file(),
                            f"「檢查方式」欄宣稱的路徑不存在：{token}（列：{row}）",
                        )
        self.assertTrue(checked_any, "整份表格找不到任何看起來像真實路徑的檢查方式片段")


if __name__ == "__main__":
    unittest.main()
