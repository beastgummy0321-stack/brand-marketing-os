"""app/background/__init__.py — single entry point (container contract §1, ticket schedule-01).

集裝箱憲章 §1 邊界定案：
1. 對外進入點：本檔（`app/background/__init__.py`）。
2. 進出形狀：`app() -> procrastinate.App`（無參數，回傳可用來
   `.configure_task(name).defer(org_id=..., ...)` 或 `.run_worker(...)` 的 procrastinate App
   物件），加上票 05 fix round 補的 `start_worker()`／`stop_worker()`（都是 async、無參數，
   見下方函式檔頭）。其餘一律私有。
3. 呼叫端：`app()` 目前只有本模組自己的測試檔、app/meta（掛 task）與手動 done-check；
   `start_worker()`／`stop_worker()` 目前只有 app/main.py 的 FastAPI lifespan
   （啟動／關閉各呼叫一次）與本模組自己的測試檔。05-1（`enqueue`/`status`/`cancel` 契約、
   job 註冊表）落地後才會有更多產品呼叫端。
4. 不碰什麼：procrastinate 套件內部（`procrastinate.schema`／`procrastinate.cli` 等）——本檔
   ／本模組永遠不呼叫 `procrastinate schema --apply`；schema 已經 vendor 進
   `supabase/migrations/20260829000001_background_baseline.sql`，由 Supabase CLI 管，跟全站
   其他模組一樣，但落在自己的 `<current_schema()>__queue` 命名空間裡（ADR 0038），不是這個
   process 平常讀寫資料的 schema。

票 05 fix round：review 打回「排程不能只靠人手動跑」（done-check「A scheduled pull runs
unattended」）。原本的判斷是「加一個常駐 worker process 是部署形態決定，CLAUDE.md 規則 9
要先提案批准」——但這不必是「加一個新 process」：`啟動行銷系統.bat` 起的 uvicorn 本來就是
唯一持續運行的東西，procrastinate 官方文件本身就替「把 worker 掛進一個更大的既有應用程式
裡跑」這個用法點名了 `install_signal_handlers=False` 這個參數（見 `start_worker()`
docstring）。讓這個既有 process 多做一件事，不是新開一個部署形態，是加法，符合規則 6
「手動路徑永遠一級公民；自動化是加法」——`python -m app.meta.daily_pull` 手動觸發路徑原封
不動留著。

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
_worker_task: asyncio.Task | None = None
_worker_app: procrastinate.App | None = None  # 跟 _worker_task 成對開／關，見 start/stop_worker()


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


async def start_worker() -> None:
    """把這個 process 掛成 procrastinate worker（票 05 fix round，見檔頭「為什麼不是新開
    一個部署形態」）。冪等——再呼叫一次，已經在跑就直接回傳，不會開出第二個 worker task。

    `install_signal_handlers=False`：procrastinate 官方文件替這個確切用法點名的參數
    （"if you run the work as an async task in a bigger application"）——worker 跑在
    uvicorn 自己的 event loop 上，不是獨立的主程序，裝自己的訊號處理只會跟 uvicorn 原本的
    Ctrl+C／SIGTERM 處理打架，甚至在非主執行緒（測試用的 TestClient portal）直接炸掉。
    """
    global _worker_task, _worker_app
    if _worker_task is not None and not _worker_task.done():
        return
    _worker_app = app()
    await _worker_app.open_async()  # run_worker_async 需要連線池先開好，不開會炸 AppNotOpen
    _worker_task = asyncio.create_task(
        _worker_app.run_worker_async(install_signal_handlers=False))


async def stop_worker() -> None:
    """FastAPI lifespan 關閉時呼叫：取消 `start_worker()` 開的 task 並等它真的收尾，關掉
    對應那個連線池，不留一個游離的背景 task或開著的連線。沒在跑就直接回傳。"""
    global _worker_task, _worker_app
    if _worker_task is None:
        return
    task, worker_app = _worker_task, _worker_app
    _worker_task = None
    _worker_app = None
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass
    if worker_app is not None:
        await worker_app.close_async()
