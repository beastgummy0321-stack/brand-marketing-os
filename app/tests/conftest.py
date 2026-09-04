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

# 票 03-1：測試預設走 dev token（BRAND_OS_ENV=local，app.core.config.settings() 開機
# 檢查才不會 RuntimeError——ADR 0062，這道檢查原本住在 app.identity.register()，票
# 02-env-flag-and-settings 搬過去的）。放在任何 app.* import 之前——app.main 組裝時
# 就會呼叫一次 settings()。IDENTITY_ALLOW_HS256／SUPABASE_JWT_SECRET 是另一條測試路徑
# （手動 mint HS256 token 驗 JWKS 以外的驗簽路徑），見 test_identity_auth.py。
os.environ.setdefault("BRAND_OS_ENV", "local")
os.environ.setdefault("SUPABASE_URL", "http://127.0.0.1:54321")
os.environ.setdefault("IDENTITY_DEV_TOKEN", "test-dev-token")
os.environ.setdefault("IDENTITY_ALLOW_HS256", "1")
# 票 storage-01：app.storage 打 Storage REST API 需要 service-role key。這是 Supabase CLI
# 本機開發固定發的 demo JWT（`supabase status` 印出來的那把），不是真的憑證，所以在這裡
# setdefault 不違反 app/main.py:73「測試程序不該拿到真金鑰」的規則。
os.environ.setdefault(
    "SUPABASE_SERVICE_ROLE_KEY",
    "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZS1kZW1vIiwicm9sZSI6InNlcnZpY2Vf"
    "cm9sZSIsImV4cCI6MTk4MzgxMjk5Nn0.EGIM96RAZx35lJzdJsyH-qQwv8Hdp7fsn3W0YpN81IU",
)
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


# ADR 0038：procrastinate 的表不住在模組 schema 裡，住在隔壁的 `<模組 schema>__queue`。
# 這個後綴有三份，SQL 那份無法 import Python，所以只能各寫各的：
# `supabase/migrations/20260829000001_background_baseline.sql`（`current_schema() || '__queue'`）、
# `app/background/__init__.py:_queue_search_path()`、這裡。改一個要改三個。
#
# 為什麼下面建/砍 schema 兩處都要連它一起砍：`_schema_name()` 用 `os.getpid()` 當後綴，
# 而 pid 作業系統會回收再發。以前只砍模組 schema、沒砍 queue schema，殘留的 queue schema
# 就一直堆在資料庫裡（實測 2026-08-29：499 個殘留，150 個不重複 pid，最兇的一個 pid 被 15
# 個不同模組用過）。下一輪同 pid＋同模組＝同名，migration 那句 `CREATE SCHEMA IF NOT EXISTS`
# 看到房還在就直接跳過，接著 `CREATE TYPE procrastinate_job_status` 撞上上一輪留下的同名
# type，噴 DuplicateObject。這就是「全套平行測試隨機紅」的成因（docs/tech-debt.md 第四節）。
_QUEUE_SUFFIX = "__queue"


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
            f' DROP SCHEMA IF EXISTS "{schema}{_QUEUE_SUFFIX}" CASCADE;'
            f' CREATE SCHEMA "{schema}";'
            f' SET search_path TO "{schema}";'
        ) + _baseline_sql())

    _reset_pool()
    os.environ["DATABASE_URL"] = _search_path_dsn(schema)

    yield schema

    _reset_pool()
    os.environ["DATABASE_URL"] = _BASE_DSN
    with _admin_conn() as admin:
        _ddl(admin, (
            f'DROP SCHEMA IF EXISTS "{schema}" CASCADE;'
            f' DROP SCHEMA IF EXISTS "{schema}{_QUEUE_SUFFIX}" CASCADE;'
        ))


@pytest.fixture(autouse=True)
def _fresh_settings():
    """票 02-env-flag-and-settings：`app.core.config.settings()` 是行程層快取的單例
    （ADR 0062——正式環境「開機驗一次」才有意義），但這裡一堆既有測試靠切換
    `os.environ`（`ANTHROPIC_API_KEY`／`BRAND_OS_TODAY`……）在同一個 worker process
    裡看到不同結果（例：`test_settings_api.py` 逐個測試方法切換 `ANTHROPIC_API_KEY`）。
    每個測試開始前清一次快取，等於幫測試恢復「每次呼叫都讀最新 os.environ」的舊行為；
    正式環境只有 `app.main` import 時碰一次，不受影響——只有這支測試 fixture 會呼叫
    `cache_clear()`。`DATABASE_URL` 不靠這支：`coredb.dsn()` 是 `config.database_url()`
    （ADR 0062 §5a），每次呼叫都直接讀 `os.environ`，不經過這顆快取，所以跟
    `_bound_connection` 誰先跑無關（也因此不塞進同一支）。獨立於 `_bound_connection` 之外
    還有第二個理由：`test_core_db_pool.py` 會整支蓋掉 `_bound_connection`，這支不能跟著
    被蓋掉。"""
    from app.core.config import settings

    settings.cache_clear()
    yield


@pytest.fixture(autouse=True)
def _bound_connection():
    """repository 層測試直接呼叫 `web.conn`／`coredb.current()`（不經過
    `TestClient` 的 middleware）時，這裡幫忙先借好一條綁在這個測試函式上的連線；
    `TestClient` 請求自己另外經 middleware 借一條——两條連線落在同一個（此刻唯一
    存在的）池子，因此同一個 schema，READ COMMITTED 底下彼此提交的資料看得到。"""
    with coredb.connection() as conn:
        yield conn
