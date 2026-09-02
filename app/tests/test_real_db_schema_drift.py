"""app/tests/test_real_db_schema_drift.py — 真實 Postgres 跟全新 migrate 出來的 schema 差在哪。

02-4 前身（SQLite 版）：比對「一路用了很久的 data/app.db」跟「全新 migrate 出來的暫存
DB」，抓「所有其他測試都看不到的死角」——舊資料庫可能因為手動改過、或某次 migration
沒補齊，跟乾淨安裝長得不一樣。

ADR 0027 起，「乾淨安裝」的定義變了：不再是跑 `MODULE_MIGRATIONS` 這份 Python 清單
（`app.tools.real_db_probe` 依賴它，02-3a 已隨 SQLite migration runner 一起退場），
改成 `supabase/migrations/*.sql` 由 Supabase CLI 管。死角本身還在：本機這顆 Supabase
Postgres（`supabase start` 開的那顆）的 `public` schema 是「一路 `supabase db reset`
疊上來的」，理論上該跟這幾個 migration 檔重放出來的結果一樣，但沒有測試釘住這件事。

這裡拿 `public` schema（本機真實資料庫，開發者可能手動戳過、也可能漏跑某次
`supabase db reset`）跟這個測試模組自己的 schema（conftest.py 的 `_module_schema`
fixture 剛用同一批 migration 檔全新灌出來的）比對表／欄位清單——兩邊都在同一顆
Postgres 裡，同一條連線查兩次 information_schema 即可，不需要另外接一顆資料庫、
也不需要 `app.tools.real_db_probe` 那樣的獨立探針模組（該檔已刪，重建它會是本票
禁止的非測試 .py 異動）。

沒跑過 `supabase db reset` 的機器（`public` schema 是空的）——跳過，不擋別人跑測試。
"""

import unittest

import psycopg

from app.core import db

# 已知且已確認過的差異。每一條都要寫明「為什麼可以留著」。目前沒有任何一條：
# public schema 跟 baseline migration 重放結果一致（02-2/02-3 都是靠
# `supabase db reset` 建出本機這顆）。冒出新差異就變紅，逼人當場看一眼那是什麼。
KNOWN_SCHEMA_DRIFT: set = set()


class RealDbSchemaDriftTest(unittest.TestCase):
    def setUp(self):
        self.conn = db.current()
        self.public_tables = self._tables("'public'")
        if not self.public_tables:
            self.skipTest("本機 public schema 是空的（沒跑過 supabase db reset），跳過")
        self.diffs = self._compute_diffs()

    def _tables(self, schema_expr: str) -> set:
        """`schema_expr` 是這個檔案內寫死的常數（`'public'` 或 `current_schema()`），
        不是外部輸入，直接嵌進 SQL 不是注入風險。"""
        rows = self.conn.execute(
            "SELECT table_name FROM information_schema.tables"
            f" WHERE table_schema = {schema_expr} AND table_type = 'BASE TABLE'"
        )
        return {r["table_name"] for r in rows}

    def _columns(self, schema_expr: str, table: str) -> dict:
        rows = self.conn.execute(
            "SELECT column_name, data_type, is_nullable FROM information_schema.columns"
            f" WHERE table_schema = {schema_expr} AND table_name = %s", (table,)
        )
        return {r["column_name"]: (r["data_type"], r["is_nullable"]) for r in rows}

    def _compute_diffs(self) -> set:
        fresh_tables = self._tables("current_schema()")
        diffs = set()
        for t in fresh_tables - self.public_tables:
            diffs.add(f"{t}：只有全新 migration 出來的 schema 有這張表"
                      "（本機 public 沒有——是不是漏跑一次 supabase db reset？）")
        for t in self.public_tables - fresh_tables:
            diffs.add(f"{t}：只有本機真實 public schema 有這張表（全新 migration 沒有）")

        for t in sorted(fresh_tables & self.public_tables):
            fresh_cols = self._columns("current_schema()", t)
            real_cols = self._columns("'public'", t)
            for col, sig in fresh_cols.items():
                if col not in real_cols:
                    diffs.add(f"{t}.{col}：只有全新 migration 出來的 schema 有這欄")
                elif real_cols[col] != sig:
                    diffs.add(f"{t}.{col}：型別／nullable 不一樣 —— "
                              f"public={real_cols[col]}，fresh={sig}")
            for col in real_cols:
                if col not in fresh_cols:
                    diffs.add(f"{t}.{col}：只有本機真實 public schema 有這欄")
        return diffs

    def test_no_undocumented_drift(self):
        """冒出沒被記錄過的 schema 差異 -> 這裡會叫。"""
        new = self.diffs - KNOWN_SCHEMA_DRIFT
        self.assertEqual(
            new, set(),
            "public schema 跟全新 migration 出來的 schema 有沒被記錄過的差異。每一條都是"
            "所有其他測試都看不到的死角，先確認會不會影響刪除順序或外鍵，再加進"
            "KNOWN_SCHEMA_DRIFT 並寫明理由：\n" + "\n".join(f"  - {d}" for d in sorted(new)))

    def test_known_drift_is_not_stale(self):
        """記錄過的差異其實已經消失了（例如補齊了）-> 也要叫，免得清單腐化。"""
        gone = KNOWN_SCHEMA_DRIFT - self.diffs
        self.assertEqual(
            gone, set(),
            "以下差異已經不存在了，把它們從 KNOWN_SCHEMA_DRIFT 刪掉：\n"
            + "\n".join(f"  - {d}" for d in sorted(gone)))


class RowLevelSecurityGateTest(unittest.TestCase):
    """Gate D (ticket 02-5, ADR 0027 decision 9): RLS enabled on every table, and policies
    scoped to role `authenticated` — which `anon` is not (docs/issues/r1-rls-tracer/ticket.md).

    Backend connects as `postgres` (bypasses RLS). RLS closes off `anon` entirely; `authenticated`
    gets only what a policy grants it — as of r1-rls-tracer that is `brand`, scoped by the
    `app.org_id` GUC (app/tests/test_rls_tenant_policy.py). Two checks: (1) every base table in
    this module's schema has `relrowsecurity = true`; (2) on the real `public` schema, `SET ROLE
    anon` sees zero rows of `organisation` while postgres sees the seeded `org_dev` — a live
    proof, not a flag check.
    """

    def setUp(self):
        self.conn = db.current()

    def test_every_table_has_rls_enabled(self):
        rows = self.conn.execute(
            "SELECT c.relname FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace"
            " WHERE n.nspname = current_schema() AND c.relkind = 'r' AND NOT c.relrowsecurity"
            " ORDER BY 1"
        )
        missing = [r["relname"] for r in rows]
        self.assertEqual(missing, [], f"tables without RLS: {missing}")

    def test_anon_sees_nothing_in_public(self):
        has_public = self.conn.execute(
            "SELECT 1 FROM information_schema.tables WHERE table_schema='public' AND table_name='organisation'"
        ).fetchone()
        if not has_public:
            self.skipTest("本機 public schema 是空的（沒跑過 supabase db reset），跳過")
        as_postgres = self.conn.execute("SELECT count(*) AS n FROM public.organisation").fetchone()["n"]
        self.assertGreaterEqual(as_postgres, 1, "seed.sql should have inserted org_dev into public")
        self.conn.execute("SET ROLE anon")
        try:
            try:
                as_anon = self.conn.execute("SELECT count(*) AS n FROM public.organisation").fetchone()["n"]
            except psycopg.errors.InsufficientPrivilege:  # permission denied is also a pass
                as_anon = 0
                self.conn.rollback()
        finally:
            self.conn.execute("RESET ROLE")
        self.assertEqual(as_anon, 0, "anon must not see tenant rows (RLS on, policies scoped to authenticated)")


if __name__ == "__main__":
    unittest.main()
