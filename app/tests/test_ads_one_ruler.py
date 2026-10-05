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

F49-I02 (Contract O, one sync outcome): an SQL write of `ads_external_sync_job` (its
`status`／`error`) outside `external_sync.py`, and a read of a sync task's `errors`／`error_code`
outside `external_sync.py`, each fail, naming file and line.

F49-I03 (Contract V, coverage): a read of a `coverage`／`ranges` key (`x["coverage"]`,
`x.get("ranges")`, an SQL path `->'coverage'`) outside `coverage.py` and the writer
`external_repository.record_sync` fails, naming file, function and line -- unless the
`(file, function, key)` is listed with why it is not the stored observations read range (the
monthly task's own proof, a served block's key).

F49-I06 (Contract B, readback): `except (ValueError, AttributeError)` anywhere in `app/ads` fails
(a code bug is not a refusal); every verification state named in `app/ads` code -- and every value
the `ads_action.verification_state`／`ads_handoff_item.status` CHECKs allow -- has its word in
`change_control_data.VERIFICATION_LABELS`.

F49-I05 (Contract Q, one decision queue): a list／tuple／set literal naming two or more queue kinds
in `app/ads` outside `queue_done.py` fails, naming file and variable (or function); every kind the
queue serves has its interrupt category and a done rule; every `reason_code` `triage.py` emits --
and every window reason `review_evidence` passes through to it -- has its `triage.reasons()` entry
(read by AST), served as `reasons` in `GET …/rules`.
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
    brief,
    budget,
    change_control_data,
    experiments,
    learning_rank,
    month_summary,
    queue_done,
    review_monitor,
    triage,
)
from app.brand_intelligence import repository as brands
from app.core import db, input_rules

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


# -- F49 Contract O: one sync outcome --------------------------------------------------------------

# The one owner of a sync job's writes and of its tasks' error fields: everything else reads
# `external_sync.outcome`／`campaign_outcome`.
SYNC_FILE = "external_sync.py"
_SYNC_JOB_WRITE = re.compile(r"\b(INSERT\s+INTO|UPDATE)\s+ads_external_sync_job\b", re.I)
TASK_ERROR_KEYS = {"errors", "error_code"}
# (file relative to app/ads, function, key) -> why that read is not a sync task's error field.
# Never widen this to hide a task read: call `external_sync.outcome` instead.
NOT_A_TASK_ERROR = {
    ("repository.py", "campaign_sync_state", "error_code"):
        "a campaign section's own sync state (`record_sync`), not a job task",
    ("asset_suggestions.py", "_call_error_code", "error_code"):
        "an AI call's `llm_task.error_code` (F50 Contract J), not a sync task",
    ("angles.py", "run", "error_code"):
        "an AI call's `llm_task.error_code` (F50 Contract J), not a sync task",
}


def _sync_job_writes(tree):
    """Yield the line of every SQL string that inserts into or updates `ads_external_sync_job`."""
    for line, value in _code_strings(tree):
        if _SYNC_JOB_WRITE.search(value):
            yield line


def _task_error_reads(tree):
    """Yield `(function_name, lineno, key)` for every `x["errors"]`／`x["error_code"]` load and
    `x.get("errors"／"error_code")` (a write building a dict is not a read)."""
    parents = _parents(tree)
    for node in ast.walk(tree):
        key = None
        if isinstance(node, ast.Subscript) and isinstance(node.ctx, ast.Load) \
                and isinstance(node.slice, ast.Constant):
            key = node.slice.value
        elif isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) \
                and node.func.attr == "get" and node.args \
                and isinstance(node.args[0], ast.Constant):
            key = node.args[0].value
        if key in TASK_ERROR_KEYS:
            yield _enclosing(parents, node), node.lineno, key


class OneSyncOutcomeTest(unittest.TestCase):
    """F49 Contract O: a sync job's status／error are written only in `external_sync.py`, and a
    task's `errors`／`error_code` are read only there; every reader goes through `outcome`. The
    monthly coverage proof (`coverage`／`last_covered`, read by `month_budget`／`connections`) is
    not an error field and stays readable."""

    def test_sync_job_is_written_only_by_external_sync(self):
        offenders = []
        for path in _ads_files():
            relative = path.relative_to(ADS_DIR).as_posix()
            if relative == SYNC_FILE:
                continue
            text = path.read_text(encoding="utf-8")
            for line in _sync_job_writes(ast.parse(text, filename=str(path))):
                offenders.append(f"app/ads/{relative}:{line}")
        self.assertEqual(
            offenders, [],
            "a sync job written outside external_sync.py -- call "
            "external_sync.record_request_failure／request_sync (F49 O)",
        )

    def test_task_errors_are_read_only_by_external_sync(self):
        offenders, seen = [], set()
        for path in _ads_files():
            relative = path.relative_to(ADS_DIR).as_posix()
            if relative == SYNC_FILE:
                continue
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for function, line, key in _task_error_reads(tree):
                if (relative, function, key) in NOT_A_TASK_ERROR:
                    seen.add((relative, function, key))
                    continue
                offenders.append(f"app/ads/{relative}:{line} in {function}(): {key}")
        self.assertEqual(
            offenders, [],
            "a sync task's errors／error_code read outside external_sync.py -- read "
            "external_sync.outcome (F49 O)",
        )
        # An allow entry whose read is gone must go too (the list only ever shrinks).
        self.assertEqual(set(NOT_A_TASK_ERROR), seen)

    def test_the_sync_scans_see_each_planted_shape(self):
        tree = ast.parse(
            '"""UPDATE ads_external_sync_job in prose is fine."""\n'
            "def fallback(conn, task, state):\n"
            "    conn.execute(\"INSERT INTO ads_external_sync_job(id,error) VALUES (%s,%s)\")\n"
            "    conn.execute('UPDATE ads_external_sync_job SET error=%s')\n"
            "    conn.execute('SELECT status FROM ads_external_sync_job')\n"
            "    text = task.get('errors') or task['error_code']\n"
            "    built = {'errors': [], 'error_code': None}\n"
            "    return text, built, state['error']\n"
        )
        self.assertEqual(sorted(_sync_job_writes(tree)), [3, 4])
        self.assertEqual(
            sorted((f, line, k) for f, line, k in _task_error_reads(tree)),
            [("fallback", 6, "error_code"), ("fallback", 6, "errors")],
        )


# -- F49 Contract V: one coverage reader -----------------------------------------------------------

# The one reader of a campaign's recorded observations ranges, and its one writer (which takes
# the clean read's `{start, end}` as its `coverage` input).
COVERAGE_FILE = "coverage.py"
COVERAGE_WRITER = ("external_repository.py", "record_sync", "coverage")
COVERAGE_KEYS = {"coverage", "ranges"}
_COVERAGE_SQL = re.compile(r"->>?\s*'(coverage|ranges)'|observations,(coverage|ranges)\}")
# (file relative to app/ads, function, key) -> why that read is not the stored observations
# range. Never widen this to hide a range read: call `coverage.load`／`gap`／`covered` instead.
NOT_THE_READ_RANGE = {
    ("external_sync.py", "_save_monthly", "coverage"):
        "the monthly task's own account-month proof (`account_campaign_day`)",
    ("month_budget.py", "_inventory", "coverage"):
        "the monthly task's own account-month proof (`account_campaign_day`)",
    ("asset_binding.py", "_eligible", "coverage"):
        "an asset-binding interval's own `continuous` flag",
    ("closeout.py", "close", "coverage"): "the `coverage` block `outcome.summary` serves",
    ("triage.py", "_insufficient_candidates", "coverage"):
        "the triage `data.coverage` read span this call serves",
}


def _coverage_reads(tree):
    """Yield `(function_name, lineno, key)` for every `x["coverage"／"ranges"]` load,
    `x.get(...)`／`x.pop(...)` of those keys, and SQL string reading them as a jsonb path."""
    parents = _parents(tree)
    for node in ast.walk(tree):
        key = None
        if isinstance(node, ast.Subscript) and isinstance(node.ctx, ast.Load) \
                and isinstance(node.slice, ast.Constant):
            key = node.slice.value
        elif isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) \
                and node.func.attr in {"get", "pop"} and node.args \
                and isinstance(node.args[0], ast.Constant):
            key = node.args[0].value
        if key in COVERAGE_KEYS:
            yield _enclosing(parents, node), node.lineno, key
    skip = _docstrings(tree)
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str) and node not in skip:
            match = _COVERAGE_SQL.search(node.value)
            if match:
                yield _enclosing(parents, node), node.lineno, match.group(1) or match.group(2)


class OneCoverageReaderTest(unittest.TestCase):
    """F49 Contract V: "which days were read" has one reader, `coverage.py`; everything else
    calls it (`load`／`missing_days`／`covered`／`gap`)."""

    def test_read_ranges_are_read_only_by_the_coverage_module(self):
        offenders, seen, writer = [], set(), []
        for path in _ads_files():
            relative = path.relative_to(ADS_DIR).as_posix()
            if relative == COVERAGE_FILE:
                continue
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for function, line, key in _coverage_reads(tree):
                entry = (relative, function, key)
                if entry == COVERAGE_WRITER:
                    writer.append(line)
                    continue
                if entry in NOT_THE_READ_RANGE:
                    seen.add(entry)
                    continue
                offenders.append(f"app/ads/{relative}:{line} in {function}(): {key}")
        self.assertEqual(
            offenders, [],
            "a read of the stored coverage／ranges outside coverage.py -- call coverage.load／"
            "missing_days／covered／gap (F49 V)",
        )
        # The writer still takes the read's range; an allow entry whose read is gone must go too.
        self.assertTrue(writer)
        self.assertEqual(set(NOT_THE_READ_RANGE), seen)

    def test_the_coverage_scan_sees_each_planted_shape(self):
        source = "\n".join([
            '"""context_json->\'coverage\' in prose is fine."""',
            "def gap(campaign, sync):",
            "    obs = sync['observations']",
            "    a = obs.get('coverage') or obs['ranges']",
            "    q = \"SELECT context_json->'external_sync'->'observations'->'ranges' FROM t\"",
            "    r = \"UPDATE t SET c = c #- '{external_sync,observations,coverage}'\"",
            "    built = {'coverage': None, 'ranges': []}",
            "    return a, q, r, built",
        ])
        self.assertEqual(
            sorted((f, line, k) for f, line, k in _coverage_reads(ast.parse(source))),
            [("gap", 4, "coverage"), ("gap", 4, "ranges"), ("gap", 5, "ranges"),
             ("gap", 6, "coverage")],
        )


# -- F49 Contract B: readback says why, and calls each state by one name --------------------------

# (file relative to app/ads, why) -- a `except (ValueError, AttributeError)` still to narrow, naming
# the issue that removes the entry. Never widen: an AttributeError is a code bug, not a refusal.
VALUE_OR_ATTRIBUTE_PENDING: dict = {}
_STATE_SQL = re.compile(
    r"verification_state\s*(?:=|<>|!=)\s*'(\w+)'|THEN\s+'(\w+)'"
    r"|verification_state\s+(?:NOT\s+)?IN\s*\(([^)]*)\)",
    re.I,
)


def _value_or_attribute_handlers(tree):
    """Yield the line of every `except (ValueError, AttributeError)` (either order, any extras)."""
    for node in ast.walk(tree):
        if isinstance(node, ast.ExceptHandler) and isinstance(node.type, ast.Tuple):
            names = {e.id for e in node.type.elts if isinstance(e, ast.Name)}
            if {"ValueError", "AttributeError"} <= names:
                yield node.lineno


def _verification_state_words(tree):
    """Yield `(lineno, word)` for every verification-state value named in code: an SQL literal
    beside `verification_state` (`= 'x'`, `<> 'x'`, `IN ('x', …)`, and a `CASE … THEN 'x'` in the
    same string), and a Python `"verification_state": "x"` entry."""
    for line, value in _code_strings(tree):
        if "verification_state" not in value:
            continue
        for match in _STATE_SQL.finditer(value):
            listed = match.group(3)
            words = re.findall(r"'(\w+)'", listed) if listed else [match.group(1) or match.group(2)]
            yield from ((line, word) for word in words)
    for node in ast.walk(tree):
        if isinstance(node, ast.Dict):
            for key, val in zip(node.keys, node.values, strict=True):
                if isinstance(key, ast.Constant) and key.value == "verification_state" \
                        and isinstance(val, ast.Constant) and isinstance(val.value, str):
                    yield val.lineno, val.value


def _checked_states(table_column):
    """The values a migration's CHECK allows for `column` (`verification_state IN (…)`,
    `status IN (…)` in the `CREATE TABLE <table>` block)."""
    table, column = table_column
    migrations = Path(__file__).resolve().parents[2] / "supabase" / "migrations"
    found = set()
    for path in migrations.glob("*_ads_*.sql"):
        text = path.read_text(encoding="utf-8")
        if table not in text:
            continue
        for match in re.finditer(column + r"\s+IN\s*\(([^)]*)\)", text):
            start = text.rfind(";", 0, match.start())
            if table in text[start:match.start()]:
                found.update(re.findall(r"'(\w+)'", match.group(1)))
    return found


class ReadbackVocabularyTest(unittest.TestCase):
    """F49 Contract B: a readback refusal is a `ValueError` with a reason code -- a code bug
    (`AttributeError`) is never caught as one -- and every verification state the ads code names
    has its one word in `change_control_data.VERIFICATION_LABELS`."""

    def test_no_value_or_attribute_error_handler_in_app_ads(self):
        offenders, seen = [], set()
        for path in _ads_files():
            relative = path.relative_to(ADS_DIR).as_posix()
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for line in _value_or_attribute_handlers(tree):
                if relative in VALUE_OR_ATTRIBUTE_PENDING:
                    seen.add(relative)
                    continue
                offenders.append(f"app/ads/{relative}:{line}")
        self.assertEqual(
            offenders, [],
            "`except (ValueError, AttributeError)` reads a code bug as a refusal -- catch "
            "ValueError only (F49 B)",
        )
        # An allow entry whose handler is gone must go too (the list only ever shrinks).
        self.assertEqual(set(VALUE_OR_ATTRIBUTE_PENDING), seen)

    def test_every_named_verification_state_has_its_label(self):
        from app.ads import change_control_data

        labels = change_control_data.VERIFICATION_LABELS
        missing, named = [], set()
        for path in _ads_files():
            relative = path.relative_to(ADS_DIR).as_posix()
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for line, word in _verification_state_words(tree):
                named.add(word)
                if word not in labels:
                    missing.append(f"app/ads/{relative}:{line}: {word}")
        self.assertEqual(missing, [], "a verification state without a VERIFICATION_LABELS word")
        self.assertTrue({"pending", "reported", "unknown", "confirmed", "stale"} <= named)
        # Every value the tables allow is a word too: the action's state and the handoff item's.
        for table_column in (("ads_action", "verification_state"), ("ads_handoff_item", "status")):
            allowed = _checked_states(table_column)
            self.assertTrue(allowed, table_column)
            self.assertEqual(allowed - set(labels), set(), table_column)

    def test_the_scans_see_each_planted_shape(self):
        tree = ast.parse(
            "def check(conn, exc):\n"
            "    try:\n"
            "        pass\n"
            "    except (AttributeError, ValueError, KeyError):\n"
            "        pass\n"
            "    try:\n"
            "        pass\n"
            "    except ValueError:\n"
            "        pass\n"
            "    conn.execute(\"UPDATE ads_action SET verification_state=CASE WHEN \"\n"
            "                 \"verification_state='pending' THEN 'gone' END WHERE kind='x'\")\n"
            "    q = \"SELECT 1 WHERE a.verification_state NOT IN ('done','stale')\"\n"
            "    return {'verification_state': 'odd', 'status': 'other'}\n"
        )
        self.assertEqual(list(_value_or_attribute_handlers(tree)), [4])
        self.assertEqual(
            sorted(word for _, word in _verification_state_words(tree)),
            ["done", "gone", "odd", "pending", "stale"],
        )

    def test_worst_state_is_the_one_aggregate(self):
        from app.ads import change_control_data

        worst = change_control_data.worst_state
        self.assertEqual(worst(["confirmed", "confirmed"]), "confirmed")
        self.assertEqual(worst(["confirmed", "deviated", "unknown"]), "deviated")
        self.assertEqual(worst(["confirmed", "stale", "unknown"]), "stale")
        self.assertEqual(worst(["confirmed", "reported", "unknown"]), "unknown")
        self.assertEqual(worst(["pending", "reported", "confirmed"]), "reported")
        self.assertEqual(worst(["confirmed", "pending"]), "pending")
        self.assertEqual(worst([]), "pending")
        labels = change_control_data.VERIFICATION_LABELS
        self.assertNotEqual(labels["unknown"], labels["reported"])


# -- F49 Contract Q: one decision queue ------------------------------------------------------------

QUEUE_FILE = "queue_done.py"
# (file relative to app/ads, variable or function) -> why that literal is not a list of queue kinds.
# Never widen this to hide one: read `queue_done.DECISION_KINDS`／`NOTICE_KINDS` instead.
NOT_A_KIND_LIST = {
    ("triage.py", "ALL_CLASSES"):
        "the trend classes (`class`); `stop_loss`／`worse` name a class there, not a queue row",
}


def _queue_kind_lists(tree, kinds):
    """Yield `(name, lineno)` for every list／tuple／set literal with two or more `kinds` strings --
    `name` is the variable it is assigned to (else the enclosing function)."""
    parents = _parents(tree)
    for node in ast.walk(tree):
        if not isinstance(node, ast.List | ast.Tuple | ast.Set):
            continue
        named = {e.value for e in node.elts
                 if isinstance(e, ast.Constant) and isinstance(e.value, str)} & kinds
        if len(named) < 2:
            continue
        parent = parents.get(node)
        if isinstance(parent, ast.Call):  # frozenset({...}) / set([...])
            parent = parents.get(parent)
        if isinstance(parent, ast.Assign | ast.AnnAssign):
            targets = parent.targets if isinstance(parent, ast.Assign) else [parent.target]
            names = [t.id for t in targets if isinstance(t, ast.Name)]
            if names:
                yield names[0], node.lineno
                continue
        yield _enclosing(parents, node), node.lineno


def _strings_of(node):
    """The string constants `node` can evaluate to: a constant, either side of `a or "x"`, either
    branch of `"x" if c else "y"`."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        yield node.value
    elif isinstance(node, ast.BoolOp):
        for value in node.values:
            yield from _strings_of(value)
    elif isinstance(node, ast.IfExp):
        yield from _strings_of(node.body)
        yield from _strings_of(node.orelse)


# The functions whose returned tuple carries a reason code, and where in the tuple.
_REASON_RETURNS = {"grade_window": -1, "_compare": 1}


def _triage_reason_codes(tree):
    """Every `reason_code` string `triage.py` emits: the code argument of each `finish(cls, code,
    …)`, the code slot of `grade_window`'s and `_compare`'s returned tuples, and every constant
    `"reason"` value a window view carries."""
    parents = _parents(tree)
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) \
                and node.func.id == "finish" and len(node.args) > 1:
            yield from _strings_of(node.args[1])
        elif isinstance(node, ast.Return) and isinstance(node.value, ast.Tuple):
            slot = _REASON_RETURNS.get(_enclosing(parents, node))
            if slot is not None and len(node.value.elts) > abs(slot):
                yield from _strings_of(node.value.elts[slot])
        elif isinstance(node, ast.Dict):
            for key, value in zip(node.keys, node.values, strict=True):
                if isinstance(key, ast.Constant) and key.value == "reason":
                    yield from _strings_of(value)


def _window_reasons(tree):
    """Every reason `review_evidence` gives a window (`reason = "…"`), which triage passes on."""
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and any(
            isinstance(t, ast.Name) and t.id == "reason" for t in node.targets
        ):
            yield from _strings_of(node.value)


class OneDecisionQueueTest(unittest.TestCase):
    """F49 Contract Q: the decision kinds are one list (`queue_done`), every served kind has its
    interrupt category and done rule, and every reason code has its served words."""

    def test_no_list_of_queue_kinds_outside_queue_done(self):
        kinds = set(triage.QUEUE_CATEGORY)
        offenders, seen = [], set()
        for path in _ads_files():
            relative = path.relative_to(ADS_DIR).as_posix()
            if relative == QUEUE_FILE:
                continue
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for name, line in _queue_kind_lists(tree, kinds):
                if (relative, name) in NOT_A_KIND_LIST:
                    seen.add((relative, name))
                    continue
                offenders.append(f"app/ads/{relative}:{line} {name}")
        self.assertEqual(
            offenders, [],
            "a list of queue kinds outside queue_done.py -- read queue_done.DECISION_KINDS／"
            "NOTICE_KINDS (F49 Q)",
        )
        # An allow entry whose literal is gone must go too (the list only ever shrinks).
        self.assertEqual(set(NOT_A_KIND_LIST), seen)

    def test_the_kind_scan_sees_each_planted_shape(self):
        tree = ast.parse(
            "ORDER = ['cleanup', 'worse']\n"
            "def pick(row):\n"
            "    return row['kind'] in {'settle', 'closeout'} or row in ('cleanup',)\n"
            "SEEN = frozenset({'scale_budget', 'insufficient_data'})\n"
            "MAP = {'cleanup': 1, 'worse': 2}\n"
        )
        self.assertEqual(
            sorted(name for name, _ in _queue_kind_lists(tree, set(triage.QUEUE_CATEGORY))),
            ["ORDER", "SEEN", "pick"],
        )

    def test_every_served_kind_has_a_category_and_a_done_rule(self):
        self.assertEqual(
            triage.KINDS_AVAILABLE,
            [*queue_done.DECISION_KINDS, *queue_done.NOTICE_KINDS],
        )
        for kind in triage.KINDS_AVAILABLE:
            with self.subTest(kind=kind):
                self.assertIn(kind, triage.QUEUE_CATEGORY)
                self.assertIn(kind, queue_done.DONE_RULES)

    def test_every_emitted_reason_code_has_served_words(self):
        codes = set(_triage_reason_codes(ast.parse(
            (ADS_DIR / "triage.py").read_text(encoding="utf-8"))))
        codes |= set(_window_reasons(ast.parse(
            (ADS_DIR / "review_evidence.py").read_text(encoding="utf-8"))))
        # The contract's wait reasons are among them (the scan is not finding nothing).
        self.assertLessEqual(
            {"too_new", "result_unknown_days", "needs_resync", "mixed_currency",
             "no_previous_window", "result_kind_unknown", "target_unresolved"},
            codes,
        )
        reasons = triage.reasons()
        self.assertEqual(sorted(codes - set(reasons)), [], "a reason code without words")
        for code, words in reasons.items():
            with self.subTest(code=code):
                self.assertEqual(set(words), {"title", "text", "fix"})
                self.assertTrue(words["title"] and words["text"])
                self.assertIn(words["fix"], {*triage.REASON_FIXES, None})
        self.assertEqual(triage.rules()["reasons"], reasons)

    def test_the_reason_scan_sees_each_planted_shape(self):
        tree = ast.parse(
            "def grade_window(v):\n"
            "    if v:\n"
            "        return (*X, 'a_code')\n"
            "    return 'g', 'l', v or 'b_code'\n"
            "def _compare(c):\n"
            "    return 'worse', 'c_code', 1\n"
            "def walk(finish):\n"
            "    finish('insufficient', 'd_code', 1)\n"
            "    finish('x', g[2] or 'e_code')\n"
            "    return {'reason': 'f_code', 'other': 'nope'}\n"
        )
        self.assertEqual(
            sorted(_triage_reason_codes(tree)),
            ["a_code", "b_code", "c_code", "d_code", "e_code", "f_code"],
        )
        tree = ast.parse("def view(r):\n    reason = 'x' if r else 'y'\n    other = 'z'\n")
        self.assertEqual(sorted(_window_reasons(tree)), ["x", "y"])


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
        self.assertEqual(set(body), {"grade", "ab", "labels", "glossary", "reasons", "limits"})
        # F50 Contract I (decision 11): the limits the screens quote, from the owning constants.
        self.assertEqual(body["limits"], {
            "review_days": {"min": review_monitor.DAYS_RANGE[0],
                            "max": review_monitor.DAYS_RANGE[1]},
            "review_cadence_default": review_monitor.DEFAULT_CADENCE_DAYS,
            "campaign_default_days": brief.DEFAULT_PERIOD_DAYS,
            "copy_items_max": change_control_data.COPY_ITEMS_MAX,
            "upload_max_mb": input_rules.UPLOAD_CAPS["ad_asset"] // (1024 * 1024),
        })
        self.assertEqual(body["limits"]["review_days"], {"min": 1, "max": 31})
        self.assertEqual(body["limits"]["upload_max_mb"], 50)
        # F49 Contract Q: the wait reasons, as `triage.reasons()` builds them.
        self.assertEqual(body["reasons"], triage.reasons())
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


# -- F49 Contract T: slot states told as they are -------------------------------------------------

SLOTS_FILE = "slots.py"
# The stored vocabularies a slot is derived from: `ads_user_asset.status` (an original's preview)
# and `workbench_brief.status` (a set's generation). Only these functions compare them.
ASSET_STATUS_WORDS = frozenset({"pending", "processing", "retryable", "error"})
BRIEF_STATUS_WORDS = frozenset({"queued", "running", "failed"})
SLOT_SOURCE_WORDS = ASSET_STATUS_WORDS | BRIEF_STATUS_WORDS
SLOT_STATE_READERS = {(SLOTS_FILE, "_original_state"), (SLOTS_FILE, "brief_state")}
# A file reads asset rows or workbench sets when it names one of these (the scan's scope: the same
# words mean other things in sync jobs, LLM tasks and review rounds).
_READS_SLOT_SOURCES = re.compile(
    r"\bget_asset\(|\bbriefs_for_source\(|\basset_status\b|\bads_user_asset\b"
)
_STATUS_KEYS = {"status", "asset_status"}


def _module_constants(tree) -> dict:
    """Module-level `NAME = <literal>` bindings (a tuple／set of words compared through a name)."""
    found = {}
    for node in tree.body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1 \
                and isinstance(node.targets[0], ast.Name):
            found[node.targets[0].id] = node.value
    return found


def _words_in(node, constants) -> set:
    """The string constants an operand stands for: a literal, a tuple／list／set of literals, or a
    module constant bound to one of those."""
    if isinstance(node, ast.Name) and node.id in constants:
        node = constants[node.id]
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return {node.value}
    if isinstance(node, ast.Tuple | ast.List | ast.Set):
        return {e.value for e in node.elts if isinstance(e, ast.Constant)
                and isinstance(e.value, str)}
    return set()


def _reads_a_status(node) -> bool:
    """`x["status"]`, `x.get("status")` (or `asset_status`), or a variable named `status`."""
    if isinstance(node, ast.Name):
        return node.id in _STATUS_KEYS
    if isinstance(node, ast.Subscript):
        return isinstance(node.slice, ast.Constant) and node.slice.value in _STATUS_KEYS
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) \
            and node.func.attr == "get" and node.args:
        return isinstance(node.args[0], ast.Constant) and node.args[0].value in _STATUS_KEYS
    return False


def _slot_source_comparisons(tree):
    """Yield `(function, lineno)` for every `==`／`!=`／`in`／`not in` between a status read and
    an asset or brief status word (directly, in a literal collection, or through a module
    constant)."""
    parents = _parents(tree)
    constants = _module_constants(tree)
    for node in ast.walk(tree):
        if not isinstance(node, ast.Compare):
            continue
        operands = [node.left, *node.comparators]
        if any(_reads_a_status(o) for o in operands) and any(
            _words_in(o, constants) & SLOT_SOURCE_WORDS for o in operands
        ):
            yield _enclosing(parents, node), node.lineno


def _slot_calls(tree):
    """Yield the state literal of every slot built in `slots.py`: `_slot(…)`'s fourth positional
    argument, and the first of the per-ad `slot(…)` closure (whose own `_slot` call forwards its
    `state` and is not a slot built)."""
    parents = _parents(tree)
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Name):
            continue
        if _enclosing(parents, node) == "slot":
            continue
        index = {"_slot": 3, "slot": 0}.get(node.func.id)
        if index is None or len(node.args) <= index:
            continue
        arg = node.args[index]
        yield arg.value if isinstance(arg, ast.Constant) else None


class SlotStatesTest(unittest.TestCase):
    """F49 Contract T: every state a slot is built with has its chip and sentence in
    `slots.STATE_TEXT` (and every entry is used); the asset／brief status words are compared only
    by `slots._original_state`／`slots.brief_state` (plus `user_assets*.py` and `app/workbench`,
    their owners)."""

    def test_every_slot_state_has_its_chip_and_sentence(self):
        from app.ads import slots

        tree = ast.parse((ADS_DIR / SLOTS_FILE).read_text(encoding="utf-8"))
        built = list(_slot_calls(tree))
        self.assertNotIn(None, built, "a slot built with a computed state -- name it literally")
        self.assertEqual(set(built), set(slots.STATE_TEXT))
        for state, (label, sentence) in slots.STATE_TEXT.items():
            self.assertTrue(label and sentence, state)

    def test_asset_and_brief_statuses_are_compared_only_by_the_slot_state_functions(self):
        offenders, scanned = [], 0
        for path in _ads_files():
            relative = path.relative_to(ADS_DIR).as_posix()
            if relative.startswith("user_assets"):
                continue
            text = path.read_text(encoding="utf-8")
            if not _READS_SLOT_SOURCES.search(text):
                continue
            scanned += 1
            for function, line in _slot_source_comparisons(ast.parse(text, filename=str(path))):
                if (relative, function) not in SLOT_STATE_READERS:
                    offenders.append(f"app/ads/{relative}:{line} in {function}()")
        self.assertGreater(scanned, 5)
        self.assertEqual(
            offenders, [],
            "an asset／brief status compared outside slots._original_state／brief_state (F49 T)",
        )
        # The readers themselves still hold the comparisons (the list only moves with them).
        tree = ast.parse((ADS_DIR / SLOTS_FILE).read_text(encoding="utf-8"))
        self.assertEqual(
            {(SLOTS_FILE, f) for f, _ in _slot_source_comparisons(tree)}, SLOT_STATE_READERS
        )

    def test_the_scans_see_each_planted_shape(self):
        tree = ast.parse(
            "RUNNING = ('queued', 'running')\n"
            "def rule(asset, brief, task, status):\n"
            "    if asset['status'] == 'retryable':\n"
            "        pass\n"
            "    if brief.get('status') in RUNNING:\n"
            "        pass\n"
            "    if status not in {'pending', 'processing'}:\n"
            "        pass\n"
            "    if task['dispatch_status'] == 'queued':\n"
            "        pass\n"
            "    if slots.brief_state(brief) == 'failed':\n"
            "        pass\n"
            "    if asset['status'] != 'ready':\n"
            "        pass\n"
            "    return _slot(a, b, c, 'ready', d) or slot('missing', None, None)\n"
        )
        self.assertEqual(sorted(line for _, line in _slot_source_comparisons(tree)), [3, 5, 7])
        self.assertEqual(sorted(_slot_calls(tree)), ["missing", "ready"])


if __name__ == "__main__":
    unittest.main()
