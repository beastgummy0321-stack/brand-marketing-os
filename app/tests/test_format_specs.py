"""app/tests/test_format_specs.py — 素材工作檯 G1-A：平台規格表常數檔守門測試。

純資料表，不碰 DB，不用 app.main。目標維度鍵集合直接跟 app/ads/plan.py 的
OBJECTIVE_TEXT 比對（不得複製一份自己抄錯），見票 G1-A 規格。
"""

import unittest

from app.ads.plan import OBJECTIVE_TEXT
from app.creative.format_specs import FORMAT_SPECS

OBJECTIVES = set(OBJECTIVE_TEXT.keys())


class FormatSpecsTests(unittest.TestCase):
    def test_three_formats_present_and_catalog_excluded(self):
        self.assertEqual(set(FORMAT_SPECS.keys()), {"single_image", "carousel", "video"})
        self.assertNotIn("catalog", FORMAT_SPECS)

    def test_every_format_has_ratio_pixels_fields_and_sources(self):
        for name, spec in FORMAT_SPECS.items():
            self.assertIn("ratio", spec, name)
            self.assertIn("pixels", spec, name)
            self.assertIn("fields", spec, name)
            for field_name, field in spec["fields"].items():
                self.assertIn("count", field, f"{name}.{field_name}")
                if field.get("char_budget") is not None:
                    self.assertIsInstance(field["char_budget"], int, f"{name}.{field_name}")
            sources = spec["sources"]
            self.assertTrue(sources)
            for source in sources:
                self.assertIn("url", source)
                self.assertIn("checked_on", source)

    def test_objective_dimension_covers_all_five_objectives_and_matches_plan(self):
        for name, spec in FORMAT_SPECS.items():
            self.assertEqual(
                set(spec["objectives"].keys()), OBJECTIVES, name
            )

    def test_single_image_ratio_and_pixels(self):
        spec = FORMAT_SPECS["single_image"]
        self.assertEqual(spec["ratio"], "4:5")
        self.assertEqual(spec["pixels"], (1080, 1350))

    def test_single_image_field_counts_and_budgets(self):
        fields = FORMAT_SPECS["single_image"]["fields"]
        self.assertEqual(fields["image_prompt"]["count"], 10)
        self.assertIsNone(fields["image_prompt"].get("char_budget"))
        self.assertEqual(fields["body"]["count"], 5)
        self.assertEqual(fields["body"]["char_budget"], 125)
        self.assertEqual(fields["title"]["count"], 5)
        self.assertEqual(fields["title"]["char_budget"], 27)
        self.assertEqual(fields["description"]["count"], 5)
        self.assertEqual(fields["description"]["char_budget"], 30)

    def test_single_image_sales_media_cap_is_10_others_are_1(self):
        objectives = FORMAT_SPECS["single_image"]["objectives"]
        self.assertEqual(objectives["sales"]["media_cap_per_theme"], 10)
        for key in OBJECTIVES - {"sales"}:
            self.assertEqual(objectives[key]["media_cap_per_theme"], 1, key)

    def test_carousel_ratio_pixels_and_card_bounds(self):
        spec = FORMAT_SPECS["carousel"]
        self.assertEqual(spec["ratio"], "1:1")
        self.assertEqual(spec["pixels"], (1080, 1080))
        self.assertEqual(spec["card_count_min"], 2)
        self.assertEqual(spec["card_count_max"], 10)

    def test_carousel_field_budgets(self):
        fields = FORMAT_SPECS["carousel"]["fields"]
        self.assertEqual(fields["card_title"]["char_budget"], 45)
        self.assertEqual(fields["body"]["char_budget"], 80)
        self.assertEqual(fields["body"]["count"], 5)

    def test_video_script_and_hook_pool_counts(self):
        fields = FORMAT_SPECS["video"]["fields"]
        self.assertEqual(fields["script"]["count"], 3)
        self.assertEqual(fields["hook_pool"]["count"], 10)

    def test_video_ratio_pixels_and_duration(self):
        spec = FORMAT_SPECS["video"]
        self.assertEqual(spec["ratio"], "9:16")
        self.assertEqual(spec["pixels"], (1080, 1920))
        self.assertEqual(spec["duration_seconds_default"], 30)


if __name__ == "__main__":
    unittest.main()
