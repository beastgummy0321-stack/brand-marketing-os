"""app/tests/test_creative_assets.py — 素材圖檔資料夾（票 T-G2-1，決策 0008）。

守三件事：設定頁改得動根目錄、刪品牌會連資料夾一起刪，以及最重要的那道——**刪除路徑
一定先確認落在根目錄底下**，設定被改成怪值時不能遞迴刪到別的東西（code-rules 第四節，
防資料遺失）。

外殼切片（2026-08-28）：檔期／主題層的資料夾測試（`CycleFolderTest`、
`MatrixFolderApiTest`、刪檔期的 cascade）隨 `app/ads/` 一起刪掉——檔期概念沒了，
`creative_assets.cycle_dir()`／`theme_dir()` 也一併移除。路徑守衛全部保留。

os.startfile() 會真的彈出檔案總管視窗，測試一律 patch 掉，不讓 pytest 開一堆視窗。
品牌名一律虛構。
"""

import atexit
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

_tmpdir = tempfile.mkdtemp(prefix="brand_os_creative_assets_")

from fastapi.testclient import TestClient  # noqa: E402

import app.main as main  # noqa: E402
from app.brand_intelligence import repository as bi_repo  # noqa: E402
from app.core import creative_assets  # noqa: E402
from app.core import settings as coresettings  # noqa: E402
from app.core.db import DEV_ORG_ID  # noqa: E402


def _cleanup():
    try:
        main.conn.close()
    except Exception:
        pass
    shutil.rmtree(_tmpdir, ignore_errors=True)


atexit.register(_cleanup)

ACTOR = "測試員"
ROOT = Path(_tmpdir) / "creative"


class _Base(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(main.app)
        coresettings.set_setting(main.conn, creative_assets.SETTING_KEY, str(ROOT),
            org_id=DEV_ORG_ID)
        self.brand = bi_repo.create_brand(main.conn, name="虛構月見茶飲（素材資料夾）",
                                          client_name="測試客戶", actor=ACTOR, org_id=DEV_ORG_ID)
        self.bid = self.brand["id"]
        self.pid = bi_repo.create_product(main.conn, self.bid, name="虛構冷萃包",
                                          actor=ACTOR)["id"]

    def _put_file(self, path: Path, mb: float) -> None:
        path.mkdir(parents=True, exist_ok=True)
        (path / "圖.png").write_bytes(b"x" * int(1024 * 1024 * mb))


class RootSettingTest(_Base):
    def test_blank_setting_falls_back_to_default_root(self):
        coresettings.set_setting(main.conn, creative_assets.SETTING_KEY, "", org_id=DEV_ORG_ID)
        self.assertEqual(
            creative_assets.get_root(main.conn, org_id=DEV_ORG_ID), creative_assets.DEFAULT_ROOT)

    def test_setting_page_saves_an_absolute_path(self):
        target = Path(_tmpdir) / "另一顆硬碟"
        resp = self.client.post("/api/settings/creative-root",
                                json={"creative_root": str(target)})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(creative_assets.get_root(main.conn, org_id=DEV_ORG_ID), target)
        coresettings.set_setting(main.conn, creative_assets.SETTING_KEY, str(ROOT),
            org_id=DEV_ORG_ID)

    def test_setting_page_rejects_relative_path_and_drive_root(self):
        for bad in ("", "行銷素材", "C:\\"):
            with self.subTest(bad=bad):
                resp = self.client.post("/api/settings/creative-root",
                                        json={"creative_root": bad})
                self.assertEqual(resp.status_code, 400)
                self.assertEqual(creative_assets.get_root(main.conn, org_id=DEV_ORG_ID), ROOT)


class OpenFolderGuardTest(_Base):
    """開資料夾的路徑守衛。跟下面的刪除守衛共用同一份 _child()／_inside()，但守的是另一側
    ——**建**資料夾：id 帶 .. 時不能在根目錄外面 mkdir 出東西、更不能把檔案總管開到那裡。
    """

    def test_refuses_to_create_or_open_anything_outside_the_root(self):
        outside = Path(_tmpdir) / "根目錄外面"
        self.assertFalse(outside.exists())

        with mock.patch("os.startfile", create=True) as startfile:
            with self.assertRaises(ValueError):
                creative_assets.open_folder(main.conn, "..", "根目錄外面", org_id=DEV_ORG_ID)

        self.assertFalse(outside.exists(), "被擋下的路徑不該被建出來")
        startfile.assert_not_called()

    def test_traversal_shaped_ids_never_reach_the_filesystem_through_the_route(self):
        """路由這一側。網址裡的 %2e%2e 解出來就是 ..（實測會原封不動進到路徑參數，不會被
        用戶端先正規化掉），所以這串真的會被拿去組路徑。品牌查無此 id 先擋成 404，資料夾
        那一步走不到；就算哪天有人把順序改壞，`_child()` 還會再擋一次。不得回 500，
        也不得在根目錄外面留下 ROOT/../外流 這種東西。"""
        escaped = Path(_tmpdir) / "外流"   # ＝ ROOT/../外流，穿越成功的話會出現在這
        self.assertFalse(escaped.exists())

        resp = self.client.post("/api/library/brands/%2e%2e%2F%E5%A4%96%E6%B5%81/delete",
                                json={"confirm_name": "外流"})

        self.assertEqual(resp.status_code, 404)
        self.assertFalse(escaped.exists(), "被擋下的路徑不該被建出來")


class DeleteFolderGuardTest(_Base):
    """刪除路徑守衛：這是全票最不能簡化的一段。"""

    def test_refuses_to_delete_anything_outside_the_root(self):
        outside = Path(_tmpdir) / "別的東西"
        outside.mkdir(parents=True, exist_ok=True)
        (outside / "重要.txt").write_text("不可以被刪掉", encoding="utf-8")

        with self.assertRaises(ValueError):
            creative_assets.delete_folder(main.conn, "..", "別的東西", org_id=DEV_ORG_ID)
        self.assertTrue((outside / "重要.txt").exists())

    def test_refuses_to_delete_the_root_itself(self):
        ROOT.mkdir(parents=True, exist_ok=True)
        with self.assertRaises(ValueError):
            creative_assets.delete_folder(main.conn, ".", org_id=DEV_ORG_ID)
        self.assertTrue(ROOT.is_dir())

    def test_missing_folder_is_not_an_error(self):
        self.assertEqual(
            creative_assets.delete_folder(main.conn, "brd_不存在", org_id=DEV_ORG_ID), "")


class DeleteCascadeTest(_Base):
    def test_deleting_a_brand_deletes_the_whole_brand_folder(self):
        brand_dir = ROOT / self.bid
        self._put_file(brand_dir / "素材", mb=1)
        other = ROOT / "brd_別的品牌"
        self._put_file(other, mb=1)

        bi_repo.update_brand(main.conn, self.bid, name=self.brand["name"],
                             client_name="測試客戶", status="archived", actor=ACTOR)
        resp = self.client.post(f"/api/library/brands/{self.bid}/delete",
                                json={"confirm_name": self.brand["name"]})

        self.assertEqual(resp.status_code, 200)
        self.assertIsNone(bi_repo.get_brand(main.conn, self.bid))
        self.assertFalse(brand_dir.exists())
        self.assertTrue(other.is_dir(), "只准刪這個品牌自己的資料夾")


if __name__ == "__main__":
    unittest.main()
