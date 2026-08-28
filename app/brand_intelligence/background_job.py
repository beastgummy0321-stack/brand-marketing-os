"""app/brand_intelligence/background_job.py — 背景工作基建（純搬家，來源：
`routes_library.py` 的 `_cv_jobs` 與 `routes_products.py` 的 `_research_jobs`，
兩邊原本各自寫了一份「job 狀態 dict＋鎖＋冪等閘＋thread 啟動」與「先通知後 commit」，
這裡抽成共用。業務內容（job 內容形狀、成功／失敗判斷、通知順序）留在呼叫端，
這裡只管機制。

對外進入點：`JobRegistry` 類別、`notify()` 函式。
誰依賴它：`routes_library.py`、`routes_products.py`（單向：routes → helper，
本檔不 import routes_*）。
"""

import threading
from collections.abc import Callable

from app.brand_intelligence import repository as bi_repo
from app.core import db as core_db
from app.core import interrupts as core_interrupts


class JobRegistry:
    """記憶體內的背景工作狀態表：job_key -> 狀態 dict。

    ponytail: 跑完的 job 不會被清掉——單機單人、生成頻率低，這點記憶體量可接受；
    長時間高頻使用真的變成問題再加 TTL 清除。
    """

    def __init__(self) -> None:
        self._jobs: dict = {}
        self._lock = threading.Lock()

    def get(self, key: str, default: dict) -> dict:
        return self._jobs.get(key, default)

    def set(self, key: str, state: dict) -> None:
        self._jobs[key] = state

    def clear(self) -> None:
        """測試用：重置狀態表（比照原本 `_research_jobs: dict = {}` 直接 `.clear()`）。"""
        self._jobs.clear()

    def items(self) -> list:
        """全站生成進度單一出口（票 B4-warroom）唯一的列舉入口：回傳 `[(key, state), ...]`
        快照。不改 get／set／start 既有形狀，這是額外新增的公開方法，供聚合端點列舉目前
        全部工作，不必讓呼叫端直接碰 `_jobs` 這個私有字典（模組邊界：只走公開進入點）。"""
        return list(self._jobs.items())

    def start(self, key: str, running_state: dict, target: Callable, args: tuple,
              *, idempotent: bool = False) -> None:
        """寫入 running 狀態並啟動背景執行緒。

        idempotent=True 時，同一個 key 已經在跑（status=="running"）就不重新啟動
        （用鎖保護，避免併發請求同時通過檢查後都各自起了一個 thread）。
        """
        with self._lock:
            if idempotent:
                entry = self._jobs.get(key)
                if entry is not None and entry.get("status") == "running":
                    return
            self._jobs[key] = running_state

        # BUG 修復（route=C 02-3c）：contextvar 不會被原生 threading.Thread 繼承，target()
        # 裡任何一次 web.conn／db 呼叫都會炸 RuntimeError: no connection bound。這裡是唯一
        # 啟動背景執行緒的進入點，所以在這裡包一層 with core_db.connection()，而不是要求
        # 每個呼叫端的 target 自己記得包（同 app/main.py 02-1 的 _auto_sync_loop 寫法）。
        def _run() -> None:
            with core_db.connection():
                target(*args)

        threading.Thread(target=_run, daemon=True).start()


def notify(conn, brand_id: str, *, category: str, dedupe_key: str, message: str, action_url: str) -> None:
    """背景工作完成／失敗時送打斷佇列通知；超過卡片字數上限就截斷
    （`core_interrupts.enqueue` 對超長訊息會直接 raise，兩邊呼叫端原本都是各自截斷）。"""
    if len(message) > core_interrupts.MAX_MESSAGE_LEN:
        message = message[: core_interrupts.MAX_MESSAGE_LEN]
    brand = bi_repo.get_brand(conn, brand_id)
    assert brand is not None, f"找不到品牌：{brand_id}"
    core_interrupts.enqueue(
        conn, org_id=brand["org_id"], category=category, dedupe_key=dedupe_key,
        brand_id=brand_id, message=message, action_url=action_url,
    )
    conn.commit()
