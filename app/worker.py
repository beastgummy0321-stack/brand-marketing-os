"""app/worker.py — the procrastinate worker, its own process everywhere (ADR 0063).

`python -m app.worker` is the only thing that runs procrastinate jobs, on every environment
including this laptop — `app/main.py` starts no worker (see its own docstring and
`app/background/__init__.py`'s container-contract entry, `docs/contracts/background.md`).
This file is a sibling of `app/main.py`, not a file inside `app/background/`: starting a
worker needs the assembly root's task registration, and `app/background` may never import
upward.

`import app.main` triggers the assembly root's side effects this worker needs: `.env` load,
logging install, and task registration (`meta.register_task()`, `schedule.register_tasks()`)
— the same line `app/meta/daily_pull.py`'s `__main__` block already uses, for the same reason.
Do not re-implement any of it.

Before any of that, `main()` takes a Postgres **session** advisory lock keyed on this
connection's own `current_schema()` (ADR 0063, amendment "one worker, and the database says
so"). Before this lock existed, nothing enforced "one worker process" at all — the two
launchers guard only on port 8710, which a worker does not bind, and this ticket's own manual
done-check asks a human to run `python -m app.worker` by hand — so a second worker's
unconditional sweep could mark a first worker's live, already-paid-for `llm_task` row failed.
A worker that cannot take the lock prints one line and returns (exit code 0 — a second worker
starting is not an error the user should be shouted at for; the `.bat` may legitimately try).
The key is derived from the schema name, never a global constant: `app/tests/conftest.py` gives
each test module its own schema and the merge gate runs `pytest -n 8` against one database, so a
global key would make unrelated test workers fight each other over it.

`main()` releases the lock itself when it returns: `SELECT pg_advisory_unlock()` on the same
connection, in a `finally`, and only if this call is the one that took the lock — a worker that
printed the line above and returned early never reaches that `finally`, so it can never release
a lock some other worker is holding (ADR 0063, amendment "release the lock, so nothing depends
on test ordering"). That is what makes `main()` safe to call more than once in the same process.
Process exit is no longer the only thing that frees the lock; it is now the fallback for a
*crashed* worker, where the operating system drops the connection and Postgres frees the lock
with it.

`fail_interrupted_tasks()` runs once here, only after the lock is taken and before the worker
takes its first job (ADR 0063, "What this changes about interrupted work"): one worker process
owns every `llm_task` row still `status = 'running'`, and owns none at the moment it boots, so
every such row left over from the previous process is dead and gets marked failed — see
`app/llm/gateway.py`'s docstring for the invariant this depends on, and its `ponytail:` note
for when it stops holding (more than one worker process). The lock is what now makes "one
worker process" true instead of assumed.

Signal handling stays procrastinate's own default (`install_signal_handlers=True`, what
`App.run_worker()` already defaults to) — do **not** pass `install_signal_handlers=False`: that
argument only made sense while the worker rode a thread inside uvicorn's process (ADR 0039,
superseded). But on Windows, procrastinate installs no signal handler at all regardless of that
argument — `.venv/Lib/site-packages/procrastinate/signals.py`'s `on_stop()` returns early on
`os.name == "nt"` — so Ctrl+C reaches Python's default and raises `KeyboardInterrupt` out of
`asyncio.run()` instead of the clean stop procrastinate gives other platforms. The
`if __name__ == "__main__":` guard below catches it and exits 0: the process that owns the main
thread owns the interrupt, and that process is this one now (ADR 0063, amendment "Ctrl+C, and
what procrastinate does not do on Windows").
"""

import hashlib

import app.main  # noqa: F401 — triggers .env load, logging install, task registration
from app.background import app as background_app
from app.core import db as coredb
from app.llm import gateway as llm_gateway


def _advisory_lock_key(schema: str) -> int:
    """Derived, never a magic number: the first 8 bytes of a sha256 digest of a schema-scoped
    string, read as a signed bigint (`pg_try_advisory_lock` takes one `bigint`). Keyed on
    schema, not global — see module docstring for why."""
    digest = hashlib.sha256(f"app.worker:{schema}".encode()).digest()
    return int.from_bytes(digest[:8], "big", signed=True)


def main(*, wait: bool = True) -> None:
    """`wait=False` drains what is queued, then returns — procrastinate's own `run_worker`
    keyword, exposed so tests can drive this real entry point (see
    `app/tests/test_background.py`) instead of a copy of it.

    The connection stays borrowed for this whole call — including `run_worker()`, which may
    run for the life of the process — because the advisory lock it takes lives on that
    connection's Postgres session; returning it to the pool early would drop the lock."""
    with coredb.connection() as conn:
        schema_row = conn.execute("SELECT current_schema()").fetchone()
        assert schema_row is not None  # SELECT current_schema() always returns exactly one row
        schema = schema_row["current_schema"]
        key = _advisory_lock_key(schema)  # same key needed again below, to release this lock
        lock_row = conn.execute(
            "SELECT pg_try_advisory_lock(%s)", (key,)
        ).fetchone()
        assert lock_row is not None  # pg_try_advisory_lock() always returns exactly one row
        got_lock = lock_row["pg_try_advisory_lock"]
        conn.commit()  # close out this SELECT's transaction now; the session lock survives
        # COMMIT regardless (verified against this repo's own Postgres, not assumed) — this
        # commit only keeps the process from sitting in an open transaction for as long as it
        # runs, it does not affect the lock.
        if not got_lock:
            print("已經有另一個 worker 行程在跑，這個行程結束，不做任何事。")
            return
        try:
            llm_gateway.fail_interrupted_tasks(conn)
            background_app().run_worker(wait=wait)
        finally:
            # Round 3 (ADR 0063): only the caller that took the lock releases it — a worker
            # that returned early above never reaches this block, so it can never release a
            # lock some other worker is holding. Runs on interruption too (run_worker() raising
            # out of Ctrl+C), so a clean or interrupted return never leaves this lock on a
            # connection that goes back to the pool still holding it — which is what let a
            # second in-process main() be handed a different, unlocked connection and quietly
            # do nothing.
            conn.execute("SELECT pg_advisory_unlock(%s)", (key,))
            conn.commit()  # verified against this repo's own Postgres: pg_advisory_unlock()
            # takes effect immediately regardless of commit/rollback; this commit only leaves
            # the connection idle before it goes back to the pool.


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pass  # Windows: procrastinate installs no SIGINT handler (see module docstring) —
        # this is the clean stop, exit code 0.
