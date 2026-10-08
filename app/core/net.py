"""app/core/net.py — 讀一個網址、抽出純文字節錄。

原本住在 `app/intake/ai.py`，只有建檔精靈在用；產品調研搬去 `brand_intelligence`
之後變成兩邊共用，放在最底層的 core（core 不 import 任何其他 app 模組），
兩邊都拿得到，也不會生出模組間的回頭依賴。

呼叫端一律 `fetch_url = net.fetch_url` 綁成自己模組的名字，測試才能各自換掉
（見 app/tests/test_intake.py、test_product_scan.py）。
"""

import html.parser
import http.client
import io
import ipaddress
import socket
import ssl
import threading
import time
import urllib.error
from concurrent.futures import ThreadPoolExecutor
from typing import cast
from urllib.parse import urljoin, urlsplit

URL_FETCH_TIMEOUT_S = 10
URL_EXCERPT_CHARS = 3000
URL_FETCH_MAX_BYTES = 500_000
URL_FETCH_MAX_REDIRECTS = 5
_dns_workers = ThreadPoolExecutor(max_workers=4, thread_name_prefix="public-url-dns")
_dns_slots = threading.BoundedSemaphore(4)


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
REASON_BLOCKED = "網址必須是公開的 HTTP 或 HTTPS 網站，不可包含帳號密碼或連到內部網路"
REASON_TOO_LARGE = "網站內容超過可讀取大小，請換一個較小的頁面"
REASON_REDIRECTS = "網站轉址次數過多，請提供最後的頁面網址"
REDACTED_URL = "（網址含敏感資訊或格式無效，未顯示）"


class _PolicyError(ValueError):
    def __init__(self, reason=REASON_BLOCKED):
        self.reason = reason


def safe_url(url: str) -> str:
    """Keep legacy stored credentials out of prompts, receipts and displayed errors."""
    try:
        parsed = urlsplit(url)
        if parsed.username is not None or parsed.password is not None:
            return REDACTED_URL
        if not parsed.hostname or any(ord(c) < 32 or ord(c) == 127 for c in url):
            return REDACTED_URL
    except (ValueError, TypeError):
        return REDACTED_URL
    return url


def _remaining(deadline: float) -> float:
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise TimeoutError()
    return remaining


def _destination(url: str):
    if (not isinstance(url, str) or len(url) > 8192
            or any(ord(c) <= 32 or ord(c) == 127 for c in url)):
        raise _PolicyError()
    try:
        parts = urlsplit(url)
        if parts.scheme not in ("http", "https") or parts.username is not None \
                or parts.password is not None or not parts.hostname or "%" in parts.hostname:
            raise _PolicyError()
        host = parts.hostname.encode("idna").decode("ascii")
        port = parts.port if parts.port is not None else (443 if parts.scheme == "https" else 80)
        if not 1 <= port <= 65535:
            raise _PolicyError()
        try:
            ipaddress.ip_address(host)
        except ValueError:
            pass
        else:
            if not _public_address(host):
                raise _PolicyError()
    except (ValueError, UnicodeError) as exc:
        raise _PolicyError() from exc
    return parts, host, port


def _public_address(address: str | int) -> bool:
    if not isinstance(address, str):
        return False
    try:
        ip = ipaddress.ip_address(address)
        if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
            ip = ip.ipv4_mapped
        return ip.is_global and not (ip.is_multicast or ip.is_reserved or ip.is_loopback
                                    or ip.is_link_local or ip.is_unspecified)
    except ValueError:
        return False


def _resolve(host: str, port: int, deadline: float):
    # getaddrinfo has no portable timeout. Bound both the caller's wait and the
    # number of still-running DNS calls; a timed-out lookup cannot grow a queue.
    if not _dns_slots.acquire(blocking=False):
        raise TimeoutError()
    try:
        future = _dns_workers.submit(socket.getaddrinfo, host, port, 0,
                                     socket.SOCK_STREAM, socket.IPPROTO_TCP)
    except BaseException:
        _dns_slots.release()
        raise
    future.add_done_callback(lambda _done: _dns_slots.release())
    addresses = future.result(timeout=_remaining(deadline))
    _remaining(deadline)
    if not addresses or any(not _public_address(item[4][0]) for item in addresses):
        raise _PolicyError()
    return addresses


class _DeadlineReader(io.RawIOBase):
    def __init__(self, sock, deadline):
        super().__init__()
        self.sock, self.deadline = sock, deadline
        # SocketIO owns a standard makefile reference: HTTPConnection may close
        # its socket after headers while HTTPResponse still needs the body.
        self.raw = sock.makefile("rb", buffering=0)

    def readable(self):
        return True

    def readinto(self, buffer):
        self.sock.settimeout(_remaining(self.deadline))
        return self.raw.readinto(buffer)

    def close(self):
        try:
            self.raw.close()
        finally:
            super().close()


class _ResponseSocket:
    def __init__(self, sock, deadline):
        self.sock, self.deadline = sock, deadline

    def makefile(self, mode):
        # HTTP status/header parsing also uses this reader, so a slow header or
        # trickle of body bytes cannot reset the overall deadline per recv.
        return io.BufferedReader(_DeadlineReader(self.sock, self.deadline))


class _PinnedConnection(http.client.HTTPConnection):
    def __init__(self, host, port, secure, address, deadline):
        self.default_port = 443 if secure else 80
        super().__init__(host, port, timeout=_remaining(deadline))
        self.address, self.deadline, self.secure = address, deadline, secure

        class DeadlineResponse(http.client.HTTPResponse):
            def __init__(self, sock, **kwargs):
                # HTTPResponse only consumes makefile from its socket argument.
                super().__init__(cast(socket.socket, _ResponseSocket(sock, deadline)), **kwargs)

        self.response_class = DeadlineResponse

    def connect(self):
        family, _type, _protocol, _name, sockaddr = self.address
        # Connect the numeric sockaddr directly. No create_connection/getaddrinfo
        # runs here, so a second DNS answer cannot replace the validated address.
        sock = socket.socket(family, socket.SOCK_STREAM, socket.IPPROTO_TCP)
        try:
            sock.settimeout(_remaining(self.deadline))
            sock.connect(sockaddr)
            if self.secure:
                context = ssl.create_default_context()
                sock.settimeout(_remaining(self.deadline))
                sock = context.wrap_socket(sock, server_hostname=self.host)
            sock.settimeout(_remaining(self.deadline))
            self.sock = sock
        except BaseException:
            sock.close()
            raise


def _read_public(url: str) -> bytes:
    deadline = time.monotonic() + URL_FETCH_TIMEOUT_S
    for hop in range(URL_FETCH_MAX_REDIRECTS + 1):
        parts, host, port = _destination(url)
        addresses = _resolve(host, port, deadline)
        connection = _PinnedConnection(host, port, parts.scheme == "https", addresses[0], deadline)
        response = None
        try:
            target = parts.path or "/"
            if parts.query:
                target += "?" + parts.query
            # Direct HTTPConnection ignores environment proxy settings entirely.
            connection.request("GET", target,
                               headers={"User-Agent": "Mozilla/5.0 (BrandOS intake)"})
            _remaining(deadline)
            response = connection.getresponse()
            if response.status in (301, 302, 303, 307, 308):
                location = response.getheader("Location")
                if not location or hop == URL_FETCH_MAX_REDIRECTS:
                    raise _PolicyError(REASON_REDIRECTS)
                url = urljoin(url, location)
                continue
            if response.status >= 300:
                raise urllib.error.HTTPError("", response.status, "", response.headers, None)
            declared = response.getheader("Content-Length")
            if declared is not None and int(declared) > URL_FETCH_MAX_BYTES:
                raise _PolicyError(REASON_TOO_LARGE)
            content = bytearray()
            while True:
                _remaining(deadline)
                chunk = response.read1(min(65536, URL_FETCH_MAX_BYTES + 1 - len(content)))
                _remaining(deadline)
                if not chunk:
                    return bytes(content)
                content.extend(chunk)
                if len(content) > URL_FETCH_MAX_BYTES:
                    raise _PolicyError(REASON_TOO_LARGE)
        finally:
            if response is not None:
                response.close()
            connection.close()
    raise _PolicyError(REASON_REDIRECTS)


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
    if isinstance(exc, _PolicyError):
        return exc.reason
    if isinstance(exc, urllib.error.HTTPError):
        return _http_reason(exc.code)
    if isinstance(exc, TimeoutError):
        return REASON_TIMEOUT
    if isinstance(exc, ssl.SSLError):
        return REASON_SSL
    if isinstance(exc, socket.gaierror):
        return REASON_NOT_FOUND
    if isinstance(exc, urllib.error.URLError):
        inner = exc.reason
        if isinstance(inner, TimeoutError):
            return REASON_TIMEOUT
        if isinstance(inner, ssl.SSLError):
            return REASON_SSL
        if isinstance(inner, socket.gaierror):
            return REASON_NOT_FOUND
        return REASON_UNREACHABLE
    if isinstance(exc, OSError):
        return REASON_UNREACHABLE
    if isinstance(exc, ValueError):  # urllib refuses a malformed URL
        return REASON_UNKNOWN
    return REASON_UNKNOWN


def read_url(url: str) -> tuple:
    """讀一個網址，回 (ok, 純文字節錄, 讀不到的原因)。ok 時原因是 None；讀不到時文字是 ""、
    原因是一句短中文（狀態碼、逾時、網域不存在、憑證；F47 Contract F），不存例外原文。
    打得開但沒有任何文字，也算讀不到（`REASON_EMPTY`）。"""
    try:
        raw = _read_public(url).decode("utf-8", errors="replace")
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
