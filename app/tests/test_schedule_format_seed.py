"""app/tests/test_schedule_format_seed.py — tripwire for ticket F01-T03-I05: the `format`
dimension's `situation` text is printed verbatim into the user-copied 【輸出】 line of an image
prompt (ARCHITECTURE.md §5.7), so it must not carry engineering provenance notes.
"""

import pathlib
import unittest

from fastapi.testclient import TestClient

import app.main as main
from app.brand_intelligence import repository as bi_repo
from app.core.db import DEV_ORG_ID, jsonb, new_id
from app.core.db import current as db_current
from app.schedule import repository as schedule_repo
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

    def test_offer_default_off_migration_text(self) -> None:
        """F38-I05 (RC-C): the one-off migration switches promo offers off, never `none`."""
        sql = (
            pathlib.Path(__file__).resolve().parents[2] / "supabase" / "migrations"
            / "20260929000003_schedule_offer_default_off.sql"
        ).read_text(encoding="utf-8")
        self.assertIn("disabled_at", sql)
        self.assertIn("disabled_at = now()", sql)
        self.assertIn("dimension = 'offer'", sql)
        self.assertIn("key <> 'none'", sql)
        self.assertIn("disabled_at IS NULL", sql)

    def test_fresh_brand_promo_offers_seeded_disabled(self) -> None:
        """F38-I05 (RC-C): a new brand gets only `offer/none` enabled; the six promo offers are
        seeded disabled. Proof stays enabled — it is gated by evidence facts, not by seed."""
        conn = db_current()
        org_id = DEV_ORG_ID
        brand_id = bi_repo.create_brand(conn, name="測試品牌：優惠預設關", client_name=None,
                                         actor="測試員", org_id=org_id)["id"]
        ensure_coordinates_seeded(conn, org_id, brand_id)
        rows = conn.execute(
            "SELECT dimension, key, disabled_at FROM brand_coordinate"
            " WHERE brand_id = %s AND dimension IN ('offer', 'proof')",
            (brand_id,),
        ).fetchall()
        offer = {r["key"]: r["disabled_at"] for r in rows if r["dimension"] == "offer"}
        proof = {r["key"]: r["disabled_at"] for r in rows if r["dimension"] == "proof"}

        self.assertIsNone(offer["none"])
        promo = {"discount", "bundle", "free_shipping", "trial_sample", "guarantee",
                 "limited_time"}
        self.assertEqual(set(offer) - {"none"}, promo)
        for key in promo:
            self.assertIsNotNone(offer[key], f"offer/{key} should be seeded disabled")
        self.assertEqual(len(proof), 7)
        for key, disabled_at in proof.items():
            self.assertIsNone(disabled_at, f"proof/{key} must stay enabled")

        # every other seeded dimension stays enabled
        others = conn.execute(
            "SELECT count(*) AS n FROM brand_coordinate WHERE brand_id = %s"
            " AND dimension NOT IN ('offer') AND disabled_at IS NOT NULL",
            (brand_id,),
        ).fetchone()["n"]
        self.assertEqual(others, 0)

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


class RetiredCoordinateApiTest(unittest.TestCase):
    """F07-I15: `format/flexible` is disabled-not-deleted (Decision 33), but the screen that
    品牌智庫 and 投放中心 both read must act as if the row does not exist — never listed, never
    re-enabled or re-disabled through the route."""

    def setUp(self) -> None:
        self.client = TestClient(main.app)
        self.conn = db_current()
        self.org_id = DEV_ORG_ID
        self.brand_a = bi_repo.create_brand(
            self.conn, name="測試品牌A：彈性隱藏", client_name=None,
            actor="測試員", org_id=self.org_id,
        )["id"]
        self.brand_b = bi_repo.create_brand(
            self.conn, name="測試品牌B：彈性隱藏", client_name=None,
            actor="測試員", org_id=self.org_id,
        )["id"]
        ensure_coordinates_seeded(self.conn, self.org_id, self.brand_a)
        ensure_coordinates_seeded(self.conn, self.org_id, self.brand_b)
        self.flexible_a = self._insert_flexible(self.brand_a, disabled=True)
        self.flexible_b = self._insert_flexible(self.brand_b, disabled=False)
        self.conn.commit()

    def _insert_flexible(self, brand_id: str, *, disabled: bool) -> str:
        coordinate_id = new_id("crd")
        self.conn.execute(
            "INSERT INTO brand_coordinate (id, org_id, brand_id, dimension, key, label,"
            " category, attributes_json, disabled_at)"
            " VALUES (%s, %s, %s, 'format', 'flexible', '彈性格式', 'Meta 版位', %s, %s)",
            (coordinate_id, self.org_id, brand_id, jsonb({}),
             "2026-01-01T00:00:00+00:00" if disabled else None),
        )
        return coordinate_id

    def test_list_route_never_shows_flexible(self) -> None:
        for brand_id in (self.brand_a, self.brand_b):
            resp = self.client.get(f"/api/schedule/brands/{brand_id}/coordinates")
            self.assertEqual(resp.status_code, 200, resp.text)
            keys = {(c["dimension"], c["key"]) for c in resp.json()["coordinates"]}
            self.assertNotIn(("format", "flexible"), keys)
            labels = {(c["dimension"], c["key"]) for c in resp.json()["coordinates"]
                      if c["dimension"] == "format"}
            self.assertEqual(labels, {("format", "single_image"), ("format", "carousel"),
                                       ("format", "video")})

    def test_disable_route_404s_and_never_writes(self) -> None:
        before_a = self._read_disabled_at(self.brand_a, self.flexible_a)
        resp_a = self.client.post(
            f"/api/schedule/brands/{self.brand_a}/coordinates/{self.flexible_a}/disable",
            json={"disabled": False},
        )
        self.assertEqual(resp_a.status_code, 404)
        self.assertEqual(resp_a.json()["error"]["code"], "coordinate_not_found")
        self.assertEqual(self._read_disabled_at(self.brand_a, self.flexible_a), before_a)

        resp_b = self.client.post(
            f"/api/schedule/brands/{self.brand_b}/coordinates/{self.flexible_b}/disable",
            json={"disabled": True},
        )
        self.assertEqual(resp_b.status_code, 404)
        self.assertIsNone(self._read_disabled_at(self.brand_b, self.flexible_b))

    def test_repository_default_still_includes_retired_row(self) -> None:
        """internal readers (`binding.py`, `performance.py`, `jobs.py`, `history.py`) call
        `list_coordinates()` with the default and must keep resolving old tagged data."""
        default_rows = schedule_repo.list_coordinates(self.conn, self.org_id, self.brand_a)
        default_keys = {(c["dimension"], c["key"]) for c in default_rows}
        self.assertIn(("format", "flexible"), default_keys)
        hidden_keys = {(c["dimension"], c["key"])
                       for c in schedule_repo.list_coordinates(
                           self.conn, self.org_id, self.brand_a, include_retired=False)}
        self.assertNotIn(("format", "flexible"), hidden_keys)

    def test_guard_is_scoped_to_the_retired_pair(self) -> None:
        """a non-retired coordinate on the same brand can still be disabled and re-enabled
        through the route — the guard must not block `format` or `flexible` in general."""
        coords = self.client.get(
            f"/api/schedule/brands/{self.brand_a}/coordinates"
        ).json()["coordinates"]
        single_image = next(c for c in coords
                             if c["dimension"] == "format" and c["key"] == "single_image")
        resp_off = self.client.post(
            f"/api/schedule/brands/{self.brand_a}/coordinates/{single_image['id']}/disable",
            json={"disabled": True},
        )
        self.assertEqual(resp_off.status_code, 200, resp_off.text)
        self.assertIsNotNone(resp_off.json()["disabled_at"])
        resp_on = self.client.post(
            f"/api/schedule/brands/{self.brand_a}/coordinates/{single_image['id']}/disable",
            json={"disabled": False},
        )
        self.assertEqual(resp_on.status_code, 200, resp_on.text)
        self.assertIsNone(resp_on.json()["disabled_at"])

    def _read_disabled_at(self, brand_id: str, coordinate_id: str):
        return self.conn.execute(
            "SELECT disabled_at FROM brand_coordinate WHERE id = %s AND brand_id = %s",
            (coordinate_id, brand_id),
        ).fetchone()["disabled_at"]


if __name__ == "__main__":
    unittest.main()
