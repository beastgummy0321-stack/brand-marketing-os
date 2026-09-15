"""app/tests/test_llm_codex_schema.py — to_strict_schema() 純函式測試（票 codex-cli-dev）。

只測 Anthropic input_schema → OpenAI strict schema 的轉換邏輯本身，不連網、不打
本機 codex CLI（那條路要真的打網路、慢、吃訂閱額度，規格明講不寫）。

CodexCliProviderCommandTest 額外測 complete() 組出來的指令列本身（effort 對映、六個
--disable，票 F07-I02）：一樣不連網、不打真的 codex，用假 subprocess.Popen 只錄 cmd。
"""

import json
import unittest
from unittest import mock

from app.llm.providers import TASK_DEFAULTS, CodexCliProvider, to_strict_schema


class ToStrictSchemaTest(unittest.TestCase):
    def test_all_required_stays_unchanged_besides_additional_properties(self):
        """既有欄位全部必填時，只補 additionalProperties，不動 required／type。"""
        schema = {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "gaps": {"type": "array", "items": {"type": "string"}, "maxItems": 8},
            },
            "required": ["name", "gaps"],
            "additionalProperties": False,
        }
        result = to_strict_schema(schema)
        self.assertEqual(result["required"], ["name", "gaps"])
        self.assertEqual(result["properties"]["name"], {"type": "string"})
        self.assertEqual(result["properties"]["gaps"]["maxItems"], 8)  # minItems/maxItems 保留
        self.assertFalse(result["additionalProperties"])

    def test_optional_field_becomes_required_with_nullable_type(self):
        """非必填欄位：列入 required，型別加上 null（實測可行的頂替寫法）。"""
        schema = {
            "type": "object",
            "properties": {
                "done": {"type": "boolean"},
                "question": {"type": "string"},
            },
            "required": ["done"],
        }
        result = to_strict_schema(schema)
        self.assertEqual(set(result["required"]), {"done", "question"})
        self.assertEqual(result["properties"]["done"], {"type": "boolean"})  # 本來就必填，不動
        self.assertEqual(result["properties"]["question"]["type"], ["string", "null"])

    def test_optional_enum_field_gets_null_appended_to_enum(self):
        schema = {
            "type": "object",
            "properties": {"aspect": {"type": "string", "enum": ["A", "B"]}},
            "required": [],
        }
        result = to_strict_schema(schema)
        prop = result["properties"]["aspect"]
        self.assertEqual(prop["type"], ["string", "null"])
        self.assertEqual(prop["enum"], ["A", "B", None])

    def test_nested_object_recurses_and_becomes_nullable_when_optional(self):
        """非必填的巢狀 object（例如 _CHOICE_SCHEMA 那種 suggested 欄位）：先遞迴轉換內部，
        再整個包上 null，兩件事都要發生。"""
        schema = {
            "type": "object",
            "properties": {
                "suggested": {
                    "type": "object",
                    "properties": {"label": {"type": "string"}, "desc": {"type": "string"}},
                    "required": ["label", "desc"],
                    "additionalProperties": False,
                },
            },
            "required": [],
        }
        result = to_strict_schema(schema)
        suggested = result["properties"]["suggested"]
        self.assertEqual(suggested["type"], ["object", "null"])
        self.assertEqual(set(suggested["required"]), {"label", "desc"})  # 內部遞迴轉換照樣跑
        self.assertFalse(suggested["additionalProperties"])

    def test_array_items_object_recurses(self):
        """array 的 items 是 object 時，items 本身也要跑過同一套轉換（branches 那種欄位）。"""
        schema = {
            "type": "object",
            "properties": {
                "branches": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {"label": {"type": "string"}, "note": {"type": "string"}},
                        "required": ["label"],
                        "additionalProperties": False,
                    },
                    "minItems": 2,
                    "maxItems": 3,
                },
            },
            "required": [],
        }
        result = to_strict_schema(schema)
        branches = result["properties"]["branches"]
        self.assertEqual(branches["type"], ["array", "null"])  # branches 本身非必填
        self.assertEqual(branches["minItems"], 2)
        self.assertEqual(branches["maxItems"], 3)
        item_schema = branches["items"]
        self.assertEqual(set(item_schema["required"]), {"label", "note"})  # items 內部也轉換過
        self.assertEqual(item_schema["properties"]["note"]["type"], ["string", "null"])

    def test_does_not_mutate_input_schema(self):
        """純函式：不能動到呼叫端傳進來的原始 dict（那些是模組層共用常數，例如
        app/intake/ai.py 的 _QUESTION_TOOL，被改到會讓 Anthropic 那條線也遭殃）。"""
        original = {
            "type": "object",
            "properties": {"question": {"type": "string"}},
            "required": [],
        }
        import copy
        snapshot = copy.deepcopy(original)
        to_strict_schema(original)
        self.assertEqual(original, snapshot)


class _FakeCodexPopen:
    """假 subprocess.Popen：錄下組出來的 cmd，寫一個最小可解析的輸出檔＋JSONL，
    不真的跑 codex（票 F07-I02，不連網、不打真的 codex 行程）。"""

    def __init__(self, cmd, *, cwd=None, stdin=None, stdout=None, stderr=None,
                 text=None, encoding=None, errors=None):
        self.cmd = cmd
        self.returncode = 0
        # -o 後面那個檔案路徑：complete() 只從這個檔案讀最終文字，這裡先寫個佔位值。
        output_index = cmd.index("-o") + 1
        from pathlib import Path
        Path(cmd[output_index]).write_text("{}", encoding="utf-8")

    def communicate(self, input=None, timeout=None):
        usage_line = json.dumps({
            "type": "turn.completed",
            "usage": {"input_tokens": 1, "output_tokens": 1},
        })
        return usage_line + "\n", ""

    def wait(self):
        return self.returncode


class CodexCliProviderCommandTest(unittest.TestCase):
    """`complete()` 組出來的指令列（票 F07-I02，ARCHITECTURE.md §1 rule 4）。"""

    def _run(self, **kwargs):
        recorded = {}

        def fake_popen(cmd, **popen_kwargs):
            proc = _FakeCodexPopen(cmd, **popen_kwargs)
            recorded["cmd"] = cmd
            return proc

        with mock.patch("app.llm.providers.subprocess.Popen", side_effect=fake_popen):
            CodexCliProvider().complete(
                model="gpt-5.6-luna", system=None,
                messages=[{"role": "user", "content": "hi"}], max_tokens=100,
                **kwargs,
            )
        return recorded["cmd"]

    def test_effort_medium_appends_reasoning_effort_and_all_six_disables(self):
        cmd = self._run(effort="medium")
        self.assertIn('model_reasoning_effort="medium"', cmd)
        for name in ("shell_tool", "browser_use", "computer_use", "apps",
                     "image_generation", "in_app_browser"):
            self.assertIn(name, cmd)
            # F07-I13 item 7: each disabled tool name must be immediately preceded by its own
            # "--disable" flag (bare assertIn passes even if the pairs are shifted).
            self.assertEqual(cmd[cmd.index(name) - 1], "--disable")
        self.assertEqual(cmd.count("--disable"), 6)

    def test_effort_levels_map_to_themselves(self):
        # F07-I13 item 3: every named level must round-trip to itself (kills the "low"->"medium",
        # "xhigh"->"high" mutant at app/llm/providers.py:668).
        for level in ("low", "medium", "high", "xhigh"):
            with self.subTest(level=level):
                cmd = self._run(effort=level)
                self.assertIn(f'model_reasoning_effort="{level}"', cmd)
                # F07-I13 item 4: the "-c" flag must sit right before the reasoning-effort arg.
                idx = cmd.index(f'model_reasoning_effort="{level}"')
                self.assertEqual(cmd[idx - 1], "-c")

    def test_effort_max_maps_to_xhigh(self):
        cmd = self._run(effort="max")
        self.assertIn('model_reasoning_effort="xhigh"', cmd)
        idx = cmd.index('model_reasoning_effort="xhigh"')
        self.assertEqual(cmd[idx - 1], "-c")

    def test_unknown_effort_appends_no_reasoning_effort(self):
        # F07-I13 item 5: an effort not in the map must not fall back to itself
        # (`.get(effort)` vs `.get(effort, effort)` at app/llm/providers.py:669).
        cmd = self._run(effort="bogus")
        self.assertNotIn("model_reasoning_effort", " ".join(cmd))

    def test_effort_none_appends_no_reasoning_effort(self):
        cmd = self._run(effort=None)
        self.assertNotIn("model_reasoning_effort", " ".join(cmd))
        # F07-I13 item 6: the six --disable pairs must still be present with no effort set.
        for name in ("shell_tool", "browser_use", "computer_use", "apps",
                     "image_generation", "in_app_browser"):
            self.assertIn(name, cmd)
            self.assertEqual(cmd[cmd.index(name) - 1], "--disable")

    def test_web_search_tool_still_present_with_effort_set(self):
        from app.llm.providers import WEB_SEARCH_TOOL
        cmd = self._run(effort="high", tools=[WEB_SEARCH_TOOL])
        self.assertIn("tools.web_search=true", cmd)
        self.assertIn('model_reasoning_effort="high"', cmd)

    def test_workbench_derive_identity_task_default_is_medium_thinking(self):
        # F07-I13 item 8: the task default must not carry a model id
        # (app/llm/providers.py:199).
        self.assertEqual(
            TASK_DEFAULTS["workbench_derive_identity"], {"model": None, "thinking": "medium"}
        )

    def test_workbench_derive_identity_task_label(self):
        # F07-I13 item 9: kills deletion of the TASK_TYPE_LABELS row (app/llm/providers.py:175).
        from app.llm.providers import TASK_TYPE_LABELS
        self.assertEqual(
            TASK_TYPE_LABELS["workbench_derive_identity"], "素材工作檯：品牌視覺推導"
        )


if __name__ == "__main__":
    unittest.main()
