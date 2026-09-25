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
   F29-I05 另提供唯讀的 `queue_snapshot(*, since=None) -> dict`（整條佇列的排隊順序與今天
   做完／失敗數，呼叫端目前只有 `app/dashboard/routes_jobs_api.py`）。F31-I02（Contract J）
   另提供唯讀的 `job_outcome(lock) -> "active"|"failed"|"succeeded"|None`（這個 lock 最新
   一個 job 的結局），供 `app/intake`／`app/brand_web` 的狀態端點判斷。其餘一律私有。
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

記憶體佇列模式（`BRAND_OS_JOB_QUEUE=memory`，e2e 後端專用，F06-I05）：開發用資料庫的
`public__queue` 是共用的——使用者自己一直開著的 `python -m app.worker`（真 Codex、舊程式）
會從那裡撿走 e2e 建出來的 job 去跑，8720 的環境變數碰不到那支獨立行程。這個模式下
`enqueue()`／`is_active()` 完全不碰 procrastinate、不寫任何一列：job 永遠不會執行。e2e 本來
就只斷言「沒有 worker 也成立」的行為（F02 Decisions），job 不跑正是它宣稱的前提。由
`app/core/config.py` 的 `_FORBIDDEN_VALUES_OUTSIDE_LOCAL` 擋住，只有 `BRAND_OS_ENV=local`
才能設。
"""

import asyncio
import logging
import re
import sys
from collections.abc import Collection
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
        new_app.task(name="background.noop")(_noop)
        _app = new_app
        _app_dsn = current_dsn
    return _app


def _sync_app_for_defer() -> procrastinate.App:
    """惰性建立／`db.dsn()` 換了就重建的模組私有 App，`enqueue()` 專用——跟 `app()` 同一套
    rebuild 規則，但接的是 `SyncPsycopgConnector`，不是 `app()` 那顆 async 的
    `PsycopgConnector`（為什麼不能共用見模組檔頭「enqueue() 為什麼要蓋第二個 App」）。"""
    global _sync_app, _sync_app_dsn
    current_dsn = db.dsn()
    if _sync_app is None or _sync_app_dsn != current_dsn:
        queue_dsn = _with_search_path(current_dsn, _queue_search_path())
        connector = procrastinate.SyncPsycopgConnector(conninfo=queue_dsn)
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


def job_outcome(lock: str) -> str | None:
    """Feature F31 Contract J: outcome of the newest job carrying this `queueing_lock`.

    Returns "active" (todo/doing), "failed" (failed, or cancelled/aborted: it never finished
    its work), "succeeded", or None when no job with this lock ever existed. Memory queue mode
    (e2e) always returns None: jobs never run there, callers fall back to their `llm_task` rule.

    "Newest" = highest job id; procrastinate never deletes finished jobs here (default
    `delete_job=never`) and never clears `queueing_lock` on completion (see `is_active()`).
    Reads through `job_manager.list_jobs(queueing_lock=...)`, procrastinate's own public query
    surface, not hand SQL on `procrastinate_jobs`."""
    if config.settings().brand_os_job_queue == "memory":
        return None
    jobs = _sync_app_for_defer().job_manager.list_jobs(queueing_lock=lock)
    if not jobs:
        return None
    newest = max(jobs, key=lambda job: job.id or 0)
    status = str(newest.status)
    if status in _ACTIVE_STATUSES:
        return "active"
    if status in _FAILED_STATUSES:
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


def _seconds(later: datetime, earlier: datetime | None) -> int | None:
    return None if earlier is None else max(0, int((later - earlier).total_seconds()))


def queue_snapshot(*, since: datetime | None = None) -> dict:
    """Read-only picture of the whole queue (every tenant — one shared worker).

    Returns `{jobs, total, done_today, failed_today}`:
    - `jobs`: every `todo`/`doing` job in pick order — running (`doing`) first by start time,
      then waiting jobs the way `procrastinate_fetch_job_v2` picks them (priority DESC, id ASC),
      then jobs scheduled for later by their scheduled time. Each item is
      `{id, task_name, status: "running"|"queued", position (1-based), org_id|None, args,
      waited_seconds|None}`; `waited_seconds` counts from the start (running) or from the time
      it was queued / became due (queued); None for a job scheduled in the future.
      `args` are the job's own kwargs: callers must pick what they show, never pass them on.
    - `done_today`/`failed_today`: `{org_id: count}` of `succeeded`/`failed` events since
      `since` (default: 00:00 UTC today); jobs without `org_id` in args are keyed `None`.
    Memory queue mode (e2e): an empty snapshot."""
    if since is None:
        since = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
    if config.settings().brand_os_job_queue == "memory":
        return {"jobs": [], "total": 0, "done_today": {}, "failed_today": {}}
    connector = _sync_app_for_defer().connector
    rows = connector.execute_query_all(_SNAPSHOT_JOBS_SQL)
    finished = connector.execute_query_all(_SNAPSHOT_FINISHED_SQL, since=since)

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
            "done_today": counts["succeeded"], "failed_today": counts["failed"]}
