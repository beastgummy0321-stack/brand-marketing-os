# -*- coding: utf-8 -*-
"""app/tools/boot_launcher.py — 票 F6：Windows 開機自動啟動用的無視窗啟動器。

Windows 工作排程器（schtasks，trigger onlogon，見 docs/boot-autostart.md）叫的是這支，
不是「啟動行銷系統.bat」——那支登入當下會開一個 cmd 視窗搶焦點、還會開瀏覽器分頁，
兩者都不是登入那一刻該發生的事。這支只做兩件事：

1. port 8710 已經有人在聽（例如使用者自己手動點了 .bat）就直接結束，不重複啟動——
   比照既有 .bat 的「netstat 找 LISTENING」邏輯，改用標準庫 `socket` 直接探測那個 port，
   不必解析 netstat 的文字輸出（依系統語系而異，一直是隱性地雷）。
2. 沒人在聽就地把 uvicorn 跑起來（in-process；不必再開一層 subprocess）。

.env 金鑰不必在這裡讀——app.main 自己會讀（`_load_dotenv`，2026-08-23 那次「換個啟動
方式就悄悄少了金鑰」之後改的：設定該由程式自己讀，不該綁在某一種啟動方式上，見
app/main.py 內該函式的說明）。

**為什麼用 pythonw.exe 而不是 python.exe 或另包一支 .vbs**：python.exe 是主控台子系統
執行檔，Windows 一定會替它分配一個主控台視窗；pythonw.exe 是 GUI 子系統執行檔，Windows
從一開始就不會分配主控台——不必再包一層 .vbs／WScript.Shell.Run 去隱藏視窗，少一個要
維護的殼。代價是 pythonw 底下沒有真正的 stdout/stderr 可以印，直接讓 uvicorn 往那裡寫
字會讓啟動器整支炸掉（`AttributeError`），所以下面先把兩者接到一個 log 檔再匯入 uvicorn。
"""

import socket
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_PORT = 8710
_LOG_PATH = _REPO_ROOT / "logs" / "boot_launcher.log"


def _port_is_listening(port: int, host: str = "127.0.0.1") -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.5)
        return sock.connect_ex((host, port)) == 0


def main() -> None:
    if _port_is_listening(_PORT):
        return  # 已經有人在跑了（例如使用者自己手動開的），不重複啟動

    _LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    log_file = open(_LOG_PATH, "a", encoding="utf-8", buffering=1)  # noqa: SIM115 — 常駐到 process 結束才關，不適合用 with
    sys.stdout = log_file
    sys.stderr = log_file
    print(f"---- boot_launcher 啟動 {__file__} ----", file=log_file)

    if str(_REPO_ROOT) not in sys.path:
        sys.path.insert(0, str(_REPO_ROOT))  # 讓 "app.main:app" 這個字串能被匯入到，不依賴目前工作目錄

    import uvicorn  # 延遲匯入：先接好 log、把路徑插好，任何匯入期的例外才有地方可以印

    uvicorn.run("app.main:app", host="127.0.0.1", port=_PORT, log_config=None)


if __name__ == "__main__":
    main()
