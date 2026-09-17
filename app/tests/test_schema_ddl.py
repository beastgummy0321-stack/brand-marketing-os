"""Fixture recovery using real PostgreSQL locks on disposable tables."""

import time
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

import psycopg
import pytest

from app.tests.conftest import _admin_conn, _ddl


def test_ddl_retries_atomic_batch_after_deadlock(monkeypatch):
    from app.tests import conftest

    monkeypatch.setattr(conftest, "_SCHEMA_DDL_LOCK_KEY", uuid4().int % (2**63))
    schema = "ddl_repro_" + uuid4().hex
    with _admin_conn() as admin, _admin_conn() as peer, _admin_conn() as observer:
        admin.execute(f'CREATE SCHEMA "{schema}"')
        admin.execute(f'CREATE TABLE "{schema}".buckets (id int)')
        admin.execute(f'CREATE TABLE "{schema}".objects (id int)')
        admin.execute("SET deadlock_timeout = '50ms'; SET statement_timeout = '8s'")
        peer.execute("SET deadlock_timeout = '5s'; SET statement_timeout = '8s'")
        sql = (
            f'CREATE TABLE "{schema}".proof (id int);'
            f'LOCK TABLE "{schema}".buckets IN ACCESS EXCLUSIVE MODE;'
            f'LOCK TABLE "{schema}".objects IN ACCESS EXCLUSIVE MODE;'
            f'INSERT INTO "{schema}".proof VALUES (1)'
        )
        execute = admin.execute
        deadlocks = []

        def observe(query, *args, **kwargs):
            try:
                return execute(query, *args, **kwargs)
            except psycopg.errors.DeadlockDetected as error:
                deadlocks.append(error)
                raise

        monkeypatch.setattr(admin, "execute", observe)
        try:
            peer.execute("BEGIN")
            peer.execute(f'LOCK TABLE "{schema}".objects IN ROW SHARE MODE')
            with ThreadPoolExecutor(max_workers=1) as executor:
                result = executor.submit(_ddl, admin, sql)
                deadline = time.monotonic() + 4
                while time.monotonic() < deadline:
                    row = observer.execute(
                        "SELECT wait_event FROM pg_stat_activity WHERE pid = %s",
                        (admin.info.backend_pid,),
                    ).fetchone()
                    if row and row[0] == "relation":
                        break
                    time.sleep(0.01)
                else:
                    pytest.fail("DDL never reached the expected lock wait")
                try:
                    peer.execute(f'LOCK TABLE "{schema}".buckets IN ROW SHARE MODE')
                finally:
                    peer.execute("ROLLBACK")
                result.result(timeout=10)
            assert len(deadlocks) == 1, "regression must exercise a real deadlock"
            assert admin.execute(f'SELECT id FROM "{schema}".proof').fetchall() == [(1,)]
        finally:
            peer.execute("ROLLBACK")
            admin.execute(f'DROP SCHEMA "{schema}" CASCADE')


def test_ddl_does_not_retry_other_errors(monkeypatch):
    with _admin_conn() as admin:
        execute = admin.execute
        attempts = []

        def observe(query, *args, **kwargs):
            if query == "SELECT missing_column":
                attempts.append(query)
            return execute(query, *args, **kwargs)

        monkeypatch.setattr(admin, "execute", observe)
        with pytest.raises(psycopg.errors.UndefinedColumn):
            _ddl(admin, "SELECT missing_column")
        assert len(attempts) == 1


def test_ddl_stops_after_second_deadlock_and_releases_advisory_lock(monkeypatch):
    from app.tests import conftest

    lock_key = uuid4().int % (2**63)
    monkeypatch.setattr(conftest, "_SCHEMA_DDL_LOCK_KEY", lock_key)

    with _admin_conn() as admin, _admin_conn() as peer:
        execute = admin.execute
        attempts = []

        def deadlock(query, *args, **kwargs):
            if query == "SELECT 1":
                attempts.append(query)
                raise psycopg.errors.DeadlockDetected("repeat contention")
            return execute(query, *args, **kwargs)

        monkeypatch.setattr(admin, "execute", deadlock)
        with pytest.raises(psycopg.errors.DeadlockDetected):
            _ddl(admin, "SELECT 1")
        assert len(attempts) == 2
        acquired = peer.execute("SELECT pg_try_advisory_lock(%s)", (lock_key,)).fetchone()
        assert acquired == (True,)
        peer.execute("SELECT pg_advisory_unlock(%s)", (lock_key,))
