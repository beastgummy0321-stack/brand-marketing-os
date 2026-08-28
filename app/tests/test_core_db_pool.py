"""app/tests/test_core_db_pool.py — 票 02-1：連線池／per-request 連線的機器驗收。
02-4 補上 schema 隔離證明（done-check 5）。

只跑得動、也只該跑在有本機 Supabase（`supabase start`）的機器上，直接打
`DATABASE_URL`（預設本機 54322）。用完自己清乾淨（DROP 掉 scratch 表／schema），
不留垃圾。本模組自己的 schema 由 conftest.py 的 `_module_schema` fixture 建立。
"""

import os
import threading
import unittest
from urllib.parse import quote

import psycopg
import pytest

from app.core import db as coredb

_SCRATCH_TABLE = "test_core_db_pool_scratch"


@pytest.fixture(autouse=True)
def _bound_connection():
    """蓋掉 conftest.py 的同名 autouse fixture（不再幫每個測試預先借好連線）：
    本檔測的正是「借連線／繫在 contextvar／離開範圍後 current() 該炸」這幾件事本身，
    CurrentOutsideConnectionTest／ConnProxyTest 刻意要測『connection() 範圍之外』，
    被全包一層會讓那個情境永遠測不到。本檔每個測試自己按需開 `coredb.connection()`。"""
    yield


class PoolSingletonTest(unittest.TestCase):
    def test_pool_returns_same_object_twice(self):
        self.assertIs(coredb.pool(), coredb.pool())


class ConnectionExecuteTest(unittest.TestCase):
    def test_connection_executes_and_fetches_dict_row(self):
        with coredb.connection() as c:
            row = c.execute("SELECT 1 AS x").fetchone()
        self.assertEqual(row["x"], 1)


class ThreadIdentityTest(unittest.TestCase):
    def test_two_threads_see_different_current(self):
        seen = {}
        barrier = threading.Barrier(2)

        def worker(key):
            with coredb.connection():
                seen[key] = coredb.current()
                barrier.wait(timeout=5)

        threads = [threading.Thread(target=worker, args=(k,)) for k in ("a", "b")]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        self.assertIsNot(seen["a"], seen["b"])


class CurrentOutsideConnectionTest(unittest.TestCase):
    def test_current_outside_connection_raises_runtime_error(self):
        with self.assertRaises(RuntimeError):
            coredb.current()


class RollbackOnExceptionTest(unittest.TestCase):
    def setUp(self):
        with coredb.connection() as c:
            c.execute(f"CREATE TABLE IF NOT EXISTS {_SCRATCH_TABLE} (x int)")
            c.execute(f"DELETE FROM {_SCRATCH_TABLE}")

    def tearDown(self):
        with coredb.connection() as c:
            c.execute(f"DROP TABLE IF EXISTS {_SCRATCH_TABLE}")

    def test_exception_inside_connection_rolls_back(self):
        class _Boom(Exception):
            pass

        with self.assertRaises(_Boom):
            with coredb.connection() as c:
                c.execute(f"INSERT INTO {_SCRATCH_TABLE} (x) VALUES (1)")
                raise _Boom()

        with coredb.connection() as c:
            rows = c.execute(f"SELECT * FROM {_SCRATCH_TABLE}").fetchall()
        self.assertEqual(rows, [])


class SchemaIsolationTest(unittest.TestCase):
    """done-check 5：這個模組 schema 裡插的一列，從指向另一個全新 schema 的連線
    看不到——證明 conftest.py 的逐模組 schema 隔離真的隔離了資料，不只是換個名字。"""

    def setUp(self):
        with coredb.connection() as c:
            c.execute(f"CREATE TABLE IF NOT EXISTS {_SCRATCH_TABLE} (x int)")
            c.execute(f"DELETE FROM {_SCRATCH_TABLE}")
            c.execute(f"INSERT INTO {_SCRATCH_TABLE} (x) VALUES (99)")
            c.commit()

    def tearDown(self):
        with coredb.connection() as c:
            c.execute(f"DROP TABLE IF EXISTS {_SCRATCH_TABLE}")

    def test_row_invisible_from_a_different_fresh_schema(self):
        other_schema = f"t_isolation_probe_{os.getpid()}"
        base_dsn = coredb.dsn().split("?", 1)[0]
        admin = psycopg.connect(base_dsn, autocommit=True)
        try:
            admin.execute(f'DROP SCHEMA IF EXISTS "{other_schema}" CASCADE')
            admin.execute(f'CREATE SCHEMA "{other_schema}"')
            admin.execute(f'CREATE TABLE "{other_schema}".{_SCRATCH_TABLE} (x int)')

            other = psycopg.connect(f"{base_dsn}?options={quote(f'-c search_path={other_schema}')}")
            try:
                rows = other.execute(f"SELECT * FROM {_SCRATCH_TABLE}").fetchall()
                self.assertEqual(rows, [], "另一個 schema 不該看到這個模組插的列")
            finally:
                other.close()
        finally:
            admin.execute(f'DROP SCHEMA IF EXISTS "{other_schema}" CASCADE')
            admin.close()


class ConnProxyTest(unittest.TestCase):
    def test_conn_proxy_forwards_inside_connection_and_raises_outside(self):
        proxy = coredb.ConnProxy()
        with coredb.connection():
            row = proxy.execute("SELECT 1 AS x").fetchone()
            self.assertEqual(row["x"], 1)

        with self.assertRaises(RuntimeError):
            proxy.execute("SELECT 1")


if __name__ == "__main__":
    unittest.main()
