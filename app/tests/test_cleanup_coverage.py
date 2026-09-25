"""app/tests/test_cleanup_coverage.py — the brand-delete coverage alarm `app/core/cleanup.py`
has always cited (F31-I09, item 13).

Root cause this guards: every module declares the tables it clears on brand delete
(`cleanup.register(..., brand_tables=...)`), but nothing compared those declarations with the
live schema, so tables added later (`campaign_period`, `channel_entity_map`,
`period_node_membership`, `ads_runtime_event`, `approval`) were never cleared and a brand with
a period could not be deleted at all (FK from its periods to `brand`).

1. Every live table with a `brand_id` column is declared by some registered module, apart from
   `EXEMPT_BRAND_TABLES` (one reason each). That list may only shrink: a new entry means brand
   data that outlives its brand, which is a product decision, not a test edit.
2. Every declared table still exists (a dropped table left in a registry is a stale claim).
3. A brand with a period, channel bindings, period membership, runtime events, an approval
   referenced by an ads change set and a kept `llm_task` deletes in one call; afterwards only
   exempt tables hold its `brand_id`, and the kept `llm_task` no longer points at the period.

Imports only legacy facades: `app.main` (the composition root, so every module's registration
has run in production order), `app.core` and `app.brand_intelligence`.
"""

import unittest

import app.main  # noqa: F401 -- composition root: runs every cleanup.register() in production order
from app.brand_intelligence import repository as bi_repo
from app.core import approval, cleanup, db

# Brand data kept on purpose after the brand is deleted. May only shrink.
EXEMPT_BRAND_TABLES = {
    # AI spend record: the money was spent even if the brand is gone (user ruling, pinned by
    # app/tests/test_orders_core_brand_cleanup.py test_delete_brand_keeps_llm_task).
    "llm_task": "AI 花費紀錄：品牌刪掉，那筆支出仍然發生過",
    # Audit outlives its subject: brand delete itself writes the final audit row.
    "audit_log": "稽核紀錄比被稽核的對象活得久（刪品牌本身也寫一筆）",
}
_EXEMPTION_CEILING = frozenset({"llm_task", "audit_log"})


def _live_brand_tables(conn) -> set:
    rows = conn.execute(
        "SELECT c.table_name FROM information_schema.columns c"
        " JOIN information_schema.tables t"
        "   ON t.table_schema = c.table_schema AND t.table_name = c.table_name"
        " WHERE c.table_schema = current_schema() AND c.column_name = 'brand_id'"
        "   AND t.table_type = 'BASE TABLE'"
    ).fetchall()
    return {r["table_name"] for r in rows}


def _declared_brand_tables() -> set:
    declared = set()
    for tables in cleanup.declared_brand_tables().values():
        declared |= tables
    return declared


class CleanupCoverageTest(unittest.TestCase):
    def setUp(self):
        self.conn = db.current()

    def test_every_live_brand_table_is_cleared_or_exempt(self):
        unclaimed = _live_brand_tables(self.conn) - _declared_brand_tables() - set(EXEMPT_BRAND_TABLES)
        self.assertEqual(
            unclaimed, set(),
            "these tables carry brand_id but no cleanup.register() declares them: deleting a "
            "brand leaves their rows behind (or fails on a foreign key)")

    def test_declared_tables_exist(self):
        stale = _declared_brand_tables() - _live_brand_tables(self.conn)
        self.assertEqual(stale, set(), "registries declare tables that no longer exist")

    def test_exemptions_are_live_undeclared_and_only_shrink(self):
        self.assertLessEqual(set(EXEMPT_BRAND_TABLES), _EXEMPTION_CEILING)
        live = _live_brand_tables(self.conn)
        declared = _declared_brand_tables()
        for table, reason in EXEMPT_BRAND_TABLES.items():
            self.assertTrue(reason)
            self.assertIn(table, live, f"exempt table {table} no longer exists: drop the exemption")
            self.assertNotIn(table, declared, f"{table} is exempt yet a registry clears it")

    def test_approval_is_registered_after_the_ads_rows_that_reference_it(self):
        names = cleanup.registered_names()
        owner = {t: n for n, ts in cleanup.declared_brand_tables().items() for t in ts}
        self.assertLess(names.index(owner["ads_change_set"]), names.index(owner["approval"]))


class BrandDeleteLeavesOnlyExemptRowsTest(unittest.TestCase):
    def setUp(self):
        self.conn = db.current()

    def _seed(self) -> tuple:
        conn, org = self.conn, db.DEV_ORG_ID
        bid = bi_repo.create_brand(conn, name="刪品牌涵蓋率測試品牌", client_name=None,
                                   actor="測試員", org_id=org)["id"]
        bi_repo.update_brand(conn, bid, name="刪品牌涵蓋率測試品牌", client_name=None,
                             status="archived", actor="測試員")
        now = db.now_utc()
        period = db.new_id("cp")
        conn.execute(
            "INSERT INTO campaign_period (id, org_id, brand_id, name, start_date, end_date, currency)"
            " VALUES (%s, %s, %s, '九月檔期', '2026-09-01', '2026-09-30', 'TWD')",
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
        conn.execute(
            "INSERT INTO ads_runtime_event (id, kind, org_id, brand_id) VALUES (%s, 'beat', %s, %s)",
            (db.new_id("are"), org, bid))
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
        # An approval referenced by an ads change set: ads clears the set before core clears it.
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

    def test_brand_with_period_bindings_events_and_approval_deletes_cleanly(self):
        bid, task = self._seed()

        bi_repo.delete_brand(self.conn, bid, actor="測試員")

        leftovers = {}
        for table in sorted(_live_brand_tables(self.conn)):
            n = self.conn.execute(
                f"SELECT COUNT(*) AS n FROM {table} WHERE brand_id = %s", (bid,)).fetchone()["n"]
            if n:
                leftovers[table] = n
        self.assertLessEqual(set(leftovers), set(EXEMPT_BRAND_TABLES), leftovers)
        kept = self.conn.execute(
            "SELECT campaign_period_id FROM llm_task WHERE id = %s", (task,)).fetchone()
        self.assertIsNotNone(kept, "llm_task is kept on brand delete on purpose")
        self.assertIsNone(kept["campaign_period_id"])


if __name__ == "__main__":
    unittest.main()
