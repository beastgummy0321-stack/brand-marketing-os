"""app/tools/boot_launcher.py — 票 F6：Windows 開機自動啟動用的無視窗啟動器。

Windows 工作排程器（schtasks，trigger onlogon，見 docs/boot-autostart.md）叫的是這支，
不是「啟動行銷系統.bat」——那支登入當下會開一個 cmd 視窗搶焦點、還會開瀏覽器分頁，
兩者都不是登入那一刻該發生的事。這支做三件事：

1. port 8710 已經有人在聽（例如使用者自己手動點了 .bat）就直接結束，不重複啟動——
   比照既有 .bat 的「netstat 找 LISTENING」邏輯，改用標準庫 `socket` 直接探測那個 port，
   不必解析 netstat 的文字輸出（依系統語系而異，一直是隱性地雷）。
2. 把 worker（`python -m app.worker`，ADR 0063）當這個 process 的**子行程**開起來——
   一定要是子行程，不能是 detached：`關閉行銷系統.bat` 用 `taskkill /PID … /T /F` 收掉
   聽 8710 那個 process，`/T` 才會連帶收掉它底下的子行程樹，worker 才會跟著死。
3. 沒人在聽就地把 uvicorn 跑起來（in-process；不必再開一層 subprocess）。

.env 金鑰不必在這裡讀——app.main 自己會讀（`_load_dotenv`，2026-08-23 那次「換個啟動
方式就悄悄少了金鑰」之後改的：設定該由程式自己讀，不該綁在某一種啟動方式上，見
app/main.py 內該函式的說明）。

**為什麼用 pythonw.exe 而不是 python.exe 或另包一支 .vbs**：python.exe 是主控台子系統
執行檔，Windows 一定會替它分配一個主控台視窗；pythonw.exe 是 GUI 子系統執行檔，Windows
從一開始就不會分配主控台——不必再包一層 .vbs／WScript.Shell.Run 去隱藏視窗，少一個要
維護的殼。代價是 pythonw 底下沒有真正的 stdout/stderr 可以印，直接讓 uvicorn 往那裡寫
字會讓啟動器整支炸掉（`AttributeError`），所以下面先把兩者接到一個 log 檔再匯入 uvicorn。
"""

import contextlib
import os
import socket
import subprocess
import sys
import threading
from pathlib import Path
from typing import TextIO

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_PORT = 8710
_LOG_PATH = _REPO_ROOT / "logs" / "boot_launcher.log"
_WORKER_LOG_PATH = _REPO_ROOT / "logs" / "worker.log"
_RESTART_DELAYS = (2, 5, 15)


class _WorkerWatchdog:
    """Own only the child we created; never discover or kill somebody else's worker."""

    def __init__(self, log: TextIO):
        self.log = log
        self.child: subprocess.Popen | None = None
        self.stop_event = threading.Event()
        self.guard = threading.Lock()
        self.thread: threading.Thread | None = None

    def _spawn(self) -> None:
        with self.guard:
            if self.stop_event.is_set():
                return
            try:
                self.child = subprocess.Popen(
                    [sys.executable, "-m", "app.worker"],
                    cwd=_REPO_ROOT,
                    stdout=self.log,
                    stderr=self.log,
                    creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
                )
            except OSError:
                self.child = None
                print("worker 無法啟動，依有限次數重試。", file=self.log)

    def start(self) -> None:
        self._spawn()
        self.thread = threading.Thread(target=self._run, name="worker-watchdog", daemon=True)
        self.thread.start()

    def _run(self) -> None:
        restarts = 0
        while not self.stop_event.is_set():
            code = self.child.poll() if self.child is not None else -1
            if code is None:
                self.stop_event.wait(0.5)
                continue
            if code == 0:
                # Includes a duplicate worker declining the schema lock.
                return
            if restarts == len(_RESTART_DELAYS):
                print("worker 重啟已達 3 次上限，網站保留；請查看 worker.log。", file=self.log)
                return
            delay = _RESTART_DELAYS[restarts]
            restarts += 1
            print(f"worker 異常結束；{delay} 秒後進行第 {restarts} 次重啟。", file=self.log)
            if self.stop_event.wait(delay):
                return
            self._spawn()

    def stop(self) -> None:
        self.stop_event.set()
        if self.thread is not None:
            self.thread.join(timeout=5)
        # Serialize shutdown against a spawn already in progress. _spawn checks the
        # stop event while holding the same guard, so no replacement escapes cleanup.
        with self.guard:
            child = self.child
            if child is None or child.poll() is not None:
                return
            self._terminate(child)
            try:
                child.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self._terminate(child, force=True)
                try:
                    child.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    print("worker 終止等待逾時，保留錯誤供檢查。", file=self.log)

    def _terminate(self, child: subprocess.Popen, *, force: bool = False) -> None:
        if os.name == "nt":
            # A Windows venv python.exe may be only a launcher. Killing that PID
            # alone would orphan the real interpreter. /T follows this owned PID's
            # descendants; never select processes by image name or search other workers.
            # Windows terminate() is already forceful; /F preserves that behavior.
            try:
                result = subprocess.run(
                    ["taskkill", "/PID", str(child.pid), "/T", "/F"],
                    capture_output=True,
                    timeout=5,
                    check=False,
                    creationflags=subprocess.CREATE_NO_WINDOW,
                )
                if result.returncode and child.poll() is None:
                    print("worker 子行程樹終止失敗，保留錯誤供檢查。", file=self.log)
            except (OSError, subprocess.TimeoutExpired):
                print("worker 子行程樹終止未完成，保留錯誤供檢查。", file=self.log)
        elif force:
            child.kill()
        else:
            child.terminate()


def _port_is_listening(port: int, host: str = "127.0.0.1") -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.5)
        return sock.connect_ex((host, port)) == 0


def main() -> None:
    if _port_is_listening(_PORT):
        return  # 已經有人在跑了（例如使用者自己手動開的），不重複啟動

    _LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    _WORKER_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with (
        open(_LOG_PATH, "a", encoding="utf-8", buffering=1) as log_file,
        open(_WORKER_LOG_PATH, "a", encoding="utf-8", buffering=1) as worker_log,
        contextlib.redirect_stdout(log_file),
        contextlib.redirect_stderr(log_file),
    ):
        print(f"---- boot_launcher 啟動 {__file__} ----")
        if str(_REPO_ROOT) not in sys.path:
            sys.path.insert(0, str(_REPO_ROOT))
        watchdog = _WorkerWatchdog(worker_log)
        try:
            watchdog.start()
            import uvicorn  # logs and import path must be ready before importing

            uvicorn.run("app.main:app", host="127.0.0.1", port=_PORT, log_config=None)
        finally:
            watchdog.stop()


if __name__ == "__main__":
    main()
