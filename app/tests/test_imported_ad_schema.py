"""app/tests/test_imported_ad_schema.py — ticket past-ads 01
(docs/issues/past-ads/01-schema-imported-ad-and-advertising-history.md), done-check 3: the
composite FK `(ad_channel_id, org_id) REFERENCES ad_channel(id, org_id)` on `imported_ad` is
attacked, not merely declared. Shaped after
`app/tests/test_org_isolation_all_tables.py::CampaignPeriodCompositeFKTenantIsolationTest
.test_period_node_membership_cross_org_period_reference_is_rejected` -- the NOT NULL class,
since `imported_ad.ad_channel_id` cannot be nulled away either.

Proven red once by hand (2026-09-08): with the composite FK replaced by a single-column
`FOREIGN KEY (ad_channel_id) REFERENCES ad_channel(id)` in the migration (and a fresh
`supabase db reset`), the cross-org insert in
`test_cross_org_channel_reference_is_rejected` below succeeded instead of raising -- i.e.
this test failed. The composite constraint was then restored (matching the live migration)
and the test passed again.
"""

import unittest

import psycopg

from app.core import cleanup, db
from app.schedule import repository as schedule_repo


class ImportedAdCompositeFKTenantIsolationTest(unittest.TestCase):
    def setUp(self):
        self.conn = db.current()

    def _make_org(self, suffix: str) -> str:
        org_id = f"org_iad_fk_test_{suffix}"
        self.conn.execute(
            "INSERT INTO organisation (id, name, kind) VALUES (%s, %s, 'personal')"
            " ON CONFLICT (id) DO NOTHING",
            (org_id, org_id),
        )
        self.conn.commit()
        return org_id

    def _make_brand(self, org_id: str) -> str:
        brand_id = db.new_id("brd")
        self.conn.execute(
            "INSERT INTO brand (id, org_id, name, status, knowledge_version, created_at,"
            " updated_at) VALUES (%s, %s, %s, 'active', 1, now(), now())",
            (brand_id, org_id, f"brand for {org_id}"),
        )
        self.conn.commit()
        return brand_id

    def _make_channel(self, org_id: str) -> str:
        channel_id = db.new_id("adch")
        self.conn.execute(
            "INSERT INTO ad_channel (id, org_id, channel_key) VALUES (%s, %s, 'meta')",
            (channel_id, org_id),
        )
        self.conn.commit()
        return channel_id

    def test_cross_org_channel_reference_is_rejected(self):
        """Org B's brand tagging an imported ad against org A's channel must be refused by
        the database; the same row naming org B's own channel must still insert (the pair
        the ticket's composite-FK reasoning is measured against)."""
        org_a, org_b = self._make_org("a"), self._make_org("b")
        brand_b = self._make_brand(org_b)
        channel_a = self._make_channel(org_a)
        channel_b = self._make_channel(org_b)

        with self.assertRaises(psycopg.errors.ForeignKeyViolation):
            self.conn.execute(
                "INSERT INTO imported_ad (id, org_id, brand_id, ad_channel_id, external_id,"
                " external_name) VALUES (%s, %s, %s, %s, 'ext-cross-org', 'cross-org ad')",
                (db.new_id("iad"), org_b, brand_b, channel_a),
            )
        self.conn.rollback()

        self.conn.execute(
            "INSERT INTO imported_ad (id, org_id, brand_id, ad_channel_id, external_id,"
            " external_name) VALUES (%s, %s, %s, %s, 'ext-same-org', 'same-org ad')",
            (db.new_id("iad"), org_b, brand_b, channel_b),
        )
        self.conn.commit()


class ImportedAdBrandDeleteCleanupTest(unittest.TestCase):
    """Ticket past-ads 01, done-check 4 as amended (review round 1, see the ticket's
    `## Blocked` section): brand delete wipes `imported_ad` through
    `app.core.cleanup.delete_all()`, the same path `app.brand_intelligence.repository
    .delete_brand()` runs (`app/tests/test_cleanup_registry.py:62-67` shows the transaction
    protocol -- `delete_all()` only issues DELETEs and never commits, so this test reads its
    own uncommitted writes back on the same connection). `app.schedule.repository` registers
    its cleanup entry ("創意座標與素材候選", covering `imported_ad`) at import time, so it is
    imported below rather than relied upon to already be loaded by another test module.

    `test_brand_delete.py` is deliberately not touched -- the wipe is proven here instead,
    per the review's ruling.
    """

    def setUp(self):
        self.conn = db.current()

    def _make_org(self, suffix: str) -> str:
        org_id = f"org_iad_wipe_test_{suffix}"
        self.conn.execute(
            "INSERT INTO organisation (id, name, kind) VALUES (%s, %s, 'personal')"
            " ON CONFLICT (id) DO NOTHING",
            (org_id, org_id),
        )
        self.conn.commit()
        return org_id

    def _make_brand(self, org_id: str, suffix: str) -> str:
        brand_id = db.new_id("brd")
        self.conn.execute(
            "INSERT INTO brand (id, org_id, name, status, knowledge_version, created_at,"
            " updated_at) VALUES (%s, %s, %s, 'active', 1, now(), now())",
            (brand_id, org_id, f"brand {suffix} for {org_id}"),
        )
        self.conn.commit()
        return brand_id

    def test_delete_all_wipes_only_the_deleted_brands_imported_ad_rows(self):
        org_id = self._make_org("wipe")
        brand_deleted = self._make_brand(org_id, "deleted")
        brand_kept = self._make_brand(org_id, "kept")
        channel_id = schedule_repo.ensure_meta_channel(self.conn, org_id)
        self.conn.execute(
            "INSERT INTO imported_ad (id, org_id, brand_id, ad_channel_id, external_id,"
            " external_name) VALUES (%s, %s, %s, %s, 'ext-deleted-brand', 'deleted-brand ad')",
            (db.new_id("iad"), org_id, brand_deleted, channel_id),
        )
        self.conn.execute(
            "INSERT INTO imported_ad (id, org_id, brand_id, ad_channel_id, external_id,"
            " external_name) VALUES (%s, %s, %s, %s, 'ext-kept-brand', 'kept-brand ad')",
            (db.new_id("iad"), org_id, brand_kept, channel_id),
        )
        self.conn.commit()

        counts = cleanup.delete_all(self.conn, brand_deleted)

        self.assertEqual(counts["舊廣告"], 1)
        self.assertEqual(
            self.conn.execute(
                "SELECT COUNT(*) FROM imported_ad WHERE brand_id = %s", (brand_deleted,)
            ).fetchone()["count"], 0)
        self.assertEqual(
            self.conn.execute(
                "SELECT COUNT(*) FROM imported_ad WHERE brand_id = %s", (brand_kept,)
            ).fetchone()["count"], 1)


if __name__ == "__main__":
    unittest.main()
