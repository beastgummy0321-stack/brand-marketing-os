"""app/background/__init__.py — single entry point (container contract §1, ticket schedule-01).

集裝箱憲章 §1 邊界定案：
1. 對外進入點：本檔（`app/background/__init__.py`）。
2. 進出形狀：`app() -> procrastinate.App`（無參數，回傳可用來
   `.configure_task(name).defer(org_id=..., ...)` 或 `.run_worker(...)` 的 procrastinate App
   物件）。其餘一律私有。
3. 呼叫端：目前只有本模組自己的測試檔與手動 done-check；05-1（`enqueue`/`status`/`cancel`
   契約、job 註冊表、正式 worker 進場點）落地後才會有真正的產品呼叫端。
4. 不碰什麼：procrastinate 套件內部（`procrastinate.schema`／`procrastinate.cli` 等）——本檔
   ／本模組永遠不呼叫 `procrastinate schema --apply`；schema 已經 vendor 進
   `supabase/migrations/20260829000001_background_baseline.sql`，由 Supabase CLI 管，跟全站
   其他模組一樣，但落在自己的 `<current_schema()>__queue` 命名空間裡（ADR 0038），不是這個
   process 平常讀寫資料的 schema。

ADR 0038（round 2 補丁）：procrastinate 的四張表沒有 `org_id`，也不會加——加了也沒有任何
程式碼會填它、會拿它篩選，是看起來像隔離、其實不是隔離的裝飾欄位（見 ADR 全文）。它們活在
獨立的 Postgre schema `<caller 的 current_schema()>__queue` 裡（`public__queue`／
`t_<module>_<pid>__queue`），不在資料模型的 schema 裡，所以 Gate A
（`app/tests/test_org_isolation_all_tables.py`）根本掃不到它們——不是被排除，是從來不在它
的掃描範圍內。租戶邊界改由 rule 5 顧：job 屬於哪個組織寫在它自己的 `args`
（`org_id` 是每個註冊 task 的必要參數，見 `_noop()` 與
`app/tests/test_background.py` 的 `TaskSignatureOrgIdGateTest`），由 handler 執行時自己認。

DSN／schema 都延遲解析（票 schedule-01 點名的 hazard，round 2 加碼）：procrastinate 的
`PsycopgConnector` 在建構當下就把 `conninfo` 存死，`app/tests/conftest.py` 每個測試模組會
重寫 `DATABASE_URL`（換一個 schema）——`app()` 每次呼叫都比對「這次 `db.dsn()` 是不是換
了」，換了就整顆丟掉重建：借 `app.core.db.pool()` 開一條連線問一次「現在的
`current_schema()` 是哪個」，組出 `<那個 schema>__queue` 當作 procrastinate 連線唯一的
`search_path`（不帶 `public` 墊底）。比 `app/core/db.py` 的 `pool()` 多這一步比對，是因為
`db.pool()` 靠 conftest 主動呼叫 `_reset_pool()` 砍掉重來，這裡沒有對應的 reset hook。

只讓 `search_path` 剛好指到那一個 queue schema（不含 `public`），額外消掉了 round 1 踩到的
`AmbiguousFunction`：procrastinate 自訂的 enum type／function 一旦真的只在一個 schema
的 search_path 上出現，Postgres 就不用在兩份同名但不同 OID 的型別之間做 overload 消歧義，
不必再讓呼叫端自己把 `DATABASE_URL` 的 `search_path` 縮到單一 schema。

Windows 專屬修正：procrastinate 的 worker 走 psycopg 的 async 連線（`PsycopgConnector`），
而 psycopg 的 async 模式不支援 Windows 預設的 `ProactorEventLoop`（實測 `run_worker()` 內部
`asyncio.run()` 直接炸 `PoolTimeout`）——這是 psycopg 官方文件點名的已知限制，不是本票發明
的猜測，修法是 import 這個模組時就把行程的 event loop policy 換成
`WindowsSelectorEventLoopPolicy`（`sys.platform` 判斷，非 Windows 平台不動）。
"""

import asyncio
import sys
from urllib.parse import quote, urlsplit, urlunsplit

import procrastinate

from app.core import db

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

_app: procrastinate.App | None = None
_app_dsn: str | None = None


def _noop(org_id: str) -> None:
    """票 schedule-01 要求的「一個瑣碎 deferred job」——不做任何事。`org_id` 是必要參數
    （ADR 0038「這份 ADR 欠的閘門」）：不使用它，只證明每個註冊 task 的簽名都留了放組織 id
    的位置，機器閘門見 `app/tests/test_background.py:TaskSignatureOrgIdGateTest`。"""


def _queue_search_path() -> str:
    """借 `db.connection()` 開一條連線問一次現在的 `current_schema()`，回傳它專屬的 queue
    schema 名稱（`db.connection()` 是借池子裡另一條連線、可以安全疊在既有連線之上）。"""
    with db.connection() as conn:
        row = conn.execute("SELECT current_schema()").fetchone()
        assert row is not None  # SELECT current_schema() always returns exactly one row
        schema = row["current_schema"]
    return f"{schema}__queue"


def _with_search_path(dsn: str, schema: str) -> str:
    """把 `dsn` 的 `search_path` option 換成只指這一個 schema（不帶 `public` 墊底）。"""
    parts = urlsplit(dsn)
    options = f"options={quote(f'-c search_path={schema}')}"
    return urlunsplit((parts.scheme, parts.netloc, parts.path, options, ""))


def app() -> procrastinate.App:
    """惰性建立 App；`db.dsn()` 換了就重建（連帶重新推導 queue schema，見上方 docstring）。"""
    global _app, _app_dsn
    current_dsn = db.dsn()
    if _app is None or _app_dsn != current_dsn:
        queue_dsn = _with_search_path(current_dsn, _queue_search_path())
        new_app = procrastinate.App(connector=procrastinate.PsycopgConnector(conninfo=queue_dsn))
        new_app.task(name="background.noop")(_noop)
        _app = new_app
        _app_dsn = current_dsn
    return _app
