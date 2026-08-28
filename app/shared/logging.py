"""app/shared/logging.py — 結構化 logging（票 03-1 附錄 A）。

JSON formatter ＋ 一個以 contextvar 記 request_id／user_id／org_id 的 `logging.Filter`。
`request_id` 由 main.py 的 middleware 每個 request 開頭產生一次（uuid4），同時回傳
`X-Request-Id` 回應 header，讓使用者回報問題時能對到後端這行 log；`user_id`／`org_id`
在 `require_actor()` 拿到 `ActorContext` 後補上（沒登入的路由這兩欄就是 None）。

contextvar 天然以 asyncio Task 為界——每個 HTTP request 是獨立的 Task，設定值不會漏到
別的並行 request，不需要手動在 request 結束時重置（比照 app/core/db.py 的 `_current`
用途類似，但那邊額外需要 token-based reset 是因為要處理背景執行緒／multiple `with`
巢狀的情境；這裡沒有那些情境，故不加）。

刻意不記 email／token 等敏感內容——稽核用 user_id 已經對得上人，帳密等級的東西不進 log。
"""

import json
import logging
from contextvars import ContextVar
from typing import Any

_request_id: ContextVar[str | None] = ContextVar("log_request_id", default=None)
_user_id: ContextVar[str | None] = ContextVar("log_user_id", default=None)
_org_id: ContextVar[str | None] = ContextVar("log_org_id", default=None)


def set_request_id(request_id: str) -> None:
    _request_id.set(request_id)


def bind_actor(*, user_id: str, org_id: str) -> None:
    _user_id.set(user_id)
    _org_id.set(org_id)


class ContextFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = _request_id.get()
        record.user_id = _user_id.get()
        record.org_id = _org_id.get()
        return True


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "request_id": getattr(record, "request_id", None),
            "user_id": getattr(record, "user_id", None),
            "org_id": getattr(record, "org_id", None),
        }
        if record.exc_info:
            payload["exc_info"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False)


def install() -> None:
    """main.py 啟動時呼叫一次：根 logger 掛 JSON formatter + ContextFilter。"""
    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())
    handler.addFilter(ContextFilter())
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(logging.INFO)
