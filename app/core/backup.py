# -*- coding: utf-8 -*-
"""app/core/backup.py — 每日備份。

app 啟動流程掛這個檢查（migrations 之後）：今天的備份檔（backups/YYYY-MM-DD.db）
不存在就複製一份現在的 DB 過去；備份只留最近 30 份，多的刪掉。DB 檔案本身不存在
（例如全新環境）就什麼都不做。
"""

import os
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from app.core.db import get_db_path

DEFAULT_BACKUP_DIR = Path("C:/Users/User/Desktop/marketing/backups")
KEEP = 30


def get_backup_dir() -> Path:
    raw = os.environ.get("BRAND_OS_BACKUP_DIR")
    return Path(raw) if raw else DEFAULT_BACKUP_DIR


def run_daily_backup(db_path: Optional[Path] = None, backup_dir: Optional[Path] = None) -> None:
    db_path = Path(db_path) if db_path else get_db_path()
    if not db_path.exists():
        return
    backup_dir = Path(backup_dir) if backup_dir else get_backup_dir()
    backup_dir.mkdir(parents=True, exist_ok=True)
    today = datetime.now(timezone.utc).date().isoformat()
    target = backup_dir / f"{today}.db"
    if not target.exists():
        shutil.copy2(db_path, target)
    _prune(backup_dir)


def snapshot(label: str, db_path: Optional[Path] = None,
             backup_dir: Optional[Path] = None) -> Optional[Path]:
    """不可逆動作前的即時備份：複製一份 DB 成 backups/<label>-<UTC 時間戳>.db。

    跟每日備份分開命名，_prune 只掃 YYYY-MM-DD.db，所以這種快照不會被 30 份上限清掉。
    DB 檔不存在就回 None（全新環境沒東西可備份）。
    """
    db_path = Path(db_path) if db_path else get_db_path()
    if not db_path.exists():
        return None
    backup_dir = Path(backup_dir) if backup_dir else get_backup_dir()
    backup_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
    target = backup_dir / f"{label}-{stamp}.db"
    shutil.copy2(db_path, target)
    return target


def _prune(backup_dir: Path, keep: int = KEEP) -> None:
    backups = sorted(backup_dir.glob("????-??-??.db"))
    for old in backups[: max(0, len(backups) - keep)]:
        old.unlink()
