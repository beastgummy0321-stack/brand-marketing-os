"""Pytest 啟動與逐模組 Postgres schema 隔離（票 02-4，ADR 0027：Supabase）。

取代 02-1 的 SQLite per-module 暫存目錄版本：每個測試模組拿一個獨立 Postgres
schema（`t_<module>_<pid>`），module setup 時建立並灌入 5 個 baseline migration
＋ seed.sql，module teardown 時整個砍掉（`DROP SCHEMA … CASCADE`）——`pytest -n auto
--dist loadfile` 的每個 worker 進程互不相干（各自的 pid、各自的 `app.core.db._pool`），
同一 worker 裡前後兩個模組也不會撞名（pid 相同但模組名不同）。

連線走法：`app/core/db.py` 的連線池是模組層單例（`coredb._pool`），只在第一次呼叫
`coredb.pool()` 時惰性建立、之後固定用建立當下的 DSN。這裡在每個模組 setup 時把
`DATABASE_URL` 指到「這個模組的 schema」（DSN `options=-c search_path=…`）、順手把
`coredb._pool` 砍掉重建，讓下一次 `coredb.pool()` 用新 DSN 開新池——等於「這個模組
期間，池子吐出來的每一條連線 search_path 都固定指這個 schema」，比 psycopg_pool 的
`configure=` hook 更直接：`configure` 只在物理連線「建立那一刻」跑一次（見
psycopg_pool.pool.ConnectionPool._connect 原始碼），同一個池子若跨模組沿用，
舊連線的 search_path 不會跟著換，所以這裡選擇「換模組＝換 DSN＋砍池重開」而不是
共用一個池子掛 configure。

`TestClient(app)` 送出的請求走 `app/main.py` 的 `_db_connection_middleware`，跟
下面的 autouse 連線 fixture 一樣都是問 `coredb.pool()` 借連線——兩邊借到的是同一個
（此刻唯一存在的）池子，因此落在同一個 schema。
"""

import os
import re
from pathlib import Path

import psycopg
import pytest

# 票 03-1：測試預設走 dev token（本機 Supabase 一定是 localhost，app.identity.register()
# 才不會 RuntimeError）。放在任何 app.* import 之前——app.main 組裝時 register() 會
# 立刻讀這兩個環境變數。IDENTITY_ALLOW_HS256／SUPABASE_JWT_SECRET 是另一條測試路徑
# （手動 mint HS256 token 驗 JWKS 以外的驗簽路徑），見 test_identity_auth.py。
os.environ.setdefault("SUPABASE_URL", "http://127.0.0.1:54321")
os.environ.setdefault("IDENTITY_DEV_TOKEN", "test-dev-token")
os.environ.setdefault("IDENTITY_ALLOW_HS256", "1")
os.environ.setdefault(
    "SUPABASE_JWT_SECRET", "super-secret-jwt-token-with-at-least-32-characters-long"
)

from starlette.testclient import TestClient as _TestClient  # noqa: E402

from app.core import db as coredb  # noqa: E402 — 環境變數必須先設好才能 import app.*

# 票 03-1：既有測試遍地 `TestClient(app)` 直接送請求，全站現在每條 /api 路由都要 Bearer
# token（`require_actor()`）。與其去改每個測試檔的建構呼叫，這裡一次幫 `TestClient`
# 這個類別本身補一個預設 `Authorization` header（dev token，見上面 IDENTITY_DEV_TOKEN）——
# `fastapi.testclient.TestClient` 就是這個類別的重新匯出，不管測試檔從哪裡 import，
# patch 的是同一顆類別物件。想測「沒帶 token」就在該測試自己
# `self.client.headers.pop("Authorization", None)`（或整段覆寫 headers）。
_orig_testclient_init = _TestClient.__init__


def _testclient_init_with_dev_token(self, *args, **kwargs):
    _orig_testclient_init(self, *args, **kwargs)
    self.headers["Authorization"] = f"Bearer {os.environ['IDENTITY_DEV_TOKEN']}"


_TestClient.__init__ = _testclient_init_with_dev_token

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_MIGRATIONS_DIR = _REPO_ROOT / "supabase" / "migrations"
_SEED_FILE = _REPO_ROOT / "supabase" / "seed.sql"
# 固定捕捉「未被任何模組改過」的原始 DSN，管理連線（建/砍 schema）永遠用這條，
# 不受下面逐模組覆寫 os.environ["DATABASE_URL"] 影響。
_BASE_DSN = os.environ.get("DATABASE_URL", coredb.dsn())

_baseline_sql_cache: list = []  # 惰性讀一次 baseline SQL 檔案內容（不是資料庫狀態）


def _baseline_sql() -> str:
    if not _baseline_sql_cache:
        parts = [p.read_text(encoding="utf-8") for p in sorted(_MIGRATIONS_DIR.glob("*.sql"))]
        parts.append(_SEED_FILE.read_text(encoding="utf-8"))
        _baseline_sql_cache.append("\n".join(parts))
    return _baseline_sql_cache[0]


def _schema_name(module_name: str) -> str:
    short = re.sub(r"[^a-zA-Z0-9_]", "_", module_name.rsplit(".", 1)[-1])
    return f"t_{short}_{os.getpid()}"


def _admin_conn() -> psycopg.Connection:
    """管理連線：固定用 `_BASE_DSN`（不受逐模組 search_path 覆寫影響），autocommit，
    只用來建/砍 test schema。"""
    return psycopg.connect(_BASE_DSN, autocommit=True)


# `pytest -n auto` 在這台機器展開 20 個 worker，`--dist loadfile` 讓它們幾乎同時各自
# 對自己的 schema 做 CREATE SCHEMA＋78 張表＋DROP SCHEMA CASCADE。實測撞過
# `psycopg.errors.OutOfMemory: out of shared memory / HINT: 可能要調高
# max_locks_per_transaction`——這是 Postgres 全域共用鎖表的容量問題（DDL 越大張、
# 同時做的 session 越多，耗掉的鎖越多），伺服器設定不在本票範圍內，這裡改用
# session 級 advisory lock 把「建表／砍表」這段 DDL 全站序列化（測試本體——借連線、
# 跑查詢——不受影響，仍然平行），把鎖的尖峰壓回單一 session，用一點總時間換掉這個
# 錯誤（ponytail: 全站單一 advisory lock 序列化 DDL，非分片鎖；78 張表的 DDL 本身
# 很快，序列化的總時間成本可接受，鎖粒度需要調更細再升級）。
_SCHEMA_DDL_LOCK_KEY = 913042027


def _ddl(admin: psycopg.Connection, sql: str) -> None:
    admin.execute("SELECT pg_advisory_lock(%s)", (_SCHEMA_DDL_LOCK_KEY,))
    try:
        admin.execute(sql)
    finally:
        admin.execute("SELECT pg_advisory_unlock(%s)", (_SCHEMA_DDL_LOCK_KEY,))


def _search_path_dsn(schema: str) -> str:
    from urllib.parse import quote

    sep = "&" if "?" in _BASE_DSN else "?"
    return f"{_BASE_DSN}{sep}options={quote(f'-c search_path={schema},public')}"


def _reset_pool() -> None:
    if coredb._pool is not None:
        coredb._pool.close()
        coredb._pool = None


@pytest.fixture(scope="module", autouse=True)
def _module_schema(request):
    """每個測試模組一個 Postgres schema：建立→灌 baseline→把連線池指過去；
    模組結束後池子關掉、schema 整個砍掉。"""
    schema = _schema_name(request.module.__name__)

    with _admin_conn() as admin:
        _ddl(admin, (
            f'DROP SCHEMA IF EXISTS "{schema}" CASCADE;'
            f' CREATE SCHEMA "{schema}";'
            f' SET search_path TO "{schema}";'
        ) + _baseline_sql())

    _reset_pool()
    os.environ["DATABASE_URL"] = _search_path_dsn(schema)

    yield schema

    _reset_pool()
    os.environ["DATABASE_URL"] = _BASE_DSN
    with _admin_conn() as admin:
        _ddl(admin, f'DROP SCHEMA IF EXISTS "{schema}" CASCADE')


@pytest.fixture(autouse=True)
def _bound_connection():
    """repository 層測試直接呼叫 `web.conn`／`coredb.current()`（不經過
    `TestClient` 的 middleware）時，這裡幫忙先借好一條綁在這個測試函式上的連線；
    `TestClient` 請求自己另外經 middleware 借一條——两條連線落在同一個（此刻唯一
    存在的）池子，因此同一個 schema，READ COMMITTED 底下彼此提交的資料看得到。"""
    with coredb.connection() as conn:
        yield conn
