"""app/core/net.py `read_url` (F47 Contract F): a failed read keeps a short Chinese reason taken
from the failure's kind, never the exception text; `fetch_url` stays the two-value reader.
`urllib.request.urlopen` is mocked: no network."""

import io
import socket
import ssl
import unittest
import urllib.error
from unittest import mock

from app.core import net

URL = "https://shop.example/p/1"


class _Resp(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _raising(exc):
    return mock.patch.object(net.urllib.request, "urlopen", side_effect=exc)


class ReadUrlTest(unittest.TestCase):
    def test_a_page_with_text_reads(self):
        html = b"<html><script>x()</script><p>\xe8\xbb\x9f\xe7\xb3\x96 NT$399</p></html>"
        with mock.patch.object(net.urllib.request, "urlopen",
                               side_effect=lambda *a, **k: _Resp(html)):
            self.assertEqual(net.read_url(URL), (True, "軟糖 NT$399", None))
            self.assertEqual(net.fetch_url(URL), (True, "軟糖 NT$399"))

    def test_an_empty_page_is_not_read(self):
        with mock.patch.object(net.urllib.request, "urlopen",
                               side_effect=lambda *a, **k: _Resp(b"<html> </html>")):
            self.assertEqual(net.read_url(URL), (False, "", net.REASON_EMPTY))
            self.assertEqual(net.fetch_url(URL), (False, ""))

    def test_failure_reasons(self):
        def http(code):
            return urllib.error.HTTPError(URL, code, "x", {}, None)  # type: ignore[arg-type]

        cases = [
            (http(404), "網站說這一頁不存在（404）"),
            (http(403), "網站不讓系統讀這一頁（403）"),
            (http(503), "網站自己出錯了（503）"),
            (http(418), "網站回了錯誤（418）"),
            (urllib.error.URLError(socket.gaierror(11001, "getaddrinfo failed")),
             net.REASON_NOT_FOUND),
            (urllib.error.URLError(TimeoutError("timed out")), net.REASON_TIMEOUT),
            (TimeoutError("timed out"), net.REASON_TIMEOUT),
            (urllib.error.URLError(ssl.SSLCertVerificationError("bad cert")), net.REASON_SSL),
            (ssl.SSLError("handshake"), net.REASON_SSL),
            (urllib.error.URLError(ConnectionRefusedError("refused")), net.REASON_UNREACHABLE),
            (ValueError("unknown url type"), net.REASON_UNKNOWN),
        ]
        for exc, reason in cases:
            with self.subTest(exc=type(exc).__name__, reason=reason), _raising(exc):
                self.assertEqual(net.read_url(URL), (False, "", reason))
                self.assertEqual(net.fetch_url(URL), (False, ""))

    def test_the_reason_never_carries_the_exception_text(self):
        with _raising(urllib.error.URLError(OSError("token=SECRET at https://x"))):
            ok, _text, reason = net.read_url(URL)
        self.assertFalse(ok)
        self.assertNotIn("SECRET", reason)
