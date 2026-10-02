"""app/core/net.py — 讀一個網址、抽出純文字節錄。

原本住在 `app/intake/ai.py`，只有建檔精靈在用；產品調研搬去 `brand_intelligence`
之後變成兩邊共用，放在最底層的 core（core 不 import 任何其他 app 模組），
兩邊都拿得到，也不會生出模組間的回頭依賴。

呼叫端一律 `fetch_url = net.fetch_url` 綁成自己模組的名字，測試才能各自換掉
（見 app/tests/test_intake.py、test_product_scan.py）。
"""

import html.parser
import socket
import ssl
import urllib.error
import urllib.request

URL_FETCH_TIMEOUT_S = 10
URL_EXCERPT_CHARS = 3000


class _TextExtractor(html.parser.HTMLParser):
    def __init__(self):
        super().__init__()
        self.chunks = []
        self._skip = 0

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style"):
            self._skip += 1

    def handle_endtag(self, tag):
        if tag in ("script", "style") and self._skip:
            self._skip -= 1

    def handle_data(self, data):
        if not self._skip and data.strip():
            self.chunks.append(data.strip())


REASON_EMPTY = "打得開，但這一頁沒有可以讀的文字"
REASON_TIMEOUT = f"網站 {URL_FETCH_TIMEOUT_S} 秒內沒有回應"
REASON_NOT_FOUND = "找不到這個網址的網站（網域打錯或不存在）"
REASON_SSL = "網站的安全憑證有問題，連不上"
REASON_UNREACHABLE = "連不上這個網站"
REASON_UNKNOWN = "打不開這個網址"


def _http_reason(code: int) -> str:
    if code == 404:
        return "網站說這一頁不存在（404）"
    if code in (401, 403):
        return f"網站不讓系統讀這一頁（{code}）"
    if code >= 500:
        return f"網站自己出錯了（{code}）"
    return f"網站回了錯誤（{code}）"


def _failure_reason(exc: BaseException) -> str:
    """A short Chinese reason for a failed read, from the exception's kind (F47 Contract F).
    Never the exception text itself (it can carry the URL or provider wording)."""
    if isinstance(exc, urllib.error.HTTPError):
        return _http_reason(exc.code)
    if isinstance(exc, TimeoutError):
        return REASON_TIMEOUT
    if isinstance(exc, ssl.SSLError):
        return REASON_SSL
    if isinstance(exc, urllib.error.URLError):
        inner = exc.reason
        if isinstance(inner, TimeoutError):
            return REASON_TIMEOUT
        if isinstance(inner, ssl.SSLError):
            return REASON_SSL
        if isinstance(inner, socket.gaierror):
            return REASON_NOT_FOUND
        return REASON_UNREACHABLE
    if isinstance(exc, ValueError):  # urllib refuses a malformed URL
        return REASON_UNKNOWN
    return REASON_UNKNOWN


def read_url(url: str) -> tuple:
    """讀一個網址，回 (ok, 純文字節錄, 讀不到的原因)。ok 時原因是 None；讀不到時文字是 ""、
    原因是一句短中文（狀態碼、逾時、網域不存在、憑證；F47 Contract F），不存例外原文。
    打得開但沒有任何文字，也算讀不到（`REASON_EMPTY`）。"""
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (BrandOS intake)"})
        with urllib.request.urlopen(req, timeout=URL_FETCH_TIMEOUT_S) as resp:
            raw = resp.read(500_000).decode("utf-8", errors="replace")
    except Exception as exc:  # noqa: BLE001 — every failure becomes a reason, never a crash
        return False, "", _failure_reason(exc)
    extractor = _TextExtractor()
    try:
        extractor.feed(raw)
        text = " ".join(extractor.chunks)
    except Exception:
        text = raw
    text = text[:URL_EXCERPT_CHARS]
    if not text.strip():
        return False, "", REASON_EMPTY
    return True, text, None


def fetch_url(url: str) -> tuple:
    """讀一個網址，回 (ok, 純文字節錄)——`read_url` 的前兩個值（不需要原因的呼叫端用）。"""
    ok, text, _reason = read_url(url)
    return ok, text
