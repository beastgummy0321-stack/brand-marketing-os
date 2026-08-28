"""app/tests/test_learning_ledger_unidirectional.py — 學習單向鐵律的機器檢查（修憲落地 A3）。

鐵則 3／architecture-rules.md A1：「學習只能補充事實層，永遠不得回寫或改寫事實層。」
`learning_ledger` 遷入品牌永久層後，跟事實層資料表（brand_fact／product_fact）住進同一個
模組檔案，這道檢查存在的理由正是防止「品牌永久層」這個新層名讓下一個實作者誤以為
事實與學習同權——靜態掃描 `app/brand_intelligence/repository.py`：任何寫入 learning_ledger
的函式，函式本體不得同時對 brand_fact／product_fact 下 INSERT／UPDATE／DELETE。

與 `test_architecture_boundaries.py` 同一套字面掃描天花板
（ponytail: 非 AST-level SQL 解析，非本票範圍，真的需要更嚴謹時再升級）。
"""

import ast
import re
import unittest
from pathlib import Path

REPO_PATH = Path(__file__).resolve().parent.parent / "brand_intelligence" / "repository.py"

_WRITE_TABLE_REF = re.compile(
    r"(?:INSERT INTO|UPDATE|DELETE FROM)\s+([a-zA-Z_][a-zA-Z0-9_]*)", re.IGNORECASE)

FACT_TABLES = {"brand_fact", "product_fact"}


def _write_tables_in(source_segment: str) -> set:
    return {t.lower() for t in _WRITE_TABLE_REF.findall(source_segment)}


class LearningLedgerUnidirectionalTest(unittest.TestCase):
    def test_ledger_write_functions_never_touch_fact_tables(self):
        source = REPO_PATH.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(REPO_PATH))
        offenders = []
        for node in ast.walk(tree):
            if not isinstance(node, ast.FunctionDef):
                continue
            body_text = ast.get_source_segment(source, node) or ""
            tables_written = _write_tables_in(body_text)
            if "learning_ledger" not in tables_written:
                continue
            hit = tables_written & FACT_TABLES
            if hit:
                offenders.append(f"{node.name}() 同時寫入 learning_ledger 與 {hit}")
        self.assertEqual(
            offenders, [],
            "以下函式同時寫入 learning_ledger 與事實層資料表，違反鐵則3單向鐵律"
            "（學習只能補充事實層，永遠不得回寫或改寫事實層）：\n" + "\n".join(offenders),
        )

    def test_scan_actually_detects_a_synthetic_violation(self):
        """TDD 證據：證明這道掃描真的抓得到問題，不是空氣測試——修好之前，把這段虛構
        違例貼進真檔案跑一次上面那個測試會轉紅；這裡不動真檔案，只驗證掃描機制本身有牙齒。"""
        fake_source = (
            "def bad_write():\n"
            "    conn.execute(\"INSERT INTO learning_ledger (id) VALUES (?)\", (1,))\n"
            "    conn.execute(\"UPDATE brand_fact SET value = ? WHERE id = ?\", (1, 2))\n"
        )
        tree = ast.parse(fake_source)
        node = tree.body[0]
        tables_written = _write_tables_in(ast.get_source_segment(fake_source, node))
        self.assertIn("learning_ledger", tables_written)
        self.assertTrue(tables_written & FACT_TABLES, "掃描機制沒抓到虛構違例，檢查本身是壞的")


if __name__ == "__main__":
    unittest.main()
