"""app/core/db.py — 單一資料存取進入點（ADR 0027：Supabase Postgres，原生 SQL，不用 ORM）。

集裝箱憲章 §1 邊界定案：
1. 對外進入點：本檔（`app/core/db.py`）。
2. 進出形狀：見下方 public 函式群——`dsn()`/`pool()`/`connection()`/`current()`/
   `ConnProxy`/`now_utc()`/`now_iso()`/`jsonb()`/`new_id()`/`DEV_ORG_ID`。其餘一律私有。
3. 呼叫端：全站經 `app.shared.web.conn`（`ConnProxy`，350 處呼叫點不動）與直接
   `from app.core import db` 的模組。
4. 不碰什麼：`app/*/migrations/*.sql`、任何 `repository.py`、任何 SQL 字面、
   本票新增測試以外的任何測試檔。

票 02-1（原本的 SQLite 連線工廠／migration runner 版本）改寫：一條連線一個 request／
一個背景工作（`connection()` 用 contextvar 綁定），不再是全程共用同一條連線。
Migration 交給 Supabase CLI 管（`supabase/migrations/`，02-2 落地內容），本檔不再
擁有 migration runner。
"""

import json
import logging
import os
import time
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from psycopg_pool import ConnectionPool

logger = logging.getLogger(__name__)

# 不在票 02-1 的刪除清單裡：好幾個模組（app/ads/meta_mcp.py、app/intake/state.py、
# app/llm/methodology.py、app/brand_web/routes_library.py）在 import 時就從這裡拿
# REPO_ROOT／APP_DIR 當路徑基準（跟 migration/sqlite 無關），刪了會炸掉它們的 import，
# 牽連 app.shared.web——這兩個常數留著。
APP_DIR = Path(__file__).resolve().parent.parent  # .../app
REPO_ROOT = APP_DIR.parent

_CROCKFORD32 = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"

DEV_ORG_ID = "org_dev"  # ADR 0027 D2a: placeholder until slice 3 (identity) binds org from JWT


def now_utc() -> datetime:
    """tz-aware UTC 現在時刻（D1a：寫入 `*_at`/`*_date` 欄位一律傳 datetime/date，不傳字串）。"""
    return datetime.now(UTC)


def now_iso() -> str:
    """ISO-8601 UTC 字串——只給 API JSON 輸出用（02-3b：不再寫入 `*_at` 欄位，改用 now_utc()）。"""
    return now_utc().isoformat()


def _json_default(value):
    """`jsonb()` 的序列化安全網：站內幾乎每個 `row` dict 都同時拿去組 SQL 參數（datetime／
    Decimal 原生值）跟丟進 `write_audit(before=row, after=row)`（整包再包一次 jsonb）——
    這裡補上 datetime/date → ISO 字串、Decimal → float，跟 `app/shared/web.py
    to_json_value()` 是同一組轉換規則，只是這裡管的是「寫進 DB 的 jsonb」而不是「回應給
    瀏覽器的 JSON」。02-3b 跑 demo() 自檢時 target_cpa.py 的 write_audit(after=row) 實測
    炸過一次（row 裡的 created_at 是 datetime），才補的這道網。"""
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    raise TypeError(f"Object of type {type(value).__name__} is not JSON serializable")


def jsonb(value):
    """包一層 `psycopg.types.json.Jsonb`，寫 jsonb 欄位用，取代 json.dumps（02-3b）。"""
    return Jsonb(value, dumps=lambda v: json.dumps(v, ensure_ascii=False, default=_json_default))


def new_id(prefix: str) -> str:
    """帶類型前綴的 ULID 風格 id（03 §1）：48-bit 毫秒時間戳 + 80-bit 亂數，Crockford Base32。

    不追求嚴格符合 ULID 規格（例如首字元溢位處理），只要求可排序、可辨識實體類型、
    不洩漏筆數／順序——「一個小產生器足矣，非重型設計」（03 §1）。
    """
    value = ((time.time_ns() // 1_000_000) << 80) | int.from_bytes(os.urandom(10), "big")
    chars = []
    for _ in range(26):
        chars.append(_CROCKFORD32[value & 0x1F])
        value >>= 5
    return f"{prefix}_{''.join(reversed(chars))}"


def dsn() -> str:
    """Postgres 連線字串：`DATABASE_URL`，預設本機 Supabase（`supabase start` 開的那個）。"""
    return os.environ.get(
        "DATABASE_URL", "postgresql://postgres:postgres@127.0.0.1:54322/postgres"
    )


class _Rows:
    """execute() 的回傳值：已經讀完的結果集，介面比照游標的讀取部分。

    呼叫端只用到 fetchone/fetchall/迭代/rowcount，所以只實作這四項。
    """

    __slots__ = ("_rows", "_index", "rowcount")

    def __init__(self, rows: list, rowcount: int):
        self._rows = rows
        self._index = 0
        self.rowcount = rowcount

    def fetchone(self):
        if self._index >= len(self._rows):
            return None
        self._index += 1
        return self._rows[self._index - 1]

    def fetchall(self):
        rest = self._rows[self._index:]
        self._index = len(self._rows)
        return rest

    def __iter__(self):
        return iter(self.fetchall())


class Conn:
    """`psycopg.Connection` 的薄包裝，`row_factory=dict_row`，維持舊呼叫端的介面契約：

    - `execute(sql, params=()) -> _Rows`：鎖裡（psycopg 遊標本身序列化）讀完整批再回傳。
      每一列是 dict，`row["col"]` 可用；`row[0]` 位置存取不支援（02-3 清掉那些用法）。
    - `executemany(sql, seq)`、`commit()`、`rollback()`、`close()`（close 是 no-op，連線
      生命週期歸連線池管，不由呼叫端關）。
    """

    __slots__ = ("_pg", "_tenant_org_id")

    def __init__(self, pg_conn: "psycopg.Connection"):
        self._pg = pg_conn
        self._tenant_org_id: str | None = None

    def execute(self, sql, params: Sequence = ()) -> _Rows:
        cur = self._pg.execute(sql, params)
        rows = cur.fetchall() if cur.description is not None else []
        return _Rows(rows, cur.rowcount)

    def executemany(self, sql, seq) -> None:
        with self._pg.cursor() as cur:
            cur.executemany(sql, seq)

    def commit(self) -> None:
        self._pg.commit()

    def rollback(self) -> None:
        """ADR 0052 clause 5: a `SET ROLE` issued inside a transaction that is then
        rolled back is undone (measured on this machine, see the R3c ticket). The
        switch commits immediately in `set_tenant_scope()`, which protects it against
        any *later*, separate rollback -- but that commit cannot protect a switch that
        is still part of the same open transaction when a rollback happens (e.g. the
        commit is skipped or delayed for any reason). Re-assert the recorded scope
        here so a rollback can never silently leave the connection unscoped or on the
        wrong org -- the RLS-silently-off failure mode this whole ticket exists to
        close.
        """
        self._pg.rollback()
        if self._tenant_org_id is not None:
            self._pg.execute("SET ROLE authenticated")
            self._pg.execute(
                "SELECT set_config('app.org_id', %s, false)", (self._tenant_org_id,)
            )
            self._pg.commit()

    def close(self) -> None:
        logger.debug("Conn.close() is a no-op; the pool owns connection lifetime")


_pool: ConnectionPool | None = None
_current: ContextVar["Conn"] = ContextVar("db_current_conn")


def _reset_pooled_connection(pg_conn: "psycopg.Connection") -> None:
    """ADR 0052 clause 4 -- the single most important line in the R3c ticket: a
    connection returning to the pool must never hand the next request the previous
    request's role or org claim. `psycopg_pool.ConnectionPool`'s `reset=` callback
    (psycopg_pool/pool.py:54) runs on every return, after any dirty transaction has
    already been rolled back (`_reset_connection`, pool.py:783) -- so this only needs
    to clear session-level state and commit; a connection this leaves in a bad status
    is discarded by the pool rather than handed on (pool.py:810-816).
    """
    pg_conn.execute("RESET ROLE")
    pg_conn.execute("RESET app.org_id")
    pg_conn.commit()


def pool() -> ConnectionPool:
    """模組層單例，惰性建立（第一次呼叫才真的開連線池）。"""
    global _pool
    if _pool is None:
        _pool = ConnectionPool(
            dsn(),
            min_size=1,
            max_size=10,
            kwargs={"row_factory": dict_row},
            open=True,
            reset=_reset_pooled_connection,
        )
    return _pool


@contextmanager
def connection() -> Iterator[Conn]:
    """跟連線池借一條連線、綁到這個 request／背景工作的 contextvar。

    `pool().connection()` 本身就是「乾淨結束 commit、例外 rollback、結束歸還連線池」
    （psycopg_pool 的 `with conn:` 語意），這裡只是多包一層 contextvar 綁定，讓
    `current()`／`ConnProxy` 能在同一個 request／工作裡查到「這條」連線。
    """
    with pool().connection() as pg_conn:
        conn = Conn(pg_conn)
        token = _current.set(conn)
        try:
            yield conn
        finally:
            _current.reset(token)


def current() -> Conn:
    """這個 request／背景工作綁定的連線；在 `connection()` 之外呼叫是程式錯誤。"""
    try:
        return _current.get()
    except LookupError:
        raise RuntimeError("no connection bound; use db.connection()")


def set_tenant_scope(conn: Conn, org_id: str) -> None:
    """ADR 0052: switch this connection to role `authenticated` with the `app.org_id`
    claim set to `org_id`, for the rest of this request/job. Called once, from
    `require_actor()` (`app/shared/web.py`), right after the actor is known -- never
    from `app/identity/`, which stays unscoped on purpose (see the ADR's identity
    section).

    Commits immediately: an uncommitted `SET ROLE` is undone by the next rollback,
    silently (measured, see the ticket) -- RLS would go silently off with every gate
    still green. `Conn.rollback()` re-applies the org recorded here if a rollback ever
    catches the switch before this commit lands.
    """
    conn.execute("SET ROLE authenticated")
    conn.execute("SELECT set_config('app.org_id', %s, false)", (org_id,))
    conn._tenant_org_id = org_id
    conn.commit()


class ConnProxy:
    """`execute`/`executemany`/`commit`/`rollback`/`close` 一律轉發給 `current()`。

    `app.shared.web.conn` 綁的就是這個物件——呼叫端寫法不變（`web.conn.execute(...)`），
    但每次呼叫都即時查「這個 request 綁的是哪條連線」，不像舊版全程共用同一條。
    """

    def execute(self, sql, params: Sequence = ()) -> _Rows:
        return current().execute(sql, params)

    def executemany(self, sql, seq) -> None:
        return current().executemany(sql, seq)

    def commit(self) -> None:
        return current().commit()

    def rollback(self) -> None:
        return current().rollback()

    def close(self) -> None:
        return current().close()
