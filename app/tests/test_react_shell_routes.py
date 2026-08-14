# -*- coding: utf-8 -*-
"""app/tests/test_react_shell_routes.py — 票 05-spa-routing 機器驗收：新殼子路徑
（品牌駕駛艙等）直接貼網址／重新整理不能 404，後端 `/app` StaticFiles 掛載要接住
react-router 接手的子路徑，退回 index.html（見 app/main.py `_SpaStaticFiles`）。

這條測試需要 frontend/dist 存在（`npm run build` 產物，不進版控）才有意義；
沒 build 過的機器直接跳過，不擋其他人跑測試（同 test_real_db_schema_drift.py
「沒有就跳過」的慣例）。
"""

import atexit
import os
import shutil
import tempfile
import unittest
from pathlib import Path

_tmpdir = tempfile.mkdtemp(prefix="brand_os_react_shell_")

from fastapi.testclient import TestClient  # noqa: E402

import app.main as main  # noqa: E402
from app.shared import web  # noqa: E402


_FRONTEND_DIST = web.BASE_DIR.parent / "frontend" / "dist"


def _cleanup():
    try:
        main.conn.close()
    except Exception:
        pass
    shutil.rmtree(_tmpdir, ignore_errors=True)


atexit.register(_cleanup)


@unittest.skipUnless(_FRONTEND_DIST.is_dir(), "frontend/dist 不存在，先 npm run build")
class ReactShellSpaFallbackTest(unittest.TestCase):
    """驗收條件：子路徑網址直接開、重新整理都正常，不會 404（票 05 checklist 第一條）。"""

    def setUp(self):
        self.client = TestClient(main.app)

    def test_brand_subpath_serves_index_html_not_404(self):
        """/app/brands/xxx 不是實體檔案，沒有 SPA fallback 一定 404；有的話要回
        index.html（200），交給 react-router 接手決定畫面。"""
        resp = self.client.get("/app/brands/some-brand-id")
        self.assertEqual(resp.status_code, 200)
        self.assertIn('<div id="root">', resp.text)

    def test_mount_root_still_serves_index_html(self):
        """掛載根目錄本來就會回退到 index.html，加了 SPA fallback 之後這條也不能壞。"""
        resp = self.client.get("/app/")
        self.assertEqual(resp.status_code, 200)
        self.assertIn('<div id="root">', resp.text)


if __name__ == "__main__":
    unittest.main()
