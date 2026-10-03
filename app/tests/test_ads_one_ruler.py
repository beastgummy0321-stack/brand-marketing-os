"""app/tests/test_ads_one_ruler.py — F29-I01 static falsifier for ads.md §6.33 "One ruler": every
judgement uses the cap grade; the trend `class` is a footnote no decision reads.

Scans every non-test Python file under `app/ads` for a read of the triage `class` key
(`x["class"]` or `x.get("class")`). The only allowed reader is the trend-note tally in
`triage.py` (`_trend_counts`, the queue's display-only `counts`). A new reader anywhere else --
a queue rule, a cleanup cut, a month bucket -- fails here, naming the file, function and line.

F48 Contract R (backend twin of `frontend/src/components/ads/oneRuler.test.ts`): the ruler's
numbers live only in `learning_rank.py` and `triage.py`. A ruler-shaped literal (1.2, 1.3, 1.5,
0.02, 3, 5, 7, 10) compared with, or multiplied into, anything named like spend／result／sales／
cost／cap／target／purchase／days anywhere else in `app/ads` fails, naming file, function and line.
`GET …/rules` (Contract R-API) serves exactly the module constants.

F48-I02: a dict literal keyed by two or more grade words (a grade -> decision table like the old
`settle._FATE`) outside those two files fails too; derived judgements read `learning_rank.rank`
or `triage` instead.

F48-I03 (Contract W): `record_learning` is called in `app/ads` only inside `ads_learnings.write`,
whose `product_id` is a required keyword; any other call fails, naming file, function and line.
"""

import ast
import inspect
import re
import unittest
from pathlib import Path
from unittest import mock

from fastapi.testclient import TestClient

import app.main as main
from app.ads import ab_pairs, ads_learnings, experiments, learning_rank, month_summary, triage
from app.brand_intelligence import repository as brands
from app.core import db

ADS_DIR = Path(__file__).resolve().parent.parent / "ads"
# (file relative to app/ads, enclosing function) pairs allowed to read `class`.
ALLOWED = {("triage.py", "_trend_counts")}

# -- F48 Contract R: ruler literals ---------------------------------------------------------------

RULER_FILES = {"learning_rank.py", "triage.py"}
RULER_NUMBERS = {1.2, 1.3, 1.5, 0.02, 3, 5, 7, 10}
RULER_OPERAND = re.compile(r"spend|result|sales|cost|cap|target|purchase|days")
# (file, function) -> why a ruler-shaped literal there is not a grading rule. Never widen this to
# hide a rule: import the constant from `triage`／`learning_rank` instead.
NOT_A_RULER = {
    ("assets.py", "_variant_count"): "campaign length -> how many images to make, not a grade",
}
# (file, function) -> the issue that moves it onto the ruler constants and deletes the entry.
PENDING: dict = {}

# F48-I02: a dict keyed by grade words is a second grade -> decision table (the old `settle._FATE`
# and `triage_capacity._CLOSE_RANK` were); judgements derive from `learning_rank`／`triage` only.
GRADE_WORDS = {
    "on_target", "watch", "over", "wasted", "划算", "偏貴", "太貴", "沒賣出",
}
# (file, variable) -> why a grade-keyed table there is not a judgement. Never widen to hide one.
GRADE_TABLE_ALLOWED = {
    ("triage_capacity.py", "GRADE_RANK"):
        "decision memory: a remembered ad returns only when its grade got worse (F29 Contract B)",
}


def _is_class_key(node) -> bool:
    return isinstance(node, ast.Constant) and node.value == "class"


def _parents(tree) -> dict:
    parents = {}
    for parent in ast.walk(tree):
        for child in ast.iter_child_nodes(parent):
            parents[child] = parent
    return parents


def _enclosing(parents, node) -> str:
    while node in parents:
        node = parents[node]
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            return node.name
    return "<module>"


def _class_reads(tree):
    """Yield `(function_name, lineno)` for every `x["class"]` load and `x.get("class", ...)`."""
    parents = _parents(tree)
    for node in ast.walk(tree):
        if isinstance(node, ast.Subscript) and isinstance(node.ctx, ast.Load) \
                and _is_class_key(node.slice):
            yield _enclosing(parents, node), node.lineno
        elif isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) \
                and node.func.attr == "get" and node.args and _is_class_key(node.args[0]):
            yield _enclosing(parents, node), node.lineno


def _is_ruler_number(node) -> bool:
    return isinstance(node, ast.Constant) and type(node.value) in (int, float) \
        and node.value in RULER_NUMBERS


def _operand_names(node):
    """Every identifier, attribute and string key inside `node`, skipping `len(...)` (a count of
    items, e.g. `len(days) > 3` truncating a list, is never a money or sample rule)."""
    stack = [node]
    while stack:
        current = stack.pop()
        if isinstance(current, ast.Call) and isinstance(current.func, ast.Name) \
                and current.func.id == "len":
            continue
        if isinstance(current, ast.Name):
            yield current.id
        elif isinstance(current, ast.Attribute):
            yield current.attr
        elif isinstance(current, ast.Constant) and isinstance(current.value, str):
            yield current.value
        stack.extend(ast.iter_child_nodes(current))


def _ruler_literals(tree):
    """Yield `(function_name, lineno, value)` for every ruler-shaped literal in a `Compare` or
    `BinOp` whose other operand names spend／result／sales／cost／cap／target／purchase／days."""
    parents = _parents(tree)
    for node in ast.walk(tree):
        if isinstance(node, ast.Compare):
            operands = [node.left, *node.comparators]
        elif isinstance(node, ast.BinOp):
            operands = [node.left, node.right]
        else:
            continue
        for index, operand in enumerate(operands):
            if not _is_ruler_number(operand):
                continue
            others = [o for i, o in enumerate(operands) if i != index]
            if any(RULER_OPERAND.search(name.lower())
                   for other in others for name in _operand_names(other)):
                yield _enclosing(parents, node), node.lineno, operand.value


def _grade_tables(tree):
    """Yield `(name, lineno)` for every dict literal with two or more grade-word keys -- `name` is
    the variable it is assigned to (else the enclosing function)."""
    parents = _parents(tree)
    for node in ast.walk(tree):
        if not isinstance(node, ast.Dict):
            continue
        keys = [k.value for k in node.keys
                if isinstance(k, ast.Constant) and isinstance(k.value, str)]
        if len(GRADE_WORDS.intersection(keys)) < 2:
            continue
        parent = parents.get(node)
        if isinstance(parent, ast.Assign | ast.AnnAssign):
            targets = parent.targets if isinstance(parent, ast.Assign) else [parent.target]
            names = [t.id for t in targets if isinstance(t, ast.Name)]
            if names:
                yield names[0], node.lineno
                continue
        yield _enclosing(parents, node), node.lineno


def _ads_files():
    return [p for p in ADS_DIR.rglob("*.py") if "tests" not in p.parts]


class OneRulerTest(unittest.TestCase):
    def test_no_decision_reads_the_trend_class(self):
        offenders = []
        files = _ads_files()
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


class RulerLiteralTest(unittest.TestCase):
    def test_ruler_numbers_live_only_in_the_two_ruler_modules(self):
        offenders, seen_allowed = [], set()
        files = _ads_files()
        self.assertTrue(files)
        for path in files:
            relative = path.relative_to(ADS_DIR).as_posix()
            if relative in RULER_FILES:
                continue
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for function, line, value in _ruler_literals(tree):
                key = (relative, function)
                if key in NOT_A_RULER or key in PENDING:
                    seen_allowed.add(key)
                    continue
                offenders.append(f"app/ads/{relative}:{line} in {function}(): {value}")
        self.assertEqual(
            offenders, [],
            "a ruler number outside learning_rank.py／triage.py -- import the constant (F48 R)",
        )
        # An allow entry whose literal is gone must go too (the lists only ever shrink).
        self.assertEqual(set(NOT_A_RULER) | set(PENDING), seen_allowed)

    def test_the_scan_sees_a_planted_offender(self):
        tree = ast.parse(
            "def judge(item, cap, sales, days):\n"
            "    if item['spend'] >= 3 * cap:\n"
            "        return 'wasted'\n"
            "    return item['cost'] <= cap * 1.2 or sales < 5 or days >= 7\n"
        )
        self.assertEqual(
            sorted((f, v) for f, _, v in _ruler_literals(tree)),
            [("judge", 1.2), ("judge", 3), ("judge", 5), ("judge", 7)],
        )

    def test_no_grade_keyed_table_outside_the_two_ruler_modules(self):
        offenders, seen_allowed = [], set()
        for path in _ads_files():
            relative = path.relative_to(ADS_DIR).as_posix()
            if relative in RULER_FILES:
                continue
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for name, line in _grade_tables(tree):
                if (relative, name) in GRADE_TABLE_ALLOWED:
                    seen_allowed.add((relative, name))
                    continue
                offenders.append(f"app/ads/{relative}:{line} {name}")
        self.assertEqual(
            offenders, [],
            "a grade -> decision table outside learning_rank.py／triage.py -- derive it from "
            "learning_rank.rank or triage (F48 R)",
        )
        self.assertEqual(set(GRADE_TABLE_ALLOWED), seen_allowed)

    def test_the_grade_table_scan_sees_a_planted_fate_table(self):
        tree = ast.parse(
            "_FATE = {'on_target': 'effective', 'over': 'ineffective'}\n"
            "def pick(row):\n"
            "    return {'太貴': 1, '沒賣出': 2}[row]\n"
            "ONE = {'on_target': 1}\n"
        )
        self.assertEqual([name for name, _ in _grade_tables(tree)], ["_FATE", "pick"])

    def test_the_scan_ignores_slices_ranges_counts_and_unrelated_names(self):
        tree = ast.parse(
            "def show(days, rows, spend, page):\n"
            "    for _ in range(3):\n"
            "        pass\n"
            "    head = rows[:3]\n"
            "    more = len(days) > 3\n"
            "    width = page * 3\n"
            "    return head, more, width, spend + 1\n"
        )
        self.assertEqual(list(_ruler_literals(tree)), [])


# -- F48 Contract W: one learning writer ----------------------------------------------------------

# (file relative to app/ads, enclosing function) -- the only place a ledger row is written.
LEARNING_WRITER = ("ads_learnings.py", "write")


def _record_learning_calls(tree):
    """Yield `(function_name, lineno)` for every `x.record_learning(...)` / `record_learning(...)`
    call and every `from … import record_learning` (an alias would hide the call)."""
    parents = _parents(tree)
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            func = node.func
            name = func.attr if isinstance(func, ast.Attribute) else \
                func.id if isinstance(func, ast.Name) else None
            if name == "record_learning":
                yield _enclosing(parents, node), node.lineno
        elif isinstance(node, ast.ImportFrom) \
                and any(alias.name == "record_learning" for alias in node.names):
            yield _enclosing(parents, node), node.lineno


class OneLearningWriterTest(unittest.TestCase):
    """F48 Contract W: every `learning_ledger` row from `app/ads` goes through
    `ads_learnings.write` (which requires the sell-way `product_id`)."""

    def test_record_learning_is_called_only_in_ads_learnings_write(self):
        offenders, writers = [], []
        for path in _ads_files():
            relative = path.relative_to(ADS_DIR).as_posix()
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for function, line in _record_learning_calls(tree):
                if (relative, function) == LEARNING_WRITER:
                    writers.append(line)
                    continue
                offenders.append(f"app/ads/{relative}:{line} in {function}()")
        self.assertEqual(
            offenders, [],
            "a learning written around ads_learnings.write -- call it instead (F48 W)",
        )
        # The one writer still exists and is the one call (moving it moves this entry).
        self.assertEqual(len(writers), 1)

    def test_the_scan_sees_a_planted_offender(self):
        tree = ast.parse(
            "from app.brand_intelligence.repository import record_learning\n"
            "def close(conn, brand):\n"
            "    bi_repo.record_learning(conn, brand, actor='x')\n"
            "    record_learning(conn, brand)\n"
            "def fine(rows):\n"
            "    return rows.list_learnings()\n"
        )
        self.assertEqual(
            sorted(_record_learning_calls(tree)),
            [("<module>", 1), ("close", 3), ("close", 4)],
        )

    def test_product_id_is_a_required_keyword(self):
        product_id = inspect.signature(ads_learnings.write).parameters["product_id"]
        self.assertIs(product_id.kind, inspect.Parameter.KEYWORD_ONLY)
        self.assertIs(product_id.default, inspect.Parameter.empty)


class RulesEndpointTest(unittest.TestCase):
    """`GET /api/ads/brands/{b}/rules` (Contract R-API) serves the ruler modules' own constants."""

    def setUp(self):
        self.conn = db.current()
        self.brand = brands.create_brand(
            self.conn, org_id=db.DEV_ORG_ID, name="尺規測試", actor="test", client_name=None,
        )["id"]
        self.conn.commit()

    def test_served_rules_equal_the_module_constants(self):
        response = TestClient(main.app).get(f"/api/ads/brands/{self.brand}/rules")
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertEqual(set(body), {"grade", "ab", "labels", "glossary"})
        self.assertEqual(body["grade"], {
            "watch_band": triage.WATCH_BAND,
            "unsold_spend_multiple": triage.STOP_LOSS_SPEND_MULTIPLE,
            "min_results": triage.MIN_RESULT_EVENTS, "min_days": triage.WINDOW_STEPS[0],
            "sample_few": learning_rank.SAMPLE_FEW, "near_best": learning_rank.NEAR_BEST,
            "break_even_band": triage.BREAK_EVEN_BAND,
        })
        self.assertEqual(body["ab"], {
            "min_days": experiments.DEFAULT_RULES["min_days"],
            "min_conversions_each": experiments.DEFAULT_RULES["min_conversions_each"],
            "relative_difference": experiments.DEFAULT_RULES["relative_difference"],
        })
        self.assertEqual(body["labels"], {
            "grade": {
                "on_target": triage.GRADE_LABELS["on_target"],
                "watch": triage.GRADE_LABELS["watch"], "over": triage.GRADE_LABELS["over"],
                "wasted": triage.GRADE_LABELS["wasted"], "too_new": triage.TOO_NEW_LABEL,
                "no_data": triage.NO_DATA_LABEL, "no_target": triage.GRADE_LABELS["no_target"],
            },
            "verdict": {
                "keep": learning_rank.VERDICT_LABELS["keep"],
                "keep_relative": learning_rank.VERDICT_LABELS["keep_relative"],
                "replace": learning_rank.VERDICT_LABELS["replace"],
            },
            "flags": {
                "few": learning_rank.FLAG_FEW, "relative": learning_rank.FLAG_RELATIVE,
                "relative_no_cap": learning_rank.FLAG_RELATIVE_NO_CAP,
            },
        })
        self.assertEqual(body["glossary"], triage.rules()["glossary"])
        self.assertEqual(
            set(body["glossary"]),
            {"cap", "on_target", "watch", "over", "wasted", "thin", "money", "notebook",
             "break_even"},
        )

    def test_ab_and_month_rulers_read_the_ruler_modules(self):
        # F48-I02 "derived rulers": the A/B sample thresholds are triage's own constants.
        self.assertEqual(experiments.DEFAULT_RULES["min_days"], triage.WINDOW_STEPS[0])
        self.assertEqual(experiments.DEFAULT_RULES["min_conversions_each"],
                         triage.MIN_RESULT_EVENTS)
        self.assertEqual(ab_pairs.RULES, experiments.DEFAULT_RULES)
        # The month review's met／missed is triage's cost grade.
        cap = 100
        self.assertEqual(month_summary._verdict(cap, cap), "met")
        self.assertEqual(month_summary._verdict(cap * triage.WATCH_BAND, cap), "missed")
        self.assertEqual(month_summary._verdict(None, cap), "unjudged")
        self.assertEqual(month_summary._verdict(50, None), "unjudged")

    def test_glossary_sentences_carry_todays_numbers(self):
        glossary = triage.rules()["glossary"]
        # Today's `patterns/glossary.ts` wording, numbers built from the constants.
        self.assertEqual(glossary["watch"], "每筆廣告費超過上限，但超過不到 2 成")
        self.assertEqual(glossary["over"], "每筆廣告費超過上限 2 成以上，賣越多虧越多")
        self.assertEqual(glossary["wasted"], "花到上限 3 倍的錢，還一筆都沒賣出")
        self.assertEqual(
            glossary["money"],
            "拿每筆廣告費跟打平線比：比它低是有賺，比它高是在虧，差不到 2% 算剛好打平",
        )
        self.assertEqual(
            glossary["thin"],
            "賣出的廣告都有分數；還沒賣出且花不到上限 3 倍的先標「剛開始」；"
            "成交少於 5 筆標「樣本少」",
        )
        # The break-even value part 「（這裡是 X）」 is the frontend's to append.
        self.assertNotIn("這裡是", glossary["break_even"])

    def test_glossary_numbers_follow_the_constants(self):
        # A changed constant changes the sentence -- the wording never holds its own copy.
        with mock.patch.object(triage, "WATCH_BAND", 1.3), \
                mock.patch.object(triage, "STOP_LOSS_SPEND_MULTIPLE", 4), \
                mock.patch.object(triage, "BREAK_EVEN_BAND", 0.05):
            glossary = triage.rules()["glossary"]
        self.assertIn("不到 3 成", glossary["watch"])
        self.assertIn("上限 4 倍", glossary["wasted"])
        self.assertIn("差不到 5%", glossary["money"])


if __name__ == "__main__":
    unittest.main()
