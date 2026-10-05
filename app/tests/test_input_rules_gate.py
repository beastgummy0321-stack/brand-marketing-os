"""app/tests/test_input_rules_gate.py — F50 Contract I (one input-rule table, audit W12) static
falsifier.

The authority is the rule table in `app/core/input_rules.py`'s module docstring: a store checks a
typed value with those functions and refuses with their sentence; it keeps no bound or sentence of
its own. This scan walks the AST of every product module under `app/` (test modules are fixtures
and are skipped) and fails, naming file, line and text, on:

1. `money_refusal` — a money／rate-named value (`price|cost|shipping|budget|revenue|cap_per_sale|
   quantity|qty|close_rate|margin`) compared with a literal 0, 1 or 100 (`<`, `<=`, `>`, `>=`)
   inside the test of an `if` whose body refuses (raises, returns a sentence／an error response, or
   appends to an error list) — a hand-made store rule. A comparison that only guards arithmetic
   (`if price <= 0: continue`) is not a refusal and is not scanned. Outside `core/input_rules.py`.
2. `url_prefix` — `.startswith("http…")`: a URL is checked by `input_rules.url`／`urls`.
3. `parse_number` — a `parse_number(` call: a store hands the typed value to `input_rules`.
4. `date_slice` — `str(…)[:10]` (or `str(…).strip()[:10]`) used as a value, i.e. not parsed by an
   enclosing `fromisoformat(…)`: a sliced vendor／typed date goes into a column unchecked; stores
   use `input_rules.iso_date`.
5. `percent_bounds` — a rule-card field in `core/rule_cards.py` with unit 「%」 whose bounds are not
   `Bounds(0, 100, …)` (decision 9: percents are stored 0–100).
6. `vocab_unregistered`／`vocab_require` — every `vocab.*_TYPES` list is registered in
   `vocab.REQUIRE_KINDS`, and every registered kind has a `vocab.require("<kind>", …)` caller in a
   product module.

Ratchet (F48's pattern): `PENDING` lists the hits that exist today with the issue that removes
them. A hit not listed fails; a listed entry the scan no longer finds is stale and fails too, so
the list only shrinks. `NOT_INPUT` is permanent: a hit that does not check user／vendor input,
with the reason; a stale one fails as well. Never add an entry to hide a new hit: call the rule.
"""

import ast
import re
import unittest
from pathlib import Path

from app.core import vocab

APP_DIR = Path(__file__).resolve().parent.parent

RULES_HOME = "core/input_rules.py"
RULE_CARDS = "core/rule_cards.py"
PARSE_NUMBER_HOME = "shared/web.py"

MONEY_NAME = re.compile(
    r"price|cost|shipping|budget|revenue|cap_per_sale|quantity|qty|close_rate|margin", re.I)
_COMPARE_OPS = (ast.Lt, ast.LtE, ast.Gt, ast.GtE)
_ERROR_CALL = re.compile(r"bad_request|JSONResponse|error|refus", re.I)

# (file relative to app/, rule, source text of the hit) -> the issue that removes it.
PENDING: dict[tuple[str, str, str], str] = {
    # rule "money_refusal" — ads stores adopt the table in F50-I05 (the intake／brand-intelligence
    # stores, close_rate included, moved in F50-I03).
    ("ads/plan.py", "money_refusal", "daily_budget <= 0"): "F50-I05",
    ("ads/strategy.py", "money_refusal", "budget_cap <= 0"): "F50-I05",
}

# (file relative to app/, rule, source text) -> why it is not a check of user／vendor input.
NOT_INPUT: dict[tuple[str, str, str], str] = {
    ("ads/handoff_new_ad.py", "money_refusal", 'budget["budget_amount"] <= 0'):
        "platform read-back, not input: a handoff premise refuses when the parent's budget read "
        "from the platform is not a positive daily amount",
}


def _product_files():
    for path in sorted(APP_DIR.rglob("*.py")):
        rel = path.relative_to(APP_DIR).as_posix()
        if rel.startswith("tests/"):
            continue
        yield rel, path


def _text(source: str, node) -> str:
    return " ".join((ast.get_source_segment(source, node) or "").split())


def _name_of(node) -> str | None:
    """The name a compared value goes by: `x`, `a.x`, `a["x"]`, `a.get("x")`."""
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    if isinstance(node, ast.Subscript) and isinstance(node.slice, ast.Constant) \
            and isinstance(node.slice.value, str):
        return node.slice.value
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) \
            and node.func.attr == "get" and node.args and isinstance(node.args[0], ast.Constant) \
            and isinstance(node.args[0].value, str):
        return node.args[0].value
    return None


def _is_edge_literal(node) -> bool:
    return isinstance(node, ast.Constant) and not isinstance(node.value, bool) \
        and isinstance(node.value, int | float) and node.value in (0, 1, 100)


def _is_money_comparison(node: ast.Compare) -> bool:
    operands = [node.left, *node.comparators]
    for i, op in enumerate(node.ops):
        if not isinstance(op, _COMPARE_OPS):
            continue
        a, b = operands[i], operands[i + 1]
        for value, edge in ((a, b), (b, a)):
            name = _name_of(value)
            if _is_edge_literal(edge) and name and MONEY_NAME.search(name):
                return True
    return False


def _callee(node) -> str:
    if isinstance(node, ast.Call):
        if isinstance(node.func, ast.Attribute):
            return node.func.attr
        if isinstance(node.func, ast.Name):
            return node.func.id
    return ""


def _refuses(body) -> bool:
    """The `if` body raises, returns a sentence／an error response, or appends to an error list."""
    for stmt in body:
        if isinstance(stmt, ast.Raise):
            return True
        if isinstance(stmt, ast.Return) and stmt.value is not None:
            value = stmt.value
            if isinstance(value, ast.Constant) and isinstance(value.value, str):
                return True
            if isinstance(value, ast.JoinedStr) or _ERROR_CALL.search(_callee(value)):
                return True
        if isinstance(stmt, ast.Expr) and _callee(stmt.value) == "append" \
                and re.search("error", ast.unparse(stmt.value.func.value), re.I):
            return True
    return False


def _is_url_prefix(call: ast.Call) -> bool:
    if _callee(call) != "startswith" or not call.args:
        return False
    first = call.args[0]
    items = first.elts if isinstance(first, ast.Tuple) else [first]
    return any(isinstance(i, ast.Constant) and isinstance(i.value, str)
               and i.value.startswith("http") for i in items)


def _roots_in_str_call(node) -> bool:
    """`str(x)` or a method chain on it (`str(x).strip()`)."""
    while isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
        node = node.func.value
    return isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "str"


def _is_date_slice(node: ast.Subscript) -> bool:
    sl = node.slice
    return isinstance(sl, ast.Slice) and sl.lower is None and sl.step is None \
        and isinstance(sl.upper, ast.Constant) and sl.upper.value == 10 \
        and _roots_in_str_call(node.value)


def _parse_wrapped(tree) -> set[int]:
    """ids of the nodes passed straight to a `fromisoformat(…)` call (parsed, not stored)."""
    return {id(arg) for node in ast.walk(tree)
            if isinstance(node, ast.Call) and _callee(node) == "fromisoformat"
            for arg in node.args}


def _vocab_aliases(tree) -> set[str]:
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module == "app.core":
            names |= {a.asname or a.name for a in node.names if a.name == "vocab"}
        elif isinstance(node, ast.Import):
            names |= {a.asname for a in node.names if a.name == "app.core.vocab" and a.asname}
    return names


def _require_kinds_called(tree) -> set[str]:
    aliases = _vocab_aliases(tree)
    return {node.args[0].value for node in ast.walk(tree)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
            and node.func.attr == "require" and isinstance(node.func.value, ast.Name)
            and node.func.value.id in aliases and node.args
            and isinstance(node.args[0], ast.Constant)}


def _percent_bound_hits(source: str) -> list[tuple[int, str]]:
    """Rule-card field dicts with `"unit": "%"` whose `"bounds"` is not `Bounds(0, 100, …)`."""
    hits = []
    for node in ast.walk(ast.parse(source)):
        if not isinstance(node, ast.Dict):
            continue
        fields = {k.value: v for k, v in zip(node.keys, node.values, strict=True)
                  if isinstance(k, ast.Constant)}
        unit = fields.get("unit")
        if not (isinstance(unit, ast.Constant) and unit.value == "%"):
            continue
        bounds = fields.get("bounds")
        ok = isinstance(bounds, ast.Call) and len(bounds.args) >= 2 and all(
            isinstance(a, ast.Constant) and a.value == want
            for a, want in zip(bounds.args[:2], (0, 100), strict=True))
        if not ok:
            label = fields.get("label")
            hits.append((node.lineno, label.value if isinstance(label, ast.Constant) else "?"))
    return hits


def scan() -> list[tuple[str, str, int, str]]:
    """Every hit as `(file, rule, line, text)`."""
    hits = []
    kinds_called: set[str] = set()
    for rel, path in _product_files():
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=rel)
        kinds_called |= _require_kinds_called(tree)
        parsed = _parse_wrapped(tree)
        seen: set[tuple[int, str]] = set()
        for node in ast.walk(tree):
            if rel != RULES_HOME and isinstance(node, ast.If) and _refuses(node.body):
                for cmp in ast.walk(node.test):
                    if isinstance(cmp, ast.Compare) and _is_money_comparison(cmp):
                        key = (cmp.lineno, _text(source, cmp))
                        if key not in seen:
                            seen.add(key)
                            hits.append((rel, "money_refusal", *key))
            elif isinstance(node, ast.Call):
                if rel != RULES_HOME and _is_url_prefix(node):
                    hits.append((rel, "url_prefix", node.lineno, _text(source, node)))
                elif rel != PARSE_NUMBER_HOME and _callee(node) == "parse_number":
                    hits.append((rel, "parse_number", node.lineno, _text(source, node)))
            elif isinstance(node, ast.Subscript) and _is_date_slice(node) \
                    and id(node) not in parsed:
                hits.append((rel, "date_slice", node.lineno, _text(source, node)))
        if rel == RULE_CARDS:
            hits += [(rel, "percent_bounds", line, label)
                     for line, label in _percent_bound_hits(source)]
    for name in dir(vocab):
        value = getattr(vocab, name)
        if name.endswith("_TYPES") and isinstance(value, list) and not any(
                items is value for _label, items in vocab.REQUIRE_KINDS.values()):
            hits.append(("core/vocab.py", "vocab_unregistered", 0, name))
    hits += [("core/vocab.py", "vocab_require", 0, kind)
             for kind in vocab.REQUIRE_KINDS if kind not in kinds_called]
    return hits


class InputRulesGateTest(unittest.TestCase):
    def test_no_store_rule_outside_the_one_table(self):
        unlisted = [
            f"app/{rel}:{line} [{rule}] {text}"
            for rel, rule, line, text in scan()
            if (rel, rule, text) not in PENDING and (rel, rule, text) not in NOT_INPUT
        ]
        self.assertEqual(unlisted, [], (
            "F50 Contract I: a store checks typed values with app/core/input_rules.py (money "
            "positive／non_negative, count, percent, iso_date, url／urls, one_of／vocab.require) "
            "and refuses with its sentence; see the rule table in that module's docstring."))

    def test_listed_entries_are_not_stale(self):
        found = {(rel, rule, text) for rel, rule, _line, text in scan()}
        stale = [f"{key} ({why})" for key, why in {**PENDING, **NOT_INPUT}.items()
                 if key not in found]
        self.assertEqual(stale, [], "these entries no longer match: delete them")

    def test_every_pending_entry_names_an_issue(self):
        for key, issue in PENDING.items():
            self.assertRegex(issue, r"^F\d+-I\d+$", key)
        for key, why in NOT_INPUT.items():
            self.assertTrue(why.strip(), key)

    def test_the_scan_sees_each_shape(self):
        # Guard against a scanner that silently matches nothing.
        source = (
            "if price <= 0:\n    raise ValueError('x')\n"
            "if not (0 < row['close_rate'] <= 1):\n    return _bad_request('x')\n"
            "if qty < 1:\n    errors.append('x')\n"
            "if price <= 0:\n    continue\n"
            "ok = url.startswith(('https://', 'http://'))\n"
            "v, ok = parse_number(raw)\n"
            "d = str(value).strip()[:10]\n"
            "e = date.fromisoformat(str(value)[:10])\n"
        )
        tree = ast.parse(source)
        parsed = _parse_wrapped(tree)
        money = [c for n in ast.walk(tree) if isinstance(n, ast.If) and _refuses(n.body)
                 for c in ast.walk(n.test)
                 if isinstance(c, ast.Compare) and _is_money_comparison(c)]
        urls = [n for n in ast.walk(tree) if isinstance(n, ast.Call) and _is_url_prefix(n)]
        numbers = [n for n in ast.walk(tree)
                   if isinstance(n, ast.Call) and _callee(n) == "parse_number"]
        slices = [n for n in ast.walk(tree)
                  if isinstance(n, ast.Subscript) and _is_date_slice(n) and id(n) not in parsed]
        self.assertEqual((len(money), len(urls), len(numbers), len(slices)), (3, 1, 1, 1))
        cards = (
            "F = [{'label': 'a', 'unit': '%', 'bounds': input_rules.Bounds(0, 100, low_open=True)},"
            " {'label': 'b', 'unit': '%', 'bounds': input_rules.Bounds(0, 1)},"
            " {'label': 'c', 'unit': 'NT$', 'bounds': input_rules.Bounds(0)}]"
        )
        self.assertEqual([label for _line, label in _percent_bound_hits(cards)], ["b"])
        calls = ast.parse("from app.core import vocab as md\nmd.require('claim', x)\n"
                          "other.require('rule', x)\n")
        self.assertEqual(_require_kinds_called(calls), {"claim"})


if __name__ == "__main__":
    unittest.main()
