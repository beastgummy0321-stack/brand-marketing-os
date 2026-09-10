#!/usr/bin/env python3
"""Architecture checker for Python projects, driven by the ARCHITECTURE.md manifest.

Copied into the project by `harness adapter apply` (tools/check_architecture.py) so CI can run it
without the plugin. Enforces, from the manifest's JSON frontmatter:
  1. cross-module imports only through the module's declared public entry
  2. a module imports only modules listed in its may_depend_on
  3. no dependency cycles between modules (from actual imports)
  4. no module imports the app shell
  5. ownership: a non-owner module does not access another module's resource
     (supabase-table: .table("x") / .from_("x") / .rpc("x") literal targets, a non-literal target in managed code is red;
      sqlalchemy-model: importing the symbol from a definition file; sql-table: the name inside a string literal)
  6. closed world: a managed module imports local code only from a declared module, app shell excluded, or a legacy facade
     (an unclassified shared/utils file is the side door that recouples every module)
Exit code = number of violations (0 = green). Prints one violation per line as path:line: message.
"""
import ast
import fnmatch
import json
import os
import re
import sys

ROOT = os.path.abspath(sys.argv[1] if len(sys.argv) > 1 else ".")


def load_manifest():
    with open(os.path.join(ROOT, "ARCHITECTURE.md"), encoding="utf-8") as f:
        text = f.read()
    m = re.match(r"^---\r?\n([\s\S]*?)\r?\n---", text)
    if not m:
        sys.exit("ARCHITECTURE.md: missing frontmatter")
    return json.loads(m.group(1))


def rel(p):
    return os.path.relpath(p, ROOT).replace(os.sep, "/")


def globmatch(path, patterns):
    for g in patterns:
        if g.endswith("/**"):
            if path == g[:-3] or path.startswith(g[:-3] + "/"):
                return True
        if fnmatch.fnmatch(path, g):
            return True
    return False


def py_files():
    skip = {".git", ".venv", "venv", "node_modules", "__pycache__", ".harness", ".claude", "site-packages"}
    for dirpath, dirnames, filenames in os.walk(ROOT):
        dirnames[:] = [d for d in dirnames if d not in skip]
        for fn in filenames:
            if fn.endswith(".py"):
                yield os.path.join(dirpath, fn)


def module_of(path, modules):
    for name, mod in modules.items():
        if globmatch(path, mod["owns"]) or path == mod["root"] or path.startswith(mod["root"].rstrip("/") + "/"):
            return name
    return None


def dotted_to_path(dotted, level, importer):
    """Resolve an import to a project-relative path prefix (without extension)."""
    if level:
        base = os.path.dirname(importer)
        for _ in range(level - 1):
            base = os.path.dirname(base)
        parts = [base] + ([dotted.replace(".", "/")] if dotted else [])
        return "/".join(p for p in parts if p)
    return dotted.replace(".", "/")


def resolve_target(prefix):
    """Map an import prefix to an existing file: prefix.py or prefix/__init__.py, else None."""
    for cand in (prefix + ".py", prefix + "/__init__.py"):
        if os.path.exists(os.path.join(ROOT, cand)):
            return cand
    return None


def main():
    manifest = load_manifest()
    modules = manifest["modules"]
    app_shell = manifest.get("app_shell", [])
    resources = manifest.get("resources", {})
    legacy = manifest.get("legacy", [])
    facades = set(manifest.get("legacy_facades", []))
    violations = []
    edges = {name: set() for name in modules}

    for abspath in py_files():
        path = rel(abspath)
        if globmatch(path, legacy):
            continue  # legacy is not governed; it may shrink, never grow (issue validation), and is reached only via facades
        me = module_of(path, modules)
        try:
            tree = ast.parse(open(abspath, encoding="utf-8").read(), filename=path)
        except SyntaxError as e:
            violations.append(f"{path}:{e.lineno}: syntax error, cannot check imports")
            continue

        for node in ast.walk(tree):
            targets = []
            if isinstance(node, ast.Import):
                for a in node.names:
                    targets.append((a.name, 0, None))
            elif isinstance(node, ast.ImportFrom):
                targets.append((node.module or "", node.level, [a.name for a in node.names]))
            for dotted, level, names in targets:
                prefix = dotted_to_path(dotted, level, path)
                target = resolve_target(prefix)
                candidates = [target] if target else []
                if names and not level and not target:
                    continue
                # `from pkg.mod import name` may reference a submodule: check each name too
                if names:
                    for n in names:
                        sub = resolve_target(prefix + "/" + n)
                        if sub:
                            candidates.append(sub)
                for tpath in candidates:
                    if me is not None and globmatch(tpath, legacy) and tpath not in facades:
                        violations.append(f"{path}:{node.lineno}: managed module {me} imports legacy internals ({tpath}); use a declared facade")
                        continue
                    other = module_of(tpath, modules)
                    if globmatch(tpath, app_shell) and me is not None:
                        violations.append(f"{path}:{node.lineno}: module {me} imports the app shell ({tpath})")
                        continue
                    if other is None and me is not None and tpath not in facades:
                        violations.append(f"{path}:{node.lineno}: module {me} imports unclassified local file {tpath}; declare it in a module, app_shell or legacy")
                        continue
                    if other is None or other == me:
                        continue
                    if me is None:
                        # app shell / glue importing a module: must still use the public entry
                        if tpath != modules[other]["public"]:
                            violations.append(f"{path}:{node.lineno}: imports {other} internals ({tpath}); use {modules[other]['public']}")
                        continue
                    edges[me].add(other)
                    if other not in modules[me].get("may_depend_on", []):
                        violations.append(f"{path}:{node.lineno}: module {me} may not depend on {other}")
                    if tpath != modules[other]["public"]:
                        violations.append(f"{path}:{node.lineno}: module {me} imports {other} internals ({tpath}); use {modules[other]['public']}")

        # ownership
        src = open(abspath, encoding="utf-8").read()
        who = me or "app shell"
        for rname, r in resources.items():
            owner = r["owner"]
            if me == owner:
                continue
            sym = r["symbol"]
            kind = r["kind"]
            definition = r.get("definition", [])
            if kind == "supabase-table":
                pat = re.compile(r"\.(?:table|from_|rpc)\(\s*['\"]" + re.escape(sym) + r"['\"]")
                for i, line in enumerate(src.splitlines(), 1):
                    if pat.search(line):
                        violations.append(f"{path}:{i}: {who} accesses resource {rname} owned by {owner}")
            elif kind == "sqlalchemy-model":
                # binding, not text: `from app.models import User` where app/models.py is a definition file.
                # ponytail: `import app.models` + `app.models.User` attribute access is not followed.
                if globmatch(path, definition):
                    continue
                for node in ast.walk(tree):
                    if isinstance(node, ast.ImportFrom) and any(a.name == sym for a in node.names):
                        target = resolve_target(dotted_to_path(node.module or "", node.level, path))
                        if target and globmatch(target, definition):
                            violations.append(f"{path}:{node.lineno}: {who} accesses resource {rname} owned by {owner} (imports {sym} from {target})")
            elif kind == "sql-table":
                if globmatch(path, definition):
                    continue
                pat = re.compile(r"['\"][^'\"\n]*\b" + re.escape(sym) + r"\b[^'\"\n]*['\"]")
                for i, line in enumerate(src.splitlines(), 1):
                    if pat.search(line):
                        violations.append(f"{path}:{i}: {who} accesses resource {rname} owned by {owner} (sql literal)")
            else:
                violations.append(f"ARCHITECTURE.md:0: resource {rname}: unsupported ownership adapter for kind {kind}")
        # dynamic supabase target in managed code: ownership unknown = red, never silently green
        if me is not None and any(r["kind"] == "supabase-table" for r in resources.values()):
            dyn = re.compile(r"\.(table|from_|rpc)\(\s*(?!['\"])[^)\s]")
            for i, line in enumerate(src.splitlines(), 1):
                m = dyn.search(line)
                if m:
                    violations.append(f"{path}:{i}: {who} calls .{m.group(1)}() with a non-literal target — ownership unknown; use a string literal")

    # cycles from actual edges
    def find_cycles():
        found = []
        for start in edges:
            stack = [(start, [start])]
            while stack:
                n, trail = stack.pop()
                for d in edges[n]:
                    if d == start:
                        found.append(trail + [d])
                    elif d not in trail:
                        stack.append((d, trail + [d]))
        return found

    seen = set()
    for c in find_cycles():
        key = tuple(sorted(c[:-1]))
        if key in seen:
            continue
        seen.add(key)
        violations.append(f"ARCHITECTURE.md:0: dependency cycle {' -> '.join(c)}")

    for v in violations:
        print(v)
    sys.exit(min(len(violations), 255))


if __name__ == "__main__":
    main()
