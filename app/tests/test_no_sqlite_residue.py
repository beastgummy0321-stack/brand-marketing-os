# -*- coding: utf-8 -*-
"""Gate C (ticket 02-5, ADR 0027 decision 1): no SQLite residue in production code.

Scans every non-test `app/**/*.py` with `ast`: string constants that look like SQL are
checked for SQLite-only constructs and `?` placeholders; the module source is checked
for `sqlite3`. Comments and docstrings are ignored by construction (docstrings are
string constants too, so the SQL-shaped check applies only to strings containing a
SQL verb, and docstrings that quote SQL are excluded by the DOCSTRING test below).
"""

import ast
import re
import unittest
from pathlib import Path

APP_DIR = Path(__file__).resolve().parents[1]
_SQL_VERB = re.compile(r"\b(SELECT|INSERT|UPDATE|DELETE|CREATE|ALTER|WITH)\b", re.I)
_BAD = {
    "sqlite placeholder ?": re.compile(r"\?\s*[,)]|=\s*\?(\s|$)"),
    "PRAGMA": re.compile(r"\bPRAGMA\b", re.I),
    "rowid": re.compile(r"\browid\b", re.I),
    "INSERT OR IGNORE/REPLACE": re.compile(r"\bINSERT\s+OR\s+(IGNORE|REPLACE)\b", re.I),
    "json_extract": re.compile(r"\bjson_extract\s*\(", re.I),
    "sqlite_master": re.compile(r"\bsqlite_master\b", re.I),
}


def _production_files():
    for p in APP_DIR.rglob("*.py"):
        rel = p.relative_to(APP_DIR).as_posix()
        if rel.startswith("tests/") or "__pycache__" in rel:
            continue
        yield p


def _docstring_nodes(tree):
    out = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            if node.body and isinstance(node.body[0], ast.Expr) and isinstance(node.body[0].value, ast.Constant):
                out.add(id(node.body[0].value))
    return out


def _joined_text(node: ast.JoinedStr) -> str:
    """Flatten an f-string: constant fragments kept, each `{expr}` becomes `{}` so the
    SQL verb and a `?` on either side of an interpolation land in ONE string."""
    parts = []
    for v in node.values:
        if isinstance(v, ast.Constant) and isinstance(v.value, str):
            parts.append(v.value)
        else:
            parts.append("{}")
    return "".join(parts)


def _sql_strings(path: Path):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    docs = _docstring_nodes(tree)
    inside_fstring = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.JoinedStr):
            for v in node.values:
                inside_fstring.add(id(v))
            text = _joined_text(node)
            if _SQL_VERB.search(text):
                yield node.lineno, text
    for node in ast.walk(tree):
        if (isinstance(node, ast.Constant) and isinstance(node.value, str)
                and id(node) not in docs and id(node) not in inside_fstring):
            if _SQL_VERB.search(node.value):
                yield node.lineno, node.value


class NoSqliteResidueTest(unittest.TestCase):
    def test_no_sqlite3_module_use(self):
        hits = []
        for p in _production_files():
            tree = ast.parse(p.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if isinstance(node, ast.Import) and any(a.name == "sqlite3" for a in node.names):
                    hits.append(f"{p}:{node.lineno}")
                if isinstance(node, ast.ImportFrom) and node.module == "sqlite3":
                    hits.append(f"{p}:{node.lineno}")
                if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name) and node.value.id == "sqlite3":
                    hits.append(f"{p}:{node.lineno}")
        self.assertEqual(hits, [], "\n".join(hits))

    def test_no_sqlite_constructs_in_sql_strings(self):
        hits = []
        for p in _production_files():
            for lineno, s in _sql_strings(p):
                for label, rx in _BAD.items():
                    if rx.search(s):
                        hits.append(f"{p.relative_to(APP_DIR)}:{lineno} {label}")
        self.assertEqual(hits, [], "\n".join(hits))


if __name__ == "__main__":
    unittest.main()
