# -*- coding: utf-8 -*-
"""專案搬家後，所有預設資料目錄都從模組位置推導，不依賴工作目錄。"""

import os
import unittest
from pathlib import Path
from unittest import mock

from app.brand_web import routes_library
from app.core import backup, creative_assets, db
from app.intake import state as intake_state


class RelocationPathsTest(unittest.TestCase):
    def test_defaults_are_repo_relative_without_environment_overrides(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            self.assertEqual(db.get_db_path(), db.REPO_ROOT / "data" / "app.db")
            self.assertEqual(backup.get_backup_dir(), db.REPO_ROOT / "backups")
            self.assertEqual(creative_assets.DEFAULT_ROOT, db.REPO_ROOT / "data" / "creative")
            self.assertEqual(intake_state.get_upload_dir(), db.REPO_ROOT / "data" / "uploads" / "intake")
            self.assertEqual(routes_library._assets_upload_dir(), db.REPO_ROOT / "data" / "uploads" / "assets")

    def test_environment_overrides_are_unchanged(self):
        with mock.patch.dict(os.environ, {
            "BRAND_OS_DB": "X:/custom/app.db",
            "BRAND_OS_BACKUP_DIR": "X:/custom/backups",
            "BRAND_OS_UPLOADS": "X:/custom/uploads",
        }, clear=True):
            self.assertEqual(db.get_db_path(), Path("X:/custom/app.db"))
            self.assertEqual(backup.get_backup_dir(), Path("X:/custom/backups"))
            self.assertEqual(intake_state.get_upload_dir(), Path("X:/custom/uploads"))
            self.assertEqual(routes_library._assets_upload_dir(), Path("X:/custom/uploads/assets"))

    def test_app_source_has_no_former_desktop_path(self):
        source = Path(db.REPO_ROOT) / "app"
        old_path = "C:" + "/Users/User/Desktop"
        self.assertFalse(any(old_path in path.read_text(encoding="utf-8")
                             for path in source.rglob("*.py")))
