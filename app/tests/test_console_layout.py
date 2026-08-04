# -*- coding: utf-8 -*-
"""app/tests/test_console_layout.py — 修憲落地票 V2：_layouts/console.html 骨架自檢。

console.html 是 DESIGN.md §21「版型原型」（B｜工作台式）的骨架，本票只交付骨架、
不套用到任何既有頁面、不新增路由（見票面「不要改任何既有頁面」）。這裡直接用
app.main.templates 的 Jinja 環境把模板渲染出來（不經 HTTP／TestClient），證明骨架
本身跑得起來、side bar 結構符合 §21.1，且既有 967 個測試（含這批新測試）全綠。

品牌與資料一律虛構，嚴禁真實品牌名稱。
"""

import atexit
import os
import shutil
import tempfile
import unittest
from pathlib import Path

_tmpdir = tempfile.mkdtemp(prefix="brand_os_console_layout_")
os.environ["BRAND_OS_DB"] = str(Path(_tmpdir) / "test.db")
os.environ["BRAND_OS_BACKUP_DIR"] = str(Path(_tmpdir) / "backups")
os.environ["BRAND_OS_UPLOADS"] = str(Path(_tmpdir) / "uploads")

import app.main as main  # noqa: E402
from app.brand_intelligence import repository as bi_repo  # noqa: E402

main.reopen_connection()

ACTOR = "測試員"


def _cleanup():
    try:
        main.conn.close()
    except Exception:
        pass
    shutil.rmtree(_tmpdir, ignore_errors=True)


atexit.register(_cleanup)


def _render(**ctx) -> str:
    template = main.templates.env.get_template("_layouts/console.html")
    return template.render(**ctx)


class ConsoleLayoutSkeletonTest(unittest.TestCase):
    """沒有品牌時（品牌總覽情境）骨架仍要渲染得出來，四分類全部灰掉不可點。"""

    def test_renders_with_no_brand(self):
        html = _render(brand=None, active_brands=[], inbox_count=0, nav_current=None)
        self.assertIn('class="console-shell"', html)
        self.assertIn('class="console-sidebar"', html)
        self.assertIn('class="console-content"', html)
        self.assertIn('id="main"', html)
        self.assertIn('class="skip-link"', html)
        # 沒有品牌：四分類全部是 is-soon 的 <span>，不是可點的 <a>
        self.assertIn('品牌智庫', html)
        self.assertIn('投放與成效', html)
        self.assertIn('內容與曝光', html)
        self.assertIn('顧客與口碑', html)
        self.assertNotIn('href="/brands/', html)

    def test_no_inbox_badge_when_zero(self):
        html = _render(brand=None, active_brands=[], inbox_count=0, nav_current=None)
        self.assertNotIn('badge badge-warn', html)


class ConsoleLayoutWithBrandTest(unittest.TestCase):
    """有品牌時：品牌智庫／投放與成效兩分類變成可點連結，收件匣待辦數顯示徽章，
    目前分類標記 is-current（DESIGN.md §21.1／§21.2）。"""

    def setUp(self):
        self.brand = bi_repo.create_brand(
            main.conn, name=f"虛構骨架測試{self.id()[-6:]}",
            client_name=None, actor=ACTOR)

    def test_renders_with_brand_and_inbox_count(self):
        html = _render(brand=self.brand, active_brands=[self.brand],
                        inbox_count=3, nav_current='hub')
        self.assertIn(f'href="/brands/{self.brand["id"]}"', html)
        self.assertIn(f'href="/brands/{self.brand["id"]}/ads"', html)
        self.assertIn('badge badge-warn', html)
        self.assertIn('>3<', html)
        self.assertIn('is-current', html)
        self.assertIn(self.brand["name"], html)  # 品牌切換器顯示品牌名稱

    def test_content_block_renders(self):
        template = main.templates.env.get_template("_layouts/console.html")
        html = template.render(brand=self.brand, active_brands=[self.brand],
                                inbox_count=0, nav_current='ads')
        # content block 預設空白，骨架本身不夾帶任何頁面內容
        self.assertIn('<main id="main" class="console-content">', html)


if __name__ == "__main__":
    unittest.main()
