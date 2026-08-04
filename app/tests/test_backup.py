# -*- coding: utf-8 -*-
"""app/tests/test_backup.py — 修憲落地 M5：備份改成真正的每日。

`app/core/backup.py` 的 `run_daily_backup()` 本身邏輯沒問題（今天沒備份就複製、
留最近 30 份）；壞的是呼叫時機——舊版 `app/main.py` 只在 process 啟動時呼叫一次
（見 `_startup()`），uvicorn 開一週不重啟就一週沒有新備份。

兩層測試：
1. `BackupCoreTest`：直接測 `run_daily_backup()` / `_prune()` 本身的三個行為
   （跨日新增、同一天不重複、上限 30 份仍生效）。
2. `MainDailyCheckTest`：測 `app/main.py` 有沒有在啟動之外的請求路徑上補這個檢查
   ——這才是本票要修的實際 bug（重現：把快取的「上次檢查日期」撥回過去，
   模擬「process 已經開了一陣子、今天還沒備過」，發一個請求應該要觸發備份）。
"""

import atexit
import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from app.core import backup as corebackup

# 先備好暫存 DB 的環境變數，才能 import app.main（它在 import 當下就會連線＋跑 migrations）。
# 跟 test_settings_page.py／test_capacity_check.py 同一套模式：模組層級只設定一次、
# 清理交給 atexit（process 結束才清）——app.main 的連線是整個測試 session 共用的全域單例，
# 每個測試方法各自 close＋rmtree 會把後面其他檔案要用的 main.conn 也一併關掉。
_tmpdir = tempfile.mkdtemp(prefix="brand_os_backup_test_")
os.environ["BRAND_OS_DB"] = str(Path(_tmpdir) / "test.db")
os.environ["BRAND_OS_BACKUP_DIR"] = str(Path(_tmpdir) / "backups")
os.environ["BRAND_OS_UPLOADS"] = str(Path(_tmpdir) / "uploads")

from fastapi.testclient import TestClient  # noqa: E402

import app.main as main  # noqa: E402

main.reopen_connection()


def _cleanup():
    try:
        main.conn.close()
    except Exception:
        pass
    shutil.rmtree(_tmpdir, ignore_errors=True)


atexit.register(_cleanup)


class BackupCoreTest(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.db_path = Path(self._tmpdir.name) / "app.db"
        self.db_path.write_bytes(b"fake-sqlite-content")
        self.backup_dir = Path(self._tmpdir.name) / "backups"

    def tearDown(self):
        self._tmpdir.cleanup()

    def test_missing_backup_for_today_gets_created(self):
        self.assertEqual(list(self.backup_dir.glob("*.db")) if self.backup_dir.exists() else [], [])
        corebackup.run_daily_backup(self.db_path, self.backup_dir)
        files = list(self.backup_dir.glob("????-??-??.db"))
        self.assertEqual(len(files), 1)

    def test_existing_backup_for_today_is_not_recopied(self):
        with mock.patch("app.core.backup.shutil.copy2", wraps=shutil.copy2) as copy_spy:
            corebackup.run_daily_backup(self.db_path, self.backup_dir)
            self.assertEqual(copy_spy.call_count, 1)
            corebackup.run_daily_backup(self.db_path, self.backup_dir)
            self.assertEqual(copy_spy.call_count, 1)  # 同一天第二次呼叫不會再複製一次
        files = list(self.backup_dir.glob("????-??-??.db"))
        self.assertEqual(len(files), 1)

    def test_backups_over_cap_are_pruned_to_thirty(self):
        self.backup_dir.mkdir(parents=True, exist_ok=True)
        # 造 35 份跨越舊日期的假備份檔（比今天早很多，檔名格式跟 _prune 掃描的一致）
        for i in range(35):
            (self.backup_dir / f"2020-01-{i + 1:02d}.db").write_bytes(b"old")
        corebackup.run_daily_backup(self.db_path, self.backup_dir)  # 連今天這份共 36 份
        files = sorted(f.name for f in self.backup_dir.glob("????-??-??.db"))
        self.assertEqual(len(files), 30)  # 36 份剪到剩 30，砍掉最舊的 6 份
        self.assertNotIn("2020-01-01.db", files)  # 最舊的先被砍
        self.assertIn("2020-01-35.db", files)  # 舊檔裡日期較新的留著
        self.assertTrue(any(name.startswith("20") and name[:4] != "2020" for name in files))  # 今天的備份也在


class MainDailyCheckTest(unittest.TestCase):
    """測 app/main.py 有沒有在請求路徑上補「今天備份了嗎」的檢查（本票要修的 bug）。

    做法：不重開 process、不動真的 datetime，只把 main.py 內部快取的
    「上次檢查日期」直接改成一個過去的假日期，模擬「process 已經開很久、
    今天還沒檢查過」，再發一個請求，看 run_daily_backup 有沒有被叫到。
    """

    def setUp(self):
        self.client = TestClient(main.app)

    def test_request_after_stale_cached_date_triggers_backup_without_restart(self):
        # 模擬「process 開很久了，快取的上次檢查日期是很久以前」——不重開、不動真的時鐘
        main._last_backup_check = "1970-01-01"
        with mock.patch.object(
            main.corebackup, "run_daily_backup", wraps=main.corebackup.run_daily_backup
        ) as backup_spy:
            resp = self.client.get("/")
            self.assertEqual(resp.status_code, 200)
            self.assertEqual(backup_spy.call_count, 1)  # 跨日快取過期，請求路徑上補了一次備份

    def test_second_request_same_day_does_not_trigger_backup_again(self):
        self.client.get("/")  # 第一次請求，快取已經記到今天
        with mock.patch.object(main.corebackup, "run_daily_backup") as backup_spy:
            resp = self.client.get("/")
            self.assertEqual(resp.status_code, 200)
            backup_spy.assert_not_called()  # 同一天不會重複觸發


if __name__ == "__main__":
    unittest.main()
