"""app/core/creative_assets.py — 素材圖檔資料夾（決策 0008：圖不進系統，系統只記得住在哪）。

圖檔不上傳進系統，使用者自己把生圖工具下載的檔案倒進系統指定的資料夾。本檔只做四件事
——算路徑、叫出檔案總管、即時算佔用空間、刪資料夾——DB 一個位元組都不存。

# 外殼切片（2026-08-28）：`cycle_dir()`／`theme_dir()` 隨 `app/ads/` 一起刪掉——檔期與
# 主題都是廣告模組的概念，沒有呼叫端了。`open_folder()`／`delete_folder()` 仍收 *ids
# （<根目錄>/<品牌 id>/…），要開第二層再多傳一段路徑即可，不必另外寫一個函式。
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path

from app.core import settings
from app.core.db import REPO_ROOT

SETTING_KEY = "creative_asset_root"

# 預設根目錄以模組位置推導專案根，而不是工作目錄或舊電腦的絕對路徑。
DEFAULT_ROOT = REPO_ROOT / "data" / "creative"


def get_root(conn=None, *, org_id: str) -> Path:
    """素材資料夾根目錄：設定頁存的值 > 預設 data/creative。

    org_id 必填、不給預設值（票 04-0）：本檔（app.core）依 LAYER_ORDER 不得 import
    app.brand_intelligence 自己拿 brand_id 反查 org_id，呼叫端（app.brand_web 等分支層）
    已經有 brand_id，反查後傳進來。
    """
    raw = (settings.get_setting(conn, SETTING_KEY, org_id=org_id) or "").strip()
    return Path(raw) if raw else DEFAULT_ROOT


def open_folder(conn, *ids: str, org_id: str) -> Path:
    """沒有就建，然後叫出檔案總管。os.startfile() 只有 Windows 有，這台就是 Windows
    （決策 0008 指定用它；不為了跨平台包一層抽象）。

    *ids：品牌層傳 (brand_id,)，要更深一層就多傳一段——_child() 本來就吃任意層數。
    """
    path = _child(get_root(conn, org_id=org_id), *ids)
    path.mkdir(parents=True, exist_ok=True)
    os.startfile(path)
    return path


def size_mb(path: Path) -> float:
    """這個資料夾現在佔幾 MB。每次都重新走訪，不寫進 DB——使用者是在檔案總管裡加減檔案，
    存下來的數字馬上就是錯的。

    ponytail: 一次 rglob 走訪整棵樹，檔案上萬筆時每次開檔期頁都要等；真的卡住再加快取。
    """
    path = Path(path)
    if not path.is_dir():
        return 0.0
    return sum(f.stat().st_size for f in path.rglob("*") if f.is_file()) / (1024 * 1024)


def delete_folder(conn, *ids: str, org_id: str) -> str:
    """刪掉一個素材資料夾（品牌層傳 brand_id；更深的層級多傳一段）。

    刪之前一定先確認算出來的路徑真的落在根目錄底下、而且不是根目錄本身。根目錄是使用者
    在設定頁自己填的字串，指到 OneDrive 或磁碟機根目錄都有可能，這道檢查是唯一擋住遞迴
    刪錯的東西（code-rules 第四節「防資料遺失」，不得簡化；_child() 組路徑時已擋過一次，
    這裡刪之前再擋一次是刻意的重複，日後有人改壞 _child() 也還有這一道）。

    刪不掉（例如檔案總管正開著那個資料夾）時不拋錯：呼叫端走到這一步時 DB 已經刪完並
    commit 了，這時炸出 500 會讓使用者以為整件事失敗、回頭再刪一次。回一句人話讓呼叫端
    接在成功訊息後面，沒事就回空字串。
    """
    root = get_root(conn, org_id=org_id)
    path = _child(root, *ids)
    if not _inside(path, root):
        raise ValueError(f"拒絕刪除 {path}：不在素材資料夾根目錄 {root} 底下。")
    if not path.is_dir():
        return ""
    try:
        shutil.rmtree(path)
    except OSError as exc:
        return f"（圖檔資料夾 {path} 沒有刪掉：{exc.strerror or exc}，請自己到檔案總管刪。）"
    return ""


def _child(root: Path, *names: str) -> Path:
    """把 id 接到根目錄底下。id 是從網址來的，帶 .. 或路徑分隔字元時當場擋下，不讓它跳出
    根目錄（信任邊界的輸入驗證）。"""
    path = Path(root).joinpath(*names)
    if not _inside(path, root):
        raise ValueError(f"素材資料夾路徑 {path} 跳出了根目錄 {root}。")
    return path


def _inside(path: Path, root: Path) -> bool:
    """path 是不是真的在 root 底下（且不是 root 本身）。resolve() 是重點：把 .. 與符號
    連結攤平之後再比，才擋得住 brand_id 帶 ../.. 這種輸入。"""
    return Path(root).resolve() in Path(path).resolve().parents


def demo() -> None:
    """最小自測：路徑守衛會擋、算得出大小。python -m app.core.creative_assets 直接跑。"""
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp) / "creative"
        outside = Path(tmp) / "別的東西"
        outside.mkdir(parents=True)
        (outside / "重要.txt").write_bytes(b"x" * 10)

        assert _inside(root / "brd_1" / "cyc_1", root)
        assert not _inside(root, root)
        assert not _inside(outside, root)
        try:
            _child(root, "..", "別的東西")
        except ValueError:
            pass
        else:
            raise AssertionError("跳出根目錄的路徑沒有被擋下")
        assert outside.is_dir(), "被擋下的路徑不該被刪掉"

        target = root / "brd_1" / "cyc_1"
        target.mkdir(parents=True)
        (target / "圖.png").write_bytes(b"x" * (1024 * 1024))
        assert 0.9 < size_mb(target) < 1.1, size_mb(target)
        assert size_mb(root / "沒這個資料夾") == 0.0
    print("creative_assets demo OK")


if __name__ == "__main__":
    demo()
