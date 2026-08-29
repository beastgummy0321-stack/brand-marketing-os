"""app/tests/test_llm_codex_schema.py — to_strict_schema() 純函式測試（票 codex-cli-dev）。

只測 Anthropic input_schema → OpenAI strict schema 的轉換邏輯本身，不連網、不打
本機 codex CLI（那條路要真的打網路、慢、吃訂閱額度，規格明講不寫）。
"""

import unittest

from app.llm.providers import to_strict_schema


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


if __name__ == "__main__":
    unittest.main()
