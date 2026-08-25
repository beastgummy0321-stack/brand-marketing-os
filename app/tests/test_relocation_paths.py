# -*- coding: utf-8 -*-
"""專案搬家後，所有預設資料目錄都從模組位置推導，不依賴工作目錄。

02-4：資料庫檔案路徑與備份目錄相關的存取函式在 ADR 0027 已整個退場——Postgres 沒有
單一資料庫檔案路徑，Supabase 自己管備份。素材根目錄／上傳目錄仍是本機檔案系統路徑
（Storage 遷移是後續切片的事），這兩項的環境變數覆寫行為照舊測。"""

import os
import unittest
from pathlib import Path
from unittest import mock

from app.brand_web import routes_library
from app.core import creative_assets, db
from app.intake import state as intake_state


class RelocationPathsTest(unittest.TestCase):
    def test_defaults_are_repo_relative_without_environment_overrides(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            self.assertEqual(creative_assets.DEFAULT_ROOT, db.REPO_ROOT / "data" / "creative")
            self.assertEqual(intake_state.get_upload_dir(), db.REPO_ROOT / "data" / "uploads" / "intake")
            self.assertEqual(routes_library._assets_upload_dir(), db.REPO_ROOT / "data" / "uploads" / "assets")

    def test_environment_overrides_are_unchanged(self):
        with mock.patch.dict(os.environ, {
            "BRAND_OS_UPLOADS": "X:/custom/uploads",
        }, clear=True):
            self.assertEqual(intake_state.get_upload_dir(), Path("X:/custom/uploads"))
            self.assertEqual(routes_library._assets_upload_dir(), Path("X:/custom/uploads/assets"))

    def test_app_source_has_no_former_desktop_path(self):
        source = Path(db.REPO_ROOT) / "app"
        old_path = "C:" + "/Users/User/Desktop"
        self.assertFalse(any(old_path in path.read_text(encoding="utf-8")
                             for path in source.rglob("*.py")))
