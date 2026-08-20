# -*- coding: utf-8 -*-
"""app/tests/test_core_db.py — 全域連線在多執行緒下的讀取正確性（F0 票 01）。

全站共用同一條連線（app/shared/web.py:47），背景工作與請求執行緒會同時讀。
只鎖 execute()、讓 fetchone/fetchall 在鎖外跑，兩條執行緒就會互踩同一條連線的游標，
安靜地讀到 None、整列 NULL 或別筆資料。這裡守住「併發讀不得有壞讀」。
"""

import tempfile
import threading
import unittest
from pathlib import Path

from app.core import db

_THREADS = 4
_READS_PER_THREAD = 15000


class ConcurrentReadTest(unittest.TestCase):
    """多執行緒同時讀同一筆，斷言零壞讀（讀不到／整列 NULL／讀到別筆／拋例外）。"""

    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.conn = db.connect(Path(self._tmpdir.name) / "test.db")
        self.conn.execute("CREATE TABLE t (id TEXT PRIMARY KEY, a TEXT)")
        for i in range(50):
            self.conn.execute("INSERT INTO t VALUES (?, ?)", (f"k{i}", f"a{i}"))
        self.conn.commit()

    def tearDown(self):
        self.conn.close()
        self._tmpdir.cleanup()

    def test_concurrent_reads_never_return_wrong_row(self):
        bad = []

        def reader():
            for _ in range(_READS_PER_THREAD):
                try:
                    row = self.conn.execute(
                        "SELECT * FROM t WHERE id = ?", ("k7",)
                    ).fetchone()
                    if row is None:
                        bad.append("讀不到")
                    elif row["id"] != "k7" or row["a"] != "a7":
                        bad.append(f"讀到別筆或整列 NULL: {tuple(row)}")
                except Exception as exc:  # 互踩游標會直接拋 sqlite3.InterfaceError
                    bad.append(f"{type(exc).__name__}: {exc}")

        threads = [threading.Thread(target=reader) for _ in range(_THREADS)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        self.assertEqual(bad[:5], [], f"{len(bad)} 次壞讀（前 5 筆如上）")


if __name__ == "__main__":
    unittest.main()
