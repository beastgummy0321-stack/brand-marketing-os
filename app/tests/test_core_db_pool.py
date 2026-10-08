"""app/tests/test_core_db_pool.py — 票 02-1：連線池／per-request 連線的機器驗收。
02-4 補上 schema 隔離證明（done-check 5）。

只跑得動、也只該跑在有本機 Supabase（`supabase start`）的機器上，直接打
`DATABASE_URL`（預設本機 54322）。用完自己清乾淨（DROP 掉 scratch 表／schema），
不留垃圾。本模組自己的 schema 由 conftest.py 的 `_module_schema` fixture 建立。
"""

import asyncio
import os
import threading
import unittest
from unittest.mock import patch
from urllib.parse import quote

import anyio
import httpx
import psycopg
import pytest
from fastapi import FastAPI
from psycopg_pool import ConnectionPool

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


class AsyncRequestPoolTest(unittest.TestCase):
    def test_more_than_ten_requests_can_wait_without_blocking_routes_or_returns(self):
        from app import main

        async def run():
            app = FastAPI()
            app.middleware("http")(main._db_connection_middleware)
            first_wave = asyncio.Event()
            release = asyncio.Event()
            active = set()
            maximum = 0
            entered = 0

            @app.get("/probe/{number}")
            async def probe(number: int):
                nonlocal maximum, entered
                conn = coredb.current()
                self.assertNotIn(id(conn), active)
                active.add(id(conn))
                maximum = max(maximum, len(active))
                entered += 1
                if entered == 10:
                    first_wave.set()
                try:
                    await release.wait()
                    self.assertIs(coredb.current(), conn)
                    self.assertIs(await asyncio.to_thread(coredb.current), conn)
                    value = coredb.ConnProxy().execute("SELECT 1 AS x").fetchone()["x"]
                    return {"number": number, "value": value}
                finally:
                    active.remove(id(conn))

            real_pool = coredb.pool()
            original_connection = real_pool.connection
            # Bound regression failures: the old blocking middleware otherwise waits
            # 30 seconds per excess request before the event loop can release a slot.
            with (
                patch.object(
                    real_pool, "connection", side_effect=lambda: original_connection(timeout=1),
                ),
                patch.object(main, "_purge_expired_llm_task_content_if_new_day") as purge,
            ):
                async with httpx.AsyncClient(
                    transport=httpx.ASGITransport(app=app), base_url="http://fixture",
                ) as client:
                    tasks = [asyncio.create_task(client.get(f"/probe/{i}")) for i in range(25)]
                    try:
                        await asyncio.wait_for(first_wave.wait(), 5)
                        # This timer and the ten waiting routes must continue to run
                        # while more requests wait for the full pool.
                        await asyncio.sleep(0.05)
                        self.assertEqual(entered, 10)
                        self.assertEqual(len(active), 10)
                        release.set()
                        responses = await asyncio.wait_for(asyncio.gather(*tasks), 8)
                    finally:
                        release.set()
                        await asyncio.gather(*tasks, return_exceptions=True)
            self.assertEqual(maximum, 10)
            self.assertEqual([response.json()["number"] for response in responses], list(range(25)))
            self.assertTrue(all(response.json()["value"] == 1 for response in responses))
            self.assertEqual(len({response.headers["X-Request-Id"] for response in responses}), 25)
            self.assertEqual(purge.call_count, 25)
            with self.assertRaises(RuntimeError):
                coredb.current()

        asyncio.run(run())

    def test_async_commit_rollback_and_nested_context_restore(self):
        async def run():
            with coredb.connection() as outer:
                outer.execute(f"CREATE TABLE {_SCRATCH_TABLE} (x int)")
                outer.commit()
                try:
                    async with coredb.async_connection() as inner:
                        self.assertIsNot(inner, outer)
                        inner.execute(f"INSERT INTO {_SCRATCH_TABLE} VALUES (1)")
                    self.assertIs(coredb.current(), outer)
                    with self.assertRaisesRegex(ValueError, "rollback"):
                        async with coredb.async_connection() as inner:
                            inner.execute(f"INSERT INTO {_SCRATCH_TABLE} VALUES (2)")
                            raise ValueError("rollback")
                    self.assertIs(coredb.current(), outer)
                    self.assertEqual(
                        outer.execute(f"SELECT x FROM {_SCRATCH_TABLE}").fetchall(), [{"x": 1}],
                    )
                finally:
                    outer.rollback()
                    outer.execute(f"DROP TABLE {_SCRATCH_TABLE}")
            with self.assertRaises(RuntimeError):
                coredb.current()

        asyncio.run(run())

    def test_tenant_scope_survives_request_rollback_and_is_reset_before_reuse(self):
        async def run():
            # One slot proves that the next request receives the same physical
            # connection, with the existing pool reset callback applied.
            with ConnectionPool(
                coredb.dsn(), min_size=1, max_size=1,
                reset=coredb._reset_pooled_connection,
                kwargs={"row_factory": psycopg.rows.dict_row},
            ) as one:
                with patch.object(coredb, "pool", return_value=one):
                    async with coredb.async_connection() as conn:
                        baseline = conn.execute(
                            "SELECT current_user AS role, pg_backend_pid() AS pid",
                        ).fetchone()
                        coredb.set_tenant_scope(conn, coredb.DEV_ORG_ID)
                        conn.rollback()
                        scoped = conn.execute(
                            "SELECT current_user AS role, current_setting('app.org_id') AS org",
                        ).fetchone()
                        self.assertEqual(
                            scoped, {"role": "authenticated", "org": coredb.DEV_ORG_ID},
                        )
                    async with coredb.async_connection() as conn:
                        restored = conn.execute(
                            "SELECT current_user AS role, pg_backend_pid() AS pid, "
                            "current_setting('app.org_id', true) AS org",
                        ).fetchone()
                        self.assertEqual(restored["pid"], baseline["pid"])
                        self.assertEqual(restored["role"], baseline["role"])
                        self.assertIn(restored["org"], (None, ""))

        asyncio.run(run())

    def test_cancelled_request_rolls_back_and_returns_its_connection(self):
        async def run():
            entered = asyncio.Event()
            with coredb.connection() as setup:
                setup.execute(f"CREATE TABLE {_SCRATCH_TABLE} (x int)")
            async def worker():
                async with coredb.async_connection() as conn:
                    conn.execute(f"INSERT INTO {_SCRATCH_TABLE} VALUES (9)")
                    entered.set()
                    await asyncio.Event().wait()
            task = asyncio.create_task(worker())
            try:
                await asyncio.wait_for(entered.wait(), 5)
                task.cancel()
                with self.assertRaises(asyncio.CancelledError):
                    await task
                async with coredb.async_connection() as conn:
                    self.assertEqual(conn.execute(f"SELECT x FROM {_SCRATCH_TABLE}").fetchall(), [])
            finally:
                with coredb.connection() as cleanup:
                    cleanup.execute(f"DROP TABLE {_SCRATCH_TABLE}")
            with self.assertRaises(RuntimeError):
                coredb.current()

        asyncio.run(run())


class AsyncCancellationTest(unittest.TestCase):
    class Manager:
        def __init__(self, *, block_borrow=False, block_return=False):
            self.borrowed = threading.Event()
            self.returning = threading.Event()
            self.allow_borrow = threading.Event()
            self.allow_return = threading.Event()
            self.exits = []
            if not block_borrow:
                self.allow_borrow.set()
            if not block_return:
                self.allow_return.set()

        def __enter__(self):
            self.borrowed.set()
            if not self.allow_borrow.wait(3):
                raise RuntimeError("test borrower timed out")
            return object()

        def __exit__(self, kind, value, traceback):
            self.returning.set()
            if not self.allow_return.wait(3):
                raise RuntimeError("test return timed out")
            self.exits.append(kind)

    def test_cancel_during_borrow_returns_eventually_acquired_connection(self):
        async def run():
            manager = self.Manager(block_borrow=True)
            entered_body = False
            async def worker():
                nonlocal entered_body
                async with coredb.async_connection():
                    entered_body = True
            with patch.object(coredb, "pool") as get_pool:
                get_pool.return_value.connection.return_value = manager
                task = asyncio.create_task(worker())
                self.assertTrue(await asyncio.to_thread(manager.borrowed.wait, 1))
                task.cancel()
                await asyncio.sleep(0)
                manager.allow_borrow.set()
                with self.assertRaises(asyncio.CancelledError):
                    await asyncio.wait_for(task, 2)
            self.assertFalse(entered_body)
            self.assertEqual(manager.exits, [asyncio.CancelledError])
            with self.assertRaises(RuntimeError):
                coredb.current()
        asyncio.run(run())

    def test_repeated_cancel_during_return_still_finishes_one_return(self):
        async def run():
            manager = self.Manager(block_return=True)
            async def worker():
                async with coredb.async_connection():
                    pass
            with patch.object(coredb, "pool") as get_pool:
                get_pool.return_value.connection.return_value = manager
                task = asyncio.create_task(worker())
                self.assertTrue(await asyncio.to_thread(manager.returning.wait, 1))
                task.cancel()
                await asyncio.sleep(0)
                task.cancel()
                await asyncio.sleep(0)
                self.assertFalse(task.done())
                manager.allow_return.set()
                with self.assertRaises(asyncio.CancelledError):
                    await asyncio.wait_for(task, 2)
            self.assertEqual(manager.exits, [None])
        asyncio.run(run())

    def test_anyio_level_cancellation_finishes_cleanup_without_leaking_context(self):
        async def run():
            manager = self.Manager()
            with patch.object(coredb, "pool") as get_pool:
                get_pool.return_value.connection.return_value = manager
                with anyio.move_on_after(0.02) as scope:
                    async with coredb.async_connection():
                        await anyio.sleep_forever()
            self.assertTrue(scope.cancel_called)
            self.assertEqual(manager.exits, [asyncio.CancelledError])
            with self.assertRaises(RuntimeError):
                coredb.current()
        asyncio.run(run())


class AtomicOperationTest(unittest.TestCase):
    def setUp(self):
        with coredb.connection() as conn:
            conn.execute(f"CREATE TABLE {_SCRATCH_TABLE} (x int)")
            conn.execute(f"GRANT ALL ON {_SCRATCH_TABLE} TO authenticated")

    def tearDown(self):
        with coredb.connection() as conn:
            conn.execute(f"DROP TABLE {_SCRATCH_TABLE}")

    def _rows(self):
        with coredb.connection() as observer:
            return observer.execute(f"SELECT x FROM {_SCRATCH_TABLE} ORDER BY x").fetchall()

    def test_helper_commit_does_not_publish_before_owner_finishes(self):
        with coredb.connection() as conn:
            conn.execute("SELECT 1")
            with self.assertRaises(ValueError):
                with conn.atomic():
                    conn.execute(f"INSERT INTO {_SCRATCH_TABLE} VALUES (1)")
                    coredb.ConnProxy().commit()
                    self.assertEqual(self._rows(), [])
                    raise ValueError("rejected")
            conn.commit()
        self.assertEqual(self._rows(), [])

    def test_swallowed_rollback_cannot_turn_into_success(self):
        with coredb.connection() as conn:
            conn.execute(f"INSERT INTO {_SCRATCH_TABLE} VALUES (1)")
            with self.assertRaises(coredb.OperationRolledBack):
                with coredb.ConnProxy().atomic():
                    conn.execute(f"INSERT INTO {_SCRATCH_TABLE} VALUES (2)")
                    conn.rollback()
                    conn.commit()
            conn.execute(f"INSERT INTO {_SCRATCH_TABLE} VALUES (3)")
        self.assertEqual(self._rows(), [{"x": 1}, {"x": 3}])

    def test_nested_failure_preserves_outer_work_and_tenant_scope(self):
        with coredb.connection() as conn:
            coredb.set_tenant_scope(conn, coredb.DEV_ORG_ID)
            conn.execute(f"INSERT INTO {_SCRATCH_TABLE} VALUES (1)")
            with conn.atomic():
                conn.execute(f"INSERT INTO {_SCRATCH_TABLE} VALUES (2)")
                with self.assertRaises(ValueError):
                    with conn.atomic():
                        conn.execute(f"INSERT INTO {_SCRATCH_TABLE} VALUES (3)")
                        conn.execute("SELECT set_config('app.org_id', 'wrong-org', false)")
                        conn.commit()
                        raise ValueError("inner rejected")
                scope = conn.execute(
                    "SELECT current_user AS role, current_setting('app.org_id') AS org").fetchone()
                self.assertEqual(scope, {"role": "authenticated", "org": coredb.DEV_ORG_ID})
                conn.execute(f"INSERT INTO {_SCRATCH_TABLE} VALUES (4)")
                self.assertEqual(self._rows(), [])
            conn.commit()
        self.assertEqual(self._rows(), [{"x": 1}, {"x": 2}, {"x": 4}])

    def test_outer_rejection_undoes_successful_nested_operation(self):
        with coredb.connection() as conn:
            conn.execute(f"INSERT INTO {_SCRATCH_TABLE} VALUES (1)")
            with self.assertRaises(ValueError):
                with conn.atomic():
                    with conn.atomic():
                        conn.execute(f"INSERT INTO {_SCRATCH_TABLE} VALUES (2)")
                    raise ValueError("outer rejected")
            conn.commit()
        self.assertEqual(self._rows(), [{"x": 1}])

    def test_sql_failure_with_swallowed_helper_rollback_remains_rejected(self):
        with coredb.connection() as conn:
            coredb.set_tenant_scope(conn, coredb.DEV_ORG_ID)
            conn.execute(f"INSERT INTO {_SCRATCH_TABLE} VALUES (1)")
            with self.assertRaisesRegex(coredb.OperationRolledBack, "requested rollback"):
                with conn.atomic():
                    conn.execute(f"INSERT INTO {_SCRATCH_TABLE} VALUES (2)")
                    try:
                        conn.execute("SELECT 1 / 0")
                    except psycopg.errors.DivisionByZero:
                        conn.rollback()
            conn.execute(f"INSERT INTO {_SCRATCH_TABLE} VALUES (3)")
            scope = conn.execute(
                "SELECT current_user AS role, current_setting('app.org_id') AS org").fetchone()
            self.assertEqual(scope, {"role": "authenticated", "org": coredb.DEV_ORG_ID})
        self.assertEqual(self._rows(), [{"x": 1}, {"x": 3}])


if __name__ == "__main__":
    unittest.main()
