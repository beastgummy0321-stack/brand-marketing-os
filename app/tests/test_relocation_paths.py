"""專案搬家後，所有預設資料目錄都從模組位置推導，不依賴工作目錄。

02-4：資料庫檔案路徑與備份目錄相關的存取函式在 ADR 0027 已整個退場——Postgres 沒有
單一資料庫檔案路徑，Supabase 自己管備份。

票 storage-02／03：官方素材與建檔精靈照片都已搬進 Supabase Storage（ADR 0043），本機
上傳目錄與它們的環境變數覆寫（`BRAND_OS_UPLOADS`）一起退場，這裡不再測。剩下唯一還
站得住腳的斷言是「原始碼裡沒有殘留搬家前的舊路徑字串」。
"""

import unittest
from pathlib import Path

from app.core import db


class RelocationPathsTest(unittest.TestCase):
    def test_app_source_has_no_former_desktop_path(self):
        source = Path(db.REPO_ROOT) / "app"
        old_path = "C:" + "/Users/User/Desktop"
        self.assertFalse(any(old_path in path.read_text(encoding="utf-8")
                             for path in source.rglob("*.py")))
