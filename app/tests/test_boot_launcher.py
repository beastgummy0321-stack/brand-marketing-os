"""app/tests/test_boot_launcher.py — 票 F6：無視窗啟動器的 port 探測邏輯。

Port probing uses a local socket. Watchdog tests replace Popen, clocks and uvicorn;
they never start a real server, worker, provider or platform request.
"""

import io
import os
import socket
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

from app.tools import boot_launcher
from app.tools.boot_launcher import _port_is_listening


class PortIsListeningTest(unittest.TestCase):
    def test_true_when_something_is_listening_on_the_port(self):
        server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        server.bind(("127.0.0.1", 0))
        server.listen(1)
        try:
            port = server.getsockname()[1]
            self.assertTrue(_port_is_listening(port))
        finally:
            server.close()

    def test_false_when_nothing_is_listening_on_the_port(self):
        # 借一個當下沒人用的 port 號：先開一個 socket 拿系統配的空號，關掉後短時間內
        # 大機率還是空的——用來確認「沒人聽」那個分支，不必猜死一個固定 port。
        probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
        probe.close()
        self.assertFalse(_port_is_listening(port))


class WorkerWatchdogTest(unittest.TestCase):
    def test_nonzero_exits_have_three_bounded_restarts(self):
        watchdog = boot_launcher._WorkerWatchdog(io.StringIO())
        watchdog.stop_event = mock.Mock()
        watchdog.stop_event.is_set.return_value = False
        watchdog.stop_event.wait.return_value = False
        child = mock.Mock()
        child.poll.return_value = 1
        with mock.patch.object(boot_launcher.subprocess, "Popen", return_value=child) as spawn:
            watchdog._spawn()
            watchdog._run()
        self.assertEqual(spawn.call_count, 4)
        self.assertEqual(
            watchdog.stop_event.wait.call_args_list, [mock.call(2), mock.call(5), mock.call(15)]
        )
        self.assertIn("3 次上限", watchdog.log.getvalue())
        self.assertEqual(spawn.call_args.kwargs["cwd"], boot_launcher._REPO_ROOT)
        self.assertNotIn("env", spawn.call_args.kwargs)  # keep configured DSN and fixture guards

    def test_spawn_failure_consumes_same_budget(self):
        watchdog = boot_launcher._WorkerWatchdog(io.StringIO())
        watchdog.stop_event = mock.Mock()
        watchdog.stop_event.is_set.return_value = False
        watchdog.stop_event.wait.return_value = False
        with mock.patch.object(
            boot_launcher.subprocess, "Popen", side_effect=OSError("not found")
        ) as spawn:
            watchdog._spawn()
            watchdog._run()
        self.assertEqual(spawn.call_count, 4)

    def test_clean_exit_and_duplicate_worker_do_not_restart(self):
        watchdog = boot_launcher._WorkerWatchdog(io.StringIO())
        watchdog.child = mock.Mock()
        watchdog.child.poll.return_value = 0
        with mock.patch.object(watchdog, "_spawn") as spawn:
            watchdog._run()
        spawn.assert_not_called()

    def test_shutdown_interrupts_backoff_without_spawning(self):
        watchdog = boot_launcher._WorkerWatchdog(io.StringIO())
        watchdog.stop_event = mock.Mock()
        watchdog.stop_event.is_set.return_value = False
        watchdog.stop_event.wait.return_value = True
        with mock.patch.object(watchdog, "_spawn") as spawn:
            watchdog._run()
        spawn.assert_not_called()

    def test_stop_terminates_only_owned_child_and_kills_after_timeout(self):
        watchdog = boot_launcher._WorkerWatchdog(io.StringIO())
        child = mock.Mock()
        child.poll.return_value = None
        child.wait.side_effect = [subprocess.TimeoutExpired("worker", 5), 0]
        watchdog.child = child
        with mock.patch.object(boot_launcher.os, "name", "posix"):
            watchdog.stop()
        child.terminate.assert_called_once()
        child.kill.assert_called_once()
        self.assertEqual(child.wait.call_args_list, [mock.call(timeout=5), mock.call(timeout=5)])
        with mock.patch.object(boot_launcher.subprocess, "Popen") as spawn:
            watchdog._spawn()
        spawn.assert_not_called()

    def test_second_wait_is_bounded_and_recorded(self):
        watchdog = boot_launcher._WorkerWatchdog(io.StringIO())
        watchdog.child = mock.Mock()
        watchdog.child.poll.return_value = None
        watchdog.child.wait.side_effect = subprocess.TimeoutExpired("worker", 5)
        with mock.patch.object(watchdog, "_terminate"):
            watchdog.stop()
        self.assertEqual(watchdog.child.wait.call_count, 2)
        self.assertIn("終止等待逾時", watchdog.log.getvalue())

    def test_shutdown_during_spawn_cannot_leave_a_new_child_running(self):
        watchdog = boot_launcher._WorkerWatchdog(io.StringIO())
        child = mock.Mock()
        child.poll.return_value = None
        entered, release = threading.Event(), threading.Event()

        def create(*args, **kwargs):
            entered.set()
            if not release.wait(timeout=2):
                raise AssertionError("test did not release pending spawn")
            return child

        with (
            mock.patch.object(boot_launcher.subprocess, "Popen", side_effect=create),
            mock.patch.object(watchdog, "_terminate") as terminate,
        ):
            spawning = threading.Thread(target=watchdog._spawn)
            stopping = threading.Thread(target=watchdog.stop)
            spawning.start()
            try:
                self.assertTrue(entered.wait(timeout=2))
                stopping.start()
                self.assertTrue(watchdog.stop_event.wait(timeout=2))
            finally:
                release.set()
                spawning.join(timeout=2)
                if stopping.ident is not None:
                    stopping.join(timeout=2)
        self.assertFalse(spawning.is_alive())
        self.assertFalse(stopping.is_alive())
        terminate.assert_called_once_with(child)
        child.wait.assert_called_once_with(timeout=5)

    @unittest.skipUnless(os.name == "nt", "Windows process-tree contract")
    def test_windows_termination_targets_only_owned_pid_tree(self):
        watchdog = boot_launcher._WorkerWatchdog(io.StringIO())
        child = mock.Mock(pid=12345)
        child.poll.return_value = None
        watchdog.child = child
        with mock.patch.object(subprocess, "run", return_value=mock.Mock(returncode=0)) as run:
            watchdog.stop()
        run.assert_called_once_with(
            ["taskkill", "/PID", "12345", "/T", "/F"],
            capture_output=True,
            timeout=5,
            check=False,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        child.terminate.assert_not_called()
        child.kill.assert_not_called()

    @unittest.skipUnless(os.name == "nt", "Windows process-tree contract")
    def test_real_venv_launcher_and_python_descendant_both_exit(self):
        # No app.worker import: these children only record identity and sleep.
        # Open handles before stopping so a recycled PID cannot fake successful cleanup.
        import ctypes
        from ctypes import wintypes

        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        kernel.OpenProcess.restype = wintypes.HANDLE
        kernel.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
        kernel.WaitForSingleObject.restype = wintypes.DWORD
        kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        code = (
            "import os,sys,time,subprocess;from pathlib import Path;"
            "subprocess.Popen([sys.executable,'-c',"
            "'import os,sys,time;from pathlib import Path;"
            "Path(sys.argv[1]).write_text(str(os.getpid()));time.sleep(20)',sys.argv[2]],"
            "creationflags=subprocess.CREATE_NO_WINDOW);"
            "Path(sys.argv[1]).write_text(str(os.getpid()));time.sleep(20)"
        )
        with tempfile.TemporaryDirectory() as directory:
            paths = [Path(directory) / name for name in ("parent.pid", "descendant.pid")]
            watchdog = boot_launcher._WorkerWatchdog(io.StringIO())
            watchdog.child = subprocess.Popen(
                [sys.executable, "-c", code, *(str(path) for path in paths)],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
            handles = []
            try:
                deadline = time.monotonic() + 10
                while not all(path.exists() and path.read_text().strip() for path in paths):
                    self.assertLess(time.monotonic(), deadline, "owned child did not become ready")
                    time.sleep(0.02)
                for path in paths:
                    handle = kernel.OpenProcess(0x00100000, False, int(path.read_text()))
                    self.assertTrue(handle)
                    handles.append(handle)
                watchdog.stop()
                self.assertIsNotNone(watchdog.child.poll())
                for handle in handles:
                    self.assertEqual(kernel.WaitForSingleObject(handle, 5000), 0)
            finally:
                watchdog.stop()
                for handle in handles:
                    kernel.CloseHandle(handle)

    def test_live_web_still_starts_and_supervises_worker_before_cleanup(self):
        calls = []
        with (
            tempfile.TemporaryDirectory() as directory,
            mock.patch.object(boot_launcher, "_port_is_listening", return_value=True),
            mock.patch.object(boot_launcher, "_port_status", return_value="alive"),
            mock.patch.object(boot_launcher, "_LOG_PATH", Path(directory) / "boot.log"),
            mock.patch.object(boot_launcher, "_WORKER_LOG_PATH", Path(directory) / "worker.log"),
            mock.patch.object(boot_launcher, "_WorkerWatchdog") as watchdog,
            mock.patch("uvicorn.run") as web,
        ):
            watchdog.return_value.start.side_effect = lambda: calls.append("start")
            watchdog.return_value.thread.is_alive.side_effect = [True, False]
            watchdog.return_value.stop_event.wait.side_effect = lambda _: calls.append("supervise")
            watchdog.return_value.stop.side_effect = lambda: calls.append("stop")
            boot_launcher.main()
        self.assertEqual(calls, ["start", "supervise", "stop"])
        web.assert_not_called()

    def test_external_web_exit_stops_only_owned_worker(self):
        with (
            tempfile.TemporaryDirectory() as directory,
            mock.patch.object(boot_launcher, "_port_is_listening", return_value=True),
            mock.patch.object(boot_launcher, "_port_status", return_value="refused") as probe,
            mock.patch.object(boot_launcher, "_LOG_PATH", Path(directory) / "boot.log"),
            mock.patch.object(boot_launcher, "_WORKER_LOG_PATH", Path(directory) / "worker.log"),
            mock.patch.object(boot_launcher, "_WorkerWatchdog") as watchdog,
        ):
            watchdog.return_value.thread.is_alive.return_value = True
            boot_launcher.main()
        watchdog.return_value.start.assert_called_once()
        watchdog.return_value.stop.assert_called_once()
        self.assertEqual(probe.call_count, boot_launcher._WEB_STOP_CONFIRMATIONS)

    def test_transient_refusals_and_unknown_probes_do_not_stop_owned_worker(self):
        statuses = ["refused"] * 5 + ["unknown"] + ["refused"] * 5 + ["alive"]
        with (
            tempfile.TemporaryDirectory() as directory,
            mock.patch.object(boot_launcher, "_port_is_listening", return_value=True),
            mock.patch.object(boot_launcher, "_port_status", side_effect=statuses) as probe,
            mock.patch.object(boot_launcher, "_LOG_PATH", Path(directory) / "boot.log"),
            mock.patch.object(boot_launcher, "_WORKER_LOG_PATH", Path(directory) / "worker.log"),
            mock.patch.object(boot_launcher, "_WorkerWatchdog") as watchdog,
        ):
            watchdog.return_value.thread.is_alive.side_effect = [True] * len(statuses) + [False]
            boot_launcher.main()
        self.assertEqual(probe.call_count, len(statuses))
        self.assertEqual(watchdog.return_value.stop_event.wait.call_count, len(statuses))
        watchdog.return_value.stop.assert_called_once()

    def test_probe_timeout_is_unknown_and_refusal_is_explicit(self):
        with mock.patch.object(boot_launcher.socket, "socket") as factory:
            sock = factory.return_value.__enter__.return_value
            for code, state in ((0, "alive"), (10061, "refused"), (10060, "unknown")):
                sock.connect_ex.return_value = code
                self.assertEqual(boot_launcher._port_status(8710), state)
            sock.connect_ex.side_effect = OSError("probe unavailable")
            self.assertEqual(boot_launcher._port_status(8710), "unknown")

    def test_web_failure_always_stops_owned_watchdog(self):
        with (
            tempfile.TemporaryDirectory() as directory,
            mock.patch.object(boot_launcher, "_port_is_listening", return_value=False),
            mock.patch.object(boot_launcher, "_LOG_PATH", Path(directory) / "boot.log"),
            mock.patch.object(boot_launcher, "_WORKER_LOG_PATH", Path(directory) / "worker.log"),
            mock.patch.object(boot_launcher, "_WorkerWatchdog") as watchdog,
            mock.patch("uvicorn.run", side_effect=RuntimeError("web stopped")),
        ):
            with self.assertRaisesRegex(RuntimeError, "web stopped"):
                boot_launcher.main()
        watchdog.return_value.start.assert_called_once()
        watchdog.return_value.stop.assert_called_once()


if __name__ == "__main__":
    unittest.main()
