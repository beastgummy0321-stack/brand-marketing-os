"""app/core/creative_assets.py — 素材圖檔資料夾（決策 0008：圖不進系統，系統只記得住在哪）。

圖檔不上傳進系統，使用者自己把生圖工具下載的檔案倒進系統指定的資料夾。本檔只做四件事
——算路徑、叫出檔案總管、即時算佔用空間、刪資料夾——DB 一個位元組都不存。

# 2026-08-09 票 04-single-image-e2e 接續：主題有自己的 id 與資料夾短碼了，`theme_dir()`
# 把 ponytail 原本規劃的第三層接上（<根目錄>/<品牌 id>/<檔期 id>/<主題名_短碼>/）；
# `open_folder()` 改收 *ids，讓開檔期資料夾／開主題資料夾共用同一個函式，呼叫端多傳一段
# 路徑即可，不必另外寫一個 open_theme_folder()。已倒好的圖不會自動搬。
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


def get_root(conn=None) -> Path:
    """素材資料夾根目錄：設定頁存的值 > 預設 data/creative。"""
    raw = (settings.get_setting(conn, SETTING_KEY) or "").strip()
    return Path(raw) if raw else DEFAULT_ROOT


def cycle_dir(conn, brand_id: str, cycle_id: str) -> Path:
    """這一期檔期的素材資料夾路徑（不保證存在，開資料夾那一步才會建）。"""
    return _child(get_root(conn), brand_id, cycle_id)


def theme_dir(conn, brand_id: str, cycle_id: str, theme_folder_name: str) -> Path:
    """單一主題的素材資料夾路徑（不保證存在）。命名＝人話名＋四碼短碼，由呼叫端組好傳進來
    （票 04-single-image-e2e；決策 0008「人看得懂的名字在前，四碼短碼在後」）。"""
    return _child(get_root(conn), brand_id, cycle_id, theme_folder_name)


def open_folder(conn, *ids: str) -> Path:
    """沒有就建，然後叫出檔案總管。os.startfile() 只有 Windows 有，這台就是 Windows
    （決策 0008 指定用它；不為了跨平台包一層抽象）。

    *ids：開檔期資料夾傳 (brand_id, cycle_id)，開主題資料夾多傳一段
    (brand_id, cycle_id, theme_folder_name)——同一個函式，_child() 本來就吃任意層數。
    """
    path = _child(get_root(conn), *ids)
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


def delete_folder(conn, *ids: str) -> str:
    """刪掉一個素材資料夾（品牌層傳 brand_id；檔期層傳 brand_id, cycle_id）。

    刪之前一定先確認算出來的路徑真的落在根目錄底下、而且不是根目錄本身。根目錄是使用者
    在設定頁自己填的字串，指到 OneDrive 或磁碟機根目錄都有可能，這道檢查是唯一擋住遞迴
    刪錯的東西（code-rules 第四節「防資料遺失」，不得簡化；_child() 組路徑時已擋過一次，
    這裡刪之前再擋一次是刻意的重複，日後有人改壞 _child() 也還有這一道）。

    刪不掉（例如檔案總管正開著那個資料夾）時不拋錯：呼叫端走到這一步時 DB 已經刪完並
    commit 了，這時炸出 500 會讓使用者以為整件事失敗、回頭再刪一次。回一句人話讓呼叫端
    接在成功訊息後面，沒事就回空字串。
    """
    root = get_root(conn)
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
