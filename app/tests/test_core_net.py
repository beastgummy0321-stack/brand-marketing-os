"""Public-page fetching: policy, pinned transport, TLS and overall resource bounds."""

import io
import socket
import ssl
import threading
import time
import urllib.error
from unittest import mock

import pytest

from app.core import net

URL = "https://shop.example/p/1"
PUBLIC = "93.184.216.34"


def addresses(ip=PUBLIC, port=443):
    family = socket.AF_INET6 if ":" in ip else socket.AF_INET
    sockaddr = (ip, port, 0, 0) if family == socket.AF_INET6 else (ip, port)
    return [(family, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", sockaddr)]


class Response(io.BytesIO):
    def __init__(self, content=b"<p>Public page</p>", status=200, headers=None):
        super().__init__(content)
        self.status, self.headers = status, headers or {}

    def getheader(self, name):
        return self.headers.get(name)


class Connection:
    def __init__(self, response):
        self.response = response

    def request(self, *args, **kwargs):
        pass

    def getresponse(self):
        return self.response

    def close(self):
        pass


class Socket:
    def __init__(self, content=b"HTTP/1.1 200 OK\r\nContent-Length: 11\r\n\r\n<p>Safe</p>"):
        self.content = io.BytesIO(content)
        self.connected, self.closed = None, False
        self.timeouts, self.sent = [], []

    def settimeout(self, value):
        self.timeouts.append(value)

    def connect(self, address):
        self.connected = address

    def sendall(self, value):
        self.sent.append(value)

    def recv_into(self, buffer):
        return self.content.readinto(buffer)

    def makefile(self, mode, buffering=0):
        sock = self

        class Reader(io.RawIOBase):
            def readable(self):
                return True

            def readinto(self, buffer):
                return sock.recv_into(buffer)

        return Reader()

    def close(self):
        self.closed = True


@pytest.fixture
def public_dns(monkeypatch):
    dns = mock.Mock(return_value=addresses())
    monkeypatch.setattr(net.socket, "getaddrinfo", dns)
    return dns


def test_text_and_empty_pages_preserve_reader_contract(public_dns):
    with mock.patch.object(net, "_PinnedConnection", side_effect=lambda *args: Connection(
            Response("<script>x()</script><p>軟糖 NT$399</p>".encode()))):
        assert net.read_url(URL) == (True, "軟糖 NT$399", None)
        assert net.fetch_url(URL) == (True, "軟糖 NT$399")
    with mock.patch.object(net, "_PinnedConnection", return_value=Connection(Response(b" "))):
        assert net.read_url(URL) == (False, "", net.REASON_EMPTY)


@pytest.mark.parametrize("exc,reason", [
    (urllib.error.HTTPError(URL, 404, "SECRET", {}, None), "網站說這一頁不存在（404）"),
    (urllib.error.HTTPError(URL, 403, "SECRET", {}, None), "網站不讓系統讀這一頁（403）"),
    (urllib.error.HTTPError(URL, 503, "SECRET", {}, None), "網站自己出錯了（503）"),
    (urllib.error.HTTPError(URL, 418, "SECRET", {}, None), "網站回了錯誤（418）"),
    (socket.gaierror("SECRET"), net.REASON_NOT_FOUND),
    (TimeoutError("SECRET"), net.REASON_TIMEOUT),
    (ssl.SSLCertVerificationError("SECRET"), net.REASON_SSL),
    (urllib.error.URLError(TimeoutError("SECRET")), net.REASON_TIMEOUT),
    (urllib.error.URLError(ssl.SSLError("SECRET")), net.REASON_SSL),
    (urllib.error.URLError(socket.gaierror("SECRET")), net.REASON_NOT_FOUND),
    (ConnectionRefusedError("SECRET"), net.REASON_UNREACHABLE),
    (ValueError("SECRET"), net.REASON_UNKNOWN),
])
def test_failure_reasons_are_safe(public_dns, exc, reason):
    with mock.patch.object(net, "_PinnedConnection", side_effect=exc):
        assert net.read_url(URL) == (False, "", reason)
        assert net.fetch_url(URL) == (False, "")
        assert "SECRET" not in reason


@pytest.mark.parametrize("url", [
    "http://127.0.0.1/", "http://10.0.0.1/", "http://172.16.0.1/", "http://192.168.1.1/",
    "http://169.254.169.254/", "http://0.0.0.0/", "http://224.0.0.1/", "http://192.0.2.1/",
    "http://100.64.0.1/", "http://[::1]/", "http://[fc00::1]/", "http://[fe80::1]/",
    "http://[::ffff:127.0.0.1]/", "http://[::ffff:10.0.0.1]/", "http://[ff02::1]/",
    "http://[::]/", "http://[fe80::1%25eth0]/", "file:///secret", "ftp://shop.example/a",
    "https://user:SECRET@shop.example/", "https://@shop.example/", "https://shop.example:0/",
    "http://shop.example/\nsecret", "http://[broken",
])
def test_forbidden_destinations_never_resolve_or_connect(url):
    with mock.patch.object(net.socket, "getaddrinfo") as dns, \
            mock.patch.object(net, "_PinnedConnection") as transport:
        assert net.read_url(url) == (False, "", net.REASON_BLOCKED)
        dns.assert_not_called()
        transport.assert_not_called()


@pytest.mark.parametrize("host", ["private.example", "localhost", "127.1", "2130706433",
                                  "0x7f000001", "0177.0.0.1"])
@pytest.mark.parametrize("ips", [["127.0.0.1"], [PUBLIC, "10.0.0.1"]])
def test_every_dns_answer_is_checked_including_alternate_and_mixed_addresses(host, ips):
    resolved = [item for ip in ips for item in addresses(ip)]
    with mock.patch.object(net.socket, "getaddrinfo", return_value=resolved), \
            mock.patch.object(net, "_PinnedConnection") as transport:
        assert net.read_url(f"https://{host}/") == (False, "", net.REASON_BLOCKED)
        transport.assert_not_called()


def test_dns_rebinding_cannot_replace_pinned_ip_and_https_keeps_hostname_verification():
    sock = Socket()
    context = ssl.create_default_context()
    answers = [addresses(), addresses("127.0.0.1")]
    with mock.patch.object(net.socket, "getaddrinfo", side_effect=answers) as dns, \
            mock.patch.object(net.socket, "socket", return_value=sock), \
            mock.patch.object(net.ssl, "create_default_context", return_value=context), \
            mock.patch.object(context, "wrap_socket", return_value=sock) as tls, \
            mock.patch.dict("os.environ", {"HTTPS_PROXY": "http://127.0.0.1:9999"}):
        assert net.read_url(URL) == (True, "Safe", None)
        dns.assert_called_once()
        assert sock.connected == (PUBLIC, 443)
        tls.assert_called_once_with(sock, server_hostname="shop.example")
        assert context.check_hostname is True
        assert context.verify_mode == ssl.CERT_REQUIRED
        assert b"Host: shop.example\r\n" in b"".join(sock.sent)
        assert sock.closed is True


def test_public_ipv6_is_connected_as_a_numeric_address():
    sock = Socket()
    ip = "2606:4700:4700::1111"
    with mock.patch.object(net.socket, "getaddrinfo", return_value=addresses(ip, 80)), \
            mock.patch.object(net.socket, "socket", return_value=sock):
        assert net.read_url("http://public.example/") == (True, "Safe", None)
        assert sock.connected == (ip, 80, 0, 0)


@pytest.mark.parametrize("location", ["http://127.0.0.1/secret", "http://private.example/",
                                       "https://user:SECRET@public.example/", "file:///secret"])
def test_redirects_revalidate_before_connecting(location):
    def dns(host, *args):
        return addresses("127.0.0.1" if host == "private.example" else PUBLIC)

    with mock.patch.object(net.socket, "getaddrinfo", side_effect=dns), \
            mock.patch.object(net, "_PinnedConnection", return_value=Connection(
                Response(status=302, headers={"Location": location}))) as transport:
        assert net.read_url(URL) == (False, "", net.REASON_BLOCKED)
        assert transport.call_count == 1


def test_redirect_loop_is_bounded(public_dns):
    with mock.patch.object(net, "_PinnedConnection", side_effect=lambda *args: Connection(
            Response(status=302, headers={"Location": "/loop"}))) as transport:
        assert net.read_url(URL) == (False, "", net.REASON_REDIRECTS)
        assert transport.call_count == net.URL_FETCH_MAX_REDIRECTS + 1


@pytest.mark.parametrize("headers", [{}, {"Content-Length": "500001"}])
def test_oversized_body_is_rejected_without_partial_content(public_dns, headers):
    with mock.patch.object(net, "_PinnedConnection", return_value=Connection(
            Response(b"x" * 500001, headers=headers))):
        assert net.read_url(URL) == (False, "", net.REASON_TOO_LARGE)


def test_redirects_share_one_deadline(public_dns):
    clock, deadlines = [0.0], []

    def connection(*args):
        deadlines.append(args[-1])
        clock[0] += 4
        return Connection(Response(status=302, headers={"Location": "/next"}))

    with mock.patch.object(net.time, "monotonic", side_effect=lambda: clock[0]), \
            mock.patch.object(net, "_PinnedConnection", side_effect=connection):
        assert net.read_url(URL) == (False, "", net.REASON_TIMEOUT)
        assert deadlines == [10.0, 10.0, 10.0]


def test_body_chunks_share_one_deadline(public_dns):
    clock = [0.0]

    class SlowResponse(Response):
        def read1(self, size):
            clock[0] += 3
            return b"one chunk"

    with mock.patch.object(net.time, "monotonic", side_effect=lambda: clock[0]), \
            mock.patch.object(net, "_PinnedConnection", return_value=Connection(SlowResponse())):
        assert net.read_url(URL) == (False, "", net.REASON_TIMEOUT)


def test_socket_reader_reduces_timeout_for_slow_header_bytes():
    sock, clock = Socket(b"HTTP/1.1"), [0.0]
    reader = net._DeadlineReader(sock, 10.0)
    with mock.patch.object(net.time, "monotonic", side_effect=lambda: clock[0]):
        reader.readinto(bytearray(1))
        clock[0] = 6
        reader.readinto(bytearray(1))
        clock[0] = 11
        with pytest.raises(TimeoutError):
            reader.readinto(bytearray(1))
    assert sock.timeouts == [10.0, 4.0]
    reader.close()


def test_tls_handshake_cannot_reset_the_request_send_deadline(public_dns):
    sock, clock = Socket(), [0.0]
    context = ssl.create_default_context()

    def handshake(*args, **kwargs):
        clock[0] = 8
        return sock

    with mock.patch.object(net.time, "monotonic", side_effect=lambda: clock[0]), \
            mock.patch.object(net.socket, "socket", return_value=sock), \
            mock.patch.object(net.ssl, "create_default_context", return_value=context), \
            mock.patch.object(context, "wrap_socket", side_effect=handshake):
        assert net.read_url(URL) == (True, "Safe", None)
        assert sock.timeouts[:3] == [10.0, 10.0, 2.0]


def test_dns_wait_is_bounded_even_when_resolver_is_still_running():
    release, finished = threading.Event(), threading.Event()

    def stuck_dns(*args):
        try:
            release.wait(2)
            return addresses()
        finally:
            finished.set()

    started = time.monotonic()
    try:
        with mock.patch.object(net.socket, "getaddrinfo", side_effect=stuck_dns), \
                mock.patch.object(net, "URL_FETCH_TIMEOUT_S", 0.03), \
                mock.patch.object(net, "_PinnedConnection") as transport:
            assert net.read_url(URL) == (False, "", net.REASON_TIMEOUT)
            assert time.monotonic() - started < 0.5
            transport.assert_not_called()
    finally:
        release.set()
        assert finished.wait(1)


def test_credentials_are_redacted_in_legacy_url_display():
    assert net.safe_url("https://user:SECRET@shop.example/") == net.REDACTED_URL
    assert net.safe_url(URL) == URL


def test_actual_http_header_reader_cannot_be_kept_alive_by_slow_bytes(public_dns):
    clock = [0.0]

    class SlowSocket(Socket):
        def recv_into(self, buffer):
            clock[0] += 1
            chunk = self.content.read(1)
            buffer[:len(chunk)] = chunk
            return len(chunk)

    sock = SlowSocket()
    with mock.patch.object(net.time, "monotonic", side_effect=lambda: clock[0]), \
            mock.patch.object(net.socket, "socket", return_value=sock):
        assert net.read_url("http://shop.example/") == (False, "", net.REASON_TIMEOUT)
    assert sock.closed is True
    assert sock.timeouts[-1] < sock.timeouts[0]


def test_busy_dns_workers_do_not_accept_an_unbounded_queue(monkeypatch):
    slots = threading.BoundedSemaphore(1)
    slots.acquire()
    monkeypatch.setattr(net, "_dns_slots", slots)
    with mock.patch.object(net.socket, "getaddrinfo") as dns:
        assert net.read_url(URL) == (False, "", net.REASON_TIMEOUT)
        dns.assert_not_called()
    slots.release()


@pytest.fixture
def socketpair_transport(monkeypatch, public_dns):
    pairs, workers = [], []
    release = threading.Event()

    def serve(wire, *, hold_open=False):
        client, server = socket.socketpair()
        pairs.append((client, server))

        def respond():
            try:
                server.settimeout(1)
                request = bytearray()
                while b"\r\n\r\n" not in request:
                    chunk = server.recv(4096)
                    if not chunk:
                        return
                    request.extend(chunk)
                server.sendall(wire)
                if hold_open:
                    release.wait(1)
            except OSError:
                pass  # The client may close immediately after rejecting headers.
            finally:
                server.close()

        worker = threading.Thread(target=respond)
        workers.append(worker)
        worker.start()

        def connect(connection):
            client.settimeout(net._remaining(connection.deadline))
            connection.sock = client

        monkeypatch.setattr(net._PinnedConnection, "connect", connect)
        return client

    yield serve
    release.set()
    for worker in workers:
        worker.join(2)
        assert not worker.is_alive()
    for client, server in pairs:
        try:
            assert client.fileno() == -1
            assert server.fileno() == -1
        finally:
            client.close()
            server.close()


@pytest.mark.parametrize("framing", ["close", "http10", "eof", "chunked"])
def test_real_socket_body_outlives_http_connection_close(socketpair_transport, framing):
    body = b"<p>" + b"Public page " * 2000 + b"</p>"
    if framing == "close":
        wire = (b"HTTP/1.1 200 OK\r\nConnection: close\r\nContent-Length: "
                + str(len(body)).encode() + b"\r\n\r\n" + body)
    elif framing == "http10":
        wire = b"HTTP/1.0 200 OK\r\n\r\n" + body
    elif framing == "eof":
        wire = b"HTTP/1.1 200 OK\r\n\r\n" + body
    else:
        wire = (b"HTTP/1.1 200 OK\r\nTransfer-Encoding: chunked\r\nConnection: close\r\n\r\n"
                + f"{len(body):x}\r\n".encode() + body + b"\r\n0\r\n\r\n")
    client = socketpair_transport(wire)
    assert net._read_public("http://shop.example/") == body
    assert client.fileno() == -1


@pytest.mark.parametrize("wire", [
    b"invalid HTTP status\r\n\r\n",
    b"HTTP/1.1 200 OK\r\nTransfer-Encoding: chunked\r\n\r\ninvalid chunk\r\n",
    b"HTTP/1.1 200 OK\r\nContent-Length: 500001\r\n\r\n",
])
def test_real_socket_exception_closes_every_io_reference(socketpair_transport, wire):
    client = socketpair_transport(wire)
    assert net.read_url("http://shop.example/")[0] is False
    assert client.fileno() == -1


@pytest.mark.parametrize("wire", [
    b"HTTP/1.1 200 OK\r\nContent-Len",
    b"HTTP/1.1 200 OK\r\nConnection: close\r\nContent-Length: 20000\r\n\r\npartial body",
])
def test_real_socket_timeout_closes_every_io_reference(socketpair_transport, monkeypatch, wire):
    monkeypatch.setattr(net, "URL_FETCH_TIMEOUT_S", 0.05)
    client = socketpair_transport(wire, hold_open=True)
    assert net.read_url("http://shop.example/") == (False, "", net.REASON_TIMEOUT)
    assert client.fileno() == -1


@pytest.mark.parametrize("wire", [
    b"HTTP/1.1 200 OK\r\nContent-Length: 1000\r\n\r\n<p>Partial secret page</p>",
    b"HTTP/1.1 200 OK\r\nTransfer-Encoding: chunked\r\n\r\n100\r\n<p>Partial secret page</p>",
    b"HTTP/1.1 200 OK\r\nTransfer-Encoding: chunked\r\n\r\n4\r\nSafe\r\n",
])
def test_real_socket_truncated_body_never_returns_partial_content(socketpair_transport, wire):
    client = socketpair_transport(wire)
    assert net.read_url("http://shop.example/") == (False, "", net.REASON_UNREACHABLE)
    assert client.fileno() == -1


class ConnectSocket(Socket):
    def __init__(self, error=None, clock=None, elapsed=0):
        super().__init__()
        self.error, self.clock, self.elapsed = error, clock, elapsed

    def connect(self, address):
        super().connect(address)
        if self.clock is not None:
            self.clock[0] += self.elapsed
        if self.error is not None:
            raise self.error


def test_pinned_tcp_falls_back_from_public_ipv6_to_same_snapshot_ipv4():
    first = ConnectSocket(OSError("IPv6 unreachable"))
    second = ConnectSocket()
    snapshot = addresses("2606:4700:4700::1111", 80) + addresses(PUBLIC, 80)
    with mock.patch.object(net.socket, "getaddrinfo", return_value=snapshot) as dns, \
            mock.patch.object(net.socket, "socket", side_effect=[first, second]) as sockets:
        assert net.read_url("http://shop.example/") == (True, "Safe", None)
    dns.assert_called_once()
    assert [call.args[0] for call in sockets.call_args_list] == [socket.AF_INET6, socket.AF_INET]
    assert first.connected == ("2606:4700:4700::1111", 80, 0, 0)
    assert second.connected == (PUBLIC, 80)
    assert first.closed and second.closed
    assert first.timeouts[0] < second.timeouts[0]


def test_every_pinned_tcp_failure_closes_the_attempt_and_returns_safe_reason():
    sockets = [ConnectSocket(OSError("SECRET")), ConnectSocket(ConnectionRefusedError("SECRET"))]
    with mock.patch.object(net.socket, "getaddrinfo", return_value=addresses() * 2) as dns, \
            mock.patch.object(net.socket, "socket", side_effect=sockets) as factory:
        assert net.read_url(URL) == (False, "", net.REASON_UNREACHABLE)
    dns.assert_called_once()
    assert factory.call_count == 2
    assert all(sock.closed for sock in sockets)


def test_pinned_tcp_attempts_share_one_deadline_and_divide_remaining_time():
    clock = [0.0]
    first = ConnectSocket(TimeoutError(), clock, 5)
    second = ConnectSocket(TimeoutError(), clock, 5)
    with mock.patch.object(net.time, "monotonic", side_effect=lambda: clock[0]), \
            mock.patch.object(net.socket, "getaddrinfo", return_value=addresses() * 2) as dns, \
            mock.patch.object(net.socket, "socket", side_effect=[first, second]) as factory:
        assert net.read_url(URL) == (False, "", net.REASON_TIMEOUT)
    dns.assert_called_once()
    assert factory.call_count == 2
    assert first.timeouts == [5.0]
    assert second.timeouts == [5.0]
    assert first.closed and second.closed


def test_tcp_fallback_preserves_tls_hostname_and_verification():
    first, second = ConnectSocket(OSError("IPv6 unreachable")), ConnectSocket()
    context = ssl.create_default_context()
    with mock.patch.object(net.socket, "getaddrinfo", return_value=(
            addresses("2606:4700:4700::1111") + addresses())), \
            mock.patch.object(net.socket, "socket", side_effect=[first, second]), \
            mock.patch.object(net.ssl, "create_default_context", return_value=context), \
            mock.patch.object(context, "wrap_socket", return_value=second) as tls:
        assert net.read_url(URL) == (True, "Safe", None)
    tls.assert_called_once_with(second, server_hostname="shop.example")
    assert context.check_hostname and context.verify_mode == ssl.CERT_REQUIRED


def test_certificate_failure_is_not_retried_on_another_address():
    sock = ConnectSocket()
    context = ssl.create_default_context()
    with mock.patch.object(net.socket, "getaddrinfo", return_value=addresses() * 2), \
            mock.patch.object(net.socket, "socket", return_value=sock) as factory, \
            mock.patch.object(net.ssl, "create_default_context", return_value=context), \
            mock.patch.object(context, "wrap_socket", side_effect=ssl.SSLCertVerificationError()):
        assert net.read_url(URL) == (False, "", net.REASON_SSL)
    factory.assert_called_once()
    assert sock.closed
