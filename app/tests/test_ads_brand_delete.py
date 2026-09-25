"""app/tests/test_ads_brand_delete.py — F31-I09 (item 13): brand delete clears the ads center's
runtime events and the approvals its change sets reference.

Before F31-I09 `ads_runtime_event` was missing from the ads registry (rows outlived the brand and
their FK to the brand blocked the delete), no registry cleared `approval` at all, and an ad's
product FK had no ON DELETE action, so deleting the brand's products first failed on it. Approval is
registered by core after every module (app/main.py), because an ads change set references it
without an ON DELETE action: clearing approvals first would fail on that reference.
"""

import unittest

import app.main  # noqa: F401 -- composition root: every cleanup.register() in production order
from app.brand_intelligence import repository as bi_repo
from app.core import approval, db

# Kept on brand delete on purpose (see app/tests/test_cleanup_coverage.py EXEMPT_BRAND_TABLES).
_KEPT = {"llm_task", "audit_log"}


def _brand_id_tables(conn) -> list:
    rows = conn.execute(
        "SELECT c.table_name FROM information_schema.columns c"
        " JOIN information_schema.tables t"
        "   ON t.table_schema = c.table_schema AND t.table_name = c.table_name"
        " WHERE c.table_schema = current_schema() AND c.column_name = 'brand_id'"
        "   AND t.table_type = 'BASE TABLE' ORDER BY 1"
    ).fetchall()
    return [r["table_name"] for r in rows]


class AdsBrandDeleteTest(unittest.TestCase):
    def setUp(self):
        self.conn = db.current()

    def _seed(self) -> str:
        conn, org = self.conn, db.DEV_ORG_ID
        bid = bi_repo.create_brand(conn, name="有核准變更的待刪品牌", client_name=None,
                                   actor="測試員", org_id=org)["id"]
        bi_repo.update_brand(conn, bid, name="有核准變更的待刪品牌", client_name=None,
                             status="archived", actor="測試員")
        conn.execute(
            "INSERT INTO ads_runtime_event (id, kind, org_id, brand_id)"
            " VALUES (%s, 'beat', %s, %s)", (db.new_id("are"), org, bid))
        approval_id = approval.approve(
            conn, org_id=org, brand_id=bid, scope_type="ads_change_set", scope_ref="set",
            content_hash="h", amount=100, max_daily_amount=100, actor="測試員", commit=False)
        campaign = db.new_id("acp")
        conn.execute(
            "INSERT INTO ads_campaign (id, org_id, brand_id, name, origin)"
            " VALUES (%s, %s, %s, '匯入活動', 'imported')", (campaign, org, bid))
        conn.execute(
            "INSERT INTO ads_change_set (id, org_id, brand_id, campaign_id, operation_id,"
            " request_hash, content_hash, title, month, plan_json, created_by, approval_id)"
            " VALUES (%s, %s, %s, %s, 'op', 'rq', 'ch', '變更', '2026-09', '{}', '測試員', %s)",
            (db.new_id("acs"), org, bid, campaign, approval_id))
        # An ad for one of the brand's products: 品牌智庫 (registered first) deletes the product
        # before 投放中心 deletes the ad, so the ad's product FK must not block
        # (20260927000007_ads_ad_product_fk_set_null.sql).
        product = bi_repo.create_product(conn, bid, name="待刪品牌的商品", actor="測試員")["id"]
        group = db.new_id("adg")
        conn.execute(
            "INSERT INTO ads_delivery_group (id, org_id, brand_id, campaign_id, channel_key, name,"
            " role, daily_budget) VALUES (%s, %s, %s, %s, 'meta', '投放組', 'new', 100)",
            (group, org, bid, campaign))
        conn.execute(
            "INSERT INTO ads_ad (id, org_id, brand_id, campaign_id, group_id, name, product_id)"
            " VALUES (%s, %s, %s, %s, %s, '廣告一', %s)",
            (db.new_id("ad"), org, bid, campaign, group, product))
        conn.commit()
        return bid

    def test_brand_with_runtime_events_approved_change_set_and_product_ad_deletes_cleanly(self):
        bid = self._seed()

        bi_repo.delete_brand(self.conn, bid, actor="測試員")

        leftovers = {}
        for table in _brand_id_tables(self.conn):
            n = self.conn.execute(
                f"SELECT COUNT(*) AS n FROM {table} WHERE brand_id = %s", (bid,)).fetchone()["n"]
            if n:
                leftovers[table] = n
        self.assertLessEqual(set(leftovers), _KEPT, leftovers)


if __name__ == "__main__":
    unittest.main()
