"""app/tests/test_quick_generate_plan.py — 快速生成欄位子集常數與純函式守門
（票 01-quick-generate-endpoint）。

純資料表 + 純函數，不碰 DB，不用 app.main。比照 app/tests/test_format_specs.py 風格。
"""

import unittest

from app.creative.format_specs import FORMAT_SPECS, QUICK_GENERATE_SCOPES
from app.creative.theme_engine import build_quick_generate_plan


class QuickGenerateScopesDataTest(unittest.TestCase):
    def test_four_scopes_present(self):
        self.assertEqual(set(QUICK_GENERATE_SCOPES.keys()), {"post", "video", "image", "script"})

    def test_every_scope_field_exists_in_its_base_format(self):
        for scope, spec in QUICK_GENERATE_SCOPES.items():
            self.assertIn(spec["base_format"], FORMAT_SPECS, scope)
            for field in spec["fields"]:
                self.assertIn(field, FORMAT_SPECS[spec["base_format"]]["fields"],
                              f"{scope}.{field}")

    def test_no_scope_declares_title_or_description(self):
        for scope, spec in QUICK_GENERATE_SCOPES.items():
            self.assertNotIn("title", spec["fields"], scope)
            self.assertNotIn("description", spec["fields"], scope)


class BuildQuickGeneratePlanTest(unittest.TestCase):
    def test_post_is_image_prompt_and_body_only(self):
        plan = build_quick_generate_plan("post")
        self.assertEqual(set(plan.keys()), {"image_prompt", "body"})
        self.assertEqual(plan["image_prompt"]["count"], 10)
        self.assertIsNone(plan["image_prompt"]["char_budget"])
        self.assertEqual(plan["body"]["count"], 5)
        self.assertEqual(plan["body"]["char_budget"], 125)

    def test_video_is_hook_pool_script_and_body(self):
        plan = build_quick_generate_plan("video")
        self.assertEqual(set(plan.keys()), {"hook_pool", "script", "body"})
        self.assertEqual(plan["hook_pool"]["count"], 10)
        self.assertEqual(plan["script"]["count"], 3)
        self.assertEqual(plan["body"]["count"], 5)

    def test_image_is_image_prompt_only(self):
        plan = build_quick_generate_plan("image")
        self.assertEqual(set(plan.keys()), {"image_prompt"})
        self.assertEqual(plan["image_prompt"]["count"], 10)

    def test_script_is_hook_pool_and_script_only(self):
        plan = build_quick_generate_plan("script")
        self.assertEqual(set(plan.keys()), {"hook_pool", "script"})
        self.assertEqual(plan["hook_pool"]["count"], 10)
        self.assertEqual(plan["script"]["count"], 3)

    def test_no_scope_ever_returns_title_or_description(self):
        for scope in QUICK_GENERATE_SCOPES:
            plan = build_quick_generate_plan(scope)
            self.assertNotIn("title", plan, scope)
            self.assertNotIn("description", plan, scope)

    def test_unknown_scope_raises_value_error(self):
        with self.assertRaises(ValueError):
            build_quick_generate_plan("nonsense")


if __name__ == "__main__":
    unittest.main()
