# -*- coding: utf-8 -*-
"""app/tests/test_creative_assets.py — 素材圖檔資料夾（票 T-G2-1，決策 0008）。

守四件事：設定頁改得動根目錄、檔期頁開得出資料夾也看得到 MB、刪品牌／刪檔期會連資料夾
一起刪，以及最重要的那道——**刪除路徑一定先確認落在根目錄底下**，設定被改成怪值時不能
遞迴刪到別的東西（code-rules 第四節，防資料遺失）。

os.startfile() 會真的彈出檔案總管視窗，測試一律 patch 掉，不讓 pytest 開一堆視窗。
品牌名一律虛構。
"""

import atexit
import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

_tmpdir = tempfile.mkdtemp(prefix="brand_os_creative_assets_")

from fastapi.testclient import TestClient  # noqa: E402

import app.main as main  # noqa: E402
from app.ads import repository as ads_repo  # noqa: E402
from app.brand_intelligence import repository as bi_repo  # noqa: E402
from app.core import creative_assets  # noqa: E402
from app.core import settings as coresettings  # noqa: E402



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
        coresettings.set_setting(main.conn, creative_assets.SETTING_KEY, str(ROOT))
        self.brand = bi_repo.create_brand(main.conn, name="虛構月見茶飲（素材資料夾）",
                                          client_name="測試客戶", actor=ACTOR)
        self.bid = self.brand["id"]
        self.pid = bi_repo.create_product(main.conn, self.bid, name="虛構冷萃包",
                                          actor=ACTOR)["id"]

    def _open_cycle(self) -> str:
        resp = self.client.post(
            f"/brands/{self.bid}/ads/new",
            data={"product_ids": [self.pid], "slider_index": "5", "objective": "sales"},
            follow_redirects=False)
        return resp.headers["location"].split("/ads/")[1].split("?")[0]

    def _cycle_label(self, cycle_id: str) -> str:
        cycle = ads_repo.get_cycle(main.conn, self.bid, cycle_id)
        return f"{cycle['start_date']} ～ {cycle['end_date']}"

    def _put_file(self, path: Path, mb: float) -> None:
        path.mkdir(parents=True, exist_ok=True)
        (path / "圖.png").write_bytes(b"x" * int(1024 * 1024 * mb))


class RootSettingTest(_Base):
    def test_blank_setting_falls_back_to_default_root(self):
        coresettings.set_setting(main.conn, creative_assets.SETTING_KEY, "")
        self.assertEqual(creative_assets.get_root(main.conn), creative_assets.DEFAULT_ROOT)

    def test_setting_page_saves_an_absolute_path(self):
        target = Path(_tmpdir) / "另一顆硬碟"
        resp = self.client.post("/settings/creative-root",
                                data={"creative_root": str(target)}, follow_redirects=False)
        self.assertEqual(resp.status_code, 303)
        self.assertEqual(creative_assets.get_root(main.conn), target)
        coresettings.set_setting(main.conn, creative_assets.SETTING_KEY, str(ROOT))

    def test_setting_page_rejects_relative_path_and_drive_root(self):
        for bad in ("", "行銷素材", "C:\\"):
            with self.subTest(bad=bad):
                resp = self.client.post("/settings/creative-root", data={"creative_root": bad})
                self.assertEqual(resp.status_code, 400)
                self.assertEqual(creative_assets.get_root(main.conn), ROOT)


class CycleFolderTest(_Base):
    def test_folder_path_is_root_slash_brand_slash_cycle(self):
        cycle_id = self._open_cycle()
        self.assertEqual(creative_assets.cycle_dir(main.conn, self.bid, cycle_id),
                         ROOT / self.bid / cycle_id)

    def test_button_creates_the_folder_and_opens_explorer(self):
        cycle_id = self._open_cycle()
        target = ROOT / self.bid / cycle_id
        self.assertFalse(target.exists())

        with mock.patch("os.startfile", create=True) as startfile:
            resp = self.client.post(f"/brands/{self.bid}/ads/{cycle_id}/creative-folder",
                                    follow_redirects=False)

        self.assertEqual(resp.status_code, 303)
        self.assertTrue(target.is_dir())
        startfile.assert_called_once_with(target)

    def test_cycle_page_shows_the_folder_size_in_mb(self):
        cycle_id = self._open_cycle()
        ads_repo.update_cycle_status(main.conn, self.bid, cycle_id,
                                     status="PRODUCTION", actor=ACTOR)
        self._put_file(ROOT / self.bid / cycle_id, mb=2)

        page = self.client.get(f"/brands/{self.bid}/ads/{cycle_id}").text
        self.assertIn("2.0 MB", page)
        self.assertIn(str(ROOT / self.bid / cycle_id), page)

    def test_size_is_computed_live_not_stored(self):
        """使用者是在檔案總管裡加減檔案，系統沒有任何寫入路徑會知道——所以每次都得重算。"""
        cycle_id = self._open_cycle()
        target = ROOT / self.bid / cycle_id
        self._put_file(target, mb=1)
        self.assertAlmostEqual(creative_assets.size_mb(target), 1.0, places=1)
        (target / "圖.png").unlink()
        self.assertEqual(creative_assets.size_mb(target), 0.0)


class MatrixFolderApiTest(_Base):
    """矩陣頁頂部素材資料夾列（票 W1）：新殼要的裸 JSON 端點，
    app/ads/routes_creative_theme.py cycle_folder()／open_cycle_folder()。
    舊頁那支 `/creative-folder`（303 轉址）由上面 CycleFolderTest 顧，兩套並存互不影響。
    """

    def test_size_endpoint_reports_mb_when_folder_has_files(self):
        cycle_id = self._open_cycle()
        self._put_file(ROOT / self.bid / cycle_id, mb=2)

        resp = self.client.get(f"/api/ads/brands/{self.bid}/ads/{cycle_id}/folder")

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json(), {"exists": True, "size_label": "2.0 MB"})

    def test_missing_folder_is_an_explicit_state_not_an_error(self):
        """還沒開過資料夾是正常狀態：不得爆 500，也不得回 0.0 MB 假裝資料夾在。"""
        cycle_id = self._open_cycle()
        self.assertFalse((ROOT / self.bid / cycle_id).exists())

        resp = self.client.get(f"/api/ads/brands/{self.bid}/ads/{cycle_id}/folder")

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json(), {"exists": False, "size_label": None})

    def test_open_endpoint_creates_the_folder_and_launches_explorer(self):
        cycle_id = self._open_cycle()
        target = ROOT / self.bid / cycle_id
        self.assertFalse(target.exists())

        with mock.patch("os.startfile", create=True) as startfile:
            resp = self.client.post(f"/api/ads/brands/{self.bid}/ads/{cycle_id}/folder")

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["folder_path"], str(target))
        self.assertTrue(target.is_dir())
        startfile.assert_called_once_with(target)

    def test_unknown_cycle_is_404_on_both_endpoints(self):
        with mock.patch("os.startfile", create=True) as startfile:
            get_resp = self.client.get(f"/api/ads/brands/{self.bid}/ads/ccy_not_real/folder")
            post_resp = self.client.post(f"/api/ads/brands/{self.bid}/ads/ccy_not_real/folder")
        self.assertEqual(get_resp.status_code, 404)
        self.assertEqual(post_resp.status_code, 404)
        startfile.assert_not_called()


class OpenFolderGuardTest(_Base):
    """開資料夾的路徑守衛。跟下面的刪除守衛共用同一份 _child()／_inside()，但守的是另一側
    ——**建**資料夾：id 帶 .. 時不能在根目錄外面 mkdir 出東西、更不能把檔案總管開到那裡。
    """

    def test_refuses_to_create_or_open_anything_outside_the_root(self):
        outside = Path(_tmpdir) / "根目錄外面"
        self.assertFalse(outside.exists())

        with mock.patch("os.startfile", create=True) as startfile:
            with self.assertRaises(ValueError):
                creative_assets.open_folder(main.conn, "..", "根目錄外面")

        self.assertFalse(outside.exists(), "被擋下的路徑不該被建出來")
        startfile.assert_not_called()

    def test_traversal_shaped_ids_never_reach_the_filesystem_through_the_route(self):
        """路由這一側。網址裡的 %2e%2e 解出來就是 ..（實測會原封不動進到路徑參數，不會被
        用戶端先正規化掉），所以這串真的會被拿去組路徑。品牌查無此 id 先擋成 404，資料夾
        那一步走不到；就算哪天有人把順序改壞，_child() 還會再擋一次。兩道都不得回 500，
        也不得在根目錄外面留下 ROOT/../外流 這種東西。"""
        escaped = Path(_tmpdir) / "外流"   # ＝ ROOT/../外流，穿越成功的話會出現在這
        self.assertFalse(escaped.exists())

        with mock.patch("os.startfile", create=True) as startfile:
            resp = self.client.post("/api/ads/brands/%2e%2e/ads/%E5%A4%96%E6%B5%81/folder")

        self.assertEqual(resp.status_code, 404)
        startfile.assert_not_called()
        self.assertFalse(escaped.exists(), "被擋下的路徑不該被建出來")


class DeleteFolderGuardTest(_Base):
    """刪除路徑守衛：這是全票最不能簡化的一段。"""

    def test_refuses_to_delete_anything_outside_the_root(self):
        outside = Path(_tmpdir) / "別的東西"
        outside.mkdir(parents=True, exist_ok=True)
        (outside / "重要.txt").write_text("不可以被刪掉", encoding="utf-8")

        with self.assertRaises(ValueError):
            creative_assets.delete_folder(main.conn, "..", "別的東西")
        self.assertTrue((outside / "重要.txt").exists())

    def test_refuses_to_delete_the_root_itself(self):
        ROOT.mkdir(parents=True, exist_ok=True)
        with self.assertRaises(ValueError):
            creative_assets.delete_folder(main.conn, ".")
        self.assertTrue(ROOT.is_dir())

    def test_missing_folder_is_not_an_error(self):
        self.assertEqual(creative_assets.delete_folder(main.conn, "brd_不存在"), "")


class DeleteCascadeTest(_Base):
    def test_deleting_a_cycle_deletes_its_folder(self):
        cycle_id = self._open_cycle()
        target = ROOT / self.bid / cycle_id
        self._put_file(target, mb=1)

        ads_repo.set_cycle_archived(main.conn, self.bid, cycle_id, archived=True, actor=ACTOR)
        resp = self.client.post(f"/brands/{self.bid}/ads/{cycle_id}/delete",
                                data={"confirm_name": self._cycle_label(cycle_id)},
                                follow_redirects=False)

        self.assertEqual(resp.status_code, 303)
        self.assertIsNone(ads_repo.get_cycle(main.conn, self.bid, cycle_id))
        self.assertFalse(target.exists())

    def test_deleting_a_brand_deletes_the_whole_brand_folder(self):
        cycle_id = self._open_cycle()
        brand_dir = ROOT / self.bid
        self._put_file(brand_dir / cycle_id, mb=1)
        other = ROOT / "brd_別的品牌"
        self._put_file(other, mb=1)

        bi_repo.update_brand(main.conn, self.bid, name=self.brand["name"],
                             client_name="測試客戶", status="archived", actor=ACTOR)
        resp = self.client.post(f"/brands/{self.bid}/delete",
                                data={"confirm_name": self.brand["name"]},
                                follow_redirects=False)

        self.assertEqual(resp.status_code, 303)
        self.assertIsNone(bi_repo.get_brand(main.conn, self.bid))
        self.assertFalse(brand_dir.exists())
        self.assertTrue(other.is_dir(), "只准刪這個品牌自己的資料夾")


if __name__ == "__main__":
    unittest.main()
