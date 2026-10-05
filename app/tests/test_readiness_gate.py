"""app/tests/test_readiness_gate.py — F50 Contract R (one readiness, audit W13) static falsifier.

The authority is `app/brand_intelligence/repository.py`: `product_readiness`, `sellable_products`
and `knowledge_products` are the only answers to "is this product ready / is this sell-way
pickable / which products can a picker list"; `all_product_rows` is the raw identity read. This scan
walks the AST of every product module under `app/` (test modules are fixtures, not product code,
and are skipped) and fails, naming file, line and text, on:

1. `create_product(` without `parent_id=` outside `app/intake/product_onboarding.py` -- a root
   knowledge product is born only through product onboarding (step 1 set), never 「ready」 with
   no sell-way;
2. `onboarding_step is None` / `is not None` (a subscript, `.get("onboarding_step")`, an
   attribute or a name of that spelling) or SQL `onboarding_step IS [NOT] NULL` outside the
   facade's readiness functions -- a reader deriving "finished / ready" on its own is the fifth
   implementation the contract removed;
3. `list_products(` anywhere outside `app/brand_intelligence/` (the raw list is gone), and
   `all_product_rows(` outside the facade and `IDENTITY_READERS` (each with why every row is
   identity there).

Allowlists are ratchets (F48's stale-entry pattern): a listed entry the scan no longer finds
fails, so they only shrink. Never add an entry to hide a new hit: read the facade instead.
"""

import ast
import re
import unittest
from pathlib import Path

APP_DIR = Path(__file__).resolve().parent.parent

FACADE = "brand_intelligence/repository.py"
CREATE_HOME = "intake/product_onboarding.py"
# The facade functions that may read `onboarding_step` as a verdict (`_readiness` is
# `product_readiness`' batch form, shared by `sellable_products`).
READINESS_FUNCTIONS = {"product_readiness", "sellable_products", "knowledge_products", "_readiness"}

# (file relative to app/, function) -> why it reads `onboarding_step` against None. Onboarding's
# own step machine, not a readiness verdict.
STEP_MACHINERY: dict[tuple[str, str], str] = {
    ("intake/product_prefill.py", "start_scan"):
        "the product-page read is offered only while onboarding runs (a finished product shows "
        "saved values only) -- step state of the onboarding flow, not 「ready / pickable」",
}

# file relative to app/ -> why every product row is identity there (Contract R item 1).
IDENTITY_READERS: dict[str, str] = {
    "workbench/claims.py": "registered_names: every active product / sell-way name is stripped "
                           "before a forbidden-word scan, ready or not",
    "intake/product_onboarding.py": "name uniqueness on create / bundle save and the scan "
                                    "suggestions hidden by an existing name or URL",
    "ads/repository.py": "brand-owns-id checks of a campaign's product_ids",
}

_STEP_SQL = re.compile(r"onboarding_step\s+IS\s+(NOT\s+)?NULL", re.IGNORECASE)


def _product_files():
    for path in sorted(APP_DIR.rglob("*.py")):
        rel = path.relative_to(APP_DIR).as_posix()
        if rel.startswith("tests/"):
            continue
        yield rel, path


def _call_name(node: ast.Call) -> str | None:
    func = node.func
    if isinstance(func, ast.Attribute):
        return func.attr
    if isinstance(func, ast.Name):
        return func.id
    return None


def _is_step(node) -> bool:
    """`x["onboarding_step"]`, `x.get("onboarding_step")`, `x.onboarding_step` or the bare
    name."""
    if isinstance(node, ast.Subscript):
        key = node.slice
        return isinstance(key, ast.Constant) and key.value == "onboarding_step"
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) \
            and node.func.attr == "get" and node.args:
        first = node.args[0]
        return isinstance(first, ast.Constant) and first.value == "onboarding_step"
    if isinstance(node, ast.Attribute):
        return node.attr == "onboarding_step"
    return isinstance(node, ast.Name) and node.id == "onboarding_step"


def _is_none(node) -> bool:
    return isinstance(node, ast.Constant) and node.value is None


def _hits(rel: str, source: str) -> list[tuple[str, str, int, str]]:
    """`(rule, enclosing function, line, text)` of every hit in one module."""
    tree = ast.parse(source)
    lines = source.splitlines()
    out = []

    def visit(node, function: str) -> None:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            function = node.name
        text = lines[node.lineno - 1].strip() if hasattr(node, "lineno") else ""
        if isinstance(node, ast.Call):
            name = _call_name(node)
            if name == "create_product" and not any(k.arg == "parent_id" for k in node.keywords):
                out.append(("create_product", function, node.lineno, text))
            elif name in ("list_products", "all_product_rows"):
                out.append((name, function, node.lineno, text))
        elif isinstance(node, ast.Compare) and any(
                isinstance(op, (ast.Is, ast.IsNot)) for op in node.ops):
            operands = [node.left, *node.comparators]
            if any(_is_step(o) for o in operands) and any(_is_none(o) for o in operands):
                out.append(("onboarding_step", function, node.lineno, text))
        elif isinstance(node, ast.Constant) and isinstance(node.value, str) \
                and _STEP_SQL.search(node.value):
            out.append(("onboarding_step", function, node.lineno, text))
        for child in ast.iter_child_nodes(node):
            visit(child, function)

    visit(tree, "<module>")
    return out


def _all_hits() -> list[tuple[str, str, str, int, str]]:
    return [(rel, *hit) for rel, path in _product_files()
            for hit in _hits(rel, path.read_text(encoding="utf-8"))]


def _violations(hits) -> list[str]:
    bad = []
    for rel, rule, function, line, text in hits:
        if rule == "create_product" and rel == CREATE_HOME:
            continue
        if rule == "onboarding_step" and (
                (rel == FACADE and function in READINESS_FUNCTIONS)
                or (rel, function) in STEP_MACHINERY):
            continue
        if rule == "list_products" and rel.startswith("brand_intelligence/"):
            continue
        if rule == "all_product_rows" and (rel.startswith("brand_intelligence/")
                                           or rel in IDENTITY_READERS):
            continue
        bad.append(f"app/{rel}:{line} [{rule}] in {function}(): {text}")
    return bad


class ReadinessGateTest(unittest.TestCase):
    def test_no_reader_outside_the_one_readiness(self):
        bad = _violations(_all_hits())
        self.assertEqual(bad, [], "F50 Contract R: read `product_readiness`／`sellable_products`／"
                                  "`knowledge_products` of the brand-intelligence facade, and "
                                  "create root products through product onboarding:\n"
                                  + "\n".join(bad))

    def test_allowlists_are_not_stale(self):
        hits = _all_hits()
        steps = {(rel, function) for rel, rule, function, _l, _t in hits
                 if rule == "onboarding_step"}
        identity = {rel for rel, rule, _f, _l, _t in hits if rule == "all_product_rows"}
        stale = [f"STEP_MACHINERY {k}" for k in STEP_MACHINERY if k not in steps]
        stale += [f"IDENTITY_READERS {k}" for k in IDENTITY_READERS if k not in identity]
        self.assertEqual(stale, [], "these allowlist entries no longer match a hit; delete them")

    def test_readiness_functions_exist_in_the_facade(self):
        tree = ast.parse((APP_DIR / FACADE).read_text(encoding="utf-8"))
        defined = {n.name for n in tree.body if isinstance(n, ast.FunctionDef)}
        self.assertLessEqual(READINESS_FUNCTIONS, defined)
        self.assertNotIn("list_products", defined)


class ScannerGoesRedTest(unittest.TestCase):
    """The scan itself: each pattern it exists for is found in a synthetic module."""

    SAMPLE = '\n'.join([
        "def picker(conn, b, p):",
        "    repo.create_product(conn, b, name='x', actor='a')",
        "    repo.create_product(conn, b, name='y', actor='a', parent_id=p)",
        "    if p.get('onboarding_step') is None: pass",
        "    if p['onboarding_step'] is not None: pass",
        "    conn.execute('SELECT 1 FROM product WHERE onboarding_step IS NULL')",
        "    repo.list_products(conn, b)",
        "    repo.all_product_rows(conn, b)",
    ])

    def test_every_pattern_is_found(self):
        rules = [rule for rule, _f, _l, _t in _hits("ads/sample.py", self.SAMPLE)]
        self.assertEqual(rules, ["create_product", "onboarding_step", "onboarding_step",
                                 "onboarding_step", "list_products", "all_product_rows"])
        bad = _violations([("ads/sample.py", *h) for h in _hits("ads/sample.py", self.SAMPLE)])
        self.assertEqual(len(bad), 6)


if __name__ == "__main__":
    unittest.main()
