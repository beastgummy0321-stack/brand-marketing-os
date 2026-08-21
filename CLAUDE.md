# CLAUDE.md

品牌行銷作業系統：Python + FastAPI + SQLite，單機單人使用。
前端 React＋Vite（`frontend/`，`npm run build` 後掛載於 `/app`）；後端只出 `/api` JSON。

- 繁體中文；使用者非工程背景，回報用白話，術語第一次出現附一句說明
- 不確定就問，不要猜
- 刪除、覆蓋、對外發布、花錢：先說後果，等確認

## 開場

讀 `BOARD.md`；有 `[>]` 的票，主動報「哪張、進度、卡在哪」。看板只放未完成，完成即刪行。

## 快速事實

- 啟動：`啟動行銷系統.bat` → http://localhost:8710/
- 資料庫 `data/app.db`、備份 `backups/`、金鑰 `.env`（皆不進版控）
- 測試：`python -m pytest app/tests`（跑法見下方 Running tests）
- 語彙 `CONTEXT.md`；決策 `docs/adr/`；技術債與機器閘門 `docs/tech-debt.md`（動超標檔前先讀）
- `app/methodology/` 是 prompt 零件不是文件，刪改先問
- 議題：`.scratch/<effort>/issues/`，規則見 `docs/agents/`

## Running tests

Full suite is ~2000 tests. Serial it takes ~420s; that wait, repeated across a
red-green loop, is where agent time actually goes.

- **Red-green loop**: run only the affected files — `pytest app/tests/test_x.py` is
  sub-second. Never run the full suite to check one assertion.
- **Final gate only**: `python -m pytest app/tests -q -n auto --dist loadfile` (~200s).
  `--dist loadfile` is required: `conftest.py` gives each test *module* its own temp DB,
  and the default per-test distribution splits a module across workers.
- `pytest-xdist` is already in `requirements.txt`. Do not add a runner.

## Before writing a spec that repoints a table

Grep for structural constraints on the old table first — they block the swap at
runtime, not at review time, and finding one mid-implementation costs a migration
plus a round trip for approval:

```
grep -rn "REFERENCES <table>" app/*/migrations/
```

Migration `.sql` files are hash-frozen in `app/core/migration_manifest.json`; fixes go
in a new file plus a manifest entry, never by editing an applied one.

`test_real_db_schema_drift.py::KNOWN_SCHEMA_DRIFT` tolerates drift between the schema
and the real `data/app.db`. Entries there are temporary by definition: the guard fails
once the drift is gone. A worktree with the migration applied and a checkout without it
cannot both be green — migrate the live DB (back it up first) rather than keeping the
entries.
