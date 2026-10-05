"""app/tests/test_background_outcome_gate.py — F50-I07, feature F50 Contract J scanner.

One background outcome means one way in: every task goes through `background.register()`, so
every job ends with a stored outcome and a failure fails the procrastinate job (the bell counts
it). This gate goes red if the old patterns come back:

1. after every module's registration call, each task on `background.app()` (procrastinate's own
   built-in maintenance task aside) was registered through `register()`;
2. no `.task(name=…)` / `.periodic(…)` registration outside `app/background/__init__.py`;
3. no `UPDATE llm_task … error =` outside `app/llm/gateway.py` — `error`／`error_code` are
   written in one place, so no reader or job replaces the model's error with a sentence of its own.
"""

import ast
import re
import unittest
from pathlib import Path

import app.background as background_module
from app import ads, intake, meta, schedule, workbench
from app import brand_web as brand_web_module
from app import main

APP_DIR = Path(__file__).resolve().parents[1]
_SELF = Path(__file__).resolve()
_BACKGROUND_ENTRY = APP_DIR / "background" / "__init__.py"
_GATEWAY = APP_DIR / "llm" / "gateway.py"

# An `error`／`error_code` assignment inside the SET list (before any WHERE).
_LLM_ERROR_WRITE = re.compile(
    r"UPDATE\s+llm_task\s+SET\b(?:(?!\bWHERE\b).)*?\berror(?:_code)?\s*=",
    re.IGNORECASE | re.DOTALL)


def _python_files():
    for path in sorted(APP_DIR.rglob("*.py")):
        if "__pycache__" in path.parts or path.resolve() == _SELF:
            continue
        yield path


def _string_constants(path: Path):
    """Every string literal in the file (implicitly concatenated literals arrive joined)."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            yield node.lineno, node.value


def _registration_calls(path: Path):
    """Line numbers of procrastinate registration calls: `<x>.task(..., name=...)` and
    `<x>.periodic(...)` (docstrings and comments that quote them are not calls)."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)):
            continue
        if node.func.attr == "periodic" or (
                node.func.attr == "task" and any(k.arg == "name" for k in node.keywords)):
            yield node.lineno


class EveryTaskIsRegisteredThroughRegisterTest(unittest.TestCase):
    def test_every_registered_task_carries_the_outcome_wrapper(self):
        schedule.register_tasks()
        workbench.register_tasks()
        ads.register_tasks()
        meta.register_task()
        intake.register(main.app)
        brand_web_module.register(main.app)

        tasks = background_module.app().tasks
        # procrastinate's own maintenance task (`builtin:…`／`procrastinate.builtin_tasks.…`) is
        # not ours to wrap.
        ours = {name: task for name, task in tasks.items()
                if not name.startswith(("builtin:", "procrastinate."))}
        self.assertGreater(len(ours), 20, "the module registration calls registered nothing?")
        offenders = sorted(name for name, task in ours.items()
                           if not background_module.is_registered_through_register(task))
        self.assertEqual(offenders, [],
                         f"tasks registered without background.register(): {offenders}")


class NoRegistrationOutsideBackgroundTest(unittest.TestCase):
    def test_no_task_or_periodic_registration_outside_the_background_entry(self):
        offenders = []
        for path in _python_files():
            if path.resolve() == _BACKGROUND_ENTRY.resolve():
                continue
            for lineno in _registration_calls(path):
                offenders.append(f"{path.relative_to(APP_DIR.parent).as_posix()}:{lineno}")
        self.assertEqual(offenders, [],
                         "register tasks through background.register(), not procrastinate "
                         "directly:\n" + "\n".join(offenders))


class LlmTaskErrorWrittenOnlyByGatewayTest(unittest.TestCase):
    def test_no_llm_task_error_write_outside_the_gateway(self):
        offenders = []
        for path in _python_files():
            if path.resolve() == _GATEWAY.resolve():
                continue
            for lineno, text in _string_constants(path):
                if _LLM_ERROR_WRITE.search(text):
                    offenders.append(f"{path.relative_to(APP_DIR.parent).as_posix()}:{lineno}")
        self.assertEqual(offenders, [],
                         "llm_task.error／error_code are written only by app/llm/gateway.py "
                         "(use gateway.record_refusal for a program refusal):\n"
                         + "\n".join(offenders))

    def test_the_patterns_still_match_what_they_forbid(self):
        """The scanners themselves stay honest: they hit the shapes they exist to stop."""
        self.assertGreaterEqual(len(list(_registration_calls(_BACKGROUND_ENTRY))), 2,
                                "the task／periodic calls inside background.register went missing")
        self.assertTrue(_LLM_ERROR_WRITE.search(
            "UPDATE llm_task SET status = 'failed', error = %s WHERE id = %s"))
        self.assertFalse(_LLM_ERROR_WRITE.search(
            "UPDATE llm_task SET structured_output_json = %s WHERE id = %s"))
        self.assertFalse(_LLM_ERROR_WRITE.search(
            "UPDATE llm_task SET cost = %s WHERE error = %s"))
        gateway_hits = [text for _, text in _string_constants(_GATEWAY)
                        if _LLM_ERROR_WRITE.search(text)]
        self.assertGreaterEqual(len(gateway_hits), 2, "the gateway's own writes went missing")


if __name__ == "__main__":
    unittest.main()
