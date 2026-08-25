# -*- coding: utf-8 -*-
"""app/tests/test_core_db_pool.py — 票 02-1：連線池／per-request 連線的機器驗收。

只跑得動、也只該跑在有本機 Supabase（`supabase start`）的機器上——不是隔離的
per-module sqlite 暫存 DB（那套是舊架構，見 conftest.py，02-4 才會轉成 Postgres
版），這裡直接打 `DATABASE_URL`（預設本機 54322）。用完自己清乾淨（DROP 掉
scratch 表），不留垃圾。
"""

import threading
import unittest

from app.core import db as coredb

_SCRATCH_TABLE = "test_core_db_pool_scratch"


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
