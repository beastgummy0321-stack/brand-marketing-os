"""app/tests/test_ads_no_platform_literal.py — F05-I05 falsifier: `app/ads/**.py` (excluding
`app/ads/channels.py`, `app/ads/outcome.py` and the whole `app/ads/adapters/**` directory) must
never carry a code string literal containing "meta" (any case). §0「不預設」says platform names
only live in `channels.py` (and `outcome.py`'s `source='meta'` ingest column, kept as a named
exception until F06's RC-D). Docstrings are excluded — they explain the rule in prose, they
don't hard-code a branch.
"""

import ast
import unittest
from pathlib import Path

APP_ADS = Path(__file__).resolve().parent.parent / "ads"

EXEMPT_FILES = {APP_ADS / "channels.py", APP_ADS / "outcome.py"}
EXEMPT_DIRS = {APP_ADS / "adapters"}

FAILURE_HINT = "平台名字只准住在 channels.py 或 adapters/（§0 不預設）"


def _is_exempt(path: Path) -> bool:
    if path in EXEMPT_FILES:
        return True
    return any(exempt_dir in path.parents for exempt_dir in EXEMPT_DIRS)


def _docstring_nodes(tree: ast.Module) -> set[int]:
    """`id()` of every AST node that is a docstring Constant (module/class/def's first
    statement) — those are excluded, everything else counts as a real literal."""
    ids: set[int] = set()
    candidates = [tree] + [
        node for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
    ]
    for node in candidates:
        body = getattr(node, "body", None)
        if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant) \
                and isinstance(body[0].value.value, str):
            ids.add(id(body[0].value))
    return ids


class NoPlatformLiteralTest(unittest.TestCase):
    def test_ads_module_has_no_meta_string_literal_outside_named_exceptions(self):
        violations = []
        for path in sorted(APP_ADS.rglob("*.py")):
            if _is_exempt(path):
                continue
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            docstring_ids = _docstring_nodes(tree)
            for node in ast.walk(tree):
                if not isinstance(node, ast.Constant) or not isinstance(node.value, str):
                    continue
                if id(node) in docstring_ids:
                    continue
                if "meta" in node.value.lower():
                    violations.append(f"{path}:{node.lineno}: {node.value!r}")
        self.assertEqual(violations, [], "\n".join([FAILURE_HINT, *violations]))


if __name__ == "__main__":
    unittest.main()
