"""app/tests/test_clock_rule.py — F50 Contract K (one clock, audit W11) static falsifier.

The authority is the clock table in `app/core/settings.py`'s module docstring: an instant comes
from `db.now_utc()`／`db.now_iso()`; "which day is it for the user" is `today_for_org`／
`org_month_start`／`org_day_start`; "which day is complete" is `last_complete_day`. This scan walks
the AST of every product module under `app/` (test modules are fixtures, not product code, and
are skipped) and fails, naming file, line and text, on:

1. a machine-clock call -- `date.today()`, `datetime.now(...)`, `datetime.utcnow()`,
   `datetime.today()`, `time.time()` (aliases such as `import datetime as dt` or
   `from time import time` included) -- outside `app/core/db.py`;
2. a month start built by hand, `strftime("%Y-%m-01…")`, outside `app/core/settings.py`;
3. yesterday built by hand -- `today_for_org(...) - timedelta(...)`, or an `.astimezone(...)`
   value (optionally `.date()`) minus `timedelta(days=…)` -- outside `app/core/settings.py` and
   `app/ads/coverage.py`;
4. a queue scheduling instant (`retry_at=`／`schedule_at=`) taken from the product clock
   (`now_utc()`／`now_iso()`). The one exception to "every instant comes from db.now_utc()":
   procrastinate compares `scheduled_at` with the database `now()`, and the drill worker patches
   `db.now_utc` to a later drill date, so such an instant would park the job until the real
   clock caught up. Queue instants come from the functions in `QUEUE_CLOCK` (each reads SQL
   `now()`), listed with the reason; a listed function that is gone or stops reading `now()`
   fails.

Ratchet (F48's pattern): `PENDING` lists the hits that exist today with the issue that removes
them. A hit not listed fails; a listed entry the scan no longer finds is stale and fails too, so
the list only shrinks. Never add an entry to hide a new hit: use the `settings` helpers instead.
"""

import ast
import unittest
from pathlib import Path

APP_DIR = Path(__file__).resolve().parent.parent

MACHINE_CLOCK_HOME = "core/db.py"
MONTH_START_HOME = "core/settings.py"
YESTERDAY_HOMES = {"core/settings.py", "ads/coverage.py"}

# (file relative to app/, rule, source text of the hit) -> the issue that removes it.
PENDING: dict[tuple[str, str, str], str] = {
}

# (file relative to app/, function) -> why it reads the queue's own clock instead of db.now_utc().
QUEUE_CLOCK: dict[tuple[str, str], str] = {
    ("background/recovery.py", "_queue_now"):
        "a startup re-queue's retry_at: procrastinate compares scheduled_at with the database "
        "now(); the drill worker's later db.now_utc would park the job until the real clock "
        "reached the drill date",
}
QUEUE_KEYWORDS = {"retry_at", "schedule_at"}
PRODUCT_CLOCK_CALLS = {"now_utc", "now_iso"}

_MACHINE_METHODS = {"datetime": {"now", "utcnow", "today"}, "date": {"today"}}


def _product_files():
    for path in sorted(APP_DIR.rglob("*.py")):
        rel = path.relative_to(APP_DIR).as_posix()
        if rel.startswith("tests/"):
            continue
        yield rel, path


def _aliases(tree) -> dict:
    """Local names bound to the `datetime`／`date` classes, the `datetime`／`time` modules and the
    `time.time` function, from this file's imports."""
    names = {"classes": {}, "datetime_modules": set(), "time_modules": set(), "time_funcs": set()}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == "datetime":
                    names["datetime_modules"].add(alias.asname or "datetime")
                elif alias.name == "time":
                    names["time_modules"].add(alias.asname or "time")
        elif isinstance(node, ast.ImportFrom) and node.module == "datetime":
            for alias in node.names:
                if alias.name in _MACHINE_METHODS:
                    names["classes"][alias.asname or alias.name] = alias.name
        elif isinstance(node, ast.ImportFrom) and node.module == "time":
            for alias in node.names:
                if alias.name == "time":
                    names["time_funcs"].add(alias.asname or "time")
    return names


def _class_of(node, names) -> str | None:
    """`datetime`／`date` when `node` names one of those classes, else None."""
    if isinstance(node, ast.Name) and node.id in names["classes"]:
        return names["classes"][node.id]
    if isinstance(node, ast.Attribute) and node.attr in _MACHINE_METHODS \
            and isinstance(node.value, ast.Name) and node.value.id in names["datetime_modules"]:
        return node.attr
    return None


def _is_machine_clock(call: ast.Call, names) -> bool:
    func = call.func
    if isinstance(func, ast.Attribute):
        cls = _class_of(func.value, names)
        if cls and func.attr in _MACHINE_METHODS[cls]:
            return True
        if func.attr == "time" and isinstance(func.value, ast.Name) \
                and func.value.id in names["time_modules"]:
            return True
    return isinstance(func, ast.Name) and func.id in names["time_funcs"]


def _is_month_start(call: ast.Call) -> bool:
    return isinstance(call.func, ast.Attribute) and call.func.attr == "strftime" \
        and bool(call.args) and isinstance(call.args[0], ast.Constant) \
        and isinstance(call.args[0].value, str) and call.args[0].value.startswith("%Y-%m-01")


def _callee(node) -> str | None:
    if not isinstance(node, ast.Call):
        return None
    if isinstance(node.func, ast.Attribute):
        return node.func.attr
    if isinstance(node.func, ast.Name):
        return node.func.id
    return None


def _is_timedelta(node, *, days_only: bool) -> bool:
    if _callee(node) != "timedelta":
        return False
    return not days_only or any(kw.arg == "days" for kw in node.keywords)


def _is_astimezone_value(node) -> bool:
    """`x.astimezone(z)` or `x.astimezone(z).date()`."""
    if _callee(node) == "date" and isinstance(node.func, ast.Attribute):
        node = node.func.value
    return _callee(node) == "astimezone"


def _is_yesterday(node: ast.BinOp) -> bool:
    if not isinstance(node.op, ast.Sub):
        return False
    if _callee(node.left) == "today_for_org" and _is_timedelta(node.right, days_only=False):
        return True
    return _is_astimezone_value(node.left) and _is_timedelta(node.right, days_only=True)


def _is_queue_instant(call: ast.Call) -> bool:
    """`retry_at=`／`schedule_at=` whose value calls the product clock."""
    return any(
        kw.arg in QUEUE_KEYWORDS and any(
            _callee(node) in PRODUCT_CLOCK_CALLS for node in ast.walk(kw.value))
        for kw in call.keywords
    )


def scan() -> list[tuple[str, str, int, str]]:
    """Every hit as `(file, rule, line, source text)`."""
    hits = []
    for rel, path in _product_files():
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=rel)
        names = _aliases(tree)
        for node in ast.walk(tree):
            rule = None
            if isinstance(node, ast.Call):
                if rel != MACHINE_CLOCK_HOME and _is_machine_clock(node, names):
                    rule = "machine_clock"
                elif rel != MONTH_START_HOME and _is_month_start(node):
                    rule = "month_start"
                elif _is_queue_instant(node):
                    rule = "queue_instant"
            elif isinstance(node, ast.BinOp) and rel not in YESTERDAY_HOMES \
                    and _is_yesterday(node):
                rule = "yesterday"
            if rule:
                text = " ".join((ast.get_source_segment(source, node) or "").split())
                hits.append((rel, rule, node.lineno, text))
    return hits


class ClockRuleTest(unittest.TestCase):
    def test_no_new_clock_outside_the_one_clock(self):
        unlisted = [
            f"app/{rel}:{line} [{rule}] {text}"
            for rel, rule, line, text in scan() if (rel, rule, text) not in PENDING
        ]
        self.assertEqual(unlisted, [], (
            "F50 Contract K: instants come from db.now_utc()／db.now_iso(); the user's day from "
            "settings.today_for_org／org_month_start／org_day_start; yesterday from "
            "settings.last_complete_day (ads: coverage.last_complete_day); queue scheduling "
            "instants from a QUEUE_CLOCK function (SQL now()). See the clock table in "
            "app/core/settings.py."))

    def test_pending_entries_are_not_stale(self):
        found = {(rel, rule, text) for rel, rule, _line, text in scan()}
        stale = [f"{key} ({issue})" for key, issue in PENDING.items() if key not in found]
        self.assertEqual(stale, [], "these PENDING entries no longer match: delete them")

    def test_every_pending_entry_names_an_issue(self):
        for key, issue in PENDING.items():
            self.assertRegex(issue, r"^F\d+-I\d+$", key)

    def test_queue_clock_functions_read_the_database_now(self):
        for (rel, function), reason in QUEUE_CLOCK.items():
            tree = ast.parse((APP_DIR / rel).read_text(encoding="utf-8"))
            found = [n for n in ast.walk(tree)
                     if isinstance(n, ast.FunctionDef | ast.AsyncFunctionDef)
                     and n.name == function]
            self.assertTrue(found, f"stale QUEUE_CLOCK entry app/{rel}::{function} ({reason})")
            reads_now = any(isinstance(n, ast.Constant) and isinstance(n.value, str)
                            and "now()" in n.value for n in ast.walk(found[0]))
            self.assertTrue(reads_now, f"app/{rel}::{function} must read SQL now() ({reason})")

    def test_the_scan_sees_each_shape(self):
        # Guard against a scanner that silently matches nothing.
        source = (
            "import time\nimport datetime as dt\nfrom datetime import date, datetime\n"
            "from time import time as now\n"
            "a = date.today()\nb = datetime.now(UTC)\nc = dt.datetime.utcnow()\n"
            "d = time.time()\ne = now()\nf = x.strftime('%Y-%m-01T00:00:00')\n"
            "g = settings.today_for_org(c, org_id=o) - timedelta(days=1)\n"
            "h = (m.astimezone(z) - timedelta(days=1)).date()\n"
            "i = m.astimezone(z).date() - timedelta(days=1)\n"
            "ok = m.astimezone(z).date() + timedelta(days=1)\n"
            "j = mgr.retry_job_by_id(1, retry_at=db.now_utc())\n"
            "ok2 = mgr.retry_job_by_id(1, retry_at=queue_now)\n"
        )
        tree = ast.parse(source)
        names = _aliases(tree)
        machine = [n for n in ast.walk(tree)
                   if isinstance(n, ast.Call) and _is_machine_clock(n, names)]
        month = [n for n in ast.walk(tree) if isinstance(n, ast.Call) and _is_month_start(n)]
        yesterday = [n for n in ast.walk(tree) if isinstance(n, ast.BinOp) and _is_yesterday(n)]
        queue = [n for n in ast.walk(tree) if isinstance(n, ast.Call) and _is_queue_instant(n)]
        self.assertEqual((len(machine), len(month), len(yesterday), len(queue)), (5, 1, 3, 1))


if __name__ == "__main__":
    unittest.main()
