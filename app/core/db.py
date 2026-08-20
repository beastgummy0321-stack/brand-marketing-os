# -*- coding: utf-8 -*-
"""app/core/db.py — SQLite 連線工廠、帶前綴的 ID 產生器、migration runner。

見 docs/design/03-data-model.md §1（共通慣例）、§8（Migration 原則）；AGENTS.md 規則 3：
每個模組擁有自己的 migrations/ 目錄，無全域共用 schema。本檔只提供「怎麼套用一個模組的
migrations」這個通用機制，不擁有任何模組的資料表定義。
"""

import hashlib
import os
import sqlite3
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

APP_DIR = Path(__file__).resolve().parent.parent  # .../app
REPO_ROOT = APP_DIR.parent
DEFAULT_DB_PATH = REPO_ROOT / "data" / "app.db"

_CROCKFORD32 = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"


def now_iso() -> str:
    """ISO-8601 UTC 字串（03 §1：時間一律存這個格式，SQLite 無原生 datetime）。"""
    return datetime.now(timezone.utc).isoformat()


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


def get_db_path() -> Path:
    raw = os.environ.get("BRAND_OS_DB")
    return Path(raw) if raw else DEFAULT_DB_PATH


class _Rows:
    """execute() 的回傳值：已在鎖裡讀完的結果集，介面比照游標的讀取部分。

    呼叫端只用到 fetchone/fetchall/迭代/rowcount（cursor()、fetchmany、lastrowid、
    description 全站 0 處使用），所以只實作這四項。

    ponytail: 鎖裡一次 fetchall 全量取出，大 SELECT 會整批進記憶體——單機單人、資料量小，
    可接受；真的撞到記憶體再改成鎖內分批取。
    """

    __slots__ = ("_rows", "_index", "rowcount")

    def __init__(self, rows, rowcount):
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


class _LockingConnection:
    """sqlite3.Connection 包一層鎖（修憲落地 M3）：db.py 原本假設「同一時間只會有一個請求
    在動用這條連線」，等待頁改背景執行緒生成後不再成立——背景執行緒與其他請求的執行緒
    現在可能同時碰同一條全域連線。包住會進出 sqlite3 底層 C API 的方法，讓呼叫序列化，
    不留資料損毀的可能。

    execute() 必須在鎖裡就把結果讀完再回傳（回傳 _Rows，不是還沒讀完的游標）：
    只鎖 execute()、讓 fetchone/fetchall 在鎖外跑是錯的——兩條執行緒會互踩同一條連線的
    游標，讀到 None、整列 NULL、別筆資料，或直接拋 sqlite3.InterfaceError。

    ponytail: 全域單一鎖序列化寫入，不是逐表細粒度鎖——這個應用是單一使用者的原型階段、
    並行量低，真的看到吞吐瓶頸再細分（見 docs/decisions/0037 原型階段結束條件）。
    """

    def __init__(self, conn: sqlite3.Connection):
        object.__setattr__(self, "_conn", conn)
        object.__setattr__(self, "_lock", threading.RLock())

    def execute(self, *args, **kwargs):
        with self._lock:
            cursor = self._conn.execute(*args, **kwargs)
            rows = cursor.fetchall() if cursor.description is not None else []
            return _Rows(rows, cursor.rowcount)

    def executemany(self, *args, **kwargs):
        with self._lock:
            return self._conn.executemany(*args, **kwargs)

    def executescript(self, *args, **kwargs):
        with self._lock:
            return self._conn.executescript(*args, **kwargs)

    def commit(self):
        with self._lock:
            return self._conn.commit()

    def rollback(self):
        with self._lock:
            return self._conn.rollback()

    def close(self):
        with self._lock:
            return self._conn.close()

    def __getattr__(self, name):
        return getattr(self._conn, name)

    def __setattr__(self, name, value):
        setattr(self._conn, name, value)


def connect(db_path: Optional[Path] = None) -> sqlite3.Connection:
    """開一個連線：Row factory、PRAGMA foreign_keys=ON、自動建立 DB 所在目錄。

    回傳值包了一層 `_LockingConnection`（修憲落地 M3），呼叫端介面不變。
    """
    path = Path(db_path) if db_path else get_db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    # check_same_thread=False：app 全程共用同一條連線，且現在背景執行緒（等待頁生成）與
    # 請求執行緒會同時呼叫；靠上面的 _LockingConnection 序列化，不是靠這個旗標防護。
    conn = sqlite3.connect(str(path), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return _LockingConnection(conn)


def _iter_statements(script: str):
    """把一份 migration 檔的原始文字切成一條條完整敘述（修憲落地 A5）。

    用 stdlib `sqlite3.complete_statement()` 判斷斷點——它認得字串常值與註解語法，
    比天真地 `split(';')` 安全（目前 migration 檔沒有含分號的字串常值，但不該賭未來也沒有）。
    """
    statements = []
    buffer = ""
    for line in script.splitlines(keepends=True):
        buffer += line
        if buffer.strip() and sqlite3.complete_statement(buffer):
            statements.append(buffer)
            buffer = ""
    if buffer.strip():
        statements.append(buffer)
    return statements


def run_migrations(conn: sqlite3.Connection, module: str, migrations_dir: Path) -> None:
    """套用某模組 migrations/ 目錄下尚未套用的 .sql 檔，依檔名數字前綴（0001_、0002_…）排序套用。

    以 schema_migrations(module, version) 追蹤已套用版本；每個模組獨立編號、互不影響（03 §8.1）。

    交易包裹（修憲落地 A5，architecture-rules.md A6）：原本用 `conn.executescript()` 整檔下去，
    SQLite 對 DDL 的預設行為是逐句自動 commit，中途失敗會留下半套 schema、也不記版本號，
    重跑會從該檔開頭再執行一次、撞上已建好的物件而報錯。改成先明確 `BEGIN`，把整份
    migration 逐句 execute，連同 schema_migrations 的版本號寫入都包在同一個交易裡，
    失敗就整包 `ROLLBACK`（SQLite 的 DDL 可被交易復原，不像多數其他資料庫）。
    """
    conn.execute(
        """CREATE TABLE IF NOT EXISTS schema_migrations (
            module TEXT NOT NULL,
            version INTEGER NOT NULL,
            applied_at TEXT NOT NULL,
            PRIMARY KEY (module, version)
        )"""
    )
    conn.commit()
    applied = {
        row["version"]
        for row in conn.execute(
            "SELECT version FROM schema_migrations WHERE module = ?", (module,)
        )
    }
    for path in sorted(migrations_dir.glob("*.sql")):
        version = int(path.name.split("_", 1)[0])
        if version in applied:
            continue
        script = path.read_text(encoding="utf-8")
        conn.execute("BEGIN")
        try:
            for statement in _iter_statements(script):
                conn.execute(statement)
            conn.execute(
                "INSERT INTO schema_migrations (module, version, applied_at) VALUES (?, ?, ?)",
                (module, version, now_iso()),
            )
        except Exception:
            conn.rollback()
            raise
        else:
            conn.commit()


def migration_manifest_path() -> Path:
    """已落地 migration 檔的內容雜湊清單（修憲落地 A5，architecture-rules.md A6：
    「migration 落地後不得再編輯，修正一律開新的 migration」）。"""
    return APP_DIR / "core" / "migration_manifest.json"


def compute_migration_hashes() -> dict:
    """回傳目前所有模組 migrations/ 目錄下 .sql 檔的內容雜湊，key 為 `模組/檔名`。

    供 `migration_manifest.json` 比對：任何已落地檔案的雜湊變了就代表被改過（改動即 FAIL）；
    新增 migration 檔時，manifest 要在同一個 commit 一併補上該檔的雜湊。
    """
    hashes = {}
    for module, migrations_dir in MODULE_MIGRATIONS:
        for path in sorted(migrations_dir.glob("*.sql")):
            hashes[f"{module}/{path.name}"] = hashlib.sha256(path.read_bytes()).hexdigest()
    return hashes


# Phase 0 模組清單：純粹是啟動時「依序套用哪些模組的 migrations」的清單，
# 不是共用 schema——每個模組仍擁有自己的 migrations/ 目錄與表定義（AGENTS.md 規則 3）。
# 之後新模組要上線時，把自己的 (module_name, migrations_dir) 加進來即可；
# 也可以不經過這裡，直接呼叫 run_migrations(conn, "自己的模組名", 自己的目錄)。
MODULE_MIGRATIONS = [
    ("core", APP_DIR / "core" / "migrations"),
    ("brand_intelligence", APP_DIR / "brand_intelligence" / "migrations"),
    ("intake", APP_DIR / "intake" / "migrations"),
    ("ads", APP_DIR / "ads" / "migrations"),
    ("orders", APP_DIR / "orders" / "migrations"),
]


def migrate_all(conn: sqlite3.Connection) -> None:
    for module, migrations_dir in MODULE_MIGRATIONS:
        run_migrations(conn, module, migrations_dir)


def connect_and_migrate(db_path: Optional[Path] = None) -> sqlite3.Connection:
    """方便啟動 / 測試用：開連線後立刻套用目前已知的所有模組 migrations。"""
    conn = connect(db_path)
    migrate_all(conn)
    return conn
