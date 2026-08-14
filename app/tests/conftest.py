# -*- coding: utf-8 -*-
"""Pytest 啟動與逐模組資料庫隔離。"""

import atexit
import os
import shutil
import tempfile
from pathlib import Path

import pytest


_collection_tmpdir = tempfile.mkdtemp(prefix="brand_os_pytest_collection_")


def _database_environment(root: Path) -> dict[str, str]:
    return {
        "BRAND_OS_DB": str(root / "test.db"),
        "BRAND_OS_BACKUP_DIR": str(root / "backups"),
        "BRAND_OS_UPLOADS": str(root / "uploads"),
    }


def pytest_configure() -> None:
    """測試模組 import app.main 前，先擋住正式資料庫。"""
    os.environ.update(_database_environment(Path(_collection_tmpdir)))


@pytest.fixture(scope="module", autouse=True)
def isolate_module_database(request, tmp_path_factory):
    """每個使用 app.main 的測試模組執行前切回自己的資料庫。"""
    module_tmpdir = getattr(request.module, "_tmpdir", None)
    module_main = getattr(request.module, "main", None)
    if module_tmpdir is None and getattr(module_main, "__name__", None) == "app.main":
        module_tmpdir = tmp_path_factory.mktemp(request.module.__name__.rsplit(".", 1)[-1])
    if module_tmpdir is None:
        yield
        return

    os.environ.update(_database_environment(Path(module_tmpdir)))

    import app.main as main

    main.reopen_connection()
    yield


atexit.register(shutil.rmtree, _collection_tmpdir, ignore_errors=True)
