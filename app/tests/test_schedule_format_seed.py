"""app/tests/test_schedule_format_seed.py — tripwire for ticket F01-T03-I05: the `format`
dimension's `situation` text is printed verbatim into the user-copied 【輸出】 line of an image
prompt (ARCHITECTURE.md §5.7), so it must not carry engineering provenance notes.
"""

import pathlib
import unittest

from app.schedule.repository import _SEED_COORDINATES

_MIGRATION_PATH = (
    pathlib.Path(__file__).resolve().parents[2]
    / "supabase"
    / "migrations"
    / "20260911000001_schedule_brand_coordinate_format_situation.sql"
)


class TestScheduleFormatSeed(unittest.TestCase):
    def setUp(self) -> None:
        self.situations = {
            key: situation for key, _category, _label, situation in _SEED_COORDINATES["format"]
        }

    def test_single_image_situation_has_no_provenance(self) -> None:
        self.assertEqual(self.situations["single_image"], "4:5，1080×1350")

    def test_flexible_is_not_a_seed(self) -> None:
        """F07-I03：Meta 已無彈性格式，排程座標種子不再有 `flexible` 這把鍵。"""
        self.assertNotIn("flexible", self.situations)

    def test_no_format_situation_leaks_engineering_notes(self) -> None:
        for situation in self.situations.values():
            self.assertNotIn("asset_feed_spec", situation)
            self.assertNotIn("查證", situation)

    def test_migration_matches_seed(self) -> None:
        sql = _MIGRATION_PATH.read_text(encoding="utf-8")
        self.assertIn("'4:5，1080×1350'", sql)

    def test_disable_flexible_migration_disables_not_relabels(self) -> None:
        """F07-I03：新遷移只停用 `flexible`，不改它的 `label`（已套用的舊遷移不能改）。"""
        migration_path = (
            pathlib.Path(__file__).resolve().parents[2]
            / "supabase"
            / "migrations"
            / "20260915000001_schedule_brand_coordinate_disable_flexible.sql"
        )
        sql = migration_path.read_text(encoding="utf-8")
        self.assertIn("dimension = 'format'", sql)
        self.assertIn("key = 'flexible'", sql)
        self.assertIn("disabled_at = now()", sql)
        self.assertNotIn("SET label", sql)

    def test_everyday_seeds_untouched(self) -> None:
        """F07-I03 只動 `flexible`；其他座標的日常字眼原封不動。"""
        audience = {
            key: label for key, _category, label, _situation in _SEED_COORDINATES["audience"]
        }
        offer = {
            key: label for key, _category, label, _situation in _SEED_COORDINATES["offer"]
        }
        self.assertEqual(audience["warm_engaged"], "互動過・沒買")
        self.assertEqual(offer["free_shipping"], "免運")


if __name__ == "__main__":
    unittest.main()
