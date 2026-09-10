"""票 F01-T02-I01：深度 3 節點的 `copy_length`——`short`／`medium`／`long`，其他值或缺
欄位一律 `short`，這不是拒絕條件。`build_tree` 是純函數，不碰 DB，直接餵 fenced json。"""

import json
import unittest

from app.schedule import tree as tree_mod


def _tree_fenced(nodes: list, levels: list | None = None, budget_level: int = 2) -> str:
    payload = {
        "levels": levels or ["行銷活動", "廣告組合", "廣告"],
        "budget_level": budget_level,
        "nodes": nodes,
    }
    body = json.dumps(payload, ensure_ascii=False)
    return f"這是一段給老闆看的說明文字。\n\n```json\n{body}\n```"


def _leaf(**overrides) -> dict:
    node = {
        "name": "單元1", "fields": [{"label": "素材", "value": "影片"}],
        "share": None, "warnings": [], "children": [],
    }
    node.update(overrides)
    return node


def _one_tree_nodes(leaf: dict) -> list:
    return [
        {
            "name": "活動一", "fields": [{"label": "目標", "value": "業績"}],
            "share": None, "warnings": [],
            "children": [
                {
                    "name": "組合1", "fields": [{"label": "受眾", "value": "既有客"}],
                    "share": 1.0, "warnings": [], "children": [leaf],
                }
            ],
        }
    ]


class CopyLengthTest(unittest.TestCase):
    def test_valid_copy_length_is_kept(self):
        body, failure = tree_mod.build_tree(
            _tree_fenced(_one_tree_nodes(_leaf(copy_length="long"))), daily_budget=1000
        )
        self.assertIsNone(failure)
        leaf_node = body["nodes"][0]["children"][0]["children"][0]
        self.assertEqual(leaf_node["copy_length"], "long")

    def test_unknown_value_becomes_short(self):
        body, failure = tree_mod.build_tree(
            _tree_fenced(_one_tree_nodes(_leaf(copy_length="enormous"))), daily_budget=1000
        )
        self.assertIsNone(failure)
        leaf_node = body["nodes"][0]["children"][0]["children"][0]
        self.assertEqual(leaf_node["copy_length"], "short")

    def test_null_becomes_short(self):
        body, failure = tree_mod.build_tree(
            _tree_fenced(_one_tree_nodes(_leaf(copy_length=None))), daily_budget=1000
        )
        self.assertIsNone(failure)
        leaf_node = body["nodes"][0]["children"][0]["children"][0]
        self.assertEqual(leaf_node["copy_length"], "short")

    def test_missing_field_becomes_short(self):
        body, failure = tree_mod.build_tree(
            _tree_fenced(_one_tree_nodes(_leaf())), daily_budget=1000
        )
        self.assertIsNone(failure)
        leaf_node = body["nodes"][0]["children"][0]["children"][0]
        self.assertEqual(leaf_node["copy_length"], "short")

    def test_depth_1_and_2_get_none(self):
        body, failure = tree_mod.build_tree(
            _tree_fenced(_one_tree_nodes(_leaf())), daily_budget=1000
        )
        self.assertIsNone(failure)
        top = body["nodes"][0]
        self.assertIsNone(top["copy_length"])
        self.assertIsNone(top["children"][0]["copy_length"])


if __name__ == "__main__":
    unittest.main()
