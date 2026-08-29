"""Gate B (ticket 02-5, ADR 0027 decision 3): a migration file only creates tables its module owns.

Files are named `<timestamp>_<module>_<desc>.sql`. Ownership registry = the tables each
`*_baseline.sql` creates (derived by parsing, never hand-copied). A later file that
CREATEs a table outside its module's registry fails here. `organisation` belongs to core.
Files whose module is not a known module (typo) fail too.
"""

import re
import unittest
from pathlib import Path

MIGRATIONS_DIR = Path(__file__).resolve().parents[2] / "supabase" / "migrations"
_CREATE = re.compile(r"^\s*CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?\"?([a-z0-9_]+)\"?", re.I | re.M)
_FILE = re.compile(r"^\d{14}_(.+)\.sql$")
MODULES = ("core", "brand_intelligence", "intake", "ads", "orders", "identity", "background", "meta")


def _module_of(path: Path):
    m = _FILE.match(path.name)
    if not m:
        return None
    rest = m.group(1)
    for mod in sorted(MODULES, key=len, reverse=True):
        if rest.startswith(mod + "_"):
            return mod
    return None


def _created_tables(path: Path):
    return _CREATE.findall(path.read_text(encoding="utf-8"))


def ownership():
    reg = {}
    for p in sorted(MIGRATIONS_DIR.glob("*_baseline.sql")):
        mod = _module_of(p)
        for t in _created_tables(p):
            key = t.lower()
            if key in reg and reg[key] != mod:
                raise AssertionError(f"table {key} created by two baselines: {reg[key]} and {mod}")
            reg[key] = mod
    return reg


class MigrationOwnershipTest(unittest.TestCase):
    def test_registry_is_populated(self):
        reg = ownership()
        self.assertGreater(len(reg), 50)
        self.assertEqual(reg.get("organisation"), "core")

    def test_every_file_names_a_known_module(self):
        bad = [p.name for p in MIGRATIONS_DIR.glob("*.sql") if _module_of(p) is None]
        self.assertEqual(bad, [], f"migration files without a known module prefix: {bad}")

    def test_files_only_create_their_own_modules_tables(self):
        reg = ownership()
        violations = []
        for p in sorted(MIGRATIONS_DIR.glob("*.sql")):
            mod = _module_of(p)
            for t in _created_tables(p):
                owner = reg.get(t.lower())
                if owner is None:
                    # a new table: it becomes owned by the file's module; record nothing
                    continue
                if owner != mod:
                    violations.append(f"{p.name} creates {t} (owned by {owner})")
        self.assertEqual(violations, [], "\n".join(violations))


if __name__ == "__main__":
    unittest.main()
