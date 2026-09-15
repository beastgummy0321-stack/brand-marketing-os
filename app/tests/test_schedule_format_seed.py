"""app/tests/test_schedule_format_seed.py — tripwire for ticket F01-T03-I05: the `format`
dimension's `situation` text is printed verbatim into the user-copied 【輸出】 line of an image
prompt (ARCHITECTURE.md §5.7), so it must not carry engineering provenance notes.
"""

import pathlib
import unittest

from app.brand_intelligence import repository as bi_repo
from app.core.db import DEV_ORG_ID, jsonb, new_id
from app.core.db import current as db_current
from app.schedule.repository import _SEED_COORDINATES, ensure_coordinates_seeded

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
        # F07-I13 item 12: every (key, label) of every seeded dimension must still appear in the
        # six-dimensions migration verbatim — catches any other seed label quietly reworded.
        six_dims_sql = (
            pathlib.Path(__file__).resolve().parents[2] / "supabase" / "migrations"
            / "20260904000002_schedule_brand_coordinate_six_dimensions.sql"
        ).read_text(encoding="utf-8")
        for dimension, rows in _SEED_COORDINATES.items():
            for key, _category, label, _situation in rows:
                self.assertIn(f"('{key}', '{label}'", six_dims_sql,
                              f"{dimension}.{key} label drifted from the applied migration")

    def test_disable_flexible_migration_behaviour(self) -> None:
        """F07-I13 item 11: execute the migration's own SQL text against real rows and check its
        effect, not just substrings — catches `SET label`, `OR key`, and a dropped
        `disabled_at IS NULL` guard, none of which the string-only test above can see."""
        conn = db_current()
        org_id = DEV_ORG_ID
        brand_a = bi_repo.create_brand(conn, name="測試品牌A：彈性停用", client_name=None,
                                        actor="測試員", org_id=org_id)["id"]
        brand_b = bi_repo.create_brand(conn, name="測試品牌B：彈性停用", client_name=None,
                                        actor="測試員", org_id=org_id)["id"]
        ensure_coordinates_seeded(conn, org_id, brand_a)
        ensure_coordinates_seeded(conn, org_id, brand_b)

        def _insert_flexible(brand_id: str, disabled_at: str | None) -> None:
            conn.execute(
                "INSERT INTO brand_coordinate (id, org_id, brand_id, dimension, key, label,"
                " category, attributes_json, disabled_at)"
                " VALUES (%s, %s, %s, 'format', 'flexible', '彈性格式', 'Meta 版位', %s, %s)",
                (new_id("crd"), org_id, brand_id, jsonb({}), disabled_at),
            )

        _insert_flexible(brand_a, None)
        _insert_flexible(brand_b, "2026-01-01T00:00:00+00:00")
        conn.commit()

        migration_path = (
            pathlib.Path(__file__).resolve().parents[2] / "supabase" / "migrations"
            / "20260915000001_schedule_brand_coordinate_disable_flexible.sql"
        )
        conn.execute(migration_path.read_text(encoding="utf-8"))
        conn.commit()

        def _row(brand_id: str, key: str) -> dict:
            return dict(conn.execute(
                "SELECT label, disabled_at FROM brand_coordinate"
                " WHERE brand_id = %s AND dimension = 'format' AND key = %s",
                (brand_id, key),
            ).fetchone())

        a_flexible = _row(brand_a, "flexible")
        self.assertIsNotNone(a_flexible["disabled_at"])
        self.assertEqual(a_flexible["label"], "彈性格式")
        for other_key in ("single_image", "carousel", "video"):
            self.assertIsNone(_row(brand_a, other_key)["disabled_at"])

        b_flexible = _row(brand_b, "flexible")
        self.assertEqual(b_flexible["disabled_at"].isoformat(), "2026-01-01T00:00:00+00:00")

    def test_format_specs_have_no_flexible_line(self) -> None:
        """F07-I13 item 2: F07-I03 removed the 彈性格式 line from
        `app/methodology/meta-format-specs.md`; the source link `flexible-ad-format/` stays."""
        specs_path = (
            pathlib.Path(__file__).resolve().parents[2]
            / "app" / "methodology" / "meta-format-specs.md"
        )
        text = specs_path.read_text(encoding="utf-8")
        self.assertNotIn("彈性格式", text)
        self.assertNotIn("`flexible` 座標值", text)


if __name__ == "__main__":
    unittest.main()
