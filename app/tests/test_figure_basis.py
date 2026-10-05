"""app/tests/test_figure_basis.py — F51 Contract F gate (audit W16): every ROAS figure a backend
payload serves is named by its basis, and the basis table is served once.

Scans (AST) every `app/ads/**.py` outside `app/ads/adapters/**`, every `app/dashboard/**.py` and
`app/meta/routes.py` for the payload names a figure can travel under -- dict keys, subscripts,
keyword argument names and class fields (a pydantic response model's field):

- a bare `roas`, `roas_conservative` or `roas_optimistic` fails (the basis is unnamed);
- any other `roas_*` name must be a basis code of `app/core/figures.py::BASES`.

A value such as `metric == "roas"` (a metric name in a brief or an experiment) is not a key and is
not counted. Pending hits live one module per removing issue under `app/tests/guards/` as
`PENDING = {(file, name): count}` (loaded by glob): a count above its entry, or an unlisted
`(file, name)`, fails naming file and line; a count below its entry fails as stale, naming the
module to lower -- the list only shrinks, and the removing issue deletes its module.

Also: `GET /api/figures` serves `BASES` to a signed-in caller.
"""

import ast
import importlib.util
import unittest
from collections import defaultdict
from pathlib import Path

from fastapi.testclient import TestClient

import app.main as main
from app.core import figures

APP_DIR = Path(__file__).resolve().parent.parent
REPO_ROOT = APP_DIR.parent
GUARDS = Path(__file__).resolve().parent / "guards"

BARE = frozenset({"roas", "roas_conservative", "roas_optimistic"})


def _scanned_files() -> list[Path]:
    files = [p for p in (APP_DIR / "ads").rglob("*.py") if "adapters" not in p.parts]
    files += list((APP_DIR / "dashboard").rglob("*.py"))
    files.append(APP_DIR / "meta" / "routes.py")
    return sorted(files)


def _key_names(tree: ast.AST):
    """`(name, line)` for every dict key, subscript, keyword name and class field that is a
    string naming a figure (`roas` or `roas_*`)."""
    for node in ast.walk(tree):
        names: list[tuple[str, int]] = []
        if isinstance(node, ast.Dict):
            names = [(k.value, k.lineno) for k in node.keys
                     if isinstance(k, ast.Constant) and isinstance(k.value, str)]
        elif isinstance(node, ast.Subscript):
            s = node.slice
            if isinstance(s, ast.Constant) and isinstance(s.value, str):
                names = [(s.value, node.lineno)]
        elif isinstance(node, ast.Call):
            names = [(k.arg, k.value.lineno) for k in node.keywords if k.arg]
        elif isinstance(node, ast.ClassDef):
            names = [(stmt.target.id, stmt.lineno) for stmt in node.body
                     if isinstance(stmt, ast.AnnAssign) and isinstance(stmt.target, ast.Name)]
        for name, line in names:
            if name == "roas" or name.startswith("roas_"):
                yield name, line


def _violations(source: str) -> list[tuple[str, int]]:
    """Bare names and `roas_*` names that are not a basis code."""
    return [
        (name, line) for name, line in _key_names(ast.parse(source))
        if name in BARE or name not in figures.BASES
    ]


def _pending() -> dict:
    """`(file, name) -> (count, module)` from every `guards/figure_basis_*.py`."""
    out: dict = {}
    for path in sorted(GUARDS.glob("figure_basis_*.py")):
        spec = importlib.util.spec_from_file_location(f"_figure_guard_{path.stem}", path)
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        for key, count in module.PENDING.items():
            out[key] = (count, path.name)
    return out


class DetectorTest(unittest.TestCase):
    def test_bare_and_unknown_basis_names_are_hits_values_are_not(self):
        source = (
            "x = {'roas': 1, 'roas_conservative': 2, 'roas_all_spend': 3, 'roas_made_up': 4}\n"
            "y = row['roas']\n"
            "z = f(roas_optimistic=1, roas_tracked_spend=2)\n"
            "class M:\n"
            "    roas: float | None\n"
            "    roas_platform: float | None\n"
            "if metric == 'roas':\n"
            "    pass\n"
            "w = {'success_metric': 'roas'}\n"
        )
        self.assertEqual(
            sorted(_violations(source)),
            [("roas", 1), ("roas", 2), ("roas", 5), ("roas_conservative", 1),
             ("roas_made_up", 1), ("roas_optimistic", 3)],
        )


class FigureBasisGateTest(unittest.TestCase):
    def test_every_roas_name_is_a_basis_code(self):
        found: dict = defaultdict(list)
        for path in _scanned_files():
            rel = path.relative_to(REPO_ROOT).as_posix()
            for name, line in _violations(path.read_text(encoding="utf-8")):
                found[(rel, name)].append(line)
        for lines in found.values():
            lines.sort()
        pending = _pending()
        problems = []
        for key, lines in sorted(found.items()):
            allowed, _module = pending.get(key, (0, None))
            if len(lines) > allowed:
                problems.append(f"{key[0]}:{lines} `{key[1]}` is not named by its basis "
                                f"(app/core/figures.py::BASES)")
        for key, (count, module) in sorted(pending.items()):
            if len(found.get(key, [])) < count:
                problems.append(f"stale pending entry {key} = {count} in guards/{module}: "
                                f"{len(found.get(key, []))} left, lower it")
        self.assertEqual(problems, [])


class BasesShapeTest(unittest.TestCase):
    def test_the_seven_bases_carry_label_formula_and_unit(self):
        self.assertEqual(set(figures.BASES), {
            "roas_all_spend", "roas_tracked_spend", "roas_at_cap", "roas_platform",
            "roas_all_channels", "earn_after_cost_and_ads", "budget_to_date",
        })
        for code, basis in figures.BASES.items():
            self.assertEqual(set(basis), {"label", "formula", "unit"}, code)
            self.assertIn(basis["unit"], {"ratio", "money"}, code)


class FiguresRouteTest(unittest.TestCase):
    """Signed in (the test client carries the dev token, `conftest.py`); the no-token 401 is
    `test_identity_auth.py`'s sweep over every `/api` route."""

    def test_signed_in_caller_reads_the_basis_table(self):
        res = TestClient(main.app).get("/api/figures")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json(), {"bases": figures.BASES})
