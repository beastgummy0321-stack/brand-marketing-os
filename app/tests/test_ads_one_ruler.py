"""app/tests/test_ads_one_ruler.py — F29-I01 static falsifier for ads.md §6.33 "One ruler": every
judgement uses the cap grade; the trend `class` is a footnote no decision reads.

Scans every non-test Python file under `app/ads` for a read of the triage `class` key
(`x["class"]` or `x.get("class")`). The only allowed reader is the trend-note tally in
`triage.py` (`_trend_counts`, the queue's display-only `counts`). A new reader anywhere else --
a queue rule, a cleanup cut, a month bucket -- fails here, naming the file, function and line.
"""

import ast
import unittest
from pathlib import Path

ADS_DIR = Path(__file__).resolve().parent.parent / "ads"
# (file relative to app/ads, enclosing function) pairs allowed to read `class`.
ALLOWED = {("triage.py", "_trend_counts")}


def _is_class_key(node) -> bool:
    return isinstance(node, ast.Constant) and node.value == "class"


def _class_reads(tree):
    """Yield `(function_name, lineno)` for every `x["class"]` load and `x.get("class", ...)`."""
    parents = {}
    for parent in ast.walk(tree):
        for child in ast.iter_child_nodes(parent):
            parents[child] = parent

    def enclosing(node):
        while node in parents:
            node = parents[node]
            if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
                return node.name
        return "<module>"

    for node in ast.walk(tree):
        if isinstance(node, ast.Subscript) and isinstance(node.ctx, ast.Load) \
                and _is_class_key(node.slice):
            yield enclosing(node), node.lineno
        elif isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) \
                and node.func.attr == "get" and node.args and _is_class_key(node.args[0]):
            yield enclosing(node), node.lineno


class OneRulerTest(unittest.TestCase):
    def test_no_decision_reads_the_trend_class(self):
        offenders = []
        files = [p for p in ADS_DIR.rglob("*.py") if "tests" not in p.parts]
        self.assertTrue(files)
        for path in files:
            relative = path.relative_to(ADS_DIR).as_posix()
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for function, line in _class_reads(tree):
                if (relative, function) not in ALLOWED:
                    offenders.append(f"app/ads/{relative}:{line} in {function}()")
        self.assertEqual(offenders, [], "a decision reads the trend `class` (ads.md §6.33)")

    def test_the_scan_sees_both_read_shapes(self):
        # Guard against a scanner that silently finds nothing.
        tree = ast.parse(
            "def rule(item):\n    return item['class'] == 'worse' or item.get('class')\n"
        )
        self.assertEqual([f for f, _ in _class_reads(tree)], ["rule", "rule"])
        # A write (building the item) is not a read.
        self.assertEqual(list(_class_reads(ast.parse("x = {}\nx['class'] = 'flat'\n"))), [])

    def test_the_allowed_reader_still_exists(self):
        # If the tally moves or is renamed, the allow-list must move with it, never widen.
        tree = ast.parse((ADS_DIR / "triage.py").read_text(encoding="utf-8"))
        self.assertIn("_trend_counts", {f for f, _ in _class_reads(tree)})


if __name__ == "__main__":
    unittest.main()
