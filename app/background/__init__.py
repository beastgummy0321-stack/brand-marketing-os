"""app/background/__init__.py — single entry point (container contract §1, ticket schedule-01,
票 05-1 補 `enqueue()`)。

集裝箱憲章 §1 邊界定案：
1. 對外進入點：本檔（`app/background/__init__.py`）。`app/worker.py`——worker 本身跑的那個
   process（ADR 0063）——不是本模組的一部分：它掛在組裝根旁邊，因為起 worker 需要組裝根
   的 task registration，而 `app/background` 永遠不可以往上 import。
2. 進出形狀：`app() -> procrastinate.App`（無參數，回傳可用來
   `.configure_task(name).defer(org_id=..., ...)` 或 `.run_worker(...)` 的 procrastinate App
   物件），加上票 05-1 補的
   `enqueue(task_name, *, org_id, lock, **kwargs) -> bool`（見下方函式檔頭：defer 一個 job，
   同一個 `lock` 已經有一個在 `todo` 狀態排隊時回 False，不拋例外），再加上票
   08-standalone-jobs-on-the-queue round 2 補的 `is_active(lock: str) -> bool`（見下方函式
   檔頭：這個 `queueing_lock` 名下還有列在 `todo` 或 `doing`）。F15 另提供
   `recover_interrupted_jobs(*, retry_tasks=None, fail_tasks=None, limit=100) -> dict`，
   僅供持有 schema worker 鎖的組裝根在啟動時回收中斷的孤兒工作（規則見
   `app/background/recovery.py` 檔頭：唯讀工作照舊重送、其餘重送一次、第二次中斷標失敗）。
   F29-I05 另提供唯讀的 `queue_snapshot(*, since) -> dict`（整條佇列的排隊順序與今天
   做完／失敗數，呼叫端目前只有 `app/dashboard/routes_jobs_api.py`）。F31-I02（Contract J）
   另提供唯讀的 `job_outcome(lock) -> "active"|"failed"|"succeeded"|None`（這個 lock 最新
   一個 job 的結局），供 `app/intake`／`app/brand_web` 的狀態端點判斷。
   F50-I07（feature F50 Contract J，one background outcome）另提供：
   `register(name, func, *, cron=None, periodic_id=None)`——全站唯一的 task 註冊方式（冪等）；
   handler 回傳 `Empty(code, text)` 記 `empty`、回傳 `Failed(code, text)` 或拋
   `JobFailed(code, text)` 記 `failed` 並讓 procrastinate 把 job 記成失敗（小鈴鐺的
   `failed_today` 因此算得到）、其他例外記 `failed`／`unexpected` 後原樣往上丟、一般回傳記
   `done`；結局寫進 `background_job_result`（每個 (org_id, lock) 留最新一次）。
   `outcome(lock) -> {state, code, text, finished_at, started_at} | None` 讀它；
   `job_state(lock, llm_row) -> {status, started_at, error}` 是各狀態端點共用的讀法，
   沒有 job 也沒有列時是 `unknown`／`started_at: None`（不編一個「現在」）。
   `job_outcome()` 只剩一層轉接，等最後一個呼叫端搬走。其餘一律私有。
3. 呼叫端：`app()` 目前是本模組自己的測試檔、app/meta（掛 task）、app/schedule（
   `register_tasks()` 掛三個生成 task）與 `app/worker.py`（起 worker 前先建，ADR 0063）；
   `enqueue()` 目前是 app/schedule/routes.py（三支 POST 端點）與本模組自己的測試檔；
   `is_active()` 目前是 `app/brand_web/routes_products.py`（再次調研）、
   `app/brand_web/routes_report_api.py`（報告生成）與本模組自己的測試檔。
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
而 psycopg 的 async 模式不支援 Windows 預設的 `ProactorEventLoop`——這是 psycopg 官方文件
點名的已知限制。修法是 import 這個模組時就把行程的 event loop policy 換成
`WindowsSelectorEventLoopPolicy`（`sys.platform` 判斷，非 Windows 平台不動）。

ADR 0063：worker 現在是自己的 process（`python -m app.worker`），跑在自己的主執行緒、自己
的 loop 上——`asyncio.run()` 照 policy 建 loop，這裡在 import 時換的 policy 才真的生效。
worker 起不來也不再需要吞掉例外保護網站：它不是網站的一部分，允許在自己的視窗裡大聲炸掉
（ADR 0039 那句「worker 起不來不准把網站一起弄死」現在是結構上自動成立，不必再靠這個
模組吞例外）。

票 05-1：`enqueue()` 為什麼要蓋第二個 App（不是重用 `app()`）——`app()` 是一顆
`PsycopgConnector`，它的 async pool 是 `app/worker.py` 呼叫 `App.run_worker()` 時，在 worker
process 自己的主 loop 上開的（ADR 0063）。`PsycopgConnector.get_sync_connector()` 只要那顆
async pool 是開的就回傳
`self`（`.venv/Lib/site-packages/procrastinate/psycopg_connector.py:110-112`），而在一顆
async connector 上呼叫任何 sync 方法都會走 `utils.async_to_sync`
（`connector.py:107-118`）——它會另開一個**新的** event loop 去跑那個 coroutine，等於拿一顆
綁在別的執行緒的 loop 上的 psycopg pool，硬塞進這個新 loop 裡用。從 request 執行緒（FastAPI
的 loop）呼叫 `app().configure_task(...).defer(...)` 就是這個模式，會炸。所以 `enqueue()`
另外蓋一顆獨立、模組私有的 `procrastinate.App`，接的是
`procrastinate.SyncPsycopgConnector(conninfo=<跟 app() 一樣的 queue DSN>)`——這顆 connector
本來就是同步的，沒有「借別的 loop 的 pool」這個問題。DSN 換了照 `app()` 同一套規則整顆重建
（見上面「DSN／schema 都延遲解析」那段）。它不需要註冊任何 task——`App.configure_task()`
預設 `allow_unknown=True`（procrastinate `app.py:209-211`），沒註冊過的任務名一樣 defer
得出去；真正的 task body 只在 `app()`（worker 用的那顆）上註冊，見 `app/schedule/jobs.py`
`register_tasks()`。

`queueing_lock` 的唯一索引只擋 `WHERE status = 'todo'`
（`supabase/migrations/20260829000001_background_baseline.sql:148`），`enqueue()` 因此只
擋得住「連按兩次、worker 都還沒撿走第一個」這個窗口。一個任務已經被 worker 撿走
（procrastinate 的 `status = 'doing'`）之後、到它自己的 handler 真正打錢之前，還有一段
`llm_task` 完全看不見的窗口——`app/llm/gateway.py` 的 `running` 列要等 provider 呼叫前一刻
才寫（round 1 上線後被獨立審查抓到：第二次按下去落在這個窗口，兩邊都真的付了錢，見票
08-standalone-jobs-on-the-queue「Blocked」節）。`is_active()`（round 2）補的就是這一段：
直接問 procrastinate 自己的 `procrastinate_jobs`（`job_manager.list_jobs()`，跟它自己的
shell `list_jobs`／`list_locks` 指令同一個公開 API，不是繞過它自建 SQL），這個
`queueing_lock` 名下還有列卡在 `todo` 或 `doing`，就代表這件事還沒結束——擋不擋、擋完
回什麼狀態碼，仍然是呼叫端的事（`app/schedule/routes.py`／`app/brand_web/routes_products.py`
／`app/brand_web/routes_report_api.py` 各自的 409／400），這裡只負責回答問題。

F47 Contract C (worker liveness): `queue_snapshot()` also answers "is any worker alive" —
`worker_alive` is True when some `procrastinate_workers` row has `last_heartbeat` within
`WORKER_HEARTBEAT_STALE_SECONDS` (60 s; procrastinate heartbeats about every 10 s), read with one
query on the same queue connection; memory-queue mode reads True (jobs never run there by
design, nothing is "stopped"). `GET /api/jobs/active` turns it into `stalled` for one org, and
every page that waits on a job shows one notice while it is stalled. A stale row left by a
killed worker is just old — only a fresh heartbeat counts.

Commit before enqueue (F47 Contract C): a caller writes and **commits** the rows a job will read
before it calls `enqueue()`. `enqueue()` defers on its own connection, so a worker may pick the
job up the instant it is deferred; rows still uncommitted on the request's connection are
invisible to it (drill 10 W4: 「找不到工單」 from `app/workbench/repository.py`).

記憶體佇列模式（`BRAND_OS_JOB_QUEUE=memory`，e2e 後端專用，F06-I05）：開發用資料庫的
`public__queue` 是共用的——使用者自己一直開著的 `python -m app.worker`（真 Codex、舊程式）
會從那裡撿走 e2e 建出來的 job 去跑，8720 的環境變數碰不到那支獨立行程。這個模式下
`enqueue()`／`is_active()` 完全不碰 procrastinate、不寫任何一列：job 永遠不會執行。e2e 本來
就只斷言「沒有 worker 也成立」的行為（F02 Decisions），job 不跑正是它宣稱的前提。由
`app/core/config.py` 的 `_FORBIDDEN_VALUES_OUTSIDE_LOCAL` 擋住，只有 `BRAND_OS_ENV=local`
才能設。
"""

import asyncio
import functools
import inspect
import logging
import re
import sys
from collections.abc import Callable, Collection
from dataclasses import dataclass
from datetime import UTC, datetime

import procrastinate
from procrastinate.exceptions import AlreadyEnqueued
from psycopg.conninfo import conninfo_to_dict, make_conninfo

from app.core import config, db

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

_log = logging.getLogger(__name__)

_app: procrastinate.App | None = None
_app_dsn: str | None = None
_sync_app: procrastinate.App | None = None  # 票 05-1：enqueue() 專用，見模組檔頭
_sync_app_dsn: str | None = None
_memory_locks: set[str] = set()  # 記憶體佇列模式（F06-I05）：只記 lock，job 永遠不真的跑


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
    """Preserve URL/keyword conninfo and other options; the last search_path wins.

    PostgreSQL options use backslash-escaped whitespace, not shell quoting. The value
    itself is a quoted SQL identifier, so spaces, commas and quotes stay one schema.
    """
    params = conninfo_to_dict(dsn)
    identifier = '"' + schema.replace('"', '""') + '"'
    option = re.sub(r"([\\\s])", r"\\\1", f"search_path={identifier}")
    options = f"{params.get('options', '')} -c {option}".strip()
    return make_conninfo(dsn, options=options)


def recover_interrupted_jobs(
    *, retry_tasks: Collection[str] | None = None,
    fail_tasks: Collection[str] | None = None, limit: int = 100,
) -> dict:
    """Recover orphaned `doing` jobs, ONLY under the worker schema session lock.

    The assembly root owns that lock and calls this before any worker starts. Read-only
    tasks are re-queued; review rounds end failed and their domain recovery runs afterward,
    through ads.bootstrap_runtime; every other task is re-queued once, and a job stranded
    again ends failed and is listed in `stranded_again` ({id, task_name}). Never inspects
    domain tables. Memory mode does nothing.
    """
    from .recovery import RECEIPT_KEYS, recover

    if config.settings().brand_os_job_queue == "memory":
        return {key: [] for key in RECEIPT_KEYS}
    return recover(
        _with_search_path(db.dsn(), _queue_search_path()),
        retry_tasks=retry_tasks, fail_tasks=fail_tasks, limit=limit,
    )


def app() -> procrastinate.App:
    """惰性建立 App；`db.dsn()` 換了就重建（連帶重新推導 queue schema，見上方 docstring）。"""
    global _app, _app_dsn
    current_dsn = db.dsn()
    if _app is None or _app_dsn != current_dsn:
        queue_dsn = _with_search_path(current_dsn, _queue_search_path())
        new_app = procrastinate.App(connector=procrastinate.PsycopgConnector(conninfo=queue_dsn))
        _register_on(new_app, "background.noop", _noop)
        _app = new_app
        _app_dsn = current_dsn
    return _app


# ---------------------------------------------------------------------------
# F50 Contract J: one background outcome. Every task is registered through `register()`; the
# wrapper stores what the handler ended as in `background_job_result` and makes a failure a
# failed procrastinate job (the bell's `failed_today` counts it).
# ---------------------------------------------------------------------------

#: Code stored for an exception the handler did not turn into a `Failed`／`JobFailed`.
UNEXPECTED_CODE = "unexpected"
#: Code `outcome()` reports for a failed job that left no stored outcome (a worker that does
#: not know the task, a job cancelled／aborted, a job that died before the wrapper wrote).
JOB_FAILED_CODE = "job_failed"


@dataclass(frozen=True)
class Empty:
    """Handler return value: the job ran fine and found nothing to do (`state = empty`)."""

    code: str
    text: str | None = None


@dataclass(frozen=True)
class Failed:
    """Handler return value: the job failed (`state = failed`); the wrapper raises `JobFailed`."""

    code: str
    text: str | None = None


class JobFailed(Exception):
    """Raised by a handler (or by the wrapper for a returned `Failed`): the job failed with
    `code` and the sentence `text`. procrastinate marks the job failed."""

    def __init__(self, code: str, text: str | None = None):
        super().__init__(f"{code}: {text}" if text else code)
        self.code = code
        self.text = text


_REGISTERED_ATTR = "__background_register__"

_UPSERT_RESULT_SQL = """
INSERT INTO background_job_result (org_id, lock, task_name, job_id, state, code, text, finished_at)
VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
ON CONFLICT (org_id, lock) DO UPDATE SET
    task_name = EXCLUDED.task_name, job_id = EXCLUDED.job_id, state = EXCLUDED.state,
    code = EXCLUDED.code, text = EXCLUDED.text, finished_at = EXCLUDED.finished_at
"""


def _record(job, state: str, code: str | None, text: str | None) -> None:
    """Store the outcome on a connection of its own, after the handler finished — never the
    handler's connection, so nothing the handler rolled back is committed here. A job without
    an `org_id` argument (a periodic dispatcher) has no row; a job without a queueing lock is
    keyed by its task name. Bookkeeping never replaces the handler's outcome: a failed write
    is logged and swallowed."""
    org_id = (job.task_kwargs or {}).get("org_id")
    if not org_id:
        return
    lock = job.queueing_lock or job.task_name
    try:
        with db.connection() as conn:
            db.set_tenant_scope(conn, org_id)
            conn.execute(_UPSERT_RESULT_SQL, (org_id, lock, job.task_name, job.id, state, code,
                                              text, db.now_utc()))
            conn.commit()
    except Exception:  # noqa: BLE001 — the job's own outcome must survive a bookkeeping failure
        _log.exception("could not record background outcome %s for %s", state, lock)


def _wrap(name: str, func: Callable) -> Callable:
    if inspect.iscoroutinefunction(func):
        raise TypeError(f"background task {name} must be a plain function")

    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        # procrastinate hands the JobContext first (pass_context=True); a direct call without
        # one (a test harness calling `.func(**kwargs)`) runs the handler and records nothing.
        context = args[0] if args and isinstance(args[0], procrastinate.JobContext) else None
        if context is not None:
            args = args[1:]
        job = context.job if context is not None else None
        try:
            result = func(*args, **kwargs)
        except JobFailed as exc:
            if job is not None:
                _record(job, "failed", exc.code, exc.text)
            raise
        except Exception:
            if job is not None:
                _record(job, "failed", UNEXPECTED_CODE, JOB_FAILED_MESSAGE)
            raise
        if isinstance(result, Failed):
            if job is not None:
                _record(job, "failed", result.code, result.text)
            raise JobFailed(result.code, result.text)
        if isinstance(result, Empty):
            if job is not None:
                _record(job, "empty", result.code, result.text)
            return None
        if job is not None:
            _record(job, "done", None, None)
        return result

    setattr(wrapper, _REGISTERED_ATTR, True)
    return wrapper


def _register_on(a: procrastinate.App, name: str, func: Callable, *, cron: str | None = None,
                 periodic_id: str | None = None) -> None:
    if name in a.tasks:
        return
    task = a.task(name=name, pass_context=True)(_wrap(name, func))
    if cron is not None:
        if periodic_id is None:
            a.periodic(cron=cron)(task)
        else:
            a.periodic(cron=cron, periodic_id=periodic_id)(task)


def register(name: str, func: Callable, *, cron: str | None = None,
             periodic_id: str | None = None) -> None:
    """The only way a task is registered (Contract J). Idempotent: a name already on the
    current `app()` is left alone (the App is rebuilt when the DSN changes, so callers
    re-register). `cron`／`periodic_id` make it periodic exactly like `App.periodic`. The
    handler keeps its own signature (`functools.wraps`); the job context comes from
    procrastinate (`pass_context`), not from a parameter the handler declares."""
    _register_on(app(), name, func, cron=cron, periodic_id=periodic_id)


def is_registered_through_register(task) -> bool:
    """True when a procrastinate task was registered by `register()` (the Contract J scanner)."""
    return bool(getattr(task.func, _REGISTERED_ATTR, False))


#: F31-I15: pool sizing for the defer App. Every caller (`enqueue()`, `is_active()`,
#: `job_outcome()`, `queue_snapshot()`) runs one or two short statements and returns the
#: connection, so one idle connection is enough; psycopg_pool's default (min_size=4, and
#: `open(wait=True)` waits for all four) held four idle connections per process for nothing.
#: `max_size` still lets a few concurrent request threads defer at once.
_DEFER_POOL_MIN_SIZE = 1
_DEFER_POOL_MAX_SIZE = 4


def _sync_app_for_defer() -> procrastinate.App:
    """惰性建立／`db.dsn()` 換了就重建的模組私有 App，`enqueue()` 專用——跟 `app()` 同一套
    rebuild 規則，但接的是 `SyncPsycopgConnector`，不是 `app()` 那顆 async 的
    `PsycopgConnector`（為什麼不能共用見模組檔頭「enqueue() 為什麼要蓋第二個 App」）。

    F31-I15: a rebuild closes the previous App's pool first. Unlike `app()` (whose pools are
    opened and closed by its callers: `with a.open()`, `run_worker()`), this App is opened
    here and owned here, so nobody else would ever close the one a DSN change replaces; its
    idle connections stayed on the server until garbage collection."""
    global _sync_app, _sync_app_dsn
    current_dsn = db.dsn()
    if _sync_app is None or _sync_app_dsn != current_dsn:
        if _sync_app is not None:
            previous, _sync_app, _sync_app_dsn = _sync_app, None, None
            previous.close()
        queue_dsn = _with_search_path(current_dsn, _queue_search_path())
        connector = procrastinate.SyncPsycopgConnector(
            conninfo=queue_dsn,
            min_size=_DEFER_POOL_MIN_SIZE,
            max_size=_DEFER_POOL_MAX_SIZE,
        )
        new_app = procrastinate.App(connector=connector)
        new_app.open()
        _sync_app = new_app
        _sync_app_dsn = current_dsn
    return _sync_app


def enqueue(task_name: str, *, org_id: str, lock: str, **kwargs) -> bool:
    """Defer one job onto the queue. `org_id` is passed through as a task argument (ADR 0038:
    the tenant travels in the args, not in a procrastinate column). `lock` becomes
    procrastinate's `queueing_lock`: `False` when a job with this lock is already waiting in
    `todo` — see module docstring for exactly how much that window covers."""
    if config.settings().brand_os_job_queue == "memory":
        if lock in _memory_locks:
            return False
        _memory_locks.add(lock)
        return True
    deferrer = _sync_app_for_defer().configure_task(task_name, queueing_lock=lock)
    try:
        deferrer.defer(org_id=org_id, **kwargs)
    except AlreadyEnqueued:
        return False
    return True


def is_active(lock: str) -> bool:
    """True while a job carrying this `queueing_lock` is still `todo` or being processed
    (`doing`) — the 409/400 signal a caller needs and `llm_task` cannot give, because its
    `running` row is written by `app/llm/gateway.py` just before the provider call, not when
    the worker claims the job (round 2, ticket 08-standalone-jobs-on-the-queue "Blocked").

    Status values and `queueing_lock`'s lifetime verified against the installed
    procrastinate==3.9.0's own vendored schema
    (`supabase/migrations/20260829000001_background_baseline.sql:71-79,148`, copied verbatim
    from `.venv/Lib/site-packages/procrastinate/sql/schema.sql`) and its `jobs.Status` enum
    (`.venv/Lib/site-packages/procrastinate/jobs.py`): `todo`/`doing`/`succeeded`/`failed`/
    `cancelled`/`aborting`/`aborted`, and `queueing_lock` is a plain column procrastinate never
    clears on completion — it stays readable on the row after the job finishes, which is what
    lets this function tell "never ran" apart from "ran and is done".

    Goes through `job_manager.list_jobs(queueing_lock=..., status=...)` — procrastinate's own
    public query surface (its `shell` CLI's `list_jobs`/`list_locks` commands take the same
    `status=` string), not a hand-rolled SQL query against `procrastinate_jobs`."""
    if config.settings().brand_os_job_queue == "memory":
        return lock in _memory_locks
    job_manager = _sync_app_for_defer().job_manager
    return bool(job_manager.list_jobs(queueing_lock=lock, status="todo")) or bool(
        job_manager.list_jobs(queueing_lock=lock, status="doing")
    )


#: Contract J: what a status reader shows when the newest job for its lock ended failed and
#: that job left no `llm_task` error to quote (it failed before the AI call, or a worker that
#: does not know the task picked it up).
JOB_FAILED_MESSAGE = (
    "背景工作沒有完成：背景程式可能沒有接到這個工作，請再試一次；一直這樣請確認背景程式有在跑。"
)

_ACTIVE_STATUSES = frozenset({"todo", "doing", "aborting"})
_FAILED_STATUSES = frozenset({"failed", "cancelled", "aborted"})


# The newest job carrying a queueing lock, with the time its wait began (started, else queued).
# "Newest" = highest job id; procrastinate never deletes finished jobs here (default
# `delete_job=never`) and never clears `queueing_lock` on completion (see `is_active()`).
_NEWEST_JOB_SQL = """
SELECT j.id, j.status::text AS status, j.args,
       (SELECT max(e.at) FROM procrastinate_events e
         WHERE e.job_id = j.id AND e.type = 'started') AS started_at,
       (SELECT max(e.at) FROM procrastinate_events e
         WHERE e.job_id = j.id
           AND e.type IN ('deferred', 'deferred_for_retry', 'retried')) AS queued_at
  FROM procrastinate_jobs j
 WHERE j.queueing_lock = %(lock)s
 ORDER BY j.id DESC
 LIMIT 1
"""
_RESULT_SQL = (
    "SELECT state, code, text, finished_at, job_id FROM background_job_result"
    " WHERE org_id = %s AND lock = %s"
)


def _stored_result(org_id: str, lock: str):
    """The stored outcome row for this org and lock, read on the caller's bound connection
    when there is one (its tenant scope applies), else on a borrowed one."""
    try:
        conn = db.current()
    except RuntimeError:
        with db.connection() as borrowed:
            return borrowed.execute(_RESULT_SQL, (org_id, lock)).fetchone()
    return conn.execute(_RESULT_SQL, (org_id, lock)).fetchone()


def outcome(lock: str) -> dict | None:
    """Contract J: how the newest job carrying this `queueing_lock` ended.

    `{state, code, text, finished_at, started_at}` with `state`:
    - `running` — the job is todo／doing／aborting (`started_at` = when it started, else when it
      was queued: the real start of the wait, never a made-up "now");
    - `failed` — procrastinate failed／cancelled／aborted: the stored code／text when the wrapper
      wrote them for this job, else `job_failed` + `JOB_FAILED_MESSAGE`;
    - `empty`／`done` — succeeded: the stored state (`done` when this job left no row).
    None when no job ever carried the lock, and always in memory queue mode (e2e: jobs never
    run there; callers fall back to their `llm_task` rule). The stored row is read with the
    job's own `org_id` argument and only counts when it was written by this very job."""
    if config.settings().brand_os_job_queue == "memory":
        return None
    rows = _sync_app_for_defer().connector.execute_query_all(_NEWEST_JOB_SQL, lock=lock)
    if not rows:
        return None
    job = rows[0]
    status = job["status"]
    started_at = job["started_at"] or job["queued_at"]
    if status in _ACTIVE_STATUSES:
        return {"state": "running", "code": None, "text": None, "finished_at": None,
                "started_at": started_at}
    args = job["args"] if isinstance(job["args"], dict) else {}
    org_id = args.get("org_id")
    stored = _stored_result(org_id, lock) if org_id else None
    if stored is not None and stored["job_id"] != job["id"]:
        stored = None  # an older job's outcome under the same lock
    finished_at = stored["finished_at"] if stored is not None else None
    if status in _FAILED_STATUSES:
        if stored is not None and stored["state"] == "failed":
            return {"state": "failed", "code": stored["code"],
                    "text": stored["text"] or JOB_FAILED_MESSAGE, "finished_at": finished_at,
                    "started_at": started_at}
        return {"state": "failed", "code": JOB_FAILED_CODE, "text": JOB_FAILED_MESSAGE,
                "finished_at": finished_at, "started_at": started_at}
    if stored is not None and stored["state"] == "empty":
        return {"state": "empty", "code": stored["code"], "text": stored["text"],
                "finished_at": finished_at, "started_at": started_at}
    return {"state": "done", "code": None, "text": None, "finished_at": finished_at,
            "started_at": started_at}


def job_state(lock: str, llm_row) -> dict:
    """Contract J: the status screens show for one job, from its queue outcome and the newest
    `llm_task` row of that job (`llm_row`, or None). Returns `{status, started_at, error}`:

    - `running`: the queue says running (`started_at` from a running `llm_row`, else from the
      queue), or there is no queue outcome and the row is running;
    - `failed`: the queue says failed (`error` = the row's own error when the row failed,
      else the stored sentence), or the row failed (its own `error`, never replaced);
    - `empty`: the job found nothing to do (`error` carries the stored sentence to show);
    - `done`: the queue says done and the row (if any) succeeded;
    - `unknown`: neither a job nor a row exists — `started_at` None, never a fabricated now.
    Readers still judge a succeeded row's content (parse／validation) themselves."""
    found = outcome(lock)
    row = llm_row
    row_started = row["started_at"] if row is not None else None
    row_running = row is not None and row["status"] == "running"
    if found is not None and found["state"] == "running":
        started = row_started if row_running else found["started_at"]
        return {"status": "running", "started_at": started, "error": None}
    if found is not None and found["state"] == "failed":
        own_error = (row["error"] if row is not None
                     and row["status"] not in ("running", "succeeded") else None)
        return {"status": "failed", "started_at": row_started,
                "error": own_error or found["text"]}
    if found is not None and found["state"] == "empty":
        return {"status": "empty", "started_at": row_started, "error": found["text"]}
    if row is None:
        return {"status": "done" if found is not None else "unknown", "started_at": None,
                "error": None}
    if row_running:
        return {"status": "running", "started_at": row_started, "error": None}
    if row["status"] == "succeeded":
        return {"status": "done", "started_at": row_started, "error": None}
    return {"status": "failed", "started_at": row_started,
            "error": row["error"] or JOB_FAILED_MESSAGE}


def job_outcome(lock: str) -> str | None:
    """Feature F31 Contract J, kept as a thin wrapper over `outcome()` until its last caller
    moves: "active" (running), "failed", "succeeded" (done or empty), or None (no job ever
    carried the lock; always None in memory queue mode)."""
    found = outcome(lock)
    if found is None:
        return None
    if found["state"] == "running":
        return "active"
    if found["state"] == "failed":
        return "failed"
    return "succeeded"


# F29-I05 (feature Contract G): one read of the whole queue. `list_jobs()` returns neither the
# time a job was queued/started nor finish times, so this is one read-only query on the same
# queue connection `enqueue()`/`is_active()` already hold (no second DSN or pool), against
# procrastinate's own tables and its own status-event log (`procrastinate_events`, written by
# its triggers in the vendored baseline migration).
_SNAPSHOT_JOBS_SQL = """
SELECT j.id, j.task_name, j.status::text AS status, j.priority, j.scheduled_at, j.args,
       (SELECT max(e.at) FROM procrastinate_events e
         WHERE e.job_id = j.id AND e.type = 'started') AS started_at,
       (SELECT max(e.at) FROM procrastinate_events e
         WHERE e.job_id = j.id
           AND e.type IN ('deferred', 'deferred_for_retry', 'retried')) AS queued_at,
       now() AS read_at
  FROM procrastinate_jobs j
 WHERE j.status IN ('todo', 'doing')
"""
_SNAPSHOT_FINISHED_SQL = """
SELECT j.args->>'org_id' AS org_id, e.type::text AS type, count(*) AS n
  FROM procrastinate_events e
  JOIN procrastinate_jobs j ON j.id = e.job_id
 WHERE e.type IN ('succeeded', 'failed') AND e.at >= %(since)s
 GROUP BY 1, 2
"""
#: Contract C: a worker whose last heartbeat is older than this is not alive.
WORKER_HEARTBEAT_STALE_SECONDS = 60
_WORKER_HEALTH_SQL = """
SELECT now() AS checked_at, max(last_heartbeat) AS last_heartbeat_at,
       COALESCE(max(last_heartbeat) >= now() - make_interval(secs => %(stale)s), false) AS alive
  FROM procrastinate_workers
"""


def worker_health() -> dict:
    """One read-only liveness projection; unavailable/test queues prove no liveness."""
    unknown = {"state": "unknown", "checked_at": db.now_utc().isoformat(),
               "last_heartbeat_at": None, "reason_code": "health_unavailable"}
    if config.settings().brand_os_job_queue == "memory":
        return {**unknown, "reason_code": "test_queue"}
    try:
        row = _sync_app_for_defer().connector.execute_query_one(
            _WORKER_HEALTH_SQL, stale=WORKER_HEARTBEAT_STALE_SECONDS,
        )
        if row is None:
            return unknown
        return {
            "state": "alive" if row["alive"] else "stopped",
            "checked_at": row["checked_at"].isoformat(),
            "last_heartbeat_at": (row["last_heartbeat_at"].isoformat()
                                  if row["last_heartbeat_at"] is not None else None),
            "reason_code": "heartbeat_fresh" if row["alive"] else "heartbeat_stale",
        }
    except Exception:
        _log.warning("Worker heartbeat read unavailable", exc_info=True)
        return unknown


def _seconds(later: datetime, earlier: datetime | None) -> int | None:
    return None if earlier is None else max(0, int((later - earlier).total_seconds()))


def queue_snapshot(*, since: datetime) -> dict:
    """Read-only picture of the whole queue (every tenant — one shared worker).

    Returns `{jobs, total, done_today, failed_today, worker_alive}`:
    - `jobs`: every `todo`/`doing` job in pick order — running (`doing`) first by start time,
      then waiting jobs the way `procrastinate_fetch_job_v2` picks them (priority DESC, id ASC),
      then jobs scheduled for later by their scheduled time. Each item is
      `{id, task_name, status: "running"|"queued", position (1-based), org_id|None, args,
      waited_seconds|None}`; `waited_seconds` counts from the start (running) or from the time
      it was queued / became due (queued); None for a job scheduled in the future.
      `args` are the job's own kwargs: callers must pick what they show, never pass them on.
    - `done_today`/`failed_today`: `{org_id: count}` of `succeeded`/`failed` events since
      `since` (required, F50 Contract K: the caller's org-day start, e.g.
      `routes_jobs_api._since`; never the machine's UTC midnight); jobs without `org_id` in args
      are keyed `None`.
    - `worker_alive`: Contract C (module docstring) — some worker heartbeat within
      `WORKER_HEARTBEAT_STALE_SECONDS`.
    `worker_health` is the canonical projection; `worker_alive` keeps legacy memory
    compatibility, which must not be treated as operational evidence."""
    health = worker_health()
    if config.settings().brand_os_job_queue == "memory":
        return {"jobs": [], "total": 0, "done_today": {}, "failed_today": {},
                "worker_alive": True, "worker_health": health}
    connector = _sync_app_for_defer().connector
    rows = connector.execute_query_all(_SNAPSHOT_JOBS_SQL)
    finished = connector.execute_query_all(_SNAPSHOT_FINISHED_SQL, since=since)
    worker_alive = health["state"] == "alive"

    far = datetime.max.replace(tzinfo=UTC)
    running = sorted(
        (r for r in rows if r["status"] == "doing"),
        key=lambda r: (r["started_at"] or far, r["id"]),
    )
    waiting = [r for r in rows if r["status"] == "todo"]

    def due(r) -> bool:
        return r["scheduled_at"] is None or r["scheduled_at"] <= r["read_at"]

    ready = sorted((r for r in waiting if due(r)), key=lambda r: (-r["priority"], r["id"]))
    later = sorted((r for r in waiting if not due(r)), key=lambda r: (r["scheduled_at"], r["id"]))

    jobs = []
    for position, r in enumerate([*running, *ready, *later], start=1):
        args = r["args"] if isinstance(r["args"], dict) else {}
        if r["status"] == "doing":
            waited = _seconds(r["read_at"], r["started_at"])
        elif due(r):
            since_queued = max(filter(None, (r["queued_at"], r["scheduled_at"])), default=None)
            waited = _seconds(r["read_at"], since_queued)
        else:
            waited = None
        jobs.append({
            "id": r["id"], "task_name": r["task_name"],
            "status": "running" if r["status"] == "doing" else "queued",
            "position": position, "org_id": args.get("org_id"), "args": args,
            "waited_seconds": waited,
        })
    counts: dict[str, dict] = {"succeeded": {}, "failed": {}}
    for r in finished:
        counts[r["type"]][r["org_id"]] = int(r["n"])
    return {"jobs": jobs, "total": len(jobs),
            "done_today": counts["succeeded"], "failed_today": counts["failed"],
            "worker_alive": worker_alive, "worker_health": health}
