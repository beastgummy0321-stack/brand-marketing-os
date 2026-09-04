# 03 — the worker becomes its own process

Route C (module boundary). Decision already settled and written: **ADR 0063**
`docs/adr/0063-the-worker-is-its-own-process-everywhere.md` (supersedes ADR 0039).
Module contract: `docs/contracts/background.md` (written 2026-09-05 for this ticket).
Graduated from `issue-daily-pull-worker-own-process.md`.

Precedence reminder: `CONSTITUTION.md` > ADR 0063 > `docs/contracts/background.md` > this ticket.
Anything here that contradicts something above it is `blocked-upstream`, not silently corrected.

## What

**`python -m app.worker` becomes the only thing that runs procrastinate jobs. `app/main.py`
starts no worker on any environment, including this laptop.** Local convenience is preserved by
the two launchers starting the worker for the user; the number of things the user clicks does
not change.

1. **New `app/worker.py`** — a sibling of `app/main.py`, not a file inside `app/background/`
   (ADR 0063: task registration lives in the assembly root, and `app/background` may never
   import upward). It must:
   - `import app.main` for `.env`, logging install, `meta.register_task()` and
     `schedule.register_tasks()` — the same line `app/meta/daily_pull.py`'s `__main__` block
     already uses, for the same reason. Do not re-implement any of it.
   - run `app/llm/gateway.py`'s `fail_interrupted_tasks()` **once, before the worker takes its
     first job** (see point 4).
   - then `app.background.app().run_worker()`.
   - expose `main(*, wait: bool = True) -> None` plus the `if __name__ == "__main__":` guard.
     `wait` is procrastinate's own `run_worker` keyword — six existing tests in this repo already
     use `wait=False` to mean "drain what is queued, then return" — and it is exposed so the
     done-check below can drive the real entry point instead of a copy of it.
   - Literal shape (this is the contract; JSON is N/A — the entry point is a process, and its
     interface is a command line plus an exit code):

     ```
     $ uv run python -m app.worker
     INFO:procrastinate.worker:Starting worker on all queues
     ^C
     $ echo $?          # Ctrl+C is a clean stop, not a traceback
     0
     ```

   - Signal handling stays procrastinate's default. **Do not pass `install_signal_handlers=False`**:
     that argument existed only because the worker used to run off the main thread inside
     uvicorn. It is now the main thread of its own process, which is the only place signal
     handlers can be installed, and Ctrl+C must stop it.

2. **`app/background/__init__.py`** — delete `start_worker()`, `stop_worker()`, `_worker_main()`,
   `_worker_thread_body()`, `_worker_thread`, `_worker_loop`, `_worker_stop`, `_worker_app`,
   `_WORKER_READY_TIMEOUT`, `_WORKER_STOP_TIMEOUT`, and the `threading` import if it is then
   unused. Keep `app()`, `enqueue()`, `_noop()`, `_queue_search_path()`, `_with_search_path()`,
   `_sync_app_for_defer()`, and **keep the win32 `WindowsSelectorEventLoopPolicy` switch at
   import** (`App.run_worker()` builds its loop with `asyncio.run()`, which reads the policy;
   psycopg's async pool still cannot run on a `ProactorEventLoop`). Rewrite the module
   docstring's §2 and §3 so the entry-point list and the caller list match
   `docs/contracts/background.md`; the paragraphs about the thread, the uvicorn loop and "a
   worker that will not start must not take the site down" describe deleted code and go with it —
   the loop lesson survives in ADR 0039, which stays on file as superseded.

3. **`app/main.py`** — remove `_lifespan` and the `lifespan=` argument to `FastAPI(...)`. Once
   the worker calls and `fail_interrupted_tasks()` move out, nothing is left in it. Remove
   whatever imports that makes unused.

4. **`app/llm/gateway.py`** — `fail_interrupted_tasks()` keeps its body unchanged; only its
   docstring changes. It must name `app/worker.py` as the caller, and its `ponytail:` note must
   say the trigger for a heartbeat/age check is **more than one worker process** (cloud
   autoscale), not "the day `start_worker()` leaves `lifespan`" — that day is today, and the
   assumption survived it, because one worker process still owns every `running` row and owns
   none at the moment it boots. Reasoning in full: ADR 0063, "What this changes about
   interrupted work".

5. **`啟動行銷系統.bat`** — after the server window is started, start the worker window too,
   minimised, from the same `.venv` python:
   `start /min "Marketing OS Worker" cmd /k ".venv\Scripts\python.exe" -m app.worker`.
   The curl wait loop is unchanged (it probes 8710, still the web process). The file must stay
   CRLF — cmd mis-parses `if`/`for` blocks in an LF-only batch file (the comment at the top of
   that file records this).

6. **`關閉行銷系統.bat`** — add a window-title kill for the worker beside the existing one:
   `taskkill /FI "WINDOWTITLE eq Marketing OS Worker*" /F`. Do not change the port-based kill.

7. **`app/tools/boot_launcher.py`** — before `uvicorn.run(...)`, spawn the worker as a **child**
   of this process with no console window (`subprocess.Popen` with `sys.executable`, which under
   this launcher is already `pythonw.exe`, and `-m app.worker`, cwd `_REPO_ROOT`). A child is
   required, not a detached process: `關閉行銷系統.bat` kills the listener on 8710 with
   `taskkill /PID … /T /F`, and `/T` is what takes the worker down with it. Send its
   stdout/stderr to a second file beside the existing one (`logs/worker.log`). Update this
   file's docstring, which currently says the launcher "只做兩件事".

8. **`docs/boot-autostart.md`** — the section 「這支排程器實際上做什麼」 must say the launcher
   also starts the worker, and that `關閉行銷系統.bat` takes both down. While in that file, the
   bullet claiming the launcher re-runs `app/main.py _auto_sync_if_due` is stale (that function
   does not exist; `git grep -n _auto_sync_if_due` returns nothing) — delete that bullet. Change
   nothing else in the file.

9. **`app/tests/test_architecture_boundaries.py`** — remove `"background"` from
   `MODULES_WITHOUT_CONTRACT` (the page now exists), update the two `KNOWN_MODULE_SIZES` entries
   per "Line-budget authorisations" below, and fix the stale comment at line 1378 naming
   ADR 0039.

10. **`app/meta/daily_pull.py`** — three comment-only fixes, no behaviour change: the module
    docstring's "It only *fires* because app/background.start_worker() now keeps a worker running
    inside the same uvicorn process" (line 22) and the two ADR 0039 references (lines 29, 194)
    must describe ADR 0063's world. The `__main__` block itself is unchanged and stays
    first-class (constitution rule 8).

11. **ADR 0063** — add `app/worker.py` to its `applies-to:` list in the same commit that creates
    the file. The ADR index refuses a path that does not exist, which is why it was left out.

Out of scope, do not touch: the cron trigger time `0 3 * * *` and its timezone (ADR 0063 records
why it stays), `frontend/playwright.config.ts` (its 8720 backend deliberately runs without a
worker — the smoke path never queues anything), `enqueue()`, and the procrastinate schema.

## How we know it's done

Gate commands, verbatim. Every one runs, and its output is reported.

1. `uv run ruff check app`
2. `uv run pyright`
3. `uv run pytest app/tests/test_background.py app/tests/test_architecture_boundaries.py app/tests/test_meta_daily_spend.py app/tests/test_schedule.py app/tests/test_approval.py app/tests/test_main_dotenv.py -q`
4. `cd frontend && npm run e2e` — builds the frontend and starts its own 8720 backend; needs
   `supabase start` up. Backend tickets run it too.
5. **One new test, in `app/tests/test_background.py`**, replacing the deleted
   `WorkerLifecycleTest`. It protects the two things that are now the worker process's job:
   defer a `background.noop` job, insert one `llm_task` row with `status = 'running'`, call
   `app.worker.main(wait=False)`, then assert **(a)** the deferred job is no longer `todo` and
   **(b)** that `llm_task` row is now `failed` with `error = INTERRUPTED_TASK_ERROR`.
   - Import `app.worker` **inside the test function**, not at module import: `conftest.py`
     rewrites `DATABASE_URL` per test module, and `app.worker` imports `app.main`.
   - **Prove it red once** and say how in the report: remove the `fail_interrupted_tasks()` call
     from `app/worker.py`, watch assertion (b) fail, restore it.
   - Delete `WorkerLifecycleTest` and its three methods — they test code this ticket removes.
6. **Manual, on a restarted backend** (the machine gate cannot see a deployment shape):
   - `uv run python -m app.worker` in one terminal and
     `uv run python -m uvicorn app.main:app --port 8710` in another. Open
     <http://localhost:8710/app>, log in as `123@example.com` / `123456`, press one generation
     button on a brand's schedule page, and see the result arrive. Ctrl+C the worker: exit code
     0, no traceback.
   - Start the site **without** a worker: it comes up clean and serves pages (a worker is no
     longer required for the site to boot).
   - Double-click `啟動行銷系統.bat`: two windows (server + a minimised "Marketing OS Worker"),
     browser opens. Then double-click `關閉行銷系統.bat`: **both** are gone
     (`tasklist | findstr python` shows neither).
7. `git diff --name-only` equals the file list under "Shared files touched", plus the one new
   file `app/worker.py`. A file in the diff that the list does not name is `blocked-upstream`:
   the ticket was written against a wrong picture of the code.

## Line-budget authorisations

All three numbers are **measured, not estimated** — run the count, write what it says, leave no
headroom:

- `KNOWN_MODULE_SIZES["app"]`: currently `526`. `app/worker.py` is new top-level code and
  `app/main.py` shrinks. Raising this entry **is authorised by this ticket**; write the measured
  number with a one-line reason naming ADR 0063.
- `KNOWN_MODULE_SIZES["app/background"]`: currently `272`. This ticket only deletes from that
  module, so it must go **down** to the measured value.
- `TEST_LINES_CEILING`: currently `19052`; the measured total today is also `19052`. Three tests
  go, one arrives, so the total must come out lower — set the ceiling to the measured number. If
  it comes out **higher**, do not raise it: that is `blocked-upstream`.

## Shared files touched

Pasted from `git grep -n -I <name>` across the whole repo (`.scratch/` excluded), one search per
name that stops existing or changes meaning in this slice. Not typed.

```
### git grep -n -I start_worker
app/background/__init__.py:8:   物件），加上票 05 fix round 補的 `start_worker()`／`stop_worker()`（都是 async、無參數，
app/background/__init__.py:13:   `register_tasks()` 掛三個生成 task）與手動 done-check；`start_worker()`／`stop_worker()`
app/background/__init__.py:26:裡跑」這個用法點名了 `install_signal_handlers=False` 這個參數（見 `start_worker()`
app/background/__init__.py:69:同一輪的第二個修正：**worker 起不來不准把網站一起弄死**。原本 `start_worker()` 的例外直接
app/background/__init__.py:195:    only time out. `start_worker()` therefore waits for it rather than returning the moment the
app/background/__init__.py:228:        ready.set()  # never leave start_worker() waiting out the full timeout on a crash
app/background/__init__.py:231:async def start_worker() -> None:
app/llm/gateway.py:97:    `app/background`——呼叫端是 `app/main.py` 的 `_lifespan`，在 `start_worker()` 之前跑一次。
app/llm/gateway.py:102:    那天，這裡要換成心跳／存活時間判斷——跟 ADR 0039 說 `start_worker()` 離開 `lifespan`
app/main.py:135:    app/background/__init__.py start_worker() 檔頭「為什麼不是新開一個部署形態」）；關閉時
app/main.py:138:    票 05-1 frozen decision 2：`start_worker()` 之前先把上一個 process 死掉時留下的
app/main.py:144:    await background_module.start_worker()
app/meta/daily_pull.py:22:block below already did by hand. It only *fires* because app/background.start_worker() now
app/tests/test_background.py:73:    mechanism that makes that false — a worker that actually starts on `start_worker()` and
app/tests/test_background.py:83:    async def test_start_worker_brings_up_a_live_worker_thread(self):
app/tests/test_background.py:85:        await background_module.start_worker()
app/tests/test_background.py:87:        self.assertIsNotNone(thread, "start_worker() 必須啟動 worker 執行緒")
app/tests/test_background.py:89:        self.assertTrue(thread.is_alive(), "start_worker() 回來時 worker 必須已經真的在跑")
app/tests/test_background.py:109:    async def test_start_worker_never_raises_so_a_broken_worker_cannot_take_the_site_down(self):
app/tests/test_background.py:110:        """憲法規則 6：自動化是加法。2026-08-29 之前 `start_worker()` 的例外會從 FastAPI
app/tests/test_background.py:114:        把執行緒啟動改成一定失敗，`start_worker()` 仍然必須安靜回來。"""
app/tests/test_background.py:119:            await background_module.start_worker()  # 不得拋出
docs/adr/0039-the-worker-rides-inside-the-web-process.md:12:> which `start_worker()` / `stop_worker()` stop being called from `lifespan` and become their
docs/adr/0039-the-worker-rides-inside-the-web-process.md:60:must not take the site down with it. That is the point at which `start_worker()` /
docs/adr/0039-the-worker-rides-inside-the-web-process.md:68:- `app/background/__init__.py` gains `start_worker()` / `stop_worker()` alongside `app()`. They
docs/adr/0039-the-worker-rides-inside-the-web-process.md:101:`start_worker()` now logs and swallows every failure, and `python -m app.meta.daily_pull` is
docs/adr/0039-the-worker-rides-inside-the-web-process.md:105:worker test called `start_worker()` / `stop_worker()` directly, because driving the lifespan
docs/adr/0039-the-worker-rides-inside-the-web-process.md:108:invariant that actually protects the site: `start_worker()` never raises. It was proven red by
docs/tech-debt.md:207:路由裝飾器，本來就不在這條規則範圍內。（原本這裡還舉了 lifespan 的 `start_worker`／

### git grep -n -I stop_worker
app/background/__init__.py:8:   物件），加上票 05 fix round 補的 `start_worker()`／`stop_worker()`（都是 async、無參數，
app/background/__init__.py:13:   `register_tasks()` 掛三個生成 task）與手動 done-check；`start_worker()`／`stop_worker()`
app/background/__init__.py:190:    `ready` once it can be stopped, runs until `stop_worker()` signals, then closes what it
app/background/__init__.py:193:    `ready` is what makes `stop_worker()` race-free: until this coroutine has published its loop
app/background/__init__.py:259:async def stop_worker() -> None:
app/main.py:146:    await background_module.stop_worker()
app/tests/test_background.py:74:    shuts down cleanly on `stop_worker()`, leaving no thread and no open pool behind.
app/tests/test_background.py:94:            await background_module.stop_worker()
app/tests/test_background.py:95:        self.assertIsNone(background_module._worker_thread, "stop_worker() 必須清掉狀態")
app/tests/test_background.py:97:    # `stop_worker()` 真的把執行緒收掉這件事**不在這裡斷言**，因為在 pytest 的
app/tests/test_background.py:100:    # `stop_worker()` 壞掉：2026-08-29 在 pytest 之外用同一組呼叫實測，
docs/adr/0039-the-worker-rides-inside-the-web-process.md:12:> which `start_worker()` / `stop_worker()` stop being called from `lifespan` and become their
docs/adr/0039-the-worker-rides-inside-the-web-process.md:61:`stop_worker()` stop being called from `lifespan` and become their own entry point.
docs/adr/0039-the-worker-rides-inside-the-web-process.md:68:- `app/background/__init__.py` gains `start_worker()` / `stop_worker()` alongside `app()`. They
docs/adr/0039-the-worker-rides-inside-the-web-process.md:105:worker test called `start_worker()` / `stop_worker()` directly, because driving the lifespan
docs/tech-debt.md:208:`stop_worker`——ADR 0063 之後 worker 是獨立行程，`app/main.py` 連 lifespan 都沒有了。）

### git grep -n -I _worker_thread
app/background/__init__.py:65:所以 worker 改成跑在**自己的執行緒、自己的 loop** 上（`_worker_thread_body`）：`asyncio.run()`
app/background/__init__.py:116:_worker_thread: threading.Thread | None = None
app/background/__init__.py:216:def _worker_thread_body(ready: threading.Event) -> None:
app/background/__init__.py:241:    global _worker_thread
app/background/__init__.py:242:    if _worker_thread is not None and _worker_thread.is_alive():
app/background/__init__.py:247:            target=_worker_thread_body, args=(ready,),
app/background/__init__.py:250:        _worker_thread = thread
app/background/__init__.py:256:        _worker_thread = None
app/background/__init__.py:262:    global _worker_thread, _worker_loop, _worker_stop, _worker_app
app/background/__init__.py:263:    thread, loop, stop = _worker_thread, _worker_loop, _worker_stop
app/background/__init__.py:264:    _worker_thread = _worker_loop = _worker_stop = _worker_app = None
app/tests/test_background.py:80:    `app/background/__init__.py` `_worker_thread_body`.
app/tests/test_background.py:83:    async def test_start_worker_brings_up_a_live_worker_thread(self):
app/tests/test_background.py:84:        self.assertIsNone(background_module._worker_thread, "沒有先前測試留下的殘留 worker")
app/tests/test_background.py:86:        thread = background_module._worker_thread
app/tests/test_background.py:95:        self.assertIsNone(background_module._worker_thread, "stop_worker() 必須清掉狀態")
app/tests/test_background.py:121:        self.assertIsNone(background_module._worker_thread, "起不來就不要留半個 worker 狀態")

### git grep -n -I _worker_loop
app/background/__init__.py:117:_worker_loop: asyncio.AbstractEventLoop | None = None  # 由 worker thread 自己填
app/background/__init__.py:197:    global _worker_loop, _worker_stop, _worker_app
app/background/__init__.py:198:    _worker_loop = asyncio.get_running_loop()
app/background/__init__.py:262:    global _worker_thread, _worker_loop, _worker_stop, _worker_app
app/background/__init__.py:263:    thread, loop, stop = _worker_thread, _worker_loop, _worker_stop
app/background/__init__.py:264:    _worker_thread = _worker_loop = _worker_stop = _worker_app = None
app/tests/test_background.py:90:        self.assertIsNotNone(background_module._worker_loop, "worker 必須公布自己的 loop")

### git grep -n -I _worker_stop
app/background/__init__.py:118:_worker_stop: asyncio.Event | None = None              # 建在 worker loop 上，只能 threadsafe 觸發
app/background/__init__.py:197:    global _worker_loop, _worker_stop, _worker_app
app/background/__init__.py:199:    _worker_stop = asyncio.Event()
app/background/__init__.py:206:        await _worker_stop.wait()
app/background/__init__.py:262:    global _worker_thread, _worker_loop, _worker_stop, _worker_app
app/background/__init__.py:263:    thread, loop, stop = _worker_thread, _worker_loop, _worker_stop
app/background/__init__.py:264:    _worker_thread = _worker_loop = _worker_stop = _worker_app = None
app/tests/test_background.py:91:        self.assertIsNotNone(background_module._worker_stop, "worker 必須公布自己的停止旗標")

### git grep -n -I _worker_app
app/background/__init__.py:197:    global _worker_loop, _worker_stop, _worker_app
app/background/__init__.py:201:    _worker_app = worker_app
app/background/__init__.py:262:    global _worker_thread, _worker_loop, _worker_stop, _worker_app
app/background/__init__.py:264:    _worker_thread = _worker_loop = _worker_stop = _worker_app = None

### git grep -n -I _WORKER_READY_TIMEOUT
app/background/__init__.py:119:_WORKER_READY_TIMEOUT = 15.0
app/background/__init__.py:251:        if not ready.wait(_WORKER_READY_TIMEOUT):
app/background/__init__.py:253:                         _WORKER_READY_TIMEOUT)

### git grep -n -I _WORKER_STOP_TIMEOUT
app/background/__init__.py:120:_WORKER_STOP_TIMEOUT = 10.0
app/background/__init__.py:269:    thread.join(timeout=_WORKER_STOP_TIMEOUT)
app/background/__init__.py:272:                     _WORKER_STOP_TIMEOUT)
app/tests/test_background.py:93:        with mock.patch.object(background_module, "_WORKER_STOP_TIMEOUT", 1.0):

### git grep -n -I _lifespan
app/llm/gateway.py:97:    `app/background`——呼叫端是 `app/main.py` 的 `_lifespan`，在 `start_worker()` 之前跑一次。
app/main.py:132:async def _lifespan(_app: FastAPI):
app/main.py:149:app = FastAPI(title="行銷作業系統（Phase 0 Mock UI）", lifespan=_lifespan)
docs/adr/0042-work-the-user-waits-for-runs-on-the-queue.md:109:- `app/llm` gains `fail_interrupted_tasks(conn)`, called once from `_lifespan` before the worker

### git grep -n -I fail_interrupted_tasks
app/llm/gateway.py:92:def fail_interrupted_tasks(conn: db.Conn) -> int:
app/main.py:139:    `llm_task` running 列標記失敗（見 `app/llm/gateway.py` `fail_interrupted_tasks()`
app/main.py:143:        llm_gateway.fail_interrupted_tasks(conn)
app/tests/test_architecture_boundaries.py:823:# fail_interrupted_tasks() 的 WHERE 條件改壞，三支各自單獨抓到。
app/tests/test_llm_gateway.py:821:        count = gateway.fail_interrupted_tasks(self.conn)
docs/adr/0042-work-the-user-waits-for-runs-on-the-queue.md:109:- `app/llm` gains `fail_interrupted_tasks(conn)`, called once from `_lifespan` before the worker

### git grep -n -I MODULES_WITHOUT_CONTRACT
app/tests/test_architecture_boundaries.py:1182:# `ContractPageRatchetTest`（MODULES_WITHOUT_CONTRACT 棘輪，跟 `FileLineCapTest`／
app/tests/test_architecture_boundaries.py:1890:MODULES_WITHOUT_CONTRACT = {
app/tests/test_architecture_boundaries.py:1899:    """②契約頁閘門：MODULES_WITHOUT_CONTRACT 只准變短，不准變長。"""
app/tests/test_architecture_boundaries.py:1903:            module for module in sorted(ALL_MODULE_DIRS - MODULES_WITHOUT_CONTRACT)
app/tests/test_architecture_boundaries.py:1908:            "以下模組沒有 docs/contracts/<module>.md，也不在 MODULES_WITHOUT_CONTRACT 的豁免"
app/tests/test_architecture_boundaries.py:1915:            m for m in MODULES_WITHOUT_CONTRACT
app/tests/test_architecture_boundaries.py:1920:            "以下模組已經補了契約頁，請從 MODULES_WITHOUT_CONTRACT 劃掉（清單只准變短）：\n"
app/tests/test_architecture_boundaries.py:1925:        stale_dirs = sorted(MODULES_WITHOUT_CONTRACT - ALL_MODULE_DIRS)
app/tests/test_architecture_boundaries.py:1928:            "以下模組已經不存在，請從 MODULES_WITHOUT_CONTRACT 劃掉（清單不留死名單）：\n"

### git grep -n -I 'Marketing OS Server'
"\345\225\237\345\213\225\350\241\214\351\212\267\347\263\273\347\265\261.bat":19:start "Marketing OS Server" cmd /k ".venv\Scripts\python.exe" -m uvicorn app.main:app --port 8710
"\345\225\237\345\213\225\350\241\214\351\212\267\347\263\273\347\265\261.bat":32:echo 請看標題「Marketing OS Server」那個黑視窗最後幾行字，問題會寫在那裡。
"\351\227\234\351\226\211\350\241\214\351\212\267\347\263\273\347\265\261.bat":16:taskkill /FI "WINDOWTITLE eq Marketing OS Server*" /F >nul 2>&1
```

`ADR 0039` also appears at `app/llm/gateway.py:100,102`, `app/meta/daily_pull.py:29,194` and
`app/tests/test_architecture_boundaries.py:1378` — the only hits left under `app/`. The `docs/`
hits were already fixed by main chat when ADR 0063 was written (`0042`, `0062`,
`contracts/meta.md`, `tech-debt.md`, `issues/ad-loop/spec.md`); do not touch those files.

## Contradiction check

Two pairs of done-checks that could both pass while the system is wrong, and the input that
shows it:

1. **Done-check 5 (the worker sweeps `running` `llm_task` rows at startup) vs done-check 3 (the
   affected test set stays green).** The sweep is unconditional — it fails *every* running row,
   not only the ones the caller made. Input that shows it: a test module where one test leaves an
   `llm_task` in `running` on purpose and a later test in the same module calls
   `worker.main(wait=False)`; the second silently destroys the first one's fixture and both still
   pass. Nothing does this today (`conftest.py` gives each module its own schema, and no other
   test calls the worker entry point), so the resolution is: the new test creates its own
   `running` row and asserts only on rows it inserted. The day a second caller of `worker.main()`
   appears in the tests, this stops being safe.

2. **Done-check 4 (`npm run e2e` green) vs the point of the ticket (jobs run only when a worker
   process runs).** The e2e backend on 8720 starts no worker, and it passes today only because
   the smoke path never queues anything — it fills in a brand name and takes the free route
   through `intake.start_or_quick()`. Input that shows it: add any step to
   `frontend/e2e/smoke.spec.ts` that presses a generation button; with no worker it hangs to the
   60-second timeout with no error saying why. So this ticket adds no such step, and whoever adds
   one later has to start a worker in `playwright.config.ts`.
