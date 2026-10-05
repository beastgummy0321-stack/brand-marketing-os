"""app/tests/test_ads_no_platform_literal.py — the one backend gate for platform literals in the
shared ads core (F05-I05 falsifier, widened by F51 Contract P, audit W19, decision 10).

Scans every `app/ads/**.py` outside `app/ads/adapters/**` (the only home of a platform's own words)
for:

- a code string literal containing `meta` (any case);
- a native status word written in a string (`ACTIVE`, `PAUSED`, … — the platform's own delivery
  vocabulary, which F49 Contract L moved into the adapter's status table; everything else reads
  `lifecycle.delivery`), including SQL quoting it (`native_status='PAUSED'`);
- the platform's level name `adset` (any case, whole word) in a string;
- an import of `app.meta` or a module under it, and the names `meta_repo`／`meta_daily_pull`.

Docstrings are prose that explains a rule, not a branch, and are never counted. No file is exempt
whole: today's hits are listed in `ALLOWED` as `(file, token) -> count`. A count above its entry
(a new literal, or a file that is not listed) fails, naming file and line; a count below its entry
fails as stale — lower it in the same change, the list only ever shrinks.
"""

import ast
import re
import unittest
from collections import defaultdict
from pathlib import Path

APP_ADS = Path(__file__).resolve().parent.parent / "ads"
ADAPTERS = "adapters/"

NATIVE_STATUS_WORDS = frozenset({
    "ACTIVE", "PAUSED", "ARCHIVED", "DELETED", "IN_PROCESS", "WITH_ISSUES", "DISAPPROVED",
    "PENDING_REVIEW", "PREAPPROVED", "PENDING_BILLING_INFO", "CAMPAIGN_PAUSED", "ADSET_PAUSED",
})
META = "meta"
LEVEL = "adset"
META_IMPORT = "app.meta"
META_NAMES = frozenset({"meta_repo", "meta_daily_pull"})

# A status word stands alone (an `_` or letter next to it makes another identifier, so the
# `PAUSED` inside `ADSET_PAUSED` is that word, not a second hit).
_STATUS_WORD = re.compile(
    r"(?<![A-Za-z0-9_])("
    + "|".join(sorted(NATIVE_STATUS_WORDS, key=len, reverse=True))
    + r")(?![A-Za-z0-9_])"
)
# `\b`: `adset_id`／`ADSET_PAUSED` are other words; `'adset'`, `native_kind='adset'` are the level.
_LEVEL_WORD = re.compile(r"\badset\b", re.I)

# Today's platform words in the shared core (counted at the F51 base). They leave with the full
# multi-platform adapter move -- docs/backlog/audit-2026-10-04/README.md 「Not in this round」.
# Lower a count when its hit goes; never raise one or add an entry.
ALLOWED = {
    ("__init__.py", META_IMPORT): 1,
    ("__init__.py", "meta_repo"): 1,
    ("ab_pairs.py", "PAUSED"): 1,  # the change-set pause payload `{"status": "PAUSED"}`
    ("change_control.py", LEVEL): 1,
    ("change_control_data.py", "PAUSED"): 1,  # the change-set pause payload, validated as written
    ("change_control_data.py", LEVEL): 1,
    ("channels.py", META): 9,
    ("channels.py", META_IMPORT): 2,
    ("channels.py", "meta_repo"): 5,
    ("channels.py", "meta_daily_pull"): 2,
    ("period_grades.py", LEVEL): 2,
    ("repository.py", LEVEL): 1,
    ("simulation_recovery.py", META_IMPORT): 1,
    ("simulation_recovery.py", "meta_repo"): 1,
    ("simulation_recovery.py", LEVEL): 1,
    ("triage_scale.py", LEVEL): 3,
}

FAILURE_HINT = (
    "平台的字（meta、平台狀態字、adset、app.meta）只准住在 app/ads/adapters/"
    "（§0 不預設，F51 Contract P）"
)


def _docstring_ids(tree: ast.Module) -> set[int]:
    """`id()` of every docstring Constant (a module／class／def's first statement)."""
    ids: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Module | ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef) \
                and node.body and isinstance(node.body[0], ast.Expr) \
                and isinstance(node.body[0].value, ast.Constant) \
                and isinstance(node.body[0].value.value, str):
            ids.add(id(node.body[0].value))
    return ids


def _package(relative: str) -> list[str]:
    """The dotted package of a file under `app/ads` (`x.py` -> app.ads, `a/x.py` -> app.ads.a)."""
    return ["app", "ads", *relative.split("/")[:-1]]


def _imported_module(node: ast.ImportFrom, relative: str) -> str:
    """The absolute module a `from … import` reads (relative imports resolved from the file)."""
    if not node.level:
        return node.module or ""
    base = _package(relative)[: len(_package(relative)) - (node.level - 1)]
    return ".".join([*base, *([node.module] if node.module else [])])


def _is_meta_module(module: str) -> bool:
    return module == META_IMPORT or module.startswith(META_IMPORT + ".")


def _string_tokens(value: str) -> set[str]:
    tokens = set(_STATUS_WORD.findall(value))
    if META in value.lower():
        tokens.add(META)
    if _LEVEL_WORD.search(value):
        tokens.add(LEVEL)
    return tokens


def platform_hits(source: str, relative: str) -> list[tuple[str, int]]:
    """`(token, line)` for every platform word in one file's code (docstrings left out)."""
    tree = ast.parse(source, filename=relative)
    docstrings = _docstring_ids(tree)
    hits: list[tuple[str, int]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            if id(node) not in docstrings:
                hits.extend((token, node.lineno) for token in sorted(_string_tokens(node.value)))
        elif isinstance(node, ast.Import):
            hits.extend((META_IMPORT, node.lineno) for alias in node.names
                        if _is_meta_module(alias.name))
        elif isinstance(node, ast.ImportFrom):
            module = _imported_module(node, relative)
            if _is_meta_module(module) or (
                module == "app" and any(alias.name == "meta" for alias in node.names)
            ):
                hits.append((META_IMPORT, node.lineno))
        elif isinstance(node, ast.Name) and node.id in META_NAMES:
            hits.append((node.id, node.lineno))
        elif isinstance(node, ast.Attribute) and node.attr in META_NAMES:
            hits.append((node.attr, node.lineno))
        elif isinstance(node, ast.arg) and node.arg in META_NAMES:
            hits.append((node.arg, node.lineno))
    return hits


def ratchet_problems(sources: dict[str, str], allowed: dict[tuple[str, str], int]) -> list[str]:
    """Every `(file, token)` over its allowance (naming each line) or under it (stale)."""
    found: dict[tuple[str, str], list[int]] = defaultdict(list)
    for relative, source in sources.items():
        for token, line in platform_hits(source, relative):
            found[(relative, token)].append(line)
    problems = []
    for (relative, token), lines in sorted(found.items()):
        limit = allowed.get((relative, token), 0)
        if len(lines) > limit:
            where = ", ".join(f"app/ads/{relative}:{line}" for line in sorted(lines))
            listed = f"allowed {limit}" if (relative, token) in allowed else "not listed"
            problems.append(f"new {token!r}: {len(lines)} hits, {listed} -- {where}")
    for (relative, token), limit in sorted(allowed.items()):
        count = len(found.get((relative, token), []))
        if count < limit:
            problems.append(
                f"stale: app/ads/{relative} has {count} {token!r} hits, ALLOWED says {limit} "
                f"-- lower ALLOWED[({relative!r}, {token!r})] to {count}"
                + (" (delete the entry)" if count == 0 else "")
            )
    return problems


def _core_sources() -> dict[str, str]:
    sources = {}
    for path in sorted(APP_ADS.rglob("*.py")):
        relative = path.relative_to(APP_ADS).as_posix()
        if relative.startswith(ADAPTERS):
            continue
        sources[relative] = path.read_text(encoding="utf-8")
    return sources


class NoPlatformLiteralTest(unittest.TestCase):
    def test_the_shared_core_gains_no_platform_word_and_the_list_only_shrinks(self):
        sources = _core_sources()
        self.assertTrue(sources)
        self.assertEqual(ratchet_problems(sources, ALLOWED), [], FAILURE_HINT)

    def test_a_new_level_literal_fails_naming_the_line(self):
        source = 'def kind():\n    return "adset"\n'
        problems = ratchet_problems({"scratch.py": source}, {})
        self.assertEqual(len(problems), 1)
        self.assertIn("'adset'", problems[0])
        self.assertIn("app/ads/scratch.py:2", problems[0])
        # A listed file over its count fails the same way.
        problems = ratchet_problems(
            {"scratch.py": 'A = "adset"\nB = "native_kind=\'adset\'"\n'},
            {("scratch.py", LEVEL): 1},
        )
        self.assertEqual(len(problems), 1)
        self.assertIn("allowed 1", problems[0])

    def test_a_docstring_mention_passes(self):
        source = (
            '"""Meta calls its group level adset and pauses with PAUSED."""\n'
            "class Group:\n"
            '    """An adset (ACTIVE／PAUSED) as app.meta.repository reads it."""\n'
            "    def name(self):\n"
            '        """meta_repo is not imported here."""\n'
            '        return "group"\n'
        )
        self.assertEqual(ratchet_problems({"scratch.py": source}, {}), [])

    def test_a_removed_hit_without_lowering_its_count_fails_as_stale(self):
        source = 'A = "adset"\n'
        problems = ratchet_problems({"scratch.py": source}, {("scratch.py", LEVEL): 2})
        self.assertEqual(len(problems), 1)
        self.assertTrue(problems[0].startswith("stale:"), problems[0])
        self.assertIn("to 1", problems[0])
        gone = ratchet_problems({"scratch.py": "A = 1\n"}, {("scratch.py", LEVEL): 1})
        self.assertIn("(delete the entry)", gone[0])

    def test_the_scan_sees_each_planted_shape(self):
        source = (
            '"""ACTIVE in prose is fine."""\n'
            "import app.meta.daily_pull\n"
            "from app.meta import repository as meta_repo\n"
            "from app import meta\n"
            "from ..meta import routes\n"
            "from .adapters import meta_read\n"
            "def rule(ad, meta_daily_pull):\n"
            "    if ad['native_status'] == 'ACTIVE':\n"
            "        return meta_repo.rows(ad)\n"
            "    q = \"SELECT 1 FROM ads_external_entity WHERE native_status='PAUSED'\"\n"
            "    r = \"SELECT 1 FROM ads_external_entity WHERE native_kind='ADSET'\"\n"
            "    s = {'status': 'ADSET_PAUSED', 'adset_id': 'x', 'channel_key': 'Meta'}\n"
            "    return f\"{ad['id']} PENDING_REVIEW\"\n"
        )
        self.assertEqual(
            sorted(platform_hits(source, "scratch.py")),
            [
                ("ACTIVE", 8), ("ADSET_PAUSED", 12), ("PAUSED", 10), ("PENDING_REVIEW", 13),
                (LEVEL, 11),
                (META_IMPORT, 2), (META_IMPORT, 3), (META_IMPORT, 4), (META_IMPORT, 5),
                (META, 12), ("meta_daily_pull", 7), ("meta_repo", 9),
            ],
        )


if __name__ == "__main__":
    unittest.main()
