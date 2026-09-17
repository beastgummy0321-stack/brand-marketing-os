# Test schema DDL deadlock under `pytest -n 8` — flaky, pre-existing

Status: bounded recovery implemented and verified (2026-09-17).

- `app/tests/conftest.py` serialises module-schema DDL with one advisory lock (`_ddl`,
  `_SCHEMA_DDL_LOCK_KEY`), but a test body running in another xdist worker can still hold a
  RowShareLock on a shared relation while the DDL waits for an AccessExclusiveLock →
  `psycopg.errors.DeadlockDetected` in `_module_schema` setup (conftest.py:155).
- Seen once in two `harness integrate feature F07` runs: 6 setup errors, all in
  `test_dashboard_brand_month.py`; that file passes alone and the rerun was fully green.
  F07 did not change conftest.py.
- Not the same as connection exhaustion: `-n 8` also needs spare backends (the 8710 app and its
  worker) stopped first (CONTEXT.md, the `pytest -n 8` note).
- F08 verification (2026-09-17): recurred in test_methodology.py module setup (28 DeadlockDetected errors; 1391 other tests passed). The affected file passed 28/28 alone; one complete integration retry passed 1419 tests and 59 subtests. No fixture or assertion was changed. Still unresolved.
- F08 logs identify the shared relations as `storage.objects` / `storage.buckets`. The advisory lock only serializes fixture DDL, not Storage sessions. A disposable two-connection reproduction produces the same AccessExclusiveLock / RowShareLock cycle; the original scheduler timing is not claimed deterministic.
- `_ddl` now retries the whole atomic batch once after DeadlockDetected. Other errors and a second deadlock still fail. Tests cover real deadlock recovery, rollback, retry bound and lock release.
- Verification: 1422 backend tests + 59 subtests passed with `-n 8 --dist loadfile`; Ruff and Pyright passed. This is bounded recovery, not a claim that shared Storage contention is eliminated.
