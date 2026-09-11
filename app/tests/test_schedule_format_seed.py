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

    def test_flexible_situation_has_no_provenance(self) -> None:
        self.assertEqual(self.situations["flexible"], "1～10 張同座標圖")

    def test_no_format_situation_leaks_engineering_notes(self) -> None:
        for situation in self.situations.values():
            self.assertNotIn("asset_feed_spec", situation)
            self.assertNotIn("查證", situation)

    def test_migration_matches_seed(self) -> None:
        sql = _MIGRATION_PATH.read_text(encoding="utf-8")
        self.assertIn("'4:5，1080×1350'", sql)
        self.assertIn("'1～10 張同座標圖'", sql)


if __name__ == "__main__":
    unittest.main()
