"""Fixture recovery using real PostgreSQL locks on disposable tables, and replays of data-moving
migrations (F50-I04 percent scale) on disposable schemas."""

import time
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from pathlib import Path
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


# ---------------------------------------------------------------------------
# F50-I04 (feature F50 Contract I, decision 9): percents stored 0–100. Each migration is replayed
# on a disposable schema holding the old 0–1 shape, so the stored-value move is proven, not
# assumed (the module schemas are built from every migration and only ever see the new shape).
# ---------------------------------------------------------------------------

_MIGRATIONS = Path(__file__).resolve().parents[2] / "supabase" / "migrations"


def _replay(schema: str, setup: str, migration: str) -> psycopg.Connection:
    conn = _admin_conn()
    conn.execute(f'CREATE SCHEMA "{schema}"')
    conn.execute(f'SET search_path TO "{schema}"')
    conn.execute(setup)
    conn.execute((_MIGRATIONS / migration).read_text(encoding="utf-8"))
    return conn


def test_close_rate_migration_turns_fractions_into_percents():
    schema = "f50_close_rate_" + uuid4().hex[:12]
    old = ("(id text PRIMARY KEY, close_rate numeric(6,4)"
           " CHECK (close_rate IS NULL OR (close_rate > 0 AND close_rate <= 1)))")
    conn = _replay(
        schema,
        f"CREATE TABLE product_economics {old}; CREATE TABLE product_economics_version {old};"
        " INSERT INTO product_economics VALUES ('a', 0.2), ('b', NULL), ('c', 1), ('d', 0.1234);"
        " INSERT INTO product_economics_version VALUES ('a', 0.2), ('c', 1);",
        "20261005000101_brand_intelligence_close_rate_percent.sql",
    )
    try:
        rows = dict(conn.execute("SELECT id, close_rate FROM product_economics").fetchall())
        assert rows == {"a": Decimal("20.00"), "b": None, "c": Decimal("100.00"),
                        "d": Decimal("12.34")}
        versions = dict(conn.execute(
            "SELECT id, close_rate FROM product_economics_version").fetchall())
        assert versions == {"a": Decimal("20.00"), "c": Decimal("100.00")}
        for table in ("product_economics", "product_economics_version"):
            conn.execute(f"INSERT INTO {table} VALUES ('ok', 100)")
            for bad in (0, 120):
                with pytest.raises(psycopg.errors.CheckViolation):
                    conn.execute(f"INSERT INTO {table} VALUES ('bad', {bad})")
    finally:
        conn.execute(f'DROP SCHEMA "{schema}" CASCADE')
        conn.close()


def test_margin_card_migration_turns_fractions_into_percents():
    schema = "f50_margin_card_" + uuid4().hex[:12]
    conn = _replay(
        schema,
        "CREATE TABLE rule_card_value (brand_id text, card_key text, field_key text,"
        " value double precision);"
        " INSERT INTO rule_card_value VALUES ('b1', 'gross_margin', 'gross_margin_rate', 0.7),"
        " ('b2', 'gross_margin', 'gross_margin_rate', 45),"
        " ('b3', 'schedule_budget', 'step_rate', 1);",
        "20261005000102_core_rule_card_margin_percent.sql",
    )
    try:
        rows = dict(conn.execute("SELECT brand_id, value FROM rule_card_value").fetchall())
        assert rows == {"b1": pytest.approx(70.0), "b2": 45.0, "b3": 1.0}
    finally:
        conn.execute(f'DROP SCHEMA "{schema}" CASCADE')
        conn.close()
