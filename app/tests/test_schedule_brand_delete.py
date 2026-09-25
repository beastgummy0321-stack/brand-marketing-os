"""app/tests/test_schedule_brand_delete.py — F31-I09 (item 13): a brand with periods can be deleted.

Before F31-I09 no registry cleared the schedule module's periods, channel bindings or period node
membership, so deleting any brand that had a period failed on the period's foreign key to the
brand. The kept AI-spend rows (`llm_task`, kept on brand delete on purpose) also pointed at the
period with a blocking foreign key.

The brand here has a period, a channel binding, a node membership, and rows of other modules
that point at the period (a core interrupt, an orders channel_revenue row, a kept llm_task). One
`delete_brand` call succeeds; afterwards only the kept tables hold its brand_id, and the kept
llm_task no longer points at the period.
"""

import unittest

import app.main  # noqa: F401 -- composition root: every cleanup.register() in production order
from app.brand_intelligence import repository as bi_repo
from app.core import db

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


class ScheduleBrandDeleteTest(unittest.TestCase):
    def setUp(self):
        self.conn = db.current()

    def _seed(self) -> tuple:
        conn, org = self.conn, db.DEV_ORG_ID
        bid = bi_repo.create_brand(conn, name="有檔期的待刪品牌", client_name=None,
                                   actor="測試員", org_id=org)["id"]
        bi_repo.update_brand(conn, bid, name="有檔期的待刪品牌", client_name=None,
                             status="archived", actor="測試員")
        now = db.now_utc()
        period = db.new_id("cp")
        conn.execute(
            "INSERT INTO campaign_period (id, org_id, brand_id, name, start_date, end_date,"
            " currency) VALUES (%s, %s, %s, '九月檔期', '2026-09-01', '2026-09-30', 'TWD')",
            (period, org, bid))
        conn.execute(
            "INSERT INTO ad_channel (id, org_id, channel_key) VALUES (%s, %s, 'meta')"
            " ON CONFLICT (org_id, channel_key) DO NOTHING", (db.new_id("chn"), org))
        channel = conn.execute(
            "SELECT id FROM ad_channel WHERE org_id = %s AND channel_key = 'meta'", (org,)
        ).fetchone()["id"]
        conn.execute(
            "INSERT INTO channel_entity_map (id, org_id, brand_id, channel_id, node_key,"
            " node_name_at_bind, external_id) VALUES (%s, %s, %s, %s, '1', '節點一', 'ext_1')",
            (db.new_id("cem"), org, bid, channel))
        conn.execute(
            "INSERT INTO period_node_membership (id, org_id, brand_id, campaign_period_id,"
            " node_key, from_date, channel_id) VALUES (%s, %s, %s, %s, '1', '2026-09-01', %s)",
            (db.new_id("pnm"), org, bid, period, channel))
        # Rows of other modules that point at the period: their owners clear them first.
        conn.execute(
            "INSERT INTO interrupt (id, org_id, brand_id, campaign_period_id, dedupe_key,"
            " category, severity, message, status, created_at)"
            " VALUES (%s, %s, %s, %s, %s, 'test', 'informational', '測試', 'open', %s)",
            (db.new_id("itr"), org, bid, period, db.new_id("dk"), now))
        conn.execute(
            "INSERT INTO channel_revenue (id, org_id, brand_id, channel, entry_date, revenue,"
            " source, currency, campaign_period_id)"
            " VALUES (%s, %s, %s, 'physical_store', '2026-09-05', 100, 'manual', 'TWD', %s)",
            (db.new_id("chr"), org, bid, period))
        task = db.new_id("llm")
        conn.execute(
            "INSERT INTO llm_task (id, org_id, brand_id, campaign_period_id, task_type,"
            " context_scope_json, input_context_ids_json, input_context_hash,"
            " knowledge_item_ids_json, brand_version, prompt_template_id,"
            " prompt_template_version, provider, model, status, attempt_no, started_at)"
            " VALUES (%s, %s, %s, %s, 'schedule_plan', '{}', '[]', '', '[]', 1, 'p', 'v1',"
            " 'seed', 'seed', 'succeeded', 1, %s)",
            (task, org, bid, period, now))
        conn.commit()
        return bid, task

    def test_brand_with_period_bindings_and_kept_llm_task_deletes_cleanly(self):
        bid, task = self._seed()

        bi_repo.delete_brand(self.conn, bid, actor="測試員")

        leftovers = {}
        for table in _brand_id_tables(self.conn):
            n = self.conn.execute(
                f"SELECT COUNT(*) AS n FROM {table} WHERE brand_id = %s", (bid,)).fetchone()["n"]
            if n:
                leftovers[table] = n
        self.assertLessEqual(set(leftovers), _KEPT, leftovers)
        kept = self.conn.execute(
            "SELECT campaign_period_id FROM llm_task WHERE id = %s", (task,)).fetchone()
        self.assertIsNotNone(kept, "llm_task is kept on brand delete on purpose")
        self.assertIsNone(kept["campaign_period_id"])


if __name__ == "__main__":
    unittest.main()
