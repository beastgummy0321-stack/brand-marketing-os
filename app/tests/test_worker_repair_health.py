"""Launcher supervision lifecycle only; no shared queue or provider is started."""

import tempfile
from pathlib import Path
from unittest import mock

import pytest

from app import background
from app.core import config
from app.tools import boot_launcher


def test_intentional_stop_cleans_owned_watchdog_with_existing_web():
    with (
        tempfile.TemporaryDirectory() as directory,
        mock.patch.object(boot_launcher, "_port_is_listening", return_value=True),
        mock.patch.object(boot_launcher, "_port_status", return_value="alive"),
        mock.patch.object(boot_launcher, "_LOG_PATH", Path(directory) / "boot.log"),
        mock.patch.object(boot_launcher, "_WORKER_LOG_PATH", Path(directory) / "worker.log"),
        mock.patch.object(boot_launcher, "_WorkerWatchdog") as watchdog,
    ):
        watchdog.return_value.thread.is_alive.return_value = True
        watchdog.return_value.stop_event.wait.side_effect = KeyboardInterrupt()
        with pytest.raises(KeyboardInterrupt):
            boot_launcher.main()
    watchdog.return_value.start.assert_called_once()
    watchdog.return_value.stop.assert_called_once()


def test_memory_health_is_not_operational_worker_evidence():
    with mock.patch.object(config.settings(), "brand_os_job_queue", "memory"):
        health = background.worker_health()
    assert health["state"] == "unknown"
    assert health["reason_code"] == "test_queue"
    assert health["last_heartbeat_at"] is None
