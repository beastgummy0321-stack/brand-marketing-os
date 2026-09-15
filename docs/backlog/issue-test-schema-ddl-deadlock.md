# Test schema DDL deadlock under `pytest -n 8` — flaky, pre-existing

Status: not planned. Hit during F07 integration (2026-09-15).

- `app/tests/conftest.py` serialises module-schema DDL with one advisory lock (`_ddl`,
  `_SCHEMA_DDL_LOCK_KEY`), but a test body running in another xdist worker can still hold a
  RowShareLock on a shared relation while the DDL waits for an AccessExclusiveLock →
  `psycopg.errors.DeadlockDetected` in `_module_schema` setup (conftest.py:155).
- Seen once in two `harness integrate feature F07` runs: 6 setup errors, all in
  `test_dashboard_brand_month.py`; that file passes alone and the rerun was fully green.
  F07 did not change conftest.py.
- Not the same as connection exhaustion: `-n 8` also needs spare backends (the 8710 app and its
  worker) stopped first (CONTEXT.md, the `pytest -n 8` note).
- Revisit if it recurs: hold the advisory lock across the whole module setup and teardown, or retry
  `_ddl` once on DeadlockDetected.
