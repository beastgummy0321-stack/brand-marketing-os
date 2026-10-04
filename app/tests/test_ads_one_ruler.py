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

F48-I07 (Contract M): `round(`／`math.floor(`／`math.ceil(` appear in `app/ads` only in `budget.py`
(the one money calculator) unless the `(file, function)` is listed with why it is not a money
figure's rounding; any other call fails, naming file, function and line.

F49-I01 (Contract L, one lifecycle): a platform status word (ACTIVE, PAUSED, …) written in code
outside `app/ads/adapters/` (allowlist: the change-set pause payload, W19); a `native_status`
comparison outside `lifecycle.py`／`adapters/`; and campaign-selection SQL on `ads_campaign`
(`status != 'closed'`, `status IN (…)`) outside `lifecycle.py` each fail, naming file and line.
"""

import ast
import inspect
import re
import unittest
from pathlib import Path
from unittest import mock

from fastapi.testclient import TestClient

import app.main as main
from app.ads import (
    ab_pairs,
    ads_learnings,
    budget,
    experiments,
    learning_rank,
    month_summary,
    triage,
)
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


# -- F48 Contract M: one money rounding ------------------------------------------------------------

# The one file allowed to round a money figure (`whole`, `daily_of`, `total_of`).
MONEY_FILE = "budget.py"
ROUNDING_CALLS = {"round", "floor", "ceil"}
# (file relative to app/ads, function) -> why the rounding there is not a money figure's rounding.
# Never widen this to hide one: call `budget.whole`／`budget.daily_of`／`budget.total_of` instead.
NOT_MONEY_ROUNDING = {
    ("ab_pairs.py", "_judge_pair"): "an A/B percent difference shown to one decimal",
    ("adapters/simulated.py", "day_rows"):
        "the simulated platform reports cents and whole purchase counts, like a real read",
    ("simulation_recovery.py", "_row"): "simulated platform rows in cents, like a real read",
    ("learning.py", "_number"): "a learning's number printed to two decimals",
    ("learning_rank.py", "_num"): "the stored scope string keeps two decimals (`parse_scope`)",
    ("learning_rank.py", "_parse_num"): "the inverse of `_num`",
    ("outcome.py", "_bucket"): "float noise off a sum of cents (two decimals), not a whole figure",
    ("recovery.py", "_find_gap"): "minutes of a sync gap",
    ("recovery.py", "_steps"): "hours of a sync gap",
    ("repository.py", "list_campaigns"): "percent of the budget spent",
    ("triage.py", "_figure"): "prints a ruler constant without float noise",
    ("triage_capacity.py", "can_support"): "how many ads a daily budget supports (a count)",
    ("visual_learning.py", "_fmt"): "a learning's number printed to two decimals",
    ("workspace_reads.py", "_totals"): "a platform cost per result served in cents",
    ("workspace_reads.py", "_platform_ad"): "a platform spend served in cents",
}
# (file, function) -> a money rounding outside `budget.py` still to move onto `budget.whole`
# (F48-I07 moved `judgment._fmt_money` and `triage_scale.scale_candidates`; keep it empty).
PENDING_MONEY: dict = {}


def _rounding_calls(tree):
    """Yield `(function_name, lineno, name)` for every `round(...)`, `math.floor(...)`,
    `math.ceil(...)` and bare `floor(...)`／`ceil(...)` call."""
    parents = _parents(tree)
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        name = func.id if isinstance(func, ast.Name) else \
            func.attr if isinstance(func, ast.Attribute) else None
        if name in ROUNDING_CALLS:
            yield _enclosing(parents, node), node.lineno, name


class OneMoneyCalculatorTest(unittest.TestCase):
    """F48 Contract M: a money figure in `app/ads` is rounded only in `budget.py`."""

    def test_money_is_rounded_only_in_budget_py(self):
        offenders, seen_allowed = [], set()
        for path in _ads_files():
            relative = path.relative_to(ADS_DIR).as_posix()
            if relative == MONEY_FILE:
                continue
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for function, line, name in _rounding_calls(tree):
                key = (relative, function)
                if key in NOT_MONEY_ROUNDING or key in PENDING_MONEY:
                    seen_allowed.add(key)
                    continue
                offenders.append(f"app/ads/{relative}:{line} in {function}(): {name}(")
        self.assertEqual(
            offenders, [],
            "a rounding outside budget.py -- use budget.whole／daily_of／total_of (F48 M)",
        )
        # An allow entry whose rounding is gone must go too (the lists only ever shrink).
        self.assertEqual(set(NOT_MONEY_ROUNDING) | set(PENDING_MONEY), seen_allowed)

    def test_the_scan_sees_every_rounding_shape(self):
        tree = ast.parse(
            "import math\n"
            "from math import floor\n"
            "def daily(total, days):\n"
            "    return round(total / days) + math.floor(total / days) + floor(total)\n"
            "def up(x):\n"
            "    return math.ceil(x)\n"
            "def fine(rows):\n"
            "    return budget.whole(rows)\n"
        )
        self.assertEqual(
            sorted((f, n) for f, _, n in _rounding_calls(tree)),
            [("daily", "floor"), ("daily", "floor"), ("daily", "round"), ("up", "ceil")],
        )

    def test_the_calculator_is_half_up_and_floors_the_daily(self):
        self.assertEqual(budget.whole(2.5), 3)  # Python's round(2.5) is 2
        self.assertEqual(budget.daily_of(10000, 7), 1428)
        self.assertEqual(budget.total_of(1428, 7), 9996)


# -- F49 Contract L: one lifecycle ---------------------------------------------------------------

# A platform's own status vocabulary belongs to its adapter (`adapters/meta_read.py`
# `STATUS_TABLE`); everything else reads `lifecycle.delivery`.
NATIVE_STATUS_WORDS = frozenset({
    "ACTIVE", "PAUSED", "ARCHIVED", "DELETED", "ADSET_PAUSED", "CAMPAIGN_PAUSED", "DISAPPROVED",
    "WITH_ISSUES", "IN_PROCESS", "PENDING_REVIEW", "PREAPPROVED", "PENDING_BILLING_INFO",
})
_SQL_STATUS_WORD = re.compile(r"'(" + "|".join(sorted(NATIVE_STATUS_WORDS)) + r")'")
# (file relative to app/ads, text on the hit line, why) -- never widen to hide a status rule.
NATIVE_WORD_ALLOWED = [
    ("ab_pairs.py", '{"status": "PAUSED"}',
     "W19 (feature D): the change-set pause payload is written in the platform's own word"),
    ("change_control_data.py", '{"status": "PAUSED"}',
     "W19 (feature D): the change-set pause payload, validated as written"),
]
# The only owners of a `native_status` comparison and of the campaign-selection SQL.
LIFECYCLE_FILE = "lifecycle.py"
_NATIVE_COMPARE_SQL = re.compile(r"\bnative_status\s*(=|<>|!=|\bIN\b|\bNOT\s+IN\b)", re.I)
_CAMPAIGN_TABLE = re.compile(r"\bads_campaign\b")
# `IN (…)` counts when the list names a campaign-only status (a change set is `draft` too).
_CAMPAIGN_SELECTION = re.compile(
    r"\bstatus\s*(!=|<>)\s*'closed'|\bstatus\s+IN\s*\([^)]*'(ready|live|ended|closed)'", re.I,
)


def _docstrings(tree) -> set:
    """The string constants that are docstrings (prose, not code)."""
    found = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Module | ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef) \
                and node.body and isinstance(node.body[0], ast.Expr) \
                and isinstance(node.body[0].value, ast.Constant):
            found.add(node.body[0].value)
    return found


def _code_strings(tree):
    """Yield `(lineno, value)` for every string constant in code (docstrings left out)."""
    skip = _docstrings(tree)
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str) and node not in skip:
            yield node.lineno, node.value


def _native_words(tree):
    """Yield the line of every native-status word written in code: a string that is the word, or
    a SQL string quoting it (`native_status='ACTIVE'`)."""
    for line, value in _code_strings(tree):
        if value in NATIVE_STATUS_WORDS or _SQL_STATUS_WORD.search(value):
            yield line


def _is_native_key(node) -> bool:
    return isinstance(node, ast.Constant) and node.value == "native_status"


def _names_native_status(node) -> bool:
    """The operand reads a `native_status` value: `x["native_status"]`, `x.get("native_status")`,
    `x.native_status` or a variable named for it. The bare key (`"native_status" in changed`, a
    field-presence check) is not a value, and neither is a call's result (`lifecycle.may_spend(x)`
    compared with another is a derived state): calls other than `.get` are not walked into."""
    stack = [node]
    while stack:
        sub = stack.pop()
        if isinstance(sub, ast.Name) and "native_status" in sub.id:
            return True
        if isinstance(sub, ast.Attribute) and sub.attr == "native_status":
            return True
        if isinstance(sub, ast.Subscript) and _is_native_key(sub.slice):
            return True
        if isinstance(sub, ast.Call):
            if isinstance(sub.func, ast.Attribute) and sub.func.attr == "get" and sub.args \
                    and _is_native_key(sub.args[0]):
                return True
            continue
        stack.extend(ast.iter_child_nodes(sub))
    return False


def _native_comparisons(tree):
    """Yield the line of every `==`／`!=`／`in`／`not in` with an operand naming `native_status`
    (`x["native_status"]`, `x.get("native_status")`, a `native_status` variable) and of every SQL
    string comparing the column. `is None` is a null check, not a vocabulary rule."""
    for node in ast.walk(tree):
        compares = (ast.Eq, ast.NotEq, ast.In, ast.NotIn)
        if isinstance(node, ast.Compare) \
                and any(isinstance(op, compares) for op in node.ops) \
                and any(_names_native_status(o) for o in [node.left, *node.comparators]):
            yield node.lineno
    for line, value in _code_strings(tree):
        if _NATIVE_COMPARE_SQL.search(value):
            yield line


def _campaign_selections(tree):
    """Yield the line of every SQL string on `ads_campaign` selecting by stored status
    (`status != 'closed'`, `status <> 'closed'`, `status IN ('live', …)`)."""
    for line, value in _code_strings(tree):
        if _CAMPAIGN_TABLE.search(value) and _CAMPAIGN_SELECTION.search(value):
            yield line


class OneLifecycleTest(unittest.TestCase):
    """F49 Contract L: the platform status vocabulary lives in the adapters, `native_status` is
    compared only in `lifecycle.py`／`adapters/`, and "which campaigns" SQL only in
    `lifecycle.py`."""

    def _scan(self, scan, *, skip):
        hits = []
        for path in _ads_files():
            relative = path.relative_to(ADS_DIR).as_posix()
            if skip(relative):
                continue
            text = path.read_text(encoding="utf-8")
            lines = text.splitlines()
            tree = ast.parse(text, filename=str(path))
            hits.extend((relative, line, lines[line - 1]) for line in sorted(set(scan(tree))))
        return hits

    @staticmethod
    def _in_adapters(relative):
        return relative.startswith("adapters/")

    def test_no_native_status_word_outside_the_adapters(self):
        hits = self._scan(_native_words, skip=self._in_adapters)
        offenders, seen = [], set()
        for relative, line, text in hits:
            allowed = [(f, t) for f, t, _why in NATIVE_WORD_ALLOWED if f == relative and t in text]
            if allowed:
                seen.update(allowed)
                continue
            offenders.append(f"app/ads/{relative}:{line}: {text.strip()}")
        self.assertEqual(
            offenders, [],
            "a platform status word outside adapters/ -- read lifecycle.delivery (F49 L)",
        )
        # An allow entry whose line is gone must go too (the list only ever shrinks).
        self.assertEqual({(f, t) for f, t, _why in NATIVE_WORD_ALLOWED}, seen)

    def test_native_status_is_compared_only_in_the_lifecycle(self):
        hits = self._scan(
            _native_comparisons,
            skip=lambda r: r == LIFECYCLE_FILE or self._in_adapters(r),
        )
        self.assertEqual(
            [f"app/ads/{r}:{line}: {text.strip()}" for r, line, text in hits], [],
            "a native_status comparison outside lifecycle.py／adapters/ (F49 L)",
        )

    def test_campaign_selection_sql_lives_only_in_the_lifecycle(self):
        hits = self._scan(_campaign_selections, skip=lambda r: r == LIFECYCLE_FILE)
        self.assertEqual(
            [f"app/ads/{r}:{line}: {text.strip()}" for r, line, text in hits], [],
            "a campaign selected by stored status outside lifecycle.py -- call "
            "lifecycle.campaigns／campaign_ids／brands (F49 L)",
        )
        # The selectors themselves still hold the stored-status filter.
        tree = ast.parse((ADS_DIR / LIFECYCLE_FILE).read_text(encoding="utf-8"))
        self.assertTrue(any("status <> 'closed'" in value for _, value in _code_strings(tree)))

    def test_the_scans_see_each_planted_shape(self):
        tree = ast.parse(
            '"""ACTIVE in prose is fine."""\n'
            "def rule(ad, rows, native_status):\n"
            "    if ad['native_status'] == 'ACTIVE':\n"
            "        pass\n"
            "    if ad.get('native_status') in CLOSED:\n"
            "        pass\n"
            "    if native_status != x:\n"
            "        pass\n"
            "    if lifecycle.may_spend({**ad, 'native_status': ad['native_status']}) != y:\n"
            "        pass\n"
            "    if ad['native_status'] is None:\n"
            "        pass\n"
            "    q = \"SELECT 1 FROM ads_external_entity WHERE native_status='PAUSED'\"\n"
            "    s = \"SELECT id FROM ads_campaign WHERE org_id=%s AND status != 'closed'\"\n"
            "    t = \"SELECT id FROM ads_campaign WHERE status IN ('live','ended')\"\n"
            "    u = (\"SELECT s.id FROM ads_change_set s JOIN ads_campaign c \"\n"
            "         \"ON c.id=s.campaign_id WHERE s.status IN ('draft','deferred')\")\n"
            "    return {'status': 'PAUSED'}\n"
        )
        self.assertEqual(sorted(set(_native_words(tree))), [3, 13, 18])
        self.assertEqual(sorted(set(_native_comparisons(tree))), [3, 5, 7, 13])
        self.assertEqual(sorted(_campaign_selections(tree)), [14, 15])


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
